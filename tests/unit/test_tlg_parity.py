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
        assert ard.filter(pl.col("variable") == "AESEV").height == 0

    def test_single_subject_arm_sd_is_null(self) -> None:
        advs = pl.DataFrame(
            {
                "USUBJID": ["S01"],
                "TRTA": ["Placebo"],
                "PARAMCD": ["SYSBP"],
                "AVAL": [120.0],
            }
        )
        adsl = pl.DataFrame({"USUBJID": ["S01"], "TRTA": ["Placebo"]})
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
