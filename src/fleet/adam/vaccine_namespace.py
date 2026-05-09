"""
ADaM Vaccine namespace extension (admiralvaccine-inspired).

Accessed via ``df.adam.vaccine`` on any Polars DataFrame.

Key derivations ported from pharmaverse/admiralvaccine:
  - ``fever_flag``          — flag elevated temperature records (ADFACE)
  - ``seroconversion_flag`` — ≥ N-fold rise from baseline (ADIS)
  - ``seroresponse_flag``   — titer at or above a threshold (ADIS)
  - ``aval_adis``           — AVAL derivation with LLOQ/ULOQ handling (ADIS)
  - ``event_flag``          — group-level and day-level reactogenicity event flags

Usage
-----
    import fleet  # triggers registration

    adface = (
        face_df.adam.vaccine
        .source("USUBJID")
        .fever_flag("FEVFL", temp_col="AVAL", threshold=38.0)
        .event_flag("EVENTFL", aval_col="AVAL", cutoff=2.5,
                    groups=["USUBJID", "FAOBJ", "ATPTREF"])
        .to_frame()
    )

    adis = (
        is_df.adam.vaccine
        .aval_adis("AVAL", stresn_col="ISSTRESN", lloq_col="ISLLOQ",
                   uloq_col="ISULOQ", orres_col="ISORRES")
        .seroconversion_flag("SRCONVFL", aval_col="AVAL", base_col="BASE")
        .seroresponse_flag("SRSFL", aval_col="AVAL", threshold=40.0)
        .to_frame()
    )
"""

from __future__ import annotations

from typing import Self

import polars as pl

from fleet.adam._mixins import SharedADaMVerbsMixin


class VaccineNamespace(SharedADaMVerbsMixin):
    """
    Immutable pipeline builder for ADaM vaccine derivations.

    Inherits shared verbs from ``SharedADaMVerbsMixin``.
    """

    # ------------------------------------------------------------------ #
    # 1. fever_flag — flag elevated temperature (ADFACE)                  #
    # ------------------------------------------------------------------ #

    def fever_flag(
        self,
        target: str,
        *,
        temp_col: str,
        threshold: float = 38.0,
        flag_value: str = "Y",
    ) -> Self:
        """
        Set *target* to *flag_value* when *temp_col* is strictly above *threshold*.

        Default threshold of 38.0 °C aligns with the WHO/FDA fever definition
        used in vaccine reactogenicity assessments.

        Example::

            .fever_flag("FEVFL", temp_col="TEMP", threshold=38.0)
            .fever_flag("HIGHFEVFL", temp_col="TEMP", threshold=39.0)
        """
        return self._chain(
            pl.when(pl.col(temp_col) > threshold)
            .then(pl.lit(flag_value))
            .otherwise(pl.lit(None))
            .alias(target)
        )

    # ------------------------------------------------------------------ #
    # 2. seroconversion_flag — ≥ N-fold rise from baseline               #
    # ------------------------------------------------------------------ #

    def seroconversion_flag(
        self,
        target: str,
        *,
        aval_col: str,
        base_col: str,
        fold_rise: float = 4.0,
        flag_value: str = "Y",
    ) -> Self:
        """
        Set *target* to *flag_value* when ``AVAL / BASE ≥ fold_rise``.

        The default four-fold rise threshold is the standard seroconversion
        criterion for most immunogenicity assays.

        Null is returned when *base_col* is null or zero.

        Example::

            .seroconversion_flag("SRCONVFL", aval_col="AVAL", base_col="BASE")
            .seroconversion_flag("SRCONV2FL", aval_col="AVAL", base_col="BASE",
                                  fold_rise=2.0)
        """
        aval = pl.col(aval_col)
        base = pl.col(base_col)
        return self._chain(
            pl.when(base.is_not_null() & (base != 0) & (aval / base >= fold_rise))
            .then(pl.lit(flag_value))
            .otherwise(pl.lit(None))
            .alias(target)
        )

    # ------------------------------------------------------------------ #
    # 3. seroresponse_flag — titer at or above a threshold               #
    # ------------------------------------------------------------------ #

    def seroresponse_flag(
        self,
        target: str,
        *,
        aval_col: str,
        threshold: float,
        flag_value: str = "Y",
    ) -> Self:
        """
        Set *target* to *flag_value* when *aval_col* ≥ *threshold*.

        Example::

            .seroresponse_flag("SRSFL", aval_col="AVAL", threshold=40.0)
        """
        return self._chain(
            pl.when(pl.col(aval_col) >= threshold)
            .then(pl.lit(flag_value))
            .otherwise(pl.lit(None))
            .alias(target)
        )

    # ------------------------------------------------------------------ #
    # 4. aval_adis — ADIS AVAL with LLOQ/ULOQ handling                   #
    # ------------------------------------------------------------------ #

    def aval_adis(
        self,
        target: str,
        *,
        stresn_col: str = "ISSTRESN",
        lloq_col: str = "ISLLOQ",
        uloq_col: str | None = "ISULOQ",
        orres_col: str | None = "ISORRES",
        lloq_rule: str = "half",
        round_digits: int | None = None,
    ) -> Self:
        """
        Derive ``AVAL`` for the ADIS domain following limit-of-quantification rules.

        Rules (mirrors ``admiralvaccine::derive_var_aval_adis``):

        1. If *stresn_col* is missing:
           - If *orres_col* starts with ``">"`` and *uloq_col* is present →
             use *uloq_col* value.
           - If *orres_col* starts with ``"<"`` → use *lloq_col* × factor
             (``"half"`` = ÷2, ``"lloq"`` = *lloq_col* itself).
           - Otherwise → null.
        2. If *stresn_col* < *lloq_col* → use *lloq_col* × factor.
        3. If *uloq_col* present and *stresn_col* > *uloq_col* → use *uloq_col*.
        4. Otherwise → use *stresn_col*.

        *lloq_rule*: ``"half"`` (LLOQ ÷ 2) or ``"lloq"`` (retain LLOQ value).

        Example::

            .aval_adis("AVAL", stresn_col="ISSTRESN",
                       lloq_col="ISLLOQ", uloq_col="ISULOQ",
                       orres_col="ISORRES")
        """
        stresn = pl.col(stresn_col)
        lloq = pl.col(lloq_col)
        lloq_val = lloq / 2.0 if lloq_rule == "half" else lloq

        if uloq_col:
            uloq = pl.col(uloq_col)
            # When STRESN is present: apply LLOQ/ULOQ capping
            stresn_rule = (
                pl.when(stresn < lloq)
                .then(lloq_val)
                .when(stresn > uloq)
                .then(uloq)
                .otherwise(stresn)
            )
            # When STRESN is missing: use ORRES string to infer direction
            if orres_col:
                orres_str = pl.col(orres_col).cast(pl.Utf8)
                missing_rule = (
                    pl.when(orres_str.str.starts_with(">"))
                    .then(uloq)
                    .when(orres_str.str.starts_with("<"))
                    .then(lloq_val)
                    .otherwise(pl.lit(None))
                )
            else:
                missing_rule = pl.lit(None)

            expr = pl.when(stresn.is_not_null()).then(stresn_rule).otherwise(missing_rule)
        else:
            # No ULOQ column
            stresn_rule = pl.when(stresn < lloq).then(lloq_val).otherwise(stresn)
            if orres_col:
                orres_str = pl.col(orres_col).cast(pl.Utf8)
                missing_rule = (
                    pl.when(orres_str.str.starts_with("<")).then(lloq_val).otherwise(pl.lit(None))
                )
            else:
                missing_rule = pl.lit(None)

            expr = pl.when(stresn.is_not_null()).then(stresn_rule).otherwise(missing_rule)

        if round_digits is not None:
            expr = expr.round(round_digits)

        return self._chain(expr.alias(target))

    # ------------------------------------------------------------------ #
    # 5. event_flag — reactogenicity event occurrence flags               #
    # ------------------------------------------------------------------ #

    def event_flag(
        self,
        target: str,
        *,
        aval_col: str,
        cutoff: float,
        groups: list[str] | None = None,
        severity_col: str | None = None,
        severity_values: list[str] | None = None,
        flag_value: str = "Y",
        no_event_value: str = "N",
    ) -> Self:
        """
        Flag whether a reactogenicity event occurred at least once per *groups*.

        An event is considered to have occurred if:
        - *aval_col* > *cutoff*, OR
        - *severity_col* (if provided) is in *severity_values* (default:
          ``["MILD", "MODERATE", "SEVERE"]``).

        All records within the group are set to *flag_value* if the event
        occurred at least once; otherwise *no_event_value*.

        Materialises the current pipeline.

        Mirrors ``admiralvaccine::derive_vars_event_flag`` (new_var1 behaviour).

        Example::

            .event_flag("EVENTFL", aval_col="AVAL", cutoff=2.5,
                        groups=["USUBJID", "FAOBJ", "ATPTREF"])
        """
        sev_vals = severity_values or ["MILD", "MODERATE", "SEVERE"]
        grps = groups or ["USUBJID"]

        df = self.to_frame()

        # Build row-level event indicator
        row_event = pl.col(aval_col) > cutoff
        if severity_col:
            row_event = row_event | pl.col(severity_col).is_in(sev_vals)

        # Any-event per group (window max of boolean cast to int)
        any_event = row_event.cast(pl.Int8).max().over(grps).cast(pl.Boolean)

        result = df.with_columns(
            pl.when(any_event)
            .then(pl.lit(flag_value))
            .otherwise(pl.lit(no_event_value))
            .alias(target)
        )
        return self._materialise_then(result)
