"""Controlled terminology loading utilities.

Adapted from pharmaversepy utils/ct_loader.py.
Supports YAML and CSV CT files, with optional URL download.
"""

from pathlib import Path
from typing import Any

import httpx
import polars as pl
import yaml

from ..core.exceptions import CTError


def load_controlled_terminology(
    ct_path: Path | str,
    codelist_name: str | None = None,
) -> dict[str, dict[str, str]]:
    """Load CDISC controlled terminology from a YAML or CSV file (or URL).

    Args:
        ct_path: Path or URL to CT file. Supported formats: .yaml, .yml, .csv.
        codelist_name: If given, only load this specific codelist.

    Returns:
        Nested dict mapping codelist_name -> {code: decoded_value}.

    Raises:
        CTError: If the file cannot be found, read, or is in an unsupported format.
    """
    if isinstance(ct_path, str):
        if ct_path.startswith("http"):
            ct_path = _download_ct(ct_path)
        else:
            ct_path = Path(ct_path)

    if not ct_path.exists():
        raise CTError(f"CT file not found: {ct_path}")

    suffix = ct_path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        return _load_ct_yaml(ct_path, codelist_name)
    elif suffix == ".csv":
        return _load_ct_csv(ct_path, codelist_name)
    else:
        raise CTError(f"Unsupported CT file type: {suffix}. Use .yaml or .csv")


def _download_ct(url: str) -> Path:
    """Download a CT file from a URL into a system temp directory."""
    import tempfile

    temp_dir = Path(tempfile.gettempdir()) / "fleet_ct"
    temp_dir.mkdir(exist_ok=True)

    filename = url.split("/")[-1]
    destination = temp_dir / filename

    try:
        with httpx.Client(follow_redirects=True, timeout=30.0) as client:
            response = client.get(url)
            response.raise_for_status()
            destination.write_bytes(response.content)
        return destination
    except httpx.HTTPError as e:
        raise CTError(f"Failed to download CT from {url}: {e}") from e


def _load_ct_yaml(ct_path: Path, codelist_name: str | None) -> dict[str, dict[str, str]]:
    try:
        with open(ct_path) as f:
            data: dict[str, Any] = yaml.safe_load(f)

        if codelist_name:
            if codelist_name not in data:
                raise CTError(f"Codelist '{codelist_name}' not found in CT file")
            return {codelist_name: data[codelist_name]}

        return data
    except yaml.YAMLError as e:
        raise CTError(f"Invalid YAML in CT file: {e}") from e
    except CTError:
        raise
    except Exception as e:
        raise CTError(f"Failed to load CT from {ct_path}: {e}") from e


def _load_ct_csv(ct_path: Path, codelist_name: str | None) -> dict[str, dict[str, str]]:
    """Load CT from CSV with columns: codelist, code, value."""
    try:
        df = pl.read_csv(ct_path)

        required = {"codelist", "code", "value"}
        if not required.issubset(df.columns):
            raise CTError(f"CT CSV must have columns: {', '.join(required)}")

        if codelist_name:
            df = df.filter(pl.col("codelist") == codelist_name)
            if df.height == 0:
                raise CTError(f"Codelist '{codelist_name}' not found in CT file")

        result: dict[str, dict[str, str]] = {}
        for cl in df["codelist"].unique().to_list():
            sub = df.filter(pl.col("codelist") == cl)
            result[cl] = dict(zip(sub["code"].to_list(), sub["value"].to_list()))

        return result
    except CTError:
        raise
    except Exception as e:
        raise CTError(f"Failed to load CT from {ct_path}: {e}") from e


def create_ct_lookup(ct_dict: dict[str, dict[str, str]], codelist_name: str) -> dict[str, str]:
    """Extract a single codelist as a flat code->value mapping.

    Args:
        ct_dict: Full CT dictionary from load_controlled_terminology.
        codelist_name: Codelist to extract.

    Raises:
        CTError: If codelist not found.
    """
    if codelist_name not in ct_dict:
        raise CTError(f"Codelist '{codelist_name}' not found in CT dictionary")
    return ct_dict[codelist_name]
