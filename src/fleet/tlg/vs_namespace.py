"""
VS TLG sub-namespace — vital-signs summary tables.

Accessed via ``df.tlg.vs`` on any Polars DataFrame containing ADaM VS data.
"""

from __future__ import annotations

from typing import Any

import polars as pl

from ._ard import (
    ard_row as _ard_row,
)
from ._ard import (
    compute_big_n,
    expand_pools,
    validate_ard,
)
from ._ard import (
    compute_stat as _compute_stat,
)
from ._ard import (
    rows_to_ard as _rows_to_ard,
)
from ._ard import (
    validate_pools as _validate_pools,
)
from ._builder import TLGBuilder
from ._specs import (
    SchemaError,
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
