# EXPERIMENTAL: Overture Divisions Cloud-Native Gazetteer (ODbL)

> [!WARNING]
> **This catalog is EXPERIMENTAL.** The schema may change without notice, the
> Source Cooperative repository that serves it is unlisted, and the column
> contract it publishes is still being negotiated with its consumer. Pin the
> `catalog_version` in [index.json](names/index.json) if you depend on
> it, and expect to rebuild.

Overture Maps divisions, release `2026-10-21.0`, republished as a
**cloud-native gazetteer**: GeoParquet and PMTiles laid out so a browser can
search and draw administrative places over HTTP range requests, with no server
and no API key. Five boundary levels from country down to locality, each with a
display-simplified companion, and a multilingual gazetteer index over all of
them.

It is a **gazetteer, not a geocoder**: it resolves place names and
administrative boundaries, not street addresses. There is no house number, no
street centerline and no interpolation here. The geocoder is the client that
consumes this.

This is a **mirror**. [Overture Maps Foundation](https://overturemaps.org/)
produces the data and remains the authoritative source. This catalog adds no
division and changes no coordinate.

## Which catalog should you use?

There are two, built to the same column contract, and the choice is about
licence and coverage rather than quality.

| | this catalog | [geoboundaries-catalog](https://source.coop/portolan-mirrors/geoboundaries-catalog) |
|---|---|---|
| Licence | **ODbL-1.0**, share-alike | CC-BY-4.0, attribution only |
| Status | **experimental**, unlisted | the default |
| Levels | country, region, county, localadmin, **locality** | ADM0, ADM1, ADM2 |
| City and village boundaries | yes | no |
| Multilingual names | yes, 2,031,617 alternative spellings | no |
| Stable feature key | Overture GERS id | geoBoundaries `shapeID` |
| Index size | 409.2 MB, range-request path | 3.6 MB, loads whole |

**Take the CC-BY one unless you need what this one adds.** Share-alike is a
real obligation: a database you derive from this catalog has to be offered
under ODbL too. A geocoder widget can be pointed at either index by changing
one URL, so the decision is reversible and belongs to whoever ships the
application, not to whoever builds it.

## What it publishes

| collection | level | rows | GeoParquet | display | PMTiles |
|---|---|---|---|---|---|
| [`country`](country/collection.json) | 0 | 272 | 51.4 MB | 5.2 MB | 2.5 MB |
| [`region`](region/collection.json) | 1 | 3,929 | 231.0 MB | 23.9 MB | 19.3 MB |
| [`county`](county/collection.json) | 2 | 38,937 | 649.4 MB | 112.5 MB | 88.7 MB |
| [`localadmin`](localadmin/collection.json) | 3 | 21,502 | 142.6 MB | 53.8 MB | 42.4 MB |
| [`locality`](locality/collection.json) | 4 | 556,094 | 1.2 GB | 870.7 MB | 682.8 MB |
| [`names`](names/collection.json) | 0-4 | 5,604,413 | 409.2 MB | - | 146.3 MB |

About 4.7 GB in all. The five boundary levels are **not** a seamless coverage
the way a composite is: Overture publishes a division where a division exists,
so a country with no localadmin level simply has no rows at that level. The
[`names`](names/collection.json) index is the only complete view, and it covers
3,572,796 divisions including the millions Overture publishes as a point with
no boundary at all.

## How a geocoder widget uses this

The end-to-end path this catalog was shaped for, as the cloud-native map
widgets project implements it:

1. **Focus.** The search box is focused. The client fetches
   [names/index.json](names/index.json), about a kilobyte, and learns the
   index's size, row group count, `catalog_version` and required attribution.
   It renders the attribution immediately, because ODbL requires it whether or
   not a search happens.
2. **Index load.** The index is 409.2 MB, so the client takes the
   **range-request path**: one exactly-sized 2,150,142-byte tail request for
   the footer, then a binary search over the row group statistics on
   `name_norm`.
3. **Keystrokes.** Each typed prefix is folded with the same rule the index
   used and resolved from a median of 1 row group of about 475.2 KB. Results
   arrive as a mixture of primary and alternative-spelling rows, in any
   language; the client dedupes by `feature_id` and ranks on `level`,
   `population`, `prominence`, `name_dupes` and whether the bbox intersects the
   current viewport.
4. **Selection, drawn instantly.** The chosen row carries a GERS `feature_id`,
   a bbox to fly to, a point to mark, and an advisory `geometry_ref` of file,
   row group and row. The client range-reads that one row group of the
   **display** file, 157 KB at the country level and 1.5 MB at the locality
   level, and decodes one outline out of it: 19.6 KiB for a country, 1.6 KiB
   for a village. The outline is the outward-buffered one, so it draws before
   the camera has finished moving and it never shows less ground than the
   division covers.
5. **Full resolution in the background.** The same `geometry_ref` indexes the
   full-resolution file, because the two hold the same rows in the same groups.
   That read is 1.5 to 1.7 MB, one row group, and the client swaps the geometry
   in when it arrives. It verifies that the `division_id` it decoded equals the
   `feature_id` it asked for before it trusts either file, because
   `geometry_ref` is a hint and only the `catalog_version` makes it valid.
6. **The boundary does work.** That polygon is then the spatial filter for any
   other cloud-native dataset: a GeoParquet of field boundaries, a COG, a
   PMTiles archive. Filter with the display geometry, which over-selects on
   purpose, and clip with the full-resolution one.

The consumption recipes for each step are in the collection agent guides,
starting at [names/AGENTS.md](names/AGENTS.md). The equivalent guides in the
[CC-BY
sibling](https://source.coop/portolan-mirrors/geoboundaries-catalog/names)
describe the same contract against the smaller index.

## Read these first

- [AGENTS.md](AGENTS.md): the collections, the join keys, and the traps that
  produce wrong answers.
- [changes-from-upstream.md](changes-from-upstream.md): every row and column
  this catalog drops, derives or adds, and how to get vanilla Overture instead.
- [names/README.md](names/README.md): the search index, and how to read it
  without downloading it.
- [catalog.json](catalog.json): the STAC entry point.

## The upstream data vs our optimized files - why both exist and when to use which

Every collection here links the **upstream Overture release** it was built
from, as `upstream-division-s3`, `upstream-division-area-s3` and
`upstream-divisions-azure` assets. Nothing in this catalog asks you to take a
mirror's word for its own contents.

**Use the upstream release when** you want the authoritative bytes, the whole
theme for analysis in DuckDB or Spark or GDAL, the columns this catalog's
projection drops, or a second opinion on anything here. It is the product of
record: Overture publishes it, versions it immutably, and is who you credit.

    s3://overturemaps-us-west-2/release/2026-10-21.0/theme=divisions/
    (type=division, type=division_area)
    https://overturemapswestus2.blob.core.windows.net/release/2026-10-21.0/theme=divisions/

Both are public and anonymous, and the requester does not pay. Measured
2026-11-12, the **S3 HTTPS endpoint sends CORS** (`Access-Control-Allow-Origin:
*`, with `Content-Range` and `Accept-Ranges` exposed) and answers
`Accept-Ranges: bytes`, so a browser *can* range-read the upstream release
directly. The **Azure mirror sends no CORS headers at all** and cannot be read
from a browser cross-origin.

So reachability is **not** the reason this catalog exists. Layout is. Measured
on `part-00000` of `type=division`, the upstream file a name search would have
to read:

| | upstream release | this catalog |
|---|---|---|
| files to search by name | 1 file, 584 MB (plus 8 files, 4.6 GB, for the polygons) | one sorted index, 409.2 MB, or the 12.9 MiB prominent index |
| sorted by name | no - `sorting_columns` not declared | yes, `name_norm` byte-wise, declared in the footer |
| find one place by name | scan every part file | binary search over row group statistics, one range request |
| row groups | 256 groups of ~18,400 rows, median 2.22 MB, up to 3.85 MB | 876 groups of 6,400 rows in the index; 8 to 960 rows in the boundary files, sized by what one feature costs |
| columns | 50 leaf chunks of the full schema, nested structs | a flat projection; 20 columns in the index |
| footer read | 1.47 MB, and **two** requests, because a speculative 512 KiB tail falls short | exact `footer_bytes` and `footer_metadata_bytes` in `names/index.json`, one request |
| one division's outline | a multi-megabyte row group of the full schema | one row group of a display file, simplified and outward-buffered |
| multilingual search | unnest a `names.common` map per row at query time | 2,031,617 pre-expanded alternative-spelling rows, in the sort |
| tiles | none | PMTiles per collection |

None of that is a criticism of the upstream files: they are laid out for bulk
analytics, which is what most consumers want, and they are very good at it.
They are simply not laid out for a browser answering a keystroke, and no amount
of client cleverness fixes a 2.22 MB row group or an undeclared sort. That is
the whole content of this catalog: the same data, reprojected and relaid out,
so each of those rows in the right-hand column is one small range request.

What this catalog changes about the data itself - every row and column it
drops, derives or adds - is in
[changes-from-upstream.md](changes-from-upstream.md). Read it before you treat
anything here as vanilla Overture.

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

Overture Maps divisions, release `2026-10-21.0`, staged from
`s3://overturemaps-us-west-2/release/2026-10-21.0/theme=divisions/` on
2026-11-12. A release is immutable, so the release identifier alone pins the
bytes; there is no commit or checksum to carry. Overture announces each release
in its [release notes](https://docs.overturemaps.org/blog/) and schedules them
on its [release calendar](https://docs.overturemaps.org/release-calendar/).

The [source
repository](https://github.com/portolan-mirrors/cn-gazetteer-overture) holds
the pipeline that built this, the per-collection provenance records and the
issue tracker.
