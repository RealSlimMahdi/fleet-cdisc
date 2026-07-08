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
from ._builder import BuilderVerbsMixin
from ._specs import (
    Row,
    Statistic,
    SummarySpecBase,
)


class EXSummarySpec(SummarySpecBase):
    """Spec for an exposure (ADEX) summary table.

    Defaults provide zero-config continuous statistics (mean, sd,
    median, min, max) per ``PARAMCD``, grouped by treatment arm.  Every
    field is also settable inline through
    [`TLGBuilder`][fleet.tlg.TLGBuilder].
    """

    rows: list[Row] = Field(
        default_factory=lambda: [Row(field="PARAMCD", label="Parameter")],
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
            "Continuous exposure statistics computed per parameter.  Set "
            "inline via [`TLGBuilder.stats()`][fleet.tlg.TLGBuilder.stats]."
        ),
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "PARAMCD", "AVAL"],
        description="Columns required in the analysis dataset for this spec.",
    )


class EXTLGNamespace(BuilderVerbsMixin):
    """Exposure tables and diagnostics.

    Accessed as ``df.tlg.ex``.  Supports both spec-driven
    (``t_summary(spec=...)``) and inline builder (``df.tlg.ex.by(...)``)
    workflows.

    Args:
        df: A Polars DataFrame containing ADaM ADEX-level data.
    """

    _builder_context = "t_ex_summary"
    _builder_specs = {"t_summary": EXSummarySpec}

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
        spec.validate_dataframe(self._df, group_col=group_col)
        # GDSR EXT01 summarizes the overall-exposure block: restrict to
        # PARCAT1 == "OVERALL" when the column exists so per-interval
        # dose records are not averaged into subject-level statistics.
        prefilter = pl.col("PARCAT1") == "OVERALL" if "PARCAT1" in self._df.columns else None
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
            prefilter=prefilter,
            header_rows=spec.header_rows,
            nested=True,
            value_col=spec.value_col,
            label_col=spec.label_col,
            decimals=spec.decimals,
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

        # Continuous stats assume one record per subject × parameter; with
        # duplicates the mean is record-weighted while n counts subjects.
        if {"USUBJID", "PARAMCD"} <= available:
            df = self._df
            if "PARCAT1" in available:
                df = df.filter(pl.col("PARCAT1") == "OVERALL")
            dup = df.group_by(["USUBJID", "PARAMCD"]).len().filter(pl.col("len") > 1)
            if dup.height > 0:
                diagnostics.append(
                    f"WARNING: {dup.height} subject×parameter group(s) have "
                    "multiple records — continuous statistics will be "
                    "record-weighted, not subject-level."
                )

        return diagnostics
