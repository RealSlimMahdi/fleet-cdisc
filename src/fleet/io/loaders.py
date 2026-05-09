"""Data loading utilities for raw clinical data.

Adapted from pharmaversepy utils/data_loader.py.
"""

from pathlib import Path
from typing import Literal

import httpx
import polars as pl

from fleet.core.exceptions import IOError as FleetIOError


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
    file_path: Path,
    file_type: Literal["csv", "excel", "parquet", "sas", "xpt", "rds", "rdata"] | None = None,
    *,
    rdata_dataset: str | None = None,
    **kwargs,
) -> pl.LazyFrame:
    """Load a raw data file as a Polars LazyFrame.

    File type is auto-detected from the extension if not provided.
    Supports CSV, Excel, Parquet, SAS7BDAT, XPT, RDS, and RData formats.

    Args:
        file_path: Path to the data file.
        file_type: Explicit file type override.
        rdata_dataset: For RData files containing multiple datasets, the
            name of the dataset to load. Defaults to the first dataset.
        **kwargs: Additional arguments forwarded to the Polars reader.

    Returns:
        Polars LazyFrame.

    Raises:
        FleetIOError: If file not found or format unsupported.
        ImportError: If optional dependency (pyreadstat, pyreadr) is missing.
    """
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
        }
        file_type = type_map.get(suffix)
        if file_type is None:
            raise FleetIOError(f"Unsupported file type: {suffix}")

    try:
        if file_type == "csv":
            return pl.scan_csv(file_path, **kwargs)
        elif file_type == "excel":
            return pl.read_excel(file_path, **kwargs).lazy()
        elif file_type == "parquet":
            return pl.scan_parquet(file_path, **kwargs)
        elif file_type in ("sas", "xpt"):
            return _load_sas(file_path, **kwargs)
        elif file_type in ("rds", "rdata"):
            return _load_r(file_path, dataset_name=rdata_dataset, **kwargs)
        else:
            raise FleetIOError(f"Unsupported file type: {file_type}")
    except (FleetIOError, ImportError):
        raise
    except Exception as e:
        raise FleetIOError(f"Failed to load {file_path}: {e}") from e


def _load_sas(file_path: Path, **kwargs) -> pl.LazyFrame:
    """Load SAS7BDAT or XPT via pyreadstat (returns LazyFrame + extracts labels)."""
    try:
        import pyreadstat
    except ImportError as exc:
        raise ImportError(
            "pyreadstat is required for SAS file support. "
            "Install it with: uv add pyreadstat (or uv sync --extra io)"
        ) from exc

    df_pd, meta = (
        pyreadstat.read_sas7bdat(str(file_path))
        if file_path.suffix.lower() == ".sas7bdat"
        else pyreadstat.read_xport(str(file_path))
    )
    # pyreadstat may return nullable pandas Extension types (e.g. Int64, StringDtype).
    # pl.from_pandas requires numpy-backed dtypes when pyarrow is not installed,
    # so coerce Extension dtypes to their numpy equivalents.
    import pandas as _pd

    df_pd = df_pd.copy()
    for col in df_pd.columns:
        col_dtype = df_pd[col].dtype
        if isinstance(col_dtype, _pd.api.extensions.ExtensionDtype):
            if hasattr(col_dtype, "numpy_dtype"):
                df_pd[col] = df_pd[col].astype(col_dtype.numpy_dtype)
            else:
                df_pd[col] = df_pd[col].astype(object)
    df = pl.from_pandas(df_pd)
    lf = df.lazy()

    # Attach SAS labels as a retrievable attribute on the LazyFrame
    # (the profiler checks for this when building ColumnProfiles)
    if meta.column_names_to_labels:
        lf._sas_labels = meta.column_names_to_labels  # type: ignore[attr-defined]

    return lf


def _load_r(file_path: Path, *, dataset_name: str | None = None, **kwargs) -> pl.LazyFrame:
    """Load RDS or RData via pyreadr (returns LazyFrame)."""
    try:
        import pyreadr
    except ImportError as exc:
        raise ImportError(
            "pyreadr is required for R file support. "
            "Install it with: uv add pyreadr (or uv sync --extra clinical-io)"
        ) from exc

    result = pyreadr.read_r(str(file_path))

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
    file_paths: dict[str, Path],
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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(output_path, **kwargs)
    return output_path


def save_xpt(df: pl.DataFrame, output_path: Path) -> Path:
    """Save a DataFrame to SAS XPT format (requires pyreadstat).

    Column names are automatically upper-cased and truncated to 8 chars
    to comply with the SAS Transport file format.

    Args:
        df: DataFrame to save.
        output_path: Destination path (should end in .xpt).

    Returns:
        Path to saved file.

    Raises:
        ImportError: If pyreadstat is not installed.
        FleetIOError: On write failure.
    """
    try:
        import pyreadstat
    except ImportError as exc:
        raise ImportError(
            "pyreadstat is required to write XPT files. Install it with: uv add fleet[io]"
        ) from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pandas_df = df.to_pandas()
    pandas_df.columns = [c[:8].upper() for c in pandas_df.columns]
    pyreadstat.write_xport(pandas_df, str(output_path))
    return output_path
