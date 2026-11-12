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

1. ``ST_SimplifyPreserveTopology`` at a tolerance chosen **per feature**:
   0.4% of that feature's own bounding-box diagonal, capped at the
   collection's ceiling. It keeps the ring topology, so a simplified division
   stays a valid polygon and does not self-intersect.

2. ``ST_Buffer`` **outward** by the same per-feature tolerance.

The tolerance is per feature because a flat one cannot serve both Russia and
Saint-Barthélemy. Measured at a flat 0.03 degrees, four of the 272 countries
and dependencies fell below 99% containment and Saint-Barthélemy reached only
81.6%, because the tolerance was most of the island's width and the
simplification collapsed it to a sliver that the buffer could not recover.
Scaling the tolerance by the feature's own extent gives 0 features below 99%
at every level, which is the guarantee this file exists to make.

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

import pyarrow.parquet as pq

from ovcommon import (
    COLLECTIONS,
    DISPLAY_ROW_GROUP_ROWS,
    SIMPLIFY_SHARE,
    SIMPLIFY_TOLERANCE,
    WORK,
    boundary_path,
    connect,
    copy_ordered,
    display_path,
    footer_metadata,
    geo_metadata,
    geom_expr,
    human,
    stream_write,
)

CONTAINMENT_REPORT = WORK / "display_containment.json"

# Two segments per quarter circle. A buffer's rounded corner is approximated by
# a polygon inscribed in the true offset circle, so fewer segments means the
# corner sits slightly closer than the nominal distance. The containment check
# measures whether that matters; at these tolerances it does not.
BUFFER_SEGMENTS = 2

# Stage one: simplify and buffer, carrying the boundary file's own row number
# so stage two can restore the order. The row order is the contract of this
# file, and a parallel scan does not preserve it on its own.
BUILD_SQL = """
WITH scaled AS (
  SELECT
    (row_number() OVER () - 1)::BIGINT AS ord,
    id, division_id, name, subtype, country,
    {geom} AS geom,
    least(
      {tol},
      sqrt(power(bbox.xmax - bbox.xmin, 2) + power(bbox.ymax - bbox.ymin, 2))
        * {share}
    ) AS tol
  FROM read_parquet('{src}')
)
SELECT
  ord, id, division_id, name, subtype, country, tol,
  ST_Buffer(ST_SimplifyPreserveTopology(geom, tol), tol, {segs}) AS geometry
FROM scaled
"""

FINALIZE_SQL = """
SELECT
  id, division_id, name, subtype, country,
  tol::FLOAT AS simplify_tolerance_deg,
  ST_NPoints({geom})::INTEGER AS vertices,
  {{
    xmin: ST_XMin({geom}), ymin: ST_YMin({geom}),
    xmax: ST_XMax({geom}), ymax: ST_YMax({geom})
  }} AS bbox,
  ST_AsWKB({geom}) AS geometry
FROM read_parquet('{src}')
ORDER BY ord
"""

# Containment: what fraction of each true polygon's area the display polygon
# covers. 1.0 means the display shape contains the true one completely, which
# is the design intent. ST_Area is planar on degrees here, which is fine
# because it is a ratio of two areas over the same small patch of the globe.
CONTAINMENT_SQL = """
WITH pair AS (
  SELECT b.division_id, b.name, b.subtype, b.country,
         ST_Area({bgeom}) AS true_area,
         ST_Area(ST_Intersection({bgeom}, {dgeom})) AS kept_area
  FROM read_parquet('{boundary}') b
  JOIN read_parquet('{display}') d USING (division_id)
  WHERE ST_Area({bgeom}) > 0
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
    print(
        f"{collection}: simplifying at 0.4% of each feature's bbox diagonal, "
        f"capped at {tol} deg, then buffering out by the same amount"
    )

    con = connect()
    raw = WORK / f"{collection}.display.raw.parquet"
    raw.unlink(missing_ok=True)
    build_sql = BUILD_SQL.format(
        tol=tol, share=SIMPLIFY_SHARE, segs=BUFFER_SEGMENTS,
        src=src.as_posix(), geom=geom_expr(con, src),
    )
    copy_ordered(con, build_sql, raw)
    ordered = WORK / f"{collection}.display.ordered.parquet"
    copy_ordered(
        con,
        FINALIZE_SQL.format(src=raw.as_posix(), geom=geom_expr(con, raw)),
        ordered,
    )
    rows, tol_lo, tol_hi, *bbox = con.execute(
        f"""SELECT count(*), min(simplify_tolerance_deg),
                   max(simplify_tolerance_deg),
                   min(bbox.xmin), min(bbox.ymin),
                   max(bbox.xmax), max(bbox.ymax)
            FROM read_parquet('{ordered.as_posix()}')"""
    ).fetchone()
    print(f"  tolerance used: {tol_lo:.3g} to {tol_hi:.3g} deg")
    con.close()
    raw.unlink(missing_ok=True)

    src_rows = pq.ParquetFile(src).metadata.num_rows
    if rows != src_rows:
        sys.exit(
            f"{collection}: {rows:,} display rows against {src_rows:,} "
            "boundary rows. The two files must hold the same rows in the same "
            "order; do not publish."
        )

    write_optimized(collection, ordered, bbox)
    ordered.unlink(missing_ok=True)
    verify_alignment(collection)
    return verify_containment(collection)


def verify_alignment(collection: str) -> None:
    """Assert row i of the display file is row i of the boundary file.

    Not a formality. The search index publishes a row number, and a consumer
    reads the same row number out of either file, so a single transposed pair
    would hand somebody another division's outline.
    """
    full = pq.read_table(boundary_path(collection), columns=["division_id"])
    disp = pq.read_table(display_path(collection), columns=["division_id"])
    a = full.column("division_id").to_pylist()
    b = disp.column("division_id").to_pylist()
    mismatched = sum(1 for x, y in zip(a, b) if x != y)
    if mismatched:
        sys.exit(
            f"{collection}: {mismatched:,} of {len(a):,} rows sit at a "
            "different offset in the display file than in the boundary file"
        )
    print(f"  aligned: all {len(a):,} rows at the same offset in both files")


def write_optimized(collection: str, ordered, bbox: list[float]) -> None:
    meta = footer_metadata(
        {
            "cnmw:collection": collection,
            "cnmw:role": "display",
            "cnmw:simplify_tolerance_ceiling_deg": str(
                SIMPLIFY_TOLERANCE[collection]
            ),
            "cnmw:simplify_share_of_diagonal": str(SIMPLIFY_SHARE),
            "cnmw:buffer_segments": str(BUFFER_SEGMENTS),
        }
    )
    meta[b"geo"] = geo_metadata(
        bbox=bbox, geometry_types=["Polygon", "MultiPolygon"]
    )
    out = display_path(collection)
    md = stream_write(
        ordered,
        out,
        row_group_rows=DISPLAY_ROW_GROUP_ROWS[collection],
        footer_meta=meta,
    )
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
    boundary, display = boundary_path(collection), display_path(collection)
    rows = con.execute(
        CONTAINMENT_SQL.format(
            boundary=boundary.as_posix(),
            display=display.as_posix(),
            bgeom=f"b.{geom_expr(con, boundary)}".replace(
                "b.ST_GeomFromWKB(geometry)", "ST_GeomFromWKB(b.geometry)"
            ),
            dgeom=f"d.{geom_expr(con, display)}".replace(
                "d.ST_GeomFromWKB(geometry)", "ST_GeomFromWKB(d.geometry)"
            ),
        )
    ).fetchall()
    con.close()
    contained = [r[4] for r in rows]
    below = [r for r in rows if r[4] < 0.99]
    full = sum(1 for c in contained if c >= 0.999999)
    import pyarrow.parquet as _pq

    tols = _pq.read_table(
        display_path(collection), columns=["simplify_tolerance_deg"]
    ).column("simplify_tolerance_deg").to_pylist()
    report = {
        "collection": collection,
        "tolerance_ceiling_deg": SIMPLIFY_TOLERANCE[collection],
        "share_of_diagonal": SIMPLIFY_SHARE,
        "tolerance_min_deg": min(tols),
        "tolerance_max_deg": max(tols),
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
