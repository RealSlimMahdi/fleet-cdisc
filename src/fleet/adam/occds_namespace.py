"""
ADaM OCCDS Polars namespace extension (one-row-per-event occurrence datasets).

Registers ``df.occds`` on every Polars DataFrame.

Usage
-----
    import fleet  # triggers registration

    adae = (
        ae_sdtm.occds
        .source("USUBJID")
        .source("AETERM")
        .treatment_emergent("TRTEMFL", start_date="AESTDTC",
                             trtsdt="TRTSDT", trtedt="TRTEDT")
        .seq("ASEQ", groups=["USUBJID"])
        .worst_flag("ANL01FL", severity_col="AESEV",
                    severity_order=["MILD", "MODERATE", "SEVERE"],
                    groups=["USUBJID", "AEBODSYS"])
        .to_frame()
    )
"""

from __future__ import annotations

from typing import Any

import polars as pl


@pl.api.register_dataframe_namespace("occds")
class OCCDSNamespace:
    """
    Immutable pipeline builder for OCCDS (one-row-per-event) derivations.

    Covers occurrence datasets: ADAE, ADCM, ADMH, ADEX, etc.

    Includes the base ADaM verbs (source, derivation, assigned, recode, rename,
    condderivation, whereclauses) plus OCCDS-specific verbs for event sequencing,
    worst-record flagging, and treatment-emergent classification.
    """

    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df
        self._pipeline: list[pl.Expr] = []

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _chain(self, *exprs: pl.Expr) -> "OCCDSNamespace":
        new = object.__new__(OCCDSNamespace)
        new._df = self._df
        new._pipeline = self._pipeline + list(exprs)
        return new

    def _materialise_then(self, df: pl.DataFrame) -> "OCCDSNamespace":
        new = object.__new__(OCCDSNamespace)
        new._df = df
        new._pipeline = []
        return new

    # ------------------------------------------------------------------ #
    # Base verbs (shared with df.adam)                                    #
    # ------------------------------------------------------------------ #

    def source(self, target: str, *, from_col: str | None = None) -> "OCCDSNamespace":
        """Copy a column from the predecessor dataset."""
        src = from_col if from_col is not None else target
        return self._chain(pl.col(src).alias(target))

    def derivation(self, target: str, *, expression: str | pl.Expr) -> "OCCDSNamespace":
        """Arbitrary Polars expression derivation."""
        from ..sdtm.utils import parse_expression
        expr = expression if isinstance(expression, pl.Expr) else parse_expression(str(expression))
        return self._chain(expr.alias(target))

    def assigned(self, target: str, *, value: Any) -> "OCCDSNamespace":
        """Global constant for every event record."""
        return self._chain(pl.lit(value).alias(target))

    def recode(
        self,
        target: str,
        *,
        source: str,
        recode_map: dict[Any, Any],
        default: Any = None,
    ) -> "OCCDSNamespace":
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

    def rename(self, target: str, *, source: str) -> "OCCDSNamespace":
        """Rename *source* column to *target*."""
        return self._chain(pl.col(source).alias(target))

    def condderivation(
        self,
        target: str,
        *,
        conditions: list[dict[str, Any]],
        else_value: Any = None,
    ) -> "OCCDSNamespace":
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

    def whereclauses(self, *, where: str | pl.Expr) -> "OCCDSNamespace":
        """Filter events by *where* expression."""
        from ..sdtm.utils import parse_expression
        df = self.to_frame()
        filter_expr = where if isinstance(where, pl.Expr) else parse_expression(str(where))
        return self._materialise_then(df.filter(filter_expr))

    # ------------------------------------------------------------------ #
    # OCCDS-specific verbs                                                 #
    # ------------------------------------------------------------------ #

    def seq(
        self,
        target: str = "ASEQ",
        *,
        groups: list[str] | None = None,
    ) -> "OCCDSNamespace":
        """
        Sequential 1-based record number within each group, preserving row order.

        Materialises the current pipeline before assigning sequence numbers.

        Example::

            .seq("ASEQ", groups=["USUBJID"])
        """
        grps = groups or ["USUBJID"]
        df = self.to_frame()
        df = df.with_columns(
            (pl.int_range(pl.len()).over(grps) + 1).cast(pl.Int64).alias(target)
        )
        return self._materialise_then(df)

    def worst_flag(
        self,
        target: str,
        *,
        severity_col: str,
        groups: list[str] | None = None,
        severity_order: list[Any] | None = None,
        where: str | pl.Expr | None = None,
    ) -> "OCCDSNamespace":
        """
        Flag the record with the worst (highest-ranked) severity per group.

        *severity_order*: list of severity values from least to most severe.
                          Defaults to ``["MILD", "MODERATE", "SEVERE"]``.
                          Use integers for numeric grades: ``[1, 2, 3, 4]``.
        *where*: optional pre-filter — only candidate rows are eligible.

        Example::

            # Categorical severity
            .worst_flag("ANL01FL", severity_col="AESEV",
                         groups=["USUBJID", "AEBODSYS"],
                         severity_order=["MILD", "MODERATE", "SEVERE"])

            # Numeric CTCAE grade
            .worst_flag("ANL01FL", severity_col="AETOXGR",
                         groups=["USUBJID", "AEBODSYS"],
                         severity_order=[1, 2, 3, 4])
        """
        from ..sdtm.utils import parse_expression

        sev_order = severity_order or ["MILD", "MODERATE", "SEVERE"]
        grps = groups or ["USUBJID"]

        # Encode severity as an integer rank for comparison
        items = [(val, idx) for idx, val in enumerate(sev_order)]
        k0, v0 = items[0]
        rank_chain = pl.when(pl.col(severity_col) == k0).then(pl.lit(v0))
        for k, v in items[1:]:
            rank_chain = rank_chain.when(pl.col(severity_col) == k).then(pl.lit(v))
        rank_expr = rank_chain.otherwise(pl.lit(-1)).alias("__sev_rank__")

        df = self.to_frame().with_columns(rank_expr)
        max_rank = df.group_by(grps).agg(pl.col("__sev_rank__").max().alias("__max_sev__"))
        df = df.join(max_rank, on=grps, how="left")

        match_cond = pl.col("__sev_rank__") == pl.col("__max_sev__")
        if where is not None:
            where_expr = where if isinstance(where, pl.Expr) else parse_expression(str(where))
            match_cond = where_expr & match_cond

        df = (
            df.with_columns(
                pl.when(match_cond)
                .then(pl.lit("Y"))
                .otherwise(pl.lit(None))
                .alias(target)
            )
            .drop(["__sev_rank__", "__max_sev__"])
        )
        return self._materialise_then(df)

    def treatment_emergent(
        self,
        target: str = "TRTEMFL",
        *,
        start_date: str,
        trtsdt: str,
        trtedt: str | None = None,
        offset_days: int = 0,
    ) -> "OCCDSNamespace":
        """
        Set *target* to ``"Y"`` for treatment-emergent events.

        An event is treatment-emergent when *start_date* >= *trtsdt* + *offset_days*.
        If *trtedt* is provided, also requires *start_date* <= *trtedt*.

        Example::

            .treatment_emergent("TRTEMFL", start_date="AESTDTC",
                                  trtsdt="TRTSDT", trtedt="TRTEDT")
        """
        start = pl.col(start_date).cast(pl.Date)
        ref = pl.col(trtsdt).cast(pl.Date)
        if offset_days:
            ref = ref + pl.duration(days=offset_days)
        cond = start >= ref
        if trtedt:
            cond = cond & (start <= pl.col(trtedt).cast(pl.Date))
        return self._chain(
            pl.when(cond)
            .then(pl.lit("Y"))
            .otherwise(pl.lit(None))
            .alias(target)
        )

    def onset_recovery(
        self,
        target: str,
        *,
        start_date: str,
        end_date: str,
        ref_date: str,
    ) -> "OCCDSNamespace":
        """
        Flag events that start within the reference window AND have a recorded end.

        Set *target* to ``"Y"`` when *start_date* >= *ref_date* AND *end_date* is not null.

        Example::

            .onset_recovery("RCVRYFL", start_date="AESTDTC",
                             end_date="AEENDTC", ref_date="TRTSDT")
        """
        cond = (
            (pl.col(start_date).cast(pl.Date) >= pl.col(ref_date).cast(pl.Date))
            & pl.col(end_date).is_not_null()
        )
        return self._chain(
            pl.when(cond)
            .then(pl.lit("Y"))
            .otherwise(pl.lit(None))
            .alias(target)
        )

    # ------------------------------------------------------------------ #
    # Terminal operation                                                   #
    # ------------------------------------------------------------------ #

    def to_frame(self) -> pl.DataFrame:
        """Materialise the accumulated pipeline into a Polars DataFrame."""
        if not self._pipeline:
            return self._df
        return self._df.with_columns(self._pipeline)
