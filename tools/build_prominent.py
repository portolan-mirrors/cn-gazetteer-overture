#!/usr/bin/env python3
"""Build the prominent index: the small, eagerly loadable half of the search.

    python3 tools/build_prominent.py --measure    # size per candidate cut
    python3 tools/build_prominent.py              # build it

Why there are two indexes
-------------------------
The full index is 408 MiB in 5.6 million rows. A browser cannot load that, so
`geocoder-core`'s `auto` strategy puts it on the **range** path: every
keystroke is an HTTP round trip, and the first one also pays the 2 MB footer.
That is the right design for "find me Ortsteil Sankt Georgen" and the wrong
one for the first three characters anybody types, which are almost always a
country, a big region or a well-known city.

So this file is the other half: **levels 0-2 entirely, plus every localadmin,
plus the localities Overture itself ranks as prominent**, in the same schema
and the same sort as the full index. It is small enough to fetch whole and
binary-search in memory, so a client can full-load it on focus and answer
keystrokes at 0 ms while the 408 MiB index stays available, unchanged, for
deep queries by range request.

Neither file is authoritative over the other. Every row in this one is a
byte-for-byte copy of a row in the full index -- same `feature_id`, same
`geometry_ref`, same `name_norm` -- so a hit found here resolves its geometry
exactly as a hit found there, and a client that wants completeness queries the
full index and ignores this one.

The prominence criteria
-----------------------
Stated here, in the manifest under `prominent_index.criteria`, and in
`AGENTS.md`, because a client that does not know what was left out cannot know
when to fall back to the full index.

1. **Every primary row at levels 0-3** -- country, dependency, region, county,
   localadmin. 64,640 divisions. These are the names a first keystroke hits
   and there is no defensible cut on them: there are only 272 countries and
   3,929 regions. Overture populates neither `cartography.prominence` nor
   `class` on anything above locality in this release -- measured, 0 of 72,947
   localadmin rows carry either -- so above level 4 there is no ranking signal
   to cut on even if one were wanted.

2. **Alternative-name rows at levels 0 and 4.** At level 0, all 25,348 of
   them: every spelling of every country and dependency, in every language
   Overture carries. Level 4's are gated by the higher prominence cut in
   criterion 3. Which alt levels to carry is a budget decision rather than a
   data fact, and the measurement below is what made it.

3. **Level 4 (locality): primary rows at `prominence >= 50`, alternative-name
   rows at `prominence >= 70`.** 18,931 primary + 59,099 alternative rows out
   of the index's 5,230,456 level-4 rows. `cartography.prominence` is
   Overture's own 1-100 ranking of how important a place is to show on a map;
   it is populated on all 3,508,156 localities and carried on their
   alternative-name rows too, so a cut on it keeps a division's spellings
   with it rather than orphaning them.

   The alternative-name rows are not optional garnish at this level: a
   locality whose primary name is not written in Latin script is *only*
   reachable by the name most users type through an alternative-name row.
   Baghdad's primary row is "بغداد"; "Baghdad" (prominence 99) is an alt
   row. The first shipped build of this file kept level-0 alt rows only,
   which silently dropped Baghdad, Tehran, Dhaka and Ho Chi Minh City while
   its published criteria claimed "primary or alternative" -- found when the
   client's fuzzy fallback could not see Baghdad, fixed 2026-11-13.

   Why two cuts: there are 7.6x as many level-4 alt rows above 50 (144,623)
   as primary ones, so admitting them all costs 20.5 MB (see the grid). At
   70 the spellings of every world-class city survive -- the lowest-scoring
   English exonyms measured among 31 famous cities were Venice (83), Cologne
   (84) and Florence (84); Baghdad is 99 -- while places at prominence 50-69
   stay reachable by their primary spelling here and by everything in the
   full index.

The size target and "levels 0-2 entirely" are mutually exclusive
---------------------------------------------------------------
This is the measurement that says so. `--measure` builds each candidate and
weighs it against the 8 MiB budget that makes a file worth fetching whole
(`cut` gates level-4 primary rows, `acut` level-4 alternative-name rows):

    primary levels   alt levels  cut acut      rows   l4 rows         size  vs 8 MiB
      [0, 1, 2, 3] [0, 1, 2, 3]   50   50   392,888    18,931   30,777,668     3.7x
      [0, 1, 2, 3]       [0, 1]   50   50   194,362    18,931   14,744,196     1.8x
      [0, 1, 2, 3]          [0]   50   50   108,919    18,931    9,037,021     1.1x
      [0, 1, 2, 3]       [0, 4]   50   50   253,542   163,554   20,464,398     2.4x
      [0, 1, 2, 3]       [0, 4]   50   60   205,643   115,655   16,609,391     2.0x
      [0, 1, 2, 3]       [0, 4]   50   70   168,018    78,030   13,566,995     1.6x  <-
      [0, 1, 2, 3]       [0, 4]   50   80   143,831    53,843   11,612,189     1.4x
      [0, 1, 2, 3]           []   50   50    83,571    18,931    7,766,402     0.9x

Carrying levels 0-2 entirely, alternative names included, is 30.8 MB however
hard level 4 is cut -- because the alternative names *are* the rows: 257,872 of
them at levels 0-2 against 43,138 divisions. The cause is the schema this file
is required to share with the full index: `feature_id` and `alt_of` are
32-character GERS identifiers and together they are a third of every
alternative-name row.

So the shipped policy keeps alternative names at level 0 (every spelling of
every country) and level 4 from prominence 70 (every spelling of every major
city), and drops them at levels 1-3, at 13,566,995 bytes -- 1.6x the 8 MiB
that would be ideal, and the price of a search index that can actually find
Baghdad. The candidates that admit levels 1-3 alt names or level-4 alt names
at 50 buy their extra recall at 1.8-3.7x, on spellings of places a first
keystroke rarely wants; the one candidate strictly under the target drops
multilingual matching altogether, which costs a user typing "Deutschland" or
"中国" every result. `ALT_LEVELS` and the two cuts move it either way, and
every row of every rejected candidate is still in the full index.

`class` was considered as the level-4 cut instead -- "keep class in ('city',
'town')" -- and rejected on two measurements: `class` is null on 113,393
localities, so a class cut silently drops unclassed places including real
cities; and the names index does not carry `class` at all, so cutting on it
would mean either adding a column to the published schema or joining the
locality boundary file on every build. `area_km2` was rejected too: 2,952,062
localities have no polygon and therefore no area, which is most of them.

**What prominence is not.** Overture documents it as cartographic guidance,
not as a measured quantity. So this is a *recall* boundary, not a claim that
an excluded place is unimportant. The cut's job is to keep the file small, and
the full index is what makes every omission recoverable.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from ovcommon import (
    NAMES_PATH,
    PUBLISH,
    ZSTD_LEVEL,
    footer_metadata,
    human,
)
from build_names import SOURCE_NAME, STATISTICS_COLUMNS

OUT = PUBLISH / "names" / "overture_division_names_prominent.parquet"

# The four knobs of the row policy. Together they are the whole definition of
# "prominent", they are published verbatim in the manifest under
# `prominent_index.criteria`, and `--measure` prints the grid they came from.
#
# PRIMARY_LEVELS     -- levels that keep every primary (one-per-division) row.
# ALT_LEVELS         -- levels that *also* keep their alternative-name rows.
# PROMINENCE_CUT     -- level-4 primary rows need at least this prominence.
# ALT_PROMINENCE_CUT -- level-4 alternative-name rows need this higher one.
PRIMARY_LEVELS = (0, 1, 2, 3)
ALT_LEVELS = (0, 4)
PROMINENCE_CUT = 50
ALT_PROMINENCE_CUT = 70

# A byte target, not a row count: this file is on the full-load path, so the
# row group size only matters for the range path a client may still use on it.
# The index contract asks for 100-150 KiB per group at this file size.
ROW_GROUP_ROWS = 1536
ROW_GROUP_TARGET_KIB = (100, 150)

# The policy grid --measure reports, as (primary levels, alt levels, cut).
# POOL_CUT is the lowest cut any of them uses, so one read pass collects a
# superset and every candidate is filtered out of it in memory.
# Entries are (primary levels, alt levels, cut, alt cut); the alt cut gates
# level-4 alternative-name rows and is meaningless unless 4 is in alt levels.
POLICY_GRID = (
    ((0, 1, 2, 3), (0, 1, 2, 3), 50, 50),
    ((0, 1, 2, 3), (0, 1), 50, 50),
    ((0, 1, 2, 3), (0,), 50, 50),
    ((0, 1, 2, 3), (0, 4), 50, 50),
    ((0, 1, 2, 3), (0, 4), 50, 60),
    ((0, 1, 2, 3), (0, 4), 50, 70),
    ((0, 1, 2, 3), (0, 4), 50, 80),
    ((0, 1, 2, 3), (), 50, 50),
)
POOL_CUT = 50

READ_BATCH = 262_144


def mask(table: pa.Table, primary_levels, alt_levels, cut: int,
         alt_cut: int | None = None):
    """The row policy, as one boolean mask.

    A row is kept when it is a primary row at a level that keeps primary rows,
    or an alternative-name row at a level that keeps those too -- and, at
    level 4 either way, only at or above a prominence cut: ``cut`` for primary
    rows, ``alt_cut`` (defaulting to ``cut``) for alternative-name rows. The
    alt cut exists because there are 7.6x as many level-4 alternative-name
    rows above 50 as primary ones, so the spellings need a higher bar than
    the divisions to stay inside the byte budget.
    """
    if alt_cut is None:
        alt_cut = cut
    level = table.column("level")
    is_alt = pc.is_valid(table.column("alt_of"))
    # A null prominence is not >= anything. fill_null keeps the mask boolean
    # rather than letting a null propagate into or_/and_, where it would drop a
    # row silently instead of by rule. Overture populates prominence on every
    # locality and on nothing else, so this is false for levels 0-3.
    prominence = table.column("prominence")
    above_cut = pc.fill_null(pc.greater_equal(prominence, cut), False)
    above_alt_cut = pc.fill_null(pc.greater_equal(prominence, alt_cut), False)
    deep = pc.equal(level, pa.scalar(4, pa.int8()))

    def admitted(levels):
        if not levels:
            return pc.equal(level, pa.scalar(-1, pa.int8()))  # all false
        return pc.is_in(level, value_set=pa.array(levels, pa.int8()))

    # At level 4 the level list alone never admits a row: the cut does.
    primary_ok = pc.and_(
        pc.invert(is_alt),
        pc.or_(
            pc.and_(admitted(primary_levels), pc.invert(deep)),
            pc.and_(deep, above_cut),
        ),
    )
    alt_ok = pc.and_(
        is_alt,
        pc.or_(
            pc.and_(admitted(alt_levels), pc.invert(deep)),
            pc.and_(pc.and_(deep, admitted(alt_levels)), above_alt_cut),
        ),
    )
    return pc.or_(primary_ok, alt_ok)


def collect() -> pa.Table:
    """One pass over the full index, keeping a superset of every candidate.

    The full index is sorted by `(name_norm, level, country, feature_id)` and a
    filter preserves row order, so the result is sorted without re-sorting --
    which matters, because re-sorting would have to reproduce the builder's
    byte-wise UTF-8 comparison exactly or silently break the binary search.
    """
    if not NAMES_PATH.exists():
        sys.exit(f"missing {NAMES_PATH}; run tools/build_names.py first")
    reader = pq.ParquetFile(NAMES_PATH)
    kept = []
    rows_in = 0
    started = time.time()
    low = min(POOL_CUT, PROMINENCE_CUT, ALT_PROMINENCE_CUT)
    widest = ((0, 1, 2, 3), (0, 1, 2, 3, 4), low, low)
    for batch in reader.iter_batches(batch_size=READ_BATCH):
        table = pa.Table.from_batches([batch])
        rows_in += table.num_rows
        kept.append(table.filter(mask(table, *widest)))
        print(
            f"\r  read {rows_in:,} of {reader.metadata.num_rows:,} rows, "
            f"kept {sum(t.num_rows for t in kept):,} "
            f"({time.time() - started:.0f}s)",
            end="",
            flush=True,
        )
    print()
    return pa.concat_tables(kept)


def subset(table: pa.Table, primary_levels, alt_levels, cut: int,
           alt_cut: int | None = None) -> pa.Table:
    return table.filter(mask(table, primary_levels, alt_levels, cut, alt_cut))


def write(table: pa.Table, out: Path, *, cut: int, alt_cut: int) -> dict:
    """Write the file with the full index's own schema metadata and sort."""
    source_schema = pq.ParquetFile(NAMES_PATH).schema_arrow
    meta = footer_metadata({"cnmw:index_source": SOURCE_NAME})
    # The GeoParquet metadata is the full index's, with its own measured
    # extent: this file is a row subset, so its bbox can only be narrower, and
    # a covering that claims more than it holds prunes nothing but is not
    # wrong. Copying it keeps the two files' metadata identical for every key
    # a client might compare.
    if source_schema.metadata and b"geo" in source_schema.metadata:
        meta[b"geo"] = source_schema.metadata[b"geo"]
    meta[b"cnmw:prominent_of"] = NAMES_PATH.name.encode()
    meta[b"cnmw:prominence_cut"] = str(cut).encode()
    meta[b"cnmw:alt_prominence_cut"] = str(alt_cut).encode()
    table = table.replace_schema_metadata(meta)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    pq.write_table(
        table,
        out,
        compression="zstd",
        compression_level=ZSTD_LEVEL,
        write_statistics=STATISTICS_COLUMNS,
        write_page_index=True,
        version="2.6",
        row_group_size=ROW_GROUP_ROWS,
        sorting_columns=[
            pq.SortingColumn(
                table.schema.get_field_index("name_norm"),
                descending=False,
                nulls_first=True,
            )
        ],
    )
    md = pq.ParquetFile(out).metadata
    return {
        "rows": md.num_rows,
        "row_groups": md.num_row_groups,
        "size": out.stat().st_size,
    }


def verify(out: Path, full_rows: int) -> None:
    """Re-check the guarantees a client re-checks, plus the subset property."""
    pf = pq.ParquetFile(out)
    md = pf.metadata
    problems = []
    full = pq.ParquetFile(NAMES_PATH).schema_arrow
    if pf.schema_arrow.names != full.names:
        problems.append("column names differ from the full index")
    else:
        for name in full.names:
            if pf.schema_arrow.field(name).type != full.field(name).type:
                problems.append(f"{name} has a different type from the full index")
    if not md.row_group(0).sorting_columns:
        problems.append("the footer declares no sorting_columns")

    norm = pq.read_table(out, columns=["name_norm"]).column("name_norm").to_pylist()
    if any(v is None for v in norm):
        problems.append("name_norm holds a null")
    else:
        encoded = [v.encode("utf-8") for v in norm]
        bad = sum(1 for i in range(len(encoded) - 1) if encoded[i] > encoded[i + 1])
        if bad:
            problems.append(f"name_norm is not ascending at {bad} position(s)")
    if md.num_rows >= full_rows:
        problems.append("the prominent index is not smaller than the full index")

    truncated = 0
    for g in range(md.num_row_groups):
        rg = md.row_group(g)
        idx = next(
            i for i in range(rg.num_columns)
            if rg.column(i).path_in_schema == "name_norm"
        )
        st = rg.column(idx).statistics
        if st is None or st.min is None or st.max is None:
            problems.append(f"row group {g} has no name_norm statistics")
            break
        if len(st.min) >= 64 or len(st.max) >= 64:
            truncated += 1
    if truncated:
        problems.append(f"{truncated} row group(s) may have truncated statistics")

    if problems:
        raise SystemExit("\n".join(f"error  {p}" for p in problems))
    print("  OK: same schema and sort as the full index, strictly a subset")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--measure", action="store_true",
                    help="report size per candidate cut and write nothing")
    ap.add_argument("--json", help="write the measurement table here")
    args = ap.parse_args(argv)

    full_md = pq.ParquetFile(NAMES_PATH).metadata
    full_size = NAMES_PATH.stat().st_size
    print(
        f"full index: {human(full_size)}, {full_md.num_rows:,} rows "
        f"({NAMES_PATH.name})"
    )

    if args.measure:
        pool = collect()
        rows = []
        tmp = PUBLISH / "names" / ".prominent-measure.parquet"
        print(
            f"\n  {'primary':>12} {'alt':>12} {'cut':>4} {'acut':>4} "
            f"{'rows':>9} {'l4 rows':>9} {'size':>12} {'B/row':>7} {'vs 8 MiB':>9}"
        )
        for primary_levels, alt_levels, cut, alt_cut in POLICY_GRID:
            table = subset(pool, primary_levels, alt_levels, cut, alt_cut)
            stats = write(table, tmp, cut=cut, alt_cut=alt_cut)
            l4 = pc.sum(
                pc.cast(pc.equal(table.column("level"), 4), pa.int64())
            ).as_py()
            rows.append({
                **stats,
                "primary_levels": list(primary_levels),
                "alt_levels": list(alt_levels),
                "cut": cut,
                "alt_cut": alt_cut,
                "level4_rows": l4,
            })
            print(
                f"  {str(list(primary_levels)):>12} {str(list(alt_levels)):>12} "
                f"{cut:>4} {alt_cut:>4} "
                f"{stats['rows']:>9,} {l4:>9,} {stats['size']:>12,} "
                f"{stats['size'] / stats['rows']:>7.1f} "
                f"{stats['size'] / (8 << 20):>8.1f}x"
            )
        tmp.unlink(missing_ok=True)
        if args.json:
            Path(args.json).write_text(json.dumps(rows, indent=2) + "\n")
        print(
            f"\n  shipped policy: primary {list(PRIMARY_LEVELS)}, "
            f"alt {list(ALT_LEVELS)}, cut {PROMINENCE_CUT}, "
            f"alt cut {ALT_PROMINENCE_CUT}"
        )
        return 0

    table = subset(
        collect(), PRIMARY_LEVELS, ALT_LEVELS, PROMINENCE_CUT, ALT_PROMINENCE_CUT
    )
    stats = write(table, OUT, cut=PROMINENCE_CUT, alt_cut=ALT_PROMINENCE_CUT)
    per_group_kib = stats["size"] / stats["row_groups"] / 1024
    print(
        f"prominent: {OUT.name} {human(stats['size'])}, {stats['rows']:,} rows "
        f"({100 * stats['rows'] / full_md.num_rows:.1f}% of the full index), "
        f"{stats['row_groups']:,} row groups of {ROW_GROUP_ROWS:,}, "
        f"{per_group_kib:.0f} KiB per group, "
        f"{stats['size'] / stats['rows']:.1f} bytes per row"
    )
    lo, hi = ROW_GROUP_TARGET_KIB
    if not (lo * 0.75 <= per_group_kib <= hi * 1.25):
        print(
            f"  WARNING: {per_group_kib:.0f} KiB per group is outside the "
            f"{lo}-{hi} KiB target. Retune ROW_GROUP_ROWS to about "
            f"{int(ROW_GROUP_ROWS * 125 / per_group_kib)}."
        )
    by_level = {}
    for lvl, n in zip(*[
        c.to_pylist() for c in
        table.group_by("level").aggregate([("level", "count")]).columns
    ]):
        by_level[lvl] = n
    print(f"  rows per level: {dict(sorted(by_level.items()))}")
    verify(OUT, full_md.num_rows)
    patch_manifest()
    return 0


def patch_manifest() -> None:
    """Write this file's `prominent_index` block into the published manifest.

    `tools/build_names.py` writes the manifest and fills `prominent_index`
    from this file when it already exists, but the pipeline runs the other way
    round -- the prominent index is built *from* the full index, so on a fresh
    build the manifest is written before this file exists. Rather than make a
    client depend on build order, this patches the one key back in, from the
    same function that would have produced it, so either order converges.
    """
    import build_names

    manifest = Path(__file__).resolve().parents[1] / "catalog" / "names" / "index.json"
    if not manifest.exists():
        print(f"  note: {manifest} does not exist; run tools/build_names.py")
        return
    doc = json.loads(manifest.read_text())
    entry = build_names.prominent_index_entry()
    if doc.get("prominent_index") == entry:
        print("  manifest already describes this prominent index")
        return
    # Keep the key where build_names.py puts it -- immediately after `index`
    # -- so the two writers cannot produce manifests that differ only in key
    # order and churn the diff.
    rebuilt = {}
    for key, value in doc.items():
        if key == "prominent_index":
            continue
        rebuilt[key] = value
        if key == "index":
            rebuilt["prominent_index"] = entry
    if "prominent_index" not in rebuilt:
        rebuilt["prominent_index"] = entry
    manifest.write_text(json.dumps(rebuilt, indent=2) + "\n")
    print(f"  manifest: prominent_index written to {manifest.name}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
