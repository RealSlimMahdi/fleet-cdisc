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
        .duration("ATIME", start="EXSTDTC", end="PCDTC", unit="hours", add_one=False)
        .predose_flag("PREDFL", time_col="ATIME")
        .dose_normalized("AVALDNM", conc_col="AVAL", dose_col="DOSE")
        .seq("PCSEQ", by=["USUBJID"])
        .merge_adsl(adsl_df, keep=["TRTSDT", "TRT01P"])
        .to_frame()
    )
"""

from __future__ import annotations

from typing import Self

import polars as pl

from fleet.adam._mixins import MultiRowMixin, SharedADaMVerbsMixin
from fleet.core.exceptions import DerivationError
from fleet.sdtm.utils import to_char

_UNIT_SCALE: dict[str, float] = {
    "s": 1.0,
    "min": 60.0,
    "h": 3600.0,
    "d": 86400.0,
}

# Default BLQ texts in --STRESC; the data transfer agreement decides the real list.
BLQ_TEXT = r"(?i)^\s*(<|(BLQ|BQL|BLOQ|LLOQ)\s*$)"


class PKNamespace(SharedADaMVerbsMixin, MultiRowMixin):
    """
    Immutable pipeline builder for PK (pharmacokinetics) derivations.

    Covers concentration-time datasets such as ADPC and parameter datasets
    such as ADPP.

    Inherits shared verbs from ``SharedADaMVerbsMixin``
    (source, derivation, assign, recode, case_when,
    whereclauses, merge_adsl) and ``MultiRowMixin`` (seq), and adds
    PK-specific verbs for BLQ handling, time derivation, and
    dose normalisation.
    """

    # ------------------------------------------------------------------ #
    # PK-specific verbs                                                    #
    # ------------------------------------------------------------------ #

    def _is_blq(
        self,
        verb: str,
        conc: pl.Expr,
        lloq_col: str | None,
        text_col: str | None,
        blq_text: str,
        numeric_below_lloq: bool,
    ) -> pl.Expr:
        """BLQ on positive evidence: a number below the LLOQ, or no number and a BLQ text."""
        parts: list[pl.Expr] = []
        if numeric_below_lloq and lloq_col is not None:
            parts.append((conc < pl.col(lloq_col).cast(pl.Float64)).fill_null(False))
        if text_col is not None:
            if text_col not in self._lazy.collect_schema().names():
                raise DerivationError(
                    f"{verb}: text_col={text_col!r} is not in the frame. SDTM keeps a BLQ "
                    "result only as text in --STRESC; pass text_col= for that column, or "
                    "text_col=None if the frame holds numeric results only."
                )
            text = pl.col(text_col).cast(pl.String).str.contains(blq_text).fill_null(False)
            parts.append(conc.is_null() & text)
        out = pl.lit(False)
        for part in parts:
            out = out | part
        return out

    def blq_flag(
        self,
        target: str,
        *,
        conc_col: str,
        lloq_col: str,
        text_col: str | None = "PCSTRESC",
        blq_text: str = BLQ_TEXT,
        numeric_below_lloq: bool = True,
    ) -> Self:
        """Flag records below the LLOQ (``"Y"``, else null).

        A record is BLQ when *conc_col* is below *lloq_col*, or *conc_col* is
        null and *text_col* matches *blq_text* (``"<0.1"``, ``"BLQ"``).
        ``"ALQ"``, ``">1000"`` and a missed sample are not BLQ.

        Args:
            target: Name of the output flag column.
            conc_col: Numeric concentration column (``PCSTRESN``).
            lloq_col: Column containing the lower limit of quantification.
            text_col: Character result column (default ``"PCSTRESC"``);
                ``None`` when the frame holds numeric results only.
            blq_text: Regular expression of the BLQ texts.  The default
                matches a text that starts with ``<`` or is ``BLQ``, ``BQL``,
                ``BLOQ`` or ``LLOQ`` (any case); the data transfer agreement
                decides the real list.
            numeric_below_lloq: Count a number below the LLOQ as BLQ
                (default ``True``, ADaM popPK 1.0 BLQFL).  ``False`` lets only
                the text decide, as admiral.

        Returns:
            Self: The namespace with *target* appended.

        Raises:
            DerivationError: When *text_col* is not in the frame.

        References:
            SDTMIG 3.4 PC (PCSTRESC holds every result as text, PCSTRESN
            numeric results only); ADaMIG-NCA 1.0 and ADaM popPK 1.0 BLQFL.

        Examples:
            Derive BLQ flag from PC data::

                adpc = (
                    pc_raw.adam.pk
                    .blq_flag("BLQFL", conc_col="PCSTRESN",
                              lloq_col="PCLLOQ")
                    .to_frame()
                )
        """
        cond = self._is_blq(
            "blq_flag",
            pl.col(conc_col).cast(pl.Float64),
            lloq_col,
            text_col,
            blq_text,
            numeric_below_lloq,
        )
        return self._chain(pl.when(cond).then(pl.lit("Y")).otherwise(pl.lit(None)).alias(target))

    def blq_impute(
        self,
        target: str,
        *,
        conc_col: str,
        lloq_col: str,
        method: str = "half_lloq",
        text_col: str | None = "PCSTRESC",
        blq_text: str = BLQ_TEXT,
        numeric_below_lloq: bool = True,
    ) -> Self:
        """Impute BLQ concentrations with a standard substitution method.

        BLQ follows :meth:`blq_flag`.  Other records keep *conc_col*.

        Args:
            target: Name of the output numeric column.
            conc_col: Numeric concentration column (``PCSTRESN``).
            lloq_col: Column containing the LLOQ.
            method: One of ``"half_lloq"`` (default), ``"zero"``, ``"lloq"``,
                or ``"missing"``.
            text_col: Character result column; see :meth:`blq_flag`.
            blq_text: BLQ texts; see :meth:`blq_flag`.
            numeric_below_lloq: See :meth:`blq_flag`.

        Returns:
            Self: The namespace with *target* appended.

        Raises:
            DerivationError: When *method* is unknown or *text_col* is not in
                the frame.

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
            raise DerivationError(
                f"blq_impute method={method!r} is not supported. "
                f"Choose one of: {sorted(valid_methods)}"
            )

        conc = pl.col(conc_col).cast(pl.Float64)
        lloq = pl.col(lloq_col).cast(pl.Float64)
        is_blq = self._is_blq("blq_impute", conc, lloq_col, text_col, blq_text, numeric_below_lloq)

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
                raise DerivationError(
                    f"nominal_time unit={u!r} is not supported. "
                    f"Choose one of: {sorted(valid_units)}"
                )
        scale = _UNIT_SCALE[input_unit] / _UNIT_SCALE[output_unit]
        expr = (pl.col(from_col).cast(pl.Float64) * scale).alias(target)
        return self._chain(expr)

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
        conc_indicator: int = 0,
    ) -> Self:
        """Derive Event ID (EVID) for Population PK datasets.

        When *from_col* is provided, casts and aliases it.  Otherwise assigns
        *conc_indicator* to every row.

        Args:
            target: Name of the output column (default ``"EVID"``).
            from_col: Existing integer column encoding EVID.
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
        text_col: str | None = "PCSTRESC",
        blq_text: str = BLQ_TEXT,
        numeric_below_lloq: bool = True,
    ) -> Self:
        """Derive a numeric BLQ flag (``1`` / ``0``).

        Complements :meth:`blq_flag` which returns character ``"Y"``/null;
        BLQ follows the same rule.

        Args:
            target: Name of the output column.
            conc_col: Numeric concentration column (``PCSTRESN``).
            lloq_col: Column containing the LLOQ.
            text_col: Character result column; see :meth:`blq_flag`.
            blq_text: BLQ texts; see :meth:`blq_flag`.
            numeric_below_lloq: See :meth:`blq_flag`.

        Returns:
            Self: The namespace with *target* appended.

        Raises:
            DerivationError: When *text_col* is not in the frame.

        Examples:
            Derive numeric BLQ indicator::

                adpc = (
                    pc_raw.adam.pk
                    .blqfn("BLQFN", conc_col="PCSTRESN",
                           lloq_col="PCLLOQ")
                    .to_frame()
                )
        """
        cond = self._is_blq(
            "blqfn",
            pl.col(conc_col).cast(pl.Float64),
            lloq_col,
            text_col,
            blq_text,
            numeric_below_lloq,
        )
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
            raise DerivationError(
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
        records, following NONMEM convention.  *conc_cmt* applies to all
        non-dose records, whatever the specimen.  For a compartment by
        specimen (PCSPEC), use ``.derivation``.

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
        text_col: str | None = "PCSTRESC",
        blq_text: str = BLQ_TEXT,
        numeric_below_lloq: bool = True,
    ) -> Self:
        """Derive a listing-ready categorised analysis value (AVALCAT1).

        A BLQ record (as :meth:`blq_flag`) gets *blq_label*.  Another record
        gets its number as text (15 significant digits, no ``.0`` end, so
        ``5.0`` gives ``"5"``), else the *text_col* text (``">1000"``,
        ``"NQ"``), else null (a missed sample).

        Args:
            target: Name of the output column.
            conc_col: Concentration column (numeric, or text that holds
                numbers).
            lloq_col: Optional LLOQ column for the numeric BLQ check.
            blq_label: Label for BLQ records (default ``"BLQ"``).
            text_col: Character result column; see :meth:`blq_flag`.
            blq_text: BLQ texts; see :meth:`blq_flag`.
            numeric_below_lloq: See :meth:`blq_flag`.

        Returns:
            Self: The namespace with *target* appended.

        Raises:
            DerivationError: When *text_col* is not in the frame.

        Examples:
            Derive AVALCAT1 from concentration and LLOQ::

                adpc = (
                    pc_raw.adam.pk
                    .avalcat("AVALCAT1", conc_col="PCSTRESN",
                             lloq_col="PCLLOQ")
                    .to_frame()
                )
        """
        conc_num = pl.col(conc_col).cast(pl.Float64, strict=False)
        is_blq = self._is_blq("avalcat", conc_num, lloq_col, text_col, blq_text, numeric_below_lloq)
        shown = to_char(conc_num, pl.Float64)
        if text_col is not None:
            shown = pl.coalesce(shown, pl.col(text_col).cast(pl.String))

        return self._chain(pl.when(is_blq).then(pl.lit(blq_label)).otherwise(shown).alias(target))

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
