#!/usr/bin/env python3
"""Every style class has to exist in the data.

A legend listing a category the data does not hold, or a band no feature falls
into, is the most common visible defect in a new catalog, and no schema
validator catches it. The browser derives its legend from the `match` or `step`
expression in a style's `fill-color`, so this gate reads the same expression
and counts the rows each branch would colour.

It needs the built data, which lives outside git. When the staging tree is
absent it skips, which is what happens in CI. Run it locally after any rebuild:

    python3 tests/test_styles.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog"
sys.path.insert(0, str(ROOT / "tools"))

try:
    import duckdb
except ImportError:  # pragma: no cover
    print("skip: duckdb is not installed")
    raise SystemExit(0)

from ovcommon import (  # noqa: E402
    COLLECTIONS,
    NAMES_PATH,
    PUBLISH,
    boundary_path,
)

# A style is checked against the full-resolution boundary file, not against the
# display file the tiles are built from. The two hold the same rows with the
# same attributes, and the full file is the one the collection documents.
SOURCES = {c: boundary_path(c) for c in COLLECTIONS}
SOURCES["names"] = NAMES_PATH


def colour_expression(style_path: Path):
    """The field and the paint expression of a style's first coloured layer."""
    style = json.loads(style_path.read_text())
    layer = next(
        layer for layer in style["layers"]
        if layer["type"] in {"fill", "circle"}
    )
    key = "fill-color" if layer["type"] == "fill" else "circle-color"
    expr = layer["paint"][key]
    getter = expr[1]
    field = getter[1][1] if getter[0] == "coalesce" else getter[1]
    return field, expr


def check(con, collection: str, src: str, style_path: Path) -> list[str]:
    field, expr = colour_expression(style_path)
    name = f"{collection}/{style_path.name}"
    errors = []

    if expr[0] == "match":
        branches = list(expr[2:-1][0::2])
        present = {
            row[0] for row in con.execute(
                f'SELECT DISTINCT "{field}" FROM read_parquet(\'{src}\')'
            ).fetchall()
        }
        missing = [b for b in branches if b not in present]
        # A NULL is absence, not a category, and the fallback colour is the
        # right rendering for it. Overture leaves `class` null on every
        # division that is not a locality and on the localities no source
        # classed, so a match on `class` has to be allowed a fallback. The
        # count still gets printed, because a fallback that swallows most of
        # the data is a style that says nothing.
        nulls = con.execute(
            f'SELECT count(*) FROM read_parquet(\'{src}\') '
            f'WHERE "{field}" IS NULL'
        ).fetchone()[0]
        unmatched = [v for v in present if v is not None and v not in branches]
        if missing:
            errors.append(
                f"{name}: match on {field} lists {missing}, "
                "which no row holds"
            )
        if unmatched:
            errors.append(
                f"{name}: {field} holds {unmatched}, which no branch covers; "
                "those rows render in the fallback colour"
            )
        print(
            f"OK   {name}: match {field}, {len(branches)} branch(es), "
            f"{nulls:,} null row(s) in the fallback"
        )
        return errors

    if expr[0] != "step":
        return [f"{name}: {expr[0]} produces no legend; use match or step"]

    edges = [None, *expr[3::2], None]
    counts = []
    for lo, hi in zip(edges, edges[1:]):
        clauses = []
        if lo is not None:
            clauses.append(f'"{field}" >= {lo}')
        if hi is not None:
            clauses.append(f'"{field}" < {hi}')
        where = " AND ".join(clauses) or "TRUE"
        counts.append(
            con.execute(
                f"SELECT count(*) FROM read_parquet('{src}') WHERE {where}"
            ).fetchone()[0]
        )
    empty = [i for i, n in enumerate(counts) if n == 0]
    if empty:
        errors.append(
            f"{name}: step on {field} has empty band(s) at {empty}: {counts}"
        )
    print(f"OK   {name}: step {field}, bands {counts}")
    return errors


def main() -> int:
    if not PUBLISH.is_dir():
        print(f"skip: no staging tree at {PUBLISH}; run the build tools first")
        return 0

    con = duckdb.connect()
    errors: list[str] = []
    checked = 0
    for collection, src in SOURCES.items():
        if not src.exists():
            print(f"skip: {src} is not built")
            return 0
        for style_path in sorted((CATALOG / collection / "styles").glob("*.json")):
            errors += check(con, collection, src.as_posix(), style_path)
            checked += 1
    con.close()

    if errors:
        print("\n".join(f"error  {e}" for e in errors))
        return 1
    print(f"OK: every class in {checked} style(s) is populated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
