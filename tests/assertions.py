"""Semantic assertion helpers for Fleet test suite.

Provides assertion functions that check structural properties (grouping,
flags, counts, nulls, cardinality) rather than brittle row-order comparisons.
"""

from __future__ import annotations

import polars as pl


def assert_one_record_per_group(df: pl.DataFrame, group_cols: list[str], msg: str = "") -> None:
    """Assert each combination of group_cols has exactly one row."""
    dupes = df.group_by(group_cols).len().filter(pl.col("len") > 1)
    assert dupes.height == 0, f"Duplicate groups found{': ' + msg if msg else ''}:\n{dupes}"


def assert_no_nulls(df: pl.DataFrame, columns: list[str], msg: str = "") -> None:
    """Assert specified columns contain no null values."""
    for col in columns:
        null_count = df[col].null_count()
        assert null_count == 0, f"Column '{col}' has {null_count} nulls{': ' + msg if msg else ''}"


def assert_all_null(df: pl.DataFrame, column: str, msg: str = "") -> None:
    """Assert a column is entirely null."""
    non_null = df[column].drop_nulls().len()
    assert non_null == 0, (
        f"Column '{column}' has {non_null} non-null values{': ' + msg if msg else ''}"
    )


def assert_flag_at_most_one_per_group(
    df: pl.DataFrame, flag_col: str, group_cols: list[str], flag_value: str = "Y"
) -> None:
    """Assert at most one row per group has the flag set."""
    flagged = df.filter(pl.col(flag_col) == flag_value)
    dupes = flagged.group_by(group_cols).len().filter(pl.col("len") > 1)
    assert dupes.height == 0, f"Multiple '{flag_value}' flags in groups:\n{dupes}"


def assert_column_values_in(df: pl.DataFrame, column: str, allowed: set, msg: str = "") -> None:
    """Assert all non-null values in column are within allowed set."""
    actual = set(df[column].drop_nulls().to_list())
    unexpected = actual - allowed
    assert not unexpected, (
        f"Unexpected values in '{column}': {unexpected}{': ' + msg if msg else ''}"
    )


def assert_deterministic(df1: pl.DataFrame, df2: pl.DataFrame, sort_cols: list[str]) -> None:
    """Assert two DataFrames are identical when sorted by sort_cols."""
    s1 = df1.sort(sort_cols)
    s2 = df2.sort(sort_cols)
    assert s1.equals(s2), "Frames differ after sorting — non-deterministic output"


def assert_row_count(df: pl.DataFrame, expected: int, msg: str = "") -> None:
    """Assert exact row count."""
    assert df.height == expected, (
        f"Expected {expected} rows, got {df.height}{': ' + msg if msg else ''}"
    )


def assert_subset_columns(df: pl.DataFrame, required: list[str]) -> None:
    """Assert that all required columns exist in the DataFrame."""
    missing = set(required) - set(df.columns)
    assert not missing, f"Missing columns: {missing}"

def assert_valid_cdisc_refs(nodes: list) -> None:
    """Assert every VariableNode has a well-formed cdisc_ref string.

    Format: ``[DOMAIN].VAR ← verb(...)`` when domain is set, ``VAR ← verb(...)`` otherwise.
    """
    for node in nodes:
        ref = node.cdisc_ref
        assert "←" in ref, f"cdisc_ref missing arrow: {ref!r}"
        expected_prefix = f"[{node.domain}].{node.name}" if node.domain else node.name
        assert ref.startswith(expected_prefix), f"cdisc_ref has wrong prefix: {ref!r}"
