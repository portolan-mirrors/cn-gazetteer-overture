# AGENTS.md — EXPERIMENTAL: Overture Divisions Cloud-Native Gazetteer (ODbL)

Guidance for AI agents and automated clients working with this catalog. Each
collection has its own guide with the queries for that level; this one is the
map.

This catalog is a **cloud-native gazetteer**: Overture's administrative
divisions, laid out so a client can search them by name and draw them, one
place at a time, over HTTP range requests. It is a gazetteer and **not a
geocoder** — it resolves place names and administrative boundaries, never
street addresses. There is no house number, no street centerline and no
interpolation here, so a query like "150 Main St" has no answer in this data.
The geocoder is the client that consumes the gazetteer.

**One rule survives every edit to this file.** Every claim here is
either quoted from a source or measured from the data. If you cannot point at
where a fact came from, it does not belong in this file. An agent acting on an
invented join key or an invented column name produces a confident wrong
answer, and nothing downstream catches it.

Each factual claim is tagged with how it was established:
**[attested]** Overture states it, with a link;
**[researched]** found outside the source's own metadata, with a link;
**[derived]** computed from the published data, with the query that computed
it. Every query below was run against the built file before this guide was
written; the output under each one is what it returned.

> [!IMPORTANT]
> **ODbL-1.0, share-alike.** A database you derive from this collection has to
> be offered under ODbL as well, and anything you show has to carry
> `© OpenStreetMap contributors. Available under the Open Database License.`
> If that does not work for your use, the CC-BY-4.0 counterpart is
> [geoboundaries-catalog](https://source.coop/portolan-mirrors/geoboundaries-catalog).

> [!WARNING]
> **EXPERIMENTAL.** The schema may change without notice. Pin the
> `catalog_version` (`overture-divisions-2026-10-21.0`) from
> [index.json](names/index.json) if you depend on it.

## What is here

Overture Maps divisions, release `2026-10-21.0`, as six collections. Public
root:
`https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/catalog.json`

| collection | level | what it holds |
|---|---|---|
| [`country`](country/collection.json) | 0 | countries and dependencies |
| [`region`](region/collection.json) | 1 | states, provinces, regions |
| [`county`](county/collection.json) | 2 | counties, districts, municipalities |
| [`localadmin`](localadmin/collection.json) | 3 | communes and equivalents, **19 countries only** |
| [`locality`](locality/collection.json) | 4 | cities, towns, villages, hamlets **with a polygon** |
| [`names`](names/collection.json) | 0-4 | the multilingual search index, and the only complete view |

Each boundary collection publishes two Parquet files, full-resolution and
display-simplified, plus PMTiles. The display file holds the same rows in the
same order in the same row groups, simplified and then buffered **outward**, so
it always contains the true boundary. Draw and filter with it; measure and clip
with the full file.

## Start here

1. Fetch [names/index.json](names/index.json), a few kilobytes. It carries the
   index's size and checksum, the `catalog_version` every data file's footer
   must agree with, the URL of every boundary and display file, the attribution
   to display, and two things worth reading before you fetch a single data
   byte:
    - **`footer_bytes` and `footer_metadata_bytes` on every file entry.**
      Parquet metadata sits at the end of a file and a reader must have it
      before it can read any row group, but nothing in the format says how big
      it is — so hyparquet speculates a 512 KiB tail and fetches again when it
      guesses short. On the full index, whose footer is 2.1 MB, that
      speculation is a *guaranteed* second round trip. Pass one of these as
      `initialFetchSize` instead: `footer_bytes` is the whole trailing span,
      footer plus page index, and gets you everything in one request;
      `footer_metadata_bytes` is the thrift footer alone, which is all
      hyparquet ever reads, since it has no sub-chunk read.
    - **`prominent_index`.** A second, 8.6 MiB names file in the same
      collection, with the same schema and the same sort as the full 409 MB
      index. Fetch it whole and answer keystrokes from memory.
      `prominent_index.criteria` states exactly which rows it holds — every
      division down to localadmin, every alternative-language spelling of every
      country, every locality at `prominence` >= 50 — and
      `prominent_index.criteria.fallback` states what it can miss, which is
      when to go to the full index. Every row in it is also in the full index,
      with the same `feature_id` and the same `geometry_ref`, so the two are
      interchangeable for resolution and a client may query both and dedupe by
      `feature_id`.
2. Resolve a name against [names](names/collection.json) with a `name_norm LIKE
   'prefix%'` range read.
3. Join the hit's `feature_id` to `division_id` in the boundary collection at
   the hit's `level`.

## The join keys

| from | to | on |
|---|---|---|
| `names` | any boundary collection | `names.feature_id = boundary.division_id` |
| any boundary collection | its display companion | the same row offset, or `division_id` |
| a boundary row | its parent | `parent_division_id = division_id` in the collection one level up |
| any row | Overture's release | `division_id` is the GERS id of the `type=division` feature |
| any row | Wikidata | `wikidata` where present |

## The traps that produce wrong answers

1. **`id` is not the join key. `division_id` is.** Both are GERS identifiers:
   `id` belongs to the polygon, `division_id` to the division. A join on `id`
   silently returns nothing.
2. **`level` is this catalog's own 0-to-4 mapping, not Overture's
   `admin_level`.** Overture puts a dependency at `admin_level` 1 and leaves
   `admin_level` null below county.
3. **The five boundary levels are not a seamless coverage.** There is no
   gap-filling from a coarser level, so a country with no localadmin divisions
   has no rows at level 3 and the polygons do not tile the globe. The `names`
   index is the only complete view.
4. **2,952,062 divisions have no polygon anywhere in this catalog**, almost all
   of them localities Overture publishes as a point. `has_boundary` says so per
   row.
5. **An alternative-name row is not another place.** Dedupe search results by
   `feature_id`, or the same city appears once per language.
5a. **Rank with `class`, `prominence` and `alt_of`, not with `area_km2`.** A
short prefix returns thousands of candidates and is dominated by
alternative-language rows of countries and regions — ranking verification found
Baghdad buried under Tajik and Uzbek spellings of Bahamas. `area_km2` makes it
worse, because a country always dwarfs a city. The columns that separate them
are `class` (`city`, `town`, `village`, `hamlet`; null above locality, and null
on 113,529 localities, so treat a null as unknown rather than as unimportant),
`prominence` (Overture's 1-100 cartographic ranking, on every locality),
`population` (sparse — 17.7% of localities, 79.9% of countries — so null means
unknown, never zero), and `alt_of`, which is non-null exactly on the
alternative-language rows and so is how you penalize one against a match on the
published name.
6. **`country` is derived alpha-3; `country_iso2` is Overture's alpha-2.** Some
   rows carry a synthetic code with no alpha-3 equivalent, and there the two
   columns are equal and two letters long.
7. **The geometry is the land outline.** Overture's `maritime` polygon is not
   carried, so a point offshore is in no row.
8. **The display files are supersets.** Neighbours overlap along a shared edge,
   so a point can fall in two of them, and an area computed from one is too
   large.
9. **ODbL share-alike is not optional.** A derived database has to be ODbL, and
   anything shown has to carry the attribution. The [CC-BY
   counterpart](https://source.coop/portolan-mirrors/geoboundaries-catalog) is
   the one without that obligation.

## The upstream data vs our optimized files

Every collection links the upstream release it was built from —
`upstream-division-s3`, `upstream-division-area-s3` and
`upstream-divisions-azure`. Use them, not this catalog, when you want the
authoritative bytes, the whole theme for analysis, or a column this catalog's
projection dropped. [derived]

    s3://overturemaps-us-west-2/release/2026-10-21.0/theme=divisions/
    https://overturemapswestus2.blob.core.windows.net/release/2026-10-21.0/theme=divisions/

Both are public and anonymous. Measured 2026-11-12: the S3 HTTPS endpoint sends
`Access-Control-Allow-Origin: *` and answers `Accept-Ranges: bytes`, so a
browser can range-read it directly; the Azure mirror sends no CORS headers and
cannot be read cross-origin. **So reachability is not why this catalog exists —
layout is.** Measured on `part-00000` of `type=division`, 584 MB: 4,700,999
rows in 256 row groups of about 18,400 rows, median 2.22 MB and up to 3.85 MB
compressed per group, 50 leaf column chunks of the nested schema, **no declared
sort**, and a 1.47 MB footer that takes two requests to read. Finding one place
by name in it means scanning every part file; pulling one division's geometry
means fetching a multi-megabyte row group. The files here are the same data
sorted by name, projected flat and cut into row groups sized by what one
feature costs, so each of those is one small range request. [derived]

That is the whole trade. Nothing here is more correct than the release — it is
the same coordinates — and nothing here is better for bulk work. Use upstream
for analysis and provenance; use this for interactive lookup.

## Example queries

**Turn a typed name into a division, then into geometry** **[derived]**

```sql
WITH hit AS (
  SELECT feature_id, name, level, country, parent_name,
         population, has_boundary
  FROM 'https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/names/overture_division_names.parquet'
  WHERE name_norm LIKE 'kyoto%' AND level = 1
  ORDER BY population DESC NULLS LAST LIMIT 3
)
SELECT h.name, h.level, h.country, h.parent_name,
       b.subtype, round(b.area_km2) AS area_km2, b.vertices
FROM hit h JOIN 'https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/region/overture_region.parquet' b ON b.division_id = h.feature_id;
```

```
name                 level  country  parent_name  subtype  area_km2  vertices
Kyoto Prefecture     1      JPN      日本           region   4601      19116
Kyoto İdari Bölgesi  1      JPN      日本           region   4601      19116
Kyoto - præfektur    1      JPN      日本           region   4601      19116
```

Two steps and no server. The index resolves the prefix; `feature_id` joins to
`division_id` in the boundary collection at the row's `level`, which here is 1,
so the join is against `region`. **The `level = 1` filter is not decoration**:
join a level-4 row to the region collection and you get nothing back, which is
why a client picks the file from `level` rather than trying all five. The three
rows are three spellings of one division, which is what `feature_id` dedupes.

**How many divisions exist per level, and how many have a boundary**
**[derived]**

```sql
SELECT level, count(*) FILTER (WHERE alt_of IS NULL) AS divisions,
       count(*) FILTER (WHERE alt_of IS NOT NULL) AS alt_spellings,
       count(*) FILTER (WHERE has_boundary
                          AND alt_of IS NULL) AS with_boundary
FROM 'https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/names/overture_division_names.parquet' GROUP BY 1 ORDER BY 1;
```

```
level  divisions  alt_spellings  with_boundary
0      272        25348          272
1      3929       85443          3929
2      38937      147081         38937
3      21502      51445          21502
4      3508156    1722300        556094
```

The gap at level 4 is the headline fact of this catalog: Overture publishes
most localities as a point only.

**The same division named in many languages** **[derived]**

```sql
SELECT name, name_lang, name_lang_count
FROM 'https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/names/overture_division_names.parquet'
WHERE feature_id = (SELECT feature_id FROM 'https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/names/overture_division_names.parquet'
                    WHERE name_norm = 'deutschland' LIMIT 1)
ORDER BY name_lang NULLS FIRST LIMIT 10;
```

```
name         name_lang  name_lang_count
Deutschland  NULL       1
Germany      aa         11
Алмантәыла   ab         1
Jeureuman    ace        1
Duitsland    af         2
ጀርመን         am         2
Alemanya     an         7
Þēodscland   ang        1
ألمانيا      ar         2
ܓܪܡܢ         arc        1
```

The row with a NULL `name_lang` is the primary row. Every other row is an
alternative spelling of the same division, sharing its `feature_id`.

## Further reading

- [changes-from-upstream.md](changes-from-upstream.md) — every row and column
  this catalog drops, derives or adds, and how to read vanilla Overture
  instead.
- [names/AGENTS.md](names/AGENTS.md) — the gazetteer index, the range-request
  path and the `geometry_ref` fast path.
- [Overture divisions guide](https://docs.overturemaps.org/guides/divisions) —
  what a subtype means, and Overture's own coverage statement.
- [_assets/overture/](_assets/overture/) — Overture's own schema files and its
  attribution block, carried verbatim.
