# EXPERIMENTAL: Overture divisions as a cloud-native gazetteer

> [!WARNING]
> **This catalog is EXPERIMENTAL.** The schema may change without notice, the
> Source Cooperative repository that serves it is **unlisted**, and the column
> contract it publishes is still being negotiated with its consumer. Pin the
> `catalog_version` in `catalog/names/index.json` if you depend on it, and
> expect to rebuild.

A git-backed [Portolan](https://www.portolan-sdi.org/) catalog that mirrors the
[Overture Maps](https://overturemaps.org/) **divisions** theme as a
**cloud-native gazetteer**: GeoParquet and PMTiles laid out so a browser can
search and draw administrative places over HTTP range requests, with no server
and no API key. Five boundary levels from country down to locality, each with a
display-simplified companion, and a multilingual gazetteer index over all of
them — plus a small *prominent* index, 12.9 MiB against the full 409 MB,
holding the rows a first keystroke is likely to want.

It is a **gazetteer, not a geocoder**: it resolves place names and
administrative boundaries, not street addresses. There is no house number, no
street centerline and no interpolation here. The geocoder is the client that
consumes it, and it lives in the
[cloud-native map widgets](https://github.com/cholmes/cn-geocoding) project.

Published at
[source.coop/portolan-mirrors/cn-gazetteer-overture](https://source.coop/portolan-mirrors/cn-gazetteer-overture).
The catalog metadata lives in this repository; the data lives in object storage
beside it.

[Overture Maps Foundation](https://overturemaps.org/) produces the data and
remains the authoritative source. This repository republishes it; it adds no
division and changes no coordinate.

## Why there are two of these

This is the **ODbL opt-in counterpart** to
[geoboundaries-catalog](https://github.com/portolan-mirrors/geoboundaries-catalog)
([published here](https://source.coop/portolan-mirrors/geoboundaries-catalog)),
which is the default. Both are built to the same column contract, and a
geocoder widget points at one or the other by changing a URL.

| | this catalog | geoboundaries-catalog |
|---|---|---|
| Licence | **ODbL-1.0**, share-alike | CC-BY-4.0, attribution only |
| Status | experimental, unlisted | the default |
| Levels | country, region, county, localadmin, **locality** | ADM0, ADM1, ADM2 |
| City and village boundaries | yes | no |
| Multilingual names | yes, hundreds of languages | no |
| Stable key | Overture GERS id | geoBoundaries `shapeID` |
| Index | large, range-request path | 3.6 MB, loads whole |

**Take the CC-BY one unless you need what this one adds.** ODbL share-alike is
a real obligation: a database derived from this catalog has to be offered under
ODbL too, and anything built on it has to display the attribution. That
decision belongs to whoever ships an application, not to whoever builds the
index, which is why both exist.

## What it publishes

Six collections. Every number here comes from the built files;
`tools/make_collections.py` reads them rather than taking them on trust, and
`catalog/README.md` carries the full table with PMTiles sizes.

| collection | level | rows | GeoParquet | display |
|---|---|---|---|---|
| `country` | 0 | 272 | 51 MB, 34 groups of 8 | 5 MB |
| `region` | 1 | 3,929 | 231 MB, 152 groups of 26 | 24 MB |
| `county` | 2 | 38,937 | 649 MB, 406 groups of 96 | 113 MB |
| `localadmin` | 3 | 21,502 | 143 MB, 90 groups of 240 | 54 MB |
| `locality` | 4 | 556,094 | 1.2 GB, 580 groups of 960 | 871 MB |
| `names` | 0-4 | 5,604,413 | 409 MB, 876 groups of 6,400, sorted by folded name | 12.9 MiB prominent index |

**The row group sizes are one reason this catalog exists.** Every boundary
level gets a row group count measured from its own compressed bytes per row,
landing every group between 1.5 and 1.7 MB, with GeoParquet 1.1 bbox covering
metadata, a Hilbert row order and a Parquet page index on every column, so a
reader finds one division's geometry without decoding any other.

**The other reason is the gazetteer index.** Overture publishes names in
hundreds of languages, and nothing in the release is ordered so a typed prefix
can be found cheaply. The index is one row per division plus one row per
distinct alternative spelling, sorted byte-wise by a folded form of the name,
with row groups sized so a keystroke is one small range request.

**The prominent index** is the third piece. The full index is 409 MB, which
means every keystroke is a round trip. `overture_division_names_prominent.parquet`
is the same schema and the same sort over a strict row subset — every division
from country down to localadmin, every alternative-language spelling of every
country, every locality Overture ranks at `cartography.prominence` 50 or above,
and every alternative-language spelling of a locality at 70 or above (the rows
that make Baghdad, Tehran and Dhaka reachable by their English names) — at
12.9 MiB, small enough to fetch whole on focus and answer keystrokes from
memory. `tools/build_prominent.py` owns the criteria and the measurement
grid behind them, and `catalog/names/index.json` publishes both under
`prominent_index.criteria` so a client knows what the small file can miss and
when to fall back.

**Every file entry in the manifest carries `footer_bytes` and
`footer_metadata_bytes`**, the exact trailing-metadata sizes, so a client reads
a file's footer in one exactly-sized request instead of hyparquet's speculative
512 KiB tail. On the full index, whose footer is 2.1 MB, that speculation is a
guaranteed second round trip.

The products Overture does not publish, and the reasoning behind each, are in
[catalog/changes-from-upstream.md](catalog/changes-from-upstream.md).

## Build it

The data is several gigabytes and never enters git. The pipeline stages it in a
sibling directory, `../cn-geocoder-overture-staging`, which
`catalog.publish.yaml` names as `data_dir`. Override the location with
`OV_STAGING`.

```bash
python3 tools/stage_source.py --dry-run   # what the two remote scans will fetch
python3 tools/stage_source.py             # 4.6 GB from Overture's S3, ~21 min
python3 tools/build_boundaries.py         # -> 5 GeoParquet files
python3 tools/build_display.py            # -> 5 simplified companions
python3 tools/build_names.py              # -> the gazetteer index and its manifest
python3 tools/build_prominent.py          # -> the prominent index, and patches the manifest
python3 tools/build_pmtiles.py            # -> 6 PMTiles archives
python3 tools/measure_index.py            # -> docs/index-measurements.md
python3 tools/make_breaks.py              # -> tools/style_breaks.py, measured
python3 tools/make_styles.py              # -> 24 style JSONs, into catalog/
python3 tools/make_thumbnails.py          # -> 6 thumbnails, into catalog/
python3 tools/make_collections.py         # -> 6 collection.json, into catalog/
python3 tools/make_readmes.py             # -> 7 READMEs and llms.txt
python3 tools/make_agents.py              # -> 7 agent guides, queries run
```

Needs `ogr2ogr` (GDAL 3.10+), `tippecanoe`, `pmtiles`, and Python with
`duckdb`, `pyarrow`, `numpy`, `pycountry`, `geopandas` and `matplotlib`.
`tools/verify_index_hyparquet.mjs` additionally needs Node 18+ with
`hyparquet` and `hyparquet-compressors`, installed outside this repository.

**`stage_source.py` is the only step that touches the network.** It projects
the columns the catalog needs, filters `division_area` to `class = 'land'`, and
writes one local file per collection, so retuning a row group size, a
simplification tolerance or a style costs no egress. It resumes: a part file
already staged is skipped on a rerun.

**The last six steps read the built files.** Row counts, bounding boxes, file
sizes, checksums, class breaks and query output are all measured rather than
typed, so a number in the published metadata cannot go stale without the
generator noticing. `tools/make_agents.py` runs every query it documents and
fails if one errors.

`tools/distributions.sql` reruns every distribution behind every style class
break. Run it after any rebuild: if a count moved, the styles and the prose
citing it are now wrong.

| Path | What it is |
|---|---|
| `catalog/` | The published tree, synced 1:1 to object storage |
| `catalog/*/.portolan/metadata.yaml` | Provenance and known issues per collection. Tracked, never published |
| `catalog/_assets/overture/` | Overture's own schema files and attribution block, carried verbatim as evidence |
| `catalog.publish.yaml` | Where it publishes, and under what public URL |
| `tools/` | The pipeline, and the publisher |
| `tools/style_breaks.py` | Generated class breaks, with the band counts as comments |
| `docs/index-measurements.md` | What the search index costs a client, measured |
| `tests/` | The gates CI runs on every pull request |
| `docs/conformance.md` | Any validator finding this catalog accepts, and why |

**`catalog/` is the published catalog.** Everything in it is published except
dot-directories. Everything outside it never is, and `tools/publish.py` has no
flag that widens that.

## Publish

```bash
python3 tools/publish.py             # dry run: what metadata would change
python3 tools/publish.py --confirm   # upload the catalog; needs AWS credentials
python3 tools/upload_data.py         # dry run: what data would change
python3 tools/upload_data.py --confirm
```

Neither ever deletes. Removing a file from `catalog/` does not unpublish it.

## Test

```bash
CI_LIGHT=1 python3 tests/run_all.py
```

`CI_LIGHT=1` exempts asset and link hrefs with a data suffix from the link
check, because the bytes live in object storage rather than git. CI sets it for
the same reason.

| Gate | What it checks |
|---|---|
| `test_links.py` | Every relative link and asset href resolves |
| `test_styles.py` | Every style class exists in the built data. Skips without the staging tree |
| `test_index_refs.py` | Every sampled `geometry_ref` resolves to the right division in both the full and the display file, and the `catalog_version` agrees in all eleven places. Skips without the staging tree |
| `test_publish.py` | Nothing outside `catalog/` can be uploaded |
| `test_upload_data.py` | Only staged files with an allowed suffix upload |
| `test_stac_valid.py` | Valid STAC 1.1.0, via `stac-check` |
| `test_conformance.py` | Portolan conformance, via `rashid` |

## License

Apache-2.0 for the tooling in this repository. The data is **ODbL-1.0** from
Overture Maps, **share-alike applies**, and the required attribution is
`© OpenStreetMap contributors. Available under the Open Database License.` The
terms, the obligation in plain words, and the verbatim evidence are in
[catalog/README.md](catalog/README.md) and
[catalog/_assets/overture/divisions-attribution.md](catalog/_assets/overture/divisions-attribution.md).
