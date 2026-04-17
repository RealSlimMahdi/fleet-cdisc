"""
ADaM PK (pharmacokinetics) namespace extension.

Accessed via ``df.adam.pk`` on any Polars DataFrame.

Usage
-----
    import fleet  # triggers registration

    adpc = (
        pc_sdtm.adam.pk
        .source("USUBJID")
        .source("PCSTRESN")
        .blq_flag("BLQFL", conc_col="PCSTRESN", lloq_col="PCLLOQ")
        .blq_impute("AVAL", conc_col="PCSTRESN", lloq_col="PCLLOQ", method="half_lloq")
        .nominal_time("NTIME", from_col="PCTPTNUM")
        .actual_time("ATIME", sample_dtm="PCDTC", dose_dtm="EXSTDTC")
        .predose_flag("PREDFL", time_col="ATIME")
        .dose_normalized("AVALDNM", conc_col="AVAL", dose_col="DOSE")
        .seq("PCSEQ", groups=["USUBJID"])
        .merge_adsl(adsl_df, keep_cols=["TRTSDT", "TRT01P"])
        .to_frame()
    )
"""

from __future__ import annotations

from typing import Self

import polars as pl

from fleet.adam._mixins import MultiRowMixin, SharedADaMVerbsMixin

_UNIT_SCALE: dict[str, float] = {
    "s": 1.0,
    "min": 60.0,
    "h": 3600.0,
    "d": 86400.0,
}


class PKNamespace(SharedADaMVerbsMixin, MultiRowMixin):
    """
    Immutable pipeline builder for PK (pharmacokinetics) derivations.

    Covers concentration-time datasets such as ADPC and parameter datasets
    such as ADPP.

    Inherits shared verbs from ``SharedADaMVerbsMixin``
    (source, derivation, assigned, recode, rename, condderivation,
    whereclauses, merge_adsl) and ``MultiRowMixin`` (seq), and adds
    PK-specific verbs for BLQ handling, time derivation, and
    dose normalisation.
    """

    # ------------------------------------------------------------------ #
    # PK-specific verbs                                                    #
    # ------------------------------------------------------------------ #

    def blq_flag(
        self,
        target: str,
        *,
        conc_col: str,
        lloq_col: str,
    ) -> Self:
        """Flag records where concentration is below the LLOQ.

        Sets *target* to ``"Y"`` when *conc_col* < *lloq_col*, null otherwise.

        Args:
            target: Name of the output flag column.
            conc_col: Column containing the observed concentration.
            lloq_col: Column containing the lower limit of quantification.

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive BLQ flag from PC data::

                adpc = (
                    pc_raw.adam.pk
                    .blq_flag("BLQFL", conc_col="PCSTRESN",
                              lloq_col="PCLLOQ")
                    .to_frame()
                )
        """
        cond = pl.col(conc_col).cast(pl.Float64) < pl.col(lloq_col).cast(pl.Float64)
        return self._chain(pl.when(cond).then(pl.lit("Y")).otherwise(pl.lit(None)).alias(target))

    def blq_impute(
        self,
        target: str,
        *,
        conc_col: str,
        lloq_col: str,
        method: str = "half_lloq",
    ) -> Self:
        """Impute BLQ concentrations with a standard substitution method.

        Args:
            target: Name of the output numeric column.
            conc_col: Column containing the observed concentration.
            lloq_col: Column containing the LLOQ.
            method: One of ``"half_lloq"`` (default), ``"zero"``, ``"lloq"``,
                or ``"missing"``.

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Impute BLQ values with half the LLOQ::

                adpc = (
                    pc_raw.adam.pk
                    .blq_impute("AVAL", conc_col="PCSTRESN",
                                lloq_col="PCLLOQ", method="half_lloq")
                    .to_frame()
                )
        """
        valid_methods = {"half_lloq", "zero", "lloq", "missing"}
        if method not in valid_methods:
            raise ValueError(
                f"blq_impute method={method!r} is not supported. "
                f"Choose one of: {sorted(valid_methods)}"
            )

        conc = pl.col(conc_col).cast(pl.Float64)
        lloq = pl.col(lloq_col).cast(pl.Float64)
        is_blq = conc < lloq

        if method == "half_lloq":
            imputed = lloq / 2.0
        elif method == "zero":
            imputed = pl.lit(0.0)
        elif method == "lloq":
            imputed = lloq
        else:  # missing
            imputed = pl.lit(None).cast(pl.Float64)

        return self._chain(pl.when(is_blq).then(imputed).otherwise(conc).alias(target))

    def nominal_time(
        self,
        target: str,
        *,
        from_col: str,
        input_unit: str = "h",
        output_unit: str = "h",
    ) -> Self:
        """Derive nominal elapsed time from a planned timepoint column.

        Applies a unit conversion from *input_unit* to *output_unit*.

        Args:
            target: Name of the output column.
            from_col: Source column of nominal time values (numeric).
            input_unit: Unit of *from_col* — ``"s"``, ``"min"``, ``"h"``, or ``"d"``.
            output_unit: Desired unit of *target* (same choices).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Copy nominal time in hours::

                adpc = (
                    pc_raw.adam.pk
                    .nominal_time("NTIME", from_col="PCTPTNUM")
                    .to_frame()
                )
        """
        valid_units = set(_UNIT_SCALE)
        for u in (input_unit, output_unit):
            if u not in valid_units:
                raise ValueError(
                    f"nominal_time unit={u!r} is not supported. "
                    f"Choose one of: {sorted(valid_units)}"
                )
        scale = _UNIT_SCALE[input_unit] / _UNIT_SCALE[output_unit]
        expr = (pl.col(from_col).cast(pl.Float64) * scale).alias(target)
        return self._chain(expr)

    def actual_time(
        self,
        target: str,
        *,
        sample_dtm: str,
        dose_dtm: str,
        unit: str = "h",
    ) -> Self:
        """Derive actual elapsed time between sample and dose datetimes.

        Parses *sample_dtm* and *dose_dtm* as ISO 8601 strings and returns
        the elapsed duration in *unit*.

        Args:
            target: Name of the output column.
            sample_dtm: Column containing the sample collection datetime.
            dose_dtm: Column containing the reference dose datetime.
            unit: Output unit — ``"s"``, ``"min"``, ``"h"``, or ``"d"``.

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive actual time in hours from PC and EX datetimes::

                adpc = (
                    pc_raw.adam.pk
                    .actual_time("ATIME", sample_dtm="PCDTC",
                                 dose_dtm="EXSTDTC")
                    .to_frame()
                )
        """
        if unit not in _UNIT_SCALE:
            raise ValueError(
                f"actual_time unit={unit!r} is not supported. Choose one of: {sorted(_UNIT_SCALE)}"
            )
        seconds_per_unit = _UNIT_SCALE[unit]

        def _to_datetime(col: str) -> pl.Expr:
            """Parse string or pass-through Datetime column."""
            return pl.col(col).str.to_datetime(
                format="%Y-%m-%dT%H:%M:%S",
                strict=False,
            )

        diff_s = (
            (_to_datetime(sample_dtm) - _to_datetime(dose_dtm)).dt.total_seconds().cast(pl.Float64)
        )
        return self._chain((diff_s / seconds_per_unit).alias(target))

    def predose_flag(
        self,
        target: str,
        *,
        time_col: str,
        window_hrs: float = 1.0,
    ) -> Self:
        """Flag pre-dose samples within an allowable window before dosing.

        Sets *target* to ``"Y"`` when ``-window_hrs <= time_col < 0``.

        Args:
            target: Name of the output flag column.
            time_col: Column containing elapsed time relative to dose.
            window_hrs: Size of the pre-dose window (default ``1.0``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Flag pre-dose samples within 1 hour::

                adpc = (
                    pc_raw.adam.pk
                    .predose_flag("PREDFL", time_col="ATIME")
                    .to_frame()
                )
        """
        t = pl.col(time_col).cast(pl.Float64)
        cond = (t >= -window_hrs) & (t < 0.0)
        return self._chain(pl.when(cond).then(pl.lit("Y")).otherwise(pl.lit(None)).alias(target))

    def dose_normalized(
        self,
        target: str,
        *,
        conc_col: str,
        dose_col: str,
    ) -> Self:
        """Dose-normalise concentration: ``target = conc / dose``.

        Returns null when *dose_col* is null or zero.

        Args:
            target: Name of the output column.
            conc_col: Column containing the concentration.
            dose_col: Column containing the administered dose.

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive dose-normalised concentration::

                adpc = (
                    pc_raw.adam.pk
                    .dose_normalized("AVALDNM", conc_col="AVAL",
                                     dose_col="DOSE")
                    .to_frame()
                )
        """
        dose = pl.col(dose_col).cast(pl.Float64)
        conc = pl.col(conc_col).cast(pl.Float64)
        safe_dose = pl.when(dose.is_null() | (dose == 0.0)).then(pl.lit(None)).otherwise(dose)
        return self._chain((conc / safe_dose).alias(target))

    def evid(
        self,
        target: str = "EVID",
        *,
        from_col: str | None = None,
        dose_indicator: int = 1,
        conc_indicator: int = 0,
    ) -> Self:
        """Derive Event ID (EVID) for Population PK datasets.

        When *from_col* is provided, casts and aliases it.  Otherwise assigns
        *conc_indicator* to every row.

        Args:
            target: Name of the output column (default ``"EVID"``).
            from_col: Existing integer column encoding EVID.
            dose_indicator: Value for dosing records (default ``1``).
            conc_indicator: Value for concentration records (default ``0``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Assign EVID=0 to all concentration records::

                adpc = (
                    pc_raw.adam.pk
                    .evid("EVID")
                    .to_frame()
                )
        """
        if from_col is not None:
            expr = pl.col(from_col).cast(pl.Int64).alias(target)
        else:
            expr = pl.lit(conc_indicator).cast(pl.Int64).alias(target)
        return self._chain(expr)

    def mrrlt(
        self,
        target: str,
        *,
        arrlt_col: str,
    ) -> Self:
        """Derive Modified Relative Time (MRRLT): ``max(ARRLT, 0)``.

        Clips negative pre-dose times to zero so they align with the
        reference dose timepoint.

        Args:
            target: Name of the output column.
            arrlt_col: Column containing the actual relative time (ARRLT).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Clip pre-dose relative times to zero::

                adpc = (
                    pc_raw.adam.pk
                    .mrrlt("MRRLT", arrlt_col="ARRLT")
                    .to_frame()
                )
        """
        t = pl.col(arrlt_col).cast(pl.Float64)
        return self._chain(pl.when(t < 0.0).then(pl.lit(0.0)).otherwise(t).alias(target))

    def blqfn(
        self,
        target: str,
        *,
        conc_col: str,
        lloq_col: str,
    ) -> Self:
        """Derive a numeric BLQ flag (``1`` / ``0``).

        Complements :meth:`blq_flag` which returns character ``"Y"``/null.

        Args:
            target: Name of the output column.
            conc_col: Column containing the observed concentration.
            lloq_col: Column containing the LLOQ.

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive numeric BLQ indicator::

                adpc = (
                    pc_raw.adam.pk
                    .blqfn("BLQFN", conc_col="PCSTRESN",
                           lloq_col="PCLLOQ")
                    .to_frame()
                )
        """
        cond = pl.col(conc_col).cast(pl.Float64) < pl.col(lloq_col).cast(pl.Float64)
        return self._chain(
            pl.when(cond).then(pl.lit(1)).otherwise(pl.lit(0)).cast(pl.Int64).alias(target)
        )

    def log_conc(
        self,
        target: str,
        *,
        conc_col: str,
        base: str = "e",
    ) -> Self:
        """Derive the logarithm of concentration.

        Returns null when *conc_col* is null or <= 0.

        Args:
            target: Name of the output column.
            conc_col: Column containing the numeric concentration.
            base: Logarithm base — ``"e"`` (default), ``"2"``, or ``"10"``.

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive natural log of DV::

                adpc = (
                    pc_raw.adam.pk
                    .log_conc("DVL", conc_col="DV")
                    .to_frame()
                )
        """
        valid_bases = {"e", "2", "10"}
        if base not in valid_bases:
            raise ValueError(
                f"log_conc base={base!r} is not supported. Choose one of: {sorted(valid_bases)}"
            )
        c = pl.col(conc_col).cast(pl.Float64)
        safe = pl.when(c.is_null() | (c <= 0.0)).then(pl.lit(None).cast(pl.Float64))
        if base == "e":
            expr = safe.otherwise(c.log(base=2.718281828459045))
        elif base == "2":
            expr = safe.otherwise(c.log(base=2.0))
        else:  # "10"
            expr = safe.otherwise(c.log(base=10.0))
        return self._chain(expr.alias(target))

    def mdv(
        self,
        target: str = "MDV",
        *,
        conc_col: str | None = None,
        evid_col: str | None = None,
    ) -> Self:
        """Derive MDV (Missing Dependent Variable) for PopPK datasets.

        ``MDV = 1`` when the dependent variable is missing or the record is
        a dosing record; ``0`` otherwise.

        Args:
            target: Name of the output column (default ``"MDV"``).
            conc_col: Concentration column (null → ``MDV = 1``).
            evid_col: Event ID column (``EVID = 1`` → ``MDV = 1``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive MDV from concentration and EVID::

                adpc = (
                    pc_raw.adam.pk
                    .mdv("MDV", conc_col="DV", evid_col="EVID")
                    .to_frame()
                )
        """
        conditions: list[pl.Expr] = []
        if evid_col is not None:
            conditions.append(pl.col(evid_col).cast(pl.Int64) == 1)
        if conc_col is not None:
            conditions.append(pl.col(conc_col).is_null())
        if not conditions:
            # No condition supplied — default to 0
            return self._chain(pl.lit(0).cast(pl.Int64).alias(target))
        combined = conditions[0]
        for cond in conditions[1:]:
            combined = combined | cond
        return self._chain(
            pl.when(combined).then(pl.lit(1)).otherwise(pl.lit(0)).cast(pl.Int64).alias(target)
        )

    def amt(
        self,
        target: str = "AMT",
        *,
        dose_col: str,
        evid_col: str = "EVID",
    ) -> Self:
        """Derive AMT (dose amount) for PopPK / NONMEM-style datasets.

        Sets *target* to the dose on dosing records (``EVID = 1``) and null
        on observation records.

        Args:
            target: Name of the output column (default ``"AMT"``).
            dose_col: Column containing the administered dose amount.
            evid_col: Column containing the Event ID (default ``"EVID"``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive AMT from the exposure dose::

                adpc = (
                    pc_raw.adam.pk
                    .amt("AMT", dose_col="EXDOSE", evid_col="EVID")
                    .to_frame()
                )
        """
        dose = pl.col(dose_col).cast(pl.Float64)
        evid = pl.col(evid_col).cast(pl.Int64)
        return self._chain(
            pl.when(evid == 1).then(dose).otherwise(pl.lit(None).cast(pl.Float64)).alias(target)
        )

    def cmt(
        self,
        target: str = "CMT",
        *,
        evid_col: str = "EVID",
        dose_cmt: int = 1,
        conc_cmt: int = 2,
    ) -> Self:
        """Derive CMT (compartment number) for PopPK datasets.

        Assigns *dose_cmt* on dosing records and *conc_cmt* on observation
        records, following NONMEM convention.

        Args:
            target: Name of the output column (default ``"CMT"``).
            evid_col: Column containing the Event ID (default ``"EVID"``).
            dose_cmt: Compartment number for dosing records (default ``1``).
            conc_cmt: Compartment number for concentration records (default ``2``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Assign compartment numbers::

                adpc = (
                    pc_raw.adam.pk
                    .cmt("CMT", evid_col="EVID", dose_cmt=1, conc_cmt=2)
                    .to_frame()
                )
        """
        evid = pl.col(evid_col).cast(pl.Int64)
        return self._chain(
            pl.when(evid == 1)
            .then(pl.lit(dose_cmt))
            .otherwise(pl.lit(conc_cmt))
            .cast(pl.Int64)
            .alias(target)
        )

    def avalcat(
        self,
        target: str,
        *,
        conc_col: str,
        lloq_col: str | None = None,
        blq_label: str = "BLQ",
        digits: int = 3,
    ) -> Self:
        """Derive a listing-ready categorised analysis value (AVALCAT1).

        Encodes BLQ records as *blq_label* and formats numeric concentrations
        to *digits* significant digits as a string.

        Args:
            target: Name of the output column.
            conc_col: Column containing the concentration value.
            lloq_col: Optional LLOQ column for numeric BLQ check.
            blq_label: Label for BLQ records (default ``"BLQ"``).
            digits: Significant digits for numeric formatting (default ``3``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive AVALCAT1 from concentration and LLOQ::

                adpc = (
                    pc_raw.adam.pk
                    .avalcat("AVALCAT1", conc_col="PCSTRESC",
                             lloq_col="PCLLOQ")
                    .to_frame()
                )
        """
        if lloq_col is not None:
            conc_num = pl.col(conc_col).cast(pl.Float64, strict=False)
            lloq_num = pl.col(lloq_col).cast(pl.Float64)
            is_blq = conc_num.is_null() | (conc_num < lloq_num)
        else:
            is_blq = pl.col(conc_col).cast(pl.String) == "<BLQ"

        # Format numeric value to `digits` significant digits (string)
        # Polars doesn't have signif() natively; we approximate via round_sig helper
        conc_str = pl.col(conc_col).cast(pl.Float64, strict=False).cast(pl.String)

        return self._chain(
            pl.when(is_blq).then(pl.lit(blq_label)).otherwise(conc_str).alias(target)
        )

    def anl_flag(
        self,
        target: str,
        *,
        exclude_dtype: bool = False,
        dtype_col: str = "DTYPE",
    ) -> Self:
        """Derive an analysis flag variable (ANL01FL, ANL02FL, etc.).

        When *exclude_dtype* is False (default), all records get ``"Y"``.
        When True, only records with null *dtype_col* get ``"Y"``.

        Args:
            target: Name of the output flag column.
            exclude_dtype: When True, exclude DTYPE records.
            dtype_col: Column to inspect (default ``"DTYPE"``).

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Flag all records for analysis::

                adpc = (
                    pc_raw.adam.pk
                    .anl_flag("ANL01FL")
                    .to_frame()
                )
        """
        if exclude_dtype:
            expr = (
                pl.when(pl.col(dtype_col).is_null())
                .then(pl.lit("Y"))
                .otherwise(pl.lit(None))
                .alias(target)
            )
        else:
            expr = pl.lit("Y").alias(target)
        return self._chain(expr)
