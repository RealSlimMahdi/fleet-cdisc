"""I/O module: data loaders and writers."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fleet.io.dataset_json import read_dataset_json, save_dataset_json
from fleet.io.loaders import download_raw_data, load_datasets, load_raw_data, save_parquet, save_xpt

if TYPE_CHECKING:
    import polars as pl

__all__ = [
    "load_raw_data",
    "load_datasets",
    "download_raw_data",
    "save_parquet",
    "save_xpt",
    "save_dataset_json",
    "read_dataset_json",
]

#: Dataset file extensions Fleet reads, in lower case.
DATASET_EXTENSIONS: tuple[str, ...] = (".parquet", ".csv", ".xpt", ".sas7bdat", ".json")

#: Output format of ``fleet run`` and ``fleet tdd build`` -> file extension.
OUTPUT_FORMATS: dict[str, str] = {"parquet": ".parquet", "xpt": ".xpt", "dataset-json": ".json"}


def write_dataset(
    df: pl.DataFrame,
    out_dir: Path,
    name: str,
    fmt: str,
    *,
    label: str | None = None,
    column_labels: Mapping[str, str | None] | None = None,
    json_metadata: Mapping[str, Any] | None = None,
) -> Path:
    """Write *df* as ``<out_dir>/<name>.<ext>`` in one of :data:`OUTPUT_FORMATS`.

    Args:
        df: The dataset.
        out_dir: The output directory.
        name: The dataset name; the file name is its lower case.
        fmt: ``"parquet"``, ``"xpt"`` or ``"dataset-json"``.
        label: The dataset label (XPT and Dataset-JSON).
        column_labels: Variable labels by name (XPT and Dataset-JSON).
        json_metadata: The :func:`save_dataset_json` keywords, for example
            from :func:`fleet.io.dataset_json.metadata_from_define`.  They
            replace *label* and *column_labels* for Dataset-JSON.

    Returns:
        Path: The file written.

    Examples:
        Write DM as XPT with its define labels::

            write_dataset(dm, Path("data/sdtm"), "DM", "xpt", label="Demographics")
    """
    path = Path(out_dir) / f"{name.lower()}{OUTPUT_FORMATS[fmt]}"
    if fmt == "parquet":
        return save_parquet(df, path)
    if fmt == "xpt":
        return save_xpt(df, path, label=label, column_labels=column_labels)
    if json_metadata is None:
        columns = {k: {"label": v} for k, v in (column_labels or {}).items()}
        json_metadata = {"label": label, "columns": columns}
    return save_dataset_json(df, path, domain=name, **json_metadata)
