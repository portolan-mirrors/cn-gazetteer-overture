# Overture Divisions - Locality Boundaries

> [!WARNING]
> **This catalog is EXPERIMENTAL.** The schema may change without notice, the
> Source Cooperative repository that serves it is unlisted, and the column
> contract it publishes is still being negotiated with its consumer. Pin the
> `catalog_version` in [names/index.json](names/index.json) if you depend on
> it, and expect to rebuild.

Populated places with a boundary: cities, towns, villages and hamlets. This is
the collection the CC-BY counterpart has no equivalent for, and the reason to
accept ODbL.

Only a minority of Overture's localities have a polygon. The rest are points,
and they are all in the names collection, which says per row whether a boundary
exists here.

This is a **mirror**. [Overture Maps Foundation](https://overturemaps.org/)
produces the data; this catalog republishes release `2026-10-21.0` in
cloud-native form and changes no coordinate and no attribute value.

| | |
|---|---|
| Rows | 556,094 |
| Countries represented | 229 |
| Search index level | 4 |
| GeoParquet, full resolution | 1.2 GB, 580 row groups of 960 rows, zstd, page index |
| Row group | ~2.2 MB |
| GeoParquet, display | 870.7 MB, 1.6 KiB per feature |
| PMTiles | 682.8 MB, zoom 0-11 |
| Vertices, full vs display | 182,154,812 vs 60,733,543 (66.7% fewer) |
| Rows with a population | 249,776 of 556,094 |
| Average name languages | 3.5 |
| CRS | CRS84 (EPSG:4326), as published |
| Order | Hilbert curve over the whole globe |

The three largest by land area: Unorganized Kenora District (CAN, 439,419 km²),
Rivière-Koksoak (CAN, 346,846 km²), ᐄᔨᔨᐤ ᐊᔅᒌ ᒉᐃᒥᔅ ᐯᐃ Eeyou Istchee Baie-James
(CAN, 345,655 km²).

## Two geometry files, and which one to use

`overture_locality.parquet` is Overture's own `class = 'land'` outline,
unchanged. Measure with it, clip with it, and fetch one feature from it by
range request when a user has committed to a place.

`overture_locality_display.parquet` holds the same 556,094 rows, in the same
order, in the same 580 row groups, simplified with
`ST_SimplifyPreserveTopology` and then **buffered outward by the same
tolerance**. Draw with it, and use it for the first paint while the full
geometry is still in flight.

The tolerance is per feature: 0.4% of that feature's own bounding-box diagonal,
capped at 0.0005 degrees. In this collection it ranged from 1.21e-08 to 0.0005
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
| Features | 556,094 |
| Fully contained | 544,866 (97.98%) |
| Below 99% contained | 0 |
| Worst | 0.996051 |
| Mean | 0.999999 |

The worst cases, which are the features whose true outline is narrower than the
tolerance somewhere:

| contained | division | country | subtype |
|---|---|---|---|
| 0.996051 | Île-d'Aix | FRA | locality |
| 0.996582 | Ilganii de Sus | ROU | locality |
| 0.997118 | Дунино | RUS | locality |
| 0.997191 | Улановы | RUS | locality |
| 0.997243 | 惠远镇牧业队 | CHN | locality |

**Two consequences.** Neighbouring divisions overlap along their shared edge in
the display file, so a point can fall in two of them; resolve with the full
file. And a display polygon is always at least as large as the true one, so
never compute an area from it.

## Get one feature

```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;

SELECT name, subtype, country, area_km2, population
FROM 'https://data.source.coop/portolan-mirrors/cn-geocoder-overture/locality/overture_locality.parquet'
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

- Overture divisions guide: https://docs.overturemaps.org/guides/divisions
- Schema, carried as an asset:
  [division.schema.yaml](../_assets/overture/division.schema.yaml),
  [division_area.schema.yaml](../_assets/overture/division_area.schema.yaml)
- Pipeline and issue tracker:
  https://github.com/portolan-mirrors/cn-geocoder-overture

## Known issues

**EXPERIMENTAL.** The schema may change without notice and the Source
Cooperative repository is unlisted. Pin the catalog_version in
names/index.json if you depend on this.

**ODbL share-alike.** A database derived from this collection has to be
released under ODbL, and an application that shows it has to display the
attribution. The CC-BY-4.0 counterpart at
https://source.coop/portolan-mirrors/geoboundaries-catalog carries no
such obligation.

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
polygons here do not tile the globe. Overture's own guide describes
coverage below county as spotty while present in every country, and the
15.85% polygon rate is the measured form of that. 205 countries have at
least one locality polygon.

**Disputed boundaries carry no perspective.** Overture models a
contested boundary through its perspectives property, and that property
is NULL on all 4,700,999 division rows of this release, so there is
exactly one representation of every division here. This catalog
publishes whatever Overture published; it makes no territorial claim and
offers no way to select a perspective.

**population is sparse and undated.** 249,776 of 556,094 rows have one.
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

**admin_level is absent**, as Overture does not require it below county.
Use this catalog's own level, 4.

**class is null on 113,393 rows.** Overture classed the rest as hamlet,
village, town or city; megacity has no rows in this release. A style
that matches on class paints the unclassed rows in its fallback colour.

**prominence is Overture's cartographic guidance, not a measurement.**
It is populated on every locality and on no other subtype, which makes
it the best ranking signal this catalog has for a city search and still
not a statistic.

The whole collection, with every column described, is in
[collection.json](collection.json). The human-facing page is at
[https://source.coop/portolan-mirrors/cn-geocoder-overture/locality](https://source.coop/portolan-mirrors/cn-geocoder-overture/locality).
