"""
MH TLG sub-namespace — Medical-history summary tables.

Accessed via ``df.tlg.mh`` on any Polars DataFrame containing ADaM MH
(ADMH) data.  Mirrors the GDSR MHT01 layout: subject counts and
percentages by MedDRA System Organ Class → Preferred Term.
"""

from __future__ import annotations

from typing import ClassVar

import polars as pl
from pydantic import Field

from ._ard import summarize_spec
from ._builder import BuilderVerbsMixin
from ._specs import Row, SummarySpecBase, Uncoded


class MHSummarySpec(SummarySpecBase):
    """Spec for a medical-history summary table (MHT01): n / % by SOC → PT.

    Uncoded rule: a null ``MHBODSYS`` or ``MHDECOD`` is counted under
    ``"No Coding Available"``.
    """

    context: ClassVar[str] = "t_mh_summary"
    nested: ClassVar[bool] = True

    uncoded: Uncoded | None = Field(
        default_factory=lambda: Uncoded(columns=["MHBODSYS", "MHDECOD"]),
    )
    rows: list[Row] = Field(
        default_factory=lambda: [
            Row(field="MHBODSYS", label="MedDRA System Organ Class"),
            Row(field="MHDECOD", label="MedDRA Preferred Term"),
        ]
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "MHDECOD", "MHBODSYS"]
    )


class MHTLGNamespace(BuilderVerbsMixin):
    """Medical-history tables, accessed as ``df.tlg.mh``."""

    _builder_context = "t_mh_summary"
    _builder_specs = {"t_summary": MHSummarySpec}

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
        return summarize_spec(self._df, spec or MHSummarySpec(), groupby=groupby, adsl=adsl)

    def check(self, *, spec: MHSummarySpec | None = None) -> list[str]:
        """Run pre-validation diagnostics without computing."""
        spec = spec or MHSummarySpec()
        diagnostics = spec.check(self._df)
        available = set(self._df.columns)
        for row_def in spec.rows:
            if row_def.field not in available:
                diagnostics.append(f"WARNING: Column '{row_def.field}' not present — skipped.")
        return diagnostics
