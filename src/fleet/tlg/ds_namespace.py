"""
Disposition TLG sub-namespace — disposition, deaths, enrollment, deviations.

Accessed via ``df.tlg.ds`` on any Polars DataFrame containing ADaM ADSL (or
ADDV) data.  Mirrors the Roche/pharmaverse ``tlg.templates`` disposition
family:

* ``t_summary``      → DST01  (subject disposition by EOSSTT / DCSREAS)
* ``t_deaths``       → DTHT01 (deaths and primary cause of death)
* ``t_enrollment``   → ENT01  (enrollment by site / region / investigator)
* ``t_deviations``   → PDT01  (major protocol deviations by DVDECOD)

All tables emit a long-format {cards}-compatible ARD.
"""

from __future__ import annotations

import polars as pl
from pydantic import Field

from ._ard import summarize_ard
from ._builder import BuilderVerbsMixin
from ._specs import (
    GroupPool,
    OverallStat,
    Row,
    Statistic,
    SummarySpecBase,
    TLGSpec,
    resolve_filter,
)


class DSDispositionSpec(SummarySpecBase):
    """Spec for subject disposition (DST01: EOSSTT → DCSREAS)."""

    rows: list[Row] = Field(default_factory=lambda: [Row(field="EOSSTT"), Row(field="DCSREAS")])
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "EOSSTT", "DCSREAS"]
    )


class DSDeathsSpec(SummarySpecBase):
    """Spec for deaths and primary cause of death (DTHT01)."""

    rows: list[Row] = Field(default_factory=lambda: [Row(field="DTHCAT")])
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "DTHFL", "DTHCAT"]
    )


class DSEnrollmentSpec(SummarySpecBase):
    """Spec for enrollment by site (ENT01: REGION1 → COUNTRY → SITEID)."""

    rows: list[Row] = Field(default_factory=lambda: [Row(field="SITEID")])
    required_columns: list[str] = Field(default_factory=lambda: ["USUBJID", "TRTA", "SITEID"])


class DSDeviationsSpec(SummarySpecBase):
    """Spec for major protocol deviations (PDT01: DVDECOD)."""

    rows: list[Row] = Field(default_factory=lambda: [Row(field="DVDECOD")])
    required_columns: list[str] = Field(default_factory=lambda: ["USUBJID", "TRTA", "DVDECOD"])


class DSTLGNamespace(BuilderVerbsMixin):
    """Disposition tables and diagnostics.

    Accessed as ``df.tlg.ds``.  Covers the four Roche disposition
    templates — disposition (DST01), deaths (DTHT01), enrollment (ENT01),
    and protocol deviations (PDT01).  Every method emits a long-format
    {cards}-compatible ARD and accepts an inline spec override.

    Args:
        df: A Polars DataFrame containing ADaM ADSL (or ADDV for
            deviations) subject-level data.
    """

    _builder_context = "t_ds_disposition"
    _builder_specs = {
        "t_summary": DSDispositionSpec,
        "t_deaths": DSDeathsSpec,
        "t_enrollment": DSEnrollmentSpec,
        "t_deviations": DSDeviationsSpec,
    }

    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df

    # ------------------------------------------------------------------ #
    # Shared count engine                                                  #
    # ------------------------------------------------------------------ #

    def _count_summary(
        self,
        *,
        groupby: str | None,
        adsl: pl.DataFrame | None,
        spec: TLGSpec,
        context: str,
        prefilter: pl.Expr | None = None,
    ) -> pl.DataFrame:
        """Build a categorical n / % subject-count ARD over the row hierarchy.

        Args:
            groupby: Treatment arm column; overrides ``spec.columns[0]``.
            adsl: ADSL DataFrame supplying big-N denominators.  ``None``
                is passed through — the engine raises when percentages
                are requested without a population.
            spec: A disposition spec carrying ``rows``, ``statistics``,
                ``pools``, and ``column_order``.
            context: TLG context tag written to every ARD row.
            prefilter: Optional Polars expression applied to the analysis
                DataFrame before counting (e.g. ``DTHFL == "Y"``).

        Returns:
            pl.DataFrame: A {cards}-compatible ARD.

        Raises:
            SchemaError: If pools reference missing arms or the ARD fails
                schema validation.
        """
        rows: list[str] = getattr(spec, "rows", [])
        stats: list[Statistic] = getattr(spec, "statistics", [])
        pools: list[GroupPool] = getattr(spec, "pools", [])
        order: list[str] = getattr(spec, "column_order", [])
        group_col = groupby or (spec.columns[0] if getattr(spec, "columns", None) else "TRTA")

        spec.validate_dataframe(self._df, group_col=group_col)

        return summarize_ard(
            self._df,
            rows=rows,
            stats=stats,
            context=context,
            group_col=group_col,
            pools=pools,
            column_order=order,
            adsl=adsl,
            adsl_filter=spec.adsl_filter,
            dataset_filter=spec.dataset_filter,
            prefilter=prefilter,
            header_rows=spec.header_rows,
        )

    # ------------------------------------------------------------------ #
    # DST01 — disposition                                                  #
    # ------------------------------------------------------------------ #

    def t_summary(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: DSDispositionSpec | None = None,
    ) -> pl.DataFrame:
        """Produce a subject-disposition ARD (DST01).

        Counts subjects by end-of-study status (``EOSSTT``) and, nested
        beneath it, discontinuation reason (``DCSREAS``), per treatment arm.

        Args:
            groupby: Treatment arm column.  Overrides ``spec.columns[0]``.
            adsl: ADSL DataFrame for big-N denominators.  Defaults to the
                primary DataFrame.
            spec: Optional ``DSDispositionSpec`` override.

        Returns:
            pl.DataFrame: A {cards}-compatible disposition ARD.

        Examples:
            Zero-config disposition table::

                ard = adsl.tlg.ds.t_summary(groupby="TRTA", adsl=adsl)
        """
        return self._count_summary(
            groupby=groupby,
            adsl=adsl if adsl is not None else self._df,
            spec=spec or DSDispositionSpec(),
            context="t_ds_disposition",
        )

    # ------------------------------------------------------------------ #
    # DTHT01 — deaths                                                      #
    # ------------------------------------------------------------------ #

    def t_deaths(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: DSDeathsSpec | None = None,
    ) -> pl.DataFrame:
        """Produce a deaths ARD (DTHT01).

        Emits a ``"Total Number of Deaths"`` headline row (n / % of the
        arm population) followed by primary cause of death (``DTHCAT``)
        rows whose percentages use the **deaths** denominator, matching
        the NEST template.  Deaths with a missing cause appear as an
        explicit ``"Unknown"`` level instead of vanishing.

        Arms without any death get the headline zeros but no cause
        breakdown (there are no deaths to break down).

        Args:
            groupby: Treatment arm column.  Overrides ``spec.columns[0]``.
            adsl: ADSL DataFrame for big-N denominators.  Defaults to the
                primary DataFrame.
            spec: Optional ``DSDeathsSpec`` override.

        Returns:
            pl.DataFrame: A {cards}-compatible deaths ARD.

        Examples:
            Death counts and causes::

                ard = adsl.tlg.ds.t_deaths(groupby="TRTA", adsl=adsl)
        """
        spec = spec or DSDeathsSpec()
        group_col = groupby or (spec.columns[0] if getattr(spec, "columns", None) else "TRTA")
        spec.validate_dataframe(self._df, group_col=group_col)
        population = adsl if adsl is not None else self._df
        # The dataset filter must bite before deaths are identified, so the
        # numerators, the deaths denominator, and the cause rows agree.
        analysis = self._df
        dataset_filter = resolve_filter(spec.dataset_filter)
        if dataset_filter is not None:
            analysis = analysis.filter(dataset_filter)
        deaths_filter = pl.col("DTHFL") == "Y" if "DTHFL" in analysis.columns else None
        deaths = analysis.filter(deaths_filter) if deaths_filter is not None else analysis

        # Headline block: total deaths against the population denominator.
        total = summarize_ard(
            analysis,
            rows=[],
            stats=spec.statistics,
            context="t_ds_deaths",
            group_col=group_col,
            pools=spec.pools,
            column_order=spec.column_order,
            adsl=population,
            adsl_filter=spec.adsl_filter,
            prefilter=deaths_filter,
            header_rows=[OverallStat(label="Total Number of Deaths"), *spec.header_rows],
        )

        death_ids = deaths["USUBJID"].unique().to_list()
        if not death_ids:
            return total

        # Cause block: percentages among deaths, not the full population.
        # Explicit-arm pools survive only when all their arms have deaths —
        # a pool cannot be validated against a population it has no members in.
        deaths_population = population.filter(pl.col("USUBJID").is_in(death_ids))
        death_arms = set(deaths[group_col].drop_nulls().unique().to_list())
        cause_pools = [
            pool for pool in spec.pools if pool.arms == "*" or set(pool.arms) <= death_arms
        ]
        cause_df = analysis
        if "DTHCAT" in cause_df.columns:
            cause_df = cause_df.with_columns(pl.col("DTHCAT").fill_null("Unknown"))
        causes = summarize_ard(
            cause_df,
            rows=getattr(spec, "rows", []),
            stats=spec.statistics,
            context="t_ds_deaths",
            group_col=group_col,
            pools=cause_pools,
            column_order=spec.column_order,
            adsl=deaths_population,
            adsl_filter=spec.adsl_filter,
            prefilter=deaths_filter,
        )
        # The headline block already carries the population N rows; drop
        # the cause block's deaths-denominator N rows to avoid two
        # conflicting "N" definitions in one ARD.
        causes = causes.filter(~((pl.col("variable") == "") & (pl.col("stat_name") == "N")))
        return pl.concat([total, causes], how="vertical_relaxed")

    # ------------------------------------------------------------------ #
    # ENT01 — enrollment by site                                           #
    # ------------------------------------------------------------------ #

    def t_enrollment(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: DSEnrollmentSpec | None = None,
    ) -> pl.DataFrame:
        """Produce an enrollment-by-site ARD (ENT01).

        Counts enrolled subjects per site (``SITEID``) within each
        treatment arm.

        Args:
            groupby: Treatment arm column.  Overrides ``spec.columns[0]``.
            adsl: ADSL DataFrame for big-N denominators.  Defaults to the
                primary DataFrame.
            spec: Optional ``DSEnrollmentSpec`` override.

        Returns:
            pl.DataFrame: A {cards}-compatible enrollment ARD.

        Examples:
            Enrollment counts per site::

                ard = adsl.tlg.ds.t_enrollment(groupby="TRTA", adsl=adsl)
        """
        return self._count_summary(
            groupby=groupby,
            adsl=adsl if adsl is not None else self._df,
            spec=spec or DSEnrollmentSpec(),
            context="t_ds_enrollment",
        )

    # ------------------------------------------------------------------ #
    # PDT01 — protocol deviations                                          #
    # ------------------------------------------------------------------ #

    def t_deviations(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: DSDeviationsSpec | None = None,
    ) -> pl.DataFrame:
        """Produce a protocol-deviations ARD (PDT01).

        Counts subjects with major protocol deviations by category
        (``DVDECOD``) per treatment arm.  The primary DataFrame is ADDV —
        it is record-level, so it is never used as its own denominator;
        percentages require the ADSL population.

        Args:
            groupby: Treatment arm column.  Overrides ``spec.columns[0]``.
            adsl: ADSL DataFrame for big-N denominators.  Required when
                percentage statistics are requested.
            spec: Optional ``DSDeviationsSpec`` override.

        Returns:
            pl.DataFrame: A {cards}-compatible deviations ARD.

        Examples:
            Deviation counts over ADDV::

                ard = addv.tlg.ds.t_deviations(groupby="TRTA", adsl=adsl)
        """
        return self._count_summary(
            groupby=groupby,
            adsl=adsl,
            spec=spec or DSDeviationsSpec(),
            context="t_ds_deviations",
        )

    # ------------------------------------------------------------------ #
    # Pre-validation diagnostic                                            #
    # ------------------------------------------------------------------ #

    def check(
        self,
        *,
        spec: TLGSpec | None = None,
    ) -> list[str]:
        """Run pre-validation diagnostics without computing.

        Args:
            spec: Optional spec to check against.  Defaults to
                ``DSDispositionSpec``.

        Returns:
            list[str]: Diagnostic messages (empty if all checks pass).

        Examples:
            Check ADSL readiness for disposition tables::

                report = adsl.tlg.ds.check()
        """
        spec = spec or DSDispositionSpec()
        diagnostics = spec.check(self._df)

        available = set(self._df.columns)
        row_fields = [getattr(r, "field", r) for r in getattr(spec, "rows", [])]
        for field in row_fields:
            if field not in available:
                diagnostics.append(
                    f"WARNING: Column '{field}' not present — its sub-analysis will be skipped."
                )
        return diagnostics
