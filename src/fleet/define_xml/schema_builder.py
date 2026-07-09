"""Regenerate the define-spec JSON schema from the algorithm registry.

The ``derivation`` section of ``schemas/define_spec_schema.json`` (the
per-algorithm models, the algorithm enum, required fields) is **machine
generated** from :mod:`fleet.core.spec_registry` so it can never drift
from what ``from_spec()`` actually executes.  The structural sections
(study, datasets, variables, documents, …) remain hand-maintained in the
JSON file itself.

Regenerate after changing the registry::

    uv run python -m fleet.define_xml.schema_builder

A sync test (``tests/unit/test_spec_parity.py``) fails when the shipped
schema does not match the registry, so the file cannot go stale again.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fleet.core._verb_mixin import SUPPORTED_SPEC_VERSION
from fleet.core.spec_registry import derivation_json_schema

SCHEMA_PATH = Path(__file__).parent / "schemas" / "define_spec_schema.json"

#: ``$defs`` entries that are hand-maintained in the JSON file.  Everything
#: else under ``$defs`` is regenerated from the registry on each build.
_HAND_OWNED_DEFS: tuple[str, ...] = (
    "study",
    "codelist",
    "dataset",
    "dataset_input",
    "variable",
    "documents",
    "crf_page_ref",
    "value_level_entry",
    "where_clause",
)


def build_schema(schema_path: str | Path = SCHEMA_PATH) -> dict[str, Any]:
    """Assemble the full define-spec JSON schema.

    Keeps the hand-maintained structural sections from *schema_path* and
    regenerates the machine-owned parts (the ``derivation`` definition,
    the per-algorithm model definitions, and the ``fleet_spec_version`` /
    ``derivations_module`` top-level properties) from the registry.

    Args:
        schema_path: Path of the existing schema file providing the
            hand-maintained skeleton.

    Returns:
        dict: The complete schema document.

    Examples:
        Check whether the shipped schema is in sync with the registry::

            import json
            from fleet.define_xml.schema_builder import SCHEMA_PATH, build_schema

            assert json.loads(SCHEMA_PATH.read_text()) == build_schema()
    """
    current = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    schema = {k: v for k, v in current.items() if k != "$defs"}

    properties = dict(schema.get("properties", {}))
    properties["fleet_spec_version"] = {
        "type": "integer",
        "description": (
            "Optional spec-format version. from_spec() and DefineSpecGenerator "
            "reject versions this Fleet build does not understand."
        ),
        "enum": [SUPPORTED_SPEC_VERSION],
    }
    properties["derivations_module"] = {
        "type": "string",
        "description": (
            "Dotted Python module imported by from_spec() before execution so "
            "that its @derivation / register_transform callables are available "
            "(removes the import-order footgun for `algorithm: callable`)."
        ),
    }
    schema["properties"] = properties

    defs: dict[str, Any] = {
        name: current["$defs"][name] for name in _HAND_OWNED_DEFS if name in current["$defs"]
    }
    derivation_def, model_defs = derivation_json_schema()
    defs["derivation"] = derivation_def
    defs.update(model_defs)
    schema["$defs"] = defs
    return schema


def write_schema(schema_path: str | Path = SCHEMA_PATH) -> Path:
    """Regenerate the schema file in place.

    Args:
        schema_path: Destination (and skeleton source) schema file.

    Returns:
        Path: The written file path.

    Examples:
        Regenerate the shipped schema after editing the registry::

            uv run python -m fleet.define_xml.schema_builder
    """
    path = Path(schema_path)
    schema = build_schema(path)
    path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    out = write_schema()
    print(f"Schema regenerated: {out}")
