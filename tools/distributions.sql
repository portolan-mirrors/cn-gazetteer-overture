-- Every distribution behind every style class break, and every count quoted
-- in the published prose.
--
--   duckdb -c ".read tools/distributions.sql"
--
-- Run it after any rebuild. If a count moved, the styles, the collection
-- descriptions and the READMEs that cite it are now wrong, and
-- tools/make_breaks.py has to run again before tools/make_styles.py.
--
-- Paths assume the default staging root, ../cn-geocoder-overture-staging.
-- Override them with your own OV_STAGING by editing the macro below.

INSTALL spatial; LOAD spatial;

CREATE OR REPLACE MACRO staged(name) AS
  '../cn-geocoder-overture-staging/publish/' || name;

CREATE OR REPLACE VIEW country AS
  SELECT * FROM read_parquet(staged('country/overture_country.parquet'));
CREATE OR REPLACE VIEW region AS
  SELECT * FROM read_parquet(staged('region/overture_region.parquet'));
CREATE OR REPLACE VIEW county AS
  SELECT * FROM read_parquet(staged('county/overture_county.parquet'));
CREATE OR REPLACE VIEW localadmin AS
  SELECT * FROM read_parquet(staged('localadmin/overture_localadmin.parquet'));
CREATE OR REPLACE VIEW locality AS
  SELECT * FROM read_parquet(staged('locality/overture_locality.parquet'));
CREATE OR REPLACE VIEW names AS
  SELECT * FROM read_parquet(staged('names/overture_division_names.parquet'));

.print
.print === Row counts and coverage ===
SELECT 'country' AS collection, count(*) AS rows,
       count(DISTINCT country) AS countries FROM country
UNION ALL SELECT 'region', count(*), count(DISTINCT country) FROM region
UNION ALL SELECT 'county', count(*), count(DISTINCT country) FROM county
UNION ALL SELECT 'localadmin', count(*), count(DISTINCT country) FROM localadmin
UNION ALL SELECT 'locality', count(*), count(DISTINCT country) FROM locality
UNION ALL SELECT 'names', count(*), count(DISTINCT country) FROM names
ORDER BY 1;

.print
.print === country: subtype, the status style ===
SELECT subtype, count(*) FROM country GROUP BY 1 ORDER BY 2 DESC;

.print
.print === locality: class, the default style ===
SELECT coalesce(class, '(null)') AS class, count(*) FROM locality
GROUP BY 1 ORDER BY 2 DESC;

.print
.print === localadmin: country, the coverage style ===
SELECT country, count(*) FROM localadmin GROUP BY 1 ORDER BY 2 DESC, 1;

.print
.print === area_km2 quantiles, the default step on every boundary level ===
SELECT 'country' AS collection,
       quantile_cont(area_km2, [0.1667, 0.3333, 0.5, 0.6667, 0.8333]) AS q
FROM country
UNION ALL SELECT 'region',
       quantile_cont(area_km2, [0.1667, 0.3333, 0.5, 0.6667, 0.8333]) FROM region
UNION ALL SELECT 'county',
       quantile_cont(area_km2, [0.1667, 0.3333, 0.5, 0.6667, 0.8333]) FROM county
UNION ALL SELECT 'localadmin',
       quantile_cont(area_km2, [0.1667, 0.3333, 0.5, 0.6667, 0.8333])
       FROM localadmin
UNION ALL SELECT 'locality',
       quantile_cont(area_km2, [0.1667, 0.3333, 0.5, 0.6667, 0.8333])
       FROM locality
ORDER BY 1;

.print
.print === name_langs: what this ODbL catalog buys over the CC-BY one ===
SELECT 'country' AS collection, round(avg(name_langs), 2) AS avg_langs,
       max(name_langs) AS max_langs,
       count(*) FILTER (WHERE name_langs = 0) AS no_alternatives FROM country
UNION ALL SELECT 'region', round(avg(name_langs), 2), max(name_langs),
       count(*) FILTER (WHERE name_langs = 0) FROM region
UNION ALL SELECT 'county', round(avg(name_langs), 2), max(name_langs),
       count(*) FILTER (WHERE name_langs = 0) FROM county
UNION ALL SELECT 'localadmin', round(avg(name_langs), 2), max(name_langs),
       count(*) FILTER (WHERE name_langs = 0) FROM localadmin
UNION ALL SELECT 'locality', round(avg(name_langs), 2), max(name_langs),
       count(*) FILTER (WHERE name_langs = 0) FROM locality
ORDER BY 1;

.print
.print === population: how sparse it is, per level ===
SELECT 'country' AS collection, count(population) AS with_population,
       count(*) AS rows FROM country
UNION ALL SELECT 'region', count(population), count(*) FROM region
UNION ALL SELECT 'county', count(population), count(*) FROM county
UNION ALL SELECT 'localadmin', count(population), count(*) FROM localadmin
UNION ALL SELECT 'locality', count(population), count(*) FROM locality
ORDER BY 1;

.print
.print === country_units: how finely each country is divided ===
SELECT 'region' AS collection, min(country_units), max(country_units),
       round(avg(country_units), 1) FROM region
UNION ALL SELECT 'county', min(country_units), max(country_units),
       round(avg(country_units), 1) FROM county
UNION ALL SELECT 'localadmin', min(country_units), max(country_units),
       round(avg(country_units), 1) FROM localadmin
UNION ALL SELECT 'locality', min(country_units), max(country_units),
       round(avg(country_units), 1) FROM locality
ORDER BY 1;

.print
.print === names: level, the default style ===
SELECT level, count(*) AS rows,
       count(*) FILTER (WHERE alt_of IS NULL) AS primary_rows,
       count(*) FILTER (WHERE alt_of IS NOT NULL) AS alt_rows,
       count(*) FILTER (WHERE has_boundary) AS with_boundary
FROM names GROUP BY 1 ORDER BY 1;

.print
.print === names: name_dupes, the ambiguity style ===
SELECT CASE WHEN name_dupes = 1 THEN '1 unique'
            WHEN name_dupes < 4 THEN '2-3'
            WHEN name_dupes < 10 THEN '4-9'
            WHEN name_dupes < 100 THEN '10-99'
            ELSE '100+' END AS band, count(*)
FROM names GROUP BY 1 ORDER BY 1;

.print
.print === names: the most repeated folded names ===
SELECT name_norm, count(*) AS rows, count(DISTINCT feature_id) AS divisions
FROM names GROUP BY 1 ORDER BY 2 DESC LIMIT 10;

.print
.print === names: name_lang_count, the languages style ===
SELECT name_lang_count, count(*) FROM names
GROUP BY 1 ORDER BY 1 LIMIT 20;

.print
.print === names: the languages with the most indexed spellings ===
SELECT name_lang, count(*) FROM names WHERE name_lang IS NOT NULL
GROUP BY 1 ORDER BY 2 DESC LIMIT 15;

.print
.print === display files: vertices saved ===
SELECT 'country' AS collection,
       (SELECT sum(vertices) FROM country) AS full_vertices,
       (SELECT sum(vertices) FROM read_parquet(
          staged('country/overture_country_display.parquet'))) AS display_vertices
UNION ALL SELECT 'region', (SELECT sum(vertices) FROM region),
       (SELECT sum(vertices) FROM read_parquet(
          staged('region/overture_region_display.parquet')))
UNION ALL SELECT 'county', (SELECT sum(vertices) FROM county),
       (SELECT sum(vertices) FROM read_parquet(
          staged('county/overture_county_display.parquet')))
UNION ALL SELECT 'localadmin', (SELECT sum(vertices) FROM localadmin),
       (SELECT sum(vertices) FROM read_parquet(
          staged('localadmin/overture_localadmin_display.parquet')))
UNION ALL SELECT 'locality', (SELECT sum(vertices) FROM locality),
       (SELECT sum(vertices) FROM read_parquet(
          staged('locality/overture_locality_display.parquet')))
ORDER BY 1;
