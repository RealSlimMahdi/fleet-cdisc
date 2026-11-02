"""
Disposition TLG sub-namespace — disposition, deaths, enrollment, deviations.

Accessed via ``df.tlg.ds`` on any Polars DataFrame containing ADaM ADSL (or
ADDV) data.  Covers the standard disposition table family:

* ``t_summary``      → DST01  (subject disposition by EOSSTT / DCSREAS)
* ``t_deaths``       → DTHT01 (deaths and primary cause of death)
* ``t_enrollment``   → ENT01  (enrollment by site / region / investigator)
* ``t_deviations``   → PDT01  (major protocol deviations by DVDECOD)

All tables emit a long-format {cards}-compatible ARD.
"""

from __future__ import annotations

from typing import ClassVar

import polars as pl
from pydantic import Field

from ._ard import prepare_frame, summarize_ard, summarize_spec
from ._builder import BuilderVerbsMixin
from ._specs import (
    OverallStat,
    Row,
    SummarySpecBase,
    TLGSpec,
)


class DSDispositionSpec(SummarySpecBase):
    """Spec for subject disposition (DST01: EOSSTT → DCSREAS)."""

    context: ClassVar[str] = "t_ds_disposition"

    rows: list[Row] = Field(default_factory=lambda: [Row(field="EOSSTT"), Row(field="DCSREAS")])
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "EOSSTT", "DCSREAS"]
    )


class DSDeathsSpec(SummarySpecBase):
    """Spec for deaths and primary cause of death (DTHT01)."""

    context: ClassVar[str] = "t_ds_deaths"

    rows: list[Row] = Field(default_factory=lambda: [Row(field="DTHCAT")])
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "DTHFL", "DTHCAT"]
    )


class DSEnrollmentSpec(SummarySpecBase):
    """Spec for enrollment by site (ENT01: REGION1 → COUNTRY → SITEID)."""

    context: ClassVar[str] = "t_ds_enrollment"

    rows: list[Row] = Field(default_factory=lambda: [Row(field="SITEID")])
    required_columns: list[str] = Field(default_factory=lambda: ["USUBJID", "TRTA", "SITEID"])


class DSDeviationsSpec(SummarySpecBase):
    """Spec for major protocol deviations (PDT01: DVDECOD)."""

    context: ClassVar[str] = "t_ds_deviations"

    rows: list[Row] = Field(default_factory=lambda: [Row(field="DVDECOD")])
    required_columns: list[str] = Field(default_factory=lambda: ["USUBJID", "TRTA", "DVDECOD"])


class DSTLGNamespace(BuilderVerbsMixin):
    """Disposition tables and diagnostics.

    Accessed as ``df.tlg.ds``.  Covers the four disposition
    tables — disposition (DST01), deaths (DTHT01), enrollment (ENT01),
    and protocol deviations (PDT01).  Every method emits a long-format
    {cards}-compatible ARD and accepts an inline spec override.

    Args:
        df: A Polars DataFrame containing ADaM ADSL (or ADDV for
            deviations) subject-level data.
    """

    _builder_specs = {
        "t_summary": DSDispositionSpec,
        "t_deaths": DSDeathsSpec,
        "t_enrollment": DSEnrollmentSpec,
        "t_deviations": DSDeviationsSpec,
    }

    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df

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
        return summarize_spec(
            self._df,
            spec or DSDispositionSpec(),
            groupby=groupby,
            adsl=adsl if adsl is not None else self._df,
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
        analysis = prepare_frame(self._df, spec)
        deaths_filter = pl.col("DTHFL") == "Y" if "DTHFL" in analysis.columns else None
        deaths = analysis.filter(deaths_filter) if deaths_filter is not None else analysis

        # Headline block: total deaths against the population denominator.
        total = summarize_ard(
            analysis,
            rows=[],
            stats=spec.statistics,
            context=spec.context,
            group_col=group_col,
            pools=spec.pools,
            column_order=spec.column_order,
            adsl=population,
            adsl_filter=spec.adsl_filter,
            prefilter=deaths_filter,
            header_rows=[OverallStat(label="Total Number of Deaths"), *spec.header_rows],
            value_col=spec.value_col,
            label_col=spec.label_col,
            decimals=spec.decimals,
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
            rows=spec.rows,
            stats=spec.statistics,
            context=spec.context,
            group_col=group_col,
            pools=cause_pools,
            column_order=spec.column_order,
            adsl=deaths_population,
            adsl_filter=spec.adsl_filter,
            prefilter=deaths_filter,
            value_col=spec.value_col,
            label_col=spec.label_col,
            decimals=spec.decimals,
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
        return summarize_spec(
            self._df,
            spec or DSEnrollmentSpec(),
            groupby=groupby,
            adsl=adsl if adsl is not None else self._df,
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
        return summarize_spec(self._df, spec or DSDeviationsSpec(), groupby=groupby, adsl=adsl)

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
        return spec.check(self._df)
