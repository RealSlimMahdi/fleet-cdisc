"""Minimal test helpers for Fleet test suite."""

import polars as pl


def shuffle_rows(df: pl.DataFrame, seed: int = 42) -> pl.DataFrame:
    """Return df with rows in a different deterministic order."""
    return df.sample(fraction=1.0, seed=seed, shuffle=True)
