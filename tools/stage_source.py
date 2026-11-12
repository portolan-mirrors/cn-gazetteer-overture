#!/usr/bin/env python3
"""Stage the Overture divisions release locally, with column projection.

    python3 tools/stage_source.py --dry-run   # sizes and projected bytes
    python3 tools/stage_source.py             # pull both types
    python3 tools/stage_source.py division    # or one of them

Two remote scans, and no more than two. The release is a 5.2 GB remote dataset
of which this catalog needs about 4.5 GB, and every later step reads the local
copy, so a rebuilt style or a retuned row group size costs nothing in egress.

``type=division_area`` is written partitioned by subtype, because the boundary
collections are per subtype and a partitioned write lets the one remote scan
feed all five of them. ``type=division`` is one file; it is small and every
consumer of it needs a self-join across the whole thing.

Why the filters are where they are
----------------------------------
``class = 'land'`` on ``division_area`` is the rule that makes the area rows
1:1 with divisions. Overture publishes a ``land`` polygon and, for coastal
divisions, a second ``maritime`` polygon covering territorial waters. Measured
against the release: 620,734 land rows over 620,734 distinct ``division_id``
values across the six subtypes this catalog carries, against 684,589 rows in
total. Keeping both would mean two geometries per GERS id, which the index
contract cannot express.

Subtype filtering saves local disk but not egress. Overture's files are
ordered spatially, so every row group holds a mix of subtypes and the reader
has to fetch each group's whole geometry column chunk regardless. The scan
reports both numbers so the difference is on the record.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time

from ovcommon import (
    COLLECTIONS,
    S3_THEME,
    SOURCES,
    SUBTYPES,
    WORK,
    ZSTD_LEVEL,
    connect,
    human,
    staged_division,
)

# Columns read from each type. Everything left out is left out on purpose,
# because a column projection is the only lever that makes this affordable.
#
# division_area: the whole ``sources`` struct array is read although only
# ``dataset`` and ``license`` are kept, because DuckDB's projection pushdown
# into a LIST(STRUCT) is not dependable and the whole column is 16 MB here.
AREA_COLUMNS = (
    "id",
    "division_id",
    "country",
    "subtype",
    "class",
    "region",
    "is_land",
    "is_territorial",
    "version",
    "bbox",
    "sources",
    "geometry",
)
# division: ``hierarchies`` is the single largest column in the file at 151 MB
# and is not read. It carries the ancestor chain with names, which would give
# a parent name directly, but ``parent_division_id`` plus a self-join gives the
# same answer from 9 MB. ``capital_division_ids``, ``capital_of_divisions``,
# ``norms``, ``theme`` and ``type`` are dropped as out of scope, and
# ``perspectives`` is dropped because it is NULL on all 4,700,999 rows of this
# release.
DIVISION_COLUMNS = (
    "id",
    "country",
    "subtype",
    "class",
    "admin_level",
    "names",
    "wikidata",
    "population",
    "region",
    "local_type",
    "parent_division_id",
    "cartography",
    "version",
    "bbox",
    "sources",
    "geometry",
)

SUBTYPE_LIST = ", ".join(f"'{s}'" for s in SUBTYPES)


def projected_bytes(con, pattern: str, columns: tuple[str, ...]) -> tuple[int, int]:
    """Compressed bytes for the projected columns, and for the whole dataset.

    Read from the Parquet footers, which is what a reader actually fetches for
    those columns. It excludes the footers themselves and any over-read, so it
    is a floor rather than an exact transfer figure.
    """
    roots = ", ".join(f"'{c}'" for c in columns)
    row = con.execute(
        f"""
        SELECT
          sum(total_compressed_size) FILTER (
            WHERE split_part(path_in_schema, ', ', 1) IN ({roots})),
          sum(total_compressed_size)
        FROM parquet_metadata('{pattern}')
        """
    ).fetchone()
    return int(row[0] or 0), int(row[1] or 0)


def stage_area(con, *, dry_run: bool) -> None:
    pattern = f"{S3_THEME}/type=division_area/*.parquet"
    projected, total = projected_bytes(con, pattern, AREA_COLUMNS)
    print(f"type=division_area: {human(total)} on S3, {human(projected)} projected")
    if dry_run:
        return

    staging_dir = WORK / "division_area-partitioned"
    staging_dir.mkdir(parents=True, exist_ok=True)
    cols = ", ".join(AREA_COLUMNS)
    started = time.time()

    # One part file at a time, each into its own directory, and each retried on
    # its own. A 4.2 GB read over a domestic connection hits a transient HTTP
    # timeout often enough that a single query over all eight parts fails more
    # often than it succeeds, and restarting it repeats the download. A
    # finished part is skipped on a rerun, so an interrupted stage resumes.
    parts_remote = [
        row[0]
        for row in con.execute(
            f"SELECT file FROM glob('{pattern}') ORDER BY file"
        ).fetchall()
    ]
    for n, remote in enumerate(parts_remote):
        part_dir = staging_dir / f"part{n:05d}"
        done = part_dir / "_DONE"
        if done.exists():
            print(f"  part {n}: already staged")
            continue
        if part_dir.exists():
            shutil.rmtree(part_dir)
        for attempt in range(1, 4):
            t0 = time.time()
            try:
                con.execute(
                    f"""
                    COPY (
                      SELECT {cols}
                      FROM read_parquet('{remote}')
                      WHERE class = 'land' AND subtype IN ({SUBTYPE_LIST})
                    ) TO '{part_dir.as_posix()}'
                    (FORMAT parquet, COMPRESSION zstd,
                     COMPRESSION_LEVEL {ZSTD_LEVEL},
                     PARTITION_BY (subtype), OVERWRITE_OR_IGNORE true)
                    """
                )
            except Exception as exc:  # noqa: BLE001 - any transport failure
                print(f"  part {n} attempt {attempt} failed: {exc}")
                if part_dir.exists():
                    shutil.rmtree(part_dir)
                if attempt == 3:
                    raise
                continue
            done.write_text("")
            print(f"  part {n}: staged in {time.time() - t0:.0f}s")
            break
    elapsed = time.time() - started

    # Fold the partition directories into one file per collection, so the
    # boundary build reads one path. country and dependency share a file.
    SOURCES.mkdir(parents=True, exist_ok=True)
    for collection, subtypes in COLLECTIONS.items():
        # Listed rather than globbed: a part file holding no rows of one
        # subtype leaves no directory for it, and DuckDB errors on a glob that
        # matches nothing.
        parts = sorted(
            f"'{p.as_posix()}'"
            for s in subtypes
            for p in staging_dir.glob(f"*/subtype={s}/*.parquet")
        )
        if not parts:
            sys.exit(f"{collection}: nothing staged for {', '.join(subtypes)}")
        out = SOURCES / f"division_area-{collection}.parquet"
        con.execute(
            f"""
            COPY (SELECT * FROM read_parquet([{', '.join(parts)}],
                                              union_by_name = true))
            TO '{out.as_posix()}'
            (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL {ZSTD_LEVEL})
            """
        )
        rows = con.execute(
            f"SELECT count(*) FROM read_parquet('{out.as_posix()}')"
        ).fetchone()[0]
        print(
            f"  {out.name}: {rows:,} rows, {human(out.stat().st_size)}"
            f" ({', '.join(subtypes)})"
        )
    shutil.rmtree(staging_dir)
    print(f"  staged in {elapsed:.0f}s")

    verify_one_area_per_division(con)


def verify_one_area_per_division(con) -> None:
    """Assert the land filter really gives one polygon per GERS id."""
    for collection in COLLECTIONS:
        path = (SOURCES / f"division_area-{collection}.parquet").as_posix()
        rows, divisions = con.execute(
            f"SELECT count(*), count(DISTINCT division_id) "
            f"FROM read_parquet('{path}')"
        ).fetchone()
        if rows != divisions:
            raise SystemExit(
                f"{collection}: {rows:,} land area rows over {divisions:,} "
                "distinct division_id. The 1:1 assumption the index contract "
                "rests on does not hold for this release; do not publish."
            )
    print("  verified: one land polygon per division in every collection")


def stage_division(con, *, dry_run: bool) -> None:
    pattern = f"{S3_THEME}/type=division/*.parquet"
    projected, total = projected_bytes(con, pattern, DIVISION_COLUMNS)
    print(f"type=division: {human(total)} on S3, {human(projected)} projected")
    if dry_run:
        return

    SOURCES.mkdir(parents=True, exist_ok=True)
    out = staged_division()
    cols = ", ".join(DIVISION_COLUMNS)
    started = time.time()
    con.execute(
        f"""
        COPY (
          SELECT {cols}
          FROM read_parquet('{pattern}')
          WHERE subtype IN ({SUBTYPE_LIST})
        ) TO '{out.as_posix()}'
        (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL {ZSTD_LEVEL})
        """
    )
    elapsed = time.time() - started
    rows = con.execute(
        f"SELECT count(*) FROM read_parquet('{out.as_posix()}')"
    ).fetchone()[0]
    print(
        f"  {out.name}: {rows:,} rows, {human(out.stat().st_size)}, "
        f"staged in {elapsed:.0f}s"
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("which", nargs="*", metavar="division|division_area")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    wanted = args.which or ["division", "division_area"]
    if set(wanted) - {"division", "division_area"}:
        ap.error("which must be division, division_area, or nothing for both")

    con = connect()
    print(f"Overture release {S3_THEME}")
    if "division" in wanted:
        stage_division(con, dry_run=args.dry_run)
    if "division_area" in wanted:
        stage_area(con, dry_run=args.dry_run)
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
