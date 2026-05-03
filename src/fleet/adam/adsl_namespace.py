"""
ADaM ADSL namespace extension (one-row-per-subject datasets).

Accessed via ``df.adam.adsl`` on any Polars DataFrame.

Usage
-----
    import fleet  # triggers registration

    adsl = (
        dm_sdtm.adam.adsl
        .source("USUBJID")
        .assigned("STUDYID", value="MYSTUDY01")
        .first_date("AESTDTM", from_dataset=ae_sdtm, date_col="AESTDTC",
                    where='pl.col("AESER") == "Y"')
        .duration("TRTDURD", start_date="TRTSDT", end_date="TRTEDT")
        .count_events("NUMAE",  from_dataset=ae_sdtm)
        .flag("SAFFL",   criteria='pl.col("RANDFL") == "Y"')
        .flag("PPROTFL", criteria='pl.col("COMPLFL") == "Y"')
        .to_frame()
    )
"""

from __future__ import annotations

from typing import Any, Self

import polars as pl

from fleet.adam._mixins import SharedADaMVerbsMixin


class ADSLNamespace(SharedADaMVerbsMixin):
    """
    Immutable pipeline builder for ADSL (one-row-per-subject) derivations.

    Inherits shared verbs from ``SharedADaMVerbsMixin``
    (source, derivation, assigned, recode, rename, condderivation,
    whereclauses) and adds ADSL-specific verbs that pull summary
    statistics from event-level datasets (AE, CM, MH, EX…).
    """

    # ------------------------------------------------------------------ #
    # ADSL-specific verbs                                                  #
    # ------------------------------------------------------------------ #

    def first_date(
        self,
        target: str,
        *,
        from_dataset: pl.DataFrame,
        date_col: str,
        where: str | pl.Expr | None = None,
        groups: list[str] | None = None,
    ) -> Self:
        """Derive *target* as the earliest date in *date_col* from *from_dataset*.

        Materialises the current pipeline, aggregates *from_dataset* to
        subject level, then left-joins.  Useful for ASTDTM, TRTSDT, etc.

        Args:
            target: Name of the output date column.
            from_dataset: Source ``pl.DataFrame`` to aggregate.
            date_col: Date column to take the minimum of.
            where: Optional filter applied to *from_dataset* before aggregation.
            groups: Join key columns (default ``["USUBJID"]``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive earliest serious AE start date::

                adsl = (
                    dm_raw.adam.adsl
                    .first_date("AESTDTM", from_dataset=ae_sdtm,
                                date_col="AESTDTC",
                                where='pl.col("AESER") == "Y"')
                    .to_frame()
                )
        """
        return self._date_agg(
            target,
            from_dataset=from_dataset,
            date_col=date_col,
            where=where,
            groups=groups,
            agg_fn="min",
        )

    def last_date(
        self,
        target: str,
        *,
        from_dataset: pl.DataFrame,
        date_col: str,
        where: str | pl.Expr | None = None,
        groups: list[str] | None = None,
    ) -> Self:
        """Derive *target* as the latest date in *date_col* from *from_dataset*.

        Useful for AENDTM, TRTEDT, DTHDT, etc.

        Args:
            target: Name of the output date column.
            from_dataset: Source ``pl.DataFrame`` to aggregate.
            date_col: Date column to take the maximum of.
            where: Optional filter applied to *from_dataset* before aggregation.
            groups: Join key columns (default ``["USUBJID"]``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive latest treatment end date::

                adsl = (
                    dm_raw.adam.adsl
                    .last_date("TRTEDT", from_dataset=ex_sdtm,
                               date_col="EXENDTC")
                    .to_frame()
                )
        """
        return self._date_agg(
            target,
            from_dataset=from_dataset,
            date_col=date_col,
            where=where,
            groups=groups,
            agg_fn="max",
        )

    def _date_agg(
        self,
        target: str,
        *,
        from_dataset: pl.DataFrame,
        date_col: str,
        where: str | pl.Expr | None,
        groups: list[str] | None,
        agg_fn: str,
    ) -> Self:
        """Shared implementation for first_date/last_date."""
        from fleet.sdtm.utils import parse_expression

        grps = groups or ["USUBJID"]
        src = from_dataset
        if where is not None:
            where_expr = where if isinstance(where, pl.Expr) else parse_expression(str(where))
            src = src.filter(where_expr)
        col = pl.col(date_col)
        agg_expr = (col.min() if agg_fn == "min" else col.max()).alias(target)
        agg_df = src.group_by(grps).agg(agg_expr)
        df = self.to_frame().join(agg_df, on=grps, how="left")
        return self._materialise_then(df)

    def count_events(
        self,
        target: str,
        *,
        from_dataset: pl.DataFrame,
        where: str | pl.Expr | None = None,
        groups: list[str] | None = None,
    ) -> Self:
        """Derive *target* as the count of matching records in *from_dataset*.

        Returns 0 for subjects with no matching records (never null).

        Args:
            target: Name of the output count column.
            from_dataset: Source ``pl.DataFrame`` to count.
            where: Optional filter applied before counting.
            groups: Join key columns (default ``["USUBJID"]``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Count total AE records per subject::

                adsl = (
                    dm_raw.adam.adsl
                    .count_events("NUMAE", from_dataset=ae_sdtm)
                    .to_frame()
                )
        """
        from fleet.sdtm.utils import parse_expression

        grps = groups or ["USUBJID"]
        src = from_dataset
        if where is not None:
            where_expr = where if isinstance(where, pl.Expr) else parse_expression(str(where))
            src = src.filter(where_expr)
        agg_df = src.group_by(grps).agg(pl.len().alias(target))
        df = self.to_frame().join(agg_df, on=grps, how="left")
        df = df.with_columns(pl.col(target).fill_null(0))
        return self._materialise_then(df)

    # ------------------------------------------------------------------ #
    # ADSL: age_years — unit-aware age conversion                         #
    # ------------------------------------------------------------------ #

    def age_years(
        self,
        target: str = "AAGE",
        *,
        age_col: str = "AGE",
        age_unit_col: str = "AGEU",
    ) -> Self:
        """Convert age to years, handling common unit strings.

        Recognises *AGEU* values: ``YEARS``, ``MONTHS``, ``WEEKS``, ``DAYS``
        (case-insensitive).  Unknown units produce null.

        Args:
            target: Name of the output column (default ``"AAGE"``).
            age_col: Source age column.
            age_unit_col: Column containing the age unit string.

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive age in years from DM variables::

                adsl = (
                    dm_raw.adam.adsl
                    .age_years("AAGE", age_col="AGE", age_unit_col="AGEU")
                    .to_frame()
                )
        """
        from fleet.adam.utils import age_in_years as _age_in_years_expr

        return self._chain(
            _age_in_years_expr(age_col=age_col, age_unit_col=age_unit_col, target=target)
        )

    # ------------------------------------------------------------------ #
    # ADSL: age_from_dates — date-based age calculation                   #
    # ------------------------------------------------------------------ #

    def age_from_dates(
        self,
        target: str = "AAGE",
        *,
        birth_date: str = "BRTHDT",
        reference_date: str = "TRTSDT",
        round_digits: int | None = 1,
    ) -> Self:
        """Compute age in years from two date columns.

        Uses ``(reference_date - birth_date) / 365.25`` for a more precise
        calculation than unit-conversion from ``AGE``.  Null when either
        date is missing.

        Args:
            target: Name of the output column (default ``"AAGE"``).
            birth_date: Date-of-birth column (``pl.Date``).
            reference_date: Reference date column (``pl.Date``).
            round_digits: Decimal places to round to (default ``1``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive age from birth and randomisation dates::

                adsl = (
                    dm_raw.adam.adsl
                    .age_from_dates("AAGE", birth_date="BRTHDT",
                                    reference_date="RANDDT")
                    .to_frame()
                )
        """
        days = (
            pl.col(reference_date).cast(pl.Date) - pl.col(birth_date).cast(pl.Date)
        ).dt.total_days()
        expr = days / 365.25
        if round_digits is not None:
            expr = expr.round(round_digits)
        return self._chain(expr.alias(target))

    # ------------------------------------------------------------------ #
    # ADSL: derive_period — Subperiod / Phase variables                   #
    # ------------------------------------------------------------------ #

    def derive_period(
        self,
        *,
        periods: list[dict[str, Any]],
        start_date: str = "TRTSDT",
    ) -> Self:
        """Create standard Subperiod / Phase variables.

        Generates ``AP{nn}SDT``, ``AP{nn}EDT``, and optionally
        ``TRT{nn:02d}P`` columns for each period.

        Args:
            periods: List of dicts each with ``"number"``, ``"start"``,
                ``"end"``, and optionally ``"treatment"``.
            start_date: Reference start date column (default ``"TRTSDT"``).

        Returns:
            Self: The namespace with period columns appended.

        Examples:
            Define two treatment periods::

                adsl = (
                    dm_raw.adam.adsl
                    .derive_period(
                        periods=[
                            {"number": 1, "start": "AP01SDT",
                             "end": "AP01EDT", "treatment": "TRT01P"},
                            {"number": 2, "start": "AP02SDT",
                             "end": "AP02EDT", "treatment": "TRT02P"},
                        ],
                    )
                    .to_frame()
                )
        """
        exprs: list[pl.Expr] = []
        for period in periods:
            n = period["number"]
            prefix = f"AP{n:02d}"
            sdt_col = period["start"]
            edt_col = period["end"]

            exprs.append(pl.col(sdt_col).alias(f"{prefix}SDT"))
            exprs.append(pl.col(edt_col).alias(f"{prefix}EDT"))

            trt = period.get("treatment")
            if trt is not None:
                trt_target = f"TRT{n:02d}P"
                if trt in self._lazy.collect_schema().names():
                    exprs.append(pl.col(trt).alias(trt_target))
                else:
                    exprs.append(pl.lit(trt).alias(trt_target))

        return self._chain(*exprs)
