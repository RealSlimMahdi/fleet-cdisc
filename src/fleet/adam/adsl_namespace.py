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
        .eligibility_flag("SAFFL",   criteria='pl.col("RANDFL") == "Y"')
        .eligibility_flag("PPROTFL", criteria='pl.col("COMPLFL") == "Y"')
        .to_frame()
    )
"""

from __future__ import annotations

from typing import Any, Self

import polars as pl

from ._mixins import SharedADaMVerbsMixin


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
        """
        Derive *target* as the earliest date in *date_col* from *from_dataset*.

        Materialises the current pipeline, aggregates *from_dataset* to
        subject level, then left-joins. Useful for ASTDTM, TRTSDT, etc.

        Example::

            .first_date("AESTDTM", from_dataset=ae_sdtm, date_col="AESTDTC",
                         where='pl.col("AESER") == "Y"')
        """
        from ..sdtm.utils import parse_expression

        grps = groups or ["USUBJID"]
        src = from_dataset
        if where is not None:
            where_expr = where if isinstance(where, pl.Expr) else parse_expression(str(where))
            src = src.filter(where_expr)
        agg_df = src.group_by(grps).agg(pl.col(date_col).min().alias(target))
        df = self.to_frame().join(agg_df, on=grps, how="left")
        return self._materialise_then(df)

    def last_date(
        self,
        target: str,
        *,
        from_dataset: pl.DataFrame,
        date_col: str,
        where: str | pl.Expr | None = None,
        groups: list[str] | None = None,
    ) -> Self:
        """
        Derive *target* as the latest date in *date_col* from *from_dataset*.

        Useful for AENDTM, TRTEDT, DTHDT, etc.

        Example::

            .last_date("TRTEDT", from_dataset=ex_sdtm, date_col="EXENDTC")
        """
        from ..sdtm.utils import parse_expression

        grps = groups or ["USUBJID"]
        src = from_dataset
        if where is not None:
            where_expr = where if isinstance(where, pl.Expr) else parse_expression(str(where))
            src = src.filter(where_expr)
        agg_df = src.group_by(grps).agg(pl.col(date_col).max().alias(target))
        df = self.to_frame().join(agg_df, on=grps, how="left")
        return self._materialise_then(df)

    def duration(
        self,
        target: str,
        *,
        start_date: str,
        end_date: str,
        unit: str = "days",
        inclusive: bool = True,
    ) -> Self:
        """
        Derive *target* as the duration between two date columns.

        *unit*: ``"days"`` (default; only unit currently supported).
        *inclusive*: if True, adds 1 so both start and end dates are counted.

        Example::

            .duration("TRTDURD", start_date="TRTSDT", end_date="TRTEDT")
        """
        diff = (pl.col(end_date).cast(pl.Date) - pl.col(start_date).cast(pl.Date)).dt.total_days()
        expr = (diff + 1 if inclusive else diff).alias(target)
        return self._chain(expr)

    def count_events(
        self,
        target: str,
        *,
        from_dataset: pl.DataFrame,
        where: str | pl.Expr | None = None,
        groups: list[str] | None = None,
    ) -> Self:
        """
        Derive *target* as the count of matching records in *from_dataset*.

        Returns 0 for subjects with no matching records (never null).

        Example::

            .count_events("NUMAE",    from_dataset=ae_sdtm)
            .count_events("NUMSAEFL", from_dataset=ae_sdtm,
                           where='pl.col("AESER") == "Y"')
        """
        from ..sdtm.utils import parse_expression

        grps = groups or ["USUBJID"]
        src = from_dataset
        if where is not None:
            where_expr = where if isinstance(where, pl.Expr) else parse_expression(str(where))
            src = src.filter(where_expr)
        agg_df = src.group_by(grps).agg(pl.len().alias(target))
        df = self.to_frame().join(agg_df, on=grps, how="left")
        df = df.with_columns(pl.col(target).fill_null(0))
        return self._materialise_then(df)

    def eligibility_flag(
        self,
        target: str,
        *,
        criteria: str | pl.Expr,
    ) -> Self:
        """
        Set *target* to ``"Y"`` where *criteria* is true, null otherwise.

        Used for population flags: SAFFL, ITTFL, PPROTFL, ENRLFL, COMPLFL.

        Example::

            .eligibility_flag("SAFFL",   criteria='pl.col("RANDFL") == "Y"')
            .eligibility_flag("PPROTFL", criteria='pl.col("COMPLFL") == "Y"')
        """
        from ..sdtm.utils import parse_expression

        crit_expr = criteria if isinstance(criteria, pl.Expr) else parse_expression(str(criteria))
        return self._chain(
            pl.when(crit_expr).then(pl.lit("Y")).otherwise(pl.lit(None)).alias(target)
        )

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
        """
        Convert age to years, handling common unit strings.

        Recognises *AGEU* values: ``YEARS``, ``MONTHS``, ``WEEKS``, ``DAYS``
        (case-insensitive).  Unknown units produce null.

        Example::

            .age_years("AAGE", age_col="AGE", age_unit_col="AGEU")
        """
        from .utils import age_in_years as _age_in_years_expr

        return self._chain(
            _age_in_years_expr(age_col=age_col, age_unit_col=age_unit_col, target=target)
        )

    # ------------------------------------------------------------------ #
    # ADSL: derive_period — Subperiod / Phase variables                   #
    # ------------------------------------------------------------------ #

    def derive_period(
        self,
        *,
        periods: list[dict[str, Any]],
        start_date: str = "TRTSDT",
    ) -> Self:
        """
        Create standard Subperiod / Phase variables (APxxSDT, APxxEDT, TRTxxP, …).

        *periods* is a list of dicts, each with at least:

        - ``"number"``: integer period number (1, 2, …)
        - ``"start"``: column name for the period start date
        - ``"end"``: column name for the period end date
        - ``"treatment"``: (optional) column name or literal for TRTxxP

        The method generates ``AP{nn}SDT``, ``AP{nn}EDT``, and optionally
        ``TRT{nn:02d}P`` columns for each period.

        Example::

            .derive_period(
                periods=[
                    {"number": 1, "start": "AP01SDT", "end": "AP01EDT",
                     "treatment": "TRT01P"},
                    {"number": 2, "start": "AP02SDT", "end": "AP02EDT",
                     "treatment": "TRT02P"},
                ],
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
