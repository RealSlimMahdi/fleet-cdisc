"""Regression tests for the medium and low ADaM audit findings (package ml-adam-b).

Each test names the finding ID it pins.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration
from fleet.core.exceptions import DerivationError

# ------------------------------------------------------------------ #
# TTE                                                                  #
# ------------------------------------------------------------------ #

TTE_ADSL = """
┌─────────┬────────────┬────────────┬────────────┬────────┐
│ USUBJID ┆ TRTSDT     ┆ DTHDT      ┆ LSTALVDT   ┆ STRAT  │
│ ---     ┆ ---        ┆ ---        ┆ ---        ┆ ---    │
│ str     ┆ date       ┆ date       ┆ date       ┆ str    │
╞═════════╪════════════╪════════════╪════════════╪════════╡
│ 01      ┆ 2024-01-01 ┆ 2024-03-01 ┆ 2024-03-01 ┆ A      │
│ 02      ┆ 2024-01-01 ┆ null       ┆ 2024-04-01 ┆ B      │
└─────────┴────────────┴────────────┴────────────┴────────┘
"""


def _tte_frames(adsl: pl.DataFrame) -> dict:
    return dict(
        start="TRTSDT",
        events={"DEATH": adsl.filter(pl.col("DTHDT").is_not_null()).select("USUBJID", ADT="DTHDT")},
        censors={1: adsl.select("USUBJID", ADT="LSTALVDT", EVNTDESC=pl.lit("ALIVE"))},
    )


def test_c1_373_explain_prints_in_a_plain_script():
    """c1-373: explain=True prints the trace in a fresh process with no logging setup."""
    script = textwrap.dedent(
        """
        import sys
        import polars as pl
        import fleet
        adsl = pl.from_repr(sys.argv[1])
        print("BEGIN", flush=True)
        adsl.adam.tte.param(
            "OS", "Overall Survival", start="TRTSDT",
            events={"DEATH": adsl.filter(pl.col("DTHDT").is_not_null())
                                 .select("USUBJID", ADT="DTHDT")},
            censors={1: adsl.select("USUBJID", ADT="LSTALVDT", EVNTDESC=pl.lit("ALIVE"))},
            explain=True,
        )
        print("END", flush=True)
        """
    )
    out = subprocess.run(
        [sys.executable, "-c", script, TTE_ADSL], capture_output=True, text=True, check=False
    )
    assert out.returncode == 0, out.stderr
    text = out.stdout
    between = text[text.index("BEGIN") : text.index("END")]
    assert "TTE decision trace" in between


def test_c1_377_avalu_is_null_where_aval_is_null():
    adsl = pl.from_repr(TTE_ADSL).with_columns(
        pl.when(pl.col("USUBJID") == "02").then(None).otherwise(pl.col("TRTSDT")).alias("TRTSDT")
    )
    out = adsl.adam.tte.param("OS", "Overall Survival", **_tte_frames(adsl)).aval().to_frame()
    row = out.filter(pl.col("USUBJID") == "02").row(0, named=True)
    assert row["AVAL"] is None
    assert row["AVALU"] is None
    assert out.filter(pl.col("USUBJID") == "01")["AVALU"].to_list() == ["DAYS"]


def test_c1_378_by_with_no_candidate_names_by_and_sources():
    adsl = pl.from_repr(TTE_ADSL)
    empty = pl.DataFrame(schema={"USUBJID": pl.String, "ADT": pl.Date, "AEDECOD": pl.String})
    with pytest.raises(DerivationError, match=r"by=\['AEDECOD'\].*AE"):
        adsl.adam.tte.param(
            "TT",
            "Time to AE",
            start="TRTSDT",
            events={"AE": empty},
            censors={1: empty.with_columns(EVNTDESC=pl.lit("X"))},
            by=["AEDECOD"],
        )


def test_c1_378_km_data_uses_the_pin_join_key():
    adsl = pl.from_repr(TTE_ADSL).rename({"USUBJID": "SUBJID"})
    frames = dict(
        start="TRTSDT",
        events={"DEATH": adsl.filter(pl.col("DTHDT").is_not_null()).select("SUBJID", ADT="DTHDT")},
        censors={1: adsl.select("SUBJID", ADT="LSTALVDT", EVNTDESC=pl.lit("ALIVE"))},
    )
    km = (
        adsl.adam.tte.pin("ADSL", adsl, join_on="SUBJID")
        .param("OS", "Overall Survival", **frames)
        .aval()
        .km_data("OS", by=["STRAT"])
        .sort("SUBJID")
    )
    assert km.columns == ["SUBJID", "duration", "event", "STRAT"]
    assert km["STRAT"].to_list() == ["A", "B"]


@pytest.mark.parametrize("col", ["CNSR", "ADT", "ADTM", "STARTDT", "STARTDTM"])
def test_c1_378_derived_columns_refused_in_set_values_to(col):
    adsl = pl.from_repr(TTE_ADSL)
    with pytest.raises(DerivationError, match=f"'{col}'.*cannot be set in set_values_to"):
        adsl.adam.tte.param("OS", "Overall Survival", **_tte_frames(adsl), set_values_to={col: 2})


def test_c1_372_paramcd_from_set_values_to_collides():
    adsl = pl.from_repr(TTE_ADSL)
    ns = adsl.adam.tte.param("OS", "Overall Survival", **_tte_frames(adsl))
    with pytest.raises(DerivationError, match="PARAMCD 'OS' already exists"):
        ns.param(
            "OS2",
            **_tte_frames(adsl),
            set_values_to={"PARAMCD": "OS", "PARAM": "Overall Survival"},
        )


def test_c1_372_by_expression_paramcd_collides_on_a_second_call():
    adsl = pl.from_repr(TTE_ADSL)
    frames = dict(
        start="TRTSDT",
        events={
            "E": adsl.filter(pl.col("DTHDT").is_not_null()).select("USUBJID", "STRAT", ADT="DTHDT")
        },
        censors={1: adsl.select("USUBJID", "STRAT", ADT="LSTALVDT", EVNTDESC=pl.lit("ALIVE"))},
        by=["STRAT"],
        set_values_to={
            "PARAMCD": pl.concat_str(pl.lit("T"), pl.col("STRAT")),
            "PARAM": pl.concat_str(pl.lit("Time "), pl.col("STRAT")),
        },
    )
    ns = adsl.adam.tte.param("T", **frames)
    with pytest.raises(DerivationError, match="PARAMCD 'TA' already exists"):
        ns.param("T", **frames)


def test_c1_374_km_data_unknown_paramcd_raises():
    adsl = pl.from_repr(TTE_ADSL)
    ns = adsl.adam.tte.param("OS", "Overall Survival", **_tte_frames(adsl)).aval()
    with pytest.raises(DerivationError, match=r"PARAMCD 'OSS' not found; present: \['OS'\]"):
        ns.km_data("OSS")


def test_c1_374_km_data_without_paramcd_column_raises():
    adsl = pl.from_repr(TTE_ADSL)
    ns = adsl.with_columns(AVAL=pl.lit(1.0), CNSR=pl.lit(0)).adam.tte
    with pytest.raises(DerivationError, match="no PARAMCD column"):
        ns.km_data("OS")


def test_c1_374_km_data_warns_on_null_duration():
    adsl = pl.from_repr(TTE_ADSL)
    ns = (
        adsl.adam.tte.param("OS", "Overall Survival", **_tte_frames(adsl))
        .aval()
        .param("TTD", "Time to Death", **_tte_frames(adsl))
    )
    with pytest.warns(UserWarning, match=r"2 row\(s\) have a null AVAL.*\['01', '02'\]"):
        km = ns.km_data("TTD")
    assert km["duration"].to_list() == [None, None]


def test_c1_376_lineage_lists_the_real_outputs():
    adsl = pl.from_repr(TTE_ADSL)
    ns = adsl.adam.tte.param("OS", "Overall Survival", **_tte_frames(adsl), stop_at=["DTHDT"])
    nodes = {n.name: n for n in ns._lineage if n.verb == "param"}
    assert "OS" not in nodes
    assert {"STARTDT", "ADT", "CNSR", "EVNTDESC", "PARAMCD", "PARAM"} <= set(nodes)
    assert nodes["CNSR"].sources == ["TRTSDT", "DTHDT"]
    second = ns.param("TTD", "Time to Death", **_tte_frames(adsl))
    assert [n.name for n in second._lineage if n.verb == "param"] == list(nodes)
