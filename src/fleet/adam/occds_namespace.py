"""
ADaM OCCDS namespace extension (one-row-per-event occurrence datasets).

Accessed via ``df.adam.occds`` on any Polars DataFrame.

Usage
-----
    import fleet  # triggers registration

    adae = (
        ae_sdtm.adam.occds
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

from typing import Any, Self

import polars as pl

from ._mixins import SharedADaMVerbsMixin


class OCCDSNamespace(SharedADaMVerbsMixin):
    """
    Immutable pipeline builder for OCCDS (one-row-per-event) derivations.

    Covers occurrence datasets: ADAE, ADCM, ADMH, ADEX, etc.

    Inherits shared verbs from ``SharedADaMVerbsMixin``
    (source, derivation, assigned, recode, rename, condderivation,
    whereclauses) and adds OCCDS-specific verbs for event sequencing,
    worst-record flagging, and treatment-emergent classification.
    """

    # ------------------------------------------------------------------ #
    # OCCDS-specific verbs                                                 #
    # ------------------------------------------------------------------ #

    def seq(
        self,
        target: str = "ASEQ",
        *,
        groups: list[str] | None = None,
    ) -> Self:
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
    ) -> Self:
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
        rank_map = {val: idx for idx, val in enumerate(sev_order)}
        rank_expr = pl.col(severity_col).replace_strict(
            rank_map, default=-1
        ).alias("__sev_rank__")

        # Use window function to find max rank per group (stays lazy)
        max_sev_expr = pl.col("__sev_rank__").max().over(grps).alias("__max_sev__")

        match_cond = pl.col("__sev_rank__") == pl.col("__max_sev__")
        if where is not None:
            where_expr = where if isinstance(where, pl.Expr) else parse_expression(str(where))
            match_cond = where_expr & match_cond

        flag_expr = (
            pl.when(match_cond)
            .then(pl.lit("Y"))
            .otherwise(pl.lit(None))
            .alias(target)
        )

        new = object.__new__(OCCDSNamespace)
        new._lazy = (
            self._lazy
            .with_columns(rank_expr)
            .with_columns(max_sev_expr)
            .with_columns(flag_expr)
            .drop(["__sev_rank__", "__max_sev__"])
        )
        return new

    def treatment_emergent(
        self,
        target: str = "TRTEMFL",
        *,
        start_date: str,
        trtsdt: str,
        trtedt: str | None = None,
        offset_days: int = 0,
    ) -> Self:
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
    ) -> Self:
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

