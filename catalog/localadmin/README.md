# Overture Divisions - Local Administrative Boundaries

> [!WARNING]
> **This catalog is EXPERIMENTAL.** The schema may change without notice, the
> Source Cooperative repository that serves it is unlisted, and the column
> contract it publishes is still being negotiated with its consumer. Pin the
> `catalog_version` in [index.json](../names/index.json) if you depend on
> it, and expect to rebuild.

The administrative level that contains localities without having an authority
of its own: the French commune, the Indonesian kecamatan, the Swiss Gemeinde.
**Coverage is partial**, and that is the first thing to know about this
collection.

A client must not read an empty result here as 'no such place'. It usually
means the country publishes no localadmin level at all.

This is a **mirror**. [Overture Maps Foundation](https://overturemaps.org/)
produces the data; this catalog republishes release `2026-10-21.0` in
cloud-native form and changes no coordinate and no attribute value.

| | |
|---|---|
| Rows | 21,502 |
| Countries represented | 19 |
| Search index level | 3 |
| GeoParquet, full resolution | 142.6 MB, 90 row groups of 240 rows, zstd, page index |
| Row group | ~1.6 MB |
| GeoParquet, display | 53.8 MB, 2.6 KiB per feature |
| PMTiles | 42.4 MB, zoom 0-10 |
| Vertices, full vs display | 19,868,586 vs 3,737,049 (81.2% fewer) |
| Rows with a population | 7,523 of 21,502 |
| Average name languages | 6.3 |
| CRS | CRS84 (EPSG:4326), as published |
| Order | Hilbert curve over the whole globe |

The three largest by land area: 若羌县 چاقىلىق ناھىيىسى (CHN, 197,840 km²), 且末县
(CHN, 138,088 km²), 改则县 སྒེར་རྩེ་རྫོང་། (CHN, 135,525 km²).

## Two geometry files, and which one to use

`overture_localadmin.parquet` is Overture's own `class = 'land'` outline,
unchanged. Measure with it, clip with it, and fetch one feature from it by
range request when a user has committed to a place.

`overture_localadmin_display.parquet` holds the same 21,502 rows, in the same
order, in the same 90 row groups, simplified with `ST_SimplifyPreserveTopology`
and then **buffered outward by the same tolerance**. Draw with it, and use it
for the first paint while the full geometry is still in flight.

The tolerance is per feature: 0.4% of that feature's own bounding-box diagonal,
capped at 0.002 degrees. In this collection it ranged from 1.02e-05 to 0.002
degrees. A flat tolerance was tried first and rejected: it cannot serve both
the largest and the smallest feature in one collection, and at the country
level it put one dependency's display polygon at 81.6% of its true area.

The outward buffer is the part to understand. Simplification moves a vertex by
up to the tolerance in either direction, so a simplified outline cuts corners
inside the true boundary as often as outside it, and a download filtered
against it would silently miss features in the slivers it cut away. Buffering
outward pushes the whole outline back past the original, so the error is always
inclusive: a filter over-selects, which a later exact pass removes, rather than
under-selecting, which nothing recovers.

Verified on every feature of this collection, as the ratio of the true
polygon's area that the display polygon covers:

| | |
|---|---|
| Features | 21,502 |
| Fully contained | 20,610 (95.85%) |
| Below 99% contained | 0 |
| Worst | 0.994748 |
| Mean | 0.999998 |

The worst cases, which are the features whose true outline is narrower than the
tolerance somewhere:

| contained | division | country | subtype |
|---|---|---|---|
| 0.994748 | Comuna de Villa Candelaria Norte | ARG | localadmin |
| 0.997940 | Tolochenaz | CHE | localadmin |
| 0.999303 | Hôrka nad Váhom | SVK | localadmin |
| 0.999327 | Vracovice | CZE | localadmin |
| 0.999391 | Soběšovice | CZE | localadmin |

**Two consequences.** Neighbouring divisions overlap along their shared edge in
the display file, so a point can fall in two of them; resolve with the full
file. And a display polygon is always at least as large as the true one, so
never compute an area from it.

## Get one feature

```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;

SELECT name, subtype, country, area_km2, population
FROM 'https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/localadmin/overture_localadmin.parquet'
WHERE division_id = '<a GERS id from the names collection>';
```

The bbox covering metadata and the row group statistics let DuckDB, GDAL or a
browser Parquet reader skip to the right row group without decoding any
geometry. See [AGENTS.md](AGENTS.md) for the queries that have been run against
the published files.

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

Built from Overture Maps divisions release `2026-10-21.0`, staged from
`s3://overturemaps-us-west-2/release/2026-10-21.0/theme=divisions/` on
2026-11-12. An Overture release is immutable, so the release identifier alone
pins the bytes.

Every row here comes from a `type=division_area` feature with `class = 'land'`,
joined to its `type=division` row on `division_id` for the names, the class,
the population and the parent. The filter is also what makes the join 1:1, and
the build refuses to publish if it is not. Full details of what this catalog
changes, drops and adds are in
[changes-from-upstream.md](../changes-from-upstream.md).

- Overture's own [divisions
  guide](https://docs.overturemaps.org/guides/divisions), which defines every
  subtype and states its coverage.
- Schema, carried as an asset:
  [division.schema.yaml](../_assets/overture/division.schema.yaml),
  [division_area.schema.yaml](../_assets/overture/division_area.schema.yaml)
- The [pipeline and issue
  tracker](https://github.com/portolan-mirrors/cn-gazetteer-overture) for this
  catalog.

## Known issues

**EXPERIMENTAL.** The schema may change without notice and the Source
Cooperative repository is unlisted. Pin the catalog_version in
[index.json](../names/index.json) if you depend on this.

**ODbL share-alike.** A database derived from this collection has to be
released under ODbL, and an application that shows it has to display the
attribution. The [CC-BY-4.0
counterpart](https://source.coop/portolan-mirrors/geoboundaries-catalog)
carries no such obligation.

**Join on division_id, never on id.** Both are GERS identifiers. id
belongs to the division_area polygon; division_id belongs to the
division, and division_id is what the names collection publishes as
feature_id. A join on id finds nothing.

**This is the land outline, not the territorial extent.** Overture's
class = 'maritime' polygon is not carried, so a reverse geocode of an
offshore point will not land in any row here.

**This level is not a seamless coverage.** Overture publishes a division
where a division exists. There is no gap-filling from a coarser level,
so a country with no divisions at this level simply has no rows, and the
polygons here do not tile the globe. At this level that matters more
than anywhere else: Overture publishes localadmin divisions for 19
countries and none at all for the other 230 in the release. The 19, as
ISO 3166-1 alpha-3: ARG, AUT, BEL, BFA, CHE, CHN, CIV, CZE, FRA, HTI,
IDN, IRN, IRQ, JOR, MAR, SEN, SLE, SVK, SYR. A client must not read an
empty result here as 'no such place'.

**Disputed boundaries carry no perspective.** Overture models a
contested boundary through its perspectives property, and that property
is NULL on all 4,700,999 division rows of this release, so there is
exactly one representation of every division here. This catalog
publishes whatever Overture published; it makes no territorial claim and
offers no way to select a perspective.

**population is sparse and undated.** 7,523 of 21,502 rows have one.
Overture states no vintage per value. Use it as a relevance weight, not
as a census figure.

**Row order does not help a lookup by id.** The file is Hilbert-ordered
for spatial queries, so the division_id statistics per row group
overlap. Use the geometry_ref in the names collection, which names the
row group directly, or read the division_id column chunks, which are a
few per cent of the file.

**The display file is deliberately larger than the truth.** Neighbouring
features overlap along a shared edge, so a point can fall inside two of
them, and an area computed from it is too large. Draw and filter with
it; measure and clip with the full-resolution file.

**admin_level is absent.** Overture requires it only down to county, and
it is null on every localadmin division in the release, so the column is
dropped rather than published empty. Use this catalog's own level, 3,
which the names collection publishes.

The whole collection, with every column described, is in
[collection.json](collection.json). The human-facing page is at
[https://source.coop/portolan-mirrors/cn-gazetteer-overture/localadmin](https://source.coop/portolan-mirrors/cn-gazetteer-overture/localadmin).
