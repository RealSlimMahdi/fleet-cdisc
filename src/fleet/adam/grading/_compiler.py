"""Apply grading criteria (Pydantic models) to a Polars frame.

Each term becomes one ``pl.when`` chain over its ``case_when`` arms, and the
whole dataset is graded in one ``with_columns``, so every input row stays,
in its order.  The rules follow admiral ``derive_var_atoxgr_dir``.
"""

from __future__ import annotations

import json
import warnings
from typing import TYPE_CHECKING

import polars as pl

from fleet.adam.grading._expr import compile_node, node_names
from fleet.core.exceptions import DerivationError

if TYPE_CHECKING:
    from fleet.adam.grading._models import CriteriaFile, TermCriteria

_NULL = pl.lit(None, dtype=pl.String)


def compile_term_expr(
    criteria: TermCriteria,
    *,
    signif_dig: int = 15,
    indicators: dict[str, list[str]] | None = None,
) -> pl.Expr:
    """Compile a term's ``case_when`` arms into a ``pl.when`` chain.

    The first arm whose condition holds gives the grade; a null condition
    counts as false, as in R ``case_when``; no arm gives null.

    Args:
        criteria: The criteria of one term (one unit and subgroup).
        signif_dig: Significant digits for R ``signif`` (admiral default 15).
        indicators: Values of each indicator param (e.g. ``high_indicator``).

    Returns:
        pl.Expr: String grade ``"0"`` to ``"4"``, or null.

    Examples:
        Grade one term::

            expr = compile_term_expr(term_criteria)
            df = df.with_columns(expr.alias("ATOXGRL"))
    """
    chain = None
    for arm in criteria.arms:
        cond = compile_node(arm.when, signif_dig=signif_dig, indicators=indicators or {})
        grade = pl.lit(arm.then, dtype=pl.String)
        chain = pl.when(cond).then(grade) if chain is None else chain.when(cond).then(grade)
    return _NULL if chain is None else chain.otherwise(_NULL)


def compile_filter_expr(node: object) -> pl.Expr:
    """Compile a population filter (expression tree) into a boolean expression.

    Args:
        node: The ``filter`` tree of a term (e.g. a DAIDS age band).

    Returns:
        pl.Expr: Boolean expression.

    Examples:
        Adults by calendar age::

            expr = compile_filter_expr(
                {"op": "ge", "args": [{"op": "age", "unit": "years",
                 "args": [{"var": "BRTHDT"}, {"var": "ADT"}]}, 18]}
            )
    """
    return compile_node(node, signif_dig=0, indicators={})


def _unit_match(unit_var: str | None, unit: str | None) -> pl.Expr:
    if unit_var is None or unit is None:
        return pl.lit(True)
    return pl.col(unit_var).cast(pl.String).str.to_uppercase() == unit.upper()


def _term_expr(
    entries: list[TermCriteria],
    *,
    unit_var: str | None,
    signif_dig: int,
    indicators: dict[str, list[str]],
) -> pl.Expr:
    """One term: the first filter that holds picks its entries, then the unit picks one."""
    groups: dict[str, list[TermCriteria]] = {}
    for entry in entries:
        groups.setdefault(json.dumps(entry.filter, sort_keys=True), []).append(entry)

    chain = None
    for members in groups.values():
        unit_chain = None
        for entry in members:
            grade = compile_term_expr(entry, signif_dig=signif_dig, indicators=indicators)
            cond = _unit_match(unit_var, entry.unit)
            unit_chain = (
                pl.when(cond).then(grade)
                if unit_chain is None
                else unit_chain.when(cond).then(grade)
            )
        assert unit_chain is not None
        graded = unit_chain.otherwise(_NULL)
        if members[0].filter is None:
            return graded if chain is None else chain.otherwise(graded)
        filt = compile_filter_expr(members[0].filter)
        if chain is None:
            chain = pl.when(filt.is_null()).then(_NULL).when(filt).then(graded)
        else:
            chain = chain.when(filt.is_null()).then(_NULL).when(filt).then(graded)
    assert chain is not None
    return chain.otherwise(_NULL)


def grade_dataset(
    df: pl.DataFrame,
    criteria_file: CriteriaFile,
    *,
    target: str,
    direction: str,
    term_var: str,
    unit_var: str | None = None,
    signif_dig: int = 15,
    indicators: dict[str, list[str]] | None = None,
) -> pl.DataFrame:
    """Grade every row of *df* whose term has criteria in *direction*.

    As admiral ``derive_var_atoxgr_dir``: the term matches without case; of
    a term's entries, the first population filter that holds is used (a
    null filter gives a null grade), then the entry whose unit matches the
    row's unit without case.  A row with another unit, a null unit or no
    entry gets a null grade.  Every row stays, in its order.

    Args:
        df: Lab dataset.
        criteria_file: Loaded criteria.
        target: Output grade column.
        direction: ``"L"`` or ``"H"``.
        term_var: Column with the term (e.g. ``"ATOXDSCL"``).
        unit_var: Column with the unit.  May be ``None`` only when each term
            has criteria for one unit.
        signif_dig: Significant digits for R ``signif`` (admiral default 15).
        indicators: Values of each indicator param (e.g. ``high_indicator``).

    Returns:
        pl.DataFrame: *df* with *target* added.

    Raises:
        DerivationError: When *direction* is not ``"L"`` or ``"H"``,
            *signif_dig* is not a positive integer, a term has criteria for
            several units and *unit_var* is ``None``, or a column the
            criteria need is missing.

    Warns:
        UserWarning: Once per term, with the count of rows whose unit
            matches no criteria entry of the term (their grade is null).
            Once per call, with the terms that have no criteria in any
            direction.

    Examples:
        Grade the high direction::

            graded = grade_dataset(
                adlb, criteria, target="ATOXGRH", direction="H",
                term_var="ATOXDSCH", unit_var="AVALU",
            )
    """
    if direction not in ("L", "H"):
        raise DerivationError(
            f"atoxgr: direction={direction!r} is not supported. Use 'L' (low) or 'H' (high)."
        )
    if isinstance(signif_dig, bool) or not isinstance(signif_dig, int) or signif_dig < 1:
        raise DerivationError(
            f"atoxgr: signif_dig={signif_dig!r} is not supported. Give a positive integer "
            "(admiral default 15)."
        )
    by_term: dict[str, list[TermCriteria]] = {}
    for entry in criteria_file.criteria:
        if entry.direction == direction:
            by_term.setdefault(entry.term.upper(), []).append(entry)

    data_terms = df.get_column(term_var).cast(pl.String).drop_nulls().unique().sort().to_list()
    known = {e.term.upper() for e in criteria_file.criteria}
    unknown = [t for t in data_terms if t.upper() not in known]
    if unknown:
        more = f" (+{len(unknown) - 10} more)" if len(unknown) > 10 else ""
        warnings.warn(
            f"atoxgr: {len(unknown)} {term_var} value(s) have no criteria in any direction, "
            f"so their grade is null: {unknown[:10]}{more}. The term must be a criteria "
            "term (ATOXDSCL or ATOXDSCH), not a PARAMCD.",
            stacklevel=3,
        )
    ind = indicators or {}
    chain = None
    for data_term in data_terms:
        entries = by_term.get(data_term.upper())
        if not entries:
            continue
        units = {e.unit.upper() for e in entries if e.unit is not None}
        if unit_var is None and len(units) > 1:
            raise DerivationError(
                f"atoxgr: '{data_term}' has criteria for the units {sorted(units)}. "
                "Pass unit_var= so each row is graded with the cut-offs of its own unit."
            )
        needed = set()
        for e in entries:
            needed |= set(e.required_vars) | node_names(e.filter, "var")
            if unit_var is not None and e.unit is not None:
                needed.add(unit_var)
        missing = sorted(needed - set(df.columns))
        if missing:
            raise DerivationError(f"atoxgr: '{data_term}' needs the column(s) {missing}.")
        cond = pl.col(term_var).cast(pl.String) == data_term
        if unit_var is not None and units and None not in {e.unit for e in entries}:
            row_unit = pl.col(unit_var).cast(pl.String).str.to_uppercase()
            n_other = df.select((cond & ~row_unit.is_in(sorted(units)).fill_null(False)).sum())
            if n_other.item():
                warnings.warn(
                    f"atoxgr: {n_other.item()} '{data_term}' row(s) have a {unit_var} that is "
                    f"not one of the criteria units {sorted(units)}; their grade is null.",
                    stacklevel=3,
                )
        term_expr = _term_expr(entries, unit_var=unit_var, signif_dig=signif_dig, indicators=ind)
        chain = pl.when(cond).then(term_expr) if chain is None else chain.when(cond).then(term_expr)

    grade = _NULL if chain is None else chain.otherwise(_NULL)
    return df.with_columns(grade.alias(target))


# ---------------------------------------------------------------------------
# Combine low/high grades
# ---------------------------------------------------------------------------


def combine_grades_expr(
    low_var: str,
    high_var: str,
    *,
    low_desc_var: str,
    high_desc_var: str,
) -> pl.Expr:
    """Build a Polars expression that merges low and high toxicity grades.

    Logic follows admiral ``derive_var_atoxgr``:

    * Both ``null`` → ``null``
    * Low grade ≥ ``"1"`` → prefix with ``"-"`` (e.g. ``"3"`` → ``"-3"``).
    * High grade ≥ ``"1"`` → keep as-is.
    * (Low ``"0"`` or low description null) and (high ``"0"`` or high
      description null) → ``"0"``.
    * Otherwise → ``null``: for example low ``"0"`` and high null while the
      high description is present (the high grade is unknown).

    Args:
        low_var: Column name for the low-direction grade.
        high_var: Column name for the high-direction grade.
        low_desc_var: Column for the low-grade term description.
        high_desc_var: Column for the high-grade term description.

    Returns:
        pl.Expr: Utf8 expression producing the combined ATOXGR value.

    Examples:
        Combine low/high into ATOXGR::

            df = df.with_columns(
                combine_grades_expr(
                    "ATOXGRL", "ATOXGRH",
                    low_desc_var="ATOXDSCL", high_desc_var="ATOXDSCH",
                ).alias("ATOXGR")
            )
    """
    low = pl.col(low_var)
    high = pl.col(high_var)

    both_null = low.is_null() & high.is_null()
    low_graded = low.is_not_null() & (low >= pl.lit("1"))
    high_graded = high.is_not_null() & (high >= pl.lit("1"))

    low_ok = (low == pl.lit("0")) | pl.col(low_desc_var).is_null()
    high_ok = (high == pl.lit("0")) | pl.col(high_desc_var).is_null()

    return (
        pl.when(both_null)
        .then(pl.lit(None, dtype=pl.Utf8))
        .when(low_graded)
        .then(pl.lit("-") + low)
        .when(high_graded)
        .then(high)
        .when(low_ok & high_ok)
        .then(pl.lit("0"))
        .otherwise(pl.lit(None, dtype=pl.Utf8))
    )
