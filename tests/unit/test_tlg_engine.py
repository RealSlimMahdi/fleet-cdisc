"""Tests for the unified ARD engine (summarize_ard).

Covers the four engine guarantees introduced with the unification round:

1. One engine — header_rows work on every summarize_ard-backed domain,
   and the AE/VS paths are the same code as everyone else.
2. Loud denominators — percentages without an ADSL population raise;
   arms in the data but absent from ADSL raise.
3. Real nesting — child levels are counted within their parent
   (``group2``/``group2_level``), continuous statistics are computed per
   leaf cell, and zero cells are explicit (including whole zero-event
   arms from ADSL).
4. Serializable filters — string filters compute like expressions,
   survive the YAML round-trip numerically, and live ``pl.Expr`` filters
   refuse to serialize instead of being dropped.

Every asserted number is hand-recomputable from the fixtures.
"""

from __future__ import annotations

import polars as pl
import pytest

import fleet  # noqa: F401 — registers df.tlg
from fleet.core.exceptions import SchemaError
from fleet.tlg import AESummarySpec, OverallStat, Statistic
from fleet.tlg._specs import resolve_filter
from fleet.tlg.cm_namespace import CMSummarySpec
from fleet.tlg.dm_namespace import DMSummarySpec

ADSL = pl.from_repr("""
┌─────────┬─────────┬───────┐
│ USUBJID ┆ TRTA    ┆ SAFFL │
│ ---     ┆ ---     ┆ ---   │
│ str     ┆ str     ┆ str   │
╞═════════╪═════════╪═══════╡
│ S01     ┆ Placebo ┆ Y     │
│ S02     ┆ Placebo ┆ Y     │
│ S03     ┆ Drug A  ┆ Y     │
│ S04     ┆ Drug A  ┆ N     │
│ S05     ┆ Drug B  ┆ Y     │
│ S06     ┆ Drug B  ┆ Y     │
└─────────┴─────────┴───────┘
""")

# Drug B has zero AE records on purpose; NAUSEA appears under two SOCs
# for S03 so nested counting can be distinguished from flat counting.
ADAE = pl.from_repr("""
┌─────────┬─────────┬──────────┬──────────┬───────┐
│ USUBJID ┆ TRTA    ┆ AEBODSYS ┆ AEDECOD  ┆ AESER │
│ ---     ┆ ---     ┆ ---      ┆ ---      ┆ ---   │
│ str     ┆ str     ┆ str      ┆ str      ┆ str   │
╞═════════╪═════════╪══════════╪══════════╪═══════╡
│ S01     ┆ Placebo ┆ NERVOUS  ┆ HEADACHE ┆ N     │
│ S02     ┆ Placebo ┆ NERVOUS  ┆ HEADACHE ┆ N     │
│ S03     ┆ Drug A  ┆ NERVOUS  ┆ NAUSEA   ┆ N     │
│ S03     ┆ Drug A  ┆ GASTRO   ┆ NAUSEA   ┆ Y     │
└─────────┴─────────┴──────────┴──────────┴───────┘
""")


def _stat(ard: pl.DataFrame, **eq: str) -> list[float | None]:
    """Values of ``stat`` for rows matching all column==value filters."""
    out = ard
    for col, val in eq.items():
        out = out.filter(pl.col(col) == val)
    return out["stat"].to_list()


# ================================================================== #
# Loud denominators                                                    #
# ================================================================== #


class TestLoudDenominators:
    def test_pct_without_adsl_raises(self) -> None:
        with pytest.raises(SchemaError, match="adsl"):
            ADAE.tlg.ae.t_soc_pt(groupby="TRTA")

    def test_count_only_without_adsl_has_no_big_n_rows(self) -> None:
        spec = AESummarySpec(statistics=[Statistic.N_SUBJECTS])
        ard = ADAE.tlg.ae.t_summary(groupby="TRTA", spec=spec)
        assert ard.filter(pl.col("stat_name") == "N").height == 0

    def test_data_arm_missing_from_adsl_raises(self) -> None:
        bad_adsl = ADSL.filter(pl.col("TRTA") != "Placebo")
        with pytest.raises(SchemaError, match="Placebo"):
            ADAE.tlg.ae.t_summary(groupby="TRTA", adsl=bad_adsl)

    def test_missing_group_col_raises_schema_error(self) -> None:
        with pytest.raises(SchemaError, match="TRT01A"):
            ADAE.tlg.ae.t_summary(groupby="TRT01A", adsl=ADSL)

    def test_deviations_without_adsl_raises(self) -> None:
        addv = pl.DataFrame(
            {"USUBJID": ["S01"], "TRTA": ["Placebo"], "DVDECOD": ["VISIT OUT OF WINDOW"]}
        )
        with pytest.raises(SchemaError, match="adsl"):
            addv.tlg.ds.t_deviations(groupby="TRTA")


# ================================================================== #
# Arm universe from ADSL + explicit zero cells                         #
# ================================================================== #


class TestZeroCells:
    def test_zero_event_arm_keeps_its_column(self) -> None:
        ard = ADAE.tlg.ae.t_summary(groupby="TRTA", adsl=ADSL)
        assert _stat(ard, stat_name="N", group1_level="Drug B") == [2.0]
        # HEADACHE zero cell for Drug B: n=0, pct=0.0
        assert _stat(
            ard,
            variable="AEDECOD",
            variable_level="HEADACHE",
            group1_level="Drug B",
            stat_name="n",
        ) == [0.0]

    def test_zero_cell_for_level_absent_in_arm(self) -> None:
        ard = ADAE.tlg.ae.t_summary(groupby="TRTA", adsl=ADSL)
        # NAUSEA never occurs under Placebo → explicit 0 rows, one per SOC parent
        vals = _stat(
            ard,
            variable="AEDECOD",
            variable_level="NAUSEA",
            group1_level="Placebo",
            stat_name="n",
        )
        assert vals == [0.0, 0.0]

    def test_pct_uses_adsl_denominator(self) -> None:
        ard = ADAE.tlg.ae.t_summary(groupby="TRTA", adsl=ADSL)
        # HEADACHE Placebo: 2 of 2 = 100.0; Drug A NAUSEA (per SOC): 1 of 2 = 50.0
        assert _stat(
            ard,
            variable="AEDECOD",
            variable_level="HEADACHE",
            group1_level="Placebo",
            stat_name="pct",
        ) == [100.0]
        assert _stat(
            ard,
            variable="AEDECOD",
            variable_level="NAUSEA",
            group1_level="Drug A",
            stat_name="pct",
        ) == [50.0, 50.0]

    def test_prefilter_matching_nothing_still_returns_all_arms(self) -> None:
        adsl = ADSL.with_columns(
            pl.lit(None, dtype=pl.Utf8).alias("DTHFL"),
            pl.lit(None, dtype=pl.Utf8).alias("DTHCAT"),
        )
        ard = adsl.tlg.ds.t_deaths(groupby="TRTA", adsl=adsl)
        n_rows = ard.filter(pl.col("stat_name") == "N")
        assert sorted(n_rows["group1_level"].to_list()) == ["Drug A", "Drug B", "Placebo"]


# ================================================================== #
# Real nesting (group2 lineage, per-cell statistics)                   #
# ================================================================== #


class TestNesting:
    def test_pt_rows_carry_soc_parent(self) -> None:
        ard = ADAE.tlg.ae.t_summary(groupby="TRTA", adsl=ADSL)
        pt = ard.filter((pl.col("variable") == "AEDECOD") & (pl.col("stat_name") == "n"))
        assert set(pt["group2"].to_list()) == {"AEBODSYS"}
        # NAUSEA appears once per parent SOC, not merged across SOCs
        nausea_parents = pt.filter(
            (pl.col("variable_level") == "NAUSEA") & (pl.col("group1_level") == "Drug A")
        )["group2_level"].to_list()
        assert sorted(nausea_parents) == ["GASTRO", "NERVOUS"]

    def test_soc_level_counts_subjects_once(self) -> None:
        ard = ADAE.tlg.ae.t_summary(groupby="TRTA", adsl=ADSL)
        # S03 has NERVOUS and GASTRO events; each SOC counts it once
        assert _stat(
            ard,
            variable="AEBODSYS",
            variable_level="NERVOUS",
            group1_level="Drug A",
            stat_name="n",
        ) == [1.0]

    def test_continuous_stats_do_not_pool_across_parameters(self) -> None:
        adlb = pl.from_repr("""
        ┌─────────┬─────────┬─────────┬──────────┬───────┐
        │ USUBJID ┆ TRTA    ┆ PARAMCD ┆ AVISIT   ┆ AVAL  │
        │ ---     ┆ ---     ┆ ---     ┆ ---      ┆ ---   │
        │ str     ┆ str     ┆ str     ┆ str      ┆ f64   │
        ╞═════════╪═════════╪═════════╪══════════╪═══════╡
        │ S01     ┆ Placebo ┆ ALT     ┆ BASELINE ┆ 10.0  │
        │ S01     ┆ Placebo ┆ SODIUM  ┆ BASELINE ┆ 140.0 │
        │ S02     ┆ Placebo ┆ ALT     ┆ BASELINE ┆ 20.0  │
        │ S02     ┆ Placebo ┆ SODIUM  ┆ BASELINE ┆ 142.0 │
        └─────────┴─────────┴─────────┴──────────┴───────┘
        """)
        ard = adlb.tlg.lb.t_summary(groupby="TRTA", adsl=ADSL)
        visit = ard.filter((pl.col("variable") == "AVISIT") & (pl.col("stat_name") == "mean"))
        by_param = dict(zip(visit["group2_level"].to_list(), visit["stat"].to_list()))
        assert by_param["ALT"] == 15.0
        assert by_param["SODIUM"] == 141.0
        # Parent (PARAMCD) rows carry only count statistics — a mean pooled
        # across visits (baseline + post-baseline) would be meaningless.
        param_rows = ard.filter(pl.col("variable") == "PARAMCD")
        assert set(param_rows["stat_name"].to_list()) == {"n"}


# ================================================================== #
# One engine: header rows on summarize_ard-backed domains              #
# ================================================================== #


class TestHeaderRowsEverywhere:
    def test_cm_header_row_now_honoured(self) -> None:
        adcm = pl.DataFrame(
            {
                "USUBJID": ["S01", "S03"],
                "TRTA": ["Placebo", "Drug A"],
                "CMCLAS": ["NSAID", "NSAID"],
                "CMDECOD": ["ASPIRIN", "ASPIRIN"],
            }
        )
        spec = CMSummarySpec(
            header_rows=[
                OverallStat(
                    label="Total number of participants with at least one treatment",
                    statistics=[Statistic.N_SUBJECTS],
                )
            ]
        )
        ard = adcm.tlg.cm.t_summary(groupby="TRTA", adsl=ADSL, spec=spec)
        hdr = ard.filter(
            pl.col("variable_level") == "Total number of participants with at least one treatment"
        )
        assert hdr.height == 3  # one per ADSL arm, including zero-event Drug B
        by_arm = dict(zip(hdr["group1_level"].to_list(), hdr["stat"].to_list()))
        assert by_arm == {"Placebo": 1.0, "Drug A": 1.0, "Drug B": 0.0}

    def test_header_row_string_filter(self) -> None:
        spec = AESummarySpec(
            header_rows=[
                OverallStat(
                    label="Serious AEs",
                    filter='pl.col("AESER") == "Y"',
                    statistics=[Statistic.N_SUBJECTS],
                )
            ],
        )
        ard = ADAE.tlg.ae.t_summary(groupby="TRTA", adsl=ADSL, spec=spec)
        hdr = ard.filter(pl.col("variable_level") == "Serious AEs")
        by_arm = dict(zip(hdr["group1_level"].to_list(), hdr["stat"].to_list()))
        assert by_arm == {"Placebo": 0.0, "Drug A": 1.0, "Drug B": 0.0}


# ================================================================== #
# Serializable filters (YAML-complete schema path)                     #
# ================================================================== #


class TestSerializableFilters:
    def test_resolve_filter_forms(self) -> None:
        assert resolve_filter(None) is None
        assert isinstance(resolve_filter(pl.col("A") == 1), pl.Expr)
        assert isinstance(resolve_filter('pl.col("A") == 1'), pl.Expr)
        with pytest.raises(TypeError):
            resolve_filter(42)

    def test_string_filters_compute_like_expressions(self) -> None:
        expr_spec = AESummarySpec(
            adsl_filter=pl.col("SAFFL") == "Y",
            dataset_filter=pl.col("AESER") == "Y",
        )
        str_spec = AESummarySpec(
            adsl_filter='pl.col("SAFFL") == "Y"',
            dataset_filter='pl.col("AESER") == "Y"',
        )
        ard_expr = ADAE.tlg.ae.t_summary(groupby="TRTA", adsl=ADSL, spec=expr_spec)
        ard_str = ADAE.tlg.ae.t_summary(groupby="TRTA", adsl=ADSL, spec=str_spec)
        assert ard_expr.equals(ard_str)

    def test_yaml_roundtrip_preserves_numbers(self) -> None:
        spec = AESummarySpec(
            adsl_filter='pl.col("SAFFL") == "Y"',
            dataset_filter='pl.col("AESER") == "Y"',
        )
        restored = AESummarySpec.from_yaml(spec.to_yaml())
        assert restored.adsl_filter == spec.adsl_filter
        assert restored.dataset_filter == spec.dataset_filter
        original = ADAE.tlg.ae.t_summary(groupby="TRTA", adsl=ADSL, spec=spec)
        reloaded = ADAE.tlg.ae.t_summary(groupby="TRTA", adsl=ADSL, spec=restored)
        assert original.equals(reloaded)
        # The filter actually bites: SAFFL removes S04 → Drug A big-N is 1
        assert _stat(original, stat_name="N", group1_level="Drug A") == [1.0]

    def test_to_yaml_raises_on_live_expression(self) -> None:
        spec = AESummarySpec(adsl_filter=pl.col("SAFFL") == "Y")
        with pytest.raises(ValueError, match="adsl_filter"):
            spec.to_yaml()

    def test_to_yaml_raises_on_header_row_expression(self) -> None:
        spec = AESummarySpec(
            header_rows=[OverallStat(label="Serious", filter=pl.col("AESER") == "Y")]
        )
        with pytest.raises(ValueError, match="Serious"):
            spec.to_yaml()

    def test_dm_pools_load_from_yaml(self) -> None:
        yaml_str = DMSummarySpec(
            pools=[{"label": "Total", "arms": "*"}],  # type: ignore[list-item]
        ).to_yaml()
        restored = DMSummarySpec.from_yaml(yaml_str)
        adsl = ADSL.with_columns(pl.lit(64).alias("AGE"), pl.lit("F").alias("SEX"))
        ard = adsl.tlg.dm.t_summary(groupby="TRTA", spec=restored)
        assert "Total" in ard["group1_level"].to_list()
