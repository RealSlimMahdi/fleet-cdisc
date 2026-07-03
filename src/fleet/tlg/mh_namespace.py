"""
MH TLG sub-namespace — Medical-history summary tables.

Accessed via ``df.tlg.mh`` on any Polars DataFrame containing ADaM MH
(ADMH) data.  Mirrors the GDSR MHT01 layout: subject counts and
percentages by MedDRA System Organ Class → Preferred Term.
"""

from __future__ import annotations

import polars as pl
from pydantic import Field

from ._ard import fill_uncoded, summarize_ard
from ._specs import GroupPool, Row, Statistic, TLGSpec


class MHSummarySpec(TLGSpec):
    """Spec for a medical-history summary table (MHT01): n / % by SOC → PT."""

    output_type: str = "summary"
    rows: list[Row] = Field(
        default_factory=lambda: [
            Row(field="MHBODSYS", label="MedDRA System Organ Class"),
            Row(field="MHDECOD", label="MedDRA Preferred Term"),
        ]
    )
    columns: list[str] = Field(default_factory=lambda: ["TRTA"])
    statistics: list[Statistic] = Field(
        default_factory=lambda: [Statistic.N_SUBJECTS, Statistic.N_PCT]
    )
    pools: list[GroupPool] = Field(default_factory=list)
    column_order: list[str] = Field(default_factory=list)
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "MHDECOD", "MHBODSYS"]
    )


class MHTLGNamespace:
    """Medical-history tables, accessed as ``df.tlg.mh``."""

    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df

    def t_summary(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: MHSummarySpec | None = None,
    ) -> pl.DataFrame:
        """Produce a medical-history summary ARD (n / % subjects by SOC → PT).

        Args:
            groupby: Treatment-arm column; overrides ``spec.columns[0]``.
            adsl: ADSL for big-N denominators (percentages).
            spec: Optional ``MHSummarySpec`` override.

        Returns:
            pl.DataFrame: {cards}-compatible ARD.

        Examples:
            ``ard = admh.tlg.mh.t_summary(groupby="TRTA", adsl=adsl)``
        """
        spec = spec or MHSummarySpec()
        group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")
        spec.validate_dataframe(self._df)
        return summarize_ard(
            fill_uncoded(self._df, ["MHBODSYS", "MHDECOD"]),
            rows=spec.rows,
            stats=spec.statistics,
            context="t_mh_summary",
            group_col=group_col,
            pools=spec.pools,
            column_order=spec.column_order,
            adsl=adsl,
            adsl_filter=spec.adsl_filter,
            dataset_filter=spec.dataset_filter,
            header_rows=spec.header_rows,
            nested=True,
        )

    def check(self, *, spec: MHSummarySpec | None = None) -> list[str]:
        """Run pre-validation diagnostics without computing."""
        spec = spec or MHSummarySpec()
        diagnostics = spec.check(self._df)
        available = set(self._df.columns)
        for row_def in spec.rows:
            if row_def.field not in available:
                diagnostics.append(f"WARNING: Column '{row_def.field}' not present — skipped.")
        return diagnostics
