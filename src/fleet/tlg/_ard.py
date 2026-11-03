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

import math
from collections.abc import Sequence
from typing import Any

import polars as pl

from ._specs import (
    NO_CODING_LABEL,
    GroupPool,
    OverallStat,
    Row,
    SchemaError,
    Statistic,
    SummarySpecBase,
    resolve_filter,
)

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


def apply_fmt_fn(value: float | None, fmt: str) -> str:
    """Apply a format specifier to a numeric value.

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

    formatted = f"{value:.{decimals}f}"
    if pct_suffix:
        formatted += "%"
    return formatted


def format_ard(ard: pl.DataFrame) -> pl.DataFrame:
    """Apply ``fmt_fn`` to every row and produce a ``stat_fmt`` column.

    This mirrors ``{cards}::apply_fmt_fn()`` — takes the ARD and produces
    human-readable formatted strings from the numeric ``stat`` column.

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
    """Validate that *df* conforms to the {cards}-compatible ARD schema.

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
            pool_df = df.with_columns(pl.lit(pool.label).alias(group_col))
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

    Args:
        adsl: The ADSL DataFrame.
        group_col: Treatment arm column.
        pools: Pool definitions to expand.
        filter_expr: Optional filter (e.g. ``SAFFL == "Y"``).

    Returns:
        dict[str, int]: Mapping from arm label to subject count.
    """
    df = adsl
    if filter_expr is not None:
        df = df.filter(filter_expr)
    # Non-strict: pool membership is validated by callers against the
    # unfiltered arm universe; a filter may legitimately empty an arm.
    df = expand_pools(df, pools, group_col, strict=False)
    counts = df.group_by(group_col).agg(pl.col("USUBJID").n_unique().alias("N")).sort(group_col)
    return dict(zip(counts[group_col].to_list(), counts["N"].to_list()))


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


def worst_case(
    df: pl.DataFrame,
    *,
    by: Sequence[str],
    order_col: str,
    order: Sequence[str],
) -> pl.DataFrame:
    """Reduce to one record per *by* group, keeping the worst *order_col*.

    Implements the GDSR "counted once at greatest intensity / highest
    grade" rule: within each group the record whose *order_col* value
    ranks highest in *order* survives.  Values not present in *order*
    rank below everything (they survive only when the group has no
    ranked value); ties break deterministically on *order_col* then the
    original sort.

    Args:
        df: The analysis DataFrame.
        by: Grouping columns (e.g. ``["USUBJID", "AEBODSYS"]``).
        order_col: Column holding the severity/grade value.
        order: Values from least to most severe (explicit clinical rank —
            never alphabetical).

    Returns:
        pl.DataFrame: One row per group at the worst level.
    """
    rank_map = {value: idx for idx, value in enumerate(order)}
    ranked = df.with_columns(
        pl.col(order_col)
        .cast(pl.Utf8)
        .replace_strict(rank_map, default=-1, return_dtype=pl.Int32)
        .alias("__worst_rank")
    )
    return (
        ranked.sort(["__worst_rank", order_col], descending=[True, False], nulls_last=True)
        .unique(subset=list(by), keep="first", maintain_order=True)
        .drop("__worst_rank")
    )


def compute_stat(
    stat_type: Statistic,
    level_df: pl.DataFrame,
    arm_n: int,
    *,
    value_col: str = "AVAL",
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

    Returns:
        Tuple of (stat_name, stat_label, stat_value).
    """
    if stat_type == Statistic.N_SUBJECTS:
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
    if stat_type == Statistic.Q1:
        return (*meta, values.quantile(0.25))
    return (*meta, values.quantile(0.75))


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
    """Build a single ARD row dict ({cards}-compatible).

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
    """Convert a list of ARD row dicts to a {cards}-compatible Polars DataFrame.

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
        Statistic.Q1: col.quantile(0.25),
        Statistic.Q3: col.quantile(0.75),
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
) -> list[dict[str, Any]]:
    """Stats per arm × level combination of *fields*, with explicit zero cells.

    Levels are enumerated globally (across all arms) from *frame*, so an
    arm without records at a level gets n=0 / pct=0 / null continuous
    rows instead of silently missing.  For two or more fields the last
    field is the ``variable`` and its immediate parent goes to
    ``group2`` / ``group2_level``.
    """
    # Deduplicate for select/group_by: a row field may repeat or equal
    # group_col (e.g. a per-arm breakdown) — the lookup tuples below are
    # built from named rows, so duplicates stay consistent either way.
    select_fields = list(dict.fromkeys(fields))
    combos = frame.select(select_fields).drop_nulls().unique().sort(select_fields)
    if combos.height == 0:
        return []

    fmt_overrides = fmt_overrides or {}
    has_value_col = value_col in frame.columns
    aggs = [pl.col("USUBJID").n_unique().alias("__n"), pl.len().alias("__n_events")]
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
) -> pl.DataFrame:
    """Build a {cards}-compatible ARD — the single shared TLG engine.

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
        adsl: Population source for big-N denominators and the arm universe.
        adsl_filter: Filter applied to *adsl* before counting
            (``pl.Expr`` or expression string).
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

    Returns:
        pl.DataFrame: Validated {cards}-compatible ARD.

    Raises:
        SchemaError: On missing group column, missing percentage
            denominator, missing *value_col* with continuous statistics
            requested, missing *label_col*, unknown arms/pools, or ARD
            schema violations.
    """
    pools = pools or []
    header_rows = header_rows or []
    row_defs = [r if isinstance(r, Row) else Row(field=r) for r in rows]

    if group_col not in df.columns:
        raise SchemaError(
            f"Group column '{group_col}' not found in the analysis dataset. "
            f"Available: {sorted(df.columns)}"
        )

    dataset_filter_expr = resolve_filter(dataset_filter)
    if dataset_filter_expr is not None:
        df = df.filter(dataset_filter_expr)
    if prefilter is not None:
        df = df.filter(prefilter)

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
    if label_col is not None and label_col not in df.columns:
        raise SchemaError(
            f"label_col '{label_col}' not found in the analysis dataset. "
            f"Available: {sorted(df.columns)}"
        )

    data_arms = set(df[group_col].drop_nulls().unique().to_list())
    if adsl is not None:
        if group_col not in adsl.columns:
            raise SchemaError(
                f"Group column '{group_col}' not found in adsl. Available: {sorted(adsl.columns)}"
            )
        adsl_arms = set(adsl[group_col].drop_nulls().unique().to_list())
        _validate_pool_arms(pools, adsl_arms, group_col, source="adsl")
        big_n = compute_big_n(adsl, group_col, pools, filter_expr=resolve_filter(adsl_filter))
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
        if hdr_filter is not None:
            hdr_df = hdr_df.filter(hdr_filter)
        effective_stats = hdr.statistics or stats
        for arm in arms:
            arm_hdr = hdr_df.filter(pl.col(group_col) == arm)
            arm_n = big_n.get(arm, 0)
            for stat_type in effective_stats:
                sn, sl, sv = compute_stat(stat_type, arm_hdr, arm_n, value_col=value_col)
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
                    )
                )

    present = [r for r in row_defs if r.field in df.columns]
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
            depth_stats = (
                stats if depth == len(fields) - 1 else [s for s in stats if s in COUNT_STATS]
            )
            if not depth_stats:
                continue
            # A row's filter_value scopes that row's own depth and its
            # descendants — never its ancestors' counts.
            frame = df
            for row_def in present[: depth + 1]:
                if row_def.filter_value is not None:
                    frame = frame.filter(pl.col(row_def.field) == row_def.filter_value)
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
            )

    ard = rows_to_ard(ard_rows)
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
    else the spec's first column, else ``"TRTA"``; the frame is
    validated against the spec, then prepared by :func:`prepare_frame`.

    Args:
        df: The analysis dataset.
        spec: A summary spec (any :class:`SummarySpecBase` subclass).
        groupby: Treatment-arm column; overrides ``spec.columns[0]``.
        adsl: ADSL for big-N denominators and the arm universe.

    Returns:
        pl.DataFrame: Validated {cards}-compatible ARD.

    Raises:
        SchemaError: If the frame fails the spec's validation, or on any
            engine refusal (see :func:`summarize_ard`).

    Examples:
        ``ard = summarize_spec(admh, MHSummarySpec(), groupby="TRTA", adsl=adsl)``
    """
    group_col = groupby or (spec.columns[0] if spec.columns else "TRTA")
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
