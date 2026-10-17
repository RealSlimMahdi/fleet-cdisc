"""
VS TLG sub-namespace — vital-signs summary tables.

Accessed via ``df.tlg.vs`` on any Polars DataFrame containing ADaM VS data.
"""

from __future__ import annotations

from typing import ClassVar

import polars as pl
from pydantic import Field

from ._ard import summarize_spec
from ._builder import BuilderVerbsMixin
from ._specs import Row, Statistic, SummarySpecBase


class VSSummarySpec(SummarySpecBase):
    """Spec for a vital-signs summary table."""

    context: ClassVar[str] = "t_vs_summary"
    nested: ClassVar[bool] = True

    rows: list[Row] = Field(
        default_factory=lambda: [Row(field="PARAMCD", label="Parameter")],
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
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "PARAMCD", "AVAL"],
    )


class VSTLGNamespace(BuilderVerbsMixin):
    """Vital-signs tables and diagnostics.

    Accessed as ``df.tlg.vs``.  Supports both spec-driven
    (``t_summary(spec=...)``) and inline builder (``df.tlg.vs.by(...)``)
    workflows.

    Args:
        df: A Polars DataFrame containing ADaM VS-level data.
    """

    _builder_specs = {"t_summary": VSSummarySpec}

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
        return summarize_spec(self._df, spec or VSSummarySpec(), groupby=groupby, adsl=adsl)

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
        return spec.check(self._df)
