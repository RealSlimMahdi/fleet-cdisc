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

from ._specs import GroupPool, OverallStat, Row, SchemaError, Statistic, resolve_filter

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
ARD_COLUMN_ORDER = [
    "group1",
    "group1_level",
    "group2",
    "group2_level",
    "variable",
    "variable_level",
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


def validate_ard(df: pl.DataFrame) -> list[str]:
    """Validate that *df* conforms to the {cards}-compatible ARD schema.

    Checks required column presence, data types, and structural integrity.
    Group columns (``group1``, ``group2``, etc.) are optional — matching
    {cards} where not all ARDs have grouping.

    Args:
        df: A DataFrame to validate as ARD.

    Returns:
        list[str]: Diagnostic messages (empty if valid).

    Examples:
        Validate an ARD after computation::

            from fleet.tlg._ard import validate_ard

            issues = validate_ard(ard)
            assert issues == [], issues
    """
    issues: list[str] = []

    # Required columns must be present
    missing_required = [c for c in ARD_REQUIRED_COLUMNS if c not in df.columns]
    if missing_required:
        issues.append(f"Missing required ARD columns: {missing_required}")

    # Check for completely unknown columns
    known = set(ARD_SCHEMA.keys())
    extra = [c for c in df.columns if c not in known]
    if extra:
        issues.append(f"Unexpected columns (not in ARD schema): {extra}")

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


#: Label used for uncoded terms, mirroring the GDSR templates' NA level.
NO_CODING_LABEL = "No Coding Available"


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
        ranked.sort(["__worst_rank", order_col], descending=[True, False])
        .unique(subset=list(by), keep="first", maintain_order=True)
        .drop("__worst_rank")
    )


def compute_stat(
    stat_type: Statistic,
    level_df: pl.DataFrame,
    arm_n: int,
) -> tuple[str, str, float | int | str | None]:
    """Compute a single statistic for a subset of data.

    Args:
        stat_type: The statistic to compute.
        level_df: Filtered DataFrame for this analysis level.
        arm_n: Big-N denominator for the arm.

    Returns:
        Tuple of (stat_name, stat_label, stat_value).
    """
    if stat_type == Statistic.N_SUBJECTS:
        n = level_df["USUBJID"].n_unique() if len(level_df) > 0 else 0
        return ("n", "n", n)
    elif stat_type == Statistic.N_EVENTS:
        return ("n_events", "Events", len(level_df))
    elif stat_type == Statistic.N_PCT:
        n = level_df["USUBJID"].n_unique() if len(level_df) > 0 else 0
        # No denominator → no percentage; never fabricate 0.0.
        pct = round(n / arm_n * 100, 1) if arm_n > 0 else None
        return ("pct", "n (%)", pct)
    elif stat_type == Statistic.MEAN:
        val = level_df["AVAL"].mean() if "AVAL" in level_df.columns and len(level_df) > 0 else None
        return ("mean", "Mean", val)
    elif stat_type == Statistic.SD:
        val = level_df["AVAL"].std() if "AVAL" in level_df.columns and len(level_df) > 0 else None
        return ("sd", "SD", val)
    elif stat_type == Statistic.MEDIAN:
        val = (
            level_df["AVAL"].median() if "AVAL" in level_df.columns and len(level_df) > 0 else None
        )
        return ("median", "Median", val)
    elif stat_type == Statistic.MIN:
        val = level_df["AVAL"].min() if "AVAL" in level_df.columns and len(level_df) > 0 else None
        return ("min", "Min", val)
    elif stat_type == Statistic.MAX:
        val = level_df["AVAL"].max() if "AVAL" in level_df.columns and len(level_df) > 0 else None
        return ("max", "Max", val)
    elif stat_type == Statistic.Q1:
        val = (
            level_df["AVAL"].quantile(0.25)
            if "AVAL" in level_df.columns and len(level_df) > 0
            else None
        )
        return ("q1", "Q1", val)
    elif stat_type == Statistic.Q3:
        val = (
            level_df["AVAL"].quantile(0.75)
            if "AVAL" in level_df.columns and len(level_df) > 0
            else None
        )
        return ("q3", "Q3", val)
    else:
        return (stat_type.value, stat_type.value, None)


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

    Args:
        rows: List of dicts (from ``ard_row()``).

    Returns:
        pl.DataFrame: Formatted ARD DataFrame.
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
                row["stat"] = None

    df = pl.DataFrame(rows).cast({"stat": pl.Float64}, strict=False)

    for col in ("warning", "error", "stat_fmt"):
        if col in df.columns and df[col].dtype == pl.Null:
            df = df.with_columns(pl.lit(None, dtype=pl.Utf8).alias(col))

    df = format_ard(df)

    return df


#: Count-type statistics — meaningful at every hierarchy depth.
COUNT_STATS = frozenset({Statistic.N_SUBJECTS, Statistic.N_EVENTS, Statistic.N_PCT})

#: Continuous statistics: (stat_name, stat_label) and aggregation exprs on AVAL.
_CONT_STAT_META: dict[Statistic, tuple[str, str]] = {
    Statistic.MEAN: ("mean", "Mean"),
    Statistic.SD: ("sd", "SD"),
    Statistic.MEDIAN: ("median", "Median"),
    Statistic.MIN: ("min", "Min"),
    Statistic.MAX: ("max", "Max"),
    Statistic.Q1: ("q1", "Q1"),
    Statistic.Q3: ("q3", "Q3"),
}

_CONT_STAT_EXPRS: dict[Statistic, pl.Expr] = {
    Statistic.MEAN: pl.col("AVAL").mean(),
    Statistic.SD: pl.col("AVAL").std(),
    Statistic.MEDIAN: pl.col("AVAL").median(),
    Statistic.MIN: pl.col("AVAL").min(),
    Statistic.MAX: pl.col("AVAL").max(),
    Statistic.Q1: pl.col("AVAL").quantile(0.25),
    Statistic.Q3: pl.col("AVAL").quantile(0.75),
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
    has_aval: bool,
) -> tuple[str, str, float | int | None]:
    """Extract one statistic from an aggregated cell (``None`` = zero cell)."""
    if stat_type == Statistic.N_SUBJECTS:
        return ("n", "n", cell["__n"] if cell else 0)
    if stat_type == Statistic.N_EVENTS:
        return ("n_events", "Events", cell["__n_events"] if cell else 0)
    if stat_type == Statistic.N_PCT:
        n = cell["__n"] if cell else 0
        # No denominator → no percentage; never fabricate 0.0.
        return ("pct", "n (%)", round(n / arm_n * 100, 1) if arm_n > 0 else None)
    meta = _CONT_STAT_META.get(stat_type)
    if meta is None:
        return (stat_type.value, stat_type.value, None)
    value = cell.get(f"__{stat_type.value}") if (cell is not None and has_aval) else None
    return (*meta, value)


def _level_rows(
    frame: pl.DataFrame,
    fields: list[str],
    stats: list[Statistic],
    arms: list[str],
    big_n: dict[str, int],
    group_col: str,
    context: str,
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

    has_aval = "AVAL" in frame.columns
    aggs = [pl.col("USUBJID").n_unique().alias("__n"), pl.len().alias("__n_events")]
    if has_aval:
        aggs += [_CONT_STAT_EXPRS[s].alias(f"__{s.value}") for s in stats if s in _CONT_STAT_EXPRS]
    group_keys = list(dict.fromkeys([group_col, *fields]))
    grouped = frame.drop_nulls(subset=select_fields).group_by(group_keys).agg(aggs)
    cells = {
        (row[group_col], *(row[f] for f in fields)): row for row in grouped.iter_rows(named=True)
    }

    variable = fields[-1]
    parent = fields[-2] if len(fields) >= 2 else None
    out: list[dict[str, Any]] = []
    combo_list = combos.to_dicts()
    for arm in arms:
        arm_n = big_n.get(arm, 0)
        for combo in combo_list:
            cell = cells.get((arm, *(combo[f] for f in fields)))
            for stat_type in stats:
                sn, sl, sv = _cell_stat(stat_type, cell, arm_n, has_aval)
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

    Returns:
        pl.DataFrame: Validated {cards}-compatible ARD.

    Raises:
        SchemaError: On missing group column, missing percentage
            denominator, unknown arms/pools, or ARD schema violations.
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

    # Big-N rows exist only when a population is given.
    if adsl is not None:
        ard_rows += [
            ard_row(group_col, arm, "", "", "N", "N", big_n.get(arm), context) for arm in arms
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
                sn, sl, sv = compute_stat(stat_type, arm_hdr, arm_n)
                ard_rows.append(ard_row(group_col, arm, "", hdr.label, sn, sl, sv, context))

    present = [r for r in row_defs if r.field in df.columns]
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
                frame, fields[: depth + 1], depth_stats, arms, big_n, group_col, context
            )
    else:
        for row_def in present:
            frame = df
            if row_def.filter_value is not None:
                frame = frame.filter(pl.col(row_def.field) == row_def.filter_value)
            ard_rows += _level_rows(frame, [row_def.field], stats, arms, big_n, group_col, context)

    ard = rows_to_ard(ard_rows)
    issues = validate_ard(ard)
    if issues:
        raise SchemaError("ARD output failed schema validation:\n  " + "\n  ".join(issues))
    return ard
