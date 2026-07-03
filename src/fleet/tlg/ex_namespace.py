"""
EX TLG sub-namespace — exposure summary tables.

Accessed via ``df.tlg.ex`` on any Polars DataFrame containing ADaM ADEX
data.  Produces continuous exposure statistics (mean/sd/median/min/max)
per exposure parameter, aligned to the {cards} ARD layout.
"""

from __future__ import annotations

import polars as pl
from pydantic import Field

from ._ard import summarize_ard
from ._builder import TLGBuilder
from ._specs import (
    GroupPool,
    Row,
    Statistic,
    TLGSpec,
)


class EXSummarySpec(TLGSpec):
    """Spec for an exposure (ADEX) summary table.

    Defaults provide zero-config continuous statistics (mean, sd,
    median, min, max) per ``PARAMCD``, grouped by treatment arm.  Every
    field is also settable inline through
    [`TLGBuilder`][fleet.tlg.TLGBuilder].
    """

    output_type: str = "summary"
    rows: list[Row] = Field(
        default_factory=lambda: [Row(field="PARAMCD", label="Parameter")],
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
            "Continuous exposure statistics computed per parameter.  Set "
            "inline via [`TLGBuilder.stats()`][fleet.tlg.TLGBuilder.stats]."
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
            "Explicit ordering of column labels.  Set inline via "
            "[`TLGBuilder.column_order()`][fleet.tlg.TLGBuilder.column_order]."
        ),
    )
    denominator: str = Field(
        default="TRTA",
        description="Column used as the denominator when computing percentages.",
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "PARAMCD", "AVAL"],
        description="Columns required in the analysis dataset for this spec.",
    )
    required_flags: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Per-column lists of required values (content validation).",
    )


class EXTLGNamespace:
    """Exposure tables and diagnostics.

    Accessed as ``df.tlg.ex``.  Supports both spec-driven
    (``t_summary(spec=...)``) and inline builder (``df.tlg.ex.by(...)``)
    workflows.

    Args:
        df: A Polars DataFrame containing ADaM ADEX-level data.
    """

    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df

    def _builder(self) -> TLGBuilder:
        """Return a ``TLGBuilder`` pre-configured with EX defaults."""
        return TLGBuilder(
            self._df,
            context="t_ex_summary",
            spec_cls=EXSummarySpec,
            namespace_cls=EXTLGNamespace,
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
            Inline EX summary::

                ard = (
                    adex.tlg.ex
                    .population(adsl, adsl_filter=pl.col("SAFFL") == "Y")
                    .by("TRTA")
                    .rows(["PARAMCD"])
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
        spec: EXSummarySpec | None = None,
    ) -> pl.DataFrame:
        """Produce an exposure summary ARD (Analysis Results Dataset).

        Computes big-N from *adsl*, then continuous statistics
        (mean/sd/median/min/max) for each exposure parameter.

        Args:
            groupby: Treatment arm column name.  Overrides
                ``spec.columns[0]`` when given.
            adsl: ADSL DataFrame for big-N denominators.
            spec: Optional ``EXSummarySpec`` override.  If ``None``, the
                default spec is used.

        Returns:
            pl.DataFrame: Long-format {cards}-compatible ARD.

        Examples:
            Zero-config EX summary::

                ard = adex.tlg.ex.t_summary(groupby="TRTA", adsl=adsl)

            Custom spec with pooled arms::

                from fleet.tlg import GroupPool

                spec = EXSummarySpec(
                    pools=[GroupPool(label="Total", arms="*")],
                )
                ard = adex.tlg.ex.t_summary(spec=spec, adsl=adsl)
        """
        spec = spec or EXSummarySpec()
        group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")
        spec.validate_dataframe(self._df)
        return summarize_ard(
            self._df,
            rows=spec.rows,
            stats=spec.statistics,
            context="t_ex_summary",
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
        spec: EXSummarySpec | None = None,
    ) -> list[str]:
        """Run pre-validation diagnostics without computing.

        Args:
            spec: Optional spec to check against.

        Returns:
            list[str]: Diagnostic messages (empty if all checks pass).

        Examples:
            Check data readiness::

                report = adex.tlg.ex.check()
        """
        spec = spec or EXSummarySpec()
        diagnostics = spec.check(self._df)

        available = set(self._df.columns)
        for row_def in spec.rows:
            if row_def.field not in available:
                diagnostics.append(
                    f"WARNING: Column '{row_def.field}' not present — "
                    f"'{row_def.label or row_def.field}' sub-analysis will be skipped."
                )

        return diagnostics
