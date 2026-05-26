"""
AE TLG sub-namespace — AE summary tables and listings.

Accessed via ``df.tlg.ae`` on any Polars DataFrame containing ADaM AE data.
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
    AEListingSpec,
    AESummarySpec,
    SchemaError,
)


class AETLGNamespace:
    """AE tables, listings, and diagnostics.

    Accessed as ``df.tlg.ae``.  Supports both spec-driven
    (``t_summary(spec=...)``) and inline builder (``df.tlg.ae.by(...)``)
    workflows.

    Args:
        df: A Polars DataFrame containing ADaM AE-level data.
    """

    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df

    def _builder(self) -> TLGBuilder:
        """Return a ``TLGBuilder`` pre-configured with AE defaults."""
        return TLGBuilder(
            self._df,
            context="t_ae_summary",
            spec_cls=AESummarySpec,
            namespace_cls=AETLGNamespace,
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
            Inline AE summary::

                ard = (
                    adae.tlg.ae
                    .population(adsl, adsl_filter=pl.col("SAFFL") == "Y")
                    .by("TRTA")
                    .rows(["AEBODSYS", "AEDECOD"])
                    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
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
        spec: AESummarySpec | None = None,
    ) -> pl.DataFrame:
        """Produce an AE summary ARD (Analysis Results Dataset).

        Computes big-N from *adsl*, then n / % subjects and optionally
        event counts for each SOC→PT (or custom row hierarchy).

        Args:
            groupby: Treatment arm column name.  Overrides
                ``spec.columns[0]`` when given.
            adsl: ADSL DataFrame for big-N denominators.  Required for
                percentage calculations.
            spec: Optional ``AESummarySpec`` override.  If ``None``, the
                default spec is used.

        Returns:
            pl.DataFrame: Long-format {cards}-compatible ARD with columns
                ``group1``, ``group1_level``, ``group2``, ``group2_level``,
                ``variable``, ``variable_level``, ``stat_name``,
                ``stat_label``, ``stat``, ``fmt_fn``, ``stat_fmt``,
                ``warning``, ``error``, ``context``.

        Examples:
            Zero-config AE summary::

                ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)

            Custom spec with pooled arms::

                from fleet.tlg import AESummarySpec, GroupPool

                spec = AESummarySpec(
                    pools=[GroupPool(label="Total", arms="*")],
                )
                ard = adae.tlg.ae.t_summary(spec=spec, adsl=adsl)
        """
        spec = spec or AESummarySpec()
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
            ard_rows.append(_ard_row(group_col, arm, "", "", "N", "N", n_val, "t_ae_summary"))

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
                            "t_ae_summary",
                        )
                    )

        # Per-row-field statistics (hierarchical: SOC → PT, etc.)
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
                                "t_ae_summary",
                            )
                        )

        ard = _rows_to_ard(ard_rows)
        issues = validate_ard(ard)
        if issues:
            raise SchemaError("ARD output failed schema validation:\n  " + "\n  ".join(issues))
        return ard

    # ------------------------------------------------------------------ #
    # Listing                                                              #
    # ------------------------------------------------------------------ #

    def l_listing(
        self,
        *,
        spec: AEListingSpec | None = None,
    ) -> pl.DataFrame:
        """Produce an AE listing DataFrame.

        Args:
            spec: Optional ``AEListingSpec`` override.  If ``None``, the
                default spec is used.

        Returns:
            pl.DataFrame: A plain DataFrame with the requested columns,
                sorted per spec.

        Examples:
            Default AE listing::

                listing = adae.tlg.ae.l_listing()

            Custom listing with additional columns::

                from fleet.tlg import AEListingSpec, Column

                spec = AEListingSpec(
                    columns=[
                        Column(field="USUBJID", label="Subject"),
                        Column(field="AEDECOD", label="Preferred Term"),
                    ],
                    sort_by=["USUBJID"],
                )
                listing = adae.tlg.ae.l_listing(spec=spec)
        """
        spec = spec or AEListingSpec()
        spec.validate_dataframe(self._df)

        df = self._df
        if spec.dataset_filter is not None:
            df = df.filter(spec.dataset_filter)

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
        spec: AESummarySpec | None = None,
    ) -> list[str]:
        """Run pre-validation diagnostics without computing.

        Args:
            spec: Optional spec to check against.  If ``None``, the
                default ``AESummarySpec`` is used.

        Returns:
            list[str]: Diagnostic messages (empty if all checks pass).

        Examples:
            Check data readiness::

                report = adae.tlg.ae.check()
        """
        spec = spec or AESummarySpec()
        diagnostics = spec.check(self._df)

        # Additional AE-specific checks
        available = set(self._df.columns)
        for row_def in spec.rows:
            if row_def.field not in available:
                diagnostics.append(
                    f"WARNING: Column '{row_def.field}' not present — "
                    f"'{row_def.label or row_def.field}' sub-analysis will be skipped."
                )

        return diagnostics
