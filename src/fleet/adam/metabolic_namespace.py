"""
ADaM Metabolic namespace extension (admiralmetabolic-inspired).

Accessed via ``df.adam.metabolic`` on any Polars DataFrame.

Key derivations ported from pharmaverse/admiralmetabolic:
  - ``waist_hip_ratio``    — WAISTHIP = WSTCIR / HIPCIR (per subject/visit)
  - ``waist_height_ratio`` — WAISTHGT = WSTCIR / height (same units)
  - ``body_fat_pct``       — estimated body fat % via Deurenberg formula
  - ``visceral_fat_flag``  — flag excessive waist circumference per sex

Usage
-----
    import fleet  # triggers registration

    advs = (
        vs_long_df.adam.metabolic
        .waist_hip_ratio("WAISTHIP", waist_col="WSTCIR", hip_col="HIPCIR")
        .waist_height_ratio("WAISTHGT", waist_col="WSTCIR", height_col="HEIGHT")
        .to_frame()
    )
"""

from __future__ import annotations

from typing import Self

import polars as pl

from fleet.adam._mixins import SharedADaMVerbsMixin


class MetabolicNamespace(SharedADaMVerbsMixin):
    """
    Immutable pipeline builder for ADaM metabolic / cardiometabolic derivations.

    Inherits shared verbs from ``SharedADaMVerbsMixin``.
    """

    # ------------------------------------------------------------------ #
    # 1. waist_hip_ratio — WSTCIR / HIPCIR                               #
    # ------------------------------------------------------------------ #

    def waist_hip_ratio(
        self,
        target: str,
        *,
        waist_col: str,
        hip_col: str,
        round_digits: int | None = 3,
    ) -> Self:
        """Derive waist-to-hip ratio: ``waist_col / hip_col``.

        Both columns must be in the same unit.

        Args:
            target: Name of the output column.
            waist_col: Column containing waist circumference.
            hip_col: Column containing hip circumference.
            round_digits: Decimal places to round to (default ``3``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive waist-to-hip ratio::

                advs = (
                    vs_raw.adam.metabolic
                    .waist_hip_ratio("WAISTHIP", waist_col="WSTCIR",
                                     hip_col="HIPCIR")
                    .to_frame()
                )
        """
        expr = pl.col(waist_col) / pl.col(hip_col)
        if round_digits is not None:
            expr = expr.round(round_digits)
        return self._chain(expr.alias(target))

    # ------------------------------------------------------------------ #
    # 2. waist_height_ratio — WSTCIR / height                            #
    # ------------------------------------------------------------------ #

    def waist_height_ratio(
        self,
        target: str,
        *,
        waist_col: str,
        height_col: str,
        round_digits: int | None = 3,
    ) -> Self:
        """Derive waist-to-height ratio: ``waist_col / height_col``.

        Both columns must be in the same unit.

        Args:
            target: Name of the output column.
            waist_col: Column containing waist circumference.
            height_col: Column containing height.
            round_digits: Decimal places to round to (default ``3``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive waist-to-height ratio::

                advs = (
                    vs_raw.adam.metabolic
                    .waist_height_ratio("WAISTHGT", waist_col="WSTCIR",
                                        height_col="HEIGHT")
                    .to_frame()
                )
        """
        expr = pl.col(waist_col) / pl.col(height_col)
        if round_digits is not None:
            expr = expr.round(round_digits)
        return self._chain(expr.alias(target))

    # ------------------------------------------------------------------ #
    # 3. body_fat_pct — Deurenberg equation                              #
    # ------------------------------------------------------------------ #

    def body_fat_pct(
        self,
        target: str,
        *,
        bmi_col: str,
        age_col: str,
        sex_col: str,
        sex_male_value: str = "M",
        round_digits: int | None = 1,
    ) -> Self:
        """Estimate body fat percentage using the Deurenberg formula.

        ``BF% = 1.2 × BMI + 0.23 × age − 10.8 × sex_num − 5.4``
        where sex_num = 1 (male) or 0 (female).

        Args:
            target: Name of the output column.
            bmi_col: Column containing BMI.
            age_col: Column containing age in years.
            sex_col: Column containing sex code.
            sex_male_value: Value indicating male (default ``"M"``).
            round_digits: Decimal places to round to (default ``1``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Estimate body fat percentage::

                advs = (
                    vs_raw.adam.metabolic
                    .body_fat_pct("BFPCT", bmi_col="BMI", age_col="AGE",
                                  sex_col="SEX")
                    .to_frame()
                )

        References:
            Deurenberg P, Weststrate JA, Seidell JC. Body mass index as a measure of
            body fatness: age- and sex-specific prediction formulas. Br J Nutr.
            1991;65(2):105-114. Constants 1.2, 0.23, 10.8 and 5.4 are the adult
            equation; admiralmetabolic ships the same rule.
        """
        sex_num = (
            pl.when(pl.col(sex_col) == sex_male_value).then(pl.lit(1.0)).otherwise(pl.lit(0.0))
        )
        expr = 1.2 * pl.col(bmi_col) + 0.23 * pl.col(age_col) - 10.8 * sex_num - 5.4
        if round_digits is not None:
            expr = expr.round(round_digits)
        return self._chain(expr.alias(target))

    # ------------------------------------------------------------------ #
    # 4. visceral_fat_flag — flag excessive waist circumference           #
    # ------------------------------------------------------------------ #

    def visceral_fat_flag(
        self,
        target: str,
        *,
        waist_col: str,
        sex_col: str,
        sex_male_value: str = "M",
        male_threshold: float = 102.0,
        female_threshold: float = 88.0,
        flag_value: str = "Y",
    ) -> Self:
        """Flag subjects with abdominal obesity by waist circumference.

        Default ATP III / NCEP thresholds: male ≥ 102 cm, female ≥ 88 cm.

        Args:
            target: Name of the output flag column.
            waist_col: Column containing waist circumference in cm.
            sex_col: Column containing sex code.
            sex_male_value: Value indicating male (default ``"M"``).
            male_threshold: Threshold for males (default ``102.0``).
            female_threshold: Threshold for females (default ``88.0``).
            flag_value: Value to assign (default ``"Y"``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Flag abdominal obesity::

                advs = (
                    vs_raw.adam.metabolic
                    .visceral_fat_flag("ABDFL", waist_col="WSTCIR",
                                       sex_col="SEX")
                    .to_frame()
                )

        References:
            Grundy SM et al. Diagnosis and management of the metabolic syndrome: an
            AHA/NHLBI scientific statement. Circulation. 2005;112:2735-2752: waist
            circumference >= 102 cm (men) and >= 88 cm (women). NCEP ATP III (2001)
            states the same cut-offs as strictly greater; IDF (2005) uses 94 and 80 cm
            for Europids. Check the SAP for the population.
        """
        is_male = pl.col(sex_col) == sex_male_value
        waist = pl.col(waist_col)
        return self._chain(
            pl.when(
                (is_male & (waist >= male_threshold)) | (~is_male & (waist >= female_threshold))
            )
            .then(pl.lit(flag_value))
            .otherwise(pl.lit(None))
            .alias(target)
        )
