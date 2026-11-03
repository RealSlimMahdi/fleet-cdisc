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

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, TypeVar

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

_SubNS = TypeVar("_SubNS", bound=SharedADaMVerbsMixin)


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
        by: list[str] | None = None,
        strict: bool = True,
    ) -> AdamNamespace:
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

        grps = by or ["USUBJID", "PARAMCD"]
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
    ) -> AdamNamespace:
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
    ) -> AdamNamespace:
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
    ) -> AdamNamespace:
        """Derive Body Mass Index: ``weight_kg / (height_cm / 100) ** 2``.

        Args:
            target: Name of the output column.
            weight: Column containing weight in kg.
            height: Column containing height in cm.

        Returns:
            AdamNamespace: The namespace with *target* appended.

        Examples:
            Compute BMI from weight and height::

                advs = (
                    vs_raw.adam
                    .bmi("BMI", weight="WEIGHT", height="HEIGHT")
                    .to_frame()
                )
        """
        return self._chain(_bmi_expr(weight=weight, height=height, target=target), verb="bmi")

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
    ) -> AdamNamespace:
        """Categorise *value* relative to normal range: LOW / NORMAL / HIGH.

        Args:
            target: Name of the output column (e.g. ``"NRIND"``).
            value: Column containing the numeric result.
            low: Column containing the lower limit of normal.
            high: Column containing the upper limit of normal.

        Returns:
            AdamNamespace: The namespace with *target* appended.

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
            _nrind_expr(value=value, low=low, high=high, target=target), verb="nrind"
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
    ) -> AdamNamespace:
        """Set *target* to ``"Y"`` when *adt* is within [trtsdt, trtedt].

        When *open_ended* is ``True`` (default) and *trtedt* is null, the
        interval is treated as ongoing (``adt >= trtsdt`` suffices).

        Args:
            target: Name of the output column (default ``"ONTRTFL"``).
            adt: Analysis date column.
            trtsdt: Treatment start date column.
            trtedt: Treatment end date column.
            open_ended: Treat null *trtedt* as open-ended (default ``True``).

        Returns:
            AdamNamespace: The namespace with *target* appended.

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
    ) -> AdamNamespace:
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
    ) -> AdamNamespace:
        """Derive Body Surface Area in m².

        Args:
            target: Name of the output column.
            weight: Column containing weight in kg.
            height: Column containing height in cm.
            method: Formula to use — ``"Mosteller"`` (default), ``"DuBois"``,
                ``"Haycock"``, or ``"Gehan-George"``.

        Returns:
            AdamNamespace: The namespace with *target* appended.

        Examples:
            Compute BSA using the Mosteller formula::

                advs = (
                    vs_raw.adam
                    .bsa("BSA", weight="WEIGHT", height="HEIGHT")
                    .to_frame()
                )
        """
        return self._chain(
            _bsa_expr(weight=weight, height=height, method=method, target=target), verb="bsa"
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
    ) -> AdamNamespace:
        """Derive Mean Arterial Pressure: ``DBP + (SBP - DBP) / 3``.

        Args:
            target: Name of the output column (default ``"MAP"``).
            systolic: Systolic blood pressure column.
            diastolic: Diastolic blood pressure column.

        Returns:
            AdamNamespace: The namespace with *target* appended.

        Examples:
            Compute MAP from blood pressure columns::

                advs = (
                    vs_raw.adam
                    .map("MAP", systolic="SYSBP", diastolic="DIABP")
                    .to_frame()
                )
        """
        return self._chain(
            _map_expr(systolic=systolic, diastolic=diastolic, target=target), verb="map"
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
    ) -> AdamNamespace:
        """Derive corrected QT interval, as admiral ``compute_qtc``.

        Args:
            target: Name of the output column (default ``"QTC"``).
            qt: QT interval column, in ms.
            rr: RR interval column, in *rr_unit*.
            method: Correction formula — ``"Fridericia"`` (default) or
                ``"Bazett"``.
            rr_unit: Unit of *rr*: ``"ms"`` (default) or ``"msec"``, or
                ``"s"`` or ``"sec"``.

        Returns:
            AdamNamespace: The namespace with *target* appended.

        Raises:
            DerivationError: When *rr_unit* is unknown, or a value cannot be
                in its unit: an RR under 10 in ms, an RR of 10 or more in
                seconds, or a QT under 10 ms.

        References:
            admiral ``compute_qtc`` (pharmaverse): RR in ms, QT in ms.

        Examples:
            Derive QTcF from QT and RR, both in ms::

                adeg = (
                    eg_raw.adam
                    .qtc("QTCF", qt="QT", rr="RR", method="Fridericia")
                    .to_frame()
                )
        """
        expr = _qtc_expr(qt=qt, rr=rr, method=method, target=target, rr_unit=rr_unit)
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
    ) -> AdamNamespace:
        """
        Compute a summary statistic per group and append the results as new records.

        *set_values_to*: column → value mapping applied to every new record
        (e.g. ``{"PARAMCD": "AVGBP", "DTYPE": "AVERAGE"}``).

        *stat*: ``"mean"`` (default), ``"sum"``, ``"min"``, ``"max"``, ``"median"``,
        ``"count"``.

        Materialises the current pipeline before concatenation.

        Examples:
            Compute mean AVAL per subject and parameter::

                advs = (
                    vs_raw.adam
                    .derive_summary_records(
                        by=["USUBJID", "PARAMCD"],
                        analysis_var="AVAL",
                        set_values_to={"DTYPE": "AVERAGE"},
                        stat="mean",
                    )
                    .to_frame()
                )
        """
        stat_lower = stat.lower()
        agg_map = {
            "mean": pl.col(analysis_var).mean(),
            "sum": pl.col(analysis_var).sum(),
            "min": pl.col(analysis_var).min(),
            "max": pl.col(analysis_var).max(),
            "median": pl.col(analysis_var).median(),
            "count": pl.col(analysis_var).count().cast(pl.Float64),
        }
        if stat_lower not in agg_map:
            raise DerivationError(f"Unknown stat '{stat}'. Supported: {', '.join(agg_map)}.")

        df = self.to_frame()
        summary = df.group_by(by).agg(agg_map[stat_lower].alias(analysis_var))

        # Apply constant values to the summary rows
        for col_name, col_val in set_values_to.items():
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
        return self._materialise_then(combined)

    # ------------------------------------------------------------------ #
    # 21. derive_locf_records — last observation carried forward          #
    # ------------------------------------------------------------------ #

    def derive_locf_records(
        self,
        *,
        by: list[str] | None = None,
        analysis_var: str = "AVAL",
        order_by: str = "ADT",
    ) -> AdamNamespace:
        """
        Forward-fill *analysis_var* within each group (LOCF).

        Sorts by *order_by* within each group defined by *by*,
        then forward-fills null values in *analysis_var*.

        Materialises the current pipeline, applies the fill, and returns.

        Examples:
            Forward-fill AVAL within each subject / parameter::

                advs = (
                    vs_raw.adam
                    .derive_locf_records(
                        by=["USUBJID", "PARAMCD"],
                        analysis_var="AVAL",
                        order_by="ADT",
                    )
                    .to_frame()
                )
        """
        grps = by or ["USUBJID", "PARAMCD"]
        df = self.to_frame()
        df = df.sort(grps + [order_by])
        df = df.with_columns(pl.col(analysis_var).forward_fill().over(grps).alias(analysis_var))
        return self._materialise_then(df)

    # ------------------------------------------------------------------ #
    # 22. derive_param — append a computed parameter as new records        #
    # ------------------------------------------------------------------ #

    def derive_param(
        self,
        *,
        by: list[str] | None = None,
        set_values_to: dict[str, Any],
        parameter_filter: dict[str, str],
        analysis_value: pl.Expr | str,
        from_dataset: pl.DataFrame | None = None,
        where: str | pl.Expr | None = None,
    ) -> AdamNamespace:
        """
        Derive a new parameter (e.g. BMI) from existing records and append
        the computed rows to the dataset.

        *parameter_filter*: ``{alias: PARAMCD}`` pairs identifying the source
        records to pivot on (e.g. ``{"WEIGHT": "WEIGHT", "HEIGHT": "HEIGHT"}``).
        Each key is a local alias; the value is the ``PARAMCD`` it matches.
        Every source parameter must be unique per *by* group — duplicates
        raise instead of silently multiplying the derived rows.

        *analysis_value*: a Polars expression (or YAML-friendly string)
        referencing the aliases to compute the new AVAL
        (e.g. ``pl.col("WEIGHT") / (pl.col("HEIGHT")/100)**2``).

        *set_values_to*: constant columns on the new rows — including the
        parameter-level identifiers ``PARAM``, ``PARAMN``, ``PARCATy`` /
        ``PARCATyN``, and ``DTYPE`` (e.g. ``{"PARAMCD": "BMI",
        "PARAM": "Body Mass Index", "PARAMN": 3, "PARCAT1": "ANTHRO"}``).
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

        Materialises the pipeline before appending.

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
        """
        from fleet.sdtm.utils import parse_expression

        if not parameter_filter:
            raise DerivationError("derive_param() requires at least one parameter_filter entry.")

        grps = by or ["USUBJID"]
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

        # Pivot: for each alias in parameter_filter, get AVAL as that alias
        pivoted_parts = []
        for alias, paramcd_val in parameter_filter.items():
            part = source.filter(pl.col("PARAMCD") == paramcd_val).select(
                grps + [pl.col("AVAL").alias(alias)]
            )
            dup = part.group_by(grps).len().filter(pl.col("len") > 1)
            if dup.height:
                raise DerivationError(
                    f"derive_param(): PARAMCD '{paramcd_val}' has multiple records for "
                    f"{dup.height} {grps} group(s) (e.g. {dup.select(grps).row(0)}). "
                    "The derived rows would multiply — deduplicate the source, extend "
                    "by=, or narrow the records with where=."
                )
            pivoted_parts.append(part)

        # Join all pivoted parts on the by keys
        joined = pivoted_parts[0]
        for part in pivoted_parts[1:]:
            joined = joined.join(part, on=grps, how="inner", nulls_equal=True)

        # Compute the new AVAL
        aval_expr = (
            analysis_value
            if isinstance(analysis_value, pl.Expr)
            else parse_expression(str(analysis_value))
        )
        new_rows = joined.with_columns(aval_expr.alias("AVAL")).select(grps + ["AVAL"])

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
        return self._materialise_then(combined)

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
        direction: str,
        term_var: str,
        unit_var: str | None = None,
        signif_dig: int = 5,
        indicators: dict[str, list[str]] | None = None,
    ) -> AdamNamespace:
        """Derive a toxicity grade column using a criteria-file grading system.

        Materialises the pipeline, applies the grading engine for every
        matching lab term, and returns a fresh namespace with *target*
        appended.

        Args:
            target: Name of the output grade column (e.g. ``"ATOXGRL"``).
            system: Grading system name (e.g. ``"ctcae_v5"``, ``"daids"``)
                or path to a custom JSON criteria file.
            direction: ``"L"`` (low) or ``"H"`` (high).
            term_var: Column holding the lab-test / term name.
            unit_var: Optional column holding the unit of measure.
            signif_dig: Significant figures for comparison (default 5).
            indicators: Optional indicator parameter map for branch
                conditions (e.g. ``{"H": ["HIGH"], "L": ["LOW"]}``).

        Returns:
            AdamNamespace: A fresh namespace wrapping the graded frame.

        Examples:
            Grade low-direction anemia using CTCAE v5::

                adlb = (
                    lb_raw.adam
                    .atoxgr("ATOXGRL", system="ctcae_v5",
                            direction="L", term_var="PARAMCD",
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
        low_desc_var: str | None = None,
        high_desc_var: str | None = None,
    ) -> AdamNamespace:
        """Combine low and high toxicity grades into a signed grade.

        Low grades are prefixed with ``"-"``; high grades are kept as-is.
        Both null → null.

        Args:
            target: Name of the output column (default ``"ATOXGR"``).
            low_var: Low-direction grade column (default ``"ATOXGRL"``).
            high_var: High-direction grade column (default ``"ATOXGRH"``).
            low_desc_var: Optional low-grade term description column.
            high_desc_var: Optional high-grade term description column.

        Returns:
            AdamNamespace: The namespace with *target* appended.

        Examples:
            Combine low/high grades into ATOXGR::

                adlb = (
                    lb_raw.adam
                    .atoxgr("ATOXGRL", system="ctcae_v5",
                            direction="L", term_var="PARAMCD")
                    .atoxgr("ATOXGRH", system="ctcae_v5",
                            direction="H", term_var="PARAMCD")
                    .combine_grades("ATOXGR")
                    .to_frame()
                )
        """
        from .grading._compiler import combine_grades_expr

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
    ) -> AdamNamespace:
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

    def _sub_namespace(self, cls: type[_SubNS]) -> _SubNS:
        """Hand the accumulated state over to a sub-namespace.

        The lazy plan is passed through unchanged (no materialisation)
        and pins, pin lineage, variable lineage, pending FK checks, and
        FK policy all propagate, so ``.pin("ADSL", adsl).occds`` keeps
        its pins.  The parent domain tag carries over unless the
        sub-namespace sets its own (ADSL).
        """
        new = cls(self._lazy)
        new._pinned = dict(getattr(self, "_pinned", {}))
        new._pin_lineage = list(getattr(self, "_pin_lineage", []))
        new._lineage = list(getattr(self, "_lineage", []))
        new._pending_fk_checks = list(getattr(self, "_pending_fk_checks", []))
        fk_severity = getattr(self, "_fk_severity", None)
        if fk_severity is not None:
            new._fk_severity = fk_severity
        if getattr(new, "_domain", None) is None:
            new._domain = getattr(self, "_domain", None)
        return new

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
