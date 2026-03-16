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

from typing import Any, Self

import polars as pl

from ._mixins import SharedADaMVerbsMixin


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
        """
        Derive waist-to-hip ratio: ``WAISTHIP = waist_col / hip_col``.

        Mirrors ``admiralmetabolic::derive_param_waisthip``.

        Both columns must be in the **same unit** (cm, in, etc.).
        No automatic unit conversion is performed.

        Example::

            .waist_hip_ratio("WAISTHIP", waist_col="WSTCIR", hip_col="HIPCIR")
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
        """
        Derive waist-to-height ratio: ``WAISTHGT = waist_col / height_col``.

        Mirrors ``admiralmetabolic::derive_param_waisthgt``.

        Both columns must be in the **same unit**.

        Example::

            .waist_height_ratio("WAISTHGT", waist_col="WSTCIR",
                                 height_col="HEIGHT")
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
        """
        Estimate body fat percentage using the Deurenberg formula (1991).

        Formula:

            BF% = 1.2 × BMI + 0.23 × age − 10.8 × sex_num − 5.4

        where ``sex_num`` = 1 for male, 0 for female.

        Reference:
            Deurenberg P. et al., *Br J Nutr* 1991;65(2):105-14.

        Example::

            .body_fat_pct("BFPCT", bmi_col="BMI", age_col="AGE",
                          sex_col="SEX", sex_male_value="M")
        """
        sex_num = (
            pl.when(pl.col(sex_col) == sex_male_value)
            .then(pl.lit(1.0))
            .otherwise(pl.lit(0.0))
        )
        expr = (
            1.2 * pl.col(bmi_col)
            + 0.23 * pl.col(age_col)
            - 10.8 * sex_num
            - 5.4
        )
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
        """
        Flag subjects with abdominal obesity based on IDF/WHO waist circumference
        thresholds (values expected in **centimetres**).

        Default thresholds (ATP III / NCEP):
        - Male:   ≥ 102 cm
        - Female: ≥  88 cm

        Example::

            .visceral_fat_flag("ABDFL", waist_col="WSTCIR", sex_col="SEX")
        """
        is_male = pl.col(sex_col) == sex_male_value
        waist = pl.col(waist_col)
        return self._chain(
            pl.when(
                (is_male & (waist >= male_threshold))
                | (~is_male & (waist >= female_threshold))
            )
            .then(pl.lit(flag_value))
            .otherwise(pl.lit(None))
            .alias(target)
        )

