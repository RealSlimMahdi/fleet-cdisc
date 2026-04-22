"""Tests for fleet.io.dataset_json — round-trip, schema, and dsjson oracle."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from fleet.io.dataset_json import (
    DATASET_JSON_SCHEMA_PATH,
    get_dataset_json_schema,
    read_dataset_json,
    save_dataset_json,
)

# ────────────────────────────────────────────────────────────────────── #
# Fixtures                                                                #
# ────────────────────────────────────────────────────────────────────── #


@pytest.fixture
def sample_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "STUDYID": ["STUDY01", "STUDY01", "STUDY01"],
            "USUBJID": ["01-001", "01-002", "01-003"],
            "SEX": ["M", "F", "M"],
            "AGE": [45, 32, 67],
            "WEIGHT": [80.5, 65.2, 92.0],
            "SAFFL": ["Y", "Y", "N"],
        }
    )


@pytest.fixture
def mixed_dtype_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "STR_COL": ["a", "b", None],
            "INT_COL": [1, 2, 3],
            "FLOAT_COL": [1.1, 2.2, 3.3],
            "BOOL_COL": [True, False, True],
        }
    )


# ────────────────────────────────────────────────────────────────────── #
# Round-trip tests                                                        #
# ────────────────────────────────────────────────────────────────────── #


def test_round_trip_preserves_schema(sample_df: pl.DataFrame, tmp_path: Path) -> None:
    out = tmp_path / "dm.json"
    save_dataset_json(sample_df, out, domain="DM")
    result = read_dataset_json(out)

    assert result.columns == sample_df.columns
    assert result.shape == sample_df.shape


def test_round_trip_preserves_string_values(sample_df: pl.DataFrame, tmp_path: Path) -> None:
    out = tmp_path / "dm.json"
    save_dataset_json(sample_df, out, domain="DM")
    result = read_dataset_json(out)

    assert result["USUBJID"].to_list() == sample_df["USUBJID"].to_list()
    assert result["SEX"].to_list() == sample_df["SEX"].to_list()


def test_round_trip_preserves_numeric_values(sample_df: pl.DataFrame, tmp_path: Path) -> None:
    out = tmp_path / "dm.json"
    save_dataset_json(sample_df, out, domain="DM")
    result = read_dataset_json(out)

    assert result["AGE"].to_list() == sample_df["AGE"].to_list()
    assert result["WEIGHT"].to_list() == sample_df["WEIGHT"].to_list()


def test_round_trip_with_nulls(mixed_dtype_df: pl.DataFrame, tmp_path: Path) -> None:
    out = tmp_path / "test.json"
    save_dataset_json(mixed_dtype_df, out, domain="TEST")
    result = read_dataset_json(out)

    assert result["STR_COL"].to_list() == mixed_dtype_df["STR_COL"].to_list()


def test_empty_dataframe(tmp_path: Path) -> None:
    df = pl.DataFrame({"A": pl.Series([], dtype=pl.String), "B": pl.Series([], dtype=pl.Int64)})
    out = tmp_path / "empty.json"
    save_dataset_json(df, out, domain="EMPTY")
    result = read_dataset_json(out)

    assert result.shape == (0, 2)
    assert result.columns == ["A", "B"]


# ────────────────────────────────────────────────────────────────────── #
# Dataset-JSON v1.1 field validation                                      #
# ────────────────────────────────────────────────────────────────────── #


def test_required_keys_present(sample_df: pl.DataFrame, tmp_path: Path) -> None:
    out = tmp_path / "dm.json"
    save_dataset_json(sample_df, out, domain="DM")
    payload = json.loads(out.read_text())

    required = {
        "datasetJSONCreationDateTime",
        "datasetJSONVersion",
        "fileOID",
        "originator",
        "sourceSystem",
        "itemGroupOID",
        "records",
        "name",
        "label",
        "columns",
        "rows",
    }
    assert required.issubset(payload.keys())
    assert "isReferenceData" not in payload, "isReferenceData is not part of Dataset-JSON v1.1"


def test_version_is_1_1_0(sample_df: pl.DataFrame, tmp_path: Path) -> None:
    out = tmp_path / "dm.json"
    save_dataset_json(sample_df, out, domain="DM")
    payload = json.loads(out.read_text())

    assert payload["datasetJSONVersion"] == "1.1.0"


def test_records_count_matches(sample_df: pl.DataFrame, tmp_path: Path) -> None:
    out = tmp_path / "dm.json"
    save_dataset_json(sample_df, out, domain="DM")
    payload = json.loads(out.read_text())

    assert payload["records"] == len(sample_df)
    assert len(payload["rows"]) == len(sample_df)


def test_column_item_oid_prefix(sample_df: pl.DataFrame, tmp_path: Path) -> None:
    out = tmp_path / "dm.json"
    save_dataset_json(sample_df, out, domain="DM")
    payload = json.loads(out.read_text())

    for col in payload["columns"]:
        assert col["itemOID"].startswith("IT.DM.")


def test_string_columns_have_length(sample_df: pl.DataFrame, tmp_path: Path) -> None:
    out = tmp_path / "dm.json"
    save_dataset_json(sample_df, out, domain="DM")
    payload = json.loads(out.read_text())

    string_cols = [c for c in payload["columns"] if c["dataType"] == "string"]
    for col in string_cols:
        assert "length" in col
        assert isinstance(col["length"], int)
        assert col["length"] > 0


def test_domain_uppercased(tmp_path: Path) -> None:
    df = pl.DataFrame({"X": [1]})
    out = tmp_path / "test.json"
    save_dataset_json(df, out, domain="dm")
    payload = json.loads(out.read_text())

    assert payload["name"] == "DM"
    assert payload["itemGroupOID"] == "IG.DM"


def test_custom_label_and_originator(sample_df: pl.DataFrame, tmp_path: Path) -> None:
    out = tmp_path / "dm.json"
    save_dataset_json(
        sample_df,
        out,
        domain="DM",
        label="Demographics",
        originator="ACME Pharma",
        file_oid="F.DM.001",
    )
    payload = json.loads(out.read_text())

    assert payload["label"] == "Demographics"
    assert payload["originator"] == "ACME Pharma"
    assert payload["fileOID"] == "F.DM.001"


def test_returns_path(sample_df: pl.DataFrame, tmp_path: Path) -> None:
    out = tmp_path / "dm.json"
    result = save_dataset_json(sample_df, out, domain="DM")

    assert isinstance(result, Path)
    assert result == out
    assert result.exists()


def test_creates_parent_dirs(sample_df: pl.DataFrame, tmp_path: Path) -> None:
    out = tmp_path / "nested" / "deep" / "dm.json"
    save_dataset_json(sample_df, out, domain="DM")

    assert out.exists()


# ────────────────────────────────────────────────────────────────────── #
# dsjson oracle cross-validation                                          #
# ────────────────────────────────────────────────────────────────────── #


def _has_dsjson() -> bool:
    try:
        import dsjson  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _has_dsjson(), reason="dsjson not installed")
def test_dsjson_can_read_our_output(sample_df: pl.DataFrame, tmp_path: Path) -> None:
    """Verify our Dataset-JSON is parseable by the dsjson reference library."""
    from dsjson import read_dataset_json as dsjson_read

    out = tmp_path / "dm.json"
    save_dataset_json(sample_df, out, domain="DM", label="Demographics")

    # dsjson returns a pandas DataFrame with metadata in .attrs
    pd_df = dsjson_read(str(out))

    assert list(pd_df.columns) == sample_df.columns
    assert len(pd_df) == len(sample_df)
    assert pd_df.attrs.get("datasetJSONVersion") == "1.1.0"
    assert pd_df.attrs.get("name") == "DM"


# ────────────────────────────────────────────────────────────────────── #
# Official CDISC v1.1 JSON-Schema validation                             #
# ────────────────────────────────────────────────────────────────────── #


def _has_jsonschema() -> bool:
    try:
        import jsonschema  # noqa: F401

        return True
    except ImportError:
        return False


def test_vendored_schema_exists() -> None:
    """The CDISC Dataset-JSON v1.1 schema must be vendored in the package."""
    assert DATASET_JSON_SCHEMA_PATH.exists(), f"Missing schema: {DATASET_JSON_SCHEMA_PATH}"
    schema = get_dataset_json_schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2019-09/schema"
    assert "datasetJSONVersion" in schema.get("required", [])


@pytest.mark.skipif(not _has_jsonschema(), reason="jsonschema not installed")
def test_cdisc_schema_validation_basic(sample_df: pl.DataFrame, tmp_path: Path) -> None:
    """Validate output against the official CDISC Dataset-JSON v1.1 schema."""
    from jsonschema import Draft201909Validator

    out = tmp_path / "dm.json"
    save_dataset_json(sample_df, out, domain="DM", label="Demographics")
    payload = json.loads(out.read_text())
    schema = get_dataset_json_schema()

    validator = Draft201909Validator(schema)
    errors = list(validator.iter_errors(payload))
    msgs = [f"{'.'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}" for e in errors]
    assert not errors, "Dataset-JSON v1.1 schema violations:\n" + "\n".join(msgs)


@pytest.mark.skipif(not _has_jsonschema(), reason="jsonschema not installed")
def test_cdisc_schema_validation_with_nulls(mixed_dtype_df: pl.DataFrame, tmp_path: Path) -> None:
    """Schema validation with null values in the data."""
    from jsonschema import Draft201909Validator

    out = tmp_path / "test.json"
    save_dataset_json(mixed_dtype_df, out, domain="TEST", label="Test Dataset")
    payload = json.loads(out.read_text())
    schema = get_dataset_json_schema()

    validator = Draft201909Validator(schema)
    errors = list(validator.iter_errors(payload))
    msgs = [f"{'.'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}" for e in errors]
    assert not errors, "Dataset-JSON v1.1 schema violations:\n" + "\n".join(msgs)


@pytest.mark.skipif(not _has_jsonschema(), reason="jsonschema not installed")
def test_cdisc_schema_validation_empty(tmp_path: Path) -> None:
    """Schema validation on an empty DataFrame."""
    from jsonschema import Draft201909Validator

    df = pl.DataFrame({"A": pl.Series([], dtype=pl.String)})
    out = tmp_path / "empty.json"
    save_dataset_json(df, out, domain="EMPTY", label="Empty")
    payload = json.loads(out.read_text())
    schema = get_dataset_json_schema()

    validator = Draft201909Validator(schema)
    errors = list(validator.iter_errors(payload))
    msgs = [f"{'.'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}" for e in errors]
    assert not errors, "Dataset-JSON v1.1 schema violations:\n" + "\n".join(msgs)


def test_source_system_has_version(sample_df: pl.DataFrame, tmp_path: Path) -> None:
    """sourceSystem must include both name and version per v1.1 spec."""
    out = tmp_path / "dm.json"
    save_dataset_json(sample_df, out, domain="DM")
    payload = json.loads(out.read_text())

    ss = payload["sourceSystem"]
    assert "name" in ss
    assert "version" in ss
    assert isinstance(ss["version"], str)
    assert len(ss["version"]) > 0
