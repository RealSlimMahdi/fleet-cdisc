"""Tests for fleet.io.dataset_json — round-trip, schema, and dsjson oracle."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from fleet.core.define_spec import DefineSpec
from fleet.core.exceptions import IOError as FleetIOError
from fleet.core.oids import item_oid
from fleet.io.dataset_json import (
    DATASET_JSON_SCHEMA_PATH,
    get_dataset_json_schema,
    metadata_from_define,
    read_dataset_json,
    save_dataset_json,
)

# ────────────────────────────────────────────────────────────────────── #
# Fixtures                                                                #
# ────────────────────────────────────────────────────────────────────── #


@pytest.fixture
def sample_df() -> pl.DataFrame:
    return pl.from_repr("""\
┌─────────┬─────────┬─────┬─────┬────────┬───────┐
│ STUDYID ┆ USUBJID ┆ SEX ┆ AGE ┆ WEIGHT ┆ SAFFL │
│ ---     ┆ ---     ┆ --- ┆ --- ┆ ---    ┆ ---   │
│ str     ┆ str     ┆ str ┆ i64 ┆ f64    ┆ str   │
╞═════════╪═════════╪═════╪═════╪════════╪═══════╡
│ STUDY01 ┆ 01-001  ┆ M   ┆ 45  ┆ 80.5   ┆ Y     │
│ STUDY01 ┆ 01-002  ┆ F   ┆ 32  ┆ 65.2   ┆ Y     │
│ STUDY01 ┆ 01-003  ┆ M   ┆ 67  ┆ 92.0   ┆ N     │
└─────────┴─────────┴─────┴─────┴────────┴───────┘
""")


@pytest.fixture
def mixed_dtype_df() -> pl.DataFrame:
    return pl.from_repr("""\
┌─────────┬─────────┬───────────┬──────────┐
│ STR_COL ┆ INT_COL ┆ FLOAT_COL ┆ BOOL_COL │
│ ---     ┆ ---     ┆ ---       ┆ ---      │
│ str     ┆ i64     ┆ f64       ┆ bool     │
╞═════════╪═════════╪═══════════╪══════════╡
│ a       ┆ 1       ┆ 1.1       ┆ true     │
│ b       ┆ 2       ┆ 2.2       ┆ false    │
│ null    ┆ 3       ┆ 3.3       ┆ true     │
└─────────┴─────────┴───────────┴──────────┘
""")


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


def test_column_item_oid_is_the_define_item_oid(sample_df: pl.DataFrame, tmp_path: Path) -> None:
    """c1-576: itemOID equals the ItemDef OID of the Define-XML."""
    out = tmp_path / "dm.json"
    save_dataset_json(sample_df, out, domain="DM")
    payload = json.loads(out.read_text())

    oids = {c["name"]: c["itemOID"] for c in payload["columns"]}
    assert oids["STUDYID"] == "IT.DM.STUDYID"
    assert oids["WEIGHT"] == "IT.DM.WEIGHT"
    assert all(oid == item_oid("DM", name) for name, oid in oids.items())


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
    df = pl.from_repr("""\
┌─────┐
│ X   │
│ --- │
│ i64 │
╞═════╡
│ 1   │
└─────┘
""")
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


# ────────────────────────────────────────────────────────────────────── #
# Define metadata (c1-576)                                                #
# ────────────────────────────────────────────────────────────────────── #


def _schema_errors(payload: dict) -> list[str]:
    from jsonschema import Draft201909Validator

    validator = Draft201909Validator(get_dataset_json_schema())
    return [e.message for e in validator.iter_errors(payload)]


_DM = pl.from_repr("""\
┌──────────────┬─────────┬─────────┐
│ STUDYID      ┆ USUBJID ┆ ARMNRS  │
│ ---          ┆ ---     ┆ ---     │
│ str          ┆ str     ┆ str     │
╞══════════════╪═════════╪═════════╡
│ CDISCPILOT01 ┆ 01-001  ┆ null    │
└──────────────┴─────────┴─────────┘
""")


def test_columns_give_the_define_labels_lengths_keys_and_oids(tmp_path: Path) -> None:
    out = save_dataset_json(
        _DM,
        tmp_path / "dm.json",
        domain="DM",
        label="Demographics",
        columns={
            "STUDYID": {"label": "Study Identifier", "length": 12, "keySequence": 1},
            "USUBJID": {"label": "Unique Subject Identifier", "keySequence": 2},
        },
        study_oid="STDY.CDISCPILOT01",
        metadata_version_oid="MDV.CDISCPILOT01.1.SDTMIG.3.4",
    )
    payload = json.loads(out.read_text())
    cols = {c["name"]: c for c in payload["columns"]}

    assert payload["label"] == "Demographics"
    assert payload["studyOID"] == "STDY.CDISCPILOT01"
    assert payload["metaDataVersionOID"] == "MDV.CDISCPILOT01.1.SDTMIG.3.4"
    assert cols["STUDYID"]["label"] == "Study Identifier"
    assert cols["STUDYID"]["length"] == 12
    assert cols["USUBJID"]["keySequence"] == 2
    assert cols["ARMNRS"]["label"] == "ARMNRS"
    assert "length" not in cols["ARMNRS"], "an all-null column has no length to report"
    assert not _schema_errors(payload)


def test_an_unknown_column_key_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FleetIOError, match="unknown column key"):
        save_dataset_json(_DM, tmp_path / "dm.json", domain="DM", columns={"STUDYID": {"lbl": "x"}})


def test_metadata_from_define_matches_the_define_xml_oids() -> None:
    spec = DefineSpec.model_validate(
        {
            "study": {"id": "CDISCPILOT01", "standard": "SDTMIG", "standard_version": "3.4"},
            "datasets": [
                {
                    "name": "DM",
                    "label": "Demographics",
                    "keys": ["STUDYID", "USUBJID"],
                    "variables": [
                        {"name": "STUDYID", "label": "Study Identifier", "length": 12},
                        {"name": "USUBJID", "label": "Unique Subject Identifier"},
                    ],
                }
            ],
        }
    )

    meta = metadata_from_define(spec, "DM")

    assert meta == {
        "label": "Demographics",
        "columns": {
            "STUDYID": {"label": "Study Identifier", "length": 12, "keySequence": 1},
            "USUBJID": {"label": "Unique Subject Identifier", "keySequence": 2},
        },
        "study_oid": "STDY.CDISCPILOT01",
        "metadata_version_oid": "MDV.CDISCPILOT01.1.SDTMIG.3.4",
    }


def test_to_dataset_json_after_from_spec_writes_the_define_labels(tmp_path: Path) -> None:
    spec = tmp_path / "define.yaml"
    spec.write_text(
        """\
study: {id: S1, standard: SDTMIG, standard_version: "3.4"}
datasets:
  - name: DM
    label: Demographics
    variables:
      - name: STUDYID
        label: Study Identifier
        derivation: {algorithm: assign, value: S1}
""",
        encoding="utf-8",
    )
    raw = pl.from_repr("""\
┌────────────┐
│ subject_id │
│ ---        │
│ str        │
╞════════════╡
│ 001        │
└────────────┘
""")

    out = raw.sdtm.from_spec(spec, dataset="DM").to_dataset_json(tmp_path / "dm.json", domain="DM")
    payload = json.loads(out.read_text())

    assert payload["label"] == "Demographics"
    assert payload["studyOID"] == "STDY.S1"
    assert {c["name"]: c["label"] for c in payload["columns"]}["STUDYID"] == "Study Identifier"


# ────────────────────────────────────────────────────────────────────── #
# Types: numeric dates, floats, decimals, integers (c1-577, c1-579, c2-943) #
# ────────────────────────────────────────────────────────────────────── #


def test_a_numeric_adam_date_round_trips_as_a_date(tmp_path: Path) -> None:
    adsl = pl.from_repr("""\
┌─────────┬────────────┬─────────────────────┐
│ USUBJID ┆ TRTSDT     ┆ TRTSDTM             │
│ ---     ┆ ---        ┆ ---                 │
│ str     ┆ date       ┆ datetime[μs]        │
╞═════════╪════════════╪═════════════════════╡
│ S1      ┆ 2024-01-15 ┆ 2024-01-15 08:30:00 │
│ S2      ┆ null       ┆ null                │
└─────────┴────────────┴─────────────────────┘
""").with_columns(TRTSTM=pl.col("TRTSDTM").dt.time())
    out = save_dataset_json(adsl, tmp_path / "adsl.json", domain="ADSL")
    payload = json.loads(out.read_text())
    cols = {c["name"]: c for c in payload["columns"]}

    assert (cols["TRTSDT"]["targetDataType"], cols["TRTSDT"]["displayFormat"]) == (
        "integer",
        "DATE9.",
    )
    assert cols["TRTSDTM"]["displayFormat"] == "DATETIME20."
    assert cols["TRTSTM"]["displayFormat"] == "TIME8."
    assert not _schema_errors(payload)
    back = read_dataset_json(out)
    assert back.schema == adsl.schema
    assert back.equals(adsl)


def test_an_sdtm_dtc_text_column_stays_text(tmp_path: Path) -> None:
    ae = pl.from_repr("""\
┌─────────┬──────────┐
│ USUBJID ┆ AESTDTC  │
│ ---     ┆ ---      │
│ str     ┆ str      │
╞═════════╪══════════╡
│ S1      ┆ 2024-01  │
└─────────┴──────────┘
""")
    out = save_dataset_json(ae, tmp_path / "ae.json", domain="AE")

    assert "targetDataType" not in json.loads(out.read_text())["columns"][1]
    assert read_dataset_json(out)["AESTDTC"].to_list() == ["2024-01"]


def _write_raw(path: Path, columns: list[dict], rows: list[list]) -> Path:
    path.write_text(json.dumps({"columns": columns, "rows": rows}), encoding="utf-8")
    return path


def test_a_partial_date_in_a_numeric_date_column_stops(tmp_path: Path) -> None:
    path = _write_raw(
        tmp_path / "adsl.json",
        [{"name": "TRTSDT", "dataType": "date", "targetDataType": "integer"}],
        [["2024-01"]],
    )

    with pytest.raises(FleetIOError, match="adsl.json, column TRTSDT"):
        read_dataset_json(path)


def test_float_reads_as_a_double_and_decimal_as_a_number(tmp_path: Path) -> None:
    path = _write_raw(
        tmp_path / "adlbc.json",
        [
            {"name": "VSSTRESN", "dataType": "float"},
            {"name": "AVAL", "dataType": "decimal", "targetDataType": "decimal"},
        ],
        [[181.61, "99.18"], [6.1, "1860.0"], [None, ""]],
    )

    out = read_dataset_json(path)

    assert out.schema == pl.Schema({"VSSTRESN": pl.Float64, "AVAL": pl.Float64})
    assert out["VSSTRESN"].to_list() == [181.61, 6.1, None]
    assert out["AVAL"].to_list() == [99.18, 1860.0, None]
    assert out["AVAL"].max() == 1860.0


def test_a_decimal_that_is_not_a_number_stops(tmp_path: Path) -> None:
    path = _write_raw(
        tmp_path / "adlbc.json",
        [{"name": "AVAL", "dataType": "decimal", "targetDataType": "decimal"}],
        [["<0.5"]],
    )

    with pytest.raises(FleetIOError, match="column AVAL"):
        read_dataset_json(path)


def test_an_integer_written_as_63_0_reads_as_an_integer(tmp_path: Path) -> None:
    path = _write_raw(
        tmp_path / "adsl.json", [{"name": "AGE", "dataType": "integer"}], [[63.0], [2.0]]
    )

    out = read_dataset_json(path)

    assert out.schema == pl.Schema({"AGE": pl.Int64})
    assert out["AGE"].to_list() == [63, 2]


def test_a_fraction_in_an_integer_column_names_file_column_row_and_value(tmp_path: Path) -> None:
    path = _write_raw(
        tmp_path / "adsl.json", [{"name": "AGE", "dataType": "integer"}], [[63], [2.5]]
    )

    with pytest.raises(FleetIOError, match=r"adsl\.json, column AGE, row 2: 2\.5"):
        read_dataset_json(path)


# ────────────────────────────────────────────────────────────────────── #
# Values JSON cannot hold (c1-578)                                        #
# ────────────────────────────────────────────────────────────────────── #


def test_nan_and_infinity_are_written_as_null_with_a_warning(tmp_path: Path) -> None:
    adlb = pl.from_repr("""\
┌─────────┬──────┬──────┐
│ USUBJID ┆ AVAL ┆ BASE │
│ ---     ┆ ---  ┆ ---  │
│ str     ┆ f64  ┆ f64  │
╞═════════╪══════╪══════╡
│ 1       ┆ 5.0  ┆ 0.0  │
│ 2       ┆ 0.0  ┆ 0.0  │
│ 3       ┆ 15.0 ┆ 10.0 │
└─────────┴──────┴──────┘
""").with_columns(R2BASE=pl.col("AVAL") / pl.col("BASE"))

    with pytest.warns(UserWarning, match=r"R2BASE \(2\)"):
        out = save_dataset_json(adlb, tmp_path / "adlb.json", domain="ADLB")

    text = out.read_text()
    payload = json.loads(text, parse_constant=lambda token: pytest.fail(f"bare {token}"))
    assert [row[3] for row in payload["rows"]] == [None, None, 1.5]


def test_a_duration_column_is_refused(tmp_path: Path) -> None:
    df = pl.DataFrame({"ADURN": pl.Series([1], dtype=pl.Duration("us"))})

    with pytest.raises(FleetIOError, match="ADURN hold"):
        save_dataset_json(df, tmp_path / "adae.json", domain="ADAE")
