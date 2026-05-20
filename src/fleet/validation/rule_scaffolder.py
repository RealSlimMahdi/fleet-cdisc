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
        "Classes": {"Include": ["EVENTS"]},
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
            with open(f) as fh:
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

    # Write YAML with a helpful header comment
    out_file = output_dir / f"{rule_id}.yaml"
    header = (
        f"# {rule_id}: {description}\n"
        "#\n"
        "# TODO: Edit the Check block below with your validation logic.\n"
        "# See CDISC Rules Engine docs for available operators:\n"
        "#   equal_to, not_equal_to, empty, non_empty, less_than,\n"
        "#   greater_than, contains, does_not_contain, is_contained_by, etc.\n"
        "#\n"
        "# After editing, validate with:\n"
        f"#   uv run python test_custom_rule.py  (update path to this file)\n"
        "\n"
    )
    yaml_content = yaml.dump(rule, default_flow_style=False, allow_unicode=True, sort_keys=False)
    out_file.write_text(header + yaml_content, encoding="utf-8")

    return out_file
