#!/usr/bin/env python3
"""Build the multilingual name search index, and its manifest.

    python3 tools/build_names.py --dry-run    # row counts per policy
    python3 tools/build_names.py

Run ``tools/stage_source.py``, ``tools/build_boundaries.py`` and
``tools/build_display.py`` first: the index reads the staged ``type=division``
rows for names and the built boundary files for the row positions behind
``geometry_ref``, so the index and the geometry it points at cannot disagree.

What a row is
-------------
One **primary** row per division, from ``names.primary``, plus one **alt** row
per distinct alternative spelling of that division's name, from the
``names.common`` map. An alt row repeats its division's ``feature_id`` and sets
``alt_of`` to the same value, which is what marks it as an alternative; a
consumer that shows results dedupes by ``feature_id``.

Every division in scope gets a primary row whether or not it has a polygon.
2,952,062 of Overture's 3,508,156 localities have no ``division_area`` row, so
their entry carries the division's own point and a bounding box collapsed onto
that point. ``has_boundary`` is false on those rows and ``geometry_ref`` is
null, so a client knows before it fetches that there is no outline to draw.

Which alternative names are indexed
-----------------------------------
Two reductions, both lossless for search and both measured in
``--dry-run``:

1. An alternative whose normalized form equals the division's primary
   normalized form is dropped. It is the same search key; a second row for it
   would only cost bytes and return a duplicate.
2. Alternatives that normalize to the same string as each other are collapsed
   into one row. ``name_lang`` then carries the first language code in
   alphabetical order and ``name_lang_count`` says how many languages agree on
   that spelling. Overture publishes "France" under dozens of language codes;
   indexing it dozens of times finds the same division dozens of times.

A third reduction would be a policy choice rather than a lossless one, and
``ALT_LEVEL_CEILING`` is where it lives. It is set to 4, which indexes every
language at every level. See the collection README for the measurement, and
for why the file is allowed to be this large.

Two columns are null on alt rows on purpose: ``geometry`` and
``geometry_ref``. An alt row describes the same division as its primary row
and carries the same ``feature_id``, so a consumer that has matched an alt row
already has to dedupe by ``feature_id`` before it shows a result. Repeating a
21-byte WKB point and a row reference on every one of two million alt rows
bought nothing and cost 60 MB.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import unicodedata

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from ovcommon import (
    CATALOG_VERSION,
    COLLECTIONS,
    COLLECTION_LEVEL,
    NAMES_PATH,
    NAMES_ROW_GROUP_ROWS,
    NAMES_ROW_GROUP_TARGET_KIB,
    RELEASE,
    SUBTYPE_LEVEL,
    WORK,
    ZSTD_LEVEL,
    boundary_path,
    connect,
    display_path,
    footer_metadata,
    geo_metadata,
    geom_expr,
    human,
    normalize_name,
    pycountry_version,
    register_iso3166,
    ROW_GROUP_ROWS,
    shrink_bbox_float32,
    staged_division,
)

SOURCE_NAME = "overture-divisions"

# The deepest level that gets alternative-name rows. 4 means every level does.
# Lowering it to 3 drops locality alternatives, which is where the row count
# lives. The published value is set from the --dry-run measurement against the
# size budget; the number that justified it is in catalog/names/README.md.
ALT_LEVEL_CEILING = 4

# Rows per Arrow batch while streaming the sorted intermediate into the final
# file. A multiple of the row group size, so every group is exactly full.
BATCH_ROWS = NAMES_ROW_GROUP_ROWS * 128

LEVEL_CASE = " ".join(
    f"WHEN '{subtype}' THEN {level}" for subtype, level in SUBTYPE_LEVEL.items()
)

# ---------------------------------------------------------------------------
# Stage 1: primary and alt rows, unsorted, with the measured columns attached
# ---------------------------------------------------------------------------
ROWS_SQL = """
CREATE OR REPLACE TABLE refs AS SELECT * FROM read_parquet('{refs}');
CREATE OR REPLACE TABLE base AS
SELECT
  d.id                                        AS feature_id,
  d.names.primary                             AS name,
  d.names.common                              AS common,
  CASE d.subtype {level_case} END::TINYINT    AS level,
  d.subtype,
  coalesce(i.alpha_3, d.country)              AS country,
  d.population,
  d.cartography.prominence                    AS prominence,
  p.names.primary                             AS parent_name,
  r.row_index,
  r.collection,
  r.area_km2,
  r.bbox                                      AS boundary_bbox,
  r.point                                     AS boundary_point,
  ST_AsWKB({dgeom})                            AS division_point,
  {{xmin: ST_XMin({dgeom}), ymin: ST_YMin({dgeom}),
    xmax: ST_XMax({dgeom}), ymax: ST_YMax({dgeom})}} AS division_bbox
FROM read_parquet('{division}') d
LEFT JOIN read_parquet('{division}') p ON d.parent_division_id = p.id
LEFT JOIN iso3166 i ON d.country = i.alpha_2
LEFT JOIN refs r ON d.id = r.division_id
WHERE d.names.primary IS NOT NULL;
"""

UNION_SQL = """
CREATE OR REPLACE TABLE rows_raw AS
WITH prim AS (
  SELECT feature_id, name, NULL::VARCHAR AS name_lang,
         1::INTEGER AS name_lang_count, NULL::VARCHAR AS alt_of,
         level, subtype, country, population, prominence, parent_name,
         row_index, collection, area_km2, boundary_bbox, boundary_point,
         division_point, division_bbox
  FROM base
),
alts AS (
  SELECT b.feature_id, kv.value AS name, kv.key AS name_lang,
         1::INTEGER AS name_lang_count, b.feature_id AS alt_of,
         b.level, b.subtype, b.country, b.population, b.prominence,
         b.parent_name, b.row_index, b.collection, b.area_km2,
         b.boundary_bbox, b.boundary_point, b.division_point, b.division_bbox
  FROM base b, unnest(map_entries(b.common)) AS t(kv)
  WHERE b.level <= {ceiling} AND kv.value IS NOT NULL
)
SELECT * FROM prim UNION ALL SELECT * FROM alts;
"""


def row_reference_table(con) -> None:
    """Row position of every division that has a polygon, per collection.

    This is what ``geometry_ref`` is built from. The boundary file and its
    display companion hold the same rows in the same order in the same groups,
    so one reference is valid against both.
    """
    frames = []
    for collection in COLLECTIONS:
        path = boundary_path(collection)
        if not path.exists():
            sys.exit(f"missing {path}; run tools/build_boundaries.py first")
        con.execute(
            f"""
            CREATE OR REPLACE TEMP TABLE ref_{collection} AS
            SELECT division_id,
                   (row_number() OVER () - 1)::BIGINT AS row_index,
                   '{collection}' AS collection,
                   area_km2,
                   bbox,
                   ST_AsWKB(ST_PointOnSurface({{geom}})) AS point
            FROM read_parquet('{path.as_posix()}')
            """.replace("{geom}", geom_expr(con, path))
        )
        frames.append(f"SELECT * FROM ref_{collection}")
    out = WORK / "names_refs.parquet"
    con.execute(
        f"COPY ({' UNION ALL '.join(frames)}) TO '{out.as_posix()}' "
        "(FORMAT parquet, COMPRESSION zstd)"
    )


def measure(con) -> dict:
    """Row counts per level and per reduction, for the --dry-run report."""
    report = {}
    report["divisions"] = con.execute("SELECT count(*) FROM base").fetchone()[0]
    report["with_boundary"] = con.execute(
        "SELECT count(*) FROM base WHERE row_index IS NOT NULL"
    ).fetchone()[0]
    report["per_level"] = con.execute(
        """SELECT level, subtype, count(*) AS divisions,
                  count(*) FILTER (WHERE row_index IS NOT NULL) AS with_boundary,
                  sum(cardinality(common)) AS alt_entries
           FROM base GROUP BY 1, 2 ORDER BY 1, 2"""
    ).fetchdf().to_string()
    report["alt_entries_total"] = con.execute(
        "SELECT sum(cardinality(common)) FROM base"
    ).fetchone()[0]
    return report


def build_rows(con, *, ceiling: int) -> None:
    con.execute(UNION_SQL.format(ceiling=ceiling))


NORMALIZE_SQL = """
CREATE OR REPLACE TABLE rows_norm AS
SELECT * EXCLUDE (name_norm), name_norm FROM (
  SELECT r.*, n.name_norm
  FROM rows_raw r JOIN norms n ON r.name = n.name
) WHERE name_norm IS NOT NULL;
"""

# The two lossless reductions, plus the global duplicate count. Collapsing
# alternatives that share a normalized form keeps the alphabetically first
# language code, which is arbitrary but stable across rebuilds.
REDUCE_SQL = """
CREATE OR REPLACE TABLE rows_reduced AS
WITH primary_norm AS (
  SELECT feature_id, name_norm FROM rows_norm WHERE alt_of IS NULL
),
alt_kept AS (
  SELECT a.feature_id, a.name_norm,
         min(a.name)      AS name,
         min(a.name_lang) AS name_lang,
         count(*)::INTEGER AS name_lang_count
  FROM rows_norm a
  JOIN primary_norm p USING (feature_id)
  WHERE a.alt_of IS NOT NULL AND a.name_norm <> p.name_norm
  GROUP BY 1, 2
),
combined AS (
  SELECT feature_id, name, name_norm, name_lang, name_lang_count,
         NULL::VARCHAR AS alt_of
  FROM rows_norm WHERE alt_of IS NULL
  UNION ALL
  SELECT feature_id, name, name_norm, name_lang, name_lang_count,
         feature_id AS alt_of
  FROM alt_kept
),
attributed AS (
  SELECT c.*, b.level, b.subtype, b.country, b.population, b.prominence,
         b.parent_name, b.row_index, b.collection, b.area_km2,
         b.boundary_bbox, b.boundary_point, b.division_point, b.division_bbox
  FROM combined c JOIN base b USING (feature_id)
)
SELECT *, count(*) OVER (PARTITION BY name_norm)::INTEGER AS name_dupes
FROM attributed;
"""

FINAL_SQL = """
SELECT
  name,
  name_norm,
  level,
  subtype,
  country,
  feature_id,
  '{source}'::VARCHAR AS source,
  name_lang,
  name_lang_count::SMALLINT AS name_lang_count,
  alt_of,
  parent_name,
  area_km2::FLOAT AS area_km2,
  population,
  prominence,
  name_dupes,
  row_index IS NOT NULL AS has_boundary,
  coalesce(boundary_bbox, division_bbox) AS bbox,
  CASE WHEN row_index IS NOT NULL AND alt_of IS NULL THEN {{
    file: 'overture_' || collection || '.parquet',
    row_group: (row_index // rg_rows)::INTEGER,
    row: row_index::INTEGER
  }} END AS geometry_ref,
  CASE WHEN alt_of IS NULL
       THEN coalesce(boundary_point, division_point) END AS geometry
FROM rows_reduced
LEFT JOIN row_group_rows g USING (collection)
ORDER BY name_norm, level, country, feature_id
"""


def write_index(con, *, started: float) -> dict:
    """Stream the sorted rows into the final file with exact row groups."""
    con.execute(
        "CREATE OR REPLACE TEMP TABLE row_group_rows "
        "(collection VARCHAR, rg_rows INTEGER)"
    )
    con.executemany(
        "INSERT INTO row_group_rows VALUES (?, ?)", list(ROW_GROUP_ROWS.items())
    )
    sorted_path = WORK / "names_sorted.parquet"
    sorted_path.unlink(missing_ok=True)
    con.execute(
        f"COPY ({FINAL_SQL.format(source=SOURCE_NAME)}) "
        f"TO '{sorted_path.as_posix()}' (FORMAT parquet, COMPRESSION zstd)"
    )

    # The extent is measured before the write rather than accumulated during
    # it, so the GeoParquet metadata is right the first time and the file is
    # written once. Widened to the float32 grid, because the bbox struct is
    # narrowed outward below and the covering has to contain what it claims.
    raw = con.execute(
        f"""SELECT min(bbox.xmin), min(bbox.ymin), max(bbox.xmax), max(bbox.ymax)
            FROM read_parquet('{sorted_path.as_posix()}')"""
    ).fetchone()
    import numpy as np

    bounds = [
        float(np.nextafter(np.float32(raw[0]), np.float32(-np.inf))),
        float(np.nextafter(np.float32(raw[1]), np.float32(-np.inf))),
        float(np.nextafter(np.float32(raw[2]), np.float32(np.inf))),
        float(np.nextafter(np.float32(raw[3]), np.float32(np.inf))),
    ]

    reader = pq.ParquetFile(sorted_path)
    NAMES_PATH.parent.mkdir(parents=True, exist_ok=True)
    NAMES_PATH.unlink(missing_ok=True)

    writer = None
    try:
        for batch in reader.iter_batches(batch_size=BATCH_ROWS):
            table = pa.Table.from_batches([batch])
            narrowed = shrink_bbox_float32(table.column("bbox"))
            table = table.set_column(
                table.schema.get_field_index("bbox"), "bbox", narrowed
            )
            if writer is None:
                meta = footer_metadata({"cnmw:index_source": SOURCE_NAME})
                meta[b"geo"] = geo_metadata(
                    bbox=[round(v, 6) for v in bounds], geometry_types=["Point"]
                )
                schema = table.schema.with_metadata(meta)
                writer = pq.ParquetWriter(
                    NAMES_PATH,
                    schema,
                    compression="zstd",
                    compression_level=ZSTD_LEVEL,
                    write_statistics=True,
                    write_page_index=True,
                    version="2.6",
                    sorting_columns=[
                        pq.SortingColumn(
                            table.schema.get_field_index("name_norm"),
                            descending=False,
                            nulls_first=True,
                        )
                    ],
                )
            table = table.cast(writer.schema)
            writer.write_table(table, row_group_size=NAMES_ROW_GROUP_ROWS)
    finally:
        if writer is not None:
            writer.close()

    md = pq.ParquetFile(NAMES_PATH).metadata
    size = NAMES_PATH.stat().st_size
    per_group_kib = size / md.num_row_groups / 1024
    print(
        f"names: {NAMES_PATH.name} {human(size)}, {md.num_rows:,} rows, "
        f"{md.num_row_groups:,} row groups of {NAMES_ROW_GROUP_ROWS:,}, "
        f"{per_group_kib:.0f} KiB per group, "
        f"{size / md.num_rows:.1f} bytes per row"
    )
    lo, hi = NAMES_ROW_GROUP_TARGET_KIB
    if not (lo * 0.75 <= per_group_kib <= hi * 1.25):
        print(
            f"  WARNING: {per_group_kib:.0f} KiB per group is outside the "
            f"{lo}-{hi} KiB target. Retune NAMES_ROW_GROUP_ROWS to about "
            f"{int(NAMES_ROW_GROUP_ROWS * 125 / per_group_kib)}."
        )
    print(f"  elapsed {time.time() - started:.0f}s")
    sorted_path.unlink(missing_ok=True)
    return {
        "rows": md.num_rows,
        "row_groups": md.num_row_groups,
        "size": size,
        "bbox": bounds,
    }


def verify(stats: dict) -> dict:
    """Assert the layout guarantees the geocoder re-checks on load.

    Everything here is a requirement the index-file contract places on the
    builder. A consumer re-checks the cheap ones from the footer; this is the
    expensive, exhaustive version, run once at build time.
    """
    pf = pq.ParquetFile(NAMES_PATH)
    md = pf.metadata
    schema = pf.schema_arrow
    required = {
        "name": pa.string(),
        "name_norm": pa.string(),
        "level": pa.int8(),
        "country": pa.string(),
        "feature_id": pa.string(),
        "source": pa.string(),
    }
    problems = []
    for col, typ in required.items():
        if col not in schema.names:
            problems.append(f"missing required column {col}")
        elif schema.field(col).type != typ:
            problems.append(
                f"{col} is {schema.field(col).type}, the contract wants {typ}"
            )
    bbox = schema.field("bbox").type
    if not (pa.types.is_struct(bbox) and bbox.num_fields == 4):
        problems.append("bbox is not a four-field struct")

    # The declared sort. A consumer refuses the range strategy without it.
    if not md.row_group(0).sorting_columns:
        problems.append("the footer declares no sorting_columns")

    # The sort itself, byte-wise, across the whole file and across every group
    # boundary. Compared on UTF-8 bytes rather than Python's str ordering,
    # because that is what a client's binary search does.
    norm = pq.read_table(NAMES_PATH, columns=["name_norm"]).column("name_norm")
    values = [v.encode("utf-8") if v is not None else None for v in norm.to_pylist()]
    if any(v is None for v in values):
        problems.append("name_norm holds a null")
    else:
        out_of_order = sum(
            1 for i in range(len(values) - 1) if values[i] > values[i + 1]
        )
        if out_of_order:
            problems.append(f"name_norm is not ascending at {out_of_order} positions")

    # Statistics on name_norm for every row group, and not truncated: a
    # truncated max is the classic silent off-by-one in a prefix search.
    truncated = 0
    missing = 0
    for g in range(md.num_row_groups):
        rg = md.row_group(g)
        idx = next(
            i
            for i in range(rg.num_columns)
            if rg.column(i).path_in_schema == "name_norm"
        )
        st = rg.column(idx).statistics
        if st is None or st.min is None or st.max is None:
            missing += 1
            continue
        lo = g * NAMES_ROW_GROUP_ROWS
        hi = min(lo + NAMES_ROW_GROUP_ROWS, len(values)) - 1
        if st.min.encode("utf-8") != values[lo] or st.max.encode("utf-8") != values[hi]:
            truncated += 1
    if missing:
        problems.append(f"{missing} row groups have no name_norm statistics")
    if problems:
        raise SystemExit("index verification failed:\n  " + "\n  ".join(problems))
    print(
        f"  verified: every required column present and typed as the contract "
        f"wants; name_norm ascending byte-wise with no nulls; untruncated "
        f"statistics on {md.num_row_groups - truncated:,} of "
        f"{md.num_row_groups:,} row groups"
    )
    return {"stats_truncated": bool(truncated)}


def write_manifest(stats: dict, extra: dict, counts: dict) -> None:
    """The small JSON a geocoder fetches before the index itself.

    It is published as catalog metadata rather than as a data file, because it
    is a kilobyte of pointers and it has to stay in step with the STAC the
    publisher uploads.
    """
    import hashlib
    from pathlib import Path

    repo_catalog = Path(__file__).resolve().parents[1] / "catalog" / "names"
    boundaries = []
    for collection in COLLECTIONS:
        full = boundary_path(collection)
        disp = display_path(collection)
        if not (full.exists() and disp.exists()):
            sys.exit(f"missing {full} or {disp}; run the boundary builds first")
        fmd = pq.ParquetFile(full).metadata
        dmd = pq.ParquetFile(disp).metadata
        boundaries.append(
            {
                "level": COLLECTION_LEVEL[collection],
                "collection": collection,
                "feature_id_column": "division_id",
                "geometry_column": "geometry",
                "row_group_rows": ROW_GROUP_ROWS[collection],
                "full": {
                    "url": f"../{collection}/{full.name}",
                    "size": full.stat().st_size,
                    "row_count": fmd.num_rows,
                    "row_groups": fmd.num_row_groups,
                },
                "display": {
                    "url": f"../{collection}/{disp.name}",
                    "size": disp.stat().st_size,
                    "row_count": dmd.num_rows,
                    "row_groups": dmd.num_row_groups,
                },
            }
        )

    doc = {
        "spec": "cnmw-index/1.0",
        "source": SOURCE_NAME,
        "experimental": True,
        "index_version": f"{time.strftime('%Y-%m-%d')}T00:00:00Z",
        "catalog_version": CATALOG_VERSION,
        "overture_release": RELEASE,
        "rows": stats["rows"],
        "primary_rows": counts["primary_rows"],
        "alt_rows": counts["alt_rows"],
        "levels": sorted(set(COLLECTION_LEVEL.values())),
        "level_names": {
            str(level): [s for s, lv in SUBTYPE_LEVEL.items() if lv == level]
            for level in sorted(set(SUBTYPE_LEVEL.values()))
        },
        "stats_truncated": extra["stats_truncated"],
        "dropped_unnamed": counts["dropped_unnamed"],
        "index": {
            "url": f"./{NAMES_PATH.name}",
            "size": stats["size"],
            "checksum": "1220"
            + hashlib.sha256(NAMES_PATH.read_bytes()).hexdigest(),
            "row_groups": stats["row_groups"],
            "row_group_rows": NAMES_ROW_GROUP_ROWS,
            "sorted_by": ["name_norm", "level", "country", "feature_id"],
        },
        "boundaries": boundaries,
        "attribution": [
            {
                "text": "© OpenStreetMap contributors. Available under the "
                "Open Database License.",
                "license": "ODbL-1.0",
                "url": "https://www.openstreetmap.org/copyright",
                "share_alike": True,
            },
            {
                "text": "Overture Maps Foundation, overturemaps.org",
                "license": "ODbL-1.0",
                "url": "https://overturemaps.org/",
                "share_alike": True,
            },
            {
                "text": "geoBoundaries. Available under CC BY 4.0.",
                "license": "CC-BY-4.0",
                "url": "https://www.geoboundaries.org/",
                "share_alike": False,
            },
            {
                "text": "Esri Community Maps contributors. Available under "
                "CC BY 4.0.",
                "license": "CC-BY-4.0",
                "url": "https://communitymaps.arcgis.com/home/",
                "share_alike": False,
            },
            {
                "text": "Land Information New Zealand (LINZ). Available under "
                "CC BY 4.0.",
                "license": "CC-BY-4.0",
                "url": "https://www.linz.govt.nz/",
                "share_alike": False,
            },
        ],
        "share_alike": True,
        "build": {
            "pycountry": pycountry_version(),
            "alt_level_ceiling": ALT_LEVEL_CEILING,
        },
    }
    repo_catalog.mkdir(parents=True, exist_ok=True)
    out = repo_catalog / "index.json"
    out.write_text(json.dumps(doc, indent=2) + "\n")
    print(f"  manifest: {out} ({out.stat().st_size:,} bytes)")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ceiling", type=int, default=ALT_LEVEL_CEILING)
    args = ap.parse_args(argv)

    division = staged_division()
    if not division.exists():
        sys.exit(f"missing {division}; run tools/stage_source.py first")

    started = time.time()
    con = connect()
    register_iso3166(con)
    row_reference_table(con)
    con.execute(
        ROWS_SQL.format(
            division=division.as_posix(),
            refs=(WORK / "names_refs.parquet").as_posix(),
            level_case=LEVEL_CASE,
            dgeom=f"d.{geom_expr(con, division)}".replace(
                "d.ST_GeomFromWKB(geometry)", "ST_GeomFromWKB(d.geometry)"
            ),
        )
    )
    total_divisions = con.execute(
        f"SELECT count(*) FROM read_parquet('{division.as_posix()}')"
    ).fetchone()[0]
    named = con.execute("SELECT count(*) FROM base").fetchone()[0]
    dropped_unnamed = total_divisions - named
    print(
        f"divisions in scope: {total_divisions:,}, named {named:,}, "
        f"dropped unnamed {dropped_unnamed:,}"
    )

    if args.dry_run:
        report = measure(con)
        print(report["per_level"])
        print(f"alternative-name entries in names.common: "
              f"{report['alt_entries_total']:,}")
        con.close()
        return 0

    build_rows(con, ceiling=args.ceiling)
    raw = con.execute("SELECT count(*) FROM rows_raw").fetchone()[0]
    print(f"  rows before reduction: {raw:,}")

    # name_norm is computed in Python, because the contract's folding rule is
    # Unicode NFD plus a category test plus an explicit alphabet, and DuckDB
    # has no NFD. Distinct names only: 4.7M rows share far fewer strings.
    distinct = [
        r[0] for r in con.execute("SELECT DISTINCT name FROM rows_raw").fetchall()
    ]
    folded = [normalize_name(n) for n in distinct]
    # Handed over as an Arrow table rather than through executemany: there are
    # millions of distinct strings, and a parameterized insert of those costs
    # minutes where a zero-copy register costs nothing.
    norms_table = pa.table({
        "name": pa.array(distinct, pa.string()),
        "name_norm": pa.array(folded, pa.string()),
    })
    con.register("norms_arrow", norms_table)
    con.execute("CREATE OR REPLACE TABLE norms AS SELECT * FROM norms_arrow")
    con.unregister("norms_arrow")
    unfoldable = sum(1 for v in folded if v is None)
    print(
        f"  normalized {len(distinct):,} distinct name strings, "
        f"{unfoldable:,} fold to nothing and are dropped"
    )

    con.execute(NORMALIZE_SQL)
    con.execute(REDUCE_SQL)
    primary_rows, alt_rows = con.execute(
        "SELECT count(*) FILTER (WHERE alt_of IS NULL), "
        "count(*) FILTER (WHERE alt_of IS NOT NULL) FROM rows_reduced"
    ).fetchone()
    print(f"  after reduction: {primary_rows:,} primary + {alt_rows:,} alt rows")

    stats = write_index(con, started=started)
    con.close()
    extra = verify(stats)
    write_manifest(
        stats,
        extra,
        {
            "primary_rows": primary_rows,
            "alt_rows": alt_rows,
            "dropped_unnamed": dropped_unnamed,
        },
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
