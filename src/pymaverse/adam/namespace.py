"""
ADaM Polars namespace extension (BDS datasets).

Registers ``df.adam`` on every Polars DataFrame.
For patient-level (ADSL) derivations use ``df.adsl``.
For occurrence datasets (ADAE/ADCM) use ``df.occds``.

Usage
-----
    import pymaverse  # triggers registration of df.adam, df.adsl, df.occds

    result = (
        vs_sdtm.adam
        .source("USUBJID")
        .rename("ADT", source="VSDTC")
        .derivation("AVAL", expression="VSSTRESN")
        .study_day("ADY", analysis_date="ADT", reference_date="TRTSDT")
        .flag("ABLFL", criteria='pl.col("VISITNUM") == 1',
              groups=["USUBJID", "PARAMCD"])
        .baseline("BASE", aval="AVAL", baseline_flag="ABLFL")
        .chg("CHG", aval="AVAL", base="BASE")
        .pchg("PCHG", aval="AVAL", base="BASE")
        .to_frame()
    )

    # Or spec-driven:
    result = vs_sdtm.adam.from_spec("specs/cdiscpilot01/adam/define.yaml", dataset="ADVS").to_frame()
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

import polars as pl
import yaml

from .utils import (
    baseline,
    bmi as _bmi_expr,
    chg,
    flag_baseline,
    nrind as _nrind_expr,
    on_treatment as _on_treatment_expr,
    pchg,
    shift as _shift_expr,
    study_day,
)

if TYPE_CHECKING:
    pass


@pl.api.register_dataframe_namespace("adam")
class AdamNamespace:
    """
    Immutable pipeline builder for ADaM derivations.

    Each verb appends to a lazy expression list; ``to_frame()`` materialises
    everything in one ``with_columns`` call (unless the verb requires a join/filter).
    """

    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df
        self._pipeline: list[pl.Expr] = []

    # ------------------------------------------------------------------ #
    # Internal chaining helper                                             #
    # ------------------------------------------------------------------ #

    def _chain(self, *exprs: pl.Expr) -> "AdamNamespace":
        new = object.__new__(AdamNamespace)
        new._df = self._df
        new._pipeline = self._pipeline + list(exprs)
        return new

    def _materialise_then(self, df: pl.DataFrame) -> "AdamNamespace":
        """Return a new namespace wrapping *df* with an empty pipeline."""
        new = object.__new__(AdamNamespace)
        new._df = df
        new._pipeline = []
        return new

    # ------------------------------------------------------------------ #
    # 1. source — direct copy from predecessor (SDTM) variable            #
    # ------------------------------------------------------------------ #

    def source(self, target: str, *, from_col: str | None = None) -> "AdamNamespace":
        """
        Direct copy from a predecessor SDTM column.

        If *from_col* is omitted, *target* is assumed to exist already and
        a pass-through identity expression is added (ensures column order).
        """
        src = from_col if from_col is not None else target
        return self._chain(pl.col(src).alias(target))

    # ------------------------------------------------------------------ #
    # 2. derivation — expression-based derivation                         #
    # ------------------------------------------------------------------ #

    def derivation(
        self,
        target: str,
        *,
        expression: str | pl.Expr,
    ) -> "AdamNamespace":
        """
        Derive *target* using a Polars expression or expression string.

        Example::

            .derivation("AVAL", expression="VSSTRESN")
            .derivation("AVAL", expression='pl.col("VSSTRESN").cast(pl.Float64)')
        """
        from ..sdtm.utils import parse_expression

        expr = expression if isinstance(expression, pl.Expr) else parse_expression(str(expression))
        return self._chain(expr.alias(target))

    # ------------------------------------------------------------------ #
    # 3. assigned — global constant for all records                       #
    # ------------------------------------------------------------------ #

    def assigned(self, target: str, *, value: Any) -> "AdamNamespace":
        """Set *target* to a constant *value* for every record."""
        return self._chain(pl.lit(value).alias(target))

    # ------------------------------------------------------------------ #
    # 3b. assign_datetime — convert raw date/datetime to ISO 8601         #
    # ------------------------------------------------------------------ #

    def assign_datetime(
        self,
        target: str,
        *,
        source: str,
        mode: str = "date",
        input_format: str | None = None,
    ) -> "AdamNamespace":
        """
        Parse *source* date string and store as ISO 8601 in *target*.

        *mode*: ``"date"`` → YYYY-MM-DD, ``"datetime"`` → YYYY-MM-DDTHH:MM:SS.

        Example::

            .assign_datetime("ADT", source="vsdtc", mode="date")
        """
        from ..sdtm.utils import to_iso8601_date, to_iso8601_datetime

        fn = to_iso8601_datetime if mode == "datetime" else to_iso8601_date
        expr = pl.col(source).map_elements(fn, return_dtype=pl.String).alias(target)
        return self._chain(expr)

    # ------------------------------------------------------------------ #
    # 4. recode — recode / group existing variable values                 #
    # ------------------------------------------------------------------ #

    def recode(
        self,
        target: str,
        *,
        source: str,
        recode_map: dict[Any, Any],
        default: Any = None,
    ) -> "AdamNamespace":
        """
        Map raw values in *source* to recoded values.

        Unmapped values get *default* (null by default).

        Example::

            .recode("AVISIT", source="visit_label", recode_map={
                "Week 1": "WEEK 1",
                "Week 4": "WEEK 4",
            }, default=pl.col("visit_label"))
        """
        # Build an if/then/else chain to avoid the deprecated replace(default=) API.
        if recode_map:
            # Start from first mapping
            items = list(recode_map.items())
            k0, v0 = items[0]
            chain = pl.when(pl.col(source) == k0).then(pl.lit(v0))
            for k, v in items[1:]:
                chain = chain.when(pl.col(source) == k).then(pl.lit(v))
            default_expr = default if isinstance(default, pl.Expr) else pl.lit(default)
            expr = chain.otherwise(default_expr).alias(target)
        else:
            default_expr = default if isinstance(default, pl.Expr) else pl.lit(default)
            expr = default_expr.alias(target)
        return self._chain(expr)

    # ------------------------------------------------------------------ #
    # 5. rename — rename a column (e.g., VSDTC → ADT)                    #
    # ------------------------------------------------------------------ #

    def rename(self, target: str, *, source: str) -> "AdamNamespace":
        """Create *target* as a copy of *source* (use for variable renaming)."""
        return self._chain(pl.col(source).alias(target))

    # ------------------------------------------------------------------ #
    # 6. condderivation — complex conditional derivation                  #
    # ------------------------------------------------------------------ #

    def condderivation(
        self,
        target: str,
        *,
        conditions: list[dict[str, Any]],
        else_value: Any = None,
    ) -> "AdamNamespace":
        """
        Multi-branch conditional derivation.

        *conditions*: list of ``{"condition": expr_str | pl.Expr, "value": any}``.

        Example::

            .condderivation("DTYPE", conditions=[
                {"condition": 'pl.col("AVISITN") == 0', "value": "BASELINE"},
            ], else_value=None)
        """
        from ..sdtm.utils import parse_expression

        if not conditions:
            return self._chain(pl.lit(else_value).alias(target))

        first = conditions[0]
        c0 = first["condition"] if isinstance(first["condition"], pl.Expr) else parse_expression(str(first["condition"]))
        chain = pl.when(c0).then(pl.lit(first["value"]))
        for branch in conditions[1:]:
            c = branch["condition"] if isinstance(branch["condition"], pl.Expr) else parse_expression(str(branch["condition"]))
            chain = chain.when(c).then(pl.lit(branch["value"]))
        expr = chain.otherwise(pl.lit(else_value)).alias(target)
        return self._chain(expr)

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
    ) -> "AdamNamespace":
        """
        SQL-style join against a lookup *dataset*.

        *where*: optional filter applied to *dataset* before the join.
        Materialises current pipeline then returns a fresh namespace.
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
    # 8.  study_day — CDISC study day derivation                          #
    # ------------------------------------------------------------------ #

    def study_day(
        self,
        target: str,
        *,
        analysis_date: str,
        reference_date: str,
    ) -> "AdamNamespace":
        """
        Compute study day: ``(analysis_date - reference_date)`` with CDISC convention.

        Day 1 = reference date; there is no day 0 (pre-reference days are negative).

        Example::

            .study_day("ADY", analysis_date="ADT", reference_date="TRTSDT")
        """
        return self._chain(study_day(analysis_date, reference_date, target=target))

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
    ) -> "AdamNamespace":
        """
        Derive BASE as the AVAL at the baseline record (``baseline_flag == "Y"``.

        Uses a window function — all records in the same group receive the same value.

        Example::

            .baseline("BASE", aval="AVAL", baseline_flag="ABLFL",
                       groups=["USUBJID", "PARAMCD"])
        """
        return self._chain(
            baseline(aval=aval, baseline_flag_col=baseline_flag,
                     group_by=groups, target=target)
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
    ) -> "AdamNamespace":
        """
        Change from baseline: ``CHG = AVAL - BASE``.

        Example::

            .chg("CHG", aval="AVAL", base="BASE")
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
    ) -> "AdamNamespace":
        """
        Percent change from baseline: ``PCHG = (AVAL - BASE) / BASE * 100``.

        Returns null when BASE is null or zero.

        Example::

            .pchg("PCHG", aval="AVAL", base="BASE")
        """
        return self._chain(pchg(aval=aval, base=base, target=target))

    # ------------------------------------------------------------------ #
    # 12. flag — generalised "Y" / null flagging                          #
    # ------------------------------------------------------------------ #

    def flag(
        self,
        target: str,
        *,
        criteria: str | pl.Expr,
        groups: list[str] | None = None,
        order_by: str | None = None,
        value_col: str | None = None,
        where: str | pl.Expr | None = None,
        flag_value: str = "Y",
    ) -> "AdamNamespace":
        """
        Set *target* to *flag_value* (default ``"Y"``) for records matching *criteria*.

        *criteria* accepts:

        - Any Polars expression or expression string (row-level boolean)
        - ``"first"`` — first record per group ordered by *order_by*
        - ``"last"``  — last record per group ordered by *order_by*
        - ``"max"``   — record(s) with maximum *value_col* per group
        - ``"min"``   — record(s) with minimum *value_col* per group

        *groups*: partition columns (default ``["USUBJID", "PARAMCD"]``).
        *where*:  optional pre-filter — only rows satisfying this are candidates.

        Examples::

            # Baseline flag by visit number
            .flag("ABLFL",    criteria='pl.col("VISITNUM") == 1',
                               groups=["USUBJID", "PARAMCD"])

            # Last on-treatment observation per parameter
            .flag("LSTOBSFL", criteria="last", order_by="ADT",
                               groups=["USUBJID", "PARAMCD"],
                               where='pl.col("ONTRTFL") == "Y"')

            # Record with peak AVAL per parameter
            .flag("AMXFL",    criteria="max", value_col="AVAL",
                               groups=["USUBJID", "PARAMCD"])
        """
        from ..sdtm.utils import parse_expression

        grps = groups or ["USUBJID", "PARAMCD"]

        if isinstance(criteria, str) and criteria in ("first", "last", "max", "min"):
            if criteria in ("first", "last"):
                if not order_by:
                    raise ValueError(f"flag criteria='{criteria}' requires order_by.")
                descending = criteria == "last"
                row_cond = (
                    pl.col(order_by).rank("ordinal", descending=descending).over(grps) == 1
                )
            else:
                if not value_col:
                    raise ValueError(f"flag criteria='{criteria}' requires value_col.")
                agg_val = (
                    pl.col(value_col).max().over(grps)
                    if criteria == "max"
                    else pl.col(value_col).min().over(grps)
                )
                row_cond = pl.col(value_col) == agg_val
        else:
            row_cond = (
                criteria if isinstance(criteria, pl.Expr)
                else parse_expression(str(criteria))
            )

        if where is not None:
            where_expr = (
                where if isinstance(where, pl.Expr)
                else parse_expression(str(where))
            )
            final_cond = where_expr & row_cond
        else:
            final_cond = row_cond

        return self._chain(
            pl.when(final_cond)
            .then(pl.lit(flag_value))
            .otherwise(pl.lit(None))
            .alias(target)
        )

    # ------------------------------------------------------------------ #
    # 13. bmi — Body Mass Index                                            #
    # ------------------------------------------------------------------ #

    def bmi(
        self,
        target: str,
        *,
        weight: str,
        height: str,
    ) -> "AdamNamespace":
        """
        BMI = weight_kg / (height_cm / 100) ** 2.

        Example::

            .bmi("BMI", weight="WEIGHT", height="HEIGHT")
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
    ) -> "AdamNamespace":
        """
        Categorise *value* relative to normal range columns: LOW / NORMAL / HIGH.

        Example::

            .nrind("LBNRIND", value="LBSTRESN", low="LBSTNRLO", high="LBSTNRHI")
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
    ) -> "AdamNamespace":
        """
        Set *target* to ``"Y"`` when *adt* falls within [trtsdt, trtedt] (inclusive).

        Example::

            .on_treatment("ONTRTFL", adt="ADT", trtsdt="TRTSDT", trtedt="TRTEDT")
        """
        return self._chain(
            _on_treatment_expr(adt=adt, trtsdt=trtsdt, trtedt=trtedt, target=target)
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
    ) -> "AdamNamespace":
        """
        Categorical shift label: ``"<baseline_cat><sep><post_cat>"``.

        Example::

            .shift("SHIFT1", baseline_cat="BNRIND", post_cat="NRIND")
            # → "NORMAL to HIGH", "NORMAL to LOW", etc.
        """
        return self._chain(
            _shift_expr(baseline_cat=baseline_cat, post_cat=post_cat,
                        target=target, sep=sep)
        )

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
        baseline_flag: str = "ABLFL",
        baseline_criteria: str | pl.Expr | None = None,
        groups: list[str] | None = None,
    ) -> "AdamNamespace":
        """Route YAML ``algorithm: std_function`` entries to the appropriate typed method."""
        func = func.lower()
        if func == "study_day":
            if not analysis_date or not reference_date:
                raise ValueError("study_day requires analysis_date and reference_date.")
            return self.study_day(target, analysis_date=analysis_date,
                                   reference_date=reference_date)
        elif func == "baseline":
            return self.baseline(target, aval=aval, baseline_flag=baseline_flag,
                                  groups=groups)
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
        else:
            raise ValueError(
                f"Unknown func='{func}'. "
                "Valid: study_day, baseline, chg, pchg, flag, flag_baseline, bmi."
            )

    # ------------------------------------------------------------------ #
    # 17. whereclauses — value-level subsetting (filter rows)             #
    # ------------------------------------------------------------------ #

    def whereclauses(self, *, where: str | pl.Expr) -> "AdamNamespace":
        """
        Filter the dataset to records matching *where*.

        This materialises the current pipeline before filtering.

        *where*: a Polars expression or expression string.

        Example::

            .whereclauses(where='pl.col("PARAMCD") == "SYSBP"')
        """
        from ..sdtm.utils import parse_expression

        df = self.to_frame()
        filter_expr = where if isinstance(where, pl.Expr) else parse_expression(str(where))
        return self._materialise_then(df.filter(filter_expr))

    # ------------------------------------------------------------------ #
    # Spec-driven pipeline                                                 #
    # ------------------------------------------------------------------ #

    def from_spec(
        self,
        spec_path: str | Path,
        *,
        dataset: str | None = None,
        only: "list[str] | None" = None,
    ) -> "AdamNamespace":
        """
        Build an ADaM derivation pipeline from a YAML specification file.

        Reads a ``define.yaml`` with a top-level ``datasets`` list where each
        variable carries a ``derivation`` block.  Pass *dataset* to select
        which dataset to execute (e.g. ``dataset="ADVS"``).  When the file
        contains only one dataset the *dataset* argument may be omitted.

        *only*: optional allow-list — power-user override to process a subset of
        variables from the spec.  For dependency-driven staging, declare
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

        Example::

            vs_df.adam.from_spec("specs/cdiscpilot01/adam/define.yaml", dataset="ADVS").to_frame()
        """
        from .models import ADAMDatasetSpec

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

            # ── auto-flush when a declared dependency is not yet committed ──
            deps = getattr(var, "depends_on", None) or []
            if deps and any(d not in ns._df.columns for d in deps):
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
                ns = ns.condderivation(target, conditions=var.conditions or [], else_value=var.else_value)
            elif alg == "std_function":
                ns = ns._std_function_dispatch(
                    target,
                    func=var.func or "chg",
                    analysis_date=var.analysis_date,
                    reference_date=var.reference_date,
                    aval=var.aval or "AVAL",
                    base=var.base or "BASE",
                    weight=var.weight,
                    height=var.height,
                    baseline_flag=var.baseline_flag or "ABLFL",
                    baseline_criteria=var.baseline_criteria,
                    groups=getattr(var, "groups", None),
                )
            # New first-class BDS algorithm names usable directly in YAML specs
            elif alg in ("study_day", "baseline", "chg", "pchg", "bmi"):
                ns = ns._std_function_dispatch(
                    target,
                    func=alg,
                    analysis_date=var.analysis_date,
                    reference_date=var.reference_date,
                    aval=var.aval or "AVAL",
                    base=var.base or "BASE",
                    weight=var.weight,
                    height=var.height,
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
            # lookup: skip in spec-driven (requires external dataset object)

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
            spec = ADAMVariableSpec(
                target=var["name"],
                **drv,
            )
            result.append(spec)
        return result

    # ------------------------------------------------------------------ #
    # Validation integration                                               #
    # ------------------------------------------------------------------ #

    def validate(
        self,
        dataset: str,
        version: str = "1.3",
        rules_engine_path: "Path | None" = None,
    ) -> "AdamNamespace":
        """Run CDISC ADaM validation and print the report. Returns self."""
        from ..validation.service import ValidationService

        svc = ValidationService(rules_engine_path=rules_engine_path)
        result = svc.validate_adam(self.to_frame(), dataset=dataset, version=version)
        result.print_report()
        return self

    # ------------------------------------------------------------------ #
    # Terminal operation                                                   #
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # select — column selection / variable-leakage guard                  #
    # ------------------------------------------------------------------ #

    def select(
        self,
        columns: list[str] | None = None,
        *,
        spec: "str | Path | None" = None,
        dataset: str | None = None,
        drop_pattern: str | None = r"^_",
    ) -> "AdamNamespace":
        """
        Materialise the pipeline then select and reorder columns.

        Resolution order:

        1. ``spec`` + ``dataset``: derive the ordered column list from a
           ``define.yaml``.  Only columns present in the frame are kept.
        2. ``columns``: explicit list to keep (in that order).
        3. Neither: keep all current columns (subject to ``drop_pattern``).

        ``drop_pattern`` (default ``r"^_"``): regex applied *before* the
        explicit selection — columns whose names match are removed.  This
        enforces the convention that ``_``-prefixed columns are scratch
        variables.  Set to ``None`` to disable (e.g. during debugging).

        Examples::

            # Keep only spec columns, drop scratch _ variables (default)
            .select(spec="specs/adam/define.yaml", dataset="ADVS")

            # Same but disable auto-drop for debugging
            .select(spec="specs/adam/define.yaml", dataset="ADVS", drop_pattern=None)

            # Just drop _ variables, keep everything else
            .select()

            # Fully disable — do nothing (passthrough, for debugging)
            .select(drop_pattern=None)
        """
        import re

        df = self.to_frame()

        # Step 1: drop scratch variables matching the pattern
        if drop_pattern is not None:
            pat = re.compile(drop_pattern)
            df = df.select([c for c in df.columns if not pat.search(c)])

        # Step 2: resolve explicit column list (spec takes priority over columns)
        col_list = columns
        if spec is not None:
            col_list = self._spec_columns(Path(spec), dataset)

        # Step 3: intersect with existing columns (preserving spec order)
        if col_list is not None:
            existing = [c for c in col_list if c in df.columns]
            df = df.select(existing)

        return self._materialise_then(df)

    @staticmethod
    def _spec_columns(spec_path: Path, dataset: str | None) -> list[str]:
        """Return the ordered variable-name list for *dataset* from a define.yaml."""
        spec_data = yaml.safe_load(spec_path.read_text())
        datasets = spec_data.get("datasets", [])
        if dataset is None:
            if len(datasets) != 1:
                names = [d["name"] for d in datasets]
                raise ValueError(
                    f"define.yaml contains {len(datasets)} datasets {names}; "
                    "pass dataset= to select one."
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
        return [v["name"] for v in ds["variables"]]

    # ------------------------------------------------------------------ #
    # Terminal operations                                                  #
    # ------------------------------------------------------------------ #

    def to_frame(self) -> pl.DataFrame:
        """Materialise the accumulated pipeline into a Polars DataFrame."""
        if not self._pipeline:
            return self._df
        return self._df.with_columns(self._pipeline)

    def write_parquet(
        self,
        path: "str | Path",
        *,
        mkdir: bool = True,
    ) -> pl.DataFrame:
        """
        Materialise the pipeline, write the result to *path* as Parquet,
        and return the DataFrame.

        This is a drop-in alternative to ``to_frame()`` when you want to
        persist the dataset as part of the chain.

        *mkdir*: when ``True`` (default) any missing parent directories are
        created automatically.

        Example::

            advs = (
                vs_raw.adam
                .rename("USUBJID", source="patient_number")
                ...
                .select(spec="specs/adam/define.yaml", dataset="ADVS")
                .write_parquet("outputs/cdiscpilot01/advs.parquet")
            )
        """
        df = self.to_frame()
        dest = Path(path)
        if mkdir:
            dest.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(dest)
        return df
