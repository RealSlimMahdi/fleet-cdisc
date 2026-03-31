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

from fleet.adam._mixins import MultiRowMixin, SharedADaMVerbsMixin


class OCCDSNamespace(SharedADaMVerbsMixin, MultiRowMixin):
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

    def worst_flag(
        self,
        target: str,
        *,
        severity_col: str,
        groups: list[str] | None = None,
        severity_order: list[Any] | None = None,
        where: str | pl.Expr | None = None,
        mode: str = "first",
    ) -> Self:
        """Flag the record with the worst severity per group.

        Args:
            target: Name of the output flag column.
            severity_col: Column containing severity values.
            groups: Partition columns (default ``["USUBJID"]``).
            severity_order: Values from least to most severe
                (default ``["MILD", "MODERATE", "SEVERE"]``).
            where: Optional pre-filter for candidate rows.
            mode: ``"first"`` (default) flags only the first record at
                worst severity per group.  ``"all"`` flags every record
                at worst severity.

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Flag worst AE by categorical severity per body system::

                adae = (
                    ae_raw.adam.occds
                    .worst_flag("ANL01FL", severity_col="AESEV",
                                groups=["USUBJID", "AEBODSYS"],
                                severity_order=["MILD", "MODERATE", "SEVERE"])
                    .to_frame()
                )

            Flag all tied worst records::

                adae = (
                    ae_raw.adam.occds
                    .worst_flag("ANL01FL", severity_col="AESEV",
                                groups=["USUBJID"], mode="all")
                    .to_frame()
                )
        """
        from fleet.sdtm.utils import parse_expression

        sev_order = severity_order or ["MILD", "MODERATE", "SEVERE"]
        grps = groups or ["USUBJID"]

        # Encode severity as an integer rank for comparison
        rank_map = {val: idx for idx, val in enumerate(sev_order)}
        rank_expr = pl.col(severity_col).replace_strict(rank_map, default=-1).alias("__sev_rank__")

        # Use window function to find max rank per group (stays lazy)
        max_sev_expr = pl.col("__sev_rank__").max().over(grps).alias("__max_sev__")

        match_cond = pl.col("__sev_rank__") == pl.col("__max_sev__")
        if where is not None:
            where_expr = where if isinstance(where, pl.Expr) else parse_expression(str(where))
            match_cond = where_expr & match_cond

        if mode == "first":
            # Among tied worst records, pick only the first (by row order)
            tie_rank = (
                pl.when(match_cond).then(pl.lit(1)).otherwise(pl.lit(None)).cum_sum().over(grps)
            )
            flag_expr = (
                pl.when(match_cond & (tie_rank == 1))
                .then(pl.lit("Y"))
                .otherwise(pl.lit(None))
                .alias(target)
            )
        else:
            flag_expr = pl.when(match_cond).then(pl.lit("Y")).otherwise(pl.lit(None)).alias(target)

        return self._materialise_then(
            self._lazy.with_columns(rank_expr)
            .with_columns(max_sev_expr)
            .with_columns(flag_expr)
            .drop(["__sev_rank__", "__max_sev__"])
            .collect()
        )

    def treatment_emergent(
        self,
        target: str = "TRTEMFL",
        *,
        start_date: str,
        trtsdt: str,
        trtedt: str | None = None,
        offset_days: int = 0,
    ) -> Self:
        """Set *target* to ``"Y"`` for treatment-emergent events.

        An event is treatment-emergent when *start_date* >= *trtsdt* +
        *offset_days*.  If *trtedt* is provided, also requires
        *start_date* <= *trtedt*.

        Args:
            target: Name of the output flag column (default ``"TRTEMFL"``).
            start_date: Event start date column.
            trtsdt: Treatment start date column.
            trtedt: Optional treatment end date column.
            offset_days: Grace period in days (default ``0``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive treatment-emergent flag for ADAE::

                adae = (
                    ae_raw.adam.occds
                    .treatment_emergent("TRTEMFL", start_date="AESTDTC",
                                        trtsdt="TRTSDT", trtedt="TRTEDT")
                    .to_frame()
                )
        """
        start = pl.col(start_date).cast(pl.Date)
        ref = pl.col(trtsdt).cast(pl.Date)
        if offset_days:
            ref = ref + pl.duration(days=offset_days)
        cond = start >= ref
        if trtedt:
            cond = cond & (start <= pl.col(trtedt).cast(pl.Date))
        return self._chain(pl.when(cond).then(pl.lit("Y")).otherwise(pl.lit(None)).alias(target))

    def onset_recovery(
        self,
        target: str,
        *,
        start_date: str,
        end_date: str,
        ref_date: str,
    ) -> Self:
        """Flag events that started on/after the reference date and have recovered.

        Sets *target* to ``"Y"`` when *start_date* >= *ref_date* and
        *end_date* is not null.

        Args:
            target: Name of the output flag column.
            start_date: Event start date column.
            end_date: Event end date column.
            ref_date: Reference date column (e.g. ``"TRTSDT"``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive recovery flag for adverse events::

                adae = (
                    ae_raw.adam.occds
                    .onset_recovery("RCVRYFL", start_date="AESTDTC",
                                    end_date="AEENDTC", ref_date="TRTSDT")
                    .to_frame()
                )
        """
        cond = (pl.col(start_date).cast(pl.Date) >= pl.col(ref_date).cast(pl.Date)) & pl.col(
            end_date
        ).is_not_null()
        return self._chain(pl.when(cond).then(pl.lit("Y")).otherwise(pl.lit(None)).alias(target))
