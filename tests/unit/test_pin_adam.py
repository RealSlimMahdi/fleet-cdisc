"""Unit tests for ADaM pin integration — join_adsl, study_day."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration

# ── Fixtures ────────────────────────────────────────────────────────────── #


@pytest.fixture
def adsl_df():
    return pl.from_repr("""\
┌─────────┬────────────┬────────────┬───────┬───────────┐
│ USUBJID ┆ TRTSDT     ┆ TRTEDT     ┆ SAFFL ┆ TRT01P    │
│ ---     ┆ ---        ┆ ---        ┆ ---   ┆ ---       │
│ str     ┆ str        ┆ str        ┆ str   ┆ str       │
╞═════════╪════════════╪════════════╪═══════╪═══════════╡
│ S001    ┆ 2014-01-02 ┆ 2014-07-02 ┆ Y     ┆ Placebo   │
│ S002    ┆ 2014-01-03 ┆ 2014-07-03 ┆ Y     ┆ Low Dose  │
│ S003    ┆ 2014-01-04 ┆ 2014-07-04 ┆ Y     ┆ High Dose │
└─────────┴────────────┴────────────┴───────┴───────────┘
""")


@pytest.fixture
def ae_df():
    return pl.from_repr("""\
┌─────────┬──────────┬────────────┐
│ USUBJID ┆ AETERM   ┆ AESTDTC    │
│ ---     ┆ ---      ┆ ---        │
│ str     ┆ str      ┆ str        │
╞═════════╪══════════╪════════════╡
│ S001    ┆ HEADACHE ┆ 2014-01-10 │
│ S001    ┆ NAUSEA   ┆ 2014-01-01 │
│ S002    ┆ RASH     ┆ 2014-02-15 │
└─────────┴──────────┴────────────┘
""")


# ── join_adsl ────────────────────────────────────────────────────────── #


class TestJoinADSL:
    def test_join_adsl_basic(self, ae_df, adsl_df):
        result = (
            ae_df.adam.occds("ADAE")
            .pin("ADSL", adsl_df)
            .source("USUBJID")
            .join_adsl("TRTSDT", "SAFFL")
            .to_frame()
        )
        assert "TRTSDT" in result.columns
        assert "SAFFL" in result.columns
        assert "TRT01P" not in result.columns  # not requested

    def test_join_adsl_no_pin_raises(self, ae_df):
        with pytest.raises(LookupError, match="join_adsl.*pinned.*ADSL"):
            (ae_df.adam.occds("ADAE").source("USUBJID").join_adsl("TRTSDT").to_frame())

    def test_join_adsl_values_correct(self, ae_df, adsl_df):
        result = (
            ae_df.adam.occds("ADAE")
            .pin("ADSL", adsl_df)
            .source("USUBJID")
            .join_adsl("TRT01P")
            .to_frame()
        )
        s001_rows = result.filter(pl.col("USUBJID") == "S001")
        assert s001_rows["TRT01P"].to_list() == ["Placebo", "Placebo"]


# ── ADaM study_day ───────────────────────────────────────────────────── #


class TestADaMStudyDay:
    def test_study_day_from_pin(self, ae_df, adsl_df):
        result = (
            ae_df.adam.occds("ADAE")
            .pin("ADSL", adsl_df)
            .source("USUBJID")
            .join_adsl("TRTSDT")
            .study_day("ASTDY", date_col="AESTDTC", ref_col="TRTSDT")
            .to_frame()
        )
        assert "ASTDY" in result.columns
        # S001: 2014-01-10 - 2014-01-02 = 8 → +1 = 9
        s001_rows = result.filter(pl.col("USUBJID") == "S001").sort("AETERM")
        assert s001_rows["ASTDY"][0] == 9  # HEADACHE

    def test_study_day_ref_already_in_frame(self, adsl_df):
        """When TRTSDT is in the frame, no pin needed."""
        df = pl.from_repr("""\
┌─────────┬────────────┬────────────┐
│ USUBJID ┆ TRTSDT     ┆ ASTDT      │
│ ---     ┆ ---        ┆ ---        │
│ str     ┆ str        ┆ str        │
╞═════════╪════════════╪════════════╡
│ S001    ┆ 2014-01-02 ┆ 2014-01-10 │
└─────────┴────────────┴────────────┘
""")
        result = (
            df.adam.adsl.source("USUBJID")
            .source("TRTSDT")
            .source("ASTDT")
            .study_day("ASTDY", date_col="ASTDT")
            .to_frame()
        )
        assert result["ASTDY"][0] == 9

    def test_study_day_no_pin_raises(self, ae_df):
        with pytest.raises(LookupError, match="study_day.*pinned.*ADSL"):
            (
                ae_df.adam.occds("ADAE")
                .source("USUBJID")
                .study_day("ASTDY", date_col="AESTDTC")
                .to_frame()
            )

    def test_study_day_same_day_is_one(self, adsl_df):
        """Same day → study day 1 (no day 0)."""
        df = pl.from_repr("""\
┌─────────┬────────────┬────────────┐
│ USUBJID ┆ TRTSDT     ┆ ASTDT      │
│ ---     ┆ ---        ┆ ---        │
│ str     ┆ str        ┆ str        │
╞═════════╪════════════╪════════════╡
│ S001    ┆ 2014-01-02 ┆ 2014-01-02 │
└─────────┴────────────┴────────────┘
""")
        result = (
            df.adam.adsl.source("USUBJID")
            .source("TRTSDT")
            .source("ASTDT")
            .study_day("ASTDY", date_col="ASTDT")
            .to_frame()
        )
        assert result["ASTDY"][0] == 1
