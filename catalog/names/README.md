# Overture Divisions Multilingual Name Search Index

> [!WARNING]
> **This catalog is EXPERIMENTAL.** The schema may change without notice, the
> Source Cooperative repository that serves it is unlisted, and the column
> contract it publishes is still being negotiated with its consumer. Pin the
> `catalog_version` in [index.json](names/index.json) if you depend on
> it, and expect to rebuild.

A search sidecar, not a boundary dataset. One row per Overture division, plus
one row per distinct alternative spelling of that division's name, sorted by a
folded form of the name.

It exists so that a **static client with no server** can turn a typed name, in
any of hundreds of languages, into a GERS id, an extent and a point. That is
the lookup half of a browser geocoder, and the multilingual half is what this
catalog has that its CC-BY counterpart,
[geoboundaries-catalog](https://source.coop/portolan-mirrors/geoboundaries-catalog),
does not.

| | |
|---|---|
| Rows | 5,604,413 |
| Primary rows, one per division | 3,572,796 |
| Alternative-spelling rows | 2,031,617 |
| Language codes represented | 1,012 |
| Divisions with a boundary in this catalog | 1,496,804 |
| Parquet | 407.7 MB, 876 row groups of 6,400 rows, zstd, page index |
| Bytes per row | 76.28 |
| Row group | ~473.6 KB |
| Footer + page index | 2,053,386 bytes |
| Sorted by | `name_norm`, `level`, `country`, `feature_id`, byte-wise on UTF-8, declared in the footer |
| PMTiles | 146.3 MB, zoom 0-8 |
| CRS | CRS84 (EPSG:4326) |

**The geometry column is one point per division**, placed inside the division
by `ST_PointOnSurface` where a polygon exists and taken from Overture's own
division point where it does not. It is a marker, not the division's shape, and
it is null on an alternative-spelling row. The shape lives in the boundary
collection at the same level.

## Rows per level

| level | subtypes | rows | primary | alternatives | with a boundary |
|---|---|---|---|---|---|
| 0 | country, dependency | 25,620 | 272 | 25,348 | 25,620 |
| 1 | region | 89,372 | 3,929 | 85,443 | 89,372 |
| 2 | county | 186,018 | 38,937 | 147,081 | 186,018 |
| 3 | localadmin | 72,947 | 21,502 | 51,445 | 72,947 |
| 4 | locality | 5,230,456 | 3,508,156 | 1,722,300 | 1,122,847 |

The 2,075,992 primary rows with no boundary are almost all localities that
Overture publishes as a point only. `has_boundary` is false on them,
`geometry_ref` and `area_km2` are null, and `bbox` is the point collapsed to
zero width. **A client has to handle them**: they are the majority of the
localities in this index, and they are still the right answer to a search.

## How to read it

**Range-request it.** At 407.7 MB this index is far too large to load whole,
and it is not meant to be. The sort is the whole design: row group statistics
on `name_norm` are tight, non-overlapping alphabetical ranges, the footer
declares the sort order, and the Parquet page index is written, so a client
binary-searches the statistics and reads only the groups a prefix can live in.

Measured over all 189,359 two-character prefixes that occur in `name_norm`:

| | row groups touched |
|---|---|
| minimum | 1 |
| median | 1 |
| mean | 1.0 |
| 95th percentile | 1 |
| maximum | 22 |

So a typed two-letter prefix costs a median of 1 read of about 473.6 KB, on top
of a 2,053,386-byte footer read that happens once. The manifest publishes
`index.size` and `index.row_groups` so that footer read can be a single
exactly-sized tail request rather than a speculative one. Full numbers,
including compressed bytes per column, are in
[docs/index-measurements.md](https://github.com/portolan-mirrors/cn-geocoder-overture/blob/main/docs/index-measurements.md).

Browser clients read it with [hyparquet](https://github.com/hyparam/hyparquet)
plus [hyparquet-compressors](https://github.com/hyparam/hyparquet-compressors),
which is **required**, because every column chunk is zstd.
`tools/verify_index_hyparquet.mjs` in the
[repository](https://github.com/portolan-mirrors/cn-geocoder-overture) does
exactly that and reports the bytes each prefix lookup fetched.

**Do not load it whole** unless you are running a batch job. A server-side
consumer should query it with DuckDB instead, which pushes the predicate into
the same statistics.

## Multilingual search

A division's primary name is one row with `alt_of` null and `name_lang` null,
because Overture does not state the language of `names.primary`. Every distinct
alternative spelling in Overture's `names.common` map is another row, with
`name_lang` holding the language code and `alt_of` holding the division's own
`feature_id`.

So a search for a prefix returns a mixture of primary and alternative rows, and
**a consumer dedupes by `feature_id`** before it shows results. A hit on an
alternative row is a hit on its division; there is no second lookup to do,
because every row carries the level, the country, the parent name, the bbox and
the ranking columns.

Two reductions are applied to the alternatives, and both are lossless for
search:

1. An alternative that folds to the same string as the division's primary name
   is dropped. It is the same search key.
2. Alternatives that fold to the same string as each other are collapsed into
   one row. `name_lang` then holds the first language code in alphabetical
   order and `name_lang_count` says how many languages agreed. Overture lists
   `France` under dozens of codes; indexing it dozens of times finds one
   division dozens of times.

The language codes with the most indexed spellings:

| language | rows |
|---|---|
| `en` | 641,853 |
| `ru` | 128,137 |
| `de` | 92,105 |
| `ko` | 84,187 |
| `uk` | 49,237 |
| `genitive` | 46,479 |
| `pl` | 44,829 |
| `ar` | 43,803 |

## The index contract

This file is built to the index-file interface the cloud-native map widgets
geocoder reads, and [index.json](index.json) beside it is the manifest a client
fetches first. The manifest carries the file's size, row group count and
checksum, the `catalog_version` that has to match the footer metadata of this
file and of every boundary file, the URL and row count of each boundary and
display file, and the attribution each source requires with a `share_alike`
flag so a widget can surface the obligation in its own interface.

`tools/build_names.py` asserts the layout guarantees on every run and refuses
to write a file that fails one: required columns present and correctly typed,
`name_norm` ascending byte-wise with no nulls, the sort declared in the footer,
and untruncated statistics on every row group.

Two deliberate divergences from that contract, both recorded in `known_issues`:

- `bbox` is **float32 rounded outward**, not float64. Four doubles a row is
  tens of megabytes at this scale. Every bound is nudged away from the centre
  so the box still contains the division, which costs about 1e-5 degrees of
  precision, roughly a metre. The CC-BY sibling index does the same, so a
  consumer that reads one reads the other.
- The file **is** GeoParquet, with a point geometry column, where the contract
  describes a plain Parquet index. The point is what lets the collection render
  in a data browser and carry styles, and the `bbox` covering it declares is a
  valid superset of the point.

## Start a query

```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;

-- Everything called Zurich, in any language, best match first.
SELECT name, name_lang, level, country, parent_name, population
FROM 'https://data.source.coop/portolan-mirrors/cn-geocoder-overture/names/overture_division_names.parquet'
WHERE name_norm LIKE 'zurich%'
ORDER BY level, population DESC NULLS LAST;
```

More recipes, including the join back to geometry and the `geometry_ref` fast
path, are in [AGENTS.md](AGENTS.md).

## Ambiguity

A name is not an identifier. The most repeated folded name in this index is
`新村`, which 1,019 rows share. `name_dupes` is the count on every row, and
`parent_name`, `level`, `country`, `population` and `prominence` are what
disambiguate.

## License and attribution

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
The live page is [Attribution and
Licensing](https://docs.overturemaps.org/attribution/).

**What you have to do.** Display this line wherever the data is shown:

> © OpenStreetMap contributors. Available under the
> [Open Database License](https://www.openstreetmap.org/copyright).

Overture also publishes the shorter form it uses on its own Explore tool,
`© OpenStreetMap contributors, Overture Maps Foundation`, and asks that a
publication cite `Overture Maps Foundation, overturemaps.org` with the date
the data were accessed. This catalog was built from release 2026-10-21.0,
accessed 2026-11-12.

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
[geoboundaries-catalog](https://source.coop/portolan-mirrors/geoboundaries-catalog)
([repository](https://github.com/portolan-mirrors/geoboundaries-catalog)). It
is the
default for that reason. It carries the same column contract at ADM0, ADM1 and
ADM2, under attribution-only terms, with no city or locality level and no
multilingual names.

## Provenance

Built by `tools/build_names.py` from the staged Overture `type=division` rows
of release `2026-10-21.0` and from the five boundary collections in this
catalog, not from the Overture release twice, so the index and the geometry it
points at cannot disagree. Staged 2026-11-12. Full details of every deviation
from the Overture release are in
[changes-from-upstream.md](../changes-from-upstream.md).

## Known issues

**EXPERIMENTAL.** The schema may change without notice and the Source
Cooperative repository is unlisted. Pin the catalog_version in
[index.json](index.json) if you depend on this.

**ODbL share-alike.** This index is a database. A database derived from it
has to be released under ODbL, and an application that shows results from it
has to display the attribution. [index.json](index.json) sets
share_alike: true on every
ODbL entry in its attribution array so a widget can surface the obligation
without reading this file. The [CC-BY-4.0
counterpart](https://source.coop/portolan-mirrors/geoboundaries-catalog)
carries no such obligation, and a geocoder configured against it needs no
share-alike notice.

**This is a sidecar, not a boundary dataset.** The geometry column is one
point per division, for a marker. The division's shape lives in the country,
region, county, localadmin or locality collection, chosen by the row's
level. Do not compute area, length or containment from this file.

**2,952,062 of the 3,572,796 divisions have no polygon anywhere in this
catalog**, almost all of them localities Overture publishes as a point only.
has_boundary is false on those rows, geometry_ref and area_km2 are null, and
bbox is the division's point collapsed to zero width. They are still the
right answer to a search, so a client has to handle them rather than filter
them out.

**An alternative-name row is not another place.** alt_of non-null means the
row is another spelling of the division its feature_id names, and the
primary row for that division is elsewhere in the file. A result list that
does not dedupe by feature_id shows the same city once per language.

**geometry and geometry_ref are null on every alternative-name row.** They
are on the primary row for the same feature_id. Repeating a 21-byte WKB
point and a row reference on 2,031,617 rows cost about 60 MB and said
nothing new.

**Two deliberate divergences from the index contract.** The contract
describes bbox as four DOUBLEs; this index stores float32 rounded outward,
which halves the cost of four coordinates a row and keeps the containment
property. The contract describes a plain Parquet index with no geometry
column; this file is GeoParquet with a point, because a point is what lets
the collection render in a data browser and carry styles, and the bbox
covering it declares is a valid superset of the point. The CC-BY sibling
index makes both the same choices, so a consumer that reads one reads the
other. Both should be confirmed against the geocoder's schema validation
before either index is treated as stable.

**names.rules is not indexed.** Overture publishes perspective-dependent
name variants there, averaging 73.7 entries on a country and 15.1 on a
region, and a contested name is exactly the kind of name that lives in it.
Indexing those as plain alternatives would return a political claim as an
ordinary synonym, and Overture's perspectives property, which says whose
perspective a variant belongs to, is NULL on every division row of this
release. The omission is a decision, not an oversight, and it is the first
thing to revisit if the release starts populating perspectives.

**A name is not an identifier.** name_dupes counts how many rows share a
folded name worldwide and across levels, and the most repeated folded name
in this index is shared by thousands of rows. Disambiguate with
parent_name, level, country, population and prominence.

**name_norm folding is lossy on purpose, and is not a collation.** It strips
combining marks, so Unión and Union collide, which is what makes
accent-insensitive search work and also inflates name_dupes for such pairs.
It does not transliterate: a Han, Arabic or Cyrillic name is only
lowercased, so it is findable in its own script and, separately, through
whichever names.common entry romanized it.

**Prefix search is cheap; substring search is not.** The sort makes a
leading prefix a range read over one or two row groups. A fragment in the
middle of a name has to scan the whole name_norm column.

**The index is far too large to load whole.** Use the range path, or query
it server-side with DuckDB. The CC-BY counterpart's 3.6 MB index is the one
designed to be full-loaded in a browser.

**level is this catalog's mapping, not Overture's admin_level.** Overture
files a dependency at admin_level 1 and leaves admin_level null below
county.

**name_lang is null on every primary row**, because Overture does not state
the language of names.primary. It is usually but not always the local
language.

**name_lang is not always a language code.** It is Overture's own
names.common key, carried through unchanged. 1,012 distinct keys appear in
this index; 965 are BCP-47 shaped and the other 47, covering 48,137 rows,
are OpenStreetMap annotation keys. genitive alone accounts for 46,479 of
them, and suffix, short, note, abbr and full make up most of the rest. The
rows are kept, because a user may type an inflected or abbreviated form and
the spelling is a real one, but an interface that prints name_lang as a
language label will print "genitive" at some point. The index-file contract
describes this column as BCP-47; it is BCP-47 for 99.1% of the alternative
rows and the source for the rest.

**name_lang on an alternative row is one of possibly several keys that
agree on that spelling.** The code kept is the first in alphabetical order,
which is arbitrary but stable across rebuilds; name_lang_count says how many
there were. A client that needs the full set has to read names.common from
the Overture release.

Every column is described in [collection.json](collection.json). The
human-facing page is at
[https://source.coop/portolan-mirrors/cn-geocoder-overture/names](https://source.coop/portolan-mirrors/cn-geocoder-overture/names).
