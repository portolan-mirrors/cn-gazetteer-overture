#!/usr/bin/env python3
"""Render each collection's thumbnail from its own default style.

    python3 tools/make_thumbnails.py            # all six
    python3 tools/make_thumbnails.py county     # one

The canonical way to build a Portolan thumbnail is to render
``styles/default.json`` server-side with chiitiler, through MapLibre GL Native,
against the collection's PMTiles. That needs a clone of chiitiler, which was
not available in the environment this catalog was built in, so this script
renders the same style's colours straight from the data instead: it parses the
``step`` or ``match`` expression out of ``styles/default.json`` and colours
every feature by it. The image a reader sees therefore agrees with the legend
the browser derives from the same expression, which is the property that
matters. It is not a MapLibre render: there is no basemap, and the line widths
are matplotlib's.

The polygon thumbnails are drawn from the **display** files, because loading
half a million full-resolution locality outlines into GeoPandas to make a
1200 px image is wasted work and the two files hold the same rows.

Framing. Each image is 3:2, matching the browser card. Six world maps in a
card grid would be six indistinguishable cards, so only the country level is
framed to the full extent and every other collection is framed on a region
that shows what that level actually looks like. The window for each is
recorded in WINDOWS below, chosen by eye from the rendered image, which is the
only way to choose a frame.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import geopandas as gpd  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from ovcommon import NAMES_PATH, display_path  # noqa: E402

CATALOG = Path(__file__).resolve().parents[1] / "catalog"

WINDOWS: dict[str, dict] = {
    "country": {
        "window": (-180.0, -90.0, 180.0, 90.0), "aspect": 2.0,
        "simplify": 0.05, "edge": 0.15,
        "label": "the whole world, the only full-extent frame",
    },
    "region": {
        "window": (-130.0, 22.0, -60.0, 56.0), "aspect": 1.5,
        "simplify": 0.02, "edge": 0.2,
        "label": "North America, where region means state or province",
    },
    "county": {
        "window": (-11.0, 35.0, 31.0, 61.0), "aspect": 1.5,
        "simplify": 0.01, "edge": 0.08,
        "label": "Europe, the densest county coverage",
    },
    "localadmin": {
        "window": (-5.5, 41.0, 9.5, 51.5), "aspect": 1.5,
        "simplify": 0.004, "edge": 0.05,
        "label": "France, one of the 19 countries with localadmin coverage",
    },
    "locality": {
        "window": (4.0, 50.0, 16.0, 55.0), "aspect": 1.5,
        "simplify": 0.001, "edge": 0.04,
        "label": "Germany and the Low Countries, dense locality coverage",
    },
    "names": {
        "window": (-20.0, -36.0, 55.0, 14.0), "aspect": 1.5,
        "simplify": 0.0, "edge": 0.0, "markersize": 0.8,
        "label": "Africa",
    },
}

WATER = "#f0f2f0"
WIDTH_PX = 1200
DPI = 100


def source(name: str) -> Path:
    return NAMES_PATH if name == "names" else display_path(name)


def eval_step(expr: list, value) -> str:
    """Evaluate a MapLibre step expression for one value."""
    fallback = expr[2]
    if value is None:
        return fallback
    colour = fallback
    for i in range(3, len(expr), 2):
        if value >= expr[i]:
            colour = expr[i + 1]
        else:
            break
    return colour


def eval_match(expr: list, value) -> str:
    """Evaluate a MapLibre match expression for one value."""
    pairs = expr[2:-1]
    for i in range(0, len(pairs), 2):
        if pairs[i] == value:
            return pairs[i + 1]
    return expr[-1]


def style_colours(style_path: Path):
    """The field, the colour function, and the layer kind of a default style."""
    style = json.loads(style_path.read_text())
    layer = next(
        layer for layer in style["layers"] if layer["type"] in {"fill", "circle"}
    )
    key = "fill-color" if layer["type"] == "fill" else "circle-color"
    expr = layer["paint"][key]
    getter = expr[1]
    field = getter[1][1] if getter[0] == "coalesce" else getter[1]
    if expr[0] == "step":
        return field, (lambda v: eval_step(expr, v)), layer["type"]
    if expr[0] == "match":
        return field, (lambda v: eval_match(expr, v)), layer["type"]
    raise SystemExit(f"{style_path}: default style is neither step nor match")


def frame(bounds, window, target: float):
    """A window at the target aspect, in degrees."""
    west, south, east, north = window or bounds
    cx, cy = (west + east) / 2, (south + north) / 2
    width, height = east - west, north - south
    if width / height < target:
        width = height * target
    else:
        height = width / target
    return (cx - width / 2, cy - height / 2, cx + width / 2, cy + height / 2)


def render(name: str) -> None:
    spec = WINDOWS[name]
    src = source(name)
    if not src.exists():
        sys.exit(f"missing {src}; run the build tools first")
    field, colour_of, kind = style_colours(
        CATALOG / name / "styles" / "default.json"
    )

    gdf = gpd.read_parquet(src, columns=[field, "geometry"])
    west, south, east, north = frame(
        tuple(gdf.total_bounds), spec["window"], spec["aspect"]
    )
    gdf = gdf.cx[west:east, south:north]
    if spec["simplify"]:
        gdf = gdf.set_geometry(gdf.geometry.simplify(spec["simplify"]))
    colours = [colour_of(v) for v in gdf[field]]

    height_px = int(WIDTH_PX / spec["aspect"])
    fig, ax = plt.subplots(figsize=(WIDTH_PX / DPI, height_px / DPI), dpi=DPI)
    fig.patch.set_facecolor(WATER)
    if kind == "fill":
        gdf.plot(
            ax=ax, color=colours, linewidth=spec["edge"],
            edgecolor="#2b2b2b", antialiased=True,
        )
    else:
        gdf.plot(
            ax=ax, color=colours, markersize=spec.get("markersize", 1.5),
            linewidth=0, alpha=0.9,
        )
    # After plotting: geopandas resets the axes background.
    ax.set_facecolor(WATER)
    ax.set_xlim(west, east)
    ax.set_ylim(south, north)
    ax.set_aspect("auto")
    ax.set_axis_off()
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)

    out = CATALOG / name / f"{name}.thumb.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=DPI, facecolor=fig.get_facecolor(), pad_inches=0)
    plt.close(fig)
    print(
        f"  {out.relative_to(CATALOG.parent)}: {out.stat().st_size:,} bytes, "
        f"{len(gdf):,} features, {spec['label']}, "
        f"bbox {west:.1f},{south:.1f},{east:.1f},{north:.1f}"
    )


def main(argv: list[str]) -> int:
    for name in argv or list(WINDOWS):
        if name not in WINDOWS:
            sys.exit(f"unknown collection {name}")
        render(name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
