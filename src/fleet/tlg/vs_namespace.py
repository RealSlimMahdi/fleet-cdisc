"""
VS TLG sub-namespace — vital-signs summary tables.

Accessed via ``df.tlg.vs`` on any Polars DataFrame containing ADaM VS data.
"""

from __future__ import annotations

import polars as pl

from ._ard import summarize_spec
from ._builder import BuilderVerbsMixin
from ._specs import VSSummarySpec


class VSTLGNamespace(BuilderVerbsMixin):
    """Vital-signs tables and diagnostics.

    Accessed as ``df.tlg.vs``.  Supports both spec-driven
    (``t_summary(spec=...)``) and inline builder (``df.tlg.vs.by(...)``)
    workflows.

    Args:
        df: A Polars DataFrame containing ADaM VS-level data.
    """

    _builder_context = "t_vs_summary"
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
        diagnostics = spec.check(self._df)

        available = set(self._df.columns)
        for row_def in spec.rows:
            if row_def.field not in available:
                diagnostics.append(
                    f"WARNING: Column '{row_def.field}' not present — "
                    f"'{row_def.label or row_def.field}' sub-analysis will be skipped."
                )

        return diagnostics
