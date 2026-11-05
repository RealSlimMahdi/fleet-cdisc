"""SDTM data models: the metadata of a Non-Standard Variable.

The spec-executable verbs and their variable models live in
:mod:`fleet.core.spec_registry` (ADR-0008).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NSVMeta:
    """Metadata for a Non-Standard Variable (qualifier)."""

    target: str
    label: str
    origin: str = "Derived"
    evaluator: str | None = None
