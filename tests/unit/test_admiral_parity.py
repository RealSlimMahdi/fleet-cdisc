"""
Unit tests for Admiral-parity additions.

Covers:
- utils.py: bsa, mean_arterial_pressure, qtc, age_in_years
- namespace.py: bsa(), map(), qtc(), derive_summary_records(),
                derive_locf_records(), derive_param()
- adsl_namespace.py: age_years(), derive_period()
"""

import math

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration
from fleet.adam.utils import (
    age_in_years,
    bsa,
    mean_arterial_pressure,
    qtc,
)

# ══════════════════════════════════════════════════════════════════════
# 1. Pure utils.py expression tests
# ══════════════════════════════════════════════════════════════════════


class TestBSA:
    """Body Surface Area calculation tests."""

    def test_mosteller(self):
        df = pl.from_repr("""\
┌────────┬────────┐
│ WEIGHT ┆ HEIGHT │
│ ---    ┆ ---    │
│ f64    ┆ f64    │
╞════════╪════════╡
│ 70.0   ┆ 170.0  │
└────────┴────────┘
""")
        result = df.select(bsa("WEIGHT", "HEIGHT", method="Mosteller"))
        expected = math.sqrt(170.0 * 70.0 / 3600.0)
        assert result["BSA"][0] == pytest.approx(round(expected, 4))

    def test_dubois(self):
        df = pl.from_repr("""\
┌────────┬────────┐
│ WEIGHT ┆ HEIGHT │
│ ---    ┆ ---    │
│ f64    ┆ f64    │
╞════════╪════════╡
│ 70.0   ┆ 170.0  │
└────────┴────────┘
""")
        result = df.select(bsa("WEIGHT", "HEIGHT", method="DuBois"))
        expected = 0.007184 * (170.0**0.725) * (70.0**0.425)
        assert result["BSA"][0] == pytest.approx(round(expected, 4))

    def test_haycock(self):
        df = pl.from_repr("""\
┌────────┬────────┐
│ WEIGHT ┆ HEIGHT │
│ ---    ┆ ---    │
│ f64    ┆ f64    │
╞════════╪════════╡
│ 70.0   ┆ 170.0  │
└────────┴────────┘
""")
        result = df.select(bsa("WEIGHT", "HEIGHT", method="Haycock"))
        expected = 0.024265 * (170.0**0.3964) * (70.0**0.5378)
        assert result["BSA"][0] == pytest.approx(round(expected, 4))

    def test_gehan_george(self):
        df = pl.from_repr("""\
┌────────┬────────┐
│ WEIGHT ┆ HEIGHT │
│ ---    ┆ ---    │
│ f64    ┆ f64    │
╞════════╪════════╡
│ 70.0   ┆ 170.0  │
└────────┴────────┘
""")
        result = df.select(bsa("WEIGHT", "HEIGHT", method="Gehan-George"))
        expected = 0.0235 * (170.0**0.42246) * (70.0**0.51456)
        assert result["BSA"][0] == pytest.approx(round(expected, 4))

    def test_unknown_method_raises(self):
        with pytest.raises(ValueError, match="Unknown BSA method"):
            bsa("WEIGHT", "HEIGHT", method="Invalid")

    def test_null_propagation(self):
        df = pl.from_repr("""\
┌────────┬────────┐
│ WEIGHT ┆ HEIGHT │
│ ---    ┆ ---    │
│ null   ┆ f64    │
╞════════╪════════╡
│ null   ┆ 170.0  │
└────────┴────────┘
""")
        result = df.select(bsa("WEIGHT", "HEIGHT"))
        assert result["BSA"][0] is None


class TestMeanArterialPressure:
    def test_basic(self):
        df = pl.from_repr("""\
┌───────┬───────┐
│ SYSBP ┆ DIABP │
│ ---   ┆ ---   │
│ f64   ┆ f64   │
╞═══════╪═══════╡
│ 120.0 ┆ 80.0  │
└───────┴───────┘
""")
        result = df.select(mean_arterial_pressure("SYSBP", "DIABP"))
        # MAP = 80 + (120 - 80) / 3 = 80 + 13.33 = 93.33
        assert result["MAP"][0] == pytest.approx(93.33, abs=0.01)

    def test_multiple_rows(self):
        df = pl.from_repr("""\
┌───────┬───────┐
│ SYSBP ┆ DIABP │
│ ---   ┆ ---   │
│ f64   ┆ f64   │
╞═══════╪═══════╡
│ 120.0 ┆ 80.0  │
│ 140.0 ┆ 90.0  │
└───────┴───────┘
""")
        result = df.select(mean_arterial_pressure("SYSBP", "DIABP"))
        assert result["MAP"][0] == pytest.approx(93.33, abs=0.01)
        assert result["MAP"][1] == pytest.approx(106.67, abs=0.01)


class TestQTc:
    def test_fridericia(self):
        df = pl.from_repr("""\
┌───────┬───────┐
│ QT    ┆ RR    │
│ ---   ┆ ---   │
│ f64   ┆ f64   │
╞═══════╪═══════╡
│ 400.0 ┆ 800.0 │
│ 350.0 ┆ 857.0 │
└───────┴───────┘
""")
        result = df.select(qtc("QT", "RR", method="Fridericia"))
        # admiral compute_qtc, RR in ms: 430.88693800637674, 368.47478182187422
        assert result["QTC"].to_list() == [430.89, 368.47]

    def test_bazett(self):
        df = pl.from_repr("""\
┌───────┬───────┐
│ QT    ┆ RR    │
│ ---   ┆ ---   │
│ f64   ┆ f64   │
╞═══════╪═══════╡
│ 400.0 ┆ 800.0 │
│ 350.0 ┆ 857.0 │
└───────┴───────┘
""")
        result = df.select(qtc("QT", "RR", method="Bazett"))
        # admiral compute_qtc, RR in ms: 447.21359549995793, 378.07471494623951
        assert result["QTC"].to_list() == [447.21, 378.07]

    def test_fridericia_rr_in_seconds(self):
        df = pl.from_repr("""\
┌───────┬─────┐
│ QT    ┆ RR  │
│ ---   ┆ --- │
│ f64   ┆ f64 │
╞═══════╪═════╡
│ 400.0 ┆ 0.8 │
└───────┴─────┘
""")
        result = df.select(qtc("QT", "RR", method="Fridericia", rr_unit="s"))
        assert result["QTC"][0] == pytest.approx(430.89)

    def test_unknown_method_raises(self):
        with pytest.raises(ValueError, match="Unknown QTc method"):
            qtc("QT", "RR", method="Unknown")


class TestAgeInYears:
    def test_years(self):
        df = pl.from_repr("""\
┌──────┬───────┐
│ AGE  ┆ AGEU  │
│ ---  ┆ ---   │
│ f64  ┆ str   │
╞══════╪═══════╡
│ 45.0 ┆ YEARS │
└──────┴───────┘
""")
        result = df.select(age_in_years("AGE", "AGEU"))
        assert result["AAGE"][0] == pytest.approx(45.0)

    def test_months(self):
        df = pl.from_repr("""\
┌──────┬────────┐
│ AGE  ┆ AGEU   │
│ ---  ┆ ---    │
│ f64  ┆ str    │
╞══════╪════════╡
│ 24.0 ┆ MONTHS │
└──────┴────────┘
""")
        result = df.select(age_in_years("AGE", "AGEU"))
        assert result["AAGE"][0] == pytest.approx(2.0)

    def test_days(self):
        df = pl.from_repr("""\
┌────────┬──────┐
│ AGE    ┆ AGEU │
│ ---    ┆ ---  │
│ f64    ┆ str  │
╞════════╪══════╡
│ 365.25 ┆ DAYS │
└────────┴──────┘
""")
        result = df.select(age_in_years("AGE", "AGEU"))
        assert result["AAGE"][0] == pytest.approx(1.0)

    def test_weeks(self):
        df = pl.from_repr("""\
┌─────────┬───────┐
│ AGE     ┆ AGEU  │
│ ---     ┆ ---   │
│ f64     ┆ str   │
╞═════════╪═══════╡
│ 52.1775 ┆ WEEKS │
└─────────┴───────┘
""")
        result = df.select(age_in_years("AGE", "AGEU"))
        assert result["AAGE"][0] == pytest.approx(1.0)

    def test_case_insensitive(self):
        df = pl.from_repr("""\
┌──────┬───────┐
│ AGE  ┆ AGEU  │
│ ---  ┆ ---   │
│ f64  ┆ str   │
╞══════╪═══════╡
│ 45.0 ┆ years │
└──────┴───────┘
""")
        result = df.select(age_in_years("AGE", "AGEU"))
        assert result["AAGE"][0] == pytest.approx(45.0)

    def test_unknown_unit_returns_null(self):
        df = pl.from_repr("""\
┌──────┬───────────┐
│ AGE  ┆ AGEU      │
│ ---  ┆ ---       │
│ f64  ┆ str       │
╞══════╪═══════════╡
│ 45.0 ┆ CENTURIES │
└──────┴───────────┘
""")
        result = df.select(age_in_years("AGE", "AGEU"))
        assert result["AAGE"][0] is None


# ══════════════════════════════════════════════════════════════════════
# 2. BDS namespace verb tests (df.adam.*)
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture
def vs_bds():
    """Vital Signs BDS-like frame."""
    return pl.from_repr("""\
┌─────────┬─────────┬──────────────┬───────┬────────────┬────────────┬───────┐
│ USUBJID ┆ PARAMCD ┆ PARAM        ┆ AVAL  ┆ ADT        ┆ TRTSDT     ┆ ABLFL │
│ ---     ┆ ---     ┆ ---          ┆ ---   ┆ ---        ┆ ---        ┆ ---   │
│ str     ┆ str     ┆ str          ┆ f64   ┆ str        ┆ str        ┆ str   │
╞═════════╪═════════╪══════════════╪═══════╪════════════╪════════════╪═══════╡
│ 01      ┆ SYSBP   ┆ Systolic BP  ┆ 120.0 ┆ 2014-01-02 ┆ 2014-01-01 ┆ Y     │
│ 01      ┆ DIABP   ┆ Diastolic BP ┆ 80.0  ┆ 2014-01-02 ┆ 2014-01-01 ┆ Y     │
│ 01      ┆ SYSBP   ┆ Systolic BP  ┆ 130.0 ┆ 2014-01-03 ┆ 2014-01-01 ┆ null  │
│ 02      ┆ SYSBP   ┆ Systolic BP  ┆ 118.0 ┆ 2014-01-02 ┆ 2014-01-01 ┆ Y     │
│ 02      ┆ DIABP   ┆ Diastolic BP ┆ 76.0  ┆ 2014-01-02 ┆ 2014-01-01 ┆ Y     │
└─────────┴─────────┴──────────────┴───────┴────────────┴────────────┴───────┘
""")


class TestNamespaceBSA:
    def test_bsa_verb(self):
        df = pl.from_repr("""\
┌─────────┬────────┬────────┐
│ USUBJID ┆ WEIGHT ┆ HEIGHT │
│ ---     ┆ ---    ┆ ---    │
│ str     ┆ f64    ┆ f64    │
╞═════════╪════════╪════════╡
│ 01      ┆ 70.0   ┆ 170.0  │
└─────────┴────────┴────────┘
""")
        result = df.adam.bsa("BSA", weight="WEIGHT", height="HEIGHT").to_frame()
        expected = math.sqrt(170.0 * 70.0 / 3600.0)
        assert result["BSA"][0] == pytest.approx(round(expected, 4))


class TestNamespaceMAP:
    def test_map_verb(self):
        df = pl.from_repr("""\
┌─────────┬───────┬───────┐
│ USUBJID ┆ SYSBP ┆ DIABP │
│ ---     ┆ ---   ┆ ---   │
│ str     ┆ f64   ┆ f64   │
╞═════════╪═══════╪═══════╡
│ 01      ┆ 120.0 ┆ 80.0  │
└─────────┴───────┴───────┘
""")
        result = df.adam.map("MAP", systolic="SYSBP", diastolic="DIABP").to_frame()
        assert result["MAP"][0] == pytest.approx(93.33, abs=0.01)


class TestNamespaceQTc:
    def test_qtc_verb(self):
        df = pl.from_repr("""\
┌─────────┬───────┬───────┐
│ USUBJID ┆ QT    ┆ RR    │
│ ---     ┆ ---   ┆ ---   │
│ str     ┆ f64   ┆ f64   │
╞═════════╪═══════╪═══════╡
│ 01      ┆ 400.0 ┆ 850.0 │
└─────────┴───────┴───────┘
""")
        result = df.adam.qtc("QTCF", qt="QT", rr="RR").to_frame()
        expected = 400.0 / (0.85 ** (1.0 / 3.0))
        assert result["QTCF"][0] == pytest.approx(round(expected, 2))


class TestDeriveSummaryRecords:
    def test_mean_summary(self, vs_bds):
        result = vs_bds.adam.derive_summary_records(
            by=["USUBJID", "PARAMCD"],
            analysis_var="AVAL",
            set_values_to={"DTYPE": "AVERAGE"},
            stat="mean",
        ).to_frame()
        # Original has 5 rows; new summary rows added per group
        assert len(result) > len(vs_bds)
        summary_rows = result.filter(pl.col("DTYPE") == "AVERAGE")
        assert len(summary_rows) > 0
        # check SYSBP mean for subject 01: (120+130)/2 = 125
        sbp_01 = summary_rows.filter((pl.col("USUBJID") == "01") & (pl.col("PARAMCD") == "SYSBP"))
        assert sbp_01["AVAL"][0] == pytest.approx(125.0)

    def test_sum_summary(self, vs_bds):
        result = vs_bds.adam.derive_summary_records(
            by=["USUBJID", "PARAMCD"],
            analysis_var="AVAL",
            set_values_to={"DTYPE": "SUM"},
            stat="sum",
        ).to_frame()
        summary_rows = result.filter(pl.col("DTYPE") == "SUM")
        sbp_01 = summary_rows.filter((pl.col("USUBJID") == "01") & (pl.col("PARAMCD") == "SYSBP"))
        assert sbp_01["AVAL"][0] == pytest.approx(250.0)

    def test_invalid_stat_raises(self, vs_bds):
        with pytest.raises(ValueError, match="Unknown stat"):
            vs_bds.adam.derive_summary_records(
                by=["USUBJID"],
                set_values_to={"DTYPE": "X"},
                stat="variance",
            ).to_frame()


class TestDeriveLOCFRecords:
    def test_forward_fill(self):
        df = pl.from_repr("""\
┌─────────┬─────────┬───────┬────────────┐
│ USUBJID ┆ PARAMCD ┆ AVAL  ┆ ADT        │
│ ---     ┆ ---     ┆ ---   ┆ ---        │
│ str     ┆ str     ┆ f64   ┆ str        │
╞═════════╪═════════╪═══════╪════════════╡
│ 01      ┆ SBP     ┆ 120.0 ┆ 2014-01-01 │
│ 01      ┆ SBP     ┆ null  ┆ 2014-01-02 │
│ 01      ┆ SBP     ┆ null  ┆ 2014-01-03 │
│ 02      ┆ SBP     ┆ 110.0 ┆ 2014-01-01 │
│ 02      ┆ SBP     ┆ null  ┆ 2014-01-02 │
└─────────┴─────────┴───────┴────────────┘
""")
        result = df.adam.derive_locf_records(
            by=["USUBJID", "PARAMCD"],
            analysis_var="AVAL",
            order_by="ADT",
        ).to_frame()
        vals = result.sort(["USUBJID", "ADT"])["AVAL"].to_list()
        # 01: 120, 120 (filled), 120 (filled); 02: 110, 110 (filled)
        assert vals == [120.0, 120.0, 120.0, 110.0, 110.0]


class TestDeriveParam:
    def test_derive_bmi_param(self):
        df = pl.from_repr("""\
┌─────────┬─────────┬────────┬───────┬────────────┐
│ USUBJID ┆ PARAMCD ┆ PARAM  ┆ AVAL  ┆ ADT        │
│ ---     ┆ ---     ┆ ---    ┆ ---   ┆ ---        │
│ str     ┆ str     ┆ str    ┆ f64   ┆ str        │
╞═════════╪═════════╪════════╪═══════╪════════════╡
│ 01      ┆ WEIGHT  ┆ Weight ┆ 70.0  ┆ 2014-01-01 │
│ 01      ┆ HEIGHT  ┆ Height ┆ 170.0 ┆ 2014-01-01 │
│ 02      ┆ WEIGHT  ┆ Weight ┆ 80.0  ┆ 2014-01-01 │
│ 02      ┆ HEIGHT  ┆ Height ┆ 180.0 ┆ 2014-01-01 │
└─────────┴─────────┴────────┴───────┴────────────┘
""")
        result = df.adam.derive_param(
            by=["USUBJID"],
            set_values_to={"PARAMCD": "BMI", "PARAM": "Body Mass Index"},
            parameter_filter={"WEIGHT": "WEIGHT", "HEIGHT": "HEIGHT"},
            analysis_value=pl.col("WEIGHT") / (pl.col("HEIGHT") / 100) ** 2,
        ).to_frame()
        bmi_rows = result.filter(pl.col("PARAMCD") == "BMI")
        assert len(bmi_rows) == 2
        # Subject 01: 70 / (1.7)^2 ≈ 24.22
        bmi_01 = bmi_rows.filter(pl.col("USUBJID") == "01")["AVAL"][0]
        assert bmi_01 == pytest.approx(70.0 / 1.7**2, rel=0.01)
        # Subject 02: 80 / (1.8)^2 ≈ 24.69
        bmi_02 = bmi_rows.filter(pl.col("USUBJID") == "02")["AVAL"][0]
        assert bmi_02 == pytest.approx(80.0 / 1.8**2, rel=0.01)

    def test_duplicate_source_records_raise_instead_of_multiplying(self):
        """admiral parity: non-unique by-groups are an error, not silent dup rows."""
        df = pl.from_repr("""
┌─────────┬─────────┬───────┐
│ USUBJID ┆ PARAMCD ┆ AVAL  │
│ ---     ┆ ---     ┆ ---   │
│ str     ┆ str     ┆ f64   │
╞═════════╪═════════╪═══════╡
│ 01      ┆ WEIGHT  ┆ 70.0  │
│ 01      ┆ WEIGHT  ┆ 71.0  │
│ 01      ┆ HEIGHT  ┆ 170.0 │
└─────────┴─────────┴───────┘
""")
        with pytest.raises(Exception, match="multiple records"):
            df.adam.derive_param(
                by=["USUBJID"],
                set_values_to={"PARAMCD": "BMI"},
                parameter_filter={"WEIGHT": "WEIGHT", "HEIGHT": "HEIGHT"},
                analysis_value=pl.col("WEIGHT") / (pl.col("HEIGHT") / 100) ** 2,
            )

    def test_set_values_to_adds_new_columns_like_dtype(self):
        """A set_values_to column absent from the frame (DTYPE) must be added,
        not silently dropped."""
        df = pl.from_repr("""
┌─────────┬─────────┬───────┐
│ USUBJID ┆ PARAMCD ┆ AVAL  │
│ ---     ┆ ---     ┆ ---   │
│ str     ┆ str     ┆ f64   │
╞═════════╪═════════╪═══════╡
│ 01      ┆ WEIGHT  ┆ 70.0  │
│ 01      ┆ HEIGHT  ┆ 170.0 │
└─────────┴─────────┴───────┘
""")
        result = df.adam.derive_param(
            by=["USUBJID"],
            set_values_to={"PARAMCD": "BMI", "DTYPE": "DERIVED"},
            parameter_filter={"WEIGHT": "WEIGHT", "HEIGHT": "HEIGHT"},
            analysis_value=pl.col("WEIGHT") / (pl.col("HEIGHT") / 100) ** 2,
        ).to_frame()
        assert "DTYPE" in result.columns
        assert result.filter(pl.col("PARAMCD") == "BMI")["DTYPE"].to_list() == ["DERIVED"]
        assert result.filter(pl.col("PARAMCD") == "WEIGHT")["DTYPE"].to_list() == [None]

    def test_from_dataset_pivots_another_bds_frame(self):
        """The source parameters can come from a different dataset entirely."""
        advs = pl.from_repr("""
┌─────────┬─────────┬───────┐
│ USUBJID ┆ PARAMCD ┆ AVAL  │
│ ---     ┆ ---     ┆ ---   │
│ str     ┆ str     ┆ f64   │
╞═════════╪═════════╪═══════╡
│ 01      ┆ SYSBP   ┆ 120.0 │
└─────────┴─────────┴───────┘
""")
        adlb = pl.from_repr("""
┌─────────┬─────────┬──────┬─────────┐
│ USUBJID ┆ PARAMCD ┆ AVAL ┆ ANL01FL │
│ ---     ┆ ---     ┆ ---  ┆ ---     │
│ str     ┆ str     ┆ f64  ┆ str     │
╞═════════╪═════════╪══════╪═════════╡
│ 01      ┆ CREAT   ┆ 1.0  ┆ Y       │
│ 01      ┆ CREAT   ┆ 9.9  ┆ N       │
└─────────┴─────────┴──────┴─────────┘
""")
        result = advs.adam.derive_param(
            by=["USUBJID"],
            set_values_to={"PARAMCD": "CREATX"},
            parameter_filter={"CREAT": "CREAT"},
            analysis_value='pl.col("CREAT") * 2',
            from_dataset=adlb,
            where='pl.col("ANL01FL") == "Y"',  # excludes the 9.9 row (and dedups)
        ).to_frame()
        new = result.filter(pl.col("PARAMCD") == "CREATX")
        assert new["AVAL"].to_list() == [2.0]
        # The current dataset's rows are untouched by where=
        assert result.filter(pl.col("PARAMCD") == "SYSBP").height == 1

    def test_param_level_identifiers_land_on_new_rows(self):
        """PARAMN / PARCATy / PARCATyN / DTYPE flow through set_values_to with
        dtypes relaxed to the frame's schema."""
        df = pl.from_repr("""
┌─────────┬─────────┬─────────────┬────────┬─────────┬──────────┬───────┐
│ USUBJID ┆ PARAMCD ┆ PARAM       ┆ PARAMN ┆ PARCAT1 ┆ PARCAT1N ┆ AVAL  │
│ ---     ┆ ---     ┆ ---         ┆ ---    ┆ ---     ┆ ---      ┆ ---   │
│ str     ┆ str     ┆ str         ┆ i64    ┆ str     ┆ i64      ┆ f64   │
╞═════════╪═════════╪═════════════╪════════╪═════════╪══════════╪═══════╡
│ 01      ┆ WEIGHT  ┆ Weight (kg) ┆ 1      ┆ ANTHRO  ┆ 1        ┆ 70.0  │
│ 01      ┆ HEIGHT  ┆ Height (cm) ┆ 2      ┆ ANTHRO  ┆ 1        ┆ 170.0 │
└─────────┴─────────┴─────────────┴────────┴─────────┴──────────┴───────┘
""")
        result = df.adam.derive_param(
            by=["USUBJID"],
            set_values_to={
                "PARAMCD": "BMI",
                "PARAM": "Body Mass Index (kg/m^2)",
                "PARAMN": 3,
                "PARCAT1": "ANTHRO",
                "PARCAT1N": 1,
                "DTYPE": "DERIVED",
            },
            parameter_filter={"WEIGHT": "WEIGHT", "HEIGHT": "HEIGHT"},
            analysis_value=pl.col("WEIGHT") / (pl.col("HEIGHT") / 100) ** 2,
        ).to_frame()
        bmi = result.filter(pl.col("PARAMCD") == "BMI")
        assert bmi.select("PARAM", "PARAMN", "PARCAT1", "PARCAT1N", "DTYPE").row(0) == (
            "Body Mass Index (kg/m^2)",
            3,
            "ANTHRO",
            1,
            "DERIVED",
        )
        assert result.schema["PARAMN"] == pl.Int64  # relaxed to the frame's dtype

    def test_existing_paramcd_collision_raises(self):
        """Appending under an already-used PARAMCD would break the
        PARAMCD ↔ PARAM one-to-one mapping — admiral parity: hard error."""
        df = pl.from_repr("""
┌─────────┬─────────┬─────────────┬───────┐
│ USUBJID ┆ PARAMCD ┆ PARAM       ┆ AVAL  │
│ ---     ┆ ---     ┆ ---         ┆ ---   │
│ str     ┆ str     ┆ str         ┆ f64   │
╞═════════╪═════════╪═════════════╪═══════╡
│ 01      ┆ WEIGHT  ┆ Weight (kg) ┆ 70.0  │
│ 01      ┆ HEIGHT  ┆ Height (cm) ┆ 170.0 │
└─────────┴─────────┴─────────────┴───────┘
""")
        with pytest.raises(Exception, match="already exists"):
            df.adam.derive_param(
                by=["USUBJID"],
                set_values_to={"PARAMCD": "WEIGHT", "PARAM": "Weight (LB)"},
                parameter_filter={"HEIGHT": "HEIGHT"},
                analysis_value=pl.col("HEIGHT"),
            )

    def test_from_dataset_missing_bds_columns_raises(self):
        advs = pl.from_repr("""\
┌─────────┬─────────┬───────┐
│ USUBJID ┆ PARAMCD ┆ AVAL  │
│ ---     ┆ ---     ┆ ---   │
│ str     ┆ str     ┆ f64   │
╞═════════╪═════════╪═══════╡
│ 01      ┆ SYSBP   ┆ 120.0 │
└─────────┴─────────┴───────┘
""")
        not_bds = pl.from_repr("""\
┌─────────┬───────┐
│ USUBJID ┆ CREAT │
│ ---     ┆ ---   │
│ str     ┆ f64   │
╞═════════╪═══════╡
│ 01      ┆ 1.0   │
└─────────┴───────┘
""")
        with pytest.raises(Exception, match="BDS-shaped"):
            advs.adam.derive_param(
                by=["USUBJID"],
                set_values_to={"PARAMCD": "X"},
                parameter_filter={"CREAT": "CREAT"},
                analysis_value=pl.col("CREAT"),
                from_dataset=not_bds,
            )


# ══════════════════════════════════════════════════════════════════════
# 3. ADSL namespace verb tests (df.adam.adsl.*)
# ══════════════════════════════════════════════════════════════════════


class TestADSLAgeYears:
    def test_years_passthrough(self):
        df = pl.from_repr("""\
┌─────────┬──────┬────────┐
│ USUBJID ┆ AGE  ┆ AGEU   │
│ ---     ┆ ---  ┆ ---    │
│ str     ┆ f64  ┆ str    │
╞═════════╪══════╪════════╡
│ 01      ┆ 45.0 ┆ YEARS  │
│ 02      ┆ 62.0 ┆ MONTHS │
└─────────┴──────┴────────┘
""")
        result = df.adam.adsl.age_years("AAGE", age_col="AGE", age_unit_col="AGEU").to_frame()
        assert result["AAGE"][0] == pytest.approx(45.0)
        # 62 months → ~5.2 years
        assert result["AAGE"][1] == pytest.approx(round(62.0 / 12.0, 1))


class TestADSLDerivePeriod:
    def test_creates_period_columns(self):
        df = pl.from_repr("""\
┌─────────┬────────────┬────────────┬────────┬────────────┬────────────┬─────────┐
│ USUBJID ┆ AP01SDT    ┆ AP01EDT    ┆ TRT01P ┆ AP02SDT    ┆ AP02EDT    ┆ TRT02P  │
│ ---     ┆ ---        ┆ ---        ┆ ---    ┆ ---        ┆ ---        ┆ ---     │
│ str     ┆ str        ┆ str        ┆ str    ┆ str        ┆ str        ┆ str     │
╞═════════╪════════════╪════════════╪════════╪════════════╪════════════╪═════════╡
│ 01      ┆ 2014-01-01 ┆ 2014-06-30 ┆ Active ┆ 2014-07-01 ┆ 2014-12-31 ┆ Placebo │
└─────────┴────────────┴────────────┴────────┴────────────┴────────────┴─────────┘
""")
        result = df.adam.adsl.derive_period(
            periods=[
                {"number": 1, "start": "AP01SDT", "end": "AP01EDT", "treatment": "TRT01P"},
                {"number": 2, "start": "AP02SDT", "end": "AP02EDT", "treatment": "TRT02P"},
            ],
        ).to_frame()
        assert result["AP01SDT"][0] == "2014-01-01"
        assert result["AP01EDT"][0] == "2014-06-30"
        assert result["TRT01P"][0] == "Active"
        assert result["AP02SDT"][0] == "2014-07-01"
        assert result["AP02EDT"][0] == "2014-12-31"
        assert result["TRT02P"][0] == "Placebo"


# ══════════════════════════════════════════════════════════════════════
# 4. Schema alignment in derive_summary_records
# ══════════════════════════════════════════════════════════════════════


class TestDeriveSummarySchemaAlignment:
    def test_concat_schema_matches(self, vs_bds):
        """Ensures pl.concat handles mismatched schemas via vertical_relaxed."""
        result = vs_bds.adam.derive_summary_records(
            by=["USUBJID"],
            analysis_var="AVAL",
            set_values_to={"DTYPE": "OVERALL_MEAN"},
            stat="mean",
        ).to_frame()
        # All original columns must be present
        for col in vs_bds.columns:
            assert col in result.columns
        # DTYPE column exists
        assert "DTYPE" in result.columns


# ══════════════════════════════════════════════════════════════════════
# 5. ANL01FL — admiral restrict_derivation + derive_var_extreme_flag
# ══════════════════════════════════════════════════════════════════════


class TestANL01FLAdmiralParity:
    """Byte-for-byte parity with admiral's ANL01FL derivation for BDS.

    Admiral pattern::

        advs <- restrict_derivation(
          advs,
          derivation = derive_var_extreme_flag,
          args = params(
            by_vars = exprs(USUBJID, PARAMCD),
            order   = exprs(ADT),
            new_var = ANL01FL,
            mode    = "last"
          ),
          filter = !is.na(AVAL)
        )

    Within each (USUBJID, PARAMCD) group, the *last* record by ADT
    among rows with non-null AVAL receives ``"Y"``; all others
    (including rows with null AVAL) receive ``null``.
    """

    @pytest.fixture
    def bds_multi_record(self):
        """BDS frame with multiple records per subject/parameter.

        Designed to exercise:
        - Multiple dates per group → only the latest gets ANL01FL = "Y"
        - Null AVAL → excluded by restrict_derivation filter
        - Single-record group → trivially flagged "Y"
        """
        return pl.from_repr("""\
┌─────────┬─────────┬───────┬────────────┐
│ USUBJID ┆ PARAMCD ┆ AVAL  ┆ ADT        │
│ ---     ┆ ---     ┆ ---   ┆ ---        │
│ str     ┆ str     ┆ f64   ┆ str        │
╞═════════╪═════════╪═══════╪════════════╡
│ 01      ┆ SYSBP   ┆ 120.0 ┆ 2014-01-02 │
│ 01      ┆ SYSBP   ┆ 130.0 ┆ 2014-01-05 │
│ 01      ┆ SYSBP   ┆ null  ┆ 2014-01-10 │
│ 01      ┆ DIABP   ┆ 80.0  ┆ 2014-01-02 │
│ 02      ┆ SYSBP   ┆ 118.0 ┆ 2014-01-03 │
│ 02      ┆ SYSBP   ┆ 125.0 ┆ 2014-01-07 │
└─────────┴─────────┴───────┴────────────┘
""")

    def test_last_valid_flagged(self, bds_multi_record):
        """Last non-null-AVAL record per group gets ANL01FL = 'Y'."""
        result = bds_multi_record.adam.flag(
            "ANL01FL",
            criteria="last",
            order_by="ADT",
            by=["USUBJID", "PARAMCD"],
            where='~pl.col("AVAL").is_null()',
        ).to_frame()

        flags = result["ANL01FL"].to_list()

        # Admiral expected output:
        # Row 0: 01/SYSBP/2014-01-02 AVAL=120  → null  (not last valid)
        # Row 1: 01/SYSBP/2014-01-05 AVAL=130  → "Y"   (last valid — 01-10 has null AVAL)
        # Row 2: 01/SYSBP/2014-01-10 AVAL=null  → null  (excluded by filter)
        # Row 3: 01/DIABP/2014-01-02 AVAL=80   → "Y"   (only record in group)
        # Row 4: 02/SYSBP/2014-01-03 AVAL=118  → null  (not last)
        # Row 5: 02/SYSBP/2014-01-07 AVAL=125  → "Y"   (last valid)
        assert flags == [None, "Y", None, "Y", None, "Y"]

    def test_all_valid_single_record_groups(self):
        """Every group has exactly one record → all get ANL01FL = 'Y'."""
        df = pl.from_repr("""\
┌─────────┬─────────┬───────┬────────────┐
│ USUBJID ┆ PARAMCD ┆ AVAL  ┆ ADT        │
│ ---     ┆ ---     ┆ ---   ┆ ---        │
│ str     ┆ str     ┆ f64   ┆ str        │
╞═════════╪═════════╪═══════╪════════════╡
│ 01      ┆ SYSBP   ┆ 120.0 ┆ 2014-01-02 │
│ 02      ┆ SYSBP   ┆ 118.0 ┆ 2014-01-03 │
└─────────┴─────────┴───────┴────────────┘
""")
        result = df.adam.flag(
            "ANL01FL",
            criteria="last",
            order_by="ADT",
            by=["USUBJID", "PARAMCD"],
            where='~pl.col("AVAL").is_null()',
        ).to_frame()
        assert result["ANL01FL"].to_list() == ["Y", "Y"]

    def test_all_null_aval_group(self):
        """Group where all AVAL are null → no records flagged."""
        df = pl.from_repr("""\
┌─────────┬─────────┬──────┬────────────┐
│ USUBJID ┆ PARAMCD ┆ AVAL ┆ ADT        │
│ ---     ┆ ---     ┆ ---  ┆ ---        │
│ str     ┆ str     ┆ null ┆ str        │
╞═════════╪═════════╪══════╪════════════╡
│ 01      ┆ SYSBP   ┆ null ┆ 2014-01-02 │
│ 01      ┆ SYSBP   ┆ null ┆ 2014-01-05 │
└─────────┴─────────┴──────┴────────────┘
""")
        result = df.adam.flag(
            "ANL01FL",
            criteria="last",
            order_by="ADT",
            by=["USUBJID", "PARAMCD"],
            where='~pl.col("AVAL").is_null()',
        ).to_frame()
        assert result["ANL01FL"].to_list() == [None, None]

    def test_with_avisit_grouping(self):
        """ANL01FL with AVISIT in by_vars — admiral's typical BDS pattern.

        Admiral::

            restrict_derivation(
              derivation = derive_var_extreme_flag,
              args = params(
                by_vars = exprs(USUBJID, PARAMCD, AVISIT),
                order   = exprs(ADT, AVAL),
                mode    = "last"
              ),
              filter = !is.na(AVAL)
            )
        """
        df = pl.from_repr("""\
┌─────────┬─────────┬────────┬───────┬────────────┐
│ USUBJID ┆ PARAMCD ┆ AVISIT ┆ AVAL  ┆ ADT        │
│ ---     ┆ ---     ┆ ---    ┆ ---   ┆ ---        │
│ str     ┆ str     ┆ str    ┆ f64   ┆ str        │
╞═════════╪═════════╪════════╪═══════╪════════════╡
│ 01      ┆ SYSBP   ┆ Week 2 ┆ 120.0 ┆ 2014-01-10 │
│ 01      ┆ SYSBP   ┆ Week 2 ┆ 125.0 ┆ 2014-01-12 │
│ 01      ┆ SYSBP   ┆ Week 4 ┆ 130.0 ┆ 2014-01-24 │
│ 01      ┆ SYSBP   ┆ Week 4 ┆ null  ┆ 2014-01-26 │
└─────────┴─────────┴────────┴───────┴────────────┘
""")
        result = df.adam.flag(
            "ANL01FL",
            criteria="last",
            order_by="ADT",
            by=["USUBJID", "PARAMCD", "AVISIT"],
            where='~pl.col("AVAL").is_null()',
        ).to_frame()
        flags = result["ANL01FL"].to_list()
        # Week 2: 01-10 (120) → null, 01-12 (125) → "Y" (last valid)
        # Week 4: 01-24 (130) → "Y" (last valid — 01-26 has null AVAL)
        #         01-26 (null) → null (excluded)
        assert flags == [None, "Y", "Y", None]
