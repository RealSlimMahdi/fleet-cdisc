"""
VS TLG sub-namespace — vital-signs summary tables.

Accessed via ``df.tlg.vs`` on any Polars DataFrame containing ADaM VS data.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from ._ard import compute_big_n, default_fmt_fn, expand_pools, format_ard, validate_ard
from ._builder import TLGBuilder
from ._specs import (
    GroupPool,
    SchemaError,
    Statistic,
    VSSummarySpec,
)


class VSTLGNamespace:
    """Vital-signs tables and diagnostics.

    Accessed as ``df.tlg.vs``.  Supports both spec-driven
    (``t_summary(spec=...)``) and inline builder (``df.tlg.vs.by(...)``)
    workflows.

    Args:
        df: A Polars DataFrame containing ADaM VS-level data.
    """

    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df

    def _builder(self) -> TLGBuilder:
        """Return a ``TLGBuilder`` pre-configured with VS defaults."""
        return TLGBuilder(
            self._df,
            context="t_vs_summary",
            spec_cls=VSSummarySpec,
            namespace_cls=VSTLGNamespace,
        )

    # -- Builder entry-point verbs delegated to TLGBuilder --

    def population(
        self,
        adsl: pl.DataFrame,
        *,
        adsl_filter: pl.Expr | None = None,
    ) -> TLGBuilder:
        """Start the inline builder with an ADSL population.

        Args:
            adsl: ADSL DataFrame for big-N denominators.
            adsl_filter: Optional filter applied to ADSL only.

        Returns:
            TLGBuilder: A new builder with population set.

        Examples:
            Inline VS summary::

                ard = (
                    advs.tlg.vs
                    .population(adsl, adsl_filter=pl.col("SAFFL") == "Y")
                    .by("TRTA")
                    .rows(["PARAMCD", "AVISIT"])
                    .stats([Statistic.MEAN, Statistic.SD, Statistic.MEDIAN])
                    .to_ard()
                )
        """
        return self._builder().population(adsl, adsl_filter=adsl_filter)

    def filter(self, expr: pl.Expr) -> TLGBuilder:
        """Start the inline builder with a dataset filter.

        Args:
            expr: Polars expression to filter the primary dataset.

        Returns:
            TLGBuilder: A new builder with dataset filter set.
        """
        return self._builder().filter(expr)

    def by(self, col: str) -> TLGBuilder:
        """Start the inline builder with a primary grouping column.

        Args:
            col: Column name for group1 (e.g. ``"TRTA"``).

        Returns:
            TLGBuilder: A new builder with group1 set.
        """
        return self._builder().by(col)

    # ------------------------------------------------------------------ #
    # Summary table                                                        #
    # ------------------------------------------------------------------ #

    def t_summary(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: VSSummarySpec | None = None,
    ) -> pl.DataFrame:
        """Produce a VS summary ARD (Analysis Results Dataset).

        Computes big-N from *adsl*, then continuous statistics for each
        parameter (or custom row hierarchy).

        Args:
            groupby: Treatment arm column name.  Overrides
                ``spec.columns[0]`` when given.
            adsl: ADSL DataFrame for big-N denominators.
            spec: Optional ``VSSummarySpec`` override.  If ``None``, the
                default spec is used.

        Returns:
            pl.DataFrame: Long-format {cards}-compatible ARD.

        Examples:
            Zero-config VS summary::

                ard = advs.tlg.vs.t_summary(groupby="TRTA", adsl=adsl)

            Custom spec with pooled arms::

                from fleet.tlg import VSSummarySpec, GroupPool

                spec = VSSummarySpec(
                    pools=[GroupPool(label="Total", arms="*")],
                )
                ard = advs.tlg.vs.t_summary(spec=spec, adsl=adsl)
        """
        spec = spec or VSSummarySpec()
        group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")

        # --- Validation ---
        spec.validate_dataframe(self._df)
        _validate_pools(self._df, spec.pools, group_col)

        # --- Apply dataset_filter ---
        df = self._df
        if spec.dataset_filter is not None:
            df = df.filter(spec.dataset_filter)

        # --- Big-N denominators from ADSL ---
        big_n: dict[str, int] = {}
        if adsl is not None:
            big_n = compute_big_n(adsl, group_col, spec.pools, filter_expr=spec.adsl_filter)

        # --- Expand pools ---
        df = expand_pools(df, spec.pools, group_col)

        # --- Compute statistics ---
        ard_rows: list[dict[str, Any]] = []
        arms = sorted(df[group_col].drop_nulls().unique().to_list())

        # Re-order arms if column_order specified
        if spec.column_order:
            ordered = [a for a in spec.column_order if a in arms]
            remaining = [a for a in arms if a not in ordered]
            arms = ordered + remaining

        # Big-N row
        for arm in arms:
            n_val = big_n.get(arm)
            ard_rows.append(_ard_row(group_col, arm, "", "", "N", "N", n_val, "t_vs_summary"))

        # --- Header rows (OverallStat) ---
        for hdr in spec.header_rows:
            hdr_df = df
            if hdr.filter is not None:
                hdr_df = hdr_df.filter(hdr.filter)
            effective_stats = hdr.statistics or spec.statistics
            for arm in arms:
                arm_hdr = hdr_df.filter(pl.col(group_col) == arm)
                arm_n = big_n.get(arm, 0)
                for stat_type in effective_stats:
                    stat_name, stat_label, stat_val = _compute_stat(stat_type, arm_hdr, arm_n)
                    ard_rows.append(
                        _ard_row(
                            group_col,
                            arm,
                            "",
                            hdr.label,
                            stat_name,
                            stat_label,
                            stat_val,
                            "t_vs_summary",
                        )
                    )

        # Per-row-field statistics (hierarchical: PARAMCD → AVISIT, etc.)
        for row_def in spec.rows:
            field = row_def.field
            if field not in df.columns:
                continue

            analysis_df = df
            if row_def.filter_value is not None:
                if field not in analysis_df.columns:
                    continue
                analysis_df = analysis_df.filter(pl.col(field) == row_def.filter_value)

            # Compute per arm × level
            levels = sorted(analysis_df[field].drop_nulls().unique().to_list())

            for arm in arms:
                arm_df = analysis_df.filter(pl.col(group_col) == arm)
                arm_n = big_n.get(arm, 0)

                for level in levels:
                    level_df = arm_df.filter(pl.col(field) == level)

                    for stat_type in spec.statistics:
                        stat_name, stat_label, stat_val = _compute_stat(stat_type, level_df, arm_n)
                        ard_rows.append(
                            _ard_row(
                                group_col,
                                arm,
                                field,
                                str(level),
                                stat_name,
                                stat_label,
                                stat_val,
                                "t_vs_summary",
                            )
                        )

        ard = _rows_to_ard(ard_rows)
        issues = validate_ard(ard)
        if issues:
            raise SchemaError("ARD output failed schema validation:\n  " + "\n  ".join(issues))
        return ard

    # ------------------------------------------------------------------ #
    # Pre-validation diagnostic                                            #
    # ------------------------------------------------------------------ #

    def check(
        self,
        *,
        spec: VSSummarySpec | None = None,
    ) -> list[str]:
        """Run pre-validation diagnostics without computing.

        Args:
            spec: Optional spec to check against.

        Returns:
            list[str]: Diagnostic messages (empty if all checks pass).

        Examples:
            Check data readiness::

                report = advs.tlg.vs.check()
        """
        spec = spec or VSSummarySpec()
        diagnostics = spec.check(self._df)

        available = set(self._df.columns)
        for row_def in spec.rows:
            if row_def.field not in available:
                diagnostics.append(
                    f"WARNING: Column '{row_def.field}' not present — "
                    f"'{row_def.label or row_def.field}' sub-analysis will be skipped."
                )

        return diagnostics


# ------------------------------------------------------------------ #
# Internal helpers                                                     #
# ------------------------------------------------------------------ #


def _validate_pools(
    df: pl.DataFrame,
    pools: list[GroupPool],
    group_col: str,
) -> None:
    """Tier 3: validate pool arm references against actual data."""
    if not pools:
        return
    actual = set(df[group_col].drop_nulls().unique().to_list())
    for pool in pools:
        if pool.arms == "*":
            continue
        missing = [a for a in pool.arms if a not in actual]
        if missing:
            raise SchemaError(
                f"Pool '{pool.label}' references arm(s) {missing} but "
                f"{group_col} contains only {sorted(actual)}"
            )


def _compute_stat(
    stat_type: Statistic,
    level_df: pl.DataFrame,
    arm_n: int,
) -> tuple[str, str, float | int | str | None]:
    """Compute a single statistic for a subset of data."""
    if stat_type == Statistic.N_SUBJECTS:
        n = level_df["USUBJID"].n_unique() if len(level_df) > 0 else 0
        return ("n", "n", n)
    elif stat_type == Statistic.N_EVENTS:
        return ("n_events", "Events", len(level_df))
    elif stat_type == Statistic.N_PCT:
        n = level_df["USUBJID"].n_unique() if len(level_df) > 0 else 0
        pct = round(n / arm_n * 100, 1) if arm_n > 0 else 0.0
        return ("pct", "n (%)", pct)
    elif stat_type == Statistic.MEAN:
        val = level_df["AVAL"].mean() if "AVAL" in level_df.columns and len(level_df) > 0 else None
        return ("mean", "Mean", val)
    elif stat_type == Statistic.SD:
        val = level_df["AVAL"].std() if "AVAL" in level_df.columns and len(level_df) > 0 else None
        return ("sd", "SD", val)
    elif stat_type == Statistic.MEDIAN:
        val = (
            level_df["AVAL"].median() if "AVAL" in level_df.columns and len(level_df) > 0 else None
        )
        return ("median", "Median", val)
    elif stat_type == Statistic.MIN:
        val = level_df["AVAL"].min() if "AVAL" in level_df.columns and len(level_df) > 0 else None
        return ("min", "Min", val)
    elif stat_type == Statistic.MAX:
        val = level_df["AVAL"].max() if "AVAL" in level_df.columns and len(level_df) > 0 else None
        return ("max", "Max", val)
    elif stat_type == Statistic.Q1:
        val = (
            level_df["AVAL"].quantile(0.25)
            if "AVAL" in level_df.columns and len(level_df) > 0
            else None
        )
        return ("q1", "Q1", val)
    elif stat_type == Statistic.Q3:
        val = (
            level_df["AVAL"].quantile(0.75)
            if "AVAL" in level_df.columns and len(level_df) > 0
            else None
        )
        return ("q3", "Q3", val)
    else:
        return (stat_type.value, stat_type.value, None)


def _ard_row(
    group1: str,
    group1_level: str,
    variable: str,
    variable_level: str,
    stat_name: str,
    stat_label: str,
    stat: float | int | str | None,
    context: str,
    *,
    group2: str = "",
    group2_level: str = "",
    fmt_fn: str | None = None,
    warning: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Build a single ARD row dict ({cards}-compatible)."""
    return {
        "group1": group1,
        "group1_level": group1_level,
        "group2": group2,
        "group2_level": group2_level,
        "variable": variable,
        "variable_level": variable_level,
        "stat_name": stat_name,
        "stat_label": stat_label,
        "stat": stat,
        "fmt_fn": fmt_fn if fmt_fn is not None else default_fmt_fn(stat_name),
        "stat_fmt": None,
        "warning": warning,
        "error": error,
        "context": context,
    }


def _rows_to_ard(rows: list[dict[str, Any]]) -> pl.DataFrame:
    """Convert a list of ARD row dicts to a {cards}-compatible Polars DataFrame."""
    if not rows:
        from ._ard import ARD_SCHEMA

        return pl.DataFrame(schema=ARD_SCHEMA)

    for row in rows:
        v = row["stat"]
        if v is None:
            row["stat"] = None
        elif isinstance(v, (int, float)):
            row["stat"] = float(v)
        else:
            row["stat"] = float(v) if str(v).replace(".", "", 1).isdigit() else None

    df = pl.DataFrame(rows).cast({"stat": pl.Float64}, strict=False)

    for col in ("warning", "error", "stat_fmt"):
        if col in df.columns and df[col].dtype == pl.Null:
            df = df.with_columns(pl.lit(None, dtype=pl.Utf8).alias(col))

    df = format_ard(df)

    return df
