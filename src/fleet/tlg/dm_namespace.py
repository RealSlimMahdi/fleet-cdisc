"""
DM TLG sub-namespace — demographic summary tables (DM/ADSL).

Accessed via ``df.tlg.dm`` on any Polars DataFrame containing ADSL-level
demographic data.  Produces a mixed continuous + categorical summary
modelled on the GDSR ``dmt01`` Roche demographics layout.
"""

from __future__ import annotations

from typing import Any

import polars as pl
from pydantic import Field

from ._ard import (
    ard_row as _ard_row,
)
from ._ard import (
    expand_pools,
    summarize_ard,
)
from ._ard import (
    rows_to_ard as _rows_to_ard,
)
from ._ard import (
    validate_pools as _validate_pools,
)
from ._specs import (
    Statistic,
    TLGSpec,
)

#: Statistics describing a continuous variable (e.g. age).
_CONTINUOUS_STATS: list[Statistic] = [
    Statistic.MEAN,
    Statistic.SD,
    Statistic.MEDIAN,
    Statistic.MIN,
    Statistic.MAX,
]


class DMSummarySpec(TLGSpec):
    """Spec for a demographic summary table (t_dm_summary).

    Defaults provide zero-config convenience for a standard ADSL
    demographics table mixing continuous age statistics with categorical
    breakdowns of sex, race, ethnicity and age group.

    Args:
        age_var: Continuous age column (``AGE`` or ``AAGE``).
        categorical_vars: Ordered list of categorical column names.
        category_labels: Display labels keyed by categorical column.
    """

    output_type: str = "summary"
    columns: list[str] = Field(
        default_factory=lambda: ["TRTA"],
        description="Column-grouping variables (typically a treatment column).",
    )
    age_var: str = Field(
        default="AGE",
        description="Continuous age column to summarise (``AGE`` or ``AAGE``).",
    )
    categorical_vars: list[str] = Field(
        default_factory=lambda: ["SEX", "AGEGR1", "RACE", "ETHNIC"],
        description="Ordered categorical columns to break down by level.",
    )
    category_labels: dict[str, str] = Field(
        default_factory=lambda: {
            "SEX": "Sex",
            "AGEGR1": "Age Group (yr)",
            "RACE": "Race",
            "ETHNIC": "Ethnicity",
        },
        description="Display labels for categorical variables.",
    )
    statistics: list[Statistic] = Field(
        default_factory=lambda: [Statistic.N_SUBJECTS, Statistic.N_PCT],
        description="Statistics computed for each categorical level.",
    )
    pools: list[Any] = Field(
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
        default_factory=lambda: ["USUBJID", "TRTA", "AGE", "SEX"],
        description="Columns required in the analysis dataset for this spec.",
    )


class DMTLGNamespace:
    """Demographic summary tables and diagnostics.

    Accessed as ``df.tlg.dm``.  Produces a {cards}-aligned ARD combining
    continuous age statistics with categorical breakdowns (sex, race,
    ethnicity, age group).

    Args:
        df: A Polars DataFrame containing ADSL-level demographic data.
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
        spec: DMSummarySpec | None = None,
    ) -> pl.DataFrame:
        """Produce a demographic summary ARD (Analysis Results Dataset).

        Computes big-N from *adsl* (or the primary DataFrame), continuous
        statistics for the age variable, then categorical n (%) for sex,
        age group, race and ethnicity.

        Args:
            groupby: Treatment arm column name.  Overrides
                ``spec.columns[0]`` when given.
            adsl: ADSL DataFrame for big-N denominators.  Defaults to the
                namespace DataFrame when ``None``.
            spec: Optional ``DMSummarySpec`` override.  If ``None``, the
                default spec is used.

        Returns:
            pl.DataFrame: Long-format {cards}-compatible ARD.

        Examples:
            Zero-config demographics summary::

                ard = adsl.tlg.dm.t_summary(groupby="TRTA", adsl=adsl)
        """
        spec = spec or DMSummarySpec()
        group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")
        denom_src = adsl if adsl is not None else self._df

        # --- Validation ---
        spec.validate_dataframe(self._df)
        _validate_pools(self._df, spec.pools, group_col)

        # --- Categorical breakdowns (big-N + n / %) via shared engine ---
        cat_ard = summarize_ard(
            self._df,
            rows=spec.categorical_vars,
            stats=spec.statistics,
            context="t_dm_summary",
            group_col=group_col,
            pools=spec.pools,
            column_order=spec.column_order,
            adsl=denom_src,
            adsl_filter=spec.adsl_filter,
            dataset_filter=spec.dataset_filter,
        )

        # --- Continuous age statistics ---
        df = self._df
        if spec.dataset_filter is not None:
            df = df.filter(spec.dataset_filter)
        df = expand_pools(df, spec.pools, group_col)

        arms = sorted(df[group_col].drop_nulls().unique().to_list())
        if spec.column_order:
            ordered = [a for a in spec.column_order if a in arms]
            arms = ordered + [a for a in arms if a not in ordered]

        age_var = spec.age_var if spec.age_var in df.columns else None
        if age_var is None:
            return cat_ard

        age_rows: list[dict[str, Any]] = []
        for arm in arms:
            ages = df.filter(pl.col(group_col) == arm)[age_var]
            for stat_type in _CONTINUOUS_STATS:
                stat_name, stat_label, value = _continuous_stat(stat_type, ages)
                age_rows.append(
                    _ard_row(
                        group_col,
                        arm,
                        age_var,
                        spec.category_labels.get(age_var, "Age (yr)"),
                        stat_name,
                        stat_label,
                        value,
                        "t_dm_summary",
                    )
                )

        return pl.concat([cat_ard, _rows_to_ard(age_rows)], how="vertical_relaxed")

    # ------------------------------------------------------------------ #
    # Pre-validation diagnostic                                            #
    # ------------------------------------------------------------------ #

    def check(
        self,
        *,
        spec: DMSummarySpec | None = None,
    ) -> list[str]:
        """Run pre-validation diagnostics without computing.

        Args:
            spec: Optional spec to check against.

        Returns:
            list[str]: Diagnostic messages (empty if all checks pass).

        Examples:
            Check data readiness::

                report = adsl.tlg.dm.check()
        """
        spec = spec or DMSummarySpec()
        diagnostics = spec.check(self._df)

        available = set(self._df.columns)
        if spec.age_var not in available:
            diagnostics.append(
                f"WARNING: Age column '{spec.age_var}' not present — "
                "age statistics will be skipped."
            )
        for field in spec.categorical_vars:
            if field not in available:
                diagnostics.append(
                    f"WARNING: Column '{field}' not present — "
                    f"'{spec.category_labels.get(field, field)}' breakdown will be skipped."
                )
        return diagnostics


def _continuous_stat(
    stat_type: Statistic,
    values: pl.Series,
) -> tuple[str, str, float | None]:
    """Compute a continuous statistic over a non-AVAL value series.

    Args:
        stat_type: The statistic to compute.
        values: Series of numeric values (e.g. ``AGE``).

    Returns:
        Tuple of (stat_name, stat_label, value).
    """
    clean = values.drop_nulls()
    if len(clean) == 0:
        return (stat_type.value, stat_type.value, None)
    if stat_type == Statistic.MEAN:
        return ("mean", "Mean", clean.mean())
    if stat_type == Statistic.SD:
        return ("sd", "SD", clean.std())
    if stat_type == Statistic.MEDIAN:
        return ("median", "Median", clean.median())
    if stat_type == Statistic.MIN:
        return ("min", "Min", clean.min())
    if stat_type == Statistic.MAX:
        return ("max", "Max", clean.max())
    return (stat_type.value, stat_type.value, None)
