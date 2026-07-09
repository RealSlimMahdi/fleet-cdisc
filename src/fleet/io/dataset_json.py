"""Dataset-JSON v1.1 serializer and reader — pure Polars, no external deps.

Implements the CDISC Dataset-JSON v1.1 specification for writing Polars
DataFrames to the ``.json`` format accepted by the CDISC Rules Engine
CLI (``-dp dataset.json``).  No pandas, pyreadstat, or pyarrow required.

References
----------
- Dataset-JSON v1.1 spec: https://wiki.cdisc.org/display/DSJSON
- JSON Schema: https://github.com/cdisc-org/DataExchange-DatasetJson
- CDISC Rules Engine supported formats: XPT, JSON, NDJSON, XLSX
"""

from __future__ import annotations

import json as _json
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

import polars as pl

# ────────────────────────────────────────────────────────────────────── #
# Schema path                                                             #
# ────────────────────────────────────────────────────────────────────── #

DATASET_JSON_SCHEMA_PATH: Path = Path(__file__).parent / "schemas" / "dataset_json_v1_1_schema.json"
"""Path to the vendored CDISC Dataset-JSON v1.1 JSON-Schema file."""


def get_dataset_json_schema() -> dict:
    """Load and return the CDISC Dataset-JSON v1.1 JSON-Schema as a dict."""
    return _json.loads(DATASET_JSON_SCHEMA_PATH.read_text(encoding="utf-8"))


# ────────────────────────────────────────────────────────────────────── #
# Dtype mapping                                                          #
# ────────────────────────────────────────────────────────────────────── #


def _dtype_to_dsj_type(dtype: pl.DataType) -> str:
    """Map a Polars dtype to the Dataset-JSON ``dataType`` string.

    Dataset-JSON v1.1 recognises:
    ``"string"``, ``"integer"``, ``"float"``, ``"double"``,
    ``"boolean"``, ``"date"``, ``"time"``, ``"datetime"``.
    """
    if dtype in (pl.String, pl.Categorical, pl.Utf8):
        return "string"
    if dtype in (pl.Int8, pl.Int16, pl.Int32, pl.Int64):
        return "integer"
    if dtype in (pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64):
        return "integer"
    if dtype == pl.Float32:
        return "float"
    if dtype == pl.Float64:
        return "double"
    if dtype == pl.Boolean:
        return "boolean"
    if dtype == pl.Date:
        return "date"
    if dtype == pl.Time:
        return "time"
    if dtype in (pl.Datetime, pl.Duration):
        return "datetime"
    return "string"


# ────────────────────────────────────────────────────────────────────── #
# Writer                                                                  #
# ────────────────────────────────────────────────────────────────────── #


def _serialize_value(v: Any) -> Any:
    """Coerce a single cell value to a JSON-safe type."""
    if v is None:
        return None
    if isinstance(v, (int, float, bool)):
        return v
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    if isinstance(v, time):
        return v.isoformat()
    return str(v)


def save_dataset_json(
    df: pl.DataFrame,
    path: str | Path,
    *,
    domain: str,
    label: str | None = None,
    originator: str = "Fleet",
    file_oid: str | None = None,
) -> Path:
    """Write a Polars DataFrame as a CDISC Dataset-JSON v1.1 file.

    Args:
        df: The DataFrame to serialize.
        path: Destination file path (should end in ``.json``).
        domain: Dataset / domain name (e.g. ``"DM"``, ``"ADSL"``).
            Used for ``name``, ``itemGroupOID``, and column ``itemOID`` prefixes.
        label: Human-readable dataset label.  Defaults to
            ``"<domain> dataset"`` if omitted.
        originator: Organisation that created the file.
        file_oid: Unique file identifier.  Defaults to the file stem.

    Returns:
        Path to the written file.

    Examples:
        Export an SDTM DM dataset::

            from fleet.io import save_dataset_json

            dm = raw_df.sdtm.assign("DOMAIN", value="DM").to_frame()
            save_dataset_json(dm, "outputs/dm.json", domain="DM")
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    dom = domain.upper()
    lbl = label or f"{dom} dataset"
    foid = file_oid or path.stem

    # ── Column definitions ──────────────────────────────────────────── #
    columns: list[dict[str, Any]] = []
    for col_name, dtype in zip(df.columns, df.dtypes):
        col_def: dict[str, Any] = {
            "itemOID": f"IT.{dom}.{col_name}",
            "name": col_name,
            "label": col_name,
            "dataType": _dtype_to_dsj_type(dtype),
        }
        if col_def["dataType"] == "string":
            max_len = df[col_name].cast(pl.String).str.len_chars().max()
            col_def["length"] = int(max_len) if max_len is not None and max_len > 0 else 200
        columns.append(col_def)

    # ── Row data ────────────────────────────────────────────────────── #
    rows: list[list[Any]] = [[_serialize_value(v) for v in row] for row in df.iter_rows()]

    # ── Assemble payload ────────────────────────────────────────────── #
    from fleet._version import __version__

    payload: dict[str, Any] = {
        "datasetJSONCreationDateTime": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        "datasetJSONVersion": "1.1.0",
        "fileOID": foid,
        "originator": originator,
        "sourceSystem": {"name": originator, "version": __version__},
        "itemGroupOID": f"IG.{dom}",
        "records": len(df),
        "name": dom,
        "label": lbl,
        "columns": columns,
        "rows": rows,
    }

    path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


# ────────────────────────────────────────────────────────────────────── #
# Reader                                                                  #
# ────────────────────────────────────────────────────────────────────── #

_DSJ_TO_PL: dict[str, pl.DataType] = {
    "string": pl.String,
    "integer": pl.Int64,
    "float": pl.Float32,
    "double": pl.Float64,
    "boolean": pl.Boolean,
    "date": pl.String,  # kept as ISO string; caller can cast
    "time": pl.String,
    "datetime": pl.String,
}


def read_dataset_json(path: str | Path) -> pl.DataFrame:
    """Read a CDISC Dataset-JSON v1.1 file into a Polars DataFrame.

    Args:
        path: Path to the ``.json`` file.

    Returns:
        pl.DataFrame with columns typed according to the Dataset-JSON
        ``dataType`` field (dates remain as ISO strings).

    Examples:
        Round-trip a dataset::

            from fleet.io import save_dataset_json, read_dataset_json

            save_dataset_json(dm, "dm.json", domain="DM")
            dm_back = read_dataset_json("dm.json")
    """
    path = Path(path)
    raw = _json.loads(path.read_text(encoding="utf-8"))

    col_names = [c["name"] for c in raw["columns"]]
    col_types = [_DSJ_TO_PL.get(c.get("dataType", "string"), pl.String) for c in raw["columns"]]

    rows: list[list[Any]] = raw.get("rows", [])

    schema = {name: dtype for name, dtype in zip(col_names, col_types)}
    if not rows:
        return pl.DataFrame(schema=schema)

    # Transpose row-oriented data to column-oriented
    data: dict[str, list[Any]] = {name: [] for name in col_names}
    for row in rows:
        for i, name in enumerate(col_names):
            data[name].append(row[i] if i < len(row) else None)

    return pl.DataFrame(data, schema=schema)
