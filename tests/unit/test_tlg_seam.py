"""The spec seam: ``summarize_spec`` reads the whole engine contract from the spec.

Vocabulary from CONTEXT.md: spec, ARD, uncoded, prefilter, dataset filter.
Decision record: docs/adr/0005-summary-specs-are-the-engine-contract.md.
"""

from __future__ import annotations

import polars as pl
import pytest

import fleet  # noqa: F401 — registers df.tlg
from fleet.core.exceptions import SchemaError
from fleet.tlg import AESummarySpec, Uncoded, summarize_spec

ADSL = pl.from_repr("""\
┌─────────┬─────────┐
│ USUBJID ┆ TRTA    │
│ ---     ┆ ---     │
│ str     ┆ str     │
╞═════════╪═════════╡
│ S01     ┆ Placebo │
│ S02     ┆ Placebo │
│ S03     ┆ Drug A  │
└─────────┴─────────┘
""")

#: S02 reported "HEADACHE" before MedDRA coding: AEBODSYS and AEDECOD are null.
ADAE = pl.from_repr("""\
┌─────────┬─────────┬──────────────────┬──────────┬──────────┐
│ USUBJID ┆ TRTA    ┆ AEBODSYS         ┆ AEDECOD  ┆ AETERM   │
│ ---     ┆ ---     ┆ ---              ┆ ---      ┆ ---      │
│ str     ┆ str     ┆ str              ┆ str      ┆ str      │
╞═════════╪═════════╪══════════════════╪══════════╪══════════╡
│ S01     ┆ Placebo ┆ CARDIAC DISORDERS┆ ANGINA   ┆ ANGINA   │
│ S02     ┆ Placebo ┆ null             ┆ null     ┆ HEADACHE │
│ S03     ┆ Drug A  ┆ CARDIAC DISORDERS┆ ANGINA   ┆ ANGINA   │
└─────────┴─────────┴──────────────────┴──────────┴──────────┘
""")


def _levels(ard: pl.DataFrame, variable: str) -> set[str]:
    return set(ard.filter(pl.col("variable") == variable)["variable_level"].to_list())


class TestUncoded:
    def test_default_spec_counts_the_uncoded_event_under_the_gdsr_label(self) -> None:
        ard = summarize_spec(ADAE, AESummarySpec(), groupby="TRTA", adsl=ADSL)
        assert "No Coding Available" in _levels(ard, "AEBODSYS")
        assert "No Coding Available" in _levels(ard, "AEDECOD")

    def test_uncoded_none_switches_the_fill_off(self) -> None:
        ard = summarize_spec(ADAE, AESummarySpec(uncoded=None), groupby="TRTA", adsl=ADSL)
        assert "No Coding Available" not in _levels(ard, "AEBODSYS")

    def test_sponsor_label_replaces_the_default(self) -> None:
        spec = AESummarySpec(uncoded=Uncoded(columns=["AEBODSYS", "AEDECOD"], label="UNCODED"))
        ard = summarize_spec(ADAE, spec, groupby="TRTA", adsl=ADSL)
        assert "UNCODED" in _levels(ard, "AEBODSYS")
        assert "No Coding Available" not in _levels(ard, "AEBODSYS")


class TestSeamContract:
    def test_context_comes_from_the_spec_class(self) -> None:
        ard = summarize_spec(ADAE, AESummarySpec(), groupby="TRTA", adsl=ADSL)
        assert ard["context"].unique().to_list() == ["t_ae_summary"]

    def test_group_column_falls_back_to_the_spec(self) -> None:
        ard = summarize_spec(ADAE, AESummarySpec(), adsl=ADSL)
        assert ard["group1"].unique().to_list() == ["TRTA"]

    def test_missing_required_column_is_refused(self) -> None:
        with pytest.raises(SchemaError, match="AEDECOD"):
            summarize_spec(ADAE.drop("AEDECOD"), AESummarySpec(), groupby="TRTA", adsl=ADSL)


#: S01 has a Week 2 change of 5.  S02's Week 2 change is missing.  Both carry a
#: baseline record with CHG = 0 that a change table must never summarise.
ADLB = pl.from_repr("""\
┌─────────┬─────────┬─────────┬──────────┬───────┬──────┐
│ USUBJID ┆ TRTA    ┆ PARAMCD ┆ AVISIT   ┆ ABLFL ┆ CHG  │
│ ---     ┆ ---     ┆ ---     ┆ ---      ┆ ---   ┆ ---  │
│ str     ┆ str     ┆ str     ┆ str      ┆ str   ┆ f64  │
╞═════════╪═════════╪═════════╪══════════╪═══════╪══════╡
│ S01     ┆ Placebo ┆ ALT     ┆ BASELINE ┆ Y     ┆ 0.0  │
│ S01     ┆ Placebo ┆ ALT     ┆ WEEK 2   ┆ null  ┆ 5.0  │
│ S02     ┆ Placebo ┆ ALT     ┆ BASELINE ┆ Y     ┆ 0.0  │
│ S02     ┆ Placebo ┆ ALT     ┆ WEEK 2   ┆ null  ┆ null │
└─────────┴─────────┴─────────┴──────────┴───────┴──────┘
""")


def _stat(ard: pl.DataFrame, arm: str, level: str, stat: str) -> float | None:
    cell = ard.filter(
        (pl.col("group1_level") == arm)
        & (pl.col("variable_level") == level)
        & (pl.col("stat_name") == stat)
    )
    assert cell.height == 1, cell
    return cell["stat"][0]


class TestPrefilter:
    def test_change_table_prefilter_is_visible_on_the_spec(self) -> None:
        from fleet.tlg import LBChgSpec

        assert "ABLFL" in LBChgSpec().prefilter

    def test_default_prefilter_drops_baseline_and_missing_change(self) -> None:
        from fleet.tlg import LBChgSpec

        ard = summarize_spec(ADLB, LBChgSpec(), groupby="TRTA", adsl=ADSL)
        assert "BASELINE" not in _levels(ard, "AVISIT")
        assert _stat(ard, "Placebo", "WEEK 2", "n") == 1
        assert _stat(ard, "Placebo", "WEEK 2", "mean") == 5.0

    def test_prefilter_follows_the_value_column(self) -> None:
        from fleet.tlg import LBChgSpec

        assert "PCHG" in LBChgSpec(value_col="PCHG").prefilter

    def test_change_table_without_baseline_flag_is_refused(self) -> None:
        from fleet.tlg import LBChgSpec

        with pytest.raises(SchemaError, match="ABLFL"):
            summarize_spec(ADLB.drop("ABLFL"), LBChgSpec(), groupby="TRTA", adsl=ADSL)

    def test_prefilter_none_is_the_visible_escape_hatch(self) -> None:
        from fleet.tlg import LBChgSpec

        spec = LBChgSpec(prefilter=None)
        ard = summarize_spec(ADLB.drop("ABLFL"), spec, groupby="TRTA", adsl=ADSL)
        assert "BASELINE" in _levels(ard, "AVISIT")

    def test_exposure_table_without_parcat1_is_refused(self) -> None:
        from fleet.tlg import EXSummarySpec

        adex = pl.from_repr("""\
        ┌─────────┬─────────┬─────────┬──────┐
        │ USUBJID ┆ TRTA    ┆ PARAMCD ┆ AVAL │
        │ ---     ┆ ---     ┆ ---     ┆ ---  │
        │ str     ┆ str     ┆ str     ┆ f64  │
        ╞═════════╪═════════╪═════════╪══════╡
        │ S01     ┆ Placebo ┆ TDOSE   ┆ 54.0 │
        └─────────┴─────────┴─────────┴──────┘
        """)
        with pytest.raises(SchemaError, match="PARCAT1"):
            summarize_spec(adex, EXSummarySpec(), groupby="TRTA", adsl=ADSL)

    def test_check_reports_the_missing_prefilter_column(self) -> None:
        from fleet.tlg import LBChgSpec

        report = LBChgSpec().check(ADLB.drop("ABLFL"))
        assert any("ABLFL" in line for line in report)


class TestCompositesSharePreparation:
    """The seven composites run prepare_frame before their own logic."""

    def test_ae_severity_honours_uncoded_none(self) -> None:
        from fleet.tlg import AESeveritySpec

        adae = ADAE.with_columns(pl.Series("AESEV", ["MILD", "SEVERE", "MILD"]))
        default = adae.tlg.ae.t_severity(groupby="TRTA", adsl=ADSL)
        assert "No Coding Available" in _levels(default, "AEBODSYS")
        off = adae.tlg.ae.t_severity(groupby="TRTA", adsl=ADSL, spec=AESeveritySpec(uncoded=None))
        assert "No Coding Available" not in _levels(off, "AEBODSYS")

    def test_lb_shift_dataset_filter_bites_before_the_worst_case_reduction(self) -> None:
        from fleet.tlg import LBShiftSpec

        # S01: HIGH at Week 2, back to NORMAL at Week 4.  A Week 4 table must
        # report NORMAL to NORMAL, not the Week 2 HIGH.
        adlb = pl.from_repr("""\
        ┌─────────┬─────────┬─────────┬────────┬───────┬────────┬────────┐
        │ USUBJID ┆ TRTA    ┆ PARAMCD ┆ AVISIT ┆ ABLFL ┆ BNRIND ┆ ANRIND │
        │ ---     ┆ ---     ┆ ---     ┆ ---    ┆ ---   ┆ ---    ┆ ---    │
        │ str     ┆ str     ┆ str     ┆ str    ┆ str   ┆ str    ┆ str    │
        ╞═════════╪═════════╪═════════╪════════╪═══════╪════════╪════════╡
        │ S01     ┆ Placebo ┆ ALT     ┆ WEEK 2 ┆ null  ┆ NORMAL ┆ HIGH   │
        │ S01     ┆ Placebo ┆ ALT     ┆ WEEK 4 ┆ null  ┆ NORMAL ┆ NORMAL │
        └─────────┴─────────┴─────────┴────────┴───────┴────────┴────────┘
        """)
        spec = LBShiftSpec(dataset_filter='pl.col("AVISIT") == "WEEK 4"')
        ard = adlb.tlg.lb.t_shift(groupby="TRTA", adsl=ADSL, spec=spec)
        assert _levels(ard, "SHIFT") == {"NORMAL to NORMAL"}


class TestBuilderVerbs:
    """Every spec field is settable inline: uncoded() and prefilter() included."""

    def test_uncoded_verb_lands_on_the_spec(self) -> None:
        spec = (
            ADAE.tlg.ae.population(ADSL)
            .by("TRTA")
            .uncoded(["AEBODSYS", "AEDECOD"], label="UNCODED")
            .to_spec()
        )
        assert spec.uncoded == Uncoded(columns=["AEBODSYS", "AEDECOD"], label="UNCODED")

    def test_uncoded_none_switches_the_rule_off_inline(self) -> None:
        ard = ADAE.tlg.ae.population(ADSL).by("TRTA").uncoded(None).to_ard()
        assert "No Coding Available" not in _levels(ard, "AEBODSYS")

    def test_prefilter_verb_lands_on_the_spec(self) -> None:
        spec = (
            ADLB.tlg.lb.population(ADSL)
            .by("TRTA")
            .template("lbt02")
            .prefilter('pl.col("ABLFL").ne_missing("Y")')
            .to_spec()
        )
        assert spec.prefilter == 'pl.col("ABLFL").ne_missing("Y")'

    def test_prefilter_verb_is_refused_on_a_listing(self) -> None:
        with pytest.raises(SchemaError, match="prefilter"):
            ADAE.tlg.ae.template("ael01").prefilter('pl.col("AESER") == "Y"').to_spec()
