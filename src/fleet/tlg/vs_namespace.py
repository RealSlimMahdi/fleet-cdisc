"""
VS TLG sub-namespace — vital-signs summary tables.

Accessed via ``df.tlg.vs`` on any Polars DataFrame containing ADaM VS data.
"""

from __future__ import annotations

import polars as pl

from ._ard import summarize_ard
from ._builder import TLGBuilder
from ._specs import VSSummarySpec


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
        spec.validate_dataframe(self._df)
        return summarize_ard(
            self._df,
            rows=spec.rows,
            stats=spec.statistics,
            context="t_vs_summary",
            group_col=group_col,
            pools=spec.pools,
            column_order=spec.column_order,
            adsl=adsl,
            adsl_filter=spec.adsl_filter,
            dataset_filter=spec.dataset_filter,
            header_rows=spec.header_rows,
            nested=True,
        )

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
