#!/usr/bin/env python3
"""Generate every AGENTS.md, running each query it documents.

    python3 tools/make_agents.py

Every query in a published agent guide has to work. A recipe that fails on
the first try costs the reader the time to debug someone else's mistake, and
no validator catches it. So the guides are generated: each query is defined
once here, run against the built file, and written out together with the
output it actually produced. A query that errors fails this script, and a
query whose result changed shows up as a diff in the generated file.

The SQL in the generated guide names the **published URL**, because that is
what a reader runs. The SQL this script executes names the local staged file,
which holds the same bytes. The two differ only in the table reference, which
is substituted from one template, so they cannot drift apart.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

from ovcommon import (
    CATALOG_VERSION,
    COLLECTIONS,
    COLLECTION_LEVEL,
    DOCS_DIVISIONS,
    DOCS_SCHEMA_DIVISION,
    DOCS_SCHEMA_DIVISION_AREA,
    NAMES_PATH,
    NAMES_ROW_GROUP_ROWS,
    RELEASE,
    ROW_GROUP_ROWS,
    WORK,
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
SIBLING = "https://source.coop/portolan-mirrors/geoboundaries-catalog"

TIER_NOTE = """Each factual claim is tagged with how it was established:
**[attested]** Overture states it, with a link;
**[researched]** found outside the source's own metadata, with a link;
**[derived]** computed from the published data, with the query that computed
it. Every query below was run against the built file before this guide was
written; the output under each one is what it returned."""

RULE = """**One rule survives every edit to this file.** Every claim here is
either quoted from a source or measured from the data. If you cannot point at
where a fact came from, it does not belong in this file. An agent acting on an
invented join key or an invented column name produces a confident wrong
answer, and nothing downstream catches it."""

PREAMBLE = """```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
```

Every file here is readable in place over HTTPS range requests. No
credentials, no API, no server."""

def license_warning(prefix: str = "../") -> str:
    """The licence and status banner, with the manifest link relative."""
    return LICENSE_WARNING_TEMPLATE.replace("{PREFIX}", prefix)


LICENSE_WARNING_TEMPLATE = f"""> [!IMPORTANT]
> **ODbL-1.0, share-alike.** A database you derive from this collection has to
> be offered under ODbL as well, and anything you show has to carry
> `© OpenStreetMap contributors. Available under the Open Database License.`
> If that does not work for your use, the CC-BY-4.0 counterpart is
> [geoboundaries-catalog]({SIBLING}).

> [!WARNING]
> **EXPERIMENTAL.** The schema may change without notice. Pin the
> `catalog_version` (`{CATALOG_VERSION}`) from
> [index.json]({{PREFIX}}names/index.json) if you depend on it."""


@dataclass
class Q:
    """One documented query, with the table reference left as a template."""

    title: str
    sql: str
    note: str = ""
    limit: int = 12
    tables: dict[str, str] = field(default_factory=dict)


def listing(rows: list[tuple[str, str]]) -> list[str]:
    """A fixed-width two-column listing for a fenced block."""
    width = max(len(name) for name, _ in rows)
    return [f"{name.ljust(width)}  {value}" for name, value in rows]


def table_ref(path: Path, *, public: bool) -> str:
    """How a query names a file: a URL in the guide, a local path when run."""
    if public:
        rel = path.relative_to(path.parent.parent)
        return f"'{PUBLIC}/{rel.as_posix()}'"
    return f"read_parquet('{path.as_posix()}')"


def path_ref(path: Path, *, public: bool) -> str:
    """The same file as a bare quoted path, for a function that takes one.

    `parquet_metadata` takes a path, not a table, so it cannot be handed the
    `read_parquet(...)` form the other queries use.
    """
    if public:
        rel = path.relative_to(path.parent.parent)
        return f"'{PUBLIC}/{rel.as_posix()}'"
    return f"'{path.as_posix()}'"


def render(con, q: Q, tables: dict[str, Path]) -> list[str]:
    """Run a query and return the markdown block for it."""
    refs = {}
    for key, value in tables.items():
        refs[key] = table_ref(value, public=True)
        refs[f"{key}_PATH"] = path_ref(value, public=True)
    doc_sql = q.sql.format(**refs)
    refs = {}
    for key, value in tables.items():
        refs[key] = table_ref(value, public=False)
        refs[f"{key}_PATH"] = path_ref(value, public=False)
    run_sql = q.sql.format(**refs)
    try:
        rel = con.sql(run_sql)
        columns = rel.columns
        rows = rel.fetchall()
    except Exception as exc:  # noqa: BLE001 - the point is to fail loudly
        raise SystemExit(f"query failed: {q.title}\n{run_sql}\n{exc}") from exc

    widths = [len(c) for c in columns]
    shown = rows[: q.limit]
    cells = []
    for row in shown:
        out = []
        for i, value in enumerate(row):
            text = "NULL" if value is None else str(value)
            if isinstance(value, float):
                text = f"{value:.6g}"
            out.append(text)
            widths[i] = max(widths[i], len(text))
        cells.append(out)
    header = "  ".join(c.ljust(widths[i]) for i, c in enumerate(columns))
    body = [
        "  ".join(v.ljust(widths[i]) for i, v in enumerate(row)) for row in cells
    ]
    block = [
        f"**{q.title}** **[derived]**",
        "",
        "```sql",
        doc_sql.strip(),
        "```",
        "",
        "```",
        header.rstrip(),
        *[line.rstrip() for line in body],
    ]
    if len(rows) > len(shown):
        block.append(f"... {len(rows) - len(shown):,} more rows")
    block.append("```")
    if q.note:
        block += ["", q.note]
    block.append("")
    return block


# ---------------------------------------------------------------------------
# Boundary collections
# ---------------------------------------------------------------------------
def boundary_queries(collection: str) -> list[Q]:
    return [
        Q(
            "What the file holds, by subtype",
            "SELECT subtype, count(*) AS n, count(DISTINCT country) AS countries,\n"
            "       round(min(area_km2), 2) AS min_km2,\n"
            "       round(max(area_km2)) AS max_km2\n"
            "FROM {T}\n"
            "GROUP BY 1 ORDER BY 2 DESC;",
        ),
        Q(
            "Resolve one division by its GERS id, the way a geocoder does",
            "SELECT name, subtype, country, parent_name, area_km2, vertices,\n"
            "       bbox.xmin, bbox.ymin, bbox.xmax, bbox.ymax\n"
            "FROM {T}\n"
            "WHERE division_id = (SELECT division_id FROM {T}\n"
            "                     ORDER BY area_km2 DESC LIMIT 1);",
            note=(
                "`division_id` is the join key and the value the names "
                "collection publishes as `feature_id`. **`id` is a different "
                "GERS identifier**, belonging to the polygon rather than to "
                "the division, and joining on it finds nothing **[attested: "
                f"[division_area schema]({DOCS_SCHEMA_DIVISION}) ]**."
            ),
        ),
        Q(
            "A bounding-box query, which the covering metadata makes cheap",
            "SELECT name, country, round(area_km2) AS area_km2\n"
            "FROM {T}\n"
            "WHERE bbox.xmin < 12.5 AND bbox.xmax > 11.5\n"
            "  AND bbox.ymin < 56.0 AND bbox.ymax > 55.0\n"
            "ORDER BY area_km2 DESC;",
            note=(
                "The `bbox` struct is declared as the GeoParquet 1.1 covering "
                "for the geometry column, so a reader prunes row groups on it "
                "without decoding any WKB. Filter on `bbox` first and call "
                "`ST_Intersects` on what survives."
            ),
        ),
        Q(
            "How much the display companion saves",
            "SELECT count(*) AS rows,\n"
            "       sum(f.vertices) AS full_vertices,\n"
            "       sum(d.vertices) AS display_vertices,\n"
            "       round(100 - 100.0 * sum(d.vertices) / sum(f.vertices), 1)\n"
            "         AS pct_fewer\n"
            "FROM {T} f JOIN {D} d USING (division_id);",
            note=(
                "The two files hold the same rows in the same order in the "
                "same row groups, so this join is a formality: row *i* of one "
                "is row *i* of the other, which is what makes the search "
                "index's `geometry_ref` valid against both."
            ),
        ),
        Q(
            "The most multilingual divisions in this collection",
            "SELECT name, country, name_langs\n"
            "FROM {T}\n"
            "ORDER BY name_langs DESC, name LIMIT 8;",
            note=(
                "`name_langs` counts the language codes in Overture's "
                "`names.common` map for that division. The spellings "
                "themselves are indexed in the "
                "[names collection](../names/collection.json)."
            ),
        ),
    ]


BOUNDARY_TRAPS = {
    "country": [
        "**`id` is not the join key.** Join on `division_id`.",
        "**This collection holds two subtypes.** 219 countries and 53 "
        "dependencies, which Overture files at `admin_level` 1. Filter on "
        "`subtype` if you want only sovereign states.",
        "**`country` is alpha-3 and derived; `country_iso2` is Overture's "
        "own alpha-2.** 25 rows carry a synthetic code with no alpha-3 "
        "equivalent, and on those two rows the two columns are equal and "
        "two letters long.",
        "**Antarctica stops at latitude -85.0511289**, the Web Mercator "
        "limit, because that is where Overture's land polygon ends.",
        "**The geometry is the land outline.** Overture's `maritime` polygon "
        "is not carried, so an offshore point is in no row here.",
    ],
    "region": [
        "**`id` is not the join key.** Join on `division_id`.",
        "**`admin_level` is 1 on most rows and 2 on 307 of them.** That is "
        "Overture's own value; this catalog's `level` for the whole "
        "collection is 1.",
        "**`local_type` is a flattened string, not Overture's map.** Read "
        "the release itself for every localized form.",
    ],
    "county": [
        "**`id` is not the join key.** Join on `division_id`.",
        "**`admin_level` takes four values here**, 0 to 3, although 38,708 "
        "of 38,937 rows are 2. Do not filter on it to find counties; filter "
        "on `subtype`.",
        "**This is not the same unit set as geoBoundaries ADM2.** The "
        f"[CC-BY counterpart]({SIBLING}) has 49,349 ADM2 rows against 38,937 "
        "here, and the two use different identifiers, so a join between the "
        "catalogs needs a spatial match or a name match.",
    ],
    "localadmin": [
        "**`id` is not the join key.** Join on `division_id`.",
        "**Coverage is 19 countries, not the world.** An empty result almost "
        "always means the country publishes no localadmin level. Query the "
        "collection for the list before you assume a gap is a bug.",
        "**`admin_level` is absent**, because Overture does not require it "
        "below county. Use this catalog's `level`, 3.",
    ],
    "locality": [
        "**`id` is not the join key.** Join on `division_id`.",
        "**This is only the 15.85% of Overture's localities that have a "
        "polygon.** 2,952,062 more exist as a point and are in the names "
        "collection with `has_boundary = false`. Treating this collection as "
        "the list of settlements understates it by a factor of six.",
        "**`class` is null on 113,393 rows.** Overture classed the rest.",
        "**`prominence` is cartographic guidance, not a measurement.** It is "
        "the best ranking signal here and still not a statistic.",
    ],
}


NAMES_QUERIES = [
    Q(
        "Rows per level, and how many have a boundary in this catalog",
        "SELECT level, count(*) AS rows,\n"
        "       count(*) FILTER (WHERE alt_of IS NULL) AS primary_rows,\n"
        "       count(*) FILTER (WHERE alt_of IS NOT NULL) AS alt_rows,\n"
        "       count(*) FILTER (WHERE has_boundary) AS with_boundary\n"
        "FROM {T}\n"
        "GROUP BY 1 ORDER BY 1;",
        note=(
            "Level 0 is country and dependency, 1 region, 2 county, 3 "
            "localadmin, 4 locality. A level-4 row with "
            "`has_boundary = false` is a place Overture publishes as a point "
            "only; it is still the right answer to a search, and `bbox` is "
            "that point collapsed to zero width."
        ),
    ),
    Q(
        "A prefix lookup, which is what a keystroke costs",
        "SELECT name, name_lang, level, country, parent_name, population\n"
        "FROM {T}\n"
        "WHERE name_norm LIKE 'zurich%'\n"
        "ORDER BY level, population DESC NULLS LAST;",
        note=(
            "`LIKE 'prefix%'` is the whole access pattern. The file is sorted "
            "by `name_norm` byte-wise on UTF-8 and the sort is declared in the "
            "footer, so DuckDB, GDAL and a browser Parquet reader all prune to "
            "the one or two row groups a prefix can live in. **Fold the user's "
            "input the same way the index did** before you compare: NFD, drop "
            "combining marks, keep only letters, digits, space, hyphen and "
            "apostrophe, collapse whitespace, lowercase."
        ),
    ),
    Q(
        "The same place, found in another language",
        "SELECT name, name_lang, name_lang_count, level, country, feature_id\n"
        "FROM {T}\n"
        "WHERE name_norm IN ('munchen', 'monaco di baviera', 'muenchen')\n"
        "ORDER BY name_norm;",
        note=(
            "Several rows, one `feature_id`. **Dedupe by `feature_id`** before "
            "you show a result list, and keep whichever row matched so you can "
            "show the user the spelling they typed. `name_lang_count` says how "
            "many of Overture's language codes agreed on that spelling; the "
            "index keeps one row per distinct folded spelling, not one per "
            "language."
        ),
    ),
    Q(
        "How ambiguous the common names are",
        "SELECT name_norm, count(*) AS rows,\n"
        "       count(DISTINCT feature_id) AS divisions\n"
        "FROM {T}\n"
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 10;",
        note=(
            "`name_dupes` carries this count on every row, so a client does "
            "not have to compute it. Disambiguate with `parent_name`, "
            "`level`, `country` and `population`."
        ),
    ),
    Q(
        "The geometry_ref fast path: index row to boundary row group",
        "SELECT n.name, n.level, n.feature_id,\n"
        "       n.geometry_ref.file AS file,\n"
        "       n.geometry_ref.row_group AS row_group,\n"
        "       n.geometry_ref.row AS row\n"
        "FROM {T} n\n"
        "WHERE n.name_norm = 'bengaluru' AND n.alt_of IS NULL;",
        note=(
            "`geometry_ref` is **advisory**. It says which row group of which "
            "boundary file holds the geometry, and the display companion holds "
            "the same row at the same offset, so `resolution: 'both'` is two "
            "range reads at one row index rather than a join. A consumer must "
            "still decode `division_id` for that row and assert it equals "
            "`feature_id`, and fall back to a lookup on mismatch: the hint is "
            "only valid while the `catalog_version` in "
            "[index.json](index.json) matches the footer metadata of both "
            "files."
        ),
    ),
    Q(
        "Join back to the real geometry",
        "SELECT n.name, n.level, b.subtype, b.area_km2, b.vertices\n"
        "FROM {T} n\n"
        "JOIN {B} b ON b.division_id = n.feature_id\n"
        "WHERE n.name_norm LIKE 'sao paulo%' AND n.level = 2;",
        note=(
            "**`feature_id` joins to `division_id`**, and the collection to "
            "join is the one at the row's `level`: 0 country, 1 region, 2 "
            "county, 3 localadmin, 4 locality. Joining a level-4 row to the "
            "county collection returns nothing, and joining on `id` returns "
            "nothing at any level."
        ),
    ),
    Q(
        "Which languages carry the most indexed spellings",
        "SELECT name_lang, count(*) AS rows\n"
        "FROM {T} WHERE name_lang IS NOT NULL\n"
        "GROUP BY 1 ORDER BY 2 DESC LIMIT 12;",
    ),
    Q(
        "Row group statistics on name_norm, the thing the sort buys",
        "SELECT row_group_id AS row_group, num_values AS rows,\n"
        "       stats_min_value AS first_name_norm,\n"
        "       stats_max_value AS last_name_norm\n"
        "FROM parquet_metadata({T_PATH})\n"
        "WHERE path_in_schema = 'name_norm'\n"
        "  AND row_group_id IN (0, 1, 2, 400, 875);",
        note=(
            "Tight, non-overlapping alphabetical ranges. A client binary-"
            "searches these and reads one group. The ranges are untruncated, "
            "which the build asserts, because a truncated maximum is the "
            "classic silent off-by-one in a prefix search."
        ),
    ),
]

NAMES_TRAPS = [
    "**`feature_id` is the division's GERS id, not the polygon's.** Join it "
    "to `division_id` in a boundary collection. Nothing here joins to `id`.",
    "**An alternative-name row is not another place.** `alt_of` non-null "
    "means the row is another spelling of the division its `feature_id` "
    "names. Dedupe by `feature_id` before showing results, or you will show "
    "the same city once per language.",
    "**`geometry` and `geometry_ref` are null on an alternative-name row.** "
    "They are on the primary row for the same `feature_id`. This is "
    "deliberate: repeating a point and a row reference on two million rows "
    "cost 60 MB and said nothing new.",
    "**`has_boundary = false` is the common case at level 4.** Most of "
    "Overture's localities have no polygon at all. Check the flag before you "
    "fetch; `bbox` is then the point, and `area_km2` is null.",
    "**`bbox` is float32, rounded outward.** It always contains the "
    "division, and it is approximate to about 1e-5 degrees. The boundary "
    "collections keep float64 if you need the exact extent.",
    "**`name_norm` folding is lossy on purpose.** It strips combining marks, "
    "so `Unión` and `Union` collide, which is what makes accent-insensitive "
    "search work. It does **not** transliterate: a Han, Arabic or Cyrillic "
    "name is only lowercased, so it is findable in its own script and, "
    "separately, through whichever `names.common` entry romanized it.",
    "**Prefix search is cheap; substring search is not.** The sort makes a "
    "leading prefix a range read. A fragment in the middle of a name has to "
    "scan the whole `name_norm` column.",
    "**`level` is this catalog's mapping, not Overture's `admin_level`.** "
    "Overture puts a dependency at `admin_level` 1 and leaves it null below "
    "county.",
    "**The index is far too large to load whole.** Use the range path, or "
    "query it server-side with DuckDB. The CC-BY counterpart's 3.6 MB index "
    "is the one that full-loads.",
]


def boundary_agents(con, collection: str) -> str:
    full, disp = boundary_path(collection), display_path(collection)
    tiles = pmtiles_path(collection)
    md, dmd = pq.ParquetFile(full).metadata, pq.ParquetFile(disp).metadata
    doc = json.loads((CATALOG / collection / "collection.json").read_text())
    report = {
        r["collection"]: r
        for r in json.loads((WORK / "display_containment.json").read_text())
    }[collection]
    tables = {"T": full, "D": disp}
    level = COLLECTION_LEVEL[collection]

    lines = [
        f"# AGENTS.md — {doc['title']}",
        "",
        "Guidance for AI agents and automated clients working with this "
        "collection.",
        "",
        RULE,
        "",
        TIER_NOTE,
        "",
        license_warning("../"),
        "",
        "## Overview",
        "",
        "One land polygon per Overture division of subtype "
        + ("`country` and `dependency`" if collection == "country"
           else f"`{collection}`")
        + f", from release `{RELEASE}`. This catalog's search level is "
        f"**{level}**. Public root: `{PUBLIC}/catalog.json`",
        "",
        "```",
        *listing([
            (f"{collection}/{full.name}",
             f"{human(full.stat().st_size)}, {md.num_rows:,} rows, "
             f"{md.num_row_groups:,} row groups of "
             f"{ROW_GROUP_ROWS[collection]:,}"),
            (f"{collection}/{disp.name}",
             f"{human(disp.stat().st_size)}, same rows, same order, "
             "same groups"),
            (f"{collection}/{tiles.name}",
             f"{human(tiles.stat().st_size)}, "
             f"zoom 0-{MAX_ZOOM[collection]}, layer \"{collection}\""),
        ]),
        "```",
        "",
        "Geometry is Overture's `class = 'land'` division area: its "
        "land-clipped, non-maritime outline, which Overture documents as "
        "intended for map rendering and cartographic display **[attested: "
        f"[division_area schema]({DOCS_SCHEMA_DIVISION_AREA})]**. "
        "The `maritime` polygon it also publishes for a coastal division is "
        "not carried here.",
        "",
        "## Accessing the data",
        "",
        PREAMBLE,
        "",
        "Two Parquet files, and the choice between them is not cosmetic.",
        "",
        f"- **`{full.name}`** is the full-resolution geometry, unchanged from "
        "Overture. Measure with it, clip with it, and fetch one feature from "
        f"it when precision matters. One row group is about "
        f"{human(int(full.stat().st_size / md.num_row_groups))}.",
        f"- **`{disp.name}`** is the same rows simplified and then buffered "
        f"**outward**, about {disp.stat().st_size / dmd.num_rows / 1024:.1f} "
        "KiB a feature. Draw with it and filter with it. It is a **superset** "
        "of the true outline, so neighbouring features overlap along a shared "
        "edge and an area computed from it is too large. Verified per "
        f"feature: {report['fully_contained']:,} of {report['features']:,} "
        f"contain their full-resolution polygon exactly, none falls below "
        f"99%, worst {report['min_contained']:.6f}.",
        "",
        "Both files declare the GeoParquet 1.1 bbox covering, carry a Parquet "
        "page index on every column, and are ordered along a Hilbert curve "
        "over the whole globe. Both carry "
        f"`cnmw:catalog_version = {CATALOG_VERSION}` in their footer "
        "key-value metadata, which is what a consumer checks against "
        "[index.json](../names/index.json) before trusting a "
        "`geometry_ref`.",
        "",
        "## Schema & field notes",
        "",
        "Every column is described in "
        "[collection.json](collection.json) under `table:columns`, with the "
        "tier of each claim. The ones that decide whether a query is right:",
        "",
        "| column | what it is |",
        "|---|---|",
        "| `division_id` | **the join key.** The division's GERS id, and the "
        "`feature_id` the names collection publishes |",
        "| `id` | the *polygon's* GERS id. Not a join key for anything in "
        "this catalog |",
        "| `country` | derived ISO 3166-1 **alpha-3** |",
        "| `country_iso2` | Overture's own alpha-2, unchanged |",
        "| `subtype` | Overture's placetype |",
        "| `level` | not a column here. It is this catalog's 0-to-4 mapping "
        f"and it is **{level}** for every row of this collection |",
        "",
        "Overture's own schema for these properties is carried as an asset: "
        "[division.schema.yaml](../_assets/overture/division.schema.yaml) and "
        "[division_area.schema.yaml]"
        "(../_assets/overture/division_area.schema.yaml). The theme guide is "
        f"at [{DOCS_DIVISIONS}]({DOCS_DIVISIONS}).",
        "",
        "## Data quality & usage notes",
        "",
    ]
    lines += [f"{i}. {trap}" for i, trap in enumerate(BOUNDARY_TRAPS[collection], 1)]
    lines += [
        "",
        "Everything else a consumer would otherwise find the hard way is in "
        "the collection's `known_issues`, rendered in "
        "[README.md](README.md).",
        "",
        "## Example queries",
        "",
    ]
    for q in boundary_queries(collection):
        lines += render(con, q, tables)
    lines += [
        "## Related collections",
        "",
        "- [names](../names/collection.json) — the multilingual search index "
        "over every level, and the only complete view of the divisions in "
        "this catalog. Start there to turn a typed name into a "
        "`division_id`.",
    ]
    for other in COLLECTIONS:
        if other == collection:
            continue
        lines.append(
            f"- [{other}](../{other}/collection.json) — level "
            f"{COLLECTION_LEVEL[other]}"
        )
    lines += [
        f"- [geoboundaries-catalog]({SIBLING}) — the CC-BY-4.0 counterpart, "
        "without share-alike, without localities and without alternative "
        "names.",
        "",
    ]
    return "\n".join(lines)


def names_agents(con) -> str:
    doc = json.loads((CATALOG / "names" / "collection.json").read_text())
    manifest = json.loads((CATALOG / "names" / "index.json").read_text())
    m = json.loads((REPO / "docs" / "index-measurements.json").read_text())
    md = pq.ParquetFile(NAMES_PATH).metadata
    tiles = pmtiles_path("names")
    tables = {"T": NAMES_PATH, "B": boundary_path("county")}
    gpp = m["groups_per_prefix"]

    lines = [
        f"# AGENTS.md — {doc['title']}",
        "",
        "Guidance for AI agents and automated clients working with this "
        "collection.",
        "",
        RULE,
        "",
        TIER_NOTE,
        "",
        license_warning("../"),
        "",
        "## Overview",
        "",
        "**A search sidecar, not a boundary dataset.** One row per Overture "
        "division plus one row per distinct alternative spelling of its name, "
        "built so a static client with no server can turn a typed name, in "
        "any of hundreds of languages, into a GERS id, a bbox and a point. "
        f"Public root: `{PUBLIC}/catalog.json`",
        "",
        "```",
        *listing([
            (f"names/{NAMES_PATH.name}",
             f"{human(NAMES_PATH.stat().st_size)}, {md.num_rows:,} rows, "
             f"{md.num_row_groups:,} row groups of {NAMES_ROW_GROUP_ROWS:,}"),
            ("names/index.json",
             f"{(CATALOG / 'names' / 'index.json').stat().st_size:,} bytes, "
             "the manifest to fetch first"),
            (f"names/{tiles.name}",
             f"{human(tiles.stat().st_size)}, zoom 0-{NAMES_MAX_ZOOM}, "
             'layer "names"'),
        ]),
        "```",
        "",
        f"{manifest['primary_rows']:,} primary rows and "
        f"{manifest['alt_rows']:,} alternative-spelling rows. The `geometry` "
        "column is **one point per division**, from `ST_PointOnSurface` of "
        "its polygon where there is one and Overture's own division point "
        "where there is not. It is a marker, not a shape: do not compute "
        "area, length or containment from this file. The shape lives in the "
        "boundary collection at the row's `level`.",
        "",
        "## Accessing the data",
        "",
        PREAMBLE,
        "",
        "**Fetch [index.json](index.json) first.** It is about a kilobyte and "
        "it carries the index's exact size, row group count and checksum, the "
        f"`catalog_version` (`{CATALOG_VERSION}`) that must match the footer "
        "metadata of this file and of every boundary file, the URL and row "
        "count of each boundary and display file, and the attribution each "
        "source requires with a `share_alike` flag. A widget reads the "
        "attribution out of it and shows it before any search happens, "
        "because ODbL requires that whether or not a search happens.",
        "",
        f"**Then range-request the index.** At "
        f"{human(NAMES_PATH.stat().st_size)} this file is not meant to be "
        "loaded whole. The manifest's `index.size` lets the footer read be "
        f"one exactly-sized tail request of {m['footer_bytes']:,} bytes "
        "rather than a speculative 512 KB. After that, the sort does the "
        "work.",
        "",
        "Measured over all "
        f"{m['prefixes']:,} two-character prefixes that occur in `name_norm`: "
        f"a prefix touches a **minimum of {gpp['min']}, a median of "
        f"{gpp['median']:.0f}, a 95th percentile of {gpp['p95']} and a "
        f"maximum of {gpp['max']}** row groups, each about "
        f"{human(m['mean_row_group_bytes'])} **[derived: "
        "tools/measure_index.py]**. Full numbers, including compressed bytes "
        "per column, are in `docs/index-measurements.md` in the "
        "[repository](https://github.com/portolan-mirrors/cn-geocoder-overture).",
        "",
        "A browser client reads it with "
        "[hyparquet](https://github.com/hyparam/hyparquet) plus "
        "[hyparquet-compressors](https://github.com/hyparam/hyparquet-compressors). "
        "The compressors package is **required**: every column chunk is zstd. "
        "`tools/verify_index_hyparquet.mjs` in the repository does exactly "
        "that and reports the bytes each lookup fetched.",
        "",
        "## Schema & field notes",
        "",
        "Every column is described in [collection.json](collection.json). The "
        "ones that decide whether a query is right:",
        "",
        "| column | what it is |",
        "|---|---|",
        "| `name_norm` | **the sort key.** NFD, combining marks dropped, only "
        "letters, digits, space, hyphen and apostrophe kept, whitespace "
        "collapsed, lowercased. Compared byte-wise on UTF-8, not by a locale "
        "collation |",
        "| `name` | the spelling to display, byte for byte from Overture |",
        "| `feature_id` | the **division's** GERS id. Joins to `division_id` "
        "in a boundary collection |",
        "| `alt_of` | null on a primary row; the row's own `feature_id` on an "
        "alternative-spelling row |",
        "| `name_lang` | the language code Overture keys this spelling under. "
        "Null on a primary row, because Overture does not state the language "
        "of `names.primary` |",
        "| `level` | 0 country and dependency, 1 region, 2 county, 3 "
        "localadmin, 4 locality. **Which boundary collection to join** |",
        "| `has_boundary` | whether any polygon exists for this division in "
        "this catalog |",
        "| `geometry_ref` | advisory `{file, row_group, row}` into the "
        "boundary file and its display companion |",
        "| `bbox` | float32, rounded **outward**, so it always contains the "
        "division |",
        "",
        "## Data quality & usage notes",
        "",
    ]
    lines += [f"{i}. {trap}" for i, trap in enumerate(NAMES_TRAPS, 1)]
    lines += [
        "",
        "## Example queries",
        "",
    ]
    for q in NAMES_QUERIES:
        lines += render(con, q, tables)
    lines += [
        "## Related collections",
        "",
        "The five boundary collections hold the geometry this index points "
        "at. Join `feature_id` to `division_id` in the one matching the row's "
        "`level`:",
        "",
        "| level | collection |",
        "|---|---|",
    ]
    for other in COLLECTIONS:
        lines.append(
            f"| {COLLECTION_LEVEL[other]} | "
            f"[{other}](../{other}/collection.json) |"
        )
    lines += [
        "",
        f"- [geoboundaries-catalog]({SIBLING}) — the CC-BY-4.0 counterpart "
        "index, 3.6 MB and meant to be loaded whole, with the same column "
        "contract, no alternative-name rows and no locality level. A geocoder "
        "widget points at one or the other by changing a URL.",
        "",
    ]
    return "\n".join(lines)


CATALOG_QUERIES = [
    Q(
        "Turn a typed name into a division, then into geometry",
        "WITH hit AS (\n"
        "  SELECT feature_id, name, level, country, parent_name,\n"
        "         population, has_boundary\n"
        "  FROM {T}\n"
        "  WHERE name_norm LIKE 'kyoto%' AND level = 1\n"
        "  ORDER BY population DESC NULLS LAST LIMIT 3\n"
        ")\n"
        "SELECT h.name, h.level, h.country, h.parent_name,\n"
        "       b.subtype, round(b.area_km2) AS area_km2, b.vertices\n"
        "FROM hit h JOIN {C} b ON b.division_id = h.feature_id;",
        note=(
            "Two steps and no server. The index resolves the prefix; "
            "`feature_id` joins to `division_id` in the boundary collection "
            "at the row's `level`, which here is 1, so the join is against "
            "`region`. **The `level = 1` filter is not decoration**: join a "
            "level-4 row to the region collection and you get nothing back, "
            "which is why a client picks the file from `level` rather than "
            "trying all five. The three rows are three spellings of one "
            "division, which is what `feature_id` dedupes."
        ),
    ),
    Q(
        "How many divisions exist per level, and how many have a boundary",
        "SELECT level, count(*) FILTER (WHERE alt_of IS NULL) AS divisions,\n"
        "       count(*) FILTER (WHERE alt_of IS NOT NULL) AS alt_spellings,\n"
        "       count(*) FILTER (WHERE has_boundary\n"
        "                          AND alt_of IS NULL) AS with_boundary\n"
        "FROM {T} GROUP BY 1 ORDER BY 1;",
        note=(
            "The gap at level 4 is the headline fact of this catalog: "
            "Overture publishes most localities as a point only."
        ),
    ),
    Q(
        "The same division named in many languages",
        "SELECT name, name_lang, name_lang_count\n"
        "FROM {T}\n"
        "WHERE feature_id = (SELECT feature_id FROM {T}\n"
        "                    WHERE name_norm = 'deutschland' LIMIT 1)\n"
        "ORDER BY name_lang NULLS FIRST LIMIT 10;",
        note=(
            "The row with a NULL `name_lang` is the primary row. Every other "
            "row is an alternative spelling of the same division, sharing its "
            "`feature_id`."
        ),
    ),
]


def catalog_agents(con) -> str:
    manifest = json.loads((CATALOG / "names" / "index.json").read_text())
    tables = {"T": NAMES_PATH, "C": boundary_path("region")}
    lines = [
        "# AGENTS.md — EXPERIMENTAL: Overture Divisions for Geocoding (ODbL)",
        "",
        "Guidance for AI agents and automated clients working with this "
        "catalog. Each collection has its own guide with the queries for that "
        "level; this one is the map.",
        "",
        RULE,
        "",
        TIER_NOTE,
        "",
        license_warning(""),
        "",
        "## What is here",
        "",
        f"Overture Maps divisions, release `{RELEASE}`, as six collections. "
        f"Public root: `{PUBLIC}/catalog.json`",
        "",
        "| collection | level | what it holds |",
        "|---|---|---|",
        "| [`country`](country/collection.json) | 0 | countries and "
        "dependencies |",
        "| [`region`](region/collection.json) | 1 | states, provinces, "
        "regions |",
        "| [`county`](county/collection.json) | 2 | counties, districts, "
        "municipalities |",
        "| [`localadmin`](localadmin/collection.json) | 3 | communes and "
        "equivalents, **19 countries only** |",
        "| [`locality`](locality/collection.json) | 4 | cities, towns, "
        "villages, hamlets **with a polygon** |",
        "| [`names`](names/collection.json) | 0-4 | the multilingual search "
        "index, and the only complete view |",
        "",
        "Each boundary collection publishes two Parquet files, "
        "full-resolution and display-simplified, plus PMTiles. The display "
        "file holds the same rows in the same order in the same row groups, "
        "simplified and then buffered **outward**, so it always contains the "
        "true boundary. Draw and filter with it; measure and clip with the "
        "full file.",
        "",
        "## Start here",
        "",
        "1. Fetch [names/index.json](names/index.json), about a kilobyte. It "
        "carries the index's size and checksum, the `catalog_version` every "
        "data file's footer must agree with, the URL of every boundary and "
        "display file, and the attribution to display.",
        "2. Resolve a name against "
        "[names](names/collection.json) with a `name_norm LIKE 'prefix%'` "
        "range read.",
        "3. Join the hit's `feature_id` to `division_id` in the boundary "
        "collection at the hit's `level`.",
        "",
        "## The join keys",
        "",
        "| from | to | on |",
        "|---|---|---|",
        "| `names` | any boundary collection | `names.feature_id = "
        "boundary.division_id` |",
        "| any boundary collection | its display companion | the same row "
        "offset, or `division_id` |",
        "| a boundary row | its parent | `parent_division_id = division_id` "
        "in the collection one level up |",
        "| any row | Overture's release | `division_id` is the GERS id of the "
        "`type=division` feature |",
        "| any row | Wikidata | `wikidata` where present |",
        "",
        "## The traps that produce wrong answers",
        "",
        "1. **`id` is not the join key. `division_id` is.** Both are GERS "
        "identifiers: `id` belongs to the polygon, `division_id` to the "
        "division. A join on `id` silently returns nothing.",
        "2. **`level` is this catalog's own 0-to-4 mapping, not Overture's "
        "`admin_level`.** Overture puts a dependency at `admin_level` 1 and "
        "leaves `admin_level` null below county.",
        "3. **The five boundary levels are not a seamless coverage.** There "
        "is no gap-filling from a coarser level, so a country with no "
        "localadmin divisions has no rows at level 3 and the polygons do not "
        "tile the globe. The `names` index is the only complete view.",
        f"4. **{manifest['primary_rows'] - 620734:,} divisions have no "
        "polygon anywhere in this catalog**, almost all of them localities "
        "Overture publishes as a point. `has_boundary` says so per row.",
        "5. **An alternative-name row is not another place.** Dedupe search "
        "results by `feature_id`, or the same city appears once per language.",
        "6. **`country` is derived alpha-3; `country_iso2` is Overture's "
        "alpha-2.** Some rows carry a synthetic code with no alpha-3 "
        "equivalent, and there the two columns are equal and two letters "
        "long.",
        "7. **The geometry is the land outline.** Overture's `maritime` "
        "polygon is not carried, so a point offshore is in no row.",
        "8. **The display files are supersets.** Neighbours overlap along a "
        "shared edge, so a point can fall in two of them, and an area "
        "computed from one is too large.",
        "9. **ODbL share-alike is not optional.** A derived database has to "
        "be ODbL, and anything shown has to carry the attribution. The "
        f"[CC-BY counterpart]({SIBLING}) is the one without that obligation.",
        "",
        "## Example queries",
        "",
    ]
    for q in CATALOG_QUERIES:
        lines += render(con, q, tables)
    lines += [
        "## Further reading",
        "",
        "- [changes-from-upstream.md](changes-from-upstream.md) — every row "
        "and column this catalog drops, derives or adds, and how to read "
        "vanilla Overture instead.",
        "- [names/AGENTS.md](names/AGENTS.md) — the search index, the "
        "range-request path and the `geometry_ref` fast path.",
        f"- [Overture divisions guide]({DOCS_DIVISIONS}) — what a subtype "
        "means, and Overture's own coverage statement.",
        "- [_assets/overture/](_assets/overture/) — Overture's own schema "
        "files and its attribution block, carried verbatim.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    written = []
    for collection in COLLECTIONS:
        path = CATALOG / collection / "AGENTS.md"
        path.write_text(wrap_markdown(boundary_agents(con, collection)))
        written.append(path)
    path = CATALOG / "names" / "AGENTS.md"
    path.write_text(wrap_markdown(names_agents(con)))
    written.append(path)
    path = CATALOG / "AGENTS.md"
    path.write_text(wrap_markdown(catalog_agents(con)))
    written.append(path)
    con.close()
    for p in written:
        print(f"  {p.relative_to(REPO)}: {p.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
