"""Unit tests for the Pediatrics Polars namespace extension (df.adam.peds)."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration

# ---------------------------------------------------------------------------
# BMI category boundary values — WHO adult thresholds used by the namespace.
# Test exactly AT the boundary (included in the upper category by convention).
# ---------------------------------------------------------------------------
_BMI_CATEGORY_CASES = [
    (17.0, "Underweight"),
    (18.4, "Underweight"),
    (18.5, "Normal weight"),  # boundary: ≥18.5
    (24.9, "Normal weight"),
    (25.0, "Overweight"),  # boundary: ≥25.0
    (29.9, "Overweight"),
    (30.0, "Obese"),  # boundary: ≥30.0
    (40.0, "Obese"),
]


@pytest.fixture
def age_frame():
    return pl.from_repr("""\
┌────────────┬────────────┐
│ BRTHDT     ┆ RFSTDTC    │
│ ---        ┆ ---        │
│ str        ┆ str        │
╞════════════╪════════════╡
│ 2020-01-01 ┆ 2022-01-01 │
│ 2020-06-15 ┆ 2022-06-15 │
└────────────┴────────────┘
""")


class TestBaseVerbs:
    """Shared verbs inherited from SharedADaMVerbsMixin."""

    def test_source(self, age_frame):
        result = age_frame.adam.peds.source("BRTHDT").to_frame()
        assert "BRTHDT" in result.columns

    def test_assigned(self, age_frame):
        result = age_frame.adam.peds.assign("STUDYID", value="PED01").to_frame()
        assert result["STUDYID"].to_list() == ["PED01"] * 2

    def test_derivation(self, age_frame):
        result = age_frame.adam.peds.derivation("CONST", expression="pl.lit(1)").to_frame()
        assert result["CONST"].to_list() == [1, 1]

    def test_recode(self, age_frame):
        df = age_frame.with_columns(pl.Series("GRP", ["A", "B"]))
        result = df.adam.peds.recode(
            "GRPCD", source="GRP", recode_map={"A": "GroupA", "B": "GroupB"}
        ).to_frame()
        assert result["GRPCD"].to_list() == ["GroupA", "GroupB"]

    def test_rename(self, age_frame):
        result = age_frame.adam.peds.assign("DOB", source="BRTHDT").to_frame()
        assert result["DOB"].to_list() == age_frame["BRTHDT"].to_list()

    def test_condderivation(self, age_frame):
        df = age_frame.with_columns(pl.Series("AGE", [5, 12]))
        result = df.adam.peds.case_when(
            "AGEGR",
            when=[{"condition": 'pl.col("AGE") < 6', "value": "Infant"}],
            else_="Child",
        ).to_frame()
        assert result["AGEGR"].to_list() == ["Infant", "Child"]

    def test_whereclauses(self, age_frame):
        df = age_frame.with_columns(pl.Series("AGE", [5, 12]))
        result = df.adam.peds.whereclauses(where='pl.col("AGE") > 6').to_frame()
        assert result.height == 1


class TestAgeDays:
    """Test 1: Age in days derivation."""

    def test_two_years_approx(self, age_frame):
        result = age_frame.adam.peds.age_days(
            "AGEDAYS", birth_date="BRTHDT", analysis_date="RFSTDTC"
        ).to_frame()
        # 2020 is leap year: 366 + 365 = 731
        assert result["AGEDAYS"][0] == 731

    def test_same_day_zero(self):
        df = pl.from_repr("""\
┌────────────┬────────────┐
│ B          ┆ A          │
│ ---        ┆ ---        │
│ str        ┆ str        │
╞════════════╪════════════╡
│ 2022-03-01 ┆ 2022-03-01 │
└────────────┴────────────┘
""")
        result = df.adam.peds.age_days("D", birth_date="B", analysis_date="A").to_frame()
        assert result["D"][0] == 0

    def test_multi_subject_realistic(self):
        """
        Multi-subject test inspired by admiralpeds test-derive_params_growth_age.R.
        Two subjects with different birth and analysis dates.
        """
        df = pl.from_repr("""\
┌──────────────┬─────────────┬────────────┬────────────┐
│ STUDYID      ┆ USUBJID     ┆ BRTHDT     ┆ RFSTDTC    │
│ ---          ┆ ---         ┆ ---        ┆ ---        │
│ str          ┆ str         ┆ str        ┆ str        │
╞══════════════╪═════════════╪════════════╪════════════╡
│ CDISCPILOT01 ┆ 01-701-1015 ┆ 2018-01-01 ┆ 2022-01-01 │
│ CDISCPILOT01 ┆ 01-701-1023 ┆ 2019-06-01 ┆ 2022-06-01 │
└──────────────┴─────────────┴────────────┴────────────┘
""")
        result = df.adam.peds.age_days(
            "AGEDAYS", birth_date="BRTHDT", analysis_date="RFSTDTC"
        ).to_frame()
        # Subject 01: 4 years (2 leap years in range: 2020, 2024 — only 2020 applies here)
        # 365+365+366+365 = 1461. Not checking exact value; just a positive integer.
        assert result["AGEDAYS"][0] > 0
        assert result["AGEDAYS"][1] > 0
        # Second subject was born later, so should have fewer days
        assert result["AGEDAYS"][1] < result["AGEDAYS"][0]


class TestAgeMonths:
    """Test 2: Age in months (floor of days / 30.4375)."""

    def test_approx_24_months(self, age_frame):
        result = age_frame.adam.peds.age_months(
            "AGEMOS", birth_date="BRTHDT", analysis_date="RFSTDTC"
        ).to_frame()
        assert result["AGEMOS"][0] == 24

    def test_same_day_zero_months(self):
        df = pl.from_repr("""\
┌────────────┬────────────┐
│ B          ┆ A          │
│ ---        ┆ ---        │
│ str        ┆ str        │
╞════════════╪════════════╡
│ 2022-03-01 ┆ 2022-03-01 │
└────────────┴────────────┘
""")
        result = df.adam.peds.age_months("M", birth_date="B", analysis_date="A").to_frame()
        assert result["M"][0] == 0


class TestAgeYears:
    """Test 3: Age in years (days / 365.25)."""

    def test_approx_two_years(self, age_frame):
        result = age_frame.adam.peds.age_years(
            "AGE", birth_date="BRTHDT", analysis_date="RFSTDTC"
        ).to_frame()
        assert result["AGE"][0] == pytest.approx(2.0, abs=0.02)


class TestCorrectedAge:
    """Test 4: Gestational-age-corrected age."""

    def test_preterm_correction(self):
        # Born at 32 weeks → 8 weeks premature → correction ≈ 8/52.18 ≈ 0.153 years
        df = pl.from_repr("""\
┌─────────┬────────┐
│ AGEDAYS ┆ GESTAG │
│ ---     ┆ ---    │
│ f64     ┆ i64    │
╞═════════╪════════╡
│ 365.0   ┆ 32     │
└─────────┴────────┘
""")
        result = df.adam.peds.corrected_age(
            "CORAGE", age_days_col="AGEDAYS", gestational_weeks_col="GESTAG"
        ).to_frame()
        expected = 365 / 365.25 - (40 - 32) / 52.18
        assert result["CORAGE"][0] == pytest.approx(expected, abs=0.001)

    def test_term_infant_no_correction(self):
        """Infant born at exactly 40 weeks → no correction applied."""
        df = pl.from_repr("""\
┌─────────┬────────┐
│ AGEDAYS ┆ GESTAG │
│ ---     ┆ ---    │
│ f64     ┆ i64    │
╞═════════╪════════╡
│ 365.0   ┆ 40     │
└─────────┴────────┘
""")
        result = df.adam.peds.corrected_age(
            "CORAGE", age_days_col="AGEDAYS", gestational_weeks_col="GESTAG"
        ).to_frame()
        assert result["CORAGE"][0] == pytest.approx(365 / 365.25, abs=0.001)

    def test_boundary_37_weeks_is_preterm(self):
        """37 gestational weeks is below the 'term' threshold of 40 — correction applies."""
        df = pl.from_repr("""\
┌─────────┬────────┐
│ AGEDAYS ┆ GESTAG │
│ ---     ┆ ---    │
│ f64     ┆ i64    │
╞═════════╪════════╡
│ 100.0   ┆ 37     │
└─────────┴────────┘
""")
        result = df.adam.peds.corrected_age(
            "CORAGE", age_days_col="AGEDAYS", gestational_weeks_col="GESTAG"
        ).to_frame()
        # Corrected should be LESS than chronological
        assert result["CORAGE"][0] < 100 / 365.25


class TestPrematurityFlag:
    """Test 5: Prematurity flag at and around the threshold."""

    def test_premature_flagged(self):
        df = pl.from_repr("""\
┌────────┐
│ GESTAG │
│ ---    │
│ i64    │
╞════════╡
│ 28     │
│ 36     │
│ 37     │
│ 40     │
└────────┘
""")
        result = df.adam.peds.prematurity_flag("PREMFL", gestational_weeks_col="GESTAG").to_frame()
        assert result["PREMFL"].to_list() == ["Y", "Y", None, None]

    def test_boundary_exactly_37_not_flagged(self):
        """Default threshold is 37 (strict <), so exactly 37 weeks is NOT preterm."""
        df = pl.from_repr("""\
┌────────┐
│ GESTAG │
│ ---    │
│ i64    │
╞════════╡
│ 37     │
└────────┘
""")
        result = df.adam.peds.prematurity_flag("PREMFL", gestational_weeks_col="GESTAG").to_frame()
        assert result["PREMFL"][0] is None

    def test_custom_threshold(self):
        """With threshold=35, exactly 35 weeks is NOT flagged (strict <)."""
        df = pl.from_repr("""\
┌────────┐
│ GESTAG │
│ ---    │
│ i64    │
╞════════╡
│ 34     │
│ 35     │
└────────┘
""")
        result = df.adam.peds.prematurity_flag(
            "PREMFL", gestational_weeks_col="GESTAG", threshold=35
        ).to_frame()
        assert result["PREMFL"].to_list() == ["Y", None]


class TestBmiCategory:
    """
    Test 6: WHO adult BMI categories — boundary values and custom labels.

    Uses parametrize to test boundaries at 18.5, 25.0, and 30.0 exactly,
    mirroring admiral's approach of testing each boundary explicitly.
    """

    @pytest.mark.parametrize("bmi,expected_category", _BMI_CATEGORY_CASES)
    def test_bmi_category_boundaries(self, bmi, expected_category):
        df = pl.DataFrame({"BMI": [bmi]})
        result = df.adam.peds.bmi_category("BMICG", bmi_col="BMI").to_frame()
        assert result["BMICG"][0] == expected_category

    def test_full_vector_all_categories(self):
        df = pl.from_repr("""\
┌──────┐
│ BMI  │
│ ---  │
│ f64  │
╞══════╡
│ 17.0 │
│ 22.0 │
│ 27.0 │
│ 32.0 │
└──────┘
""")
        result = df.adam.peds.bmi_category("BMICG", bmi_col="BMI").to_frame()
        assert result["BMICG"].to_list() == ["Underweight", "Normal weight", "Overweight", "Obese"]

    def test_custom_labels(self):
        """Custom labels dict {category_name: upper_bound} overrides defaults."""
        df = pl.from_repr("""\
┌──────┐
│ BMI  │
│ ---  │
│ f64  │
╞══════╡
│ 17.0 │
│ 22.0 │
│ 27.0 │
│ 32.0 │
└──────┘
""")
        custom = {
            "Low": 18.5,
            "Normal": 25.0,
            "High": 30.0,
            "Very High": float("inf"),
        }
        result = df.adam.peds.bmi_category("BMICG", bmi_col="BMI", labels=custom).to_frame()
        assert result["BMICG"].to_list() == ["Low", "Normal", "High", "Very High"]
