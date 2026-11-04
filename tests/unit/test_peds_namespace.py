"""Unit tests for the Pediatrics Polars namespace extension (df.adam.peds)."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration
from fleet.core.exceptions import VerbUsageError


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
    """Test 3: Age in completed years (c1-138)."""

    def test_approx_two_years(self, age_frame):
        result = age_frame.adam.peds.age_years(
            "AGE", birth_date="BRTHDT", analysis_date="RFSTDTC"
        ).to_frame()
        assert result["AGE"][0] == pytest.approx(2.0, abs=0.02)

    def test_completed_years_by_default(self):
        df = pl.from_repr("""\
┌────────────┬────────────┐
│ BRTHDT     ┆ RFSTDT     │
│ ---        ┆ ---        │
│ date       ┆ date       │
╞════════════╪════════════╡
│ 2016-03-15 ┆ 2021-03-14 │
│ 2016-03-15 ┆ 2021-03-15 │
│ 2012-02-29 ┆ 2021-02-28 │
│ 2012-02-29 ┆ 2021-03-01 │
│ null       ┆ 2021-03-01 │
└────────────┴────────────┘
""")
        result = df.adam.peds.age_years(
            "AAGE", birth_date="BRTHDT", analysis_date="RFSTDT"
        ).to_frame()
        assert result["AAGE"].dtype == pl.Int64
        assert result["AAGE"].to_list() == [4, 5, 8, 9, None]

    def test_decimal_unit_keeps_full_precision(self):
        df = pl.from_repr("""\
┌────────────┬────────────┐
│ BRTHDT     ┆ RFSTDT     │
│ ---        ┆ ---        │
│ date       ┆ date       │
╞════════════╪════════════╡
│ 2016-03-15 ┆ 2021-03-14 │
└────────────┴────────────┘
""")
        result = df.adam.peds.age_years(
            "AAGE", birth_date="BRTHDT", analysis_date="RFSTDT", unit="decimal"
        ).to_frame()
        assert result["AAGE"][0] == pytest.approx(1825 / 365.25, abs=1e-12)

    def test_round_digits_with_completed_years_raises(self, age_frame):
        with pytest.raises(VerbUsageError, match="round_digits"):
            age_frame.adam.peds.age_years(
                "AAGE", birth_date="BRTHDT", analysis_date="RFSTDTC", round_digits=1
            )


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

    def test_missing_gestational_age_gives_null(self):
        """c1-159: a null or NaN GESTAG gives null, not the chronological age."""
        df = pl.from_repr("""\
┌─────────┬─────────┬────────┐
│ USUBJID ┆ AGEDAYS ┆ GESTAG │
│ ---     ┆ ---     ┆ ---    │
│ str     ┆ i64     ┆ f64    │
╞═════════╪═════════╪════════╡
│ S1      ┆ 365     ┆ null   │
│ S2      ┆ 365     ┆ 32.0   │
│ S3      ┆ 365     ┆ NaN    │
└─────────┴─────────┴────────┘
""")
        result = df.adam.peds.corrected_age(
            "CORAGE", age_days_col="AGEDAYS", gestational_weeks_col="GESTAG"
        ).to_frame()
        assert result["CORAGE"][0] is None
        assert result["CORAGE"][1] == pytest.approx(0.846, abs=1e-4)
        assert result["CORAGE"][2] is None


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


class TestBmiPercentileCategory:
    """Test 6: BMI-for-age class from the CDC 2000 and WHO 2007 references (c1-161)."""

    def test_cdc2000_uses_the_completed_month_row(self):
        # CDC bmiagerev.csv: boys 60.5 P5 13.839 P85 16.841 P95 17.93892524;
        # boys 120.5 P95 22.154; girls 60.5 P85 16.802 P95 18.257.
        df = pl.from_repr("""\
┌─────────┬──────┬────────┬─────────────┐
│ USUBJID ┆ SEX  ┆ AGEMOS ┆ BMI         │
│ ---     ┆ ---  ┆ ---    ┆ ---         │
│ str     ┆ str  ┆ f64    ┆ f64         │
╞═════════╪══════╪════════╪═════════════╡
│ P01     ┆ M    ┆ 60.0   ┆ 18.0        │
│ P02     ┆ M    ┆ 60.0   ┆ 15.0        │
│ P03     ┆ M    ┆ 120.0  ┆ 23.0        │
│ P04     ┆ F    ┆ 60.0   ┆ 17.0        │
│ P05     ┆ M    ┆ 60.9   ┆ 13.5        │
│ P06     ┆ M    ┆ 60.0   ┆ 17.93892524 │
│ P07     ┆ M    ┆ 60.0   ┆ 17.9389     │
│ P08     ┆ M    ┆ 23.9   ┆ 18.0        │
│ P09     ┆ M    ┆ 240.0  ┆ 25.0        │
│ P10     ┆ U    ┆ 60.0   ┆ 18.0        │
│ P11     ┆ M    ┆ 60.0   ┆ null        │
│ P12     ┆ M    ┆ 60.0   ┆ NaN         │
└─────────┴──────┴────────┴─────────────┘
""")
        result = df.adam.peds.bmi_percentile_category(
            "BMICG", bmi_col="BMI", age_months_col="AGEMOS", sex_col="SEX", reference="CDC2000"
        ).to_frame()
        assert result["USUBJID"].to_list() == df["USUBJID"].to_list()
        assert result["BMICG"].to_list() == [
            "Obesity",
            "Healthy weight",
            "Obesity",
            "Overweight",
            "Underweight",
            "Obesity",
            "Overweight",
            None,
            None,
            None,
            None,
            None,
        ]

    def test_who2007_classes_by_z_score(self):
        # WHO 2007 expanded tables, boys 120 months: SD3neg 12.775, SD2neg 13.735,
        # SD1 18.48, SD2 21.4; girls 150 months: SD2 25.596; boys 228: SD0 22.188.
        df = pl.from_repr("""\
┌─────────┬─────┬────────┬──────┐
│ USUBJID ┆ SEX ┆ AGEMOS ┆ BMI  │
│ ---     ┆ --- ┆ ---    ┆ ---  │
│ str     ┆ str ┆ f64    ┆ f64  │
╞═════════╪═════╪════════╪══════╡
│ W01     ┆ M   ┆ 120.0  ┆ 12.5 │
│ W02     ┆ M   ┆ 120.0  ┆ 13.5 │
│ W03     ┆ M   ┆ 120.0  ┆ 16.4 │
│ W04     ┆ M   ┆ 120.0  ┆ 20.0 │
│ W05     ┆ M   ┆ 120.0  ┆ 22.0 │
│ W06     ┆ F   ┆ 150.0  ┆ 26.0 │
│ W07     ┆ M   ┆ 228.0  ┆ 22.2 │
│ W08     ┆ M   ┆ 228.5  ┆ 22.2 │
│ W09     ┆ M   ┆ 60.0   ┆ 15.3 │
└─────────┴─────┴────────┴──────┘
""")
        result = df.adam.peds.bmi_percentile_category(
            "BMICG", bmi_col="BMI", age_months_col="AGEMOS", sex_col="SEX", reference="WHO2007"
        ).to_frame()
        assert result["BMICG"].to_list() == [
            "Severe thinness",
            "Thinness",
            "Normal",
            "Overweight",
            "Obesity",
            "Obesity",
            "Normal",
            None,
            None,
        ]

    def test_who2007_interpolates_between_months_and_rounds_z(self):
        # Boys LMS 120: (-1.7407, 16.4433, 0.10566); 121: (-1.7468, 16.4807, 0.10609).
        # At 120.5 the mean LMS puts z = +2 at BMI 21.4415. At 120, BMI 21.41 is
        # z = 2.0028, which WHO AnthroPlus rounds to 2.00 (not above +2).
        df = pl.from_repr("""\
┌─────┬────────┬───────┐
│ SEX ┆ AGEMOS ┆ BMI   │
│ --- ┆ ---    ┆ ---   │
│ str ┆ f64    ┆ f64   │
╞═════╪════════╪═══════╡
│ M   ┆ 120.5  ┆ 21.43 │
│ M   ┆ 120.5  ┆ 21.47 │
│ M   ┆ 120.0  ┆ 21.41 │
└─────┴────────┴───────┘
""")
        result = df.adam.peds.bmi_percentile_category(
            "BMICG", bmi_col="BMI", age_months_col="AGEMOS", sex_col="SEX", reference="WHO2007"
        ).to_frame()
        assert result["BMICG"].to_list() == ["Overweight", "Obesity", "Overweight"]

    def test_reference_is_required_and_checked(self):
        df = pl.from_repr("""\
┌─────┬────────┬──────┐
│ SEX ┆ AGEMOS ┆ BMI  │
│ --- ┆ ---    ┆ ---  │
│ str ┆ f64    ┆ f64  │
╞═════╪════════╪══════╡
│ M   ┆ 60.0   ┆ 18.0 │
└─────┴────────┴──────┘
""")
        with pytest.raises(TypeError, match="reference"):
            df.adam.peds.bmi_percentile_category(
                "BMICG", bmi_col="BMI", age_months_col="AGEMOS", sex_col="SEX"
            )
        with pytest.raises(VerbUsageError, match="CDC2000"):
            df.adam.peds.bmi_percentile_category(
                "BMICG", bmi_col="BMI", age_months_col="AGEMOS", sex_col="SEX", reference="IOTF"
            )

    def test_adult_verb_is_gone_from_peds(self):
        df = pl.from_repr("""\
┌──────┐
│ BMI  │
│ ---  │
│ f64  │
╞══════╡
│ 18.0 │
└──────┘
""")
        assert not hasattr(df.adam.peds, "bmi_category")
