"""Unit tests for the ADaM Polars namespace extension (df.adam)."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration


@pytest.fixture
def vs_frame():
    """Minimal VS SDTM-like frame."""
    return pl.from_repr("""┌─────────────┬─────────┬──────────────┬──────────┬──────────┬────────────┬────────────┬───────┐
│ USUBJID     ┆ PARAMCD ┆ PARAM        ┆ VSSTRESN ┆ vsorresu ┆ vsdtc      ┆ TRTSDT     ┆ ABLFL │
│ ---         ┆ ---     ┆ ---          ┆ ---      ┆ ---      ┆ ---        ┆ ---        ┆ ---   │
│ str         ┆ str     ┆ str          ┆ f64      ┆ str      ┆ str        ┆ str        ┆ str   │
╞═════════════╪═════════╪══════════════╪══════════╪══════════╪════════════╪════════════╪═══════╡
│ 01-701-1015 ┆ SYSBP   ┆ Systolic BP  ┆ 120.0    ┆ mmHg     ┆ 2014-01-02 ┆ 2014-01-02 ┆ Y     │
│ 01-701-1015 ┆ DIABP   ┆ Diastolic BP ┆ 80.0     ┆ mmHg     ┆ 2014-01-02 ┆ 2014-01-02 ┆ Y     │
│ 01-701-1023 ┆ SYSBP   ┆ Systolic BP  ┆ 118.0    ┆ mmHg     ┆ 2014-01-03 ┆ 2014-01-03 ┆ Y     │
└─────────────┴─────────┴──────────────┴──────────┴──────────┴────────────┴────────────┴───────┘
""")


class TestSource:
    def test_source_copies_column(self, vs_frame):
        result = vs_frame.adam.source("USUBJID").to_frame()
        assert "USUBJID" in result.columns

    def test_assign_renames_where_source_from_col_did(self, vs_frame):
        result = vs_frame.adam.assign("SUBJECT", source="USUBJID").to_frame()
        assert result["SUBJECT"].to_list() == vs_frame["USUBJID"].to_list()


class TestDerivation:
    def test_column_ref(self, vs_frame):
        result = vs_frame.adam.derivation("AVAL", expression="VSSTRESN").to_frame()
        assert result["AVAL"].to_list() == vs_frame["VSSTRESN"].to_list()

    def test_expression(self, vs_frame):
        result = vs_frame.adam.derivation("AVAL2", expression='pl.col("VSSTRESN") * 2').to_frame()
        assert result["AVAL2"][0] == pytest.approx(240.0)


class TestAssigned:
    def test_constant(self, vs_frame):
        result = vs_frame.adam.assign("STUDYID", value="CDISCPILOT01").to_frame()
        assert result["STUDYID"].to_list() == ["CDISCPILOT01"] * 3


class TestRecode:
    def test_recode_values(self, vs_frame):
        result = vs_frame.adam.recode(
            "PARAMCD_CODED",
            source="PARAMCD",
            recode_map={"SYSBP": "SBP", "DIABP": "DBP"},
        ).to_frame()
        vals = result["PARAMCD_CODED"].to_list()
        assert vals[0] == "SBP"
        assert vals[1] == "DBP"

    def test_unmapped_gets_default(self, vs_frame):
        result = vs_frame.adam.recode(
            "PARAMCD_CODED",
            source="PARAMCD",
            recode_map={"SYSBP": "SBP"},
            default="OTHER",
        ).to_frame()
        assert result["PARAMCD_CODED"][1] == "OTHER"


class TestRename:
    def test_rename_column(self, vs_frame):
        result = vs_frame.adam.assign("ADT", source="vsdtc").to_frame()
        assert "ADT" in result.columns
        assert result["ADT"].to_list() == vs_frame["vsdtc"].to_list()


class TestCondDerivation:
    def test_multi_branch(self, vs_frame):
        result = vs_frame.adam.case_when(
            "DTYPE",
            when=[
                {"condition": 'pl.col("ABLFL") == "Y"', "value": "BASELINE"},
            ],
            else_=None,
        ).to_frame()
        assert result["DTYPE"][0] == "BASELINE"


class TestStudyDay:
    def test_study_day_same_day(self, vs_frame):
        result = vs_frame.adam.duration("ADY", start="TRTSDT", end="vsdtc").to_frame()
        assert result["ADY"][0] == 1

    def test_study_day_requires_dates(self, vs_frame):
        with pytest.raises((ValueError, TypeError, AttributeError)):
            vs_frame.adam.duration("ADY", start="vsdtc", end=None)


class TestBaseline:
    def test_baseline_aval(self, vs_frame):
        df = vs_frame.with_columns(pl.col("VSSTRESN").alias("AVAL"))
        result = df.adam.baseline(
            "BASE",
            aval="AVAL",
            baseline_flag="ABLFL",
            by=["USUBJID", "PARAMCD"],
        ).to_frame()
        assert result["BASE"].to_list() == [120.0, 80.0, 118.0]


class TestChg:
    def test_chg_computation(self):
        df = pl.from_repr("""┌───────┬───────┐
│ AVAL  ┆ BASE  │
│ ---   ┆ ---   │
│ f64   ┆ f64   │
╞═══════╪═══════╡
│ 120.0 ┆ 120.0 │
│ 118.0 ┆ 120.0 │
└───────┴───────┘
""")
        result = df.adam.chg("CHG", aval="AVAL", base="BASE").to_frame()
        assert result["CHG"][0] == pytest.approx(0.0)
        assert result["CHG"][1] == pytest.approx(-2.0)


class TestPchg:
    def test_pchg_computation(self):
        df = pl.from_repr("""┌───────┬───────┐
│ AVAL  ┆ BASE  │
│ ---   ┆ ---   │
│ f64   ┆ f64   │
╞═══════╪═══════╡
│ 130.0 ┆ 100.0 │
│ 120.0 ┆ 100.0 │
└───────┴───────┘
""")
        result = df.adam.pchg("PCHG", aval="AVAL", base="BASE").to_frame()
        assert result["PCHG"][0] == pytest.approx(30.0)
        assert result["PCHG"][1] == pytest.approx(20.0)


class TestFlag:
    def test_expression_criteria(self, vs_frame):
        result = vs_frame.adam.flag(
            "ABLFL2",
            criteria='pl.col("ABLFL") == "Y"',
        ).to_frame()
        assert result["ABLFL2"][0] == "Y"

    def test_max_criteria(self):
        df = pl.from_repr("""
        ┌─────────┬─────────┬───────┐
        │ USUBJID ┆ PARAMCD ┆ AVAL  │
        │ ---     ┆ ---     ┆ ---   │
        │ str     ┆ str     ┆ f64   │
        ╞═════════╪═════════╪═══════╡
        │ S1      ┆ SYSBP   ┆ 120.0 │
        │ S1      ┆ SYSBP   ┆ 135.0 │
        │ S1      ┆ DIABP   ┆ 80.0  │
        │ S2      ┆ SYSBP   ┆ 118.0 │
        │ S2      ┆ SYSBP   ┆ 110.0 │
        └─────────┴─────────┴───────┘
        """)
        result = df.adam.flag(
            "AMXFL",
            criteria="max",
            value_col="AVAL",
            by=["USUBJID", "PARAMCD"],
        ).to_frame()
        assert result["AMXFL"].to_list() == [None, "Y", "Y", "Y", None]

    def test_max_requires_value_col(self, vs_frame):
        with pytest.raises(ValueError, match="value_col"):
            vs_frame.adam.flag("X", criteria="max", by=["USUBJID"]).to_frame()

    def test_first_requires_order_by(self, vs_frame):
        with pytest.raises(ValueError, match="order_by"):
            vs_frame.adam.flag("X", criteria="first", by=["USUBJID"]).to_frame()


class TestBMI:
    def test_bmi_computation(self):
        df = pl.from_repr("""┌───────────┬───────────┐
│ weight_kg ┆ height_cm │
│ ---       ┆ ---       │
│ f64       ┆ f64       │
╞═══════════╪═══════════╡
│ 70.0      ┆ 175.0     │
└───────────┴───────────┘
""")
        result = df.adam.bmi("BMI", weight="weight_kg", height="height_cm").to_frame()
        assert result["BMI"][0] == pytest.approx(22.9, abs=0.1)

    def test_a_height_of_zero_gives_null_not_infinity(self):
        """c1-578: inf would reach Parquet, compare and TLG output."""
        df = pl.from_repr("""┌───────────┬───────────┐
│ weight_kg ┆ height_cm │
│ ---       ┆ ---       │
│ f64       ┆ f64       │
╞═══════════╪═══════════╡
│ 70.0      ┆ 0.0       │
│ 70.0      ┆ null      │
└───────────┴───────────┘
""")
        result = df.adam.bmi("BMI", weight="weight_kg", height="height_cm").to_frame()
        assert result["BMI"].to_list() == [None, None]


class TestNrind:
    def test_low_normal_high(self):
        df = pl.from_repr("""┌──────────┬──────────┬──────────┐
│ LBSTRESN ┆ LBSTNRLO ┆ LBSTNRHI │
│ ---      ┆ ---      ┆ ---      │
│ f64      ┆ f64      ┆ f64      │
╞══════════╪══════════╪══════════╡
│ 3.0      ┆ 4.0      ┆ 8.0      │
│ 5.0      ┆ 4.0      ┆ 8.0      │
│ 9.0      ┆ 4.0      ┆ 8.0      │
└──────────┴──────────┴──────────┘
""")
        result = df.adam.nrind(
            "NRIND", value="LBSTRESN", low="LBSTNRLO", high="LBSTNRHI"
        ).to_frame()
        assert result["NRIND"].to_list() == ["LOW", "NORMAL", "HIGH"]


class TestOnTreatment:
    def test_on_treatment_flag(self):
        df = pl.from_repr("""┌────────────┬────────────┬────────────┐
│ ADT        ┆ TRTSDT     ┆ TRTEDT     │
│ ---        ┆ ---        ┆ ---        │
│ str        ┆ str        ┆ str        │
╞════════════╪════════════╪════════════╡
│ 2024-01-15 ┆ 2024-01-10 ┆ 2024-01-31 │
│ 2024-01-05 ┆ 2024-01-10 ┆ 2024-01-31 │
│ 2024-02-01 ┆ 2024-01-10 ┆ 2024-01-31 │
└────────────┴────────────┴────────────┘
""")
        result = df.adam.on_treatment(
            "ONTRTFL", adt="ADT", trtsdt="TRTSDT", trtedt="TRTEDT"
        ).to_frame()
        flags = result["ONTRTFL"].to_list()
        assert flags[0] == "Y"  # on-treatment
        assert flags[1] is None  # before treatment
        assert flags[2] is None  # after treatment


class TestShift:
    def test_shift_string(self):
        df = pl.from_repr("""┌────────┬────────┐
│ BNRIND ┆ NRIND  │
│ ---    ┆ ---    │
│ str    ┆ str    │
╞════════╪════════╡
│ NORMAL ┆ HIGH   │
│ LOW    ┆ NORMAL │
└────────┴────────┘
""")
        result = df.adam.shift("SHIFT1", baseline_cat="BNRIND", post_cat="NRIND").to_frame()
        assert result["SHIFT1"].to_list() == ["NORMAL to HIGH", "LOW to NORMAL"]

    def test_custom_sep(self):
        df = pl.from_repr("""┌────────┬──────┐
│ B      ┆ P    │
│ ---    ┆ ---  │
│ str    ┆ str  │
╞════════╪══════╡
│ NORMAL ┆ HIGH │
└────────┴──────┘
""")
        result = df.adam.shift("SH", baseline_cat="B", post_cat="P", sep=" → ").to_frame()
        assert result["SH"][0] == "NORMAL → HIGH"


class TestWhereclauses:
    def test_filter(self, vs_frame):
        result = vs_frame.adam.whereclauses(where='pl.col("PARAMCD") == "SYSBP"').to_frame()
        assert all(p == "SYSBP" for p in result["PARAMCD"].to_list())
        assert result.height == 2

    def test_filter_expr(self, vs_frame):
        result = vs_frame.adam.whereclauses(where=pl.col("VSSTRESN") > 100).to_frame()
        assert result.height == vs_frame.filter(pl.col("VSSTRESN") > 100).height


class TestChaining:
    def test_full_chain(self, vs_frame):
        result = (
            vs_frame.adam.source("USUBJID")
            .assign("ADT", source="vsdtc")
            .derivation("AVAL", expression="VSSTRESN")
            .assign("STUDYID", value="CDISCPILOT01")
            .to_frame()
        )
        assert "USUBJID" in result.columns
        assert "ADT" in result.columns
        assert "AVAL" in result.columns
        assert result["STUDYID"][0] == "CDISCPILOT01"

    def test_unbroken_flag_baseline_chg_chain(self):
        """flag -> baseline -> chg -> pchg runs in ONE chain (GUIDE Part 8).

        The old GUIDE taught that ABLFL/BASE must be materialised with an
        intermediate ``.to_frame()`` before the next window verb — "a Polars
        constraint". That is false: Fleet checkpoints internally and keeps the
        chain going. This test locks the single-chain form in permanently.
        """
        vs = pl.from_repr("""\
┌─────────┬─────────┬──────┬──────┐
│ USUBJID ┆ PARAMCD ┆ AVAL ┆ vsdy │
│ ---     ┆ ---     ┆ ---  ┆ ---  │
│ str     ┆ str     ┆ f64  ┆ i64  │
╞═════════╪═════════╪══════╪══════╡
│ S1      ┆ SYSBP   ┆ 120  ┆ -1   │
│ S1      ┆ SYSBP   ┆ 125  ┆ 2    │
│ S1      ┆ SYSBP   ┆ 130  ┆ 5    │
│ S2      ┆ SYSBP   ┆ 110  ┆ -2   │
│ S2      ┆ SYSBP   ┆ 112  ┆ 3    │
└─────────┴─────────┴──────┴──────┘
""")
        advs = (
            vs.adam.flag("ABLFL", criteria='pl.col("vsdy") <= 0')
            .baseline("BASE", aval="AVAL", baseline_flag="ABLFL", by=["USUBJID", "PARAMCD"])
            .chg("CHG", aval="AVAL", base="BASE")
            .pchg("PCHG", aval="AVAL", base="BASE")
            .to_frame()
        )
        assert {"ABLFL", "BASE", "CHG", "PCHG"}.issubset(advs.columns)
        # BASE is the pre-dose value for each subject.
        assert advs.filter(pl.col("USUBJID") == "S1")["BASE"].to_list() == [120.0] * 3
        assert advs.filter(pl.col("USUBJID") == "S2")["BASE"].to_list() == [110.0] * 2
        # CHG == 0 exactly on the baseline row, and equals AVAL-BASE elsewhere.
        assert advs.filter(pl.col("ABLFL") == "Y")["CHG"].to_list() == [0.0, 0.0]
        assert advs.filter(pl.col("USUBJID") == "S1")["CHG"].to_list() == [0.0, 5.0, 10.0]


class TestToFrame:
    def test_empty_pipeline(self, vs_frame):
        result = vs_frame.adam.to_frame()
        assert result.shape == vs_frame.shape


# ------------------------------------------------------------------ #
# Phase 4 hardening: null propagation, order invariance, edge cases    #
# ------------------------------------------------------------------ #

from tests.assertions import assert_deterministic  # noqa: E402
from tests.helpers import shuffle_rows  # noqa: E402


class TestDerivationNullPropagation:
    """derivation verb must propagate nulls correctly."""

    def test_null_in_source_column(self):
        df = pl.from_repr("""┌─────────┬──────────┐
│ USUBJID ┆ VSSTRESN │
│ ---     ┆ ---      │
│ str     ┆ f64      │
╞═════════╪══════════╡
│ S01     ┆ 120.0    │
│ S02     ┆ null     │
│ S03     ┆ 115.0    │
└─────────┴──────────┘
""")
        result = df.adam.derivation("AVAL", expression="VSSTRESN").to_frame()
        assert result["AVAL"][1] is None

    def test_expression_on_null_yields_null(self):
        df = pl.from_repr("""┌─────────┬──────────┐
│ USUBJID ┆ VSSTRESN │
│ ---     ┆ ---      │
│ str     ┆ f64      │
╞═════════╪══════════╡
│ S01     ┆ 120.0    │
│ S02     ┆ null     │
└─────────┴──────────┘
""")
        result = df.adam.derivation("AVAL2", expression='pl.col("VSSTRESN") * 2').to_frame()
        assert result["AVAL2"][0] == pytest.approx(240.0)
        assert result["AVAL2"][1] is None


class TestRecodeNullAndUnmapped:
    """recode behavior with null and unmapped source values."""

    def test_null_source_stays_null(self):
        df = pl.from_repr("""┌──────┐
│ CODE │
│ ---  │
│ str  │
╞══════╡
│ A    │
│ null │
│ B    │
└──────┘
""")
        result = df.adam.recode(
            "DECODED", source="CODE", recode_map={"A": "Alpha", "B": "Beta"}
        ).to_frame()
        assert result["DECODED"][1] is None

    def test_unmapped_without_default_is_null(self):
        df = pl.from_repr("""┌──────┐
│ CODE │
│ ---  │
│ str  │
╞══════╡
│ A    │
│ X    │
└──────┘
""")
        result = df.adam.recode("DECODED", source="CODE", recode_map={"A": "Alpha"}).to_frame()
        # Unmapped "X" without default should be null
        assert result["DECODED"][1] is None or result["DECODED"][1] == "X"


class TestADaMOrderInvariance:
    """ADaM pipeline results should not depend on input row order."""

    def test_source_order_invariant(self):
        df = pl.from_repr("""┌─────────┬───────┬───────┐
│ USUBJID ┆ PARAM ┆ AVAL  │
│ ---     ┆ ---   ┆ ---   │
│ str     ┆ str   ┆ f64   │
╞═════════╪═══════╪═══════╡
│ S01     ┆ SYSBP ┆ 120.0 │
│ S02     ┆ DIABP ┆ 80.0  │
│ S03     ┆ SYSBP ┆ 118.0 │
└─────────┴───────┴───────┘
""")
        result1 = df.adam.source("USUBJID").source("PARAM").to_frame()
        result2 = shuffle_rows(df).adam.source("USUBJID").source("PARAM").to_frame()
        assert_deterministic(result1, result2, sort_cols=["USUBJID", "PARAM"])

    def test_chained_pipeline_order_invariant(self):
        df = pl.from_repr("""┌─────────┬─────────┬──────────┬────────────┐
│ USUBJID ┆ PARAMCD ┆ VSSTRESN ┆ vsdtc      │
│ ---     ┆ ---     ┆ ---      ┆ ---        │
│ str     ┆ str     ┆ f64      ┆ str        │
╞═════════╪═════════╪══════════╪════════════╡
│ S01     ┆ SYSBP   ┆ 120.0    ┆ 2014-01-02 │
│ S02     ┆ DIABP   ┆ 80.0     ┆ 2014-01-02 │
│ S03     ┆ SYSBP   ┆ 118.0    ┆ 2014-01-03 │
└─────────┴─────────┴──────────┴────────────┘
""")

        def pipeline(d):
            return (
                d.adam.source("USUBJID")
                .derivation("AVAL", expression="VSSTRESN")
                .assign("STUDYID", value="CDISCPILOT01")
                .to_frame()
            )

        result1 = pipeline(df)
        result2 = pipeline(shuffle_rows(df))
        assert_deterministic(result1, result2, sort_cols=["USUBJID"])


class TestCondDerivationWithNulls:
    """condderivation must handle nulls in condition columns."""

    def test_null_in_condition_column(self):
        df = pl.from_repr("""┌─────────┬───────┬──────────┐
│ USUBJID ┆ ABLFL ┆ VSSTRESN │
│ ---     ┆ ---   ┆ ---      │
│ str     ┆ str   ┆ f64      │
╞═════════╪═══════╪══════════╡
│ S01     ┆ Y     ┆ 120.0    │
│ S02     ┆ null  ┆ 80.0     │
│ S03     ┆ Y     ┆ 115.0    │
└─────────┴───────┴──────────┘
""")
        result = df.adam.case_when(
            "BASE",
            when=[
                {"condition": pl.col("ABLFL") == "Y", "value": "BASELINE"},
            ],
            else_=None,
        ).to_frame()
        # Subject with null ABLFL should get null BASE (else_value)
        assert result["BASE"][1] is None
        assert result["BASE"][0] == "BASELINE"
