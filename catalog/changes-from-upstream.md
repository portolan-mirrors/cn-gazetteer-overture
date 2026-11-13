# Changes from the Overture release

This catalog is **not** a byte-for-byte mirror of Overture Maps divisions
release `2026-10-21.0`. It drops rows, drops columns, derives columns, and adds
two products Overture does not publish. Every deviation is listed here with how
to reproduce it and how to get vanilla Overture instead.

Nothing here changes a coordinate or an attribute value. Where a column is
derived, the Overture column it came from is carried through unchanged beside
it.

**To get vanilla Overture**, read the release directly. It is public and needs
no credentials:

```sql
INSTALL httpfs; LOAD httpfs;
SET s3_region = 'us-west-2';
SET s3_access_key_id = ''; SET s3_secret_access_key = '';

SELECT count(*)
FROM read_parquet(
  's3://overturemaps-us-west-2/release/2026-10-21.0/'
  'theme=divisions/type=division_area/*.parquet'
);
```

## Rows dropped

### 1. Three subtypes are excluded

Overture's divisions theme has twelve subtypes. This catalog carries six:
`country`, `dependency`, `region`, `county`, `localadmin` and `locality`.

Excluded, with the row count in `type=division`:

| subtype | rows | why |
|---|---|---|
| `neighborhood` | 732,094 | Below the level a boundary geocoder resolves. A neighborhood name is rarely what a user types to pick an area, and the three together would roughly double the search index. |
| `microhood` | 239,113 | Same, and Overture defines it as a mini-neighborhood inside a neighborhood, so it is the finest grain in the theme. |
| `macrohood` | 156,996 | Same. Overture describes it as a super-neighborhood, which has no counterpart in the level contract this catalog publishes. |

Overture's own coverage note is the other half of the reason: the guide says
country, dependency, region and county align with OpenStreetMap `admin_level`
and geoBoundaries globally, while `locality`, `borough`, `neighborhood` and
`microhood` exist everywhere but with coverage that is "spotty". A level whose
coverage cannot be described is a level a geocoder cannot rank against.

`macroregion`, `macrocounty` and `borough` are in Overture's schema but have no
rows in this release, so there was nothing to exclude.

This is the first thing to revisit. Adding the three hood levels is a change to
`SUBTYPE_LEVEL` in `tools/ovcommon.py` and a rebuild; the reason it has not
happened is index size, not difficulty.

### 2. Maritime polygons are dropped

`type=division_area` publishes up to two polygons per division: one with
`class = 'land'`, which Overture describes as "the land-clipped, non-maritime
boundary" intended for "map rendering, cartographic display, and similar
purposes", and, for a coastal division, one with `class = 'maritime'`, which is
"Overture's best approximation of this place's maritime boundary" intended for
"data processing, reverse-geocoding, and similar purposes".

This catalog keeps only `class = 'land'`. Measured across the six subtypes it
carries: 684,589 area rows in total, of which 620,734 are land and 63,855 are
maritime.

Two reasons. The land polygon is what a user recognizes as the shape of a
place, and the search index can only point one geometry at one GERS id.
Measured, the land filter makes that exactly true: 620,734 land rows over
620,734 distinct `division_id` values, which `tools/stage_source.py` asserts on
every run and refuses to publish without.

If you need the maritime extent, read it from the release:

```sql
SELECT division_id, geometry
FROM read_parquet(
  's3://overturemaps-us-west-2/release/2026-10-21.0/'
  'theme=divisions/type=division_area/*.parquet'
)
WHERE class = 'maritime' AND division_id = '<a GERS id from this catalog>';
```

### 3. Divisions with no primary name are not indexed

The search index drops any division whose `names.primary` is null, because
there is nothing to search for. Measured on this release: **0 rows**, across all
3,572,796 divisions in scope. The check stays in because a future release could
change that, and the count is published in `names/index.json` as
`dropped_unnamed`.

## Rows added

None. This catalog publishes no division that Overture does not publish.

## Columns dropped

From `type=division`, the staging step does not read: `hierarchies`,
`capital_division_ids`, `capital_of_divisions`, `norms`, `perspectives`,
`theme`, `type`, and most of `sources`.

- `hierarchies` is the largest column in the file, 151 MB of the 554 MB, and
  carries each division's full ancestor chain with names. `parent_name` and
  `parent_subtype` in this catalog are the one thing it was needed for, and a
  self-join on the 9 MB `parent_division_id` column produces the same answer.
  If you need the whole chain, or the alternative hierarchies a disputed
  division participates in, read `hierarchies` from the release.
- `perspectives` is **null on all 4,700,999 rows** of this release, so it was
  dropped as empty rather than as unwanted. See "Disputed divisions" below.
- `capital_division_ids`, `capital_of_divisions` and `norms.driving_side` are
  real data with no bearing on a boundary geocoder.

From `type=division_area`: `names`, `admin_level` and `region` are read but not
published, because `type=division` carries the same properties and the search
index is built from the division row. Overture repeats them on the area row
"for ease of use"; taking both from one place is what keeps the two halves of
this catalog consistent.

`is_land` and `is_territorial` are read, used as the filter, and then dropped,
because after the filter every surviving row has `is_land = true` and a column
with one value in every row is noise in `table:columns`.

## Columns derived

| column | from | how |
|---|---|---|
| `country` | Overture `country` (alpha-2) | Mapped to ISO 3166-1 alpha-3 through the official ISO 3166-1 table packaged with pycountry, so this catalog and the CC-BY geoBoundaries mirror can be filtered with one code system. Overture's alpha-2 is kept unchanged as `country_iso2`. A synthetic Overture code with no alpha-3 equivalent is carried through unchanged. |
| `local_type` | Overture `local_type` (a map) | Flattened to the `local` entry, or the first entry where there is none. |
| `parent_name`, `parent_subtype` | `parent_division_id` | Self-join over the whole `type=division` release, so a parent in an excluded subtype still resolves. |
| `prominence` | `cartography.prominence` | Unwrapped from the struct. Overture populates it on all 3,508,156 localities and on nothing else. |
| `class` | Overture `class` | Carried through unchanged onto every names-index row, including alternative-name rows. It is null above locality — Overture populates it on 3,394,627 of 3,508,156 localities and on none of the 64,640 divisions above them. Added 2026-11-12 so a client can rank a city above a country that happens to share a prefix; see "A `class` column in the gazetteer index" below. |
| `name_langs` | `names.common` | `cardinality` of the map. |
| `country_units` | this file | Window count of rows sharing `country`. |
| `area_km2`, `perimeter_km` | `geometry` | `ST_Area_Spheroid` and `ST_Perimeter_Spheroid` on the WGS 84 ellipsoid, coordinates flipped to latitude-first as those functions require. |
| `compactness` | the two above | Polsby-Popper, 4&pi;A/P². |
| `vertices` | `geometry` | `ST_NPoints`. |
| `bbox` | `geometry` | The GeoParquet 1.1 covering struct, recomputed rather than copied from Overture's own `bbox` column, so it is guaranteed to match the geometry in this file. |

## Products added

### Display-simplified parquet, one per boundary collection

Not in Overture. Each holds the same rows in the same order in the same row
groups as the full-resolution file beside it, with the geometry put through
`ST_SimplifyPreserveTopology` and then **buffered outward** by the same
tolerance. The result always contains the true boundary, so a spatial filter
drawn against it over-selects rather than under-selects. Neighbouring divisions
therefore overlap along their shared edge. **Draw and filter with these;
measure and clip with the full-resolution files.**

### A `class` column in the gazetteer index

Overture carries `class` on its division rows; nothing in Overture carries it
in a form a name search can rank on. The index now does, on every row
including the alternative-name rows, because **without it a short prefix
returns the wrong answers**. Ranking verification against this catalog found
that a prefix like `bag` is dominated by alternative-language rows of countries
and regions — Tajik and Uzbek transliterations of "Bahamas" and the like — which
bury Baghdad, since a country outranks a city on every signal the index
previously offered. `area_km2` makes it worse rather than better: a country
always dwarfs a city.

`class` is the only column that separates them. Measured on this release its
distribution is hamlet 1,715,416, village 1,561,816, town 103,175 and city
14,220, so `class IN ('city', 'town')` is 117,395 places out of 3.5 million.

**It is a ranking signal, not a filter.** 113,529 localities have no class and
some of those are real cities, so a client that filters on `class` loses them.
Treat null as unknown. The same holds for `population`, which was already
carried: it is populated on 17.7% of localities and 79.9% of countries, so a
client that coalesces null to zero sorts five localities in six last.

To get vanilla behaviour, ignore the column; nothing else in the index depends
on it.

### The prominent gazetteer index

Not in Overture, and not a transformation of the data — a **row subset of this
catalog's own index**, in the same schema and the same sort.
`overture_division_names_prominent.parquet` is 12.9 MiB against the full
index's 409 MB, holding 168,018 of its 5,604,413 rows: every primary row at
levels 0-3 (country, dependency, region, county, localadmin), every
alternative-name row at level 0, and every level-4 locality row at
`cartography.prominence` 50 or above for a primary row, 70 or above for an
alternative-name row. The level-4 alternative-name rows are what make a city
whose primary name is not in Latin script — Baghdad ("بغداد"), Tehran, Dhaka —
reachable by its English name; the first published build dropped them, which
its own criteria text did not admit, and was fixed on 2026-11-13.

It exists because a 409 MB index means every keystroke is an HTTP round trip.
This one is small enough to fetch whole on focus and answer keystrokes from
memory, while the full index stays available by range request for anything
deeper. Every row in it is byte-for-byte a row of the full index — same
`feature_id`, same `geometry_ref`, same `name_norm` — so a hit found in either
resolves its geometry identically, and neither is authoritative over the other.

**What it can miss, and therefore when to fall back:** any locality below the
prominence cuts, and any alternative-language name of a region, county,
localadmin or locality. `catalog/names/index.json` publishes the criteria and
the fallback rule verbatim under `prominent_index.criteria`.

The criteria are a budget decision and the measurement is in
`tools/build_prominent.py`: carrying levels 0-2 entirely with their
alternative names is 29.9 MB however hard level 4 is cut, because the
alternative-name rows are the rows — 257,872 of them at levels 0-2 against
43,138 divisions — and `feature_id` plus `alt_of` is 64 bytes of GERS
identifier on each. `class` was considered as the level-4 cut instead of
`prominence` and rejected (null on 113,393 localities, and not a column the
index carried at the time); `area_km2` was rejected too, since 2,952,062
localities have no polygon and so no area.

To get vanilla behaviour, ignore this file and read the full index.

### Multilingual name search index

Not in Overture. One row per division plus one row per distinct alternative
spelling from `names.common`, sorted by a folded form of the name so a client
can resolve a typed prefix with HTTP range requests. Two reductions are applied
to the alternative spellings, both of them lossless for search: an alternative
that folds to the same string as the division's primary name is dropped, and
alternatives that fold to the same string as each other are collapsed into one
row carrying a count. See [names/README.md](names/README.md).

### PMTiles, one per collection

Not in Overture. Built with tippecanoe from the display files.

## Disputed divisions

Overture models a disputed boundary through the `perspectives` property, whose
schema says that an absent value means "this division is not known to be
disputed from any political perspective". **In this release `perspectives` is
null on every one of the 4,700,999 division rows**, and `type=division_area`
has no such column at all, so there is exactly one representation of every
division here and no perspective to choose between.

That is a property of the release, not a claim that no boundary in it is
contested. Overture's own schema describes `accepted_by` and `disputed_by`
modes and a procedure for drawing a map from one country's perspective, so a
future release may populate it; this catalog would then have to decide which
perspective it publishes, and that decision is not made yet. It is tracked in
`known_issues` on every collection.

What the release does carry is `names.rules`, an array of
perspective-dependent name variants, averaging 73.7 entries on a country and
15.1 on a region. **The search index does not read it.** Those variants are
where a contested name lives, and indexing them without also modelling the
perspective they belong to would return a name as a plain alternative when it
is a political claim. The count is recorded here so the omission is a decision
rather than an oversight.

## Reproducing all of it

```bash
python3 tools/stage_source.py        # the two remote scans
python3 tools/build_boundaries.py    # the five full-resolution files
python3 tools/build_display.py       # the five display files
python3 tools/build_names.py         # the index and its manifest
python3 tools/build_pmtiles.py       # six PMTiles archives
python3 tools/measure_index.py       # the numbers the prose cites
```

Every number in this file is printed by one of those tools.
