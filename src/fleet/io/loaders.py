"""Data loading utilities for raw clinical data.

Adapted from pharmaversepy utils/data_loader.py.
"""

from pathlib import Path
from typing import Literal

import httpx
import polars as pl

from ..core.exceptions import IOError as FleetIOError


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
    file_type: Literal["csv", "excel", "parquet"] | None = None,
    **kwargs,
) -> pl.LazyFrame:
    """Load a raw data file as a Polars LazyFrame.

    File type is auto-detected from the extension if not provided.

    Args:
        file_path: Path to the data file (.csv, .xlsx, .parquet).
        file_type: Explicit file type override.
        **kwargs: Additional arguments forwarded to the Polars reader.

    Returns:
        Polars LazyFrame.

    Raises:
        FleetIOError: If file not found or format unsupported.
    """
    if not file_path.exists():
        raise FleetIOError(f"File not found: {file_path}")

    if file_type is None:
        suffix = file_path.suffix.lower()
        type_map = {".csv": "csv", ".xlsx": "excel", ".xls": "excel", ".parquet": "parquet"}
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
        else:
            raise FleetIOError(f"Unsupported file type: {file_type}")
    except FleetIOError:
        raise
    except Exception as e:
        raise FleetIOError(f"Failed to load {file_path}: {e}") from e


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
    return {
        name: load_raw_data(path, file_type, **kwargs)
        for name, path in file_paths.items()
    }


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
            "pyreadstat is required to write XPT files. "
            "Install it with: uv add fleet[io]"
        ) from exc

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pandas_df = df.to_pandas()
    pandas_df.columns = [c[:8].upper() for c in pandas_df.columns]
    pyreadstat.write_xport(pandas_df, str(output_path))
    return output_path
