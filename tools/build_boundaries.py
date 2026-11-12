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

from ovcommon import (
    COLLECTIONS,
    GLOBAL_BOUNDS,
    PUBLISH,
    ROW_GROUP_ROWS,
    WORK,
    boundary_path,
    connect,
    copy_ordered,
    footer_metadata,
    geo_metadata,
    human,
    register_iso3166,
    staged_area,
    staged_division,
    stream_write,
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
-- division_id breaks a tie in the Hilbert key, so the row order is
-- reproducible across rebuilds. Without it two polygons in the same cell
-- could swap places between runs, and the display companion's row
-- alignment and the search index's geometry_ref would both go stale
-- without anything failing.
ORDER BY ST_Hilbert(m.geometry, {bounds}), m.division_id
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
    ordered = WORK / f"{collection}.ordered.parquet"
    copy_ordered(con, sql, ordered)

    # The join must not drop or duplicate an area row. A missing division row
    # would silently lose a polygon; a duplicate would give one GERS id two
    # geometries, which the index contract cannot express.
    staged_rows, = con.execute(
        f"SELECT count(*) FROM read_parquet('{area.as_posix()}')"
    ).fetchone()
    rows, unnamed, *bbox = con.execute(
        f"""SELECT count(*), count(*) - count(name),
                   min(bbox.xmin), min(bbox.ymin),
                   max(bbox.xmax), max(bbox.ymax)
            FROM read_parquet('{ordered.as_posix()}')"""
    ).fetchone()
    # Columns Overture populates at some levels and not at others. An
    # all-null column is noise in table:columns and a question a consumer has
    # to answer, so it is dropped per collection and the drop is reported.
    # Measured on this release: cartography.prominence exists only on
    # localities, class only on localities, admin_level only down to county.
    candidates = [
        "class", "prominence", "admin_level", "region", "wikidata",
        "population", "local_type", "parent_division_id", "parent_name",
        "parent_subtype", "country_iso2",
    ]
    counts = con.execute(
        "SELECT "
        + ", ".join(f'count("{c}")' for c in candidates)
        + f" FROM read_parquet('{ordered.as_posix()}')"
    ).fetchone()
    empty = [c for c, n in zip(candidates, counts) if n == 0]
    con.close()
    if empty:
        print(f"  dropping all-null column(s): {', '.join(empty)}")
    if rows != staged_rows:
        sys.exit(
            f"{collection}: joined {rows:,} rows from {staged_rows:,} staged "
            "land polygons. The join to type=division is not 1:1; do not "
            "publish."
        )
    print(f"  joined {rows:,} rows, {unnamed:,} with no primary name")

    write_optimized(collection, ordered, bbox, empty)
    ordered.unlink(missing_ok=True)


def write_optimized(
    collection: str, ordered, bbox: list[float], empty: list[str]
) -> None:
    meta = footer_metadata({"cnmw:collection": collection})
    meta[b"geo"] = geo_metadata(
        bbox=bbox, geometry_types=["Polygon", "MultiPolygon"]
    )
    out = boundary_path(collection)
    md = stream_write(
        ordered,
        out,
        row_group_rows=ROW_GROUP_ROWS[collection],
        footer_meta=meta,
        transform=(lambda tb: tb.drop_columns(empty)) if empty else None,
    )
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
