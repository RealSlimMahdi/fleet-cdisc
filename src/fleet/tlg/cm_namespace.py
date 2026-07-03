"""
CM TLG sub-namespace — concomitant-medication summary tables.

Accessed via ``df.tlg.cm`` on any Polars DataFrame containing ADaM CM
(ADCM) data.  Produces a hierarchical CMCLAS→CMDECOD summary of subjects
with at least one concomitant medication, mirroring the GDSR ``cmt01a``
template (ATC class → preferred term, n / % subjects per arm).
"""

from __future__ import annotations

import polars as pl
from pydantic import Field

from ._ard import fill_uncoded, summarize_ard
from ._specs import (
    GroupPool,
    Row,
    Statistic,
    TLGSpec,
)


class CMSummarySpec(TLGSpec):
    """Spec for a concomitant-medication summary table (t_cm_summary).

    Defaults provide zero-config convenience for a standard CMCLAS→CMDECOD
    table, counting subjects with at least one medication per arm.  Every
    field is also settable inline through the same pattern as
    :class:`AESummarySpec`.
    """

    output_type: str = "summary"
    rows: list[Row] = Field(
        default_factory=lambda: [
            Row(field="CMCLAS", label="ATC Class Level 2"),
            Row(field="CMDECOD", label="Other Treatment"),
        ],
        description="Hierarchy of row groupings (ATC class → preferred term).",
    )
    columns: list[str] = Field(
        default_factory=lambda: ["TRTA"],
        description="Column-grouping variables (typically a treatment column).",
    )
    statistics: list[Statistic] = Field(
        default_factory=lambda: [Statistic.N_SUBJECTS, Statistic.N_PCT],
        description="Statistics computed for each row.",
    )
    pools: list[GroupPool] = Field(
        default_factory=list,
        description="Composite (pooled) treatment groups.",
    )
    column_order: list[str] = Field(
        default_factory=list,
        description="Explicit ordering of column labels in the rendered output.",
    )
    denominator: str = Field(
        default="TRTA",
        description="Column used as the denominator when computing percentages.",
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "CMDECOD", "CMCLAS"],
        description="Columns required in the analysis dataset for this spec.",
    )


class CMTLGNamespace:
    """Concomitant-medication tables and diagnostics.

    Accessed as ``df.tlg.cm``.  Produces a CDISC-aligned ARD summarising
    subjects with at least one concomitant medication, broken down by ATC
    class (``CMCLAS``) and preferred term (``CMDECOD``).

    Args:
        df: A Polars DataFrame containing ADaM CM-level data.
    """

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
        spec: CMSummarySpec | None = None,
    ) -> pl.DataFrame:
        """Produce a CM summary ARD (Analysis Results Dataset).

        Computes big-N from *adsl*, then n / % subjects for each
        CMCLAS→CMDECOD (or custom row hierarchy) level.

        Args:
            groupby: Treatment arm column name.  Overrides
                ``spec.columns[0]`` when given.
            adsl: ADSL DataFrame for big-N denominators.  Required for
                percentage calculations.
            spec: Optional ``CMSummarySpec`` override.  If ``None``, the
                default spec is used.

        Returns:
            pl.DataFrame: Long-format {cards}-compatible ARD with columns
                ``group1``, ``group1_level``, ``group2``, ``group2_level``,
                ``variable``, ``variable_level``, ``stat_name``,
                ``stat_label``, ``stat``, ``fmt_fn``, ``stat_fmt``,
                ``warning``, ``error``, ``context``.

        Examples:
            Zero-config CM summary::

                ard = adcm.tlg.cm.t_summary(groupby="TRTA", adsl=adsl)

            Custom spec with pooled arms::

                from fleet.tlg import CMSummarySpec, GroupPool

                spec = CMSummarySpec(
                    pools=[GroupPool(label="Total", arms="*")],
                )
                ard = adcm.tlg.cm.t_summary(spec=spec, adsl=adsl)
        """
        spec = spec or CMSummarySpec()
        group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")
        spec.validate_dataframe(self._df)
        return summarize_ard(
            fill_uncoded(self._df, ["CMCLAS", "CMDECOD"]),
            rows=spec.rows,
            stats=spec.statistics,
            context="t_cm_summary",
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
    # By preferred term only                                               #
    # ------------------------------------------------------------------ #

    def t_by_pt(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
    ) -> pl.DataFrame:
        """Produce a CM-by-preferred-term ARD (CMDECOD only).

        Single-level variant of :meth:`t_summary` mirroring the GDSR
        ``cmt02_pt`` template: counts subjects with at least one
        concomitant medication per arm, broken down by preferred term
        (``CMDECOD``) without the ATC-class hierarchy.

        Args:
            groupby: Treatment arm column name (defaults to ``"TRTA"``).
            adsl: ADSL DataFrame for big-N denominators.  Required for
                percentage calculations.

        Returns:
            pl.DataFrame: Long-format {cards}-compatible ARD.

        Examples:
            ``ard = adcm.tlg.cm.t_by_pt(groupby="TRTA", adsl=adsl)``
        """
        group_col = groupby or "TRTA"
        spec = CMSummarySpec(
            rows=[Row(field="CMDECOD", label="Other Treatment")],
            columns=[group_col],
            required_columns=["USUBJID", group_col, "CMDECOD"],
        )
        spec.validate_dataframe(self._df)
        return summarize_ard(
            fill_uncoded(self._df, ["CMCLAS", "CMDECOD"]),
            rows=spec.rows,
            stats=spec.statistics,
            context="t_cm_by_pt",
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
        spec: CMSummarySpec | None = None,
    ) -> list[str]:
        """Run pre-validation diagnostics without computing.

        Args:
            spec: Optional spec to check against.  If ``None``, the
                default ``CMSummarySpec`` is used.

        Returns:
            list[str]: Diagnostic messages (empty if all checks pass).

        Examples:
            Check data readiness::

                report = adcm.tlg.cm.check()
        """
        spec = spec or CMSummarySpec()
        diagnostics = spec.check(self._df)

        # Additional CM-specific checks
        available = set(self._df.columns)
        for row_def in spec.rows:
            if row_def.field not in available:
                diagnostics.append(
                    f"WARNING: Column '{row_def.field}' not present — "
                    f"'{row_def.label or row_def.field}' sub-analysis will be skipped."
                )

        return diagnostics
