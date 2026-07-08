"""Utility helpers for SDTM derivations."""

from __future__ import annotations

import ast
import re
from typing import Any

import polars as pl

from fleet.core.exceptions import DerivationError

# ------------------------------------------------------------------ #
# ISO 8601 date/datetime helpers (vectorised)                          #
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


def dtc_date_expr(source: str, target: str, *, input_format: str | None = None) -> pl.Expr:
    """Return a vectorised expression that parses *source* to ISO 8601 date string.

    Tries each format in ``_ISO_DATE_FMTS`` via ``pl.coalesce``; partial dates
    (e.g. ``"2014-01"``, ``"2014"``) that fail all formats are preserved as-is.

    Args:
        source: Name of the input column containing date strings.
        target: Name of the output column.
        input_format: When provided, skips the coalesce chain and uses a
            single ``str.to_date`` call for maximum performance.

    Returns:
        pl.Expr: Expression producing an ISO 8601 date string (``pl.String``).
    """
    col = pl.col(source)
    if input_format is not None:
        parsed = col.str.to_date(input_format, strict=False)
        return (
            pl.when(parsed.is_not_null())
            .then(parsed.dt.to_string("%Y-%m-%d"))
            .otherwise(col)
            .alias(target)
        )
    candidates = [
        col.str.to_date(fmt, strict=False).dt.to_string("%Y-%m-%d") for fmt in _ISO_DATE_FMTS
    ]
    return pl.coalesce(*candidates, col).alias(target)


def dtc_datetime_expr(source: str, target: str, *, input_format: str | None = None) -> pl.Expr:
    """Return a vectorised expression that parses *source* to ISO 8601 datetime string.

    Args:
        source: Name of the input column containing datetime strings.
        target: Name of the output column.
        input_format: When provided, skips the coalesce chain and uses a
            single ``str.to_datetime`` call for maximum performance.

    Returns:
        pl.Expr: Expression producing an ISO 8601 datetime string (``pl.String``).
    """
    col = pl.col(source)
    if input_format is not None:
        parsed = col.str.to_datetime(input_format, strict=False)
        return (
            pl.when(parsed.is_not_null())
            .then(parsed.dt.to_string("%Y-%m-%dT%H:%M:%S"))
            .otherwise(col)
            .alias(target)
        )
    all_fmts = _ISO_DATETIME_FMTS + _ISO_DATE_FMTS
    candidates = [
        col.str.to_datetime(fmt, strict=False).dt.to_string("%Y-%m-%dT%H:%M:%S") for fmt in all_fmts
    ]
    return pl.coalesce(*candidates, col).alias(target)


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


def _validate_ast(expr_str: str) -> ast.Expression:
    """Validate *expr_str* against an AST whitelist before eval.

    Rejects any node type not in ``_ALLOWED_AST_NODES`` and any
    ``Name`` containing double-underscore identifiers.  Returns the
    parsed tree so callers can transform it without re-parsing.
    """
    try:
        tree = ast.parse(expr_str, mode="eval")
    except SyntaxError as exc:
        raise DerivationError(
            f"Syntax error in expression {expr_str!r}: {exc}. "
            "Use Polars syntax, e.g. pl.col('AVAL') * 2."
        ) from exc

    for node in ast.walk(tree):
        if type(node) not in _ALLOWED_AST_NODES:
            raise DerivationError(
                f"Disallowed construct {type(node).__name__!r} in expression {expr_str!r}"
            )
        if isinstance(node, ast.Name) and "__" in node.id:
            raise DerivationError(
                f"Dunder identifier {node.id!r} is not allowed in expression {expr_str!r}"
            )
        if isinstance(node, ast.Attribute) and "__" in node.attr:
            raise DerivationError(
                f"Dunder attribute {node.attr!r} is not allowed in expression {expr_str!r}"
            )
    return tree


#: Names that are *not* rewritten to column references during the AST
#: transform — only the ``pl`` namespace is exposed to expressions.
_EXPR_NAMESPACES = frozenset({"pl"})


class _BareNameToColumn(ast.NodeTransformer):
    """Rewrite bare ``ast.Name`` nodes to ``pl.col(name)`` calls.

    Makes SAS-friendly expressions like ``"AVAL * 2"`` work while
    keeping the whitelist security posture: after the transform, only
    the ``pl`` namespace, literals, and resolved column references
    remain.
    """

    def visit_Name(self, node: ast.Name) -> ast.AST:  # noqa: N802 — ast API
        if node.id in _EXPR_NAMESPACES:
            return node
        return ast.copy_location(
            ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="pl", ctx=ast.Load()),
                    attr="col",
                    ctx=ast.Load(),
                ),
                args=[ast.Constant(value=node.id)],
                keywords=[],
            ),
            node,
        )


def parse_expression(expr_str: str) -> pl.Expr:
    """Evaluate a simple Polars expression string.

    Supports column references — ``pl.col("NAME")`` or plain ``NAME`` —
    and mixed forms like ``"AVAL * 2"`` or ``"VSSTRESN > LBSTNRHI"``:
    bare names resolve to ``pl.col(name)``.  Expressions are validated
    against an AST whitelist before evaluation to prevent code
    injection; only the ``pl`` namespace, literals, and column
    references are available.

    Args:
        expr_str: The expression string to parse.

    Returns:
        pl.Expr: The parsed Polars expression.

    Raises:
        DerivationError: On syntax errors, disallowed constructs, or
            input that does not produce a ``pl.Expr``.  Also catchable
            as ``ValueError``.

    Examples:
        Parse a derived-value expression inside a pipeline::

            advs = (
                vs_df.adam
                .derivation("AVAL", expression="VSSTRESN * 2")
                .to_frame()
            )
    """
    # Allow bare column name shorthand: e.g. "VSSTRESN" → pl.col("VSSTRESN")
    if re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", expr_str.strip()):
        return pl.col(expr_str.strip())

    tree = _validate_ast(expr_str)
    tree = ast.fix_missing_locations(_BareNameToColumn().visit(tree))
    code = compile(tree, "<fleet-expression>", "eval")

    local_ns: dict[str, Any] = {"pl": pl}
    try:
        result = eval(code, {"__builtins__": {}}, local_ns)  # noqa: S307
        if not isinstance(result, pl.Expr):
            raise DerivationError(
                f"Expression did not produce a pl.Expr: {expr_str!r}. "
                "Reference columns as pl.col('X') or a bare name, "
                'e.g. "pl.col(\'AVAL\') * 2" or "AVAL * 2".'
            )
        return result
    except DerivationError:
        raise
    except Exception as exc:
        raise DerivationError(
            f"Cannot parse expression {expr_str!r}: {exc}. "
            "Reference columns as pl.col('X') or a bare name, "
            'e.g. "pl.col(\'AVAL\') * 2" or "AVAL * 2".'
        ) from exc
