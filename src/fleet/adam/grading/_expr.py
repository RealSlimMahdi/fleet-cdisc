"""Expression trees of the grading criteria files, and their Polars form.

A node is a leaf (a number, ``true``/``false``, ``{"var": ...}``,
``{"str": ...}``, ``{"param": ...}``) or a call ``{"op": ..., "args": [...]}``.
``scripts/regen_grading_criteria.R`` writes these trees from the admiral R
code, so each operator keeps its R meaning: a null in a comparison gives
null, which no ``when`` arm takes, and ``in`` on a null gives false, as
``NA %in% x`` does.
"""

from __future__ import annotations

import operator
from typing import Any

import polars as pl

from fleet.core.exceptions import DerivationError

_BINARY = {
    "lt": operator.lt,
    "le": operator.le,
    "gt": operator.gt,
    "ge": operator.ge,
    "eq": operator.eq,
    "ne": operator.ne,
    "mul": operator.mul,
    "add": operator.add,
    "sub": operator.sub,
}

_ARITY: dict[str, tuple[int, int | None]] = {
    "and": (2, None),
    "or": (2, None),
    "not": (1, 1),
    "is_na": (1, 1),
    "in": (2, 2),
    "lt": (2, 2),
    "le": (2, 2),
    "gt": (2, 2),
    "ge": (2, 2),
    "eq": (2, 2),
    "ne": (2, 2),
    "mul": (2, 2),
    "add": (2, 2),
    "sub": (2, 2),
    "neg": (1, 1),
    "signif": (1, 1),
    "age": (2, 2),
}
_LEAF_KEYS = ("var", "str", "param")
_AGE_UNITS = ("days", "months", "years")


def validate_node(node: Any, where: str = "node") -> None:
    """Raise ``ValueError`` when *node* is not a valid expression tree."""
    if isinstance(node, bool | int | float):
        return
    if not isinstance(node, dict):
        raise ValueError(f"{where}: expected a number, a boolean or an object, got {node!r}")
    leaf = [k for k in _LEAF_KEYS if k in node]
    if leaf:
        if len(node) != 1 or not isinstance(node[leaf[0]], str):
            raise ValueError(f"{where}: a leaf holds one string key, got {node!r}")
        return
    op = node.get("op")
    if op not in _ARITY:
        raise ValueError(f"{where}: unknown op {op!r}; known: {sorted(_ARITY)}")
    args = node.get("args")
    low, high = _ARITY[op]
    if not isinstance(args, list) or len(args) < low or (high is not None and len(args) > high):
        raise ValueError(f"{where}: op {op!r} takes {low}..{high or 'n'} args, got {args!r}")
    if op == "age" and node.get("unit") not in _AGE_UNITS:
        raise ValueError(f"{where}: age unit must be one of {_AGE_UNITS}, got {node.get('unit')!r}")
    if op == "in" and not (isinstance(args[1], dict) and "param" in args[1]):
        raise ValueError(f"{where}: the second arg of 'in' must be a param")
    for i, arg in enumerate(args):
        validate_node(arg, f"{where}.args[{i}]")


def node_names(node: Any, key: str) -> set[str]:
    """Return every ``var`` (or ``param``) name used in *node*."""
    if not isinstance(node, dict):
        return set()
    if key in node:
        return {node[key]}
    names: set[str] = set()
    for arg in node.get("args", []):
        names |= node_names(arg, key)
    return names


def _calendar_age(start: pl.Expr, end: pl.Expr, unit: str) -> pl.Expr:
    """admiral ``compute_duration(trunc_out = TRUE, add_one = FALSE)`` on dates."""
    s, e = start.cast(pl.Date), end.cast(pl.Date)
    if unit == "days":
        return (e - s).dt.total_days()
    months = (e.dt.year() - s.dt.year()) * 12 + e.dt.month().cast(pl.Int32) - s.dt.month()
    months = months - (e.dt.day() < s.dt.day()).cast(pl.Int32)
    if unit == "months":
        return months
    return months.floordiv(12)


def compile_node(
    node: Any,
    *,
    signif_dig: int,
    indicators: dict[str, list[str]],
) -> pl.Expr:
    """Translate a validated expression tree into a Polars expression.

    Args:
        node: The expression tree.
        signif_dig: Significant digits for ``signif`` (R ``signif``).
        indicators: Values of each ``param`` (e.g. ``high_indicator``).

    Returns:
        pl.Expr: The expression.

    Raises:
        DerivationError: When a ``param`` has no values in *indicators*.
    """

    def go(n: Any) -> pl.Expr:
        if isinstance(n, bool):
            return pl.lit(n)
        if isinstance(n, int | float):
            return pl.lit(float(n))
        if "var" in n:
            return pl.col(n["var"])
        if "str" in n:
            return pl.lit(n["str"])
        if "param" in n:
            raise DerivationError(f"param {n['param']!r} is only allowed in 'in'.")
        op, args = n["op"], n["args"]
        if op == "in":
            name = args[1]["param"]
            if name not in indicators:
                raise DerivationError(
                    f"The criteria need {name}=; pass it in indicators={{'{name}': [...]}}."
                )
            return go(args[0]).cast(pl.String).is_in(indicators[name]).fill_null(False)
        if op == "age":
            return _calendar_age(go(args[0]), go(args[1]), n["unit"])
        parts = [go(a) for a in args]
        if op == "and":
            out = parts[0]
            for p in parts[1:]:
                out = out & p
            return out
        if op == "or":
            out = parts[0]
            for p in parts[1:]:
                out = out | p
            return out
        if op == "not":
            return ~parts[0]
        if op == "is_na":
            return parts[0].is_null()
        if op == "neg":
            return -parts[0]
        if op == "signif":
            value = parts[0].cast(pl.Float64)
            return value.round_sig_figs(signif_dig) if signif_dig > 0 else value
        left, right = parts
        return _BINARY[op](left, right)

    return go(node)
