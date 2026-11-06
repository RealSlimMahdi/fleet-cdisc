"""
AE TLG sub-namespace — AE summary tables and listings.

Accessed via ``df.tlg.ae`` on any Polars DataFrame containing ADaM AE data.
"""

from __future__ import annotations

from typing import ClassVar, Self

import polars as pl
from pydantic import Field, model_validator

from ._ard import listing_frame, summarize_spec
from ._builder import BuilderVerbsMixin
from ._specs import (
    Column,
    MissingLevel,
    OverallStat,
    Row,
    SummarySpecBase,
    TLGSpec,
    Uncoded,
    resolve_filter,
)


class AESummarySpec(SummarySpecBase):
    """Spec for an AE summary table (t_ae_summary).

    Defaults provide zero-config convenience for a standard SOC→PT
    table.  Uncoded rule: a null ``AEBODSYS`` or ``AEDECOD`` is counted
    under ``"No Coding Available"``.
    """

    context: ClassVar[str] = "t_ae_summary"
    nested: ClassVar[bool] = True

    uncoded: Uncoded | None = Field(
        default_factory=lambda: Uncoded(columns=["AEBODSYS", "AEDECOD"]),
    )
    rows: list[Row] = Field(
        default_factory=lambda: [
            Row(field="AEBODSYS", label="System Organ Class"),
            Row(field="AEDECOD", label="Preferred Term"),
        ],
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "AEDECOD", "AEBODSYS"],
    )


class AEListingSpec(TLGSpec):
    """Spec for an AE listing (l_ae_listing)."""

    _unconsumed_spec_fields: ClassVar[frozenset[str]] = frozenset({"adsl_filter", "header_rows"})

    output_type: str = "listing"
    columns: list[Column] = Field(
        default_factory=lambda: [
            Column(field="USUBJID", label="Subject"),
            Column(field="TRTA", label="Treatment"),
            Column(field="AEBODSYS", label="SOC"),
            Column(field="AEDECOD", label="Preferred Term"),
            Column(field="AESEV", label="Severity"),
            Column(field="AESER", label="Serious"),
        ],
        description="Ordered list of columns to include in the listing.",
    )
    sort_by: list[str] = Field(
        default_factory=lambda: ["USUBJID", "AEBODSYS", "AEDECOD"],
        description="Sort order applied before rendering.",
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "AEDECOD"],
        description="Columns required in the analysis dataset for this spec.",
    )


class AEOverviewSpec(AESummarySpec):
    """Spec for the AE overview table (AET01).

    A real overview: whole-population header rows (any AE, any serious
    AE, any AE leading to treatment discontinuation, fatal AEs) with an
    **empty** row hierarchy — the SOC→PT breakdown is AET02
    (:class:`AESocPtSpec`), not this table.
    """

    context: ClassVar[str] = "t_ae_overview"

    rows: list[Row] = Field(default_factory=list)
    header_rows: list[OverallStat] = Field(
        default_factory=lambda: [
            OverallStat(label="Subjects with at least one adverse event"),
            OverallStat(
                label="Subjects with at least one serious adverse event",
                filter='pl.col("AESER") == "Y"',
            ),
            OverallStat(
                label="Subjects with at least one adverse event leading to discontinuation",
                filter='pl.col("AEACN") == "DRUG WITHDRAWN"',
            ),
            OverallStat(
                label="Subjects with fatal adverse events",
                filter='pl.col("AESDTH") == "Y"',
            ),
        ],
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "AESER", "AEACN", "AESDTH"],
    )


class AESocPtSpec(AESummarySpec):
    """Spec for AE by SOC → PT (AET02): n / % subjects by SOC → PT."""

    context: ClassVar[str] = "t_ae_soc_pt"

    rows: list[Row] = Field(
        default_factory=lambda: [
            Row(field="AEBODSYS", label="MedDRA System Organ Class"),
            Row(field="AEDECOD", label="MedDRA Preferred Term"),
        ]
    )


class _WorstCaseAESpec(AESummarySpec):
    """Shared rules of the worst-case AE tables (AET03, AET04, relationship).

    The last row field is the ranked level; a subject is counted once at
    its worst value within its arm and the other row levels.  Unless
    set, the required columns and the missing level follow ``rows``.
    """

    #: Name of the spec field holding the rank, from least to most severe.
    order_field: ClassVar[str] = ""

    @model_validator(mode="after")
    def _rows_drive_the_reduction(self) -> Self:
        """Refuse empty rows; derive required columns and the missing level."""
        if not self.rows:
            raise ValueError(
                f"{type(self).__name__}.rows is empty: the last row field is the "
                "ranked level of the worst-case reduction. Give at least one row."
            )
        if self.uses_default("required_columns"):
            self.required_columns = list(
                dict.fromkeys(["USUBJID", "TRTA", *(r.field for r in self.rows)])
            )
        if "missing" not in self.model_fields_set:
            self.missing = MissingLevel(columns=[self.rows[-1].field])
        return self

    def leaf_rank(self) -> tuple[list[str], str] | None:
        """Return the rank of the last row field and its spec field name.

        Returns:
            tuple[list[str], str] | None: The rank and the field name.

        Examples:
            ``AEGradeSpec().leaf_rank() == (["1", "2", "3", "4", "5"], "grade_order")``
        """
        return list(getattr(self, self.order_field)), self.order_field


class AESeveritySpec(_WorstCaseAESpec):
    """Spec for AE by greatest severity (AET03): n / % by SOC → worst intensity.

    Each subject is counted once per SOC at their greatest intensity
    (``severity_order`` rank, never alphabetical), so the intensity rows
    partition the SOC's any-AE count.  The ranked level is the last row
    field (``AESEV`` by default; ``ASEV`` when the rows say so).  A
    record with a null intensity counts under ``"Missing"`` only when
    the subject has no ranked intensity in the SOC.
    """

    context: ClassVar[str] = "t_ae_severity"
    order_field: ClassVar[str] = "severity_order"

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


class AEGradeSpec(_WorstCaseAESpec):
    """Spec for AE by highest NCI CTCAE grade (AET04): n / % by SOC → worst grade.

    Each subject is counted once per SOC at their highest toxicity grade
    (``grade_order`` rank).  A numeric grade such as ``3.0`` reads as
    ``"3"``.
    """

    context: ClassVar[str] = "t_ae_grade"
    order_field: ClassVar[str] = "grade_order"

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


class AERelationshipSpec(_WorstCaseAESpec):
    """Spec for AE by relationship (n / % by SOC → relationship).

    Each subject is counted once per SOC — related if any of their
    events in the SOC is related (``relationship_order`` rank).
    """

    context: ClassVar[str] = "t_ae_relationship"
    order_field: ClassVar[str] = "relationship_order"

    rows: list[Row] = Field(
        default_factory=lambda: [
            Row(field="AEBODSYS", label="MedDRA System Organ Class"),
            Row(field="AEREL", label="Relationship"),
        ]
    )
    relationship_order: list[str] = Field(
        default_factory=lambda: ["N", "Y"],
        description=(
            "Relationship values from least to most related.  AEREL has no "
            "CDISC codelist, so the default fits a Y/N study only.  A value "
            "of AEREL outside this list stops the table: set the study's "
            "terms here."
        ),
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "AEBODSYS", "AEREL"]
    )


class AETLGNamespace(BuilderVerbsMixin):
    """AE tables, listings, and diagnostics.

    Accessed as ``df.tlg.ae``.  Supports both spec-driven
    (``t_summary(spec=...)``) and inline builder (``df.tlg.ae.by(...)``)
    workflows.

    Args:
        df: A Polars DataFrame containing ADaM AE-level data.
    """

    _builder_specs = {
        "t_summary": AESummarySpec,
        "t_overview": AEOverviewSpec,
        "t_soc_pt": AESocPtSpec,
        "t_severity": AESeveritySpec,
        "t_grade": AEGradeSpec,
        "t_relationship": AERelationshipSpec,
        "l_listing": AEListingSpec,
    }

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
            pl.DataFrame: ARD in the {cards} long layout, with columns
                ``group1``, ``group1_level``, ``group2``, ``group2_level``,
                ``variable``, ``variable_level``, ``stat_name``,
                ``stat_label``, ``stat``, ``fmt_fn``, ``stat_fmt``,
                ``warning``, ``error``, ``context``.

        Examples:
            AE summary, ADSL arm in TRT01A::

                spec = AESummarySpec(adsl_group_col="TRT01A")
                ard = adae.tlg.ae.t_summary(spec=spec, adsl=adsl)

            Custom spec with pooled arms::

                from fleet.tlg import AESummarySpec, GroupPool

                spec = AESummarySpec(
                    pools=[GroupPool(label="Total", arms="*")],
                    adsl_group_col="TRT01A",
                )
                ard = adae.tlg.ae.t_summary(spec=spec, adsl=adsl)
        """
        return summarize_spec(self._df, spec or AESummarySpec(), groupby=groupby, adsl=adsl)

    # ------------------------------------------------------------------ #
    # Overview (AET01)                                                     #
    # ------------------------------------------------------------------ #

    def t_overview(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: AEOverviewSpec | None = None,
    ) -> pl.DataFrame:
        """Overview of adverse events (AET01): whole-population header rows.

        Counts subjects with any AE, any serious AE, any AE leading to
        treatment discontinuation, and fatal AEs — one n / % row each,
        no SOC→PT hierarchy (that is :meth:`t_soc_pt` / AET02).  The
        default filters read ``AESER`` / ``AEACN`` / ``AESDTH``;
        override ``spec.header_rows`` for sponsor-specific definitions.

        Args:
            groupby: Treatment-arm column; overrides ``spec.columns[0]``.
            adsl: ADSL for big-N denominators (percentages).
            spec: Optional ``AEOverviewSpec`` override.

        Returns:
            pl.DataFrame: ARD in the {cards} long layout.

        Examples:
            ADSL arm in TRT01A::

                spec = AEOverviewSpec(adsl_group_col="TRT01A")
                ard = adae.tlg.ae.t_overview(spec=spec, adsl=adsl)
        """
        return summarize_spec(self._df, spec or AEOverviewSpec(), groupby=groupby, adsl=adsl)

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
            pl.DataFrame: ARD in the {cards} long layout.

        Examples:
            ADSL arm in TRT01A::

                spec = AESocPtSpec(adsl_group_col="TRT01A")
                ard = adae.tlg.ae.t_soc_pt(spec=spec, adsl=adsl)
        """
        return summarize_spec(self._df, spec or AESocPtSpec(), groupby=groupby, adsl=adsl)

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
        every intensity they reported.  The reduction runs after the
        pools, so a subject on two arms counts once in Total; the SOC
        rows and header rows count every record.

        Args:
            groupby: Treatment-arm column; overrides ``spec.columns[0]``.
            adsl: ADSL for big-N denominators (percentages).
            spec: Optional ``AESeveritySpec`` override.

        Returns:
            pl.DataFrame: ARD in the {cards} long layout.

        References:
            tern ``count_occurrences_by_grade``; GDSR AET03.

        Examples:
            ADSL arm in TRT01A::

                spec = AESeveritySpec(adsl_group_col="TRT01A")
                ard = adae.tlg.ae.t_severity(spec=spec, adsl=adsl)
        """
        return summarize_spec(self._df, spec or AESeveritySpec(), groupby=groupby, adsl=adsl)

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
            pl.DataFrame: ARD in the {cards} long layout.

        Examples:
            ADSL arm in TRT01A::

                spec = AEGradeSpec(adsl_group_col="TRT01A")
                ard = adae.tlg.ae.t_grade(spec=spec, adsl=adsl)
        """
        spec = spec or AEGradeSpec()
        df = self._df
        grade_col = spec.rows[-1].field
        if grade_col in df.columns:
            df = df.with_columns(pl.col(grade_col).cast(pl.Utf8).str.replace(r"\.0$", ""))
        return summarize_spec(df, spec, groupby=groupby, adsl=adsl)

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
            pl.DataFrame: ARD in the {cards} long layout.

        Examples:
            ADSL arm in TRT01A::

                spec = AERelationshipSpec(adsl_group_col="TRT01A")
                ard = adae.tlg.ae.t_relationship(spec=spec, adsl=adsl)
        """
        return summarize_spec(self._df, spec or AERelationshipSpec(), groupby=groupby, adsl=adsl)

    # ------------------------------------------------------------------ #
    # Listing                                                              #
    # ------------------------------------------------------------------ #

    def l_listing(
        self,
        *,
        spec: AEListingSpec | None = None,
    ) -> pl.DataFrame:
        """Produce an AE listing DataFrame.

        Applies ``dataset_filter``, sorts by ``sort_by`` (a key need not
        be a displayed column; ties keep the input order), formats each
        column with its ``Column.format`` and keeps the requested
        columns, as PROC SORT BY then PROC PRINT VAR.

        Args:
            spec: Optional ``AEListingSpec`` override.  If ``None``, the
                default spec is used.

        Returns:
            pl.DataFrame: A plain DataFrame with the requested columns,
                sorted per spec.

        Raises:
            SchemaError: If a listing column or a sort key that the user
                set is not in the dataset, or a format cannot print a
                value.

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
        return listing_frame(df, spec)

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
        return spec.check(self._df)
