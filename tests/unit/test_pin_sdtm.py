"""Unit tests for SDTM pin integration — study_day, baseline_flag, auto FK."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration

# ── Fixtures ────────────────────────────────────────────────────────────── #


@pytest.fixture
def dm_df():
    return pl.from_repr("""\
┌─────────┬────────────┬───────────┐
│ USUBJID ┆ RFSTDTC    ┆ ARM       │
│ ---     ┆ ---        ┆ ---       │
│ str     ┆ str        ┆ str       │
╞═════════╪════════════╪═══════════╡
│ S001    ┆ 2014-01-02 ┆ Placebo   │
│ S002    ┆ 2014-01-03 ┆ Low Dose  │
│ S003    ┆ 2014-01-04 ┆ High Dose │
└─────────┴────────────┴───────────┘
""")


@pytest.fixture
def ae_raw():
    return pl.from_repr("""\
┌────────────────┬──────────┬───────────────┐
│ patient_number ┆ ae_term  ┆ ae_start_date │
│ ---            ┆ ---      ┆ ---           │
│ str            ┆ str      ┆ str           │
╞════════════════╪══════════╪═══════════════╡
│ S001           ┆ HEADACHE ┆ 2014-01-10    │
│ S001           ┆ NAUSEA   ┆ 2014-01-01    │
│ S002           ┆ RASH     ┆ 2014-02-15    │
│ S003           ┆ FATIGUE  ┆ 2014-01-04    │
└────────────────┴──────────┴───────────────┘
""")


@pytest.fixture
def vs_raw():
    return pl.from_repr("""\
┌────────────────┬──────────┬────────────┬──────────┐
│ patient_number ┆ vstestcd ┆ vs_date    ┆ vsresult │
│ ---            ┆ ---      ┆ ---        ┆ ---      │
│ str            ┆ str      ┆ str        ┆ i64      │
╞════════════════╪══════════╪════════════╪══════════╡
│ S001           ┆ SYSBP    ┆ 2013-12-20 ┆ 120      │
│ S001           ┆ SYSBP    ┆ 2014-01-01 ┆ 125      │
│ S001           ┆ SYSBP    ┆ 2014-01-10 ┆ 130      │
│ S002           ┆ DIABP    ┆ 2014-01-02 ┆ 80       │
│ S002           ┆ DIABP    ┆ 2014-01-10 ┆ 85       │
└────────────────┴──────────┴────────────┴──────────┘
""")


# ── SDTM study_day ──────────────────────────────────────────────────── #


class TestSDTMStudyDay:
    def test_study_day_from_pin(self, ae_raw, dm_df):
        result = (
            ae_raw.sdtm.assign("DOMAIN", value="AE")
            .assign("USUBJID", source="patient_number")
            .date("AESTDTC", source="ae_start_date")
            .pin("DM", dm_df)
            .study_day("AESTDY", date_col="AESTDTC")
            .to_frame()
        )
        assert "AESTDY" in result.columns
        # S001: 2014-01-10 - 2014-01-02 = 8 days → +1 = 9
        s001_days = result.filter(pl.col("USUBJID") == "S001")["AESTDY"].to_list()
        assert 9 in s001_days  # first AE
        # S001: 2014-01-01 - 2014-01-02 = -1 day (before ref, no +1)
        assert -1 in s001_days

    def test_study_day_from_explicit_dm(self, ae_raw, dm_df):
        result = (
            ae_raw.sdtm.assign("DOMAIN", value="AE")
            .assign("USUBJID", source="patient_number")
            .date("AESTDTC", source="ae_start_date")
            .study_day("AESTDY", date_col="AESTDTC", dm=dm_df)
            .to_frame()
        )
        assert "AESTDY" in result.columns

    def test_study_day_ref_in_frame(self, dm_df):
        """When RFSTDTC is already in the frame, no pin needed."""
        df = pl.from_repr("""\
┌─────────┬────────────┬────────────┐
│ USUBJID ┆ RFSTDTC    ┆ AESTDTC    │
│ ---     ┆ ---        ┆ ---        │
│ str     ┆ str        ┆ str        │
╞═════════╪════════════╪════════════╡
│ S001    ┆ 2014-01-02 ┆ 2014-01-10 │
└─────────┴────────────┴────────────┘
""")
        result = df.sdtm.study_day("AESTDY", date_col="AESTDTC").to_frame()
        assert result["AESTDY"][0] == 9

    def test_study_day_no_pin_raises(self, ae_raw):
        ns = (
            ae_raw.sdtm.assign("DOMAIN", value="AE")
            .assign("USUBJID", source="patient_number")
            .date("AESTDTC", source="ae_start_date")
        )
        with pytest.raises(LookupError, match="study_day.*pinned.*DM"):
            ns.study_day("AESTDY", date_col="AESTDTC")

    def test_study_day_same_day(self, dm_df):
        """Same day as ref → study day 1 (no day 0)."""
        df = pl.from_repr("""\
┌─────────┬────────────┬────────────┐
│ USUBJID ┆ RFSTDTC    ┆ AESTDTC    │
│ ---     ┆ ---        ┆ ---        │
│ str     ┆ str        ┆ str        │
╞═════════╪════════════╪════════════╡
│ S001    ┆ 2014-01-02 ┆ 2014-01-02 │
└─────────┴────────────┴────────────┘
""")
        result = df.sdtm.study_day("AESTDY", date_col="AESTDTC").to_frame()
        assert result["AESTDY"][0] == 1

    def test_study_day_drops_ref_col(self, ae_raw, dm_df):
        """The temp ref column is cleaned up — not in the output."""
        result = (
            ae_raw.sdtm.assign("USUBJID", source="patient_number")
            .date("AESTDTC", source="ae_start_date")
            .pin("DM", dm_df)
            .study_day("AESTDY", date_col="AESTDTC")
            .to_frame()
        )
        assert "__pin_RFSTDTC__" not in result.columns
        assert "RFSTDTC" not in result.columns


# ── SDTM baseline_flag ──────────────────────────────────────────────── #


class TestSDTMBaselineFlag:
    def test_baseline_flag_basic(self, vs_raw, dm_df):
        result = (
            vs_raw.sdtm.assign("DOMAIN", value="VS")
            .assign("USUBJID", source="patient_number")
            .assign("VSTESTCD", source="vstestcd")
            .assign("VSDTC", source="vs_date")
            .pin("DM", dm_df)
            .baseline_flag("VSBLFL", date_col="VSDTC", testcd_col="VSTESTCD")
            .to_frame()
        )
        assert "VSBLFL" in result.columns
        # S001 SYSBP: dates 2013-12-20, 2014-01-01, 2014-01-10; ref=2014-01-02
        # On or before ref: 2013-12-20, 2014-01-01 → last = 2014-01-01 → "Y"
        s001_sysbp = result.filter(
            (pl.col("USUBJID") == "S001") & (pl.col("VSTESTCD") == "SYSBP")
        ).sort("VSDTC")
        flags = s001_sysbp["VSBLFL"].to_list()
        assert flags == [None, "Y", None]

    def test_baseline_flag_no_temp_cols(self, vs_raw, dm_df):
        result = (
            vs_raw.sdtm.assign("USUBJID", source="patient_number")
            .assign("VSTESTCD", source="vstestcd")
            .assign("VSDTC", source="vs_date")
            .pin("DM", dm_df)
            .baseline_flag("VSBLFL", date_col="VSDTC", testcd_col="VSTESTCD")
            .to_frame()
        )
        temp_cols = [c for c in result.columns if c.startswith("__")]
        assert temp_cols == []

    def test_baseline_flag_explicit_dm(self, vs_raw, dm_df):
        result = (
            vs_raw.sdtm.assign("USUBJID", source="patient_number")
            .assign("VSTESTCD", source="vstestcd")
            .assign("VSDTC", source="vs_date")
            .baseline_flag("VSBLFL", date_col="VSDTC", testcd_col="VSTESTCD", dm=dm_df)
            .to_frame()
        )
        assert "VSBLFL" in result.columns


# ── Auto FK checks ──────────────────────────────────────────────────── #


class TestAutoFKCheck:
    def test_auto_fk_silent_without_pin(self, ae_raw):
        """No pin → no FK check → no warning."""
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            ae_raw.sdtm.assign("USUBJID", source="patient_number").to_frame()

    def test_auto_fk_triggers_with_pin(self, dm_df):
        """FK check fires when pin exists and orphan values are found."""
        bad_df = pl.DataFrame({"patient_number": ["S001", "ORPHAN_SUBJ"]})
        with pytest.warns(UserWarning, match="FK check"):
            bad_df.sdtm.pin("DM", dm_df).assign("USUBJID", source="patient_number").to_frame()
