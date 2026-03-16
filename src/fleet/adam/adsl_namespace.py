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
        diff = (
            pl.col(end_date).cast(pl.Date) - pl.col(start_date).cast(pl.Date)
        ).dt.total_days()
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


