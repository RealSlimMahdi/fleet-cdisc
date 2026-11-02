"""Types for the CSV side of a comparison: a CSV file holds none (c1-237).

A CSV side is read as text, then each column takes a type, decided across
both sides so that a key pairs and a value compares under one rule:

* against a typed side (Parquet, XPT, SAS7BDAT), the typed side's dtype;
* otherwise text when a ``text`` option names it, when a value on either
  CSV side has a leading zero (SITEID ``001``) or is not a number, and a
  number in every other case, compared by value as PROC COMPARE does.
"""

from __future__ import annotations

from collections.abc import Collection

import polars as pl

from fleet.io.loaders import LEADING_ZERO


def type_csv_sides(
    base: pl.LazyFrame,
    candidate: pl.LazyFrame,
    *,
    base_csv: bool,
    candidate_csv: bool,
    text: Collection[str] = (),
) -> tuple[pl.LazyFrame, pl.LazyFrame, dict[str, pl.DataType]]:
    """Give each column of the CSV side(s) a type; the other side is unchanged.

    Args:
        base: The base, read as text when it is a CSV file.
        candidate: The candidate, read as text when it is a CSV file.
        base_csv: Whether the base is a CSV file.
        candidate_csv: Whether the candidate is a CSV file.
        text: Columns to keep as text, the equivalent of a ``$`` informat.

    Returns:
        The two sides, and the dtype each CSV column was given.

    Examples:
        Type two CSV exports before comparing them::

            base, candidate, types = type_csv_sides(
                pl.scan_csv("adlb.csv", infer_schema=False),
                pl.scan_csv("adlb_qc.csv", infer_schema=False),
                base_csv=True,
                candidate_csv=True,
            )
            report = fleet.compare(base, candidate, keys="USUBJID")
    """
    sides = ((base, base_csv), (candidate, candidate_csv))
    csv_frames = [lf for lf, is_csv in sides if is_csv]
    typed = next((lf.collect_schema() for lf, is_csv in sides if not is_csv), pl.Schema())
    columns = list(dict.fromkeys(c for lf in csv_frames for c in lf.collect_schema()))
    undecided = [c for c in columns if c not in text and c not in typed]
    numbers = _number_columns(csv_frames, undecided)

    def dtype(c: str) -> pl.DataType:
        if c in text:
            return pl.String()
        if c in typed:
            return typed[c]
        return numbers.get(c, pl.String())

    types = {c: dtype(c) for c in columns}

    def cast(lf: pl.LazyFrame, is_csv: bool) -> pl.LazyFrame:
        if not is_csv:
            return lf
        return lf.with_columns(
            _from_text(c, types[c]) for c in lf.collect_schema() if types[c] != pl.String
        )

    return cast(base, base_csv), cast(candidate, candidate_csv), types


def _number_columns(frames: list[pl.LazyFrame], columns: list[str]) -> dict[str, pl.DataType]:
    """The columns whose every value, on every CSV side, is a number with no leading zero."""
    integer: dict[str, bool] = dict.fromkeys(columns, True)
    number: dict[str, bool] = dict.fromkeys(columns, True)
    for lf in frames:
        present = [c for c in columns if c in lf.collect_schema()]
        if not present:
            continue
        row = (
            lf.select(
                expr
                for c in present
                for expr in (
                    pl.col(c).is_not_null().sum().alias(f"{c}\0n"),
                    _parsed(c, pl.Float64).is_not_null().sum().alias(f"{c}\0f"),
                    _parsed(c, pl.Int64).is_not_null().sum().alias(f"{c}\0i"),
                    pl.col(c).str.contains(LEADING_ZERO).any().alias(f"{c}\0z"),
                )
            )
            .collect()
            .row(0, named=True)
        )
        for c in present:
            n = row[f"{c}\0n"]
            number[c] &= row[f"{c}\0f"] == n and not row[f"{c}\0z"]
            integer[c] &= row[f"{c}\0i"] == n
    return {c: pl.Int64() if integer[c] else pl.Float64() for c in columns if number[c]}


def _parsed(column: str, dtype: pl.DataType) -> pl.Expr:
    return pl.col(column).str.strip_chars().cast(dtype, strict=False)


def _from_text(column: str, dtype: pl.DataType) -> pl.Expr:
    """A text column cast to *dtype*; a value that does not cast is null, so it differs."""
    if dtype.is_numeric():
        return _parsed(column, dtype).alias(column)
    if dtype.is_temporal():
        return pl.col(column).cast(dtype, strict=False)
    return pl.col(column)  # no text form to cast from: the compare reports a type conflict
