"""Tests for the ported domain TLG namespaces (cm/dm/ds/eg/lb/mh/ex).

Mirrors the {tlg.templates} NEST tests: each template runs without error,
produces the declared object (a valid {cards} ARD), and honours a custom
``by``.  Fixtures use ``pl.from_repr`` for clarity.
"""

from __future__ import annotations

import polars as pl
import pytest

import fleet  # noqa: F401 — registers df.tlg
from fleet.tlg._ard import validate_ard

ADSL = pl.from_repr("""
┌─────────┬─────────┬─────┬─────┬────────────┬─────────┬───────┬─────────┬─────────┐
│ USUBJID ┆ TRTA    ┆ AGE ┆ SEX ┆ EOSSTT     ┆ DCSREAS ┆ DTHFL ┆ SITEID  ┆ DTHCAT  │
│ ---     ┆ ---     ┆ --- ┆ --- ┆ ---        ┆ ---     ┆ ---   ┆ ---     ┆ ---     │
│ str     ┆ str     ┆ i64 ┆ str ┆ str        ┆ str     ┆ str   ┆ str     ┆ str     │
╞═════════╪═════════╪═════╪═════╪════════════╪═════════╪═══════╪═════════╪═════════╡
│ S01     ┆ Placebo ┆  60 ┆ M   ┆ COMPLETED  ┆         ┆ N     ┆ 701     ┆         │
│ S02     ┆ Placebo ┆  70 ┆ F   ┆ DISCONT    ┆ AE      ┆ Y     ┆ 701     ┆ AE      │
│ S03     ┆ Drug A  ┆  55 ┆ M   ┆ COMPLETED  ┆         ┆ N     ┆ 702     ┆         │
│ S04     ┆ Drug A  ┆  80 ┆ F   ┆ COMPLETED  ┆         ┆ N     ┆ 702     ┆         │
└─────────┴─────────┴─────┴─────┴────────────┴─────────┴───────┴─────────┴─────────┘
""")


def _ard_ok(ard: pl.DataFrame, group_col: str = "TRTA") -> None:
    """A produced ARD validates and carries a big-N row per arm."""
    assert validate_ard(ard) == []
    n_rows = ard.filter(pl.col("stat_name") == "N")
    assert n_rows.height == 2
    assert set(n_rows["group1"].unique()) == {group_col}


def test_dm_summary() -> None:
    assert ADSL.tlg.dm.t_summary(groupby="TRTA", adsl=ADSL).height > 0
    _ard_ok(ADSL.tlg.dm.t_summary(groupby="TRTA", adsl=ADSL))


def test_ds_disposition_deaths_enrollment() -> None:
    _ard_ok(ADSL.tlg.ds.t_summary(groupby="TRTA", adsl=ADSL))
    deaths = ADSL.tlg.ds.t_deaths(groupby="TRTA", adsl=ADSL)
    assert validate_ard(deaths) == []
    assert ADSL.tlg.ds.t_enrollment(groupby="TRTA", adsl=ADSL).height > 0


def test_mh_summary() -> None:
    admh = pl.from_repr("""
    ┌─────────┬─────────┬──────────┬─────────┐
    │ USUBJID ┆ TRTA    ┆ MHBODSYS ┆ MHDECOD │
    │ ---     ┆ ---     ┆ ---      ┆ ---     │
    │ str     ┆ str     ┆ str      ┆ str     │
    ╞═════════╪═════════╪══════════╪═════════╡
    │ S01     ┆ Placebo ┆ CARDIAC  ┆ ANGINA  │
    │ S03     ┆ Drug A  ┆ CARDIAC  ┆ ANGINA  │
    └─────────┴─────────┴──────────┴─────────┘
    """)
    _ard_ok(admh.tlg.mh.t_summary(groupby="TRTA", adsl=ADSL))


def test_cm_summary() -> None:
    adcm = pl.from_repr("""
    ┌─────────┬─────────┬────────┬─────────┐
    │ USUBJID ┆ TRTA    ┆ CMCLAS ┆ CMDECOD │
    │ ---     ┆ ---     ┆ ---    ┆ ---     │
    │ str     ┆ str     ┆ str    ┆ str     │
    ╞═════════╪═════════╪════════╪═════════╡
    │ S01     ┆ Placebo ┆ NSAID  ┆ ASPIRIN │
    │ S03     ┆ Drug A  ┆ NSAID  ┆ ASPIRIN │
    └─────────┴─────────┴────────┴─────────┘
    """)
    _ard_ok(adcm.tlg.cm.t_summary(groupby="TRTA", adsl=ADSL))


@pytest.mark.parametrize("ns,param", [("eg", "QT"), ("lb", "ALT"), ("ex", "DUR")])
def test_continuous_findings(ns: str, param: str) -> None:
    df = pl.from_repr(f"""
    ┌─────────┬─────────┬─────────┬──────┬────────┐
    │ USUBJID ┆ TRTA    ┆ PARAMCD ┆ AVAL ┆ AVISIT │
    │ ---     ┆ ---     ┆ ---     ┆ ---  ┆ ---    │
    │ str     ┆ str     ┆ str     ┆ f64  ┆ str    │
    ╞═════════╪═════════╪═════════╪══════╪════════╡
    │ S01     ┆ Placebo ┆ {param:<7}┆ 10.0 ┆ W1     │
    │ S03     ┆ Drug A  ┆ {param:<7}┆ 20.0 ┆ W1     │
    └─────────┴─────────┴─────────┴──────┴────────┘
    """)
    ard = getattr(df.tlg, ns).t_summary(groupby="TRTA", adsl=ADSL)
    _ard_ok(ard)
    assert "mean" in ard["stat_name"].to_list()


def test_wave2_variants() -> None:
    adae = pl.from_repr("""
    ┌─────────┬─────────┬──────────┬─────────┬─────────┬───────┐
    │ USUBJID ┆ TRTA    ┆ AEBODSYS ┆ AEDECOD ┆ AESEV   ┆ AEREL │
    │ ---     ┆ ---     ┆ ---      ┆ ---     ┆ ---     ┆ ---   │
    │ str     ┆ str     ┆ str      ┆ str     ┆ str     ┆ str   │
    ╞═════════╪═════════╪══════════╪═════════╪═════════╪═══════╡
    │ S01     ┆ Placebo ┆ CARDIAC  ┆ ANGINA  ┆ MILD    ┆ Y     │
    │ S03     ┆ Drug A  ┆ CARDIAC  ┆ ANGINA  ┆ SEVERE  ┆ N     │
    └─────────┴─────────┴──────────┴─────────┴─────────┴───────┘
    """)
    for m in ("t_soc_pt", "t_severity", "t_relationship"):
        assert validate_ard(getattr(adae.tlg.ae, m)(groupby="TRTA", adsl=ADSL)) == []

    adcm = pl.from_repr("""
    ┌─────────┬─────────┬────────┬─────────┐
    │ USUBJID ┆ TRTA    ┆ CMCLAS ┆ CMDECOD │
    │ ---     ┆ ---     ┆ ---    ┆ ---     │
    │ str     ┆ str     ┆ str    ┆ str     │
    ╞═════════╪═════════╪════════╪═════════╡
    │ S01     ┆ Placebo ┆ NSAID  ┆ ASPIRIN │
    │ S03     ┆ Drug A  ┆ NSAID  ┆ ASPIRIN │
    └─────────┴─────────┴────────┴─────────┘
    """)
    assert validate_ard(adcm.tlg.cm.t_by_pt(groupby="TRTA", adsl=ADSL)) == []
