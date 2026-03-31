"""
ADaM Pediatrics namespace extension (admiralpeds-inspired).

Accessed via ``df.adam.peds`` on any Polars DataFrame.

Key derivations ported from pharmaverse/admiralpeds and pediatric standards:
  - ``age_days``          — age in whole days between two date columns
  - ``age_months``        — age in whole calendar months
  - ``age_years``         — age in decimal years (days / 365.25)
  - ``corrected_age``     — gestational-corrected age for preterm infants
  - ``prematurity_flag``  — flag infants born before *threshold* gestational weeks
  - ``bmi_category``      — adult/paediatric BMI category label (WHO thresholds)

Note
----
Z-score and percentile derivations (``derive_params_growth_age`` /
``derive_params_growth_height``) require WHO/CDC normative lookup tables and
are not yet included as easy-win single-expression operations.

Usage
-----
    import fleet  # triggers registration

    adsl = (
        dm_sdtm.adam.peds
        .source("USUBJID")
        .age_days("AGEDAYS", birth_date="BRTHDT", analysis_date="RFSTDTC")
        .age_years("AGE", birth_date="BRTHDT", analysis_date="RFSTDTC")
        .prematurity_flag("PREMFL", gestational_weeks_col="GESTAG")
        .to_frame()
    )
"""

from __future__ import annotations

from typing import Self

import polars as pl

from fleet.adam._mixins import SharedADaMVerbsMixin


class PedsNamespace(SharedADaMVerbsMixin):
    """
    Immutable pipeline builder for paediatric ADaM derivations.

    Inherits shared verbs from ``SharedADaMVerbsMixin``.
    """

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
        expr = (
            pl.col(analysis_date).cast(pl.Date) - pl.col(birth_date).cast(pl.Date)
        ).dt.total_days().cast(pl.Int64).alias(target)
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
        """
        days = (
            pl.col(analysis_date).cast(pl.Date) - pl.col(birth_date).cast(pl.Date)
        ).dt.total_days()
        expr = (days / 30.4375).floor().cast(pl.Int64).alias(target)
        return self._chain(expr)

    # ------------------------------------------------------------------ #
    # 3. age_years — age in decimal years                                 #
    # ------------------------------------------------------------------ #

    def age_years(
        self,
        target: str,
        *,
        birth_date: str,
        analysis_date: str,
        round_digits: int | None = 2,
    ) -> Self:
        """Compute age in decimal years (days / 365.25).

        Args:
            target: Name of the output column.
            birth_date: Column containing the date of birth.
            analysis_date: Column containing the reference date.
            round_digits: Decimal places to round to (default ``2``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive age in years::

                adsl = (
                    dm_raw.adam.peds
                    .age_years("AGE", birth_date="BRTHDT",
                               analysis_date="RFSTDTC")
                    .to_frame()
                )
        """
        days = (
            pl.col(analysis_date).cast(pl.Date) - pl.col(birth_date).cast(pl.Date)
        ).dt.total_days()
        expr = days / 365.25
        if round_digits is not None:
            expr = expr.round(round_digits)
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
        No correction when gestational weeks >= *term_weeks*.

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
        """
        prematurity_years = (
            pl.when(pl.col(gestational_weeks_col) < term_weeks)
            .then((term_weeks - pl.col(gestational_weeks_col)) / 52.18)
            .otherwise(0.0)
        )
        chron_age_years = pl.col(age_days_col) / 365.25
        return self._chain(
            (chron_age_years - prematurity_years).round(4).alias(target)
        )

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
        """
        return self._chain(
            pl.when(pl.col(gestational_weeks_col) < threshold)
            .then(pl.lit(flag_value))
            .otherwise(pl.lit(None))
            .alias(target)
        )

    # ------------------------------------------------------------------ #
    # 6. bmi_category — WHO BMI category label                            #
    # ------------------------------------------------------------------ #

    def bmi_category(
        self,
        target: str,
        *,
        bmi_col: str,
        labels: dict[str, float] | None = None,
    ) -> Self:
        """Categorise BMI using WHO adult thresholds.

        Default categories: Underweight (<18.5), Normal weight (18.5–24.9),
        Overweight (25.0–29.9), Obese (≥30.0).

        Args:
            target: Name of the output column.
            bmi_col: Column containing the BMI value.
            labels: Optional ``{"label": upper_bound}`` dict to override
                default thresholds.

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Categorise BMI with WHO thresholds::

                adsl = (
                    dm_raw.adam.peds
                    .bmi_category("BMICG", bmi_col="BMI")
                    .to_frame()
                )
        """
        default_thresholds: list[tuple[str, float]] = [
            ("Underweight", 18.5),
            ("Normal weight", 25.0),
            ("Overweight", 30.0),
            ("Obese", float("inf")),
        ]

        if labels is not None:
            thresholds = [(k, v) for k, v in labels.items()]
        else:
            thresholds = default_thresholds

        bmi = pl.col(bmi_col)
        # Build the when/then chain
        if not thresholds:
            return self._chain(pl.lit(None).alias(target))

        label0, upper0 = thresholds[0]
        chain = pl.when(bmi < upper0).then(pl.lit(label0))
        for label, upper in thresholds[1:-1]:
            chain = chain.when(bmi < upper).then(pl.lit(label))
        last_label = thresholds[-1][0]
        expr = chain.otherwise(pl.lit(last_label)).alias(target)
        return self._chain(expr)

