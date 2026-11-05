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
        .flag("SAFFL",   criteria='pl.col("TRTSDT").is_not_null()', false_value="N")
        .flag("PPROTFL", criteria='pl.col("COMPLFL") == "Y"', false_value="N")
        .to_frame()
    )
"""

from __future__ import annotations

import warnings
from typing import Any, Literal, Self

import polars as pl

from fleet.adam._mixins import SharedADaMVerbsMixin
from fleet.core.dtc import to_day


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
        round_digits: int | None = None,
    ) -> Self:
        """Convert age to years, handling common unit strings.

        Recognises *AGEU* values: ``YEARS``, ``MONTHS``, ``WEEKS``, ``DAYS``,
        ``HOURS`` (case-insensitive).  Unknown units produce null and a
        warning with their count.  The value keeps full precision (AGE 7
        MONTHS gives 0.5833...).

        Args:
            target: Name of the output column (default ``"AAGE"``).
            age_col: Source age column.
            age_unit_col: Column containing the age unit string.
            round_digits: Decimal places, rounded as SAS ``ROUND`` (half away
                from zero).  Default ``None``: no rounding.

        Returns:
            Self: The namespace with *target* appended.

        References:
            admiral ``compute_age_years`` (pharmaverse): full precision; one year is
            12 months, 365.25/7 weeks, 365.25 days or 8766 hours. CDISC CT
            C66781 (AGEU). ADR-0025: a derived value is rounded only when the
            call says so. ADR-0053: the week and hour divisors.

        Examples:
            Derive age in years from DM variables::

                adsl = (
                    dm_raw.adam.adsl
                    .age_years("AAGE", age_col="AGE", age_unit_col="AGEU")
                    .to_frame()
                )
        """
        from fleet.adam.utils import age_in_years as _age_in_years_expr

        if age_unit_col in self._lazy.collect_schema().names():
            unit = pl.col(age_unit_col).cast(pl.String).str.to_uppercase()
            known = ["YEARS", "MONTHS", "WEEKS", "DAYS", "HOURS"]
            bad = (
                self._lazy.filter(unit.is_not_null() & ~unit.is_in(known))
                .select(pl.col(age_unit_col).cast(pl.String))
                .collect()
                .get_column(age_unit_col)
            )
            if bad.len():
                warnings.warn(
                    f"age_years(): {bad.len()} row(s) have an {age_unit_col} that is not "
                    f"{', '.join(known)} (for example {bad.unique(maintain_order=True).head(3).to_list()}); "
                    f"{target} is null on them.",
                    UserWarning,
                    stacklevel=2,
                )
        return self._chain(
            _age_in_years_expr(
                age_col=age_col,
                age_unit_col=age_unit_col,
                target=target,
                round_digits=round_digits,
            )
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
        unit: Literal["years", "decimal"] = "years",
        round_digits: int | None = None,
    ) -> Self:
        """Compute age from two date columns, in completed years by default.

        ``unit="years"`` gives whole completed years (Int64): the year
        difference, minus 1 when the birthday of the reference year is not
        yet reached.  A subject born 1956-06-01 is 64 on 2021-05-31.  A 29
        February birthday is reached on 1 March in a non-leap year.  A
        reference date before birth gives a negative age.
        ``unit="decimal"`` gives days / 365.25 at full precision.  Null when
        either date is missing.

        Args:
            target: Name of the output column (default ``"AAGE"``).
            birth_date: Date-of-birth column (``pl.Date``).
            reference_date: Reference date column (``pl.Date``).
            unit: ``"years"`` (default) or ``"decimal"``.
            round_digits: Decimal places for ``unit="decimal"``, rounded as
                SAS ``ROUND``.  Default ``None``: no rounding.

        Returns:
            Self: The namespace with *target* appended.

        Raises:
            VerbUsageError: When *round_digits* is given with
                ``unit="years"``, or *unit* is unknown.

        References:
            admiral ``derive_vars_aage`` (pharmaverse) and SAS
            ``FLOOR(YRDIF(BRTHDT, TRTSDT, 'AGE'))``: completed years. ICH E7 and
            E11 age bands use completed years. ADR-0025.

        Examples:
            Derive age from birth and randomisation dates::

                adsl = (
                    dm_raw.adam.adsl
                    .age_from_dates("AAGE", birth_date="BRTHDT",
                                    reference_date="RANDDT")
                    .to_frame()
                )
        """
        from fleet.adam.utils import age_between

        schema = self._lazy.collect_schema()
        reference, birth = (
            to_day(pl.col(c), schema.get(c), verb="age_from_dates").cast(pl.Date)
            for c in (reference_date, birth_date)
        )
        expr = age_between(
            birth, reference, unit=unit, round_digits=round_digits, verb="age_from_dates"
        )
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
