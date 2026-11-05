"""Controlled terminology loading utilities.

Adapted from pharmaversepy utils/ct_loader.py.
Supports YAML and CSV CT files, with optional URL download.
"""

import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import polars as pl
import yaml

from fleet.core.exceptions import CTError


def load_controlled_terminology(
    ct_path: Path | str,
    codelist_name: str | None = None,
) -> dict[str, dict[str, str]]:
    """Load CDISC controlled terminology from a YAML or CSV file (or URL).

    Every term and decode stays exact text: a YAML ``0``, ``Yes`` or
    ``1.10`` is the term ``"0"``, ``"Yes"`` or ``"1.10"``.  A URL file is
    downloaded into a private temporary folder and read there.

    Args:
        ct_path: Path or URL to CT file. Supported formats: .yaml, .yml, .csv.
        codelist_name: If given, only load this specific codelist.

    Returns:
        Nested dict mapping codelist_name -> {code: decoded_value}.

    Raises:
        CTError: If the file cannot be found or read, is in an unsupported
            format, or is not a non-empty mapping of codelists to terms.

    Examples:
        Read the codelists of a study CT file::

            from fleet.ct import load_controlled_terminology

            ct = load_controlled_terminology("ct/cdisc_ct.yaml")
            sex_terms = sorted(ct["C66731"])
    """
    if isinstance(ct_path, str) and ct_path.lower().startswith(("http://", "https://")):
        with tempfile.TemporaryDirectory(prefix="fleet_ct_") as tmp:
            return _load_file(_download_ct(ct_path, Path(tmp)), codelist_name)
    return _load_file(Path(ct_path), codelist_name)


def _load_file(ct_path: Path, codelist_name: str | None) -> dict[str, dict[str, str]]:
    if not ct_path.exists():
        raise CTError(f"CT file not found: {ct_path}")
    suffix = ct_path.suffix.lower()
    if suffix in (".yaml", ".yml"):
        return _load_ct_yaml(ct_path, codelist_name)
    if suffix == ".csv":
        return _load_ct_csv(ct_path, codelist_name)
    raise CTError(f"Unsupported CT file type: {suffix}. Use .yaml or .csv")


def _download_ct(url: str, folder: Path) -> Path:
    """Download a CT file from *url* into *folder*, a private temporary folder."""
    filename = Path(urlsplit(url).path).name
    if not filename:
        raise CTError(f"CT URL {url} names no file (.yaml, .yml or .csv).")
    destination = folder / filename
    try:
        with httpx.Client(follow_redirects=True, timeout=30.0) as client:
            response = client.get(url)
            response.raise_for_status()
            destination.write_bytes(response.content)
        return destination
    except httpx.HTTPError as e:
        raise CTError(f"Failed to download CT from {url}: {e}") from e


def _checked(data: Any, ct_path: Path) -> dict[str, dict[str, str]]:
    """*data* when it is a non-empty mapping of codelists to term mappings."""
    if not isinstance(data, dict) or not data:
        raise CTError(
            f"{ct_path}: a CT file is a mapping of codelists to terms "
            "(C66731: {M: Male, F: Female}); this file is empty or not a mapping."
        )
    bad = [str(key) for key, terms in data.items() if not isinstance(terms, dict)]
    if bad:
        raise CTError(
            f"{ct_path}: codelist(s) {', '.join(bad[:5])} are not a mapping of terms "
            "to decodes (M: Male)."
        )
    return data


def _load_ct_yaml(ct_path: Path, codelist_name: str | None) -> dict[str, dict[str, str]]:
    try:
        # BaseLoader keeps every scalar as text: the term 0 or Yes is not an int or bool.
        data = _checked(
            yaml.load(ct_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader), ct_path
        )  # noqa: S506
    except yaml.YAMLError as e:
        raise CTError(f"Invalid YAML in CT file: {e}") from e
    except OSError as e:
        raise CTError(f"Failed to load CT from {ct_path}: {e}") from e
    if codelist_name:
        if codelist_name not in data:
            raise CTError(f"Codelist '{codelist_name}' not found in CT file")
        return {codelist_name: data[codelist_name]}
    return data


def _load_ct_csv(ct_path: Path, codelist_name: str | None) -> dict[str, dict[str, str]]:
    """Load CT from CSV with columns: codelist, code, value."""
    try:
        df = pl.read_csv(ct_path, infer_schema=False)
    except Exception as e:
        raise CTError(f"Failed to load CT from {ct_path}: {e}") from e

    required = {"codelist", "code", "value"}
    if not required.issubset(df.columns):
        raise CTError(f"CT CSV must have columns: {', '.join(sorted(required))}")

    if codelist_name:
        df = df.filter(pl.col("codelist") == codelist_name)
        if df.height == 0:
            raise CTError(f"Codelist '{codelist_name}' not found in CT file")

    result: dict[str, dict[str, str]] = {}
    for cl in df["codelist"].unique(maintain_order=True).to_list():
        sub = df.filter(pl.col("codelist") == cl)
        result[cl] = dict(zip(sub["code"].to_list(), sub["value"].to_list(), strict=True))
    return _checked(result, ct_path)
