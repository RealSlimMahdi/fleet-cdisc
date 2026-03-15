"""
ADaM Pediatrics Polars namespace extension (admiralpeds-inspired).

Registers ``df.peds`` on every Polars DataFrame.

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
        dm_sdtm.peds
        .source("USUBJID")
        .age_days("AGEDAYS", birth_date="BRTHDT", analysis_date="RFSTDTC")
        .age_years("AGE", birth_date="BRTHDT", analysis_date="RFSTDTC")
        .prematurity_flag("PREMFL", gestational_weeks_col="GESTAG")
        .to_frame()
    )
"""

from __future__ import annotations

from typing import Any

import polars as pl


@pl.api.register_dataframe_namespace("peds")
class PedsNamespace:
    """
    Immutable pipeline builder for paediatric ADaM derivations.

    Follows the same immutable-builder pattern as ``AdamNamespace``.
    """

    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df
        self._pipeline: list[pl.Expr] = []

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _chain(self, *exprs: pl.Expr) -> "PedsNamespace":
        new = object.__new__(PedsNamespace)
        new._df = self._df
        new._pipeline = self._pipeline + list(exprs)
        return new

    def _materialise_then(self, df: pl.DataFrame) -> "PedsNamespace":
        new = object.__new__(PedsNamespace)
        new._df = df
        new._pipeline = []
        return new

    # ------------------------------------------------------------------ #
    # Base verbs                                                           #
    # ------------------------------------------------------------------ #

    def source(self, target: str, *, from_col: str | None = None) -> "PedsNamespace":
        """Copy *from_col* (or *target* itself) to *target*."""
        src = from_col if from_col is not None else target
        return self._chain(pl.col(src).alias(target))

    def assigned(self, target: str, *, value: Any) -> "PedsNamespace":
        """Set *target* to a constant *value* for every record."""
        return self._chain(pl.lit(value).alias(target))

    def derivation(
        self, target: str, *, expression: str | pl.Expr
    ) -> "PedsNamespace":
        """Arbitrary Polars expression derivation."""
        from ..sdtm.utils import parse_expression
        expr = (
            expression
            if isinstance(expression, pl.Expr)
            else parse_expression(str(expression))
        )
        return self._chain(expr.alias(target))

    def whereclauses(self, *, where: str | pl.Expr) -> "PedsNamespace":
        """Filter the dataset to records matching *where*."""
        from ..sdtm.utils import parse_expression
        df = self.to_frame()
        fexpr = where if isinstance(where, pl.Expr) else parse_expression(str(where))
        return self._materialise_then(df.filter(fexpr))

    # ------------------------------------------------------------------ #
    # 1. age_days — age in whole days                                     #
    # ------------------------------------------------------------------ #

    def age_days(
        self,
        target: str,
        *,
        birth_date: str,
        analysis_date: str,
    ) -> "PedsNamespace":
        """
        Compute age in whole days as ``analysis_date - birth_date``.

        Both columns are cast to ``pl.Date`` before subtraction.

        Example::

            .age_days("AGEDAYS", birth_date="BRTHDT", analysis_date="RFSTDTC")
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
    ) -> "PedsNamespace":
        """
        Compute age in whole months (floor of days / 30.4375).

        Example::

            .age_months("AGEMOS", birth_date="BRTHDT", analysis_date="RFSTDTC")
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
    ) -> "PedsNamespace":
        """
        Compute age in decimal years (days / 365.25).

        Example::

            .age_years("AGE", birth_date="BRTHDT", analysis_date="RFSTDTC")
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
    ) -> "PedsNamespace":
        """
        Compute gestational-corrected age in decimal years for preterm infants.

        Corrected age = chronological age − prematurity correction
        where correction = (term_weeks − gestational_weeks) / 52.18 years.

        If gestational weeks ≥ *term_weeks*, no correction is applied
        (correction is zero).

        Example::

            .corrected_age("CORAGE", age_days_col="AGEDAYS",
                           gestational_weeks_col="GESTAG")
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
    ) -> "PedsNamespace":
        """
        Set *target* to *flag_value* when gestational weeks < *threshold*.

        The default threshold of 37 weeks matches the standard clinical definition
        of prematurity.

        Example::

            .prematurity_flag("PREMFL", gestational_weeks_col="GESTAG")
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
    ) -> "PedsNamespace":
        """
        Categorise BMI using WHO adult thresholds (or a custom *labels* dict).

        Default thresholds (WHO adult):

        ============  =================
        BMI range     Category
        ============  =================
        < 18.5        Underweight
        18.5 – 24.9   Normal weight
        25.0 – 29.9   Overweight
        ≥ 30.0        Obese
        ============  =================

        *labels*: optional ``{"label": upper_bound, ...}`` ordered dict that
        overrides the defaults.  The last category has no upper bound.

        .. note::
            For age- and sex-specific paediatric BMI categories based on WHO/CDC
            growth charts, use a lookup join with the reference tables.

        Example::

            .bmi_category("BMICG", bmi_col="BMI")
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

    # ------------------------------------------------------------------ #
    # Materialise                                                          #
    # ------------------------------------------------------------------ #

    def to_frame(self) -> pl.DataFrame:
        """Materialise the pipeline and return a ``pl.DataFrame``."""
        if not self._pipeline:
            return self._df
        return self._df.with_columns(self._pipeline)
