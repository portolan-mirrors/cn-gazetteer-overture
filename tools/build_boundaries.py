#!/usr/bin/env python3
"""Build one optimized boundary GeoParquet per collection.

    python3 tools/build_boundaries.py              # all five
    python3 tools/build_boundaries.py county       # one or more

Run ``tools/stage_source.py`` first. Everything here reads the local staging
tree, so retuning a row group size costs no egress.

Three stages per collection.

1. DuckDB joins the staged ``division_area`` land polygons to the staged
   ``division`` rows on ``division_id``, which is where the names, the
   settlement class, the population and the parent come from. ``division_area``
   repeats a few of those properties, but not all of them, and the division row
   is the one the search index is built from, so taking both from the same
   place is what keeps the two halves consistent.

2. The same query derives the measured columns and orders the rows along a
   Hilbert curve over the whole globe, so the five collections and the search
   index sit on one comparable curve.

3. PyArrow writes the file. The write is not delegated: the row group size is
   the point of this catalog, and PyArrow is the only writer here that honours
   an exact small row group count and can also write the Parquet page index.

Why Hilbert order and not ``(country, id)``
-------------------------------------------
The index-file contract suggests ordering a boundary mirror by country and id
so a consumer can binary-search for one feature. This catalog orders by
geometry instead, because the search index carries an explicit
``geometry_ref`` of file, row group and row for every division that has a
polygon, so the fast path never searches. Hilbert order is what makes a
bounding-box query read few row groups, and a map is the other consumer. The
fallback path, for a consumer that distrusts ``geometry_ref``, reads the
``division_id`` column chunks: dictionary-encoded, and a few per cent of the
file.
"""
from __future__ import annotations

import json
import sys

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from ovcommon import (
    COLLECTIONS,
    GLOBAL_BOUNDS,
    PUBLISH,
    ROW_GROUP_ROWS,
    ZSTD_LEVEL,
    boundary_path,
    connect,
    footer_metadata,
    geo_metadata,
    human,
    register_iso3166,
    staged_area,
    staged_division,
)

SQL = """
WITH area AS (
  SELECT id, division_id, country, region, version, geometry
  FROM read_parquet('{area}')
),
div AS (
  SELECT id, subtype, class, admin_level, names, wikidata, population,
         local_type, parent_division_id, cartography
  FROM read_parquet('{division}')
),
parents AS (
  SELECT id, names.primary AS parent_name, subtype AS parent_subtype
  FROM read_parquet('{division}')
),
joined AS (
  SELECT
    a.id,
    a.division_id,
    d.names.primary AS name,
    d.subtype,
    d.class,
    d.admin_level,
    -- local_type is Overture's localized name for the subtype, a map of
    -- language code to name. The index takes the 'local' entry where there is
    -- one and the first entry otherwise, so a reader gets 'province' for
    -- Quebec rather than a map to unpack.
    coalesce(d.local_type['local'],
             CASE WHEN cardinality(d.local_type) > 0
                  THEN map_values(d.local_type)[1] END) AS local_type,
    a.country,
    a.region,
    d.parent_division_id,
    p.parent_name,
    p.parent_subtype,
    d.population,
    d.wikidata,
    d.cartography.prominence AS prominence,
    cardinality(d.names.common)::INTEGER AS name_langs,
    a.version,
    a.geometry
  FROM area a
  JOIN div d ON a.division_id = d.id
  LEFT JOIN parents p ON d.parent_division_id = p.id
),
counted AS (
  -- How many divisions of this collection share this row's country. It is
  -- how finely Overture divides that country at this level, and at the
  -- localadmin level it is also what exposes the coverage gap: 19 countries
  -- have localadmin divisions and the rest have none at all.
  SELECT *, count(*) OVER (PARTITION BY country)::INTEGER AS country_units
  FROM joined
),
measured AS (
  SELECT
    * EXCLUDE (geometry),
    ST_Area_Spheroid(ST_FlipCoordinates(geometry)) / 1e6 AS area_km2,
    ST_Perimeter_Spheroid(ST_FlipCoordinates(geometry)) / 1e3 AS perimeter_km,
    ST_NPoints(geometry)::INTEGER AS vertices,
    geometry
  FROM counted
)
SELECT
  m.id,
  m.division_id,
  m.name,
  m.subtype,
  coalesce(i.alpha_3, m.country) AS country,
  m.country AS country_iso2,
  m.region,
  m.class,
  m.local_type,
  m.admin_level,
  m.parent_division_id,
  m.parent_name,
  m.parent_subtype,
  m.country_units,
  m.population,
  m.wikidata,
  m.prominence,
  m.name_langs,
  round(m.area_km2, 6) AS area_km2,
  round(m.perimeter_km, 6) AS perimeter_km,
  CASE WHEN m.perimeter_km > 0
       THEN round(4 * pi() * m.area_km2 / (m.perimeter_km * m.perimeter_km), 6)
       ELSE NULL END AS compactness,
  m.vertices,
  m.version,
  {{
    xmin: ST_XMin(m.geometry), ymin: ST_YMin(m.geometry),
    xmax: ST_XMax(m.geometry), ymax: ST_YMax(m.geometry)
  }} AS bbox,
  ST_AsWKB(m.geometry) AS geometry
FROM measured m
LEFT JOIN iso3166 i ON m.country = i.alpha_2
ORDER BY ST_Hilbert(m.geometry, {bounds})
"""


def build(collection: str) -> None:
    print(f"{collection}: building")
    area = staged_area(collection)
    division = staged_division()
    for path in (area, division):
        if not path.exists():
            sys.exit(f"missing {path}; run tools/stage_source.py first")

    con = connect()
    register_iso3166(con)
    sql = SQL.format(
        area=area.as_posix(),
        division=division.as_posix(),
        bounds=GLOBAL_BOUNDS,
    )
    table = con.execute(sql).to_arrow_table()

    # The join must not drop or duplicate an area row. A missing division row
    # would silently lose a polygon; a duplicate would give one GERS id two
    # geometries, which the index contract cannot express.
    staged_rows = con.execute(
        f"SELECT count(*) FROM read_parquet('{area.as_posix()}')"
    ).fetchone()[0]
    con.close()
    if table.num_rows != staged_rows:
        sys.exit(
            f"{collection}: joined {table.num_rows:,} rows from "
            f"{staged_rows:,} staged land polygons. The join to type=division "
            "is not 1:1; do not publish."
        )
    invalid = pc.sum(pc.is_null(table.column("name"))).as_py() or 0
    print(f"  joined {table.num_rows:,} rows, {invalid:,} with no primary name")

    write_optimized(collection, table)


def write_optimized(collection: str, table: pa.Table) -> None:
    bbox_col = table.column("bbox").combine_chunks()
    bbox = [
        pc.min(bbox_col.field("xmin")).as_py(),
        pc.min(bbox_col.field("ymin")).as_py(),
        pc.max(bbox_col.field("xmax")).as_py(),
        pc.max(bbox_col.field("ymax")).as_py(),
    ]
    meta = footer_metadata({"cnmw:collection": collection})
    meta[b"geo"] = geo_metadata(
        bbox=bbox, geometry_types=["Polygon", "MultiPolygon"]
    )
    table = table.replace_schema_metadata(meta)

    out = boundary_path(collection)
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        table,
        out,
        compression="zstd",
        compression_level=ZSTD_LEVEL,
        row_group_size=ROW_GROUP_ROWS[collection],
        write_statistics=True,
        write_page_index=True,
        version="2.6",
        sorting_columns=None,
    )
    md = pq.ParquetFile(out).metadata
    size = out.stat().st_size
    per_group = size / md.num_row_groups
    print(
        f"  {out.name}: {human(size)}, {md.num_rows:,} rows, "
        f"{md.num_row_groups:,} row groups of {ROW_GROUP_ROWS[collection]:,}, "
        f"{per_group / 1e6:.2f} MB per group, "
        f"{size / md.num_rows:.0f} bytes per row"
    )
    if not (0.7e6 <= per_group <= 2.4e6):
        print(
            f"  WARNING: {per_group / 1e6:.2f} MB per group is outside the "
            f"1-2 MB target. Retune ROW_GROUP_ROWS['{collection}'] to about "
            f"{int(ROW_GROUP_ROWS[collection] * 1.5e6 / per_group)}."
        )
    print(f"  bbox: {json.dumps([round(v, 6) for v in bbox])}")


def main(argv: list[str]) -> int:
    wanted = argv or list(COLLECTIONS)
    unknown = set(wanted) - set(COLLECTIONS)
    if unknown:
        sys.exit(f"unknown collection(s): {', '.join(sorted(unknown))}")
    PUBLISH.mkdir(parents=True, exist_ok=True)
    for collection in wanted:
        build(collection)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
