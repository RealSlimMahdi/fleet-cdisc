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

from ._mixins import MultiRowMixin, SharedADaMVerbsMixin

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
        """
        Flag records where the concentration is below the limit of quantification.

        Sets *target* to ``"Y"`` when *conc_col* < *lloq_col*, otherwise ``null``.

        Parameters
        ----------
        conc_col:
            Column containing the observed concentration value.
        lloq_col:
            Column containing the lower limit of quantification (LLOQ).

        Example::

            .blq_flag("BLQFL", conc_col="PCSTRESN", lloq_col="PCLLOQ")
        """
        cond = pl.col(conc_col).cast(pl.Float64) < pl.col(lloq_col).cast(pl.Float64)
        return self._chain(
            pl.when(cond)
            .then(pl.lit("Y"))
            .otherwise(pl.lit(None))
            .alias(target)
        )

    def blq_impute(
        self,
        target: str,
        *,
        conc_col: str,
        lloq_col: str,
        method: str = "half_lloq",
    ) -> Self:
        """
        Impute BLQ concentrations with a standard substitution method.

        Sets *target* to the imputed (or original) numeric concentration.

        Parameters
        ----------
        conc_col:
            Column containing the observed concentration value.
        lloq_col:
            Column containing the LLOQ.
        method:
            One of:

            * ``"half_lloq"`` (default) — replace BLQ with ``LLOQ / 2``
            * ``"zero"``                — replace BLQ with ``0``
            * ``"lloq"``               — replace BLQ with ``LLOQ``
            * ``"missing"``            — replace BLQ with ``null``

        Example::

            .blq_impute("AVAL", conc_col="PCSTRESN", lloq_col="PCLLOQ")
            .blq_impute("AVAL", conc_col="PCSTRESN", lloq_col="PCLLOQ", method="zero")
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

        return self._chain(
            pl.when(is_blq).then(imputed).otherwise(conc).alias(target)
        )

    def nominal_time(
        self,
        target: str,
        *,
        from_col: str,
        input_unit: str = "h",
        output_unit: str = "h",
    ) -> Self:
        """
        Derive nominal elapsed time from a planned timepoint column (e.g. ``PCTPTNUM``).

        Applies a unit conversion from *input_unit* to *output_unit*.

        Parameters
        ----------
        from_col:
            Source column of nominal planned time values (numeric).
        input_unit:
            Unit of *from_col* values.  One of ``"s"``, ``"min"``, ``"h"``, ``"d"``.
        output_unit:
            Desired unit of *target*.  Same choices as *input_unit*.

        Example::

            .nominal_time("NTIME", from_col="PCTPTNUM")
            .nominal_time("NTIME", from_col="PCTPTNUM", input_unit="h", output_unit="d")
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
        """
        Derive actual elapsed time as the difference between two datetime columns.

        Parses *sample_dtm* and *dose_dtm* as ISO 8601 datetime strings (or
        ``pl.Datetime`` columns) and returns the elapsed duration in *unit*.

        Parameters
        ----------
        sample_dtm:
            Column containing the sample collection datetime.
        dose_dtm:
            Column containing the reference dose datetime.
        unit:
            Output unit.  One of ``"s"``, ``"min"``, ``"h"``, ``"d"``.

        Example::

            .actual_time("ATIME", sample_dtm="PCDTC", dose_dtm="EXSTDTC")
            .actual_time("ATIME", sample_dtm="PCDTC", dose_dtm="EXSTDTC", unit="min")
        """
        if unit not in _UNIT_SCALE:
            raise ValueError(
                f"actual_time unit={unit!r} is not supported. "
                f"Choose one of: {sorted(_UNIT_SCALE)}"
            )
        seconds_per_unit = _UNIT_SCALE[unit]

        def _to_datetime(col: str) -> pl.Expr:
            """Parse string or pass-through Datetime column."""
            return pl.col(col).str.to_datetime(
                format="%Y-%m-%dT%H:%M:%S",
                strict=False,
            )

        diff_s = (
            (_to_datetime(sample_dtm) - _to_datetime(dose_dtm))
            .dt.total_seconds()
            .cast(pl.Float64)
        )
        return self._chain((diff_s / seconds_per_unit).alias(target))

    def predose_flag(
        self,
        target: str,
        *,
        time_col: str,
        window_hrs: float = 1.0,
    ) -> Self:
        """
        Flag pre-dose samples within an allowable window before dosing.

        Sets *target* to ``"Y"`` when ``-window_hrs <= time_col < 0``, else ``null``.
        Typically applied after :meth:`actual_time` has been derived.

        Parameters
        ----------
        time_col:
            Column containing the elapsed time relative to dose (hours or
            the same unit chosen in :meth:`actual_time`).
        window_hrs:
            Size of the pre-dose window in the same unit as *time_col*
            (default ``1.0``).

        Example::

            .predose_flag("PREDFL", time_col="ATIME")
            .predose_flag("PREDFL", time_col="ATIME", window_hrs=2.0)
        """
        t = pl.col(time_col).cast(pl.Float64)
        cond = (t >= -window_hrs) & (t < 0.0)
        return self._chain(
            pl.when(cond)
            .then(pl.lit("Y"))
            .otherwise(pl.lit(None))
            .alias(target)
        )

    def dose_normalized(
        self,
        target: str,
        *,
        conc_col: str,
        dose_col: str,
    ) -> Self:
        """
        Dose-normalise concentration: ``target = conc / dose``.

        Returns ``null`` when *dose_col* is null or zero to avoid division errors.

        Parameters
        ----------
        conc_col:
            Column containing the concentration (e.g. ``"AVAL"``).
        dose_col:
            Column containing the administered dose (e.g. ``"DOSE"``).

        Example::

            .dose_normalized("AVALDNM", conc_col="AVAL", dose_col="DOSE")
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
        """
        Derive Event ID (``EVID``) — a standard Population PK variable.

        If *from_col* is provided the column is cast to ``Int64`` and aliased;
        this supports datasets that were built by stacking concentration and
        dosing records (concentration records ``EVID=0``, dosing records
        ``EVID=1``).

        When *from_col* is ``None`` the verb assigns *conc_indicator* to every
        row — useful when the frame already contains only concentration records
        and the dosing rows will be appended later.

        Parameters
        ----------
        from_col:
            Existing integer column that encodes EVID.  When provided the
            column is simply cast and aliased.
        dose_indicator:
            Integer value that marks dosing records (default ``1``).
        conc_indicator:
            Integer value that marks concentration records (default ``0``).

        Example::

            # Assign EVID=0 to every row (pure concentration dataset)
            .evid("EVID")

            # Re-use an existing flag column
            .evid("EVID", from_col="IS_DOSE_ROW")
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
        """
        Derive Modified Relative Time from Reference Dose (``MRRLT``).

        Clips negative *arrlt_col* values to zero: ``MRRLT = max(ARRLT, 0)``.
        Pre-dose records that have a negative actual relative time are set to
        ``0`` so they align with the reference dose timepoint.

        Parameters
        ----------
        arrlt_col:
            Column containing the Actual Relative Time from Reference Dose
            (``ARRLT``), typically derived via :meth:`actual_time`.

        Example::

            .mrrlt("MRRLT", arrlt_col="ARRLT")
        """
        t = pl.col(arrlt_col).cast(pl.Float64)
        return self._chain(
            pl.when(t < 0.0).then(pl.lit(0.0)).otherwise(t).alias(target)
        )

    def blqfn(
        self,
        target: str,
        *,
        conc_col: str,
        lloq_col: str,
    ) -> Self:
        """
        Derive a **numeric** BLQ flag (``BLQFN``).

        Sets *target* to ``1`` when *conc_col* < *lloq_col*, otherwise ``0``.
        Complements :meth:`blq_flag` which returns a character ``"Y"``/null.

        Parameters
        ----------
        conc_col:
            Column containing the observed concentration value.
        lloq_col:
            Column containing the LLOQ.

        Example::

            .blqfn("BLQFN", conc_col="PCSTRESN", lloq_col="PCLLOQ")
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
        """
        Derive the logarithm of concentration (e.g. ``DVL`` in ADPPK).

        Returns ``null`` when *conc_col* is ``null`` or ``≤ 0`` to avoid
        undefined results.

        Parameters
        ----------
        conc_col:
            Column containing the numeric concentration (e.g. ``"DV"``).
        base:
            Logarithm base: ``"e"`` (natural, default), ``"2"``, or ``"10"``.

        Example::

            .log_conc("DVL", conc_col="DV")
            .log_conc("DVL", conc_col="DV", base="10")
        """
        valid_bases = {"e", "2", "10"}
        if base not in valid_bases:
            raise ValueError(
                f"log_conc base={base!r} is not supported. "
                f"Choose one of: {sorted(valid_bases)}"
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
        """
        Derive ``MDV`` (Missing Dependent Variable) for Population PK datasets.

        NONMEM / PopPK convention: ``MDV = 1`` when the dependent variable is
        missing or the record is a dosing record; ``MDV = 0`` otherwise.

        * If *evid_col* is supplied every dosing record (``EVID = 1``) gets
          ``MDV = 1``.
        * If *conc_col* is supplied every row with a null concentration gets
          ``MDV = 1``.
        * Both conditions can be combined (logical OR).

        Parameters
        ----------
        conc_col:
            Column containing the concentration value (``DV`` or ``AVAL``).
        evid_col:
            Column containing the Event ID flag (``EVID``).

        Example::

            .mdv("MDV", conc_col="DV", evid_col="EVID")
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
        """
        Derive ``AMT`` (dose amount) for Population PK / NONMEM-style datasets.

        Sets *target* to *dose_col* value on dosing records (``EVID = 1``) and
        to ``null`` on observation records (``EVID = 0``).

        Parameters
        ----------
        dose_col:
            Column containing the administered dose amount (e.g. ``"EXDOSE"``).
        evid_col:
            Column containing the Event ID (default ``"EVID"``).

        Example::

            .amt("AMT", dose_col="EXDOSE", evid_col="EVID")
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
        """
        Derive ``CMT`` (compartment number) for Population PK datasets.

        Assigns *dose_cmt* on dosing records and *conc_cmt* on observation
        records, following NONMEM convention.

        Parameters
        ----------
        evid_col:
            Column containing the Event ID (default ``"EVID"``).
        dose_cmt:
            Compartment number for dosing records (default ``1``).
        conc_cmt:
            Compartment number for concentration records (default ``2``).

        Example::

            .cmt("CMT", evid_col="EVID", dose_cmt=1, conc_cmt=2)
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
        """
        Derive a listing-ready categorised analysis value (``AVALCAT1``).

        Encodes BLQ records as *blq_label* and formats numeric concentrations
        to *digits* significant digits as a string, matching admiral's
        ``AVALCAT1`` derivation.

        Parameters
        ----------
        conc_col:
            Column containing the raw concentration string or numeric value.
            When equal to ``"<BLQ"`` (or null when *lloq_col* is provided for
            comparison) the BLQ label is used.
        lloq_col:
            Optional LLOQ column.  When provided the BLQ check uses
            ``conc < LLOQ`` on the cast numeric value. When ``None`` the column
            is treated as a string and ``"<BLQ"`` values are flagged.
        blq_label:
            Label for BLQ records (default ``"BLQ"``).
        digits:
            Number of significant digits for numeric formatting (default ``3``).

        Example::

            .avalcat("AVALCAT1", conc_col="PCSTRESC", lloq_col="PCLLOQ")
            .avalcat("AVALCAT1", conc_col="AVAL", lloq_col="PCLLOQ", digits=3)
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
            pl.when(is_blq)
            .then(pl.lit(blq_label))
            .otherwise(conc_str)
            .alias(target)
        )

    def anl_flag(
        self,
        target: str,
        *,
        exclude_dtype: bool = False,
        dtype_col: str = "DTYPE",
    ) -> Self:
        """
        Derive an analysis flag variable (``ANL01FL``, ``ANL02FL``, etc.).

        * When *exclude_dtype* is ``False`` (default): sets *target* to
          ``"Y"`` for **all** records — equivalent to admiral's ``ANL01FL``.
        * When *exclude_dtype* is ``True``: sets *target* to ``"Y"`` only for
          records where *dtype_col* is null (i.e. excludes ``"COPY"`` or
          ``"HALFLLOQ"`` records) — equivalent to admiral's ``ANL02FL``.

        Parameters
        ----------
        exclude_dtype:
            When ``True``, ``"Y"`` is only assigned to non-DTYPE records.
        dtype_col:
            The ``DTYPE`` column to inspect when *exclude_dtype* is ``True``
            (default ``"DTYPE"``).

        Example::

            .anl_flag("ANL01FL")                            # all records
            .anl_flag("ANL02FL", exclude_dtype=True)        # non-DTYPE only
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
