"""
LB TLG sub-namespace — laboratory summary tables and abnormality listings.

Accessed via ``df.tlg.lb`` on any Polars DataFrame containing ADaM ADLB data.
Ports the ``{tlg.templates}`` LBT01 (continuous lab statistics per
PARAM/AVISIT) and LBL01 (laboratory abnormalities listing) templates.
"""

from __future__ import annotations

from typing import ClassVar

import polars as pl
from pydantic import Field, model_validator

from ._ard import (
    ard_row,
    compute_big_n,
    rows_to_ard,
    summarize_ard,
    validate_ard,
    worst_case,
)
from ._builder import BuilderVerbsMixin
from ._specs import (
    Column,
    Row,
    SchemaError,
    Statistic,
    SummarySpecBase,
    TLGSpec,
    change_from_baseline_prefilter,
    resolve_filter,
)


class LBSummarySpec(SummarySpecBase):
    """Spec for a laboratory summary table (LBT01).

    Defaults provide zero-config continuous statistics for each
    parameter (``PARAMCD``) at each analysis visit (``AVISIT``),
    mirroring the GDSR ``LBT01`` baseline/change layout.
    """

    rows: list[Row] = Field(
        default_factory=lambda: [
            Row(field="PARAMCD", label="Parameter"),
            Row(field="AVISIT", label="Analysis Visit"),
        ],
        description=(
            "Hierarchy of row groupings (PARAM \u2192 AVISIT).  Set inline via "
            "[`TLGBuilder.rows()`][fleet.tlg.TLGBuilder.rows]."
        ),
    )
    statistics: list[Statistic] = Field(
        default_factory=lambda: [
            Statistic.N_SUBJECTS,
            Statistic.MEAN,
            Statistic.SD,
            Statistic.MEDIAN,
            Statistic.MIN,
            Statistic.MAX,
        ],
        description=(
            "Continuous statistics computed per row.  Set inline via "
            "[`TLGBuilder.stats()`][fleet.tlg.TLGBuilder.stats]."
        ),
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "PARAMCD", "AVAL", "AVISIT"],
        description="Columns required in the analysis dataset for this spec.",
    )


class LBListingSpec(TLGSpec):
    """Spec for a laboratory abnormalities listing (LBL01).

    Defaults select results with a non-normal range indicator
    (``ANRIND``) and present subject, parameter, value, and toxicity
    grade columns sorted for review.
    """

    _unconsumed_spec_fields: ClassVar[frozenset[str]] = frozenset({"adsl_filter", "header_rows"})

    output_type: str = "listing"
    columns: list[Column] = Field(
        default_factory=lambda: [
            Column(field="USUBJID", label="Subject"),
            Column(field="TRTA", label="Treatment"),
            Column(field="PARAM", label="Parameter"),
            Column(field="AVISIT", label="Analysis Visit"),
            Column(field="AVAL", label="Result"),
            Column(field="AVALU", label="Unit"),
            Column(field="ANRIND", label="Range Indicator"),
            Column(field="ATOXGR", label="Toxicity Grade"),
        ],
        description="Ordered list of columns to include in the listing.",
    )
    sort_by: list[str] = Field(
        default_factory=lambda: ["USUBJID", "PARAM", "AVISIT"],
        description="Sort order applied before rendering.",
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "PARAMCD", "AVAL", "ANRIND"],
        description="Columns required in the analysis dataset for this spec.",
    )


class LBChgSpec(LBSummarySpec):
    """Spec for lab change from baseline (lbt02): CHG stats per PARAM × visit.

    Prefilter rule: the baseline record (``ABLFL`` = Y) and records
    with no change value are dropped before summarising, so ``ABLFL``
    is a required column.  Unless set, the prefilter follows
    ``value_col``; ``prefilter=None`` switches the rule off.
    """

    context: ClassVar[str] = "t_lb_chg"

    value_col: str = Field(
        default="CHG",
        description="Analysis-value column summarized (change from baseline).",
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "PARAMCD", "AVISIT", "CHG"],
    )

    @model_validator(mode="after")
    def _default_prefilter_follows_value_col(self) -> LBChgSpec:
        if "prefilter" not in self.model_fields_set:
            self.prefilter = change_from_baseline_prefilter(self.value_col)
        return self


class LBShiftSpec(SummarySpecBase):
    """Spec for the lab shift table (lbt03).

    The row hierarchy is fixed (PARAMCD → baseline-to-worst shift cell);
    the spec drives validation, pooling, ordering and the worst-case
    rank (``anrind_order``).
    """

    _unconsumed_spec_fields: ClassVar[frozenset[str]] = frozenset(
        {"rows", "header_rows", "value_col"}
    )

    statistics: list[Statistic] = Field(
        default_factory=lambda: [Statistic.N_SUBJECTS],
    )
    anrind_order: list[str] = Field(
        default_factory=lambda: ["NORMAL", "LOW", "HIGH", "LOW LOW", "HIGH HIGH"],
        description="Range indicators from least to most abnormal (worst-case rank).",
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "PARAMCD", "BNRIND", "ANRIND"],
    )


class LBAbnormalSpec(SummarySpecBase):
    """Spec for laboratory abnormalities not present at baseline (lbt04)."""

    _unconsumed_spec_fields: ClassVar[frozenset[str]] = frozenset(
        {"rows", "statistics", "header_rows", "pools", "value_col", "label_col"}
    )

    low_values: list[str] = Field(
        default_factory=lambda: ["LOW", "LOW LOW"],
        description="ANRIND values counted as the Low direction.",
    )
    high_values: list[str] = Field(
        default_factory=lambda: ["HIGH", "HIGH HIGH"],
        description="ANRIND values counted as the High direction.",
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "PARAMCD", "ANRIND"],
    )


class LBTLGNamespace(BuilderVerbsMixin):
    """Laboratory tables, listings, and diagnostics.

    Accessed as ``df.tlg.lb``.  Provides the LBT01 continuous lab
    statistics table and the LBL01 abnormalities listing.

    Args:
        df: A Polars DataFrame containing ADaM ADLB-level data.
    """

    _builder_context = "t_lb_summary"
    _builder_specs = {
        "t_summary": LBSummarySpec,
        "t_chg": LBChgSpec,
        "t_shift": LBShiftSpec,
        "t_abnormal": LBAbnormalSpec,
        "l_listing": LBListingSpec,
    }

    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df

    # ------------------------------------------------------------------ #
    # Summary table (LBT01)                                                #
    # ------------------------------------------------------------------ #

    def t_summary(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: LBSummarySpec | None = None,
    ) -> pl.DataFrame:
        """Produce a laboratory summary ARD (Analysis Results Dataset).

        Computes big-N from *adsl*, then continuous statistics for each
        parameter at each analysis visit (or custom row hierarchy),
        cards-aligned for downstream rendering.

        Args:
            groupby: Treatment arm column name.  Overrides
                ``spec.columns[0]`` when given.
            adsl: ADSL DataFrame for big-N denominators.
            spec: Optional ``LBSummarySpec`` override.  If ``None``, the
                default spec is used.

        Returns:
            pl.DataFrame: Long-format {cards}-compatible ARD with columns
                ``group1``, ``group1_level``, ``group2``, ``group2_level``,
                ``variable``, ``variable_level``, ``stat_name``,
                ``stat_label``, ``stat``, ``fmt_fn``, ``stat_fmt``,
                ``warning``, ``error``, ``context``.

        Examples:
            Zero-config lab summary::

                ard = adlb.tlg.lb.t_summary(groupby="TRTA", adsl=adsl)

            Custom spec with pooled arms::

                from fleet.tlg import GroupPool

                from fleet.tlg.lb_namespace import LBSummarySpec

                spec = LBSummarySpec(pools=[GroupPool(label="Total", arms="*")])
                ard = adlb.tlg.lb.t_summary(spec=spec, adsl=adsl)
        """
        spec = spec or LBSummarySpec()
        group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")
        spec.validate_dataframe(self._df, group_col=group_col)
        return summarize_ard(
            self._df,
            rows=spec.rows,
            stats=spec.statistics,
            context="t_lb_summary",
            group_col=group_col,
            pools=spec.pools,
            column_order=spec.column_order,
            adsl=adsl,
            adsl_filter=spec.adsl_filter,
            dataset_filter=spec.dataset_filter,
            header_rows=spec.header_rows,
            nested=True,
            value_col=spec.value_col,
            label_col=spec.label_col,
            decimals=spec.decimals,
        )

    # ------------------------------------------------------------------ #
    # Change from baseline (LBT02/LBT03)                                   #
    # ------------------------------------------------------------------ #

    def t_chg(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: LBChgSpec | None = None,
    ) -> pl.DataFrame:
        """Mean change-from-baseline ARD per parameter and visit (LBT02).

        Summarizes ``spec.value_col`` (``CHG`` by default, not raw
        ``AVAL``) for post-baseline records, nested per parameter ×
        visit.  The paired n counts only subjects with a non-missing
        change value at the visit; baseline records are excluded
        null-safely (ADaM codes ``ABLFL`` as Y / null).

        Args:
            groupby: Treatment-arm column.
            adsl: ADSL DataFrame for big-N denominators.
            spec: Optional ``LBChgSpec`` override.

        Returns:
            pl.DataFrame: {cards}-compatible ARD.

        Examples:
            ``ard = adlb.tlg.lb.t_chg(groupby="TRTA", adsl=adsl)``
        """
        spec = spec or LBChgSpec()
        group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")
        spec.validate_dataframe(self._df, group_col=group_col)
        prefilter = pl.col(spec.value_col).is_not_null()
        if "ABLFL" in self._df.columns:
            prefilter = prefilter & pl.col("ABLFL").ne_missing("Y")
        return summarize_ard(
            self._df,
            rows=spec.rows,
            stats=spec.statistics,
            context="t_lb_chg",
            group_col=group_col,
            pools=spec.pools,
            column_order=spec.column_order,
            adsl=adsl,
            adsl_filter=spec.adsl_filter,
            dataset_filter=spec.dataset_filter,
            prefilter=prefilter,
            header_rows=spec.header_rows,
            nested=True,
            value_col=spec.value_col,
            label_col=spec.label_col,
            decimals=spec.decimals,
        )

    # ------------------------------------------------------------------ #
    # Shift counts (LBT03)                                                 #
    # ------------------------------------------------------------------ #

    def t_shift(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: LBShiftSpec | None = None,
    ) -> pl.DataFrame:
        """Baseline → worst post-baseline shift table per parameter (LBT03).

        A true cross-tabulation: per parameter, each subject contributes
        one ``"<BNRIND> to <ANRIND>"`` shift cell, where ANRIND is their
        worst post-baseline range indicator (NORMAL < LOW < HIGH <
        LOW LOW < HIGH HIGH — deterministic clinical rank, HIGH breaking
        the LOW/HIGH tie).  Baseline records are excluded (``ONTRTFL``
        preferred, else null-safe ``ABLFL``); subjects without a
        baseline indicator are excluded.

        Percentages are intentionally not emitted: the correct
        denominator is subjects with both a baseline and a post-baseline
        result per parameter, which needs per-cell denominator support
        in the engine (next round) — a percentage against the arm big-N
        would be wrong.

        Args:
            groupby: Treatment-arm column.
            adsl: ADSL DataFrame for the arm universe and big-N rows.
            spec: Optional ``LBShiftSpec`` override.

        Returns:
            pl.DataFrame: {cards}-compatible ARD (subject counts).

        Raises:
            SchemaError: If the spec carries ``rows`` or ``header_rows``
                — the shift hierarchy is fixed and would silently ignore
                them.

        Examples:
            ``ard = adlb.tlg.lb.t_shift(groupby="TRTA", adsl=adsl)``
        """
        spec = spec or LBShiftSpec()
        if spec.rows or spec.header_rows:
            raise SchemaError(
                "t_shift's row hierarchy is fixed (PARAMCD → baseline-to-worst "
                "shift cell) and it emits no header rows — 'rows' and "
                "'header_rows' in the spec would be silently ignored, so they "
                "are rejected. Use t_summary for a custom hierarchy."
            )
        group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")
        spec.validate_dataframe(self._df, group_col=group_col)
        post = self._df.filter(pl.col("ANRIND").is_not_null())
        if "ONTRTFL" in post.columns:
            post = post.filter(pl.col("ONTRTFL") == "Y")
        elif "ABLFL" in post.columns:
            post = post.filter(pl.col("ABLFL").ne_missing("Y"))
        worst = worst_case(
            post,
            by=["USUBJID", group_col, "PARAMCD"],
            order_col="ANRIND",
            order=spec.anrind_order,
        )
        shift = worst.filter(pl.col("BNRIND").is_not_null()).with_columns(
            (pl.col("BNRIND").cast(pl.Utf8) + " to " + pl.col("ANRIND").cast(pl.Utf8)).alias(
                "SHIFT"
            )
        )
        return summarize_ard(
            shift,
            rows=["PARAMCD", "SHIFT"],
            stats=spec.statistics,
            context="t_lb_shift",
            group_col=group_col,
            pools=spec.pools,
            column_order=spec.column_order,
            adsl=adsl,
            adsl_filter=spec.adsl_filter,
            dataset_filter=spec.dataset_filter,
            nested=True,
            label_col=spec.label_col,
            decimals=spec.decimals,
        )

    # ------------------------------------------------------------------ #
    # Abnormal counts (LBT04)                                              #
    # ------------------------------------------------------------------ #

    def t_abnormal(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: LBAbnormalSpec | None = None,
    ) -> pl.DataFrame:
        """Laboratory abnormalities not present at baseline (LBT04).

        Per parameter and direction (Low = LOW / LOW LOW, High = HIGH /
        HIGH HIGH), following ``crane::ard_tabulate_abnormal``:

        - denominator ``N`` = subjects with ≥1 post-baseline assessment
          whose baseline is **not** abnormal in that direction;
        - numerator ``n`` = those with any post-baseline value in the
          direction;
        - ``pct`` = n / N (null when N = 0 — never fabricated).

        Post-baseline means ``ONTRTFL == "Y"`` when present, else
        non-baseline via null-safe ``ABLFL``.  Without a ``BNRIND``
        column no baseline exclusion is applied.

        Args:
            groupby: Treatment-arm column.
            adsl: ADSL DataFrame for the arm universe and big-N rows.

        Returns:
            pl.DataFrame: {cards}-compatible ARD.

        Examples:
            ``ard = adlb.tlg.lb.t_abnormal(group_col="TRTA", adsl=adsl)``
        """
        spec = spec or LBAbnormalSpec()
        group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")
        spec.validate_dataframe(self._df, group_col=group_col)
        if spec.pools or spec.header_rows:
            raise SchemaError(
                "t_abnormal does not support pools or header_rows yet — "
                "its per-cell denominators need dedicated engine support."
            )
        source = self._df
        if group_col not in source.columns:
            raise SchemaError(
                f"Group column '{group_col}' not found in the analysis dataset. "
                f"Available: {sorted(source.columns)}"
            )
        dataset_filter = resolve_filter(spec.dataset_filter)
        if dataset_filter is not None:
            source = source.filter(dataset_filter)
        post = source.filter(pl.col("ANRIND").is_not_null())
        if "ONTRTFL" in post.columns:
            post = post.filter(pl.col("ONTRTFL") == "Y")
        elif "ABLFL" in post.columns:
            post = post.filter(pl.col("ABLFL").ne_missing("Y"))
        post = post.with_columns(pl.col("ANRIND").str.to_uppercase().alias("__anrind"))

        context = "t_lb_abnormal"
        if adsl is not None:
            if group_col not in adsl.columns:
                raise SchemaError(f"Group column '{group_col}' not found in adsl.")
            big_n = compute_big_n(adsl, group_col, [], filter_expr=resolve_filter(spec.adsl_filter))
            data_arms = set(post[group_col].drop_nulls().unique().to_list())
            unknown = sorted(data_arms - set(big_n))
            if unknown:
                raise SchemaError(
                    f"Arm(s) {unknown} in the analysis dataset have no denominator in ADSL."
                )
            arms = sorted(big_n)
        else:
            big_n = {}
            arms = sorted(post[group_col].drop_nulls().unique().to_list())
        if spec.column_order:
            arms = [a for a in spec.column_order if a in arms] + [
                a for a in arms if a not in spec.column_order
            ]

        fmt = spec.decimals or {}
        rows_out: list[dict[str, object]] = []
        if adsl is not None:
            rows_out += [
                ard_row(
                    group_col, arm, "", "", "N", "N", big_n.get(arm), context, fmt_fn=fmt.get("N")
                )
                for arm in arms
            ]

        directions = {"Low": spec.low_values, "High": spec.high_values}
        has_baseline = "BNRIND" in source.columns
        baseline = (
            source.with_columns(pl.col("BNRIND").str.to_uppercase().alias("__bnrind"))
            if has_baseline
            else None
        )
        for param in sorted(post["PARAMCD"].drop_nulls().unique().to_list()):
            p_post = post.filter(pl.col("PARAMCD") == param)
            for direction, levels in directions.items():
                base_abnormal: set[str] = set()
                if baseline is not None:
                    base_abnormal = set(
                        baseline.filter(
                            (pl.col("PARAMCD") == param) & pl.col("__bnrind").is_in(levels)
                        )["USUBJID"].to_list()
                    )
                for arm in arms:
                    a_post = p_post.filter(pl.col(group_col) == arm)
                    eligible = set(a_post["USUBJID"].to_list()) - base_abnormal
                    abnormal = set(
                        a_post.filter(pl.col("__anrind").is_in(levels))["USUBJID"].to_list()
                    )
                    n = len(abnormal & eligible)
                    denom = len(eligible)
                    # Unrounded — display precision belongs to fmt_fn.
                    pct = n / denom * 100 if denom > 0 else None
                    lineage = {"group2": "PARAMCD", "group2_level": str(param)}
                    rows_out += [
                        ard_row(
                            group_col,
                            arm,
                            "ABNORMAL",
                            direction,
                            "n",
                            "n",
                            n,
                            context,
                            fmt_fn=fmt.get("n"),
                            **lineage,
                        ),
                        ard_row(
                            group_col,
                            arm,
                            "ABNORMAL",
                            direction,
                            "N",
                            "N assessed",
                            denom,
                            context,
                            fmt_fn=fmt.get("N"),
                            **lineage,
                        ),
                        ard_row(
                            group_col,
                            arm,
                            "ABNORMAL",
                            direction,
                            "pct",
                            "n / N (%)",
                            pct,
                            context,
                            fmt_fn=fmt.get("pct"),
                            **lineage,
                        ),
                    ]

        ard = rows_to_ard(rows_out)
        issues = validate_ard(ard)
        if issues:
            raise SchemaError("ARD output failed schema validation:\n  " + "\n  ".join(issues))
        return ard

    # ------------------------------------------------------------------ #
    # Listing (LBL01)                                                      #
    # ------------------------------------------------------------------ #

    def l_listing(
        self,
        *,
        spec: LBListingSpec | None = None,
    ) -> pl.DataFrame:
        """Produce a laboratory abnormalities listing DataFrame.

        Selects rows with a non-normal range indicator (``ANRIND``) and
        returns the requested columns, sorted per spec.

        Args:
            spec: Optional ``LBListingSpec`` override.  If ``None``, the
                default spec is used.

        Returns:
            pl.DataFrame: A plain DataFrame with the requested columns,
                sorted per spec.

        Examples:
            Default lab listing::

                listing = adlb.tlg.lb.l_listing()

            Custom listing with explicit columns::

                from fleet.tlg import Column

                from fleet.tlg.lb_namespace import LBListingSpec

                spec = LBListingSpec(
                    columns=[
                        Column(field="USUBJID", label="Subject"),
                        Column(field="PARAM", label="Parameter"),
                        Column(field="AVAL", label="Result"),
                    ],
                    sort_by=["USUBJID"],
                )
                listing = adlb.tlg.lb.l_listing(spec=spec)
        """
        spec = spec or LBListingSpec()
        spec.validate_dataframe(self._df)

        df = self._df
        dataset_filter = resolve_filter(spec.dataset_filter)
        if dataset_filter is not None:
            df = df.filter(dataset_filter)
        elif "ANRIND" in df.columns:
            # Default: abnormalities only (exclude normal / missing indicators).
            df = df.filter(
                pl.col("ANRIND").is_not_null()
                & (~pl.col("ANRIND").str.to_uppercase().is_in(["NORMAL", "N", ""]))
            )

        # Select only requested columns (that exist)
        available = set(df.columns)
        select_cols = [c.field for c in spec.columns if c.field in available]
        df = df.select(select_cols)

        # Rename to labels
        rename_map = {c.field: c.label for c in spec.columns if c.label and c.field in available}
        if rename_map:
            df = df.rename(rename_map)

        # Sort
        sort_cols = []
        for s in spec.sort_by:
            col_name = rename_map.get(s, s)
            if col_name in df.columns:
                sort_cols.append(col_name)
        if sort_cols:
            df = df.sort(sort_cols)

        return df

    # ------------------------------------------------------------------ #
    # Pre-validation diagnostic                                            #
    # ------------------------------------------------------------------ #

    def check(
        self,
        *,
        spec: LBSummarySpec | None = None,
    ) -> list[str]:
        """Run pre-validation diagnostics without computing.

        Args:
            spec: Optional spec to check against.  If ``None``, the
                default ``LBSummarySpec`` is used.

        Returns:
            list[str]: Diagnostic messages (empty if all checks pass).

        Examples:
            Check data readiness::

                report = adlb.tlg.lb.check()
        """
        spec = spec or LBSummarySpec()
        diagnostics = spec.check(self._df)

        available = set(self._df.columns)
        for row_def in spec.rows:
            if row_def.field not in available:
                diagnostics.append(
                    f"WARNING: Column '{row_def.field}' not present — "
                    f"'{row_def.label or row_def.field}' sub-analysis will be skipped."
                )

        return diagnostics
