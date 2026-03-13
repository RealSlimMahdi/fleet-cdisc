"""Unit tests for the ADaM ADSL Polars namespace extension (df.adsl)."""

import polars as pl
import pytest

import pymaverse  # noqa: F401 — triggers namespace registration


@pytest.fixture
def subject_frame():
    """Minimal ADSL-like subject-level frame."""
    return pl.DataFrame({
        "USUBJID": ["01-001", "01-002", "01-003"],
        "AGE":     [45, 62, 38],
        "TRTSDT":  ["2024-01-10", "2024-01-11", "2024-01-12"],
        "TRTEDT":  ["2024-03-10", "2024-03-11", "2024-03-12"],
        "RANDFL":  ["Y", "Y", "Y"],
        "COMPLFL": ["Y", "N", "Y"],
    })


@pytest.fixture
def ae_dataset():
    """Minimal AE SDTM-like event frame."""
    return pl.DataFrame({
        "USUBJID": ["01-001", "01-001", "01-002"],
        "AESTDTC": ["2024-01-15", "2024-01-20", "2024-01-18"],
        "AESER":   ["N", "Y", "N"],
    })


class TestBaseVerbs:
    def test_source(self, subject_frame):
        result = subject_frame.adsl.source("USUBJID").to_frame()
        assert "USUBJID" in result.columns

    def test_assigned(self, subject_frame):
        result = subject_frame.adsl.assigned("STUDYID", value="TEST01").to_frame()
        assert result["STUDYID"].to_list() == ["TEST01"] * 3

    def test_derivation(self, subject_frame):
        result = subject_frame.adsl.derivation(
            "AGE2", expression='pl.col("AGE") * 2'
        ).to_frame()
        assert result["AGE2"][0] == 90

    def test_rename(self, subject_frame):
        result = subject_frame.adsl.rename("SUBJECTID", source="USUBJID").to_frame()
        assert "SUBJECTID" in result.columns

    def test_whereclauses(self, subject_frame):
        result = subject_frame.adsl.whereclauses(
            where='pl.col("AGE") > 40'
        ).to_frame()
        assert result.height == 2


class TestFirstDate:
    def test_first_ae_date(self, subject_frame, ae_dataset):
        result = subject_frame.adsl.first_date(
            "AESTDTC", from_dataset=ae_dataset, date_col="AESTDTC"
        ).to_frame()
        assert "AESTDTC" in result.columns
        # 01-001 has two AEs, earliest is 2024-01-15
        row = result.filter(pl.col("USUBJID") == "01-001")
        assert row["AESTDTC"][0] == "2024-01-15"

    def test_first_date_with_where(self, subject_frame, ae_dataset):
        result = subject_frame.adsl.first_date(
            "SAESTDTC", from_dataset=ae_dataset, date_col="AESTDTC",
            where='pl.col("AESER") == "Y"'
        ).to_frame()
        # Only 01-001 has a serious AE
        row_001 = result.filter(pl.col("USUBJID") == "01-001")
        assert row_001["SAESTDTC"][0] == "2024-01-20"
        # 01-002 has no serious AEs → null
        row_002 = result.filter(pl.col("USUBJID") == "01-002")
        assert row_002["SAESTDTC"][0] is None

    def test_subject_no_events_gets_null(self, subject_frame, ae_dataset):
        result = subject_frame.adsl.first_date(
            "AESTDTC", from_dataset=ae_dataset, date_col="AESTDTC"
        ).to_frame()
        # 01-003 has no AEs
        row_003 = result.filter(pl.col("USUBJID") == "01-003")
        assert row_003["AESTDTC"][0] is None


class TestLastDate:
    def test_last_ae_date(self, subject_frame, ae_dataset):
        result = subject_frame.adsl.last_date(
            "AEENDTC", from_dataset=ae_dataset, date_col="AESTDTC"
        ).to_frame()
        row = result.filter(pl.col("USUBJID") == "01-001")
        assert row["AEENDTC"][0] == "2024-01-20"


class TestDuration:
    def test_duration_days(self, subject_frame):
        result = subject_frame.adsl.duration(
            "TRTDURD", start_date="TRTSDT", end_date="TRTEDT"
        ).to_frame()
        assert "TRTDURD" in result.columns
        assert result["TRTDURD"][0] > 0

    def test_duration_non_inclusive(self, subject_frame):
        result_inc = subject_frame.adsl.duration(
            "TRTDURD", start_date="TRTSDT", end_date="TRTEDT", inclusive=True
        ).to_frame()
        result_exc = subject_frame.adsl.duration(
            "TRTDURD", start_date="TRTSDT", end_date="TRTEDT", inclusive=False
        ).to_frame()
        assert result_inc["TRTDURD"][0] == result_exc["TRTDURD"][0] + 1


class TestCountEvents:
    def test_count_all(self, subject_frame, ae_dataset):
        result = subject_frame.adsl.count_events(
            "NUMAE", from_dataset=ae_dataset
        ).to_frame()
        row_001 = result.filter(pl.col("USUBJID") == "01-001")
        assert row_001["NUMAE"][0] == 2

    def test_count_zero_for_no_events(self, subject_frame, ae_dataset):
        result = subject_frame.adsl.count_events(
            "NUMAE", from_dataset=ae_dataset
        ).to_frame()
        row_003 = result.filter(pl.col("USUBJID") == "01-003")
        assert row_003["NUMAE"][0] == 0

    def test_count_with_where(self, subject_frame, ae_dataset):
        result = subject_frame.adsl.count_events(
            "NUMSAE", from_dataset=ae_dataset,
            where='pl.col("AESER") == "Y"'
        ).to_frame()
        row_001 = result.filter(pl.col("USUBJID") == "01-001")
        assert row_001["NUMSAE"][0] == 1


class TestEligibilityFlag:
    def test_all_randomised(self, subject_frame):
        result = subject_frame.adsl.eligibility_flag(
            "SAFFL", criteria='pl.col("RANDFL") == "Y"'
        ).to_frame()
        assert result["SAFFL"].to_list() == ["Y", "Y", "Y"]

    def test_partial_compliant(self, subject_frame):
        result = subject_frame.adsl.eligibility_flag(
            "PPROTFL", criteria='pl.col("COMPLFL") == "Y"'
        ).to_frame()
        flags = result["PPROTFL"].to_list()
        assert flags[0] == "Y"
        assert flags[1] is None
        assert flags[2] == "Y"
