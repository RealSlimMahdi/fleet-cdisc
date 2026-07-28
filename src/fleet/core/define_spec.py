"""Validated envelope model for define.yaml / simplified spec files.

Fleet already validates the *derivation* half of a spec through the
algorithm registry (:mod:`fleet.core.spec_registry`).  This module covers
the other half — the envelope around it: top-level keys, dataset entries,
and variable metadata.  Without it a typo like ``datsets:`` parses fine,
matches nothing, and ``from_spec()`` silently returns the input frame.

Every reader that *executes* a spec (``from_spec``, ``build_dag``, NSV
metadata resolution) goes through :func:`load_define_spec`, so the format
is interpreted in exactly one place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from fleet.core.exceptions import SpecError


class CTBlock(BaseModel):
    """Top-level ``ct:`` block — opts a spec into CT validation."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    #: ``validate:`` in YAML — renamed because ``validate`` is taken on BaseModel.
    enabled: bool = Field(default=False, alias="validate")
    file: str | None = None


class VariableEntry(BaseModel):
    """One entry in a dataset's ``variables:`` list.

    Only the keys Fleet's execution path reads are declared; the rest of
    the define metadata (``length``, ``mandatory``, ``codelist``, …) is
    carried through untouched.
    """

    # ponytail: extra="allow" — define metadata varies by standard and is
    # type-checked by the JSON schema in the define_xml path.  Strictness
    # that matters here is `name` being present and the *derivation* block,
    # which the algorithm registry validates with extra="forbid".
    model_config = ConfigDict(extra="allow")

    name: str
    type: str | None = None
    label: str | None = None
    origin: str | None = None
    origin_source: str | None = None
    predecessor: str | None = None
    role: str | None = None
    evaluator: str | None = None
    derivation: dict[str, Any] | None = None


class DatasetEntry(BaseModel):
    """One entry in the top-level ``datasets:`` list."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    variables: list[VariableEntry] = Field(default_factory=list)
    inputs: list[dict[str, Any]] = Field(default_factory=list)
    output: str | None = None
    output_format: str | None = None
    label: str | None = None
    structure: str | None = None
    repeating: Any = None
    keys: Any = None
    value_level: Any = None
    class_: Any = Field(default=None, alias="class")


class DefineSpec(BaseModel):
    """A parsed spec file — either format ``from_spec()`` accepts.

    ``datasets:`` is the full define.yaml shape (one entry per domain,
    each variable carrying a ``derivation:`` block).  ``variables:`` with
    ``domain:``/``dataset:`` is the simplified single-dataset shape whose
    entries hold inline algorithm fields.
    """

    model_config = ConfigDict(extra="forbid")

    study: dict[str, Any] = Field(default_factory=dict)
    codelists: list[dict[str, Any]] = Field(default_factory=list)
    datasets: list[DatasetEntry] | None = None
    fleet_spec_version: int | None = None
    derivations_module: str | None = None
    ct: CTBlock = Field(default_factory=CTBlock)
    output_format: str = "parquet"

    # Simplified single-dataset format.
    domain: str | None = None
    dataset: str | None = None
    variables: list[dict[str, Any]] | None = None

    @model_validator(mode="after")
    def _require_a_format(self) -> DefineSpec:
        if self.datasets is None and self.variables is None:
            raise ValueError(
                "spec declares neither 'datasets:' (define.yaml format) nor "
                "'variables:' (simplified format)"
            )
        return self

    def select(self, dataset: str | None) -> DatasetEntry:
        """Return the requested dataset entry from a define.yaml spec.

        Args:
            dataset: Dataset name to select; may be ``None`` when the spec
                declares exactly one dataset.

        Returns:
            DatasetEntry: The matching dataset.

        Raises:
            DerivationError: When *dataset* is unknown, or omitted for a
                multi-dataset spec.
        """
        from fleet.core.exceptions import DerivationError

        datasets = self.datasets or []
        names = [d.name for d in datasets]
        if dataset is None:
            if len(datasets) != 1:
                raise DerivationError(
                    f"define.yaml contains {len(datasets)} datasets {names}. "
                    "Pass dataset= to select one."
                )
            return datasets[0]
        for entry in datasets:
            if entry.name.upper() == dataset.upper():
                return entry
        raise DerivationError(f"Dataset '{dataset}' not found in define.yaml. Available: {names}")


def load_define_spec(path: str | Path) -> DefineSpec:
    """Load and validate a define.yaml / simplified spec file.

    Args:
        path: Path to the YAML specification file.

    Returns:
        DefineSpec: The validated spec envelope.

    Raises:
        SpecError: On unreadable YAML, a non-mapping document, unknown
            keys, or a missing ``name:`` on a dataset or variable.

    Examples:
        Inspect a spec before executing it::

            from fleet.core.define_spec import load_define_spec

            spec = load_define_spec("examples/cdiscpilot01/sdtm/define.yaml")
            names = [d.name for d in spec.datasets or []]
    """
    p = Path(path)
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as err:
        raise SpecError(f"{p}: invalid YAML: {err}") from err
    if not isinstance(data, dict):
        raise SpecError(f"{p}: spec must be a YAML mapping, got {type(data).__name__}.")
    try:
        return DefineSpec.model_validate(data)
    except ValidationError as err:
        raise SpecError(f"{p}: {err}") from err
