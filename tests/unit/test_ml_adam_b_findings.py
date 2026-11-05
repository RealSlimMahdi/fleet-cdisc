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


# ------------------------------------------------------------------ #
# PK                                                                   #
# ------------------------------------------------------------------ #

PK_BLQ = """
┌──────────┬────────┬──────────┐
│ PCSTRESN ┆ PCLLOQ ┆ PCSTRESC │
│ ---      ┆ ---    ┆ ---      │
│ f64      ┆ f64    ┆ str      │
╞══════════╪════════╪══════════╡
│ 0.5      ┆ 1.0    ┆ 0.5      │
│ 4.0      ┆ 1.0    ┆ 4.0      │
│ 0.2      ┆ 1.0    ┆ 0.2      │
│ 1.0      ┆ 1.0    ┆ 1.0      │
└──────────┴────────┴──────────┘
"""


def test_c1_396_blq_impute_is_one_rule_for_every_row():
    """c1-396: BLQ before and after the first quantifiable value get LLOQ/2 alike."""
    out = (
        pl.from_repr(PK_BLQ)
        .adam.pk.blq_impute("AVAL", conc_col="PCSTRESN", lloq_col="PCLLOQ")
        .to_frame()
    )
    assert out["AVAL"].to_list() == [0.5, 4.0, 0.5, 1.0]
    from fleet.adam.pk_namespace import PKNamespace

    assert "whatever the sample position" in (PKNamespace.blq_impute.__doc__ or "")


def test_c1_402_pk_docstring_claims_no_adpp():
    from fleet.adam.pk_namespace import PKNamespace

    assert "ADPP " not in (PKNamespace.__doc__ or "")


def test_c1_401_nominal_time_minutes_is_the_exact_quotient():
    pc = pl.DataFrame({"PCTPTNUM": list(range(4321))})
    out = pc.adam.pk.nominal_time("NFRLT", from_col="PCTPTNUM", input_unit="min").to_frame()
    assert out["NFRLT"].to_list() == [x / 60 for x in range(4321)]


def test_c2_lead_1_predose_flag_include_zero():
    adpc = pl.from_repr("""
┌───────┐
│ NFRLT │
│ ---   │
│ f64   │
╞═══════╡
│ 0.0   │
│ -0.5  │
│ 1.0   │
│ -0.1  │
└───────┘
""")
    default = adpc.adam.pk.predose_flag("PREFL", time_col="NFRLT").to_frame()
    assert default["PREFL"].to_list() == [None, "Y", None, "Y"]
    nominal = adpc.adam.pk.predose_flag("PREFL", time_col="NFRLT", include_zero=True).to_frame()
    assert nominal["PREFL"].to_list() == ["Y", "Y", None, "Y"]


PK_EVID = """
┌──────┬──────┬────────┐
│ EVID ┆ DV   ┆ EXDOSE │
│ ---  ┆ ---  ┆ ---    │
│ i64  ┆ f64  ┆ f64    │
╞══════╪══════╪════════╡
│ 0    ┆ 5.0  ┆ null   │
│ 1    ┆ null ┆ 100.0  │
│ 2    ┆ null ┆ null   │
│ 3    ┆ null ┆ null   │
│ 4    ┆ null ┆ 100.0  │
│ null ┆ 3.0  ┆ null   │
└──────┴──────┴────────┘
"""


def test_c1_397_evid_4_is_a_dose_and_mdv_is_1_off_observations():
    out = (
        pl.from_repr(PK_EVID)
        .adam.pk.amt("AMT", dose_col="EXDOSE")
        .cmt("CMT")
        .mdv("MDV_E", conc_col=None, evid_col="EVID")
        .to_frame()
    )
    assert out["AMT"].to_list() == [None, 100.0, None, None, 100.0, None]
    assert out["CMT"].to_list() == [2, 1, None, None, 1, None]
    assert out["MDV_E"].to_list() == [0, 1, 1, 1, 1, 1]


def test_c1_398_mdv_defaults_read_evid_and_dv():
    out = pl.from_repr(PK_EVID).adam.pk.mdv("MDV").to_frame()
    assert out["MDV"].to_list() == [0, 1, 1, 1, 1, 1]


def test_c1_398_mdv_text_dv_dot_is_missing():
    pp = pl.from_repr("""
┌──────┬──────┐
│ EVID ┆ DV   │
│ ---  ┆ ---  │
│ i64  ┆ str  │
╞══════╪══════╡
│ 0    ┆ .    │
│ 0    ┆      │
│ 0    ┆ null │
│ 0    ┆ 2.5  │
└──────┴──────┘
""")
    out = pp.adam.pk.mdv("MDV").to_frame()
    assert out["MDV"].to_list() == [1, 1, 1, 0]


def test_c1_395_avalcat_digits():
    pc = pl.from_repr("""
┌──────────────┬────────┐
│ PCSTRESN     ┆ PCLLOQ │
│ ---          ┆ ---    │
│ f64          ┆ f64    │
╞══════════════╪════════╡
│ 10.27        ┆ 0.1    │
│ 5.0          ┆ 0.1    │
│ 12345678.0   ┆ 0.1    │
│ 0.05         ┆ 0.1    │
└──────────────┴────────┘
""")
    ns = pc.adam.pk
    kw = dict(conc_col="PCSTRESN", lloq_col="PCLLOQ", text_col=None)
    assert ns.avalcat("A", **kw).to_frame()["A"].to_list() == ["10.27", "5", "12345678", "BLQ"]
    # R: prettyNum(signif(c(10.27, 5, 12345678), 3)) gives "10.3", "5", "12300000".
    three = ns.avalcat("A", **kw, digits=3).to_frame()["A"].to_list()
    assert three == ["10.3", "5", "12300000", "BLQ"]


PK_EDGE = """
┌──────────┬────────┬──────────┐
│ PCSTRESN ┆ PCLLOQ ┆ PCSTRESC │
│ ---      ┆ ---    ┆ ---      │
│ f64      ┆ f64    ┆ str      │
╞══════════╪════════╪══════════╡
│ 1.0      ┆ 1.0    ┆ 1.0      │
│ 0.99     ┆ 1.0    ┆ 0.99     │
└──────────┴────────┴──────────┘
"""


def test_c1_404_value_equal_to_lloq_is_not_blq():
    kw = dict(conc_col="PCSTRESN", lloq_col="PCLLOQ")
    out = (
        pl.from_repr(PK_EDGE)
        .adam.pk.blq_flag("BLQFL", **kw)
        .blqfn("BLQFN", **kw)
        .blq_impute("AVAL", **kw)
        .avalcat("AVALCAT1", **kw)
        .to_frame()
    )
    assert out["BLQFL"].to_list() == [None, "Y"]
    assert out["BLQFN"].to_list() == [0, 1]
    assert out["AVAL"].to_list() == [1.0, 0.5]
    assert out["AVALCAT1"].to_list() == ["1", "BLQ"]


def test_c1_404_predose_window_bounds():
    adpc = pl.from_repr("""
┌───────┐
│ ATIME │
│ ---   │
│ f64   │
╞═══════╡
│ -1.0  │
│ -1.5  │
└───────┘
""")
    out = adpc.adam.pk.predose_flag("PREDFL", time_col="ATIME").to_frame()
    assert out["PREDFL"].to_list() == ["Y", None]
    wide = adpc.adam.pk.predose_flag("PREDFL", time_col="ATIME", window_hrs=1.5).to_frame()
    assert wide["PREDFL"].to_list() == ["Y", "Y"]


def test_c1_404_nominal_time_minutes_and_log2_exact():
    df = pl.from_repr("""
┌──────────┬──────┐
│ PCTPTNUM ┆ DV   │
│ ---      ┆ ---  │
│ f64      ┆ f64  │
╞══════════╪══════╡
│ 90.0     ┆ 8.0  │
└──────────┴──────┘
""")
    out = (
        df.adam.pk.nominal_time("NFRLT", from_col="PCTPTNUM", input_unit="min")
        .log_conc("DVL", conc_col="DV", base="2")
        .to_frame()
    )
    assert out["NFRLT"].to_list() == [1.5]
    assert out["DVL"].to_list() == [3.0]


# ------------------------------------------------------------------ #
# Onco                                                                 #
# ------------------------------------------------------------------ #

RS_TEXT_DATES = """
┌─────────┬───────┬──────────────────┐
│ USUBJID ┆ AVALC ┆ ADT              │
│ ---     ┆ ---   ┆ ---              │
│ str     ┆ str   ┆ str              │
╞═════════╪═══════╪══════════════════╡
│ A       ┆ PR    ┆ 2024-01-01T10:30 │
│ A       ┆ PR    ┆ 2024-03-01       │
│ A       ┆ PD    ┆ 2024-05-01       │
└─────────┴───────┴──────────────────┘
"""


def test_c1_413_filter_pd_text_date_with_time_raises():
    rs = pl.from_repr(RS_TEXT_DATES)
    with pytest.raises(
        DerivationError, match=r"filter_pd\(\): ADT must be a complete date.*'2024-01-01T10:30'"
    ):
        rs.adam.onco.filter_pd(response_col="AVALC", date_col="ADT")


def test_c1_413_confirmed_response_partial_date_raises():
    rs = pl.from_repr(RS_TEXT_DATES).with_columns(
        pl.when(pl.col("ADT").str.contains("T"))
        .then(pl.lit("2024-01"))
        .otherwise("ADT")
        .alias("ADT")
    )
    with pytest.raises(DerivationError, match=r"complete date.*'2024-01'"):
        rs.adam.onco.confirmed_response_flag("CRSPFL", source="AVALC", date_col="ADT")


def test_c1_413_complete_text_dates_still_work():
    rs = pl.from_repr(RS_TEXT_DATES).with_columns(pl.col("ADT").str.slice(0, 10))
    out = rs.adam.onco.filter_pd(response_col="AVALC", date_col="ADT").to_frame()
    assert out.height == 3


@pytest.mark.parametrize("verb", ["filter_pd", "confirmed_response_flag"])
def test_c1_413_wrong_column_names_the_verb(verb):
    rs = pl.from_repr(RS_TEXT_DATES)
    with pytest.raises(DerivationError, match=rf"{verb}\(\): column\(s\) \['AVALCX'\] not found"):
        if verb == "filter_pd":
            rs.adam.onco.filter_pd(response_col="AVALCX", date_col="ADT")
        else:
            rs.adam.onco.confirmed_response_flag("F", source="AVALCX", date_col="ADT")


def test_c1_413_null_dtype_response_gives_null_or_missing():
    rs = pl.DataFrame(
        {"USUBJID": ["A"], "RESP": [None], "ADT": [None]},
        schema={"USUBJID": pl.String, "RESP": pl.Null, "ADT": pl.Date},
    )
    out = (
        rs.adam.onco.aval_resp("AVAL", source="RESP")
        .best_overall_response(
            "BOR", source="RESP", date_col="ADT", reference_date="ADT", min_sd_days=0
        )
        .to_frame()
    )
    assert out["AVAL"].to_list() == [None]
    assert out["BOR"].to_list() == ["MISSING"]


ADRS_409 = """
┌─────────┬────────────┬──────────┐
│ USUBJID ┆ ADT        ┆ OVRLRESP │
│ ---     ┆ ---        ┆ ---      │
│ str     ┆ date       ┆ str      │
╞═════════╪════════════╪══════════╡
│ B14     ┆ 2020-03-01 ┆ null     │
│ B15     ┆ 2020-03-01 ┆ UNK      │
│ B16     ┆ 2020-03-01 ┆ PR       │
│ B16     ┆ 2020-04-01 ┆ null     │
└─────────┴────────────┴──────────┘
"""


def test_c1_409_bor_is_missing_without_a_known_response():
    out = (
        pl.from_repr(ADRS_409)
        .adam.onco.best_overall_response(
            "BOR", source="OVRLRESP", date_col="ADT", reference_date="ADT", min_sd_days=0
        )
        .to_frame()
    )
    assert out["BOR"].to_list() == ["MISSING", "MISSING", "PR", "PR"]


ADRS_410 = """
┌─────────┬────────────┬──────────┐
│ USUBJID ┆ ADT        ┆ OVRLRESP │
│ ---     ┆ ---        ┆ ---      │
│ str     ┆ date       ┆ str      │
╞═════════╪════════════╪══════════╡
│ S1      ┆ 2020-03-01 ┆ CR       │
│ S1      ┆ 2020-04-01 ┆ SD       │
│ S2      ┆ 2020-03-01 ┆ Partial  │
│ S2      ┆ 2020-04-01 ┆ PD       │
│ S3      ┆ 2020-03-01 ┆ pr       │
└─────────┴────────────┴──────────┘
"""


def test_c1_410_unknown_response_values_raise_in_three_verbs():
    adrs = pl.from_repr(ADRS_410).with_columns(
        pl.when(pl.col("OVRLRESP") == "CR")
        .then(pl.lit("CR "))
        .otherwise("OVRLRESP")
        .alias("OVRLRESP")
    )
    match = r"unknown response values \['CR ', 'Partial', 'pr'\]; known: CR, PR"
    with pytest.raises(DerivationError, match=r"best_overall_response\(\): " + match):
        adrs.adam.onco.best_overall_response(
            "BOR", source="OVRLRESP", date_col="ADT", reference_date="ADT", min_sd_days=0
        )
    with pytest.raises(DerivationError, match=r"confirmed_response_flag\(\): " + match):
        adrs.adam.onco.confirmed_response_flag("F", source="OVRLRESP", date_col="ADT")
    with pytest.raises(DerivationError, match=r"filter_pd\(\): " + match):
        adrs.adam.onco.filter_pd(response_col="OVRLRESP", date_col="ADT")


RS_VERTICAL = """
┌─────────┬──────────┬──────────┬────────────┐
│ USUBJID ┆ PARAMCD  ┆ AVALC    ┆ ADT        │
│ ---     ┆ ---      ┆ ---      ┆ ---        │
│ str     ┆ str      ┆ str      ┆ date       │
╞═════════╪══════════╪══════════╪════════════╡
│ S1      ┆ TRGRESP  ┆ CR       ┆ 2020-03-01 │
│ S1      ┆ OVRLRESP ┆ PR       ┆ 2020-03-01 │
│ S2      ┆ TRGRESP  ┆ PR       ┆ 2020-03-01 │
│ S2      ┆ OVRLRESP ┆ PD       ┆ 2020-03-01 │
└─────────┴──────────┴──────────┴────────────┘
"""


def test_c1_411_vertical_adrs_filtered_to_one_parameter():
    adrs = pl.from_repr(RS_VERTICAL)
    bor = (
        adrs.filter(pl.col("PARAMCD") == "OVRLRESP")
        .adam.onco.best_overall_response(
            "BOR", source="AVALC", date_col="ADT", reference_date="ADT", min_sd_days=0
        )
        .to_frame()
        .sort("USUBJID")
    )
    assert bor["BOR"].to_list() == ["PR", "PD"]
    from fleet.adam import onco_namespace

    assert 'source="OVRLRESP"' not in (onco_namespace.__doc__ or "")
