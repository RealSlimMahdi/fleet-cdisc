"""
ADaM Pediatrics namespace extension (admiralpeds-inspired).

Accessed via ``df.adam.peds`` on any Polars DataFrame.

Key derivations, inspired by pharmaverse/admiralpeds and pediatric standards (not ports; values can differ):
  - ``age_days``          — age in whole days between two date columns
  - ``age_months``        — age in whole calendar months
  - ``age_years``         — age in completed years (or decimal years)
  - ``corrected_age``     — gestational-corrected age for preterm infants
  - ``prematurity_flag``  — flag infants born before *threshold* gestational weeks
  - ``bmi_percentile_category`` — BMI-for-age class from the CDC 2000 or WHO 2007
    reference

The adult BMI classes (WHO cut-offs) are ``metabolic.bmi_category_adult``.

Usage
-----
    import fleet  # triggers registration

    adsl = (
        dm_sdtm.adam.peds
        .source("USUBJID")
        .age_days("AGEDAYS", birth_date="BRTHDT", analysis_date="RFSTDT")
        .age_years("AAGE", birth_date="BRTHDT", analysis_date="RFSTDT")
        .prematurity_flag("PREMFL", gestational_weeks_col="GESTAG")
        .to_frame()
    )
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

import polars as pl

from fleet.adam._mixins import SharedADaMVerbsMixin
from fleet.core.dtc import to_day
from fleet.core.exceptions import VerbUsageError

_GROWTH_DIR = Path(__file__).parent / "data" / "growth"


@lru_cache(maxsize=1)
def _cdc2000_bmi() -> pl.DataFrame:
    raw = pl.read_csv(_GROWTH_DIR / "cdc2000_bmiagerev.csv", infer_schema=False)
    # The CDC file repeats its header line before the girls' rows.
    return raw.filter(pl.col("Sex") != "Sex").select(
        pl.col("Sex").cast(pl.Int64).alias("__sex__"),
        pl.col("Agemos").cast(pl.Float64).alias("__agemos__"),
        *(pl.col(p).cast(pl.Float64).alias(f"__{p}__") for p in ("P5", "P85", "P95")),
    )


@lru_cache(maxsize=1)
def _who2007_bmi() -> pl.DataFrame:
    return pl.read_csv(
        _GROWTH_DIR / "who2007_bmi_for_age.csv",
        schema={
            "Sex": pl.Int64,
            "Month": pl.Int64,
            "L": pl.Float64,
            "M": pl.Float64,
            "S": pl.Float64,
        },
    )


class PedsNamespace(SharedADaMVerbsMixin):
    """
    Immutable pipeline builder for paediatric ADaM derivations.

    Inherits shared verbs from ``SharedADaMVerbsMixin``.
    """

    def _age_in_days(self, verb: str, birth_date: str, analysis_date: str) -> pl.Expr:
        """Days from *birth_date* to *analysis_date*; ``--DTC`` text by its date, a number raises."""
        schema = self._lazy.collect_schema()
        analysis, birth = (
            to_day(pl.col(c), schema.get(c), verb=verb).cast(pl.Date)
            for c in (analysis_date, birth_date)
        )
        return (analysis - birth).dt.total_days()

    # ------------------------------------------------------------------ #
    # 1. age_days — age in whole days                                     #
    # ------------------------------------------------------------------ #

    def age_days(
        self,
        target: str,
        *,
        birth_date: str,
        analysis_date: str,
    ) -> Self:
        """Compute age in whole days.

        Args:
            target: Name of the output column.
            birth_date: Column containing the date of birth.
            analysis_date: Column containing the reference date.

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive age in days from birth and reference dates::

                adsl = (
                    dm_raw.adam.peds
                    .age_days("AGEDAYS", birth_date="BRTHDT",
                              analysis_date="RFSTDTC")
                    .to_frame()
                )
        """
        expr = self._age_in_days("age_days", birth_date, analysis_date).cast(pl.Int64).alias(target)
        return self._chain(expr)

    # ------------------------------------------------------------------ #
    # 2. age_months — age in whole calendar months                        #
    # ------------------------------------------------------------------ #

    def age_months(
        self,
        target: str,
        *,
        birth_date: str,
        analysis_date: str,
    ) -> Self:
        """Compute age in whole months (floor of days / 30.4375).

        Args:
            target: Name of the output column.
            birth_date: Column containing the date of birth.
            analysis_date: Column containing the reference date.

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive age in months::

                adsl = (
                    dm_raw.adam.peds
                    .age_months("AGEMOS", birth_date="BRTHDT",
                                analysis_date="RFSTDTC")
                    .to_frame()
                )

        References:
            admiral ``derive_vars_duration`` (pharmaverse): one month = 30.4375 days
            (365.25 / 12). A month of 30 days gives a different answer.
        """
        days = self._age_in_days("age_months", birth_date, analysis_date)
        expr = (days / 30.4375).floor().cast(pl.Int64).alias(target)
        return self._chain(expr)

    # ------------------------------------------------------------------ #
    # 3. age_years — age in completed years                               #
    # ------------------------------------------------------------------ #

    def age_years(
        self,
        target: str,
        *,
        birth_date: str,
        analysis_date: str,
        unit: Literal["years", "decimal"] = "years",
        round_digits: int | None = None,
    ) -> Self:
        """Compute age from two date columns, in completed years by default.

        Same rule as ``adsl.age_from_dates``: ``unit="years"`` gives whole
        completed years (Int64), so a child is 4 on the day before the 5th
        birthday.  A 29 February birthday is reached on 1 March in a non-leap
        year; a reference date before birth gives a negative age.
        ``unit="decimal"`` gives days / 365.25 at full precision.

        Args:
            target: Name of the output column.
            birth_date: Column containing the date of birth.
            analysis_date: Column containing the reference date.
            unit: ``"years"`` (default) or ``"decimal"``.
            round_digits: Decimal places for ``unit="decimal"``, rounded as
                SAS ``ROUND``.  Default ``None``: no rounding.

        Returns:
            Self: The namespace with *target* appended.

        Raises:
            VerbUsageError: When *round_digits* is given with
                ``unit="years"``, or *unit* is unknown.

        Examples:
            Derive age in completed years::

                adsl = (
                    dm_raw.adam.peds
                    .age_years("AAGE", birth_date="BRTHDT",
                               analysis_date="RFSTDT")
                    .to_frame()
                )

        References:
            admiral ``derive_vars_aage`` (pharmaverse) and SAS
            ``FLOOR(YRDIF(BRTHDT, RFSTDT, 'AGE'))``: completed years. ICH E11 age
            bands use completed years. Decimal: one year = 365.25 days. ADR-0025.
        """
        from fleet.adam.utils import age_between

        schema = self._lazy.collect_schema()
        reference, birth = (
            to_day(pl.col(c), schema.get(c), verb="age_years").cast(pl.Date)
            for c in (analysis_date, birth_date)
        )
        expr = age_between(birth, reference, unit=unit, round_digits=round_digits, verb="age_years")
        return self._chain(expr.alias(target))

    # ------------------------------------------------------------------ #
    # 4. corrected_age — gestational-corrected age for preterm infants    #
    # ------------------------------------------------------------------ #

    def corrected_age(
        self,
        target: str,
        *,
        age_days_col: str,
        gestational_weeks_col: str,
        term_weeks: int = 40,
    ) -> Self:
        """Compute gestational-corrected age in decimal years.

        Corrected age = chronological age − (term_weeks − gestational_weeks) / 52.18.
        No correction when gestational weeks >= *term_weeks*.  A null or NaN
        gestational age gives a null result; if the SAP assumes term birth,
        fill the column with *term_weeks* before the call.

        Args:
            target: Name of the output column.
            age_days_col: Column containing age in days.
            gestational_weeks_col: Column containing gestational age in weeks.
            term_weeks: Full-term threshold (default ``40``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive corrected age for preterm infants::

                adsl = (
                    dm_raw.adam.peds
                    .corrected_age("CORAGE", age_days_col="AGEDAYS",
                                   gestational_weeks_col="GESTAG")
                    .to_frame()
                )

        References:
            American Academy of Pediatrics, Committee on Fetus and Newborn. Age
            terminology during the perinatal period. Pediatrics. 2004;114(5):1362-1364:
            corrected age = chronological age minus the weeks born before 40 weeks.
            52.18 weeks per year = 365.25 / 7.
        """
        ga = pl.col(gestational_weeks_col).cast(pl.Float64).fill_nan(None)
        prematurity_years = pl.when(ga >= term_weeks).then(0.0).otherwise((term_weeks - ga) / 52.18)
        chron_age_years = pl.col(age_days_col) / 365.25
        return self._chain((chron_age_years - prematurity_years).round(4).alias(target))

    # ------------------------------------------------------------------ #
    # 5. prematurity_flag — flag infants born prematurely                 #
    # ------------------------------------------------------------------ #

    def prematurity_flag(
        self,
        target: str,
        *,
        gestational_weeks_col: str,
        threshold: int = 37,
        flag_value: str = "Y",
    ) -> Self:
        """Flag infants born before *threshold* gestational weeks.

        Default threshold of 37 weeks matches the clinical definition of
        prematurity.

        Args:
            target: Name of the output flag column.
            gestational_weeks_col: Column containing gestational age in weeks.
            threshold: Weeks below which prematurity is flagged (default ``37``).
            flag_value: Value to assign (default ``"Y"``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive prematurity flag::

                adsl = (
                    dm_raw.adam.peds
                    .prematurity_flag("PREMFL",
                                     gestational_weeks_col="GESTAG")
                    .to_frame()
                )

        References:
            WHO: preterm birth is birth before 37 completed weeks of gestation
            (ICD-10 P07; WHO preterm birth fact sheet).
        """
        return self._chain(
            pl.when(pl.col(gestational_weeks_col) < threshold)
            .then(pl.lit(flag_value))
            .otherwise(pl.lit(None))
            .alias(target)
        )

    # ------------------------------------------------------------------ #
    # 6. bmi_percentile_category — BMI-for-age class (CDC 2000, WHO 2007) #
    # ------------------------------------------------------------------ #

    def bmi_percentile_category(
        self,
        target: str,
        *,
        bmi_col: str,
        age_months_col: str,
        sex_col: str,
        reference: Literal["CDC2000", "WHO2007"],
        sex_male_value: str = "M",
        sex_female_value: str = "F",
    ) -> Self:
        """Classify a child's BMI by age and sex with the CDC 2000 or WHO 2007 reference.

        ``reference="CDC2000"`` (ages 24 to < 240 months) takes the table row
        of the completed month (row 60.5 for 60.0 to 60.99 months) and gives
        Underweight (< P5), Healthy weight (P5 to < P85), Overweight (P85 to
        < P95) or Obesity (>= P95).

        ``reference="WHO2007"`` (ages 61 to 228 months) interpolates L, M and
        S linearly between the two whole months around the age, as WHO
        AnthroPlus, computes the z-score ``((BMI / M) ** L - 1) / (L * S)``
        rounded to 2 decimals, and gives Severe thinness (z < -3), Thinness
        (z < -2), Normal (-2 to +1), Overweight (> +1 to +2) or Obesity
        (z > +2).

        A null, NaN or infinite BMI, a null age, an age out of the range of
        the reference, or a sex that is neither *sex_male_value* nor
        *sex_female_value* gives null.  Check the SAP for the reference and
        for the age rule (completed months or exact age).

        Args:
            target: Name of the output column.
            bmi_col: Column containing BMI in kg/m2.
            age_months_col: Column containing age in months at the
                measurement (whole or decimal months).
            sex_col: Column containing the sex code.
            reference: ``"CDC2000"`` or ``"WHO2007"``.  No default: the SAP
                names the reference.
            sex_male_value: Value indicating male (default ``"M"``).
            sex_female_value: Value indicating female (default ``"F"``).

        Returns:
            Self: The namespace with *target* appended.

        Raises:
            VerbUsageError: When *reference* is not ``"CDC2000"`` or
                ``"WHO2007"``.

        Examples:
            Classify BMI-for-age with the CDC 2000 charts::

                adsl = (
                    adsl_raw.adam.peds
                    .bmi_percentile_category("BMICG", bmi_col="BMI",
                                             age_months_col="AGEMOS",
                                             sex_col="SEX",
                                             reference="CDC2000")
                    .to_frame()
                )

        References:
            CDC NCHS, 2000 CDC growth charts, BMI-for-age LMS and percentile file
            ``bmiagerev.csv``; CDC "Child and Teen BMI Categories": < 5th, 5th to
            < 85th, 85th to < 95th, >= 95th percentile.
            WHO 2007 growth reference 5-19 years, BMI-for-age expanded LMS tables
            (de Onis M et al. Bull World Health Organ. 2007;85:660-667): thinness
            < -2 SD, severe thinness < -3 SD, overweight > +1 SD, obesity > +2 SD.
            WHO ``anthroplus`` R package: linear interpolation of L, M and S, z
            rounded to 2 decimals. Source files and SHA-256:
            ``fleet/adam/data/growth/README.md``. ADR-0026.
        """
        loaders = {"CDC2000": self._cdc2000_class, "WHO2007": self._who2007_class}
        if reference not in loaders:
            raise VerbUsageError(
                f"bmi_percentile_category: reference={reference!r} is not supported. "
                "Use 'CDC2000' or 'WHO2007'."
            )
        df = self.to_frame()
        sex_code = (
            pl.when(pl.col(sex_col) == sex_male_value)
            .then(pl.lit(1, dtype=pl.Int64))
            .when(pl.col(sex_col) == sex_female_value)
            .then(pl.lit(2, dtype=pl.Int64))
        )
        keyed = df.with_columns(
            sex_code.alias("__sex__"),
            pl.col(age_months_col).cast(pl.Float64).alias("__age__"),
            pl.col(bmi_col).cast(pl.Float64).alias("__bmi__"),
        )
        classed = loaders[reference](keyed)
        bmi_ok = pl.col("__bmi__").is_finite()
        result = classed.with_columns(
            pl.when(bmi_ok).then(pl.col("__class__")).alias(target)
        ).select(*[c for c in df.columns if c != target], target)
        return self._materialise_then(result)

    @staticmethod
    def _cdc2000_class(keyed: pl.DataFrame) -> pl.DataFrame:
        age = pl.col("__age__")
        row = pl.when((age >= 24) & (age < 240)).then(age.floor() + 0.5)
        joined = keyed.with_columns(row.alias("__agemos__")).join(
            _cdc2000_bmi(), on=["__sex__", "__agemos__"], how="left", maintain_order="left"
        )
        bmi = pl.col("__bmi__")
        return joined.with_columns(
            pl.when(pl.col("__P5__").is_null())
            .then(pl.lit(None, dtype=pl.String))
            .when(bmi < pl.col("__P5__"))
            .then(pl.lit("Underweight"))
            .when(bmi < pl.col("__P85__"))
            .then(pl.lit("Healthy weight"))
            .when(bmi < pl.col("__P95__"))
            .then(pl.lit("Overweight"))
            .otherwise(pl.lit("Obesity"))
            .alias("__class__")
        )

    @staticmethod
    def _who2007_class(keyed: pl.DataFrame) -> pl.DataFrame:
        table = _who2007_bmi()
        age = pl.col("__age__")
        low_month = pl.when((age >= 61) & (age <= 228)).then(age.floor().cast(pl.Int64))
        low = table.rename(
            {"Sex": "__sex__", "Month": "__lo__", "L": "__L0", "M": "__M0", "S": "__S0"}
        )
        high = table.rename(
            {"Sex": "__sex__", "Month": "__hi__", "L": "__L1", "M": "__M1", "S": "__S1"}
        )
        joined = (
            keyed.with_columns(low_month.alias("__lo__"))
            .with_columns((pl.col("__lo__") + 1).alias("__hi__"))
            .join(low, on=["__sex__", "__lo__"], how="left", maintain_order="left")
            .join(high, on=["__sex__", "__hi__"], how="left", maintain_order="left")
        )
        frac = age - pl.col("__lo__")

        def _interp(p: str) -> pl.Expr:
            lo, hi = pl.col(f"__{p}0"), pl.col(f"__{p}1")
            return pl.when(frac == 0).then(lo).otherwise(lo + frac * (hi - lo))

        lam, mu, sigma = _interp("L"), _interp("M"), _interp("S")
        z = (((pl.col("__bmi__") / mu).pow(lam) - 1) / (lam * sigma)).round(2)
        return joined.with_columns(
            pl.when(z.is_null())
            .then(pl.lit(None, dtype=pl.String))
            .when(z < -3)
            .then(pl.lit("Severe thinness"))
            .when(z < -2)
            .then(pl.lit("Thinness"))
            .when(z <= 1)
            .then(pl.lit("Normal"))
            .when(z <= 2)
            .then(pl.lit("Overweight"))
            .otherwise(pl.lit("Obesity"))
            .alias("__class__")
        )
