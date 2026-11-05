"""
ARD (Analysis Results Dataset) builder and pool-expansion utilities.

ARD is the standardised computation layer — a long-format DataFrame with
columns aligned to CDISC ARS / pharmaverse {cards}.

The canonical column order follows {cards}::tidy_ard_column_order():
  group1, group1_level, group2, group2_level,
  variable, variable_level,
  stat_name, stat_label, stat,
  fmt_fn, warning, error, context

Polars adaptation notes vs. R {cards}:
  - {cards} uses list-columns for stat, fmt_fun, warning, error.
    In Polars there are no list-columns, so:
      stat     → Float64 (numeric) or Utf8 (string stats via stat_fmt)
      fmt_fn   → Utf8 format specifier (e.g. "xx.x", "xx.x%", "xx")
      warning  → Utf8 (null when clean)
      error    → Utf8 (null when clean)
"""

from __future__ import annotations

import logging
import math
import warnings
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import polars as pl

from ._specs import (
    NO_CODING_LABEL,
    GroupPool,
    MissingLevel,
    OverallStat,
    Row,
    SchemaError,
    Statistic,
    SummarySpecBase,
    blank_filter_columns,
    resolve_filter,
)

logger = logging.getLogger("fleet")

# ------------------------------------------------------------------ #
# Canonical ARD schema (aligned with {cards})                          #
# ------------------------------------------------------------------ #

#: Required columns — must always be present.
ARD_REQUIRED_COLUMNS = [
    "variable",
    "stat_name",
    "stat_label",
    "stat",
    "fmt_fn",
    "warning",
    "error",
]

#: Optional group columns — present when grouping is used.
ARD_GROUP_COLUMNS = [
    "group1",
    "group1_level",
    "group2",
    "group2_level",
]

#: Full column order matching {cards}::tidy_ard_column_order().
#: ``variable_label`` is a Polars adaptation: R {cards} carries variable
#: display labels as data-frame attributes, which Polars does not have,
#: so the label travels as an ordinary (optional) column instead.
ARD_COLUMN_ORDER = [
    "group1",
    "group1_level",
    "group2",
    "group2_level",
    "variable",
    "variable_level",
    "variable_label",
    "stat_name",
    "stat_label",
    "stat",
    "fmt_fn",
    "stat_fmt",
    "warning",
    "error",
    "context",
]

#: Full schema with data types.
ARD_SCHEMA: dict[str, pl.DataType] = {
    "group1": pl.Utf8,
    "group1_level": pl.Utf8,
    "group2": pl.Utf8,
    "group2_level": pl.Utf8,
    "variable": pl.Utf8,
    "variable_level": pl.Utf8,
    "variable_label": pl.Utf8,
    "stat_name": pl.Utf8,
    "stat_label": pl.Utf8,
    "stat": pl.Float64,
    "fmt_fn": pl.Utf8,
    "stat_fmt": pl.Utf8,
    "warning": pl.Utf8,
    "error": pl.Utf8,
    "context": pl.Utf8,
}

ARD_COLUMNS = list(ARD_SCHEMA.keys())


# ------------------------------------------------------------------ #
# Default format functions (mirroring {cards}::.default_fmt_fun)       #
# ------------------------------------------------------------------ #

#: Default format specifiers per stat_name.
_DEFAULT_FMT: dict[str, str] = {
    "N": "xx",
    "n": "xx",
    "n_events": "xx",
    "pct": "xx.x",
    "mean": "xx.x",
    "sd": "xx.xx",
    "median": "xx.x",
    "min": "xx.x",
    "max": "xx.x",
    "q1": "xx.x",
    "q3": "xx.x",
    "p": "xx.x",
}


def default_fmt_fn(stat_name: str) -> str:
    """Return the default format specifier for a given stat_name.

    Mirrors the logic of ``{cards}::.default_fmt_fun()``:
      - ``"pct"`` → ``"xx.x"``
      - Integer stats (N, n, n_events) → ``"xx"``
      - Other numeric → ``"xx.x"``

    Args:
        stat_name: The statistic identifier.

    Returns:
        str: A format specifier string.
    """
    return _DEFAULT_FMT.get(stat_name, "xx.x")


def _round_half_away(value: float, decimals: int) -> str:
    """Print *value* with *decimals* places, a tie rounded away from zero.

    The value is first read at 15 significant digits, so a binary
    artefact (31.249999999999996 for 31.25) does not break the tie.
    A result that rounds to zero prints without a minus sign.
    """
    if not math.isfinite(value) or abs(value) >= 1e15:
        return f"{value:.{decimals}f}"
    rounded = Decimal(f"{value:.15g}").quantize(
        Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP
    )
    return format(abs(rounded) if rounded.is_zero() else rounded, "f")


def apply_fmt_fn(value: float | None, fmt: str) -> str:
    """Apply a format specifier to a numeric value.

    A tie rounds half away from zero, as SAS ``ROUND`` and the {cards}
    default: 31.25 at ``"xx.x"`` prints ``31.3``, -2.25 prints ``-2.3``.
    A value that rounds to zero prints ``0.0``, never ``-0.0``.

    Supported format patterns:
      - ``"xx"``       → integer (e.g. ``"86"``)
      - ``"xx.x"``     → 1 decimal (e.g. ``"75.2"``)
      - ``"xx.xx"``    → 2 decimals (e.g. ``"8.59"``)
      - ``"xx.xxx"``   → 3 decimals
      - ``"xx.x%"``    → 1 decimal with % suffix

    Args:
        value: The numeric value to format (None → ``""``).
        fmt: The format specifier string.

    Returns:
        str: The formatted string.

    References:
        SAS ROUND function (half away from zero); {cards}
        ``round_type`` default; ADR-0037.

    Examples:
        ``apply_fmt_fn(31.25, "xx.x") == "31.3"``
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""

    # Count decimal places from the "xx.xxx" pattern
    pct_suffix = fmt.endswith("%")
    clean = fmt.rstrip("%")

    if "." in clean:
        decimals = len(clean.split(".")[1])
    else:
        decimals = 0

    formatted = _round_half_away(float(value), decimals)
    if pct_suffix:
        formatted += "%"
    return formatted


def format_ard(ard: pl.DataFrame) -> pl.DataFrame:
    """Apply ``fmt_fn`` to every row and produce a ``stat_fmt`` column.

    This mirrors ``{cards}::apply_fmt_fn()`` — takes the ARD and produces
    human-readable formatted strings from the numeric ``stat`` column.
    A tie rounds half away from zero (SAS ``ROUND``), see
    :func:`apply_fmt_fn`.

    Args:
        ard: An ARD DataFrame with ``stat`` and ``fmt_fn`` columns.

    Returns:
        pl.DataFrame: The ARD with ``stat_fmt`` column populated.
    """
    if "fmt_fn" not in ard.columns or "stat" not in ard.columns:
        return ard

    formatted = []
    stat_vals = ard["stat"].to_list()
    fmt_vals = ard["fmt_fn"].to_list()

    for val, fmt in zip(stat_vals, fmt_vals):
        if fmt is None:
            formatted.append("" if val is None else str(val))
        else:
            formatted.append(apply_fmt_fn(val, fmt))

    return ard.with_columns(pl.Series("stat_fmt", formatted, dtype=pl.Utf8))


# ------------------------------------------------------------------ #
# ARD validation                                                       #
# ------------------------------------------------------------------ #


def validate_ard(df: pl.DataFrame, *, strict: bool = True) -> list[str]:
    """Validate that *df* conforms to the Fleet ARD schema.

    Checks required column presence, data types, and structural integrity.
    Group columns (``group1``, ``group2``, etc.) are optional — matching
    {cards} where not all ARDs have grouping.

    Args:
        df: A DataFrame to validate as ARD.
        strict: When ``True`` (default), columns outside the ARD schema
            are flagged.  Pass ``strict=False`` for post-processing
            workflows (the standard {cards} pattern of annotating an ARD
            with extra columns) — unknown columns are then accepted and
            ignored, while the known columns are still fully checked.

    Returns:
        list[str]: Diagnostic messages (empty if valid).

    Examples:
        Validate an ARD after computation::

            from fleet.tlg._ard import validate_ard

            issues = validate_ard(ard)
            assert issues == [], issues

        Accept a post-processed ARD carrying annotation columns::

            issues = validate_ard(annotated_ard, strict=False)
    """
    issues: list[str] = []

    # Required columns must be present
    missing_required = [c for c in ARD_REQUIRED_COLUMNS if c not in df.columns]
    if missing_required:
        issues.append(f"Missing required ARD columns: {missing_required}")

    # Check for completely unknown columns (strict mode only)
    if strict:
        known = set(ARD_SCHEMA.keys())
        extra = [c for c in df.columns if c not in known]
        if extra:
            issues.append(
                f"Unexpected columns (not in ARD schema): {extra}. "
                "Pass strict=False to accept post-processing columns."
            )

    # Data types (only check columns that exist)
    for col, expected_dtype in ARD_SCHEMA.items():
        if col in df.columns:
            actual = df[col].dtype
            if actual != expected_dtype:
                issues.append(f"Column '{col}': expected {expected_dtype}, got {actual}")

    # Non-empty check
    if len(df) == 0:
        issues.append("ARD is empty (0 rows)")

    return issues


# ------------------------------------------------------------------ #
# ARD row builder                                                      #
# ------------------------------------------------------------------ #


def build_ard_row(
    *,
    group1: str = "",
    group1_level: str = "",
    group2: str = "",
    group2_level: str = "",
    variable: str,
    variable_level: str = "",
    variable_label: str = "",
    stat_name: str,
    stat_label: str,
    stat: float | int | str | None,
    fmt_fn: str | None = None,
    warning: str | None = None,
    error: str | None = None,
    context: str = "",
) -> dict[str, str | float | int | None]:
    """Build a single ARD row as a dict (public API).

    Args:
        group1: Primary grouping variable name (e.g. ``"TRTA"``).
        group1_level: Level within group1 (e.g. ``"Placebo"``).
        group2: Secondary grouping variable name (e.g. ``"SEX"``).
        group2_level: Level within group2 (e.g. ``"F"``).
        variable: Analysis variable name (e.g. ``"AEDECOD"``).
        variable_level: Level of the analysis variable (e.g. ``"HEADACHE"``).
        variable_label: Display label for *variable* (e.g. ``"Preferred
            Term"``); ``""`` when no label applies.
        stat_name: Short stat identifier (e.g. ``"n"``, ``"pct"``).
        stat_label: Human-readable label (e.g. ``"n (%)"``, ``"N"``).
        stat: The computed statistic value.
        fmt_fn: Format specifier (e.g. ``"xx.x"``).  If ``None``,
            ``default_fmt_fn(stat_name)`` is used.
        warning: Warning message from computation (``None`` if clean).
        error: Error message from computation (``None`` if clean).
        context: TLG context identifier (e.g. ``"t_ae_summary"``).

    Returns:
        dict: A single ARD row.
    """
    return {
        "group1": group1,
        "group1_level": group1_level,
        "group2": group2,
        "group2_level": group2_level,
        "variable": variable,
        "variable_level": variable_level,
        "variable_label": variable_label,
        "stat_name": stat_name,
        "stat_label": stat_label,
        "stat": stat,
        "fmt_fn": fmt_fn if fmt_fn is not None else default_fmt_fn(stat_name),
        "stat_fmt": None,
        "warning": warning,
        "error": error,
        "context": context,
    }


# ------------------------------------------------------------------ #
# Pool expansion                                                       #
# ------------------------------------------------------------------ #


def expand_pools(
    df: pl.DataFrame,
    pools: list[GroupPool],
    group_col: str,
    *,
    strict: bool = True,
) -> pl.DataFrame:
    """Expand a DataFrame by stacking pooled treatment groups.

    For each ``GroupPool``, filters *df* to the constituent arms, relabels
    the group column with the pool label, and concatenates onto the
    original DataFrame.

    Args:
        df: The analysis DataFrame.
        pools: Pool definitions to expand.
        group_col: Column containing treatment arm labels.
        strict: When ``True``, a pool referencing arms absent from *df*
            raises.  ``summarize_ard`` passes ``False`` after validating
            pools against the population arm universe, so an arm with
            zero analysis records does not fail the expansion.

    Returns:
        pl.DataFrame: Original rows plus duplicated rows for each pool.

    Raises:
        SchemaError: If *strict* and a pool references arms not present
            in the data.
    """
    if not pools:
        return df

    actual_arms = set(df[group_col].drop_nulls().unique().to_list())
    parts = [df]

    for pool in pools:
        if pool.arms == "*":
            # "*" pools every arm present; a null is not an arm.
            pool_df = df.filter(pl.col(group_col).is_not_null()).with_columns(
                pl.lit(pool.label).alias(group_col)
            )
        else:
            missing = [a for a in pool.arms if a not in actual_arms]
            if missing and strict:
                raise SchemaError(
                    f"Pool '{pool.label}' references arm(s) {missing} but "
                    f"{group_col} contains only {sorted(actual_arms)}"
                )
            pool_df = df.filter(pl.col(group_col).is_in(pool.arms)).with_columns(
                pl.lit(pool.label).alias(group_col)
            )
        parts.append(pool_df)

    return pl.concat(parts, how="vertical_relaxed")


def compute_big_n(
    adsl: pl.DataFrame,
    group_col: str,
    pools: list[GroupPool],
    filter_expr: pl.Expr | None = None,
) -> dict[str, int]:
    """Compute big-N denominators per treatment arm (including pools).

    A subject in the population with a null arm is in no column, as
    PROC FREQ leaves out a missing class level.  The subjects are left
    out of every N, a ``"*"`` pool included, with one ``UserWarning``
    that names the column and the count (ADR-0038).

    Args:
        adsl: The ADSL DataFrame.
        group_col: Treatment arm column.
        pools: Pool definitions to expand.
        filter_expr: Optional filter (e.g. ``SAFFL == "Y"``).

    Returns:
        dict[str, int]: Mapping from arm label to subject count.

    References:
        SAS PROC FREQ, missing class levels; ADR-0038.

    Examples:
        ``compute_big_n(adsl, "TRT01A", [], filter_expr=pl.col("SAFFL") == "Y")``
    """
    df = adsl
    if filter_expr is not None:
        df = df.filter(filter_expr)
    no_arm = df.filter(pl.col(group_col).is_null())
    if no_arm.height:
        ids = no_arm["USUBJID"].unique(maintain_order=True)
        warnings.warn(
            f"{group_col} is null for {ids.len()} subject(s) in the population; "
            f"they are in no column: {ids.head(5).to_list()}. Set a population "
            "filter (adsl_filter) or correct the arm.",
            UserWarning,
            stacklevel=3,
        )
        df = df.filter(pl.col(group_col).is_not_null())
    # Non-strict: pool membership is validated by callers against the
    # unfiltered arm universe; a filter may legitimately empty an arm.
    df = expand_pools(df, pools, group_col, strict=False)
    counts = df.group_by(group_col).agg(pl.col("USUBJID").n_unique().alias("N")).sort(group_col)
    return dict(zip(counts[group_col].to_list(), counts["N"].to_list()))


def restrict_to_population(
    df: pl.DataFrame,
    adsl: pl.DataFrame,
    adsl_filter: Any | None = None,
) -> pl.DataFrame:
    """Keep only the analysis records of subjects in the filtered ADSL.

    The population filter defines the denominator, so it must define the
    numerator too: a record of a subject outside the population would
    count in n but not in N (a percentage above 100 at worst).  The ADaM
    IG population flags (SAFFL, ITTFL) select subjects, and the SAS idiom
    is ``where saffl = 'Y'`` on both ADSL and the analysis dataset
    (ADR-0016).

    Records of subjects in ADSL but outside the filter are dropped with
    an INFO note on the ``fleet`` logger.  Records whose subject is not
    in ADSL at all (or whose ``USUBJID`` is null) are dropped with a
    ``UserWarning``: that is a data issue, not a population choice.

    Args:
        df: The analysis dataset.
        adsl: The population source.
        adsl_filter: The population filter (``pl.Expr`` or string);
            ``None`` keeps every ADSL subject.

    Returns:
        pl.DataFrame: *df* without the records outside the population.

    References:
        ADaM IG v1.3, ADSL subject-level population flags; ADR-0016.

    Examples:
        ``restrict_to_population(adae, adsl, 'pl.col("SAFFL") == "Y"')``
    """
    all_ids = adsl["USUBJID"].drop_nulls().unique()
    filter_expr = resolve_filter(adsl_filter)
    pop_ids = adsl.filter(filter_expr)["USUBJID"] if filter_expr is not None else all_ids
    in_adsl = pl.col("USUBJID").is_in(all_ids.implode())
    in_pop = pl.col("USUBJID").is_in(pop_ids.drop_nulls().unique().implode())

    absent = df.filter(~in_adsl.fill_null(False))
    if absent.height:
        ids = absent["USUBJID"].unique(maintain_order=True)
        warnings.warn(
            f"{ids.len()} subject(s) ({absent.height} record(s)) in the analysis "
            f"dataset are not in ADSL and are left out: {ids.head(5).to_list()}. "
            "Check USUBJID between the datasets.",
            UserWarning,
            stacklevel=3,
        )
    outside = df.filter(in_adsl.fill_null(False) & ~in_pop)
    if outside.height:
        logger.info(
            "NOTE: %d subject(s) (%d record(s)) outside the population "
            "(adsl_filter) are left out of the counts.",
            outside["USUBJID"].n_unique(),
            outside.height,
        )
    return df.filter(in_pop.fill_null(False))


def _quantile_qntldef5(col: pl.Expr, p: float) -> pl.Expr:
    """Quantile by SAS QNTLDEF=5 (PROC UNIVARIATE / PROC MEANS default).

    Sort the non-missing values x(1) <= ... <= x(n).  With n*p = j + g
    (j the integer part): when g > 0 the quantile is x(j+1); when g = 0
    it is the mean of x(j) and x(j+1).  This equals R ``quantile(type =
    2)``.  Polars' own ``quantile`` uses another definition.

    References:
        SAS PROC UNIVARIATE, "Calculating Percentiles", PCTLDEF=5.
    """
    x = col.drop_nulls().sort()
    n = x.len()
    np_ = n.cast(pl.Float64) * p
    j = np_.floor().cast(pl.Int64)
    upper = x.get(j.clip(upper_bound=(n - 1).clip(lower_bound=0)), null_on_oob=True)
    lower = x.get((j - 1).clip(lower_bound=0), null_on_oob=True)
    return (
        pl.when(n == 0)
        .then(None)
        .when(np_ > j)
        .then(upper)
        .otherwise((lower + upper) / 2)
        .cast(pl.Float64)
    )


# ------------------------------------------------------------------ #
# Shared TLG computation helpers                                       #
# ------------------------------------------------------------------ #


def fill_uncoded(
    df: pl.DataFrame,
    columns: Sequence[str],
    label: str = NO_CODING_LABEL,
) -> pl.DataFrame:
    """Fill null coding columns with an explicit level.

    GDSR templates recode missing MedDRA/ATC terms to a visible
    ``"No Coding Available"`` row instead of dropping the records — a
    subject whose only events are uncoded must still be counted.

    Args:
        df: The analysis DataFrame.
        columns: Coding columns to fill; names absent from *df* are skipped.
        label: Replacement level for nulls.

    Returns:
        pl.DataFrame: *df* with nulls in the given columns filled.
    """
    present = [c for c in columns if c in df.columns]
    if not present:
        return df
    return df.with_columns(pl.col(c).fill_null(label) for c in present)


def check_rank_values(
    df: pl.DataFrame,
    order_col: str,
    order: Sequence[str],
    order_field: str,
    unranked: Sequence[str] = (),
) -> None:
    """Raise when a non-blank *order_col* value is not in *order*.

    Ranking an unknown value below every listed value would let a
    sponsor term ("POSSIBLY RELATED") lose against "N" without a sign.

    Args:
        df: The analysis DataFrame.
        order_col: Column holding the ranked value.
        order: Values from least to most severe.
        order_field: Spec field name shown in the message.
        unranked: Values that are allowed and rank as a null does.

    Raises:
        SchemaError: If a non-blank value is not in *order* or *unranked*.

    Examples:
        ``check_rank_values(adae, "AESEV", ["MILD", "MODERATE", "SEVERE"], "severity_order")``
    """
    unknown = (
        df.select(pl.col(order_col).cast(pl.Utf8).alias("__v"))
        .filter(pl.col("__v").str.strip_chars() != "")
        .filter(~pl.col("__v").is_in([*order, *unranked]))
        .unique()
        .sort("__v")["__v"]
        .to_list()
    )
    if unknown:
        raise SchemaError(
            f"{order_col} has values {unknown} that are not in {order_field} "
            f"{list(order)}. Set {order_field} in the spec to the study's "
            "terms, from least to most severe."
        )


def worst_case(
    df: pl.DataFrame,
    *,
    by: Sequence[str],
    order_col: str,
    order: Sequence[str],
    order_field: str = "order",
    unranked: Sequence[str] = (),
) -> pl.DataFrame:
    """Reduce to one record per *by* group, keeping the worst *order_col*.

    Implements the GDSR "counted once at greatest intensity / highest
    grade" rule: within each group the record whose *order_col* value
    ranks highest in *order* survives.  A null or blank value ranks
    below everything (it survives only when the group has no ranked
    value); ties keep the original record order.

    Args:
        df: The analysis DataFrame.
        by: Grouping columns (e.g. ``["USUBJID", "AEBODSYS"]``).
        order_col: Column holding the severity/grade value.
        order: Values from least to most severe (explicit clinical rank —
            never alphabetical).
        order_field: Name of the spec field that holds *order*, shown in
            the error message (e.g. ``"relationship_order"``).
        unranked: Values that rank as a null does (the missing-level
            label, e.g. ``"Missing"``).

    Returns:
        pl.DataFrame: One row per group at the worst level.

    Raises:
        SchemaError: If a non-blank *order_col* value is not in *order*.
            Ranking it below every listed value would let a sponsor term
            ("POSSIBLY RELATED") lose against "N" without a sign.
    """
    rank_map = {value: idx for idx, value in enumerate(order)}
    as_text = pl.col(order_col).cast(pl.Utf8)
    check_rank_values(df, order_col, order, order_field, unranked)
    ranked = df.with_columns(
        as_text.replace_strict(rank_map, default=-1, return_dtype=pl.Int32).alias("__worst_rank")
    )
    return (
        ranked.sort("__worst_rank", descending=True, nulls_last=True, maintain_order=True)
        .unique(subset=list(by), keep="first", maintain_order=True)
        .drop("__worst_rank")
    )


def compute_stat(
    stat_type: Statistic,
    level_df: pl.DataFrame,
    arm_n: int,
    *,
    value_col: str = "AVAL",
    count_values: bool = False,
) -> tuple[str, str, float | int | str | None]:
    """Compute a single statistic for a subset of data.

    Percentages are stored unrounded — display precision belongs
    exclusively to ``fmt_fn`` / ``format_ard`` ({cards} stat/format
    separation), so QC against SAS full-precision values stays possible.

    Args:
        stat_type: The statistic to compute.
        level_df: Filtered DataFrame for this analysis level.
        arm_n: Big-N denominator for the arm.
        value_col: Analysis-value column for continuous statistics.
        count_values: When ``True`` (a continuous summary), ``n`` is the
            count of non-missing *value_col* values, as PROC MEANS N.

    Returns:
        Tuple of (stat_name, stat_label, stat_value).
    """
    if stat_type == Statistic.N_SUBJECTS:
        if count_values and value_col in level_df.columns:
            return ("n", "n", level_df[value_col].count())
        n = level_df["USUBJID"].n_unique() if len(level_df) > 0 else 0
        return ("n", "n", n)
    if stat_type == Statistic.N_EVENTS:
        return ("n_events", "Events", len(level_df))
    if stat_type == Statistic.N_PCT:
        n = level_df["USUBJID"].n_unique() if len(level_df) > 0 else 0
        # No denominator → no percentage; never fabricate 0.0.
        pct = n / arm_n * 100 if arm_n > 0 else None
        return ("pct", "n (%)", pct)
    meta = _CONT_STAT_META.get(stat_type)
    if meta is None:
        return (stat_type.value, stat_type.value, None)
    if value_col not in level_df.columns or len(level_df) == 0:
        return (*meta, None)
    values = level_df[value_col]
    if stat_type == Statistic.MEAN:
        return (*meta, values.mean())
    if stat_type == Statistic.SD:
        return (*meta, values.std())
    if stat_type == Statistic.MEDIAN:
        return (*meta, values.median())
    if stat_type == Statistic.MIN:
        return (*meta, values.min())
    if stat_type == Statistic.MAX:
        return (*meta, values.max())
    p = 0.25 if stat_type == Statistic.Q1 else 0.75
    return (*meta, level_df.select(_quantile_qntldef5(pl.col(value_col), p)).item())


def ard_row(
    group1: str,
    group1_level: str,
    variable: str,
    variable_level: str,
    stat_name: str,
    stat_label: str,
    stat: float | int | str | None,
    context: str,
    *,
    group2: str = "",
    group2_level: str = "",
    variable_label: str = "",
    fmt_fn: str | None = None,
    warning: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Build a single ARD row dict (the {cards} long layout).

    Args:
        group1: Primary grouping variable name.
        group1_level: Level within group1.
        variable: Analysis variable name.
        variable_level: Level of the analysis variable.
        stat_name: Short stat identifier.
        stat_label: Human-readable label.
        stat: The computed statistic value.
        context: TLG context identifier.
        group2: Secondary grouping variable name.
        group2_level: Level within group2.
        variable_label: Display label for *variable* (``""`` when none).
        fmt_fn: Format specifier; uses default if None.
        warning: Warning message from computation.
        error: Error message from computation.

    Returns:
        dict: A single ARD row.
    """
    return {
        "group1": group1,
        "group1_level": group1_level,
        "group2": group2,
        "group2_level": group2_level,
        "variable": variable,
        "variable_level": variable_level,
        "variable_label": variable_label,
        "stat_name": stat_name,
        "stat_label": stat_label,
        "stat": stat,
        "fmt_fn": fmt_fn if fmt_fn is not None else default_fmt_fn(stat_name),
        "stat_fmt": None,
        "warning": warning,
        "error": error,
        "context": context,
    }


def rows_to_ard(rows: list[dict[str, Any]]) -> pl.DataFrame:
    """Convert a list of ARD row dicts to a Polars DataFrame in the {cards} long layout.

    The ARD ``stat`` column is Float64.  A value that cannot be coerced
    to a float raises instead of being silently nulled — a nulled
    statistic would render as an innocent blank cell.

    Args:
        rows: List of dicts (from ``ard_row()``).

    Returns:
        pl.DataFrame: Formatted ARD DataFrame.

    Raises:
        SchemaError: If any row carries a non-numeric ``stat`` value.
    """
    if not rows:
        return pl.DataFrame(schema=ARD_SCHEMA)

    for row in rows:
        v = row["stat"]
        if v is None:
            row["stat"] = None
        elif isinstance(v, (int, float)):
            row["stat"] = float(v)
        else:
            try:
                row["stat"] = float(v)
            except (TypeError, ValueError):
                raise SchemaError(
                    f"Non-numeric stat value {v!r} for stat "
                    f"{row.get('stat_name')!r} (variable "
                    f"{row.get('variable')!r}, level "
                    f"{row.get('variable_level')!r}): the ARD stat column "
                    "is Float64. Convert the value or carry string "
                    "statistics through stat_fmt instead."
                ) from None

    df = pl.DataFrame(rows).cast({"stat": pl.Float64}, strict=False)

    for col in ("warning", "error", "stat_fmt"):
        if col in df.columns and df[col].dtype == pl.Null:
            df = df.with_columns(pl.lit(None, dtype=pl.Utf8).alias(col))

    df = format_ard(df)

    return df


#: Count-type statistics — meaningful at every hierarchy depth.
COUNT_STATS = frozenset({Statistic.N_SUBJECTS, Statistic.N_EVENTS, Statistic.N_PCT})

#: Continuous statistics: (stat_name, stat_label) per Statistic.
_CONT_STAT_META: dict[Statistic, tuple[str, str]] = {
    Statistic.MEAN: ("mean", "Mean"),
    Statistic.SD: ("sd", "SD"),
    Statistic.MEDIAN: ("median", "Median"),
    Statistic.MIN: ("min", "Min"),
    Statistic.MAX: ("max", "Max"),
    Statistic.Q1: ("q1", "Q1"),
    Statistic.Q3: ("q3", "Q3"),
}


def _cont_stat_exprs(value_col: str) -> dict[Statistic, pl.Expr]:
    """Aggregation expressions for continuous statistics on *value_col*."""
    col = pl.col(value_col)
    return {
        Statistic.MEAN: col.mean(),
        Statistic.SD: col.std(),
        Statistic.MEDIAN: col.median(),
        Statistic.MIN: col.min(),
        Statistic.MAX: col.max(),
        Statistic.Q1: _quantile_qntldef5(col, 0.25),
        Statistic.Q3: _quantile_qntldef5(col, 0.75),
    }


def _validate_pool_arms(
    pools: list[GroupPool],
    valid_arms: set[str],
    group_col: str,
    source: str,
) -> None:
    """Raise if any pool references an arm outside *valid_arms*."""
    for pool in pools:
        if pool.arms == "*":
            continue
        missing = [a for a in pool.arms if a not in valid_arms]
        if missing:
            raise SchemaError(
                f"Pool '{pool.label}' references arm(s) {missing} not present "
                f"in {source} ({group_col} values: {sorted(valid_arms)})"
            )


def _cell_stat(
    stat_type: Statistic,
    cell: dict[str, Any] | None,
    arm_n: int,
    has_value_col: bool,
) -> tuple[str, str, float | int | None]:
    """Extract one statistic from an aggregated cell (``None`` = zero cell).

    Percentages are stored unrounded — display precision belongs
    exclusively to ``fmt_fn`` / ``format_ard``.
    """
    if stat_type == Statistic.N_SUBJECTS:
        return ("n", "n", cell["__n"] if cell else 0)
    if stat_type == Statistic.N_EVENTS:
        return ("n_events", "Events", cell["__n_events"] if cell else 0)
    if stat_type == Statistic.N_PCT:
        n = cell["__n"] if cell else 0
        # No denominator → no percentage; never fabricate 0.0.
        return ("pct", "n (%)", n / arm_n * 100 if arm_n > 0 else None)
    meta = _CONT_STAT_META.get(stat_type)
    if meta is None:
        return (stat_type.value, stat_type.value, None)
    value = cell.get(f"__{stat_type.value}") if (cell is not None and has_value_col) else None
    return (*meta, value)


def _level_rows(
    frame: pl.DataFrame,
    fields: list[str],
    stats: list[Statistic],
    arms: list[str],
    big_n: dict[str, int],
    group_col: str,
    context: str,
    *,
    value_col: str = "AVAL",
    field_labels: dict[str, str] | None = None,
    fmt_overrides: dict[str, str] | None = None,
    count_values: bool = False,
    missing_label: str | None = None,
) -> list[dict[str, Any]]:
    """Stats per arm × level combination of *fields*, with explicit zero cells.

    Levels are enumerated globally (across all arms) from *frame*, so an
    arm without records at a level gets n=0 / pct=0 / null continuous
    rows instead of silently missing.  For two or more fields the last
    field is the ``variable`` and its immediate parent goes to
    ``group2`` / ``group2_level``.

    With *count_values* (a continuous summary) ``n`` follows PROC MEANS:
    at a level with continuous statistics it is the count of non-missing
    *value_col* values; at a parent level it is the count of subjects
    with a non-missing value.  A level equal to *missing_label* sorts
    last within its parent.
    """
    # Deduplicate for select/group_by: a row field may repeat or equal
    # group_col (e.g. a per-arm breakdown) — the lookup tuples below are
    # built from named rows, so duplicates stay consistent either way.
    select_fields = list(dict.fromkeys(fields))
    sort_keys: list[Any] = list(select_fields)
    if missing_label is not None:
        sort_keys = [
            key
            for f in select_fields
            for key in (pl.col(f).cast(pl.Utf8).eq_missing(missing_label), pl.col(f))
        ]
    combos = frame.select(select_fields).drop_nulls().unique().sort(sort_keys)
    if combos.height == 0:
        return []

    fmt_overrides = fmt_overrides or {}
    has_value_col = value_col in frame.columns
    n_expr = pl.col("USUBJID").n_unique()
    if count_values and has_value_col:
        if any(s in _CONT_STAT_META for s in stats):
            n_expr = pl.col(value_col).count()
        else:
            n_expr = pl.col("USUBJID").filter(pl.col(value_col).is_not_null()).n_unique()
    aggs = [n_expr.alias("__n"), pl.len().alias("__n_events")]
    if has_value_col:
        cont_exprs = _cont_stat_exprs(value_col)
        aggs += [cont_exprs[s].alias(f"__{s.value}") for s in stats if s in cont_exprs]
    group_keys = list(dict.fromkeys([group_col, *fields]))
    grouped = frame.drop_nulls(subset=select_fields).group_by(group_keys).agg(aggs)
    cells = {
        (row[group_col], *(row[f] for f in fields)): row for row in grouped.iter_rows(named=True)
    }

    variable = fields[-1]
    variable_label = (field_labels or {}).get(variable, "")
    parent = fields[-2] if len(fields) >= 2 else None
    out: list[dict[str, Any]] = []
    combo_list = combos.to_dicts()
    for arm in arms:
        arm_n = big_n.get(arm, 0)
        for combo in combo_list:
            cell = cells.get((arm, *(combo[f] for f in fields)))
            for stat_type in stats:
                sn, sl, sv = _cell_stat(stat_type, cell, arm_n, has_value_col)
                out.append(
                    ard_row(
                        group_col,
                        arm,
                        variable,
                        str(combo[variable]),
                        sn,
                        sl,
                        sv,
                        context,
                        group2=parent or "",
                        group2_level=str(combo[parent]) if parent else "",
                        variable_label=variable_label,
                        fmt_fn=fmt_overrides.get(sn),
                    )
                )
    return out


def _apply_missing(
    df: pl.DataFrame, missing: MissingLevel | None
) -> tuple[pl.DataFrame, dict[str, str]]:
    """Give a null or blank category value the missing level.

    Returns the frame and, for ``label=None``, one warning text per
    column that holds a null (the count of subjects); each text is also
    raised once as a ``UserWarning``.
    """
    notes: dict[str, str] = {}
    if missing is None:
        return df, notes
    for column in missing.columns:
        if column not in df.columns:
            continue
        as_text = pl.col(column).cast(pl.Utf8)
        is_missing = as_text.is_null() | (as_text.str.strip_chars() == "")
        hit = df.filter(is_missing)
        if hit.height == 0:
            continue
        if missing.label is not None:
            df = df.with_columns(
                pl.when(is_missing).then(pl.lit(missing.label)).otherwise(as_text).alias(column)
            )
            continue
        note = (
            f"{column} is null or blank for {hit['USUBJID'].n_unique()} subject(s); "
            f"they are in no {column} row."
        )
        warnings.warn(note, UserWarning, stacklevel=3)
        notes[column] = note
    return df, notes


def _adsl_arm_error(adsl_col: str, adsl: pl.DataFrame, explicit: bool) -> str:
    """Message for an arm column that ADSL does not hold."""
    candidates = [
        c
        for c in adsl.columns
        if c in ("TRTA", "TRTP", "ARM", "ACTARM")
        or (len(c) == 6 and c.startswith("TRT") and c[3:5].isdigit() and c[5] in "AP")
    ]
    source = "adsl_group_col" if explicit else "The group column"
    hint = (
        ""
        if explicit
        else (
            " ADaM puts the actual arm on ADSL as TRTxxA: name the ADSL arm with "
            "adsl_group_col (YAML adsl_group_col:, builder population(adsl, "
            "group_col=...), CLI --adsl-groupby"
            + (f" {candidates[0]}" if candidates else " <column>")
            + ")."
        )
    )
    return (
        f"{source} '{adsl_col}' not found in adsl.{hint} "
        f"ADSL arm columns found: {candidates}. Available: {sorted(adsl.columns)}"
    )


def summarize_ard(
    df: pl.DataFrame,
    *,
    rows: Sequence[str | Row],
    stats: list[Statistic],
    context: str,
    group_col: str = "TRTA",
    pools: list[GroupPool] | None = None,
    column_order: list[str] | None = None,
    adsl: pl.DataFrame | None = None,
    adsl_filter: Any | None = None,
    dataset_filter: Any | None = None,
    prefilter: Any | None = None,
    header_rows: list[OverallStat] | None = None,
    nested: bool = False,
    value_col: str = "AVAL",
    label_col: str | None = None,
    decimals: dict[str, str] | None = None,
    missing: MissingLevel | None = None,
    leaf_rank: tuple[Sequence[str], str] | None = None,
    adsl_group_col: str | None = None,
) -> pl.DataFrame:
    """Build an ARD in the {cards} long layout: the single shared TLG engine.

    The layout follows {cards}, but the names differ: ``fmt_fn`` (not
    ``fmt_fun``), ``pct`` on 0 to 100 (not ``p`` on 0 to 1), and big-N
    rows with ``variable=""``.  Convert the ARD before you give it to R
    tools such as gtsummary.

    Every summary table (categorical counts and continuous statistics)
    goes through this function: big-N rows, header rows (``OverallStat``),
    then stats per arm × row level, with explicit zero cells.

    Denominator rules (loud, never silently wrong):
      - Percentages (``n_pct``) require *adsl*; omitting it raises.
      - The arm universe comes from *adsl* when given — an arm with zero
        analysis records keeps its column (N row + zero cells) instead of
        vanishing, and an arm in the data but absent from ADSL raises.
      - Without *adsl* no big-N rows are emitted (there is no population).

    Args:
        df: Analysis dataset.
        rows: Row fields — names or ``Row`` objects (honouring
            ``Row.filter_value``), e.g. ``["AEBODSYS", "AEDECOD"]``.
        stats: Statistics computed per arm × level.
        context: ARD context tag written to every row.
        group_col: Treatment-arm column.
        pools: Composite arms; ``None`` for none.
        column_order: Explicit arm ordering; remaining arms keep sort order.
        adsl: Population source for big-N denominators and the arm
            universe.  Analysis records of subjects outside the filtered
            ADSL are left out of every count (ADR-0016).
        adsl_filter: Population filter (``pl.Expr`` or expression
            string).  It selects the ADSL subjects for N and, through
            them, the analysis records for n.  Requires *adsl*.
        dataset_filter: Filter applied to *df* before counting
            (``pl.Expr`` or expression string).
        prefilter: Extra *df* filter (e.g. ``DTHFL == "Y"``).
        header_rows: ``OverallStat`` aggregate rows emitted above the
            hierarchy (``variable=""``, ``variable_level=label``).
        nested: When ``True``, *rows* is a hierarchy: count statistics
            are emitted at every depth and continuous statistics only at
            the deepest level, computed per level *combination* (e.g.
            PT-within-SOC, visit-within-parameter) with the parent level
            in ``group2`` / ``group2_level``.  When ``False`` each field
            is summarized as an independent flat breakdown.
        value_col: Analysis-value column for continuous statistics
            (default ``"AVAL"``).  Point at ``CHG``/``PCHG``/``BASE`` to
            summarize those without pre-renaming.  Missing while
            continuous statistics are requested raises.
        label_col: Column holding display labels for the first row
            field's values (e.g. ``"PARAM"`` for ``"PARAMCD"`` stubs).
            The mapped label replaces the raw value in
            ``variable_level`` / ``group2_level``.
        decimals: Per-statistic format overrides — ARD ``stat_name``
            (e.g. ``"mean"``) to format string (e.g. ``"xx.xx"``).
            ``Row.decimals`` overrides again for that row's leaf level.
        missing: The missing-level rule.  A null or blank value of its
            columns is counted under ``missing.label``, last in the
            block; with ``label=None`` the count goes to the ARD
            ``warning`` column (ADR-0038).
        leaf_rank: ``(order, order_field)`` of a worst-case table.  At
            the last depth of a nested hierarchy each subject is counted
            once, at the worst value of the last row field, within its
            arm (pools included) and its parent levels.  Parent levels
            and header rows count every record; no ``n_events`` is
            emitted at the reduced level.
        adsl_group_col: Arm column of *adsl* when it differs from
            *group_col* (an ADAE with ``TRTA``, an ADSL with
            ``TRT01A``).  The arm values must match.

    Returns:
        pl.DataFrame: Validated ARD in the {cards} long layout.

    Raises:
        SchemaError: On missing group column, missing percentage
            denominator, missing or non-numeric *value_col* with
            continuous statistics requested, missing *label_col*, a row
            field absent from *df*, unknown arms/pools, or ARD schema
            violations.

    References:
        ADaMIG v1.3 (TRTxxA on ADSL, TRTA on OCCDS/BDS); FDA CDER
        Standard Safety Tables and Figures IG v2.0, 2.1.2 (missing row);
        ADR-0038.

    Examples:
        ``summarize_ard(adae, rows=["AEBODSYS", "AEDECOD"], stats=[Statistic.N_PCT],
        context="t_ae", adsl=adsl, adsl_group_col="TRT01A")``
    """
    pools = pools or []
    header_rows = header_rows or []
    row_defs = [r if isinstance(r, Row) else Row(field=r) for r in rows]

    if group_col not in df.columns:
        raise SchemaError(
            f"Group column '{group_col}' not found in the analysis dataset. "
            f"Available: {sorted(df.columns)}"
        )
    absent_rows = [r.field for r in row_defs if r.field not in df.columns]
    if absent_rows:
        raise SchemaError(
            f"Row field(s) {absent_rows} are not in the analysis dataset. "
            f"Available: {sorted(df.columns)}"
        )

    dataset_filter_expr = resolve_filter(dataset_filter)
    if dataset_filter_expr is not None:
        df = df.filter(dataset_filter_expr)
    if prefilter is not None:
        df = df.filter(prefilter)
    if leaf_rank is not None and row_defs:
        check_rank_values(
            df,
            row_defs[-1].field,
            leaf_rank[0],
            leaf_rank[1],
            [missing.label] if missing is not None and missing.label else (),
        )
    if adsl is not None:
        if "USUBJID" not in adsl.columns:
            raise SchemaError(f"adsl has no USUBJID column. Available: {sorted(adsl.columns)}")
        df = restrict_to_population(df, adsl, adsl_filter)
    elif adsl_filter is not None:
        raise SchemaError(
            "adsl_filter is set but no adsl was given. The population filter "
            "selects ADSL subjects, so it cannot apply without ADSL: pass "
            "adsl=..., or filter the analysis dataset with dataset_filter."
        )

    pct_requested = Statistic.N_PCT in stats or any(
        Statistic.N_PCT in (hdr.statistics or stats) for hdr in header_rows
    )
    if pct_requested and adsl is None:
        raise SchemaError(
            "Percentage statistics (n_pct) require an ADSL population for "
            "the denominator — pass adsl=... . A percentage computed "
            "without a population denominator would be silently wrong."
        )

    cont_requested = sorted(
        {
            s.value
            for s in [*stats, *(s for hdr in header_rows for s in (hdr.statistics or stats))]
            if s in _CONT_STAT_META
        }
    )
    if cont_requested and value_col not in df.columns:
        raise SchemaError(
            f"Continuous statistics {cont_requested} require the value "
            f"column '{value_col}', which is not in the analysis dataset. "
            f"Available: {sorted(df.columns)}. Pass value_col=... to point "
            "at the analysis value (e.g. CHG), or drop the continuous "
            "statistics."
        )
    if cont_requested and not df[value_col].dtype.is_numeric():
        raise SchemaError(
            f"Continuous statistics {cont_requested} need a numeric {value_col}; "
            f"{value_col} is {df[value_col].dtype}. Cast it: "
            f"pl.col('{value_col}').cast(pl.Float64)"
        )
    if label_col is not None and label_col not in df.columns:
        raise SchemaError(
            f"label_col '{label_col}' not found in the analysis dataset. "
            f"Available: {sorted(df.columns)}"
        )

    data_arms = set(df[group_col].drop_nulls().unique().to_list())
    if adsl is not None:
        adsl_col = adsl_group_col or group_col
        if adsl_col not in adsl.columns:
            raise SchemaError(_adsl_arm_error(adsl_col, adsl, adsl_group_col is not None))
        adsl_arms = set(adsl[adsl_col].drop_nulls().unique().to_list())
        _validate_pool_arms(pools, adsl_arms, adsl_col, source="adsl")
        big_n = compute_big_n(adsl, adsl_col, pools, filter_expr=resolve_filter(adsl_filter))
        unknown = sorted(a for a in data_arms if a not in big_n)
        if unknown:
            raise SchemaError(
                f"Arm(s) {unknown} in the analysis dataset have no denominator "
                f"in ADSL (after adsl_filter). Align {group_col} between the "
                "datasets or filter the analysis dataset to the population."
            )
        # An arm or pool emptied by adsl_filter keeps its column with N=0
        # (and null percentages) rather than silently vanishing.
        universe = set(big_n) | adsl_arms | {p.label for p in pools}
        big_n = {arm: big_n.get(arm, 0) for arm in universe}
        arms = sorted(universe)
    else:
        big_n = {}
        _validate_pool_arms(pools, data_arms, group_col, source="the analysis dataset")
        arms = sorted(data_arms | {p.label for p in pools})

    df, missing_notes = _apply_missing(df, missing)
    missing_label = missing.label if missing is not None else None
    df = expand_pools(df, pools, group_col, strict=False)

    if column_order:
        arms = [a for a in column_order if a in arms] + [a for a in arms if a not in column_order]

    ard_rows: list[dict[str, Any]] = []
    table_fmt = decimals or {}

    # Big-N rows exist only when a population is given.
    if adsl is not None:
        ard_rows += [
            ard_row(
                group_col,
                arm,
                "",
                "",
                "N",
                "N",
                big_n.get(arm),
                context,
                fmt_fn=table_fmt.get("N"),
            )
            for arm in arms
        ]

    # Header rows (OverallStat) — whole-dataset aggregates above the hierarchy.
    for hdr in header_rows:
        hdr_df = df
        hdr_filter = resolve_filter(hdr.filter)
        hdr_warning = None
        if hdr_filter is not None:
            blank = blank_filter_columns(hdr_filter, hdr_df)
            if blank:
                hdr_warning = (
                    f"filter column {', '.join(blank)} is null or blank on every "
                    f"record (row '{hdr.label}')"
                )
                warnings.warn(hdr_warning, UserWarning, stacklevel=2)
            hdr_df = hdr_df.filter(hdr_filter)
        effective_stats = hdr.statistics or stats
        hdr_values = value_col in hdr_df.columns and any(
            s in _CONT_STAT_META for s in effective_stats
        )
        for arm in arms:
            arm_hdr = hdr_df.filter(pl.col(group_col) == arm)
            arm_n = big_n.get(arm, 0)
            for stat_type in effective_stats:
                sn, sl, sv = compute_stat(
                    stat_type, arm_hdr, arm_n, value_col=value_col, count_values=hdr_values
                )
                ard_rows.append(
                    ard_row(
                        group_col,
                        arm,
                        "",
                        hdr.label,
                        sn,
                        sl,
                        sv,
                        context,
                        fmt_fn=table_fmt.get(sn),
                        warning=hdr_warning,
                    )
                )

    present = row_defs
    field_labels = {r.field: (r.label or "") for r in row_defs}
    if nested:
        fields = [r.field for r in present]
        if len(fields) > 2:
            raise SchemaError(
                f"Nested row hierarchies support at most 2 levels — the ARD "
                f"schema carries one parent (group2/group2_level) per row, so "
                f"deeper lineages would emit indistinguishable duplicate rows. "
                f"Got {fields}. Reduce the hierarchy or pass nested=False."
            )
        for depth in range(len(fields)):
            is_leaf = depth == len(fields) - 1
            depth_stats = stats if is_leaf else [s for s in stats if s in COUNT_STATS]
            if is_leaf and leaf_rank is not None:
                # One reduced record per subject: an event count means nothing here.
                depth_stats = [s for s in depth_stats if s != Statistic.N_EVENTS]
            if not depth_stats:
                continue
            # A row's filter_value scopes that row's own depth and its
            # descendants — never its ancestors' counts.
            frame = df
            for row_def in present[:depth]:
                if row_def.filter_value is not None:
                    frame = frame.filter(pl.col(row_def.field) == row_def.filter_value)
            if is_leaf and leaf_rank is not None:
                order, order_field = leaf_rank
                frame = worst_case(
                    frame,
                    by=["USUBJID", group_col, *fields[:-1]],
                    order_col=fields[-1],
                    order=order,
                    order_field=order_field,
                    unranked=[missing_label] if missing_label else (),
                )
            if present[depth].filter_value is not None:
                frame = frame.filter(pl.col(fields[depth]) == present[depth].filter_value)
            ard_rows += _level_rows(
                frame,
                fields[: depth + 1],
                depth_stats,
                arms,
                big_n,
                group_col,
                context,
                value_col=value_col,
                field_labels=field_labels,
                fmt_overrides={**table_fmt, **(present[depth].decimals or {})},
                count_values=bool(cont_requested),
                missing_label=missing_label,
            )
    else:
        for row_def in present:
            frame = df
            if row_def.filter_value is not None:
                frame = frame.filter(pl.col(row_def.field) == row_def.filter_value)
            ard_rows += _level_rows(
                frame,
                [row_def.field],
                stats,
                arms,
                big_n,
                group_col,
                context,
                value_col=value_col,
                field_labels=field_labels,
                fmt_overrides={**table_fmt, **(row_def.decimals or {})},
                count_values=bool(cont_requested),
                missing_label=missing_label,
            )

    ard = rows_to_ard(ard_rows)
    for column, note in missing_notes.items():
        ard = ard.with_columns(
            pl.when(pl.col("variable") == column)
            .then(pl.lit(note))
            .otherwise(pl.col("warning"))
            .alias("warning")
        )
    if label_col is not None and present:
        ard = _apply_label_col(ard, df, present[0].field, label_col)
    issues = validate_ard(ard)
    if issues:
        raise SchemaError("ARD output failed schema validation:\n  " + "\n  ".join(issues))
    return ard


def prepare_frame(df: pl.DataFrame, spec: SummarySpecBase) -> pl.DataFrame:
    """Apply a summary spec's record rules to the analysis dataset, in order.

    The order is fixed and shared by every summary table: the uncoded
    rule first (so a dataset filter may name the uncoded label), then
    the dataset filter, then the template's prefilter.  The seam
    (:func:`summarize_spec`) calls it; a composite table that does its
    own work between the filter and the engine calls it first and then
    passes no ``dataset_filter`` to :func:`summarize_ard`.

    Args:
        df: The analysis dataset.
        spec: A summary spec carrying ``uncoded``, ``dataset_filter``
            and ``prefilter``.

    Returns:
        pl.DataFrame: *df* with the three rules applied.

    Examples:
        A composite table prepares its frame, then does its own work::

            df = prepare_frame(adae, spec)
            df = worst_case(df, by=["USUBJID", "TRTA", "AEBODSYS"], order_col="AESEV")
    """
    if spec.uncoded is not None:
        df = fill_uncoded(df, spec.uncoded.columns, spec.uncoded.label)
    dataset_filter = resolve_filter(spec.dataset_filter)
    if dataset_filter is not None:
        df = df.filter(dataset_filter)
    prefilter = resolve_filter(spec.prefilter)
    if prefilter is not None:
        df = df.filter(prefilter)
    return df


def summarize_spec(
    df: pl.DataFrame,
    spec: SummarySpecBase,
    *,
    groupby: str | None = None,
    adsl: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Build a summary ARD from a spec — the seam every forwarding table uses.

    The spec is the whole engine contract: every :func:`summarize_ard`
    argument is read from its fields, and the cards ``context`` tag and
    the ``nested`` flag from its class.  The group column is *groupby*,
    else :meth:`SummarySpecBase.default_group_col` (the spec's first
    column, or the first ``arm_fallback`` column in the data); the frame is
    validated against the spec, then prepared by :func:`prepare_frame`.

    Args:
        df: The analysis dataset.
        spec: A summary spec (any :class:`SummarySpecBase` subclass).
        groupby: Treatment-arm column; overrides ``spec.columns[0]``.
        adsl: ADSL for big-N denominators and the arm universe.

    Returns:
        pl.DataFrame: Validated ARD in the {cards} long layout.

    Raises:
        SchemaError: If the frame fails the spec's validation, or on any
            engine refusal (see :func:`summarize_ard`).

    Examples:
        ``ard = summarize_spec(admh, MHSummarySpec(adsl_group_col="TRT01A"), adsl=adsl)``
    """
    group_col = groupby or spec.default_group_col(df.columns)
    spec.validate_dataframe(df, group_col=group_col)
    return summarize_ard(
        prepare_frame(df, spec),
        rows=spec.rows,
        stats=spec.statistics,
        context=spec.context,
        group_col=group_col,
        pools=spec.pools,
        column_order=spec.column_order,
        adsl=adsl,
        adsl_filter=spec.adsl_filter,
        header_rows=spec.header_rows,
        nested=spec.nested,
        value_col=spec.value_col,
        label_col=spec.label_col,
        decimals=spec.decimals,
        missing=spec.missing,
        leaf_rank=spec.leaf_rank(),
        adsl_group_col=spec.adsl_group_col,
    )


def _apply_label_col(
    ard: pl.DataFrame,
    df: pl.DataFrame,
    field: str,
    label_col: str,
) -> pl.DataFrame:
    """Replace *field*'s coded levels with display labels from *label_col*.

    Applied to ``variable_level`` (where the field is the variable) and
    ``group2_level`` (where it is the parent).  Codes without a label
    pass through unchanged.
    """
    pairs = (
        df.select(pl.col(field).cast(pl.Utf8), pl.col(label_col).cast(pl.Utf8))
        .drop_nulls()
        .unique(subset=[field], keep="first", maintain_order=True)
    )
    mapping = dict(zip(pairs[field].to_list(), pairs[label_col].to_list()))
    if not mapping:
        return ard
    return ard.with_columns(
        pl.when(pl.col("variable") == field)
        .then(pl.col("variable_level").replace(mapping))
        .otherwise(pl.col("variable_level"))
        .alias("variable_level"),
        pl.when(pl.col("group2") == field)
        .then(pl.col("group2_level").replace(mapping))
        .otherwise(pl.col("group2_level"))
        .alias("group2_level"),
    )
