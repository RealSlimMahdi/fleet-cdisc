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
import warnings
from collections.abc import Mapping
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

from fleet.core import oids
from fleet.core.exceptions import IOError as FleetIOError
from fleet.core.oids import item_oid

if TYPE_CHECKING:
    from fleet.core.define_spec import DefineSpec

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
    if isinstance(dtype, pl.Datetime):
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


#: The keys a ``columns=`` entry may set, as Dataset-JSON 1.1 names them.
_COLUMN_KEYS = ("label", "targetDataType", "length", "displayFormat", "keySequence")


def _temporal_format(dtype: pl.DataType) -> str | None:
    """The SAS display format of a numeric date, datetime or time column."""
    if dtype == pl.Date:
        return "DATE9."
    if isinstance(dtype, pl.Datetime):
        return "DATETIME20."
    if dtype == pl.Time:
        return "TIME8."
    return None


def _column_def(
    df: pl.DataFrame, dom: str, name: str, dtype: pl.DataType, meta: Mapping[str, Any]
) -> dict[str, Any]:
    """The ``columns`` entry of *name*: define metadata first, then what the data shows."""
    unknown = sorted(set(meta) - set(_COLUMN_KEYS))
    if unknown:
        raise FleetIOError(
            f"{dom}.{name}: unknown column key(s) {', '.join(unknown)}; "
            f"use {', '.join(_COLUMN_KEYS)}."
        )
    col: dict[str, Any] = {
        "itemOID": item_oid(dom, name),
        "name": name,
        "label": meta.get("label") or name,
        "dataType": _dtype_to_dsj_type(dtype),
    }
    fmt = _temporal_format(dtype)
    if fmt:
        # Dataset-JSON 1.1: a numeric date is ISO text in the file, integer in SAS.
        col["targetDataType"] = "integer"
        col["displayFormat"] = fmt
    if col["dataType"] == "string":
        longest = df[name].cast(pl.String).str.len_chars().max()
        if longest:
            col["length"] = int(longest)  # type: ignore[arg-type]
    col.update({key: meta[key] for key in _COLUMN_KEYS[1:] if meta.get(key) is not None})
    return col


def _finite(df: pl.DataFrame, dom: str) -> pl.DataFrame:
    """*df* with NaN and infinity as null, with one warning that names the columns."""
    floats = [c for c, dtype in df.schema.items() if dtype.is_float()]
    counts = {c: int((~df[c].is_finite()).sum()) for c in floats}
    bad = {c: n for c, n in counts.items() if n}
    if not bad:
        return df
    named = ", ".join(f"{c} ({n})" for c, n in bad.items())
    warnings.warn(
        f"{dom}: {named} hold(s) NaN or infinity, written as null (JSON has no such "
        "number). Check the derivation for a division by zero.",
        stacklevel=3,
    )
    return df.with_columns(pl.when(pl.col(c).is_finite()).then(pl.col(c)).alias(c) for c in bad)


def save_dataset_json(
    df: pl.DataFrame,
    path: str | Path,
    *,
    domain: str,
    label: str | None = None,
    originator: str = "Fleet",
    file_oid: str | None = None,
    columns: Mapping[str, Mapping[str, Any]] | None = None,
    study_oid: str | None = None,
    metadata_version_oid: str | None = None,
) -> Path:
    """Write a Polars DataFrame as a CDISC Dataset-JSON v1.1 file.

    Each ``itemOID`` is the ItemDef OID of the Define-XML
    (:func:`fleet.core.oids.item_oid`).  A ``pl.Date``, ``pl.Datetime`` or
    ``pl.Time`` column is ISO text with ``targetDataType: integer`` and a
    SAS display format, so :func:`read_dataset_json` gives the date back.
    NaN and infinity are written as null with a warning, because JSON has
    no such number (RFC 8259).  A string column with no value gets no
    ``length``.

    Args:
        df: The DataFrame to serialize.
        path: Destination file path (should end in ``.json``).
        domain: Dataset / domain name (e.g. ``"DM"``, ``"ADSL"``).
            Used for ``name``, ``itemGroupOID``, and column ``itemOID``.
        label: Human-readable dataset label.  Defaults to
            ``"<domain> dataset"`` if omitted.
        originator: Organisation that created the file.
        file_oid: Unique file identifier.  Defaults to the file stem.
        columns: Define metadata by column name.  Each entry may hold
            ``label``, ``targetDataType``, ``length``, ``displayFormat``
            and ``keySequence``; a given value wins over the one Fleet
            derives from the data.  :func:`metadata_from_define` builds
            these from a define.yaml.
        study_oid: The Study OID of the Define-XML.
        metadata_version_oid: The MetaDataVersion OID of the Define-XML.

    Returns:
        Path to the written file.

    Raises:
        FleetIOError: When a column holds a duration, or a ``columns``
            entry holds an unknown key.

    Examples:
        Export an SDTM DM dataset with its define labels::

            from fleet.io import save_dataset_json

            dm = raw_df.sdtm.assign("DOMAIN", value="DM").to_frame()
            save_dataset_json(
                dm,
                "outputs/dm.json",
                domain="DM",
                label="Demographics",
                columns={"STUDYID": {"label": "Study Identifier", "keySequence": 1}},
            )
    """
    path = Path(path)
    dom = domain.upper()
    durations = [c for c, dtype in df.schema.items() if isinstance(dtype, pl.Duration)]
    if durations:
        raise FleetIOError(
            f"{dom}: {', '.join(durations)} hold(s) a duration, which Dataset-JSON has no "
            "type for. Convert it to a number in the unit you need, for example days."
        )
    path.parent.mkdir(parents=True, exist_ok=True)

    lbl = label or f"{dom} dataset"
    foid = file_oid or path.stem
    meta = columns or {}

    col_defs = [_column_def(df, dom, n, t, meta.get(n, {})) for n, t in df.schema.items()]
    rows: list[list[Any]] = [
        [_serialize_value(v) for v in row] for row in _finite(df, dom).iter_rows()
    ]

    from fleet._version import __version__

    payload: dict[str, Any] = {
        "datasetJSONCreationDateTime": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S"),
        "datasetJSONVersion": "1.1.0",
        "fileOID": foid,
        "originator": originator,
        "sourceSystem": {"name": originator, "version": __version__},
    }
    if study_oid:
        payload["studyOID"] = study_oid
    if metadata_version_oid:
        payload["metaDataVersionOID"] = metadata_version_oid
    payload |= {
        "itemGroupOID": f"IG.{dom}",
        "records": len(df),
        "name": dom,
        "label": lbl,
        "columns": col_defs,
        "rows": rows,
    }

    path.write_text(_json.dumps(payload, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return path


def metadata_from_define(spec: DefineSpec, dataset: str) -> dict[str, Any]:
    """Return the :func:`save_dataset_json` keywords that a define.yaml gives *dataset*.

    Args:
        spec: The loaded define.yaml.
        dataset: The dataset name, for example ``"DM"``.

    Returns:
        dict: ``label``, ``columns``, ``study_oid`` and
            ``metadata_version_oid``; a value the define lacks is left out.

    Examples:
        Write DM with the labels and OIDs of its define::

            from fleet.core.define_spec import load_define_spec
            from fleet.io import save_dataset_json
            from fleet.io.dataset_json import metadata_from_define

            spec = load_define_spec("sdtm/define.yaml")
            dm = raw_df.sdtm.from_spec("sdtm/define.yaml", dataset="DM").to_frame()
            save_dataset_json(dm, "dm.json", domain="DM", **metadata_from_define(spec, "DM"))
    """
    entry = spec.select(dataset)
    keys = entry.keys if isinstance(entry.keys, list) else []
    columns: dict[str, dict[str, Any]] = {}
    for var in entry.variables:
        extra = var.model_extra or {}
        col = {"label": var.label, "length": extra.get("length")}
        if var.name in keys:
            col["keySequence"] = keys.index(var.name) + 1
        columns[var.name] = {k: v for k, v in col.items() if v is not None}
    out: dict[str, Any] = {"columns": columns}
    if entry.label:
        out["label"] = entry.label
    study = spec.study
    if study.get("id"):
        out["study_oid"] = oids.study_oid(study["id"])
        if study.get("standard") and study.get("standard_version"):
            out["metadata_version_oid"] = oids.metadata_version_oid(
                study["id"], study["standard"], str(study["standard_version"])
            )
    return out


# ────────────────────────────────────────────────────────────────────── #
# Reader                                                                  #
# ────────────────────────────────────────────────────────────────────── #

_DSJ_TO_PL: dict[str, pl.DataType] = {
    "string": pl.String,
    "integer": pl.Int64,
    "float": pl.Float64,  # SAS holds doubles; Float32 changes 181.61
    "double": pl.Float64,
    "decimal": pl.Float64,
    "boolean": pl.Boolean,
}

#: ISO text of a numeric date (``targetDataType: integer``) and how to parse it.
_TEMPORAL_PARSE = {
    "date": lambda s: s.str.to_date("%Y-%m-%d"),
    "datetime": lambda s: s.str.to_datetime(time_unit="us"),
    "time": lambda s: s.str.to_time("%H:%M:%S%.f"),
}


def _int_cell(value: Any, where: str, row: int) -> int | None:
    """An integer cell: ``63.0`` is 63 (the schema allows it); ``2.5`` stops."""
    if value is None or isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise FleetIOError(f"{where}, row {row}: {value!r} is not an integer.")


def _read_column(name: str, meta: Mapping[str, Any], values: list[Any], source: Path) -> pl.Series:
    """One column, typed from its ``dataType`` and ``targetDataType``."""
    where = f"{source.name}, column {name}"
    data_type = meta.get("dataType", "string")
    target = meta.get("targetDataType")
    if data_type == "integer":
        return pl.Series(name, [_int_cell(v, where, i) for i, v in enumerate(values, 1)], pl.Int64)
    if data_type in _TEMPORAL_PARSE and target == "integer":
        text = pl.Series(name, values, pl.String)
        try:
            return _TEMPORAL_PARSE[data_type](text)
        except (pl.exceptions.InvalidOperationError, pl.exceptions.ComputeError) as exc:
            raise FleetIOError(f"{where}: a value is not a full ISO {data_type}: {exc}") from exc
    if data_type == "decimal" or target == "decimal":
        text = pl.Series(name, [None if v is None else str(v) for v in values], pl.String)
        try:
            return text.replace("", None).cast(pl.Float64, strict=True)
        except pl.exceptions.InvalidOperationError as exc:
            raise FleetIOError(f"{where}: a value is not a decimal number: {exc}") from exc
    return pl.Series(name, values, _DSJ_TO_PL.get(data_type, pl.String))


def read_dataset_json(path: str | Path) -> pl.DataFrame:
    """Read a CDISC Dataset-JSON v1.1 file into a Polars DataFrame.

    ``float`` and ``double`` read as ``pl.Float64``, as SAS holds them.  A
    ``decimal`` column (text in the file) reads as ``pl.Float64``; an
    empty value is null.  A date, datetime or time column with
    ``targetDataType: integer`` (a numeric ADaM date) reads as
    ``pl.Date``, ``pl.Datetime`` or ``pl.Time``; without it, as ISO text
    (an SDTM ``--DTC``).  An integer column accepts ``63.0``.

    Args:
        path: Path to the ``.json`` file.

    Returns:
        pl.DataFrame with columns typed according to the Dataset-JSON
        ``dataType`` and ``targetDataType`` fields.

    Raises:
        FleetIOError: When a value does not fit its column type, for
            example ``2.5`` in an integer column or a partial date in a
            numeric date column.

    Examples:
        Round-trip a dataset::

            from fleet.io import save_dataset_json, read_dataset_json

            save_dataset_json(dm, "dm.json", domain="DM")
            dm_back = read_dataset_json("dm.json")
    """
    path = Path(path)
    raw = _json.loads(path.read_text(encoding="utf-8"))
    rows: list[list[Any]] = raw.get("rows", [])
    return pl.DataFrame(
        [
            _read_column(col["name"], col, [row[i] if i < len(row) else None for row in rows], path)
            for i, col in enumerate(raw["columns"])
        ]
    )
