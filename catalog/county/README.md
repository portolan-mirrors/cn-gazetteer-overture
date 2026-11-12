# Overture Divisions - County Boundaries

> [!WARNING]
> **This catalog is EXPERIMENTAL.** The schema may change without notice, the
> Source Cooperative repository that serves it is unlisted, and the column
> contract it publishes is still being negotiated with its consumer. Pin the
> `catalog_version` in [index.json](../names/index.json) if you depend on
> it, and expect to rebuild.

Second-level subdivisions: Overture's county, the largest sub-region
administrative unit in most countries. This is the level that lines up with
ADM2 in the CC-BY counterpart, so it is the one to compare when choosing
between the two catalogs.

The county level is where this catalog and the CC-BY one are most nearly
interchangeable, so it is the honest place to look at what ODbL buys: roughly
the same features, with alternative names attached.

This is a **mirror**. [Overture Maps Foundation](https://overturemaps.org/)
produces the data; this catalog republishes release `2026-10-21.0` in
cloud-native form and changes no coordinate and no attribute value.

| | |
|---|---|
| Rows | 38,937 |
| Countries represented | 171 |
| Search index level | 2 |
| GeoParquet, full resolution | 649.4 MB, 406 row groups of 96 rows, zstd, page index |
| Row group | ~1.6 MB |
| GeoParquet, display | 112.5 MB, 3.0 KiB per feature |
| PMTiles | 88.7 MB, zoom 0-9 |
| Vertices, full vs display | 82,088,290 vs 8,011,576 (90.2% fewer) |
| Rows with a population | 8,301 of 38,937 |
| Average name languages | 7.7 |
| CRS | CRS84 (EPSG:4326), as published |
| Order | Hilbert curve over the whole globe |

The three largest by land area: Таймырский Долгано-Ненецкий муниципальный округ
(RUS, 845,448 km²), Unorganized Borough (USA, 844,238 km²), Эвенкийский
муниципальный округ (RUS, 763,249 km²).

## Two geometry files, and which one to use

`overture_county.parquet` is Overture's own `class = 'land'` outline,
unchanged. Measure with it, clip with it, and fetch one feature from it by
range request when a user has committed to a place.

`overture_county_display.parquet` holds the same 38,937 rows, in the same
order, in the same 406 row groups, simplified with
`ST_SimplifyPreserveTopology` and then **buffered outward by the same
tolerance**. Draw with it, and use it for the first paint while the full
geometry is still in flight.

The tolerance is per feature: 0.4% of that feature's own bounding-box diagonal,
capped at 0.004 degrees. In this collection it ranged from 1.59e-06 to 0.004
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
| Features | 38,937 |
| Fully contained | 37,163 (95.44%) |
| Below 99% contained | 0 |
| Worst | 0.991267 |
| Mean | 0.999998 |

The worst cases, which are the features whose true outline is narrower than the
tolerance somewhere:

| contained | division | country | subtype |
|---|---|---|---|
| 0.991267 | Acadia First Nation | CAN | county |
| 0.996091 | Unincorporated South Coast | AUS | county |
| 0.998438 | Toshima | JPN | county |
| 0.998950 | Кронштадтский район | RUS | county |
| 0.999046 | Siljan | NOR | county |

**Two consequences.** Neighbouring divisions overlap along their shared edge in
the display file, so a point can fall in two of them; resolve with the full
file. And a display polygon is always at least as large as the true one, so
never compute an area from it.

## Get one feature

```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;

SELECT name, subtype, country, area_km2, population
FROM 'https://data.source.coop/portolan-mirrors/cn-geocoder-overture/county/overture_county.parquet'
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
  tracker](https://github.com/portolan-mirrors/cn-geocoder-overture) for this
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
polygons here do not tile the globe. Overture publishes counties for 171
countries.

**Disputed boundaries carry no perspective.** Overture models a
contested boundary through its perspectives property, and that property
is NULL on all 4,700,999 division rows of this release, so there is
exactly one representation of every division here. This catalog
publishes whatever Overture published; it makes no territorial claim and
offers no way to select a perspective.

**population is sparse and undated.** 8,301 of 38,937 rows have one.
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

**51 rows carry a synthetic country code** with no ISO 3166-1 alpha-3
equivalent: XG, XK, XP, XR, XU, XW. On those rows country and
country_iso2 hold the same two-letter string.

The whole collection, with every column described, is in
[collection.json](collection.json). The human-facing page is at
[https://source.coop/portolan-mirrors/cn-geocoder-overture/county](https://source.coop/portolan-mirrors/cn-geocoder-overture/county).
