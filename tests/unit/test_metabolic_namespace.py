"""Unit tests for the Metabolic Polars namespace extension (df.adam.metabolic)."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration


@pytest.fixture
def metab_frame():
    """Minimal frame for shared verb tests on the metabolic namespace."""
    return pl.DataFrame({
        "USUBJID": ["01-001", "01-002"],
        "WSTCIR":  [90.0, 110.0],
        "SEX":     ["F", "M"],
    })


class TestBaseVerbs:
    """Shared verbs inherited from SharedADaMVerbsMixin."""

    def test_source(self, metab_frame):
        result = metab_frame.adam.metabolic.source("USUBJID").to_frame()
        assert "USUBJID" in result.columns

    def test_assigned(self, metab_frame):
        result = metab_frame.adam.metabolic.assigned("STUDYID", value="MET01").to_frame()
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
        result = metab_frame.adam.metabolic.rename("SUBJ", source="USUBJID").to_frame()
        assert result["SUBJ"].to_list() == metab_frame["USUBJID"].to_list()

    def test_condderivation(self, metab_frame):
        result = metab_frame.adam.metabolic.condderivation(
            "WSTCAT",
            conditions=[{"condition": 'pl.col("WSTCIR") > 100', "value": "HIGH"}],
            else_value="NORMAL",
        ).to_frame()
        assert result["WSTCAT"].to_list() == ["NORMAL", "HIGH"]

    def test_whereclauses(self, metab_frame):
        result = metab_frame.adam.metabolic.whereclauses(
            where='pl.col("SEX") == "F"'
        ).to_frame()
        assert result.height == 1


class TestWaistHipRatio:
    """Test 1: Waist-to-hip ratio."""

    def test_basic_ratio(self):
        df = pl.DataFrame({"WSTCIR": [90.0], "HIPCIR": [100.0]})
        result = df.adam.metabolic.waist_hip_ratio(
            "WAISTHIP", waist_col="WSTCIR", hip_col="HIPCIR"
        ).to_frame()
        assert result["WAISTHIP"][0] == pytest.approx(0.9)

    def test_multiple_rows(self):
        df = pl.DataFrame({
            "WSTCIR": [110.0, 120.0],
            "HIPCIR": [125.0, 135.0],
        })
        result = df.adam.metabolic.waist_hip_ratio(
            "WAISTHIP", waist_col="WSTCIR", hip_col="HIPCIR"
        ).to_frame()
        assert result["WAISTHIP"][0] == pytest.approx(0.88, abs=0.001)
        assert result["WAISTHIP"][1] == pytest.approx(0.889, abs=0.001)

    def test_non_derived_columns_preserved(self):
        df = pl.DataFrame({
            "USUBJID": ["01-701-1015"],
            "WSTCIR":  [90.0],
            "HIPCIR":  [100.0],
        })
        result = df.adam.metabolic.waist_hip_ratio(
            "WAISTHIP", waist_col="WSTCIR", hip_col="HIPCIR"
        ).to_frame()
        assert "USUBJID" in result.columns


class TestWaistHeightRatio:
    """Test 2: Waist-to-height ratio."""

    def test_ratio_computation(self):
        df = pl.DataFrame({"WSTCIR": [88.0], "HEIGHT": [170.0]})
        result = df.adam.metabolic.waist_height_ratio(
            "WAISTHGT", waist_col="WSTCIR", height_col="HEIGHT"
        ).to_frame()
        assert result["WAISTHGT"][0] == pytest.approx(88.0 / 170.0, abs=0.001)


class TestBodyFatPct:
    """Test 3: Deurenberg (1991) body-fat percentage formula."""

    def test_male_40yo_bmi25(self):
        # BF% = 1.2*25 + 0.23*40 - 10.8*1 - 5.4 = 30 + 9.2 - 10.8 - 5.4 = 23.0
        df = pl.DataFrame({"BMI": [25.0], "AGE": [40.0], "SEX": ["M"]})
        result = df.adam.metabolic.body_fat_pct(
            "BFPCT", bmi_col="BMI", age_col="AGE", sex_col="SEX"
        ).to_frame()
        assert result["BFPCT"][0] == pytest.approx(23.0, abs=0.1)

    def test_female_40yo_bmi25(self):
        # BF% = 1.2*25 + 0.23*40 - 10.8*0 - 5.4 = 30 + 9.2 - 0 - 5.4 = 33.8
        df = pl.DataFrame({"BMI": [25.0], "AGE": [40.0], "SEX": ["F"]})
        result = df.adam.metabolic.body_fat_pct(
            "BFPCT", bmi_col="BMI", age_col="AGE", sex_col="SEX"
        ).to_frame()
        assert result["BFPCT"][0] == pytest.approx(33.8, abs=0.1)

    def test_null_bmi_gives_null(self):
        """Null BMI input must propagate as null — not an error."""
        df = pl.DataFrame({"BMI": [None], "AGE": [40.0], "SEX": ["M"]})
        result = df.adam.metabolic.body_fat_pct(
            "BFPCT", bmi_col="BMI", age_col="AGE", sex_col="SEX"
        ).to_frame()
        assert result["BFPCT"][0] is None

    def test_custom_sex_encoding(self):
        """Non-default male value — e.g., '1' instead of 'M'."""
        df = pl.DataFrame({"BMI": [25.0], "AGE": [40.0], "SEX": ["1"]})
        result_custom = df.adam.metabolic.body_fat_pct(
            "BFPCT", bmi_col="BMI", age_col="AGE", sex_col="SEX",
            sex_male_value="1"
        ).to_frame()
        # Same formula as for 'M' → 23.0
        assert result_custom["BFPCT"][0] == pytest.approx(23.0, abs=0.1)


class TestVisceralFatFlag:
    """Test 4: Visceral fat flag using sex-specific IDF thresholds."""

    def test_male_above_threshold_flagged(self):
        df = pl.DataFrame({
            "WSTCIR": [103.0, 100.0, 95.0],
            "SEX":    ["M",   "M",   "M"],
        })
        result = df.adam.metabolic.visceral_fat_flag(
            "ABDFL", waist_col="WSTCIR", sex_col="SEX"
        ).to_frame()
        assert result["ABDFL"].to_list() == ["Y", None, None]

    def test_female_above_threshold_flagged(self):
        df = pl.DataFrame({
            "WSTCIR": [89.0, 88.0, 80.0],
            "SEX":    ["F",  "F",  "F"],
        })
        result = df.adam.metabolic.visceral_fat_flag(
            "ABDFL", waist_col="WSTCIR", sex_col="SEX"
        ).to_frame()
        assert result["ABDFL"].to_list() == ["Y", "Y", None]

    def test_exactly_at_male_threshold_flagged(self):
        """Exactly at 102.0 cm (male threshold) → flagged (inclusive >=)."""
        df = pl.DataFrame({"WSTCIR": [102.0], "SEX": ["M"]})
        result = df.adam.metabolic.visceral_fat_flag(
            "ABDFL", waist_col="WSTCIR", sex_col="SEX"
        ).to_frame()
        assert result["ABDFL"][0] == "Y"

    def test_mixed_sex_multi_subject(self):
        """Multi-subject frame with mixed sexes — each row uses correct threshold."""
        df = pl.DataFrame({
            "STUDYID": ["METABSTUDY"] * 4,
            "USUBJID": ["01-001", "01-002", "01-003", "01-004"],
            "WSTCIR":  [103.0,    89.0,     95.0,     80.0  ],
            "SEX":     ["M",      "F",      "M",      "F"   ],
        })
        result = df.adam.metabolic.visceral_fat_flag(
            "ABDFL", waist_col="WSTCIR", sex_col="SEX"
        ).to_frame()
        flags = dict(zip(result["USUBJID"].to_list(), result["ABDFL"].to_list()))
        assert flags["01-001"] == "Y"   # male 103 > 102
        assert flags["01-002"] == "Y"   # female 89 > 88
        assert flags["01-003"] is None  # male 95 ≤ 102
        assert flags["01-004"] is None  # female 80 ≤ 88


class TestChaining:
    """Test 5: Multi-verb chaining."""

    def test_chain_waist_ratios(self):
        df = pl.DataFrame({
            "WSTCIR": [90.0],
            "HIPCIR": [100.0],
            "HEIGHT": [170.0],
        })
        result = (
            df.adam.metabolic
            .waist_hip_ratio("WAISTHIP", waist_col="WSTCIR", hip_col="HIPCIR")
            .waist_height_ratio("WAISTHGT", waist_col="WSTCIR", height_col="HEIGHT")
            .to_frame()
        )
        assert "WAISTHIP" in result.columns
        assert "WAISTHGT" in result.columns
