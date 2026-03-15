"""Utility helpers for SDTM derivations."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import polars as pl


# ------------------------------------------------------------------ #
# ISO 8601 date/datetime helpers                                       #
# ------------------------------------------------------------------ #

_ISO_DATE_FMTS = [
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%Y%m%d",
    "%d-%b-%Y",
    "%d %b %Y",
]

_ISO_DATETIME_FMTS = [
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M",
]


def _try_parse(value: str, formats: list[str]) -> datetime | None:
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except (ValueError, TypeError):
            continue
    return None


def to_iso8601_date(value: str | None) -> str | None:
    """Convert a date string to ISO 8601 (YYYY-MM-DD)."""
    if not value:
        return None
    dt = _try_parse(str(value), _ISO_DATE_FMTS)
    if dt:
        return dt.strftime("%Y-%m-%d")
    return str(value)


def to_iso8601_datetime(value: str | None) -> str | None:
    """Convert a datetime string to ISO 8601 (YYYY-MM-DDTHH:MM:SS)."""
    if not value:
        return None
    dt = _try_parse(str(value), _ISO_DATETIME_FMTS + _ISO_DATE_FMTS)
    if dt:
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    return str(value)


# ------------------------------------------------------------------ #
# Expression parsing                                                   #
# ------------------------------------------------------------------ #

def parse_expression(expr_str: str) -> pl.Expr:
    """
    Evaluate a simple Polars expression string.

    Supports column references: ``pl.col("NAME")`` or plain ``NAME``.
    For safety, only polars and builtins are exposed.
    """
    # Allow bare column name shorthand: e.g. "VSSTRESN" → pl.col("VSSTRESN")
    if re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', expr_str.strip()):
        return pl.col(expr_str.strip())

    local_ns: dict[str, Any] = {"pl": pl}
    try:
        result = eval(expr_str, {"__builtins__": {}}, local_ns)  # noqa: S307
        if not isinstance(result, pl.Expr):
            raise ValueError(f"Expression did not produce a pl.Expr: {expr_str!r}")
        return result
    except Exception as exc:
        raise ValueError(f"Cannot parse expression {expr_str!r}: {exc}") from exc


# ------------------------------------------------------------------ #
# Sequence number generation                                           #
# ------------------------------------------------------------------ #

def make_seq_expr(group_by: list[str] | None = None, target: str = "SEQ") -> pl.Expr:
    """Return an expression that adds sequential row numbers (1-based)."""
    if group_by:
        return pl.int_range(pl.len()).over(group_by).alias(target) + 1
    return (pl.int_range(pl.len()) + 1).alias(target)
