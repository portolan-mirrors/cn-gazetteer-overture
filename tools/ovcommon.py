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
#   https://docs.overturemaps.org/release/latest/
#
RELEASE = "2026-10-21.0"
S3_BUCKET = "overturemaps-us-west-2"
S3_REGION = "us-west-2"
S3_THEME = f"s3://{S3_BUCKET}/release/{RELEASE}/theme=divisions"
EXTRACTION_DATE = "2026-11-12"

# The release's own documentation and attribution pages, cited throughout the
# catalog metadata.
DOCS_DIVISIONS = "https://docs.overturemaps.org/guides/divisions"
DOCS_SCHEMA_DIVISION = "https://docs.overturemaps.org/schema/reference/divisions/division"
DOCS_SCHEMA_DIVISION_AREA = (
    "https://docs.overturemaps.org/schema/reference/divisions/division_area"
)
DOCS_ATTRIBUTION = "https://docs.overturemaps.org/attribution/"
RELEASE_NOTES = "https://docs.overturemaps.org/release/latest/"

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
    "country": 2,
    "region": 16,
    "county": 128,
    "localadmin": 256,
    "locality": 4096,
}

# The display-simplified files hold the same rows in the same order and the
# same groups, so a consumer reads row i of either file from group i // n.
DISPLAY_ROW_GROUP_ROWS = ROW_GROUP_ROWS

# Simplification tolerance in degrees per collection, then an outward buffer of
# the same size. Chosen so a display feature lands in the low single-digit KB.
# The buffer is what makes the simplified shape a superset of the true one; see
# tools/build_display.py.
SIMPLIFY_TOLERANCE = {
    "country": 0.01,
    "region": 0.005,
    "county": 0.002,
    "localadmin": 0.002,
    "locality": 0.0005,
}

# The search index is sorted by name_norm, so a client that wants a name prefix
# fetches a contiguous run of row groups. The target is bytes, not rows: a row
# group of 100-150 KiB is what keeps a prefix lookup a single small range
# request as the index grows. tools/build_names.py prints the achieved KiB per
# group and fails if it leaves the band.
NAMES_ROW_GROUP_ROWS = 2048
NAMES_ROW_GROUP_TARGET_KIB = (100, 150)

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


def footer_metadata(extra: dict[str, str] | None = None) -> dict[bytes, bytes]:
    """Key-value footer metadata every data file in this catalog carries."""
    meta = {
        CNMW_VERSION_KEY: CATALOG_VERSION,
        "overture:release": RELEASE,
        "overture:theme": "divisions",
    }
    meta.update(extra or {})
    return {k.encode("utf-8"): v.encode("utf-8") for k, v in meta.items()}


def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n:.1f} GB"
