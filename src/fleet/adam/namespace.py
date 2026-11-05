"""
ADaM Polars namespace extension (BDS datasets).

Registers ``df.adam`` on every Polars DataFrame.
All ADaM sub-structures and extensions are accessed via properties:
  - ``df.adam.adsl``   — one-row-per-subject derivations
  - ``df.adam.occds``  — one-row-per-event derivations
  - ``df.adam.onco``   — Oncology TA extension
  - ``df.adam.ophtha`` — Ophthalmology TA extension
  - ``df.adam.peds``   — Pediatrics TA extension
  - ``df.adam.vaccine``— Vaccine TA extension
  - ``df.adam.metabolic`` — Metabolic TA extension
  - ``df.adam.neuro``  — Neuroscience TA extension

Usage
-----
    import fleet  # triggers registration of df.adam, df.adsl, df.occds

    result = (
        vs_sdtm.adam
        .source("USUBJID")
        .date("ADT", source="VSDTC")
        .derivation("AVAL", expression="VSSTRESN")
        .duration("ADY", start="TRTSDT", end="ADT")
        .flag("ABLFL", criteria='pl.col("VISITNUM") == 1',
              by=["USUBJID", "PARAMCD"])
        .baseline("BASE", aval="AVAL", baseline_flag="ABLFL")
        .chg("CHG", aval="AVAL", base="BASE")
        .pchg("PCHG", aval="AVAL", base="BASE")
        .to_frame()
    )

Discover every available verb programmatically with ``df.adam.verbs()``.

    # Or spec-driven:
    result = vs_sdtm.adam.from_spec("examples/cdiscpilot01/adam/define.yaml", dataset="ADVS").to_frame()
"""

from __future__ import annotations

import difflib
import warnings
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, Self

import polars as pl

from fleet.core.exceptions import DerivationError, VerbUsageError

from ._mixins import SharedADaMVerbsMixin
from .utils import (
    baseline,
    chg,
    pchg,
)
from .utils import (
    bmi as _bmi_expr,
)
from .utils import (
    bsa as _bsa_expr,
)
from .utils import (
    mean_arterial_pressure as _map_expr,
)
from .utils import (
    nrind as _nrind_expr,
)
from .utils import (
    on_treatment as _on_treatment_expr,
)
from .utils import (
    qtc as _qtc_expr,
)
from .utils import (
    shift as _shift_expr,
)

if TYPE_CHECKING:
    from .adsl_namespace import ADSLNamespace
    from .metabolic_namespace import MetabolicNamespace
    from .neuro_namespace import NeuroNamespace
    from .occds_namespace import OCCDSNamespace
    from .onco_namespace import OncoNamespace
    from .ophtha_namespace import OphthaNamespace
    from .peds_namespace import PedsNamespace
    from .pk_namespace import PKNamespace
    from .tte_namespace import TTENamespace
    from .vaccine_namespace import VaccineNamespace

#: The grades that ``combine_grades`` accepts (admiral ``derive_var_atoxgr``).
_GRADES = frozenset({"0", "1", "2", "3", "4"})


@pl.api.register_dataframe_namespace("adam")
@pl.api.register_lazyframe_namespace("adam")
class AdamNamespace(SharedADaMVerbsMixin):
    """
    Immutable pipeline builder for ADaM derivations.

    Each verb appends to a lazy expression list; ``to_frame()`` materialises
    everything in one ``with_columns`` call (unless the verb requires a join/filter).
    Accepts both ``pl.DataFrame`` and ``pl.LazyFrame`` inputs, so scanned
    sources stay lazy end-to-end.

    Inherits shared verbs from ``SharedADaMVerbsMixin`` (``assign``,
    ``case_when``, ``merge``, ``source``, ``derivation``, ``whereclauses``,
    ...).  Discover the full set with ``df.adam.verbs()``.
    """

    # ------------------------------------------------------------------ #
    # 9.  baseline — propagate baseline value to all group records        #
    # ------------------------------------------------------------------ #

    def baseline(
        self,
        target: str,
        *,
        aval: str = "AVAL",
        baseline_flag: str = "ABLFL",
        by: str | list[str] | None = None,
        strict: bool = True,
    ) -> Self:
        """Derive BASE as the AVAL where the baseline flag equals ``"Y"``.

        Uses a window function so all records in the same group receive the
        same baseline value.  A group with **more than one** flagged
        record has an ambiguous baseline: with ``strict=True`` (default)
        this raises a ``DerivationError`` naming the offending groups
        (admiral semantics); ``strict=False`` keeps the legacy behaviour
        (silently taking the maximum flagged value) but emits a
        ``UserWarning``.

        Args:
            target: Name of the output column (e.g. ``"BASE"``).
            aval: Analysis value column (default ``"AVAL"``).
            baseline_flag: Flag column indicating the baseline record.
            by: Partition columns (default ``["USUBJID", "PARAMCD"]``).
            strict: Raise when a group has multiple baseline-flagged
                records (default ``True``).

        Returns:
            AdamNamespace: The namespace with *target* appended.

        Raises:
            DerivationError: When ``strict=True`` and at least one group
                carries more than one baseline-flagged record.

        Examples:
            Propagate baseline AVAL to all records::

                advs = (
                    vs_raw.adam
                    .baseline("BASE", aval="AVAL", baseline_flag="ABLFL",
                              by=["USUBJID", "PARAMCD"])
                    .to_frame()
                )
        """
        import warnings

        grps = [by] if isinstance(by, str) else list(by or ["USUBJID", "PARAMCD"])
        schema_names = self._lazy.collect_schema().names()
        if baseline_flag not in schema_names or any(g not in schema_names for g in grps):
            # Missing columns — defer to _chain's verb-attributed error.
            return self._chain(
                baseline(aval=aval, baseline_flag_col=baseline_flag, group_by=grps, target=target),
                verb="baseline",
            )
        dup_groups = (
            self._lazy.filter(pl.col(baseline_flag) == "Y")
            .group_by(grps)
            .agg(pl.len().alias("__n_baseline__"))
            .filter(pl.col("__n_baseline__") > 1)
            .collect()
        )
        if dup_groups.height:
            sample = dup_groups.select(grps).head(5).rows()
            keys = "; ".join(", ".join(f"{k}={v!r}" for k, v in zip(grps, row)) for row in sample)
            more = f" (+{dup_groups.height - 5} more)" if dup_groups.height > 5 else ""
            detail = (
                f"baseline('{target}'): {dup_groups.height} group(s) have more than one "
                f"record flagged {baseline_flag}='Y' — the baseline is ambiguous. "
                f"Offending groups: {keys}{more}."
            )
            if strict:
                raise DerivationError(
                    f"{detail} Deduplicate the baseline flag (e.g. via "
                    ".flag(..., criteria='last') or .nodup(...)) or pass strict=False "
                    "to keep the legacy max() behaviour."
                )
            warnings.warn(
                f"{detail} Taking the maximum flagged value per group (strict=False).",
                stacklevel=2,
            )
        return self._chain(
            baseline(aval=aval, baseline_flag_col=baseline_flag, group_by=grps, target=target),
            verb="baseline",
        )

    # ------------------------------------------------------------------ #
    # 10. chg — change from baseline                                      #
    # ------------------------------------------------------------------ #

    def chg(
        self,
        target: str,
        *,
        aval: str = "AVAL",
        base: str = "BASE",
    ) -> Self:
        """Compute change from baseline: ``CHG = AVAL - BASE``.

        Args:
            target: Name of the output column (e.g. ``"CHG"``).
            aval: Analysis value column.
            base: Baseline value column.

        Returns:
            AdamNamespace: The namespace with *target* appended.

        Examples:
            Derive CHG from AVAL and BASE::

                advs = (
                    vs_raw.adam
                    .chg("CHG", aval="AVAL", base="BASE")
                    .to_frame()
                )
        """
        return self._chain(chg(aval=aval, base=base, target=target), verb="chg")

    # ------------------------------------------------------------------ #
    # 11. pchg — percent change from baseline                             #
    # ------------------------------------------------------------------ #

    def pchg(
        self,
        target: str,
        *,
        aval: str = "AVAL",
        base: str = "BASE",
    ) -> Self:
        """Compute percent change from baseline.

        ``PCHG = (AVAL - BASE) / BASE * 100``.  Returns null when BASE is
        null or zero.

        Args:
            target: Name of the output column (e.g. ``"PCHG"``).
            aval: Analysis value column.
            base: Baseline value column.

        Returns:
            AdamNamespace: The namespace with *target* appended.

        Examples:
            Derive PCHG from AVAL and BASE::

                advs = (
                    vs_raw.adam
                    .pchg("PCHG", aval="AVAL", base="BASE")
                    .to_frame()
                )
        """
        return self._chain(pchg(aval=aval, base=base, target=target), verb="pchg")

    # ------------------------------------------------------------------ #
    # 13. bmi — Body Mass Index                                            #
    # ------------------------------------------------------------------ #

    def bmi(
        self,
        target: str,
        *,
        weight: str,
        height: str,
        round_digits: int | None = None,
    ) -> Self:
        """Derive Body Mass Index: ``weight_kg / (height_cm / 100) ** 2``.

        The value keeps full precision.  A height of 0 gives null, as SAS
        gives a missing value for a division by zero.

        Args:
            target: Name of the output column.
            weight: Column containing weight in kg.
            height: Column containing height in cm.
            round_digits: Decimal places, rounded as SAS ``ROUND`` (half away
                from zero).  Default ``None``: no rounding.

        Returns:
            AdamNamespace: The namespace with *target* appended.

        References:
            admiral ``compute_bmi`` (pharmaverse): full precision, NA for height 0.
            ADR-0025: a derived value is rounded only when the call says so.

        Examples:
            Compute BMI from weight and height::

                advs = (
                    vs_raw.adam
                    .bmi("BMI", weight="WEIGHT", height="HEIGHT")
                    .to_frame()
                )
        """
        return self._chain(
            _bmi_expr(weight=weight, height=height, target=target, round_digits=round_digits),
            verb="bmi",
        )

    # ------------------------------------------------------------------ #
    # 14. nrind — normal range indicator                                   #
    # ------------------------------------------------------------------ #

    def nrind(
        self,
        target: str,
        *,
        value: str,
        low: str,
        high: str,
        signif_dig: int = 15,
    ) -> Self:
        """Categorise *value* relative to normal range: LOW / NORMAL / HIGH.

        The value and the limits are compared at *signif_dig* significant
        digits, so float noise (1.3 x 88.4 = 114.92000000000002) does not
        move a value at the limit out of the range.  A null or NaN value gives
        null.

        Args:
            target: Name of the output column (e.g. ``"NRIND"``).
            value: Column containing the numeric result.
            low: Column containing the lower limit of normal.
            high: Column containing the upper limit of normal.
            signif_dig: Significant digits for the comparison (default 15).

        Returns:
            AdamNamespace: The namespace with *target* appended.

        References:
            admiral ``derive_var_anrind`` (pharmaverse): ``signif(x, 15)`` on AVAL,
            ANRLO and ANRHI before the comparison.

        Examples:
            Derive normal range indicator for lab results::

                adlb = (
                    lb_raw.adam
                    .nrind("NRIND", value="LBSTRESN",
                           low="LBSTNRLO", high="LBSTNRHI")
                    .to_frame()
                )
        """
        return self._chain(
            _nrind_expr(value=value, low=low, high=high, target=target, signif_dig=signif_dig),
            verb="nrind",
        )

    # ------------------------------------------------------------------ #
    # 15. on_treatment — derive ONTRTFL                                    #
    # ------------------------------------------------------------------ #

    def on_treatment(
        self,
        target: str = "ONTRTFL",
        *,
        adt: str,
        trtsdt: str,
        trtedt: str,
        open_ended: bool = True,
    ) -> Self:
        """Set *target* to ``"Y"`` when *adt* is within [trtsdt, trtedt].

        When *open_ended* is ``True`` (default) and *trtedt* is null, the
        interval is treated as ongoing (``adt >= trtsdt`` suffices).
        ``--DTC`` text is read by its date portion (a partial or blank
        value gives null); a number raises.  When *adt* and *trtsdt* are
        both ``pl.Datetime``, the start comparison keeps the time, so a
        pre-dose record on the first dose day is not on treatment; the end
        comparison is at date level.

        Args:
            target: Name of the output column (default ``"ONTRTFL"``).
            adt: Analysis date column.
            trtsdt: Treatment start date column.
            trtedt: Treatment end date column.
            open_ended: Treat null *trtedt* as open-ended (default ``True``).

        Returns:
            AdamNamespace: The namespace with *target* appended.

        References:
            admiral ``derive_var_ontrtfl`` (start compared with time when
            both are date-times); ADR-0011 and ADR-0022.

        Examples:
            Derive on-treatment flag::

                advs = (
                    vs_raw.adam
                    .on_treatment("ONTRTFL", adt="ADT",
                                  trtsdt="TRTSDT", trtedt="TRTEDT")
                    .to_frame()
                )
        """
        return self._chain(
            _on_treatment_expr(
                adt=adt,
                trtsdt=trtsdt,
                trtedt=trtedt,
                target=target,
                open_ended=open_ended,
                dtypes=self._lazy.collect_schema(),
            ),
            verb="on_treatment",
        )

    # ------------------------------------------------------------------ #
    # 16. shift — baseline-to-post categorical shift string               #
    # ------------------------------------------------------------------ #

    def shift(
        self,
        target: str,
        *,
        baseline_cat: str,
        post_cat: str,
        sep: str = " to ",
    ) -> Self:
        """Derive a categorical shift label: ``"<baseline><sep><post>"``.

        Args:
            target: Name of the output column (e.g. ``"SHIFT1"``).
            baseline_cat: Column with baseline category (e.g. ``"BNRIND"``).
            post_cat: Column with post-baseline category (e.g. ``"NRIND"``).
            sep: Separator string (default ``" to "``).

        Returns:
            AdamNamespace: The namespace with *target* appended.

        Examples:
            Create a shift variable from baseline and post normal range::

                adlb = (
                    lb_raw.adam
                    .shift("SHIFT1", baseline_cat="BNRIND",
                           post_cat="NRIND")
                    .to_frame()
                )
        """
        return self._chain(
            _shift_expr(baseline_cat=baseline_cat, post_cat=post_cat, target=target, sep=sep),
            verb="shift",
        )

    # ------------------------------------------------------------------ #
    # 17. bsa — Body Surface Area                                          #
    # ------------------------------------------------------------------ #

    def bsa(
        self,
        target: str,
        *,
        weight: str,
        height: str,
        method: str = "Mosteller",
        round_digits: int | None = None,
    ) -> Self:
        """Derive Body Surface Area in m², at full precision.

        Args:
            target: Name of the output column.
            weight: Column containing weight in kg.
            height: Column containing height in cm.
            method: Formula to use — ``"Mosteller"`` (default), ``"DuBois"``,
                ``"Haycock"``, or ``"Gehan-George"``.
            round_digits: Decimal places, rounded as SAS ``ROUND`` (half away
                from zero).  Default ``None``: no rounding.

        Returns:
            AdamNamespace: The namespace with *target* appended.

        References:
            admiral ``compute_bsa`` (pharmaverse): full precision.
            ADR-0025: a derived value is rounded only when the call says so.

        Examples:
            Compute BSA using the Mosteller formula::

                advs = (
                    vs_raw.adam
                    .bsa("BSA", weight="WEIGHT", height="HEIGHT")
                    .to_frame()
                )
        """
        return self._chain(
            _bsa_expr(
                weight=weight,
                height=height,
                method=method,
                target=target,
                round_digits=round_digits,
            ),
            verb="bsa",
        )

    # ------------------------------------------------------------------ #
    # 18. map — Mean Arterial Pressure                                     #
    # ------------------------------------------------------------------ #

    def map(
        self,
        target: str = "MAP",
        *,
        systolic: str = "SYSBP",
        diastolic: str = "DIABP",
        round_digits: int | None = None,
    ) -> Self:
        """Derive Mean Arterial Pressure: ``DBP + (SBP - DBP) / 3``, at full precision.

        Args:
            target: Name of the output column (default ``"MAP"``).
            systolic: Systolic blood pressure column.
            diastolic: Diastolic blood pressure column.
            round_digits: Decimal places, rounded as SAS ``ROUND`` (half away
                from zero).  Default ``None``: no rounding.

        Returns:
            AdamNamespace: The namespace with *target* appended.

        References:
            admiral ``compute_map`` (pharmaverse): full precision.
            ADR-0025: a derived value is rounded only when the call says so.

        Examples:
            Compute MAP from blood pressure columns::

                advs = (
                    vs_raw.adam
                    .map("MAP", systolic="SYSBP", diastolic="DIABP")
                    .to_frame()
                )
        """
        return self._chain(
            _map_expr(
                systolic=systolic, diastolic=diastolic, target=target, round_digits=round_digits
            ),
            verb="map",
        )

    # ------------------------------------------------------------------ #
    # 19. qtc — Corrected QT interval                                      #
    # ------------------------------------------------------------------ #

    def qtc(
        self,
        target: str = "QTC",
        *,
        qt: str = "QT",
        rr: str = "RR",
        method: str = "Fridericia",
        rr_unit: str = "ms",
        round_digits: int | None = None,
    ) -> Self:
        """Derive corrected QT interval, as admiral ``compute_qtc``, at full precision.

        Args:
            target: Name of the output column (default ``"QTC"``).
            qt: QT interval column, in ms.
            rr: RR interval column, in *rr_unit*.
            method: Correction formula — ``"Fridericia"`` (default) or
                ``"Bazett"``.
            rr_unit: Unit of *rr*: ``"ms"`` (default) or ``"msec"``, or
                ``"s"`` or ``"sec"``.
            round_digits: Decimal places, rounded as SAS ``ROUND`` (half away
                from zero).  Default ``None``: no rounding.

        Returns:
            AdamNamespace: The namespace with *target* appended.

        Raises:
            DerivationError: When *rr_unit* is unknown, or a value cannot be
                in its unit: an RR under 10 in ms, an RR of 10 or more in
                seconds, or a QT under 10 ms.

        References:
            admiral ``compute_qtc`` (pharmaverse): RR in ms, QT in ms, full precision.
            ADR-0025: a derived value is rounded only when the call says so.

        Examples:
            Derive QTcF from QT and RR, both in ms::

                adeg = (
                    eg_raw.adam
                    .qtc("QTCF", qt="QT", rr="RR", method="Fridericia")
                    .to_frame()
                )
        """
        expr = _qtc_expr(
            qt=qt, rr=rr, method=method, target=target, rr_unit=rr_unit, round_digits=round_digits
        )
        schema_names = self._lazy.collect_schema().names()
        if qt in schema_names and rr in schema_names:
            seconds = rr_unit.lower() in ("s", "sec")
            rr_num = pl.col(rr).cast(pl.Float64, strict=False)
            bad_rr = rr_num >= 10 if seconds else rr_num < 10
            counts = (
                self._lazy.select(
                    bad_rr.sum().alias("rr"),
                    (pl.col(qt).cast(pl.Float64, strict=False) < 10).sum().alias("qt"),
                )
                .collect()
                .row(0)
            )
            if counts[0]:
                raise DerivationError(
                    f"qtc('{target}'): {counts[0]} {rr} value(s) cannot be in "
                    f"rr_unit={rr_unit!r} (RR in ms is 10 or more; in seconds it is under 10). "
                    "State the unit of the data with rr_unit=."
                )
            if counts[1]:
                raise DerivationError(
                    f"qtc('{target}'): {counts[1]} {qt} value(s) are under 10. QT must be in ms."
                )
        return self._chain(expr, verb="qtc")

    # ------------------------------------------------------------------ #
    # 20. derive_summary_records — aggregate and append new rows          #
    # ------------------------------------------------------------------ #

    def derive_summary_records(
        self,
        *,
        by: list[str],
        analysis_var: str = "AVAL",
        set_values_to: dict[str, Any],
        stat: Literal["mean", "sum", "min", "max", "median", "count"] = "mean",
        where: str | pl.Expr | None = None,
    ) -> Self:
        """
        Compute a summary statistic per group and append the results as new records.

        *set_values_to*: column → value mapping applied to every new record
        (e.g. ``{"PARAMCD": "AVGBP", "DTYPE": "AVERAGE"}``).  A ``pl.Expr``
        value is evaluated per *by* group and must give one value, as
        admiral ``set_values_to = exprs(ADT = min(ADT))``; other values are
        constants.  Put PARAM in *by* (or in *set_values_to*), so the new
        record has a PARAM.

        *stat*: ``"mean"`` (default), ``"sum"``, ``"min"``, ``"max"``, ``"median"``,
        ``"count"``. A group with only null values gives null for every stat
        except ``"count"``, which gives 0, as SAS ``SUM()`` and PROC MEANS.

        *where*: filter on the source records of the summary. The rows of the
        dataset are all kept. A second call in one chain reads the rows that
        the first call added: give ``where=pl.col("DTYPE").is_null()`` to
        summarise only collected records. When *where* is None and the source
        holds a non-null DTYPE, the verb warns.

        Materialises the current pipeline before concatenation.

        Examples:
            Compute mean AVAL per subject and parameter, dated at the first record::

                advs = (
                    vs_raw.adam
                    .derive_summary_records(
                        by=["USUBJID", "PARAMCD", "PARAM"],
                        analysis_var="AVAL",
                        set_values_to={"DTYPE": "AVERAGE", "ADT": pl.col("ADT").min()},
                        stat="mean",
                    )
                    .to_frame()
                )
        """
        stat_lower = stat.lower()
        agg_map = {
            "mean": pl.col(analysis_var).mean(),
            "sum": pl.when(pl.col(analysis_var).count() > 0).then(pl.col(analysis_var).sum()),
            "min": pl.col(analysis_var).min(),
            "max": pl.col(analysis_var).max(),
            "median": pl.col(analysis_var).median(),
            "count": pl.col(analysis_var).count().cast(pl.Float64),
        }
        if stat_lower not in agg_map:
            raise DerivationError(f"Unknown stat '{stat}'. Supported: {', '.join(agg_map)}.")

        df = self.to_frame()
        source = df
        if where is not None:
            from fleet.sdtm.utils import parse_expression

            source = df.filter(where if isinstance(where, pl.Expr) else parse_expression(where))
        elif "DTYPE" in df.columns and df.get_column("DTYPE").is_not_null().any():
            warnings.warn(
                "derive_summary_records(): the source holds records with a non-null DTYPE, "
                "and they enter the summary. Give where=pl.col('DTYPE').is_null() to "
                "summarise only collected records.",
                UserWarning,
                stacklevel=2,
            )
        summary = source.group_by(by, maintain_order=True).agg(
            agg_map[stat_lower].alias(analysis_var),
            *(v.alias(k) for k, v in set_values_to.items() if isinstance(v, pl.Expr)),
        )

        # Apply constant values to the summary rows
        for col_name, col_val in set_values_to.items():
            if not isinstance(col_val, pl.Expr):
                summary = summary.with_columns(pl.lit(col_val).alias(col_name))

        # Align schemas before concat: add missing columns as null in both directions
        for c in df.columns:
            if c not in summary.columns:
                summary = summary.with_columns(pl.lit(None).cast(df.schema[c]).alias(c))
        for c in summary.columns:
            if c not in df.columns:
                df = df.with_columns(pl.lit(None).cast(summary.schema[c]).alias(c))

        col_order = df.columns
        summary = summary.select(col_order)

        combined = pl.concat([df, summary], how="vertical_relaxed")
        from fleet.core.lineage import record_row_step

        return record_row_step(self._materialise_then(combined), "derive_summary_records", {})

    # ------------------------------------------------------------------ #
    # 21. derive_locf_records — last observation carried forward          #
    # ------------------------------------------------------------------ #

    def derive_locf_records(
        self,
        *,
        dataset_ref: pl.DataFrame,
        by: str | list[str],
        order_by: str | list[str],
        analysis_var: str = "AVAL",
        imputation: Literal["add", "update", "update_add"] = "add",
        keep_vars: list[str] | None = None,
    ) -> Self:
        """Add LOCF records for missed visits and for a null *analysis_var*.

        For each *by* group, every row of *dataset_ref* (the expected visits)
        that has no record with a non-null *analysis_var* gets a value carried
        forward from the previous record, sorted by *by* and *order_by*. Each
        imputed record has DTYPE ``"LOCF"``; an existing DTYPE on the other
        records is kept. A group with no earlier value keeps a null value.

        Args:
            dataset_ref: Expected observations, for example AVISIT and AVISITN,
                or PARAMCD, AVISIT and AVISITN. Add USUBJID for a per-subject
                list. Each of its columns must be in the dataset.
            by: Group columns, for example ``["STUDYID", "USUBJID", "PARAMCD"]``.
            order_by: Sort column(s) within a group. The first one must be in
                *dataset_ref*, so that a new record has a sort value.
            analysis_var: Column to carry forward (default ``"AVAL"``).
            imputation: ``"add"`` (default, as admiral) keeps each record with a
                null value and adds an imputed record. ``"update"`` puts the
                value on that record. ``"update_add"`` does both.
            keep_vars: Other columns to carry forward, for example PARAMN.
                A new record has values only in *by*, *dataset_ref*,
                *analysis_var*, *keep_vars* and DTYPE; other columns are null.

        Returns:
            AdamNamespace: The namespace with the LOCF records; call
                ``.to_frame()`` to materialise.

        Raises:
            DerivationError: On an unknown *imputation*, a missing column, a
                first *order_by* column that is not in *dataset_ref*, or a null
                *order_by* value on a record to sort.

        Examples:
            Add WEEK 24 by LOCF for each subject and parameter::

                visits = pl.DataFrame(
                    {"AVISIT": ["BASELINE", "WEEK 8", "WEEK 16", "WEEK 24"],
                     "AVISITN": [0, 8, 16, 24]}
                )
                adqs = (
                    qs_raw.adam
                    .derive_locf_records(
                        dataset_ref=visits,
                        by=["STUDYID", "USUBJID", "PARAMCD"],
                        order_by=["AVISITN"],
                        keep_vars=["PARAM"],
                    )
                    .to_frame()
                )

        References:
            ADaMIG v1.3 section 4.4 (BDS): DTYPE must be populated on a record
            whose AVAL is imputed; "LOCF" is in CDISC CT codelist DTYPE (C81224).
            admiral ``derive_locf_records`` (pharmaverse) defines the three
            imputation modes. ADR-0029.
        """
        by = [by] if isinstance(by, str) else list(by)
        order = [order_by] if isinstance(order_by, str) else list(order_by)
        keep = list(keep_vars or [])
        if imputation not in ("add", "update", "update_add"):
            raise DerivationError(
                f"derive_locf_records(): imputation={imputation!r} is not supported. "
                "Choose 'add', 'update' or 'update_add'."
            )
        if not order:
            raise DerivationError("derive_locf_records(): order_by needs at least one column.")
        ref_cols = dataset_ref.columns
        if order[0] not in ref_cols:
            raise DerivationError(
                f"derive_locf_records(): the first order_by column {order[0]!r} is not in "
                f"dataset_ref (columns {ref_cols}). A new record would have no sort value. "
                "Sort by a visit column of dataset_ref, for example order_by=['AVISITN']."
            )
        df = self.to_frame()
        needed = dict.fromkeys([*by, analysis_var, *order, *keep, *ref_cols])
        missing = [c for c in needed if c not in df.columns]
        if missing:
            raise DerivationError(f"derive_locf_records(): column(s) {missing} not in the dataset.")

        ref = dataset_ref.cast({c: df.schema[c] for c in ref_cols})
        ids = df.select([c for c in by if c not in ref_cols]).unique(maintain_order=True)
        expected = ids.join(ref, how="cross") if ids.width else ref
        exp_by = list(dict.fromkeys([*by, *ref_cols]))

        is_null = pl.col(analysis_var).is_null()
        fill_base = df.filter(~is_null) if imputation == "add" else df
        to_add = expected.join(fill_base.select(exp_by), on=exp_by, how="anti", nulls_equal=True)
        stacked = pl.concat([fill_base, to_add], how="diagonal_relaxed")
        dtype = pl.when(is_null).then(pl.lit("LOCF"))
        if "DTYPE" in df.columns:
            dtype = dtype.otherwise(pl.col("DTYPE"))
        stacked = stacked.with_columns(dtype.alias("DTYPE"))

        n_null = stacked.select(pl.any_horizontal(pl.col(order).is_null()).sum()).item()
        if n_null:
            raise DerivationError(
                f"derive_locf_records(): {n_null} record(s) have a null value in order_by "
                f"{order}, so their place in the visit order is unknown."
            )
        filled = stacked.sort([*by, *order], maintain_order=True).with_columns(
            pl.col([analysis_var, *keep]).forward_fill().over(by)
        )
        if imputation != "update":
            filled = pl.concat([filled, df.filter(is_null)], how="diagonal_relaxed")
        from fleet.core.lineage import record_row_step

        new = self._materialise_then(filled.select(list(dict.fromkeys([*df.columns, "DTYPE"]))))
        return record_row_step(new, "derive_locf_records", {})

    # ------------------------------------------------------------------ #
    # 22. derive_param — append a computed parameter as new records        #
    # ------------------------------------------------------------------ #

    def derive_param(
        self,
        *,
        by: str | list[str] | None = None,
        set_values_to: dict[str, Any],
        parameter_filter: dict[str, str],
        analysis_value: pl.Expr | str,
        from_dataset: pl.DataFrame | None = None,
        where: str | pl.Expr | None = None,
        constant_by: str | list[str] | None = None,
        constant_parameters: dict[str, str] | None = None,
        keep_nas: bool = False,
    ) -> Self:
        """
        Derive a new parameter (e.g. BMI) from existing records and append
        the computed rows to the dataset.

        *parameter_filter*: ``{alias: PARAMCD}`` pairs identifying the source
        records to pivot on (e.g. ``{"WEIGHT": "WEIGHT", "HEIGHT": "HEIGHT"}``).
        Each key is a local alias; the value is the ``PARAMCD`` it matches.
        Every source parameter must be unique per *by* group — duplicates
        raise instead of silently multiplying the derived rows.  The parts
        join on *by* with an inner join: a *by* group without every source
        parameter gives no new record.  A code with no record warns.

        *constant_parameters*: ``{alias: PARAMCD}`` pairs measured once per
        *constant_by* group, for example height at screening only.  They
        join on *constant_by*, which must be a subset of *by*
        (admiral ``constant_by_vars``), so a per-visit BMI takes the one
        height.

        *keep_nas*: with ``False`` (default, as admiral), a new record whose
        AVAL is null is not added.  ``True`` keeps it.

        *analysis_value*: a Polars expression (or YAML-friendly string)
        referencing the aliases to compute the new AVAL
        (e.g. ``pl.col("WEIGHT") / (pl.col("HEIGHT")/100)**2``).

        *set_values_to*: constant columns on the new rows — including the
        parameter-level identifiers ``PARAM``, ``PARAMN``, ``PARCATy`` /
        ``PARCATyN``, and ``DTYPE`` (e.g. ``{"PARAMCD": "BMI",
        "PARAM": "Body Mass Index", "PARAMN": 3, "PARCAT1": "ANTHRO"}``).
        An expression raises: give constants only.
        Columns that don't exist yet are added to the dataset.  The new
        ``PARAMCD`` must not already exist in the dataset: appending under
        an existing code would break the PARAMCD ↔ PARAM/PARAMN one-to-one
        mapping that ADaM conformance checks enforce.

        *from_dataset*: optional BDS-shaped frame (``PARAMCD`` + ``AVAL``)
        to pivot the source parameters from — derive into this dataset
        **from another one** (e.g. compute a param in ADVS from ADLB rows).
        Defaults to the current pipeline frame.

        *where*: optional filter applied to the source records before the
        pivot (e.g. restrict to ``ANL01FL == "Y"`` or baseline rows) —
        the current dataset's rows are never dropped.

        A new AVAL that is infinite or NaN (for example a division by zero)
        becomes null, with a warning that gives the count, as SAS gives a
        missing value.

        Materialises the pipeline before appending.

        References:
            admiral ``derive_param_computed`` (``constant_by_vars``,
            ``keep_nas = FALSE``, and the warning for a filter with no
            observations).  ADR-0051
            (docs/adr/0051-derive-param-adds-no-record-with-a-null-aval.md).

        Examples:
            Derive BMI as a new PARAMCD from WEIGHT and HEIGHT::

                advs = (
                    vs_raw.adam
                    .derive_param(
                        by=["USUBJID", "ADT"],
                        set_values_to={"PARAMCD": "BMI",
                                       "PARAM": "Body Mass Index"},
                        parameter_filter={"WEIGHT": "WEIGHT",
                                          "HEIGHT": "HEIGHT"},
                        analysis_value=(
                            pl.col("WEIGHT") / (pl.col("HEIGHT") / 100) ** 2
                        ),
                    )
                    .to_frame()
                )

            Add a parameter computed from ANOTHER dataset's records::

                advs = (
                    advs.adam
                    .derive_param(
                        by=["USUBJID", "AVISIT"],
                        set_values_to={"PARAMCD": "BSCRCL",
                                       "PARAM": "Creatinine Clearance"},
                        parameter_filter={"CREAT": "CREAT"},
                        analysis_value='pl.col("CREAT") * 1.1',
                        from_dataset=adlb,
                        where='pl.col("ANL01FL") == "Y"',
                    )
                    .to_frame()
                )

            BMI per visit with the height of the screening visit::

                advs = (
                    vs_raw.adam
                    .derive_param(
                        by=["USUBJID", "AVISIT"],
                        constant_by=["USUBJID"],
                        constant_parameters={"HEIGHT": "HEIGHT"},
                        parameter_filter={"WEIGHT": "WEIGHT"},
                        set_values_to={"PARAMCD": "BMI",
                                       "PARAM": "Body Mass Index"},
                        analysis_value=(
                            pl.col("WEIGHT") / (pl.col("HEIGHT") / 100) ** 2
                        ),
                    )
                    .to_frame()
                )
        """
        from fleet.sdtm.utils import parse_expression

        if not parameter_filter:
            raise DerivationError("derive_param() requires at least one parameter_filter entry.")
        exprs = [k for k, v in set_values_to.items() if isinstance(v, pl.Expr)]
        if exprs:
            raise DerivationError(
                f"derive_param(): set_values_to holds an expression for {exprs}. Give a "
                "constant for each column; compute AVAL with analysis_value=."
            )

        grps = [by] if isinstance(by, str) else list(by or ["USUBJID"])
        const_grps = [constant_by] if isinstance(constant_by, str) else list(constant_by or [])
        constants = dict(constant_parameters or {})
        if constants and not const_grps:
            raise DerivationError("derive_param(): constant_parameters needs constant_by=.")
        outside = [c for c in const_grps if c not in grps]
        if outside:
            raise DerivationError(
                f"derive_param(): constant_by {outside} is not in by {grps}. constant_by "
                "must be a subset of by."
            )
        shared = sorted(set(constants) & set(parameter_filter))
        if shared:
            raise DerivationError(
                f"derive_param(): alias(es) {shared} are in parameter_filter and in "
                "constant_parameters. Give each alias once."
            )
        df = self.to_frame()

        # Guard the BDS one-to-one parameter mapping: appending rows under an
        # already-used PARAMCD would mix parameter-level metadata (PARAM,
        # PARAMN, PARCATy) for one code — a guaranteed conformance finding.
        new_paramcd = set_values_to.get("PARAMCD")
        if (
            isinstance(new_paramcd, str)
            and "PARAMCD" in df.columns
            and (df.get_column("PARAMCD") == new_paramcd).any()
        ):
            raise DerivationError(
                f"derive_param(): PARAMCD '{new_paramcd}' already exists in the dataset — "
                "appending would break the PARAMCD ↔ PARAM/PARAMN one-to-one mapping. "
                "Choose a new PARAMCD, or remove the existing rows first."
            )

        source = from_dataset if from_dataset is not None else df
        missing = [c for c in ("PARAMCD", "AVAL") if c not in source.columns]
        if missing:
            origin = "from_dataset" if from_dataset is not None else "the current frame"
            raise DerivationError(
                f"derive_param(): {origin} is missing required column(s) {missing} — "
                "the source must be BDS-shaped (PARAMCD + AVAL)."
            )
        if where is not None:
            where_expr = where if isinstance(where, pl.Expr) else parse_expression(str(where))
            source = source.filter(where_expr)

        # Pivot: for each alias, get AVAL as that alias, unique on its own key
        codes = source.get_column("PARAMCD").drop_nulls().unique().sort().to_list()

        def pivot(alias: str, paramcd_val: str, keys: list[str]) -> pl.DataFrame:
            part = source.filter(pl.col("PARAMCD") == paramcd_val).select(
                keys + [pl.col("AVAL").alias(alias)]
            )
            if part.height == 0:
                close = difflib.get_close_matches(str(paramcd_val), codes, n=1)
                warnings.warn(
                    f"derive_param(): no record has PARAMCD {paramcd_val!r}."
                    + (f" Did you mean {close[0]!r}?" if close else "")
                    + " No new records were added.",
                    UserWarning,
                    stacklevel=3,
                )
            dup = part.group_by(keys).len().filter(pl.col("len") > 1)
            if dup.height:
                raise DerivationError(
                    f"derive_param(): PARAMCD '{paramcd_val}' has multiple records for "
                    f"{dup.height} {keys} group(s) (e.g. {dup.select(keys).row(0)}). "
                    "The derived rows would multiply — deduplicate the source, extend "
                    "by=, or narrow the records with where=."
                )
            return part

        pivoted_parts = [pivot(a, p, grps) for a, p in parameter_filter.items()]
        constant_parts = [pivot(a, p, const_grps) for a, p in constants.items()]

        # Join the by-keyed parts on by, then the constant parts on constant_by
        joined = pivoted_parts[0]
        for part in pivoted_parts[1:]:
            joined = joined.join(part, on=grps, how="inner", nulls_equal=True)
        for part in constant_parts:
            joined = joined.join(part, on=const_grps, how="inner", nulls_equal=True)

        # Compute the new AVAL
        aval_expr = (
            analysis_value
            if isinstance(analysis_value, pl.Expr)
            else parse_expression(str(analysis_value))
        )
        new_rows = joined.with_columns(aval_expr.alias("AVAL")).select(grps + ["AVAL"])
        if new_rows.schema["AVAL"].is_float():
            non_finite = new_rows.select((~pl.col("AVAL").is_finite()).sum()).item()
            if non_finite:
                warnings.warn(
                    f"derive_param(): {non_finite} new AVAL value(s) are infinite or NaN "
                    "(for example a division by zero) and are set to null"
                    + ("." if keep_nas else ", so their records are not added."),
                    stacklevel=2,
                )
                new_rows = new_rows.with_columns(
                    pl.when(pl.col("AVAL").is_finite()).then(pl.col("AVAL")).alias("AVAL")
                )
        if not keep_nas:
            new_rows = new_rows.filter(pl.col("AVAL").is_not_null())

        # Apply set_values_to constants
        for col_name, col_val in set_values_to.items():
            new_rows = new_rows.with_columns(pl.lit(col_val).alias(col_name))

        # Align schemas both ways: new set_values_to columns (e.g. DTYPE)
        # are added to the base frame instead of being silently dropped.
        for c in df.columns:
            if c not in new_rows.columns:
                new_rows = new_rows.with_columns(pl.lit(None).cast(df.schema[c]).alias(c))
        for c in new_rows.columns:
            if c not in df.columns:
                df = df.with_columns(pl.lit(None).cast(new_rows.schema[c]).alias(c))
        new_rows = new_rows.select(df.columns)

        combined = pl.concat([df, new_rows], how="vertical_relaxed")
        from fleet.core.lineage import record_row_step

        return record_row_step(self._materialise_then(combined), "derive_param", {})

    # ------------------------------------------------------------------ #
    # Private: YAML spec dispatcher for algorithm: std_function           #
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # 17. atoxgr — toxicity grading via criteria files                     #
    # ------------------------------------------------------------------ #

    def atoxgr(
        self,
        target: str,
        *,
        system: str = "ctcae_v5",
        direction: Literal["L", "H"],
        term_var: str,
        unit_var: str,
        signif_dig: int = 15,
        indicators: dict[str, list[str]] | None = None,
    ) -> Self:
        """Derive a toxicity grade, as admiral ``derive_var_atoxgr_dir``.

        Materialises the pipeline and grades every row whose term has
        criteria in *direction*.  The bundled criteria are generated from the
        admiral metadata (``scripts/regen_grading_criteria.R``), so each term
        follows the admiral ``case_when``: for example, a null ``BNRIND``
        counts as not abnormal and the ULN criteria apply, and CTCAE v5 INR
        takes the worse of the absolute and the baseline cut-offs (admiral
        COMMENT: worst case, assume on anticoagulation).  The term and the
        unit match without case.  A row with another unit, a null unit, no
        criteria or a population no criteria cover gets a null grade.  Every
        row stays, in its order.

        The ``ctcae_*``, ``daids`` systems hold SI cut-offs (hemoglobin in
        g/L); the ``*_uscv`` systems hold US conventional units (g/dL).  A
        row whose unit is not a unit of the criteria gets null, with a
        warning that gives the count.

        Args:
            target: Name of the output grade column (e.g. ``"ATOXGRL"``).
            system: Grading system name (e.g. ``"ctcae_v5"``, ``"daids"``)
                or path to a custom JSON criteria file (schema version 2).
            direction: ``"L"`` (low) or ``"H"`` (high).
            term_var: Column holding the lab-test / term name.
            unit_var: Column holding the unit of measure (e.g. ``"AVALU"``).
                Required, as admiral: each row is graded with the cut-offs
                of its own unit.
            signif_dig: Significant digits for comparison (default 15, as
                admiral ``signif_digits``).
            indicators: Values of the indicator params of the criteria
                (default ``{"high_indicator": ["HIGH", "H"],
                "low_indicator": ["LOW", "L"]}``).

        Returns:
            AdamNamespace: A fresh namespace wrapping the graded frame.

        Raises:
            DerivationError: When *direction* is not ``"L"`` or ``"H"``,
                *signif_dig* is not a positive integer, or a needed column
                is missing.

        Warns:
            UserWarning: Once, with the *term_var* values that have no
                criteria in any direction (their grade is null).

        References:
            admiral ``derive_var_atoxgr_dir`` and the metadata tables
            ``atoxgr_criteria_ctcv4/5/6`` and ``atoxgr_criteria_daids``
            (SI and USCV), admiral 1.4.1, where ``get_unit_expr`` is required;
            NCI CTCAE v4.03, v5.0, v6.0; DAIDS grading table v2.1. ADR-0028.

        Examples:
            Grade low-direction anemia using CTCAE v5::

                adlb = (
                    lb_raw.adam
                    .atoxgr("ATOXGRL", system="ctcae_v5",
                            direction="L", term_var="ATOXDSCL",
                            unit_var="AVALU")
                    .to_frame()
                )
        """
        from .grading._compiler import grade_dataset
        from .grading._registry import load_criteria

        criteria = load_criteria(system)
        df = self.to_frame()
        # Provide standard BNRIND defaults when no indicators are given.
        if indicators is None:
            indicators = {
                "high_indicator": ["HIGH", "H"],
                "low_indicator": ["LOW", "L"],
            }
        graded = grade_dataset(
            df,
            criteria,
            target=target,
            direction=direction,
            term_var=term_var,
            unit_var=unit_var,
            signif_dig=signif_dig,
            indicators=indicators,
        )
        return self._materialise_then(graded)

    # ------------------------------------------------------------------ #
    # 18. combine_grades — merge low/high toxicity grades                  #
    # ------------------------------------------------------------------ #

    def combine_grades(
        self,
        target: str = "ATOXGR",
        *,
        low_var: str = "ATOXGRL",
        high_var: str = "ATOXGRH",
        low_desc_var: str = "ATOXDSCL",
        high_desc_var: str = "ATOXDSCH",
    ) -> Self:
        """Combine low and high toxicity grades into a signed grade, as admiral.

        Low grades are prefixed with ``"-"``; high grades are kept as-is.
        Both null → null.  ``"0"`` only when each side is ``"0"`` or its
        description is null (no criteria in that direction).  Low ``"0"``
        with a null high grade and a present high description gives null:
        the high grade is unknown (for example ANRHI is missing).

        Args:
            target: Name of the output column (default ``"ATOXGR"``).
            low_var: Low-direction grade column (default ``"ATOXGRL"``).
            high_var: High-direction grade column (default ``"ATOXGRH"``).
            low_desc_var: Low-grade term description column (default
                ``"ATOXDSCL"``).  Required in the data; for a
                one-direction study, add it as a null column.
            high_desc_var: High-grade term description column (default
                ``"ATOXDSCH"``).  Required in the data, as *low_desc_var*.

        Returns:
            AdamNamespace: The namespace with *target* appended.

        Raises:
            DerivationError: When a grade or description column is missing,
                a grade column is not text, or a grade is not ``"0"`` to
                ``"4"`` or null.

        References:
            admiral ``derive_var_atoxgr`` (admiral 1.4.1): ``lowgrade == "0" |
            is.na(lowdesc)`` and the same for high give "0"; a grade other
            than "0" to "4" or NA stops. ADR-0028.

        Examples:
            Combine low/high grades into ATOXGR::

                adlb = (
                    lb_raw.adam
                    .atoxgr("ATOXGRL", system="ctcae_v5", direction="L",
                            term_var="ATOXDSCL", unit_var="AVALU")
                    .atoxgr("ATOXGRH", system="ctcae_v5", direction="H",
                            term_var="ATOXDSCH", unit_var="AVALU")
                    .combine_grades("ATOXGR")
                    .to_frame()
                )
        """
        from .grading._compiler import combine_grades_expr

        names = self._lazy.collect_schema().names()
        missing = [c for c in (low_var, high_var, low_desc_var, high_desc_var) if c not in names]
        if missing:
            raise DerivationError(
                f"combine_grades('{target}'): column(s) {missing} are missing. The "
                "descriptions tell a direction with no criteria from an unknown grade; "
                "for a one-direction study add the other description as a null column."
            )
        schema = self._lazy.collect_schema()
        for col in (low_var, high_var):
            if schema[col] != pl.String:
                raise DerivationError(
                    f"combine_grades('{target}'): {col} is {schema[col]}, not text. A grade "
                    'is "0", "1", "2", "3", "4" or null; cast it with pl.col(...).cast(pl.String).'
                )
        seen = self._lazy.select(
            pl.col(low_var).unique().implode(), pl.col(high_var).unique().implode()
        ).collect()
        for col in (low_var, high_var):
            bad = sorted(v for v in seen[col][0] if v is not None and v not in _GRADES)
            if bad:
                raise DerivationError(
                    f"combine_grades('{target}'): {col} holds {bad}. A grade is "
                    '"0", "1", "2", "3", "4" or null.'
                )
        return self._chain(
            combine_grades_expr(
                low_var,
                high_var,
                low_desc_var=low_desc_var,
                high_desc_var=high_desc_var,
            ).alias(target),
            verb="combine_grades",
        )

    # ------------------------------------------------------------------ #
    # 19. transform — arbitrary DataFrame → DataFrame function            #
    # ------------------------------------------------------------------ #

    def transform(
        self,
        fn: str | Callable[[pl.DataFrame], pl.DataFrame],
        *,
        label: str | None = None,  # noqa: ARG002  — cosmetic, intentionally unused
    ) -> Self:
        """
        Apply an arbitrary ``(pl.DataFrame) -> pl.DataFrame`` function.

        The pending expression pipeline is materialised before the function
        is called, so the function always receives a fully committed frame.

        Args:
            fn: Either a callable directly, or the registered name of a
                transform (see :func:`fleet.adam.transforms.register_transform`).
            label: Optional cosmetic label for documentation/lineage; has no
                effect on the output.

        Raises:
            KeyError: If *fn* is a string that has not been registered.
            TypeError: If *fn* is neither a callable nor a string, or if the
                function does not return a ``pl.DataFrame``.

        Returns:
            AdamNamespace: A fresh namespace wrapping the transformed frame.

        Examples:
            Register and apply a custom age-group transform::

                from fleet.adam.transforms import register_transform

                @register_transform("add_agegr1")
                def add_agegr1(df):
                    return df.with_columns(
                        pl.when(pl.col("AGE") < 65).then(pl.lit("<65"))
                          .otherwise(pl.lit(">=65")).alias("AGEGR1")
                    )

                adsl = (
                    dm_raw.adam
                    .assign("STUDYID", value="S01")
                    .transform("add_agegr1")
                    .to_frame()
                )
        """
        from .transforms import get_transform

        if isinstance(fn, str):
            fn = get_transform(fn)  # raises KeyError if not found
        elif not callable(fn):
            raise VerbUsageError(
                f"transform() expects a callable or a registered name string, "
                f"got {type(fn).__name__!r}."
            )

        # Materialise pending expressions so the function sees a full frame.
        committed = self.to_frame()
        result = fn(committed)

        if not isinstance(result, pl.DataFrame):
            raise VerbUsageError(
                f"Transform function must return a polars DataFrame, got {type(result).__name__!r}."
            )

        return self._materialise_then(result)

    # ------------------------------------------------------------------ #
    # Spec-driven pipeline: from_spec() is inherited from                  #
    # SharedVerbsMixin and executes through fleet.core.spec_registry.      #
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    # ADaM sub-structures (accessed as df.adam.adsl / df.adam.occds)       #
    # ------------------------------------------------------------------ #

    @property
    def adsl(self) -> ADSLNamespace:
        """ADSL (one-row-per-subject) derivations: treatment dates, duration, population flags."""
        from .adsl_namespace import ADSLNamespace

        return self._sub_namespace(ADSLNamespace)

    @property
    def occds(self) -> OCCDSNamespace:
        """OCCDS (one-row-per-event) derivations: sequencing, worst flag, treatment-emergent."""
        from .occds_namespace import OCCDSNamespace

        return self._sub_namespace(OCCDSNamespace)

    # ------------------------------------------------------------------ #
    # Therapeutic-area extensions (accessed as df.adam.<ta>)               #
    # ------------------------------------------------------------------ #

    @property
    def onco(self) -> OncoNamespace:
        """Oncology derivations (admiralonco-inspired): RECIST, BOR, response flags."""
        from .onco_namespace import OncoNamespace

        return self._sub_namespace(OncoNamespace)

    @property
    def ophtha(self) -> OphthaNamespace:
        """Ophthalmology derivations (admiralophtha-inspired): ETDRS/LogMAR, study eye."""
        from .ophtha_namespace import OphthaNamespace

        return self._sub_namespace(OphthaNamespace)

    @property
    def peds(self) -> PedsNamespace:
        """Pediatrics derivations (admiralpeds-inspired): age, prematurity, BMI."""
        from .peds_namespace import PedsNamespace

        return self._sub_namespace(PedsNamespace)

    @property
    def vaccine(self) -> VaccineNamespace:
        """Vaccine derivations (admiralvaccine-inspired): fever, seroconversion."""
        from .vaccine_namespace import VaccineNamespace

        return self._sub_namespace(VaccineNamespace)

    @property
    def metabolic(self) -> MetabolicNamespace:
        """Metabolic derivations (admiralmetabolic-inspired): waist ratios, body fat."""
        from .metabolic_namespace import MetabolicNamespace

        return self._sub_namespace(MetabolicNamespace)

    @property
    def neuro(self) -> NeuroNamespace:
        """Neuroscience derivations (admiralneuro-inspired): Centiloid, MMSE, CDR-SoB."""
        from .neuro_namespace import NeuroNamespace

        return self._sub_namespace(NeuroNamespace)

    @property
    def pk(self) -> PKNamespace:
        """PK (pharmacokinetics) derivations: BLQ flags, actual/nominal time, dose normalisation."""
        from .pk_namespace import PKNamespace

        return self._sub_namespace(PKNamespace)

    @property
    def tte(self) -> TTENamespace:
        """Time-to-event (ADTTE) derivations: event/censor sources, param, AVAL, KM inputs."""
        from .tte_namespace import TTENamespace

        return self._sub_namespace(TTENamespace)
