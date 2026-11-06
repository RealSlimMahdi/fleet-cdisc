"""Utility to generate ``pl.from_repr()``-ready table strings from DataFrames.

Usage::

    import polars as pl
    from fleet import to_repr

    df = pl.DataFrame({"USUBJID": ["S001", "S002"], "AGE": [35, 42]})
    print(to_repr(df))
    # Copy the output into your test / example as:
    # df = pl.from_repr(\"\"\"\\
    # <pasted table>
    # \"\"\")
"""

from __future__ import annotations

import polars as pl

from fleet.core.exceptions import DerivationError


def to_repr(
    df: pl.DataFrame | pl.LazyFrame,
    *,
    max_cols: int = 50,
    max_width: int = 500,
    max_str_len: int = 100,
) -> str:
    """Return a ``pl.from_repr()``-ingestible table string for *df*.

    Temporarily widens the Polars display settings up to the given caps and
    prints floats in full, then checks that ``pl.from_repr`` gives back an
    equal frame.  When it does not (more columns than *max_cols*, a text
    longer than *max_str_len*, a table wider than *max_width*, or a value
    that holds the column separator), it raises instead of returning a
    table that makes a different frame.

    Args:
        df: A Polars DataFrame or LazyFrame to render.
        max_cols: Maximum number of columns to display (avoids ``…``).
        max_width: Maximum character width for the table (at most 65535).
        max_str_len: Maximum string length before truncation.

    Returns:
        str: A Unicode box-drawing table string that can be pasted directly
            into ``pl.from_repr(...)`` to recreate the DataFrame.

    Raises:
        DerivationError: When ``pl.from_repr`` of the table does not give
            back a frame equal to *df*.

    Examples:
        Generate a pasteable repr and use it to recreate the DataFrame::

            import polars as pl
            from fleet import to_repr

            # Start with any DataFrame (e.g. from a CSV, query, or dict)
            original = pl.DataFrame({
                "USUBJID": ["S001", "S002"],
                "AGE": [35, 42],
                "ARM": ["Drug A", "Placebo"],
            })

            # Generate the from_repr-ready string
            print(to_repr(original))
            # shape: (2, 3)
            # ┌─────────┬─────┬─────────┐
            # │ USUBJID ┆ AGE ┆ ARM     │
            # │ ---     ┆ --- ┆ ---     │
            # │ str     ┆ i64 ┆ str     │
            # ╞═════════╪═════╪═════════╡
            # │ S001    ┆ 35  ┆ Drug A  │
            # │ S002    ┆ 42  ┆ Placebo │
            # └─────────┴─────┴─────────┘

            # Paste that output into pl.from_repr() in your test/example:
            df = pl.from_repr(\"\"\"\\\n            ┌─────────┬─────┬─────────┐
            │ USUBJID ┆ AGE ┆ ARM     │
            │ ---     ┆ --- ┆ ---     │
            │ str     ┆ i64 ┆ str     │
            ╞═════════╪═════╪═════════╡
            │ S001    ┆ 35  ┆ Drug A  │
            │ S002    ┆ 42  ┆ Placebo │
            └─────────┴─────┴─────────┘
            \"\"\")
            assert df.shape == (2, 3)
    """
    if isinstance(df, pl.LazyFrame):
        df = df.collect()

    with pl.Config(
        tbl_cols=max_cols,
        tbl_width_chars=min(max_width, 65535),
        fmt_str_lengths=max_str_len,
        fmt_float="full",
        tbl_rows=-1,
    ):
        text = str(df)
    try:
        same = pl.from_repr(text).equals(df)
    except pl.exceptions.PolarsError:
        same = False
    if not same:
        raise DerivationError(
            f"to_repr(): pl.from_repr of the table does not give back the frame of shape "
            f"{df.shape}. Widen max_cols (now {max_cols}), max_str_len (now {max_str_len}) "
            f"or max_width (now {max_width}); a value that holds the column separator "
            "cannot be written as a table."
        )
    return text
