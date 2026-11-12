#!/usr/bin/env python3
"""Build the display-simplified companion for every boundary collection.

    python3 tools/build_display.py            # all five
    python3 tools/build_display.py county     # one or more

Run ``tools/build_boundaries.py`` first. Each display file holds the same rows,
in the same order, in the same row groups, as the boundary file beside it, so a
consumer that knows a feature sits at row *i* of one reads row *i* of the other
without a join. That is also what makes the search index's ``geometry_ref``
valid against both files.

What the geometry is, and why it is bigger than the truth
---------------------------------------------------------
Two steps, in this order.

1. ``ST_SimplifyPreserveTopology`` at a tolerance chosen per collection. It
   keeps the ring topology, so a simplified division stays a valid polygon and
   does not self-intersect.

2. ``ST_Buffer`` **outward** by the same tolerance.

Step 2 is the point. Simplification moves a vertex by up to the tolerance in
*either* direction, so a simplified outline cuts corners *inside* the true
boundary as often as outside it. A consumer that uses the display geometry to
decide what to download would then silently miss features in the slivers the
simplification cut away. Buffering outward by the tolerance pushes the whole
outline back out past the original, so the display shape is a superset of the
truth and the error is always inclusive. A spatial filter drawn against it
over-selects, which a later exact pass removes, rather than under-selecting,
which nothing recovers.

The buffer costs vertices, so it is drawn with two segments per quarter circle
rather than the default eight. The containment check below is what decides
whether that is enough, and it is run on every feature of every collection.
"""
from __future__ import annotations

import json
import sys

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from ovcommon import (
    COLLECTIONS,
    DISPLAY_ROW_GROUP_ROWS,
    SIMPLIFY_TOLERANCE,
    WORK,
    ZSTD_LEVEL,
    boundary_path,
    connect,
    display_path,
    footer_metadata,
    geo_metadata,
    human,
)

CONTAINMENT_REPORT = WORK / "display_containment.json"

# Two segments per quarter circle. A buffer's rounded corner is approximated by
# a polygon inscribed in the true offset circle, so fewer segments means the
# corner sits slightly closer than the nominal distance. The containment check
# measures whether that matters; at these tolerances it does not.
BUFFER_SEGMENTS = 2

BUILD_SQL = """
SELECT
  id,
  division_id,
  name,
  subtype,
  country,
  ST_Buffer(
    ST_SimplifyPreserveTopology(geometry, {tol}), {tol}, {segs}
  ) AS geometry
FROM read_parquet('{src}')
"""

FINALIZE_SQL = """
SELECT
  id, division_id, name, subtype, country,
  ST_NPoints(geometry)::INTEGER AS vertices,
  {{
    xmin: ST_XMin(geometry), ymin: ST_YMin(geometry),
    xmax: ST_XMax(geometry), ymax: ST_YMax(geometry)
  }} AS bbox,
  ST_AsWKB(geometry) AS geometry
FROM read_parquet('{src}')
"""

# Containment: what fraction of each true polygon's area the display polygon
# covers. 1.0 means the display shape contains the true one completely, which
# is the design intent. ST_Area is planar on degrees here, which is fine
# because it is a ratio of two areas over the same small patch of the globe.
CONTAINMENT_SQL = """
WITH pair AS (
  SELECT b.division_id, b.name, b.subtype, b.country,
         ST_Area(b.geometry) AS true_area,
         ST_Area(ST_Intersection(b.geometry, d.geometry)) AS kept_area
  FROM read_parquet('{boundary}') b
  JOIN read_parquet('{display}') d USING (division_id)
  WHERE ST_Area(b.geometry) > 0
)
SELECT division_id, name, subtype, country,
       kept_area / true_area AS contained
FROM pair
ORDER BY contained
"""


def build(collection: str) -> dict:
    tol = SIMPLIFY_TOLERANCE[collection]
    src = boundary_path(collection)
    if not src.exists():
        sys.exit(f"missing {src}; run tools/build_boundaries.py first")
    print(f"{collection}: simplifying at {tol} deg, then buffering out {tol} deg")

    con = connect()
    intermediate = WORK / f"{collection}.display.raw.parquet"
    intermediate.unlink(missing_ok=True)
    con.execute(
        f"""COPY ({BUILD_SQL.format(tol=tol, segs=BUFFER_SEGMENTS,
                                    src=src.as_posix())})
            TO '{intermediate.as_posix()}' (FORMAT parquet, COMPRESSION zstd)"""
    )
    table = con.execute(
        FINALIZE_SQL.format(src=intermediate.as_posix())
    ).to_arrow_table()
    con.close()

    src_rows = pq.ParquetFile(src).metadata.num_rows
    if table.num_rows != src_rows:
        sys.exit(
            f"{collection}: {table.num_rows:,} display rows against "
            f"{src_rows:,} boundary rows. The two files must hold the same "
            "rows in the same order; do not publish."
        )

    # Row order has to match the boundary file exactly, because that is the
    # whole contract of this file. Reorder the simplified rows into the
    # boundary file's own division_id order rather than trusting that COPY
    # preserved it.
    order = pq.read_table(src, columns=["division_id"]).column("division_id")
    positions = pc.index_in(order, value_set=table.column("division_id").combine_chunks())
    if pc.sum(pc.is_null(positions)).as_py():
        sys.exit(f"{collection}: a boundary division_id is missing from the display file")
    table = table.take(positions)

    write_optimized(collection, table)
    intermediate.unlink(missing_ok=True)
    return verify_containment(collection)


def write_optimized(collection: str, table: pa.Table) -> None:
    bbox_col = table.column("bbox").combine_chunks()
    bbox = [
        pc.min(bbox_col.field("xmin")).as_py(),
        pc.min(bbox_col.field("ymin")).as_py(),
        pc.max(bbox_col.field("xmax")).as_py(),
        pc.max(bbox_col.field("ymax")).as_py(),
    ]
    meta = footer_metadata(
        {
            "cnmw:collection": collection,
            "cnmw:role": "display",
            "cnmw:simplify_tolerance_deg": str(SIMPLIFY_TOLERANCE[collection]),
        }
    )
    meta[b"geo"] = geo_metadata(
        bbox=bbox, geometry_types=["Polygon", "MultiPolygon"]
    )
    table = table.replace_schema_metadata(meta)

    out = display_path(collection)
    out.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        table,
        out,
        compression="zstd",
        compression_level=ZSTD_LEVEL,
        row_group_size=DISPLAY_ROW_GROUP_ROWS[collection],
        write_statistics=True,
        write_page_index=True,
        version="2.6",
    )
    md = pq.ParquetFile(out).metadata
    size = out.stat().st_size
    full = pq.ParquetFile(boundary_path(collection)).metadata
    print(
        f"  {out.name}: {human(size)}, {md.num_rows:,} rows, "
        f"{md.num_row_groups:,} row groups, "
        f"{size / md.num_rows / 1024:.1f} KiB per feature"
    )
    if md.num_row_groups != full.num_row_groups:
        sys.exit(
            f"{collection}: {md.num_row_groups} display row groups against "
            f"{full.num_row_groups} boundary row groups; they must match"
        )


def verify_containment(collection: str) -> dict:
    """Measure what fraction of each true polygon the display polygon covers."""
    con = connect()
    rows = con.execute(
        CONTAINMENT_SQL.format(
            boundary=boundary_path(collection).as_posix(),
            display=display_path(collection).as_posix(),
        )
    ).fetchall()
    con.close()
    contained = [r[4] for r in rows]
    below = [r for r in rows if r[4] < 0.99]
    full = sum(1 for c in contained if c >= 0.999999)
    report = {
        "collection": collection,
        "tolerance_deg": SIMPLIFY_TOLERANCE[collection],
        "buffer_segments": BUFFER_SEGMENTS,
        "features": len(rows),
        "fully_contained": full,
        "min_contained": min(contained) if contained else None,
        "mean_contained": sum(contained) / len(contained) if contained else None,
        "below_99pct": len(below),
        "worst": [
            {
                "division_id": r[0],
                "name": r[1],
                "subtype": r[2],
                "country": r[3],
                "contained": round(r[4], 6),
            }
            for r in rows[:5]
        ],
    }
    print(
        f"  containment: {full:,}/{len(rows):,} features fully contained, "
        f"{len(below):,} below 99%, worst "
        f"{report['min_contained']:.6f}"
    )
    for w in report["worst"][:3]:
        print(f"    {w['contained']:.6f}  {w['name']} ({w['country']}, {w['subtype']})")
    return report


def main(argv: list[str]) -> int:
    wanted = argv or list(COLLECTIONS)
    unknown = set(wanted) - set(COLLECTIONS)
    if unknown:
        sys.exit(f"unknown collection(s): {', '.join(sorted(unknown))}")
    existing = {}
    if CONTAINMENT_REPORT.exists():
        existing = {
            r["collection"]: r for r in json.loads(CONTAINMENT_REPORT.read_text())
        }
    for collection in wanted:
        existing[collection] = build(collection)
    CONTAINMENT_REPORT.parent.mkdir(parents=True, exist_ok=True)
    CONTAINMENT_REPORT.write_text(
        json.dumps([existing[c] for c in COLLECTIONS if c in existing], indent=2)
        + "\n"
    )
    print(f"containment report: {CONTAINMENT_REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
