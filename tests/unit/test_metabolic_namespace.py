"""Unit tests for the Metabolic Polars namespace extension (df.metabolic)."""

import polars as pl
import pytest

import pymaverse  # noqa: F401 — triggers namespace registration


class TestWaistHipRatio:
    def test_basic_ratio(self):
        df = pl.DataFrame({"WSTCIR": [90.0], "HIPCIR": [100.0]})
        result = df.metabolic.waist_hip_ratio(
            "WAISTHIP", waist_col="WSTCIR", hip_col="HIPCIR"
        ).to_frame()
        assert result["WAISTHIP"][0] == pytest.approx(0.9)

    def test_multiple_rows(self):
        df = pl.DataFrame({
            "WSTCIR": [110.0, 120.0],
            "HIPCIR": [125.0, 135.0],
        })
        result = df.metabolic.waist_hip_ratio(
            "WAISTHIP", waist_col="WSTCIR", hip_col="HIPCIR"
        ).to_frame()
        assert result["WAISTHIP"][0] == pytest.approx(0.88, abs=0.001)
        assert result["WAISTHIP"][1] == pytest.approx(0.889, abs=0.001)


class TestWaistHeightRatio:
    def test_ratio_computation(self):
        df = pl.DataFrame({"WSTCIR": [88.0], "HEIGHT": [170.0]})
        result = df.metabolic.waist_height_ratio(
            "WAISTHGT", waist_col="WSTCIR", height_col="HEIGHT"
        ).to_frame()
        assert result["WAISTHGT"][0] == pytest.approx(88.0 / 170.0, abs=0.001)


class TestBodyFatPct:
    def test_male_40yo_bmi25(self):
        # BF% = 1.2*25 + 0.23*40 - 10.8*1 - 5.4 = 30 + 9.2 - 10.8 - 5.4 = 23.0
        df = pl.DataFrame({"BMI": [25.0], "AGE": [40.0], "SEX": ["M"]})
        result = df.metabolic.body_fat_pct(
            "BFPCT", bmi_col="BMI", age_col="AGE", sex_col="SEX"
        ).to_frame()
        assert result["BFPCT"][0] == pytest.approx(23.0, abs=0.1)

    def test_female_40yo_bmi25(self):
        # BF% = 1.2*25 + 0.23*40 - 10.8*0 - 5.4 = 30 + 9.2 - 0 - 5.4 = 33.8
        df = pl.DataFrame({"BMI": [25.0], "AGE": [40.0], "SEX": ["F"]})
        result = df.metabolic.body_fat_pct(
            "BFPCT", bmi_col="BMI", age_col="AGE", sex_col="SEX"
        ).to_frame()
        assert result["BFPCT"][0] == pytest.approx(33.8, abs=0.1)


class TestVisceralFatFlag:
    def test_male_above_threshold_flagged(self):
        df = pl.DataFrame({
            "WSTCIR": [103.0, 100.0, 95.0],
            "SEX":    ["M",   "M",   "M"],
        })
        result = df.metabolic.visceral_fat_flag(
            "ABDFL", waist_col="WSTCIR", sex_col="SEX"
        ).to_frame()
        assert result["ABDFL"].to_list() == ["Y", None, None]

    def test_female_above_threshold_flagged(self):
        df = pl.DataFrame({
            "WSTCIR": [89.0, 88.0, 80.0],
            "SEX":    ["F",  "F",  "F"],
        })
        result = df.metabolic.visceral_fat_flag(
            "ABDFL", waist_col="WSTCIR", sex_col="SEX"
        ).to_frame()
        assert result["ABDFL"].to_list() == ["Y", "Y", None]


class TestChaining:
    def test_chain_waist_ratios(self):
        df = pl.DataFrame({
            "WSTCIR": [90.0],
            "HIPCIR": [100.0],
            "HEIGHT": [170.0],
        })
        result = (
            df.metabolic
            .waist_hip_ratio("WAISTHIP", waist_col="WSTCIR", hip_col="HIPCIR")
            .waist_height_ratio("WAISTHGT", waist_col="WSTCIR", height_col="HEIGHT")
            .to_frame()
        )
        assert "WAISTHIP" in result.columns
        assert "WAISTHGT" in result.columns
