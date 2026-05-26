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
from typing import Any

import polars as pl

from ._specs import GroupPool, SchemaError, Statistic

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
) -> pl.DataFrame:
    """Expand a DataFrame by stacking pooled treatment groups.

    For each ``GroupPool``, filters *df* to the constituent arms, relabels
    the group column with the pool label, and concatenates onto the
    original DataFrame.

    Args:
        df: The analysis DataFrame.
        pools: Pool definitions to expand.
        group_col: Column containing treatment arm labels.

    Returns:
        pl.DataFrame: Original rows plus duplicated rows for each pool.

    Raises:
        SchemaError: If a pool references arms not present in the data.
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
            if missing:
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
    df = expand_pools(df, pools, group_col)
    counts = df.group_by(group_col).agg(pl.col("USUBJID").n_unique().alias("N")).sort(group_col)
    return dict(zip(counts[group_col].to_list(), counts["N"].to_list()))


# ------------------------------------------------------------------ #
# Shared TLG computation helpers                                       #
# ------------------------------------------------------------------ #


def validate_pools(
    df: pl.DataFrame,
    pools: list[GroupPool],
    group_col: str,
) -> None:
    """Validate pool arm references against actual data.

    Args:
        df: The analysis DataFrame.
        pools: Pool definitions to validate.
        group_col: Column containing treatment arm labels.

    Raises:
        SchemaError: If a pool references arms not present in the data.
    """
    if not pools:
        return
    actual = set(df[group_col].drop_nulls().unique().to_list())
    for pool in pools:
        if pool.arms == "*":
            continue
        missing = [a for a in pool.arms if a not in actual]
        if missing:
            raise SchemaError(
                f"Pool '{pool.label}' references arm(s) {missing} but "
                f"{group_col} contains only {sorted(actual)}"
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
        pct = round(n / arm_n * 100, 1) if arm_n > 0 else 0.0
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
            row["stat"] = float(v) if str(v).replace(".", "", 1).isdigit() else None

    df = pl.DataFrame(rows).cast({"stat": pl.Float64}, strict=False)

    for col in ("warning", "error", "stat_fmt"):
        if col in df.columns and df[col].dtype == pl.Null:
            df = df.with_columns(pl.lit(None, dtype=pl.Utf8).alias(col))

    df = format_ard(df)

    return df
