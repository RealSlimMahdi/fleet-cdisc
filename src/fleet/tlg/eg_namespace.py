"""
EG TLG sub-namespace — ECG summary tables.

Accessed via ``df.tlg.eg`` on any Polars DataFrame containing ADaM ADEG data.
"""

from __future__ import annotations

import polars as pl
from pydantic import Field

from ._ard import summarize_ard
from ._ard import validate_pools as _validate_pools
from ._builder import TLGBuilder
from ._specs import (
    GroupPool,
    Row,
    Statistic,
    TLGSpec,
)


class EGSummarySpec(TLGSpec):
    """Spec for an ECG summary table (t_eg_summary).

    Defaults provide zero-config convenience for a standard ADEG
    per-PARAM × AVISIT continuous-stats table.  Every field is also
    settable inline through [`TLGBuilder`][fleet.tlg.TLGBuilder].
    """

    output_type: str = "summary"
    rows: list[Row] = Field(
        default_factory=lambda: [
            Row(field="PARAMCD", label="Parameter"),
            Row(field="AVISIT", label="Visit"),
        ],
        description=(
            "Hierarchy of row groupings.  Set inline via "
            "[`TLGBuilder.rows()`][fleet.tlg.TLGBuilder.rows]."
        ),
    )
    columns: list[str] = Field(
        default_factory=lambda: ["TRTA"],
        description=(
            "Column-grouping variables.  Set inline via "
            "[`TLGBuilder.by()`][fleet.tlg.TLGBuilder.by]."
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
            "Statistics computed per row.  Set inline via "
            "[`TLGBuilder.stats()`][fleet.tlg.TLGBuilder.stats]."
        ),
    )
    pools: list[GroupPool] = Field(
        default_factory=list,
        description=(
            "Composite (pooled) treatment groups.  Set inline via "
            "[`TLGBuilder.pools()`][fleet.tlg.TLGBuilder.pools]."
        ),
    )
    column_order: list[str] = Field(
        default_factory=list,
        description=(
            "Explicit ordering of column labels in the rendered output.  "
            "Set inline via "
            "[`TLGBuilder.column_order()`][fleet.tlg.TLGBuilder.column_order]."
        ),
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "PARAMCD", "AVAL", "AVISIT", "TRTA"],
        description="Columns required in the analysis dataset for this spec.",
    )


class EGTLGNamespace:
    """ECG tables and diagnostics.

    Accessed as ``df.tlg.eg``.  Supports both spec-driven
    (``t_summary(spec=...)``) and inline builder (``df.tlg.eg.by(...)``)
    workflows.

    Args:
        df: A Polars DataFrame containing ADaM ADEG-level data.
    """

    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df

    def _builder(self) -> TLGBuilder:
        """Return a ``TLGBuilder`` pre-configured with EG defaults."""
        return TLGBuilder(
            self._df,
            context="t_eg_summary",
            spec_cls=EGSummarySpec,
            namespace_cls=EGTLGNamespace,
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
            Inline EG summary::

                ard = (
                    adeg.tlg.eg
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
        spec: EGSummarySpec | None = None,
    ) -> pl.DataFrame:
        """Produce an ECG summary ARD (Analysis Results Dataset).

        Computes big-N from *adsl*, then continuous statistics for each
        parameter × visit (or custom row hierarchy).

        Args:
            groupby: Treatment arm column name.  Overrides
                ``spec.columns[0]`` when given.
            adsl: ADSL DataFrame for big-N denominators.
            spec: Optional ``EGSummarySpec`` override.  If ``None``, the
                default spec is used.

        Returns:
            pl.DataFrame: Long-format {cards}-compatible ARD.

        Examples:
            Zero-config EG summary::

                ard = adeg.tlg.eg.t_summary(groupby="TRTA", adsl=adsl)

            Custom spec with pooled arms::

                from fleet.tlg import EGSummarySpec, GroupPool

                spec = EGSummarySpec(
                    pools=[GroupPool(label="Total", arms="*")],
                )
                ard = adeg.tlg.eg.t_summary(spec=spec, adsl=adsl)
        """
        spec = spec or EGSummarySpec()
        group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")

        # --- Validation ---
        spec.validate_dataframe(self._df)
        _validate_pools(self._df, spec.pools, group_col)

        return summarize_ard(
            self._df,
            rows=[r.field for r in spec.rows],
            stats=spec.statistics,
            context="t_eg_summary",
            group_col=group_col,
            pools=spec.pools,
            column_order=spec.column_order,
            adsl=adsl,
            adsl_filter=spec.adsl_filter,
            dataset_filter=spec.dataset_filter,
        )

    # ------------------------------------------------------------------ #
    # Change-from-baseline (egt03) — continuous                            #
    # ------------------------------------------------------------------ #

    def t_chg(
        self,
        *,
        groupby: str = "TRTA",
        adsl: pl.DataFrame | None = None,
    ) -> pl.DataFrame:
        """ECG change-from-baseline ARD (continuous, egt03).

        Summarizes ``CHG`` (mean/SD/median/min/max) per PARAMCD × AVISIT.

        Args:
            groupby: Treatment-arm column.
            adsl: ADSL for big-N denominators.

        Returns:
            pl.DataFrame: {cards}-compatible ARD.

        Examples:
            ``ard = adeg.tlg.eg.t_chg(groupby="TRTA", adsl=adsl)``
        """
        df = self._df.with_columns(pl.col("CHG").alias("AVAL"))
        return summarize_ard(
            df,
            rows=["PARAMCD", "AVISIT"],
            stats=[
                Statistic.N_SUBJECTS,
                Statistic.MEAN,
                Statistic.SD,
                Statistic.MEDIAN,
                Statistic.MIN,
                Statistic.MAX,
            ],
            context="t_eg_chg",
            group_col=groupby,
            adsl=adsl,
        )

    # ------------------------------------------------------------------ #
    # QTc category counts (egt05_qtcat) — categorical                      #
    # ------------------------------------------------------------------ #

    def t_qtcat(
        self,
        *,
        groupby: str = "TRTA",
        adsl: pl.DataFrame | None = None,
    ) -> pl.DataFrame:
        """QTc category-count ARD (n / %, egt05_qtcat).

        Counts subjects by AVALCAT1 category per PARAMCD × AVISIT.

        Args:
            groupby: Treatment-arm column.
            adsl: ADSL for big-N denominators.

        Returns:
            pl.DataFrame: {cards}-compatible ARD.

        Examples:
            ``ard = adeg.tlg.eg.t_qtcat(groupby="TRTA", adsl=adsl)``
        """
        return summarize_ard(
            self._df,
            rows=["PARAMCD", "AVISIT", "AVALCAT1"],
            stats=[Statistic.N_SUBJECTS, Statistic.N_PCT],
            context="t_eg_qtcat",
            group_col=groupby,
            adsl=adsl,
        )

    # ------------------------------------------------------------------ #
    # Pre-validation diagnostic                                            #
    # ------------------------------------------------------------------ #

    def check(
        self,
        *,
        spec: EGSummarySpec | None = None,
    ) -> list[str]:
        """Run pre-validation diagnostics without computing.

        Args:
            spec: Optional spec to check against.

        Returns:
            list[str]: Diagnostic messages (empty if all checks pass).

        Examples:
            Check data readiness::

                report = adeg.tlg.eg.check()
        """
        spec = spec or EGSummarySpec()
        diagnostics = spec.check(self._df)

        available = set(self._df.columns)
        for row_def in spec.rows:
            if row_def.field not in available:
                diagnostics.append(
                    f"WARNING: Column '{row_def.field}' not present — "
                    f"'{row_def.label or row_def.field}' sub-analysis will be skipped."
                )

        return diagnostics
