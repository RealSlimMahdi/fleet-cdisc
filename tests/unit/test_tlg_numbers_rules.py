"""Alpha audit package G: TLG numbers (c1-424, c1-425/426, c1-427, c1-433, c1-500, c1-808, c1-822)."""

from __future__ import annotations

import logging

import polars as pl
import pytest

import fleet  # noqa: F401
from fleet.core.exceptions import SchemaError
from fleet.tlg import OverallStat, Statistic
from fleet.tlg._ard import summarize_ard
from fleet.tlg.ae_namespace import AERelationshipSpec
from fleet.tlg.eg_namespace import EGQtcatSpec
from fleet.tlg.lb_namespace import LBAbnormalSpec, LBShiftSpec


def _stat(ard: pl.DataFrame, arm: str, level: str, name: str, *, group2_level: str | None = None):
    rows = ard.filter(
        (pl.col("group1_level") == arm)
        & (pl.col("variable_level") == level)
        & (pl.col("stat_name") == name)
    )
    if group2_level is not None:
        rows = rows.filter(pl.col("group2_level") == group2_level)
    assert rows.height == 1, rows
    return rows["stat"][0]


ADSL = pl.from_repr("""\
┌─────────┬─────────┬───────┐
│ USUBJID ┆ TRTA    ┆ SAFFL │
│ ---     ┆ ---     ┆ ---   │
│ str     ┆ str     ┆ str   │
╞═════════╪═════════╪═══════╡
│ 01-001  ┆ Placebo ┆ Y     │
│ 01-002  ┆ Placebo ┆ Y     │
│ 01-005  ┆ Placebo ┆ N     │
└─────────┴─────────┴───────┘
""")

ADAE = pl.from_repr("""\
┌─────────┬─────────┬──────────┐
│ USUBJID ┆ TRTA    ┆ AEDECOD  │
│ ---     ┆ ---     ┆ ---      │
│ str     ┆ str     ┆ str      │
╞═════════╪═════════╪══════════╡
│ 01-001  ┆ Placebo ┆ HEADACHE │
│ 01-005  ┆ Placebo ┆ HEADACHE │
└─────────┴─────────┴──────────┘
""")


# ── c1-424: the population filter reaches the numerator (Q1 A) ──────────────


def test_a_subject_outside_the_population_leaves_the_numerator(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="fleet"):
        ard = summarize_ard(
            ADAE,
            rows=["AEDECOD"],
            stats=[Statistic.N_SUBJECTS, Statistic.N_PCT],
            context="t",
            adsl=ADSL,
            adsl_filter='pl.col("SAFFL") == "Y"',
        )

    assert _stat(ard, "Placebo", "", "N") == 2
    assert _stat(ard, "Placebo", "HEADACHE", "n") == 1
    assert _stat(ard, "Placebo", "HEADACHE", "pct") == 50.0
    assert "1 subject(s)" in caplog.text


def test_a_subject_absent_from_adsl_is_dropped_with_a_warning() -> None:
    adae = pl.concat(
        [ADAE, pl.DataFrame({"USUBJID": ["01-099"], "TRTA": ["Placebo"], "AEDECOD": ["RASH"]})]
    )

    with pytest.warns(UserWarning, match="01-099"):
        ard = summarize_ard(
            adae,
            rows=["AEDECOD"],
            stats=[Statistic.N_SUBJECTS],
            context="t",
            adsl=ADSL,
        )

    assert "RASH" not in ard["variable_level"].to_list()


def test_adsl_filter_without_adsl_stops() -> None:
    with pytest.raises(SchemaError, match="adsl"):
        summarize_ard(
            ADAE,
            rows=["AEDECOD"],
            stats=[Statistic.N_SUBJECTS],
            context="t",
            adsl_filter='pl.col("SAFFL") == "Y"',
        )


def test_the_safety_table_counts_only_the_population() -> None:
    from fleet.tlg.ae_namespace import AESummarySpec

    adae = ADAE.with_columns(pl.lit("NERVOUS SYSTEM DISORDERS").alias("AEBODSYS"))
    spec = AESummarySpec(adsl_filter='pl.col("SAFFL") == "Y"')

    ard = adae.tlg.ae.t_summary(adsl=ADSL, spec=spec)

    assert _stat(ard, "Placebo", "HEADACHE", "n") == 1


# ── c1-425 / c1-426: continuous n counts the non-missing values (Q2 A) ───────

LB = pl.from_repr("""\
┌─────────┬─────────┬─────────┬────────┬──────┐
│ USUBJID ┆ TRTA    ┆ PARAMCD ┆ AVISIT ┆ AVAL │
│ ---     ┆ ---     ┆ ---     ┆ ---    ┆ ---  │
│ str     ┆ str     ┆ str     ┆ str    ┆ f64  │
╞═════════╪═════════╪═════════╪════════╪══════╡
│ 01-001  ┆ Placebo ┆ ALT     ┆ WEEK 2 ┆ 10.0 │
│ 01-001  ┆ Placebo ┆ ALT     ┆ WEEK 2 ┆ 30.0 │
│ 01-002  ┆ Placebo ┆ ALT     ┆ WEEK 2 ┆ 20.0 │
└─────────┴─────────┴─────────┴────────┴──────┘
""")


def test_continuous_n_counts_values_as_proc_means() -> None:
    ard = LB.tlg.lb.t_summary(adsl=ADSL)

    assert _stat(ard, "Placebo", "WEEK 2", "n") == 3
    assert _stat(ard, "Placebo", "WEEK 2", "mean") == 20.0
    assert _stat(ard, "Placebo", "WEEK 2", "sd") == 10.0


def test_a_null_value_never_counts_in_n() -> None:
    lb = pl.concat(
        [
            LB.filter(pl.col("AVAL") != 30.0),
            pl.DataFrame(
                {
                    "USUBJID": ["01-005"],
                    "TRTA": ["Placebo"],
                    "PARAMCD": ["ALT"],
                    "AVISIT": ["WEEK 2"],
                    "AVAL": [None],
                },
                schema=LB.schema,
            ),
        ]
    )

    ard = lb.tlg.lb.t_summary(adsl=ADSL)

    assert _stat(ard, "Placebo", "WEEK 2", "n") == 2
    assert _stat(ard, "Placebo", "WEEK 2", "mean") == 15.0


def test_a_header_row_counts_values_too() -> None:
    ard = summarize_ard(
        LB,
        rows=[],
        stats=[Statistic.N_SUBJECTS, Statistic.MEAN],
        context="t",
        header_rows=[OverallStat(label="All")],
    )

    assert _stat(ard, "Placebo", "All", "n") == 3


def test_a_count_table_still_counts_subjects() -> None:
    ard = summarize_ard(LB, rows=["PARAMCD"], stats=[Statistic.N_SUBJECTS], context="t")

    assert _stat(ard, "Placebo", "ALT", "n") == 2


# ── c1-427: Q1 and Q3 follow SAS QNTLDEF=5 (R type 2) ───────────────────────


@pytest.mark.parametrize(
    ("values", "q1", "q3"),
    [
        ([1, 2, 3], 1.0, 3.0),
        ([1, 2, 3, 4], 1.5, 3.5),
        ([1, 2, 3, 4, 5, 6, 7], 2.0, 6.0),
        ([1, 2, 4, 8, 16, 32], 2.0, 16.0),
        ([10.2, 11.5, 11.9, 12.4, 13.1, 14.8, 15.0, 19.3], 11.7, 14.9),
        ([1, 2, 3, 4, None], 1.5, 3.5),
    ],
)
def test_quartiles_follow_qntldef5(values: list, q1: float, q3: float) -> None:
    frame = pl.DataFrame(
        {"USUBJID": [f"S{i}" for i in range(len(values))], "TRTA": "A", "P": "X", "AVAL": values},
        schema_overrides={"AVAL": pl.Float64},
    )
    stats = [Statistic.Q1, Statistic.Q3]

    leaf = summarize_ard(frame, rows=["P"], stats=stats, context="t")
    header = summarize_ard(
        frame, rows=[], stats=stats, context="t", header_rows=[OverallStat(label="All")]
    )

    for ard, level in ((leaf, "X"), (header, "All")):
        assert _stat(ard, "A", level, "q1") == pytest.approx(q1)
        assert _stat(ard, "A", level, "q3") == pytest.approx(q3)


# ── c1-433: a value outside the order stops the table (Q3 A) ────────────────

AE_REL = pl.from_repr("""\
┌─────────────┬─────────┬──────────────────────────┬──────────────────┐
│ USUBJID     ┆ TRTA    ┆ AEBODSYS                 ┆ AEREL            │
│ ---         ┆ ---     ┆ ---                      ┆ ---              │
│ str         ┆ str     ┆ str                      ┆ str              │
╞═════════════╪═════════╪══════════════════════════╪══════════════════╡
│ 01-701-1015 ┆ Placebo ┆ NERVOUS SYSTEM DISORDERS ┆ POSSIBLY RELATED │
│ 01-701-1015 ┆ Placebo ┆ NERVOUS SYSTEM DISORDERS ┆ NOT RELATED      │
│ 01-701-1023 ┆ Placebo ┆ NERVOUS SYSTEM DISORDERS ┆ RELATED          │
│ 01-701-1023 ┆ Placebo ┆ NERVOUS SYSTEM DISORDERS ┆ null             │
└─────────────┴─────────┴──────────────────────────┴──────────────────┘
""")


def test_relationship_values_outside_the_order_stop_the_table() -> None:
    with pytest.raises(SchemaError, match="relationship_order") as err:
        AE_REL.tlg.ae.t_relationship()
    assert "POSSIBLY RELATED" in str(err.value)


def test_relationship_with_the_study_order_counts_the_most_related() -> None:
    spec = AERelationshipSpec(
        relationship_order=["NOT RELATED", "UNLIKELY RELATED", "POSSIBLY RELATED", "RELATED"],
        statistics=[Statistic.N_SUBJECTS],
    )

    ard = AE_REL.tlg.ae.t_relationship(spec=spec)

    assert _stat(ard, "Placebo", "POSSIBLY RELATED", "n") == 1
    assert _stat(ard, "Placebo", "RELATED", "n") == 1
    assert "NOT RELATED" not in ard["variable_level"].to_list()


# ── c1-500: shift and abnormality tables need a post-baseline rule (Q4 A) ────

ADLB = pl.from_repr("""\
┌─────────┬─────────┬─────────┬───────────┬─────┬───────┬────────┬────────┐
│ USUBJID ┆ TRTA    ┆ PARAMCD ┆ AVISIT    ┆ ADY ┆ ABLFL ┆ BNRIND ┆ ANRIND │
│ ---     ┆ ---     ┆ ---     ┆ ---       ┆ --- ┆ ---   ┆ ---    ┆ ---    │
│ str     ┆ str     ┆ str     ┆ str       ┆ i64 ┆ str   ┆ str    ┆ str    │
╞═════════╪═════════╪═════════╪═══════════╪═════╪═══════╪════════╪════════╡
│ P1      ┆ Placebo ┆ ALT     ┆ SCREENING ┆ -14 ┆ null  ┆ NORMAL ┆ HIGH   │
│ P1      ┆ Placebo ┆ ALT     ┆ BASELINE  ┆ 1   ┆ Y     ┆ NORMAL ┆ NORMAL │
│ P1      ┆ Placebo ┆ ALT     ┆ WEEK 2    ┆ 15  ┆ null  ┆ NORMAL ┆ NORMAL │
└─────────┴─────────┴─────────┴───────────┴─────┴───────┴────────┴────────┘
""")


def test_shift_without_a_post_baseline_rule_stops() -> None:
    with pytest.raises(SchemaError, match=r'pl.col\("ADY"\) > 1'):
        ADLB.tlg.lb.t_shift()


def test_shift_with_the_sap_rule_counts_post_baseline_only() -> None:
    ard = ADLB.tlg.lb.t_shift(spec=LBShiftSpec(prefilter='pl.col("ADY") > 1'))

    assert _stat(ard, "Placebo", "NORMAL to NORMAL", "n") == 1
    assert "NORMAL to HIGH" not in ard["variable_level"].to_list()


def test_shift_default_rule_leaves_out_an_on_treatment_baseline() -> None:
    adlb = ADLB.with_columns(
        pl.when(pl.col("ADY") >= 1).then(pl.lit("Y")).alias("ONTRTFL"),
        pl.when(pl.col("AVISIT") == "BASELINE")
        .then(pl.lit("HIGH"))
        .otherwise("ANRIND")
        .alias("ANRIND"),
    )

    ard = adlb.tlg.lb.t_shift()

    assert _stat(ard, "Placebo", "NORMAL to NORMAL", "n") == 1


def test_abnormal_without_a_post_baseline_rule_stops() -> None:
    with pytest.raises(SchemaError, match="prefilter"):
        ADLB.tlg.lb.t_abnormal()


def test_abnormal_with_the_sap_rule_ignores_screening() -> None:
    ard = ADLB.tlg.lb.t_abnormal(spec=LBAbnormalSpec(prefilter='pl.col("ADY") > 1'))

    assert _stat(ard, "Placebo", "High", "n", group2_level="ALT") == 0


# ── c1-808: QTc categories per parameter and visit (Q5 A, spec field for B) ──

ADEG = pl.from_repr("""\
┌─────────┬──────┬─────────┬────────┬────────────┐
│ USUBJID ┆ TRTA ┆ PARAMCD ┆ AVISIT ┆ AVALCAT1   │
│ ---     ┆ ---  ┆ ---     ┆ ---    ┆ ---        │
│ str     ┆ str  ┆ str     ┆ str    ┆ str        │
╞═════════╪══════╪═════════╪════════╪════════════╡
│ D1      ┆ Drug ┆ QTCF    ┆ WEEK 4 ┆ >500 msec  │
│ D2      ┆ Drug ┆ QTCF    ┆ WEEK 4 ┆ <=450 msec │
│ D1      ┆ Drug ┆ QTCF    ┆ WEEK 2 ┆ <=450 msec │
│ D2      ┆ Drug ┆ QTCF    ┆ WEEK 2 ┆ <=450 msec │
│ D3      ┆ Drug ┆ QTCF    ┆ WEEK 2 ┆ <=450 msec │
│ D1      ┆ Drug ┆ HR      ┆ WEEK 4 ┆ null       │
└─────────┴──────┴─────────┴────────┴────────────┘
""")
ADSL_EG = pl.DataFrame({"USUBJID": ["D1", "D2", "D3"], "TRTA": ["Drug"] * 3})


def test_qtcat_counts_per_parameter_and_visit_on_the_visit_base() -> None:
    ard = ADEG.tlg.eg.t_qtcat(adsl=ADSL_EG)

    block = "QTCF / WEEK 4"
    assert _stat(ard, "Drug", ">500 msec", "n", group2_level=block) == 1
    assert _stat(ard, "Drug", ">500 msec", "pct", group2_level=block) == 50.0
    assert _stat(ard, "Drug", "n", "n", group2_level=block) == 2
    assert _stat(ard, "Drug", "<=450 msec", "n", group2_level="QTCF / WEEK 2") == 3
    assert not ard["group2_level"].str.starts_with("HR").any()


def test_qtcat_percent_base_adsl_uses_big_n() -> None:
    ard = ADEG.tlg.eg.t_qtcat(adsl=ADSL_EG, spec=EGQtcatSpec(percent_base="adsl"))

    assert _stat(ard, "Drug", ">500 msec", "pct", group2_level="QTCF / WEEK 4") == pytest.approx(
        100 / 3
    )


def test_qtcat_stops_on_two_records_of_one_subject_in_a_cell() -> None:
    adeg = pl.concat([ADEG, ADEG.head(1)])

    with pytest.raises(SchemaError, match="D1"):
        adeg.tlg.eg.t_qtcat(adsl=ADSL_EG)


# ── c1-822: VS summary per parameter and visit ────────────────────────────────


def test_vs_summary_defaults_to_one_block_per_visit() -> None:
    advs = pl.from_repr("""\
┌─────────┬─────────┬─────────┬──────────┬───────┐
│ USUBJID ┆ TRTA    ┆ PARAMCD ┆ AVISIT   ┆ AVAL  │
│ ---     ┆ ---     ┆ ---     ┆ ---      ┆ ---   │
│ str     ┆ str     ┆ str     ┆ str      ┆ f64   │
╞═════════╪═════════╪═════════╪══════════╪═══════╡
│ P1      ┆ Placebo ┆ SYSBP   ┆ BASELINE ┆ 100.0 │
│ P2      ┆ Placebo ┆ SYSBP   ┆ BASELINE ┆ 110.0 │
│ P1      ┆ Placebo ┆ SYSBP   ┆ WEEK 2   ┆ 140.0 │
│ P2      ┆ Placebo ┆ SYSBP   ┆ WEEK 2   ┆ 150.0 │
└─────────┴─────────┴─────────┴──────────┴───────┘
""")

    ard = advs.tlg.vs.t_summary()

    assert _stat(ard, "Placebo", "BASELINE", "mean") == 105.0
    assert _stat(ard, "Placebo", "WEEK 2", "mean") == 145.0
