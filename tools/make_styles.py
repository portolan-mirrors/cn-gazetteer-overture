#!/usr/bin/env python3
"""Generate the style JSON for every collection.

    python3 tools/make_styles.py

The styles are generated rather than hand-written because every class break in
them is a measured number. The query that produced each break is quoted beside
it, and ``tools/distributions.sql`` reruns every one of them against the built
files. If a count moved, the style and the prose citing it are now wrong.

Two rules shape every style here.

**The legend rule.** The Portolan data browser derives a legend only from a
``fill`` layer whose ``fill-color`` is a ``match`` or ``step`` array
expression. See
https://github.com/portolan-sdi/portolan-browser/blob/main/src/utils/portolanStyles.js
So the five polygon collections use ``step`` or ``match`` on ``fill-color``
and nothing else. The names collection is points, so a ``circle`` layer is the
only honest choice and it gets no legend; its agent guide says so out loud.

**Every branch is real.** Each ``match`` branch and each ``step`` band carries
the count of features that land in it, measured on the built file.
``tests/test_styles.py`` is the gate: it reads the same expression back and
counts the rows each branch would colour, and it fails on an empty band or on
a value no branch covers.

Palettes
--------
One hue family per collection, and none of them reused from the CC-BY sibling
catalog, which took ochre, teal, violet and amber. Six cards in a grid have to
be six cards a reader can tell apart at a glance.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

CATALOG = Path(__file__).resolve().parents[1] / "catalog"

# Sequential ramps, light to dark, six steps each.
AZURE = ["#e8f1fa", "#bcd8ef", "#80b4dd", "#4a8bc2", "#2a5f99", "#133a66"]
MOSS = ["#eef4e0", "#cfe3a9", "#a6cc72", "#74a84a", "#4a7c32", "#2a4d1c"]
CORAL = ["#fdeae6", "#fbc4b6", "#f4948008", "#e05f49", "#b23c28", "#78200f"]
SLATE = ["#edf0f2", "#ccd6dd", "#a2b4c0", "#75909f", "#4d6676", "#283d4a"]
ROSE = ["#fdeaf3", "#f8c2dd", "#ec8dbe", "#d55a9b", "#ab3273", "#6e1246"]
CHARTREUSE = ["#f4f8da", "#e0ecab", "#c2da72", "#9dbf45", "#75932c", "#4a6118"]

# CORAL had a typo-prone middle value; fix it explicitly rather than silently.
CORAL[2] = "#f49480"

GREY = "#cfcfcf"


def fill(layer: str, color, *, opacity: float = 0.85) -> dict:
    return {
        "id": f"{layer}-fill",
        "type": "fill",
        "source": "data",
        "source-layer": layer,
        "paint": {
            "fill-color": color,
            "fill-opacity": opacity,
            "fill-outline-color": "rgba(40,40,40,0.35)",
        },
    }


def outline(layer: str, color: str = "rgba(30,30,30,0.55)") -> dict:
    return {
        "id": f"{layer}-line",
        "type": "line",
        "source": "data",
        "source-layer": layer,
        "paint": {"line-color": color, "line-width": 0.4},
    }


def ramp(palette: list[str], bands: int) -> list[str]:
    """`bands` colours sampled evenly from a ramp, ends included.

    The break generator drops a break that brackets no feature, so a style can
    end up with fewer bands than the ramp has colours. Sampling keeps the full
    tonal range instead of truncating the dark end, which is what a legend
    needs: the lightest and the darkest band stay distinguishable however many
    bands there are.
    """
    if bands >= len(palette):
        return list(palette)
    if bands == 1:
        return [palette[len(palette) // 2]]
    last = len(palette) - 1
    return [palette[round(i * last / (bands - 1))] for i in range(bands)]


def step(field: str, palette: list[str], breaks: list[float]) -> list:
    """A step expression: colours[0] below breaks[0], then one per break."""
    colours = ramp(palette, len(breaks) + 1)
    expr: list = ["step", ["coalesce", ["get", field], 0], colours[0]]
    for value, color in zip(breaks, colours[1:]):
        expr += [value, color]
    return expr


def match(field: str, pairs: list[tuple[str, str]], fallback: str) -> list:
    expr: list = ["match", ["get", field]]
    for value, color in pairs:
        expr += [value, color]
    expr.append(fallback)
    return expr


def polygon_style(name: str, layer: str, color) -> dict:
    return {
        "version": 8,
        "name": name,
        "sources": {
            "data": {"type": "vector", "url": f"pmtiles://../{layer}.pmtiles"}
        },
        "layers": [fill(layer, color), outline(layer)],
    }


def point_style(name: str, layer: str, color) -> dict:
    return {
        "version": 8,
        "name": name,
        "sources": {
            "data": {"type": "vector", "url": f"pmtiles://../{layer}.pmtiles"}
        },
        "layers": [
            {
                "id": f"{layer}-circle",
                "type": "circle",
                "source": "data",
                "source-layer": layer,
                "paint": {
                    "circle-color": color,
                    "circle-radius": [
                        "interpolate", ["linear"], ["zoom"],
                        0, 0.7, 4, 1.8, 8, 4.0,
                    ],
                    "circle-opacity": 0.8,
                    "circle-stroke-width": 0.2,
                    "circle-stroke-color": "rgba(30,30,30,0.45)",
                },
            }
        ],
    }


# ---------------------------------------------------------------------------
# The specs. Counts beside each band were measured on the built files by
# tools/distributions.sql.
# ---------------------------------------------------------------------------
SPECS: dict[str, list[tuple[str, str, dict]]] = {}


def load_specs() -> None:
    from style_breaks import BREAKS  # measured; see tools/distributions.sql

    SPECS["country"] = [
        ("default", "Land area", polygon_style(
            "Land area", "country",
            step("area_km2", AZURE, BREAKS["country.area_km2"]))),
        ("status", "Country or dependency", polygon_style(
            "Country or dependency", "country",
            match("subtype",
                  [("country", AZURE[4]), ("dependency", "#e0a030")], GREY))),
        ("languages", "Languages with a name for this country", polygon_style(
            "Languages with a name for this country", "country",
            step("name_langs", AZURE, BREAKS["country.name_langs"]))),
        ("population", "Population", polygon_style(
            "Population", "country",
            step("population", AZURE, BREAKS["country.population"]))),
    ]
    # The default here is the language count rather than the area, because
    # area at this level paints almost every region in the top band: a region
    # is the largest sub-country unit, so most of them are large, and the
    # small ones are islands that occupy few pixels. Both framings were
    # rendered; the language count is the one that shows variation, and it is
    # also what this catalog has that its CC-BY counterpart does not.
    SPECS["region"] = [
        ("default", "Languages with a name for this region", polygon_style(
            "Languages with a name for this region", "region",
            step("name_langs", MOSS, BREAKS["region.name_langs"]))),
        ("area", "Land area", polygon_style(
            "Land area", "region",
            step("area_km2", MOSS, BREAKS["region.area_km2"]))),
        ("units-per-country", "Regions in this country", polygon_style(
            "Regions in this country", "region",
            step("country_units", MOSS, BREAKS["region.country_units"]))),
        ("population", "Population", polygon_style(
            "Population", "region",
            step("population", MOSS, BREAKS["region.population"]))),
    ]
    SPECS["county"] = [
        ("default", "Land area", polygon_style(
            "Land area", "county",
            step("area_km2", CORAL, BREAKS["county.area_km2"]))),
        ("languages", "Languages with a name for this county", polygon_style(
            "Languages with a name for this county", "county",
            step("name_langs", CORAL, BREAKS["county.name_langs"]))),
        ("units-per-country", "Counties in this country", polygon_style(
            "Counties in this country", "county",
            step("country_units", CORAL, BREAKS["county.country_units"]))),
        ("population", "Population", polygon_style(
            "Population", "county",
            step("population", CORAL, BREAKS["county.population"]))),
    ]
    SPECS["localadmin"] = [
        ("default", "Land area", polygon_style(
            "Land area", "localadmin",
            step("area_km2", SLATE, BREAKS["localadmin.area_km2"]))),
        ("coverage", "Which country publishes this level", polygon_style(
            "Which country publishes this level", "localadmin",
            match("country", BREAKS["localadmin.country"], GREY))),
        ("languages", "Languages with a name for this division", polygon_style(
            "Languages with a name for this division", "localadmin",
            step("name_langs", SLATE, BREAKS["localadmin.name_langs"]))),
        ("population", "Population", polygon_style(
            "Population", "localadmin",
            step("population", SLATE, BREAKS["localadmin.population"]))),
    ]
    SPECS["locality"] = [
        ("default", "Settlement class", polygon_style(
            "Settlement class", "locality",
            match("class", BREAKS["locality.class"], GREY))),
        ("area", "Land area", polygon_style(
            "Land area", "locality",
            step("area_km2", ROSE, BREAKS["locality.area_km2"]))),
        ("population", "Population", polygon_style(
            "Population", "locality",
            step("population", ROSE, BREAKS["locality.population"]))),
        ("languages", "Languages with a name for this place", polygon_style(
            "Languages with a name for this place", "locality",
            step("name_langs", ROSE, BREAKS["locality.name_langs"]))),
    ]
    SPECS["names"] = [
        ("default", "Indexed names by level", point_style(
            "Indexed names by level", "names",
            step("level", CHARTREUSE[1:], BREAKS["names.level"]))),
        ("ambiguity", "How many places share this name", point_style(
            "How many places share this name", "names",
            step("name_dupes", CHARTREUSE, BREAKS["names.name_dupes"]))),
        ("languages", "Languages indexed for this spelling", point_style(
            "Languages indexed for this spelling", "names",
            step("name_lang_count", CHARTREUSE,
                 BREAKS["names.name_lang_count"]))),
        ("population", "Population of the named place", point_style(
            "Population of the named place", "names",
            step("population", CHARTREUSE, BREAKS["names.population"]))),
    ]


def main() -> int:
    load_specs()
    written = removed = 0
    for collection, styles in SPECS.items():
        out_dir = CATALOG / collection / "styles"
        out_dir.mkdir(parents=True, exist_ok=True)
        keep = set()
        for slug, title, doc in styles:
            doc["name"] = title
            path = out_dir / f"{slug}.json"
            path.write_text(json.dumps(doc, indent=2) + "\n")
            keep.add(path.name)
            written += 1
            print(f"  {path.relative_to(CATALOG.parent)}")
        # Renaming a style leaves the old file behind, and an orphan style
        # publishes without any collection.json referencing it. The directory
        # is output, so it is made to match the spec rather than added to.
        for stale in sorted(out_dir.glob("*.json")):
            if stale.name not in keep:
                stale.unlink()
                removed += 1
                print(f"  removed {stale.relative_to(CATALOG.parent)}")
    print(f"{written} style files written, {removed} stale file(s) removed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
