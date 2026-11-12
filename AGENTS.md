## This Repository

A git-backed Portolan catalog that publishes the Overture Maps **divisions**
theme as a **cloud-native gazetteer** — the data a browser geocoder reads. It
is **experimental**, and the Source Cooperative repository that serves it is
unlisted.

### Gazetteer is the word for the data; geocoder is the word for the client

The split is deliberate and the docs hold it. What this repository publishes is
a gazetteer: place names and administrative boundaries, searchable by name.
What consumes it is a geocoder widget, and that lives elsewhere. So the
catalog, the `names` collection and the two index files are described as the
gazetteer, and "geocoder" is reserved for the client and for
`@cnmw/geocoder-core`'s own contract.

Say once, in the catalog README and in `catalog/AGENTS.md`, that this is
place-name and boundary lookup and **not address geocoding** — no house
numbers, no street centerlines, no interpolation. Do not repeat that caveat in
every file, and do not rename anything: the collection is still `names`, the
files are still `overture_division_names*.parquet`, and the columns are
unchanged. The terminology is framing, not a schema change.

Read `README.md` for the pipeline and `catalog/README.md` for what is
published. Read `catalog/changes-from-upstream.md` before you claim anything
about what this catalog does or does not carry.

### It is the ODbL counterpart, not the default

`portolan-mirrors/geoboundaries-catalog` is the default catalog, CC-BY-4.0 and
attribution-only. This one exists because Overture reaches further down the
hierarchy and carries names in hundreds of languages, and the price is ODbL
share-alike. Both publish the same column contract so a consumer can switch
with a URL.

**Never soften the share-alike statement.** A reader deciding between the two
catalogs is making a licensing decision, and the whole reason this repository
exists is that the decision is theirs rather than ours. The obligation belongs
in the repository README, the catalog README, every collection description,
every collection README and the `share_alike` flag in
`catalog/names/index.json`.

### There are two name indexes, and the small one is a strict subset

`tools/build_names.py` writes the full 409 MB index; `tools/build_prominent.py`
writes `overture_division_names_prominent.parquet`, 8.6 MiB, from it. The
prominent index is a **row subset in the same schema and the same sort** — it
copies rows, it never recomputes them — so a hit found in either resolves its
geometry identically and `build_prominent.verify()` fails the build if the
schema, the sort or the subset property breaks.

Its three criteria live in `PRIMARY_LEVELS`, `ALT_LEVELS` and
`PROMINENCE_CUT`, they are published verbatim in the manifest under
`prominent_index.criteria`, and `--measure` reprints the grid they were chosen
from. **A client that does not know what was left out cannot know when a miss
means "no such place" and when it means "ask the full index"**, so any change
to those three constants has to update `criteria.fallback` with it.

The 8 MiB budget and "carry levels 0-2 entirely" are mutually exclusive at this
schema — the measurement is in the `build_prominent.py` docstring — because the
alternative-name rows *are* the rows, and `feature_id` plus `alt_of` is 64
bytes of GERS identifier on each one. Do not quietly widen `ALT_LEVELS` without
re-running `--measure`.

### Order matters: build_prominent runs after build_names

The prominent index is built *from* the full index, so on a fresh pipeline the
manifest is written before the prominent file exists. `build_names.py` fills
`prominent_index` from the file when it is there and prints a note when it is
not; `build_prominent.py` patches the key back in afterwards, from the same
function, so either order converges on the same manifest. Run both.

### Every number is measured, never typed

`tools/make_collections.py`, `tools/make_readmes.py`, `tools/make_agents.py`,
`tools/make_breaks.py` and `tools/measure_index.py` read the built files and
interpolate what they find. A row count, a file size, a class break, a
containment ratio or a query result that appears in `catalog/` got there from
a query. If you need to change a number, change what produced it.

`catalog/**/README.md` and `catalog/**/AGENTS.md` are **generated output**. A
hand edit is lost on the next run. Edit the prose blocks in the generator, or
the provenance in `catalog/*/.portolan/metadata.yaml`, and regenerate.

### The row order of a boundary file is a contract

`catalog/names/` publishes a `geometry_ref` naming a row group and a row in a
boundary file, and each display file holds the same rows at the same offsets.
So the Hilbert `ORDER BY` in `tools/build_boundaries.py` carries a
`division_id` tiebreaker and the write forces `preserve_insertion_order`.
Both are load-bearing: without the tiebreaker a rebuild reordered 4,724
locality rows and every display file silently went stale.

Rebuilding a boundary file means rebuilding its display file. `build_display.py`
asserts the alignment and refuses to publish a file that fails it.

### The display files are supersets on purpose

Simplified, then buffered **outward** by the same per-feature tolerance, so
the shape always contains the true boundary. Never describe one as an
approximation of the boundary, and never compute an area from one. The
guarantee is verified per feature on every build and the worst cases are
published.

### The publish boundary

`catalog/` is the published catalog. Everything in it is published, and
nothing outside it ever is. Do not move a file into `catalog/` to make it
publish, and do not add a path outside `publish_dir` to `tools/publish.py`.
The boundary is the only thing standing between a scratch file and a public
bucket, and it holds because it is structural rather than a list of
exclusions.

### Data never enters git

Never commit a GeoParquet, COG, PMTiles, Zarr, or COPC file. The staging tree
is `../cn-geocoder-overture-staging`, outside this repository. Git keeps every
version of a binary forever and deleting it later reclaims nothing.

### Do not re-download the release to answer a question

`tools/stage_source.py` is the only step that touches the network, and it
pulls 4.6 GB. Everything else reads the local staging tree. If you need a fact
about the Overture release, query the staged files; if you need one the
staging projection dropped, add it to the projection and say so in
`catalog/changes-from-upstream.md`.

### The conformance allow-list

`ACCEPTED` in `tests/test_conformance.py` ships empty. Never add an entry
without a matching row in `docs/conformance.md` giving the rule, where it
fires, why it is accepted, and the issue tracking its removal.

### Published agent guides

Every claim in a `catalog/**/AGENTS.md` is either quoted from a source or
measured from the data, and every query in one was run against the built file
by `tools/make_agents.py`. An invented join key or column name produces a
confident wrong answer that nothing downstream catches.

The three tiers are not decoration. **Attested** means Overture's own schema
or attribution page states it, and the evidence is carried in
`catalog/_assets/overture/`. **Derived** means a query in `tools/` computed
it. Anything else does not ship.

### Link the upstream release from every collection

Every collection carries `upstream-division-s3`, `upstream-division-area-s3`
and `upstream-divisions-azure` assets pointing at the authoritative release, so
nobody has to take this mirror's word for its own contents and anyone who wants
the real thing for bulk work can skip the catalog entirely. They are remote
prefixes holding several part files whose bytes this repository never has, so
they carry **no `file:size` and no `file:checksum`** — a checksum of a
directory listing would be a fabrication.

State the reachability accurately, because it is counter-intuitive and it was
measured: the **S3 HTTPS endpoint sends CORS** and answers range requests, so a
browser *can* read the upstream release directly. The **Azure mirror sends no
CORS headers**. So this catalog's justification is **layout, not
reachability** — an undeclared sort and 2.22 MB row groups of a 50-column
nested schema — and the README says so in those terms. Never argue for this
catalog on grounds that measurement contradicts.

### The links back to this repository

`catalog/catalog.json` ships absolute `vcs` and `issues` links. The repository
sits outside the published catalog, so a relative href would resolve against
the public base URL. The Portolan spec recommends both links for a git-backed
catalog. See
[git-backed catalogs](https://github.com/portolan-sdi/portolan-spec/blob/main/specs/best-practices/git-backed-catalogs.md).
