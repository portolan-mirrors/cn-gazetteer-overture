#!/usr/bin/env python3
"""Build one PMTiles archive per collection, for the data browser.

    python3 tools/build_pmtiles.py              # all six
    python3 tools/build_pmtiles.py locality     # one target

``ogr2ogr`` streams the published GeoParquet to newline-delimited GeoJSON on
stdout and tippecanoe reads it from a pipe, so no intermediate GeoJSON is
written. The styles read the attributes carried here, so the ``-select`` list
in each target and the expressions in ``tools/make_styles.py`` have to stay in
step; ``tests/test_styles.py`` is the gate that catches a drift.

Maximum zoom is set per collection rather than globally. A country outline is
legible long before a village boundary is, and every extra zoom level on the
locality archive costs tiles nobody opens.

Where the geometry comes from
-----------------------------
The five polygon archives are tiled from the **display** geometry, not the
full-resolution one. Tippecanoe simplifies per zoom level anyway, and the
display geometry is already a topology-preserving simplification of the same
rings; feeding it the full-resolution Overture coastline instead means
streaming gigabytes of WKB to produce the same tiles. The display geometry is
an outward-buffered superset of the truth, so a tile boundary sits a fraction
of a tolerance outside the real one, which at these zoom levels is well under
a pixel. The GeoParquet asset is what a consumer uses when that matters, and
every collection README says so.

The attributes come from the **full** file, because the display file is a
geometry companion and carries only what identifies a row. So this step joins
the two on ``division_id`` into a scratch file under the staging work
directory, tiles that, and deletes it. The scratch file is never published.
"""
from __future__ import annotations

import subprocess
import sys

from ovcommon import (
    COLLECTIONS,
    NAMES_PATH,
    WORK,
    boundary_path,
    connect,
    display_path,
    human,
    pmtiles_path,
    run,
)

# Attributes carried into the tiles. Only what a style or a popup reads, and
# only where the collection has the column: every extra field is repeated in
# every tile. tools/make_styles.py reads these same names, and
# tests/test_styles.py is the gate that catches a drift between the two.
POLYGON_FIELDS = [
    "division_id",
    "name",
    "subtype",
    "country",
    "class",
    "local_type",
    "parent_name",
    "country_units",
    "population",
    "name_langs",
    "area_km2",
]

MAX_ZOOM = {
    "country": 6,
    "region": 8,
    "county": 9,
    "localadmin": 10,
    "locality": 11,
}

# Polygon tiling. --detect-shared-borders keeps a shared edge between two
# neighbouring divisions simplified identically, so the coverage stays seamless
# instead of opening hairline gaps as it simplifies.
# --coalesce-smallest-as-needed merges the smallest features rather than
# dropping them when a tile runs over the size limit, which keeps the fill
# continuous. --drop-densest-as-needed is added for the locality archive,
# where half a million small polygons would otherwise blow the tile budget in
# dense countries at low zoom.
POLYGON_ARGS = [
    "--detect-shared-borders",
    "--coalesce-smallest-as-needed",
    "--simplification=4",
    "--simplify-only-low-zooms",
]
DENSE_ARGS = ["--drop-densest-as-needed", "--maximum-tile-bytes=400000"]

NAMES_FIELDS = [
    "name",
    "level",
    "subtype",
    "country",
    "name_dupes",
    "name_lang_count",
    "population",
    "has_boundary",
]
NAMES_MAX_ZOOM = 8


def tile(src, out, *, layer: str, name: str, maxzoom: int,
         fields: list[str], extra: list[str]) -> None:
    ogr = [
        "ogr2ogr", "-f", "GeoJSONSeq", "/vsistdout/", str(src),
        "-select", ",".join(fields),
    ]
    tip = [
        "tippecanoe", "-o", str(out), "-f", "-q",
        "-l", layer,
        "-n", name,
        "-z", str(maxzoom), "-Z", "0",
        *extra,
    ]
    print(f"  $ {' '.join(ogr)} | {' '.join(tip)}", flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    with subprocess.Popen(ogr, stdout=subprocess.PIPE) as reader:
        subprocess.run(tip, stdin=reader.stdout, check=True)
        reader.stdout.close()
        if reader.wait() != 0:
            raise SystemExit(f"{out.name}: ogr2ogr failed")
    print(f"  {out.name}: {human(out.stat().st_size)}")
    run(["pmtiles", "show", str(out)])


def build(target: str) -> None:
    print(f"{target}: tiling")
    if target == "names":
        if not NAMES_PATH.exists():
            sys.exit(f"missing {NAMES_PATH}; run tools/build_names.py first")
        # One point per row, and an alt-name row carries no point, so the
        # archive holds exactly the primary rows: one marker per division.
        tile(
            NAMES_PATH,
            pmtiles_path("names"),
            layer="names",
            name="Overture divisions name index",
            maxzoom=NAMES_MAX_ZOOM,
            fields=NAMES_FIELDS,
            extra=["-r1", "--drop-densest-as-needed", "--maximum-tile-bytes=400000"],
        )
        return

    full, disp = boundary_path(target), display_path(target)
    for path in (full, disp):
        if not path.exists():
            sys.exit(f"missing {path}; run the boundary and display builds first")

    con = connect()
    present = set(
        con.sql(f"SELECT * FROM read_parquet('{full.as_posix()}') LIMIT 0").columns
    )
    fields = [f for f in POLYGON_FIELDS if f in present]
    scratch = WORK / f"{target}.tiles.parquet"
    scratch.unlink(missing_ok=True)
    cols = ", ".join(f"f.{f}" for f in fields)
    con.execute(
        f"""COPY (
              SELECT {cols}, d.geometry
              FROM read_parquet('{full.as_posix()}') f
              JOIN read_parquet('{disp.as_posix()}') d USING (division_id)
            ) TO '{scratch.as_posix()}'
            (FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 3)"""
    )
    rows = con.execute(
        f"SELECT count(*) FROM read_parquet('{scratch.as_posix()}')"
    ).fetchone()[0]
    con.close()
    print(f"  joined {rows:,} rows with {len(fields)} attribute(s) for tiling")

    extra = list(POLYGON_ARGS)
    if target in ("locality", "localadmin", "county"):
        extra += DENSE_ARGS
    try:
        tile(
            scratch,
            pmtiles_path(target),
            layer=target,
            name=f"Overture divisions {target}",
            maxzoom=MAX_ZOOM[target],
            fields=fields,
            extra=extra,
        )
    finally:
        scratch.unlink(missing_ok=True)


def main(argv: list[str]) -> int:
    targets = list(COLLECTIONS) + ["names"]
    for target in argv or targets:
        if target not in targets:
            sys.exit(f"unknown target {target}; one of {', '.join(targets)}")
        build(target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
