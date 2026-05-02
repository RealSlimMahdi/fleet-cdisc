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
        .flag("ANL01FL", criteria="max", value_col="AESEV",
              groups=["USUBJID", "AEBODSYS"])
        .to_frame()
    )
"""

from __future__ import annotations

from typing import Self

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
