"""
CM TLG sub-namespace — concomitant-medication summary tables.

Accessed via ``df.tlg.cm`` on any Polars DataFrame containing ADaM CM
(ADCM) data.  Produces a hierarchical CMCLAS→CMDECOD summary of subjects
with at least one concomitant medication, mirroring the GDSR ``cmt01a``
template (ATC class → preferred term, n / % subjects per arm).
"""

from __future__ import annotations

from typing import ClassVar

import polars as pl
from pydantic import Field

from ._ard import summarize_spec
from ._builder import BuilderVerbsMixin
from ._specs import Row, SummarySpecBase, Uncoded


class CMSummarySpec(SummarySpecBase):
    """Spec for a concomitant-medication summary table (t_cm_summary).

    Defaults provide zero-config convenience for a standard CMCLAS→CMDECOD
    table, counting subjects with at least one medication per arm.  Every
    field is also settable inline through the same pattern as
    :class:`AESummarySpec`.  Uncoded rule: a null ``CMCLAS`` or
    ``CMDECOD`` is counted under ``"No Coding Available"``.
    """

    context: ClassVar[str] = "t_cm_summary"
    nested: ClassVar[bool] = True

    uncoded: Uncoded | None = Field(
        default_factory=lambda: Uncoded(columns=["CMCLAS", "CMDECOD"]),
    )
    rows: list[Row] = Field(
        default_factory=lambda: [
            Row(field="CMCLAS", label="ATC Class Level 2"),
            Row(field="CMDECOD", label="Other Treatment"),
        ],
        description="Hierarchy of row groupings (ATC class → preferred term).",
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "CMDECOD", "CMCLAS"],
        description="Columns required in the analysis dataset for this spec.",
    )


class CMByPTSpec(CMSummarySpec):
    """Spec for CM by preferred term only (cmt02): flat CMDECOD counts."""

    context: ClassVar[str] = "t_cm_by_pt"
    nested: ClassVar[bool] = False

    rows: list[Row] = Field(
        default_factory=lambda: [Row(field="CMDECOD", label="Other Treatment")],
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "CMDECOD"],
    )


class CMTLGNamespace(BuilderVerbsMixin):
    """Concomitant-medication tables and diagnostics.

    Accessed as ``df.tlg.cm``.  Produces a CDISC-aligned ARD summarising
    subjects with at least one concomitant medication, broken down by ATC
    class (``CMCLAS``) and preferred term (``CMDECOD``).

    Args:
        df: A Polars DataFrame containing ADaM CM-level data.
    """

    _builder_specs = {"t_summary": CMSummarySpec, "t_by_pt": CMByPTSpec}

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
        return summarize_spec(self._df, spec or CMSummarySpec(), groupby=groupby, adsl=adsl)

    # ------------------------------------------------------------------ #
    # By preferred term only                                               #
    # ------------------------------------------------------------------ #

    def t_by_pt(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: CMByPTSpec | None = None,
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
        return summarize_spec(self._df, spec or CMByPTSpec(), groupby=groupby, adsl=adsl)

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
        return spec.check(self._df)
