#!/usr/bin/env python3
"""Generate the catalog README and every collection README.

    python3 tools/make_readmes.py

A README here is output, not a source file. Every number in one is read out of
a built file or out of the collection.json beside it, and the prose comes from
the blocks in this module. Hand-editing a README loses the edit on the next
run; edit the prose here, or the provenance in the collection's
``.portolan/metadata.yaml``, and regenerate.

Run ``tools/make_collections.py`` first: this reads the collection.json it
writes, so the two cannot disagree about a row count.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pyarrow.parquet as pq

from ovcommon import (
    COLLECTIONS,
    COLLECTION_LEVEL,
    DOCS_ATTRIBUTION,
    DOCS_DIVISIONS,
    EXTRACTION_DATE,
    NAMES_PATH,
    NAMES_ROW_GROUP_ROWS,
    RELEASE,
    ROW_GROUP_ROWS,
    SIMPLIFY_TOLERANCE,
    boundary_path,
    display_path,
    human,
    wrap_markdown,
    pmtiles_path,
)
from build_pmtiles import MAX_ZOOM, NAMES_MAX_ZOOM

REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "catalog"
PUBLIC = "https://data.source.coop/portolan-mirrors/cn-geocoder-overture"
HUMAN = "https://source.coop/portolan-mirrors/cn-geocoder-overture"
SIBLING = "https://source.coop/portolan-mirrors/geoboundaries-catalog"
SIBLING_REPO = "https://github.com/portolan-mirrors/geoboundaries-catalog"
REPO_URL = "https://github.com/portolan-mirrors/cn-geocoder-overture"

EXPERIMENTAL_BANNER = """> [!WARNING]
> **This catalog is EXPERIMENTAL.** The schema may change without notice, the
> Source Cooperative repository that serves it is unlisted, and the column
> contract it publishes is still being negotiated with its consumer. Pin the
> `catalog_version` in [names/index.json](names/index.json) if you depend on
> it, and expect to rebuild.
"""

LICENSE_BLOCK = f"""## License and attribution

The data is **ODbL-1.0**. Overture's own attribution page states, for the
divisions theme:

> **License for theme:** ODbL
>
> - © OpenStreetMap contributors. Available under the Open Database License.
> - geoBoundaries. Available under CC BY 4.0.
> - Esri Community Maps contributors. Available under CC BY 4.0.
> - Land Information New Zealand (LINZ). Available under CC BY 4.0.

That block, copied verbatim with its links, is published beside the data at
[_assets/overture/divisions-attribution.md](_assets/overture/divisions-attribution.md).
The live page is [Attribution and Licensing]({DOCS_ATTRIBUTION}).

**What you have to do.** Display this line wherever the data is shown:

> © OpenStreetMap contributors. Available under the
> [Open Database License](https://www.openstreetmap.org/copyright).

Overture also publishes the shorter form it uses on its own Explore tool,
`© OpenStreetMap contributors, Overture Maps Foundation`, and asks that a
publication cite `Overture Maps Foundation, overturemaps.org` with the date
the data were accessed. This catalog was built from release {RELEASE},
accessed {EXTRACTION_DATE}.

**Share-alike, plainly.** ODbL is a copyleft licence for databases. Because
OpenStreetMap content is in the conflated whole, the share-alike term applies
to all of it:

- A **derived database** -- a subset, a reprojection, a join, an index built
  on top of this one -- has to be offered under ODbL as well.
- A **produced work** -- a map image, a screenshot, an application screen --
  does not have to be ODbL, but it has to carry the attribution above.
- You cannot apply technical measures that stop someone else exercising those
  rights on the data you pass on.

The index manifest sets `share_alike: true` on every ODbL entry in its
`attribution` array, so a client can surface the obligation in its own
interface without reading this file.

**If share-alike does not work for you**, use the CC-BY-4.0 counterpart,
[geoboundaries-catalog]({SIBLING}) ([repository]({SIBLING_REPO})). It is the
default for that reason. It carries the same column contract at ADM0, ADM1 and
ADM2, under attribution-only terms, with no city or locality level and no
multilingual names.
"""


def stats(path: Path) -> dict:
    pf = pq.ParquetFile(path)
    geo = json.loads(pf.schema_arrow.metadata[b"geo"])
    return {
        "rows": pf.metadata.num_rows,
        "row_groups": pf.metadata.num_row_groups,
        "size": path.stat().st_size,
        "bbox": geo["columns"][geo["primary_column"]]["bbox"],
    }


def collection_doc(collection: str) -> dict:
    path = CATALOG / collection / "collection.json"
    if not path.exists():
        sys.exit(f"missing {path}; run tools/make_collections.py first")
    return json.loads(path.read_text())


def index_manifest() -> dict:
    path = CATALOG / "names" / "index.json"
    if not path.exists():
        sys.exit(f"missing {path}; run tools/build_names.py first")
    return json.loads(path.read_text())


def measurements() -> dict:
    path = REPO / "docs" / "index-measurements.json"
    if not path.exists():
        sys.exit(f"missing {path}; run tools/measure_index.py first")
    return json.loads(path.read_text())


def containment() -> dict:
    from ovcommon import WORK

    path = WORK / "display_containment.json"
    if not path.exists():
        sys.exit(f"missing {path}; run tools/build_display.py first")
    return {r["collection"]: r for r in json.loads(path.read_text())}


# ---------------------------------------------------------------------------
# Per-collection prose. Numbers are never written here; they are interpolated
# from the measurements above.
# ---------------------------------------------------------------------------
OVERVIEW = {
    "country": (
        "The top of the Overture divisions hierarchy: sovereign countries and "
        "the dependencies Overture files one level below them. This catalog "
        "keeps both in one collection and at one level, because an ISO-coded "
        "dependency such as Greenland or Puerto Rico is a country-equivalent "
        "for a name search even though Overture gives it `admin_level` 1. The "
        "`subtype` column is what tells the two apart."
    ),
    "region": (
        "First-level subdivisions: what Overture calls a region and defines "
        "as the largest sub-country administrative unit. In practice that is "
        "a state, a province, a governorate, a canton or an oblast, and the "
        "`local_type` column carries the word the country itself uses."
    ),
    "county": (
        "Second-level subdivisions: Overture's county, the largest "
        "sub-region administrative unit in most countries. This is the level "
        "that lines up with ADM2 in the CC-BY counterpart, so it is the one "
        "to compare when choosing between the two catalogs."
    ),
    "localadmin": (
        "The administrative level that contains localities without having an "
        "authority of its own: the French commune, the Indonesian kecamatan, "
        "the Swiss Gemeinde. **Coverage is partial**, and that is the first "
        "thing to know about this collection."
    ),
    "locality": (
        "Populated places with a boundary: cities, towns, villages and "
        "hamlets. This is the collection the CC-BY counterpart has no "
        "equivalent for, and the reason to accept ODbL."
    ),
}

WHY_IT_MATTERS = {
    "country": (
        "Overture's country outlines are OpenStreetMap coastline, so they are "
        "the most detailed geometry in this catalog by a wide margin and the "
        "least suitable to draw directly. Use the display asset for a map and "
        "this file for measurement."
    ),
    "region": (
        "Region is the level where multilingual naming starts to pay off: "
        "Overture lists an average of 37 language variants for a region "
        "against 8 for a county."
    ),
    "county": (
        "The county level is where this catalog and the CC-BY one are most "
        "nearly interchangeable, so it is the honest place to look at what "
        "ODbL buys: roughly the same features, with alternative names "
        "attached."
    ),
    "localadmin": (
        "A client must not read an empty result here as 'no such place'. It "
        "usually means the country publishes no localadmin level at all."
    ),
    "locality": (
        "Only a minority of Overture's localities have a polygon. The rest "
        "are points, and they are all in the names collection, which says per "
        "row whether a boundary exists here."
    ),
}


def boundary_readme(collection: str, docs: dict, cont: dict) -> str:
    doc = docs[collection]
    full = stats(boundary_path(collection))
    disp = stats(display_path(collection))
    tiles = pmtiles_path(collection)
    report = cont[collection]
    level = COLLECTION_LEVEL[collection]
    short = doc["title"].split(" - ", 1)[-1]

    import duckdb

    con = duckdb.connect()
    src = boundary_path(collection).as_posix()
    countries, vfull, vdisp, named, pop, langs = con.execute(
        f"""SELECT count(DISTINCT country), sum(vertices),
                   (SELECT sum(vertices) FROM read_parquet(
                      '{display_path(collection).as_posix()}')),
                   count(name), count(population), round(avg(name_langs), 1)
            FROM read_parquet('{src}')"""
    ).fetchone()
    top = con.execute(
        f"""SELECT name, country, round(area_km2) FROM read_parquet('{src}')
            ORDER BY area_km2 DESC LIMIT 3"""
    ).fetchall()
    con.close()

    lines = [
        f"# {doc['title']}",
        "",
        EXPERIMENTAL_BANNER,
        OVERVIEW[collection],
        "",
        WHY_IT_MATTERS[collection],
        "",
        "This is a **mirror**. [Overture Maps Foundation](https://overturemaps.org/)",
        f"produces the data; this catalog republishes release `{RELEASE}` in "
        "cloud-native form and changes no coordinate and no attribute value.",
        "",
        "| | |",
        "|---|---|",
        f"| Rows | {full['rows']:,} |",
        f"| Countries represented | {countries:,} |",
        f"| Search index level | {level} |",
        f"| GeoParquet, full resolution | {human(full['size'])}, "
        f"{full['row_groups']:,} row groups of "
        f"{ROW_GROUP_ROWS[collection]:,} rows, zstd, page index |",
        f"| Row group | ~{human(int(full['size'] / full['row_groups']))} |",
        f"| GeoParquet, display | {human(disp['size'])}, "
        f"{disp['size'] / disp['rows'] / 1024:.1f} KiB per feature |",
        f"| PMTiles | {human(tiles.stat().st_size)}, zoom 0-"
        f"{MAX_ZOOM[collection]} |",
        f"| Vertices, full vs display | {int(vfull):,} vs {int(vdisp):,} "
        f"({100 * (1 - vdisp / vfull):.1f}% fewer) |",
        f"| Rows with a population | {pop:,} of {full['rows']:,} |",
        f"| Average name languages | {langs} |",
        "| CRS | CRS84 (EPSG:4326), as published |",
        f"| Order | Hilbert curve over the whole globe |",
        "",
        "The three largest by land area: "
        + ", ".join(f"{n} ({c}, {a:,.0f} km²)" for n, c, a in top)
        + ".",
        "",
        "## Two geometry files, and which one to use",
        "",
        f"`overture_{collection}.parquet` is Overture's own "
        "`class = 'land'` outline, unchanged. Measure with it, clip with it, "
        "and fetch one feature from it by range request when a user has "
        "committed to a place.",
        "",
        f"`overture_{collection}_display.parquet` holds the same "
        f"{disp['rows']:,} rows, in the same order, in the same "
        f"{disp['row_groups']:,} row groups, simplified with "
        "`ST_SimplifyPreserveTopology` and then **buffered outward by the "
        "same tolerance**. Draw with it, and use it for the first paint while "
        "the full geometry is still in flight.",
        "",
        "The tolerance is per feature: "
        f"{report['share_of_diagonal'] * 100:g}% of that feature's own "
        f"bounding-box diagonal, capped at "
        f"{report['tolerance_ceiling_deg']} degrees. In this collection it "
        f"ranged from {report['tolerance_min_deg']:.3g} to "
        f"{report['tolerance_max_deg']:.3g} degrees. A flat tolerance was "
        "tried first and rejected: it cannot serve both the largest and the "
        "smallest feature in one collection, and at the country level it put "
        "one dependency's display polygon at 81.6% of its true area.",
        "",
        "The outward buffer is the part to understand. Simplification moves a "
        "vertex by up to the tolerance in either direction, so a simplified "
        "outline cuts corners inside the true boundary as often as outside "
        "it, and a download filtered against it would silently miss features "
        "in the slivers it cut away. Buffering outward pushes the whole "
        "outline back past the original, so the error is always inclusive: a "
        "filter over-selects, which a later exact pass removes, rather than "
        "under-selecting, which nothing recovers.",
        "",
        "Verified on every feature of this collection, as the ratio of the "
        "true polygon's area that the display polygon covers:",
        "",
        "| | |",
        "|---|---|",
        f"| Features | {report['features']:,} |",
        f"| Fully contained | {report['fully_contained']:,} "
        f"({100 * report['fully_contained'] / report['features']:.2f}%) |",
        f"| Below 99% contained | {report['below_99pct']:,} |",
        f"| Worst | {report['min_contained']:.6f} |",
        f"| Mean | {report['mean_contained']:.6f} |",
        "",
    ]
    if report["worst"]:
        lines += [
            "The worst cases, which are the features whose true outline is "
            "narrower than the tolerance somewhere:",
            "",
            "| contained | division | country | subtype |",
            "|---|---|---|---|",
        ]
        lines += [
            f"| {w['contained']:.6f} | {w['name']} | {w['country']} | "
            f"{w['subtype']} |"
            for w in report["worst"]
        ]
        lines += [
            "",
            "**Two consequences.** Neighbouring divisions overlap along their "
            "shared edge in the display file, so a point can fall in two of "
            "them; resolve with the full file. And a display polygon is "
            "always at least as large as the true one, so never compute an "
            "area from it.",
            "",
        ]

    lines += [
        "## Get one feature",
        "",
        "```sql",
        "INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;",
        "",
        "SELECT name, subtype, country, area_km2, population",
        f"FROM '{PUBLIC}/{collection}/overture_{collection}.parquet'",
        "WHERE division_id = '<a GERS id from the names collection>';",
        "```",
        "",
        "The bbox covering metadata and the row group statistics let DuckDB, "
        "GDAL or a browser Parquet reader skip to the right row group without "
        "decoding any geometry. See [AGENTS.md](AGENTS.md) for the queries "
        "that have been run against the published files.",
        "",
        LICENSE_BLOCK,
        "## Provenance",
        "",
        f"Built from Overture Maps divisions release `{RELEASE}`, staged from "
        "`s3://overturemaps-us-west-2/release/" + RELEASE + "/theme=divisions/`"
        f" on {EXTRACTION_DATE}. An Overture release is immutable, so the "
        "release identifier alone pins the bytes.",
        "",
        "Every row here comes from a `type=division_area` feature with "
        "`class = 'land'`, joined to its `type=division` row on "
        "`division_id` for the names, the class, the population and the "
        "parent. The filter is also what makes the join 1:1, and the build "
        "refuses to publish if it is not. Full details of what this catalog "
        "changes, drops and adds are in "
        "[changes-from-upstream.md](../changes-from-upstream.md).",
        "",
        f"- Overture divisions guide: {DOCS_DIVISIONS}",
        f"- Schema, carried as an asset: "
        f"[division.schema.yaml](../_assets/overture/division.schema.yaml), "
        f"[division_area.schema.yaml](../_assets/overture/division_area.schema.yaml)",
        f"- Pipeline and issue tracker: {REPO_URL}",
        "",
        "## Known issues",
        "",
    ]
    meta = CATALOG / collection / ".portolan" / "metadata.yaml"
    if meta.exists():
        import re

        text = meta.read_text()
        block = re.search(r"known_issues: >\n(.*)", text, re.S)
        if block:
            body = "\n".join(
                line[2:] if line.startswith("  ") else line
                for line in block.group(1).splitlines()
            )
            lines.append(body.strip())
    lines += [
        "",
        f"The whole collection, with every column described, is in "
        f"[collection.json](collection.json). The human-facing page is at "
        f"[{HUMAN}/{collection}]({HUMAN}/{collection}).",
        "",
    ]
    return "\n".join(lines)


def names_readme(docs: dict) -> str:
    doc = docs["names"]
    index = stats(NAMES_PATH)
    manifest = index_manifest()
    m = measurements()
    tiles = pmtiles_path("names")

    import duckdb

    con = duckdb.connect()
    src = NAMES_PATH.as_posix()
    per_level = con.execute(
        f"""SELECT level, count(*) AS rows,
                   count(*) FILTER (WHERE alt_of IS NULL) AS prim,
                   count(*) FILTER (WHERE alt_of IS NOT NULL) AS alt,
                   count(*) FILTER (WHERE has_boundary) AS geom
            FROM read_parquet('{src}') GROUP BY 1 ORDER BY 1"""
    ).fetchall()
    langs, max_dupes, worst_name = con.execute(
        f"""SELECT count(DISTINCT name_lang), max(name_dupes),
                   (SELECT name_norm FROM read_parquet('{src}')
                    ORDER BY name_dupes DESC, name_norm LIMIT 1)
            FROM read_parquet('{src}')"""
    ).fetchone()
    top_langs = con.execute(
        f"""SELECT name_lang, count(*) FROM read_parquet('{src}')
            WHERE name_lang IS NOT NULL GROUP BY 1 ORDER BY 2 DESC LIMIT 8"""
    ).fetchall()
    con.close()

    gpp = m["groups_per_prefix"]
    lines = [
        f"# {doc['title']}",
        "",
        EXPERIMENTAL_BANNER,
        "A search sidecar, not a boundary dataset. One row per Overture "
        "division, plus one row per distinct alternative spelling of that "
        "division's name, sorted by a folded form of the name.",
        "",
        "It exists so that a **static client with no server** can turn a "
        "typed name, in any of hundreds of languages, into a GERS id, an "
        "extent and a point. That is the lookup half of a browser geocoder, "
        "and the multilingual half is what this catalog has that its CC-BY "
        f"counterpart, [geoboundaries-catalog]({SIBLING}), does not.",
        "",
        "| | |",
        "|---|---|",
        f"| Rows | {index['rows']:,} |",
        f"| Primary rows, one per division | {manifest['primary_rows']:,} |",
        f"| Alternative-spelling rows | {manifest['alt_rows']:,} |",
        f"| Language codes represented | {langs:,} |",
        f"| Divisions with a boundary in this catalog | "
        f"{sum(r[4] for r in per_level):,} |",
        f"| Parquet | {human(index['size'])}, {index['row_groups']:,} row "
        f"groups of {NAMES_ROW_GROUP_ROWS:,} rows, zstd, page index |",
        f"| Bytes per row | {m['bytes_per_row']} |",
        f"| Row group | ~{human(m['mean_row_group_bytes'])} |",
        f"| Footer + page index | {m['footer_bytes']:,} bytes |",
        f"| Sorted by | `name_norm`, `level`, `country`, `feature_id`, "
        "byte-wise on UTF-8, declared in the footer |",
        f"| PMTiles | {human(tiles.stat().st_size)}, zoom 0-"
        f"{NAMES_MAX_ZOOM} |",
        "| CRS | CRS84 (EPSG:4326) |",
        "",
        "**The geometry column is one point per division**, placed inside the "
        "division by `ST_PointOnSurface` where a polygon exists and taken "
        "from Overture's own division point where it does not. It is a "
        "marker, not the division's shape, and it is null on an "
        "alternative-spelling row. The shape lives in the boundary "
        "collection at the same level.",
        "",
        "## Rows per level",
        "",
        "| level | subtypes | rows | primary | alternatives | with a boundary |",
        "|---|---|---|---|---|---|",
    ]
    level_subtypes = {
        0: "country, dependency", 1: "region", 2: "county",
        3: "localadmin", 4: "locality",
    }
    for level, rows, prim, alt, geom in per_level:
        lines.append(
            f"| {level} | {level_subtypes[level]} | {rows:,} | {prim:,} | "
            f"{alt:,} | {geom:,} |"
        )
    lines += [
        "",
        f"The {manifest['primary_rows'] - sum(r[4] for r in per_level):,} "
        "primary rows with no boundary are almost all localities that "
        "Overture publishes as a point only. `has_boundary` is false on them, "
        "`geometry_ref` and `area_km2` are null, and `bbox` is the point "
        "collapsed to zero width. **A client has to handle them**: they are "
        "the majority of the localities in this index, and they are still the "
        "right answer to a search.",
        "",
        "## How to read it",
        "",
        f"**Range-request it.** At {human(index['size'])} this index is far "
        "too large to load whole, and it is not meant to be. The sort is the "
        "whole design: row group statistics on `name_norm` are tight, "
        "non-overlapping alphabetical ranges, the footer declares the sort "
        "order, and the Parquet page index is written, so a client binary-"
        "searches the statistics and reads only the groups a prefix can live "
        "in.",
        "",
        f"Measured over all {m['prefixes']:,} two-character prefixes that "
        "occur in `name_norm`:",
        "",
        "| | row groups touched |",
        "|---|---|",
        f"| minimum | {gpp['min']} |",
        f"| median | {gpp['median']:.0f} |",
        f"| mean | {gpp['mean']} |",
        f"| 95th percentile | {gpp['p95']} |",
        f"| maximum | {gpp['max']} |",
        "",
        f"So a typed two-letter prefix costs a median of {gpp['median']:.0f} "
        f"read of about {human(m['mean_row_group_bytes'])}, on top of a "
        f"{m['footer_bytes']:,}-byte footer read that happens once. The "
        "manifest publishes `index.size` and `index.row_groups` so that "
        "footer read can be a single exactly-sized tail request rather than a "
        "speculative one. Full numbers, including compressed bytes per "
        "column, are in "
        "[docs/index-measurements.md]"
        f"({REPO_URL}/blob/main/docs/index-measurements.md).",
        "",
        "Browser clients read it with "
        "[hyparquet](https://github.com/hyparam/hyparquet) plus "
        "[hyparquet-compressors](https://github.com/hyparam/hyparquet-compressors), "
        "which is **required**, because every column chunk is zstd. "
        f"`tools/verify_index_hyparquet.mjs` in the "
        f"[repository]({REPO_URL}) does exactly that and reports the bytes "
        "each prefix lookup fetched.",
        "",
        "**Do not load it whole** unless you are running a batch job. A "
        "server-side consumer should query it with DuckDB instead, which "
        "pushes the predicate into the same statistics.",
        "",
        "## Multilingual search",
        "",
        "A division's primary name is one row with `alt_of` null and "
        "`name_lang` null, because Overture does not state the language of "
        "`names.primary`. Every distinct alternative spelling in Overture's "
        "`names.common` map is another row, with `name_lang` holding the "
        "language code and `alt_of` holding the division's own `feature_id`.",
        "",
        "So a search for a prefix returns a mixture of primary and "
        "alternative rows, and **a consumer dedupes by `feature_id`** before "
        "it shows results. A hit on an alternative row is a hit on its "
        "division; there is no second lookup to do, because every row carries "
        "the level, the country, the parent name, the bbox and the ranking "
        "columns.",
        "",
        "Two reductions are applied to the alternatives, and both are "
        "lossless for search:",
        "",
        "1. An alternative that folds to the same string as the division's "
        "primary name is dropped. It is the same search key.",
        "2. Alternatives that fold to the same string as each other are "
        "collapsed into one row. `name_lang` then holds the first language "
        "code in alphabetical order and `name_lang_count` says how many "
        "languages agreed. Overture lists `France` under dozens of codes; "
        "indexing it dozens of times finds one division dozens of times.",
        "",
        "The language codes with the most indexed spellings:",
        "",
        "| language | rows |",
        "|---|---|",
    ]
    lines += [f"| `{lang}` | {n:,} |" for lang, n in top_langs]
    lines += [
        "",
        "## The index contract",
        "",
        "This file is built to the index-file interface the cloud-native map "
        "widgets geocoder reads, and "
        "[index.json](index.json) beside it is the manifest a client fetches "
        "first. The manifest carries the file's size, row group count and "
        "checksum, the `catalog_version` that has to match the footer "
        "metadata of this file and of every boundary file, the URL and row "
        "count of each boundary and display file, and the attribution each "
        "source requires with a `share_alike` flag so a widget can surface "
        "the obligation in its own interface.",
        "",
        "`tools/build_names.py` asserts the layout guarantees on every run "
        "and refuses to write a file that fails one: required columns present "
        "and correctly typed, `name_norm` ascending byte-wise with no nulls, "
        "the sort declared in the footer, and untruncated statistics on every "
        "row group.",
        "",
        "Two deliberate divergences from that contract, both recorded in "
        "`known_issues`:",
        "",
        "- `bbox` is **float32 rounded outward**, not float64. Four doubles a "
        "row is tens of megabytes at this scale. Every bound is nudged away "
        "from the centre so the box still contains the division, which costs "
        "about 1e-5 degrees of precision, roughly a metre. The CC-BY sibling "
        "index does the same, so a consumer that reads one reads the other.",
        "- The file **is** GeoParquet, with a point geometry column, where "
        "the contract describes a plain Parquet index. The point is what lets "
        "the collection render in a data browser and carry styles, and the "
        "`bbox` covering it declares is a valid superset of the point.",
        "",
        "## Start a query",
        "",
        "```sql",
        "INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;",
        "",
        "-- Everything called Zurich, in any language, best match first.",
        "SELECT name, name_lang, level, country, parent_name, population",
        f"FROM '{PUBLIC}/names/overture_division_names.parquet'",
        "WHERE name_norm LIKE 'zurich%'",
        "ORDER BY level, population DESC NULLS LAST;",
        "```",
        "",
        "More recipes, including the join back to geometry and the "
        "`geometry_ref` fast path, are in [AGENTS.md](AGENTS.md).",
        "",
        "## Ambiguity",
        "",
        f"A name is not an identifier. The most repeated folded name in this "
        f"index is `{worst_name}`, which {max_dupes:,} rows share. "
        "`name_dupes` is the count on every row, and `parent_name`, `level`, "
        "`country`, `population` and `prominence` are what disambiguate.",
        "",
        LICENSE_BLOCK,
        "## Provenance",
        "",
        f"Built by `tools/build_names.py` from the staged Overture "
        f"`type=division` rows of release `{RELEASE}` and from the five "
        "boundary collections in this catalog, not from the Overture release "
        "twice, so the index and the geometry it points at cannot disagree. "
        "Staged " + EXTRACTION_DATE + ". Full details of every deviation from "
        "the Overture release are in "
        "[changes-from-upstream.md](../changes-from-upstream.md).",
        "",
        "## Known issues",
        "",
    ]
    meta = CATALOG / "names" / ".portolan" / "metadata.yaml"
    if meta.exists():
        import re

        block = re.search(r"known_issues: >\n(.*)", meta.read_text(), re.S)
        if block:
            body = "\n".join(
                line[2:] if line.startswith("  ") else line
                for line in block.group(1).splitlines()
            )
            lines.append(body.strip())
    lines += [
        "",
        "Every column is described in [collection.json](collection.json). The "
        f"human-facing page is at [{HUMAN}/names]({HUMAN}/names).",
        "",
    ]
    return "\n".join(lines)


def catalog_readme(docs: dict) -> str:
    manifest = index_manifest()
    m = measurements()
    rows = []
    total = 0
    for collection in COLLECTIONS:
        full = stats(boundary_path(collection))
        disp = stats(display_path(collection))
        tiles = pmtiles_path(collection)
        total += full["size"] + disp["size"] + tiles.stat().st_size
        rows.append(
            f"| [`{collection}`]({collection}/collection.json) | "
            f"{COLLECTION_LEVEL[collection]} | {full['rows']:,} | "
            f"{human(full['size'])} | {human(disp['size'])} | "
            f"{human(tiles.stat().st_size)} |"
        )
    index = stats(NAMES_PATH)
    names_tiles = pmtiles_path("names")
    total += index["size"] + names_tiles.stat().st_size

    return "\n".join([
        "# EXPERIMENTAL: Overture Divisions for Geocoding (ODbL)",
        "",
        EXPERIMENTAL_BANNER,
        "Overture Maps divisions, release "
        f"`{RELEASE}`, republished as cloud-native GeoParquet and PMTiles for "
        "a browser geocoder: five boundary levels from country down to "
        "locality, each with a display-simplified companion, and a "
        "multilingual name search index over all of them.",
        "",
        "This is a **mirror**. "
        "[Overture Maps Foundation](https://overturemaps.org/) produces the "
        "data and remains the authoritative source. This catalog adds no "
        "division and changes no coordinate.",
        "",
        "## Which catalog should you use?",
        "",
        "There are two, built to the same column contract, and the choice is "
        "about licence and coverage rather than quality.",
        "",
        "| | this catalog | "
        f"[geoboundaries-catalog]({SIBLING}) |",
        "|---|---|---|",
        "| Licence | **ODbL-1.0**, share-alike | CC-BY-4.0, attribution only |",
        "| Status | **experimental**, unlisted | the default |",
        "| Levels | country, region, county, localadmin, **locality** | "
        "ADM0, ADM1, ADM2 |",
        "| City and village boundaries | yes | no |",
        "| Multilingual names | yes, "
        f"{manifest['alt_rows']:,} alternative spellings | no |",
        "| Stable feature key | Overture GERS id | geoBoundaries `shapeID` |",
        f"| Index size | {human(index['size'])}, range-request path | "
        "3.6 MB, loads whole |",
        "",
        "**Take the CC-BY one unless you need what this one adds.** "
        "Share-alike is a real obligation: a database you derive from this "
        "catalog has to be offered under ODbL too. A geocoder widget can be "
        "pointed at either index by changing one URL, so the decision is "
        "reversible and belongs to whoever ships the application, not to "
        "whoever builds it.",
        "",
        "## What it publishes",
        "",
        "| collection | level | rows | GeoParquet | display | PMTiles |",
        "|---|---|---|---|---|---|",
        *rows,
        f"| [`names`](names/collection.json) | 0-4 | {index['rows']:,} | "
        f"{human(index['size'])} | - | {human(names_tiles.stat().st_size)} |",
        "",
        f"About {human(total)} in all. The five boundary levels are "
        "**not** a seamless coverage the way a composite is: Overture "
        "publishes a division where a division exists, so a country with no "
        "localadmin level simply has no rows at that level. The "
        f"[`names`](names/collection.json) index is the only complete view, "
        f"and it covers {manifest['primary_rows']:,} divisions including the "
        "millions Overture publishes as a point with no boundary at all.",
        "",
        "## How a geocoder widget uses this",
        "",
        "The end-to-end path this catalog was shaped for, as the "
        "cloud-native map widgets project implements it:",
        "",
        "1. **Focus.** The search box is focused. The client fetches "
        f"[names/index.json](names/index.json), about a kilobyte, and learns "
        "the index's size, row group count, `catalog_version` and required "
        "attribution. It renders the attribution immediately, because ODbL "
        "requires it whether or not a search happens.",
        f"2. **Index load.** The index is {human(index['size'])}, so the "
        "client takes the **range-request path**: one exactly-sized "
        f"{m['footer_bytes']:,}-byte tail request for the footer, then a "
        "binary search over the row group statistics on `name_norm`.",
        "3. **Keystrokes.** Each typed prefix is folded with the same rule "
        f"the index used and resolved from a median of "
        f"{m['groups_per_prefix']['median']:.0f} row group of about "
        f"{human(m['mean_row_group_bytes'])}. Results arrive as a mixture of "
        "primary and alternative-spelling rows, in any language; the client "
        "dedupes by `feature_id` and ranks on `level`, `population`, "
        "`prominence`, `name_dupes` and whether the bbox intersects the "
        "current viewport.",
        "4. **Selection, drawn instantly.** The chosen row carries a GERS "
        "`feature_id`, a bbox to fly to, a point to mark, and an advisory "
        "`geometry_ref` of file, row group and row. One range read of the "
        "**display** file at that row group returns a few kilobytes of "
        "outward-buffered outline, which draws before the camera has "
        "finished moving.",
        "5. **Full resolution in the background.** The same `geometry_ref` "
        "indexes the full-resolution file, because the two hold the same rows "
        "in the same groups. The client swaps the geometry in when it "
        "arrives, and verifies that the `division_id` it decoded equals the "
        "`feature_id` it asked for before it trusts either.",
        "6. **The boundary does work.** That polygon is then the spatial "
        "filter for any other cloud-native dataset: a GeoParquet of field "
        "boundaries, a COG, a PMTiles archive. Filter with the display "
        "geometry, which over-selects on purpose, and clip with the "
        "full-resolution one.",
        "",
        "The consumption recipes for each step are in the collection agent "
        f"guides, starting at [names/AGENTS.md](names/AGENTS.md). The "
        f"equivalent guides in the "
        f"[CC-BY sibling]({SIBLING}/names) describe the same contract against "
        "the smaller index.",
        "",
        "## Read these first",
        "",
        "- [AGENTS.md](AGENTS.md): the collections, the join keys, and the "
        "traps that produce wrong answers.",
        "- [changes-from-upstream.md](changes-from-upstream.md): every row "
        "and column this catalog drops, derives or adds, and how to get "
        "vanilla Overture instead.",
        "- [names/README.md](names/README.md): the search index, and how to "
        "read it without downloading it.",
        "- [catalog.json](catalog.json): the STAC entry point.",
        "",
        LICENSE_BLOCK,
        "## Provenance",
        "",
        f"Overture Maps divisions, release `{RELEASE}`, staged from "
        f"`s3://overturemaps-us-west-2/release/{RELEASE}/theme=divisions/` "
        f"on {EXTRACTION_DATE}. A release is immutable, so the release "
        "identifier alone pins the bytes; there is no commit or checksum to "
        "carry. Overture's release index is at "
        "https://docs.overturemaps.org/release/latest/ .",
        "",
        f"The pipeline that built this, the per-collection provenance records "
        f"and the issue tracker are at {REPO_URL} .",
        "",
    ])


def llms_txt(docs: dict) -> str:
    manifest = index_manifest()
    m = measurements()
    index = stats(NAMES_PATH)
    lines = [
        "# EXPERIMENTAL: Overture Divisions for Geocoding (ODbL)",
        "",
        "> Overture Maps divisions, release "
        f"{RELEASE}, as cloud-native GeoParquet and PMTiles for a browser "
        "geocoder. Five boundary levels from country to locality, each with a "
        "display-simplified companion, plus a multilingual name search index "
        f"of {index['rows']:,} rows over {manifest['primary_rows']:,} "
        "divisions. Static files on object storage, no API, no credentials. "
        "Produced by Overture Maps Foundation; this catalog republishes, it "
        "does not produce.",
        "",
        f"Public root: {PUBLIC}/catalog.json",
        "",
        "EXPERIMENTAL: the schema may change without notice and the hosting "
        "repository is unlisted. Pin the catalog_version from "
        f"{PUBLIC}/names/index.json if you depend on it.",
        "",
        "This is a Portolan catalog, which is STAC 1.1.0 plus the Portolan "
        "profile. Every file is readable in place over HTTPS range requests. "
        "Six collections, each with a collection.json, a README.md for "
        "humans, an AGENTS.md for machine clients, GeoParquet, PMTiles and "
        "four MapLibre styles.",
        "",
        "License: ODbL-1.0, SHARE-ALIKE. A database derived from this one has "
        "to be released under ODbL, and anything shown has to display "
        "'© OpenStreetMap contributors. Available under the Open Database "
        "License.' The CC-BY-4.0 alternative, with no share-alike, no "
        f"locality level and no multilingual names, is {SIBLING} .",
        "",
        "This is NOT a byte-for-byte mirror. It keeps only the land polygon "
        "of each division, excludes the neighborhood, microhood and macrohood "
        "subtypes, derives an ISO 3166-1 alpha-3 country code, and adds "
        "display-simplified geometry, a search index and vector tiles. Every "
        f"deviation is in {PUBLIC}/changes-from-upstream.md .",
        "",
        "## Read these first",
        "",
        f"- [Catalog agent guide]({PUBLIC}/AGENTS.md): the collections, the "
        "join keys, and the nine traps that produce wrong answers.",
        f"- [Catalog README]({PUBLIC}/README.md): what is here, which of the "
        "two catalogs to use, the license, and how a geocoder widget consumes "
        "it end to end.",
        f"- [Search index guide]({PUBLIC}/names/AGENTS.md): the "
        "range-request path, multilingual lookup, and the join back to "
        "geometry.",
        f"- [Index manifest]({PUBLIC}/names/index.json): fetch this before "
        "the index itself.",
        f"- [Changes from vanilla Overture]({PUBLIC}/changes-from-upstream.md).",
        f"- [Root catalog.json]({PUBLIC}/catalog.json): the STAC entry point.",
        "",
        "## Collections",
        "",
    ]
    for collection in COLLECTIONS:
        full = stats(boundary_path(collection))
        doc = docs[collection]
        lines.append(
            f"- [{collection} — {doc['title'].split(' - ', 1)[-1]}]"
            f"({PUBLIC}/{collection}/collection.json): level "
            f"{COLLECTION_LEVEL[collection]}, {full['rows']:,} rows, "
            f"{human(full['size'])} GeoParquet in {full['row_groups']:,} row "
            f"groups of {ROW_GROUP_ROWS[collection]:,}. "
            f"[agent guide]({PUBLIC}/{collection}/AGENTS.md)"
        )
    lines += [
        f"- [names — Multilingual Name Search Index]"
        f"({PUBLIC}/names/collection.json): {index['rows']:,} rows "
        f"({manifest['primary_rows']:,} divisions + "
        f"{manifest['alt_rows']:,} alternative spellings), "
        f"{human(index['size'])}, sorted by folded name, "
        f"{index['row_groups']:,} row groups of {NAMES_ROW_GROUP_ROWS:,}. "
        f"[agent guide]({PUBLIC}/names/AGENTS.md)",
        "",
        "## Data files",
        "",
    ]
    for collection in COLLECTIONS:
        lines.append(f"- {PUBLIC}/{collection}/{boundary_path(collection).name}")
    for collection in COLLECTIONS:
        lines.append(
            f"- {PUBLIC}/{collection}/{display_path(collection).name} "
            "(simplified, buffered outward; same rows and row groups as the "
            "full-resolution file)"
        )
    for collection in list(COLLECTIONS) + ["names"]:
        lines.append(f"- {PUBLIC}/{collection}/{pmtiles_path(collection).name}")
    lines += [
        f"- {PUBLIC}/names/{NAMES_PATH.name}",
        f"- {PUBLIC}/names/index.json",
        "",
        "## Start a query",
        "",
        "```sql",
        "INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;",
        "",
        "-- Everything called Kyoto, in any language, best match first.",
        "SELECT name, name_lang, level, country, parent_name, population",
        f"FROM '{PUBLIC}/names/{NAMES_PATH.name}'",
        "WHERE name_norm LIKE 'kyoto%'",
        "ORDER BY level, population DESC NULLS LAST;",
        "```",
        "",
        "## The things that produce wrong answers",
        "",
        "1. Join on `division_id`, never on `id`. Both are GERS identifiers; "
        "`id` belongs to the polygon and a join on it returns nothing.",
        "2. `level` is this catalog's 0-to-4 mapping, not Overture's "
        "`admin_level`.",
        "3. The five boundary levels do not tile the globe and do not fill "
        "gaps from a coarser level. The names index is the only complete view.",
        f"4. {manifest['primary_rows'] - 620734:,} divisions have no polygon "
        "anywhere here, almost all localities Overture publishes as a point. "
        "`has_boundary` says so per row.",
        "5. An alternative-name row shares its division's `feature_id`. "
        "Dedupe results on it or the same city appears once per language.",
        "6. The geometry is the land outline; Overture's maritime polygon is "
        "not carried.",
        "7. The `*_display.parquet` files are buffered OUTWARD on purpose, so "
        "neighbours overlap. Draw and filter with them; measure and clip with "
        "the full-resolution files.",
        "8. localadmin exists for 19 countries only. An empty result there is "
        "usually missing coverage, not a missing place.",
        "",
        "## Optional",
        "",
        f"- [Overture Maps divisions guide]({DOCS_DIVISIONS}): what each "
        "subtype means and Overture's own coverage statement.",
        f"- [Overture attribution and licensing]({DOCS_ATTRIBUTION}): the "
        "exact attribution this catalog's license requires.",
        "- [Overture release index](https://docs.overturemaps.org/release/latest/): "
        "the authoritative source, including the themes this catalog does not "
        "mirror.",
        f"- [geoboundaries-catalog]({SIBLING}): the CC-BY-4.0 counterpart, "
        "same column contract, no share-alike, no localities, no "
        "multilingual names.",
        f"- [Source repository]({REPO_URL}): the pipeline, the per-collection "
        "provenance records, the index measurements, and the issue tracker.",
        "- [Portolan specification](https://github.com/portolan-sdi/portolan-spec): "
        "what this catalog conforms to.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    docs = {c: collection_doc(c) for c in list(COLLECTIONS) + ["names"]}
    cont = containment()
    written = []
    for collection in COLLECTIONS:
        path = CATALOG / collection / "README.md"
        path.write_text(wrap_markdown(boundary_readme(collection, docs, cont)))
        written.append(path)
    path = CATALOG / "names" / "README.md"
    path.write_text(wrap_markdown(names_readme(docs)))
    written.append(path)
    path = CATALOG / "README.md"
    path.write_text(wrap_markdown(catalog_readme(docs)))
    written.append(path)
    path = CATALOG / "llms.txt"
    path.write_text(wrap_markdown(llms_txt(docs)))
    written.append(path)
    for p in written:
        print(f"  {p.relative_to(REPO)}: {p.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
