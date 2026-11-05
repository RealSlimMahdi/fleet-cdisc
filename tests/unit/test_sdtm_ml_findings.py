"""Regression tests for the medium and low SDTM audit findings (package ml-sdtm)."""

from __future__ import annotations

import warnings

import polars as pl
import pytest

import fleet  # noqa: F401
from fleet.core.exceptions import DerivationError
from fleet.sdtm.utils import parse_expression

# ── c1-109 condition_add keeps the current value ──────────────────────── #


def test_c1_109_chained_condition_add_keeps_each_value() -> None:
    ae = pl.from_repr("""
┌──────┐
│ sev  │
│ ---  │
│ i64  │
╞══════╡
│ 1    │
│ 2    │
│ 3    │
│ null │
└──────┘
""")
    out = (
        ae.sdtm.condition_add("AESEV", condition=pl.col("sev") == 1, then_value="MILD")
        .condition_add("AESEV", condition=pl.col("sev") == 2, then_value="MODERATE")
        .condition_add("AESEV", condition=pl.col("sev") == 3, then_value="SEVERE")
        .to_frame()
    )
    assert out["AESEV"].to_list() == ["MILD", "MODERATE", "SEVERE", None]


def test_c1_109_condition_add_over_an_existing_column() -> None:
    ae = pl.from_repr("""
┌───────────────┬───────┐
│ AEOUT         ┆ death │
│ ---           ┆ ---   │
│ str           ┆ str   │
╞═══════════════╪═══════╡
│ RECOVERED     ┆ N     │
│ X             ┆ Y     │
│ NOT RECOVERED ┆ N     │
└───────────────┴───────┘
""")
    out = ae.sdtm.condition_add(
        "AEOUT", condition=pl.col("death") == "Y", then_value="FATAL"
    ).to_frame()
    assert out["AEOUT"].to_list() == ["RECOVERED", "FATAL", "NOT RECOVERED"]


# ── c1-108 c1-114 ae_aerel ─────────────────────────────────────────────── #


def test_c1_108_mixed_case_map_keys_match() -> None:
    ae = pl.from_repr("""
┌─────┐
│ r   │
│ --- │
│ str │
╞═════╡
│ yes │
│ YES │
│ no  │
│ No  │
└─────┘
""")
    out = ae.sdtm.ae_aerel(source="r", aerel_map={"Yes": "RELATED", "NO": "NOT RELATED"}).to_frame()
    assert out["AEREL"].to_list() == ["RELATED", "RELATED", "NOT RELATED", "NOT RELATED"]


def test_c1_108_an_empty_map_maps_nothing() -> None:
    ae = pl.from_repr("""
┌─────┐
│ r   │
│ --- │
│ str │
╞═════╡
│ yes │
└─────┘
""")
    with pytest.warns(UserWarning, match="no mapping"):
        out = ae.sdtm.ae_aerel(source="r", aerel_map={}).to_frame()
    assert out["AEREL"].to_list() == ["YES"]


def test_c1_114_unmapped_values_are_trimmed_and_warned() -> None:
    raw = pl.from_repr("""
┌──────────────────┐
│ ae_relationship  │
│ ---              │
│ str              │
╞══════════════════╡
│ possible         │
│  Maybe           │
│ possibly related │
│ yes              │
└──────────────────┘
""")
    raw = raw.with_columns(pl.col("ae_relationship").replace("Maybe", " Maybe "))
    with pytest.warns(UserWarning, match=r"2 value\(s\) have no mapping: \['Maybe', 'possible'\]"):
        out = raw.sdtm.ae_aerel("AEREL", source="ae_relationship").to_frame()
    assert out["AEREL"].to_list() == ["POSSIBLE", "MAYBE", "POSSIBLY RELATED", "RELATED"]


# ── c1-112 multiple_responses skips empty tokens ───────────────────────── #


def test_c1_112_empty_tokens_give_no_blank_record() -> None:
    raw = pl.DataFrame({"r": ["x||y", "x|", "|", "", "x| |y", None]})
    out = raw.sdtm.multiple_responses("T", source="r").to_frame()
    assert out["T"].to_list() == ["x", "y", "x", None, None, "x", "y", None]


# ── c1-110 c1-113 export_supp checks ───────────────────────────────────── #


@pytest.fixture
def dm_one() -> pl.DataFrame:
    return pl.from_repr("""
┌─────────┬────────┬─────────┬─────┐
│ STUDYID ┆ DOMAIN ┆ USUBJID ┆ c   │
│ ---     ┆ ---    ┆ ---     ┆ --- │
│ str     ┆ str    ┆ str     ┆ str │
╞═════════╪════════╪═════════╪═════╡
│ S       ┆ DM     ┆ 1       ┆ v   │
└─────────┴────────┴─────────┴─────┘
""")


@pytest.mark.parametrize("qnam", ["TOOLONGNAME", "low_name", "1BAD"])
def test_c1_110_a_bad_qnam_raises(dm_one: pl.DataFrame, qnam: str) -> None:
    with pytest.raises(DerivationError, match="QNAM"):
        dm_one.sdtm.nsv(qnam, source="c", label="L").export_supp()


@pytest.mark.parametrize("label", ["", "L" * 41])
def test_c1_110_a_bad_qlabel_raises(dm_one: pl.DataFrame, label: str) -> None:
    with pytest.raises(DerivationError, match="QLABEL"):
        dm_one.sdtm.nsv("SAFETY", source="c", label=label).export_supp()


def test_c1_110_a_long_qval_warns(dm_one: pl.DataFrame) -> None:
    dm = dm_one.with_columns(pl.lit("v" * 250).alias("c"))
    with pytest.warns(UserWarning, match="over 200 characters"):
        supp = dm.sdtm.nsv("COMMENT", source="c", label="Comment").export_supp()
    assert supp.height == 1


def test_c1_113_two_domains_raise() -> None:
    ae = pl.from_repr("""
┌─────────┬─────────┬────────┬─────┬─────┐
│ STUDYID ┆ USUBJID ┆ DOMAIN ┆ SEQ ┆ X   │
│ ---     ┆ ---     ┆ ---    ┆ --- ┆ --- │
│ str     ┆ str     ┆ str    ┆ i64 ┆ str │
╞═════════╪═════════╪════════╪═════╪═════╡
│ S       ┆ 1       ┆ AE     ┆ 1   ┆ a   │
│ S       ┆ 2       ┆ CE     ┆ 2   ┆ b   │
└─────────┴─────────┴────────┴─────┴─────┘
""")
    with pytest.raises(DerivationError, match="DOMAIN holds AE and CE"):
        ae.sdtm.export_supp(qualifiers={"X": {"label": "x"}}, idvar="SEQ")
    supp = ae.sdtm.export_supp(qualifiers={"X": {"label": "x"}}, idvar="SEQ", domain="AE")
    assert supp["RDOMAIN"].to_list() == ["AE", "AE"]


def test_c1_113_a_null_first_domain_takes_the_other_value() -> None:
    ae = pl.from_repr("""
┌─────────┬─────────┬────────┬─────┬─────┐
│ STUDYID ┆ USUBJID ┆ DOMAIN ┆ SEQ ┆ X   │
│ ---     ┆ ---     ┆ ---    ┆ --- ┆ --- │
│ str     ┆ str     ┆ str    ┆ i64 ┆ str │
╞═════════╪═════════╪════════╪═════╪═════╡
│ S       ┆ 1       ┆ null   ┆ 1   ┆ a   │
│ S       ┆ 2       ┆ AE     ┆ 2   ┆ b   │
└─────────┴─────────┴────────┴─────┴─────┘
""")
    supp = ae.sdtm.export_supp(qualifiers={"X": {"label": "x"}}, idvar="SEQ")
    assert supp["RDOMAIN"].to_list() == ["AE", "AE"]


def test_c1_113_no_studyid_or_usubjid_raises() -> None:
    raw = pl.from_repr("""
┌─────┐
│ X   │
│ --- │
│ str │
╞═════╡
│ a   │
└─────┘
""")
    with pytest.raises(DerivationError, match="no STUDYID and no USUBJID"):
        raw.sdtm.export_supp(qualifiers={"X": {"label": "x"}}, domain="DM")


# ── c1-96 c2-956 automatic FK rules ────────────────────────────────────── #


def test_c1_96_epoch_is_checked_against_ta() -> None:
    raw = pl.DataFrame({"ep": ["NOT-AN-EPOCH"]})
    ta = pl.DataFrame({"ARMCD": ["A"], "EPOCH": ["TREATMENT"]})
    with pytest.raises(DerivationError, match=r"not found in pinned TA\.EPOCH"):
        raw.sdtm.pin("TA", ta, join_on="ARMCD").fk_policy("error").assign(
            "EPOCH", source="ep"
        ).to_frame()


def test_c2_956_unplan_and_unscheduled_visits_are_not_errors() -> None:
    raw = pl.from_repr("""
┌────────┬─────┐
│ etcd   ┆ vn  │
│ ---    ┆ --- │
│ str    ┆ f64 │
╞════════╪═════╡
│ UNPLAN ┆ 1.1 │
└────────┴─────┘
""")
    te = pl.DataFrame({"ETCD": ["SCRN"]})
    tv = pl.DataFrame({"VISITNUM": [1.0]})
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = (
            raw.sdtm.pin("TE", te, join_on="ETCD").fk_policy("error").assign("ETCD", source="etcd")
        )
        assert out.to_frame()["ETCD"].to_list() == ["UNPLAN"]
    with pytest.warns(UserWarning, match="TV holds planned visits only"):
        raw.sdtm.pin("TV", tv, join_on="VISITNUM").fk_policy("error").assign(
            "VISITNUM", source="vn"
        ).to_frame()


# ── c1-107 baseline_flag needs ref_col and testcd_col ──────────────────── #


def test_c1_107_ref_col_and_testcd_col_are_required() -> None:
    vs = pl.from_repr("""
┌─────────┬──────────┬────────────┬─────────┬────────────┬────────────┐
│ USUBJID ┆ VSTESTCD ┆ VSDTC      ┆ VSORRES ┆ RFSTDTC    ┆ RFXSTDTC   │
│ ---     ┆ ---      ┆ ---        ┆ ---     ┆ ---        ┆ ---        │
│ str     ┆ str      ┆ str        ┆ str     ┆ str        ┆ str        │
╞═════════╪══════════╪════════════╪═════════╪════════════╪════════════╡
│ S1      ┆ SYSBP    ┆ 2013-12-28 ┆ 1       ┆ 2014-01-01 ┆ 2014-01-10 │
│ S1      ┆ SYSBP    ┆ 2014-01-05 ┆ 2       ┆ 2014-01-01 ┆ 2014-01-10 │
│ S1      ┆ WEIGHT   ┆ 2014-01-03 ┆ 3       ┆ 2014-01-01 ┆ 2014-01-10 │
└─────────┴──────────┴────────────┴─────────┴────────────┴────────────┘
""")
    with pytest.raises(TypeError, match="ref_col"):
        vs.sdtm.baseline_flag("VSLOBXFL", date_col="VSDTC", testcd_col="VSTESTCD")  # type: ignore[call-arg]
    with pytest.raises(TypeError, match="testcd_col"):
        vs.sdtm.baseline_flag("VSLOBXFL", date_col="VSDTC", ref_col="RFXSTDTC")  # type: ignore[call-arg]
    out = vs.sdtm.baseline_flag(
        "VSLOBXFL", date_col="VSDTC", testcd_col="VSTESTCD", ref_col="RFXSTDTC"
    ).to_frame()
    assert out["VSLOBXFL"].to_list() == [None, "Y", "Y"]


# ── c1-92 parse_expression names the parenthesised form ────────────────── #


@pytest.mark.parametrize("text", ["AGE > 20 and AGE < 75", "AGE > 20 & AGE < 75", "20 < AGE < 75"])
def test_c1_92_boolean_without_parentheses_names_the_fix(text: str) -> None:
    with pytest.raises(DerivationError, match=r"write \(AGE > 20\) & \(AGE < 75\)"):
        parse_expression(text)


# ── c1-231 docstring convention ────────────────────────────────────────── #


def test_c1_231_no_bare_example_section_in_the_source() -> None:
    from pathlib import Path

    src = Path(fleet.__file__).parent
    bare = [str(f.relative_to(src)) for f in src.rglob("*.py") if "Example::" in f.read_text()]
    assert bare == []
