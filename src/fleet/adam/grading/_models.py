"""Pydantic data models for CTCAE / DAIDS toxicity-grading criteria.

Grading criteria are stored as JSON files with a structured DSL that
describes how to map laboratory values to NCI-CTCAE or DAIDS grade
levels.  These models validate the JSON structure at load time so that
the grading engine can trust its inputs unconditionally.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

# -- Low-level rule atoms -------------------------------------------------


class ComparisonRule(BaseModel):
    """A single numeric comparison against a column value.

    Exactly one of ``right``, ``right_var``, or ``right_expr`` must be
    provided to define what the *left* column is compared against.

    Args:
        left: Column name used as the left-hand operand (e.g. ``"AVAL"``).
        op: Comparison operator.
        right: Literal numeric threshold.
        right_var: Column name for a variable-to-variable comparison.
        right_expr: Expression dict for computed thresholds, e.g.
            ``{"multiply": ["ANRHI", 20]}``.
    """

    model_config = ConfigDict(frozen=True)

    left: str
    op: Literal["lt", "gt", "le", "ge"]
    right: float | None = None
    right_var: str | None = None
    right_expr: dict | None = None

    @model_validator(mode="after")
    def _exactly_one_rhs(self) -> ComparisonRule:
        """Ensure exactly one right-hand side is specified."""
        count = sum(v is not None for v in (self.right, self.right_var, self.right_expr))
        if count != 1:
            msg = f"Exactly one of 'right', 'right_var', or 'right_expr' must be set, got {count}"
            raise ValueError(msg)
        return self


class BranchCondition(BaseModel):
    """Indicator-variable predicate used to select a grading branch.

    Exactly one of ``in_values`` or ``not_in_values`` must be provided.

    Args:
        var: Indicator column name (e.g. ``"BNRIND"``).
        in_values: Parameter name whose values the indicator must match.
        not_in_values: Parameter name whose values the indicator must
            *not* match.
    """

    model_config = ConfigDict(frozen=True)

    var: str
    in_values: str | None = None
    not_in_values: str | None = None

    @model_validator(mode="after")
    def _exactly_one_direction(self) -> BranchCondition:
        """Ensure exactly one of in_values / not_in_values is set."""
        count = sum(v is not None for v in (self.in_values, self.not_in_values))
        if count != 1:
            msg = f"Exactly one of 'in_values' or 'not_in_values' must be set, got {count}"
            raise ValueError(msg)
        return self


class BranchRule(BaseModel):
    """Conditional grading: apply a comparison only when an indicator matches.

    Args:
        when: The indicator predicate that activates this branch.
        then: The comparison to evaluate when *when* is satisfied.
    """

    model_config = ConfigDict(frozen=True)

    when: BranchCondition
    then: ComparisonRule


# -- Grade-level aggregation -----------------------------------------------


class GradeRule(BaseModel):
    """Rules that determine a single grade level.

    At least one of ``rules`` or ``branches`` must be provided.  When both
    are present, ``branches`` (indicator-dependent) take precedence.

    Args:
        grade: Integer grade level (typically 1–4).
        rules: Direct comparison rules evaluated in order (first match wins).
        branches: Indicator-dependent rules keyed on a branch condition.
        na_guard: Columns where a NULL value means this grade is NULL.
    """

    model_config = ConfigDict(frozen=True)

    grade: int
    rules: list[ComparisonRule] | None = None
    branches: list[BranchRule] | None = None
    na_guard: list[str] | None = None

    @model_validator(mode="after")
    def _at_least_one_rule_source(self) -> GradeRule:
        """Ensure at least one grading mechanism is present."""
        if not self.rules and not self.branches:
            msg = "At least one of 'rules' or 'branches' must be set"
            raise ValueError(msg)
        return self


# -- Term / file-level structures ------------------------------------------


class TermCriteria(BaseModel):
    """Complete grading criteria for a single lab parameter / adverse event.

    Args:
        term: Human-readable lab test description (e.g. ``"Anemia"``).
        direction: ``"L"`` for low abnormality, ``"H"`` for high.
        unit: Expected unit of measure (e.g. ``"g/L"``).  Optional.
        required_vars: Columns that must exist in the input data.
        na_check: Columns where NULL → the final grade is NULL.
            Applied before any grade evaluation.
        grades: Grade rules ordered by grade (highest first).
        filter_expr: Population filter expression (DAIDS only).
        subgroup: Human-readable subgroup description.
    """

    model_config = ConfigDict(frozen=True)

    term: str
    direction: Literal["L", "H"]
    unit: str | None = None
    required_vars: list[str]
    na_check: list[str] | None = None
    grades: list[GradeRule]
    filter_expr: str | None = None
    subgroup: str | None = None


class CriteriaFile(BaseModel):
    """Top-level JSON structure for a grading-criteria file.

    Args:
        version: Criteria standard identifier (e.g. ``"ctcae_v5"``).
        unit_system: ``"SI"`` or ``"USCV"`` (US conventional).
        criteria: List of per-term grading criteria.
    """

    model_config = ConfigDict(frozen=True)

    version: str
    unit_system: Literal["SI", "USCV"]
    criteria: list[TermCriteria]
