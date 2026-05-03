"""Unit tests for the ADaM Polars namespace extension (df.adam)."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration


@pytest.fixture
def vs_frame():
    """Minimal VS SDTM-like frame."""
    return pl.DataFrame(
        {
            "USUBJID": ["01-701-1015", "01-701-1015", "01-701-1023"],
            "PARAMCD": ["SYSBP", "DIABP", "SYSBP"],
            "PARAM": ["Systolic BP", "Diastolic BP", "Systolic BP"],
            "VSSTRESN": [120.0, 80.0, 118.0],
            "vsorresu": ["mmHg", "mmHg", "mmHg"],
            "vsdtc": ["2014-01-02", "2014-01-02", "2014-01-03"],
            "TRTSDT": ["2014-01-02", "2014-01-02", "2014-01-03"],
            "ABLFL": ["Y", "Y", "Y"],
        }
    )


class TestSource:
    def test_source_copies_column(self, vs_frame):
        result = vs_frame.adam.source("USUBJID").to_frame()
        assert "USUBJID" in result.columns

    def test_source_from_col(self, vs_frame):
        result = vs_frame.adam.source("SUBJECT", from_col="USUBJID").to_frame()
        assert result["SUBJECT"].to_list() == vs_frame["USUBJID"].to_list()


class TestDerivation:
    def test_column_ref(self, vs_frame):
        result = vs_frame.adam.derivation("AVAL", expression="VSSTRESN").to_frame()
        assert result["AVAL"].to_list() == vs_frame["VSSTRESN"].to_list()

    def test_expression(self, vs_frame):
        result = vs_frame.adam.derivation("AVAL2", expression='pl.col("VSSTRESN") * 2').to_frame()
        assert result["AVAL2"][0] == pytest.approx(240.0)


class TestAssigned:
    def test_constant(self, vs_frame):
        result = vs_frame.adam.assigned("STUDYID", value="CDISCPILOT01").to_frame()
        assert result["STUDYID"].to_list() == ["CDISCPILOT01"] * 3


class TestRecode:
    def test_recode_values(self, vs_frame):
        result = vs_frame.adam.recode(
            "PARAMCD_CODED",
            source="PARAMCD",
            recode_map={"SYSBP": "SBP", "DIABP": "DBP"},
        ).to_frame()
        vals = result["PARAMCD_CODED"].to_list()
        assert vals[0] == "SBP"
        assert vals[1] == "DBP"

    def test_unmapped_gets_default(self, vs_frame):
        result = vs_frame.adam.recode(
            "PARAMCD_CODED",
            source="PARAMCD",
            recode_map={"SYSBP": "SBP"},
            default="OTHER",
        ).to_frame()
        assert result["PARAMCD_CODED"][1] == "OTHER"


class TestRename:
    def test_rename_column(self, vs_frame):
        result = vs_frame.adam.rename("ADT", source="vsdtc").to_frame()
        assert "ADT" in result.columns
        assert result["ADT"].to_list() == vs_frame["vsdtc"].to_list()


class TestCondDerivation:
    def test_multi_branch(self, vs_frame):
        result = vs_frame.adam.condderivation(
            "DTYPE",
            conditions=[
                {"condition": 'pl.col("ABLFL") == "Y"', "value": "BASELINE"},
            ],
            else_value=None,
        ).to_frame()
        assert result["DTYPE"][0] == "BASELINE"


class TestStudyDay:
    def test_study_day_same_day(self, vs_frame):
        result = vs_frame.adam.duration(
            "ADY", start="TRTSDT", end="vsdtc"
        ).to_frame()
        assert result["ADY"][0] == 1

    def test_study_day_requires_dates(self, vs_frame):
        with pytest.raises((ValueError, TypeError, AttributeError)):
            vs_frame.adam.duration("ADY", start="vsdtc", end=None)


class TestBaseline:
    def test_baseline_aval(self, vs_frame):
        df = vs_frame.with_columns(pl.col("VSSTRESN").alias("AVAL"))
        result = df.adam.baseline(
            "BASE",
            aval="AVAL",
            baseline_flag="ABLFL",
            groups=["USUBJID", "PARAMCD"],
        ).to_frame()
        assert "BASE" in result.columns


class TestChg:
    def test_chg_computation(self):
        df = pl.DataFrame({"AVAL": [120.0, 118.0], "BASE": [120.0, 120.0]})
        result = df.adam.chg("CHG", aval="AVAL", base="BASE").to_frame()
        assert result["CHG"][0] == pytest.approx(0.0)
        assert result["CHG"][1] == pytest.approx(-2.0)


class TestPchg:
    def test_pchg_computation(self):
        df = pl.DataFrame({"AVAL": [130.0, 120.0], "BASE": [100.0, 100.0]})
        result = df.adam.pchg("PCHG", aval="AVAL", base="BASE").to_frame()
        assert result["PCHG"][0] == pytest.approx(30.0)
        assert result["PCHG"][1] == pytest.approx(20.0)


class TestFlag:
    def test_expression_criteria(self, vs_frame):
        result = vs_frame.adam.flag(
            "ABLFL2",
            criteria='pl.col("ABLFL") == "Y"',
            groups=["USUBJID", "PARAMCD"],
        ).to_frame()
        assert result["ABLFL2"][0] == "Y"

    def test_max_criteria(self, vs_frame):
        df = vs_frame.with_columns(pl.col("VSSTRESN").alias("AVAL"))
        result = df.adam.flag(
            "AMXFL",
            criteria="max",
            value_col="AVAL",
            groups=["USUBJID", "PARAMCD"],
        ).to_frame()
        assert "AMXFL" in result.columns

    def test_max_requires_value_col(self, vs_frame):
        with pytest.raises(ValueError, match="value_col"):
            vs_frame.adam.flag("X", criteria="max", groups=["USUBJID"]).to_frame()

    def test_first_requires_order_by(self, vs_frame):
        with pytest.raises(ValueError, match="order_by"):
            vs_frame.adam.flag("X", criteria="first", groups=["USUBJID"]).to_frame()


class TestBMI:
    def test_bmi_computation(self):
        df = pl.DataFrame({"weight_kg": [70.0], "height_cm": [175.0]})
        result = df.adam.bmi("BMI", weight="weight_kg", height="height_cm").to_frame()
        assert result["BMI"][0] == pytest.approx(22.9, abs=0.1)


class TestNrind:
    def test_low_normal_high(self):
        df = pl.DataFrame(
            {
                "LBSTRESN": [3.0, 5.0, 9.0],
                "LBSTNRLO": [4.0, 4.0, 4.0],
                "LBSTNRHI": [8.0, 8.0, 8.0],
            }
        )
        result = df.adam.nrind(
            "NRIND", value="LBSTRESN", low="LBSTNRLO", high="LBSTNRHI"
        ).to_frame()
        assert result["NRIND"].to_list() == ["LOW", "NORMAL", "HIGH"]


class TestOnTreatment:
    def test_on_treatment_flag(self):
        df = pl.DataFrame(
            {
                "ADT": ["2024-01-15", "2024-01-05", "2024-02-01"],
                "TRTSDT": ["2024-01-10", "2024-01-10", "2024-01-10"],
                "TRTEDT": ["2024-01-31", "2024-01-31", "2024-01-31"],
            }
        )
        result = df.adam.on_treatment(
            "ONTRTFL", adt="ADT", trtsdt="TRTSDT", trtedt="TRTEDT"
        ).to_frame()
        flags = result["ONTRTFL"].to_list()
        assert flags[0] == "Y"  # on-treatment
        assert flags[1] is None  # before treatment
        assert flags[2] is None  # after treatment


class TestShift:
    def test_shift_string(self):
        df = pl.DataFrame(
            {
                "BNRIND": ["NORMAL", "LOW"],
                "NRIND": ["HIGH", "NORMAL"],
            }
        )
        result = df.adam.shift("SHIFT1", baseline_cat="BNRIND", post_cat="NRIND").to_frame()
        assert result["SHIFT1"].to_list() == ["NORMAL to HIGH", "LOW to NORMAL"]

    def test_custom_sep(self):
        df = pl.DataFrame({"B": ["NORMAL"], "P": ["HIGH"]})
        result = df.adam.shift("SH", baseline_cat="B", post_cat="P", sep=" → ").to_frame()
        assert result["SH"][0] == "NORMAL → HIGH"


class TestWhereclauses:
    def test_filter(self, vs_frame):
        result = vs_frame.adam.whereclauses(where='pl.col("PARAMCD") == "SYSBP"').to_frame()
        assert all(p == "SYSBP" for p in result["PARAMCD"].to_list())
        assert result.height == 2

    def test_filter_expr(self, vs_frame):
        result = vs_frame.adam.whereclauses(where=pl.col("VSSTRESN") > 100).to_frame()
        assert result.height == vs_frame.filter(pl.col("VSSTRESN") > 100).height


class TestChaining:
    def test_full_chain(self, vs_frame):
        result = (
            vs_frame.adam.source("USUBJID")
            .rename("ADT", source="vsdtc")
            .derivation("AVAL", expression="VSSTRESN")
            .assigned("STUDYID", value="CDISCPILOT01")
            .to_frame()
        )
        assert "USUBJID" in result.columns
        assert "ADT" in result.columns
        assert "AVAL" in result.columns
        assert result["STUDYID"][0] == "CDISCPILOT01"


class TestToFrame:
    def test_empty_pipeline(self, vs_frame):
        result = vs_frame.adam.to_frame()
        assert result.shape == vs_frame.shape
