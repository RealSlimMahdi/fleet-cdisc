"""Unit tests for the Pediatrics Polars namespace extension (df.peds)."""

import polars as pl
import pytest

import pymaverse  # noqa: F401 — triggers namespace registration


@pytest.fixture
def age_frame():
    return pl.DataFrame({
        "BRTHDT": ["2020-01-01", "2020-06-15"],
        "RFSTDTC": ["2022-01-01", "2022-06-15"],
    })


class TestAgeDays:
    def test_two_years_approx(self, age_frame):
        result = age_frame.peds.age_days(
            "AGEDAYS", birth_date="BRTHDT", analysis_date="RFSTDTC"
        ).to_frame()
        # 2020 is leap year: 366 + 365 = 731
        assert result["AGEDAYS"][0] == 731

    def test_same_day_zero(self):
        df = pl.DataFrame({"B": ["2022-03-01"], "A": ["2022-03-01"]})
        result = df.peds.age_days("D", birth_date="B", analysis_date="A").to_frame()
        assert result["D"][0] == 0


class TestAgeMonths:
    def test_approx_24_months(self, age_frame):
        result = age_frame.peds.age_months(
            "AGEMOS", birth_date="BRTHDT", analysis_date="RFSTDTC"
        ).to_frame()
        assert result["AGEMOS"][0] == 24


class TestAgeYears:
    def test_approx_two_years(self, age_frame):
        result = age_frame.peds.age_years(
            "AGE", birth_date="BRTHDT", analysis_date="RFSTDTC"
        ).to_frame()
        assert result["AGE"][0] == pytest.approx(2.0, abs=0.02)


class TestCorrectedAge:
    def test_preterm_correction(self):
        # Born at 32 weeks → 8 weeks premature → correction ≈ 8/52.18 ≈ 0.153 years
        df = pl.DataFrame({
            "AGEDAYS": [365.0],      # 1 year chronological
            "GESTAG":  [32],         # 32 gestational weeks
        })
        result = df.peds.corrected_age(
            "CORAGE", age_days_col="AGEDAYS", gestational_weeks_col="GESTAG"
        ).to_frame()
        expected = 365 / 365.25 - (40 - 32) / 52.18
        assert result["CORAGE"][0] == pytest.approx(expected, abs=0.001)

    def test_term_infant_no_correction(self):
        df = pl.DataFrame({
            "AGEDAYS": [365.0],
            "GESTAG":  [40],
        })
        result = df.peds.corrected_age(
            "CORAGE", age_days_col="AGEDAYS", gestational_weeks_col="GESTAG"
        ).to_frame()
        assert result["CORAGE"][0] == pytest.approx(365 / 365.25, abs=0.001)


class TestPrematurityFlag:
    def test_premature_flagged(self):
        df = pl.DataFrame({"GESTAG": [28, 36, 37, 40]})
        result = df.peds.prematurity_flag(
            "PREMFL", gestational_weeks_col="GESTAG"
        ).to_frame()
        assert result["PREMFL"].to_list() == ["Y", "Y", None, None]

    def test_custom_threshold(self):
        df = pl.DataFrame({"GESTAG": [34, 35]})
        result = df.peds.prematurity_flag(
            "PREMFL", gestational_weeks_col="GESTAG", threshold=35
        ).to_frame()
        assert result["PREMFL"].to_list() == ["Y", None]


class TestBmiCategory:
    def test_who_adult_categories(self):
        df = pl.DataFrame({"BMI": [17.0, 22.0, 27.0, 32.0]})
        result = df.peds.bmi_category("BMICG", bmi_col="BMI").to_frame()
        assert result["BMICG"].to_list() == [
            "Underweight", "Normal weight", "Overweight", "Obese"
        ]

    def test_boundary_normal_weight(self):
        df = pl.DataFrame({"BMI": [18.5]})
        result = df.peds.bmi_category("BMICG", bmi_col="BMI").to_frame()
        assert result["BMICG"][0] == "Normal weight"
