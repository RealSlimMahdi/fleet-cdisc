"""Compile grading criteria (Pydantic models) into Polars expressions.

Translates the structured JSON DSL for CTCAE / DAIDS toxicity grading into
``pl.when / .then / .otherwise`` expression chains that can be applied to a
Polars DataFrame in a single pass per lab term.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import polars as pl

from ._models import (
    BranchCondition,
    ComparisonRule,
    GradeRule,
    TermCriteria,
)

if TYPE_CHECKING:
    from ._models import CriteriaFile

# ---------------------------------------------------------------------------
# Operator map
# ---------------------------------------------------------------------------

_OPS: dict[str, str] = {"lt": "__lt__", "gt": "__gt__", "le": "__le__", "ge": "__ge__"}

# ---------------------------------------------------------------------------
# Significant-figures helper
# ---------------------------------------------------------------------------


def _sig(col: str, dig: int) -> pl.Expr:
    """Round a column to *dig* significant figures for safe comparison.

    Args:
        col: Column name.
        dig: Number of significant figures.  ``<= 0`` returns the raw column.

    Returns:
        pl.Expr: Rounded expression.
    """
    c = pl.col(col)
    if dig <= 0:
        return c
    return c.round_sig_figs(dig)


def _sig_expr(expr: pl.Expr, dig: int) -> pl.Expr:
    """Apply significant-figure rounding to an arbitrary expression."""
    if dig <= 0:
        return expr
    return expr.round_sig_figs(dig)


# ---------------------------------------------------------------------------
# Low-level expression builders
# ---------------------------------------------------------------------------


def _compile_right_expr(expr_dict: dict, dig: int) -> pl.Expr:
    """Build a Polars expression from a ``right_expr`` dictionary.

    Currently supports ``{"multiply": [col_name, factor]}``.

    Args:
        expr_dict: Expression specification from the criteria JSON.
        dig: Significant-figures precision.

    Returns:
        pl.Expr: The computed threshold expression.

    Raises:
        ValueError: If the expression type is not supported.
    """
    if "multiply" in expr_dict:
        col_name, factor = expr_dict["multiply"]
        return _sig_expr(pl.col(col_name) * factor, dig)
    msg = f"Unsupported right_expr type: {expr_dict!r}"
    raise ValueError(msg)


def _compile_comparison(rule: ComparisonRule, dig: int) -> pl.Expr:
    """Translate a single ``ComparisonRule`` into a boolean Polars expression.

    Args:
        rule: The comparison to compile.
        dig: Significant-figures precision.

    Returns:
        pl.Expr: Boolean expression (``True`` when the comparison holds).
    """
    lhs = _sig(rule.left, dig)
    op = _OPS[rule.op]

    if rule.right is not None:
        return getattr(lhs, op)(rule.right)
    if rule.right_var is not None:
        return getattr(lhs, op)(_sig(rule.right_var, dig))
    # right_expr is guaranteed non-None by the model validator.
    assert rule.right_expr is not None
    return getattr(lhs, op)(_compile_right_expr(rule.right_expr, dig))


def _compile_branch_condition(
    cond: BranchCondition,
    indicators: dict[str, list[str]],
) -> pl.Expr:
    """Build a boolean expression from a ``BranchCondition``.

    Args:
        cond: The branch predicate.
        indicators: Mapping of indicator parameter names to their member
            values (e.g. ``{"high_indicator": ["HIGH", "H"]}``).

    Returns:
        pl.Expr: Boolean expression for the indicator check.

    Raises:
        KeyError: If the referenced indicator parameter is not in *indicators*.
    """
    if cond.in_values is not None:
        values = indicators[cond.in_values]
        return pl.col(cond.var).is_in(values)
    assert cond.not_in_values is not None
    values = indicators[cond.not_in_values]
    return ~pl.col(cond.var).is_in(values)


# ---------------------------------------------------------------------------
# Grade-level expression
# ---------------------------------------------------------------------------


def _compile_grade_rule(
    grade: GradeRule,
    dig: int,
    indicators: dict[str, list[str]],
) -> pl.Expr:
    """Build the boolean condition for a single grade level.

    Direct ``rules`` are combined with OR (any rule match → this grade).
    ``branches`` produce ``(indicator_cond & comparison_cond)`` per branch,
    also combined with OR.

    Args:
        grade: The grade-level rule set.
        dig: Significant-figures precision.
        indicators: Indicator parameter map (see ``_compile_branch_condition``).

    Returns:
        pl.Expr: Boolean — ``True`` when the row qualifies for this grade.
    """
    parts: list[pl.Expr] = []

    if grade.rules:
        for rule in grade.rules:
            parts.append(_compile_comparison(rule, dig))

    if grade.branches:
        for branch in grade.branches:
            cond = _compile_branch_condition(branch.when, indicators)
            comp = _compile_comparison(branch.then, dig)
            parts.append(cond & comp)

    assert parts, f"GradeRule for grade {grade.grade} produced no conditions"
    result = parts[0]
    for p in parts[1:]:
        result = result | p
    return result


# ---------------------------------------------------------------------------
# Term-level expression chain
# ---------------------------------------------------------------------------


def compile_term_expr(
    criteria: TermCriteria,
    *,
    signif_dig: int = 5,
    indicators: dict[str, list[str]] | None = None,
) -> pl.Expr:
    """Compile a ``TermCriteria`` into a Polars ``when/then/otherwise`` chain.

    Evaluation order mirrors Admiral:
    1. Global NA check (any ``na_check`` column null → ``null``).
    2. Grade 4 → Grade 3 → Grade 2 → Grade 1, each with optional
       per-grade ``na_guard``.
    3. Otherwise → ``"0"`` (gradable, within normal range).

    Args:
        criteria: The grading criteria for one lab term.
        signif_dig: Significant figures for floating-point comparison.
        indicators: Indicator parameter map used by branch conditions.

    Returns:
        pl.Expr: Expression that produces a Utf8 grade column
            (``"0"``–``"4"`` or ``null``).

    Examples:
        Compile criteria for a single term::

            expr = compile_term_expr(term_criteria, signif_dig=5)
            df = df.with_columns(expr.alias("ATOXGR"))
    """
    ind = indicators or {}
    # Sort grades descending (4, 3, 2, 1) so we evaluate highest first.
    sorted_grades = sorted(criteria.grades, key=lambda g: g.grade, reverse=True)

    # Start building the chain.  We'll nest when/then pairs.
    # Step 1: global NA check.
    chain: pl.Expr | None = None

    if criteria.na_check:
        null_cond = pl.lit(False)
        for col in criteria.na_check:
            null_cond = null_cond | pl.col(col).is_null()
        chain = pl.when(null_cond).then(pl.lit(None, dtype=pl.Utf8))

    # Step 2-5: grade rules in descending order.
    for grade_rule in sorted_grades:
        # Per-grade NA guard: null in any guard column → null for this grade.
        if grade_rule.na_guard:
            guard_cond = pl.lit(False)
            for col in grade_rule.na_guard:
                guard_cond = guard_cond | pl.col(col).is_null()
            if chain is None:
                chain = pl.when(guard_cond).then(pl.lit(None, dtype=pl.Utf8))
            else:
                chain = chain.when(guard_cond).then(pl.lit(None, dtype=pl.Utf8))

        grade_cond = _compile_grade_rule(grade_rule, signif_dig, ind)
        grade_str = pl.lit(str(grade_rule.grade))

        if chain is None:
            chain = pl.when(grade_cond).then(grade_str)
        else:
            chain = chain.when(grade_cond).then(grade_str)

    # Step 6: otherwise → "0".
    if chain is None:
        return pl.lit("0")
    return chain.otherwise(pl.lit("0"))


# ---------------------------------------------------------------------------
# Filter-expression parser
# ---------------------------------------------------------------------------

_AGE_PATTERN = re.compile(
    r"age_(days|months|years)\(\s*(\w+)\s*,\s*(\w+)\s*\)"
    r"\s*(==|!=|<=|>=|<|>)\s*"
    r"([0-9.]+)"
)

_STR_EQ_PATTERN = re.compile(r"(\w+)\s*==\s*'([^']*)'")

_COMPARE_OPS: dict[str, str] = {
    "==": "__eq__",
    "!=": "__ne__",
    "<": "__lt__",
    ">": "__gt__",
    "<=": "__le__",
    ">=": "__ge__",
}

_AGE_DIVISORS: dict[str, float] = {
    "days": 1.0,
    "months": 30.4375,
    "years": 365.25,
}


def _compile_age_atom(match: re.Match) -> pl.Expr:  # type: ignore[type-arg]
    """Build a Polars expression for an ``age_*(COL1, COL2) OP VALUE`` atom."""
    unit, birth_col, ref_col, op_str, value_str = match.groups()
    diff_days = (pl.col(ref_col) - pl.col(birth_col)).dt.total_days()
    divisor = _AGE_DIVISORS[unit]
    age_expr = diff_days if divisor == 1.0 else diff_days / divisor
    return getattr(age_expr, _COMPARE_OPS[op_str])(float(value_str))


def _compile_str_eq_atom(match: re.Match) -> pl.Expr:  # type: ignore[type-arg]
    """Build ``pl.col(COL) == "VALUE"``."""
    col, value = match.groups()
    return pl.col(col) == value


def _compile_filter_atom(atom: str) -> pl.Expr:
    """Compile a single filter atom (no ``&`` connective)."""
    atom = atom.strip()

    age_match = _AGE_PATTERN.fullmatch(atom)
    if age_match:
        return _compile_age_atom(age_match)

    str_match = _STR_EQ_PATTERN.fullmatch(atom)
    if str_match:
        return _compile_str_eq_atom(str_match)

    msg = f"Unsupported filter expression atom: {atom!r}"
    raise ValueError(msg)


def compile_filter_expr(filter_str: str) -> pl.Expr:
    """Parse a simplified DSL filter string into a Polars boolean expression.

    Supports ``age_days``, ``age_months``, ``age_years`` helpers, string
    equality checks, and ``&`` (AND) connectives.

    Args:
        filter_str: The filter expression string from the criteria JSON.

    Returns:
        pl.Expr: Boolean expression suitable for ``df.filter()``.

    Raises:
        ValueError: If any atom cannot be parsed.

    Examples:
        Parse a compound DAIDS age filter::

            expr = compile_filter_expr("age_days(BRTHDT, ADT) > 28")
    """
    parts = [p.strip() for p in filter_str.split("&")]
    compiled = _compile_filter_atom(parts[0])
    for part in parts[1:]:
        compiled = compiled & _compile_filter_atom(part)
    return compiled


# ---------------------------------------------------------------------------
# Dataset-level grading
# ---------------------------------------------------------------------------


def grade_term(
    df: pl.DataFrame,
    criteria: TermCriteria,
    *,
    target: str,
    signif_dig: int = 5,
    indicators: dict[str, list[str]] | None = None,
) -> pl.DataFrame:
    """Apply grading for a single lab term to rows in *df*.

    Rows are assumed to already be filtered to the matching term. If the
    criteria specify a ``filter_expr``, rows not matching the filter receive
    ``null`` in *target*.

    Args:
        df: Input data (already scoped to one term).
        criteria: Grading criteria for the term.
        target: Name of the output grade column.
        signif_dig: Significant figures for comparison.
        indicators: Indicator parameter map for branch conditions.

    Returns:
        pl.DataFrame: *df* with the *target* column populated.

    Examples:
        Grade a single term's rows::

            graded = grade_term(dm_rows, anemia_criteria, target="ATOXGR")
    """
    expr = compile_term_expr(criteria, signif_dig=signif_dig, indicators=indicators)

    if criteria.filter_expr is not None:
        filt = compile_filter_expr(criteria.filter_expr)
        # Rows passing the filter get the grade; others get null.
        expr = pl.when(filt).then(expr).otherwise(pl.lit(None, dtype=pl.Utf8))

    return df.with_columns(expr.alias(target))


def grade_dataset(
    df: pl.DataFrame,
    criteria_file: CriteriaFile,
    *,
    target: str,
    direction: str,
    term_var: str,
    unit_var: str | None = None,
    signif_dig: int = 5,
    indicators: dict[str, list[str]] | None = None,
) -> pl.DataFrame:
    """Apply toxicity grading for all matching terms in a dataset.

    For each distinct term in *term_var*, the corresponding
    ``TermCriteria`` is looked up (case-insensitive) and applied.  Rows
    with no matching criteria receive ``null`` in *target*.

    Args:
        df: Full lab dataset.
        criteria_file: Loaded and validated criteria file.
        target: Name of the output grade column.
        direction: ``"L"`` or ``"H"`` — only criteria matching this
            direction are considered.
        term_var: Column holding the lab-test / term name.
        unit_var: Optional column holding the unit of measure.  When
            provided and the criteria specify a unit, rows with a
            mismatched unit are skipped.
        signif_dig: Significant figures for comparison.
        indicators: Indicator parameter map for branch conditions.

    Returns:
        pl.DataFrame: *df* with the *target* column added.

    Examples:
        Grade all high-direction terms::

            graded = grade_dataset(
                adlb, criteria, target="ATOXGRH",
                direction="H", term_var="PARAMCD",
            )
    """
    # Build a lookup: lowercase term → TermCriteria (filtered by direction).
    criteria_by_term: dict[str, TermCriteria] = {}
    for tc in criteria_file.criteria:
        if tc.direction == direction:
            criteria_by_term[tc.term.lower()] = tc

    if not criteria_by_term:
        return df.with_columns(pl.lit(None, dtype=pl.Utf8).alias(target))

    # Distinct terms present in data.
    distinct_terms: list[str] = (
        df.select(pl.col(term_var).unique()).to_series().drop_nulls().to_list()
    )

    graded_parts: list[pl.DataFrame] = []
    unmatched_mask = pl.lit(True)

    for data_term in distinct_terms:
        tc = criteria_by_term.get(data_term.lower())
        if tc is None:
            continue

        # Unit validation: skip rows where unit does not match criteria.
        # fill_null(False) so that null term/unit values don't poison the mask.
        term_cond = (pl.col(term_var) == data_term).fill_null(False)
        if unit_var is not None and tc.unit is not None:
            term_cond = term_cond & (pl.col(unit_var) == tc.unit).fill_null(False)

        term_rows = df.filter(term_cond)
        if term_rows.height == 0:
            continue

        graded_chunk = grade_term(
            term_rows,
            tc,
            target=target,
            signif_dig=signif_dig,
            indicators=indicators,
        )
        graded_parts.append(graded_chunk)
        unmatched_mask = unmatched_mask & ~term_cond

    # Rows with no matching criteria.
    unmatched = df.filter(unmatched_mask).with_columns(
        pl.lit(None, dtype=pl.Utf8).alias(target),
    )
    graded_parts.append(unmatched)

    return pl.concat(graded_parts, how="diagonal_relaxed")


# ---------------------------------------------------------------------------
# Combine low/high grades
# ---------------------------------------------------------------------------


def combine_grades_expr(
    low_var: str,
    high_var: str,
    *,
    low_desc_var: str | None = None,
    high_desc_var: str | None = None,
) -> pl.Expr:
    """Build a Polars expression that merges low and high toxicity grades.

    Logic follows Admiral conventions:

    * Both ``null`` → ``null``
    * Low grade ≥ ``"1"`` → prefix with ``"-"`` (e.g. ``"3"`` → ``"-3"``).
    * High grade ≥ ``"1"`` → keep as-is.
    * Low ``"0"`` and (high ``"0"`` or high description missing) → ``"0"``.
    * High ``"0"`` and (low ``"0"`` or low description missing) → ``"0"``.
    * Otherwise → ``null``.

    When neither ``low_desc_var`` nor ``high_desc_var`` are provided the
    "description missing" legs are skipped.

    Args:
        low_var: Column name for the low-direction grade.
        high_var: Column name for the high-direction grade.
        low_desc_var: Optional column for the low-grade term description.
        high_desc_var: Optional column for the high-grade term description.

    Returns:
        pl.Expr: Utf8 expression producing the combined ATOXGR value.

    Examples:
        Combine low/high into ATOXGR::

            df = df.with_columns(
                combine_grades_expr("ATOXGRL", "ATOXGRH").alias("ATOXGR")
            )
    """
    low = pl.col(low_var)
    high = pl.col(high_var)

    both_null = low.is_null() & high.is_null()
    low_graded = low.is_not_null() & (low >= pl.lit("1"))
    high_graded = high.is_not_null() & (high >= pl.lit("1"))

    # "0" on one side while the other side is "0" or has no grading criteria.
    low_zero = low == pl.lit("0")
    high_zero = high == pl.lit("0")

    high_absent = high.is_null()
    low_absent = low.is_null()
    if high_desc_var is not None:
        high_absent = high_absent | pl.col(high_desc_var).is_null()
    if low_desc_var is not None:
        low_absent = low_absent | pl.col(low_desc_var).is_null()

    zero_cond = (low_zero & (high_zero | high_absent)) | (high_zero & (low_zero | low_absent))

    return (
        pl.when(both_null)
        .then(pl.lit(None, dtype=pl.Utf8))
        .when(low_graded)
        .then(pl.lit("-") + low)
        .when(high_graded)
        .then(high)
        .when(zero_cond)
        .then(pl.lit("0"))
        .otherwise(pl.lit(None, dtype=pl.Utf8))
    )
