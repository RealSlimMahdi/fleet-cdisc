"""Scaffold custom validation rule YAML files.

Generates schema-valid CDISC rule YAML skeletons that programmers can
fill in with their domain-specific logic (the ``Check:`` block).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

_RULE_TEMPLATE: dict = {
    "Authorities": [
        {
            "Organization": "Custom",
            "Standards": [
                {
                    "Name": "SDTMIG",
                    "References": [
                        {
                            "Citations": [
                                {
                                    "Cited Guidance": "Custom sponsor rule.",
                                    "Document": "Sponsor SOP",
                                    "Section": "TBD",
                                }
                            ],
                            "Origin": "Sponsor SOP",
                            "Rule Identifier": {"Id": "", "Version": "1"},
                            "Version": "1",
                        }
                    ],
                    "Version": "3.4",
                }
            ],
            "Category": {
                "Purpose": "Sponsor SOP compliance",
                "Keywords": [],
            },
        }
    ],
    "Check": {
        "all": [
            {
                "name": "VARIABLE_NAME",
                "operator": "empty",
            }
        ]
    },
    "Core": {"Id": "", "Status": "Draft", "Version": "1"},
    "Description": "",
    "Executability": "Fully Executable",
    "Outcome": {
        "Message": "",
        "Output Variables": ["USUBJID"],
    },
    "Rule Type": "Record Data",
    "Scope": {
        "Classes": {"Include": ["ALL"]},
        "Domains": {"Include": []},
    },
    "Sensitivity": "Record",
}


def _scan_existing_ids(directory: Path) -> set[str]:
    """Scan all YAML files in *directory* and extract Core.Id values."""
    ids: set[str] = set()
    if not directory.is_dir():
        return ids
    for f in directory.glob("*.yaml"):
        try:
            with open(f, encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if isinstance(data, dict):
                core_id = data.get("Core", {}).get("Id")
                if core_id:
                    ids.add(core_id)
        except Exception:
            continue
    return ids


def _next_sequence(directory: Path, prefix: str, domain: str) -> int:
    """Determine the next available sequence number for a rule ID."""
    pattern = re.compile(rf"^{re.escape(prefix)}-{re.escape(domain)}-(\d{{3}})$", re.IGNORECASE)
    existing_ids = _scan_existing_ids(directory)
    max_seq = 0
    for rule_id in existing_ids:
        m = pattern.match(rule_id)
        if m:
            max_seq = max(max_seq, int(m.group(1)))
    return max_seq + 1


def scaffold_rule(
    *,
    domain: str,
    description: str,
    output_dir: Path,
    prefix: str = "FLEET",
    rule_id: str | None = None,
    organization: str | None = None,
    ig_version: str = "3.4",
) -> Path:
    """Generate a schema-valid custom rule YAML skeleton.

    Args:
        domain: SDTM/ADaM domain code (e.g. ``"AE"``, ``"DM"``).
        description: Human-readable description of the rule.
        output_dir: Directory to write the generated YAML file.
        prefix: Rule ID prefix (default ``"FLEET"``).
        rule_id: Explicit rule ID override; skips auto-increment.
        organization: Organization name for Authorities block.
        ig_version: IG version for the Standards reference.

    Returns:
        Path to the generated YAML file.

    Raises:
        FileExistsError: If a rule with the same ID already exists.
        FileNotFoundError: If *output_dir* does not exist.
    """
    output_dir = Path(output_dir)
    if not output_dir.exists():
        output_dir.mkdir(parents=True, exist_ok=True)

    existing_ids = _scan_existing_ids(output_dir)

    # Determine rule ID
    if rule_id is None:
        seq = _next_sequence(output_dir, prefix, domain.upper())
        rule_id = f"{prefix}-{domain.upper()}-{seq:03d}"

    if rule_id in existing_ids:
        raise FileExistsError(
            f"Rule ID '{rule_id}' already exists in {output_dir}. "
            "Use a different ID or remove the existing rule."
        )

    # Build the rule from template
    import copy

    rule = copy.deepcopy(_RULE_TEMPLATE)

    rule["Core"]["Id"] = rule_id
    rule["Description"] = description
    rule["Outcome"]["Message"] = description
    rule["Scope"]["Domains"]["Include"] = [domain.upper()]
    rule["Authorities"][0]["Standards"][0]["References"][0]["Rule Identifier"]["Id"] = rule_id
    rule["Authorities"][0]["Standards"][0]["Version"] = ig_version
    rule["Authorities"][0]["Category"]["Keywords"] = [domain.upper()]

    if organization:
        rule["Authorities"][0]["Organization"] = organization

    # Write YAML with schema directive and a helpful header comment
    out_file = output_dir / f"{rule_id}.yaml"

    # Resolve schema path relative to output file (works with installed package)
    import importlib.resources
    import os

    schema_ref = (
        importlib.resources.files("fleet") / "validation" / "schemas" / "cdisc_rule_schema.json"
    )
    with importlib.resources.as_file(schema_ref) as schema_abs:
        schema_rel_path = os.path.relpath(schema_abs, output_dir.resolve())

    header = (
        f"# yaml-language-server: $schema={schema_rel_path}\n"
        f"# {rule_id}: {description}\n"
        "#\n"
        "# TODO: Edit the Check block below with your validation logic.\n"
        "#\n"
        "# Rule types and operators reference:\n"
        "#   https://github.com/cdisc-org/cdisc-rules-engine/wiki/Rule-Types\n"
        "#\n"
        "# Available operators:\n"
        "#   equal_to, not_equal_to, empty, non_empty, less_than,\n"
        "#   greater_than, contains, does_not_contain, is_contained_by, etc.\n"
        "#\n"
        "# Rule types:\n"
        "#   Record Data       — check within a single row\n"
        "#   Record Data [VP]  — check across rows (value-level)\n"
        "#   Dataset Data      — check across datasets\n"
        "#\n"
        "# Validate this rule:\n"
        f"#   uv run fleet check-rule {rule_id}.yaml\n"
        "#\n"
        "# Run via pipeline:\n"
        f'#   .validate("{domain.upper()}", custom_rules="{output_dir}")\n'
        "\n"
    )
    yaml_content = yaml.dump(rule, default_flow_style=False, allow_unicode=True, sort_keys=False)
    out_file.write_text(header + yaml_content, encoding="utf-8")

    return out_file


# ── Rule validation ───────────────────────────────────────────────────


_SCHEMA_PATH = Path(__file__).parent / "schemas" / "cdisc_rule_schema.json"


def check_rule(rule_path: Path) -> list[str]:
    """Validate a custom rule YAML file against the CDISC schema.

    Performs three levels of checking:
      1. YAML syntax — can the file be parsed?
      2. Structure — does the parsed dict have required top-level keys?
      3. Schema — full JSON Schema validation against the CDISC rule schema.

    Args:
        rule_path: Path to the rule YAML file.

    Returns:
        List of error messages. Empty list means the rule is valid.
    """
    import json

    errors: list[str] = []

    # ── 1. YAML parse ─────────────────────────────────────────────────
    try:
        with open(rule_path, encoding="utf-8") as f:
            rule = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        if mark:
            errors.append(
                f"YAML syntax error at line {mark.line + 1}, column {mark.column + 1}: "
                f"{getattr(exc, 'problem', str(exc))}"
            )
        else:
            errors.append(f"YAML syntax error: {exc}")
        return errors

    if not isinstance(rule, dict):
        errors.append(f"Expected a YAML mapping (dict) at top level, got {type(rule).__name__}")
        return errors

    # ── 2. Quick structure checks ─────────────────────────────────────
    required_keys = {"Core", "Check", "Scope", "Rule Type"}
    missing = required_keys - set(rule.keys())
    if missing:
        errors.append(f"Missing required top-level keys: {', '.join(sorted(missing))}")

    core = rule.get("Core", {})
    if isinstance(core, dict):
        if not core.get("Id"):
            errors.append("Core.Id is missing or empty")
        if not core.get("Version"):
            errors.append("Core.Version is missing or empty")

    check = rule.get("Check")
    if isinstance(check, dict):
        if not any(k in check for k in ("all", "any", "not")):
            errors.append(
                "Check block must contain at least one combinator: 'all', 'any', or 'not'"
            )

    scope = rule.get("Scope", {})
    if isinstance(scope, dict):
        domains = scope.get("Domains", {})
        if isinstance(domains, dict) and not domains.get("Include"):
            errors.append("Scope.Domains.Include is empty — rule won't match any domain")

    # ── 3. Full JSON Schema validation ────────────────────────────────
    if _SCHEMA_PATH.exists():
        try:
            from jsonschema import Draft202012Validator

            schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
            validator = Draft202012Validator(schema)
            for error in sorted(validator.iter_errors(rule), key=lambda e: list(e.path)):
                path = ".".join(str(p) for p in error.absolute_path) or "(root)"
                errors.append(f"Schema: {path}: {error.message}")
        except ImportError:
            errors.append(
                "jsonschema not installed — install with: uv add jsonschema "
                "(schema validation skipped)"
            )
    else:
        errors.append(f"Schema file not found at {_SCHEMA_PATH} (schema validation skipped)")

    return errors
