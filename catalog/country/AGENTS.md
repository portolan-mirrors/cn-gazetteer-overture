# AGENTS.md — Overture Divisions - Country and Dependency Boundaries

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

One land polygon per Overture division of subtype `country` and `dependency`,
from release `2026-10-21.0`. This catalog's search level is **0**. Public root:
`https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/catalog.json`

```
country/overture_country.parquet          51.4 MB, 272 rows, 34 row groups of 8
country/overture_country_display.parquet  5.2 MB, same rows, same order, same groups
country/country.pmtiles                   2.5 MB, zoom 0-6, layer "country"
```

Geometry is Overture's `class = 'land'` division area: its land-clipped,
non-maritime outline, which Overture documents as intended for map rendering
and cartographic display **[attested: [division_area
schema](https://docs.overturemaps.org/schema/reference/divisions/division_area)]**.
The `maritime` polygon it also publishes for a coastal division is not carried
here.

## Accessing the data

```sql
INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;
```

Every file here is readable in place over HTTPS range requests. No
credentials, no API, no server.

Two Parquet files, and the choice between them is not cosmetic.

- **`overture_country.parquet`** is the full-resolution geometry, unchanged
  from Overture. Measure with it, clip with it, and fetch one feature from it
  when precision matters. One row group is about 1.5 MB.
- **`overture_country_display.parquet`** is the same rows simplified and then
  buffered **outward**, about 19.6 KiB a feature. Draw with it and filter with
  it. It is a **superset** of the true outline, so neighbouring features
  overlap along a shared edge and an area computed from it is too large.
  Verified per feature: 210 of 272 contain their full-resolution polygon
  exactly, none falls below 99%, worst 0.997082.

Both files declare the GeoParquet 1.1 bbox covering, carry a Parquet page index
on every column, and are ordered along a Hilbert curve over the whole globe.
Both carry `cnmw:catalog_version = overture-divisions-2026-10-21.0` in their
footer key-value metadata, which is what a consumer checks against
[index.json](../names/index.json) before trusting a `geometry_ref`.

## Schema & field notes

Every column is described in [collection.json](collection.json) under
`table:columns`, with the tier of each claim. The ones that decide whether a
query is right:

| column | what it is |
|---|---|
| `division_id` | **the join key.** The division's GERS id, and the `feature_id` the names collection publishes |
| `id` | the *polygon's* GERS id. Not a join key for anything in this catalog |
| `country` | derived ISO 3166-1 **alpha-3** |
| `country_iso2` | Overture's own alpha-2, unchanged |
| `subtype` | Overture's placetype |
| `level` | not a column here. It is this catalog's 0-to-4 mapping and it is **0** for every row of this collection |

Overture's own schema for these properties is carried as an asset:
[division.schema.yaml](../_assets/overture/division.schema.yaml) and
[division_area.schema.yaml](../_assets/overture/division_area.schema.yaml). The
theme guide is at
[https://docs.overturemaps.org/guides/divisions](https://docs.overturemaps.org/guides/divisions).

## Data quality & usage notes

1. **`id` is not the join key.** Join on `division_id`.
2. **This collection holds two subtypes.** 219 countries and 53 dependencies,
   which Overture files at `admin_level` 1. Filter on `subtype` if you want
   only sovereign states.
3. **`country` is alpha-3 and derived; `country_iso2` is Overture's own
   alpha-2.** 25 rows carry a synthetic code with no alpha-3 equivalent, and on
   those two rows the two columns are equal and two letters long.
4. **Antarctica stops at latitude -85.0511289**, the Web Mercator limit,
   because that is where Overture's land polygon ends.
5. **The geometry is the land outline.** Overture's `maritime` polygon is not
   carried, so an offshore point is in no row here.

Everything else a consumer would otherwise find the hard way is in the
collection's `known_issues`, rendered in [README.md](README.md).

## Example queries

**What the file holds, by subtype** **[derived]**

```sql
SELECT subtype, count(*) AS n, count(DISTINCT country) AS countries,
       round(min(area_km2), 2) AS min_km2,
       round(max(area_km2)) AS max_km2
FROM 'https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/country/overture_country.parquet'
GROUP BY 1 ORDER BY 2 DESC;
```

```
subtype     n    countries  min_km2  max_km2
country     219  219        0.49     1.69405e+07
dependency  53   53         5.9      2.16174e+06
```

**Resolve one division by its GERS id, the way a geocoder does** **[derived]**

```sql
SELECT name, subtype, country, parent_name, area_km2, vertices,
       bbox.xmin, bbox.ymin, bbox.xmax, bbox.ymax
FROM 'https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/country/overture_country.parquet'
WHERE division_id = (SELECT division_id FROM 'https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/country/overture_country.parquet'
                     ORDER BY area_km2 DESC LIMIT 1);
```

```
name    subtype  country  parent_name  area_km2     vertices  xmin  ymin     xmax  ymax
Россия  country  RUS      NULL         1.69405e+07  224251    -180  41.1851  180   81.8591
```

`division_id` is the join key and the value the names collection publishes as
`feature_id`. **`id` is a different GERS identifier**, belonging to the polygon
rather than to the division, and joining on it finds nothing **[attested:
[division_area
schema](https://docs.overturemaps.org/schema/reference/divisions/division) ]**.

**A bounding-box query, which the covering metadata makes cheap** **[derived]**

```sql
SELECT name, country, round(area_km2) AS area_km2
FROM 'https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/country/overture_country.parquet'
WHERE bbox.xmin < 12.5 AND bbox.xmax > 11.5
  AND bbox.ymin < 56.0 AND bbox.ymax > 55.0
ORDER BY area_km2 DESC;
```

```
name           country  area_km2
Россия         RUS      1.69405e+07
United States  USA      9.47701e+06
Sverige        SWE      449550
Deutschland    DEU      357630
Danmark        DNK      43120
```

The `bbox` struct is declared as the GeoParquet 1.1 covering for the geometry
column, so a reader prunes row groups on it without decoding any WKB. Filter on
`bbox` first and call `ST_Intersects` on what survives.

**How much the display companion saves** **[derived]**

```sql
SELECT count(*) AS rows,
       sum(f.vertices) AS full_vertices,
       sum(d.vertices) AS display_vertices,
       round(100 - 100.0 * sum(d.vertices) / sum(f.vertices), 1)
         AS pct_fewer
FROM 'https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/country/overture_country.parquet' f JOIN 'https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/country/overture_country_display.parquet' d USING (division_id);
```

```
rows  full_vertices  display_vertices  pct_fewer
272   6131107        366568            94
```

The two files hold the same rows in the same order in the same row groups, so
this join is a formality: row *i* of one is row *i* of the other, which is what
makes the search index's `geometry_ref` valid against both.

**The most multilingual divisions in this collection** **[derived]**

```sql
SELECT name, country, name_langs
FROM 'https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/country/overture_country.parquet'
ORDER BY name_langs DESC, name LIMIT 8;
```

```
name            country  name_langs
افغانستان       AFG      301
United Kingdom  GBR      299
中国              CHN      297
Chile           CHL      296
مصر             EGY      295
Россия          RUS      290
საქართველო      GEO      289
Shqipëria       ALB      288
```

`name_langs` counts the language codes in Overture's `names.common` map for
that division. The spellings themselves are indexed in the [names
collection](../names/collection.json).

## Related collections

- [names](../names/collection.json) — the multilingual search index over every
  level, and the only complete view of the divisions in this catalog. Start
  there to turn a typed name into a `division_id`.
- [region](../region/collection.json) — level 1
- [county](../county/collection.json) — level 2
- [localadmin](../localadmin/collection.json) — level 3
- [locality](../locality/collection.json) — level 4
- [geoboundaries-catalog](https://source.coop/portolan-mirrors/geoboundaries-catalog)
  — the CC-BY-4.0 counterpart, without share-alike, without localities and
  without alternative names.
