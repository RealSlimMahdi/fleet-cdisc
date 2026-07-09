"""
ADaM ADSL namespace extension (one-row-per-subject datasets).

Accessed via ``df.adam.adsl`` on any Polars DataFrame.

Usage
-----
    import fleet  # triggers registration

    adsl = (
        dm_sdtm.adam.adsl
        .source("USUBJID")
        .assign("STUDYID", value="MYSTUDY01")
        .first_date("AESTDT", from_dataset=ae_sdtm, date_col="AESTDTC",
                    where='pl.col("AESER") == "Y"')
        .duration("TRTDURD", start="TRTSDT", end="TRTEDT")
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


@pl.api.register_lazyframe_namespace("adsl")
class ADSLNamespace(SharedADaMVerbsMixin):
    """
    Immutable pipeline builder for ADSL (one-row-per-subject) derivations.

    Also registered as the ``adsl`` LazyFrame namespace, so
    ``pl.scan_parquet(...).adsl`` starts a fully lazy ADSL pipeline.

    Inherits shared verbs from ``SharedADaMVerbsMixin``
    (assign, case_when, merge, source, derivation, whereclauses, ...)
    and adds ADSL-specific verbs that pull summary statistics from
    event-level datasets (AE, CM, MH, EX…).  Discover the full set with
    ``.verbs()``.
    """

    def __init__(self, df: pl.DataFrame | pl.LazyFrame) -> None:
        super().__init__(df)
        self._domain = "ADSL"

    # ------------------------------------------------------------------ #
    # ADSL-specific verbs.                                                 #
    # first_date / last_date / count_events moved to                       #
    # SharedADaMVerbsMixin so the spec path (from_spec) can dispatch them. #
    # ------------------------------------------------------------------ #

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
    ) -> Self:
        """Create standard Subperiod / Phase variables.

        Generates ``AP{nn}SDT``, ``AP{nn}EDT``, and optionally
        ``TRT{nn:02d}P`` columns for each period.

        Args:
            periods: List of dicts each with ``"number"``, ``"start"``,
                ``"end"``, and optionally ``"treatment"``.

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
