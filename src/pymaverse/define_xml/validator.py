"""Define-XML YAML Validator.

Validates Define-XML YAML files against the JSON schema and performs
business rule checks to ensure CDISC Define-XML 2.1 compliance.

Business Rules:
    BR01: Each ItemGroupDef must have at least one key variable
    BR02: All ItemRef references must resolve to ItemDefs
    BR03: All CodeListRef references must resolve to CodeLists
    BR04: MethodDef references must resolve

Algorithm Validation Rules:
    ALG01: assign_no_ct requires source_variable
    ALG02: assign_ct requires source_variable and ct_codelist
    ALG03: hardcode_* requires constant_value
    ALG05: merge requires merge_dataset and merge_key
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import jsonschema
import yaml

_DEFAULT_SCHEMA = Path(__file__).parent / "schemas" / "define_xml_2_1_schema.json"

# Pymaverse's verb field name in the YAML spec
_ALGO_KEY = "pymaverse_algorithm"


@dataclass
class DefineIssue:
    severity: str  # "error" | "warning" | "info"
    location: str
    message: str
    rule: str


class DefineValidator:
    """Validate Define-XML YAML files against schema and business rules."""

    def __init__(self, schema_path: Path | None = None) -> None:
        schema_file = schema_path or _DEFAULT_SCHEMA
        self.schema = json.loads(Path(schema_file).read_text())
        self.issues: list[DefineIssue] = []

    def validate(self, define_yaml_path: Path) -> bool:
        """Validate a Define-XML YAML file. Returns True if no errors."""
        self.issues = []
        try:
            data = yaml.safe_load(Path(define_yaml_path).read_text())
        except yaml.YAMLError as exc:
            self.issues.append(DefineIssue("error", "root", f"YAML parse error: {exc}", "YAML_001"))
            return False

        self._validate_schema(data)
        self._validate_business_rules(data)
        self._validate_cross_references(data)
        self._validate_algorithms(data)
        self._validate_consistency(data)
        return not self.has_errors()

    # ------------------------------------------------------------------ #
    # Schema validation                                                    #
    # ------------------------------------------------------------------ #

    def _validate_schema(self, data: dict[str, Any]) -> None:
        validator = jsonschema.Draft7Validator(self.schema)
        for error in validator.iter_errors(data):
            location = ".".join(str(x) for x in error.path) if error.path else "root"
            self.issues.append(DefineIssue("error", location, error.message, "SCHEMA_001"))

    # ------------------------------------------------------------------ #
    # Business rules                                                       #
    # ------------------------------------------------------------------ #

    def _validate_business_rules(self, data: dict[str, Any]) -> None:
        meta = data.get("metadata_version", {})

        # BR01 – each ItemGroupDef needs at least one key variable
        for ig in meta.get("item_group_defs", []):
            key_vars = [r for r in ig.get("item_refs", []) if r.get("key_sequence") is not None]
            if not key_vars:
                self.issues.append(DefineIssue(
                    "error",
                    f"item_group_defs[oid={ig.get('oid', '?')}]",
                    f"Dataset '{ig.get('name', '?')}' must have at least one key variable (key_sequence).",
                    "BR01",
                ))

        item_def_oids = {i["oid"] for i in meta.get("item_defs", [])}
        codelist_oids = {c["oid"] for c in meta.get("code_lists", [])}
        method_oids = {m["oid"] for m in meta.get("method_defs", [])}

        for ig in meta.get("item_group_defs", []):
            for ref in ig.get("item_refs", []):
                # BR02
                oid = ref.get("item_oid")
                if oid and oid not in item_def_oids:
                    self.issues.append(DefineIssue(
                        "error", f"item_group_defs[oid={ig.get('oid')}].item_refs",
                        f"ItemRef '{oid}' not found in item_defs.", "BR02",
                    ))
                # BR04
                m_oid = ref.get("method_oid")
                if m_oid and m_oid not in method_oids:
                    self.issues.append(DefineIssue(
                        "warning", f"item_group_defs[oid={ig.get('oid')}].item_refs[{oid}]",
                        f"MethodDef '{m_oid}' not found in method_defs.", "BR04",
                    ))

        # BR03
        for item in meta.get("item_defs", []):
            cl_ref = item.get("codelist_ref", {})
            if isinstance(cl_ref, dict):
                cl_oid = cl_ref.get("codelist_oid")
                if cl_oid and cl_oid not in codelist_oids:
                    self.issues.append(DefineIssue(
                        "error", f"item_defs[oid={item.get('oid')}].codelist_ref",
                        f"CodeList '{cl_oid}' not found in code_lists.", "BR03",
                    ))

    # ------------------------------------------------------------------ #
    # Cross references                                                     #
    # ------------------------------------------------------------------ #

    def _validate_cross_references(self, data: dict[str, Any]) -> None:
        meta = data.get("metadata_version", {})
        standard_oids = {s["oid"] for s in meta.get("standards", [])}
        leaf_ids = {l["id"] for l in meta.get("leaf_defs", [])}

        for ig in meta.get("item_group_defs", []):
            loc_base = f"item_group_defs[oid={ig.get('oid')}]"
            std_oid = ig.get("standard_oid")
            if std_oid and std_oid not in standard_oids:
                self.issues.append(DefineIssue(
                    "warning", f"{loc_base}.standard_oid",
                    f"Standard '{std_oid}' not found in standards section.", "CR01",
                ))
            leaf_id = ig.get("archive_location_id")
            if leaf_id and leaf_id not in leaf_ids:
                self.issues.append(DefineIssue(
                    "error", f"{loc_base}.archive_location_id",
                    f"Leaf '{leaf_id}' not found in leaf_defs.", "CR02",
                ))

    # ------------------------------------------------------------------ #
    # Algorithm completeness                                               #
    # ------------------------------------------------------------------ #

    def _validate_algorithms(self, data: dict[str, Any]) -> None:
        meta = data.get("metadata_version", {})

        for item in meta.get("item_defs", []):
            algo = item.get(_ALGO_KEY, {})
            if not isinstance(algo, dict):
                continue
            algo_type = algo.get("algorithm")
            if not algo_type:
                continue

            oid = item.get("oid", "?")
            name = item.get("name", "?")
            loc = f"item_defs[oid={oid}].{_ALGO_KEY}"

            if algo_type == "assign_no_ct" and not algo.get("source_variable"):
                self.issues.append(DefineIssue("error", loc, f"'{name}': assign_no_ct requires source_variable.", "ALG01"))

            if algo_type == "assign_ct":
                if not algo.get("source_variable"):
                    self.issues.append(DefineIssue("error", loc, f"'{name}': assign_ct requires source_variable.", "ALG02A"))
                if not algo.get("ct_codelist"):
                    self.issues.append(DefineIssue("error", loc, f"'{name}': assign_ct requires ct_codelist.", "ALG02B"))

            if algo_type in ("hardcode_no_ct", "hardcode_ct", "dataset_level") and not algo.get("constant_value"):
                self.issues.append(DefineIssue("error", loc, f"'{name}': {algo_type} requires constant_value.", "ALG03"))

            if algo_type == "merge":
                if not algo.get("merge_dataset"):
                    self.issues.append(DefineIssue("error", loc, f"'{name}': merge requires merge_dataset.", "ALG05A"))
                if not algo.get("merge_key"):
                    self.issues.append(DefineIssue("error", loc, f"'{name}': merge requires merge_key.", "ALG05B"))

    # ------------------------------------------------------------------ #
    # Consistency                                                         #
    # ------------------------------------------------------------------ #

    def _validate_consistency(self, data: dict[str, Any]) -> None:
        meta = data.get("metadata_version", {})
        all_oids: dict[str, list[str]] = {}

        for section in ("item_group_defs", "item_defs", "code_lists", "method_defs", "comment_defs", "standards"):
            for item in meta.get(section, []):
                oid = item.get("oid")
                if oid:
                    all_oids.setdefault(oid, []).append(section)

        for oid, sections in all_oids.items():
            if len(sections) > 1:
                self.issues.append(DefineIssue(
                    "error", f"multiple sections: {', '.join(sections)}",
                    f"Duplicate OID '{oid}' found in {len(sections)} sections.", "CONS01",
                ))

    # ------------------------------------------------------------------ #
    # Reporting helpers                                                    #
    # ------------------------------------------------------------------ #

    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    def get_errors(self) -> list[DefineIssue]:
        return [i for i in self.issues if i.severity == "error"]

    def get_warnings(self) -> list[DefineIssue]:
        return [i for i in self.issues if i.severity == "warning"]

    def print_report(self) -> None:
        if not self.issues:
            print("Validation passed — no issues found.")
            return

        errors = self.get_errors()
        warnings = self.get_warnings()
        print(f"\n{'='*80}")
        print("Define-XML YAML Validation Report")
        print(f"{'='*80}")
        if errors:
            print(f"\n{len(errors)} ERROR(S):\n")
            for i in errors:
                print(f"  [{i.rule}] {i.location}\n           {i.message}\n")
        if warnings:
            print(f"\n{len(warnings)} WARNING(S):\n")
            for i in warnings:
                print(f"  [{i.rule}] {i.location}\n           {i.message}\n")
        print(f"{'='*80}")
        status = "FAILED" if errors else "PASSED"
        print(f"Result: {status} — {len(errors)} errors, {len(warnings)} warnings")
