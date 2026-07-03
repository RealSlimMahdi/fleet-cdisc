"""
AE TLG sub-namespace — AE summary tables and listings.

Accessed via ``df.tlg.ae`` on any Polars DataFrame containing ADaM AE data.
"""

from __future__ import annotations

import polars as pl
from pydantic import Field

from ._ard import fill_uncoded, summarize_ard, worst_case
from ._builder import TLGBuilder
from ._specs import (
    AEListingSpec,
    AESummarySpec,
    Row,
    resolve_filter,
)


class AESocPtSpec(AESummarySpec):
    """Spec for AE by SOC → PT (AET02): n / % subjects by SOC → PT."""

    rows: list[Row] = Field(
        default_factory=lambda: [
            Row(field="AEBODSYS", label="MedDRA System Organ Class"),
            Row(field="AEDECOD", label="MedDRA Preferred Term"),
        ]
    )


class AESeveritySpec(AESummarySpec):
    """Spec for AE by greatest severity (AET03): n / % by SOC → worst intensity.

    Each subject is counted once per SOC at their greatest intensity
    (``severity_order`` rank, never alphabetical), so the intensity rows
    partition the SOC's any-AE count.  PT-level intensity nesting needs
    a third lineage slot (group3) and is deferred until the ARD schema
    grows one.
    """

    rows: list[Row] = Field(
        default_factory=lambda: [
            Row(field="AEBODSYS", label="MedDRA System Organ Class"),
            Row(field="AESEV", label="Intensity"),
        ]
    )
    severity_order: list[str] = Field(
        default_factory=lambda: ["MILD", "MODERATE", "SEVERE"],
        description=(
            "Intensity values from least to most severe — the explicit "
            "clinical rank used for the worst-case reduction."
        ),
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "AEBODSYS", "AESEV"]
    )


class AEGradeSpec(AESummarySpec):
    """Spec for AE by highest NCI CTCAE grade (AET04): n / % by SOC → worst grade.

    Each subject is counted once per SOC at their highest toxicity grade
    (``grade_order`` rank).
    """

    rows: list[Row] = Field(
        default_factory=lambda: [
            Row(field="AEBODSYS", label="MedDRA System Organ Class"),
            Row(field="AETOXGR", label="Grade"),
        ]
    )
    grade_order: list[str] = Field(
        default_factory=lambda: ["1", "2", "3", "4", "5"],
        description="Toxicity grades from lowest to highest.",
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "AEBODSYS", "AETOXGR"]
    )


class AERelationshipSpec(AESummarySpec):
    """Spec for AE by relationship (n / % by SOC → relationship).

    Each subject is counted once per SOC — related if any of their
    events in the SOC is related (``relationship_order`` rank).
    """

    rows: list[Row] = Field(
        default_factory=lambda: [
            Row(field="AEBODSYS", label="MedDRA System Organ Class"),
            Row(field="AEREL", label="Relationship"),
        ]
    )
    relationship_order: list[str] = Field(
        default_factory=lambda: ["N", "Y"],
        description="Relationship values from least to most related.",
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "AEBODSYS", "AEREL"]
    )


class AETLGNamespace:
    """AE tables, listings, and diagnostics.

    Accessed as ``df.tlg.ae``.  Supports both spec-driven
    (``t_summary(spec=...)``) and inline builder (``df.tlg.ae.by(...)``)
    workflows.

    Args:
        df: A Polars DataFrame containing ADaM AE-level data.
    """

    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df

    def _builder(self) -> TLGBuilder:
        """Return a ``TLGBuilder`` pre-configured with AE defaults."""
        return TLGBuilder(
            self._df,
            context="t_ae_summary",
            spec_cls=AESummarySpec,
            namespace_cls=AETLGNamespace,
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
            Inline AE summary::

                ard = (
                    adae.tlg.ae
                    .population(adsl, adsl_filter=pl.col("SAFFL") == "Y")
                    .by("TRTA")
                    .rows(["AEBODSYS", "AEDECOD"])
                    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
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
        spec: AESummarySpec | None = None,
    ) -> pl.DataFrame:
        """Produce an AE summary ARD (Analysis Results Dataset).

        Computes big-N from *adsl*, then n / % subjects and optionally
        event counts for each SOC→PT (or custom row hierarchy).

        Args:
            groupby: Treatment arm column name.  Overrides
                ``spec.columns[0]`` when given.
            adsl: ADSL DataFrame for big-N denominators.  Required for
                percentage calculations.
            spec: Optional ``AESummarySpec`` override.  If ``None``, the
                default spec is used.

        Returns:
            pl.DataFrame: Long-format {cards}-compatible ARD with columns
                ``group1``, ``group1_level``, ``group2``, ``group2_level``,
                ``variable``, ``variable_level``, ``stat_name``,
                ``stat_label``, ``stat``, ``fmt_fn``, ``stat_fmt``,
                ``warning``, ``error``, ``context``.

        Examples:
            Zero-config AE summary::

                ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)

            Custom spec with pooled arms::

                from fleet.tlg import AESummarySpec, GroupPool

                spec = AESummarySpec(
                    pools=[GroupPool(label="Total", arms="*")],
                )
                ard = adae.tlg.ae.t_summary(spec=spec, adsl=adsl)
        """
        spec = spec or AESummarySpec()
        group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")
        spec.validate_dataframe(self._df)
        return summarize_ard(
            fill_uncoded(self._df, ["AEBODSYS", "AEDECOD"]),
            rows=spec.rows,
            stats=spec.statistics,
            context="t_ae_summary",
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
    # Hierarchical variants (AET02 / AET03 / AET04)                        #
    # ------------------------------------------------------------------ #

    def t_soc_pt(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: AESocPtSpec | None = None,
    ) -> pl.DataFrame:
        """AE by SOC → PT (AET02): n / % subjects per arm × SOC → PT.

        Args:
            groupby: Treatment-arm column; overrides ``spec.columns[0]``.
            adsl: ADSL for big-N denominators (percentages).
            spec: Optional ``AESocPtSpec`` override.

        Returns:
            pl.DataFrame: {cards}-compatible ARD.

        Examples:
            ``ard = adae.tlg.ae.t_soc_pt(groupby="TRTA", adsl=adsl)``
        """
        spec = spec or AESocPtSpec()
        group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")
        spec.validate_dataframe(self._df)
        return summarize_ard(
            fill_uncoded(self._df, ["AEBODSYS", "AEDECOD"]),
            rows=spec.rows,
            stats=spec.statistics,
            context="t_ae_soc_pt",
            group_col=group_col,
            pools=spec.pools,
            column_order=spec.column_order,
            adsl=adsl,
            adsl_filter=spec.adsl_filter,
            dataset_filter=spec.dataset_filter,
            header_rows=spec.header_rows,
            nested=True,
        )

    def t_severity(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: AESeveritySpec | None = None,
    ) -> pl.DataFrame:
        """AE by greatest severity (AET03): n / % by SOC → worst intensity.

        Each subject is counted once per SOC at their greatest intensity
        (``spec.severity_order`` rank), so intensity rows partition the
        SOC's subject count instead of double-counting a subject at
        every intensity they reported.

        Args:
            groupby: Treatment-arm column; overrides ``spec.columns[0]``.
            adsl: ADSL for big-N denominators (percentages).
            spec: Optional ``AESeveritySpec`` override.

        Returns:
            pl.DataFrame: {cards}-compatible ARD.

        Examples:
            ``ard = adae.tlg.ae.t_severity(groupby="TRTA", adsl=adsl)``
        """
        spec = spec or AESeveritySpec()
        group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")
        spec.validate_dataframe(self._df)
        df = fill_uncoded(self._df, ["AEBODSYS", "AEDECOD"])
        df = worst_case(
            df,
            by=["USUBJID", group_col, "AEBODSYS"],
            order_col="AESEV",
            order=spec.severity_order,
        )
        return summarize_ard(
            df,
            rows=spec.rows,
            stats=spec.statistics,
            context="t_ae_severity",
            group_col=group_col,
            pools=spec.pools,
            column_order=spec.column_order,
            adsl=adsl,
            adsl_filter=spec.adsl_filter,
            dataset_filter=spec.dataset_filter,
            header_rows=spec.header_rows,
            nested=True,
        )

    def t_grade(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: AEGradeSpec | None = None,
    ) -> pl.DataFrame:
        """AE by highest NCI CTCAE grade (AET04): n / % by SOC → worst grade.

        Each subject is counted once per SOC at their highest toxicity
        grade (``spec.grade_order`` rank).

        Args:
            groupby: Treatment-arm column; overrides ``spec.columns[0]``.
            adsl: ADSL for big-N denominators (percentages).
            spec: Optional ``AEGradeSpec`` override.

        Returns:
            pl.DataFrame: {cards}-compatible ARD.

        Examples:
            ``ard = adae.tlg.ae.t_grade(groupby="TRTA", adsl=adsl)``
        """
        spec = spec or AEGradeSpec()
        group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")
        spec.validate_dataframe(self._df)
        df = fill_uncoded(self._df, ["AEBODSYS", "AEDECOD"])
        df = df.with_columns(pl.col("AETOXGR").cast(pl.Utf8))
        df = worst_case(
            df,
            by=["USUBJID", group_col, "AEBODSYS"],
            order_col="AETOXGR",
            order=spec.grade_order,
        )
        return summarize_ard(
            df,
            rows=spec.rows,
            stats=spec.statistics,
            context="t_ae_grade",
            group_col=group_col,
            pools=spec.pools,
            column_order=spec.column_order,
            adsl=adsl,
            adsl_filter=spec.adsl_filter,
            dataset_filter=spec.dataset_filter,
            header_rows=spec.header_rows,
            nested=True,
        )

    def t_relationship(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: AERelationshipSpec | None = None,
    ) -> pl.DataFrame:
        """AE by relationship: n / % by SOC → relationship.

        Each subject is counted once per SOC — related if any of their
        events in the SOC is related (``spec.relationship_order`` rank).

        Args:
            groupby: Treatment-arm column; overrides ``spec.columns[0]``.
            adsl: ADSL for big-N denominators (percentages).
            spec: Optional ``AERelationshipSpec`` override.

        Returns:
            pl.DataFrame: {cards}-compatible ARD.

        Examples:
            ``ard = adae.tlg.ae.t_relationship(groupby="TRTA", adsl=adsl)``
        """
        spec = spec or AERelationshipSpec()
        group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")
        spec.validate_dataframe(self._df)
        df = fill_uncoded(self._df, ["AEBODSYS", "AEDECOD"])
        df = worst_case(
            df,
            by=["USUBJID", group_col, "AEBODSYS"],
            order_col="AEREL",
            order=spec.relationship_order,
        )
        return summarize_ard(
            df,
            rows=spec.rows,
            stats=spec.statistics,
            context="t_ae_relationship",
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
    # Listing                                                              #
    # ------------------------------------------------------------------ #

    def l_listing(
        self,
        *,
        spec: AEListingSpec | None = None,
    ) -> pl.DataFrame:
        """Produce an AE listing DataFrame.

        Args:
            spec: Optional ``AEListingSpec`` override.  If ``None``, the
                default spec is used.

        Returns:
            pl.DataFrame: A plain DataFrame with the requested columns,
                sorted per spec.

        Examples:
            Default AE listing::

                listing = adae.tlg.ae.l_listing()

            Custom listing with additional columns::

                from fleet.tlg import AEListingSpec, Column

                spec = AEListingSpec(
                    columns=[
                        Column(field="USUBJID", label="Subject"),
                        Column(field="AEDECOD", label="Preferred Term"),
                    ],
                    sort_by=["USUBJID"],
                )
                listing = adae.tlg.ae.l_listing(spec=spec)
        """
        spec = spec or AEListingSpec()
        spec.validate_dataframe(self._df)

        df = self._df
        dataset_filter = resolve_filter(spec.dataset_filter)
        if dataset_filter is not None:
            df = df.filter(dataset_filter)

        # Select only requested columns (that exist)
        available = set(df.columns)
        select_cols = [c.field for c in spec.columns if c.field in available]
        df = df.select(select_cols)

        # Rename to labels
        rename_map = {c.field: c.label for c in spec.columns if c.label and c.field in available}
        if rename_map:
            df = df.rename(rename_map)

        # Sort
        sort_cols = []
        for s in spec.sort_by:
            col_name = rename_map.get(s, s)
            if col_name in df.columns:
                sort_cols.append(col_name)
        if sort_cols:
            df = df.sort(sort_cols)

        return df

    # ------------------------------------------------------------------ #
    # Pre-validation diagnostic                                            #
    # ------------------------------------------------------------------ #

    def check(
        self,
        *,
        spec: AESummarySpec | None = None,
    ) -> list[str]:
        """Run pre-validation diagnostics without computing.

        Args:
            spec: Optional spec to check against.  If ``None``, the
                default ``AESummarySpec`` is used.

        Returns:
            list[str]: Diagnostic messages (empty if all checks pass).

        Examples:
            Check data readiness::

                report = adae.tlg.ae.check()
        """
        spec = spec or AESummarySpec()
        diagnostics = spec.check(self._df)

        # Additional AE-specific checks
        available = set(self._df.columns)
        for row_def in spec.rows:
            if row_def.field not in available:
                diagnostics.append(
                    f"WARNING: Column '{row_def.field}' not present — "
                    f"'{row_def.label or row_def.field}' sub-analysis will be skipped."
                )

        return diagnostics
