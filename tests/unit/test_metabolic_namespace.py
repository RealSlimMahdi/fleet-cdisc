"""Unit tests for the Metabolic Polars namespace extension (df.adam.metabolic)."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration
from fleet.core.exceptions import DerivationError


@pytest.fixture
def metab_frame():
    """Minimal frame for shared verb tests on the metabolic namespace."""
    return pl.from_repr("""\
┌─────────┬────────┬─────┐
│ USUBJID ┆ WSTCIR ┆ SEX │
│ ---     ┆ ---    ┆ --- │
│ str     ┆ f64    ┆ str │
╞═════════╪════════╪═════╡
│ 01-001  ┆ 90.0   ┆ F   │
│ 01-002  ┆ 110.0  ┆ M   │
└─────────┴────────┴─────┘
""")


class TestBaseVerbs:
    """Shared verbs inherited from SharedADaMVerbsMixin."""

    def test_source(self, metab_frame):
        result = metab_frame.adam.metabolic.source("USUBJID").to_frame()
        assert "USUBJID" in result.columns

    def test_assigned(self, metab_frame):
        result = metab_frame.adam.metabolic.assign("STUDYID", value="MET01").to_frame()
        assert result["STUDYID"].to_list() == ["MET01"] * 2

    def test_derivation(self, metab_frame):
        result = metab_frame.adam.metabolic.derivation(
            "WCIR_CM", expression='pl.col("WSTCIR") / 10'
        ).to_frame()
        assert result["WCIR_CM"].to_list() == [9.0, 11.0]

    def test_recode(self, metab_frame):
        result = metab_frame.adam.metabolic.recode(
            "SEXN", source="SEX", recode_map={"F": "1", "M": "2"}
        ).to_frame()
        assert result["SEXN"].to_list() == ["1", "2"]

    def test_rename(self, metab_frame):
        result = metab_frame.adam.metabolic.assign("SUBJ", source="USUBJID").to_frame()
        assert result["SUBJ"].to_list() == metab_frame["USUBJID"].to_list()

    def test_condderivation(self, metab_frame):
        result = metab_frame.adam.metabolic.case_when(
            "WSTCAT",
            when=[{"condition": 'pl.col("WSTCIR") > 100', "value": "HIGH"}],
            else_="NORMAL",
        ).to_frame()
        assert result["WSTCAT"].to_list() == ["NORMAL", "HIGH"]

    def test_whereclauses(self, metab_frame):
        result = metab_frame.adam.metabolic.whereclauses(where='pl.col("SEX") == "F"').to_frame()
        assert result.height == 1


class TestWaistHipRatio:
    """Test 1: Waist-to-hip ratio."""

    def test_basic_ratio(self):
        df = pl.from_repr("""\
┌────────┬────────┐
│ WSTCIR ┆ HIPCIR │
│ ---    ┆ ---    │
│ f64    ┆ f64    │
╞════════╪════════╡
│ 90.0   ┆ 100.0  │
└────────┴────────┘
""")
        result = df.adam.metabolic.waist_hip_ratio(
            "WAISTHIP", waist_col="WSTCIR", hip_col="HIPCIR"
        ).to_frame()
        assert result["WAISTHIP"][0] == pytest.approx(0.9)

    def test_multiple_rows(self):
        df = pl.from_repr("""\
┌────────┬────────┐
│ WSTCIR ┆ HIPCIR │
│ ---    ┆ ---    │
│ f64    ┆ f64    │
╞════════╪════════╡
│ 110.0  ┆ 125.0  │
│ 120.0  ┆ 135.0  │
└────────┴────────┘
""")
        result = df.adam.metabolic.waist_hip_ratio(
            "WAISTHIP", waist_col="WSTCIR", hip_col="HIPCIR"
        ).to_frame()
        assert result["WAISTHIP"][0] == pytest.approx(0.88, abs=0.001)
        assert result["WAISTHIP"][1] == pytest.approx(0.889, abs=0.001)

    def test_non_derived_columns_preserved(self):
        df = pl.from_repr("""\
┌─────────────┬────────┬────────┐
│ USUBJID     ┆ WSTCIR ┆ HIPCIR │
│ ---         ┆ ---    ┆ ---    │
│ str         ┆ f64    ┆ f64    │
╞═════════════╪════════╪════════╡
│ 01-701-1015 ┆ 90.0   ┆ 100.0  │
└─────────────┴────────┴────────┘
""")
        result = df.adam.metabolic.waist_hip_ratio(
            "WAISTHIP", waist_col="WSTCIR", hip_col="HIPCIR"
        ).to_frame()
        assert "USUBJID" in result.columns


class TestWaistHeightRatio:
    """Test 2: Waist-to-height ratio."""

    def test_ratio_computation(self):
        df = pl.from_repr("""\
┌────────┬────────┐
│ WSTCIR ┆ HEIGHT │
│ ---    ┆ ---    │
│ f64    ┆ f64    │
╞════════╪════════╡
│ 88.0   ┆ 170.0  │
└────────┴────────┘
""")
        result = df.adam.metabolic.waist_height_ratio(
            "WAISTHGT", waist_col="WSTCIR", height_col="HEIGHT"
        ).to_frame()
        assert result["WAISTHGT"][0] == pytest.approx(88.0 / 170.0, abs=0.001)


class TestBodyFatPct:
    """Test 3: Deurenberg (1991) body-fat percentage formula."""

    def test_male_40yo_bmi25(self):
        # BF% = 1.2*25 + 0.23*40 - 10.8*1 - 5.4 = 30 + 9.2 - 10.8 - 5.4 = 23.0
        df = pl.from_repr("""\
┌──────┬──────┬─────┐
│ BMI  ┆ AGE  ┆ SEX │
│ ---  ┆ ---  ┆ --- │
│ f64  ┆ f64  ┆ str │
╞══════╪══════╪═════╡
│ 25.0 ┆ 40.0 ┆ M   │
└──────┴──────┴─────┘
""")
        result = df.adam.metabolic.body_fat_pct(
            "BFPCT", bmi_col="BMI", age_col="AGE", sex_col="SEX"
        ).to_frame()
        assert result["BFPCT"][0] == pytest.approx(23.0, abs=0.1)

    def test_female_40yo_bmi25(self):
        # BF% = 1.2*25 + 0.23*40 - 10.8*0 - 5.4 = 30 + 9.2 - 0 - 5.4 = 33.8
        df = pl.from_repr("""\
┌──────┬──────┬─────┐
│ BMI  ┆ AGE  ┆ SEX │
│ ---  ┆ ---  ┆ --- │
│ f64  ┆ f64  ┆ str │
╞══════╪══════╪═════╡
│ 25.0 ┆ 40.0 ┆ F   │
└──────┴──────┴─────┘
""")
        result = df.adam.metabolic.body_fat_pct(
            "BFPCT", bmi_col="BMI", age_col="AGE", sex_col="SEX"
        ).to_frame()
        assert result["BFPCT"][0] == pytest.approx(33.8, abs=0.1)

    def test_null_bmi_gives_null(self):
        """Null BMI input must propagate as null — not an error."""
        df = pl.from_repr("""\
┌──────┬──────┬─────┐
│ BMI  ┆ AGE  ┆ SEX │
│ ---  ┆ ---  ┆ --- │
│ null ┆ f64  ┆ str │
╞══════╪══════╪═════╡
│ null ┆ 40.0 ┆ M   │
└──────┴──────┴─────┘
""")
        result = df.adam.metabolic.body_fat_pct(
            "BFPCT", bmi_col="BMI", age_col="AGE", sex_col="SEX"
        ).to_frame()
        assert result["BFPCT"][0] is None

    def test_custom_sex_encoding(self):
        """Non-default male value — e.g., '1' instead of 'M'."""
        df = pl.from_repr("""\
┌──────┬──────┬─────┐
│ BMI  ┆ AGE  ┆ SEX │
│ ---  ┆ ---  ┆ --- │
│ f64  ┆ f64  ┆ str │
╞══════╪══════╪═════╡
│ 25.0 ┆ 40.0 ┆ 1   │
└──────┴──────┴─────┘
""")
        result_custom = df.adam.metabolic.body_fat_pct(
            "BFPCT", bmi_col="BMI", age_col="AGE", sex_col="SEX", sex_male_value="1"
        ).to_frame()
        # Same formula as for 'M' → 23.0
        assert result_custom["BFPCT"][0] == pytest.approx(23.0, abs=0.1)


class TestVisceralFatFlag:
    """Test 4: Visceral fat flag using the sex-specific ATP III / NCEP thresholds."""

    def test_male_above_threshold_flagged(self):
        df = pl.from_repr("""\
┌────────┬─────┐
│ WSTCIR ┆ SEX │
│ ---    ┆ --- │
│ f64    ┆ str │
╞════════╪═════╡
│ 103.0  ┆ M   │
│ 100.0  ┆ M   │
│ 95.0   ┆ M   │
└────────┴─────┘
""")
        result = df.adam.metabolic.visceral_fat_flag(
            "ABDFL", waist_col="WSTCIR", sex_col="SEX"
        ).to_frame()
        assert result["ABDFL"].to_list() == ["Y", None, None]

    def test_female_above_threshold_flagged(self):
        df = pl.from_repr("""\
┌────────┬─────┐
│ WSTCIR ┆ SEX │
│ ---    ┆ --- │
│ f64    ┆ str │
╞════════╪═════╡
│ 89.0   ┆ F   │
│ 88.0   ┆ F   │
│ 80.0   ┆ F   │
└────────┴─────┘
""")
        result = df.adam.metabolic.visceral_fat_flag(
            "ABDFL", waist_col="WSTCIR", sex_col="SEX"
        ).to_frame()
        assert result["ABDFL"].to_list() == ["Y", "Y", None]

    def test_exactly_at_male_threshold_flagged(self):
        """Exactly at 102.0 cm (male threshold) → flagged (inclusive >=)."""
        df = pl.from_repr("""\
┌────────┬─────┐
│ WSTCIR ┆ SEX │
│ ---    ┆ --- │
│ f64    ┆ str │
╞════════╪═════╡
│ 102.0  ┆ M   │
└────────┴─────┘
""")
        result = df.adam.metabolic.visceral_fat_flag(
            "ABDFL", waist_col="WSTCIR", sex_col="SEX"
        ).to_frame()
        assert result["ABDFL"][0] == "Y"

    def test_mixed_sex_multi_subject(self):
        """Multi-subject frame with mixed sexes — each row uses correct threshold."""
        df = pl.from_repr("""\
┌────────────┬─────────┬────────┬─────┐
│ STUDYID    ┆ USUBJID ┆ WSTCIR ┆ SEX │
│ ---        ┆ ---     ┆ ---    ┆ --- │
│ str        ┆ str     ┆ f64    ┆ str │
╞════════════╪═════════╪════════╪═════╡
│ METABSTUDY ┆ 01-001  ┆ 103.0  ┆ M   │
│ METABSTUDY ┆ 01-002  ┆ 89.0   ┆ F   │
│ METABSTUDY ┆ 01-003  ┆ 95.0   ┆ M   │
│ METABSTUDY ┆ 01-004  ┆ 80.0   ┆ F   │
└────────────┴─────────┴────────┴─────┘
""")
        result = df.adam.metabolic.visceral_fat_flag(
            "ABDFL", waist_col="WSTCIR", sex_col="SEX"
        ).to_frame()
        flags = dict(zip(result["USUBJID"].to_list(), result["ABDFL"].to_list()))
        assert flags["01-001"] == "Y"  # male 103 > 102
        assert flags["01-002"] == "Y"  # female 89 > 88
        assert flags["01-003"] is None  # male 95 ≤ 102
        assert flags["01-004"] is None  # female 80 ≤ 88


class TestChaining:
    """Test 5: Multi-verb chaining."""

    def test_chain_waist_ratios(self):
        df = pl.from_repr("""\
┌────────┬────────┬────────┐
│ WSTCIR ┆ HIPCIR ┆ HEIGHT │
│ ---    ┆ ---    ┆ ---    │
│ f64    ┆ f64    ┆ f64    │
╞════════╪════════╪════════╡
│ 90.0   ┆ 100.0  ┆ 170.0  │
└────────┴────────┴────────┘
""")
        result = (
            df.adam.metabolic.waist_hip_ratio("WAISTHIP", waist_col="WSTCIR", hip_col="HIPCIR")
            .waist_height_ratio("WAISTHGT", waist_col="WSTCIR", height_col="HEIGHT")
            .to_frame()
        )
        assert "WAISTHIP" in result.columns
        assert "WAISTHGT" in result.columns


# WHO TRS 894 adult classes; exactly AT a cut-off goes to the upper class.
_BMI_ADULT_CASES = [
    (17.0, "Underweight"),
    (18.4, "Underweight"),
    (18.5, "Normal weight"),
    (24.9, "Normal weight"),
    (25.0, "Overweight"),
    (29.9, "Overweight"),
    (30.0, "Obese"),
    (40.0, "Obese"),
]


class TestBmiCategoryAdult:
    """c1-161: the adult rule moved from peds; c1-158: no class for a missing BMI."""

    @pytest.mark.parametrize(("bmi", "expected"), _BMI_ADULT_CASES)
    def test_boundaries(self, bmi, expected):
        df = pl.DataFrame({"BMI": [bmi]})
        result = df.adam.metabolic.bmi_category_adult("BMICG", bmi_col="BMI").to_frame()
        assert result["BMICG"][0] == expected

    def test_null_nan_and_inf_get_no_class(self):
        df = pl.from_repr("""\
┌─────────┬──────┐
│ USUBJID ┆ BMI  │
│ ---     ┆ ---  │
│ str     ┆ f64  │
╞═════════╪══════╡
│ S1      ┆ 20.8 │
│ S2      ┆ null │
│ S3      ┆ NaN  │
│ S4      ┆ inf  │
└─────────┴──────┘
""")
        result = df.adam.metabolic.bmi_category_adult("BMICG", bmi_col="BMI").to_frame()
        assert result["BMICG"].to_list() == ["Normal weight", None, None, None]

    def test_custom_labels_give_null_at_or_above_the_last_bound(self):
        df = pl.from_repr("""\
┌──────┐
│ BMI  │
│ ---  │
│ f64  │
╞══════╡
│ 17.0 │
│ 22.0 │
│ 35.0 │
│ null │
└──────┘
""")
        result = df.adam.metabolic.bmi_category_adult(
            "BMICG", bmi_col="BMI", labels={"Low": 18.5, "High": 30.0}
        ).to_frame()
        assert result["BMICG"].to_list() == ["Low", "High", None, None]

    def test_custom_labels_that_do_not_ascend_raise(self):
        """c1-162: a descending dict would give wrong classes."""
        df = pl.from_repr("""\
┌──────┐
│ BMI  │
│ ---  │
│ f64  │
╞══════╡
│ 17.0 │
└──────┘
""")
        with pytest.raises(DerivationError, match="do not strictly ascend"):
            df.adam.metabolic.bmi_category_adult(
                "BMICG", bmi_col="BMI", labels={"Obese": float("inf"), "Normal": 25.0}
            )

    def test_all_null_column_keeps_string(self):
        df = pl.DataFrame({"BMI": [None, None]}, schema={"BMI": pl.Float64})
        result = df.adam.metabolic.bmi_category_adult("BMICG", bmi_col="BMI").to_frame()
        assert result["BMICG"].dtype == pl.String


class TestSexOtherThanMaleOrFemale:
    """c1-160, c1-706: U, UNDIFFERENTIATED and null have no Deurenberg or ATP III value."""

    FRAME = """\
┌─────────┬──────────────────┬──────┬──────┬────────┐
│ USUBJID ┆ SEX              ┆ BMI  ┆ AGE  ┆ WSTCIR │
│ ---     ┆ ---              ┆ ---  ┆ ---  ┆ ---    │
│ str     ┆ str              ┆ f64  ┆ f64  ┆ f64    │
╞═════════╪══════════════════╪══════╪══════╪════════╡
│ 01      ┆ M                ┆ 25.0 ┆ 40.0 ┆ 95.0   │
│ 02      ┆ F                ┆ 25.0 ┆ 40.0 ┆ 95.0   │
│ 03      ┆ U                ┆ 25.0 ┆ 40.0 ┆ 95.0   │
│ 04      ┆ UNDIFFERENTIATED ┆ 25.0 ┆ 40.0 ┆ 95.0   │
│ 05      ┆ null             ┆ 25.0 ┆ 40.0 ┆ 95.0   │
└─────────┴──────────────────┴──────┴──────┴────────┘
"""

    def test_body_fat_pct(self):
        df = pl.from_repr(self.FRAME)
        result = df.adam.metabolic.body_fat_pct(
            "BFPCT", bmi_col="BMI", age_col="AGE", sex_col="SEX"
        ).to_frame()
        assert result["BFPCT"].to_list() == [23.0, 33.8, None, None, None]

    def test_body_fat_pct_with_numeric_sex_codes(self):
        df = pl.from_repr(self.FRAME).with_columns(pl.col("SEX").replace({"M": "1", "F": "2"}))
        result = df.adam.metabolic.body_fat_pct(
            "BFPCT",
            bmi_col="BMI",
            age_col="AGE",
            sex_col="SEX",
            sex_male_value="1",
            sex_female_value="2",
        ).to_frame()
        assert result["BFPCT"].to_list() == [23.0, 33.8, None, None, None]

    def test_visceral_fat_flag(self):
        df = pl.from_repr(self.FRAME)
        result = df.adam.metabolic.visceral_fat_flag(
            "ABDFL", waist_col="WSTCIR", sex_col="SEX"
        ).to_frame()
        assert result["ABDFL"].to_list() == [None, "Y", None, None, None]


def test_ratio_verbs_give_null_for_a_zero_denominator():
    """c1-84: SAS gives a missing value for x / 0, not inf or NaN."""
    df = pl.from_repr("""\
┌────────┬────────┬────────┐
│ WSTCIR ┆ HIPCIR ┆ HEIGHT │
│ ---    ┆ ---    ┆ ---    │
│ f64    ┆ f64    ┆ f64    │
╞════════╪════════╪════════╡
│ 90.0   ┆ 0.0    ┆ 0.0    │
│ 0.0    ┆ 0.0    ┆ 0.0    │
│ 90.0   ┆ 100.0  ┆ 180.0  │
└────────┴────────┴────────┘
""")
    result = (
        df.adam.metabolic.waist_hip_ratio("WAISTHIP", waist_col="WSTCIR", hip_col="HIPCIR")
        .waist_height_ratio("WAISTHGT", waist_col="WSTCIR", height_col="HEIGHT")
        .to_frame()
    )
    assert result["WAISTHIP"].to_list() == [None, None, 0.9]
    assert result["WAISTHGT"].to_list() == [None, None, 0.5]
