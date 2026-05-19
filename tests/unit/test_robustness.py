"""Parameterized robustness tests for order invariance and determinism."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration
from tests.assertions import assert_deterministic
from tests.factories import build_dm_cohort, shuffle_rows

SEEDS = [42, 123, 999, 7, 2024]


class TestSDTMOrderInvarianceParameterized:
    """SDTM pipeline results must be independent of input row order."""

    @pytest.mark.parametrize("seed", SEEDS)
    def test_full_pipeline_order_invariant(self, seed):
        df = build_dm_cohort(n_subjects=5)

        def pipeline(d):
            return (
                d.sdtm
                .hardcode_no_ct("DOMAIN", value="DM")
                .assign_no_ct("USUBJID", source="patient_number")
                .assign_no_ct("SITEID", source="site_id")
                .to_frame()
            )
        result1 = pipeline(df)
        result2 = pipeline(shuffle_rows(df, seed=seed))
        assert_deterministic(result1, result2, sort_cols=["USUBJID"])


class TestADaMOrderInvarianceParameterized:
    """ADaM pipeline results must be independent of input row order."""

    @pytest.mark.parametrize("seed", SEEDS)
    def test_derivation_chain_order_invariant(self, seed):
        df = pl.DataFrame({
            "USUBJID": [f"S{i:02d}" for i in range(10)],
            "PARAMCD": ["SYSBP"] * 5 + ["DIABP"] * 5,
            "VSSTRESN": [120.0 + i for i in range(10)],
            "vsdtc": [f"2014-01-{i + 1:02d}" for i in range(10)],
        })
        def pipeline(d):
            return (
                d.adam
                .source("USUBJID")
                .source("PARAMCD")
                .derivation("AVAL", expression="VSSTRESN")
                .assigned("STUDYID", value="STUDY01")
                .to_frame()
            )
        result1 = pipeline(df)
        result2 = pipeline(shuffle_rows(df, seed=seed))
        assert_deterministic(result1, result2, sort_cols=["USUBJID", "PARAMCD"])


class TestNodupDeterminism:
    """Nodup results must be deterministic regardless of input order."""

    @pytest.mark.parametrize("seed", SEEDS)
    def test_keep_first_deterministic(self, seed, capsys):
        df = pl.DataFrame({
            "USUBJID": ["S01", "S01", "S02", "S02", "S03"],
            "AEDECOD": ["HA", "HA", "NA", "NA", "RA"],
            "AESEQ": [1, 2, 1, 2, 1],
        })
        result1 = df.sdtm.nodup(
            subset=["USUBJID", "AEDECOD"], sort_by=["AESEQ"], keep="first"
        ).to_frame()
        capsys.readouterr()
        result2 = shuffle_rows(df, seed=seed).sdtm.nodup(
            subset=["USUBJID", "AEDECOD"], sort_by=["AESEQ"], keep="first"
        ).to_frame()
        capsys.readouterr()
        assert_deterministic(result1, result2, sort_cols=["USUBJID", "AEDECOD"])
