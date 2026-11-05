"""Regression tests for the medium and low ADaM audit findings of package ml-adam-a."""

from __future__ import annotations

import warnings
from datetime import date

import polars as pl
import pytest

import fleet  # noqa: F401 — registers namespaces
from fleet.core.exceptions import DerivationError


class TestWrongStringsRaise:
    """c1-140: a misspelled column or keyword raises instead of a silent value."""

    @pytest.fixture
    def adsl(self) -> pl.DataFrame:
        return pl.from_repr("""\
┌─────────┬────────────┬────────────┬────────┐
│ USUBJID ┆ AP01SDT    ┆ AP01EDT    ┆ TRT01P │
│ ---     ┆ ---        ┆ ---        ┆ ---    │
│ str     ┆ date       ┆ date       ┆ str    │
╞═════════╪════════════╪════════════╪════════╡
│ S1      ┆ 2024-01-01 ┆ 2024-02-01 ┆ DRUG A │
│ S2      ┆ 2024-01-03 ┆ 2024-02-03 ┆ DRUG B │
└─────────┴────────────┴────────────┴────────┘
""")

    def test_a_misspelled_treatment_column_raises(self, adsl):
        period = {"number": 1, "start": "AP01SDT", "end": "AP01EDT", "treatment": "TRT01PP"}
        with pytest.raises(DerivationError, match="'TRT01PP' not found. Did you mean 'TRT01P'"):
            adsl.adam.adsl.derive_period(periods=[period])

    def test_a_treatment_value_is_a_literal(self, adsl):
        period = {"number": 1, "start": "AP01SDT", "end": "AP01EDT", "treatment_value": "DRUG A"}

        out = adsl.adam.adsl.derive_period(periods=[period]).to_frame()

        assert out["TRT01P"].to_list() == ["DRUG A", "DRUG A"]

    def test_a_misspelled_impute_value_raises(self):
        vs = pl.from_repr("""\
┌─────────┬─────────┐
│ USUBJID ┆ VSDTC   │
│ ---     ┆ ---     │
│ str     ┆ str     │
╞═════════╪═════════╡
│ A       ┆ 2021-03 │
└─────────┴─────────┘
""")
        with pytest.raises(DerivationError, match="impute='fist'.*Did you mean 'first'"):
            vs.adam.date("ASTDT", source="VSDTC", impute="fist")


_VS = """\
┌─────────┬───────────┬─────────┬───────┐
│ USUBJID ┆ AVISIT    ┆ PARAMCD ┆ AVAL  │
│ ---     ┆ ---       ┆ ---     ┆ ---   │
│ str     ┆ str       ┆ str     ┆ f64   │
╞═════════╪═══════════╪═════════╪═══════╡
│ S01     ┆ SCREENING ┆ HEIGHT  ┆ 170.0 │
│ S01     ┆ SCREENING ┆ WEIGHT  ┆ 70.0  │
│ S01     ┆ BASELINE  ┆ WEIGHT  ┆ 71.0  │
│ S01     ┆ WEEK 2    ┆ WEIGHT  ┆ 72.0  │
│ S02     ┆ BASELINE  ┆ HEIGHT  ┆ 180.0 │
│ S02     ┆ BASELINE  ┆ WEIGHT  ┆ null  │
└─────────┴───────────┴─────────┴───────┘
"""

_BMI = pl.col("W") / (pl.col("H") / 100) ** 2


class TestDeriveParam:
    """c1-320, c1-321, c1-322, c1-326, c1-327: derive_param follows admiral derive_param_computed."""

    def _bmi(self, vs: pl.DataFrame, **kwargs) -> pl.DataFrame:
        out = vs.adam.derive_param(
            set_values_to={"PARAMCD": "BMI"}, analysis_value=_BMI, **kwargs
        ).to_frame()
        return out.filter(pl.col("PARAMCD") == "BMI").select("USUBJID", "AVISIT", "AVAL")

    def test_constant_parameters_give_one_bmi_per_visit(self):
        out = self._bmi(
            pl.from_repr(_VS),
            by=["USUBJID", "AVISIT"],
            constant_by=["USUBJID"],
            constant_parameters={"H": "HEIGHT"},
            parameter_filter={"W": "WEIGHT"},
        )

        s01 = out.filter(pl.col("USUBJID") == "S01")
        assert s01["AVISIT"].to_list() == ["SCREENING", "BASELINE", "WEEK 2"]
        assert s01["AVAL"].round(6).to_list() == [24.221453, 24.567474, 24.913495]

    def test_constant_by_outside_by_raises(self):
        with pytest.raises(DerivationError, match="subset of by"):
            pl.from_repr(_VS).adam.derive_param(
                by=["USUBJID", "AVISIT"],
                constant_by=["STUDYID"],
                constant_parameters={"H": "HEIGHT"},
                parameter_filter={"W": "WEIGHT"},
                set_values_to={"PARAMCD": "BMI"},
                analysis_value=_BMI,
            )

    def test_a_null_component_adds_no_record_by_default(self):
        kwargs = {"by": ["USUBJID", "AVISIT"], "parameter_filter": {"W": "WEIGHT", "H": "HEIGHT"}}
        vs = pl.from_repr(_VS)

        default = self._bmi(vs, **kwargs)
        kept = self._bmi(vs, keep_nas=True, **kwargs)

        assert default["USUBJID"].to_list() == ["S01"]
        assert kept.rows() == [
            ("S01", "SCREENING", pytest.approx(24.221453)),
            ("S02", "BASELINE", None),
        ]

    def test_a_paramcd_with_no_record_warns(self):
        with pytest.warns(UserWarning, match="'WEIGHTT'. Did you mean 'WEIGHT'"):
            out = self._bmi(
                pl.from_repr(_VS),
                by=["USUBJID", "AVISIT"],
                parameter_filter={"W": "WEIGHTT", "H": "HEIGHT"},
            )
        assert out.height == 0

    def test_an_expression_in_set_values_to_raises(self):
        with pytest.raises(DerivationError, match="derive_param.*expression"):
            pl.from_repr(_VS).adam.derive_param(
                by="USUBJID",
                parameter_filter={"W": "WEIGHT"},
                set_values_to={"PARAMCD": "X", "AVISIT": pl.col("AVISIT").first()},
                analysis_value=pl.col("W"),
            )


class TestSummaryRecords:
    """c1-326: an expression in set_values_to is evaluated per group."""

    def test_adt_takes_the_group_minimum(self):
        advs = pl.from_repr("""\
┌─────────┬─────────┬───────────┬───────┬────────────┐
│ USUBJID ┆ PARAMCD ┆ PARAM     ┆ AVAL  ┆ ADT        │
│ ---     ┆ ---     ┆ ---       ┆ ---   ┆ ---        │
│ str     ┆ str     ┆ str       ┆ f64   ┆ date       │
╞═════════╪═════════╪═══════════╪═══════╪════════════╡
│ S01     ┆ QTCF    ┆ QTcF (ms) ┆ 400.0 ┆ 2024-02-01 │
│ S01     ┆ QTCF    ┆ QTcF (ms) ┆ 420.0 ┆ 2024-02-02 │
└─────────┴─────────┴───────────┴───────┴────────────┘
""")
        out = advs.adam.derive_summary_records(
            by=["USUBJID", "PARAMCD", "PARAM"],
            set_values_to={"DTYPE": "AVERAGE", "ADT": pl.col("ADT").min()},
        ).to_frame()

        new = out.filter(pl.col("DTYPE") == "AVERAGE")
        assert new.select("PARAM", "AVAL", "ADT").rows() == [("QTcF (ms)", 410.0, date(2024, 2, 1))]


class TestByAsString:
    """c1-327: a str by is one column, so the duplicate check still runs."""

    def test_baseline_with_a_str_by_raises_on_two_flags(self):
        bl = pl.from_repr("""\
┌─────────┬─────────┬───────┬───────┐
│ USUBJID ┆ PARAMCD ┆ AVAL  ┆ ABLFL │
│ ---     ┆ ---     ┆ ---   ┆ ---   │
│ str     ┆ str     ┆ f64   ┆ str   │
╞═════════╪═════════╪═══════╪═══════╡
│ S1      ┆ SYS     ┆ 120.0 ┆ Y     │
│ S1      ┆ SYS     ┆ 130.0 ┆ Y     │
│ S1      ┆ SYS     ┆ 125.0 ┆ null  │
└─────────┴─────────┴───────┴───────┘
""")
        with pytest.raises(DerivationError, match="more than one"):
            bl.adam.baseline("BASE", aval="AVAL", baseline_flag="ABLFL", by="USUBJID")

    def test_seq_with_a_str_by(self):
        ae = pl.from_repr("""\
┌─────────┬───────┐
│ USUBJID ┆ ASTDY │
│ ---     ┆ ---   │
│ str     ┆ i64   │
╞═════════╪═══════╡
│ S1      ┆ 5     │
│ S2      ┆ 1     │
│ S1      ┆ 2     │
└─────────┴───────┘
""")
        out = ae.adam.seq("ASEQ", order_by="ASTDY", by="USUBJID").to_frame()

        assert out.sort("USUBJID", "ASEQ").rows() == [("S1", 2, 1), ("S1", 5, 2), ("S2", 1, 1)]


class TestGradingArguments:
    """c1-331, c1-332, c1-391: grading stops or warns on a value it cannot grade."""

    @pytest.fixture
    def lb(self) -> pl.DataFrame:
        return pl.from_repr("""\
┌──────────┬─────────┬───────┬───────┐
│ ATOXDSCL ┆ AVAL    ┆ AVALU ┆ ANRLO │
│ ---      ┆ ---     ┆ ---   ┆ ---   │
│ str      ┆ f64     ┆ str   ┆ f64   │
╞══════════╪═════════╪═══════╪═══════╡
│ HGB      ┆ 99.9996 ┆ g/L   ┆ 120.0 │
└──────────┴─────────┴───────┴───────┘
""")

    def test_a_term_with_no_criteria_warns(self, lb):
        with pytest.warns(UserWarning, match=r"no criteria in any direction.*\['HGB'\]"):
            out = lb.adam.atoxgr(
                "ATOXGRL", direction="L", term_var="ATOXDSCL", unit_var="AVALU"
            ).to_frame()
        assert out["ATOXGRL"].to_list() == [None]

    def test_a_term_with_criteria_in_the_other_direction_does_not_warn(self, lb):
        lb = lb.with_columns(pl.lit("Anemia").alias("ATOXDSCL"))
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            lb.adam.atoxgr("ATOXGRH", direction="H", term_var="ATOXDSCL", unit_var="AVALU")

    @pytest.mark.parametrize("signif_dig", [0, -1, 2.5])
    def test_signif_dig_must_be_a_positive_integer(self, lb, signif_dig):
        with pytest.raises(DerivationError, match="signif_dig"):
            lb.adam.atoxgr(
                "ATOXGRL",
                direction="L",
                term_var="ATOXDSCL",
                unit_var="AVALU",
                signif_dig=signif_dig,
            )

    def test_combine_grades_rejects_a_grade_outside_0_to_4(self):
        adlb = pl.from_repr("""\
┌─────────┬─────────┬──────────┬──────────┐
│ ATOXGRL ┆ ATOXGRH ┆ ATOXDSCL ┆ ATOXDSCH │
│ ---     ┆ ---     ┆ ---      ┆ ---      │
│ str     ┆ str     ┆ str      ┆ str      │
╞═════════╪═════════╪══════════╪══════════╡
│ G3      ┆ 0       ┆ Anemia   ┆ Hgb incr │
│ -1      ┆ 0       ┆ Anemia   ┆ Hgb incr │
│ 10      ┆ 0       ┆ Anemia   ┆ Hgb incr │
│ 5       ┆ 0       ┆ Anemia   ┆ Hgb incr │
└─────────┴─────────┴──────────┴──────────┘
""")
        with pytest.raises(DerivationError, match=r"ATOXGRL holds \['-1', '10', '5', 'G3'\]"):
            adlb.adam.combine_grades("ATOXGR")

    def test_combine_grades_rejects_a_numeric_grade(self):
        adlb = pl.from_repr("""\
┌─────────┬─────────┬──────────┬──────────┐
│ ATOXGRL ┆ ATOXGRH ┆ ATOXDSCL ┆ ATOXDSCH │
│ ---     ┆ ---     ┆ ---      ┆ ---      │
│ i64     ┆ str     ┆ str      ┆ str      │
╞═════════╪═════════╪══════════╪══════════╡
│ 3       ┆ 0       ┆ Anemia   ┆ Hgb incr │
└─────────┴─────────┴──────────┴──────────┘
""")
        with pytest.raises(DerivationError, match="ATOXGRL is Int64, not text"):
            adlb.adam.combine_grades("ATOXGR")
