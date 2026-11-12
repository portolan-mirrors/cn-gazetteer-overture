#!/usr/bin/env python3
"""The search index's pointers into the boundary files have to be right.

This is the catalog's load-bearing claim. ``geometry_ref`` names a file, a row
group and a row, and a consumer range-reads that row group and takes that row.
If the pointer is stale, the consumer gets **another division's polygon** and
nothing looks wrong: the geometry is valid, the bbox is plausible, and the map
flies somewhere. No schema validator catches it.

Four things are checked, all of them against the built files:

1. Every ``geometry_ref`` resolves to a row whose ``division_id`` equals the
   index row's ``feature_id``, in the full-resolution file.
2. The same row offset in the display companion holds the same
   ``division_id``, which is what makes one pointer valid against both.
3. ``row // row_group_rows`` equals the published ``row_group``.
4. The ``cnmw:catalog_version`` in the manifest, in the index's footer and in
   every boundary and display footer are the same string. That is the version
   pin a consumer checks before it trusts the pointer at all.

It needs the built data, which lives outside git. When the staging tree is
absent it skips, which is what happens in CI. Run it locally after any
rebuild:

    python3 tests/test_index_refs.py
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

try:
    import pyarrow.compute as pc
    import pyarrow.parquet as pq
except ImportError:  # pragma: no cover
    print("skip: pyarrow is not installed")
    raise SystemExit(0)

from ovcommon import (  # noqa: E402
    CATALOG_VERSION,
    CNMW_VERSION_KEY,
    NAMES_PATH,
    ROW_GROUP_ROWS,
    boundary_path,
    display_path,
)

MANIFEST = ROOT / "catalog" / "names" / "index.json"
# Sampling rather than exhaustive: resolving all 620,734 pointers means
# reading every division_id column in the catalog, which is minutes. A
# systematic fault shows up in the first handful of rows, and the seed is
# fixed so a failure is reproducible.
SAMPLE = 2000
SEED = 7


def footer_version(path: Path) -> str | None:
    meta = pq.ParquetFile(path).schema_arrow.metadata or {}
    value = meta.get(CNMW_VERSION_KEY.encode())
    return value.decode() if value else None


def main() -> int:
    if not NAMES_PATH.exists():
        print(f"skip: no built index at {NAMES_PATH}; run the build tools first")
        return 0
    if not MANIFEST.exists():
        print(f"error: {MANIFEST} is missing; run tools/build_names.py")
        return 1

    errors: list[str] = []
    manifest = json.loads(MANIFEST.read_text())

    # 4. The version pin, first, because nothing below means anything without
    #    it. Checked exhaustively: there are only eleven files.
    versions = {"manifest": manifest["catalog_version"],
                str(NAMES_PATH.name): footer_version(NAMES_PATH)}
    for collection in ROW_GROUP_ROWS:
        for path in (boundary_path(collection), display_path(collection)):
            if not path.exists():
                print(f"skip: {path} is not built")
                return 0
            versions[path.name] = footer_version(path)
    disagree = {k: v for k, v in versions.items() if v != CATALOG_VERSION}
    if disagree:
        errors.append(
            "catalog_version disagrees: "
            + ", ".join(f"{k}={v!r}" for k, v in disagree.items())
            + f" (expected {CATALOG_VERSION!r})"
        )
    else:
        print(f"OK   catalog_version {CATALOG_VERSION} in {len(versions)} places")

    table = pq.read_table(
        NAMES_PATH, columns=["feature_id", "name", "alt_of", "geometry_ref"]
    )
    refs = table.filter(pc.invert(pc.is_null(table.column("geometry_ref"))))
    on_alt = refs.num_rows - pc.sum(pc.is_null(refs.column("alt_of"))).as_py()
    if on_alt:
        errors.append(
            f"{on_alt:,} alternative-name rows carry a geometry_ref; it "
            "belongs on the primary row only"
        )
    print(f"OK   {refs.num_rows:,} geometry_ref(s), all on primary rows")

    rows = refs.to_pylist()
    random.seed(SEED)
    sample = random.sample(rows, min(SAMPLE, len(rows)))
    by_file: dict[str, list[dict]] = {}
    for row in sample:
        by_file.setdefault(row["geometry_ref"]["file"], []).append(row)

    checked = 0
    for filename, items in sorted(by_file.items()):
        collection = filename.removeprefix("overture_").removesuffix(".parquet")
        if collection not in ROW_GROUP_ROWS:
            errors.append(f"geometry_ref names an unknown file {filename!r}")
            continue
        full = pq.read_table(
            boundary_path(collection), columns=["division_id"]
        ).column("division_id").to_pylist()
        disp = pq.read_table(
            display_path(collection), columns=["division_id"]
        ).column("division_id").to_pylist()
        group_rows = ROW_GROUP_ROWS[collection]
        for row in items:
            ref = row["geometry_ref"]
            index, group = ref["row"], ref["row_group"]
            if not 0 <= index < len(full):
                errors.append(f"{collection}: row {index} is out of range")
                continue
            if full[index] != row["feature_id"]:
                errors.append(
                    f"{collection}: geometry_ref for {row['name']!r} points at "
                    f"row {index}, which holds {full[index]} and not "
                    f"{row['feature_id']}"
                )
            if disp[index] != row["feature_id"]:
                errors.append(
                    f"{collection}: the display file holds {disp[index]} at "
                    f"row {index}, where the full file holds "
                    f"{row['feature_id']}"
                )
            if index // group_rows != group:
                errors.append(
                    f"{collection}: row {index} is in row group "
                    f"{index // group_rows}, not the published {group}"
                )
            checked += 1
        print(f"OK   {collection}: {len(items):,} pointer(s) resolve")

    if errors:
        print("\n".join(f"error  {e}" for e in errors))
        return 1
    print(
        f"OK: {checked:,} sampled geometry_ref(s) resolve to the right "
        f"division in both the full and the display file"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
