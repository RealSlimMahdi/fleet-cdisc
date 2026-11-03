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
        .treatment_emergent("TRTEMFL", start_date="ASTDT", end_date="AENDT",
                             trtsdt="TRTSDT", trtedt="TRTEDT", end_window=30)
        .seq("ASEQ", by=["USUBJID"])
        .flag("ANL01FL", criteria="max", value_col="AESEV",
              by=["USUBJID", "AEBODSYS"])
        .to_frame()
    )
"""

from __future__ import annotations

from typing import Self

import polars as pl

from fleet.adam._mixins import MultiRowMixin, SharedADaMVerbsMixin
from fleet.core.dtc import to_day
from fleet.core.exceptions import DerivationError


@pl.api.register_lazyframe_namespace("occds")
class OCCDSNamespace(SharedADaMVerbsMixin, MultiRowMixin):
    """
    Immutable pipeline builder for OCCDS (one-row-per-event) derivations.

    Covers occurrence datasets: ADAE, ADCM, ADMH, ADEX, etc.  Also
    registered as the ``occds`` LazyFrame namespace, so
    ``pl.scan_parquet(...).occds`` starts a fully lazy OCCDS pipeline.

    Inherits shared verbs from ``SharedADaMVerbsMixin``
    (assign, case_when, merge, source, derivation, whereclauses, ...)
    and adds OCCDS-specific verbs for event sequencing, worst-record
    flagging, and treatment-emergent classification.  Discover the full
    set with ``.verbs()``.
    """

    # ------------------------------------------------------------------ #
    # OCCDS-specific verbs                                                 #
    # ------------------------------------------------------------------ #

    def treatment_emergent(
        self,
        target: str = "TRTEMFL",
        *,
        start_date: str,
        end_date: str | None,
        trtsdt: str,
        trtedt: str | None = None,
        end_window: int | None = None,
        offset_days: int = 0,
    ) -> Self:
        """Set *target* to ``"Y"`` for treatment-emergent events, as admiral ``derive_var_trtemfl``.

        The cases are taken in this order; the first that applies decides:

        1. *trtsdt* missing: null (the subject is not treated).
        2. *end_date* before *trtsdt*: null (the event ended before treatment).
        3. *start_date* missing: ``"Y"`` (a missing start cannot show the
           event began before treatment).
        4. *start_date* on or after *trtsdt* (+ *offset_days*), and, when
           *end_window* is given, on or before *trtedt* + *end_window* days,
           with a missing *trtedt* read as still on treatment: ``"Y"``.
        5. Otherwise: null.

        ``--DTC`` text is read by its date portion.  Pass ``end_date=None``
        when the data hold no event end date; the SAP decides the window.

        Args:
            target: Name of the output flag column (default ``"TRTEMFL"``).
            start_date: Event start date column (``ASTDT``).
            end_date: Event end date column (``AENDT``), or ``None``.
            trtsdt: Treatment start date column.
            trtedt: Treatment end date column; given with *end_window*.
            end_window: Days after *trtedt* in which an event still counts;
                given with *trtedt*.  ``0`` stops at the last dose date.
            offset_days: Days added to *trtsdt* before the start-date
                comparison of case 4 (a Fleet extension; admiral has none).

        Returns:
            Self: The namespace with *target* appended.

        Raises:
            DerivationError: When only one of *trtedt* and *end_window* is
                given, or *end_window* is negative.

        References:
            admiral ``derive_var_trtemfl`` (pharmaverse), Details. CDISC gives
            no rule for missing dates; check the SAP.

        Examples:
            TEAE up to 30 days after the last dose::

                adae = (
                    ae_raw.adam.occds
                    .treatment_emergent("TRTEMFL", start_date="ASTDT", end_date="AENDT",
                                        trtsdt="TRTSDT", trtedt="TRTEDT", end_window=30)
                    .to_frame()
                )
        """
        if (trtedt is None) != (end_window is None):
            raise DerivationError(
                f"treatment_emergent('{target}'): give trtedt= and end_window= together "
                "(admiral end_window). end_window=0 stops at the last dose date; without "
                "both, an event after the last dose still counts."
            )
        if end_window is not None and end_window < 0:
            raise DerivationError(
                f"treatment_emergent('{target}'): end_window={end_window} must be 0 or more days."
            )
        schema = self._lazy.collect_schema()

        def day(name: str) -> pl.Expr:
            return to_day(pl.col(name), schema.get(name)).cast(pl.Date)

        start, trt_start = day(start_date), day(trtsdt)
        ref = trt_start + pl.duration(days=offset_days) if offset_days else trt_start
        in_window = start >= ref
        if trtedt is not None:
            last = day(trtedt) + pl.duration(days=end_window)
            in_window = in_window & (last.is_null() | (start <= last))
        ended_before = day(end_date) < trt_start if end_date is not None else pl.lit(False)
        flag = (
            pl.when(trt_start.is_null())
            .then(None)
            .when(ended_before.fill_null(False))
            .then(None)
            .when(start.is_null())
            .then(pl.lit("Y"))
            .when(in_window)
            .then(pl.lit("Y"))
            .otherwise(None)
        )
        return self._chain(flag.cast(pl.String).alias(target))

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
