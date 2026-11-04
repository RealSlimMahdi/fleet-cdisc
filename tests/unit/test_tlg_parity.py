"""Dual-API parity guard + statistical edge battery (review round, point 8).

The product guarantee: every TLG is creatable via inline verbs AND via a
(valid, YAML-serializable) spec, and the two paths produce the identical
ARD.  Parametrized over all nine namespaces and over the builder's
template() selector, so a namespace cannot ship without both paths.
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl
import pytest

import fleet  # noqa: F401 — registers df.tlg
from fleet.core.exceptions import SchemaError
from fleet.tlg import TEMPLATES, AESeveritySpec, AESummarySpec, Statistic
from fleet.tlg._registry import OutputType

sys.path.insert(0, str(Path(__file__).parent.parent))
from fixtures.study import ADAE, ADSL, FRAMES  # noqa: E402

NAMESPACES = ["ae", "vs", "cm", "dm", "ds", "eg", "ex", "lb", "mh"]

NS_FRAME = {
    "ae": "ADAE",
    "vs": "ADVS",
    "cm": "ADCM",
    "dm": "ADSL",
    "ds": "ADSL",
    "eg": "ADEG",
    "ex": "ADEX",
    "lb": "ADLB",
    "mh": "ADMH",
}


@pytest.mark.parametrize("ns_name", NAMESPACES)
def test_triple_parity_inline_spec_yaml(ns_name: str) -> None:
    """builder.to_ard() == t_summary(spec=to_spec()) == YAML round-trip."""
    frame = FRAMES[NS_FRAME[ns_name]]
    ns = getattr(frame.tlg, ns_name)

    builder = ns.population(ADSL).by("TRTA")
    ard_inline = builder.to_ard()

    spec = builder.to_spec()
    ard_spec = ns.t_summary(groupby="TRTA", adsl=ADSL, spec=spec)
    assert ard_inline.equals(ard_spec), f"{ns_name}: inline != spec path"

    restored = type(spec).from_yaml(spec.to_yaml())
    ard_yaml = ns.t_summary(groupby="TRTA", adsl=ADSL, spec=restored)
    assert ard_inline.equals(ard_yaml), f"{ns_name}: YAML round-trip changed the ARD"


@pytest.mark.parametrize(
    "meta",
    [m for m in TEMPLATES.values() if m.output_type is OutputType.TABLE],
    ids=lambda m: m.id,
)
def test_template_selector_reaches_every_table(meta) -> None:
    """.template(id) materialises the same ARD as the direct method call."""
    frame = FRAMES[meta.domains[-1]]
    ns = getattr(frame.tlg, meta.namespace)
    inline = ns.population(ADSL).by("TRTA").template(meta.id).to_ard()
    direct = getattr(ns, meta.method)(groupby="TRTA", adsl=ADSL)
    assert inline.equals(direct), f"{meta.id}: template() != direct call"


def test_template_selector_rejects_foreign_namespace() -> None:
    with pytest.raises(SchemaError, match="does not belong"):
        ADAE.tlg.ae.population(ADSL).by("TRTA").template("lbt02").to_ard()


def test_template_selector_rejects_unknown_id() -> None:
    with pytest.raises(SchemaError, match="Unknown template"):
        ADAE.tlg.ae.population(ADSL).by("TRTA").template("nope01")


# ================================================================== #
# Listing parity — the fluent API produces listings too                #
# ================================================================== #


@pytest.mark.parametrize(
    "meta",
    [m for m in TEMPLATES.values() if m.output_type is OutputType.LISTING],
    ids=lambda m: m.id,
)
def test_template_selector_reaches_every_listing(meta) -> None:
    """.template(id).to_listing() materialises the direct l_listing output."""
    frame = FRAMES[meta.domains[-1]]
    ns = getattr(frame.tlg, meta.namespace)
    inline = ns.template(meta.id).to_listing()
    direct = getattr(ns, meta.method)()
    assert inline.equals(direct), f"{meta.id}: template().to_listing() != direct call"


def test_builder_listing_columns_and_sort() -> None:
    """columns()/sort_by() drive the listing spec like Column objects do."""
    from fleet.tlg import AEListingSpec, Column

    inline = ADAE.tlg.ae.columns(["USUBJID", "AEDECOD", "AESEV"]).sort_by(["USUBJID"]).to_listing()
    spec = AEListingSpec(
        columns=[
            Column(field="USUBJID"),
            Column(field="AEDECOD"),
            Column(field="AESEV"),
        ],
        sort_by=["USUBJID"],
    )
    direct = ADAE.tlg.ae.l_listing(spec=spec)
    assert inline.equals(direct)
    assert inline.columns == ["USUBJID", "AEDECOD", "AESEV"]


def test_listing_target_rejects_to_ard_and_vice_versa() -> None:
    with pytest.raises(SchemaError, match="to_listing"):
        ADAE.tlg.ae.template("ael01").to_ard()
    with pytest.raises(SchemaError, match="to_ard"):
        ADAE.tlg.ae.template("aet02").to_listing()


def test_listing_rejects_grouping_and_population_filter() -> None:
    """Listings consume neither by() nor a population filter — loud, not silent."""
    with pytest.raises(SchemaError, match="by\\(\\)"):
        ADAE.tlg.ae.by("TRTA").template("ael01").to_listing()
    with pytest.raises(SchemaError, match="adsl_filter"):
        (
            ADAE.tlg.ae.population(ADSL, adsl_filter='pl.col("SAFFL") == "Y"')
            .template("ael01")
            .to_listing()
        )


def test_namespace_without_listing_raises() -> None:
    advs = FRAMES["ADVS"]
    with pytest.raises(SchemaError, match="no listing"):
        advs.tlg.vs.by("TRTA").to_listing()


# ================================================================== #
# New verb parity — value / label / decimals / Row objects             #
# ================================================================== #


def test_value_verb_matches_spec_path() -> None:
    from fleet.tlg import LBChgSpec

    adlb = FRAMES["ADLB"]
    builder = adlb.tlg.lb.population(ADSL).by("TRTA").template("lbt02").value("CHG")
    ard_inline = builder.to_ard()
    ard_spec = adlb.tlg.lb.t_chg(groupby="TRTA", adsl=ADSL, spec=LBChgSpec(value_col="CHG"))
    assert ard_inline.equals(ard_spec)


def test_rows_accepts_row_objects() -> None:
    from fleet.tlg import AESummarySpec, Row

    row_objs = [Row(field="AEBODSYS", label="SOC"), Row(field="AEDECOD", label="PT")]
    inline = ADAE.tlg.ae.population(ADSL).by("TRTA").rows(row_objs).to_ard()
    direct = ADAE.tlg.ae.t_summary(groupby="TRTA", adsl=ADSL, spec=AESummarySpec(rows=row_objs))
    assert inline.equals(direct)


def test_decimals_verb_threads_to_fmt_fn() -> None:
    ard = (
        ADAE.tlg.ae.population(ADSL)
        .by("TRTA")
        .rows(["AEBODSYS"])
        .decimals({"pct": "xx.xx"})
        .to_ard()
    )
    pct = ard.filter(pl.col("stat_name") == "pct")
    assert set(pct["fmt_fn"].to_list()) == {"xx.xx"}


# ================================================================== #
# Statistical edge battery                                             #
# ================================================================== #


class TestEdgeBattery:
    def test_empty_analysis_dataset_yields_population_only(self) -> None:
        ard = ADAE.head(0).tlg.ae.t_summary(groupby="TRTA", adsl=ADSL)
        n_rows = ard.filter(pl.col("stat_name") == "N")
        assert n_rows.height == 3  # all arms survive an empty ADAE
        assert ard.filter(pl.col("variable") != "").height == 0

    def test_all_null_severity_keeps_soc_rows(self) -> None:
        adae = ADAE.with_columns(pl.lit(None, dtype=pl.Utf8).alias("AESEV"))
        ard = adae.tlg.ae.t_severity(groupby="TRTA", adsl=ADSL)
        assert ard.filter(pl.col("variable") == "AEBODSYS").height > 0
        # c1-442: a null intensity counts under "Missing", so rows add up to the SOC.
        levels = ard.filter(pl.col("variable") == "AESEV")["variable_level"].unique()
        assert levels.to_list() == ["Missing"]

    def test_single_subject_arm_sd_is_null(self) -> None:
        advs = pl.from_repr("""\
┌─────────┬─────────┬─────────┬────────┬──────┐
│ USUBJID ┆ TRTA    ┆ PARAMCD ┆ AVISIT ┆ AVAL │
│ ---     ┆ ---     ┆ ---     ┆ ---    ┆ ---  │
│ str     ┆ str     ┆ str     ┆ str    ┆ f64  │
╞═════════╪═════════╪═════════╪════════╪══════╡
│ S01     ┆ Placebo ┆ SYSBP   ┆ WEEK 2 ┆ 120  │
└─────────┴─────────┴─────────┴────────┴──────┘
""")
        adsl = pl.from_repr("""\
┌─────────┬─────────┐
│ USUBJID ┆ TRTA    │
│ ---     ┆ ---     │
│ str     ┆ str     │
╞═════════╪═════════╡
│ S01     ┆ Placebo │
└─────────┴─────────┘
""")
        ard = advs.tlg.vs.t_summary(groupby="TRTA", adsl=adsl)
        sd = ard.filter(pl.col("stat_name") == "sd")["stat"].to_list()
        assert sd == [None]

    def test_treatment_emergent_string_filter(self) -> None:
        spec = AESummarySpec(dataset_filter='pl.col("TRTEMFL") == "Y"')
        ard = ADAE.tlg.ae.t_summary(groupby="TRTA", adsl=ADSL, spec=spec)
        # S06's DIZZINESS is not treatment-emergent → excluded everywhere
        assert "DIZZINESS" not in ard["variable_level"].to_list()

    def test_severity_partition_property_on_study(self) -> None:
        """Worst-case invariant: intensity rows partition each SOC count."""
        ard = ADAE.tlg.ae.t_severity(groupby="TRTA", adsl=ADSL)
        socs = ard.filter((pl.col("variable") == "AEBODSYS") & (pl.col("stat_name") == "n"))
        for row in socs.iter_rows(named=True):
            sev_sum = ard.filter(
                (pl.col("variable") == "AESEV")
                & (pl.col("group2_level") == row["variable_level"])
                & (pl.col("group1_level") == row["group1_level"])
                & (pl.col("stat_name") == "n")
            )["stat"].sum()
            assert sev_sum == row["stat"], (
                f"{row['group1_level']}/{row['variable_level']}: "
                f"severity sum {sev_sum} != SOC n {row['stat']}"
            )

    def test_custom_severity_spec_still_partitions(self) -> None:
        spec = AESeveritySpec(severity_order=["MILD", "MODERATE", "SEVERE"])
        ard = ADAE.tlg.ae.t_severity(groupby="TRTA", adsl=ADSL, spec=spec)
        any_ae = ADAE.tlg.ae.t_summary(
            groupby="TRTA",
            adsl=ADSL,
            spec=AESummarySpec(statistics=[Statistic.N_SUBJECTS]),
        )
        # Total subjects at any severity == subjects with any AE, per arm
        for arm in ("Placebo", "Drug A", "Drug B"):
            sev_total = ard.filter(
                (pl.col("variable") == "AESEV")
                & (pl.col("group1_level") == arm)
                & (pl.col("stat_name") == "n")
            )["stat"].sum()
            soc_any = any_ae.filter(
                (pl.col("variable") == "AEBODSYS")
                & (pl.col("group1_level") == arm)
                & (pl.col("stat_name") == "n")
            )["stat"].sum()
            assert sev_total == soc_any
