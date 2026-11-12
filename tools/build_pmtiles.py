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
The five polygon archives are tiled from the **display** file, not the
full-resolution one. Tippecanoe simplifies per zoom level anyway, and the
display geometry is already a topology-preserving simplification of the same
rings; feeding it the full-resolution Overture coastline instead means
streaming gigabytes of WKB to produce the same tiles. The display geometry is
an outward-buffered superset of the truth, so a tile boundary sits a fraction
of a tolerance outside the real one, which at these zoom levels is well under
a pixel. The GeoParquet asset is what a consumer uses when that matters, and
every collection README says so.
"""
from __future__ import annotations

import subprocess
import sys

from ovcommon import (
    COLLECTIONS,
    NAMES_PATH,
    display_path,
    human,
    pmtiles_path,
    run,
)

# Attributes carried into the tiles, per collection. Only what a style or a
# popup reads: every extra field is repeated in every tile.
POLYGON_FIELDS = [
    "division_id",
    "name",
    "subtype",
    "country",
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

    src = display_path(target)
    if not src.exists():
        sys.exit(f"missing {src}; run tools/build_display.py first")
    extra = list(POLYGON_ARGS)
    if target in ("locality", "localadmin", "county"):
        extra += DENSE_ARGS
    tile(
        src,
        pmtiles_path(target),
        layer=target,
        name=f"Overture divisions {target}",
        maxzoom=MAX_ZOOM[target],
        fields=POLYGON_FIELDS,
        extra=extra,
    )


def main(argv: list[str]) -> int:
    targets = list(COLLECTIONS) + ["names"]
    for target in argv or targets:
        if target not in targets:
            sys.exit(f"unknown target {target}; one of {', '.join(targets)}")
        build(target)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
