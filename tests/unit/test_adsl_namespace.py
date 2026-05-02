"""Unit tests for the ADaM ADSL Polars namespace extension (df.adam.adsl)."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration


@pytest.fixture
def subject_frame():
    """Minimal ADSL-like subject-level frame."""
    return pl.DataFrame(
        {
            "USUBJID": ["01-001", "01-002", "01-003"],
            "AGE": [45, 62, 38],
            "TRTSDT": ["2024-01-10", "2024-01-11", "2024-01-12"],
            "TRTEDT": ["2024-03-10", "2024-03-11", "2024-03-12"],
            "RANDFL": ["Y", "Y", "Y"],
            "COMPLFL": ["Y", "N", "Y"],
            "EXDOSE": [54.0, 0.0, 81.0],
            "RANDDT": ["2024-01-09", "2024-01-10", None],
        }
    )


@pytest.fixture
def ae_dataset():
    """Minimal AE SDTM-like event frame."""
    return pl.DataFrame(
        {
            "USUBJID": ["01-001", "01-001", "01-002"],
            "AESTDTC": ["2024-01-15", "2024-01-20", "2024-01-18"],
            "AESER": ["N", "Y", "N"],
        }
    )


class TestBaseVerbs:
    def test_source(self, subject_frame):
        result = subject_frame.adam.adsl.source("USUBJID").to_frame()
        assert "USUBJID" in result.columns

    def test_assigned(self, subject_frame):
        result = subject_frame.adam.adsl.assigned("STUDYID", value="TEST01").to_frame()
        assert result["STUDYID"].to_list() == ["TEST01"] * 3

    def test_derivation(self, subject_frame):
        result = subject_frame.adam.adsl.derivation(
            "AGE2", expression='pl.col("AGE") * 2'
        ).to_frame()
        assert result["AGE2"][0] == 90

    def test_rename(self, subject_frame):
        result = subject_frame.adam.adsl.rename("SUBJECTID", source="USUBJID").to_frame()
        assert "SUBJECTID" in result.columns

    def test_whereclauses(self, subject_frame):
        result = subject_frame.adam.adsl.whereclauses(where='pl.col("AGE") > 40').to_frame()
        assert result.height == 2

    def test_recode(self, subject_frame):
        result = subject_frame.adam.adsl.recode(
            "RANDFL_N",
            source="RANDFL",
            recode_map={"Y": "1", "N": "0"},
        ).to_frame()
        assert result["RANDFL_N"].to_list() == ["1", "1", "1"]

    def test_condderivation(self, subject_frame):
        result = subject_frame.adam.adsl.condderivation(
            "AGEGR",
            conditions=[
                {"condition": 'pl.col("AGE") < 40', "value": "<40"},
                {"condition": 'pl.col("AGE") <= 64', "value": "40-64"},
            ],
            else_value=">64",
        ).to_frame()
        assert result["AGEGR"].to_list() == ["40-64", "40-64", "<40"]


class TestFirstDate:
    def test_first_ae_date(self, subject_frame, ae_dataset):
        result = subject_frame.adam.adsl.first_date(
            "AESTDTC", from_dataset=ae_dataset, date_col="AESTDTC"
        ).to_frame()
        assert "AESTDTC" in result.columns
        # 01-001 has two AEs, earliest is 2024-01-15
        row = result.filter(pl.col("USUBJID") == "01-001")
        assert row["AESTDTC"][0] == "2024-01-15"

    def test_first_date_with_where(self, subject_frame, ae_dataset):
        result = subject_frame.adam.adsl.first_date(
            "SAESTDTC", from_dataset=ae_dataset, date_col="AESTDTC", where='pl.col("AESER") == "Y"'
        ).to_frame()
        # Only 01-001 has a serious AE
        row_001 = result.filter(pl.col("USUBJID") == "01-001")
        assert row_001["SAESTDTC"][0] == "2024-01-20"
        # 01-002 has no serious AEs → null
        row_002 = result.filter(pl.col("USUBJID") == "01-002")
        assert row_002["SAESTDTC"][0] is None

    def test_subject_no_events_gets_null(self, subject_frame, ae_dataset):
        result = subject_frame.adam.adsl.first_date(
            "AESTDTC", from_dataset=ae_dataset, date_col="AESTDTC"
        ).to_frame()
        # 01-003 has no AEs
        row_003 = result.filter(pl.col("USUBJID") == "01-003")
        assert row_003["AESTDTC"][0] is None


class TestLastDate:
    def test_last_ae_date(self, subject_frame, ae_dataset):
        result = subject_frame.adam.adsl.last_date(
            "AEENDTC", from_dataset=ae_dataset, date_col="AESTDTC"
        ).to_frame()
        row = result.filter(pl.col("USUBJID") == "01-001")
        assert row["AEENDTC"][0] == "2024-01-20"


class TestDuration:
    def test_duration_days(self, subject_frame):
        result = subject_frame.adam.adsl.duration(
            "TRTDURD", start_date="TRTSDT", end_date="TRTEDT"
        ).to_frame()
        assert "TRTDURD" in result.columns
        assert result["TRTDURD"][0] > 0

    def test_duration_non_inclusive(self, subject_frame):
        result_inc = subject_frame.adam.adsl.duration(
            "TRTDURD", start_date="TRTSDT", end_date="TRTEDT", inclusive=True
        ).to_frame()
        result_exc = subject_frame.adam.adsl.duration(
            "TRTDURD", start_date="TRTSDT", end_date="TRTEDT", inclusive=False
        ).to_frame()
        assert result_inc["TRTDURD"][0] == result_exc["TRTDURD"][0] + 1


class TestCountEvents:
    def test_count_all(self, subject_frame, ae_dataset):
        result = subject_frame.adam.adsl.count_events("NUMAE", from_dataset=ae_dataset).to_frame()
        row_001 = result.filter(pl.col("USUBJID") == "01-001")
        assert row_001["NUMAE"][0] == 2

    def test_count_zero_for_no_events(self, subject_frame, ae_dataset):
        result = subject_frame.adam.adsl.count_events("NUMAE", from_dataset=ae_dataset).to_frame()
        row_003 = result.filter(pl.col("USUBJID") == "01-003")
        assert row_003["NUMAE"][0] == 0

    def test_count_with_where(self, subject_frame, ae_dataset):
        result = subject_frame.adam.adsl.count_events(
            "NUMSAE", from_dataset=ae_dataset, where='pl.col("AESER") == "Y"'
        ).to_frame()
        row_001 = result.filter(pl.col("USUBJID") == "01-001")
        assert row_001["NUMSAE"][0] == 1


class TestEligibilityFlag:
    def test_saffl_at_least_one_dose(self, subject_frame):
        """SAFFL = 'Y' when patient has at least one dose > 0."""
        result = subject_frame.adam.adsl.flag(
            "SAFFL", criteria='pl.col("EXDOSE") > 0'
        ).to_frame()
        flags = result["SAFFL"].to_list()
        assert flags[0] == "Y"  # 01-001: EXDOSE=54 → Y
        assert flags[1] is None  # 01-002: EXDOSE=0  → null
        assert flags[2] == "Y"  # 01-003: EXDOSE=81 → Y

    def test_ittfl_has_randomization_date(self, subject_frame):
        """ITTFL = 'Y' when patient has a randomization date."""
        result = subject_frame.adam.adsl.flag(
            "ITTFL", criteria='pl.col("RANDDT").is_not_null()'
        ).to_frame()
        flags = result["ITTFL"].to_list()
        assert flags[0] == "Y"  # 01-001: RANDDT present → Y
        assert flags[1] == "Y"  # 01-002: RANDDT present → Y
        assert flags[2] is None  # 01-003: RANDDT missing → null

    def test_partial_compliant(self, subject_frame):
        result = subject_frame.adam.adsl.flag(
            "PPROTFL", criteria='pl.col("COMPLFL") == "Y"'
        ).to_frame()
        flags = result["PPROTFL"].to_list()
        assert flags[0] == "Y"
        assert flags[1] is None
        assert flags[2] == "Y"
