# AGENTS.md — Overture Divisions - Locality Boundaries

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

One land polygon per Overture division of subtype `locality`, from release
`2026-10-21.0`. This catalog's search level is **4**. Public root:
`https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/catalog.json`

```
locality/overture_locality.parquet          1.2 GB, 556,094 rows, 580 row groups of 960
locality/overture_locality_display.parquet  870.7 MB, same rows, same order, same groups
locality/locality.pmtiles                   682.8 MB, zoom 0-11, layer "locality"
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

- **`overture_locality.parquet`** is the full-resolution geometry, unchanged
  from Overture. Measure with it, clip with it, and fetch one feature from it
  when precision matters. One row group is about 2.2 MB.
- **`overture_locality_display.parquet`** is the same rows simplified and then
  buffered **outward**, about 1.6 KiB a feature. Draw with it and filter with
  it. It is a **superset** of the true outline, so neighbouring features
  overlap along a shared edge and an area computed from it is too large.
  Verified per feature: 544,866 of 556,094 contain their full-resolution
  polygon exactly, none falls below 99%, worst 0.996051.

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
| `level` | not a column here. It is this catalog's 0-to-4 mapping and it is **4** for every row of this collection |

Overture's own schema for these properties is carried as an asset:
[division.schema.yaml](../_assets/overture/division.schema.yaml) and
[division_area.schema.yaml](../_assets/overture/division_area.schema.yaml). The
theme guide is at
[https://docs.overturemaps.org/guides/divisions](https://docs.overturemaps.org/guides/divisions).

## Data quality & usage notes

1. **`id` is not the join key.** Join on `division_id`.
2. **This is only the 15.85% of Overture's localities that have a polygon.**
   2,952,062 more exist as a point and are in the names collection with
   `has_boundary = false`. Treating this collection as the list of settlements
   understates it by a factor of six.
3. **`class` is null on 113,393 rows.** Overture classed the rest.
4. **`prominence` is cartographic guidance, not a measurement.** It is the best
   ranking signal here and still not a statistic.

Everything else a consumer would otherwise find the hard way is in the
collection's `known_issues`, rendered in [README.md](README.md).

## Example queries

**What the file holds, by subtype** **[derived]**

```sql
SELECT subtype, count(*) AS n, count(DISTINCT country) AS countries,
       round(min(area_km2), 2) AS min_km2,
       round(max(area_km2)) AS max_km2
FROM 'https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/locality/overture_locality.parquet'
GROUP BY 1 ORDER BY 2 DESC;
```

```
subtype   n       countries  min_km2  max_km2
locality  556094  229        0        439419
```

**Resolve one division by its GERS id, the way a geocoder does** **[derived]**

```sql
SELECT name, subtype, country, parent_name, area_km2, vertices,
       bbox.xmin, bbox.ymin, bbox.xmax, bbox.ymax
FROM 'https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/locality/overture_locality.parquet'
WHERE division_id = (SELECT division_id FROM 'https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/locality/overture_locality.parquet'
                     ORDER BY area_km2 DESC LIMIT 1);
```

```
name                         subtype   country  parent_name      area_km2  vertices  xmin     ymin     xmax      ymax
Unorganized Kenora District  locality  CAN      Kenora District  439419    65152     -95.156  49.0011  -81.5242  56.8614
```

`division_id` is the join key and the value the names collection publishes as
`feature_id`. **`id` is a different GERS identifier**, belonging to the polygon
rather than to the division, and joining on it finds nothing **[attested:
[division_area
schema](https://docs.overturemaps.org/schema/reference/divisions/division) ]**.

**A bounding-box query, which the covering metadata makes cheap** **[derived]**

```sql
SELECT name, country, round(area_km2) AS area_km2
FROM 'https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/locality/overture_locality.parquet'
WHERE bbox.xmin < 12.5 AND bbox.xmax > 11.5
  AND bbox.ymin < 56.0 AND bbox.ymax > 55.0
ORDER BY area_km2 DESC;
```

```
name            country  area_km2
Viemose Skov    DNK      2
Bulte           DNK      0
Torpe           DNK      0
Østermark       DNK      0
Hovedskov       DNK      0
Hegnede Bakker  DNK      0
Ammerup         DNK      0
Årløse          DNK      0
Læskovhus       DNK      0
Bjerget         DNK      0
Fjællebro Huse  DNK      0
Klippede        DNK      0
... 11 more rows
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
FROM 'https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/locality/overture_locality.parquet' f JOIN 'https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/locality/overture_locality_display.parquet' d USING (division_id);
```

```
rows    full_vertices  display_vertices  pct_fewer
556094  182154812      60733543          66.7
```

The two files hold the same rows in the same order in the same row groups, so
this join is a formality: row *i* of one is row *i* of the other, which is what
makes the search index's `geometry_ref` valid against both.

**The most multilingual divisions in this collection** **[derived]**

```sql
SELECT name, country, name_langs
FROM 'https://data.source.coop/portolan-mirrors/cn-gazetteer-overture/locality/overture_locality.parquet'
ORDER BY name_langs DESC, name LIMIT 8;
```

```
name             country  name_langs
Москва           RUS      249
Washington       USA      244
ירושלים | القدس  XW       231
Roma             ITA      223
Singapore        SGP      221
Chicago          USA      219
القاهرة          EGY      217
بغداد            IRQ      211
```

`name_langs` counts the language codes in Overture's `names.common` map for
that division. The spellings themselves are indexed in the [names
collection](../names/collection.json).

## Related collections

- [names](../names/collection.json) — the multilingual search index over every
  level, and the only complete view of the divisions in this catalog. Start
  there to turn a typed name into a `division_id`.
- [country](../country/collection.json) — level 0
- [region](../region/collection.json) — level 1
- [county](../county/collection.json) — level 2
- [localadmin](../localadmin/collection.json) — level 3
- [geoboundaries-catalog](https://source.coop/portolan-mirrors/geoboundaries-catalog)
  — the CC-BY-4.0 counterpart, without share-alike, without localities and
  without alternative names.
