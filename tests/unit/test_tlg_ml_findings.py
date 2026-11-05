"""Regression tests for the medium and low TLG audit findings (package ml-tlg).

Each test names its finding ID.  The data is inline (``pl.from_repr``).
"""

from __future__ import annotations

import math
import warnings
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

import fleet  # noqa: F401 — registers df.tlg
import fleet.tlg as tlg
from fleet import cli
from fleet.core.exceptions import SchemaError
from fleet.tlg import (
    AEListingSpec,
    AESummarySpec,
    ChoiceOption,
    Column,
    DMSummarySpec,
    DSDeathsSpec,
    EGChgSpec,
    EXSummarySpec,
    GroupPool,
    InteractiveBlock,
    LBAbnormalSpec,
    LBChgSpec,
    LBListingSpec,
    LBShiftSpec,
    LBSummarySpec,
    OverallStat,
    RenderMetadata,
    Row,
    Statistic,
    ard_to_table_model,
    listing_to_model,
    paginate,
    paginate_listing,
    render_html,
    render_listing_html,
    summarize_ard,
)
from fleet.tlg._ard import worst_case


def _run(argv: list[str]) -> int:
    """Invoke ``cli.main`` and return its exit code (0 when it returns)."""
    try:
        cli.main(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _stats(ard: pl.DataFrame, **match: str) -> dict[str, float | None]:
    """stat_name -> stat for the ARD rows that match every column value."""
    sub = ard
    for col, value in match.items():
        sub = sub.filter(pl.col(col) == value)
    return {r["stat_name"]: r["stat"] for r in sub.iter_rows(named=True)}


# ------------------------------------------------------------------ #
# Engine: values, arms, row order                                      #
# ------------------------------------------------------------------ #

ADSL_S012 = pl.from_repr("""
┌─────────┬──────┐
│ USUBJID ┆ TRTA │
│ ---     ┆ ---  │
│ str     ┆ str  │
╞═════════╪══════╡
│ S0      ┆ A    │
│ S1      ┆ A    │
│ S2      ┆ A    │
└─────────┴──────┘
""")

_CONT = [Statistic.N_SUBJECTS, Statistic.MEAN, Statistic.SD, Statistic.MEDIAN, Statistic.MAX]


def test_c1_434_nan_counts_as_missing_with_one_warning() -> None:
    adlb = pl.from_repr("""
┌─────────┬──────┬─────────┬──────┐
│ USUBJID ┆ TRTA ┆ PARAMCD ┆ AVAL │
│ ---     ┆ ---  ┆ ---     ┆ ---  │
│ str     ┆ str  ┆ str     ┆ f64  │
╞═════════╪══════╪═════════╪══════╡
│ S0      ┆ A    ┆ ALT     ┆ 10.0 │
│ S1      ┆ A    ┆ ALT     ┆ NaN  │
│ S2      ┆ A    ┆ ALT     ┆ 20.0 │
└─────────┴──────┴─────────┴──────┘
""")
    with pytest.warns(UserWarning, match="AVAL has 1 NaN value"):
        ard = summarize_ard(
            adlb, rows=[Row(field="PARAMCD")], stats=_CONT, context="lb", adsl=ADSL_S012
        )
    stats = _stats(ard, variable="PARAMCD")
    assert stats["n"] == 2
    assert stats["mean"] == 15.0
    assert stats["sd"] == pytest.approx(7.0711, abs=1e-4)
    assert stats["median"] == 15.0
    assert stats["max"] == 20.0


def test_c1_434_inf_raises_with_column_and_count() -> None:
    adlb = pl.from_repr("""
┌─────────┬──────┬─────────┬──────┐
│ USUBJID ┆ TRTA ┆ PARAMCD ┆ AVAL │
│ ---     ┆ ---  ┆ ---     ┆ ---  │
│ str     ┆ str  ┆ str     ┆ f64  │
╞═════════╪══════╪═════════╪══════╡
│ S0      ┆ A    ┆ ALT     ┆ 10.0 │
│ S1      ┆ A    ┆ ALT     ┆ inf  │
└─────────┴──────┴─────────┴──────┘
""")
    with pytest.raises(SchemaError, match="AVAL has 1 infinite value"):
        summarize_ard(adlb, rows=["PARAMCD"], stats=_CONT, context="lb", adsl=ADSL_S012)


def test_c1_434_renderer_survives_a_nan_statistic() -> None:
    adlb = pl.from_repr("""
┌─────────┬──────┬─────────┬──────┐
│ USUBJID ┆ TRTA ┆ PARAMCD ┆ AVAL │
│ ---     ┆ ---  ┆ ---     ┆ ---  │
│ str     ┆ str  ┆ str     ┆ f64  │
╞═════════╪══════╪═════════╪══════╡
│ S0      ┆ A    ┆ ALT     ┆ 10.0 │
└─────────┴──────┴─────────┴──────┘
""")
    ard = summarize_ard(adlb, rows=["PARAMCD"], stats=_CONT, context="lb", adsl=ADSL_S012)
    ard = ard.with_columns(stat=pl.lit(float("nan")), stat_fmt=pl.lit(""))
    model = ard_to_table_model(ard)
    assert model.columns[0].big_n is None


ADAE_XAN = pl.from_repr("""
┌─────────┬──────────┬──────────┐
│ USUBJID ┆ TRTA     ┆ AEDECOD  │
│ ---     ┆ ---      ┆ ---      │
│ str     ┆ str      ┆ str      │
╞═════════╪══════════╪══════════╡
│ S1      ┆ Placebo  ┆ HEADACHE │
│ S2      ┆ Xan Low  ┆ HEADACHE │
│ S3      ┆ Xan High ┆ HEADACHE │
└─────────┴──────────┴──────────┘
""")
ADSL_XAN = ADAE_XAN.select("USUBJID", "TRTA")


def _arm_order(ard: pl.DataFrame) -> list[str]:
    return ard.filter((pl.col("stat_name") == "N") & (pl.col("variable") == ""))[
        "group1_level"
    ].to_list()


def test_c1_438_pools_come_after_the_arms() -> None:
    ard = summarize_ard(
        ADAE_XAN,
        rows=["AEDECOD"],
        stats=[Statistic.N_SUBJECTS],
        context="ae",
        adsl=ADSL_XAN,
        pools=[GroupPool(label="Total", arms="*")],
    )
    assert _arm_order(ard) == ["Placebo", "Xan High", "Xan Low", "Total"]


def test_c1_438_enum_arm_keeps_its_order_and_empty_categories() -> None:
    arm = pl.Enum(["Placebo", "Xan Low", "Xan High", "Xan Mega"])
    adsl = ADSL_XAN.with_columns(pl.col("TRTA").cast(arm))
    ard = summarize_ard(
        ADAE_XAN.with_columns(pl.col("TRTA").cast(arm)),
        rows=["AEDECOD"],
        stats=[Statistic.N_SUBJECTS],
        context="ae",
        adsl=adsl,
    )
    assert _arm_order(ard) == ["Placebo", "Xan Low", "Xan High", "Xan Mega"]
    assert _stats(ard, group1_level="Xan Mega", variable="")["N"] == 0


def test_c1_438_column_order_typo_raises() -> None:
    with pytest.raises(SchemaError, match="column_order 'Placbo' is not an arm or pool"):
        summarize_ard(
            ADAE_XAN,
            rows=["AEDECOD"],
            stats=[Statistic.N_SUBJECTS],
            context="ae",
            adsl=ADSL_XAN,
            column_order=["Placbo", "Xan Low", "Xan High"],
        )


@pytest.mark.parametrize("dtype", [pl.Int64, pl.Float64])
def test_c1_448_numeric_arm_stops_at_once(dtype: pl.DataType) -> None:
    adae = pl.from_repr("""
┌─────────┬──────┬───────┬──────────┬─────────┐
│ USUBJID ┆ TRTA ┆ TRTAN ┆ AEBODSYS ┆ AEDECOD │
│ ---     ┆ ---  ┆ ---   ┆ ---      ┆ ---     │
│ str     ┆ str  ┆ i64   ┆ str      ┆ str     │
╞═════════╪══════╪═══════╪══════════╪═════════╡
│ S1      ┆ A    ┆ 1     ┆ X        ┆ P       │
│ S2      ┆ B    ┆ 2     ┆ X        ┆ P       │
└─────────┴──────┴───────┴──────────┴─────────┘
""").with_columns(pl.col("TRTAN").cast(dtype))
    adsl = adae.select("USUBJID", "TRTA", "TRTAN")
    with pytest.raises(SchemaError, match=r"'TRTAN' .* must be text.*TRTA.*column_order"):
        adae.tlg.ae.t_summary(groupby="TRTAN", adsl=adsl)


ADLB_VISITS = pl.from_repr("""
┌─────────┬──────┬─────────┬──────────────────┬─────────┬──────┐
│ USUBJID ┆ TRTA ┆ PARAMCD ┆ AVISIT           ┆ AVISITN ┆ AVAL │
│ ---     ┆ ---  ┆ ---     ┆ ---              ┆ ---     ┆ ---  │
│ str     ┆ str  ┆ str     ┆ str              ┆ i64     ┆ f64  │
╞═════════╪══════╪═════════╪══════════════════╪═════════╪══════╡
│ S1      ┆ A    ┆ ALT     ┆ Baseline         ┆ 0       ┆ 1.0  │
│ S1      ┆ A    ┆ ALT     ┆ Week 2           ┆ 2       ┆ 2.0  │
│ S1      ┆ A    ┆ ALT     ┆ Week 4           ┆ 4       ┆ 3.0  │
│ S1      ┆ A    ┆ ALT     ┆ Week 12          ┆ 12      ┆ 4.0  │
│ S1      ┆ A    ┆ ALT     ┆ End of Treatment ┆ 99      ┆ 5.0  │
└─────────┴──────┴─────────┴──────────────────┴─────────┴──────┘
""")
_VISIT_ORDER = ["Baseline", "Week 2", "Week 4", "Week 12", "End of Treatment"]
ADSL_S1 = pl.from_repr("""
┌─────────┬──────┐
│ USUBJID ┆ TRTA │
│ ---     ┆ ---  │
│ str     ┆ str  │
╞═════════╪══════╡
│ S1      ┆ A    │
└─────────┴──────┘
""")


def _visits(ard: pl.DataFrame) -> list[str]:
    return list(dict.fromkeys(ard.filter(pl.col("variable") == "AVISIT")["variable_level"]))


def test_c1_439_visits_sort_by_avisitn_by_default() -> None:
    ard = ADLB_VISITS.tlg.lb.t_summary(groupby="TRTA", adsl=ADSL_S1)
    assert _visits(ard) == _VISIT_ORDER
    html = render_html(ard_to_table_model(ard))
    assert html.index("Week 2") < html.index("Week 12")


def test_c1_439_explicit_order_by_survives_a_yaml_round_trip() -> None:
    adlb = ADLB_VISITS.rename({"AVISITN": "VISORD"})
    spec = LBSummarySpec(
        rows=[Row(field="PARAMCD"), Row(field="AVISIT", order_by="VISORD")],
    )
    again = LBSummarySpec.from_yaml(spec.to_yaml())
    assert again.rows[1].order_by == "VISORD"
    ard = adlb.tlg.lb.t_summary(groupby="TRTA", adsl=ADSL_S1, spec=again)
    assert _visits(ard) == _VISIT_ORDER


def test_c1_439_unknown_order_by_raises() -> None:
    spec = LBSummarySpec(rows=[Row(field="PARAMCD"), Row(field="AVISIT", order_by="NOPE")])
    with pytest.raises(SchemaError, match="order_by"):
        ADLB_VISITS.tlg.lb.t_summary(groupby="TRTA", adsl=ADSL_S1, spec=spec)


def test_c1_443_duplicate_adsl_record_raises() -> None:
    adsl = pl.from_repr("""
┌─────────┬────────┬─────┬─────┐
│ USUBJID ┆ TRT01A ┆ AGE ┆ SEX │
│ ---     ┆ ---    ┆ --- ┆ --- │
│ str     ┆ str    ┆ i64 ┆ str │
╞═════════╪════════╪═════╪═════╡
│ S1      ┆ A      ┆ 50  ┆ F   │
│ S1      ┆ A      ┆ 50  ┆ F   │
│ S2      ┆ A      ┆ 80  ┆ M   │
└─────────┴────────┴─────┴─────┘
""")
    with pytest.raises(SchemaError, match=r"1 duplicate USUBJID \+ TRT01A \(S1\)"):
        adsl.tlg.dm.t_summary(groupby="TRT01A")
    assert any("duplicate USUBJID" in m for m in adsl.tlg.dm.check(groupby="TRT01A"))


def test_c1_443_subject_in_two_arms_warns() -> None:
    adsl = pl.from_repr("""
┌─────────┬──────┐
│ USUBJID ┆ TRTA │
│ ---     ┆ ---  │
│ str     ┆ str  │
╞═════════╪══════╡
│ S1      ┆ A    │
│ S1      ┆ B    │
│ S2      ┆ A    │
└─────────┴──────┘
""")
    with pytest.warns(UserWarning, match="more than one TRTA arm"):
        ard = summarize_ard(adsl, rows=[], stats=[Statistic.N_SUBJECTS], context="x", adsl=adsl)
    assert _stats(ard, group1_level="A", variable="")["N"] == 2


def test_c1_446_string_prefilter_is_accepted() -> None:
    ard = summarize_ard(
        ADAE_XAN,
        rows=["AEDECOD"],
        stats=[Statistic.N_SUBJECTS],
        context="ae",
        adsl=ADSL_XAN,
        prefilter='pl.col("TRTA") == "Placebo"',
    )
    assert _stats(ard, group1_level="Placebo", variable="AEDECOD")["n"] == 1
    assert _stats(ard, group1_level="Xan Low", variable="AEDECOD")["n"] == 0


def test_c1_450_header_row_continuous_statistics() -> None:
    df = pl.from_repr("""
┌─────────┬──────┬──────┐
│ USUBJID ┆ TRTA ┆ AVAL │
│ ---     ┆ ---  ┆ ---  │
│ str     ┆ str  ┆ f64  │
╞═════════╪══════╪══════╡
│ S1      ┆ A    ┆ 1.0  │
│ S2      ┆ A    ┆ 2.0  │
│ S3      ┆ A    ┆ 4.0  │
│ S4      ┆ A    ┆ 7.0  │
│ S5      ┆ A    ┆ 20.0 │
└─────────┴──────┴──────┘
""")
    stats = [
        Statistic.N_SUBJECTS,
        Statistic.MEAN,
        Statistic.SD,
        Statistic.MEDIAN,
        Statistic.MIN,
        Statistic.MAX,
    ]
    ard = summarize_ard(
        df,
        rows=[],
        stats=stats,
        context="x",
        adsl=df.select("USUBJID", "TRTA"),
        header_rows=[OverallStat(label="All")],
    )
    got = _stats(ard, variable_level="All")
    assert got["n"] == 5
    assert got["mean"] == pytest.approx(6.8)
    assert got["sd"] == pytest.approx(7.7266, abs=1e-4)
    assert got["median"] == 4.0
    assert got["min"] == 1.0
    assert got["max"] == 20.0


@pytest.mark.parametrize(
    ("order", "low", "high"),
    [(["MILD", "MODERATE", "SEVERE"], "MILD", "MODERATE"), (["1", "2", "3", "4", "5"], "3", "4")],
)
def test_c1_450_worst_case_keeps_the_higher_of_adjacent_ranks(
    order: list[str], low: str, high: str
) -> None:
    df = pl.DataFrame({"USUBJID": ["S1", "S1", "S2", "S2"], "SEV": [high, low, low, high]})
    worst = worst_case(df, by=["USUBJID"], order_col="SEV", order=order)
    assert worst.sort("USUBJID")["SEV"].to_list() == [high, high]


def test_c2_869_numeric_levels_print_without_float_noise() -> None:
    adlb = pl.from_repr("""
┌─────────┬──────┬─────────┬─────────┬────────┬────────────────────┐
│ USUBJID ┆ TRTA ┆ PARAMCD ┆ AVISITN ┆ AVISIT ┆ AVAL               │
│ ---     ┆ ---  ┆ ---     ┆ ---     ┆ ---    ┆ ---                │
│ str     ┆ str  ┆ str     ┆ f64     ┆ str    ┆ f64                │
╞═════════╪══════╪═════════╪═════════╪════════╪════════════════════╡
│ S1      ┆ A    ┆ GLUC    ┆ 2.0     ┆ Week 2 ┆ 13.565999999999999 │
└─────────┴──────┴─────────┴─────────┴────────┴────────────────────┘
""")
    spec = LBSummarySpec(rows=[Row(field="AVISITN"), Row(field="PARAMCD")])
    ard = adlb.tlg.lb.t_summary(groupby="TRTA", adsl=ADSL_S1, spec=spec)
    assert set(ard.filter(pl.col("variable") == "AVISITN")["variable_level"]) == {"2"}
    labelled = LBSummarySpec(rows=[Row(field="AVISITN")], label_col="AVISIT")
    ard = adlb.tlg.lb.t_summary(groupby="TRTA", adsl=ADSL_S1, spec=labelled)
    assert set(ard.filter(pl.col("variable") == "AVISITN")["variable_level"]) == {"Week 2"}
    listing = listing_to_model(adlb.select("USUBJID", "AVISITN", "AVAL"))
    assert listing.data[0] == {"USUBJID": "S1", "AVISITN": "2", "AVAL": "13.566"}


def test_c1_506_one_code_with_two_labels_raises() -> None:
    adlb = pl.from_repr("""
┌─────────┬──────┬─────────┬──────────────────┬────────┬───────┐
│ USUBJID ┆ TRTA ┆ PARAMCD ┆ PARAM            ┆ AVISIT ┆ AVAL  │
│ ---     ┆ ---  ┆ ---     ┆ ---              ┆ ---    ┆ ---   │
│ str     ┆ str  ┆ str     ┆ str              ┆ str    ┆ f64   │
╞═════════╪══════╪═════════╪══════════════════╪════════╪═══════╡
│ P1      ┆ A    ┆ GLUC    ┆ Glucose (mg/dL)  ┆ W1     ┆ 100.0 │
│ P2      ┆ A    ┆ GLUC    ┆ Glucose (mmol/L) ┆ W1     ┆ 5.5   │
└─────────┴──────┴─────────┴──────────────────┴────────┴───────┘
""")
    adsl = adlb.select("USUBJID", "TRTA")
    with pytest.raises(SchemaError, match="GLUC.*2 PARAM labels"):
        adlb.tlg.lb.t_summary(groupby="TRTA", adsl=adsl, spec=LBSummarySpec(label_col="PARAM"))


# ------------------------------------------------------------------ #
# Specs                                                                #
# ------------------------------------------------------------------ #


def test_c1_437_decimals_key_and_pattern_are_checked() -> None:
    with pytest.raises(ValidationError, match="decimals key 'n_pct'.*use 'pct'"):
        AESummarySpec(decimals={"n_pct": "xx.xxx"})
    with pytest.raises(ValidationError, match="decimals key 'Mean'.*use 'mean'"):
        Row(field="AVAL", decimals={"Mean": "xx.x"})
    with pytest.raises(ValidationError, match="not a format pattern"):
        AESummarySpec(decimals={"mean": "xx.x (xx.x)"})
    assert AESummarySpec(decimals={"pct": "xx.x%", "N": "xx"}).decimals == {
        "pct": "xx.x%",
        "N": "xx",
    }


def test_c1_462_duplicate_labels_raise() -> None:
    with pytest.raises(ValidationError, match="label 'Any' is used twice"):
        AESummarySpec(
            header_rows=[
                OverallStat(label="Any", filter='pl.col("AESER") == "Y"'),
                OverallStat(label="Any"),
            ]
        )
    with pytest.raises(ValidationError, match="option label 'All' is used twice"):
        InteractiveBlock(
            population=[
                ChoiceOption(label="All", default=True),
                ChoiceOption(label="All", filter='pl.col("SAFFL") == "Y"'),
            ]
        )


def test_c1_465_yaml_refuses_a_field_the_template_does_not_use(tmp_path: Path) -> None:
    path = tmp_path / "ael.yaml"
    path.write_text('template: ael01\nadsl_filter: \'pl.col("SAFFL") == "Y"\'\n')
    with pytest.raises((SchemaError, ValidationError), match="ael01 does not use adsl_filter"):
        tlg.load_spec(path)
    with pytest.raises(ValidationError, match="does not use rows"):
        DMSummarySpec(rows=[Row(field="COUNTRY")])
    with pytest.raises(ValidationError, match="does not use value_col"):
        LBAbnormalSpec(value_col="NOPE")
    with pytest.raises(ValidationError, match="does not use rows"):
        LBAbnormalSpec(rows=[Row(field="PARAMCD")])
    # A round trip writes every field: defaults must still load.
    assert LBShiftSpec.from_yaml(LBShiftSpec().to_yaml()) == LBShiftSpec()


# ------------------------------------------------------------------ #
# LB templates                                                         #
# ------------------------------------------------------------------ #

ADLB_ABN = pl.from_repr("""
┌─────────┬──────┬─────────┬────────┬────────┬───────┬─────────┐
│ USUBJID ┆ TRTA ┆ PARAMCD ┆ BNRIND ┆ ANRIND ┆ ABLFL ┆ ONTRTFL │
│ ---     ┆ ---  ┆ ---     ┆ ---    ┆ ---    ┆ ---   ┆ ---     │
│ str     ┆ str  ┆ str     ┆ str    ┆ str    ┆ str   ┆ str     │
╞═════════╪══════╪═════════╪════════╪════════╪═══════╪═════════╡
│ P1      ┆ A    ┆ ALT     ┆ HIGH   ┆ HIGH   ┆ Y     ┆ null    │
│ P1      ┆ A    ┆ ALT     ┆ HIGH   ┆ HIGH   ┆ null  ┆ Y       │
│ P2      ┆ A    ┆ ALT     ┆ NORMAL ┆ NORMAL ┆ Y     ┆ null    │
│ P2      ┆ A    ┆ ALT     ┆ NORMAL ┆ NORMAL ┆ null  ┆ Y       │
│ P3      ┆ A    ┆ ALT     ┆ NORMAL ┆ NORMAL ┆ Y     ┆ null    │
│ P3      ┆ A    ┆ ALT     ┆ NORMAL ┆ HIGH   ┆ null  ┆ Y       │
└─────────┴──────┴─────────┴────────┴────────┴───────┴─────────┘
""")


def _abnormal(ard: pl.DataFrame, arm: str, direction: str) -> dict[str, float | None]:
    return _stats(ard, group1_level=arm, variable="ABNORMAL", variable_level=direction)


def test_c1_501_t_abnormal_needs_bnrind() -> None:
    with pytest.raises(SchemaError, match="BNRIND"):
        ADLB_ABN.drop("BNRIND").tlg.lb.t_abnormal(groupby="TRTA")
    ard = ADLB_ABN.tlg.lb.t_abnormal(groupby="TRTA")
    high = _abnormal(ard, "A", "High")
    assert (high["n"], high["N"], high["pct"]) == (1, 2, 50.0)


def test_c1_510_t_abnormal_keeps_an_arm_emptied_by_the_population() -> None:
    adsl = pl.from_repr("""
┌─────────┬─────────┬───────┐
│ USUBJID ┆ TRTA    ┆ SAFFL │
│ ---     ┆ ---     ┆ ---   │
│ str     ┆ str     ┆ str   │
╞═════════╪═════════╪═══════╡
│ P1      ┆ A       ┆ Y     │
│ P2      ┆ A       ┆ Y     │
│ P3      ┆ A       ┆ Y     │
│ D1      ┆ Drug    ┆ N     │
└─────────┴─────────┴───────┘
""")
    spec = LBAbnormalSpec(adsl_filter='pl.col("SAFFL") == "Y"')
    ard = ADLB_ABN.tlg.lb.t_abnormal(groupby="TRTA", adsl=adsl, spec=spec)
    assert _arm_order(ard) == ["A", "Drug"]
    assert _stats(ard, group1_level="Drug", variable="")["N"] == 0
    assert _abnormal(ard, "Drug", "High")["pct"] is None


def test_c1_513_mixed_case_levels_count() -> None:
    adlb = pl.from_repr("""
┌─────────┬──────┬─────────┬────────┬────────┬───────┬─────────┐
│ USUBJID ┆ TRTA ┆ PARAMCD ┆ BNRIND ┆ ANRIND ┆ ABLFL ┆ ONTRTFL │
│ ---     ┆ ---  ┆ ---     ┆ ---    ┆ ---    ┆ ---   ┆ ---     │
│ str     ┆ str  ┆ str     ┆ str    ┆ str    ┆ str   ┆ str     │
╞═════════╪══════╪═════════╪════════╪════════╪═══════╪═════════╡
│ P1      ┆ A    ┆ ALT     ┆ Normal ┆ High   ┆ null  ┆ Y       │
└─────────┴──────┴─────────┴────────┴────────┴───────┴─────────┘
""")
    spec = LBAbnormalSpec(high_values=["High"], low_values=["Low"])
    high = _abnormal(adlb.tlg.lb.t_abnormal(groupby="TRTA", spec=spec), "A", "High")
    assert (high["n"], high["N"]) == (1, 1)


def test_c1_505_t_shift_refuses_a_percentage() -> None:
    adsl = ADLB_ABN.select("USUBJID", "TRTA").unique(maintain_order=True)
    spec = LBShiftSpec(statistics=[Statistic.N_SUBJECTS, Statistic.N_PCT])
    with pytest.raises(SchemaError, match="t_shift emits subject counts only"):
        ADLB_ABN.tlg.lb.t_shift(groupby="TRTA", adsl=adsl, spec=spec)
    builder = (
        ADLB_ABN.tlg.lb.population(adsl)
        .by("TRTA")
        .template("lbt03")
        .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
    )
    with pytest.raises(SchemaError, match="t_shift emits subject counts only"):
        builder.to_ard()


ADLB_CHG = pl.from_repr("""
┌─────────┬──────┬─────────┬────────┬───────┬──────┐
│ USUBJID ┆ TRTA ┆ PARAMCD ┆ AVISIT ┆ ABLFL ┆ PCHG │
│ ---     ┆ ---  ┆ ---     ┆ ---    ┆ ---   ┆ ---  │
│ str     ┆ str  ┆ str     ┆ str    ┆ str   ┆ f64  │
╞═════════╪══════╪═════════╪════════╪═══════╪══════╡
│ S1      ┆ A    ┆ ALT     ┆ BASE   ┆ Y     ┆ null │
│ S1      ┆ A    ┆ ALT     ┆ WEEK 2 ┆ null  ┆ 10.0 │
└─────────┴──────┴─────────┴────────┴───────┴──────┘
""")


def test_c1_512_change_tables_run_on_pchg_without_chg() -> None:
    lb = ADLB_CHG.tlg.lb.t_chg(groupby="TRTA", adsl=ADSL_S1, spec=LBChgSpec(value_col="PCHG"))
    assert _stats(lb, variable="AVISIT", variable_level="WEEK 2")["mean"] == 10.0
    eg = ADLB_CHG.tlg.eg.t_chg(groupby="TRTA", adsl=ADSL_S1, spec=EGChgSpec(value_col="PCHG"))
    assert _stats(eg, variable="AVISIT", variable_level="WEEK 2")["mean"] == 10.0
    with pytest.raises(SchemaError, match="CHG"):
        ADLB_CHG.tlg.lb.t_chg(groupby="TRTA", adsl=ADSL_S1)


ADLB_LIST = pl.from_repr("""
┌─────────┬──────┬─────────┬────────┬──────┬────────┐
│ USUBJID ┆ TRTA ┆ PARAMCD ┆ AVISIT ┆ AVAL ┆ ANRIND │
│ ---     ┆ ---  ┆ ---     ┆ ---    ┆ ---  ┆ ---    │
│ str     ┆ str  ┆ str     ┆ str    ┆ f64  ┆ str    │
╞═════════╪══════╪═════════╪════════╪══════╪════════╡
│ P1      ┆ A    ┆ ALT     ┆ WEEK 2 ┆ 90.0 ┆ HIGH   │
│ P1      ┆ A    ┆ ALT     ┆ WEEK 4 ┆ 10.0 ┆ NORMAL │
│ P1      ┆ A    ┆ AST     ┆ WEEK 2 ┆ 80.0 ┆ HIGH   │
└─────────┴──────┴─────────┴────────┴──────┴────────┘
""")


def test_c1_502_listing_prefilter_follows_the_dataset_filter() -> None:
    spec = LBListingSpec(dataset_filter='pl.col("PARAMCD") == "ALT"')
    listing = ADLB_LIST.tlg.lb.l_listing(spec=spec)
    assert listing["Range Indicator"].to_list() == ["HIGH"]
    assert listing["Parameter"].to_list() == ["ALT"]  # PARAMCD when PARAM is absent
    every = ADLB_LIST.tlg.lb.l_listing(spec=LBListingSpec(prefilter=None))
    assert every.height == 3
    again = LBListingSpec.from_yaml(LBListingSpec(prefilter=None).to_yaml())
    assert again.prefilter is None


def test_c1_467_listing_column_format() -> None:
    adlb = pl.from_repr("""
┌─────────┬─────────┬────────────────────┐
│ USUBJID ┆ AVAL    ┆ CHG                │
│ ---     ┆ ---     ┆ ---                │
│ str     ┆ f64     ┆ f64                │
╞═════════╪═════════╪════════════════════╡
│ S1      ┆ 1.23456 ┆ 2.1000000000000014 │
│ S2      ┆ NaN     ┆ null               │
└─────────┴─────────┴────────────────────┘
""").with_columns(ANRIND=pl.lit("HIGH"), TRTA=pl.lit("A"), PARAMCD=pl.lit("ALT"))
    columns = [
        Column(field="USUBJID"),
        Column(field="AVAL", format="{:.2f}"),
        Column(field="CHG", format="{:.2f}"),
    ]
    spec = LBListingSpec(columns=columns, sort_by=["USUBJID"])
    listing = adlb.tlg.lb.l_listing(spec=spec)
    model = listing_to_model(listing)
    assert model.data == [
        {"USUBJID": "S1", "AVAL": "1.23", "CHG": "2.10"},
        {"USUBJID": "S2", "AVAL": "", "CHG": ""},
    ]
    bad = LBListingSpec(columns=[Column(field="AVAL", format="{:.2q}")], sort_by=["AVAL"])
    with pytest.raises(SchemaError, match="AVAL"):
        adlb.tlg.lb.l_listing(spec=bad)


ADAE_DATES = pl.from_repr("""
┌─────────┬──────┬─────────┬───────┬────────────┐
│ USUBJID ┆ TRTA ┆ AEDECOD ┆ AESEV ┆ AESTDT     │
│ ---     ┆ ---  ┆ ---     ┆ ---   ┆ ---        │
│ str     ┆ str  ┆ str     ┆ str   ┆ date       │
╞═════════╪══════╪═════════╪═══════╪════════════╡
│ A01     ┆ X    ┆ HEAD    ┆ SEV   ┆ 2024-01-03 │
│ A01     ┆ X    ┆ HEAD    ┆ MILD  ┆ 2024-01-01 │
│ A01     ┆ X    ┆ NAUSEA  ┆ MILD  ┆ 2024-01-02 │
└─────────┴──────┴─────────┴───────┴────────────┘
""")


def test_c1_802_hidden_sort_key_sorts_and_unknown_key_raises() -> None:
    cols = [Column(field="USUBJID"), Column(field="AEDECOD"), Column(field="AESEV")]
    spec = AEListingSpec(columns=cols, sort_by=["USUBJID", "AESTDT"])
    listing = ADAE_DATES.tlg.ae.l_listing(spec=spec)
    assert listing["AESEV"].to_list() == ["MILD", "MILD", "SEV"]
    assert listing.columns == ["USUBJID", "AEDECOD", "AESEV"]
    typo = AEListingSpec(columns=cols, sort_by=["USUBJID", "ASTDTX"])
    with pytest.raises(SchemaError, match="ASTDTX"):
        ADAE_DATES.tlg.ae.l_listing(spec=typo)
    assert any("ASTDTX" in m for m in typo.check(ADAE_DATES))


def test_c1_802_date_column_format() -> None:
    cols = [Column(field="USUBJID"), Column(field="AESTDT", format="%d%b%Y")]
    spec = AEListingSpec(columns=cols, sort_by=["AESTDT"])
    listing = ADAE_DATES.tlg.ae.l_listing(spec=spec)
    assert listing["AESTDT"].to_list() == ["01Jan2024", "02Jan2024", "03Jan2024"]


# ------------------------------------------------------------------ #
# DM, DS, EX                                                           #
# ------------------------------------------------------------------ #

ADSL_AGE = pl.from_repr("""
┌─────────┬────────┬──────┬──────┬──────────┬────────┬─────┐
│ USUBJID ┆ TRT01A ┆ AGE  ┆ AAGE ┆ HEIGHTBL ┆ AGEGR1 ┆ SEX │
│ ---     ┆ ---    ┆ ---  ┆ ---  ┆ ---      ┆ ---    ┆ --- │
│ str     ┆ str    ┆ f64  ┆ f64  ┆ f64      ┆ str    ┆ str │
╞═════════╪════════╪══════╪══════╪══════════╪════════╪═════╡
│ A       ┆ X      ┆ 70.0 ┆ 70.0 ┆ 160.0    ┆ >=65   ┆ F   │
│ B       ┆ X      ┆ null ┆ null ┆ 170.0    ┆ null   ┆ M   │
└─────────┴────────┴──────┴──────┴──────────┴────────┴─────┘
""")


def test_c1_804_age_block_starts_with_n() -> None:
    ard = ADSL_AGE.tlg.dm.t_summary()
    age = ard.filter(pl.col("variable") == "AGE")
    assert age["stat_name"].to_list() == ["n", "mean", "sd", "median", "min", "max"]
    assert _stats(ard, variable="AGE")["n"] == 1


def test_c1_804_continuous_var_without_age_runs() -> None:
    spec = DMSummarySpec(continuous_vars={"AAGE": "Age (yr)"})
    ard = ADSL_AGE.drop("AGE").tlg.dm.t_summary(spec=spec)
    assert _stats(ard, variable="AAGE")["mean"] == 70.0


def test_c1_804_dm_refuses_unused_settings() -> None:
    with pytest.raises(SchemaError, match="do not apply"):
        ADSL_AGE.tlg.dm.t_summary(spec=DMSummarySpec(statistics=[Statistic.Q1]))
    with pytest.raises(SchemaError, match="value_col"):
        ADSL_AGE.tlg.dm.by("TRT01A").value("AAGE").to_ard()


def test_c2_965_several_continuous_blocks() -> None:
    blocks = {"AGE": "Age (yr)", "HEIGHTBL": "Height (cm)"}
    ard = ADSL_AGE.tlg.dm.by("TRT01A").continuous(blocks).to_ard()
    height = ard.filter(pl.col("variable") == "HEIGHTBL")
    assert set(height["variable_level"]) == {"Height (cm)"}
    assert _stats(ard, variable="HEIGHTBL")["mean"] == 165.0
    assert _stats(ard, variable="HEIGHTBL")["n"] == 2


ADSL_DEATHS = pl.from_repr("""
┌─────────┬─────────┬───────┬───────────────┬─────────┐
│ USUBJID ┆ TRT01A  ┆ DTHFL ┆ DTHCAT        ┆ DTHCAUS │
│ ---     ┆ ---     ┆ ---   ┆ ---           ┆ ---     │
│ str     ┆ str     ┆ str   ┆ str           ┆ str     │
╞═════════╪═════════╪═══════╪═══════════════╪═════════╡
│ S1      ┆ Placebo ┆ Y     ┆ ADVERSE EVENT ┆ MI      │
│ S2      ┆ Placebo ┆ null  ┆ null          ┆ null    │
│ S3      ┆ Drug A  ┆ null  ┆ null          ┆ null    │
│ S4      ┆ Drug A  ┆ null  ┆ null          ┆ null    │
└─────────┴─────────┴───────┴───────────────┴─────────┘
""")


def test_c1_805_deaths_pool_and_no_death_arm_get_cause_cells() -> None:
    spec = DSDeathsSpec(pools=[GroupPool(label="Both", arms=["Placebo", "Drug A"])])
    ard = ADSL_DEATHS.tlg.ds.t_deaths(spec=spec)
    model = ard_to_table_model(ard)
    cause = next(r for r in model.rows if r.label == "ADVERSE EVENT")
    assert cause.cells == {"Drug A": "0", "Placebo": "1 (100.0%)", "Both": "1 (100.0%)"}


def test_c1_805_null_cause_of_the_last_row_field_is_unknown() -> None:
    adsl = ADSL_DEATHS.with_columns(
        DTHFL=pl.when(pl.col("USUBJID") == "S3").then(pl.lit("Y")).otherwise("DTHFL")
    )
    ard = adsl.tlg.ds.t_deaths(spec=DSDeathsSpec(rows=[Row(field="DTHCAUS")]))
    assert _stats(ard, group1_level="Drug A", variable="DTHCAUS", variable_level="Unknown")[
        "n"
    ] == (1)


ADEX = pl.from_repr("""
┌─────────┬──────┬─────────┬─────────┬──────┐
│ USUBJID ┆ TRTA ┆ PARAMCD ┆ PARCAT1 ┆ AVAL │
│ ---     ┆ ---  ┆ ---     ┆ ---     ┆ ---  │
│ str     ┆ str  ┆ str     ┆ str     ┆ f64  │
╞═════════╪══════╪═════════╪═════════╪══════╡
│ S1      ┆ A    ┆ TDOSE   ┆ Overall ┆ 3.0  │
│ S1      ┆ A    ┆ TDOSE   ┆ Cycle 1 ┆ 1.0  │
│ S1      ┆ A    ┆ TDOSE   ┆ Cycle 2 ┆ 2.0  │
└─────────┴──────┴─────────┴─────────┴──────┘
""")


def test_c1_809_an_emptying_prefilter_warns_with_the_values_seen() -> None:
    with pytest.warns(
        UserWarning, match="kept 0 of 3 records; PARCAT1 values: Overall, Cycle 1, Cycle 2"
    ):
        ADEX.tlg.ex.t_summary(groupby="TRTA", adsl=ADSL_S1)


def test_c1_809_check_reads_the_spec_prefilter_and_reports_once() -> None:
    cycles = ADEX.filter(pl.col("PARCAT1") != "Overall")
    report = cycles.tlg.ex.check(spec=EXSummarySpec(prefilter=None))
    assert any("multiple records" in m for m in report)
    nope = ADEX.tlg.ex.check(spec=EXSummarySpec(rows=[Row(field="NOPE")]))
    assert sum("NOPE" in m for m in nope) == 1


# ------------------------------------------------------------------ #
# Builder, registry, namespaces                                        #
# ------------------------------------------------------------------ #


def test_c1_791_second_filter_raises() -> None:
    builder = ADAE_XAN.tlg.ae.population(ADSL_XAN).filter('pl.col("TRTA") == "Placebo"')
    with pytest.raises(SchemaError, match="filter is already set; combine the conditions with &"):
        builder.filter('pl.col("AEDECOD") == "HEADACHE"')


def test_c1_792_register_template_docstring_example_runs() -> None:
    def my_shell(df, *, adsl, spec, groupby):
        return df.tlg.ae.t_summary(groupby=groupby, adsl=adsl, spec=spec)

    adae = ADAE_XAN.with_columns(AEBODSYS=pl.lit("NERV"))
    tlg.register_template(
        tlg.TemplateMeta(
            id="spon01",
            title="Sponsor AE Shell",
            cdisc_class=tlg.CDISCClass.EVENTS,
            namespace="ae",
            method="my_shell",
            output_type=tlg.OutputType.TABLE,
            domains=("ADSL", "ADAE"),
            source_ref="sponsor",
            status=tlg.Status.DONE,
            spec_cls=tlg.AESummarySpec,
        ),
        my_shell,
    )
    try:
        ard = adae.tlg.ae.population(ADSL_XAN).by("TRTA").template("spon01").to_ard()
    finally:
        tlg.unregister_template("spon01")
    assert ard.filter(pl.col("variable") == "AEDECOD").height > 0


def test_c1_793_registry_lookups_are_exported() -> None:
    from fleet.tlg import by_class, by_namespace, get

    assert get("aet01").id == "aet01"
    assert any(m.id == "aet01" for m in by_namespace("ae"))
    assert by_class(tlg.CDISCClass.EVENTS)


def test_c1_810_tlg_namespaces_list_their_verbs() -> None:
    ae = ADAE_XAN.tlg.ae.verbs()
    assert ae.columns == ["verb", "summary", "origin"]
    assert {"t_summary", "l_listing", "population"} <= set(ae["verb"])
    assert set(ae.filter(pl.col("verb") == "t_summary")["origin"]) == {"tlg.ae"}
    assert "catalog" in set(ADAE_XAN.tlg.verbs()["verb"])


# ------------------------------------------------------------------ #
# Rendering                                                            #
# ------------------------------------------------------------------ #


def _ae_model(adsl: pl.DataFrame, decimals: dict[str, str] | None = None) -> object:
    ard = summarize_ard(
        ADAE_XAN.filter(pl.col("TRTA") == "Placebo").with_columns(TRTA=pl.lit("A")),
        rows=["AEDECOD"],
        stats=[Statistic.N_SUBJECTS, Statistic.N_PCT],
        context="ae",
        adsl=adsl,
        decimals=decimals,
    )
    return ard_to_table_model(ard)


def test_c1_455_one_percent_sign_and_no_percent_for_zero() -> None:
    adsl = pl.from_repr("""
┌─────────┬──────┐
│ USUBJID ┆ TRTA │
│ ---     ┆ ---  │
│ str     ┆ str  │
╞═════════╪══════╡
│ S1      ┆ A    │
│ S2      ┆ A    │
│ S3      ┆ B    │
└─────────┴──────┘
""")
    row = _ae_model(adsl, {"pct": "xx.x%"}).rows[0]
    assert row.cells == {"A": "1 (50.0%)", "B": "0"}
    big = pl.DataFrame({"USUBJID": ["S1", *[f"X{i}" for i in range(4999)]], "TRTA": "A"})
    assert _ae_model(big, {"pct": "xx.x%"}).rows[0].cells == {"A": "1 (<0.1%)"}
    zero = _ae_model(adsl, {"n": "xx.x"}).rows[0]
    assert zero.cells["B"] == "0.0"


def _vs_model() -> object:
    adlb = ADLB_VISITS.with_columns(PARAMCD=pl.lit("SYSBP"))
    return ard_to_table_model(adlb.tlg.lb.t_summary(groupby="TRTA", adsl=ADSL_S1))


def test_c1_457_unknown_page_by_raises() -> None:
    model = _vs_model()
    assert len(paginate(model, page_by="PARAMCD")) == 1
    with pytest.raises(SchemaError, match="page_by 'NOSUCH' is not a row variable"):
        paginate(model, page_by="NOSUCH")


@pytest.mark.parametrize("size", [0, -1])
def test_c1_459_rows_per_page_below_one_raises(size: int) -> None:
    with pytest.raises(SchemaError, match="rows_per_page must be 1 or more"):
        paginate(_vs_model(), rows_per_page=size)
    listing = listing_to_model(ADAE_XAN)
    with pytest.raises(SchemaError, match="rows_per_page must be 1 or more"):
        paginate_listing(listing, rows_per_page=size)


def test_c1_459_c1_457_cli_usage_errors(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    spec = Path("examples/tlg_specs").resolve() / "ael01.yaml"
    if not spec.is_file():
        spec = tmp_path / "ael01.yaml"
        spec.write_text("template: ael01\n")
    data = tmp_path / "adae.csv"
    ADAE_XAN.write_csv(data)
    code = _run(["tlg", "run", str(spec), "--data", str(data), "--rows-per-page", "-1"])
    assert code == 2
    assert "must be 1 or more" in capsys.readouterr().err
    code = _run(
        ["tlg", "run", str(spec), "--data", str(data), "--page-by", "USUBJID", "-o", str(tmp_path)]
    )
    assert code == 1
    assert "--page-by applies to tables only" in capsys.readouterr().err


def test_c1_461_ard_without_group2_renders() -> None:
    ard = summarize_ard(
        ADAE_XAN, rows=["AEDECOD"], stats=[Statistic.N_SUBJECTS], context="ae", adsl=ADSL_XAN
    )
    model = ard_to_table_model(ard.drop("group2", "group2_level"))
    assert [r.label for r in model.rows] == ["HEADACHE"]


def test_c1_461_c1_819_pptx_header_row_is_not_bold_and_listing_has_notes(
    tmp_path: Path,
) -> None:
    pptx = pytest.importorskip("pptx")
    from fleet.tlg.render.slides import _DEFAULT_THEME, render_listing_pptx, render_pptx

    assert "bold_header_rows" not in _DEFAULT_THEME
    spec = AESummarySpec(header_rows=[OverallStat(label="Any")], rows=[])
    ard = ADAE_XAN.with_columns(AEBODSYS=pl.lit("NERV")).tlg.ae.t_summary(
        groupby="TRTA", adsl=ADSL_XAN, spec=spec
    )
    path = render_pptx(ard_to_table_model(ard), tmp_path / "t.pptx")
    table = next(s for s in pptx.Presentation(path).slides[0].shapes if s.has_table).table
    assert table.cell(1, 0).text == "Any"
    assert table.cell(1, 0).text_frame.paragraphs[0].font.bold is False
    meta = RenderMetadata(title="Listing 1", subtitle="Safety", footnotes=["Note A"])
    path = render_listing_pptx(listing_to_model(ADAE_XAN, meta), tmp_path / "l.pptx")
    texts = [
        s.text_frame.text for s in pptx.Presentation(path).slides[0].shapes if s.has_text_frame
    ]
    assert texts == ["Listing 1", "Safety", "Note A"]


def test_c1_814_html_is_ascii_and_files_are_documents(tmp_path: Path) -> None:
    model = _ae_model(ADSL_S012)
    model.metadata.title = "Temp ≥ 38 °C"
    model.rows[0].label = "Röntgen"
    html = render_html(model)
    assert html.isascii()
    assert "&#8805;" in html
    adae = ADAE_XAN.with_columns(AEBODSYS=pl.lit("NERV"))
    out = tmp_path / "t.html"
    adae.tlg.ae.population(ADSL_XAN).by("TRTA").to_html(out)
    assert out.read_text(encoding="utf-8").startswith("<!DOCTYPE html>\n<html><head><meta charset")


def test_c1_815_wrapper_without_placeholder_raises() -> None:
    model = _ae_model(ADSL_S012)
    with pytest.raises(ValueError, match=r"no \{table\} placeholder"):
        render_html(model, html_wrapper="<html>{tabel}</html>")
    with pytest.raises(ValueError, match=r"no \{table\} placeholder"):
        render_listing_html(listing_to_model(ADAE_XAN), html_wrapper="<html></html>")


def test_c1_815_wrap_with_rtf_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    adae = ADAE_XAN.with_columns(AEBODSYS=pl.lit("NERV"))
    data, adsl, wrap = tmp_path / "adae.csv", tmp_path / "adsl.csv", tmp_path / "w.html"
    adae.write_csv(data)
    ADSL_XAN.write_csv(adsl)
    wrap.write_text("<div>{table}</div>")
    argv = ["tlg", "export", "--domain", "ae", "--data", str(data), "--adsl", str(adsl)]
    argv += ["--format", "rtf", "--wrap", str(wrap), "-o", str(tmp_path / "t.rtf")]
    assert _run(argv) == 1
    assert "--wrap applies to html and pdf only" in capsys.readouterr().err


def test_c1_817_builder_paginates_and_pdf_numbers_every_page() -> None:
    from fleet.tlg.render.pdf import _html_document

    doc = _html_document("<p>x</p>")
    assert "counter(page)" in doc and "counter(pages)" in doc
    assert ".fleet-page-footer { display: none; }" in doc
    adae = ADAE_XAN.with_columns(
        AEBODSYS=pl.lit("NERV"), AEDECOD=pl.Series(["HEADACHE", "NAUSEA", "NAUSEA"])
    )
    builder = adae.tlg.ae.population(ADSL_XAN).by("TRTA").rows(["AEDECOD"])
    assert "Page 1 of" not in builder.to_html()
    assert "Page 1 of 2" in builder.to_html(rows_per_page=1)


def test_c1_817_to_pdf_takes_rows_per_page(tmp_path: Path) -> None:
    pytest.importorskip("weasyprint")
    adae = ADAE_XAN.with_columns(AEBODSYS=pl.lit("NERV"))
    builder = adae.tlg.ae.population(ADSL_XAN).by("TRTA").rows(["AEDECOD"])
    path = builder.to_pdf(tmp_path / "t.pdf", rows_per_page=1)
    assert path.read_bytes().startswith(b"%PDF")


def test_c1_818_missing_native_libraries_give_a_clean_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "weasyprint":
            raise OSError("cannot load library 'libgobject-2.0-0'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    from fleet.tlg.render.pdf import render_pdf

    with pytest.raises(ImportError, match=r"system libraries \(Pango\)"):
        render_pdf(_ae_model(ADSL_S012), "unused.pdf")


def test_c1_818_doctor_reports_weasyprint_not_usable(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    real = importlib.import_module

    def fake(name: str, *args: object) -> object:
        if name == "weasyprint":
            raise OSError("cannot load library 'libgobject-2.0-0'")
        return real(name, *args)

    monkeypatch.setattr(cli, "_module_available", lambda module: True)
    monkeypatch.setattr(importlib, "import_module", fake)
    entry = next(e for e in cli._check_extras() if e[0] == "weasyprint")
    assert entry[1] is False
    assert "not usable" in entry[2]


def test_c1_821_rtf_writes_astral_characters_as_surrogate_pairs() -> None:
    from fleet.tlg.render.rtf import _esc

    assert _esc("😀") == "\\u-10179?\\u-8704?"
    assert _esc("é") == "\\u233?"


def test_c1_811_non_default_variant_prints_its_selection() -> None:
    from fleet.tlg.ae_namespace import AEOverviewSpec
    from fleet.tlg.render.explorer import ExplorerEntry, render_explorer

    adae = ADAE_XAN.with_columns(
        AEBODSYS=pl.lit("NERV"), AESER=pl.lit("N"), AEACN=pl.lit("NONE"), AESDTH=pl.lit("N")
    )
    spec = AEOverviewSpec(
        template="aet01",
        header_rows=[OverallStat(label="Any AE")],
        interactive=InteractiveBlock(
            dataset_filter=[
                ChoiceOption(label="All AEs", default=True),
                ChoiceOption(label="Serious only", filter='pl.col("AESER") == "Y"'),
            ]
        ),
    )
    html = render_explorer(
        [ExplorerEntry(name="aet01", spec=spec, df=adae, adsl=ADSL_XAN, groupby="TRTA")]
    )
    assert html.count('class="fleet-exploratory"') == 1
    assert "Exploratory view, not the batch output. Dataset filter: Serious only." in html


def test_c2_970_pdf_refuses_external_resources(tmp_path: Path) -> None:
    pytest.importorskip("weasyprint")
    from fleet.tlg.render.pdf import render_pdf

    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET")
    wrapper = f'<div><img src="file://{secret}"><a rel="attachment" href="file://{secret}">a</a>{{table}}</div>'
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        path = render_pdf(_ae_model(ADSL_S012), tmp_path / "t.pdf", html_wrapper=wrapper)
    assert any("PDF export" in str(w.message) for w in caught)
    assert b"TOPSECRET" not in path.read_bytes()
    assert not math.isnan(len(path.read_bytes()))
