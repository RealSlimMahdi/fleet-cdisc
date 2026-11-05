"""Semantic assertion helpers for Fleet test suite.

Provides assertion functions that check structural properties (grouping,
flags, counts, nulls, cardinality) rather than brittle row-order comparisons.
"""

from __future__ import annotations

import polars as pl


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


def assert_valid_cdisc_refs(nodes: list) -> None:
    """Assert every VariableNode has a well-formed cdisc_ref string.

    Format: ``[DOMAIN].VAR ← verb(...)`` when domain is set, ``VAR ← verb(...)`` otherwise.
    """
    for node in nodes:
        ref = node.cdisc_ref
        assert "←" in ref, f"cdisc_ref missing arrow: {ref!r}"
        expected_prefix = f"[{node.domain}].{node.name}" if node.domain else node.name
        assert ref.startswith(expected_prefix), f"cdisc_ref has wrong prefix: {ref!r}"
