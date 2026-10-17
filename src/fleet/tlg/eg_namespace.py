"""
EG TLG sub-namespace — ECG summary tables.

Accessed via ``df.tlg.eg`` on any Polars DataFrame containing ADaM ADEG data.
"""

from __future__ import annotations

from typing import ClassVar

import polars as pl
from pydantic import Field, model_validator

from ._ard import summarize_spec
from ._builder import BuilderVerbsMixin
from ._specs import (
    Row,
    Statistic,
    SummarySpecBase,
    change_from_baseline_prefilter,
)


class EGSummarySpec(SummarySpecBase):
    """Spec for an ECG summary table (t_eg_summary).

    Defaults provide zero-config convenience for a standard ADEG
    per-PARAM × AVISIT continuous-stats table.  Every field is also
    settable inline through [`TLGBuilder`][fleet.tlg.TLGBuilder].
    """

    context: ClassVar[str] = "t_eg_summary"
    nested: ClassVar[bool] = True

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
    """Spec for ECG change from baseline (egt03): CHG stats per PARAM × visit.

    Prefilter rule: the baseline record (``ABLFL`` = Y) and records
    with no change value are dropped before summarising, so ``ABLFL``
    is a required column.  Unless set, the prefilter follows
    ``value_col``; ``prefilter=None`` switches the rule off.
    """

    context: ClassVar[str] = "t_eg_chg"

    value_col: str = Field(
        default="CHG",
        description="Analysis-value column summarized (change from baseline).",
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "PARAMCD", "AVISIT", "CHG"],
    )

    @model_validator(mode="after")
    def _default_prefilter_follows_value_col(self) -> EGChgSpec:
        if "prefilter" not in self.model_fields_set:
            self.prefilter = change_from_baseline_prefilter(self.value_col)
        return self


class EGQtcatSpec(SummarySpecBase):
    """Spec for QTc category counts (egt05_qtcat): n / % per PARAM × visit × category."""

    context: ClassVar[str] = "t_eg_qtcat"
    nested: ClassVar[bool] = False

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
        return summarize_spec(self._df, spec or EGSummarySpec(), groupby=groupby, adsl=adsl)

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

        Summarizes ``spec.value_col`` (``CHG`` by default) with
        mean/SD/median/min/max per PARAMCD × AVISIT for post-baseline
        records with a non-missing change value (the spec's prefilter;
        ``ABLFL`` is required).

        Args:
            groupby: Treatment-arm column; overrides ``spec.columns[0]``.
            adsl: ADSL for big-N denominators.
            spec: Optional ``EGChgSpec`` override.

        Returns:
            pl.DataFrame: {cards}-compatible ARD.

        Examples:
            ``ard = adeg.tlg.eg.t_chg(groupby="TRTA", adsl=adsl)``
        """
        return summarize_spec(self._df, spec or EGChgSpec(), groupby=groupby, adsl=adsl)

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
        return summarize_spec(self._df, spec or EGQtcatSpec(), groupby=groupby, adsl=adsl)

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
        return spec.check(self._df)
