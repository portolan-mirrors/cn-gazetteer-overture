# Overture Divisions - Region Boundaries

> [!WARNING]
> **This catalog is EXPERIMENTAL.** The schema may change without notice, the
> Source Cooperative repository that serves it is unlisted, and the column
> contract it publishes is still being negotiated with its consumer. Pin the
> `catalog_version` in [names/index.json](names/index.json) if you depend on
> it, and expect to rebuild.

First-level subdivisions: what Overture calls a region and defines as the
largest sub-country administrative unit. In practice that is a state, a
province, a governorate, a canton or an oblast, and the `local_type` column
carries the word the country itself uses.

Region is the level where multilingual naming starts to pay off: Overture lists
an average of 37 language variants for a region against 8 for a county.

This is a **mirror**. [Overture Maps Foundation](https://overturemaps.org/)
produces the data; this catalog republishes release `2026-10-21.0` in
cloud-native form and changes no coordinate and no attribute value.

| | |
|---|---|
| Rows | 3,929 |
| Countries represented | 226 |
| Search index level | 1 |
| GeoParquet, full resolution | 231.0 MB, 152 row groups of 26 rows, zstd, page index |
| Row group | ~1.5 MB |
| GeoParquet, display | 23.9 MB, 6.2 KiB per feature |
| PMTiles | 19.3 MB, zoom 0-8 |
| Vertices, full vs display | 29,508,797 vs 1,748,873 (94.1% fewer) |
| Rows with a population | 1,204 of 3,929 |
| Average name languages | 37.4 |
| CRS | CRS84 (EPSG:4326), as published |
| Order | Hilbert curve over the whole globe |

The three largest by land area: Республика Саха (Якутия) (RUS, 3,070,426 km²),
Western Australia (AUS, 2,526,238 km²), Красноярский край (RUS, 2,331,878 km²).

## Two geometry files, and which one to use

`overture_region.parquet` is Overture's own `class = 'land'` outline,
unchanged. Measure with it, clip with it, and fetch one feature from it by
range request when a user has committed to a place.

`overture_region_display.parquet` holds the same 3,929 rows, in the same order,
in the same 152 row groups, simplified with `ST_SimplifyPreserveTopology` and
then **buffered outward by the same tolerance**. Draw with it, and use it for
the first paint while the full geometry is still in flight.

The tolerance is per feature: 0.4% of that feature's own bounding-box diagonal,
capped at 0.01 degrees. In this collection it ranged from 3.93e-05 to 0.01
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
| Features | 3,929 |
| Fully contained | 3,632 (92.44%) |
| Below 99% contained | 0 |
| Worst | 0.998256 |
| Mean | 0.999997 |

The worst cases, which are the features whose true outline is narrower than the
tolerance somewhere:

| contained | division | country | subtype |
|---|---|---|---|
| 0.998256 | Pamandzi | MYT | region |
| 0.999210 | Îles Sous-le-Vent | PYF | region |
| 0.999228 | 澎湖縣 | TWN | region |
| 0.999338 | Îles Australes | PYF | region |
| 0.999668 | Other British Virgin Islands | VGB | region |

**Two consequences.** Neighbouring divisions overlap along their shared edge in
the display file, so a point can fall in two of them; resolve with the full
file. And a display polygon is always at least as large as the true one, so
never compute an area from it.

## Get one feature

```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;

SELECT name, subtype, country, area_km2, population
FROM 'https://data.source.coop/portolan-mirrors/cn-geocoder-overture/region/overture_region.parquet'
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
polygons here do not tile the globe. Overture publishes regions for 226
countries.

**Disputed boundaries carry no perspective.** Overture models a
contested boundary through its perspectives property, and that property
is NULL on all 4,700,999 division rows of this release, so there is
exactly one representation of every division here. This catalog
publishes whatever Overture published; it makes no territorial claim and
offers no way to select a perspective.

**population is sparse and undated.** 1,204 of 3,929 rows have one.
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

**7 rows carry a synthetic country code with no ISO 3166-1 alpha-3
equivalent**, all of them XK, the code used for Kosovo. On those rows
country and country_iso2 hold the same two-letter string.

The whole collection, with every column described, is in
[collection.json](collection.json). The human-facing page is at
[https://source.coop/portolan-mirrors/cn-geocoder-overture/region](https://source.coop/portolan-mirrors/cn-geocoder-overture/region).
