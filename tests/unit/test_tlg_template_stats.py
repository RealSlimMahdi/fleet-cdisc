"""Numeric tests for the template statistical fixes (review round, point 5).

Every assertion is hand-recomputable from the fixture: worst-case
severity/grade/relationship dedup, No-Coding-Available levels, CHG-based
lab change tables, true shift cross-tabs, GDSR abnormality denominators,
DM population filtering, EX overall-block selection, and DTHT01 deaths
denominators.
"""

from __future__ import annotations

import polars as pl
import pytest

import fleet  # noqa: F401 — registers df.tlg
from fleet.core.exceptions import SchemaError
from fleet.tlg._registry import TEMPLATES

ADSL = pl.from_repr("""
┌─────────┬─────────┐
│ USUBJID ┆ TRTA    │
│ ---     ┆ ---     │
│ str     ┆ str     │
╞═════════╪═════════╡
│ S01     ┆ Placebo │
│ S02     ┆ Placebo │
│ S03     ┆ Drug A  │
│ S04     ┆ Drug A  │
└─────────┴─────────┘
""")

# S01 has a MILD and a SEVERE event in the same SOC (worst-case probe);
# S04's event is uncoded (null SOC/PT).
ADAE = pl.DataFrame(
    {
        "USUBJID": ["S01", "S01", "S02", "S03", "S04"],
        "TRTA": ["Placebo", "Placebo", "Placebo", "Drug A", "Drug A"],
        "AEBODSYS": ["NERVOUS", "NERVOUS", "NERVOUS", "NERVOUS", None],
        "AEDECOD": ["HEADACHE", "MIGRAINE", "HEADACHE", "HEADACHE", None],
        "AESEV": ["MILD", "SEVERE", "MILD", "MODERATE", "MILD"],
        "AEREL": ["N", "Y", "N", "N", "N"],
        "AETOXGR": ["1", "3", "1", "2", "1"],
    }
)


def _stat(ard: pl.DataFrame, **eq: str) -> list[float | None]:
    out = ard
    for col, val in eq.items():
        out = out.filter(pl.col(col) == val)
    return out["stat"].to_list()


class TestWorstCaseAE:
    def test_severity_counts_subject_once_at_worst(self) -> None:
        ard = ADAE.tlg.ae.t_severity(groupby="TRTA", adsl=ADSL)
        sev = ard.filter(
            (pl.col("variable") == "AESEV")
            & (pl.col("group1_level") == "Placebo")
            & (pl.col("group2_level") == "NERVOUS")
            & (pl.col("stat_name") == "n")
        )
        by_level = dict(zip(sev["variable_level"].to_list(), sev["stat"].to_list()))
        # S01 counted ONLY at SEVERE (worst), S02 at MILD; MODERATE is an
        # explicit zero cell (level observed in Drug A)
        assert by_level == {"MILD": 1.0, "MODERATE": 0.0, "SEVERE": 1.0}

    def test_severity_partition_sums_to_soc_count(self) -> None:
        ard = ADAE.tlg.ae.t_severity(groupby="TRTA", adsl=ADSL)
        for arm in ("Placebo", "Drug A"):
            soc = ard.filter(
                (pl.col("variable") == "AEBODSYS")
                & (pl.col("variable_level") == "NERVOUS")
                & (pl.col("group1_level") == arm)
                & (pl.col("stat_name") == "n")
            )["stat"].to_list()
            sev_sum = sum(
                ard.filter(
                    (pl.col("variable") == "AESEV")
                    & (pl.col("group2_level") == "NERVOUS")
                    & (pl.col("group1_level") == arm)
                    & (pl.col("stat_name") == "n")
                )["stat"].to_list()
            )
            assert sev_sum == soc[0]

    def test_severity_rank_is_clinical_not_alphabetical(self) -> None:
        # Alphabetically MILD < MODERATE < SEVERE happens to agree, so use
        # a custom order to prove the rank map drives the reduction.
        from fleet.tlg.ae_namespace import AESeveritySpec

        spec = AESeveritySpec(severity_order=["SEVERE", "MODERATE", "MILD"])
        ard = ADAE.tlg.ae.t_severity(groupby="TRTA", adsl=ADSL, spec=spec)
        sev = ard.filter(
            (pl.col("variable") == "AESEV")
            & (pl.col("group1_level") == "Placebo")
            & (pl.col("group2_level") == "NERVOUS")
            & (pl.col("stat_name") == "n")
        )
        by_level = dict(zip(sev["variable_level"].to_list(), sev["stat"].to_list()))
        # Inverted order: MILD now ranks worst → S01 counted at MILD
        assert by_level == {"MILD": 2.0, "MODERATE": 0.0}

    def test_grade_counts_subject_once_at_highest(self) -> None:
        ard = ADAE.tlg.ae.t_grade(groupby="TRTA", adsl=ADSL)
        grades = ard.filter(
            (pl.col("variable") == "AETOXGR")
            & (pl.col("group1_level") == "Placebo")
            & (pl.col("group2_level") == "NERVOUS")
            & (pl.col("stat_name") == "n")
        )
        by_level = dict(zip(grades["variable_level"].to_list(), grades["stat"].to_list()))
        # S01 worst grade 3, S02 grade 1; grade 2 is Drug A's zero cell
        assert by_level == {"1": 1.0, "2": 0.0, "3": 1.0}

    def test_relationship_related_if_any_related(self) -> None:
        ard = ADAE.tlg.ae.t_relationship(groupby="TRTA", adsl=ADSL)
        rel = ard.filter(
            (pl.col("variable") == "AEREL")
            & (pl.col("group1_level") == "Placebo")
            & (pl.col("group2_level") == "NERVOUS")
            & (pl.col("stat_name") == "n")
        )
        by_level = dict(zip(rel["variable_level"].to_list(), rel["stat"].to_list()))
        # S01 has one related event → counted once as Y; S02 as N
        assert by_level == {"N": 1.0, "Y": 1.0}

    def test_registry_aet04_is_grade_table(self) -> None:
        assert TEMPLATES["aet04"].method == "t_grade"
        assert "Grade" in TEMPLATES["aet04"].title


class TestNoCodingAvailable:
    def test_ae_uncoded_events_visible(self) -> None:
        ard = ADAE.tlg.ae.t_summary(groupby="TRTA", adsl=ADSL)
        assert _stat(
            ard,
            variable="AEBODSYS",
            variable_level="No Coding Available",
            group1_level="Drug A",
            stat_name="n",
        ) == [1.0]

    def test_cm_subject_with_only_uncoded_meds_counted(self) -> None:
        adcm = pl.DataFrame(
            {
                "USUBJID": ["S01", "S02"],
                "TRTA": ["Placebo", "Placebo"],
                "CMCLAS": ["NSAID", None],
                "CMDECOD": ["ASPIRIN", None],
            }
        )
        ard = adcm.tlg.cm.t_summary(groupby="TRTA", adsl=ADSL)
        assert _stat(
            ard,
            variable="CMCLAS",
            variable_level="No Coding Available",
            group1_level="Placebo",
            stat_name="n",
        ) == [1.0]

    def test_mh_uncoded_terms_visible(self) -> None:
        admh = pl.DataFrame(
            {
                "USUBJID": ["S01"],
                "TRTA": ["Placebo"],
                "MHBODSYS": [None],
                "MHDECOD": [None],
            },
            schema={
                "USUBJID": pl.Utf8,
                "TRTA": pl.Utf8,
                "MHBODSYS": pl.Utf8,
                "MHDECOD": pl.Utf8,
            },
        )
        ard = admh.tlg.mh.t_summary(groupby="TRTA", adsl=ADSL)
        assert _stat(
            ard,
            variable="MHBODSYS",
            variable_level="No Coding Available",
            group1_level="Placebo",
            stat_name="n",
        ) == [1.0]


ADLB_CHG = pl.DataFrame(
    {
        "USUBJID": ["S01", "S01", "S02", "S02"],
        "TRTA": ["Placebo"] * 4,
        "PARAMCD": ["ALT"] * 4,
        "AVISIT": ["BASELINE", "WEEK 1", "BASELINE", "WEEK 1"],
        "ABLFL": ["Y", None, "Y", None],  # ADaM-standard Y / null coding
        "AVAL": [10.0, 16.0, 20.0, 22.0],
        "CHG": [None, 6.0, None, 2.0],
    }
)


class TestLabChange:
    def test_chg_summarized_not_aval(self) -> None:
        ard = ADLB_CHG.tlg.lb.t_chg(groupby="TRTA", adsl=ADSL)
        cell = ard.filter(
            (pl.col("variable") == "AVISIT")
            & (pl.col("variable_level") == "WEEK 1")
            & (pl.col("group2_level") == "ALT")
            & (pl.col("group1_level") == "Placebo")
        )
        stats = dict(zip(cell["stat_name"].to_list(), cell["stat"].to_list()))
        assert stats["mean"] == 4.0  # (6 + 2) / 2 — CHG, not AVAL (19.0)
        assert stats["n"] == 2.0  # paired n: subjects with non-null CHG

    def test_null_ablfl_data_does_not_crash_or_leak_baseline(self) -> None:
        ard = ADLB_CHG.tlg.lb.t_chg(groupby="TRTA", adsl=ADSL)
        visits = set(ard.filter(pl.col("variable") == "AVISIT")["variable_level"].to_list())
        assert visits == {"WEEK 1"}  # baseline rows excluded null-safely

    def test_missing_chg_column_raises(self) -> None:
        with pytest.raises(SchemaError, match="CHG"):
            ADLB_CHG.drop("CHG").tlg.lb.t_chg(groupby="TRTA", adsl=ADSL)


class TestLabShift:
    ADLB = pl.DataFrame(
        {
            "USUBJID": ["S01", "S01", "S01", "S02"],
            "TRTA": ["Placebo"] * 4,
            "PARAMCD": ["ALT"] * 4,
            "ABLFL": ["Y", None, None, None],
            "BNRIND": ["NORMAL", "NORMAL", "NORMAL", "LOW"],
            "ANRIND": ["NORMAL", "HIGH", "NORMAL", "NORMAL"],
        }
    )

    def test_true_cross_tab_at_worst_post_baseline(self) -> None:
        ard = self.ADLB.tlg.lb.t_shift(groupby="TRTA", adsl=ADSL)
        shifts = ard.filter((pl.col("variable") == "SHIFT") & (pl.col("stat_name") == "n"))
        by_cell = {
            (r["group2_level"], r["variable_level"]): r["stat"]
            for r in shifts.iter_rows(named=True)
            if r["group1_level"] == "Placebo"
        }
        # S01: worst post-baseline = HIGH (not the W2 NORMAL, not baseline)
        assert by_cell[("ALT", "NORMAL to HIGH")] == 1.0
        assert by_cell[("ALT", "LOW to NORMAL")] == 1.0

    def test_no_percentages_emitted(self) -> None:
        ard = self.ADLB.tlg.lb.t_shift(groupby="TRTA", adsl=ADSL)
        assert "pct" not in ard["stat_name"].to_list()


class TestLabAbnormal:
    ADLB = pl.DataFrame(
        {
            "USUBJID": ["S01", "S01", "S02", "S02", "S03", "S03"],
            "TRTA": ["Placebo"] * 6,
            "PARAMCD": ["ALT"] * 6,
            "ABLFL": ["Y", None, "Y", None, "Y", None],
            "BNRIND": ["NORMAL", "NORMAL", "HIGH", "HIGH", "NORMAL", "NORMAL"],
            "ANRIND": ["NORMAL", "HIGH", "HIGH", "HIGH", "NORMAL", "NORMAL"],
        }
    )
    ADSL3 = pl.DataFrame({"USUBJID": ["S01", "S02", "S03"], "TRTA": ["Placebo"] * 3})

    def test_baseline_abnormal_excluded_from_both_sides(self) -> None:
        ard = self.ADLB.tlg.lb.t_abnormal(groupby="TRTA", adsl=self.ADSL3)
        high = ard.filter(
            (pl.col("variable") == "ABNORMAL")
            & (pl.col("variable_level") == "High")
            & (pl.col("group2_level") == "ALT")
        )
        stats = dict(zip(high["stat_name"].to_list(), high["stat"].to_list()))
        # S02 is baseline-HIGH → out of numerator AND denominator.
        # Eligible: S01, S03 (N=2); abnormal post-baseline: S01 only.
        assert stats["n"] == 1.0
        assert stats["N"] == 2.0
        assert stats["pct"] == 50.0

    def test_low_direction_has_full_denominator(self) -> None:
        ard = self.ADLB.tlg.lb.t_abnormal(groupby="TRTA", adsl=self.ADSL3)
        low = ard.filter(
            (pl.col("variable") == "ABNORMAL")
            & (pl.col("variable_level") == "Low")
            & (pl.col("group2_level") == "ALT")
        )
        stats = dict(zip(low["stat_name"].to_list(), low["stat"].to_list()))
        # Nobody baseline-LOW → all 3 assessed subjects eligible, 0 abnormal
        assert stats["n"] == 0.0
        assert stats["N"] == 3.0
        assert stats["pct"] == 0.0


class TestDMPopulationFilter:
    def test_filter_applies_to_numerators_and_age(self) -> None:
        from fleet.tlg.dm_namespace import DMSummarySpec

        adsl = pl.DataFrame(
            {
                "USUBJID": ["S01", "S02", "S03"],
                "TRTA": ["Placebo"] * 3,
                "SAFFL": ["Y", "Y", "N"],
                "AGE": [60, 70, 80],
                "SEX": ["M", "F", "F"],
            }
        )
        spec = DMSummarySpec(adsl_filter='pl.col("SAFFL") == "Y"')
        ard = adsl.tlg.dm.t_summary(groupby="TRTA", spec=spec)
        assert _stat(ard, stat_name="N", group1_level="Placebo") == [2.0]
        # S03 (out of population) contributes nowhere: F n=1 of 2, mean 65
        assert _stat(
            ard, variable="SEX", variable_level="F", group1_level="Placebo", stat_name="n"
        ) == [1.0]
        assert _stat(
            ard, variable="SEX", variable_level="F", group1_level="Placebo", stat_name="pct"
        ) == [50.0]
        assert _stat(ard, variable="AGE", stat_name="mean") == [65.0]


class TestEXOverallBlock:
    def test_interval_records_excluded(self) -> None:
        adex = pl.DataFrame(
            {
                "USUBJID": ["S01"] * 5 + ["S02"],
                "TRTA": ["Placebo"] * 6,
                "PARAMCD": ["TDOSE"] * 6,
                "PARCAT1": ["OVERALL", "WEEK", "WEEK", "WEEK", "WEEK", "OVERALL"],
                "AVAL": [100.0, 25.0, 25.0, 25.0, 25.0, 200.0],
            }
        )
        ard = adex.tlg.ex.t_summary(groupby="TRTA", adsl=ADSL)
        cell = ard.filter((pl.col("variable") == "PARAMCD") & (pl.col("group1_level") == "Placebo"))
        stats = dict(zip(cell["stat_name"].to_list(), cell["stat"].to_list()))
        assert stats["mean"] == 150.0  # (100 + 200) / 2, not record-weighted
        assert stats["n"] == 2.0

    def test_check_warns_on_duplicate_records(self) -> None:
        adex = pl.DataFrame(
            {
                "USUBJID": ["S01", "S01"],
                "TRTA": ["Placebo"] * 2,
                "PARAMCD": ["TDOSE"] * 2,
                "AVAL": [50.0, 60.0],
            }
        )
        report = adex.tlg.ex.check()
        assert any("record-weighted" in msg for msg in report)


class TestDeaths:
    ADSL_DTH = pl.DataFrame(
        {
            "USUBJID": ["S01", "S02", "S03", "S04"],
            "TRTA": ["Placebo"] * 4,
            "DTHFL": ["Y", "Y", "N", "N"],
            "DTHCAT": ["ADVERSE EVENT", None, None, None],
        }
    )

    def test_total_deaths_uses_population_denominator(self) -> None:
        ard = self.ADSL_DTH.tlg.ds.t_deaths(groupby="TRTA")
        total = ard.filter(pl.col("variable_level") == "Total Number of Deaths")
        stats = dict(zip(total["stat_name"].to_list(), total["stat"].to_list()))
        assert stats["n"] == 2.0
        assert stats["pct"] == 50.0  # 2 of 4 population

    def test_causes_use_deaths_denominator_and_unknown_level(self) -> None:
        ard = self.ADSL_DTH.tlg.ds.t_deaths(groupby="TRTA")
        causes = ard.filter(pl.col("variable") == "DTHCAT")
        by_cell = {
            (r["variable_level"], r["stat_name"]): r["stat"] for r in causes.iter_rows(named=True)
        }
        assert by_cell[("ADVERSE EVENT", "n")] == 1.0
        assert by_cell[("ADVERSE EVENT", "pct")] == 50.0  # 1 of 2 deaths
        assert by_cell[("Unknown", "n")] == 1.0  # missing cause is visible
        assert by_cell[("Unknown", "pct")] == 50.0

    def test_population_n_rows_only(self) -> None:
        ard = self.ADSL_DTH.tlg.ds.t_deaths(groupby="TRTA")
        n_rows = ard.filter((pl.col("stat_name") == "N") & (pl.col("variable") == ""))
        assert n_rows["stat"].to_list() == [4.0]  # one N per arm, population


class TestReviewRoundTwo:
    """Regressions for findings on the point-5 commit (unverified finder
    reports, confirmed by hand before fixing)."""

    def test_dataset_filter_bites_before_worst_case(self) -> None:
        from fleet.tlg import AESeveritySpec

        # Excluding S01's SEVERE record must leave S01 counted at MILD —
        # not dropped because dedup already picked the filtered record.
        spec = AESeveritySpec(dataset_filter='pl.col("AEDECOD") != "MIGRAINE"')
        ard = ADAE.tlg.ae.t_severity(groupby="TRTA", adsl=ADSL, spec=spec)
        sev = ard.filter(
            (pl.col("variable") == "AESEV")
            & (pl.col("group1_level") == "Placebo")
            & (pl.col("group2_level") == "NERVOUS")
            & (pl.col("stat_name") == "n")
        )
        by_level = dict(zip(sev["variable_level"].to_list(), sev["stat"].to_list()))
        assert by_level.get("MILD") == 2.0
        assert "SEVERE" not in by_level

    def test_grade_matches_numeric_aetoxgr(self) -> None:
        adae = ADAE.with_columns(pl.col("AETOXGR").cast(pl.Float64))
        ard = adae.tlg.ae.t_grade(groupby="TRTA", adsl=ADSL)
        grades = set(ard.filter(pl.col("variable") == "AETOXGR")["variable_level"].to_list())
        assert grades == {"1", "2", "3"}  # not "1.0"/"3.0"

    def test_deaths_dataset_filter_applies_to_death_ids(self) -> None:
        adsl = pl.DataFrame(
            {
                "USUBJID": ["S01", "S02", "S03", "S04"],
                "TRTA": ["Placebo"] * 4,
                "DTHFL": ["Y", "Y", "N", "N"],
                "DTHCAT": ["ADVERSE EVENT", "OTHER", None, None],
                "ANL01FL": ["Y", "N", "Y", "Y"],
            }
        )
        from fleet.tlg import DSDeathsSpec

        spec = DSDeathsSpec(dataset_filter='pl.col("ANL01FL") == "Y"')
        ard = adsl.tlg.ds.t_deaths(groupby="TRTA", spec=spec)
        total = ard.filter(pl.col("variable_level") == "Total Number of Deaths")
        stats = dict(zip(total["stat_name"].to_list(), total["stat"].to_list()))
        assert stats["n"] == 1.0  # S02 excluded by the analysis flag
        causes = ard.filter(pl.col("variable") == "DTHCAT")
        assert set(causes["variable_level"].to_list()) == {"ADVERSE EVENT"}
        pct = causes.filter(pl.col("stat_name") == "pct")["stat"].to_list()
        assert pct == [100.0]  # 1 of 1 death after filtering

    def test_deaths_pool_with_zero_death_arm_does_not_crash(self) -> None:
        from fleet.tlg import DSDeathsSpec, GroupPool

        adsl = pl.DataFrame(
            {
                "USUBJID": ["S01", "S02", "S03", "S04"],
                "TRTA": ["Placebo", "Placebo", "Drug A", "Drug A"],
                "DTHFL": ["Y", "N", "N", "N"],
                "DTHCAT": ["ADVERSE EVENT", None, None, None],
            }
        )
        spec = DSDeathsSpec(pools=[GroupPool(label="Both", arms=["Placebo", "Drug A"])])
        ard = adsl.tlg.ds.t_deaths(groupby="TRTA", spec=spec)
        # Headline carries the pool; the cause block drops it (no deaths in
        # Drug A) instead of crashing.
        total = ard.filter(
            (pl.col("variable_level") == "Total Number of Deaths")
            & (pl.col("group1_level") == "Both")
            & (pl.col("stat_name") == "n")
        )
        assert total["stat"].to_list() == [1.0]

    def test_abnormal_missing_group_column_raises_schema_error(self) -> None:
        adlb = TestLabAbnormal.ADLB
        with pytest.raises(SchemaError, match="TRT01A"):
            adlb.tlg.lb.t_abnormal(groupby="TRT01A", adsl=TestLabAbnormal.ADSL3)
