"""DatasetChecker: one clean frame and one failing frame per check (c1-847)."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
import yaml

from fleet.define_xml import CheckResult, DatasetChecker, TypeMismatch
from fleet.define_xml.checker import _classify

_SPEC = {
    "study": {"id": "S01", "standard": "SDTMIG", "standard_version": "3.4"},
    "codelists": [
        {
            "oid": "C66731",
            "name": "Sex",
            "type": "text",
            "items": [
                {"coded_value": "F", "decode": "Female"},
                {"coded_value": "M", "decode": "Male"},
            ],
        },
        {"oid": "C66790", "name": "Ethnic Group", "type": "text"},
    ],
    "datasets": [
        {
            "name": "DM",
            "label": "Demographics",
            "variables": [
                {
                    "name": "USUBJID",
                    "label": "Unique Subject Identifier",
                    "type": "text",
                    "core": "Req",
                },
                {"name": "AGE", "label": "Age", "type": "integer", "core": "Exp"},
                {
                    "name": "RFSTDTC",
                    "label": "Subject Reference Start Date/Time",
                    "type": "datetime",
                    "core": "Exp",
                },
                {
                    "name": "SEX",
                    "label": "Sex",
                    "type": "text",
                    "core": "Req",
                    "codelist": "C66731",
                },
                {
                    "name": "ETHNIC",
                    "label": "Ethnicity",
                    "type": "text",
                    "core": "Perm",
                    "codelist": "C66790",
                },
                {
                    "name": "ARMNRS",
                    "label": "Reason Arm and/or Actual Arm is Null",
                    "type": "text",
                    "core": "Perm",
                },
            ],
        }
    ],
}

CLEAN = pl.from_repr("""
┌─────────────┬─────┬────────────┬─────┬────────────────────────┬────────┐
│ USUBJID     ┆ AGE ┆ RFSTDTC    ┆ SEX ┆ ETHNIC                 ┆ ARMNRS │
│ ---         ┆ --- ┆ ---        ┆ --- ┆ ---                    ┆ ---    │
│ str         ┆ i64 ┆ str        ┆ str ┆ str                    ┆ str    │
╞═════════════╪═════╪════════════╪═════╪════════════════════════╪════════╡
│ 01-701-1015 ┆ 63  ┆ 2014-01-02 ┆ F   ┆ NOT HISPANIC OR LATINO ┆ null   │
│ 01-701-1023 ┆ 64  ┆ 2012-08-05 ┆ M   ┆ HISPANIC OR LATINO     ┆ null   │
└─────────────┴─────┴────────────┴─────┴────────────────────────┴────────┘
""")


@pytest.fixture
def checker(tmp_path: Path) -> DatasetChecker:
    path = tmp_path / "define.yaml"
    path.write_text(yaml.safe_dump(_SPEC, sort_keys=False), encoding="utf-8")
    return DatasetChecker(path, validate_schema=False)


def test_a_clean_frame_has_only_the_empty_codelist_warning(checker: DatasetChecker) -> None:
    result = checker.check(CLEAN, "dm")

    assert result.is_valid
    assert result.errors == []
    assert result.warnings == [
        "Column 'ETHNIC': codelist C66790 has no items, so its values are not checked; "
        "run fleet init ct."
    ]
    assert result.info == []
    assert result.labels["SEX"] == "Sex"


def test_a_missing_required_column_is_an_error(checker: DatasetChecker) -> None:
    result = checker.check(CLEAN.drop("USUBJID"), "DM")

    assert result.missing_columns == ["USUBJID"]
    assert result.errors == ["Column 'USUBJID' declared in define is missing from the DataFrame."]


def test_strict_false_downgrades_a_required_column_to_a_warning(checker: DatasetChecker) -> None:
    result = checker.check(CLEAN.drop("USUBJID"), "DM", strict=False)

    assert result.is_valid
    assert (
        "Column 'USUBJID' declared in define is missing from the DataFrame. "
        "[strict=False: downgraded from error]"
    ) in result.warnings


def test_a_missing_expected_column_is_a_warning_and_permissible_is_info(
    checker: DatasetChecker,
) -> None:
    result = checker.check(CLEAN.drop("AGE", "ARMNRS"), "DM")

    assert result.errors == []
    assert "Column 'AGE' declared in define is missing from the DataFrame." in result.warnings
    assert result.info == ["Column 'ARMNRS' declared in define is missing from the DataFrame."]


def test_an_extra_column_is_a_warning_and_a_private_column_is_ignored(
    checker: DatasetChecker,
) -> None:
    frame = CLEAN.with_columns(pl.lit("X").alias("RACE"), pl.lit(1).alias("_TMP"))

    result = checker.check(frame, "DM")

    assert result.extra_columns == ["RACE"]
    assert (
        "Column 'RACE' is present in the DataFrame but not declared in the define."
        in result.warnings
    )


def test_a_type_mismatch_on_a_required_variable_is_an_error(checker: DatasetChecker) -> None:
    frame = CLEAN.with_columns(pl.col("SEX").cast(pl.Categorical).alias("SEX"))
    assert checker.check(frame, "DM").type_mismatches == []

    result = checker.check(CLEAN.with_columns(pl.lit(1).alias("USUBJID")), "DM")

    assert result.type_mismatches == [TypeMismatch("USUBJID", "text", "Int32")]
    assert result.errors == [
        "Column 'USUBJID': define type 'text' (expects String/Categorical) "
        "but actual dtype is 'Int32'."
    ]


def test_a_dtc_variable_must_be_iso_text_whatever_its_define_type(
    checker: DatasetChecker,
) -> None:
    frame = CLEAN.with_columns(pl.col("RFSTDTC").str.to_date().alias("RFSTDTC"))

    result = checker.check(frame, "DM")

    assert result.type_mismatches == [TypeMismatch("RFSTDTC", "datetime", "Date")]
    assert (
        "Column 'RFSTDTC': define type 'datetime' (expects String (ISO 8601 text)) "
        "but actual dtype is 'Date'."
    ) in result.warnings


def test_an_integer_column_passes_a_float_define_type() -> None:
    result = CheckResult(dataset="DM")
    DatasetChecker._run_type_checks(
        result,
        pl.DataFrame({"AVAL": [1, 2]}),
        {"AVAL": {"name": "AVAL", "type": "float", "core": "Req"}},
        {"AVAL"},
    )

    assert result.type_mismatches == []


def test_a_decode_in_a_coded_column_is_a_ct_error_with_a_hint(checker: DatasetChecker) -> None:
    result = checker.check(CLEAN.with_columns(pl.Series("SEX", ["Female", "M"])), "DM")

    assert result.ct_violations == [
        "Column 'SEX': value(s) ['Female'] not in codelist 'C66731' (Sex). "
        "Valid values: ['F', 'M']. ('Female' is the decode of submission value 'F')"
    ]
    assert result.errors == result.ct_violations


def test_an_unknown_dataset_is_an_error(checker: DatasetChecker) -> None:
    result = checker.check(CLEAN, "AE")

    assert result.errors == ["Dataset 'AE' not found in define. Available: ['DM']"]


def test_a_disabled_checker_returns_an_empty_result(tmp_path: Path) -> None:
    path = tmp_path / "define.yaml"
    path.write_text(yaml.safe_dump(_SPEC), encoding="utf-8")

    result = DatasetChecker(path, enabled=False).check(CLEAN.drop("USUBJID"), "DM")

    assert result == CheckResult(dataset="DM")


@pytest.mark.parametrize(
    ("core", "mandatory", "strict", "bucket", "suffix"),
    [
        ("Req", False, True, "errors", ""),
        ("Req", False, False, "warnings", " [strict=False: downgraded from error]"),
        ("Exp", True, True, "warnings", ""),
        ("Perm", True, True, "info", ""),
        ("Conditionally Required", False, True, "info", ""),
        ("", True, True, "errors", ""),
        ("", True, False, "warnings", " [strict=False: downgraded from error]"),
        ("", False, True, "warnings", ""),
    ],
)
def test_classify_routes_by_core_then_by_mandatory(
    core: str, mandatory: bool, strict: bool, bucket: str, suffix: str
) -> None:
    result = CheckResult(dataset="DM")

    _classify(result, "msg", core=core, mandatory=mandatory, strict=strict)

    assert getattr(result, bucket) == ["msg" + suffix]
    others = {"errors", "warnings", "info"} - {bucket}
    assert all(getattr(result, other) == [] for other in others)
