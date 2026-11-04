"""Utility helpers for SDTM derivations."""

from __future__ import annotations

import ast
import re
from typing import Any

import polars as pl

from fleet.core.dtc import is_iso8601
from fleet.core.exceptions import DerivationError

# ------------------------------------------------------------------ #
# ISO 8601 date/datetime helpers (vectorised)                          #
# ------------------------------------------------------------------ #

_ISO_DATE_FMTS = [
    "%Y%m%d",
    "%d-%b-%Y",
    "%d %b %Y",
    "%d%b%Y",
]
"""Layouts read with no ``format=``: none can be read two ways."""

#: A slash date, whose day and month order needs a guess.
GUESSED_SLASH = r"^\s*\d{1,2}/\d{1,2}/\d{1,4}\s*$"
#: A date with a two-digit year, whose century needs a guess.
GUESSED_YEAR = r"^\s*(?:\d{1,2}[-/ ]?[A-Za-z]{3}[-/ ]?\d{2}|\d{2}[-/]\d{2}[-/]\d{2})\s*$"

_TIME = r"^(\d{1,2})(?::(\d{2})(?::(\d{2}(?:\.\d+)?))?)?$"
#: A time literal for ``time=``; anything else names a column.
TIME_LITERAL = re.compile(r"^\d{1,2}:\d{2}(:\d{2}(\.\d+)?)?$")


def _blank_to_null(expr: pl.Expr) -> pl.Expr:
    text = expr.cast(pl.String).str.strip_chars()
    return pl.when(text == "").then(None).otherwise(text)


def to_char(expr: pl.Expr, dtype: pl.DataType) -> pl.Expr:
    """Write a value as SDTM character text, with no float noise.

    A float keeps 15 significant digits and loses a ``.0`` end, so ``1.0``
    gives ``"1"`` and ``0.1 + 0.2`` gives ``"0.3"``.  A Date or Datetime
    gives ISO 8601 text.  Any other type is cast to ``pl.String``.

    Args:
        expr: The value expression.
        dtype: The Polars type of *expr*.

    Returns:
        pl.Expr: A ``pl.String`` expression.

    Examples:
        IDVARVAL from a Float64 AESEQ read from XPT::

            supp = ae.with_columns(to_char(pl.col("AESEQ"), pl.Float64).alias("IDVARVAL"))
    """
    if dtype.is_float():
        return expr.round_sig_figs(15).cast(pl.String).str.replace(r"\.0$", "")
    if dtype == pl.Date:
        return expr.dt.strftime("%Y-%m-%d")
    if isinstance(dtype, pl.Datetime):
        return expr.dt.strftime("%Y-%m-%dT%H:%M:%S")
    return expr.cast(pl.String)


def dtc_text(raw: pl.Expr, *, input_format: str | None = None) -> pl.Expr:
    """Convert raw text to ``--DTC`` text, or null; never guess a layout.

    A valid ISO 8601 value (SDTMIG 3.4 sections 4.4.1 to 4.4.3) stays as it
    is, partial dates included.  ``YYYY-MM-DD hh:mm`` gets its ``T``.  With
    no *input_format*, the layouts ``YYYYMMDD``, ``DD-MON-YYYY``,
    ``DD MON YYYY`` and ``DDMONYYYY`` are converted; with one, that layout
    is.  Every other value gives null, and a blank gives null.

    Args:
        raw: An expression of raw text.
        input_format: A ``strptime`` layout, e.g. ``"%m/%d/%Y"``.

    Returns:
        pl.Expr: A ``pl.String`` expression.

    Examples:
        Convert an EDC date column::

            ae = raw.with_columns(dtc_text(pl.col("ae_start")).alias("AESTDTC"))
    """
    text = _blank_to_null(raw).str.replace(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})", "${1}T${2}")
    iso = pl.when(is_iso8601(text)).then(text)
    if input_format is None:
        converted = [
            text.str.to_date(fmt, strict=False).dt.to_string("%Y-%m-%d") for fmt in _ISO_DATE_FMTS
        ]
    else:
        converted = [_formatted(text, input_format).dt.to_string(_iso_layout(input_format))]
    return pl.coalesce(iso, *converted)


def _formatted(text: pl.Expr, input_format: str) -> pl.Expr:
    if _iso_layout(input_format) == "%Y-%m-%d":
        return text.str.to_date(input_format, strict=False)
    return text.str.to_datetime(input_format, strict=False)


def _iso_layout(input_format: str) -> str:
    """The ISO 8601 layout that keeps the precision *input_format* reads."""
    if "%S" in input_format or "%T" in input_format:
        return "%Y-%m-%dT%H:%M:%S"
    if "%M" in input_format or "%R" in input_format:
        return "%Y-%m-%dT%H:%M"
    if "%H" in input_format:
        return "%Y-%m-%dT%H"
    return "%Y-%m-%d"


def guessed_values(raw: pl.Expr, *, input_format: str | None = None) -> pl.Expr:
    """True where turning *raw* into a date needs a guess the call did not state.

    With no *input_format*: a slash date or a two-digit year.  With one: a
    value it reads to a year before 1000, as ``%Y`` does with ``21``.

    Args:
        raw: An expression of raw text.
        input_format: The ``strptime`` layout of the call, if any.

    Returns:
        pl.Expr: A boolean expression.

    Examples:
        Find the rows that need a layout::

            raw.filter(guessed_values(pl.col("ae_start")))
    """
    text = _blank_to_null(raw)
    if input_format is None:
        return text.str.contains(GUESSED_SLASH) | text.str.contains(GUESSED_YEAR)
    return _formatted(text, input_format).dt.year() < 1000


def dtc_with_time(date_dtc: pl.Expr, raw_date: pl.Expr, raw_time: pl.Expr) -> pl.Expr:
    """Join ``--DTC`` date text and a collected time by SDTMIG 3.4 section 4.4.2.

    A blank time leaves the date alone.  A time is ``h[h]:mm[:ss[.f]]``,
    with the hour padded to two digits.  A partial date takes one hyphen
    for each missing component before the time (``2021-03--T08:30``,
    ``2021----T08:30``).  A time with no date gives ``-----T08:30``.  A
    time in another layout is left out (see :func:`bad_time`).

    Args:
        date_dtc: The date as ``--DTC`` text (from :func:`dtc_text`).
        raw_date: The raw date, to tell a missing date from an unreadable one.
        raw_time: The raw time.

    Returns:
        pl.Expr: A ``pl.String`` expression.

    Examples:
        Combine EXSTDAT and EXSTTIM::

            ex = raw.with_columns(
                dtc_with_time(dtc_text(pl.col("d")), pl.col("d"), pl.col("t")).alias("EXSTDTC")
            )
    """
    clock = _clock(raw_time)
    no_date = _blank_to_null(raw_date).is_null()
    with_hyphens = (
        pl.when(date_dtc.str.contains(r"^\d{4}-\d{2}$"))
        .then(date_dtc + "--")
        .when(date_dtc.str.contains(r"^\d{4}$"))
        .then(date_dtc + "----")
        .otherwise(date_dtc)
    )
    return (
        pl.when(clock.is_null())
        .then(date_dtc)
        .when(no_date)
        .then(pl.lit("-----T") + clock)
        .when(date_dtc.is_null() | date_dtc.str.contains("T"))
        .then(date_dtc)
        .otherwise(with_hyphens + pl.lit("T") + clock)
    )


def _clock(raw_time: pl.Expr) -> pl.Expr:
    """``hh:mm[:ss[.f]]`` from a raw time, or null when it is blank or not a clock time."""
    parts = _blank_to_null(raw_time).str.extract_groups(_TIME)
    hour = parts.struct.field("1").str.pad_start(2, "0")
    minute, second = parts.struct.field("2"), parts.struct.field("3")
    valid = (
        (hour.cast(pl.Int32, strict=False) <= 23)
        & (minute.is_null() | (minute.cast(pl.Int32, strict=False) <= 59))
        & (second.is_null() | (second.cast(pl.Float64, strict=False) < 60))
    )
    text = pl.concat_str(
        hour,
        pl.when(minute.is_not_null()).then(pl.lit(":") + minute).otherwise(pl.lit("")),
        pl.when(second.is_not_null()).then(pl.lit(":") + second).otherwise(pl.lit("")),
    )
    return pl.when(valid.fill_null(False)).then(text)


def bad_time(raw_time: pl.Expr) -> pl.Expr:
    """True for a time that is not blank and not a clock time (``0830``, ``UNK``, ``25:00``).

    Args:
        raw_time: The raw time.

    Returns:
        pl.Expr: A boolean expression.

    Examples:
        Count the times the EDC export holds in another layout::

            raw.select(bad_time(pl.col("t")).sum())
    """
    return _blank_to_null(raw_time).is_not_null() & _clock(raw_time).is_null()


def dtc_date_expr(source: str, target: str, *, input_format: str | None = None) -> pl.Expr:
    """Return :func:`dtc_text` of column *source*, named *target*.

    Args:
        source: Name of the input column containing date strings.
        target: Name of the output column.
        input_format: A ``strptime`` layout, or ``None``.

    Returns:
        pl.Expr: Expression producing ``--DTC`` text (``pl.String``).

    Examples:
        Convert raw dates::

            ae = raw.with_columns(dtc_date_expr("ae_start", "AESTDTC"))
    """
    return dtc_text(pl.col(source), input_format=input_format).alias(target)


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
        if isinstance(node, ast.Compare) and any(
            isinstance(side, ast.Constant) and side.value is None
            for side in (node.left, *node.comparators)
        ):
            raise DerivationError(
                f"A compare with None is always null in {expr_str!r}: use "
                "COL.is_null() or COL.is_not_null()."
            )
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

#: ``pl.<name>`` an expression string may use: expression constructors and
#: data types.  The rest of the module (``pl.read_csv``, ``pl.DataFrame``,
#: ``pl.os``) reads, writes or runs code, so it is refused.
_PL_NAMES: frozenset[str] = frozenset(
    {
        # expression constructors
        "col", "lit", "when", "len", "count", "all", "any", "sum", "mean", "min", "max",
        "median", "std", "var", "quantile", "first", "last", "n_unique", "approx_n_unique",
        "concat_str", "concat_list", "concat_arr", "coalesce", "format", "struct",
        "exclude", "element", "field", "nth", "head", "tail", "implode", "repeat",
        "int_range", "int_ranges", "date", "datetime", "duration", "time", "date_range",
        "date_ranges", "datetime_range", "datetime_ranges", "time_range", "time_ranges",
        "max_horizontal", "min_horizontal", "sum_horizontal", "mean_horizontal",
        "any_horizontal", "all_horizontal", "cum_sum", "cum_sum_horizontal", "cum_count",
        "arg_where", "arg_sort_by", "corr", "cov", "rolling_corr", "rolling_cov",
        "arctan2", "zeros", "ones", "business_day_count",
        # data types
        "Int8", "Int16", "Int32", "Int64", "Int128", "UInt8", "UInt16", "UInt32",
        "UInt64", "Float32", "Float64", "Decimal", "Boolean", "String", "Utf8", "Binary",
        "Date", "Datetime", "Duration", "Time", "Categorical", "Enum", "List", "Array",
        "Struct", "Field", "Null",
    }
)  # fmt: skip

#: Methods refused on any object: they take a callable, run a plugin,
#: format text with attribute access, or (de)serialise an expression.
_BLOCKED_METHODS: frozenset[str] = frozenset(
    {
        "deserialize",
        "format",
        "format_map",
        "inspect",
        "meta",
        "pipe",
        "plugins",
        "register_plugin",
    }
)


def _expression_methods() -> frozenset[str]:
    """Public methods of ``pl.Expr``, its namespaces and ``when``/``then`` chains."""
    expr = pl.col("x")
    when = pl.when(expr)
    chained = when.then(expr).when(expr)
    names = {n for n in dir(pl.Expr) if not n.startswith("_")}
    for namespace in ("arr", "bin", "cat", "dt", "list", "name", "str", "struct"):
        names |= {n for n in dir(getattr(expr, namespace)) if not n.startswith("_")}
    for step in (when, when.then(expr), chained, chained.then(expr)):
        names |= {n for n in dir(step) if not n.startswith("_")}
    return frozenset(n for n in names - _BLOCKED_METHODS if "map" not in n)


_EXPR_METHODS = _expression_methods()


def _check_names(tree: ast.Expression, expr_str: str) -> None:
    """Refuse a ``pl`` attribute or method that is not an expression constructor or method.

    Runs on the tree after bare names became ``pl.col(...)``.  ``pl`` may
    only appear before a dot.
    """
    pl_heads = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and id(node) not in pl_heads:
            raise DerivationError(
                f"'pl' can only start an expression such as pl.col('X'), in {expr_str!r}"
            )
        if not isinstance(node, ast.Attribute):
            continue
        on_pl = isinstance(node.value, ast.Name)
        if on_pl and node.attr not in _PL_NAMES:
            raise DerivationError(
                f"pl.{node.attr} is not allowed in expression {expr_str!r}: only Polars "
                "expression constructors (pl.col, pl.lit, pl.when, ...) and data types are."
            )
        if not on_pl and node.attr not in _EXPR_METHODS:
            raise DerivationError(
                f".{node.attr} is not allowed in expression {expr_str!r}: only methods "
                "of Polars expressions are."
            )


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


def _column_name(node: ast.AST) -> str | None:
    """Return ``X`` for a ``pl.col("X")`` call node, else ``None``."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "col"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "pl"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        return node.args[0].value
    return None


def _check_date_differences(tree: ast.AST, expr_str: str, schema: pl.Schema) -> None:
    """Refuse ``DATE2 - DATE1`` outside ``.dt``: Polars gives a Duration, not days."""
    temporal = {name for name, dtype in schema.items() if dtype in (pl.Date, pl.Datetime)}
    in_dt: set[int] = {
        id(node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "dt"
    }
    for node in ast.walk(tree):
        if not (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub)):
            continue
        left, right = _column_name(node.left), _column_name(node.right)
        if left in temporal and right in temporal and id(node) not in in_dt:
            raise DerivationError(
                f"In {expr_str!r}, {left} - {right} is a duration, not a number of days. "
                f"Write ({left} - {right}).dt.total_days() for days."
            )


def parse_expression(expr_str: str, schema: pl.Schema | None = None) -> pl.Expr:
    """Evaluate a simple Polars expression string.

    Supports column references — ``pl.col("NAME")`` or plain ``NAME`` —
    and mixed forms like ``"AVAL * 2"`` or ``"VSSTRESN > LBSTNRHI"``:
    bare names resolve to ``pl.col(name)``.  Before evaluation the string
    is checked against three allow-lists: Python syntax nodes, ``pl``
    names (expression constructors and data types) and Polars expression
    methods.  Methods that take a function, run a plugin or
    (de)serialise (``pipe``, ``map_*``, ``meta``) are refused, so a
    string in a spec cannot read files or run commands.  A ``callable:``
    or ``derivations_module:`` in a ``define.yaml`` still imports Python
    code: a spec that holds one is a program to review.

    Args:
        expr_str: The expression string to parse.
        schema: The frame schema.  When given, a difference of two Date
            or Datetime columns outside ``.dt`` (``TRTEDT - TRTSDT > 10``)
            is refused: Polars gives a Duration, so ``> 10`` would compare
            with 10 microseconds, not 10 days as in SAS.

    Returns:
        pl.Expr: The parsed Polars expression.

    Raises:
        DerivationError: On syntax errors, disallowed constructs, a date
            difference outside ``.dt`` (with *schema*), or input that does
            not produce a ``pl.Expr``.  Also catchable as ``ValueError``.

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
    _check_names(tree, expr_str)
    if schema is not None:
        _check_date_differences(tree, expr_str, schema)
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
