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
    ns = adsl.adam.tte.param(
        "OS", "Overall Survival", **_tte_frames(adsl), stop_at={"DTHDT": (2, "DEATH DATE")}
    )
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


# ------------------------------------------------------------------ #
# Neuro, metabolic, ophtha, vaccine, peds                              #
# ------------------------------------------------------------------ #

PET = """
┌──────┐
│ SUVR │
│ ---  │
│ f64  │
╞══════╡
│ 0.0  │
│ -1.0 │
│ 1.2  │
│ NaN  │
└──────┘
"""


def test_c1_717_centiloid_suvr_zero_or_below_is_null():
    out = (
        pl.from_repr(PET)
        .adam.neuro.centiloid("CL", suvr_col="SUVR", slope=183.07, intercept=-177.26)
        .to_frame()
    )
    assert out["CL"].to_list() == [None, None, 42.42, None]


def test_c1_717_centiloid_half_pair_raises():
    with pytest.raises(DerivationError, match="slope and intercept must be given together"):
        pl.from_repr(PET).adam.neuro.centiloid(
            "CL",
            suvr_col="SUVR",
            slope=200.0,
            tracer="18F-Florbetapir",
            pipeline="AVID FBP SUVR PIPELINE",
        )


def test_c1_714_panss_total_refuses_string_columns():
    qs = pl.from_repr("""
┌──────────┬──────────┬──────────┐
│ PANSSPOS ┆ PANSSNEG ┆ PANSSGEN │
│ ---      ┆ ---      ┆ ---      │
│ str      ┆ str      ┆ str      │
╞══════════╪══════════╪══════════╡
│ 14       ┆ 16       ┆ 30       │
└──────────┴──────────┴──────────┘
""")
    with pytest.raises(DerivationError, match="column 'PANSSPOS' is String; cast it"):
        qs.adam.neuro.panss_total(
            "PANSSTOT", positive_col="PANSSPOS", negative_col="PANSSNEG", general_col="PANSSGEN"
        )


CDR6 = """
┌────────┬─────────┬─────────┬─────────┬─────────┬─────────┐
│ CDRMEM ┆ CDRORNT ┆ CDRJDGM ┆ CDRCOMM ┆ CDRHOME ┆ CDRPERS │
│ ---    ┆ ---     ┆ ---     ┆ ---     ┆ ---     ┆ ---     │
│ f64    ┆ f64     ┆ f64     ┆ f64     ┆ f64     ┆ f64     │
╞════════╪═════════╪═════════╪═════════╪═════════╪═════════╡
│ 1.0    ┆ 1.0     ┆ 1.0     ┆ 1.0     ┆ 1.0     ┆ 1.0     │
└────────┴─────────┴─────────┴─────────┴─────────┴─────────┘
"""


@pytest.mark.parametrize("n", [5, 0])
def test_c1_715_cdrsob_needs_six_boxes(n):
    cols = ["CDRMEM", "CDRORNT", "CDRJDGM", "CDRCOMM", "CDRHOME", "CDRPERS"][:n]
    with pytest.raises(DerivationError, match=f"give the 6 CDR boxes, got {n}"):
        pl.from_repr(CDR6).adam.neuro.cdrsob_total("CDRSOB", domain_cols=cols)


def test_c1_715_cdrsob_six_boxes():
    cols = ["CDRMEM", "CDRORNT", "CDRJDGM", "CDRCOMM", "CDRHOME", "CDRPERS"]
    out = pl.from_repr(CDR6).adam.neuro.cdrsob_total("CDRSOB", domain_cols=cols).to_frame()
    assert out["CDRSOB"].to_list() == [6.0]


NAN_ROW = """
┌──────┬────────┬─────┐
│ AVAL ┆ WSTCIR ┆ SEX │
│ ---  ┆ ---    ┆ --- │
│ f64  ┆ f64    ┆ str │
╞══════╪════════╪═════╡
│ NaN  ┆ NaN    ┆ M   │
│ 28.0 ┆ 110.0  ┆ M   │
└──────┴────────┴─────┘
"""


def test_c1_713_nan_gives_no_category_or_flag():
    out = (
        pl.from_repr(NAN_ROW)
        .adam.neuro.mmse_category("MMSECG", score_col="AVAL")
        .moca_category("MOCACG", score_col="AVAL")
        .to_frame()
    )
    assert out["MMSECG"].to_list() == [None, "Normal"]
    assert out["MOCACG"].to_list() == [None, "Normal"]
    flag = (
        pl.from_repr(NAN_ROW)
        .adam.metabolic.visceral_fat_flag("ABDFL", waist_col="WSTCIR", sex_col="SEX")
        .to_frame()
    )
    assert flag["ABDFL"].to_list() == [None, "Y"]
    bcva = (
        pl.from_repr(NAN_ROW)
        .adam.ophtha.bcva_criterion("CRITFL", value_col="AVAL", threshold=24, direction="ge")
        .to_frame()
    )
    assert bcva["CRITFL"].to_list() == [None, "Y"]


@pytest.mark.parametrize("suffix", ["csv", "parquet"])
def test_c1_713_loader_reads_nan_as_null(tmp_path, suffix):
    path = tmp_path / f"x.{suffix}"
    frame = pl.DataFrame({"AVAL": [float("nan"), 1.0]})
    if suffix == "csv":
        path.write_text("AVAL\nNaN\n1.0\n", encoding="utf-8")
    else:
        frame.write_parquet(path)
    out = fleet.load_raw_data(path).collect()
    assert out["AVAL"].to_list() == [None, 1.0]


def test_c1_707_ta_verbs_round_ties_half_away_from_zero():
    advs = pl.from_repr("""
┌──────┬─────┬─────┬────────┬────────┬──────┐
│ BMI  ┆ AGE ┆ SEX ┆ WSTCIR ┆ HIPCIR ┆ SUVR │
│ ---  ┆ --- ┆ --- ┆ ---    ┆ ---    ┆ ---  │
│ f64  ┆ i64 ┆ str ┆ f64    ┆ f64    ┆ f64  │
╞══════╪═════╪═════╪════════╪════════╪══════╡
│ 15.0 ┆ 25  ┆ M   ┆ 52.0   ┆ 64.0   ┆ 1.25 │
│ 20.0 ┆ 40  ┆ F   ┆ 80.0   ┆ 100.0  ┆ 1.5  │
└──────┴─────┴─────┴────────┴────────┴──────┘
""")
    out = (
        advs.adam.metabolic.body_fat_pct("BFPCT", bmi_col="BMI", age_col="AGE", sex_col="SEX")
        .waist_hip_ratio("WHR", waist_col="WSTCIR", hip_col="HIPCIR")
        .to_frame()
    )
    assert out["BFPCT"].to_list() == [7.6, 27.8]
    assert out["WHR"].to_list() == [0.813, 0.8]
    cl = advs.adam.neuro.centiloid(
        "CL", suvr_col="SUVR", tracer="18F-Florbetaben", pipeline="AVID FBB SUVR PIPELINE"
    ).to_frame()
    assert cl["CL"].to_list() == [46.95, 85.96]


SC_718 = """
┌─────────┬──────────┬──────────┐
│ USUBJID ┆ SCTESTCD ┆ SCSTRESC │
│ ---     ┆ ---      ┆ ---      │
│ str     ┆ str      ┆ str      │
╞═════════╪══════════╪══════════╡
│ P01     ┆ FOCID    ┆ OS       │
│ P01     ┆ ACOHORT  ┆ COHORT 1 │
│ P02     ┆ FOCID    ┆ OD       │
│ P02     ┆ ACOHORT  ┆ COHORT 2 │
└─────────┴──────────┴──────────┘
"""


def test_c1_718_study_eye_on_focid_records_merges_one_row_per_subject():
    adsl = pl.from_repr("""
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ P01     │
│ P02     │
│ P03     │
└─────────┘
""")
    sc = pl.from_repr(SC_718)
    se = (
        sc.filter(pl.col("SCTESTCD") == "FOCID")
        .adam.ophtha.study_eye("STUDYEYE", source="SCSTRESC")
        .to_frame()
    )
    out = adsl.adam.merge(se, on="USUBJID", keep=["STUDYEYE"], validate="m:1").to_frame()
    assert out.sort("USUBJID")["STUDYEYE"].to_list() == ["LEFT", "RIGHT", None]
    from fleet.adam.ophtha_namespace import OphthaNamespace

    assert 'pl.col("SCTESTCD") == "FOCID"' in (OphthaNamespace.study_eye.__doc__ or "")


def test_c1_421_seroresponse_docstring_states_the_threshold_rule():
    from fleet.adam.vaccine_namespace import VaccineNamespace

    doc = VaccineNamespace.seroresponse_flag.__doc__ or ""
    assert "seroconversion_flag" in doc and "References:" in doc
    adis = pl.from_repr("""
┌─────────┬──────┬──────┐
│ USUBJID ┆ BASE ┆ AVAL │
│ ---     ┆ ---  ┆ ---  │
│ str     ┆ f64  ┆ f64  │
╞═════════╪══════╪══════╡
│ S01     ┆ 40.0 ┆ 40.0 │
└─────────┴──────┴──────┘
""")
    out = adis.adam.vaccine.seroresponse_flag("SRSFL", aval_col="AVAL", threshold=40.0)
    assert out.to_frame()["SRSFL"].to_list() == ["Y"]


def test_c1_415_ophtha_default_digits_and_bilateral_study_eye():
    df = pl.from_repr("""
┌───────┬──────────┬───────┬───────┐
│ ETDRS ┆ STUDYEYE ┆ AELOC ┆ AELAT │
│ ---   ┆ ---      ┆ ---   ┆ ---   │
│ f64   ┆ str      ┆ str   ┆ str   │
╞═══════╪══════════╪═══════╪═══════╡
│ 57.3  ┆ BILATERAL┆ EYE   ┆ LEFT  │
└───────┴──────────┴───────┴───────┘
""")
    out = (
        df.adam.ophtha.etdrs_to_logmar("LOGMAR", source="ETDRS")
        .affected_eye("AFEYE", loc_col="AELOC", lat_col="AELAT")
        .to_frame()
    )
    assert out["LOGMAR"].to_list() == [0.554]
    assert out["AFEYE"].to_list() == ["Study Eye"]


def test_c1_415_vaccine_cutoff_and_lloq_half_without_uloq():
    fa = pl.from_repr("""
┌─────────┬──────┬───────┐
│ USUBJID ┆ AVAL ┆ AVALC │
│ ---     ┆ ---  ┆ ---   │
│ str     ┆ f64  ┆ str   │
╞═════════╪══════╪═══════╡
│ S1      ┆ 2.5  ┆ NONE  │
│ S2      ┆ 2.6  ┆ NONE  │
└─────────┴──────┴───────┘
""")
    ev = fa.adam.vaccine.event_flag("EVENTFL", aval_col="AVAL", cutoff=2.5, by=["USUBJID"])
    assert ev.to_frame()["EVENTFL"].to_list() == ["N", "Y"]
    is_ = pl.from_repr("""
┌──────────┬────────┬─────────┐
│ ISSTRESN ┆ ISLLOQ ┆ ISORRES │
│ ---      ┆ ---    ┆ ---     │
│ f64      ┆ f64    ┆ str     │
╞══════════╪════════╪═════════╡
│ null     ┆ 4.0    ┆ <4      │
│ 10.0     ┆ 4.0    ┆ 10      │
└──────────┴────────┴─────────┘
""")
    out = is_.adam.vaccine.aval_adis("AVAL", uloq_col=None).to_frame()
    assert out["AVAL"].to_list() == [2.0, 10.0]


# ------------------------------------------------------------------ #
# Grading                                                              #
# ------------------------------------------------------------------ #


def test_c1_390_nan_gives_a_null_grade():
    lb = pl.from_repr("""
┌──────────────┬───────┬───────┬───────┬────────┬───────┐
│ T            ┆ AVAL  ┆ ANRLO ┆ ANRHI ┆ AVALU  ┆ BASE  │
│ ---          ┆ ---   ┆ ---   ┆ ---   ┆ ---    ┆ ---   │
│ str          ┆ f64   ┆ f64   ┆ f64   ┆ str    ┆ f64   │
╞══════════════╪═══════╪═══════╪═══════╪════════╪═══════╡
│ Hyperkalemia ┆ NaN   ┆ 3.5   ┆ 5.0   ┆ mmol/L ┆ 4.0   │
│ Hyperkalemia ┆ 5.2   ┆ 3.5   ┆ NaN   ┆ mmol/L ┆ 4.0   │
│ Hyperkalemia ┆ 6.5   ┆ 3.5   ┆ 5.0   ┆ mmol/L ┆ 4.0   │
└──────────────┴───────┴───────┴───────┴────────┴───────┘
""")
    hi = lb.adam.atoxgr("ATOXGRH", direction="H", term_var="T", unit_var="AVALU").to_frame()
    assert hi["ATOXGRH"].to_list() == [None, None, "3"]
    assert hi["AVAL"].is_nan().to_list() == [True, False, False]
    lo = lb.with_columns(pl.lit("Hypokalemia").alias("T"))
    out = lo.adam.atoxgr("ATOXGRL", direction="L", term_var="T", unit_var="AVALU").to_frame()
    assert out["ATOXGRL"][0] is None


def _hyperkalemia_file(tmp_path, **changes):
    import json
    from pathlib import Path

    from fleet.adam.grading import _registry

    raw = json.loads(
        (Path(_registry.__file__).parent / "criteria" / "ctcae_v5.json").read_text("utf-8")
    )
    entry = next(
        e for e in raw["criteria"] if e["term"] == "Hyperkalemia" and e["direction"] == "H"
    )
    entry.update(changes)
    raw["criteria"] = [entry]
    path = tmp_path / "my_criteria.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path, raw


LB_K = """
┌──────────────┬───────┬───────┬───────┬────────┐
│ T            ┆ AVAL  ┆ ANRLO ┆ ANRHI ┆ AVALU  │
│ ---          ┆ ---   ┆ ---   ┆ ---   ┆ ---    │
│ str          ┆ f64   ┆ f64   ┆ f64   ┆ str    │
╞══════════════╪═══════╪═══════╪═══════╪════════╡
│ Hyperkalemia ┆ 6.5   ┆ 3.5   ┆ 5.0   ┆ mmol/L │
└──────────────┴───────┴───────┴───────┴────────┘
"""


def test_c1_700_mistyped_key_raises(tmp_path):
    from pydantic import ValidationError

    path, _ = _hyperkalemia_file(tmp_path, filtr=None)
    with pytest.raises(ValidationError, match="filtr"):
        pl.from_repr(LB_K).adam.atoxgr(
            "ATOXGRH", system=str(path), direction="H", term_var="T", unit_var="AVALU"
        )


def test_c1_700_bad_json_names_the_file(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{ nope", encoding="utf-8")
    with pytest.raises(ValueError, match=r"bad.json: not valid JSON \(line 1, column 3\)"):
        pl.from_repr(LB_K).adam.atoxgr(
            "ATOXGRH", system=str(path), direction="H", term_var="T", unit_var="AVALU"
        )


def test_c1_701_an_edited_criteria_file_is_read_again(tmp_path):
    import json

    path, raw = _hyperkalemia_file(tmp_path)
    kw = dict(system=str(path), direction="H", term_var="T", unit_var="AVALU")
    first = pl.from_repr(LB_K).adam.atoxgr("G", **kw).to_frame()["G"][0]
    raw["criteria"][0]["arms"] = [{"when": True, "then": "1"}]
    path.write_text(json.dumps(raw), encoding="utf-8")
    second = pl.from_repr(LB_K).adam.atoxgr("G", **kw).to_frame()["G"][0]
    assert (first, second) == ("3", "1")


# ------------------------------------------------------------------ #
# BDS formulas, ADSL age, dates, study day, docs                       #
# ------------------------------------------------------------------ #


def test_c1_80_pchg_follows_adamig_sign_on_a_negative_baseline():
    admb = pl.from_repr("""
┌──────┬───────┐
│ AVAL ┆ BASE  │
│ ---  ┆ ---   │
│ f64  ┆ f64   │
╞══════╪═══════╡
│ -2.0 ┆ -2.5  │
│ -5.0 ┆ -10.0 │
└──────┴───────┘
""")
    out = admb.adam.pchg("PCHG").to_frame()
    assert out["PCHG"].to_list() == [-20.0, -50.0]
    from fleet.adam.namespace import AdamNamespace

    assert "abs(BASE)" in (AdamNamespace.pchg.__doc__ or "")


def test_c1_82_bsa_accepts_admiral_dubois_dubois():
    advs = pl.from_repr("""
┌───────┬──────┐
│ H     ┆ W    │
│ ---   ┆ ---  │
│ f64   ┆ f64  │
╞═══════╪══════╡
│ 170.0 ┆ 70.0 │
└───────┴──────┘
""")
    a = advs.adam.bsa("BSA", height="H", weight="W", method="DuBois").to_frame()
    b = advs.adam.bsa("BSA", height="H", weight="W", method="DuBois-DuBois").to_frame()
    assert a["BSA"].to_list() == b["BSA"].to_list()
    assert round(b["BSA"][0], 6) == 1.809708


def test_c1_83_age_years_weeks_hours_and_unknown_unit_warns():
    dm = pl.from_repr("""
┌───────┬───────┐
│ AGE   ┆ AGEU  │
│ ---   ┆ ---   │
│ f64   ┆ str   │
╞═══════╪═══════╡
│ 587.0 ┆ WEEKS │
│ 24.0  ┆ HOURS │
│ 5.0   ┆ YEAR  │
└───────┴───────┘
""")
    with pytest.warns(UserWarning, match=r"1 row\(s\) have an AGEU.*\['YEAR'\]"):
        out = dm.adam.adsl.age_years("AAGE", age_col="AGE", age_unit_col="AGEU").to_frame()
    assert out["AAGE"].to_list() == [587 * 7 / 365.25, 24 / 8766, None]
    rounded = dm.head(1).adam.adsl.age_years("AAGE", round_digits=1).to_frame()["AAGE"].to_list()
    assert rounded == [11.2]


def test_c1_85_pchg_base_zero_is_null():
    df = pl.from_repr("""
┌──────┬──────┐
│ AVAL ┆ BASE │
│ ---  ┆ ---  │
│ f64  ┆ f64  │
╞══════╪══════╡
│ 5.0  ┆ 0.0  │
│ 6.0  ┆ 4.0  │
└──────┴──────┘
""")
    assert df.adam.pchg("PCHG").to_frame()["PCHG"].to_list() == [None, 50.0]


@pytest.mark.parametrize(("stat", "expected"), [("min", 1.0), ("median", 2.0)])
def test_c1_85_summary_records_min_and_median(stat, expected):
    df = pl.from_repr("""
┌─────────┬─────────┬──────┐
│ USUBJID ┆ PARAMCD ┆ AVAL │
│ ---     ┆ ---     ┆ ---  │
│ str     ┆ str     ┆ f64  │
╞═════════╪═════════╪══════╡
│ 01      ┆ SYSBP   ┆ 1.0  │
│ 01      ┆ SYSBP   ┆ 2.0  │
│ 01      ┆ SYSBP   ┆ 9.0  │
└─────────┴─────────┴──────┘
""")
    out = df.adam.derive_summary_records(
        by=["USUBJID", "PARAMCD"], set_values_to={"DTYPE": "AVERAGE"}, stat=stat
    ).to_frame()
    assert out.filter(pl.col("DTYPE") == "AVERAGE")["AVAL"].to_list() == [expected]


def test_c1_85_derive_param_gives_no_row_without_a_source_parameter():
    df = pl.from_repr("""
┌─────────┬─────────┬───────┐
│ USUBJID ┆ PARAMCD ┆ AVAL  │
│ ---     ┆ ---     ┆ ---   │
│ str     ┆ str     ┆ f64   │
╞═════════╪═════════╪═══════╡
│ 01      ┆ WEIGHT  ┆ 70.0  │
│ 01      ┆ HEIGHT  ┆ 170.0 │
│ 02      ┆ WEIGHT  ┆ 80.0  │
└─────────┴─────────┴───────┘
""")
    out = df.adam.derive_param(
        by=["USUBJID"],
        set_values_to={"PARAMCD": "BMI"},
        parameter_filter={"WEIGHT": "WEIGHT", "HEIGHT": "HEIGHT"},
        analysis_value=pl.col("WEIGHT") / (pl.col("HEIGHT") / 100) ** 2,
    ).to_frame()
    assert out.filter(pl.col("PARAMCD") == "BMI")["USUBJID"].to_list() == ["01"]


def test_c1_87_cdisc_day_has_no_day_zero():
    from fleet.core.dtc import cdisc_day

    df = pl.DataFrame({"d": [-2, -1, 0, 1]})
    assert df.select(cdisc_day(pl.col("d")))["d"].to_list() == [-2, -1, 1, 2]
    import importlib.util

    from fleet.adam import utils

    assert importlib.util.find_spec("fleet.core.seq") is None
    assert not hasattr(utils, "study_day")


@pytest.mark.parametrize(
    ("target", "value"),
    [("RFSTDT", "15JAN2024"), ("ADT", "2024-02-30"), ("ADTM", "2024-01-15 08:30")],
)
def test_c1_71_date_literal_that_is_not_iso_raises(target, value):
    df = pl.DataFrame({"USUBJID": ["01"]})
    with pytest.raises(DerivationError, match=rf"date\('{target}'\): value '{value}' is not ISO"):
        df.adam.date(target, value=value)


def test_c1_71_date_literal_with_time():
    df = pl.DataFrame({"USUBJID": ["01"]})
    out = (
        df.adam.date("ADTM", value="2024-01-15T08:30")
        .date("ADT", value="2024-01-15T08:30:00")
        .to_frame()
    )
    assert str(out["ADTM"][0]) == "2024-01-15 08:30:00"
    assert str(out["ADT"][0]) == "2024-01-15"


def test_c1_71_sdtm_dtc_literal_must_be_iso_but_may_be_partial():
    df = pl.DataFrame({"USUBJID": ["01"]})
    with pytest.raises(DerivationError, match="not an ISO 8601 --DTC value"):
        df.sdtm.date("RFSTDTC", value="15JAN2024")
    assert df.sdtm.date("RFSTDTC", value="2024-01").to_frame()["RFSTDTC"].to_list() == ["2024-01"]


def test_c1_73_hhmm_time_gives_tmf_s():
    ae = pl.from_repr("""
┌──────────────────┐
│ AESTDTC          │
│ ---              │
│ str              │
╞══════════════════╡
│ 2021-03-15T10:30 │
└──────────────────┘
""")
    out = ae.adam.date("ASTDTM", source="AESTDTC").to_frame()
    assert str(out["ASTDTM"][0]) == "2021-03-15 10:30:00"
    assert out["ASTTMF"].to_list() == ["S"]
    from fleet.adam._mixins import SharedADaMVerbsMixin

    assert "ignore_seconds_flag" in (SharedADaMVerbsMixin.date.__doc__ or "")


def test_c1_721_transform_algorithm_has_a_rename_hint():
    from fleet.tools.migrate_spec import ALGORITHM_RENAMES

    assert ALGORITHM_RENAMES["transform"] == "derivation"
    from fleet.adam import transforms

    assert "algorithm: transform" not in (transforms.__doc__ or "")


def test_c1_414_third_party_notice_ships_in_the_package():
    from importlib.resources import files

    text = (files("fleet") / "THIRD_PARTY_NOTICES").read_text(encoding="utf-8")
    assert "admiralophtha" in text and "Apache License" in text
    from fleet.adam import ophtha_namespace

    assert "ported from" not in (ophtha_namespace.__doc__ or "")
