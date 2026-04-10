"""Shared sequence-number derivation used by both SDTM and ADaM namespaces.

This is the single implementation of the ``--SEQ`` / ``ASEQ`` logic.
Both ``SDTMNamespace.seq()`` and ``MultiRowMixin.seq()`` delegate here
to avoid code duplication across namespace trees.
"""

from __future__ import annotations

import warnings

import polars as pl


def derive_seq(
    df: pl.DataFrame,
    target: str,
    *,
    order_by: list[str] | None = None,
    groups: list[str],
    start_at: int = 1,
    check_uniqueness: bool = False,
) -> pl.DataFrame:
    """Derive a 1-based integer sequence number within each group.

    Aligns with sdtm.oak ``derive_seq()`` and admiral
    ``derive_var_obs_number()``:

    1. Sort by *order_by* (if provided) to ensure deterministic numbering.
    2. Assign ``row_number()`` within each *groups* partition, starting at
       *start_at*.
    3. Optionally warn if *groups* + *order_by* do not uniquely identify
       each row.

    Args:
        df: Input DataFrame (already materialised).
        target: Name of the output sequence column.
        order_by: Columns that define the sort order within each group.
            When ``None``, the current row order is preserved.
        groups: Partition columns for the sequence.
        start_at: First sequence value (default ``1``).
        check_uniqueness: If ``True``, emit a warning when the
            combination of *groups* + *order_by* does not uniquely
            identify each row.

    Returns:
        pl.DataFrame: The input frame with *target* appended.
    """
    if order_by:
        df = df.sort(order_by)

    if check_uniqueness and order_by:
        key_cols = groups + order_by
        available = [c for c in key_cols if c in df.columns]
        n_total = df.shape[0]
        n_unique = df.select(available).unique().shape[0]
        if n_unique < n_total:
            warnings.warn(
                f"Rows are not unique by {available}: "
                f"{n_total} rows but only {n_unique} unique combinations. "
                f"{target} values may be arbitrary for tied rows.",
                stacklevel=3,
            )

    return df.with_columns(
        (pl.int_range(pl.len()).over(groups) + start_at)
        .cast(pl.Int64)
        .alias(target)
    )
