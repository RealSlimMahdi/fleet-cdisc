"""Unit tests for the Metabolic Polars namespace extension (df.adam.metabolic)."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration


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
    """Test 4: Visceral fat flag using sex-specific IDF thresholds."""

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
