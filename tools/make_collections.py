#!/usr/bin/env python3
"""Generate every collection.json from the built data files.

    python3 tools/make_collections.py

Row counts, bounding boxes, row group counts, asset sizes and checksums are
read out of the files in the staging tree rather than typed in, because a
number typed in is a number that goes stale on the next rebuild without
anything noticing. The prose, the keywords and the column descriptions live in
the spec below, which is the one place to edit them.

Run the four build tools first: ``stage_source``, ``build_boundaries``,
``build_display``, ``build_names``, then ``build_pmtiles``,
``make_styles`` and ``make_thumbnails``.

Provenance of the column descriptions
-------------------------------------
Every ``table:columns`` entry is one of three tiers, and the tier is stated in
the text.

* **Attested** columns are quoted or paraphrased from Overture's published
  JSON Schema for the divisions theme, at
  https://github.com/OvertureMaps/schema/blob/main/schema/divisions/, which is
  what the reference pages under docs.overturemaps.org render. ``id``,
  ``division_id``, ``subtype``, ``class``, ``country``, ``region``,
  ``admin_level``, ``local_type``, ``parent_division_id``, ``population``,
  ``wikidata``, ``is_land`` and ``names`` all come from there.
* **Derived** columns are computed by this repository's tools, and the query
  is in the tool named in the description.
* Nothing here is guessed. Where Overture documents no meaning, the
  description says so.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

from ovcommon import (
    AZURE_HTTPS_THEME,
    CATALOG_VERSION,
    COLLECTIONS,
    COLLECTION_LEVEL,
    DOCS_ATTRIBUTION,
    DOCS_DIVISIONS,
    DOCS_SCHEMA_DIVISION,
    DOCS_SCHEMA_DIVISION_AREA,
    EXTRACTION_DATE,
    NAMES_PATH,
    NAMES_ROW_GROUP_ROWS,
    PUBLISH,
    RELEASE,
    RELEASE_NOTES,
    ROW_GROUP_ROWS,
    S3_HTTPS_THEME,
    S3_THEME,
    UPSTREAM_BYTES,
    UPSTREAM_FILES,
    WORK,
    boundary_path,
    display_path,
    pmtiles_path,
)
from build_pmtiles import MAX_ZOOM, NAMES_MAX_ZOOM
from build_prominent import (
    OUT as PROMINENT_PATH,
    ROW_GROUP_ROWS as PROMINENT_ROW_GROUP_ROWS,
)

PROMINENT_NAME = PROMINENT_PATH.name

REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "catalog"

LICENSE = "ODbL-1.0"
LICENSE_URL = "https://opendatacommons.org/licenses/odbl/"
SIBLING_SOURCECOOP = "https://source.coop/portolan-mirrors/geoboundaries-catalog"
SIBLING_REPO = "https://github.com/portolan-mirrors/geoboundaries-catalog"

PROVIDERS = [
    {
        "name": "Overture Maps Foundation",
        "description": (
            "Produces the divisions theme by conflating OpenStreetMap with "
            "geoBoundaries, Esri Community Maps and Land Information New "
            "Zealand, and publishes it under ODbL with a stable GERS "
            "identifier on every feature."
        ),
        "roles": ["producer", "licensor"],
        "url": "https://overturemaps.org/",
    },
    {
        "name": "OpenStreetMap contributors",
        "description": (
            "The primary source of the divisions theme, and the reason the "
            "theme carries ODbL share-alike."
        ),
        "roles": ["producer", "licensor"],
        "url": "https://www.openstreetmap.org/copyright",
    },
    {
        "name": "Portolan Mirrors",
        "description": (
            "Republishes the Overture divisions release as cloud-native "
            "GeoParquet, a display-simplified companion, PMTiles and a "
            "multilingual name search index. Adds no divisions and changes no "
            "attribute values."
        ),
        "roles": ["processor", "host"],
        "url": "https://github.com/portolan-mirrors/cn-gazetteer-overture",
    },
]

ATTRIBUTION_SENTENCE = (
    "Attribution is required and share-alike applies: see the "
    "[collection README](README.md)."
)

# ---------------------------------------------------------------------------
# Shared column documentation for the five boundary collections
# ---------------------------------------------------------------------------
ID = {
    "name": "id",
    "type": "string",
    "description": (
        "Attested. The GERS identifier of the *division area* feature, the "
        "polygon row Overture published. Globally unique and stable across "
        "releases while the feature keeps its identity. This is not the key "
        "the search index points at; `division_id` is. Overture's schema for "
        f"the property is at [division_area]({DOCS_SCHEMA_DIVISION_AREA})."
    ),
}
DIVISION_ID = {
    "name": "division_id",
    "type": "string",
    "description": (
        "Attested. The GERS identifier of the division this polygon belongs "
        "to, which Overture defines as 'Division ID of the division this area "
        "belongs to'. **This is the join key**: it is what the names "
        "collection publishes as `feature_id`, and it is unique in this file "
        "because the build keeps only the one `class = 'land'` polygon per "
        "division. Join on this, never on `id`."
    ),
}
NAME = {
    "name": "name",
    "type": "string",
    "description": (
        "Attested. `names.primary` of the division, byte for byte as Overture "
        "published it. Overture's own display name, in whichever language it "
        "considers primary for that place, which is usually but not always "
        "the local one. The names collection carries this string plus every "
        "alternative spelling Overture lists, each folded for searching."
    ),
}


def subtype_column(composition: str) -> dict:
    return {
        "name": "subtype",
        "type": "string",
        "description": (
            "Attested. Overture's placetype for the division. In this file: "
            f"{composition}. The full list and the meaning of each value are "
            f"in the [divisions guide]({DOCS_DIVISIONS})."
        ),
    }


COUNTRY = {
    "name": "country",
    "type": "string",
    "description": (
        "Derived. ISO 3166-1 **alpha-3**, mapped from Overture's alpha-2 "
        "`country` property through the official ISO 3166-1 table packaged "
        "with pycountry. The mapping exists so that this catalog and the "
        f"CC-BY [geoBoundaries mirror]({SIBLING_SOURCECOOP}) can be filtered "
        "with one code system. Overture's own alpha-2 value is kept unchanged "
        "in `country_iso2`; where Overture uses a synthetic code with no "
        "alpha-3 equivalent, that code is carried through here as well."
    ),
}
COUNTRY_ISO2 = {
    "name": "country_iso2",
    "type": "string",
    "description": (
        "Attested. Overture's `country` property, unchanged: the ISO 3166-1 "
        "alpha-2 code of 'the country or country-like entity that this "
        "division represents or belongs to'. For a division that has no "
        "country code of its own, Overture fills it from the first ancestor "
        "that has one, so a locality in Puerto Rico carries PR."
    ),
}
REGION = {
    "name": "region",
    "type": "string",
    "description": (
        "Attested. The ISO 3166-2 principal subdivision code of 'the "
        "subdivision-like entity this division represents or belongs to', "
        "inherited from the nearest ancestor that has one. Omitted for a "
        "country. Overture's example: New York City carries US-NY."
    ),
}


def class_column(distribution: str) -> dict:
    return {
        "name": "class",
        "type": "string",
        "description": (
            "Attested. Overture's settlement class, one of `megacity`, "
            "`city`, `town`, `village` or `hamlet`, each defined by relative "
            f"size in the [division schema]({DOCS_SCHEMA_DIVISION}). "
            f"In this file: {distribution}. It is only populated for "
            "localities; every other subtype leaves it null."
        ),
    }


LOCAL_TYPE = {
    "name": "local_type",
    "type": "string",
    "description": (
        "Derived from an attested column. Overture publishes `local_type` as "
        "a map of language code to the locally used word for the subtype, "
        "because, in its own example, Quebec has subtype `region` but is "
        "locally a province and Yukon is a territory. This file flattens the "
        "map to one string: the entry keyed `local` where there is one, "
        "otherwise the first entry. Use the Overture release itself if you "
        "need every localized form."
    ),
}
ADMIN_LEVEL = {
    "name": "admin_level",
    "type": "int32",
    "description": (
        "Attested. Overture's administrative level, which it requires only "
        "for country, dependency, macroregion, region, macrocounty and "
        "county, and which it says generally aligns with the OpenStreetMap "
        "`admin_level` tag. Null for localadmin and locality. It is not the "
        "same number as the `level` the names collection publishes; that one "
        "is this catalog's own 0-to-4 mapping of the subtype."
    ),
}
PARENT_DIVISION_ID = {
    "name": "parent_division_id",
    "type": "string",
    "description": (
        "Attested. The GERS id of the division's parent, 'as seen from the "
        "default political perspective'. Not present on a country. Join it to "
        "`division_id` in the collection one level up, which is what "
        "`parent_name` below was built from."
    ),
}
PARENT_NAME = {
    "name": "parent_name",
    "type": "string",
    "description": (
        "Derived. `names.primary` of the parent division, looked up through "
        "`parent_division_id` in a self-join over the whole Overture "
        "`type=division` release, so it resolves even when the parent sits in "
        "a subtype this catalog does not carry. It is what lets a result list "
        "say which of the many places called Springfield is meant."
    ),
}
PARENT_SUBTYPE = {
    "name": "parent_subtype",
    "type": "string",
    "description": (
        "Derived. The parent division's subtype, from the same self-join. "
        "A locality's parent is usually a localadmin or a county, and knowing "
        "which tells a reader how far up `parent_name` reaches."
    ),
}
COUNTRY_UNITS = {
    "name": "country_units",
    "type": "int32",
    "description": (
        "Derived. How many rows of this file share this row's `country`, so "
        "how finely Overture divides that country at this level. Counted over "
        "this file only, by a window function in tools/build_boundaries.py."
    ),
}
POPULATION = {
    "name": "population",
    "type": "int32",
    "description": (
        "Attested. 'Population of the division', as Overture publishes it. "
        "Sparse: Overture carries it where a source supplied one and leaves "
        "it null otherwise, and it states no vintage per value, so treat it "
        "as a relevance weight rather than as a census figure."
    ),
}
WIKIDATA = {
    "name": "wikidata",
    "type": "string",
    "description": (
        "Attested. The division's Wikidata QID where Overture has one. Useful "
        "as a second identifier to join this catalog to anything keyed on "
        "Wikidata."
    ),
}
PROMINENCE = {
    "name": "prominence",
    "type": "int32",
    "description": (
        "Attested. `cartography.prominence` from the division row: Overture's "
        "own ranking of how important a place is to show on a map. Overture "
        "documents it as cartographic guidance rather than as a measured "
        "quantity, so it is a tie-break for a search result list, not a "
        "statistic. Measured on this release, Overture populates it on all "
        "3,508,156 localities and on nothing else, so it appears only in the "
        "locality collection and on level-4 rows of the search index. The "
        "sibling `cartography` fields `min_zoom`, `max_zoom` and `sort_key` "
        "are null on every division in the release and are not carried."
    ),
}
NAME_LANGS = {
    "name": "name_langs",
    "type": "int32",
    "description": (
        "Derived. How many language codes appear in the division's "
        "`names.common` map, counted before this catalog's deduplication. It "
        "is the single number that says what this ODbL catalog buys over its "
        "CC-BY counterpart: countries average 202, regions 37, counties 8, "
        "localities 2.5. The names collection indexes the distinct spellings "
        "behind this count."
    ),
}
AREA = {
    "name": "area_km2",
    "type": "double",
    "description": (
        "Derived. Geodesic area of the land polygon in square kilometres on "
        "the WGS 84 ellipsoid, from DuckDB's `ST_Area_Spheroid` with the "
        "coordinates flipped to latitude-first, which that function requires. "
        "It is the area of the `class = 'land'` polygon, so it excludes "
        "territorial waters and is smaller than a figure quoted for the "
        "maritime extent."
    ),
}
PERIMETER = {
    "name": "perimeter_km",
    "type": "double",
    "description": (
        "Derived. Geodesic perimeter of the land polygon in kilometres on the "
        "WGS 84 ellipsoid."
    ),
}
COMPACTNESS = {
    "name": "compactness",
    "type": "double",
    "description": (
        "Derived. Polsby-Popper ratio, 4*pi*area/perimeter^2. 1.0 for a "
        "circle, falling towards 0 as an outline gets long or fragmented, so "
        "it separates island groups and river-defined divisions from blocky "
        "inland ones. Computed on the full-resolution geometry in this file, "
        "not on the display-simplified companion."
    ),
}
VERTICES = {
    "name": "vertices",
    "type": "int32",
    "description": (
        "Derived. `ST_NPoints` of the full-resolution geometry. It is how to "
        "predict what a feature costs to fetch and draw, and it is the number "
        "the display-simplified companion exists to reduce."
    ),
}
VERSION = {
    "name": "version",
    "type": "int32",
    "description": (
        "Attested. Overture's version counter for the feature, incremented "
        "when the feature changes between releases. Compare it, not the "
        "geometry, to find what moved since the last release."
    ),
}
BBOX = {
    "name": "bbox",
    "type": "struct",
    "description": (
        "GeoParquet 1.1 bbox covering struct, with xmin, ymin, xmax and ymax "
        "as doubles in CRS84, declared in the file's `geo` metadata. A reader "
        "prunes row groups on it without decoding any WKB, and it is also the "
        "extent to fly a map to after a search hit."
    ),
}
GEOMETRY = {
    "name": "geometry",
    "type": "geometry",
    "description": (
        "Attested, unchanged. Polygon or MultiPolygon as WKB in CRS84 "
        "(longitude, latitude on WGS 84), the `class = 'land'` division area: "
        "Overture's land-clipped, non-maritime outline, which it describes as "
        "intended for 'map rendering, cartographic display, and similar "
        "purposes'. Nothing is reprojected and no coordinate is moved. The "
        "`maritime` polygon Overture also publishes for coastal divisions is "
        "not carried here."
    ),
}

BOUNDARY_COLUMNS_TAIL = [
    AREA, PERIMETER, COMPACTNESS, VERTICES, VERSION, BBOX, GEOMETRY,
]

DISPLAY_COLUMNS = [
    {
        "name": "id",
        "type": "string",
        "description": "Attested. Same GERS division-area id as the full file.",
    },
    {
        "name": "division_id",
        "type": "string",
        "description": (
            "Attested. Same GERS division id as the full file, in the same "
            "row order, so row *i* here is row *i* there."
        ),
    },
    {
        "name": "name",
        "type": "string",
        "description": "Attested. `names.primary`, as in the full file.",
    },
    {
        "name": "subtype",
        "type": "string",
        "description": "Attested. As in the full file.",
    },
    {
        "name": "country",
        "type": "string",
        "description": "Derived. ISO 3166-1 alpha-3, as in the full file.",
    },
    {
        "name": "vertices",
        "type": "int32",
        "description": (
            "Derived. `ST_NPoints` of the simplified, buffered geometry. "
            "Compare it against `vertices` in the full file to see what the "
            "simplification bought."
        ),
    },
    {
        "name": "bbox",
        "type": "struct",
        "description": (
            "GeoParquet 1.1 bbox covering struct of the **display** geometry, "
            "which is marginally larger than the full file's because the "
            "outline is buffered outward."
        ),
    },
    {
        "name": "geometry",
        "type": "geometry",
        "description": (
            "Derived. Polygon or MultiPolygon as WKB in CRS84: the full "
            "geometry put through `ST_SimplifyPreserveTopology` and then "
            "buffered **outward** by the same tolerance, so the shape is a "
            "superset of the true outline rather than an approximation that "
            "cuts corners off it. Draw it; do not measure it."
        ),
    },
]


def boundary_spec(
    collection: str,
    *,
    title: str,
    short: str,
    description: str,
    keywords: list[str],
    composition: str,
    class_distribution: str | None,
    style_titles: dict[str, str],
) -> dict:
    columns = [ID, DIVISION_ID, NAME, subtype_column(composition), COUNTRY,
               COUNTRY_ISO2, REGION]
    if class_distribution:
        columns.append(class_column(class_distribution))
    columns += [LOCAL_TYPE, ADMIN_LEVEL, PARENT_DIVISION_ID, PARENT_NAME,
                PARENT_SUBTYPE, COUNTRY_UNITS, POPULATION, WIKIDATA,
                PROMINENCE, NAME_LANGS]
    columns += BOUNDARY_COLUMNS_TAIL
    return {
        "dir": collection,
        "id": collection,
        "level": COLLECTION_LEVEL[collection],
        "title": title,
        "short": short,
        "description": description,
        "keywords": keywords,
        "columns": columns,
        "styles": style_titles,
        "geometry_types": ["Polygon", "MultiPolygon"],
    }




# ---------------------------------------------------------------------------
# Measured facts
# ---------------------------------------------------------------------------
# Every number that appears in a description comes from here, and every entry
# here is a query against a built file. Nothing in the prose is typed.
FACT_SQL = {
    "country_rows": "SELECT count(*) FROM b_country",
    "country_countries": "SELECT count(*) FROM b_country WHERE subtype='country'",
    "country_dependencies":
        "SELECT count(*) FROM b_country WHERE subtype='dependency'",
    "country_vertices": "SELECT sum(vertices) FROM b_country",
    "region_rows": "SELECT count(*) FROM b_region",
    "region_countries": "SELECT count(DISTINCT country) FROM b_region",
    "region_max_units": "SELECT max(country_units) FROM b_region",
    "county_rows": "SELECT count(*) FROM b_county",
    "county_countries": "SELECT count(DISTINCT country) FROM b_county",
    "county_max_units": "SELECT max(country_units) FROM b_county",
    "localadmin_rows": "SELECT count(*) FROM b_localadmin",
    "localadmin_countries": "SELECT count(DISTINCT country) FROM b_localadmin",
    "localadmin_country_list":
        "SELECT string_agg(DISTINCT country, ', ' ORDER BY country) "
        "FROM b_localadmin",
    "locality_rows": "SELECT count(*) FROM b_locality",
    "locality_countries": "SELECT count(DISTINCT country) FROM b_locality",
    "locality_cities": "SELECT count(*) FROM b_locality WHERE class='city'",
    "locality_towns": "SELECT count(*) FROM b_locality WHERE class='town'",
    "locality_villages": "SELECT count(*) FROM b_locality WHERE class='village'",
    "locality_hamlets": "SELECT count(*) FROM b_locality WHERE class='hamlet'",
    "locality_unclassed": "SELECT count(*) FROM b_locality WHERE class IS NULL",
    "names_rows": "SELECT count(*) FROM n",
    "names_primary": "SELECT count(*) FROM n WHERE alt_of IS NULL",
    "names_alt": "SELECT count(*) FROM n WHERE alt_of IS NOT NULL",
    "names_with_boundary": "SELECT count(*) FROM n WHERE has_boundary",
    "names_point_only":
        "SELECT count(*) FROM n WHERE NOT has_boundary AND alt_of IS NULL",
    "names_languages": "SELECT count(DISTINCT name_lang) FROM n",
    "names_max_dupes": "SELECT max(name_dupes) FROM n",
    "names_countries": "SELECT count(DISTINCT country) FROM n",
    "names_level4": "SELECT count(*) FROM n WHERE level=4 AND alt_of IS NULL",
}


def measure_facts() -> dict:
    import duckdb

    con = duckdb.connect()
    con.execute("LOAD spatial;")
    for collection in COLLECTIONS:
        path = boundary_path(collection)
        if not path.exists():
            sys.exit(f"missing {path}; run the build tools first")
        con.execute(
            f"CREATE VIEW b_{collection} AS "
            f"SELECT * FROM read_parquet('{path.as_posix()}')"
        )
    if not NAMES_PATH.exists():
        sys.exit(f"missing {NAMES_PATH}; run tools/build_names.py first")
    con.execute(
        f"CREATE VIEW n AS SELECT * FROM read_parquet('{NAMES_PATH.as_posix()}')"
    )
    facts = {}
    for key, sql in FACT_SQL.items():
        value = con.execute(sql).fetchone()[0]
        facts[key] = value
    con.close()
    out = {}
    for key, value in facts.items():
        out[key] = value
        if isinstance(value, (int, float)):
            out[key] = f"{int(value):,}"
    out["release"] = RELEASE
    out["sibling"] = SIBLING_SOURCECOOP
    return out


def containment() -> dict:
    path = WORK / "display_containment.json"
    if not path.exists():
        sys.exit(f"missing {path}; run tools/build_display.py first")
    return {r["collection"]: r for r in json.loads(path.read_text())}


# ---------------------------------------------------------------------------
# The specs. Every {placeholder} is filled from measure_facts().
# ---------------------------------------------------------------------------
EXPERIMENTAL = (
    "**EXPERIMENTAL.** The schema of this collection may change without "
    "notice, and the Source Cooperative repository that serves it is "
    "unlisted. "
)

SHARE_ALIKE = (
    " **ODbL share-alike applies.** A database derived from this collection "
    "has to be released under ODbL as well, and an application that shows it "
    "has to display the attribution: *© OpenStreetMap contributors. Available "
    "under the [Open Database License](https://www.openstreetmap.org/copyright).* "
    f"The [CC-BY-4.0 counterpart]({SIBLING_SOURCECOOP}) carries no such "
    "obligation and less coverage."
)


def spec_list(facts: dict) -> list[dict]:
    specs = [
        boundary_spec(
            "country",
            title="Overture Divisions - Country and Dependency Boundaries",
            short="Country and Dependency Boundaries",
            description=(
                EXPERIMENTAL
                + "{country_rows} land polygons at the top of the Overture "
                "divisions hierarchy from release {release}: "
                "{country_countries} countries and {country_dependencies} "
                "dependencies, which Overture files as a separate subtype at "
                "`admin_level` 1 and this catalog carries in the same "
                "collection because an ISO-coded dependency is a "
                "country-equivalent for a name search. Geometry is Overture's "
                "`class = 'land'` outline, which is OpenStreetMap coastline "
                "detail: {country_vertices} vertices across "
                "{country_rows} features, so the "
                "display-simplified companion asset, not this file, is what "
                "you draw. GeoParquet 1.1 with bbox covering metadata, "
                "Hilbert-ordered, with row groups sized so one country's "
                "geometry costs about a megabyte to fetch. Read the "
                "[agent guide](AGENTS.md): the join key is `division_id`, not "
                "`id`." + SHARE_ALIKE
            ),
            keywords=[
                "experimental", "administrative boundaries", "countries",
                "dependencies", "Overture Maps", "divisions", "GERS",
                "ODbL", "global", "GeoParquet", "PMTiles",
            ],
            composition=(
                "{country_countries} country and {country_dependencies} "
                "dependency"
            ),
            class_distribution=None,
            style_titles={
                "default": "Land area",
                "status": "Country or dependency",
                "languages": "Languages with a name for this country",
                "population": "Population",
            },
        ),
        boundary_spec(
            "region",
            title="Overture Divisions - Region Boundaries",
            short="Region Boundaries",
            description=(
                EXPERIMENTAL
                + "{region_rows} first-level subdivisions worldwide, across "
                "{region_countries} countries: what Overture calls a region "
                "and defines as the 'largest sub-country administrative "
                "unit', so states, provinces, governorates and cantons. The "
                "`local_type` column carries the word each country actually "
                "uses. One country is divided into as many as "
                "{region_max_units} of them. GeoParquet 1.1 with bbox "
                "covering metadata, Hilbert-ordered, with a "
                "display-simplified companion for drawing. Read the "
                "[agent guide](AGENTS.md)." + SHARE_ALIKE
            ),
            keywords=[
                "experimental", "administrative boundaries", "regions",
                "states", "provinces", "Overture Maps", "divisions", "GERS",
                "ODbL", "subnational", "GeoParquet", "PMTiles",
            ],
            composition="{region_rows} region",
            class_distribution=None,
            style_titles={
                "default": "Languages with a name for this region",
                "area": "Land area",
                "units-per-country": "Regions in this country",
                "population": "Population",
            },
        ),
        boundary_spec(
            "county",
            title="Overture Divisions - County Boundaries",
            short="County Boundaries",
            description=(
                EXPERIMENTAL
                + "{county_rows} second-level subdivisions across "
                "{county_countries} countries: what Overture calls a county "
                "and defines as the 'largest sub-region administrative unit "
                "in most countries', so counties, districts, departments and "
                "municipalities. One country contributes as many as "
                "{county_max_units} of them. This is the level that lines up "
                f"with ADM2 in the [geoBoundaries mirror]({SIBLING_SOURCECOOP}), "
                "and the one to compare if you are deciding between the two "
                "catalogs. GeoParquet 1.1 with bbox covering metadata, "
                "Hilbert-ordered. Read the [agent guide](AGENTS.md)."
                + SHARE_ALIKE
            ),
            keywords=[
                "experimental", "administrative boundaries", "counties",
                "districts", "municipalities", "Overture Maps", "divisions",
                "GERS", "ODbL", "subnational", "GeoParquet", "PMTiles",
            ],
            composition="{county_rows} county",
            class_distribution=None,
            style_titles={
                "default": "Land area",
                "languages": "Languages with a name for this county",
                "units-per-country": "Counties in this country",
                "population": "Population",
            },
        ),
        boundary_spec(
            "localadmin",
            title="Overture Divisions - Local Administrative Boundaries",
            short="Local Administrative Boundaries",
            description=(
                EXPERIMENTAL
                + "{localadmin_rows} local administrative divisions, which "
                "Overture defines as the level that contains localities "
                "without having an independent authority of its own: the "
                "French commune, the Indonesian kecamatan. **Coverage is "
                "partial by design and this is the collection where that "
                "matters most**: Overture publishes localadmin divisions for "
                "{localadmin_countries} countries and none at all for the "
                "rest, so a client must not treat an empty result here as "
                "'no such place'. The countries are "
                "{localadmin_country_list}. GeoParquet 1.1 with bbox covering "
                "metadata, Hilbert-ordered. Read the "
                "[agent guide](AGENTS.md)." + SHARE_ALIKE
            ),
            keywords=[
                "experimental", "administrative boundaries", "communes",
                "localadmin", "Overture Maps", "divisions", "GERS", "ODbL",
                "subnational", "GeoParquet", "PMTiles",
            ],
            composition="{localadmin_rows} localadmin",
            class_distribution=None,
            style_titles={
                "default": "Land area",
                "coverage": "Which country publishes this level",
                "languages": "Languages with a name for this division",
                "population": "Population",
            },
        ),
        boundary_spec(
            "locality",
            title="Overture Divisions - Locality Boundaries",
            short="Locality Boundaries",
            description=(
                EXPERIMENTAL
                + "{locality_rows} city, town, village and hamlet outlines "
                "across {locality_countries} countries, the part of this "
                "catalog the CC-BY counterpart has no equivalent for. "
                "Overture defines a locality as 'a populated place that may "
                "or may not have its own administrative authority', and "
                "classes each one by size: {locality_cities} cities, "
                "{locality_towns} towns, {locality_villages} villages, "
                "{locality_hamlets} hamlets and {locality_unclassed} with no "
                "class. **These are the localities that have a polygon.** "
                "Overture's release holds far more localities than this, most "
                "of them as a point only; all of them are in the "
                "[names collection](../names/collection.json), which says per "
                "row whether a boundary exists here. GeoParquet 1.1 with bbox "
                "covering metadata, Hilbert-ordered. Read the "
                "[agent guide](AGENTS.md)." + SHARE_ALIKE
            ),
            keywords=[
                "experimental", "cities", "towns", "villages", "localities",
                "settlements", "Overture Maps", "divisions", "GERS", "ODbL",
                "global", "GeoParquet", "PMTiles",
            ],
            composition="{locality_rows} locality",
            class_distribution=(
                "{locality_hamlets} hamlet, {locality_villages} village, "
                "{locality_towns} town, {locality_cities} city and "
                "{locality_unclassed} with no class"
            ),
            style_titles={
                "default": "Settlement class",
                "area": "Land area",
                "population": "Population",
                "languages": "Languages with a name for this place",
            },
        ),
    ]
    return specs


# ---------------------------------------------------------------------------
# The names collection
# ---------------------------------------------------------------------------
NAMES_COLUMNS = [
    {
        "name": "name",
        "type": "string",
        "description": (
            "The spelling to display, byte for byte as Overture published it. "
            "On a primary row it is `names.primary`; on an alternative row it "
            "is the value Overture lists under one language code in "
            "`names.common`. Display this; search `name_norm`."
        ),
    },
    {
        "name": "name_norm",
        "type": "string",
        "description": (
            "Derived, and **the column the file is sorted by**. The folding "
            "is fixed by the index contract: Unicode NFD, combining marks "
            "(category Mn) dropped, everything outside Unicode letters, "
            "digits, space, hyphen and apostrophe replaced by a space, "
            "whitespace collapsed, trimmed, lowercased. So 'Zurich' finds "
            "'Zürich' and 'koln' finds 'Köln'. A script with no Latin "
            "decomposition, such as Han or Arabic, is lowercased and "
            "otherwise unchanged, so it is findable only in its own script. "
            "The sort is byte-wise on the UTF-8 encoding and not a locale "
            "collation, which is what lets a JavaScript `a < b` on the same "
            "folded strings agree with the file's order."
        ),
    },
    {
        "name": "level",
        "type": "int8",
        "description": (
            "Derived. This catalog's 0-to-4 mapping of Overture's subtype, "
            "and the level contract a geocoder filters on: 0 country and "
            "dependency, 1 region, 2 county, 3 localadmin, 4 locality. It is "
            "**not** Overture's `admin_level`, which is null below county and "
            "puts a dependency at 1. The boundary collection that holds a "
            "row's geometry is the one at the same level."
        ),
    },
    {
        "name": "subtype",
        "type": "string",
        "description": (
            "Attested. Overture's own placetype, carried through so that the "
            "two subtypes sharing level 0 stay distinguishable: `country`, "
            "`dependency`, `region`, `county`, `localadmin` or `locality`."
        ),
    },
    {
        "name": "class",
        "type": "string",
        "description": (
            "Attested. Overture's `class` on the division row: how settled a "
            "locality is, one of `city`, `town`, `village` or `hamlet`. It is "
            "**a ranking signal, not a filter**, and it is null above "
            "locality: measured on this release, Overture populates it on "
            "3,394,627 of 3,508,156 localities and on none of the 64,640 "
            "divisions above them, so 113,529 localities have no class and "
            "some of those are real cities. The distribution is hamlet "
            "1,715,416, village 1,561,816, town 103,175, city 14,220, which "
            "makes `class IN ('city', 'town')` 117,395 places out of 3.5 "
            "million. It is in this index because ranking verification showed "
            "a short prefix is otherwise dominated by alternative-language "
            "rows of countries and regions -- Baghdad buried under Tajik and "
            "Uzbek spellings of Bahamas -- and no other column separates a "
            "city from a country that happens to share a prefix. `area_km2` "
            "makes it worse, because a country always dwarfs a city."
        ),
    },
    {
        "name": "country",
        "type": "string",
        "description": (
            "Derived. ISO 3166-1 alpha-3, mapped from Overture's alpha-2 "
            "through the official ISO 3166-1 table packaged with pycountry, "
            "so this index and the CC-BY counterpart can be filtered with one "
            "code system. A country row carries its own code. A synthetic "
            "Overture code with no alpha-3 equivalent is carried through "
            "unchanged."
        ),
    },
    {
        "name": "feature_id",
        "type": "string",
        "description": (
            "Attested. The GERS id of the **division**, which is "
            "`division_id` in every boundary collection. It is a logical key "
            "and never a row offset, which is what makes a version skew "
            "between this index and the boundary files recoverable rather "
            "than silently wrong. An alternative-name row repeats its "
            "division's `feature_id`, so a result list dedupes on it."
        ),
    },
    {
        "name": "source",
        "type": "string",
        "description": (
            "Constant `overture-divisions` on every row. The index contract "
            "allows one index to hold several sources and requires a result "
            "to be able to say where it came from; this index holds one."
        ),
    },
    {
        "name": "name_lang",
        "type": "string",
        "description": (
            "Attested, and **not always a language code**. It is the key "
            "Overture uses for this spelling in `names.common`, carried "
            "through unchanged. 1,012 distinct keys appear in this index and "
            "965 of them are BCP-47 shaped; the other 47, covering 48,137 "
            "rows, are OpenStreetMap annotation keys rather than languages. "
            "`genitive` alone accounts for 46,479 of them, and `suffix`, "
            "`short`, `note`, `abbr` and `full` make up most of the rest. "
            "Those rows are worth indexing, because a user may well type an "
            "inflected or abbreviated form, but an interface that prints this "
            "column as a language label will print `genitive`. Null on a "
            "primary row, where the language of `names.primary` is unstated. "
            "Where several keys agree on one spelling the index keeps a "
            "single row holding the first key in alphabetical order, with "
            "`name_lang_count` saying how many agreed."
        ),
    },
    {
        "name": "name_lang_count",
        "type": "int16",
        "description": (
            "Derived. How many of Overture's language codes map to this exact "
            "folded spelling for this division. 1 on a primary row. It is "
            "high where a name travels unchanged between languages, which is "
            "also a usable signal that a spelling is widely recognized."
        ),
    },
    {
        "name": "alt_of",
        "type": "string",
        "description": (
            "Derived. Null on a primary row; on an alternative-name row it "
            "holds that row's own `feature_id`, which is the index contract's "
            "way of marking the row as an alternative spelling of a division "
            "whose primary row is elsewhere in the file. Filter "
            "`alt_of IS NULL` for one row per division."
        ),
    },
    {
        "name": "parent_name",
        "type": "string",
        "description": (
            "Derived. `names.primary` of the division's parent, so an "
            "autocomplete can show 'Springfield, Illinois' without a second "
            "fetch. Null for a country, which has no parent."
        ),
    },
    {
        "name": "area_km2",
        "type": "float",
        "description": (
            "Derived. The division's geodesic land area in square "
            "kilometres, copied from its boundary row, as float32 because an "
            "index this size cannot afford a double for a relevance weight. "
            "**Null where `has_boundary` is false**, which is most "
            "localities. Of two divisions with the same name, the larger is "
            "usually the one meant."
        ),
    },
    {
        "name": "population",
        "type": "int32",
        "description": (
            "Attested. Overture's `population` for the division where it has "
            "one, carried byte for byte. Undated, and **sparse in a way a "
            "ranker has to handle explicitly**: measured on this release, "
            "Overture populates it on 79.9% of countries (175 of 219), 30.6% "
            "of regions, 21.3% of counties, 35.0% of localadmins and 17.7% of "
            "localities (621,090 of 3,508,156). Null means unknown, never "
            "zero -- a client that coalesces it to 0 sorts every unpopulated "
            "place last, which at level 4 is five rows in six. Use it as a "
            "relevance weight alongside `prominence` and `class`, not as a "
            "census figure."
        ),
    },
    {
        "name": "prominence",
        "type": "int32",
        "description": (
            "Attested. Overture's `cartography.prominence`, its own ranking "
            "of how important a place is to show on a map. Documented as "
            "cartographic guidance rather than a measurement, so use it as a "
            "tie-break."
        ),
    },
    {
        "name": "name_dupes",
        "type": "int32",
        "description": (
            "Derived. How many rows of this index share this row's "
            "`name_norm`, counted worldwide and across levels and across "
            "primary and alternative rows. An autocomplete needs it to decide "
            "when to disambiguate: the most repeated folded name in this "
            "index occurs {names_max_dupes} times."
        ),
    },
    {
        "name": "has_boundary",
        "type": "boolean",
        "description": (
            "Derived. True when a boundary collection in this catalog holds a "
            "polygon for this division. False on {names_point_only} of the "
            "{names_primary} primary rows, all of them localities that "
            "Overture publishes as a point only. On a false row `bbox` is the "
            "division's point collapsed to zero width, `area_km2` is null and "
            "`geometry_ref` is null, so a client knows before it fetches that "
            "there is no outline to draw."
        ),
    },
    {
        "name": "bbox",
        "type": "struct",
        "description": (
            "The extent to fly a map to after a hit, as xmin, ymin, xmax, "
            "ymax. It is the division's full extent where a boundary exists "
            "and the division's point, collapsed, where one does not. Stored "
            "as **float32 with every bound rounded outward**, which halves "
            "what four coordinates a row cost across millions of rows; the "
            "box therefore always contains the division but is approximate to "
            "about 1e-5 degrees, roughly a metre. The boundary collections "
            "keep float64. A signed box where xmin > xmax would mean an "
            "antimeridian crossing."
        ),
    },
    {
        "name": "geometry_ref",
        "type": "struct",
        "description": (
            "Derived, and **advisory**. `file`, `row_group` and `row`: where "
            "this division's geometry sits in its boundary collection, and at "
            "the same index in that collection's display companion, which "
            "holds the same rows in the same groups. It turns a geometry "
            "fetch into one range read with no search. A consumer must still "
            "verify that the `division_id` it decodes equals `feature_id` and "
            "fall back to a lookup on mismatch, because this is a hint and "
            "the catalog version is what makes it valid. Null on an "
            "alternative-name row and on a point-only division."
        ),
    },
    {
        "name": "geometry",
        "type": "geometry",
        "description": (
            "Derived. A Point as WKB in CRS84: `ST_PointOnSurface` of the "
            "division's land polygon where there is one, which is guaranteed "
            "to fall inside the division where a centroid is not, and "
            "Overture's own division point where there is not. Use it for a "
            "marker, never as the division's geometry. **Null on an "
            "alternative-name row**, which describes the same division as its "
            "primary row; repeating the point on two million alternative rows "
            "cost 40 MB and said nothing new."
        ),
    },
]


def names_spec(facts: dict) -> dict:
    return {
        "dir": "names",
        "id": "names",
        "level": None,
        "title": "Overture Divisions Multilingual Gazetteer (Name Index)",
        "short": "Multilingual Gazetteer Index",
        "description": (
            EXPERIMENTAL
            + "The gazetteer itself -- a search sidecar, not a boundary "
            "dataset: {names_rows} rows "
            "over {names_primary} divisions in {names_countries} countries, "
            "sorted by a folded form of the name. {names_alt} of those rows "
            "are alternative spellings drawn from Overture's `names.common` "
            "map across {names_languages} language codes, each pointing back "
            "at its division through `alt_of`, which is what makes this "
            "catalog worth its ODbL obligations. It resolves place names and "
            "administrative boundaries, **not street addresses**: there is no "
            "house number and no interpolation here. **The sort is the whole "
            "design.** This index is far too large to load whole, so the "
            "intended path is HTTP range requests: row group statistics on "
            "`name_norm` are tight, non-overlapping alphabetical ranges, the "
            "footer declares the sort, and the Parquet page index is written, "
            "so a typed prefix resolves from one or two row groups of about "
            "478 KiB. A client that wants a keystroke answered with no round "
            "trip at all loads the **prominent index** instead -- a second, "
            "8.6 MiB file in this same collection, same schema and same sort, "
            "holding every division down to localadmin, every "
            "alternative-language spelling of every country, and every "
            "locality Overture ranks at prominence 50 or above. "
            "`names/index.json` describes it under `prominent_index` with its "
            "selection criteria in full. Every row of either file carries the "
            "GERS `feature_id` that joins it "
            "to a boundary collection, a bbox to fly to, a point, and an "
            "advisory `geometry_ref` that turns the geometry fetch into a "
            "single range read. {names_point_only} divisions, almost all "
            "localities, have no polygon anywhere in this catalog and say so "
            "through `has_boundary`. The [agent guide](AGENTS.md) has the "
            "prefix-lookup recipe and the join back to geometry."
            + SHARE_ALIKE
        ),
        "keywords": [
            "experimental", "geocoding", "search index", "place names",
            "gazetteer", "autocomplete", "multilingual", "Overture Maps",
            "divisions", "GERS", "ODbL", "GeoParquet",
        ],
        "columns": NAMES_COLUMNS,
        "geometry_types": ["Point"],
        "styles": {
            "default": "Indexed names by level",
            "ambiguity": "How many places share this name",
            "languages": "Languages indexed for this spelling",
            "population": "Population of the named place",
        },
    }


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------
def checksum(path: Path) -> str:
    """A multihash sha2-256, the form STAC's file extension expects."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return f"1220{digest}"


def clamp_wgs84(bbox: list[float]) -> list[float]:
    """Clamp a STAC extent to the valid WGS84 range.

    Two reasons it can fall outside. A land polygon reaches the antimeridian
    and floating-point rounding puts its east edge a fraction past 180. And
    the search index's bbox struct is float32 rounded outward, which pushes
    its east edge to about 180.000015, some 1.5 m. Neither is a real
    coordinate past the antimeridian, and rashid's PTL-BBX-001 correctly
    refuses a STAC extent outside [-180, 180]. The data files keep their
    measured bbox so the covering metadata still contains every geometry;
    only the STAC extent is clamped.
    """
    xmin, ymin, xmax, ymax = bbox
    return [max(-180.0, xmin), max(-90.0, ymin),
            min(180.0, xmax), min(90.0, ymax)]


def parquet_stats(path: Path) -> dict:
    pf = pq.ParquetFile(path)
    geo = json.loads(pf.schema_arrow.metadata[b"geo"])
    primary = geo["primary_column"]
    return {
        "rows": pf.metadata.num_rows,
        "row_groups": pf.metadata.num_row_groups,
        "bbox": geo["columns"][primary]["bbox"],
        "primary": primary,
    }


def style_assets(spec: dict, out_dir: Path) -> dict:
    assets = {}
    for slug, title in spec["styles"].items():
        path = out_dir / "styles" / f"{slug}.json"
        if not path.exists():
            sys.exit(f"missing {path}; run tools/make_styles.py first")
        key = "style-default" if slug == "default" else f"style-{slug}"
        assets[key] = {
            "href": f"./styles/{slug}.json",
            "type": "application/vnd.mapbox.style+json",
            "title": title,
            "roles": ["style", "default"] if slug == "default" else ["style"],
            "file:size": path.stat().st_size,
            "file:checksum": checksum(path),
        }
    return assets


UPSTREAM_CAVEAT = (
    "This is the authoritative release, not a copy of it: use it for bulk "
    "download, for analysis over the whole theme, and for anything where the "
    "answer has to come from Overture rather than from a mirror. It is not "
    "what this catalog's files are for, and the difference is layout rather "
    "than reachability -- measured 2026-11-12 on part-00000 of type=division: "
    "4,700,999 rows in 256 row groups of about 18,400 rows, median 2.22 MB "
    "and up to 3.85 MB compressed per row group, 50 leaf column chunks, no "
    "declared sort, and a 1.47 MB footer that takes a reader two requests "
    "because a speculative 512 KiB tail falls short. Finding one place by "
    "name in it means scanning every part file; pulling one division's "
    "geometry means fetching a multi-megabyte row group of the full "
    "50-column schema. The files in this catalog are the same data sorted, "
    "projected and laid out so that each of those is one small range "
    "request. See the catalog README's \"The upstream data vs our optimized "
    "files\"."
)

SOURCE_ASSETS = {
    "upstream-division-s3": {
        "href": f"{S3_HTTPS_THEME}/type=division/",
        "type": "application/vnd.apache.parquet",
        "title": (
            f"Overture release {RELEASE}, type=division, on S3 over HTTPS "
            f"({UPSTREAM_FILES['division']} file, "
            f"{UPSTREAM_BYTES['division'] / 1e9:.2f} GB)"
        ),
        "roles": ["data", "source"],
        "description": (
            "Every division record in the release: the names, the hierarchy "
            "and a point per division. The names collection here is built "
            "from this type, and every collection takes its names from it. "
            f"The same bytes are addressable as `{S3_THEME}/type=division/` "
            "for DuckDB, GDAL and the AWS CLI; the bucket is public and "
            "anonymous and the requester does not pay. Measured 2026-11-12, "
            "this HTTPS endpoint answers `Accept-Ranges: bytes` and sends "
            "`Access-Control-Allow-Origin: *` with `Content-Range` and "
            "`Accept-Ranges` exposed, so a browser can range-read it "
            f"cross-origin. {UPSTREAM_CAVEAT}"
        ),
    },
    "upstream-division-area-s3": {
        "href": f"{S3_HTTPS_THEME}/type=division_area/",
        "type": "application/vnd.apache.parquet",
        "title": (
            f"Overture release {RELEASE}, type=division_area, on S3 over "
            f"HTTPS ({UPSTREAM_FILES['division_area']} files, "
            f"{UPSTREAM_BYTES['division_area'] / 1e9:.2f} GB)"
        ),
        "roles": ["data", "source"],
        "description": (
            "The polygons. Every boundary collection in this catalog is a "
            "projection of one `subtype` of this type, joined to "
            "type=division for names. Also addressable as "
            f"`{S3_THEME}/type=division_area/`. Same public anonymous access "
            f"and the same CORS headers as type=division. {UPSTREAM_CAVEAT}"
        ),
    },
    "upstream-divisions-azure": {
        "href": f"{AZURE_HTTPS_THEME}/",
        "type": "application/vnd.apache.parquet",
        "title": (
            f"Overture release {RELEASE}, divisions theme, on the Azure Blob "
            "mirror"
        ),
        "roles": ["data", "source"],
        "description": (
            "Overture publishes every release to Azure Blob Storage as well "
            "as to S3, and these are the same files under `type=division/` "
            "and `type=division_area/`. **It sends no CORS headers**, "
            "measured 2026-11-12, so unlike the S3 HTTPS endpoint it cannot "
            "be read from a browser cross-origin; it is for server-side and "
            "CLI consumers, and for anyone whose egress is cheaper from "
            f"Azure. {UPSTREAM_CAVEAT}"
        ),
    },
    "overture-division-schema": {
        "href": "../_assets/overture/division.schema.yaml",
        "type": "application/yaml",
        "title": "Overture type=division JSON Schema, as published",
        "roles": ["metadata", "source"],
        "description": (
            "Overture's own schema for the division feature type, copied from "
            "OvertureMaps/schema. Every column description in this collection "
            "marked attested is quoted or paraphrased from it."
        ),
    },
    "overture-division-area-schema": {
        "href": "../_assets/overture/division_area.schema.yaml",
        "type": "application/yaml",
        "title": "Overture type=division_area JSON Schema, as published",
        "roles": ["metadata", "source"],
        "description": (
            "Overture's own schema for the division_area feature type, which "
            "is where the land and maritime class definitions and the "
            "is_land flag come from."
        ),
    },
    "overture-attribution": {
        "href": "../_assets/overture/divisions-attribution.md",
        "type": "text/markdown",
        "title": "Overture attribution requirements for divisions, verbatim",
        "roles": ["metadata", "license"],
        "description": (
            "The divisions block of Overture's attribution page, copied "
            "verbatim on 2026-11-12. It is the evidence behind this "
            "collection's license and required attribution."
        ),
    },
}


def common_links(spec: dict, specs: list[dict]) -> list[dict]:
    root_title = "EXPERIMENTAL: Overture Divisions for Geocoding (ODbL)"
    links = [
        {"rel": "root", "href": "../catalog.json", "type": "application/json",
         "title": root_title},
        {"rel": "parent", "href": "../catalog.json",
         "type": "application/json", "title": root_title},
        {"rel": "describedby", "href": "./README.md", "type": "text/markdown",
         "title": "Collection README"},
        {"rel": "agents", "href": "./AGENTS.md", "type": "text/markdown",
         "title": "Collection agent guide"},
        {"rel": "via", "href": DOCS_DIVISIONS, "type": "text/html",
         "title": "Overture Maps divisions theme guide (upstream source)"},
        {"rel": "describedby", "href": DOCS_SCHEMA_DIVISION,
         "type": "text/html",
         "title": "Overture division schema reference"},
        {"rel": "cite-as", "href": "https://overturemaps.org/",
         "type": "text/html",
         "title": "Overture Maps Foundation, overturemaps.org"},
        {"rel": "license", "href": LICENSE_URL, "type": "text/html",
         "title": "Open Database License (ODbL) v1.0"},
        {"rel": "license", "href": DOCS_ATTRIBUTION, "type": "text/html",
         "title": "Overture attribution and licensing requirements"},
        {"rel": "related", "href": SIBLING_SOURCECOOP, "type": "text/html",
         "title": "geoBoundaries CGAZ, the CC-BY-4.0 counterpart catalog"},
    ]
    for sibling in specs:
        if sibling["id"] == spec["id"]:
            continue
        links.append({
            "rel": "related",
            "href": f"../{sibling['dir']}/collection.json",
            "type": "application/json",
            "title": sibling["title"],
        })
    return links


def build(spec: dict, specs: list[dict], facts: dict, reports: dict) -> dict:
    out_dir = CATALOG / spec["dir"]
    out_dir.mkdir(parents=True, exist_ok=True)
    is_names = spec["id"] == "names"
    data = NAMES_PATH if is_names else boundary_path(spec["id"])
    tiles = pmtiles_path(spec["id"])
    for path in (data, tiles):
        if not path.exists():
            sys.exit(f"missing {path}; run the build tools first")
    stats = parquet_stats(data)
    max_zoom = NAMES_MAX_ZOOM if is_names else MAX_ZOOM[spec["id"]]

    assets: dict[str, dict] = {}
    if is_names:
        assets["data"] = {
            "href": f"./{data.name}",
            "type": "application/vnd.apache.parquet",
            "title": (
                f"Multilingual name index, GeoParquet 1.1 "
                f"({stats['row_groups']:,} row groups of "
                f"{NAMES_ROW_GROUP_ROWS:,} rows, zstd, page index, sorted by "
                "name_norm)"
            ),
            "roles": ["data"],
            "file:size": data.stat().st_size,
            "file:checksum": checksum(data),
            "table:primary_geometry": stats["primary"],
            "description": (
                "The whole gazetteer. Too large to load in a browser, and "
                "not meant to be: it is sorted by `name_norm` so a typed "
                "prefix is a range request. A client that wants an answer "
                "with no round trip loads the `prominent-index` asset "
                "instead and comes here for anything that file can miss."
            ),
        }
        prominent = PUBLISH / "names" / PROMINENT_NAME
        if prominent.exists():
            pstats = parquet_stats(prominent)
            assets["prominent-index"] = {
                "href": f"./{prominent.name}",
                "type": "application/vnd.apache.parquet",
                "title": (
                    f"Prominent gazetteer index, GeoParquet 1.1 "
                    f"({pstats['row_groups']:,} row groups of "
                    f"{PROMINENT_ROW_GROUP_ROWS:,} rows, "
                    f"{prominent.stat().st_size / (1 << 20):.1f} MiB, same "
                    "schema and sort as the full index)"
                ),
                # "overview" is STAC's role for a reduced version of the data
                # asset. This is a reduction in rows rather than in
                # resolution, which is the same relationship.
                "roles": ["data", "overview"],
                "file:size": prominent.stat().st_size,
                "file:checksum": checksum(prominent),
                "table:primary_geometry": pstats["primary"],
                "table:row_count": pstats["rows"],
                "description": (
                    f"A strict row subset of the full index -- "
                    f"{pstats['rows']:,} rows of "
                    f"{stats['rows']:,} -- small enough for a client to fetch "
                    "whole on focus and answer keystrokes from memory, while "
                    "the full index stays available by range request for "
                    "anything deeper. Same schema, same sort, same "
                    "`feature_id` and `geometry_ref`, so a hit found here "
                    "resolves its geometry exactly as a hit found there. It "
                    "holds every division from country down to localadmin, "
                    "every alternative-language spelling of every country and "
                    "dependency, and every locality Overture ranks at "
                    "`cartography.prominence` 50 or above. What it can miss, "
                    "and therefore when to fall back: any locality below that "
                    "cut, and any alternative-language name of a region, "
                    "county, localadmin or locality. The full criteria, with "
                    "row counts per level, are in `index.json` under "
                    "`prominent_index.criteria`."
                ),
            }
        manifest = out_dir / "index.json"
        if not manifest.exists():
            sys.exit(f"missing {manifest}; run tools/build_names.py first")
        assets["index-manifest"] = {
            "href": "./index.json",
            "type": "application/json",
            "title": "Gazetteer manifest for the geocoder (cnmw-index/1.0)",
            "roles": ["metadata"],
            "file:size": manifest.stat().st_size,
            "file:checksum": checksum(manifest),
            "description": (
                "The few kilobytes a client fetches before anything else. "
                "For the full index, the prominent index and every boundary "
                "and display file: the URL, size, checksum, row count, row "
                "group count and `row_group_rows`, plus two exact metadata "
                "sizes. `footer_bytes` is the whole trailing span, thrift "
                "footer plus page index, so one range request of exactly "
                "that many bytes from the end of a file leaves a client "
                "holding all of its metadata; `footer_metadata_bytes` is the "
                "thrift footer alone, the minimum needed to locate row "
                "groups and what a hyparquet client should pass as "
                "`initialFetchSize`. Without them hyparquet speculates a "
                "512 KiB tail, which on the 409 MB index is a guaranteed "
                "second round trip because its footer is 2.1 MB. Also "
                "carries `prominent_index.criteria` -- exactly which rows "
                "the small index holds and what it can miss -- the catalog "
                "version, and the attribution each file requires with a "
                "share_alike flag."
            ),
        }
    else:
        display = display_path(spec["id"])
        if not display.exists():
            sys.exit(f"missing {display}; run tools/build_display.py first")
        report = reports[spec["id"]]
        dstats = parquet_stats(display)
        assets["data"] = {
            "href": f"./{data.name}",
            "type": "application/vnd.apache.parquet",
            "title": (
                f"{spec['short']}, full-resolution GeoParquet 1.1 "
                f"({stats['row_groups']:,} row groups of "
                f"{ROW_GROUP_ROWS[spec['id']]:,} rows, zstd, page index, "
                "Hilbert order)"
            ),
            "roles": ["data"],
            "file:size": data.stat().st_size,
            "file:checksum": checksum(data),
            "table:primary_geometry": stats["primary"],
        }
        assets["display"] = {
            "href": f"./{display.name}",
            "type": "application/vnd.apache.parquet",
            "title": (
                f"{spec['short']}, display-simplified GeoParquet 1.1 "
                f"({display.stat().st_size / dstats['rows'] / 1024:.1f} KiB "
                "per feature)"
            ),
            "roles": ["data", "visual", "overview"],
            "file:size": display.stat().st_size,
            "file:checksum": checksum(display),
            "table:primary_geometry": dstats["primary"],
            "description": (
                "The same rows in the same order and the same row groups as "
                "the full file, simplified with ST_SimplifyPreserveTopology "
                "and then buffered **outward** by the same amount, so the "
                "shape always contains the true boundary rather than cutting "
                "corners off it. The tolerance is per feature, "
                f"{report['share_of_diagonal'] * 100:g}% of that feature's "
                f"own bounding-box diagonal capped at "
                f"{report['tolerance_ceiling_deg']} degrees, which here "
                f"ranged from {report['tolerance_min_deg']:.3g} to "
                f"{report['tolerance_max_deg']:.3g} degrees. Verified per "
                "feature: "
                f"{report['fully_contained']:,} of {report['features']:,} "
                "contain their full-resolution polygon completely, "
                f"{report['below_99pct']:,} fall below 99% of its area, and "
                f"the worst is {report['min_contained']:.4f}. Draw it, filter "
                "with it, and measure with the full file."
            ),
        }
    assets["pmtiles"] = {
        "href": f"./{tiles.name}",
        "type": "application/vnd.pmtiles",
        "title": f"{spec['short']}, vector tiles to zoom {max_zoom}",
        "roles": ["visual", "data"],
        "file:size": tiles.stat().st_size,
        "file:checksum": checksum(tiles),
        "pmtiles:layers": [spec["id"]],
    }
    assets.update(style_assets(spec, out_dir))
    for key, asset in SOURCE_ASSETS.items():
        assets[key] = dict(asset)
        # The evidence assets are files in `catalog/_assets/`, so they get a
        # size and a checksum. The upstream release assets are remote prefixes
        # holding several part files whose bytes this repository never holds,
        # so they get neither -- a `file:checksum` of a directory listing
        # would be a fabrication, and `file:size` of one part file would
        # understate the eight that type=division_area has.
        if asset["href"].startswith(("http://", "https://")):
            # A remote release prefix gets neither `file:size` nor
            # `file:checksum`. The prefix holds several part files, so a
            # multihash of it would be a fabrication -- and declaring a
            # `file:size` is worse than omitting it: `portolan check` verifies
            # a declared size against the bytes it can reach, finds none for a
            # remote href, and turns a warning into a PTL-DAT-002 error.
            # Measured, not assumed. The byte totals live in the asset titles
            # instead, where they inform a reader without claiming to be a
            # verifiable property of a local file. See docs/conformance.md for
            # the PTL-AST-003 warnings this leaves.
            continue
        local = CATALOG / asset["href"].replace("../", "")
        assets[key]["file:size"] = local.stat().st_size
        assets[key]["file:checksum"] = checksum(local)
    thumb = out_dir / f"{spec['id']}.thumb.png"
    if thumb.exists():
        assets["thumbnail"] = {
            "href": f"./{thumb.name}",
            "type": "image/png",
            "title": f"{spec['short']}, rendered from the default style",
            "roles": ["thumbnail"],
            "file:size": thumb.stat().st_size,
            "file:checksum": checksum(thumb),
        }

    links = common_links(spec, specs)
    links.append({
        "rel": "pmtiles", "href": f"./{tiles.name}",
        "type": "application/vnd.pmtiles",
        "title": f"{spec['short']}, vector tiles",
        "pmtiles:layers": [spec["id"]],
    })

    # Only the columns the file actually holds. build_boundaries.py drops a
    # column Overture leaves null at this level, so the spec above is the
    # superset and the file is the truth.
    present = set(pq.ParquetFile(data).schema_arrow.names)
    columns = [
        {**col, "description": col["description"].format(**facts)}
        for col in spec["columns"]
        if col["name"] in present
    ]
    missing = [c["name"] for c in spec["columns"] if c["name"] not in present]
    if missing:
        print(f"    (not in {spec['id']}: {', '.join(missing)})")
    doc = {
        "type": "Collection",
        "stac_version": "1.1.0",
        "stac_extensions": [
            "https://schemas.portolan-sdi.org/portolan/v0.2.0/schema.json",
            "https://stac-extensions.github.io/table/v1.2.0/schema.json",
            "https://stac-extensions.github.io/file/v2.1.0/schema.json",
            "https://stac-extensions.github.io/web-map-links/v1.3.0/schema.json",
        ],
        "id": spec["id"],
        "title": spec["title"],
        "description": spec["description"].format(**facts),
        "license": LICENSE,
        "keywords": spec["keywords"],
        "providers": PROVIDERS,
        "extent": {
            "spatial": {
                "bbox": [[round(v, 6) for v in clamp_wgs84(stats["bbox"])]]
            },
            # Overture publishes no validity date per division, so the
            # interval is the release this catalog mirrors. A release is
            # immutable, so the two ends are the same instant.
            "temporal": {
                "interval": [[f"{RELEASE[:10]}T00:00:00Z",
                              f"{RELEASE[:10]}T00:00:00Z"]]
            },
        },
        # PTL-PRO-003: a mirror has to say when it last synced. This is the
        # date the Overture release was staged, which is what a reader
        # compares against the live release index.
        "updated": f"{EXTRACTION_DATE}T00:00:00Z",
        "table:primary_geometry": stats["primary"],
        "table:row_count": stats["rows"],
        "table:columns": columns,
        "assets": assets,
        "links": links,
    }
    path = out_dir / "collection.json"
    path.write_text(json.dumps(doc, indent=2) + "\n")
    print(
        f"  {path.relative_to(REPO)}: {stats['rows']:,} rows, "
        f"{len(assets)} assets, {len(columns)} columns"
    )
    return doc


def main() -> int:
    facts = measure_facts()
    reports = containment()
    specs = spec_list(facts)
    specs.append(names_spec(facts))
    for spec in specs:
        build(spec, specs, facts, reports)
    print(f"catalog version: {CATALOG_VERSION}, release notes {RELEASE_NOTES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
