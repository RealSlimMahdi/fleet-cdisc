"""Utility helpers for SDTM derivations."""

from __future__ import annotations

import ast
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

# AST node types allowed in expression strings.  Anything not listed
# here is rejected *before* ``eval`` is called.
_ALLOWED_AST_NODES: frozenset[type] = frozenset(
    {
        ast.Expression,
        ast.Attribute,
        ast.Call,
        ast.Name,
        ast.Constant,
        ast.BinOp,
        ast.UnaryOp,
        ast.Compare,
        ast.BoolOp,
        ast.IfExp,
        ast.Subscript,
        ast.List,
        ast.Tuple,
        ast.Dict,
        ast.Starred,
        ast.keyword,
        ast.Slice,
        ast.Index,  # py 3.8 compat
        # Operators
        ast.Add,
        ast.Sub,
        ast.Mult,
        ast.Div,
        ast.FloorDiv,
        ast.Mod,
        ast.Pow,
        ast.USub,
        ast.UAdd,
        ast.Not,
        ast.Invert,
        ast.Eq,
        ast.NotEq,
        ast.Lt,
        ast.LtE,
        ast.Gt,
        ast.GtE,
        ast.Is,
        ast.IsNot,
        ast.In,
        ast.NotIn,
        ast.And,
        ast.Or,
        ast.BitAnd,
        ast.BitOr,
        ast.BitXor,
        ast.Load,
    }
)


def _validate_ast(expr_str: str) -> None:
    """Validate *expr_str* against an AST whitelist before eval.

    Rejects any node type not in ``_ALLOWED_AST_NODES`` and any
    ``Name`` containing double-underscore identifiers.
    """
    try:
        tree = ast.parse(expr_str, mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Syntax error in expression {expr_str!r}: {exc}") from exc

    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_AST_NODES:
            raise ValueError(
                f"Disallowed construct {type(node).__name__!r} in expression {expr_str!r}"
            )
        if isinstance(node, ast.Name) and "__" in node.id:
            raise ValueError(
                f"Dunder identifier {node.id!r} is not allowed in expression {expr_str!r}"
            )


def parse_expression(expr_str: str) -> pl.Expr:
    """Evaluate a simple Polars expression string.

    Supports column references: ``pl.col("NAME")`` or plain ``NAME``.
    Complex expressions are validated against an AST whitelist before
    evaluation to prevent code injection.
    """
    # Allow bare column name shorthand: e.g. "VSSTRESN" → pl.col("VSSTRESN")
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", expr_str.strip()):
        return pl.col(expr_str.strip())

    _validate_ast(expr_str)

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
