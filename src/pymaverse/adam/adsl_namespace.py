"""
ADaM ADSL Polars namespace extension (one-row-per-subject datasets).

Registers ``df.adsl`` on every Polars DataFrame.

Usage
-----
    import pymaverse  # triggers registration

    adsl = (
        dm_sdtm.adsl
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

from typing import Any

import polars as pl


@pl.api.register_dataframe_namespace("adsl")
class ADSLNamespace:
    """
    Immutable pipeline builder for ADSL (one-row-per-subject) derivations.

    Includes the base ADaM verbs (source, derivation, assigned, recode, rename,
    condderivation, whereclauses) plus ADSL-specific verbs that pull summary
    statistics from event-level datasets (AE, CM, MH, EX…).
    """

    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df
        self._pipeline: list[pl.Expr] = []

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _chain(self, *exprs: pl.Expr) -> "ADSLNamespace":
        new = object.__new__(ADSLNamespace)
        new._df = self._df
        new._pipeline = self._pipeline + list(exprs)
        return new

    def _materialise_then(self, df: pl.DataFrame) -> "ADSLNamespace":
        new = object.__new__(ADSLNamespace)
        new._df = df
        new._pipeline = []
        return new

    # ------------------------------------------------------------------ #
    # Base verbs (shared with df.adam)                                    #
    # ------------------------------------------------------------------ #

    def source(self, target: str, *, from_col: str | None = None) -> "ADSLNamespace":
        """Copy a column from the predecessor dataset (pass-through)."""
        src = from_col if from_col is not None else target
        return self._chain(pl.col(src).alias(target))

    def derivation(self, target: str, *, expression: str | pl.Expr) -> "ADSLNamespace":
        """Arbitrary Polars expression derivation."""
        from ..sdtm.utils import parse_expression
        expr = expression if isinstance(expression, pl.Expr) else parse_expression(str(expression))
        return self._chain(expr.alias(target))

    def assigned(self, target: str, *, value: Any) -> "ADSLNamespace":
        """Global constant for every subject record."""
        return self._chain(pl.lit(value).alias(target))

    def recode(
        self,
        target: str,
        *,
        source: str,
        recode_map: dict[Any, Any],
        default: Any = None,
    ) -> "ADSLNamespace":
        """Map values in *source* to recoded values; unmapped → *default*."""
        if recode_map:
            items = list(recode_map.items())
            k0, v0 = items[0]
            chain = pl.when(pl.col(source) == k0).then(pl.lit(v0))
            for k, v in items[1:]:
                chain = chain.when(pl.col(source) == k).then(pl.lit(v))
            default_expr = default if isinstance(default, pl.Expr) else pl.lit(default)
            expr = chain.otherwise(default_expr).alias(target)
        else:
            default_expr = default if isinstance(default, pl.Expr) else pl.lit(default)
            expr = default_expr.alias(target)
        return self._chain(expr)

    def rename(self, target: str, *, source: str) -> "ADSLNamespace":
        """Rename *source* column to *target*."""
        return self._chain(pl.col(source).alias(target))

    def condderivation(
        self,
        target: str,
        *,
        conditions: list[dict[str, Any]],
        else_value: Any = None,
    ) -> "ADSLNamespace":
        """Multi-branch conditional derivation."""
        from ..sdtm.utils import parse_expression
        if not conditions:
            return self._chain(pl.lit(else_value).alias(target))
        first = conditions[0]
        c0 = (first["condition"] if isinstance(first["condition"], pl.Expr)
               else parse_expression(str(first["condition"])))
        chain = pl.when(c0).then(pl.lit(first["value"]))
        for branch in conditions[1:]:
            c = (branch["condition"] if isinstance(branch["condition"], pl.Expr)
                 else parse_expression(str(branch["condition"])))
            chain = chain.when(c).then(pl.lit(branch["value"]))
        return self._chain(chain.otherwise(pl.lit(else_value)).alias(target))

    def whereclauses(self, *, where: str | pl.Expr) -> "ADSLNamespace":
        """Filter subjects by *where* expression."""
        from ..sdtm.utils import parse_expression
        df = self.to_frame()
        filter_expr = where if isinstance(where, pl.Expr) else parse_expression(str(where))
        return self._materialise_then(df.filter(filter_expr))

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
    ) -> "ADSLNamespace":
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
    ) -> "ADSLNamespace":
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
    ) -> "ADSLNamespace":
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
    ) -> "ADSLNamespace":
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
    ) -> "ADSLNamespace":
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
    # Terminal operation                                                   #
    # ------------------------------------------------------------------ #

    def to_frame(self) -> pl.DataFrame:
        """Materialise the accumulated pipeline into a Polars DataFrame."""
        if not self._pipeline:
            return self._df
        return self._df.with_columns(self._pipeline)
