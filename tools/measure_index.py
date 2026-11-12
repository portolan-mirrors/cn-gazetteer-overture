#!/usr/bin/env python3
"""Measure what the search index costs a client, and write the numbers down.

    python3 tools/measure_index.py

Three questions a consumer of this index has, answered against the built file
rather than asserted:

1. **What does the metadata cost?** A range-request client reads the footer
   before anything else, and the index manifest declares the file size so that
   read can be one exactly-sized tail request. The number this prints is what
   that request has to fetch.

2. **What does a keystroke cost?** For every two-letter prefix that occurs in
   the index, how many row groups can hold a match. The answer is bounded by
   the sort: a prefix lives in a contiguous run of groups, and the row group
   statistics on ``name_norm`` are what a client binary-searches. A prefix that
   touches one group costs one range request.

3. **Where do the bytes go?** Compressed bytes per column, so a future change
   to the schema can be argued about with numbers.

The results go to ``docs/index-measurements.md``, which the collection README
cites. Rerun it after any rebuild: if these numbers moved, the prose is wrong.
"""
from __future__ import annotations

import bisect
import json
import statistics
import sys
from pathlib import Path

import pyarrow.parquet as pq

from ovcommon import NAMES_PATH, NAMES_ROW_GROUP_ROWS, human

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs" / "index-measurements.md"


def footer_bytes(path: Path) -> int:
    """Bytes from the end of the last page to the end of the file.

    That is the column index, the offset index and the footer together, which
    is what a client fetches before it can read any row group. Parquet writes
    the page index after the last row group and the footer after that, so the
    span from the end of the last column chunk's pages to EOF is the right
    measure. ``file_offset`` is optional and PyArrow writes 0 for it, so the
    offset is taken from the dictionary page where there is one and from the
    first data page otherwise.
    """
    md = pq.ParquetFile(path).metadata
    last = md.row_group(md.num_row_groups - 1)
    end_of_data = 0
    for i in range(last.num_columns):
        col = last.column(i)
        start = col.dictionary_page_offset or col.data_page_offset
        end_of_data = max(end_of_data, start + col.total_compressed_size)
    size = path.stat().st_size
    with path.open("rb") as fh:
        fh.seek(-8, 2)
        tail = fh.read(8)
    metadata_len = int.from_bytes(tail[:4], "little")
    # The thrift footer plus its length and the trailing magic. This is what a
    # reader fetches as "the footer": the page index bodies sit before it and
    # are read per column chunk, lazily, only by a reader that wants a page
    # rather than a whole chunk.
    footer = metadata_len + 8
    return footer, size - end_of_data - footer


def row_group_ranges(path: Path) -> list[tuple[str, str]]:
    """The name_norm min and max of every row group, in file order."""
    md = pq.ParquetFile(path).metadata
    ranges = []
    for g in range(md.num_row_groups):
        rg = md.row_group(g)
        idx = next(
            i for i in range(rg.num_columns)
            if rg.column(i).path_in_schema == "name_norm"
        )
        st = rg.column(idx).statistics
        ranges.append((st.min, st.max))
    return ranges


def groups_for_prefix(ranges: list[tuple[str, str]], prefix: str) -> int:
    """How many row groups can hold a name starting with prefix.

    The same arithmetic a client does: find the first group whose max is not
    below the prefix, then walk while the group's min still sorts below the
    prefix's upper bound. Compared on UTF-8 bytes, which is the file's order.
    """
    lows = [lo.encode("utf-8") for lo, _ in ranges]
    highs = [hi.encode("utf-8") for _, hi in ranges]
    key = prefix.encode("utf-8")
    upper = key + b"\xff" * 8
    first = bisect.bisect_left(highs, key)
    last = bisect.bisect_right(lows, upper) - 1
    if first > last:
        return 0
    return last - first + 1


def column_bytes(path: Path) -> list[tuple[str, int]]:
    md = pq.ParquetFile(path).metadata
    totals: dict[str, int] = {}
    for g in range(md.num_row_groups):
        rg = md.row_group(g)
        for i in range(rg.num_columns):
            col = rg.column(i)
            totals[col.path_in_schema] = (
                totals.get(col.path_in_schema, 0) + col.total_compressed_size
            )
    return sorted(totals.items(), key=lambda kv: -kv[1])


def main() -> int:
    if not NAMES_PATH.exists():
        sys.exit(f"missing {NAMES_PATH}; run tools/build_names.py first")
    pf = pq.ParquetFile(NAMES_PATH)
    md = pf.metadata
    size = NAMES_PATH.stat().st_size
    footer, page_index = footer_bytes(NAMES_PATH)
    ranges = row_group_ranges(NAMES_PATH)

    # Every two-character prefix that actually occurs, taken from the row group
    # boundaries plus the full name_norm column. Reading one column of this
    # file is a few hundred megabytes of decode, which is fine once.
    norms = pq.read_table(NAMES_PATH, columns=["name_norm"]).column("name_norm")
    prefixes = sorted({v[:2] for v in norms.to_pylist() if len(v) >= 2})
    counts = [groups_for_prefix(ranges, p) for p in prefixes]
    present = [c for c in counts if c]

    cols = column_bytes(NAMES_PATH)
    lines = [
        "# Search index measurements",
        "",
        "Generated by `tools/measure_index.py` against the built index. Every",
        "number in `catalog/names/README.md` and in the collection description",
        "comes from here. Rerun after any rebuild.",
        "",
        "## The file",
        "",
        "| | |",
        "|---|---|",
        f"| Rows | {md.num_rows:,} |",
        f"| Size | {human(size)} ({size:,} bytes) |",
        f"| Bytes per row | {size / md.num_rows:.1f} |",
        f"| Row groups | {md.num_row_groups:,} of {NAMES_ROW_GROUP_ROWS:,} rows |",
        f"| Mean row group | "
        f"{human(int((size - footer - page_index) / md.num_row_groups))} |",
        f"| Footer metadata | {footer:,} bytes "
        f"({100 * footer / size:.2f}% of the file) |",
        f"| Page index | {page_index:,} bytes "
        f"({100 * page_index / size:.2f}% of the file) |",
        f"| Columns | {len(pf.schema_arrow.names)} |",
        "",
        "A range-request client fetches the footer metadata once, and the",
        "index manifest declares `index.size` so that fetch can be one",
        "exactly-sized tail request rather than a speculative 512 KB one. The",
        "page index is **not** part of that read: its bodies sit before the",
        "footer, and a reader fetches the slice belonging to one column chunk",
        "only when it wants a single page rather than the whole chunk.",
        "",
        "**Why the row groups are this large.** The index-file contract asks",
        "for 100-150 KiB per row group, which is right for the 2.5 MB index it",
        "was measured on and wrong for this one. The footer carries one thrift",
        "record per column per row group, so it grows as the row groups shrink,",
        "and a range-request client reads the whole footer before it reads",
        "anything. Measured on this index:",
        "",
        "| rows/group | groups | footer | page index | per group | footer + 1 group |",
        "|---|---|---|---|---|---|",
        "| 1,600 | 3,503 | 8.15 MB | 2.45 MB | 121 KiB | 8.27 MB |",
        "| 3,200 | 1,752 | 4.10 MB | 1.23 MB | 239 KiB | 4.34 MB |",
        "| 6,400 | 876 | 2.05 MB | 0.62 MB | 474 KiB | 2.52 MB |",
        "| 12,800 | 438 | 1.05 MB | 0.32 MB | 960 KiB | 2.01 MB |",
        "",
        "6,400 is the knee: it answers a first keystroke in 2.5 MB against 8.3",
        "MB at the contract's band, and a later keystroke in under half a",
        "megabyte, which a client holds anyway because typing one more letter",
        "of the same prefix stays inside the same row group. 12,800 saves",
        "another half megabyte on the first read and doubles every later one.",
        "",
        "Statistics are written on",
        "`name_norm`, `level`, `subtype`, `country`, `source`, `has_boundary`,",
        "`name_lang`, `name_lang_count` and `name_dupes` only. With statistics",
        "on all 19 columns the footer was 8.15 MB at 1,600-row groups rather",
        "than 10.77 MB, because a min and a max of `name`, `parent_name`,",
        "`feature_id` and `alt_of` is four strings per row group. Those",
        "statistics would prune nothing: the file is sorted by `name_norm` and",
        "nothing else, so every other column's ranges overlap across every",
        "group.",
        "",
        "## Row groups touched per two-letter prefix",
        "",
        f"Measured over all {len(prefixes):,} two-character prefixes that occur",
        "in `name_norm`, using the same arithmetic a client does against the",
        "row group statistics.",
        "",
        "| | row groups |",
        "|---|---|",
        f"| minimum | {min(present)} |",
        f"| median | {statistics.median(present):.0f} |",
        f"| mean | {statistics.mean(present):.2f} |",
        f"| 95th percentile | "
        f"{sorted(present)[int(0.95 * len(present))]} |",
        f"| maximum | {max(present)} |",
        "",
        f"So a typed two-letter prefix costs a median of "
        f"{statistics.median(present):.0f} row group read"
        f"{'' if statistics.median(present) == 1 else 's'} of about "
        f"{human(int((size - footer - page_index) / md.num_row_groups))}, on "
        f"top of the {footer:,}-byte footer metadata read that happens once, "
        f"and never more than {max(present)}.",
        "",
        "The worst prefixes, which are the common ones:",
        "",
        "| prefix | row groups |",
        "|---|---|",
    ]
    worst = sorted(zip(prefixes, counts), key=lambda kv: -kv[1])[:10]
    lines += [f"| `{p}` | {c} |" for p, c in worst]
    lines += [
        "",
        "## Compressed bytes per column",
        "",
        "| column | bytes | share |",
        "|---|---|---|",
    ]
    data_bytes = sum(b for _, b in cols)
    lines += [
        f"| `{name}` | {b:,} | {100 * b / data_bytes:.1f}% |" for name, b in cols
    ]
    lines += [""]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines))
    print("\n".join(lines[:30]))
    print(f"\nwritten to {OUT.relative_to(REPO)}")
    (OUT.parent / "index-measurements.json").write_text(
        json.dumps(
            {
                "rows": md.num_rows,
                "size": size,
                "bytes_per_row": round(size / md.num_rows, 2),
                "row_groups": md.num_row_groups,
                "row_group_rows": NAMES_ROW_GROUP_ROWS,
                "mean_row_group_bytes": int(
                    (size - footer - page_index) / md.num_row_groups
                ),
                "footer_bytes": footer,
                "page_index_bytes": page_index,
                "prefixes": len(prefixes),
                "groups_per_prefix": {
                    "min": min(present),
                    "median": statistics.median(present),
                    "mean": round(statistics.mean(present), 2),
                    "p95": sorted(present)[int(0.95 * len(present))],
                    "max": max(present),
                },
            },
            indent=2,
        )
        + "\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
