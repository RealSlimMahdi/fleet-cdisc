"""Data loading utilities for raw clinical data.

Adapted from pharmaversepy utils/data_loader.py.
"""

import mmap
import re
import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

import httpx
import polars as pl
import polars.selectors as cs

from fleet.core.exceptions import IOError as FleetIOError

_IO_EXTRA_HINT = 'Install it with: uv add "fleet-cdisc[io]"'

#: A SAS V5 name: the XPT member and every variable (FDA TCG 3.1.1, SAS TS-140).
_XPT_NAME = re.compile(r"[A-Z_][A-Z0-9_]{0,7}")
_XPT_MAX_LABEL = 40
_XPT_MAX_VALUE_BYTES = 200

#: pyreadstat reads DATE and DATETIME formats by default, but not TIME with a width.
_SAS_TIME_FORMATS = ["TIME", *(f"TIME{w}" for w in range(2, 21))]

#: A CSV value that a number would lose: SITEID 001, SUBJID 0012.
LEADING_ZERO = r"^\s*[+-]?0[0-9]"
_POLARS_CSV_ENCODINGS = ("utf8", "utf8-lossy")


def download_raw_data(
    url: str,
    destination: Path,
    overwrite: bool = False,
) -> Path:
    """Download a raw data file from a URL.

    Args:
        url: Source URL.
        destination: Local path to save the file.
        overwrite: If False and file exists, skip the download.

    Returns:
        Path to the downloaded file.

    Raises:
        FleetIOError: On download or write failure.
    """
    if destination.exists() and not overwrite:
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)

    try:
        with httpx.Client(follow_redirects=True, timeout=30.0) as client:
            response = client.get(url)
            response.raise_for_status()
            destination.write_bytes(response.content)
        return destination
    except httpx.HTTPError as e:
        raise FleetIOError(f"Failed to download data from {url}: {e}") from e
    except OSError as e:
        raise FleetIOError(f"Failed to save data to {destination}: {e}") from e


def load_raw_data(
    file_path: Path | str,
    file_type: Literal["csv", "excel", "parquet", "sas", "xpt", "rds", "rdata", "dataset-json"]
    | None = None,
    *,
    rdata_dataset: str | None = None,
    **kwargs,
) -> pl.LazyFrame:
    """Load a raw data file as a Polars LazyFrame.

    File type is auto-detected from the extension if not provided.
    Supports CSV, Excel, Parquet, SAS7BDAT, XPT, RDS, RData and
    Dataset-JSON (``.json``, read by :func:`fleet.io.read_dataset_json`).

    SAS files (XPT, SAS7BDAT) follow the SAS rule for missing values: a
    blank character value reads as null, so ``is_null()`` finds it.  A
    variable with no value keeps its SAS type, and DATE, DATETIME and TIME
    formats read as ``pl.Date``, ``pl.Datetime`` and ``pl.Time``.

    A CSV file holds no type, so Polars infers one from every row.  A
    column with a value that has a leading zero (SITEID ``001``) reads as
    text, with a warning, because a number would lose the zero.  Give
    ``schema_overrides={"SITEID": pl.String}`` for a text column, the
    equivalent of a SAS ``$`` informat; the caller's types always win.  A
    ``NaN`` cell in a float column reads as null, as SAS has no NaN, so a
    threshold verb never sees it as a number.

    Args:
        file_path: Path to the data file.
        file_type: Explicit file type override.
        rdata_dataset: For RData files containing multiple datasets, the
            name of the dataset to load. Defaults to the first dataset.
        **kwargs: Forwarded to the reader of the file type: the Polars
            reader for CSV, Excel and Parquet, pyreadstat for SAS files
            (for example ``encoding="iso-8859-1"`` for a file from a
            WLATIN1 SAS session, or ``usecols=``), and pyreadr for R
            files.  A keyword the reader does not take raises.

    Returns:
        Polars LazyFrame.

    Raises:
        FleetIOError: If file not found, format unsupported, or the reader
            refuses a keyword or cannot decode the text.
        ImportError: If optional dependency (pyreadstat, pyreadr) is missing.

    Examples:
        Read a legacy XPT from a WLATIN1 SAS session, then derive::

            ae = fleet.load_raw_data(Path("legacy/ae.xpt"), encoding="iso-8859-1")
            adae = ae.collect().adam.source("USUBJID").to_frame()
    """
    file_path = Path(file_path)
    if not file_path.exists():
        raise FleetIOError(f"File not found: {file_path}")

    if file_type is None:
        suffix = file_path.suffix.lower()
        type_map = {
            ".csv": "csv",
            ".xlsx": "excel",
            ".xls": "excel",
            ".parquet": "parquet",
            ".sas7bdat": "sas",
            ".xpt": "xpt",
            ".rds": "rds",
            ".rda": "rdata",
            ".rdata": "rdata",
            ".json": "dataset-json",
        }
        file_type = type_map.get(suffix)
        if file_type is None:
            raise FleetIOError(f"Unsupported file type: {suffix}")

    try:
        if file_type == "csv":
            # SAS has no NaN: a text NaN cell is a missing value.
            return _load_csv(file_path, **kwargs).with_columns(cs.float().fill_nan(None))
        elif file_type == "excel":
            return pl.read_excel(file_path, **kwargs).lazy()
        elif file_type == "parquet":
            return pl.scan_parquet(file_path, **kwargs)
        elif file_type in ("sas", "xpt"):
            return _load_sas(file_path, **kwargs)
        elif file_type in ("rds", "rdata"):
            return _load_r(file_path, dataset_name=rdata_dataset, **kwargs)
        elif file_type == "dataset-json":
            from fleet.io.dataset_json import read_dataset_json

            return read_dataset_json(file_path).lazy()
        else:
            raise FleetIOError(f"Unsupported file type: {file_type}")
    except (FleetIOError, ImportError):
        raise
    except Exception as e:
        raise FleetIOError(f"Failed to load {file_path}: {e}") from e


def _load_csv(file_path: Path, **kwargs) -> pl.LazyFrame:
    """Read a CSV with types inferred from every row; a leading zero keeps a column text."""
    encoding = kwargs.get("encoding", "utf8")

    def scan(**options) -> pl.LazyFrame:
        if encoding in _POLARS_CSV_ENCODINGS:
            return pl.scan_csv(file_path, **options)
        return pl.read_csv(file_path, **options).lazy()  # Python decodes other encodings

    if "schema" in kwargs or kwargs.get("infer_schema") is False:
        return scan(**kwargs)
    overrides = dict(kwargs.pop("schema_overrides", None) or {})
    hits = (
        scan(**kwargs, infer_schema=False)
        .select(pl.all().str.contains(LEADING_ZERO).any())
        .collect()
        .row(0, named=True)
    )
    leading = [c for c, hit in hits.items() if hit and c not in overrides]
    if leading:
        warnings.warn(
            f"{file_path.name}: {', '.join(leading)} hold(s) a value with a leading zero, "
            "so read as text. Pass schema_overrides= to choose the type.",
            stacklevel=4,
        )
    kwargs.setdefault("infer_schema_length", None)
    return scan(**kwargs, schema_overrides=overrides | dict.fromkeys(leading, pl.String))


def _load_sas(file_path: Path, **kwargs) -> pl.LazyFrame:
    """Load SAS7BDAT or XPT via pyreadstat (returns LazyFrame + extracts labels)."""
    try:
        import pyreadstat
    except ImportError as exc:
        raise ImportError(f"pyreadstat is required for SAS file support. {_IO_EXTRA_HINT}") from exc

    is_sas7bdat = file_path.suffix.lower() == ".sas7bdat"
    if not is_sas7bdat:
        members = _xpt_members(file_path)
        if len(members) > 1:
            raise FleetIOError(
                f"{file_path.name} holds {len(members)} members ({', '.join(members)}); "
                "write one dataset per file (FDA TCG 3.1.1)."
            )
    reader = pyreadstat.read_sas7bdat if is_sas7bdat else pyreadstat.read_xport
    try:
        df, meta = reader(
            str(file_path),
            output_format="polars",
            extra_time_formats=_SAS_TIME_FORMATS,
            **kwargs,
        )
    except UnicodeDecodeError as exc:
        raise FleetIOError(
            f"Cannot read the text in {file_path}: {exc}. The file was likely written by a "
            'SAS session in another encoding. Name it, for example encoding="iso-8859-1" '
            "(fleet compare and fleet validate: --encoding iso-8859-1)."
        ) from exc
    sas_types = meta.readstat_variable_types
    lf = (
        df.lazy()
        .with_columns(
            pl.col(c).cast(pl.String if sas_types.get(c) == "string" else pl.Float64)
            for c, dtype in df.schema.items()
            if dtype == pl.Null
        )
        .with_columns(cs.string().replace("", None))
    )

    # Attach SAS labels as a retrievable attribute on the LazyFrame
    # (the profiler checks for this when building ColumnProfiles)
    if meta.column_names_to_labels:
        lf._sas_labels = meta.column_names_to_labels  # type: ignore[attr-defined]

    return lf


def _xpt_members(file_path: Path) -> list[str]:
    """The member names of a SAS transport file, in file order."""
    names = []
    with (
        file_path.open("rb") as handle,
        mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as data,
    ):
        for header, width in (
            (b"HEADER RECORD*******MEMBER  ", 8),
            (b"HEADER RECORD*******MEMBV8  ", 32),
        ):
            pos = data.find(header)
            while pos != -1:
                if pos % 80 == 0:
                    # member header, descriptor header, then "SAS     " + member name
                    start = pos + 160 + 8
                    names.append(
                        (pos, data[start : start + width].decode("ascii", "replace").strip())
                    )
                pos = data.find(header, pos + 1)
    return [name for _, name in sorted(names)]


def _load_r(file_path: Path, *, dataset_name: str | None = None, **kwargs) -> pl.LazyFrame:
    """Load RDS or RData via pyreadr (returns LazyFrame)."""
    try:
        import pyreadr
    except ImportError as exc:
        raise ImportError(
            "pyreadr is required for R file support. "
            "Install it with: uv add pyreadr (or uv sync --extra clinical-io)"
        ) from exc

    result = pyreadr.read_r(str(file_path), **kwargs)

    if not result:
        raise FleetIOError(f"No datasets found in R file: {file_path}")

    if dataset_name:
        if dataset_name not in result:
            available = ", ".join(result.keys())
            raise FleetIOError(
                f"Dataset '{dataset_name}' not found in {file_path}. Available: {available}"
            )
        df_pd = result[dataset_name]
    else:
        # Use the first (or only) dataset
        df_pd = next(iter(result.values()))

    # pyreadr may return pandas Extension types; coerce to numpy-backed equivalents
    import pandas as _pd

    df_pd = df_pd.copy()
    for col in df_pd.columns:
        col_dtype = df_pd[col].dtype
        if isinstance(col_dtype, _pd.api.extensions.ExtensionDtype):
            if hasattr(col_dtype, "numpy_dtype"):
                df_pd[col] = df_pd[col].astype(col_dtype.numpy_dtype)
            else:
                df_pd[col] = df_pd[col].astype(object)
    return pl.from_pandas(df_pd).lazy()


def load_datasets(
    file_paths: dict[str, Path | str],
    file_type: Literal["csv", "excel", "parquet"] | None = None,
    **kwargs,
) -> dict[str, pl.LazyFrame]:
    """Load multiple datasets into a named dict of LazyFrames.

    Args:
        file_paths: Mapping of dataset name to file path.
        file_type: Common file type override (auto-detected per file if None).
        **kwargs: Additional arguments forwarded to all readers.

    Returns:
        Dict mapping dataset names to LazyFrames.

    Raises:
        FleetIOError: If any file fails to load.
    """
    return {name: load_raw_data(path, file_type, **kwargs) for name, path in file_paths.items()}


def save_parquet(df: pl.DataFrame, output_path: Path, **kwargs) -> Path:
    """Save a DataFrame to Parquet.

    Args:
        df: DataFrame to save.
        output_path: Destination path.
        **kwargs: Forwarded to df.write_parquet().

    Returns:
        Path to the saved file.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(output_path, **kwargs)
    return output_path


def save_xpt(
    df: pl.DataFrame,
    output_path: Path,
    *,
    label: str | None = None,
    column_labels: Mapping[str, str | None] | None = None,
) -> Path:
    """Save a DataFrame as a SAS transport file, version 5 (requires pyreadstat).

    The file follows FDA TCG 3.1.1: XPORT version 5, and the member is
    named as the file (``adsl.xpt`` holds ``ADSL``).  Variable names are
    upper-cased.  A ``pl.Date`` is stored as SAS days since 01JAN1960 with
    DATE9, a ``pl.Datetime`` as seconds with DATETIME20, and a ``pl.Time``
    as seconds with TIME8.  NaN and infinity become SAS missing; infinity
    also warns.  A value that is not ASCII is written as UTF-8 bytes, with
    a warning (TCG 3.1.5).  Nothing is cut: a name over 8 characters, a
    label over 40 or a value over 200 bytes stops the write.

    Args:
        df: DataFrame to save.
        output_path: Destination path, ``<member>.xpt``.
        label: The dataset label, at most 40 ASCII characters.
        column_labels: Variable labels by name, at most 40 ASCII characters each.

    Returns:
        Path to saved file.

    Raises:
        ImportError: If pyreadstat is not installed.
        FleetIOError: When a name, a label or a value does not fit XPORT
            version 5, or a column holds a nested type.

    Examples:
        Write ADSL for submission::

            adsl = raw_dm.adam.source("USUBJID").to_frame()
            fleet.io.save_xpt(adsl, Path("adam/adsl.xpt"), label="Subject-Level Analysis Dataset")
    """
    try:
        import pyreadstat
    except ImportError as exc:
        raise ImportError(f"pyreadstat is required to write XPT files. {_IO_EXTRA_HINT}") from exc

    output_path = Path(output_path)
    member = output_path.stem.upper()
    out = _xpt_frame(df, member)
    labels = {name.upper(): text for name, text in (column_labels or {}).items() if text}
    _check_xpt_labels(member, label, labels)
    formats = {c: f for c, dtype in out.schema.items() if (f := _xpt_format(dtype))}

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pyreadstat.write_xport(
        out,
        str(output_path),
        file_label=label or "",
        column_labels={c: labels[c] for c in out.columns if c in labels},
        table_name=member,
        file_format_version=5,
        variable_format=formats,
    )
    return output_path


def _xpt_frame(df: pl.DataFrame, member: str) -> pl.DataFrame:
    """*df* with V5 names and SAS types, after every check that can stop the write."""
    rule = "1 to 8 letters, digits or underscores, not starting with a digit"
    if not _XPT_NAME.fullmatch(member):
        raise FleetIOError(
            f"XPT member name {member} must be {rule}; it is the file name (FDA TCG 3.1.1)."
        )
    bad = [c for c in df.columns if not _XPT_NAME.fullmatch(c.upper())]
    if bad:
        raise FleetIOError(f"{member}: variable name(s) {', '.join(bad)} must be {rule}.")
    upper = [c.upper() for c in df.columns]
    repeated = sorted({u for u in upper if upper.count(u) > 1})
    if repeated:
        raise FleetIOError(f"{member}: {', '.join(repeated)} repeat(s) once upper-cased.")
    nested = [c for c, dtype in df.schema.items() if dtype.is_nested()]
    if nested:
        raise FleetIOError(f"{member}: {', '.join(nested)} hold nested values; XPT has none.")

    out = df.rename(dict(zip(df.columns, upper, strict=True))).with_columns(
        cs.decimal().cast(pl.Float64),
        cs.categorical().cast(pl.String),
        cs.enum().cast(pl.String),
    )
    strings = [c for c, dtype in out.schema.items() if dtype == pl.String]
    too_long = [c for c in strings if (out[c].str.len_bytes().max() or 0) > _XPT_MAX_VALUE_BYTES]
    if too_long:
        raise FleetIOError(
            f"{member}: {', '.join(too_long)} hold(s) a value over "
            f"{_XPT_MAX_VALUE_BYTES} bytes, the XPT V5 limit. Split it (SDTMIG 4.5.3.2)."
        )
    non_ascii = [c for c in strings if (out[c].str.len_bytes() != out[c].str.len_chars()).any()]
    if non_ascii:
        warnings.warn(
            f"{member}: {', '.join(non_ascii)} hold(s) characters that are not ASCII; they are "
            "written as UTF-8 bytes, which a WLATIN1 SAS session reads wrongly (FDA TCG 3.1.5).",
            stacklevel=3,
        )
    floats = [c for c, dtype in out.schema.items() if dtype.is_float()]
    infinite = [c for c in floats if out[c].is_infinite().any()]
    if infinite:
        warnings.warn(
            f"{member}: {', '.join(infinite)} hold(s) an infinite value, written as SAS "
            "missing. Check the derivation for a division by zero.",
            stacklevel=3,
        )
    return out.with_columns(pl.when(pl.col(c).is_finite()).then(pl.col(c)).alias(c) for c in floats)


def _check_xpt_labels(member: str, label: str | None, labels: Mapping[str, str]) -> None:
    """Refuse a dataset or variable label that XPT V5 cannot hold."""
    named = [("dataset label", label), *((f"label of {c}", text) for c, text in labels.items())]
    for what, text in named:
        if text and (len(text) > _XPT_MAX_LABEL or not text.isascii()):
            raise FleetIOError(
                f"{member}: the {what} {text!r} must be ASCII and at most "
                f"{_XPT_MAX_LABEL} characters (XPT V5)."
            )


def _xpt_format(dtype: pl.DataType) -> str | None:
    """The SAS format a temporal dtype is stored with; ``None`` for the others."""
    if dtype == pl.Date:
        return "DATE9"
    if isinstance(dtype, pl.Datetime):
        return "DATETIME20"
    if dtype == pl.Time:
        return "TIME8"
    return None
