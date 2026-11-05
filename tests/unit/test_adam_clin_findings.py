"""Regression tests for the adam-clin audit findings (c1-76, c1-77, c1-84, c1-137,
c1-138, c1-329, c1-386, c1-420)."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration
from fleet.core.exceptions import DerivationError, VerbUsageError

# ── c1-76: full precision by default, SAS ROUND on request ────────────────────


def test_bmi_keeps_full_precision_and_rounds_as_sas_on_request():
    advs = pl.from_repr("""\
┌─────────┬────────┬────────┐
│ USUBJID ┆ WEIGHT ┆ HEIGHT │
│ ---     ┆ ---    ┆ ---    │
│ str     ┆ f64    ┆ f64    │
╞═════════╪════════╪════════╡
│ 01      ┆ 86.6   ┆ 170.0  │
│ 02      ┆ 97.0   ┆ 200.0  │
└─────────┴────────┴────────┘
""")
    full = advs.adam.bmi("BMI", weight="WEIGHT", height="HEIGHT").to_frame()
    one = advs.adam.bmi("BMI", weight="WEIGHT", height="HEIGHT", round_digits=1).to_frame()

    assert full["BMI"].to_list() == pytest.approx([86.6 / 1.7**2, 24.25], abs=1e-12)
    assert full["BMI"][0] < 30
    # SAS ROUND(24.25, 0.1) = 24.3; half-to-even would give 24.2.
    assert one["BMI"].to_list() == [30.0, 24.3]


def test_map_bsa_qtc_and_age_years_keep_full_precision():
    df = pl.from_repr("""\
┌───────┬───────┬────────┬────────┬───────┬───────┬─────┬────────┐
│ SYSBP ┆ DIABP ┆ WEIGHT ┆ HEIGHT ┆ QT    ┆ RR    ┆ AGE ┆ AGEU   │
│ ---   ┆ ---   ┆ ---    ┆ ---    ┆ ---   ┆ ---   ┆ --- ┆ ---    │
│ f64   ┆ f64   ┆ f64    ┆ f64    ┆ f64   ┆ f64   ┆ f64 ┆ str    │
╞═══════╪═══════╪════════╪════════╪═══════╪═══════╪═════╪════════╡
│ 120.0 ┆ 80.0  ┆ 70.0   ┆ 170.0  ┆ 400.0 ┆ 800.0 ┆ 7.0 ┆ MONTHS │
└───────┴───────┴────────┴────────┴───────┴───────┴─────┴────────┘
""")
    out = (
        df.adam.map("MAP")
        .bsa("BSA", weight="WEIGHT", height="HEIGHT")
        .qtc("QTCF", qt="QT", rr="RR")
        .to_frame()
    )
    aage = df.adam.adsl.age_years("AAGE", age_col="AGE", age_unit_col="AGEU").to_frame()

    assert out["MAP"][0] == pytest.approx(80 + 40 / 3, abs=1e-12)
    assert out["BSA"][0] == pytest.approx((170 * 70 / 3600) ** 0.5, abs=1e-12)
    assert out["QTCF"][0] == pytest.approx(430.88693800637674, abs=1e-12)
    assert aage["AAGE"][0] == pytest.approx(7 / 12, abs=1e-12)


def test_round_digits_on_map_follows_sas_round():
    df = pl.from_repr("""\
┌───────┬───────┐
│ SYSBP ┆ DIABP │
│ ---   ┆ ---   │
│ f64   ┆ f64   │
╞═══════╪═══════╡
│ 120.0 ┆ 80.0  │
│ 81.5  ┆ 80.0  │
└───────┴───────┘
""")
    out = df.adam.map("MAP", round_digits=1).to_frame()
    # 93.333 -> 93.3; 80.5 -> 80.5 (exact), check the half case below.
    assert out["MAP"].to_list() == [93.3, 80.5]
    half = df.adam.map("MAP", round_digits=0).to_frame()
    assert half["MAP"].to_list() == [93.0, 81.0]


# ── c1-138: age from dates is completed years ────────────────────────────────


def test_age_from_dates_gives_completed_years():
    adsl = pl.from_repr("""\
┌─────────┬────────────┬────────────┐
│ USUBJID ┆ BRTHDT     ┆ TRTSDT     │
│ ---     ┆ ---        ┆ ---        │
│ str     ┆ date       ┆ date       │
╞═════════╪════════════╪════════════╡
│ 01-001  ┆ 2003-03-15 ┆ 2021-03-14 │
│ 01-002  ┆ 1956-01-02 ┆ 2021-01-01 │
│ 01-003  ┆ 1996-02-29 ┆ 2020-02-28 │
│ 01-004  ┆ 1956-06-01 ┆ 2021-05-31 │
│ 01-005  ┆ 2000-03-15 ┆ 2021-03-15 │
│ 01-006  ┆ 2021-03-01 ┆ 2022-03-01 │
│ 01-007  ┆ 1952-02-29 ┆ 2023-02-28 │
│ 01-008  ┆ 1952-02-29 ┆ 2023-03-01 │
│ 01-009  ┆ 2000-03-15 ┆ 2000-03-14 │
│ 01-010  ┆ null       ┆ 2021-01-01 │
└─────────┴────────────┴────────────┘
""")
    out = adsl.adam.adsl.age_from_dates("AAGE").to_frame()

    assert out["AAGE"].dtype == pl.Int64
    assert out["AAGE"].to_list() == [17, 64, 23, 64, 21, 1, 70, 71, -1, None]


def test_age_from_dates_decimal_is_unrounded_and_rounds_on_request():
    adsl = pl.from_repr("""\
┌────────────┬────────────┐
│ BRTHDT     ┆ TRTSDT     │
│ ---        ┆ ---        │
│ date       ┆ date       │
╞════════════╪════════════╡
│ 1956-06-01 ┆ 2021-05-31 │
└────────────┴────────────┘
""")
    full = adsl.adam.adsl.age_from_dates("AAGE", unit="decimal").to_frame()
    two = adsl.adam.adsl.age_from_dates("AAGE", unit="decimal", round_digits=2).to_frame()

    assert full["AAGE"][0] == pytest.approx(23740 / 365.25, abs=1e-12)
    assert two["AAGE"][0] == 65.0
    with pytest.raises(VerbUsageError, match="round_digits"):
        adsl.adam.adsl.age_from_dates("AAGE", round_digits=1)


# ── c1-77, c1-84: nrind at 15 significant digits, NaN and zero divisors ──────


def test_nrind_compares_at_15_significant_digits_and_nulls_nan():
    adlb = pl.from_repr("""\
┌─────────┬─────────────────────┬───────┬────────┐
│ USUBJID ┆ AVAL                ┆ ANRLO ┆ ANRHI  │
│ ---     ┆ ---                 ┆ ---   ┆ ---    │
│ str     ┆ f64                 ┆ f64   ┆ f64    │
╞═════════╪═════════════════════╪═══════╪════════╡
│ 01      ┆ 114.92000000000002  ┆ 10.0  ┆ 114.92 │
│ 02      ┆ 0.30000000000000004 ┆ 0.1   ┆ 0.3    │
│ 03      ┆ 0.7999999999999999  ┆ 0.8   ┆ 1.0    │
│ 04      ┆ NaN                 ┆ 0.1   ┆ 0.3    │
│ 05      ┆ 0.30001             ┆ 0.1   ┆ 0.3    │
└─────────┴─────────────────────┴───────┴────────┘
""")
    out = adlb.adam.nrind("ANRIND", value="AVAL", low="ANRLO", high="ANRHI").to_frame()

    assert out["ANRIND"].to_list() == ["NORMAL", "NORMAL", "NORMAL", None, "HIGH"]


def test_bmi_height_zero_gives_null_and_nrind_null():
    advs = pl.from_repr("""\
┌─────────┬────────┬────────┬───────┬───────┐
│ USUBJID ┆ WEIGHT ┆ HEIGHT ┆ BMILO ┆ BMIHI │
│ ---     ┆ ---    ┆ ---    ┆ ---   ┆ ---   │
│ str     ┆ f64    ┆ f64    ┆ f64   ┆ f64   │
╞═════════╪════════╪════════╪═══════╪═══════╡
│ 01      ┆ 70.0   ┆ 0.0    ┆ 18.5  ┆ 25.0  │
│ 02      ┆ 0.0    ┆ 0.0    ┆ 18.5  ┆ 25.0  │
└─────────┴────────┴────────┴───────┴───────┘
""")
    out = (
        advs.adam.bmi("BMI", weight="WEIGHT", height="HEIGHT")
        .nrind("BMIIND", value="BMI", low="BMILO", high="BMIHI")
        .to_frame()
    )
    assert out["BMI"].to_list() == [None, None]
    assert out["BMIIND"].to_list() == [None, None]


def test_derive_param_nulls_a_non_finite_aval_with_a_warning():
    advs = pl.from_repr("""\
┌─────────┬─────────┬──────┐
│ USUBJID ┆ PARAMCD ┆ AVAL │
│ ---     ┆ ---     ┆ ---  │
│ str     ┆ str     ┆ f64  │
╞═════════╪═════════╪══════╡
│ 01      ┆ X       ┆ 4.0  │
│ 01      ┆ Y       ┆ 0.0  │
│ 02      ┆ X       ┆ 4.0  │
│ 02      ┆ Y       ┆ 2.0  │
└─────────┴─────────┴──────┘
""")
    with pytest.warns(UserWarning, match="1 new AVAL"):
        out = advs.adam.derive_param(
            by=["USUBJID"],
            set_values_to={"PARAMCD": "RATIO"},
            parameter_filter={"X": "X", "Y": "Y"},
            analysis_value='pl.col("X") / pl.col("Y")',
            keep_nas=True,
        ).to_frame()
    ratio = out.filter(pl.col("PARAMCD") == "RATIO").sort("USUBJID")
    assert ratio["AVAL"].to_list() == [None, 2.0]


# ── c1-137: counts are signed, chg/pchg are Float64 ──────────────────────────


def test_count_events_is_int64_and_subtraction_goes_below_zero():
    adsl = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ 01      │
│ 03      │
└─────────┘
""")
    ae = pl.DataFrame({"USUBJID": ["01", "01"]})
    out = (
        adsl.adam.adsl.count_events("NAE", from_dataset=ae)
        .derivation("NM1", expression="pl.col('NAE') - 1")
        .to_frame()
    )
    assert out["NAE"].dtype == pl.Int64
    assert out["NM1"].to_list() == [1, -1]


def test_chg_and_pchg_on_unsigned_values_do_not_wrap():
    adlb = pl.from_repr("""\
┌─────────┬──────┬──────┐
│ USUBJID ┆ AVAL ┆ BASE │
│ ---     ┆ ---  ┆ ---  │
│ str     ┆ u32  ┆ u32  │
╞═════════╪══════╪══════╡
│ 01      ┆ 1    ┆ 2    │
└─────────┴──────┴──────┘
""")
    out = adlb.adam.chg("CHG").pchg("PCHG").to_frame()
    assert out["CHG"].to_list() == [-1.0]
    assert out["PCHG"].to_list() == [-50.0]


# ── c1-329, c1-420: atoxgr states its unit and refuses an unknown direction ──


ANEMIA = """\
┌─────────┬──────────┬──────┬───────┬───────┐
│ USUBJID ┆ ATOXDSCL ┆ AVAL ┆ ANRLO ┆ AVALU │
│ ---     ┆ ---      ┆ ---  ┆ ---   ┆ ---   │
│ str     ┆ str      ┆ f64  ┆ f64   ┆ str   │
╞═════════╪══════════╪══════╪═══════╪═══════╡
│ S1      ┆ Anemia   ┆ 13.5 ┆ 12.0  ┆ g/dL  │
│ S2      ┆ Anemia   ┆ 75.0 ┆ 120.0 ┆ g/L   │
└─────────┴──────────┴──────┴───────┴───────┘
"""


def test_atoxgr_needs_unit_var():
    adlb = pl.from_repr(ANEMIA)
    with pytest.raises(TypeError, match="unit_var"):
        adlb.adam.atoxgr("ATOXGRL", direction="L", term_var="ATOXDSCL")


def test_atoxgr_warns_and_gives_null_for_a_unit_with_no_criteria():
    adlb = pl.from_repr(ANEMIA)
    with pytest.warns(UserWarning, match="1 'Anemia' row"):
        out = adlb.adam.atoxgr(
            "ATOXGRL", direction="L", term_var="ATOXDSCL", unit_var="AVALU"
        ).to_frame()
    assert out["ATOXGRL"].to_list() == [None, "3"]


@pytest.mark.parametrize("direction", ["LOW", "l", "low", "B"])
def test_atoxgr_refuses_an_unknown_direction(direction):
    adlb = pl.from_repr(ANEMIA)
    with pytest.raises(DerivationError, match="'L' \\(low\\) or 'H' \\(high\\)"):
        adlb.adam.atoxgr("ATOXGRL", direction=direction, term_var="ATOXDSCL", unit_var="AVALU")


# ── c1-386: combine_grades needs the descriptions, as admiral ────────────────


def test_combine_grades_zero_only_when_the_other_side_is_zero_or_has_no_criteria():
    adlb = pl.from_repr("""\
┌─────────┬─────────┬─────────┬─────────────┬──────────────┐
│ USUBJID ┆ ATOXGRL ┆ ATOXGRH ┆ ATOXDSCL    ┆ ATOXDSCH     │
│ ---     ┆ ---     ┆ ---     ┆ ---         ┆ ---          │
│ str     ┆ str     ┆ str     ┆ str         ┆ str          │
╞═════════╪═════════╪═════════╪═════════════╪══════════════╡
│ K-1     ┆ 0       ┆ null    ┆ Hypokalemia ┆ Hyperkalemia │
│ K-2     ┆ null    ┆ 0       ┆ Hypokalemia ┆ Hyperkalemia │
│ K-3     ┆ 0       ┆ null    ┆ Hypokalemia ┆ null         │
│ K-4     ┆ 0       ┆ 0       ┆ Hypokalemia ┆ Hyperkalemia │
│ K-5     ┆ 2       ┆ null    ┆ Hypokalemia ┆ Hyperkalemia │
└─────────┴─────────┴─────────┴─────────────┴──────────────┘
""")
    out = adlb.adam.combine_grades("ATOXGR").to_frame()
    assert out["ATOXGR"].to_list() == [None, None, "0", "0", "-2"]


def test_combine_grades_raises_when_a_description_column_is_missing():
    adlb = pl.from_repr("""\
┌─────────┬─────────┬─────────────┐
│ ATOXGRL ┆ ATOXGRH ┆ ATOXDSCL    │
│ ---     ┆ ---     ┆ ---         │
│ str     ┆ str     ┆ str         │
╞═════════╪═════════╪═════════════╡
│ 0       ┆ null    ┆ Hypokalemia │
└─────────┴─────────┴─────────────┘
""")
    with pytest.raises(DerivationError, match="ATOXDSCH"):
        adlb.adam.combine_grades("ATOXGR")
