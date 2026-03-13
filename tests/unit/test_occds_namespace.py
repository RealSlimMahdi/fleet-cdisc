"""Unit tests for the ADaM OCCDS Polars namespace extension (df.occds)."""

import polars as pl
import pytest

import pymaverse  # noqa: F401 — triggers namespace registration


@pytest.fixture
def ae_frame():
    """Minimal AE SDTM-like event frame."""
    return pl.DataFrame({
        "USUBJID":  ["01-001", "01-001", "01-001", "01-002"],
        "AETERM":   ["Headache", "Nausea", "Fatigue", "Dizziness"],
        "AEBODSYS": ["Nervous", "GI", "General", "Nervous"],
        "AESEV":    ["MILD", "SEVERE", "MODERATE", "MILD"],
        "AESTDTC":  ["2024-01-15", "2024-01-20", "2024-01-25", "2024-01-16"],
        "AEENDTC":  ["2024-01-17", None,          "2024-01-26", "2024-01-18"],
        "TRTSDT":   ["2024-01-10", "2024-01-10", "2024-01-10", "2024-01-11"],
        "TRTEDT":   ["2024-03-10", "2024-03-10", "2024-03-10", "2024-03-11"],
    })


class TestBaseVerbs:
    def test_source(self, ae_frame):
        result = ae_frame.occds.source("USUBJID").to_frame()
        assert "USUBJID" in result.columns

    def test_assigned(self, ae_frame):
        result = ae_frame.occds.assigned("STUDYID", value="TEST01").to_frame()
        assert result["STUDYID"].to_list() == ["TEST01"] * 4

    def test_derivation(self, ae_frame):
        result = ae_frame.occds.derivation(
            "AETERM2", expression='pl.col("AETERM").str.to_uppercase()'
        ).to_frame()
        assert result["AETERM2"][0] == "HEADACHE"

    def test_whereclauses(self, ae_frame):
        result = ae_frame.occds.whereclauses(
            where='pl.col("AESEV") == "MILD"'
        ).to_frame()
        assert result.height == 2


class TestSeq:
    def test_seq_starts_at_one(self, ae_frame):
        result = ae_frame.occds.seq("ASEQ", groups=["USUBJID"]).to_frame()
        rows_001 = result.filter(pl.col("USUBJID") == "01-001")
        assert sorted(rows_001["ASEQ"].to_list()) == [1, 2, 3]

    def test_seq_resets_per_subject(self, ae_frame):
        result = ae_frame.occds.seq("ASEQ", groups=["USUBJID"]).to_frame()
        rows_002 = result.filter(pl.col("USUBJID") == "01-002")
        assert rows_002["ASEQ"].to_list() == [1]


class TestWorstFlag:
    def test_worst_per_body_system(self, ae_frame):
        result = ae_frame.occds.worst_flag(
            "ANL01FL",
            severity_col="AESEV",
            groups=["USUBJID", "AEBODSYS"],
            severity_order=["MILD", "MODERATE", "SEVERE"],
        ).to_frame()
        assert "ANL01FL" in result.columns
        # For 01-001 / Nervous system: only MILD → flagged
        nervous_001 = result.filter(
            (pl.col("USUBJID") == "01-001") & (pl.col("AEBODSYS") == "Nervous")
        )
        assert nervous_001["ANL01FL"][0] == "Y"

    def test_worst_flag_non_worst_is_null(self, ae_frame):
        result = ae_frame.occds.worst_flag(
            "ANL01FL",
            severity_col="AESEV",
            groups=["USUBJID"],
            severity_order=["MILD", "MODERATE", "SEVERE"],
        ).to_frame()
        # SEVERE is worst for 01-001; MILD rows should be null
        mild_001 = result.filter(
            (pl.col("USUBJID") == "01-001") & (pl.col("AESEV") == "MILD")
        )
        assert mild_001["ANL01FL"][0] is None


class TestTreatmentEmergent:
    def test_on_treatment_flagged(self, ae_frame):
        result = ae_frame.occds.treatment_emergent(
            "TRTEMFL", start_date="AESTDTC", trtsdt="TRTSDT", trtedt="TRTEDT"
        ).to_frame()
        # All events start after TRTSDT and before TRTEDT
        assert all(f == "Y" for f in result["TRTEMFL"].to_list())

    def test_pre_treatment_not_flagged(self):
        df = pl.DataFrame({
            "AESTDTC": ["2024-01-05"],
            "TRTSDT":  ["2024-01-10"],
            "TRTEDT":  ["2024-03-10"],
        })
        result = df.occds.treatment_emergent(
            "TRTEMFL", start_date="AESTDTC", trtsdt="TRTSDT", trtedt="TRTEDT"
        ).to_frame()
        assert result["TRTEMFL"][0] is None


class TestOnsetRecovery:
    def test_recovered_flagged(self, ae_frame):
        result = ae_frame.occds.onset_recovery(
            "RCVRYFL", start_date="AESTDTC", end_date="AEENDTC", ref_date="TRTSDT"
        ).to_frame()
        # Row 0: started on-trt, has end date → Y
        assert result["RCVRYFL"][0] == "Y"
        # Row 1: started on-trt, NO end date → null
        assert result["RCVRYFL"][1] is None
