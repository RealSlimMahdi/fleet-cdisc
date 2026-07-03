"""
LB TLG sub-namespace — laboratory summary tables and abnormality listings.

Accessed via ``df.tlg.lb`` on any Polars DataFrame containing ADaM ADLB data.
Ports the ``{tlg.templates}`` LBT01 (continuous lab statistics per
PARAM/AVISIT) and LBL01 (laboratory abnormalities listing) templates.
"""

from __future__ import annotations

import polars as pl
from pydantic import Field

from ._ard import summarize_ard
from ._specs import (
    Column,
    GroupPool,
    Row,
    Statistic,
    TLGSpec,
    resolve_filter,
)


class LBSummarySpec(TLGSpec):
    """Spec for a laboratory summary table (LBT01).

    Defaults provide zero-config continuous statistics for each
    parameter (``PARAMCD``) at each analysis visit (``AVISIT``),
    mirroring the GDSR ``LBT01`` baseline/change layout.
    """

    output_type: str = "summary"
    rows: list[Row] = Field(
        default_factory=lambda: [
            Row(field="PARAMCD", label="Parameter"),
            Row(field="AVISIT", label="Analysis Visit"),
        ],
        description=(
            "Hierarchy of row groupings (PARAM \u2192 AVISIT).  Set inline via "
            "[`TLGBuilder.rows()`][fleet.tlg.TLGBuilder.rows]."
        ),
    )
    columns: list[str] = Field(
        default_factory=lambda: ["TRTA"],
        description=(
            "Column-grouping variables.  Set inline via "
            "[`TLGBuilder.by()`][fleet.tlg.TLGBuilder.by]."
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
            "Continuous statistics computed per row.  Set inline via "
            "[`TLGBuilder.stats()`][fleet.tlg.TLGBuilder.stats]."
        ),
    )
    pools: list[GroupPool] = Field(
        default_factory=list,
        description=(
            "Composite (pooled) treatment groups.  Set inline via "
            "[`TLGBuilder.pools()`][fleet.tlg.TLGBuilder.pools]."
        ),
    )
    column_order: list[str] = Field(
        default_factory=list,
        description=(
            "Explicit ordering of column labels.  Set inline via "
            "[`TLGBuilder.column_order()`][fleet.tlg.TLGBuilder.column_order]."
        ),
    )
    denominator: str = Field(
        default="TRTA",
        description="Column used as the denominator when computing percentages.",
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "PARAMCD", "AVAL", "AVISIT"],
        description="Columns required in the analysis dataset for this spec.",
    )


class LBListingSpec(TLGSpec):
    """Spec for a laboratory abnormalities listing (LBL01).

    Defaults select results with a non-normal range indicator
    (``ANRIND``) and present subject, parameter, value, and toxicity
    grade columns sorted for review.
    """

    output_type: str = "listing"
    columns: list[Column] = Field(
        default_factory=lambda: [
            Column(field="USUBJID", label="Subject"),
            Column(field="TRTA", label="Treatment"),
            Column(field="PARAM", label="Parameter"),
            Column(field="AVISIT", label="Analysis Visit"),
            Column(field="AVAL", label="Result"),
            Column(field="AVALU", label="Unit"),
            Column(field="ANRIND", label="Range Indicator"),
            Column(field="ATOXGR", label="Toxicity Grade"),
        ],
        description="Ordered list of columns to include in the listing.",
    )
    sort_by: list[str] = Field(
        default_factory=lambda: ["USUBJID", "PARAM", "AVISIT"],
        description="Sort order applied before rendering.",
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "PARAMCD", "AVAL", "ANRIND"],
        description="Columns required in the analysis dataset for this spec.",
    )


class LBTLGNamespace:
    """Laboratory tables, listings, and diagnostics.

    Accessed as ``df.tlg.lb``.  Provides the LBT01 continuous lab
    statistics table and the LBL01 abnormalities listing.

    Args:
        df: A Polars DataFrame containing ADaM ADLB-level data.
    """

    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df

    # ------------------------------------------------------------------ #
    # Summary table (LBT01)                                                #
    # ------------------------------------------------------------------ #

    def t_summary(
        self,
        *,
        groupby: str | None = None,
        adsl: pl.DataFrame | None = None,
        spec: LBSummarySpec | None = None,
    ) -> pl.DataFrame:
        """Produce a laboratory summary ARD (Analysis Results Dataset).

        Computes big-N from *adsl*, then continuous statistics for each
        parameter at each analysis visit (or custom row hierarchy),
        cards-aligned for downstream rendering.

        Args:
            groupby: Treatment arm column name.  Overrides
                ``spec.columns[0]`` when given.
            adsl: ADSL DataFrame for big-N denominators.
            spec: Optional ``LBSummarySpec`` override.  If ``None``, the
                default spec is used.

        Returns:
            pl.DataFrame: Long-format {cards}-compatible ARD with columns
                ``group1``, ``group1_level``, ``group2``, ``group2_level``,
                ``variable``, ``variable_level``, ``stat_name``,
                ``stat_label``, ``stat``, ``fmt_fn``, ``stat_fmt``,
                ``warning``, ``error``, ``context``.

        Examples:
            Zero-config lab summary::

                ard = adlb.tlg.lb.t_summary(groupby="TRTA", adsl=adsl)

            Custom spec with pooled arms::

                from fleet.tlg import GroupPool

                from fleet.tlg.lb_namespace import LBSummarySpec

                spec = LBSummarySpec(pools=[GroupPool(label="Total", arms="*")])
                ard = adlb.tlg.lb.t_summary(spec=spec, adsl=adsl)
        """
        spec = spec or LBSummarySpec()
        group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")
        spec.validate_dataframe(self._df)
        return summarize_ard(
            self._df,
            rows=spec.rows,
            stats=spec.statistics,
            context="t_lb_summary",
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
    # Change from baseline (LBT02/LBT03)                                   #
    # ------------------------------------------------------------------ #

    def t_chg(
        self,
        *,
        groupby: str = "TRTA",
        adsl: pl.DataFrame | None = None,
    ) -> pl.DataFrame:
        """Mean change-from-baseline ARD per parameter and visit (LBT02/03).

        Computes continuous statistics for post-baseline visits, grouped by
        parameter (``PARAMCD``) and analysis visit (``AVISIT``).

        Args:
            groupby: Treatment-arm column.
            adsl: ADSL DataFrame for big-N denominators.

        Returns:
            pl.DataFrame: {cards}-compatible ARD.

        Examples:
            ``ard = adlb.tlg.lb.t_chg(groupby="TRTA", adsl=adsl)``
        """
        return summarize_ard(
            self._df,
            rows=["PARAMCD", "AVISIT"],
            stats=[
                Statistic.N_SUBJECTS,
                Statistic.MEAN,
                Statistic.SD,
                Statistic.MEDIAN,
                Statistic.MIN,
                Statistic.MAX,
            ],
            context="t_lb_chg",
            group_col=groupby,
            adsl=adsl,
            prefilter=pl.col("ABLFL") != "Y" if "ABLFL" in self._df.columns else None,
        )

    # ------------------------------------------------------------------ #
    # Shift counts (LBT03)                                                 #
    # ------------------------------------------------------------------ #

    def t_shift(
        self,
        *,
        groupby: str = "TRTA",
        adsl: pl.DataFrame | None = None,
    ) -> pl.DataFrame:
        """Shift n / % ARD from baseline range to analysis range (LBT03).

        Counts subjects by parameter, baseline range indicator (``BNRIND``)
        and analysis range indicator (``ANRIND``).

        Args:
            groupby: Treatment-arm column.
            adsl: ADSL DataFrame for big-N denominators.

        Returns:
            pl.DataFrame: {cards}-compatible ARD.

        Examples:
            ``ard = adlb.tlg.lb.t_shift(groupby="TRTA", adsl=adsl)``
        """
        return summarize_ard(
            self._df,
            rows=["PARAMCD", "BNRIND", "ANRIND"],
            stats=[Statistic.N_SUBJECTS, Statistic.N_PCT],
            context="t_lb_shift",
            group_col=groupby,
            adsl=adsl,
        )

    # ------------------------------------------------------------------ #
    # Abnormal counts (LBT04)                                              #
    # ------------------------------------------------------------------ #

    def t_abnormal(
        self,
        *,
        groupby: str = "TRTA",
        adsl: pl.DataFrame | None = None,
    ) -> pl.DataFrame:
        """Abnormal-result n / % ARD per parameter and direction (LBT04).

        Counts subjects with abnormal post-baseline range indicators
        (``ANRIND``) by parameter, restricted to on-treatment records.

        Args:
            groupby: Treatment-arm column.
            adsl: ADSL DataFrame for big-N denominators.

        Returns:
            pl.DataFrame: {cards}-compatible ARD.

        Examples:
            ``ard = adlb.tlg.lb.t_abnormal(groupby="TRTA", adsl=adsl)``
        """
        prefilter = (
            pl.col("ANRIND").str.to_uppercase().is_in(["LOW", "LOW LOW", "HIGH", "HIGH HIGH"])
        )
        if "ONTRTFL" in self._df.columns:
            prefilter = prefilter & (pl.col("ONTRTFL") == "Y")
        return summarize_ard(
            self._df,
            rows=["PARAMCD", "ANRIND"],
            stats=[Statistic.N_SUBJECTS, Statistic.N_PCT],
            context="t_lb_abnormal",
            group_col=groupby,
            adsl=adsl,
            prefilter=prefilter if "ANRIND" in self._df.columns else None,
        )

    # ------------------------------------------------------------------ #
    # Listing (LBL01)                                                      #
    # ------------------------------------------------------------------ #

    def l_listing(
        self,
        *,
        spec: LBListingSpec | None = None,
    ) -> pl.DataFrame:
        """Produce a laboratory abnormalities listing DataFrame.

        Selects rows with a non-normal range indicator (``ANRIND``) and
        returns the requested columns, sorted per spec.

        Args:
            spec: Optional ``LBListingSpec`` override.  If ``None``, the
                default spec is used.

        Returns:
            pl.DataFrame: A plain DataFrame with the requested columns,
                sorted per spec.

        Examples:
            Default lab listing::

                listing = adlb.tlg.lb.l_listing()

            Custom listing with explicit columns::

                from fleet.tlg import Column

                from fleet.tlg.lb_namespace import LBListingSpec

                spec = LBListingSpec(
                    columns=[
                        Column(field="USUBJID", label="Subject"),
                        Column(field="PARAM", label="Parameter"),
                        Column(field="AVAL", label="Result"),
                    ],
                    sort_by=["USUBJID"],
                )
                listing = adlb.tlg.lb.l_listing(spec=spec)
        """
        spec = spec or LBListingSpec()
        spec.validate_dataframe(self._df)

        df = self._df
        dataset_filter = resolve_filter(spec.dataset_filter)
        if dataset_filter is not None:
            df = df.filter(dataset_filter)
        elif "ANRIND" in df.columns:
            # Default: abnormalities only (exclude normal / missing indicators).
            df = df.filter(
                pl.col("ANRIND").is_not_null()
                & (~pl.col("ANRIND").str.to_uppercase().is_in(["NORMAL", "N", ""]))
            )

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
        spec: LBSummarySpec | None = None,
    ) -> list[str]:
        """Run pre-validation diagnostics without computing.

        Args:
            spec: Optional spec to check against.  If ``None``, the
                default ``LBSummarySpec`` is used.

        Returns:
            list[str]: Diagnostic messages (empty if all checks pass).

        Examples:
            Check data readiness::

                report = adlb.tlg.lb.check()
        """
        spec = spec or LBSummarySpec()
        diagnostics = spec.check(self._df)

        available = set(self._df.columns)
        for row_def in spec.rows:
            if row_def.field not in available:
                diagnostics.append(
                    f"WARNING: Column '{row_def.field}' not present — "
                    f"'{row_def.label or row_def.field}' sub-analysis will be skipped."
                )

        return diagnostics
