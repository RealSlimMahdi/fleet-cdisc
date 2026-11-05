"""
DM TLG sub-namespace — demographic summary tables (DM/ADSL).

Accessed via ``df.tlg.dm`` on any Polars DataFrame containing ADSL-level
demographic data.  Produces a mixed continuous + categorical summary
in the style of a standard demographics table (DMT01).
"""

from __future__ import annotations

from typing import Any, ClassVar

import polars as pl
from pydantic import Field

from ._ard import (
    ard_row as _ard_row,
)
from ._ard import (
    expand_pools,
    nan_to_null,
    prepare_frame,
    restrict_to_population,
    summarize_ard,
)
from ._ard import (
    rows_to_ard as _rows_to_ard,
)
from ._builder import BuilderVerbsMixin
from ._specs import (
    ADSL_ARM_FALLBACK,
    MissingLevel,
    Row,
    SchemaError,
    Statistic,
    SummarySpecBase,
)

#: Statistics describing a continuous variable (e.g. age), n first as
#: PROC MEANS N and tern ``analyze_vars``.
_CONTINUOUS_STATS: list[Statistic] = [
    Statistic.N_SUBJECTS,
    Statistic.MEAN,
    Statistic.SD,
    Statistic.MEDIAN,
    Statistic.MIN,
    Statistic.MAX,
]


class DMSummarySpec(SummarySpecBase):
    """Spec for a demographic summary table (t_dm_summary).

    Defaults provide zero-config convenience for a standard ADSL
    demographics table mixing continuous age statistics with categorical
    breakdowns of sex, race, ethnicity and age group.  A subject with a
    null category value counts in a ``"Missing"`` row, last in the
    block (``missing``).  Each continuous block starts with n, the count
    of subjects with a value.  The default arm is the ADSL arm: ``TRT01A``,
    else ``TRT01P`` when ADSL has no ``TRT01A``.  Each field's
    ``description`` documents it (rendered by mkdocstrings) — a docstring
    ``Args:`` section would duplicate them and confuse griffe, since
    Pydantic fields are not ``__init__`` parameters.  ``rows`` and
    ``value_col`` do not apply: set ``categorical_vars`` and
    ``continuous_vars``.

    References:
        ADaMIG 1.3, section 3.1.4: ADSL carries the arm as TRTxxP and
        TRTxxA; TRTA and TRTP are BDS and OCCDS variables.  ADR-0046.
        tern ``analyze_vars`` and SAS PROC MEANS N (n row); ADR-0055.
    """

    context: ClassVar[str] = "t_dm_summary"
    arm_fallback: ClassVar[tuple[str, ...]] = ADSL_ARM_FALLBACK
    _unconsumed_spec_fields: ClassVar[frozenset[str]] = frozenset({"rows", "value_col"})

    missing: MissingLevel | None = Field(
        default_factory=lambda: MissingLevel(columns=["SEX", "AGEGR1", "RACE", "ETHNIC"]),
    )

    continuous_vars: dict[str, str] = Field(
        default_factory=lambda: {"AGE": "Age (yr)"},
        description=(
            "Continuous columns to summarise, each with its block label "
            '(e.g. ``{"AGE": "Age (yr)", "HEIGHTBL": "Height (cm)"}``).  '
            "Each block shows n, Mean, SD, Median, Min and Max.  Every "
            "column must be in ADSL.  Set inline via "
            "[`TLGBuilder.continuous()`][fleet.tlg.TLGBuilder.continuous]."
        ),
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
    columns: list[str] = Field(
        default_factory=lambda: ["TRT01A"],
        description=(
            "Column-grouping variable: the ADSL arm.  When not set, ``TRT01A``, else ``TRT01P``."
        ),
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRT01A", "SEX"],
        description=(
            "Columns required in the analysis dataset for this spec.  The "
            "columns of ``continuous_vars`` are required too."
        ),
    )


class DMTLGNamespace(BuilderVerbsMixin):
    """Demographic summary tables and diagnostics.

    Accessed as ``df.tlg.dm``.  Produces a {cards}-aligned ARD combining
    continuous age statistics with categorical breakdowns (sex, race,
    ethnicity, age group).

    Args:
        df: A Polars DataFrame containing ADSL-level demographic data.
    """

    _builder_specs = {"t_summary": DMSummarySpec}

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

        Computes big-N from *adsl* (or the primary DataFrame), categorical
        n (%) for sex, age group, race and ethnicity, then one block of
        n, Mean, SD, Median, Min and Max per ``continuous_vars`` entry
        (default age).

        Args:
            groupby: Treatment arm column name.  Overrides
                ``spec.columns[0]`` when given.  Default: ``TRT01A``,
                else ``TRT01P`` (ADR-0046).
            adsl: ADSL DataFrame for big-N denominators.  Defaults to the
                namespace DataFrame when ``None``.
            spec: Optional ``DMSummarySpec`` override.  If ``None``, the
                default spec is used.

        Returns:
            pl.DataFrame: ARD in the {cards} long layout.

        Examples:
            Zero-config demographics summary, by TRT01A::

                ard = adsl.tlg.dm.t_summary()
        """
        spec = spec or DMSummarySpec()
        group_col = groupby or spec.default_group_col(self._df.columns)
        denom_src = adsl if adsl is not None else self._df

        # --- Validation ---
        spec.validate_dataframe(self._df, group_col=group_col)
        absent = [v for v in spec.continuous_vars if v not in self._df.columns]
        if absent:
            raise SchemaError(
                f"continuous_vars {absent} are not in the analysis dataset. "
                f"Available: {sorted(self._df.columns)}"
            )
        not_numeric = [v for v in spec.continuous_vars if not self._df[v].dtype.is_numeric()]
        if not_numeric:
            v = not_numeric[0]
            raise SchemaError(
                f"Continuous statistics need a numeric {v}; {v} is "
                f"{self._df[v].dtype}. Cast it: pl.col('{v}').cast(pl.Float64)"
            )
        count_stats = (Statistic.N_SUBJECTS, Statistic.N_PCT, Statistic.N_EVENTS)
        cont_stats = [s for s in spec.statistics if s not in count_stats]
        if cont_stats:
            raise SchemaError(
                f"DM statistics {[s.value for s in cont_stats]} do not apply: "
                "statistics set the categorical rows (counts), and each "
                "continuous_vars block (age) always shows n, Mean, SD, Median, "
                "Min and Max. Remove them."
            )

        # For demographics the analysis dataset IS the population, so the
        # population filter applies to numerators and continuous stats
        # too — filtering only the denominators would let out-of-population
        # subjects into the counts (pct > 100%).
        analysis_df = restrict_to_population(self._df, denom_src, spec.adsl_filter)
        analysis_df = prepare_frame(analysis_df, spec)

        # --- Categorical breakdowns (big-N + n / %) via shared engine ---
        # Each categorical variable carries its display label so the
        # renderer can head its block ("Sex", "Race", …).  A default
        # variable that ADSL lacks is left out; a variable the user named
        # must exist (the engine raises).
        cat_vars = spec.categorical_vars
        if spec.uses_default("categorical_vars"):
            cat_vars = [f for f in cat_vars if f in analysis_df.columns]
        cat_rows = [Row(field=f, label=spec.category_labels.get(f)) for f in cat_vars]
        cat_ard = summarize_ard(
            analysis_df,
            rows=cat_rows,
            stats=spec.statistics,
            context=spec.context,
            group_col=group_col,
            pools=spec.pools,
            column_order=spec.column_order,
            adsl=denom_src,
            adsl_filter=spec.adsl_filter,
            header_rows=spec.header_rows,
            value_col=spec.value_col,
            label_col=spec.label_col,
            decimals=spec.decimals,
            missing=spec.missing,
            adsl_group_col=spec.adsl_group_col,
        )

        # --- Continuous statistics, one block per continuous_vars entry ---
        df = expand_pools(analysis_df, spec.pools, group_col, strict=False)
        df = df.with_columns(pl.col(group_col).cast(pl.Utf8))

        # Same arm universe (and order) as the engine's big-N rows, so an
        # arm without analysis records keeps its column in the block.
        arms = cat_ard.filter(pl.col("stat_name") == "N")["group1_level"].to_list()

        fmt = spec.decimals or {}
        cont_rows: list[dict[str, Any]] = []
        for var, label in spec.continuous_vars.items():
            values_df = nan_to_null(df, var)
            for arm in arms:
                values = values_df.filter(pl.col(group_col) == arm)[var]
                for stat_type in _CONTINUOUS_STATS:
                    stat_name, stat_label, value = _continuous_stat(stat_type, values)
                    cont_rows.append(
                        _ard_row(
                            group_col,
                            arm,
                            var,
                            label,
                            stat_name,
                            stat_label,
                            value,
                            spec.context,
                            fmt_fn=fmt.get(stat_name),
                        )
                    )
        if not cont_rows:
            return cat_ard
        return pl.concat([cat_ard, _rows_to_ard(cont_rows)], how="vertical_relaxed")

    # ------------------------------------------------------------------ #
    # Pre-validation diagnostic                                            #
    # ------------------------------------------------------------------ #

    def check(
        self,
        *,
        groupby: str | None = None,
        spec: DMSummarySpec | None = None,
    ) -> list[str]:
        """Run pre-validation diagnostics without computing.

        Args:
            groupby: Treatment arm column.  ``None`` checks the arm that
                ``t_summary()`` takes without ``groupby``.
            spec: Optional spec to check against.

        Returns:
            list[str]: Diagnostic messages (empty if all checks pass).

        Examples:
            Check data readiness::

                report = adsl.tlg.dm.check()
        """
        spec = spec or DMSummarySpec()
        diagnostics = spec.check(self._df, group_col=groupby)

        available = set(self._df.columns)
        for var in spec.continuous_vars:
            if var not in available:
                diagnostics.append(
                    f"MISSING CONTINUOUS COLUMN: '{var}' (continuous_vars) not present — "
                    "the table stops."
                )
        for field in spec.categorical_vars:
            if field not in available:
                diagnostics.append(
                    f"WARNING: Column '{field}' not present — "
                    f"'{spec.category_labels.get(field, field)}' breakdown will be skipped."
                )
        # ADSL has one record per subject; a duplicate weights the mean.
        group_col = groupby or spec.default_group_col(self._df.columns)
        if {"USUBJID", group_col} <= available:
            dup = self._df.group_by(["USUBJID", group_col]).len().filter(pl.col("len") > 1)
            if dup.height:
                diagnostics.append(
                    f"ERROR: ADSL has {dup.height} duplicate USUBJID + {group_col} "
                    "record(s); the table stops. ADSL has one record per subject."
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
    names: dict[Statistic, tuple[str, str]] = {
        Statistic.N_SUBJECTS: ("n", "n"),
        Statistic.MEAN: ("mean", "Mean"),
        Statistic.SD: ("sd", "SD"),
        Statistic.MEDIAN: ("median", "Median"),
        Statistic.MIN: ("min", "Min"),
        Statistic.MAX: ("max", "Max"),
    }
    name, label = names.get(stat_type, (stat_type.value, stat_type.value))
    clean = values.drop_nulls()
    if stat_type == Statistic.N_SUBJECTS:
        return (name, label, len(clean))
    if len(clean) == 0:
        return (name, label, None)
    if stat_type == Statistic.MEAN:
        return (name, label, clean.mean())
    if stat_type == Statistic.SD:
        return (name, label, clean.std())
    if stat_type == Statistic.MEDIAN:
        return (name, label, clean.median())
    if stat_type == Statistic.MIN:
        return (name, label, clean.min())
    if stat_type == Statistic.MAX:
        return (name, label, clean.max())
    return (name, label, None)
