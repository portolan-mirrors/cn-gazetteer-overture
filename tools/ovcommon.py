#!/usr/bin/env python3
"""Shared constants and helpers for the Overture divisions build.

Nothing here touches the published catalog. The build stages the Overture
release under ``sources/`` in the staging root, works in ``work/``, and writes
data files to ``publish/`` under the same root, which ``catalog.publish.yaml``
names as ``data_dir``. ``tools/publish.py`` never reads that tree, so the
publish boundary is unchanged.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import unicodedata
from pathlib import Path

# The staging root. Override with OV_STAGING. It sits outside the repository
# because the staged release is several gigabytes and git keeps every version
# of a binary forever.
_DEFAULT_STAGING = Path(__file__).resolve().parents[2] / "cn-geocoder-overture-staging"
STAGING = Path(os.environ.get("OV_STAGING", _DEFAULT_STAGING))
SOURCES = STAGING / "sources"
WORK = STAGING / "work"
PUBLISH = STAGING / "publish"

# The Overture release this catalog mirrors. A release is immutable, so the
# version alone pins the bytes; there is no commit or checksum to carry.
#
#   https://docs.overturemaps.org/blog/   (the release notes)
#
RELEASE = "2026-10-21.0"
S3_BUCKET = "overturemaps-us-west-2"
S3_REGION = "us-west-2"
S3_THEME = f"s3://{S3_BUCKET}/release/{RELEASE}/theme=divisions"
EXTRACTION_DATE = "2026-11-12"

# ---------------------------------------------------------------------------
# The upstream release, addressed directly
# ---------------------------------------------------------------------------
# Every collection links the authoritative files it was built from, so nobody
# has to take this mirror's word for its own contents and anybody who wants
# the real thing for bulk or analytical work can skip this catalog entirely.
# See the README's "The upstream data vs our optimized files".
#
# Three forms of the same bytes, because they are not interchangeable in
# practice:
#
# * `s3://` -- what DuckDB, GDAL and the AWS CLI take. Public and anonymous,
#   requester does not pay.
# * HTTPS on the S3 endpoint -- what a browser or a plain `curl` takes.
#   Measured 2026-11-12: it answers `Accept-Ranges: bytes` and sends
#   `Access-Control-Allow-Origin: *` with `Content-Range` and `Accept-Ranges`
#   exposed, so a browser *can* range-read the upstream release directly. That
#   is worth stating precisely, because the reason this catalog exists is
#   layout rather than reachability (again, see the README).
# * HTTPS on the Azure mirror -- the same release, published by Overture to
#   Azure Blob. Measured on the same date: it serves the files but sends **no
#   CORS headers at all**, so it is not browser-reachable cross-origin.
S3_HTTPS_THEME = (
    f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com/release/{RELEASE}"
    "/theme=divisions"
)
AZURE_ACCOUNT = "overturemapswestus2"
AZURE_HTTPS_THEME = (
    f"https://{AZURE_ACCOUNT}.blob.core.windows.net/release/{RELEASE}"
    "/theme=divisions"
)

# Measured against the release on 2026-11-12, by listing the Azure container
# and by reading part-00000 of each type with tools/measure_reads.mjs:
#
#   type=division        1 file    0.58 GB   4,700,999 rows in part-00000
#   type=division_area   8 files   4.58 GB
#
# part-00000 of type=division holds its 4,700,999 rows in 256 row groups of
# about 18,400 rows, median 2.22 MB and up to 3.85 MB compressed per group,
# across 50 leaf column chunks, and declares no sorting columns. Its footer
# alone is 1.47 MB and hyparquet needs two requests to read it, because its
# speculative 512 KiB tail falls short.
UPSTREAM_FILES = {"division": 1, "division_area": 8}
UPSTREAM_BYTES = {"division": 584_189_981, "division_area": 4_583_000_000}

# The release's own documentation and attribution pages, cited throughout the
# catalog metadata.
DOCS_DIVISIONS = "https://docs.overturemaps.org/guides/divisions"
DOCS_SCHEMA_DIVISION = "https://docs.overturemaps.org/schema/reference/divisions/division"
DOCS_SCHEMA_DIVISION_AREA = (
    "https://docs.overturemaps.org/schema/reference/divisions/division_area"
)
DOCS_ATTRIBUTION = "https://docs.overturemaps.org/attribution/"
RELEASE_NOTES = "https://docs.overturemaps.org/blog/"
RELEASE_CALENDAR = "https://docs.overturemaps.org/release-calendar/"

# ---------------------------------------------------------------------------
# Scope
# ---------------------------------------------------------------------------
# The subtypes this catalog carries, and the integer level each maps to in the
# search index. The mapping is the geocoder's level contract (country 0,
# region 1, county 2, localadmin 3, locality 4); ``dependency`` is folded into
# level 0 because an ISO 3166-1 coded dependency is a country-equivalent for a
# name search, even though Overture files it at admin_level 1.
#
# neighborhood, microhood and macrohood are excluded. See SUBTYPE_EXCLUDED.
SUBTYPE_LEVEL = {
    "country": 0,
    "dependency": 0,
    "region": 1,
    "county": 2,
    "localadmin": 3,
    "locality": 4,
}
SUBTYPES = tuple(SUBTYPE_LEVEL)
SUBTYPE_EXCLUDED = ("neighborhood", "microhood", "macrohood")

# One collection per subtype, except ``country``, which carries the 53
# dependencies alongside the 219 countries at the same level.
COLLECTIONS: dict[str, tuple[str, ...]] = {
    "country": ("country", "dependency"),
    "region": ("region",),
    "county": ("county",),
    "localadmin": ("localadmin",),
    "locality": ("locality",),
}
COLLECTION_LEVEL = {name: SUBTYPE_LEVEL[subs[0]] for name, subs in COLLECTIONS.items()}

# ---------------------------------------------------------------------------
# Layout targets
# ---------------------------------------------------------------------------
# Rows per row group, chosen per collection from the measured compressed bytes
# per row so that one row group lands between 1 and 2 MB. A client that wants
# one division's geometry fetches about that much instead of the whole file.
# tools/build_boundaries.py prints the measurement on every run; the numbers
# behind these constants are in catalog/*/README.md.
ROW_GROUP_ROWS = {
    "country": 8,
    "region": 26,
    "county": 96,
    "localadmin": 240,
    "locality": 960,
}

# The display-simplified files hold the same rows in the same order and the
# same groups, so a consumer reads row i of either file from group i // n.
DISPLAY_ROW_GROUP_ROWS = ROW_GROUP_ROWS

# Display simplification. The tolerance is per feature, not per collection:
#
#     tol = least(SIMPLIFY_TOLERANCE[collection],
#                 bbox_diagonal * SIMPLIFY_SHARE)
#
# and the outward buffer uses the same value. A single absolute tolerance
# cannot serve both Russia and Saint-Barthélemy, and the measurement that
# settled it is in catalog/country/README.md: at a flat 0.03 degrees,
# Saint-Barthélemy's display polygon covered 81.6% of its true area, because
# the tolerance was most of the island's width. Scaling by the feature's own
# extent gives 0 features below 99% containment at every level.
#
# SIMPLIFY_SHARE is the fraction of a feature's own bbox diagonal the outline
# may move. 0.4% was measured as the largest share that keeps every feature of
# every collection above 99% containment.
SIMPLIFY_SHARE = 0.004

# The per-collection ceiling, which binds only for features larger than
# SIMPLIFY_TOLERANCE / SIMPLIFY_SHARE degrees across.
SIMPLIFY_TOLERANCE = {
    "country": 0.03,
    "region": 0.01,
    "county": 0.004,
    "localadmin": 0.002,
    "locality": 0.0005,
}

# The search index is sorted by name_norm, so a client that wants a name
# prefix fetches a contiguous run of row groups.
#
# The index-file contract asks for 100-150 KiB per row group, and that is the
# right target for the index it was measured on: 2.5 MB, where the Parquet
# footer is a rounding error. It is the wrong target here. This index is 424 MB
# in 5.6 million rows, and the footer carries one thrift record per column per
# row group, so the footer grows as the row groups shrink. A range-request
# client reads the whole footer before it can read anything, which makes the
# footer part of what the first keystroke costs.
#
# Measured on the built index, with statistics restricted to the columns that
# need them:
#
#   rows/group  groups  footer  page index  per group  footer + 1 group
#        1,600   3,503  8.15 MB     2.45 MB    121 KiB          8.27 MB
#        3,200   1,752  4.10 MB     1.23 MB    239 KiB          4.34 MB
#        6,400     876  2.05 MB     0.62 MB    474 KiB          2.52 MB
#       12,800     438  1.05 MB     0.32 MB    960 KiB          2.01 MB
#
# 6,400 is the knee. It answers a first keystroke in 2.5 MB against 8.3 MB at
# the contract's band, and a later keystroke in under half a megabyte, which a
# client holds in memory anyway because typing one more letter of the same
# prefix stays inside the same row group. 12,800 saves another half megabyte
# on the first read and doubles every later one, which is the wrong way round
# for an autocomplete.
#
# tools/measure_index.py reprints the whole table's worth of numbers for the
# built file, and the build warns if the achieved figure leaves the band.
NAMES_ROW_GROUP_ROWS = 6400
NAMES_ROW_GROUP_TARGET_KIB = (400, 560)

ZSTD_LEVEL = 15

GLOBAL_BOUNDS = "{min_x: -180, min_y: -90, max_x: 180, max_y: 90}::BOX_2D"


def run(cmd: list[str] | str, **kw) -> None:
    """Run a command, echo it, and fail loudly."""
    shell = isinstance(cmd, str)
    printable = cmd if shell else " ".join(cmd)
    print(f"  $ {printable}", flush=True)
    subprocess.run(cmd, shell=shell, check=True, **kw)


def connect(*, memory_limit: str = "12GB", threads: int | None = None):
    """A DuckDB connection with spatial, httpfs and anonymous S3 access.

    Overture's bucket is public, so the credentials are set empty rather than
    left unset: an unset key makes DuckDB look for a credential chain and fail
    on a machine that has one configured for a different account.
    """
    import duckdb

    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial; INSTALL httpfs; LOAD httpfs;")
    con.execute(
        f"SET s3_region='{S3_REGION}'; "
        "SET s3_access_key_id=''; SET s3_secret_access_key='';"
    )
    # The default 30 s HTTP timeout is not enough for a multi-hundred-megabyte
    # column chunk read over a domestic connection, and a single timeout aborts
    # the whole query. Measured: the default failed partway through
    # part-00002 of type=division_area on the first attempt.
    con.execute(
        "SET http_timeout = 600000; SET http_retries = 6; "
        "SET http_retry_backoff = 4; SET http_keep_alive = true;"
    )
    con.execute("SET preserve_insertion_order = false;")
    con.execute(f"SET memory_limit='{memory_limit}';")
    WORK.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory='{(WORK / 'duckdb-tmp').as_posix()}';")
    if threads:
        con.execute(f"SET threads={threads};")
    con.execute("SET enable_progress_bar=false;")
    return con


# ---------------------------------------------------------------------------
# ISO 3166-1 alpha-2 to alpha-3
# ---------------------------------------------------------------------------
# Overture's ``country`` property is ISO 3166-1 alpha-2 (attested:
# docs.overturemaps.org/schema/reference/divisions/division). The index-file
# contract the geocoder reads declares ``country`` as alpha-3, and the sibling
# geoBoundaries index publishes alpha-3, so a widget configurable to either
# index can filter on one code system. The index therefore carries both: the
# derived alpha-3 under ``country``, and Overture's own alpha-2 byte for byte
# under ``country_iso2``.
#
# The mapping comes from pycountry, which packages the official ISO 3166-1
# table. The schema permits a synthetic alpha-2 code where no recognized one
# exists; such a code has no alpha-3 and is carried through unchanged, counted,
# and reported.


def register_iso3166(con) -> int:
    """Create an ``iso3166`` lookup table on a connection. Returns its size."""
    import pycountry

    rows = [(c.alpha_2, c.alpha_3) for c in pycountry.countries]
    con.execute("CREATE OR REPLACE TEMP TABLE iso3166 (alpha_2 VARCHAR, alpha_3 VARCHAR)")
    con.executemany("INSERT INTO iso3166 VALUES (?, ?)", rows)
    return len(rows)


def pycountry_version() -> str:
    import pycountry

    return getattr(pycountry, "__version__", "unknown")


def copy_ordered(con, sql: str, out: Path) -> None:
    """Run an ORDER BY query and write the result to one Parquet file in order.

    ``preserve_insertion_order`` is forced on for the write. The default
    connection turns it off, which is right for an unordered aggregate and
    wrong here: a parallel single-file write may emit batches out of order,
    and the row order of a boundary file is load-bearing. The search index's
    ``geometry_ref`` names a row number in it, and the display companion has
    to hold the same rows at the same offsets.

    The intermediate is written at zstd level 3 rather than the publishing
    level, because it is read once and deleted.
    """
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    con.execute("SET preserve_insertion_order = true;")
    try:
        con.execute(
            f"COPY ({sql}) TO '{out.as_posix()}' "
            "(FORMAT parquet, COMPRESSION zstd, COMPRESSION_LEVEL 3)"
        )
    finally:
        con.execute("SET preserve_insertion_order = false;")


def stream_write(
    src: Path,
    out: Path,
    *,
    row_group_rows: int,
    footer_meta: dict[bytes, bytes],
    batch_rows: int | None = None,
    transform=None,
    sorting_columns=None,
):
    """Rewrite a Parquet file with exact row groups, a batch at a time.

    The whole table is never held in memory. That is not only thrift: DuckDB's
    Arrow appender refuses a binary column whose offsets exceed 2 GiB, which
    the locality geometry column does on its own, and streaming avoids the
    limit rather than switching to 64-bit offsets and changing the published
    column types.

    ``batch_rows`` is rounded down to a multiple of ``row_group_rows``, so
    every group written is exactly full and a row number alone tells a
    consumer which group a row is in.
    """
    import pyarrow as pa
    import pyarrow.parquet as pq

    if batch_rows is None:
        batch_rows = row_group_rows * max(1, 65_536 // row_group_rows)
    batch_rows = max(row_group_rows, (batch_rows // row_group_rows) * row_group_rows)
    reader = pq.ParquetFile(src)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    writer = None
    try:
        for batch in reader.iter_batches(batch_size=batch_rows):
            table = pa.Table.from_batches([batch])
            if transform is not None:
                table = transform(table)
            if writer is None:
                schema = table.schema.with_metadata(footer_meta)
                writer = pq.ParquetWriter(
                    out,
                    schema,
                    compression="zstd",
                    compression_level=ZSTD_LEVEL,
                    write_statistics=True,
                    write_page_index=True,
                    version="2.6",
                    sorting_columns=sorting_columns,
                )
            writer.write_table(table.cast(writer.schema), row_group_size=row_group_rows)
    finally:
        if writer is not None:
            writer.close()
    return pq.ParquetFile(out).metadata


def geom_expr(con, path: Path, column: str = "geometry") -> str:
    """A SQL expression that is a DuckDB GEOMETRY, whatever the file holds.

    DuckDB recognizes the GeoParquet metadata it wrote itself and hands back a
    GEOMETRY column. It does not always recognize metadata PyArrow wrote, and
    then the same column arrives as a BLOB of WKB. Both happen in this
    pipeline -- the staged files come from DuckDB and the published files from
    PyArrow -- so the expression is chosen from the column's actual type
    rather than assumed.
    """
    rel = con.sql(f"SELECT {column} FROM read_parquet('{path.as_posix()}') LIMIT 0")
    kind = str(rel.types[0]).upper()
    if kind.startswith("GEOMETRY"):
        return column
    return f"ST_GeomFromWKB({column})"


def staged_area(collection: str) -> Path:
    return SOURCES / f"division_area-{collection}.parquet"


def staged_division() -> Path:
    return SOURCES / "division.parquet"


def boundary_path(collection: str) -> Path:
    return PUBLISH / collection / f"overture_{collection}.parquet"


def display_path(collection: str) -> Path:
    return PUBLISH / collection / f"overture_{collection}_display.parquet"


def pmtiles_path(collection: str) -> Path:
    return PUBLISH / collection / f"{collection}.pmtiles"


NAMES_PATH = PUBLISH / "names" / "overture_division_names.parquet"


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------
# The index-file contract fixes this: NFD, strip combining marks (Unicode
# category Mn), lowercase, collapse whitespace, trim, and keep only Unicode
# letters, digits, space, hyphen and apostrophe. Everything else is removed.
# The alphabet matters because the geocoder normalizes the user's keystrokes
# with the same rule in JavaScript and then compares strings byte-wise against
# this column; a character this rule keeps and the client's rule drops makes
# the binary search miss.
_KEEP = re.compile(r"[^\w\s'-]", re.UNICODE)
_UNDERSCORE = re.compile(r"_")
_WS = re.compile(r"\s+")


def normalize_name(name: str | None) -> str | None:
    """Fold a display name to the index's sort key."""
    if name is None:
        return None
    decomposed = unicodedata.normalize("NFD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    # \w includes the underscore, which is not in the declared alphabet.
    cleaned = _UNDERSCORE.sub(" ", _KEEP.sub(" ", stripped))
    folded = _WS.sub(" ", cleaned).strip().lower()
    return folded or None


def shrink_bbox_float32(bbox_array):
    """Recast a float64 bbox struct to float32, rounding outward.

    Halves what the bbox costs in the search index, where four doubles a row
    across millions of rows is tens of megabytes. A naive cast is not safe:
    float32 rounds to nearest, so an xmin could round *up* and leave part of
    the geometry outside the bbox that claims to cover it, which silently
    breaks both row group pruning and a map fly-to. So each minimum is nudged
    towards -inf and each maximum towards +inf whenever the cast moved it the
    wrong way. The resulting box is never smaller than the true one.

    float32 holds about 7 significant decimal digits, so a degree value keeps
    roughly 1e-5 degrees, about a metre.
    """
    import numpy as np
    import pyarrow as pa

    def outward(values, towards):
        exact = np.asarray(values, dtype=np.float64)
        cast = exact.astype(np.float32)
        wrong = (cast > exact) if towards < 0 else (cast < exact)
        if wrong.any():
            cast[wrong] = np.nextafter(cast[wrong], np.float32(towards * np.inf))
        return pa.array(cast, pa.float32())

    bbox_array = bbox_array.combine_chunks()
    return pa.StructArray.from_arrays(
        [
            outward(bbox_array.field("xmin").to_numpy(zero_copy_only=False), -1),
            outward(bbox_array.field("ymin").to_numpy(zero_copy_only=False), -1),
            outward(bbox_array.field("xmax").to_numpy(zero_copy_only=False), +1),
            outward(bbox_array.field("ymax").to_numpy(zero_copy_only=False), +1),
        ],
        names=["xmin", "ymin", "xmax", "ymax"],
    )


def geo_metadata(
    *,
    geometry_column: str = "geometry",
    bbox_column: str = "bbox",
    bbox: list[float],
    geometry_types: list[str],
) -> bytes:
    """A GeoParquet 1.1.0 ``geo`` metadata value with bbox covering.

    The ``crs`` key is omitted, which the GeoParquet specification defines as
    OGC:CRS84 (longitude, latitude in degrees on WGS 84). That is the CRS
    Overture publishes, so nothing is reprojected.
    """
    doc = {
        "version": "1.1.0",
        "primary_column": geometry_column,
        "columns": {
            geometry_column: {
                "encoding": "WKB",
                "geometry_types": geometry_types,
                "bbox": bbox,
                "covering": {
                    "bbox": {
                        "xmin": [bbox_column, "xmin"],
                        "ymin": [bbox_column, "ymin"],
                        "xmax": [bbox_column, "xmax"],
                        "ymax": [bbox_column, "ymax"],
                    }
                },
            }
        },
    }
    return json.dumps(doc).encode("utf-8")


# The version string the geocoder pins an index against. It appears in the
# index manifest, in the index parquet footer, and in every boundary file's
# footer; all three must agree or the geocoder refuses the fast path.
CATALOG_VERSION = f"overture-divisions-{RELEASE}"
CNMW_VERSION_KEY = "cnmw:catalog_version"


def trailing_bytes(path) -> tuple[int, int]:
    """``(footer_metadata, page_index)`` -- the two metadata spans at the end.

    Parquet writes the page index after the last row group and the thrift
    footer after that, so everything from the end of the last column chunk's
    pages to EOF is metadata and nothing else.

    A range client has to read that metadata before it can read any row group,
    and it has no way to know how big it is: hyparquet speculates a 512 KiB
    tail and fetches again when it guesses short. On this catalog's 408 MB
    index the footer alone is 2 MB, so the speculation is a *guaranteed*
    second round trip on every first query. Publishing both numbers in
    ``index.json`` removes it:

    * their sum, published as ``footer_bytes`` -- one request of exactly that
      many bytes from the end of the file leaves a client holding every piece
      of metadata the file has, footer and page index together;
    * the first element alone, published as ``footer_metadata_bytes`` -- the
      minimum a reader needs to locate row groups. hyparquet never reads the
      page index bodies, because it has no sub-chunk read, so a hyparquet
      client should ask for this one.

    ``file_offset`` is optional in the format and PyArrow writes 0 for it, so a
    chunk's start is taken from its dictionary page where it has one and from
    its first data page otherwise.
    """
    import pyarrow.parquet as pq

    path = Path(path)
    md = pq.ParquetFile(path).metadata
    last = md.row_group(md.num_row_groups - 1)
    end_of_data = 0
    for i in range(last.num_columns):
        col = last.column(i)
        start = col.dictionary_page_offset or col.data_page_offset
        end_of_data = max(end_of_data, start + col.total_compressed_size)
    size = path.stat().st_size
    with path.open("rb") as fh:
        fh.seek(-8, 2)
        metadata_len = int.from_bytes(fh.read(8)[:4], "little")
    footer = metadata_len + 8
    return footer, size - end_of_data - footer


def parquet_entry(path, url: str) -> dict:
    """The measured manifest description of one published Parquet file."""
    import pyarrow.parquet as pq

    path = Path(path)
    md = pq.ParquetFile(path).metadata
    footer, page_index = trailing_bytes(path)
    return {
        "url": url,
        "size": path.stat().st_size,
        "row_count": md.num_rows,
        "row_groups": md.num_row_groups,
        "footer_bytes": footer + page_index,
        "footer_metadata_bytes": footer,
    }


def footer_metadata(extra: dict[str, str] | None = None) -> dict[bytes, bytes]:
    """Key-value footer metadata every data file in this catalog carries."""
    meta = {
        CNMW_VERSION_KEY: CATALOG_VERSION,
        "overture:release": RELEASE,
        "overture:theme": "divisions",
    }
    meta.update(extra or {})
    return {k.encode("utf-8"): v.encode("utf-8") for k, v in meta.items()}


def wrap_markdown(text: str, width: int = 79) -> str:
    """Wrap generated markdown to a readable width, leaving structure alone.

    A generator builds a paragraph as one long string, and a reader opening
    the raw file in a terminal or a diff then gets one line per paragraph.
    Fenced code blocks, tables and headings are left exactly as they are,
    because wrapping any of those changes what they mean. List markers and
    blockquote markers keep their prefix and get a hanging indent.
    """
    import re
    import textwrap

    out: list[str] = []
    in_fence = False
    for line in text.split("\n"):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        stripped = line.strip()
        if (
            in_fence
            or not stripped
            or len(line) <= width
            or stripped.startswith(("|", "#", "---"))
        ):
            out.append(line)
            continue
        prefix = re.match(r"^(\s*(?:> )?(?:[-*] |\d+\. )?)", line).group(1)
        body = line[len(prefix):]
        hanging = " " * len(prefix)
        if prefix.lstrip().startswith(">"):
            hanging = prefix[: prefix.index(">") + 2]
        out.extend(
            textwrap.wrap(
                body,
                width=width,
                initial_indent=prefix,
                subsequent_indent=hanging,
                break_long_words=False,
                break_on_hyphens=False,
            )
            or [line]
        )
    return "\n".join(out)


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} GB"
