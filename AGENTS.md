## This Repository

A git-backed Portolan catalog that mirrors the Overture Maps **divisions**
theme for a browser geocoder. It is **experimental**, and the Source
Cooperative repository that serves it is unlisted.

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

### The links back to this repository

`catalog/catalog.json` ships absolute `vcs` and `issues` links. The repository
sits outside the published catalog, so a relative href would resolve against
the public base URL. The Portolan spec recommends both links for a git-backed
catalog. See
[git-backed catalogs](https://github.com/portolan-sdi/portolan-spec/blob/main/specs/best-practices/git-backed-catalogs.md).
