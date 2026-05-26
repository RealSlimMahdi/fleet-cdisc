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
              groups=["USUBJID", "PARAMCD"])
        .baseline("BASE", aval="AVAL", baseline_flag="ABLFL")
        .chg("CHG", aval="AVAL", base="BASE")
        .pchg("PCHG", aval="AVAL", base="BASE")
        .to_frame()
    )

    # Or spec-driven:
    result = vs_sdtm.adam.from_spec("examples/cdiscpilot01/adam/define.yaml", dataset="ADVS").to_frame()
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl
import yaml

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
    from .vaccine_namespace import VaccineNamespace


from fleet.core._resolve_callable import resolve_callable as _resolve_callable


@pl.api.register_dataframe_namespace("adam")
class AdamNamespace(SharedADaMVerbsMixin):
    """
    Immutable pipeline builder for ADaM derivations.

    Each verb appends to a lazy expression list; ``to_frame()`` materialises
    everything in one ``with_columns`` call (unless the verb requires a join/filter).

    Inherits shared verbs from ``SharedADaMVerbsMixin``:
    ``source``, ``derivation``, ``assigned``, ``recode``, ``rename``,
    ``condderivation``, ``whereclauses``.
    """

    # ------------------------------------------------------------------ #
    # 7. lookup — merge/join with subset conditions                       #
    # ------------------------------------------------------------------ #

    def lookup(
        self,
        target_cols: list[str] | None = None,
        *,
        dataset: pl.DataFrame,
        on: str | list[str],
        how: str = "left",
        where: str | None = None,
    ) -> AdamNamespace:
        """SQL-style join against a lookup *dataset*.

        Optionally filters *dataset* with *where* before the join.
        Materialises the current pipeline then returns a fresh namespace.

        Args:
            target_cols: Optional columns to keep from the joined result.
            dataset: The lookup ``pl.DataFrame`` to join.
            on: Key column name(s) for the join.
            how: Join strategy (default ``"left"``).
            where: Optional filter expression applied to *dataset* before
                the join.

        Returns:
            AdamNamespace: A fresh namespace wrapping the joined frame.

        Examples:
            Join a parameter-code lookup table on ``VSTESTCD``::

                advs = (
                    vs_df.adam
                    .lookup(
                        dataset=paramcd_lookup,
                        on="VSTESTCD",
                        how="left",
                    )
                    .to_frame()
                )
        """
        from ..sdtm.utils import parse_expression

        lookup_df = dataset
        if where:
            filter_expr = parse_expression(where)
            lookup_df = dataset.filter(filter_expr)

        joined = self.to_frame().join(lookup_df, on=on, how=how)
        ns = self._materialise_then(joined)
        if target_cols:
            ns._pipeline = [pl.col(c) for c in target_cols]
        return ns

    # ------------------------------------------------------------------ #
    # 9.  baseline — propagate baseline value to all group records        #
    # ------------------------------------------------------------------ #

    def baseline(
        self,
        target: str,
        *,
        aval: str = "AVAL",
        baseline_flag: str = "ABLFL",
        groups: list[str] | None = None,
    ) -> AdamNamespace:
        """Derive BASE as the AVAL where the baseline flag equals ``"Y"``.

        Uses a window function so all records in the same group receive the
        same baseline value.

        Args:
            target: Name of the output column (e.g. ``"BASE"``).
            aval: Analysis value column (default ``"AVAL"``).
            baseline_flag: Flag column indicating the baseline record.
            groups: Partition columns (default ``["USUBJID", "PARAMCD"]``).

        Returns:
            AdamNamespace: The namespace with *target* appended.

        Examples:
            Propagate baseline AVAL to all records::

                advs = (
                    vs_raw.adam
                    .baseline("BASE", aval="AVAL", baseline_flag="ABLFL",
                              groups=["USUBJID", "PARAMCD"])
                    .to_frame()
                )
        """
        return self._chain(
            baseline(aval=aval, baseline_flag_col=baseline_flag, group_by=groups, target=target)
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
        return self._chain(chg(aval=aval, base=base, target=target))

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
        return self._chain(pchg(aval=aval, base=base, target=target))

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
        return self._chain(_bmi_expr(weight=weight, height=height, target=target))

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
        return self._chain(_nrind_expr(value=value, low=low, high=high, target=target))

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
            )
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
            _shift_expr(baseline_cat=baseline_cat, post_cat=post_cat, target=target, sep=sep)
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
        return self._chain(_bsa_expr(weight=weight, height=height, method=method, target=target))

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
        return self._chain(_map_expr(systolic=systolic, diastolic=diastolic, target=target))

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
    ) -> AdamNamespace:
        """Derive corrected QT interval.

        Args:
            target: Name of the output column (default ``"QTC"``).
            qt: QT interval column.
            rr: RR interval column.
            method: Correction formula — ``"Fridericia"`` (default) or
                ``"Bazett"``.

        Returns:
            AdamNamespace: The namespace with *target* appended.

        Examples:
            Derive QTcF from QT and RR::

                adeg = (
                    eg_raw.adam
                    .qtc("QTCF", qt="QT", rr="RR", method="Fridericia")
                    .to_frame()
                )
        """
        return self._chain(_qtc_expr(qt=qt, rr=rr, method=method, target=target))

    # ------------------------------------------------------------------ #
    # 20. derive_summary_records — aggregate and append new rows          #
    # ------------------------------------------------------------------ #

    def derive_summary_records(
        self,
        *,
        by_vars: list[str],
        analysis_var: str = "AVAL",
        set_values_to: dict[str, Any],
        stat: str = "mean",
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
                        by_vars=["USUBJID", "PARAMCD"],
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
            raise ValueError(f"Unknown stat '{stat}'. Supported: {', '.join(agg_map)}.")

        df = self.to_frame()
        summary = df.group_by(by_vars).agg(agg_map[stat_lower].alias(analysis_var))

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
        by_vars: list[str] | None = None,
        analysis_var: str = "AVAL",
        order_by: str = "ADT",
    ) -> AdamNamespace:
        """
        Forward-fill *analysis_var* within each group (LOCF).

        Sorts by *order_by* within each group defined by *by_vars*,
        then forward-fills null values in *analysis_var*.

        Materialises the current pipeline, applies the fill, and returns.

        Examples:
            Forward-fill AVAL within each subject / parameter::

                advs = (
                    vs_raw.adam
                    .derive_locf_records(
                        by_vars=["USUBJID", "PARAMCD"],
                        analysis_var="AVAL",
                        order_by="ADT",
                    )
                    .to_frame()
                )
        """
        grps = by_vars or ["USUBJID", "PARAMCD"]
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
        by_vars: list[str] | None = None,
        set_values_to: dict[str, Any],
        parameter_filter: dict[str, str],
        analysis_value: pl.Expr,
    ) -> AdamNamespace:
        """
        Derive a new parameter (e.g. BMI) from existing records and append
        the computed rows to the dataset.

        *parameter_filter*: ``{PARAMCD: value}`` pairs identifying the source
        records to pivot on (e.g. ``{"WEIGHT": "WEIGHT", "HEIGHT": "HEIGHT"}``).
        Each key is a local alias; the value is the ``PARAMCD`` it matches.

        *analysis_value*: a Polars expression referencing the aliases to
        compute the new AVAL (e.g. ``pl.col("WEIGHT") / (pl.col("HEIGHT")/100)**2``).

        *set_values_to*: constant columns on the new rows
        (e.g. ``{"PARAMCD": "BMI", "PARAM": "Body Mass Index"}``).

        Materialises the pipeline before appending.

        Examples:
            Derive BMI as a new PARAMCD from WEIGHT and HEIGHT::

                advs = (
                    vs_raw.adam
                    .derive_param(
                        by_vars=["USUBJID", "ADT"],
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
        """
        grps = by_vars or ["USUBJID"]
        df = self.to_frame()

        # Pivot: for each alias in parameter_filter, get AVAL as that alias
        pivoted_parts = []
        for alias, paramcd_val in parameter_filter.items():
            part = df.filter(pl.col("PARAMCD") == paramcd_val).select(
                grps + [pl.col("AVAL").alias(alias)]
            )
            pivoted_parts.append(part)

        # Join all pivoted parts on the by_vars
        joined = pivoted_parts[0]
        for part in pivoted_parts[1:]:
            joined = joined.join(part, on=grps, how="inner")

        # Compute the new AVAL
        new_rows = joined.with_columns(analysis_value.alias("AVAL")).select(grps + ["AVAL"])

        # Apply set_values_to constants
        for col_name, col_val in set_values_to.items():
            new_rows = new_rows.with_columns(pl.lit(col_val).alias(col_name))

        # Align schemas and concat
        for c in df.columns:
            if c not in new_rows.columns:
                new_rows = new_rows.with_columns(pl.lit(None).cast(df.schema[c]).alias(c))
        new_rows = new_rows.select(df.columns)

        combined = pl.concat([df, new_rows], how="vertical_relaxed")
        return self._materialise_then(combined)

    # ------------------------------------------------------------------ #
    # Private: YAML spec dispatcher for algorithm: std_function           #
    # ------------------------------------------------------------------ #

    def _std_function_dispatch(
        self,
        target: str,
        func: str,
        *,
        analysis_date: str | None = None,
        reference_date: str | None = None,
        aval: str = "AVAL",
        base: str = "BASE",
        weight: str | None = None,
        height: str | None = None,
        systolic: str | None = None,
        diastolic: str | None = None,
        qt: str | None = None,
        rr: str | None = None,
        method: str | None = None,
        baseline_flag: str = "ABLFL",
        baseline_criteria: str | pl.Expr | None = None,
        groups: list[str] | None = None,
    ) -> AdamNamespace:
        """Route YAML ``algorithm: std_function`` entries to the appropriate typed method."""
        func = func.lower()
        if func == "study_day":
            if not analysis_date or not reference_date:
                raise ValueError("study_day requires analysis_date and reference_date.")
            return self.duration(target, start=reference_date, end=analysis_date)
        elif func == "baseline":
            return self.baseline(target, aval=aval, baseline_flag=baseline_flag, groups=groups)
        elif func == "chg":
            return self.chg(target, aval=aval, base=base)
        elif func == "pchg":
            return self.pchg(target, aval=aval, base=base)
        elif func in ("flag_baseline", "flag"):
            if baseline_criteria is None:
                raise ValueError("flag requires baseline_criteria.")
            return self.flag(target, criteria=baseline_criteria, groups=groups)
        elif func == "bmi":
            if not weight or not height:
                raise ValueError("bmi requires weight and height.")
            return self.bmi(target, weight=weight, height=height)
        elif func == "bsa":
            if not weight or not height:
                raise ValueError("bsa requires weight and height.")
            return self.bsa(target, weight=weight, height=height, method=method or "Mosteller")
        elif func in ("map", "mean_arterial_pressure"):
            if not systolic or not diastolic:
                raise ValueError("map requires systolic and diastolic.")
            return self.map(target, systolic=systolic, diastolic=diastolic)
        elif func == "qtc":
            if not qt or not rr:
                raise ValueError("qtc requires qt and rr.")
            return self.qtc(target, qt=qt, rr=rr, method=method or "Fridericia")
        else:
            raise ValueError(
                f"Unknown func='{func}'. "
                "Valid: study_day, baseline, chg, pchg, flag, flag_baseline, "
                "bmi, bsa, map, qtc."
            )

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
            ).alias(target)
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
                    .assigned("STUDYID", value="S01")
                    .transform("add_agegr1")
                    .to_frame()
                )
        """
        from .transforms import get_transform

        if isinstance(fn, str):
            fn = get_transform(fn)  # raises KeyError if not found
        elif not callable(fn):
            raise TypeError(
                f"transform() expects a callable or a registered name string, "
                f"got {type(fn).__name__!r}."
            )

        # Materialise pending expressions so the function sees a full frame.
        committed = self.to_frame()
        result = fn(committed)

        if not isinstance(result, pl.DataFrame):
            raise TypeError(
                f"Transform function must return a polars DataFrame, got {type(result).__name__!r}."
            )

        return self._materialise_then(result)

    # ------------------------------------------------------------------ #
    # Spec-driven pipeline                                                 #
    # ------------------------------------------------------------------ #

    def from_spec(
        self,
        spec_path: str | Path,
        *,
        dataset: str | None = None,
        only: list[str] | None = None,
        omit: list[str] | None = None,
    ) -> AdamNamespace:
        """
        Build an ADaM derivation pipeline from a YAML specification file.

        Reads a ``define.yaml`` with a top-level ``datasets`` list where each
        variable carries a ``derivation`` block.  Pass *dataset* to select
        which dataset to execute (e.g. ``dataset="ADVS"``).  When the file
        contains only one dataset the *dataset* argument may be omitted.

        *only*: optional allow-list — process only the listed variable names.
        *omit*: optional deny-list — skip the listed variable names; useful when
        you want to override a spec variable with custom inline logic::

            dm.adam.from_spec(..., omit=["MYVAR"]).assigned("MYVAR", value="override")

        ``only`` and ``omit`` are mutually exclusive; specifying both raises
        ``ValueError``.

        For dependency-driven staging, declare
        ``depends_on: [col, ...]`` in the YAML derivation block instead;
        ``from_spec()`` will flush automatically before any variable whose
        declared dependencies are not yet committed to the frame::

            # define.yaml
            - name: ADY
              derivation:
                algorithm: study_day
                analysis_date: ADT
                reference_date: TRTSDT
                depends_on: [ADT]    # flush before ADY if ADT only pending

        With ``depends_on`` set, a single call suffices::

            advs = vs_df.adam.from_spec("specs/.../define.yaml", dataset="ADVS").to_frame()

        Examples:
            Build ADVS from a YAML specification::

                advs = (
                    vs_raw.adam
                    .from_spec("examples/cdiscpilot01/adam/define.yaml",
                               dataset="ADVS")
                    .to_frame()
                )
        """
        from .models import ADAMDatasetSpec

        if only is not None and omit is not None:
            raise ValueError(
                "Cannot specify both only= and omit= in from_spec(). "
                "Use only= to allow-list variables, or omit= to deny-list them."
            )

        spec_data = yaml.safe_load(Path(spec_path).read_text())

        # ── Detect format: define.yaml has a top-level "datasets" key ──
        if "datasets" in spec_data:
            variables = self._extract_define_variables(spec_data, dataset)
        else:
            spec = ADAMDatasetSpec(**spec_data)
            variables = spec.variables

        ns: AdamNamespace = self
        for var in variables:
            alg = var.algorithm.value
            target = var.target
            if only is not None and target not in only:
                continue
            if omit is not None and target in omit:
                continue

            # ── auto-flush when a declared dependency is not yet committed ──
            deps = getattr(var, "depends_on", None) or []
            if deps and any(d not in ns._lazy.columns for d in deps):
                ns = ns._materialise_then(ns.to_frame())

            if alg == "source":
                ns = ns.source(target, from_col=var.source)
            elif alg == "derivation":
                ns = ns.derivation(target, expression=var.expression or target)
            elif alg == "assigned":
                ns = ns.assigned(target, value=var.value)
            elif alg == "recode":
                ns = ns.recode(
                    target,
                    source=var.source or target,
                    recode_map=var.recode_map or {},
                    default=var.default,
                )
            elif alg == "rename":
                ns = ns.rename(target, source=var.source or target)
            elif alg == "condderivation":
                ns = ns.condderivation(
                    target, conditions=var.conditions or [], else_value=var.else_value
                )
            # First-class BDS algorithm names usable directly in YAML specs
            elif alg in (
                "study_day",
                "baseline",
                "chg",
                "pchg",
                "bmi",
                "bsa",
                "map",
                "mean_arterial_pressure",
                "qtc",
            ):
                ns = ns._std_function_dispatch(
                    target,
                    func=alg,
                    analysis_date=var.analysis_date,
                    reference_date=var.reference_date,
                    aval=var.aval or "AVAL",
                    base=var.base or "BASE",
                    weight=var.weight,
                    height=var.height,
                    systolic=getattr(var, "systolic", None),
                    diastolic=getattr(var, "diastolic", None),
                    qt=getattr(var, "qt", None),
                    rr=getattr(var, "rr", None),
                    method=getattr(var, "method", None),
                    baseline_flag=var.baseline_flag or "ABLFL",
                    groups=getattr(var, "groups", None),
                )
            elif alg == "flag":
                ns = ns.flag(
                    target,
                    criteria=getattr(var, "criteria", "") or "",
                    groups=getattr(var, "groups", None),
                    order_by=getattr(var, "flag_order_by", None),
                    value_col=getattr(var, "flag_value_col", None),
                    where=getattr(var, "flag_where", None),
                )
            elif alg == "date":
                kwargs: dict[str, Any] = {}
                if var.source:
                    kwargs["source"] = var.source
                elif getattr(var, "value", None):
                    kwargs["value"] = var.value
                if getattr(var, "output", None):
                    kwargs["output"] = var.output
                if getattr(var, "impute", None):
                    kwargs["impute"] = var.impute
                if getattr(var, "impute_time", None):
                    kwargs["impute_time"] = var.impute_time
                if getattr(var, "flag", None) is not None:
                    kwargs["flag"] = var.flag
                ns = ns.date(target, **kwargs)
            elif alg == "duration":
                ns = ns.duration(
                    target,
                    start=getattr(var, "start", None) or var.analysis_date or "",
                    end=getattr(var, "end", None) or var.reference_date or "",
                    unit=getattr(var, "unit", "days") or "days",
                )
            elif alg == "nrind":
                ns = ns.nrind(
                    target,
                    value=var.aval or "AVAL",
                    low=getattr(var, "low", "LBSTNRLO"),
                    high=getattr(var, "high", "LBSTNRHI"),
                )
            elif alg == "on_treatment":
                ns = ns.on_treatment(
                    target,
                    adt=var.analysis_date or "ADT",
                    trtsdt=var.reference_date or "TRTSDT",
                    trtedt=getattr(var, "trtedt", "TRTEDT"),
                )
            elif alg == "shift":
                ns = ns.shift(
                    target,
                    baseline_cat=getattr(var, "baseline_cat", ""),
                    post_cat=getattr(var, "post_cat", ""),
                )
            elif alg == "whereclauses":
                if var.where:
                    ns = ns.whereclauses(where=var.where)
            elif alg == "pick":
                pick_targets = getattr(var, "targets", None) or [target]
                pick_events = getattr(var, "events", None) or []
                pick_by = getattr(var, "by", None)
                pick_order = getattr(var, "order", None)
                pick_mode = getattr(var, "mode", "first") or "first"
                ns = ns.pick(
                    pick_targets,
                    events=pick_events,
                    by=pick_by,
                    order=pick_order,
                    mode=pick_mode,
                )
            elif alg == "callable":
                fn = _resolve_callable(var.callable_ref or "")
                if hasattr(fn, "kind"):
                    ns = ns.derivation(fn)
                else:
                    ns = ns._materialise_then(fn(ns.to_frame()))
            else:
                import warnings

                warnings.warn(
                    f"from_spec: skipping variable '{target}' — "
                    f"algorithm '{alg}' is not supported in spec-driven mode.",
                    stacklevel=2,
                )

        return ns

    @staticmethod
    def _extract_define_variables(spec_data: dict, dataset: str | None) -> list:
        """Convert define.yaml dataset variables into ADAMVariableSpec objects."""
        from .models import ADAMVariableSpec

        datasets = spec_data["datasets"]
        if dataset is None:
            if len(datasets) != 1:
                names = [d["name"] for d in datasets]
                raise ValueError(
                    f"define.yaml contains {len(datasets)} datasets {names}. "
                    "Pass dataset= to select one."
                )
            ds = datasets[0]
        else:
            matches = [d for d in datasets if d["name"].upper() == dataset.upper()]
            if not matches:
                names = [d["name"] for d in datasets]
                raise ValueError(
                    f"Dataset '{dataset}' not found in define.yaml. Available: {names}"
                )
            ds = matches[0]

        result = []
        for var in ds["variables"]:
            drv = var.get("derivation")
            if not drv:
                continue  # no derivation → carry-through / manual column
            # Backward compat: callable: without algorithm: → inject algorithm.
            if "callable" in drv and "algorithm" not in drv:
                drv = {**drv, "algorithm": "callable"}
            spec = ADAMVariableSpec(
                target=var["name"],
                **drv,
            )
            result.append(spec)
        return result

    # ------------------------------------------------------------------ #
    # ADaM sub-structures (accessed as df.adam.adsl / df.adam.occds)       #
    # ------------------------------------------------------------------ #

    @property
    def adsl(self) -> ADSLNamespace:
        """ADSL (one-row-per-subject) derivations: treatment dates, duration, population flags."""
        from .adsl_namespace import ADSLNamespace

        return ADSLNamespace(self.to_frame())

    @property
    def occds(self) -> OCCDSNamespace:
        """OCCDS (one-row-per-event) derivations: sequencing, worst flag, treatment-emergent."""
        from .occds_namespace import OCCDSNamespace

        return OCCDSNamespace(self.to_frame())

    # ------------------------------------------------------------------ #
    # Therapeutic-area extensions (accessed as df.adam.<ta>)               #
    # ------------------------------------------------------------------ #

    @property
    def onco(self) -> OncoNamespace:
        """Oncology derivations (admiralonco-inspired): RECIST, BOR, response flags."""
        from .onco_namespace import OncoNamespace

        return OncoNamespace(self.to_frame())

    @property
    def ophtha(self) -> OphthaNamespace:
        """Ophthalmology derivations (admiralophtha-inspired): ETDRS/LogMAR, study eye."""
        from .ophtha_namespace import OphthaNamespace

        return OphthaNamespace(self.to_frame())

    @property
    def peds(self) -> PedsNamespace:
        """Pediatrics derivations (admiralpeds-inspired): age, prematurity, BMI."""
        from .peds_namespace import PedsNamespace

        return PedsNamespace(self.to_frame())

    @property
    def vaccine(self) -> VaccineNamespace:
        """Vaccine derivations (admiralvaccine-inspired): fever, seroconversion."""
        from .vaccine_namespace import VaccineNamespace

        return VaccineNamespace(self.to_frame())

    @property
    def metabolic(self) -> MetabolicNamespace:
        """Metabolic derivations (admiralmetabolic-inspired): waist ratios, body fat."""
        from .metabolic_namespace import MetabolicNamespace

        return MetabolicNamespace(self.to_frame())

    @property
    def neuro(self) -> NeuroNamespace:
        """Neuroscience derivations (admiralneuro-inspired): Centiloid, MMSE, CDR-SoB."""
        from .neuro_namespace import NeuroNamespace

        return NeuroNamespace(self.to_frame())

    @property
    def pk(self) -> PKNamespace:
        """PK (pharmacokinetics) derivations: BLQ flags, actual/nominal time, dose normalisation."""
        from .pk_namespace import PKNamespace

        return PKNamespace(self.to_frame())
