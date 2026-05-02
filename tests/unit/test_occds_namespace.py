"""Unit tests for the ADaM OCCDS Polars namespace extension (df.adam.occds)."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration


@pytest.fixture
def ae_frame():
    """Minimal AE SDTM-like event frame."""
    return pl.DataFrame(
        {
            "USUBJID": ["01-001", "01-001", "01-001", "01-002"],
            "AETERM": ["Headache", "Nausea", "Fatigue", "Dizziness"],
            "AEBODSYS": ["Nervous", "GI", "General", "Nervous"],
            "AESEV": ["MILD", "SEVERE", "MODERATE", "MILD"],
            "AESTDTC": ["2024-01-15", "2024-01-20", "2024-01-25", "2024-01-16"],
            "AEENDTC": ["2024-01-17", None, "2024-01-26", "2024-01-18"],
            "TRTSDT": ["2024-01-10", "2024-01-10", "2024-01-10", "2024-01-11"],
            "TRTEDT": ["2024-03-10", "2024-03-10", "2024-03-10", "2024-03-11"],
        }
    )


class TestBaseVerbs:
    def test_source(self, ae_frame):
        result = ae_frame.adam.occds.source("USUBJID").to_frame()
        assert "USUBJID" in result.columns

    def test_assigned(self, ae_frame):
        result = ae_frame.adam.occds.assigned("STUDYID", value="TEST01").to_frame()
        assert result["STUDYID"].to_list() == ["TEST01"] * 4

    def test_derivation(self, ae_frame):
        result = ae_frame.adam.occds.derivation(
            "AETERM2", expression='pl.col("AETERM").str.to_uppercase()'
        ).to_frame()
        assert result["AETERM2"][0] == "HEADACHE"

    def test_whereclauses(self, ae_frame):
        result = ae_frame.adam.occds.whereclauses(where='pl.col("AESEV") == "MILD"').to_frame()
        assert result.height == 2

    def test_recode(self, ae_frame):
        result = ae_frame.adam.occds.recode(
            "AESEVN",
            source="AESEV",
            recode_map={"MILD": "1", "MODERATE": "2", "SEVERE": "3"},
        ).to_frame()
        assert result["AESEVN"][0] == "1"  # Headache=MILD
        assert result["AESEVN"][1] == "3"  # Nausea=SEVERE

    def test_rename(self, ae_frame):
        result = ae_frame.adam.occds.rename("AEDECOD", source="AETERM").to_frame()
        assert result["AEDECOD"].to_list() == ae_frame["AETERM"].to_list()

    def test_condderivation(self, ae_frame):
        result = ae_frame.adam.occds.condderivation(
            "SEVGR",
            conditions=[
                {"condition": 'pl.col("AESEV") == "SEVERE"', "value": "HIGH"},
            ],
            else_value="LOW",
        ).to_frame()
        # Only Nausea is SEVERE
        assert result["SEVGR"][1] == "HIGH"
        assert result["SEVGR"][0] == "LOW"


class TestSeq:
    def test_seq_starts_at_one(self, ae_frame):
        result = ae_frame.adam.occds.seq("ASEQ", groups=["USUBJID"]).to_frame()
        rows_001 = result.filter(pl.col("USUBJID") == "01-001")
        assert sorted(rows_001["ASEQ"].to_list()) == [1, 2, 3]

    def test_seq_resets_per_subject(self, ae_frame):
        result = ae_frame.adam.occds.seq("ASEQ", groups=["USUBJID"]).to_frame()
        rows_002 = result.filter(pl.col("USUBJID") == "01-002")
        assert rows_002["ASEQ"].to_list() == [1]


class TestFlagMax:
    def test_max_per_body_system(self, ae_frame):
        # Encode severity as numeric to use flag(criteria="max")
        sev_map = {"MILD": 1, "MODERATE": 2, "SEVERE": 3}
        df = ae_frame.with_columns(
            pl.col("AESEV").replace_strict(sev_map, default=0).alias("AESEVN")
        )
        result = df.adam.occds.flag(
            "ANL01FL",
            criteria="max",
            value_col="AESEVN",
            groups=["USUBJID", "AEBODSYS"],
        ).to_frame()
        assert "ANL01FL" in result.columns
        # For 01-001 / Nervous system: only MILD (AESEVN=1) → flagged (it's the max for that group)
        nervous_001 = result.filter(
            (pl.col("USUBJID") == "01-001") & (pl.col("AEBODSYS") == "Nervous")
        )
        assert nervous_001["ANL01FL"][0] == "Y"

    def test_flag_max_non_worst_is_null(self, ae_frame):
        sev_map = {"MILD": 1, "MODERATE": 2, "SEVERE": 3}
        df = ae_frame.with_columns(
            pl.col("AESEV").replace_strict(sev_map, default=0).alias("AESEVN")
        )
        result = df.adam.occds.flag(
            "ANL01FL",
            criteria="max",
            value_col="AESEVN",
            groups=["USUBJID"],
        ).to_frame()
        # SEVERE (AESEVN=3) is worst for 01-001; MILD rows should be null
        mild_001 = result.filter((pl.col("USUBJID") == "01-001") & (pl.col("AESEV") == "MILD"))
        assert mild_001["ANL01FL"][0] is None


class TestTreatmentEmergent:
    def test_on_treatment_flagged(self, ae_frame):
        result = ae_frame.adam.occds.treatment_emergent(
            "TRTEMFL", start_date="AESTDTC", trtsdt="TRTSDT", trtedt="TRTEDT"
        ).to_frame()
        # All events start after TRTSDT and before TRTEDT
        assert all(f == "Y" for f in result["TRTEMFL"].to_list())

    def test_pre_treatment_not_flagged(self):
        df = pl.DataFrame(
            {
                "AESTDTC": ["2024-01-05"],
                "TRTSDT": ["2024-01-10"],
                "TRTEDT": ["2024-03-10"],
            }
        )
        result = df.adam.occds.treatment_emergent(
            "TRTEMFL", start_date="AESTDTC", trtsdt="TRTSDT", trtedt="TRTEDT"
        ).to_frame()
        assert result["TRTEMFL"][0] is None


class TestOnsetRecovery:
    def test_recovered_flagged(self, ae_frame):
        result = ae_frame.adam.occds.onset_recovery(
            "RCVRYFL", start_date="AESTDTC", end_date="AEENDTC", ref_date="TRTSDT"
        ).to_frame()
        # Row 0: started on-trt, has end date → Y
        assert result["RCVRYFL"][0] == "Y"
        # Row 1: started on-trt, NO end date → null
        assert result["RCVRYFL"][1] is None
