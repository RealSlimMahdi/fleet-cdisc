"""Parameterized robustness tests for order invariance and determinism."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration
from tests.assertions import assert_deterministic
from tests.helpers import shuffle_rows

SEEDS = [42, 123, 999, 7, 2024]


class TestSDTMOrderInvarianceParameterized:
    """SDTM pipeline results must be independent of input row order."""

    @pytest.mark.parametrize("seed", SEEDS)
    def test_full_pipeline_order_invariant(self, seed):
        df = pl.from_repr("""\
┌────────────────┬─────────┬─────┬─────┐
│ patient_number ┆ site_id ┆ age ┆ sex │
│ ---            ┆ ---     ┆ --- ┆ --- │
│ str            ┆ str     ┆ i64 ┆ str │
╞════════════════╪═════════╪═════╪═════╡
│ 01-701-1015    ┆ 701     ┆ 63  ┆ F   │
│ 01-701-1016    ┆ 701     ┆ 64  ┆ M   │
│ 01-701-1017    ┆ 701     ┆ 71  ┆ F   │
│ 01-701-1018    ┆ 701     ┆ 55  ┆ M   │
│ 01-701-1019    ┆ 701     ┆ 48  ┆ F   │
└────────────────┴─────────┴─────┴─────┘
""")

        def pipeline(d):
            return (
                d.sdtm.hardcode_no_ct("DOMAIN", value="DM")
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
        df = pl.from_repr("""┌─────────┬─────────┬──────────┬────────────┐
│ USUBJID ┆ PARAMCD ┆ VSSTRESN ┆ vsdtc      │
│ ---     ┆ ---     ┆ ---      ┆ ---        │
│ str     ┆ str     ┆ f64      ┆ str        │
╞═════════╪═════════╪══════════╪════════════╡
│ S00     ┆ SYSBP   ┆ 120.0    ┆ 2014-01-01 │
│ S01     ┆ SYSBP   ┆ 121.0    ┆ 2014-01-02 │
│ S02     ┆ SYSBP   ┆ 122.0    ┆ 2014-01-03 │
│ S03     ┆ SYSBP   ┆ 123.0    ┆ 2014-01-04 │
│ S04     ┆ SYSBP   ┆ 124.0    ┆ 2014-01-05 │
│ S05     ┆ DIABP   ┆ 125.0    ┆ 2014-01-06 │
│ S06     ┆ DIABP   ┆ 126.0    ┆ 2014-01-07 │
│ S07     ┆ DIABP   ┆ 127.0    ┆ 2014-01-08 │
│ S08     ┆ DIABP   ┆ 128.0    ┆ 2014-01-09 │
│ S09     ┆ DIABP   ┆ 129.0    ┆ 2014-01-10 │
└─────────┴─────────┴──────────┴────────────┘
""")

        def pipeline(d):
            return (
                d.adam.source("USUBJID")
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
        df = pl.from_repr("""┌─────────┬─────────┬───────┐
│ USUBJID ┆ AEDECOD ┆ AESEQ │
│ ---     ┆ ---     ┆ ---   │
│ str     ┆ str     ┆ i64   │
╞═════════╪═════════╪═══════╡
│ S01     ┆ HA      ┆ 1     │
│ S01     ┆ HA      ┆ 2     │
│ S02     ┆ NA      ┆ 1     │
│ S02     ┆ NA      ┆ 2     │
│ S03     ┆ RA      ┆ 1     │
└─────────┴─────────┴───────┘
""")
        result1 = df.sdtm.nodup(
            subset=["USUBJID", "AEDECOD"], sort_by=["AESEQ"], keep="first"
        ).to_frame()
        capsys.readouterr()
        result2 = (
            shuffle_rows(df, seed=seed)
            .sdtm.nodup(subset=["USUBJID", "AEDECOD"], sort_by=["AESEQ"], keep="first")
            .to_frame()
        )
        capsys.readouterr()
        assert_deterministic(result1, result2, sort_cols=["USUBJID", "AEDECOD"])
