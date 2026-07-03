"""
EG TLG sub-namespace — ECG summary tables.

Accessed via ``df.tlg.eg`` on any Polars DataFrame containing ADaM ADEG data.
"""

from __future__ import annotations

import polars as pl
from pydantic import Field

from ._ard import summarize_ard
from ._builder import BuilderVerbsMixin
from ._specs import (
    Row,
    SchemaError,
    Statistic,
    SummarySpecBase,
)


class EGSummarySpec(SummarySpecBase):
    """Spec for an ECG summary table (t_eg_summary).

    Defaults provide zero-config convenience for a standard ADEG
    per-PARAM × AVISIT continuous-stats table.  Every field is also
    settable inline through [`TLGBuilder`][fleet.tlg.TLGBuilder].
    """

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
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "PARAMCD", "AVAL", "AVISIT", "TRTA"],
        description="Columns required in the analysis dataset for this spec.",
    )


class EGChgSpec(EGSummarySpec):
    """Spec for ECG change from baseline (egt03): CHG stats per PARAM × visit."""

    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "PARAMCD", "AVISIT", "CHG"],
    )


class EGQtcatSpec(SummarySpecBase):
    """Spec for QTc category counts (egt05_qtcat): n / % per PARAM × visit × category."""

    rows: list[Row] = Field(
        default_factory=lambda: [
            Row(field="PARAMCD", label="Parameter"),
            Row(field="AVISIT", label="Visit"),
            Row(field="AVALCAT1", label="QTc Category"),
        ],
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "PARAMCD", "AVISIT", "AVALCAT1"],
    )


class EGTLGNamespace(BuilderVerbsMixin):
    """ECG tables and diagnostics.

    Accessed as ``df.tlg.eg``.  Supports both spec-driven
    (``t_summary(spec=...)``) and inline builder (``df.tlg.eg.by(...)``)
    workflows.

    Args:
        df: A Polars DataFrame containing ADaM ADEG-level data.
    """

    _builder_context = "t_eg_summary"
    _builder_specs = {"t_summary": EGSummarySpec, "t_chg": EGChgSpec, "t_qtcat": EGQtcatSpec}

    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df

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
        spec.validate_dataframe(self._df, group_col=group_col)
        return summarize_ard(
            self._df,
            rows=spec.rows,
            stats=spec.statistics,
            context="t_eg_summary",
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
    # Change-from-baseline (egt03) — continuous                            #
    # ------------------------------------------------------------------ #

    def t_chg(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: EGChgSpec | None = None,
    ) -> pl.DataFrame:
        """ECG change-from-baseline ARD (continuous, egt03).

        Summarizes ``CHG`` (mean/SD/median/min/max) per PARAMCD × AVISIT
        for post-baseline records with a non-missing change value.

        Args:
            groupby: Treatment-arm column; overrides ``spec.columns[0]``.
            adsl: ADSL for big-N denominators.
            spec: Optional ``EGChgSpec`` override.

        Returns:
            pl.DataFrame: {cards}-compatible ARD.

        Examples:
            ``ard = adeg.tlg.eg.t_chg(groupby="TRTA", adsl=adsl)``
        """
        spec = spec or EGChgSpec()
        group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")
        spec.validate_dataframe(self._df, group_col=group_col)
        if "CHG" not in self._df.columns:
            raise SchemaError(
                "t_chg summarizes change from baseline and requires a CHG "
                f"column. Available: {sorted(self._df.columns)}"
            )
        df = self._df.with_columns(pl.col("CHG").alias("AVAL"))
        prefilter = pl.col("CHG").is_not_null()
        if "ABLFL" in df.columns:
            prefilter = prefilter & pl.col("ABLFL").ne_missing("Y")
        return summarize_ard(
            df,
            rows=spec.rows,
            stats=spec.statistics,
            context="t_eg_chg",
            group_col=group_col,
            pools=spec.pools,
            column_order=spec.column_order,
            adsl=adsl,
            adsl_filter=spec.adsl_filter,
            dataset_filter=spec.dataset_filter,
            prefilter=prefilter,
            header_rows=spec.header_rows,
            nested=True,
        )

    # ------------------------------------------------------------------ #
    # QTc category counts (egt05_qtcat) — categorical                      #
    # ------------------------------------------------------------------ #

    def t_qtcat(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: EGQtcatSpec | None = None,
    ) -> pl.DataFrame:
        """QTc category-count ARD (n / %, egt05_qtcat).

        Counts subjects by AVALCAT1 category per PARAMCD × AVISIT.

        Args:
            groupby: Treatment-arm column; overrides ``spec.columns[0]``.
            adsl: ADSL for big-N denominators.
            spec: Optional ``EGQtcatSpec`` override.

        Returns:
            pl.DataFrame: {cards}-compatible ARD.

        Examples:
            ``ard = adeg.tlg.eg.t_qtcat(groupby="TRTA", adsl=adsl)``
        """
        spec = spec or EGQtcatSpec()
        group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")
        spec.validate_dataframe(self._df, group_col=group_col)
        return summarize_ard(
            self._df,
            rows=spec.rows,
            stats=spec.statistics,
            context="t_eg_qtcat",
            group_col=group_col,
            pools=spec.pools,
            column_order=spec.column_order,
            adsl=adsl,
            adsl_filter=spec.adsl_filter,
            dataset_filter=spec.dataset_filter,
            header_rows=spec.header_rows,
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
