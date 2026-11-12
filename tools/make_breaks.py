#!/usr/bin/env python3
"""Measure the distributions behind every style, and write the class breaks.

    python3 tools/make_breaks.py

Output is ``tools/style_breaks.py``, which ``tools/make_styles.py`` imports.
It is committed, so a reviewer can read every break and the count of features
in every band without running anything, and a rebuild that moves a count shows
up as a diff.

How a break is chosen
---------------------
Quantiles of the column's non-null values, then snapped outward to the nearest
readable number of the form 1, 2 or 5 times a power of ten, because a legend
that reads "1,000" is worth more to a reader than one that reads "1,043". The
snap can collapse two breaks into one or empty a band, so every candidate set
is counted against the data and tightened until no band is empty. That check
is the same one ``tests/test_styles.py`` runs, so a style this script emits
cannot fail that gate.

A ``match`` style's branches are not quantiles; they are the distinct values,
taken in descending frequency, and every populated value gets a branch.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb

from ovcommon import COLLECTIONS, NAMES_PATH, boundary_path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "tools" / "style_breaks.py"

# Collection -> column -> how many bands to cut it into. Six bands is the
# ramp length; a column whose spread cannot carry six gets fewer.
STEP_FIELDS = {
    "country": {"area_km2": 6, "name_langs": 6, "population": 6},
    "region": {
        "area_km2": 6, "name_langs": 6, "country_units": 6, "population": 6,
    },
    "county": {
        "area_km2": 6, "name_langs": 6, "country_units": 6, "population": 6,
    },
    "localadmin": {"area_km2": 6, "name_langs": 6, "population": 6},
    "locality": {
        "area_km2": 6, "population": 6, "name_langs": 6,
    },
    "names": {
        "name_dupes": 6, "name_lang_count": 6, "population": 6,
    },
}

# Columns styled with a match expression: every populated value gets a branch.
MATCH_FIELDS = {
    "localadmin": ["country"],
    "locality": ["class"],
}

# A qualitative palette for the one match style whose domain is large: the 19
# countries that publish a localadmin level. Spaced around the hue circle so
# neighbours in the legend are not neighbours in colour.
QUALITATIVE = [
    "#1f78b4", "#e31a1c", "#33a02c", "#ff7f00", "#6a3d9a",
    "#b15928", "#a6cee3", "#fb9a99", "#b2df8a", "#fdbf6f",
    "#cab2d6", "#ffff99", "#17becf", "#d62728", "#2ca02c",
    "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
]
CLASS_COLOURS = {
    "city": "#6e1246",
    "town": "#d55a9b",
    "village": "#f8c2dd",
    "hamlet": "#fdeaf3",
    "megacity": "#3d0526",
}


def nice(value: float) -> float:
    """Snap a value to 1, 2 or 5 times a power of ten, rounding up."""
    import math

    if value <= 0:
        return 1
    exponent = math.floor(math.log10(value))
    base = 10 ** exponent
    for multiple in (1, 2, 5, 10):
        if value <= multiple * base * 1.0000001:
            return multiple * base
    return 10 * base


def band_counts(con, table: str, field: str, breaks: list[float]) -> list[int]:
    edges = [None, *breaks, None]
    counts = []
    for lo, hi in zip(edges, edges[1:]):
        clauses = []
        if lo is not None:
            clauses.append(f'"{field}" >= {lo}')
        if hi is not None:
            clauses.append(f'"{field}" < {hi}')
        where = " AND ".join(clauses) or "TRUE"
        counts.append(
            con.execute(f"SELECT count(*) FROM {table} WHERE {where}").fetchone()[0]
        )
    return counts


# Columns whose distribution quantiles cannot carry bands, with the break set
# that does and the reason. name_lang_count is 1 on the great majority of rows,
# so every quantile of it is 1 and a quantile-derived band 0 would be empty;
# the bands below are the ones a reader of a legend would want anyway.
BREAK_OVERRIDES = {
    "names.name_lang_count": [2, 3, 5, 10, 50],
    "names.name_dupes": [2, 4, 10, 100],
    # Quantiles of name_langs at the country level land every cut on 200,
    # because the distribution is a spike there: a country averages 202
    # language names and a dependency 104. Snapped to readable numbers that
    # separate the two populations instead of collapsing to one break, which
    # would make a two-entry legend out of the most interesting column in the
    # collection.
    "country.name_langs": [50, 150, 200, 230, 260],
    # Localities cluster at 1 and 2 language names, so quantiles give two
    # bands. These separate "named once" from "named in a handful of
    # languages" from "named widely", which is what a reader wants to see.
    "locality.name_langs": [2, 3, 5, 10],
}


def step_breaks(con, table: str, field: str, bands: int) -> tuple[list, list[int]]:
    """Quantile cuts, snapped to readable numbers, with no empty band."""
    key = f"{table}.{field}"
    if key in BREAK_OVERRIDES:
        out = list(BREAK_OVERRIDES[key])
        return out, band_counts(con, table, field, out)

    quantiles = [i / bands for i in range(1, bands)]
    raw = con.execute(
        f'SELECT quantile_cont("{field}", {quantiles}) FROM {table} '
        f'WHERE "{field}" IS NOT NULL'
    ).fetchone()[0]
    candidate = []
    for value in raw:
        snapped = nice(float(value))
        if not candidate or snapped > candidate[-1]:
            candidate.append(snapped)
    # Drop any break that brackets nothing. An empty band i is fixed by
    # removing the break at index i, which merges it into its neighbour: for
    # band 0 that is the break below everything, for the last band the break
    # above everything, and in between either side works.
    while len(candidate) > 1:
        counts = band_counts(con, table, field, candidate)
        empty = [i for i, n in enumerate(counts) if n == 0]
        if not empty:
            break
        candidate.pop(min(empty[0], len(candidate) - 1))
    counts = band_counts(con, table, field, candidate)
    if any(n == 0 for n in counts):
        sys.exit(
            f"{key}: cannot find breaks with no empty band; measured bands "
            f"{counts} for breaks {candidate}. Add an entry to "
            "BREAK_OVERRIDES with the reason."
        )
    out = [int(v) if float(v).is_integer() else float(v) for v in candidate]
    return out, band_counts(con, table, field, out)


def match_branches(con, table: str, field: str) -> tuple[list, list[int]]:
    rows = con.execute(
        f'SELECT "{field}", count(*) FROM {table} '
        f'WHERE "{field}" IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1'
    ).fetchall()
    nulls = con.execute(
        f'SELECT count(*) FROM {table} WHERE "{field}" IS NULL'
    ).fetchone()[0]
    if field == "class":
        pairs = [(value, CLASS_COLOURS[value]) for value, _ in rows]
    else:
        if len(rows) > len(QUALITATIVE):
            sys.exit(
                f"{table}.{field}: {len(rows)} distinct values but only "
                f"{len(QUALITATIVE)} colours. Pick a step style instead."
            )
        pairs = [
            (value, QUALITATIVE[i % len(QUALITATIVE)])
            for i, (value, _) in enumerate(rows)
        ]
    return pairs, [n for _, n in rows] + ([nulls] if nulls else [])


def main() -> int:
    con = duckdb.connect()
    con.execute("LOAD spatial;")
    for collection in COLLECTIONS:
        path = boundary_path(collection)
        if not path.exists():
            sys.exit(f"missing {path}; run tools/build_boundaries.py first")
        con.execute(
            f"CREATE VIEW {collection} AS "
            f"SELECT * FROM read_parquet('{path.as_posix()}')"
        )
    if not NAMES_PATH.exists():
        sys.exit(f"missing {NAMES_PATH}; run tools/build_names.py first")
    con.execute(
        f"CREATE VIEW names AS SELECT * FROM read_parquet('{NAMES_PATH.as_posix()}')"
    )

    breaks: dict[str, object] = {}
    notes: list[str] = []
    for collection, fields in STEP_FIELDS.items():
        for field, bands in fields.items():
            values, counts = step_breaks(con, collection, field, bands)
            key = f"{collection}.{field}"
            breaks[key] = values
            notes.append(f"# {key}: bands {counts}")
            print(f"{key:36s} breaks {values} counts {counts}")
    # level is a fixed 0-to-4 domain, so the bands are the levels themselves
    # rather than quantiles of them.
    level_counts = con.execute(
        "SELECT level, count(*) FROM names GROUP BY 1 ORDER BY 1"
    ).fetchall()
    breaks["names.level"] = [1, 2, 3, 4]
    notes.append(f"# names.level: per level {dict(level_counts)}")
    print(f"{'names.level':36s} breaks [1, 2, 3, 4] counts {dict(level_counts)}")

    for collection, fields in MATCH_FIELDS.items():
        for field in fields:
            pairs, counts = match_branches(con, collection, field)
            key = f"{collection}.{field}"
            breaks[key] = pairs
            notes.append(
                f"# {key}: {len(pairs)} branch(es), counts {counts}"
            )
            print(f"{key:36s} {len(pairs)} branches, counts {counts}")
    con.close()

    body = [
        '"""Measured class breaks for every style. Generated; do not edit.',
        "",
        "Written by tools/make_breaks.py from the built data files. Rerun it",
        "after any rebuild, then rerun tools/make_styles.py. The counts in the",
        "comments are the features in each band at the time of generation, and",
        "tools/distributions.sql reruns the same queries.",
        '"""',
        "",
        *notes,
        "",
        "BREAKS = " + json.dumps(breaks, indent=4).replace("[\n            ", "[\n            "),
        "",
    ]
    OUT.write_text("\n".join(body))
    print(f"\nwritten to {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
