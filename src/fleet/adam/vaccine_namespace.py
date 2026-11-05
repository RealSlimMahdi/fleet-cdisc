"""
ADaM Vaccine namespace extension (admiralvaccine-inspired).

Accessed via ``df.adam.vaccine`` on any Polars DataFrame.

Key derivations, inspired by pharmaverse/admiralvaccine (not ports; values can differ):
  - ``fever_flag``          — flag elevated temperature records (ADFACE)
  - ``seroconversion_flag`` — ≥ N-fold rise from baseline, with an LLOQ rule (ADIS)
  - ``seroresponse_flag``   — titer at or above a threshold (ADIS)
  - ``aval_adis``           — AVAL derivation with LLOQ/ULOQ handling (ADIS)
  - ``event_flag``          — group-level reactogenicity event flag

A float NaN compares above every threshold in Polars.  ``load_raw_data``
reads a CSV ``NaN`` cell as null, but a NaN from a user expression (for
example 0/0) passes as a number: fill it with ``fill_nan(None)`` first.

Usage
-----
    import fleet  # triggers registration

    adface = (
        face_df.adam.vaccine
        .source("USUBJID")
        .fever_flag("FEVFL", temp_col="AVAL", threshold=38.0)
        .event_flag("EVENTFL", aval_col="AVAL", cutoff=2.5,
                    by=["USUBJID", "FAOBJ", "ATPTREF"])
        .to_frame()
    )

    adis = (
        is_df.adam.vaccine
        .aval_adis("AVAL", stresn_col="ISSTRESN", lloq_col="ISLLOQ",
                   uloq_col="ISULOQ", orres_col="ISORRES")
        .to_frame()
        .adam.baseline("BASE", aval="AVAL", baseline_flag="ABLFL",
                       by=["USUBJID", "PARAMCD"])
        .to_frame()
        .adam.vaccine
        .seroconversion_flag("SRCONVFL", aval_col="AVAL", base_col="BASE",
                             lloq_col="ISLLOQ")
        .seroresponse_flag("SRSFL", aval_col="AVAL", threshold=40.0)
        .to_frame()
    )
"""

from __future__ import annotations

from typing import Literal, Self

import polars as pl

from fleet.adam._mixins import SharedADaMVerbsMixin
from fleet.core.exceptions import DerivationError


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
        inclusive: bool = True,
        flag_value: str = "Y",
    ) -> Self:
        """
        Set *target* to *flag_value* when *temp_col* is at or above *threshold*.

        The default 38.0 °C is the start of grade 1 fever on the FDA 2007
        toxicity grading scale, so a record of exactly 38.0 °C gets the flag.
        ``inclusive=False`` flags strictly above *threshold*, for a SAP limit
        such as FDA grade 4 (> 40.0 °C).  With ``inclusive=False`` and the
        default threshold, a record of 38.0 °C gets no flag.

        Examples:
            Flag fever, and grade 4 fever::

                adface = (
                    vs_df.adam.vaccine
                    .fever_flag("FEVFL", temp_col="TEMP")
                    .fever_flag("G4FEVFL", temp_col="TEMP", threshold=40.0, inclusive=False)
                    .to_frame()
                )

        References:
            FDA, Guidance for Industry: Toxicity Grading Scale for Healthy Adult and
            Adolescent Volunteers Enrolled in Preventive Vaccine Clinical Trials
            (2007): grade 1 fever starts at 38.0 °C; grade 4 is > 40 °C. Brighton
            Collaboration fever case definition (Marcy SM et al. Vaccine.
            2004;22:551-556): >= 38.0 °C. admiralvaccine ``derive_fever_records``:
            VSSTRESN >= 38. ADR-0027.
        """
        temp = pl.col(temp_col)
        return self._chain(
            pl.when(temp >= threshold if inclusive else temp > threshold)
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
        lloq_col: str | None,
        fold_rise: float = 4.0,
        seronegative_fold: float | None = None,
        flag_value: str = "Y",
    ) -> Self:
        """
        Flag seroconversion: a *fold_rise* rise from baseline, with an LLOQ rule.

        *lloq_col* has no default, so the call states the rule of the SAP:

        - ``lloq_col="ISLLOQ"`` (two-arm rule, FDA CBER 2007): when BASE is
          below the LLOQ, the flag needs ``AVAL >= seronegative_fold × LLOQ``
          (HI: pre < 1:10 needs post >= 1:40); when BASE is at or above the
          LLOQ, it needs ``AVAL >= fold_rise × BASE``.  Null when AVAL, BASE
          or the LLOQ is null.  *lloq_col* must hold the LLOQ of the baseline
          record.
        - ``lloq_col=None`` (plain ratio): ``AVAL / BASE >= fold_rise``, for a
          SAP that states the ratio only.  Null when BASE is null or zero.

        Rows that do not meet the rule get null.

        Examples:
            Seroconversion with the LLOQ rule, and a two-fold rise::

                adis = (
                    is_df.adam.vaccine
                    .seroconversion_flag("SRCONVFL", aval_col="AVAL", base_col="BASE",
                                         lloq_col="ISLLOQ")
                    .seroconversion_flag("SRCONV2FL", aval_col="AVAL", base_col="BASE",
                                         lloq_col=None, fold_rise=2.0)
                    .to_frame()
                )

        References:
            FDA CBER, Guidance for Industry: Clinical Data Needed to Support the
            Licensure of Seasonal Inactivated Influenza Vaccines (2007): seroconversion
            is a pre-vaccination HI titre < 1:10 and a post-vaccination titre
            >= 1:40, or a pre-vaccination titre >= 1:10 and a >= 4-fold rise. EMA
            CHMP, CPMP/BWP/214/96, states the same criterion. Some SAPs use the
            plain ratio. ADR-0027.
        """
        aval = pl.col(aval_col)
        base = pl.col(base_col)
        if lloq_col is None:
            met = base.is_not_null() & (base != 0) & (aval / base >= fold_rise)
        else:
            lloq = pl.col(lloq_col)
            neg_fold = fold_rise if seronegative_fold is None else seronegative_fold
            met = (
                pl.when(aval.is_null() | base.is_null() | lloq.is_null())
                .then(pl.lit(False))
                .when(base < lloq)
                .then(aval >= neg_fold * lloq)
                .otherwise(aval >= fold_rise * base)
            )
        return self._chain(
            pl.when(met).then(pl.lit(flag_value)).otherwise(pl.lit(None)).alias(target)
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

        Examples:
            Flag a titre of 40 or more::

                adis = (
                    is_df.adam.vaccine
                    .seroresponse_flag("SRSFL", aval_col="AVAL", threshold=40.0)
                    .to_frame()
                )
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
        lloq_rule: Literal["half", "lloq"] = "half",
        round_digits: int | None = None,
    ) -> Self:
        """
        Derive ``AVAL`` for the ADIS domain following limit-of-quantification rules.

        Rules (based on ``admiralvaccine::derive_var_aval_adis``):

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
        Any other text raises ``DerivationError``.

        Examples:
            ADIS AVAL with the LLOQ and ULOQ rules::

                adis = (
                    is_df.adam.vaccine
                    .aval_adis("AVAL", stresn_col="ISSTRESN",
                               lloq_col="ISLLOQ", uloq_col="ISULOQ",
                               orres_col="ISORRES")
                    .to_frame()
                )

        References:
            admiralvaccine ``derive_var_aval_adis`` (pharmaverse): the rule set this
            verb is based on. No CDISC standard fixes the LLOQ/2 imputation; it is an
            analysis convention. Check the SAP for the rule in force.
        """
        if lloq_rule not in ("half", "lloq"):
            raise DerivationError(
                f"aval_adis: lloq_rule={lloq_rule!r} is not supported. Use 'half' or 'lloq'."
            )
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
        by: list[str],
        severity_col: str | None = "AVALC",
        severity_values: list[str] | None = None,
        flag_value: str = "Y",
        no_event_value: str = "N",
    ) -> Self:
        """
        Flag whether a reactogenicity event occurred at least once per *by* group.

        A record has an event if *aval_col* > *cutoff*, or *severity_col* is
        in *severity_values* (default ``["Y", "MILD", "MODERATE", "SEVERE"]``;
        ``[]`` means no value counts).  Every record of a group with an event
        gets *flag_value*.  In a group with no event, a record gets
        *no_event_value* when it shows no event (*aval_col* <= *cutoff*, or
        *severity_col* is ``"N"``), and null when it has no assessable data
        (both missing).  So a diary with only missing records gets null, not
        *no_event_value*.

        *by* has no default: one event must not spread to the other FAOBJ or
        ATPTREF of the subject.  ``severity_col=None`` uses *aval_col* only.

        Materialises the current pipeline.

        Based on ``admiralvaccine::derive_vars_event_flag`` (new_var1 behaviour).

        Examples:
            Flag any event per subject, object and time point::

                adface = (
                    face_df.adam.vaccine
                    .event_flag("EVENTFL", aval_col="AVAL", cutoff=2.5,
                                by=["USUBJID", "FAOBJ", "ATPTREF"])
                    .to_frame()
                )

        References:
            admiralvaccine ``derive_vars_event_flag`` (pharmaverse), ``new_var1``:
            AVALC in Y, MILD, MODERATE, SEVERE; no default ``by_vars``; a record
            with missing AVAL and AVALC gets NA. FDA toxicity grading scale (2007)
            for the severity grades. ADR-0027.
        """
        sev_vals = (
            ["Y", "MILD", "MODERATE", "SEVERE"] if severity_values is None else severity_values
        )
        aval = pl.col(aval_col)
        row_event = aval > cutoff
        row_no_event = aval <= cutoff
        if severity_col is not None:
            sev = pl.col(severity_col)
            row_event = row_event | sev.is_in(sev_vals).fill_null(False)
            row_no_event = row_no_event | (sev == "N").fill_null(False)

        # Kleene any, as R any(): True, else null when a record is unknown, else False.
        any_event = row_event.any(ignore_nulls=False).over(by)
        return self._chain(
            pl.when(any_event)
            .then(pl.lit(flag_value))
            .when(row_no_event)
            .then(pl.lit(no_event_value))
            .otherwise(pl.lit(None, dtype=pl.String))
            .alias(target),
            verb="event_flag",
        )
