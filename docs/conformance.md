# Portolan Conformance

Conformance means passing [rashid](https://github.com/portolan-sdi/rashid),
not claiming to conform, so it runs in CI:

```bash
python3 tests/test_conformance.py
```

That gate fails on any error-severity finding whose rule is not listed below.
The list starts empty and it must never grow without a row here. A known
deviation with an issue number is a debt someone can pay off. A silently
widened allow-list is a false claim about what this catalog conforms to.

## The rashid version floor

The gate needs rashid `>=0.1.5,<0.2.0`. It reads `rashid --version` and fails
outside that range. It also fails when rashid is absent, and prints the install
command. A skip would report a green run for a catalog that no validator read.

The floor is 0.1.5 because rules PTL-LNK-007, PTL-LNK-008, PTL-LNK-009 and
PTL-AST-006 do not exist below it. The gate asserts all four. An older rashid
reports a pass for a catalog that it never checked against them. The same range
is in `portolan-cli/pyproject.toml` and in the CI install step.

The upper bound stops an unreviewed 0.2 rule set from changing what this gate
means. Raise both bounds together when you move to 0.2, and read the new rules
first.

This file also records workarounds for the other validator CI runs. Those are
not conformance debts, because the catalog is correct and the validator is not.
They live here so nobody has to read CI code to find out why a gate skips
something.

## Accepted deviations

None. `rashid 0.1.8` reports 0 errors and 0 warnings across the seven STAC
objects.

## Informational findings, and the decisions behind them

These are `info` severity, so they do not fail the gate. They are recorded
because rashid asks for a decision and silence is not one.

| Rule | Where | Decision |
|---|---|---|
| PTL-PRO-002 | all six collections | No `rel:"canonical"` link. The rule asks for one **when the upstream publishes its own STAC catalog**. Overture does not: the divisions theme is published as Parquet on S3 and Azure Blob with documentation at docs.overturemaps.org, and there is no STAC object to point at. The `via` link names the theme guide and the `cite-as` link names Overture instead. Revisit if Overture publishes STAC. |

`portolan check` additionally reports that 17 registered assets are missing
from disk. That is the publish boundary working as intended: the GeoParquet
and PMTiles files live in object storage and never enter git, and the STAC
references them by the public URL that `catalog.publish.yaml` builds. Run the
check against the published tree to see them resolve.

<!--
When you accept one, add a row and a section explaining it, like this:

| Rule | Where | Why accepted | Tracking |
|---|---|---|---|
| PTL-VIZ-001 | all thumbnails | WebP is not yet permitted; the size saving is 4x | portolan-spec#121 |

Then add the rule id to ACCEPTED in tests/test_conformance.py. Both, or
neither.
-->

## Validator workarounds

### gpq crashes on a GeoParquet file with a null geometry value

`gpq validate` panics with a nil-pointer dereference on
`catalog/names/overture_division_names.parquet`:

```
panic: runtime error: invalid memory address or nil pointer dereference
github.com/paulmach/orb/geojson.(*Geometry).Geometry(0x0?)
github.com/planetlabs/gpq/internal/validator.(*Validator).Report(...)
  internal/validator/validator.go:242
```

The file is not at fault. The search index carries a point on each primary row
and **null on each alternative-name row**, because an alternative spelling
describes the division its primary row already carries a point for, and
repeating the point on 2,031,617 rows cost about 40 MB and said nothing new.
GeoParquet permits a nullable geometry column; nothing in the specification
requires a value on every row.

Minimal reproduction, three rows and no catalog involved:

```python
import pyarrow as pa, pyarrow.parquet as pq, json, struct

point = struct.pack("<BIdd", 1, 1, 10.0, 20.0)
geo = json.dumps({
    "version": "1.1.0", "primary_column": "geometry",
    "columns": {"geometry": {"encoding": "WKB", "geometry_types": ["Point"]}},
}).encode()

for name, values in [("with-null", [point, None, point]),
                     ("no-null", [point, point, point])]:
    table = pa.table({"geometry": pa.array(values, pa.binary())})
    pq.write_table(table.replace_schema_metadata({b"geo": geo}),
                   f"{name}.parquet")
```

`gpq validate no-null.parquet` passes. `gpq validate with-null.parquet`
panics. The crash is in the data-scanning path, so:

```bash
gpq validate --metadata-only catalog/names/overture_division_names.parquet
```

passes all 16 metadata and schema checks, and that is what this repository
runs for the search index. The ten other GeoParquet files in the catalog carry
a geometry on every row and pass the full `gpq validate`, 20 checks each.

The file is otherwise readable: GeoPandas reads all 5,604,413 rows and reports
2,031,617 null geometries, and the hyparquet client in
`tools/verify_index_hyparquet.mjs` reads it as a browser would.

**This is an upstream bug and belongs upstream**, at
<https://github.com/planetlabs/gpq>. It is not reported there yet; the
reproduction above is what to file. Nothing in this catalog works around it,
because working around it would mean publishing 40 MB of duplicate points to
satisfy a validator rather than a specification.

### stac-check reports a dialect crash on every collection

`tests/test_stac_valid.py` exempts one stac-check failure:

```
'list' object has no attribute 'get'
[Schema: https://schemas.portolan-sdi.org/portolan/vX.Y.Z/schema.json]. Error in Extensions.
```

The Portolan schema is valid draft-07, and rashid validates catalogs against it
cleanly. `stac-validator`, which stac-check uses, hardcodes the JSON Schema
2020-12 dialect and ignores the `$schema` a schema declares. The profile schema
uses the draft-07 tuple form of `items` in `valid_bbox`, which means something
different under 2020-12, so the library raises instead of validating.

Tracked upstream at <https://github.com/stac-utils/stac-check/issues/159>,
and on the Portolan side at
<https://github.com/portolan-sdi/portolan-spec/issues/157>.

The exemption matches that exact message, and only when the failing schema is a
Portolan profile schema. Every other stac-check error still fails the build,
and the gate prints how many objects took the exemption.

The exemption expires on its own. The gate fails once stac-check stops emitting
the crash on a collection or item that declares the profile schema, and tells
you to delete both the exemption and this section. CI installs stac-check
unpinned, so the next release triggers that without anyone watching for it.

`tests/test_stac_valid.py` also fails when stac-check is absent, and prints the
install command. It takes no version floor and no pin. The rashid floor exists
because that gate asserts four named rules. This gate asserts no stac-check
rule. It needs the opposite property. A pin holds the exemption open after the
upstream fix ships.
