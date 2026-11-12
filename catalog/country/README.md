# Overture Divisions - Country and Dependency Boundaries

> [!WARNING]
> **This catalog is EXPERIMENTAL.** The schema may change without notice, the
> Source Cooperative repository that serves it is unlisted, and the column
> contract it publishes is still being negotiated with its consumer. Pin the
> `catalog_version` in [names/index.json](names/index.json) if you depend on
> it, and expect to rebuild.

The top of the Overture divisions hierarchy: sovereign countries and the
dependencies Overture files one level below them. This catalog keeps both in
one collection and at one level, because an ISO-coded dependency such as
Greenland or Puerto Rico is a country-equivalent for a name search even though
Overture gives it `admin_level` 1. The `subtype` column is what tells the two
apart.

Overture's country outlines are OpenStreetMap coastline, so they are the most
detailed geometry in this catalog by a wide margin and the least suitable to
draw directly. Use the display asset for a map and this file for measurement.

This is a **mirror**. [Overture Maps Foundation](https://overturemaps.org/)
produces the data; this catalog republishes release `2026-10-21.0` in
cloud-native form and changes no coordinate and no attribute value.

| | |
|---|---|
| Rows | 272 |
| Countries represented | 272 |
| Search index level | 0 |
| GeoParquet, full resolution | 51.4 MB, 34 row groups of 8 rows, zstd, page index |
| Row group | ~1.5 MB |
| GeoParquet, display | 5.2 MB, 19.6 KiB per feature |
| PMTiles | 2.5 MB, zoom 0-6 |
| Vertices, full vs display | 6,131,107 vs 366,568 (94.0% fewer) |
| Rows with a population | 212 of 272 |
| Average name languages | 182.7 |
| CRS | CRS84 (EPSG:4326), as published |
| Order | Hilbert curve over the whole globe |

The three largest by land area: Россия (RUS, 16,940,527 km²), Antarctica (ATA,
13,054,471 km²), Canada (CAN, 9,966,762 km²).

## Two geometry files, and which one to use

`overture_country.parquet` is Overture's own `class = 'land'` outline,
unchanged. Measure with it, clip with it, and fetch one feature from it by
range request when a user has committed to a place.

`overture_country_display.parquet` holds the same 272 rows, in the same order,
in the same 34 row groups, simplified with `ST_SimplifyPreserveTopology` and
then **buffered outward by the same tolerance**. Draw with it, and use it for
the first paint while the full geometry is still in flight.

The tolerance is per feature: 0.4% of that feature's own bounding-box diagonal,
capped at 0.03 degrees. In this collection it ranged from 5.79e-05 to 0.03
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
| Features | 272 |
| Fully contained | 210 (77.21%) |
| Below 99% contained | 0 |
| Worst | 0.997082 |
| Mean | 0.999958 |

The worst cases, which are the features whose true outline is narrower than the
tolerance somewhere:

| contained | division | country | subtype |
|---|---|---|---|
| 0.997082 | Spratly Islands | XR | country |
| 0.998327 | Saint Helena, Ascension and Tristan da Cunha | SHN | dependency |
| 0.998551 | Kiribati | KIR | country |
| 0.998635 | Kūki ʻĀirani | COK | dependency |
| 0.998945 | Polynésie Française | PYF | dependency |

**Two consequences.** Neighbouring divisions overlap along their shared edge in
the display file, so a point can fall in two of them; resolve with the full
file. And a display polygon is always at least as large as the true one, so
never compute an area from it.

## Get one feature

```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;

SELECT name, subtype, country, area_km2, population
FROM 'https://data.source.coop/portolan-mirrors/cn-geocoder-overture/country/overture_country.parquet'
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
class = 'maritime' polygon, which reaches to the territorial sea, is not
carried. A reverse geocode of a point offshore will not land in any row
here. Read the maritime polygon from the Overture release if you need
it.

**Antarctica is clipped at latitude -85.0511289.** That is the Web
Mercator limit, and it is where Overture's land polygon ends, so the
collection's southern extent is a projection artifact of the source
rather than a coastline. The 35 southernmost degrees of the continent
are absent.

**25 rows carry a synthetic country code with no ISO 3166-1 alpha-3
equivalent**, so country and country_iso2 hold the same string on those
rows: CP, XA, XB, XC, XD, XE, XG, XH, XI, XJ, XK, XL, XM, XN, XO, XP,
XQ, XR, XS, XT, XU, XW, XX, XY, XZ. Overture's schema permits this where
no internationally recognized code exists, which is mostly disputed or
unassigned territory. A client that assumes a three-letter code will
read two letters on those rows.

**Disputed boundaries carry no perspective.** Overture models a
contested boundary through its perspectives property, and that property
is NULL on all 4,700,999 division rows of this release, so there is
exactly one representation of every division here. This catalog
publishes whatever Overture published; it makes no territorial claim and
offers no way to select a perspective. A future release that populates
perspectives would force a choice this catalog has not made.

**population is sparse and undated.** 212 of 272 rows have one, and
Overture states no vintage per value. Use it as a relevance weight, not
as a census figure.

**parent_name is null on the 219 countries**, which have no parent. The
53 dependencies carry the country they depend on.

**Row order does not help a lookup by id.** The file is Hilbert-ordered
for spatial queries, so the division_id statistics per row group
overlap. Use the geometry_ref in the names collection, which names the
row group directly, or read the division_id column chunks, which are a
few per cent of the file.

**The display file is deliberately larger than the truth.** Neighbouring
features overlap along a shared edge, so a point can fall inside two of
them, and an area computed from it is too large. Draw and filter with
it; measure and clip with the full-resolution file.

The whole collection, with every column described, is in
[collection.json](collection.json). The human-facing page is at
[https://source.coop/portolan-mirrors/cn-geocoder-overture/country](https://source.coop/portolan-mirrors/cn-geocoder-overture/country).
