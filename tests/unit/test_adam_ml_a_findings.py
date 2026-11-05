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


_SUBS = ["adsl", "occds", "onco", "ophtha", "peds", "vaccine", "metabolic", "neuro", "pk", "tte"]


class TestSubNamespaceState:
    """c1-336, c1-337: a sub-namespace switch keeps the reports, and .adam goes back."""

    @pytest.fixture
    def base(self) -> pl.DataFrame:
        return pl.from_repr("""\
┌─────────┬──────┐
│ USUBJID ┆ AVAL │
│ ---     ┆ ---  │
│ str     ┆ f64  │
╞═════════╪══════╡
│ S1      ┆ 1.0  │
│ S2      ┆ 2.0  │
└─────────┴──────┘
""")

    @pytest.mark.parametrize("sub", _SUBS)
    def test_the_last_comparison_survives_the_switch(self, base, sub):
        cand = base.with_columns(pl.lit(9.0).alias("AVAL"))
        ns = base.adam.compare(cand, keys="USUBJID")

        switched = getattr(ns, sub)

        assert switched.last_comparison is ns.last_comparison
        assert switched.last_comparison.is_equal is False

    def test_adam_after_occds_keeps_pins_lineage_and_domain(self, base):
        adsl = base.select("USUBJID")
        ns = base.adam.occds("ADAE").pin("ADSL", adsl).assign("AVAL2", source="AVAL")

        back = ns.adam

        assert type(back).__name__ == "AdamNamespace"
        assert back._domain == "ADAE"
        assert "ADSL" in back._pinned
        assert len(back._lineage) == len(ns._lineage) > 0
        assert back._pinned is not ns._pinned
        out = back.chg("CHG", aval="AVAL2", base="AVAL").to_frame()
        assert out["CHG"].to_list() == [0.0, 0.0]


_TTE_ADSL = """\
┌─────────┬────────────┬─────────┬────────────┬────────────┐
│ USUBJID ┆ TRTSDT     ┆ TRTSDTF ┆ EOSDT      ┆ NACTDT     │
│ ---     ┆ ---        ┆ ---     ┆ ---        ┆ ---        │
│ str     ┆ date       ┆ str     ┆ date       ┆ date       │
╞═════════╪════════════╪═════════╪════════════╪════════════╡
│ 01      ┆ 2023-01-01 ┆ D       ┆ 2023-05-05 ┆ null       │
│ 02      ┆ 2023-01-01 ┆ null    ┆ 2023-06-30 ┆ 2023-01-15 │
│ 03      ┆ 2023-01-01 ┆ null    ┆ 2023-03-31 ┆ null       │
└─────────┴────────────┴─────────┴────────────┴────────────┘
"""

_TTE_AE = """\
┌─────────┬─────────┬────────────┐
│ USUBJID ┆ AEDECOD ┆ ADT        │
│ ---     ┆ ---     ┆ ---        │
│ str     ┆ str     ┆ date       │
╞═════════╪═════════╪════════════╡
│ 01      ┆ FATIGUE ┆ 2023-02-01 │
│ 03      ┆ NAUSEA  ┆ 2023-02-15 │
└─────────┴─────────┴────────────┘
"""


class TestTimeToEvent:
    """c1-356 to c1-370: tte.param() strata, flags, trace, ties and arguments."""

    @pytest.fixture
    def adsl(self) -> pl.DataFrame:
        return pl.from_repr(_TTE_ADSL)

    @pytest.fixture
    def adae(self) -> pl.DataFrame:
        return pl.from_repr(_TTE_AE)

    def _tt(self, adsl, adae, **kwargs) -> pl.DataFrame:
        set_values = {"PARAMCD": pl.concat_str(pl.lit("TT"), pl.col("AEDECOD").str.head(3))}
        return (
            adsl.adam.tte.param(
                "TT",
                "Time to AE",
                start="TRTSDT",
                events={"AE": adae},
                by=["AEDECOD"],
                set_values_to=set_values,
                **kwargs,
            )
            .aval()
            .to_frame()
            .sort("AEDECOD", "USUBJID")
        )

    def test_an_adsl_censor_is_crossed_with_the_strata(self, adsl, adae):
        eos = adsl.select("USUBJID", ADT="EOSDT", EVNTDESC=pl.lit("END OF STUDY"))

        out = self._tt(adsl, adae, censors={1: eos})

        assert out.select("USUBJID", "AEDECOD", "CNSR", "AVAL").rows() == [
            ("01", "FATIGUE", 0, 32.0),
            ("02", "FATIGUE", 1, 181.0),
            ("03", "FATIGUE", 1, 90.0),
            ("01", "NAUSEA", 1, 125.0),
            ("02", "NAUSEA", 1, 181.0),
            ("03", "NAUSEA", 0, 46.0),
        ]

    def test_a_censor_with_only_some_by_columns_raises(self, adsl, adae):
        adae = adae.with_columns(pl.lit("GEN").alias("AEBODSYS"))
        partial = adae.select("USUBJID", "AEDECOD", "ADT", EVNTDESC=pl.lit("C"))
        with pytest.raises(DerivationError, match="column 'AEBODSYS' not found"):
            adsl.adam.tte.param(
                "TT",
                "Time to AE",
                start="TRTSDT",
                events={"AE": adae},
                censors={1: partial},
                by=["AEDECOD", "AEBODSYS"],
            )

    def test_the_drop_warning_under_by_names_the_cross(self, adsl, adae):
        with pytest.warns(UserWarning, match=r"none of the by columns \['AEDECOD'\] is crossed"):
            self._tt(adsl, adae)

    def test_startdtf_comes_from_the_start_flag(self, adsl, adae):
        rows = (
            adsl.adam.tte.param(
                "TTAE",
                "Time to AE",
                start="TRTSDT",
                events={"AE": adae},
                censors={1: adsl.select("USUBJID", ADT="EOSDT", EVNTDESC=pl.lit("EOS"))},
            )
            .to_frame()
            .sort("USUBJID")
        )

        assert rows["STARTDTF"].to_list() == ["D", None, None]

    def test_starttmf_comes_with_create_datetime(self):
        adsl = pl.from_repr("""\
┌─────────┬─────────────────────┬──────────┬──────────┐
│ USUBJID ┆ TRTSDTM             ┆ TRTSDTF  ┆ TRTSTMF  │
│ ---     ┆ ---                 ┆ ---      ┆ ---      │
│ str     ┆ datetime[μs]        ┆ str      ┆ str      │
╞═════════╪═════════════════════╪══════════╪══════════╡
│ 01      ┆ 2023-01-01 00:00:00 ┆ D        ┆ H        │
└─────────┴─────────────────────┴──────────┴──────────┘
""")
        event = pl.from_repr("""\
┌─────────┬─────────────────────┐
│ USUBJID ┆ ADT                 │
│ ---     ┆ ---                 │
│ str     ┆ datetime[μs]        │
╞═════════╪═════════════════════╡
│ 01      ┆ 2023-01-05 09:30:00 │
└─────────┴─────────────────────┘
""")
        rows = adsl.adam.tte.param(
            "TTAE", "Time to AE", start="TRTSDTM", events={"AE": event}, create_datetime=True
        ).to_frame()

        assert rows.select("STARTDTF", "STARTTMF").row(0) == ("D", "H")
        assert rows["ADTM"].dt.strftime("%H:%M").to_list() == ["09:30"]

    def test_the_trace_shows_retained_subjects_and_records_after_the_stop(self, adsl):
        late = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ ADT        │
│ ---     ┆ ---        │
│ str     ┆ date       │
╞═════════╪════════════╡
│ 02      ┆ 2023-02-05 │
└─────────┴────────────┘
""")
        from fleet.adam.tte import select_tte

        rows, trace = select_tte(
            universe=adsl,
            start="TRTSDT",
            events={"AE": late},
            censors={},
            subject_keys=["USUBJID"],
            stop_at=["NACTDT"],
            retain="censor_at_start",
        )

        assert sorted(trace.select("USUBJID", "reason").rows()) == [
            ("01", "censored at STARTDT: no record"),
            ("02", "after the stop date"),
            ("02", "censored at STARTDT: no record"),
            ("03", "censored at STARTDT: no record"),
        ]
        retained = rows.filter(pl.col("USUBJID") == "01")
        assert retained.select("SRCDOM", "SRCVAR").row(0) == ("ADSL", "TRTSDT")

    def test_a_wrong_retain_raises(self, adsl, adae):
        with pytest.raises(DerivationError, match="retain='censor_at_star' is not supported"):
            adsl.adam.tte.param(
                "TTAE",
                "Time to AE",
                start="TRTSDT",
                events={"AE": adae},
                retain="censor_at_star",
            )

    def test_a_tie_on_srcseq_warns(self, adsl):
        ae = pl.from_repr("""\
┌─────────┬────────────┬────────┐
│ USUBJID ┆ ADT        ┆ SRCSEQ │
│ ---     ┆ ---        ┆ ---    │
│ str     ┆ date       ┆ i64    │
╞═════════╪════════════╪════════╡
│ 01      ┆ 2023-01-05 ┆ 3      │
│ 01      ┆ 2023-01-05 ┆ 3      │
└─────────┴────────────┴────────┘
""")
        with pytest.warns(UserWarning, match="with respect to USUBJID, ADT, SRCSEQ"):
            adsl.adam.tte.param("TTAE", "Time to AE", start="TRTSDT", events={"AE": ae})

    def test_a_tie_on_another_date_names_the_columns(self, adsl):
        ae = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ ADT        │
│ ---     ┆ ---        │
│ str     ┆ date       │
╞═════════╪════════════╡
│ 01      ┆ 2023-01-05 │
│ 01      ┆ 2023-01-10 │
│ 01      ┆ 2023-01-10 │
└─────────┴────────────┘
""")
        with pytest.warns(UserWarning, match=r"with respect to USUBJID, ADT \(no SRCSEQ"):
            adsl.adam.tte.param("TTAE", "Time to AE", start="TRTSDT", events={"AE": ae})

    def test_srcseq_breaks_a_date_tie(self, adsl):
        src = pl.from_repr("""\
┌─────────┬────────────┬────────┐
│ USUBJID ┆ ADT        ┆ SRCSEQ │
│ ---     ┆ ---        ┆ ---    │
│ str     ┆ date       ┆ i64    │
╞═════════╪════════════╪════════╡
│ 01      ┆ 2023-01-05 ┆ 2      │
│ 01      ┆ 2023-01-05 ┆ 1      │
└─────────┴────────────┴────────┘
""")
        event = adsl.adam.tte.param(
            "TTE1", "Event", start="TRTSDT", events={"AE": src}, retain="censor_at_start"
        ).to_frame()
        censor = adsl.adam.tte.param(
            "TTE2",
            "Censor",
            start="TRTSDT",
            events={"X": src.clear()},
            censors={1: src.with_columns(EVNTDESC=pl.lit("C"))},
            retain="censor_at_start",
        ).to_frame()

        assert event.filter(pl.col("USUBJID") == "01")["SRCSEQ"].to_list() == [1]
        assert censor.filter(pl.col("USUBJID") == "01")["SRCSEQ"].to_list() == [2]

    def test_a_repeated_adsl_subject_raises(self):
        adsl = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ TRTSDT     │
│ ---     ┆ ---        │
│ str     ┆ date       │
╞═════════╪════════════╡
│ 01      ┆ 2023-01-01 │
│ 01      ┆ 2023-02-01 │
│ 02      ┆ 2023-01-01 │
└─────────┴────────────┘
""")
        event = adsl.select("USUBJID", ADT="TRTSDT")
        with pytest.raises(DerivationError, match="more than one row.*01"):
            adsl.adam.tte.param("OS", "Overall Survival", start="TRTSDT", events={"D": event})

    def test_km_data_counts_a_subject_once(self):
        adsl = pl.from_repr("""\
┌─────────┬────────────┬────────┐
│ USUBJID ┆ TRTSDT     ┆ TRT01P │
│ ---     ┆ ---        ┆ ---    │
│ str     ┆ date       ┆ str    │
╞═════════╪════════════╪════════╡
│ 01      ┆ 2023-01-01 ┆ A      │
│ 01      ┆ 2023-01-01 ┆ A      │
│ 02      ┆ 2023-01-01 ┆ B      │
└─────────┴────────────┴────────┘
""")
        event = adsl.select("USUBJID", ADT="TRTSDT").unique()
        ns = adsl.adam.tte.param(
            "OS", "Overall Survival", start="TRTSDT", events={"D": event}
        ).aval()

        assert ns.to_frame().height == 2
        assert ns.km_data("OS", by=["TRT01P"]).height == 2


class TestAgeConstants:
    """c1-166: one year is 365.25 days in corrected_age and age_in_years."""

    def test_corrected_age_uses_days(self):
        inf = pl.from_repr("""\
┌─────────┬────────┐
│ AGEDAYS ┆ GESTAG │
│ ---     ┆ ---    │
│ i64     ┆ f64    │
╞═════════╪════════╡
│ 1       ┆ 34.0   │
└─────────┴────────┘
""")
        out = (
            inf.adam.peds.corrected_age(
                "CA", age_days_col="AGEDAYS", gestational_weeks_col="GESTAG"
            )
            .adam.peds.corrected_age(
                "CA4", age_days_col="AGEDAYS", gestational_weeks_col="GESTAG", round_digits=4
            )
            .to_frame()
        )

        assert out["CA"][0] == pytest.approx((1 - 7 * 6) / 365.25, rel=1e-12)
        assert out["CA4"][0] == -0.1123

    def test_age_in_weeks_converts_with_365_25_over_7(self):
        from fleet.adam.utils import age_in_years

        df = pl.from_repr("""\
┌───────┬───────┐
│ AGE   ┆ AGEU  │
│ ---   ┆ ---   │
│ f64   ┆ str   │
╞═══════╪═══════╡
│ 52.0  ┆ WEEKS │
└───────┴───────┘
""")
        assert df.select(age_in_years())["AAGE"][0] == pytest.approx(52 * 7 / 365.25, rel=1e-12)


def test_define_xml_on_a_version_1_spec_names_fleet_migrate(tmp_path):
    """c1-142: DefineSpecGenerator gives the same hint as from_spec."""
    from fleet.core.exceptions import SpecError
    from fleet.define_xml import DefineSpecGenerator

    path = tmp_path / "define.yaml"
    path.write_text("fleet_spec_version: 1\nstudy:\n  name: S01\ndatasets: []\n")

    with pytest.raises(SpecError, match="fleet migrate --spec"):
        DefineSpecGenerator(path)


class TestBoundaryRules:
    """c1-149: one-day changes to these rules make a test fail."""

    @staticmethod
    def _temfl(ae: pl.DataFrame, **kwargs) -> list:
        out = ae.adam.occds.treatment_emergent(
            "TRTEMFL", start_date="ASTDT", end_date="AENDT", trtsdt="TRTSDT", **kwargs
        ).to_frame()
        return out["TRTEMFL"].to_list()

    def test_the_end_window_includes_its_last_day(self):
        ae = pl.from_repr("""\
┌────────────┬────────────┬────────────┬────────────┐
│ ASTDT      ┆ AENDT      ┆ TRTSDT     ┆ TRTEDT     │
│ ---        ┆ ---        ┆ ---        ┆ ---        │
│ date       ┆ date       ┆ date       ┆ date       │
╞════════════╪════════════╪════════════╪════════════╡
│ 2024-01-15 ┆ null       ┆ 2024-01-01 ┆ 2024-01-10 │
│ 2024-01-16 ┆ null       ┆ 2024-01-01 ┆ 2024-01-10 │
└────────────┴────────────┴────────────┴────────────┘
""")
        assert self._temfl(ae, trtedt="TRTEDT", end_window=5) == ["Y", None]

    def test_an_event_that_ends_on_the_first_dose_day_has_not_ended_before(self):
        ae = pl.from_repr("""\
┌───────┬────────────┬────────────┐
│ ASTDT ┆ AENDT      ┆ TRTSDT     │
│ ---   ┆ ---        ┆ ---        │
│ date  ┆ date       ┆ date       │
╞═══════╪════════════╪════════════╡
│ null  ┆ 2024-01-01 ┆ 2024-01-01 │
│ null  ┆ 2023-12-31 ┆ 2024-01-01 │
└───────┴────────────┴────────────┘
""")
        assert self._temfl(ae) == ["Y", None]

    def test_offset_days_moves_the_start_later(self):
        ae = pl.from_repr("""\
┌────────────┬───────┬────────────┐
│ ASTDT      ┆ AENDT ┆ TRTSDT     │
│ ---        ┆ ---   ┆ ---        │
│ date       ┆ date  ┆ date       │
╞════════════╪═══════╪════════════╡
│ 2023-12-31 ┆ null  ┆ 2024-01-01 │
│ 2024-01-01 ┆ null  ┆ 2024-01-01 │
│ 2024-01-02 ┆ null  ┆ 2024-01-01 │
└────────────┴───────┴────────────┘
""")
        assert self._temfl(ae, offset_days=1) == [None, None, "Y"]

    def test_study_day_from_the_pin_is_1_on_the_reference_day(self):
        adsl = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ TRTSDT     │
│ ---     ┆ ---        │
│ str     ┆ date       │
╞═════════╪════════════╡
│ S1      ┆ 2024-01-02 │
└─────────┴────────────┘
""")
        ae = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ ASTDT      │
│ ---     ┆ ---        │
│ str     ┆ date       │
╞═════════╪════════════╡
│ S1      ┆ 2024-01-01 │
│ S1      ┆ 2024-01-02 │
│ S1      ┆ 2024-01-03 │
└─────────┴────────────┘
""")
        out = (
            ae.adam.occds.pin("ADSL", adsl)
            .study_day("ASTDY", date_col="ASTDT", ref_col="TRTSDT")
            .to_frame()
        )

        assert "TRTSDT" not in out.columns
        assert out["ASTDY"].to_list() == [-1, 1, 2]
