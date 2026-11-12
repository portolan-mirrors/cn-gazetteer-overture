# AGENTS.md — Overture Divisions Multilingual Name Search Index

Guidance for AI agents and automated clients working with this collection.

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
> [index.json](../names/index.json) if you depend on it.

## Overview

**A search sidecar, not a boundary dataset.** One row per Overture division
plus one row per distinct alternative spelling of its name, built so a static
client with no server can turn a typed name, in any of hundreds of languages,
into a GERS id, a bbox and a point. Public root:
`https://data.source.coop/portolan-mirrors/cn-geocoder-overture/catalog.json`

```
names/overture_division_names.parquet  407.7 MB, 5,604,413 rows, 876 row groups of 6,400
names/index.json                       4,534 bytes, the manifest to fetch first
names/names.pmtiles                    146.3 MB, zoom 0-8, layer "names"
```

3,572,796 primary rows and 2,031,617 alternative-spelling rows. The `geometry`
column is **one point per division**, from `ST_PointOnSurface` of its polygon
where there is one and Overture's own division point where there is not. It is
a marker, not a shape: do not compute area, length or containment from this
file. The shape lives in the boundary collection at the row's `level`.

## Accessing the data

```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
```

Every file here is readable in place over HTTPS range requests. No
credentials, no API, no server.

**Fetch [index.json](index.json) first.** It is about a kilobyte and it carries
the index's exact size, row group count and checksum, the `catalog_version`
(`overture-divisions-2026-10-21.0`) that must match the footer metadata of this
file and of every boundary file, the URL and row count of each boundary and
display file, and the attribution each source requires with a `share_alike`
flag. A widget reads the attribution out of it and shows it before any search
happens, because ODbL requires that whether or not a search happens.

**Then range-request the index.** At 407.7 MB this file is not meant to be
loaded whole. The manifest's `index.size` lets the footer read be one
exactly-sized tail request of 2,053,386 bytes rather than a speculative 512 KB.
After that, the sort does the work.

Measured over all 189,359 two-character prefixes that occur in `name_norm`: a
prefix touches a **minimum of 1, a median of 1, a 95th percentile of 1 and a
maximum of 22** row groups, each about 473.6 KB **[derived:
tools/measure_index.py]**. Full numbers, including compressed bytes per column,
are in `docs/index-measurements.md` in the
[repository](https://github.com/portolan-mirrors/cn-geocoder-overture).

A browser client reads it with
[hyparquet](https://github.com/hyparam/hyparquet) plus
[hyparquet-compressors](https://github.com/hyparam/hyparquet-compressors). The
compressors package is **required**: every column chunk is zstd.
`tools/verify_index_hyparquet.mjs` in the repository does exactly that and
reports the bytes each lookup fetched.

## Schema & field notes

Every column is described in [collection.json](collection.json). The ones that
decide whether a query is right:

| column | what it is |
|---|---|
| `name_norm` | **the sort key.** NFD, combining marks dropped, only letters, digits, space, hyphen and apostrophe kept, whitespace collapsed, lowercased. Compared byte-wise on UTF-8, not by a locale collation |
| `name` | the spelling to display, byte for byte from Overture |
| `feature_id` | the **division's** GERS id. Joins to `division_id` in a boundary collection |
| `alt_of` | null on a primary row; the row's own `feature_id` on an alternative-spelling row |
| `name_lang` | the language code Overture keys this spelling under. Null on a primary row, because Overture does not state the language of `names.primary` |
| `level` | 0 country and dependency, 1 region, 2 county, 3 localadmin, 4 locality. **Which boundary collection to join** |
| `has_boundary` | whether any polygon exists for this division in this catalog |
| `geometry_ref` | advisory `{file, row_group, row}` into the boundary file and its display companion |
| `bbox` | float32, rounded **outward**, so it always contains the division |

## Data quality & usage notes

1. **`feature_id` is the division's GERS id, not the polygon's.** Join it to
   `division_id` in a boundary collection. Nothing here joins to `id`.
2. **An alternative-name row is not another place.** `alt_of` non-null means
   the row is another spelling of the division its `feature_id` names. Dedupe
   by `feature_id` before showing results, or you will show the same city once
   per language.
3. **`geometry` and `geometry_ref` are null on an alternative-name row.** They
   are on the primary row for the same `feature_id`. This is deliberate:
   repeating a point and a row reference on two million rows cost 60 MB and
   said nothing new.
4. **`has_boundary = false` is the common case at level 4.** Most of Overture's
   localities have no polygon at all. Check the flag before you fetch; `bbox`
   is then the point, and `area_km2` is null.
5. **`bbox` is float32, rounded outward.** It always contains the division, and
   it is approximate to about 1e-5 degrees. The boundary collections keep
   float64 if you need the exact extent.
6. **`name_norm` folding is lossy on purpose.** It strips combining marks, so
   `Unión` and `Union` collide, which is what makes accent-insensitive search
   work. It does **not** transliterate: a Han, Arabic or Cyrillic name is only
   lowercased, so it is findable in its own script and, separately, through
   whichever `names.common` entry romanized it.
7. **Prefix search is cheap; substring search is not.** The sort makes a
   leading prefix a range read. A fragment in the middle of a name has to scan
   the whole `name_norm` column.
8. **`level` is this catalog's mapping, not Overture's `admin_level`.**
   Overture puts a dependency at `admin_level` 1 and leaves it null below
   county.
9. **The index is far too large to load whole.** Use the range path, or query
   it server-side with DuckDB. The CC-BY counterpart's 3.6 MB index is the one
   that full-loads.

## Example queries

**Rows per level, and how many have a boundary in this catalog** **[derived]**

```sql
SELECT level, count(*) AS rows,
       count(*) FILTER (WHERE alt_of IS NULL) AS primary_rows,
       count(*) FILTER (WHERE alt_of IS NOT NULL) AS alt_rows,
       count(*) FILTER (WHERE has_boundary) AS with_boundary
FROM 'https://data.source.coop/portolan-mirrors/cn-geocoder-overture/names/overture_division_names.parquet'
GROUP BY 1 ORDER BY 1;
```

```
level  rows     primary_rows  alt_rows  with_boundary
0      25620    272           25348     25620
1      89372    3929          85443     89372
2      186018   38937         147081    186018
3      72947    21502         51445     72947
4      5230456  3508156       1722300   1122847
```

Level 0 is country and dependency, 1 region, 2 county, 3 localadmin, 4
locality. A level-4 row with `has_boundary = false` is a place Overture
publishes as a point only; it is still the right answer to a search, and `bbox`
is that point collapsed to zero width.

**A prefix lookup, which is what a keystroke costs** **[derived]**

```sql
SELECT name, name_lang, level, country, parent_name, population
FROM 'https://data.source.coop/portolan-mirrors/cn-geocoder-overture/names/overture_division_names.parquet'
WHERE name_norm LIKE 'zurich%'
ORDER BY level, population DESC NULLS LAST;
```

```
name    name_lang  level  country  parent_name                     population
Zürich  NULL       1      CHE      Schweiz/Suisse/Svizzera/Svizra  NULL
Zürich  NULL       2      CHE      Zürich                          NULL
Zürich  NULL       3      CHE      Zürich                          NULL
Zürich  NULL       4      CHE      Zürich                          443037
Zurich  NULL       4      NLD      Súdwest-Fryslân                 190
Zurich  NULL       4      USA      Rooks County                    120
Zurich  NULL       4      CAN      Bluewater                       NULL
Zürich  NULL       4      SWE      Åtvidabergs kommun              NULL
Zurich  NULL       4      USA      Arcadia                         NULL
Zurich  NULL       4      USA      Blaine County                   NULL
```

`LIKE 'prefix%'` is the whole access pattern. The file is sorted by `name_norm`
byte-wise on UTF-8 and the sort is declared in the footer, so DuckDB, GDAL and
a browser Parquet reader all prune to the one or two row groups a prefix can
live in. **Fold the user's input the same way the index did** before you
compare: NFD, drop combining marks, keep only letters, digits, space, hyphen
and apostrophe, collapse whitespace, lowercase.

**The same place, found in another language** **[derived]**

```sql
SELECT name, name_lang, name_lang_count, level, country, feature_id
FROM 'https://data.source.coop/portolan-mirrors/cn-geocoder-overture/names/overture_division_names.parquet'
WHERE name_norm IN ('munchen', 'monaco di baviera', 'muenchen')
ORDER BY name_norm;
```

```
name               name_lang  name_lang_count  level  country  feature_id
Monaco di Baviera  it         1                2      DEU      09755310-09cb-4d76-861f-74f19544e65a
Monaco di Baviera  it         1                4      DEU      694b5dbd-13eb-4d10-853f-88e338d5b53b
München            NULL       1                2      DEU      09755310-09cb-4d76-861f-74f19544e65a
München            de         1                4      CZE      41fb1415-d4d1-4887-913e-341c9fda57d7
München            NULL       1                4      DEU      03a94fd4-c08d-4ec7-945f-0444c6c63a0a
München            NULL       1                4      DEU      3a31fcef-c526-4063-ab51-40aa56af4a23
München            NULL       1                4      DEU      52559594-c2ac-44f9-90a2-fd94a554813f
München            NULL       1                4      DEU      694b5dbd-13eb-4d10-853f-88e338d5b53b
München            NULL       1                4      DEU      eb67cc96-effa-4b9f-84c1-fd38bb7687cf
```

Several rows, one `feature_id`. **Dedupe by `feature_id`** before you show a
result list, and keep whichever row matched so you can show the user the
spelling they typed. `name_lang_count` says how many of Overture's language
codes agreed on that spelling; the index keeps one row per distinct folded
spelling, not one per language.

**How ambiguous the common names are** **[derived]**

```sql
SELECT name_norm, count(*) AS rows,
       count(DISTINCT feature_id) AS divisions
FROM 'https://data.source.coop/portolan-mirrors/cn-geocoder-overture/names/overture_division_names.parquet'
GROUP BY 1 ORDER BY 2 DESC LIMIT 10;
```

```
name_norm    rows  divisions
新村           1019  1019
santa rosa   881   881
san antonio  842   842
san jose     771   771
san isidro   699   699
santa cruz   627   627
santa maria  625   625
san pedro    603   603
san miguel   570   570
le bourg     563   563
```

`name_dupes` carries this count on every row, so a client does not have to
compute it. Disambiguate with `parent_name`, `level`, `country` and
`population`.

**The geometry_ref fast path: index row to boundary row group** **[derived]**

```sql
SELECT n.name, n.level, n.feature_id,
       n.geometry_ref.file AS file,
       n.geometry_ref.row_group AS row_group,
       n.geometry_ref.row AS row
FROM 'https://data.source.coop/portolan-mirrors/cn-geocoder-overture/names/overture_division_names.parquet' n
WHERE n.name_norm = 'bengaluru' AND n.alt_of IS NULL;
```

```
name       level  feature_id                            file                       row_group  row
Bengaluru  4      83d231e2-da9e-4933-bb89-0997d5dd8741  overture_locality.parquet  117        112700
```

`geometry_ref` is **advisory**. It says which row group of which boundary file
holds the geometry, and the display companion holds the same row at the same
offset, so `resolution: 'both'` is two range reads at one row index rather than
a join. A consumer must still decode `division_id` for that row and assert it
equals `feature_id`, and fall back to a lookup on mismatch: the hint is only
valid while the `catalog_version` in [index.json](index.json) matches the
footer metadata of both files.

**Join back to the real geometry** **[derived]**

```sql
SELECT n.name, n.level, b.subtype, b.area_km2, b.vertices
FROM 'https://data.source.coop/portolan-mirrors/cn-geocoder-overture/names/overture_division_names.parquet' n
JOIN 'https://data.source.coop/portolan-mirrors/cn-geocoder-overture/county/overture_county.parquet' b ON b.division_id = n.feature_id
WHERE n.name_norm LIKE 'sao paulo%' AND n.level = 2;
```

```
name  level  subtype  area_km2  vertices
```

**`feature_id` joins to `division_id`**, and the collection to join is the one
at the row's `level`: 0 country, 1 region, 2 county, 3 localadmin, 4 locality.
Joining a level-4 row to the county collection returns nothing, and joining on
`id` returns nothing at any level.

**Which languages carry the most indexed spellings** **[derived]**

```sql
SELECT name_lang, count(*) AS rows
FROM 'https://data.source.coop/portolan-mirrors/cn-geocoder-overture/names/overture_division_names.parquet' WHERE name_lang IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC LIMIT 12;
```

```
name_lang       rows
en              641853
ru              128137
de              92105
ko              84187
uk              49237
genitive        46479
pl              44829
ar              43803
zh-Latn-pinyin  37419
zh-Hant         36104
zh              35296
ja              35171
```

**Row group statistics on name_norm, the thing the sort buys** **[derived]**

```sql
SELECT row_group_id AS row_group, num_values AS rows,
       stats_min_value AS first_name_norm,
       stats_max_value AS last_name_norm
FROM parquet_metadata('https://data.source.coop/portolan-mirrors/cn-geocoder-overture/names/overture_division_names.parquet')
WHERE path_in_schema = 'name_norm'
  AND row_group_id IN (0, 1, 2, 400, 875);
```

```
row_group  rows  first_name_norm  last_name_norm
0          6400  'a forza         a agrina
1          6400  a agua           a penamoura
2          6400  a penamusga      abdon castro tolay
400        6400  patrao-mor       pcoline
875        4413  龙岘3洞             𱊜尔蓬
```

Tight, non-overlapping alphabetical ranges. A client binary-searches these and
reads one group. The ranges are untruncated, which the build asserts, because a
truncated maximum is the classic silent off-by-one in a prefix search.

## Related collections

The five boundary collections hold the geometry this index points at. Join
`feature_id` to `division_id` in the one matching the row's `level`:

| level | collection |
|---|---|
| 0 | [country](../country/collection.json) |
| 1 | [region](../region/collection.json) |
| 2 | [county](../county/collection.json) |
| 3 | [localadmin](../localadmin/collection.json) |
| 4 | [locality](../locality/collection.json) |

- [geoboundaries-catalog](https://source.coop/portolan-mirrors/geoboundaries-catalog)
  — the CC-BY-4.0 counterpart index, 3.6 MB and meant to be loaded whole, with
  the same column contract, no alternative-name rows and no locality level. A
  geocoder widget points at one or the other by changing a URL.
