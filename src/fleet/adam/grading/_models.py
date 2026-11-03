"""Pydantic models for the CTCAE / DAIDS toxicity-grading criteria files.

A criteria file (schema version 2) holds, for each term, the ordered arms of
an R ``case_when``: the first arm whose condition holds gives the grade, and
no arm gives null.  ``scripts/regen_grading_criteria.R`` writes the bundled
files from the admiral metadata; each term keeps the admiral text under
``source``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from fleet.adam.grading._expr import validate_node

SCHEMA_VERSION = 2


class Arm(BaseModel):
    """One arm of a term's ``case_when``.

    Args:
        when: Condition (expression tree, or ``true``).
        then: Grade ``"0"`` to ``"4"``, or ``None`` for a null grade.
    """

    model_config = ConfigDict(frozen=True)

    when: Any
    then: Literal["0", "1", "2", "3", "4"] | None

    @model_validator(mode="after")
    def _check_when(self) -> Arm:
        validate_node(self.when, "when")
        return self


class TermCriteria(BaseModel):
    """Grading criteria for one term, direction, unit and subgroup.

    Args:
        term: Term name (e.g. ``"Anemia"``); matched without case.
        direction: ``"L"`` for low, ``"H"`` for high.
        unit: Unit the cut-offs assume (matched without case), or ``None``.
        required_vars: Columns the arms read.
        subgroup: Population label (DAIDS), or ``None``.
        filter: Population condition (expression tree), or ``None``.
        arms: Ordered ``case_when`` arms; an empty list grades null.
        source: The admiral text the arms come from.
    """

    model_config = ConfigDict(frozen=True)

    term: str
    direction: Literal["L", "H"]
    unit: str | None = None
    required_vars: list[str]
    subgroup: str | None = None
    filter: Any = None
    arms: list[Arm]
    source: dict[str, str | None] | None = None

    @model_validator(mode="after")
    def _check_filter(self) -> TermCriteria:
        if self.filter is not None:
            validate_node(self.filter, f"{self.term}.filter")
        return self


class CriteriaFile(BaseModel):
    """Top-level structure of a grading-criteria file.

    Args:
        schema_version: Format version; must be ``2``.
        version: Criteria standard (e.g. ``"ctcae_v5"``).
        unit_system: ``"SI"`` or ``"USCV"`` (US conventional).
        source: Provenance (package, version, dataset, generator).
        criteria: Per-term criteria.
    """

    model_config = ConfigDict(frozen=True)

    schema_version: Literal[2]
    version: str
    unit_system: Literal["SI", "USCV"]
    source: dict[str, str] | None = None
    criteria: list[TermCriteria]
