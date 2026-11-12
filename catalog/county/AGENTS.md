# AGENTS.md — Overture Divisions - County Boundaries

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

One land polygon per Overture division of subtype `county`, from release
`2026-10-21.0`. This catalog's search level is **2**. Public root:
`https://data.source.coop/portolan-mirrors/cn-geocoder-overture/catalog.json`

```
county/overture_county.parquet          649.4 MB, 38,937 rows, 406 row groups of 96
county/overture_county_display.parquet  112.5 MB, same rows, same order, same groups
county/county.pmtiles                   88.7 MB, zoom 0-9, layer "county"
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

- **`overture_county.parquet`** is the full-resolution geometry, unchanged from
  Overture. Measure with it, clip with it, and fetch one feature from it when
  precision matters. One row group is about 1.6 MB.
- **`overture_county_display.parquet`** is the same rows simplified and then
  buffered **outward**, about 3.0 KiB a feature. Draw with it and filter with
  it. It is a **superset** of the true outline, so neighbouring features
  overlap along a shared edge and an area computed from it is too large.
  Verified per feature: 37,163 of 38,937 contain their full-resolution polygon
  exactly, none falls below 99%, worst 0.991267.

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
| `level` | not a column here. It is this catalog's 0-to-4 mapping and it is **2** for every row of this collection |

Overture's own schema for these properties is carried as an asset:
[division.schema.yaml](../_assets/overture/division.schema.yaml) and
[division_area.schema.yaml](../_assets/overture/division_area.schema.yaml). The
theme guide is at
[https://docs.overturemaps.org/guides/divisions](https://docs.overturemaps.org/guides/divisions).

## Data quality & usage notes

1. **`id` is not the join key.** Join on `division_id`.
2. **`admin_level` takes four values here**, 0 to 3, although 38,708 of 38,937
   rows are 2. Do not filter on it to find counties; filter on `subtype`.
3. **This is not the same unit set as geoBoundaries ADM2.** The [CC-BY
   counterpart](https://source.coop/portolan-mirrors/geoboundaries-catalog) has
   49,349 ADM2 rows against 38,937 here, and the two use different identifiers,
   so a join between the catalogs needs a spatial match or a name match.

Everything else a consumer would otherwise find the hard way is in the
collection's `known_issues`, rendered in [README.md](README.md).

## Example queries

**What the file holds, by subtype** **[derived]**

```sql
SELECT subtype, count(*) AS n, count(DISTINCT country) AS countries,
       round(min(area_km2), 2) AS min_km2,
       round(max(area_km2)) AS max_km2
FROM 'https://data.source.coop/portolan-mirrors/cn-geocoder-overture/county/overture_county.parquet'
GROUP BY 1 ORDER BY 2 DESC;
```

```
subtype  n      countries  min_km2  max_km2
county   38937  171        0        845448
```

**Resolve one division by its GERS id, the way a geocoder does** **[derived]**

```sql
SELECT name, subtype, country, parent_name, area_km2, vertices,
       bbox.xmin, bbox.ymin, bbox.xmax, bbox.ymax
FROM 'https://data.source.coop/portolan-mirrors/cn-geocoder-overture/county/overture_county.parquet'
WHERE division_id = (SELECT division_id FROM 'https://data.source.coop/portolan-mirrors/cn-geocoder-overture/county/overture_county.parquet'
                     ORDER BY area_km2 DESC LIMIT 1);
```

```
name                                             subtype  country  parent_name        area_km2  vertices  xmin     ymin     xmax     ymax
Таймырский Долгано-Ненецкий муниципальный округ  county   RUS      Красноярский край  845448    32915     76.0983  67.2148  113.921  81.274
```

`division_id` is the join key and the value the names collection publishes as
`feature_id`. **`id` is a different GERS identifier**, belonging to the polygon
rather than to the division, and joining on it finds nothing **[attested:
[division_area
schema](https://docs.overturemaps.org/schema/reference/divisions/division) ]**.

**A bounding-box query, which the covering metadata makes cheap** **[derived]**

```sql
SELECT name, country, round(area_km2) AS area_km2
FROM 'https://data.source.coop/portolan-mirrors/cn-geocoder-overture/county/overture_county.parquet'
WHERE bbox.xmin < 12.5 AND bbox.xmax > 11.5
  AND bbox.ymin < 56.0 AND bbox.ymax > 55.0
ORDER BY area_km2 DESC;
```

```
name                 country  area_km2
Unorganized Borough  USA      844238
Lolland Kommune      DNK      895
Næstved Kommune      DNK      685
Vordingborg Kommune  DNK      624
Holbæk Kommune       DNK      579
Slagelse Kommune     DNK      570
Faxe Kommune         DNK      405
Odsherred Kommune    DNK      357
Sorø Kommune         DNK      309
Ringsted Kommune     DNK      295
Gribskov Kommune     DNK      279
Køge Kommune         DNK      258
... 30 more rows
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
FROM 'https://data.source.coop/portolan-mirrors/cn-geocoder-overture/county/overture_county.parquet' f JOIN 'https://data.source.coop/portolan-mirrors/cn-geocoder-overture/county/overture_county_display.parquet' d USING (division_id);
```

```
rows   full_vertices  display_vertices  pct_fewer
38937  82088290       8011576           90.2
```

The two files hold the same rows in the same order in the same row groups, so
this join is a formality: row *i* of one is row *i* of the other, which is what
makes the search index's `geometry_ref` valid against both.

**The most multilingual divisions in this collection** **[derived]**

```sql
SELECT name, country, name_langs
FROM 'https://data.source.coop/portolan-mirrors/cn-geocoder-overture/county/overture_county.parquet'
ORDER BY name_langs DESC, name LIMIT 8;
```

```
name               country  name_langs
Warszawa           POL      191
San Francisco      USA      181
Frankfurt am Main  DEU      173
Lisboa             PRT      153
Paris              FRA      145
广州市                CHN      139
武汉市                CHN      128
کراچی ڈویژن        PAK      125
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
- [localadmin](../localadmin/collection.json) — level 3
- [locality](../locality/collection.json) — level 4
- [geoboundaries-catalog](https://source.coop/portolan-mirrors/geoboundaries-catalog)
  — the CC-BY-4.0 counterpart, without share-alike, without localities and
  without alternative names.
