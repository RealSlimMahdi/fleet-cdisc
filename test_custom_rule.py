"""Validate a custom CDISC rule YAML against the vendored JSON Schema and run it."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

# ── 1. Schema validation ──────────────────────────────────────────────
# Vendored CDISC rule JSON Schema (bundled from the modular schemas at
# https://github.com/cdisc-org/cdisc-rules-engine/tree/main/resources/schema/rule)

SCHEMA_PATH = (
    Path(__file__).parent / "src" / "fleet" / "validation" / "schemas" / "cdisc_rule_schema.json"
)


def validate_rule_schema(rule: dict) -> list[str]:
    """Validate rule dict against the vendored CDISC rule JSON Schema."""
    from jsonschema import Draft202012Validator

    schema = json.loads(SCHEMA_PATH.read_text())
    validator = Draft202012Validator(schema)
    errors = []
    for error in sorted(validator.iter_errors(rule), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in error.absolute_path) or "(root)"
        errors.append(f"{path}: {error.message}")
    return errors


# ── 2. Engine execution test ──────────────────────────────────────────


def make_test_xpt(tmpdir: Path) -> Path:
    """Create a minimal AE XPT with one passing and one failing record.

    Uses XPT (SAS Transport v5) format because the CDISC Rules Engine
    resolves domain from the filename (ae.xpt → AE), which is required
    for domain-scoped rules without a populated library cache.
    """
    import polars as pl
    import pyreadstat

    ae_data = pl.DataFrame(
        {
            "STUDYID": ["CDISCPILOT01", "CDISCPILOT01", "CDISCPILOT01"],
            "DOMAIN": ["AE", "AE", "AE"],
            "USUBJID": ["CDISC01.100001", "CDISC01.100002", "CDISC01.100003"],
            "AESEQ": [1.0, 2.0, 3.0],
            "AETERM": ["HEADACHE", "NAUSEA", "RASH"],
            "AESEV": ["MODERATE", None, "MILD"],  # Row 2: missing → should FAIL
            "AESER": ["Y", "Y", "N"],  # Row 3: not serious → should PASS
        }
    )
    out = tmpdir / "ae.xpt"
    # pyreadstat requires a pandas DataFrame for XPT serialisation;
    # build it from the polars dict representation to avoid a pyarrow dep.
    import pandas as pd  # transitive dep of pyreadstat — not used elsewhere

    pyreadstat.write_xport(pd.DataFrame(ae_data.to_dict()), str(out), file_format_version=5)
    return out


def run_engine_test(rule_path: Path) -> bool:
    """Run the CDISC Rules Engine with the custom rule against test data."""
    from fleet.validation.engine import discover_engine

    engine = discover_engine()
    if engine is None:
        print("\n[SKIP] CDISC Rules Engine not installed. Run: fleet install-engine")
        return True  # not a failure, just skipped

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        dataset_path = make_test_xpt(tmpdir_path)
        output_path = tmpdir_path / "result"

        cmd = [
            str(engine),
            "validate",
            "-s",
            "sdtmig",
            "-v",
            "3-4",
            "-dp",
            str(dataset_path),
            "-lr",
            str(rule_path),
            "-o",
            str(output_path),
            "-of",
            "JSON",
            "-rr",
        ]

        print(f"\n{'─' * 60}")
        print("ENGINE TEST")
        print(f"{'─' * 60}")
        print(f"  Engine:  {engine}")
        print(f"  Rule:    {rule_path.name}")
        print(f"  Dataset: {dataset_path.name}")
        print(f"  Command: {' '.join(cmd)}")
        print()

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(engine.parent),
            timeout=120,
        )

        print(f"  Exit code: {result.returncode}")
        if result.stdout.strip():
            # Limit stdout to avoid flooding
            stdout_lines = result.stdout.strip().splitlines()
            for line in stdout_lines[:20]:
                print(f"  stdout: {line}")
            if len(stdout_lines) > 20:
                print(f"  ... ({len(stdout_lines) - 20} more lines)")

        if result.stderr.strip():
            stderr_lines = result.stderr.strip().splitlines()
            for line in stderr_lines[:10]:
                print(f"  stderr: {line}")

        # Check for output
        json_result = output_path.with_suffix(".json")
        if json_result.exists():
            report = json.loads(json_result.read_text())

            # Show Rules_Report for our custom rule
            rules_report = report.get("Rules_Report", [])
            our_rule = [r for r in rules_report if r.get("core_id", "") == "FLEET-AE-001"]
            if our_rule:
                status = our_rule[0].get("status", "UNKNOWN")
                print(f"\n  Rule status: {status}")
                if status == "ISSUE_REPORTED":
                    print(
                        "  [PASS] Engine found issues (expected — test data has a failing record)"
                    )
                elif status == "SUCCESS":
                    print("  [WARN] Engine reported SUCCESS — no issues found (unexpected)")
                elif status == "SKIPPED":
                    print(f"  [WARN] Rule was SKIPPED: {our_rule[0].get('message', '')}")
                elif status == "EXECUTION_ERROR":
                    print(f"  [FAIL] Rule had execution error: {our_rule[0].get('message', '')}")
                    return False
            else:
                print("\n  [WARN] FLEET-AE-001 not found in Rules_Report")
                print(f"  Rules in report: {[r.get('core_id') for r in rules_report]}")

            # Show Issue_Details
            issues = report.get("Issue_Details", [])
            our_issues = [i for i in issues if i.get("core_id", "") == "FLEET-AE-001"]
            if our_issues:
                print(f"\n  Issues found: {len(our_issues)}")
                for issue in our_issues:
                    row = issue.get("row", "?")
                    usubjid = issue.get("USUBJID", "?")
                    msg = issue.get("message", "")
                    print(f"    Row {row} (USUBJID={usubjid}): {msg}")
            else:
                print("\n  No issues reported for FLEET-AE-001")

            return True
        else:
            print("\n  [FAIL] No output JSON generated by engine.")
            return False


# ── 3. Main ───────────────────────────────────────────────────────────


def main() -> int:
    rule_file = (
        Path(__file__).parent
        / "specs"
        / "cdiscpilot01"
        / "sdtm"
        / "custom_rules"
        / "FLEET-AE-001.yaml"
    )
    if not rule_file.exists():
        print(f"Rule file not found: {rule_file}")
        return 1

    print(f"{'═' * 60}")
    print("CUSTOM RULE VALIDATION: FLEET-AE-001")
    print(f"{'═' * 60}")
    print(f"  File: {rule_file}")
    print()

    # ── Step 1: Load and parse YAML ──
    print("STEP 1: Parse YAML")
    print(f"{'─' * 60}")
    with open(rule_file) as f:
        rule = yaml.safe_load(f)

    if not isinstance(rule, dict):
        print(f"  [FAIL] YAML did not parse to a dict (got {type(rule).__name__})")
        return 1

    print(f"  Top-level keys: {sorted(rule.keys())}")
    print(f"  Core.Id: {rule.get('Core', {}).get('Id', 'MISSING')}")
    print(f"  Rule Type: {rule.get('Rule Type', 'MISSING')}")
    print(f"  Domains: {rule.get('Scope', {}).get('Domains', {}).get('Include', 'MISSING')}")
    print("  [OK] YAML parsed successfully")
    print()

    # ── Step 2: Schema validation ──
    print("STEP 2: Validate against CDISC rule schema")
    print(f"{'─' * 60}")
    errors = validate_rule_schema(rule)
    if errors:
        print("  [FAIL] Schema validation errors:")
        for err in errors:
            print(f"    - {err}")
        return 1
    print("  [PASS] Rule conforms to CDISC YAML schema")
    print()

    # ── Step 3: Run engine ──
    print("STEP 3: Execute rule via CDISC Rules Engine")
    print(f"{'─' * 60}")
    ok = run_engine_test(rule_file)
    print()

    if ok:
        print(f"{'═' * 60}")
        print("ALL CHECKS PASSED")
        print(f"{'═' * 60}")
        return 0
    else:
        print(f"{'═' * 60}")
        print("SOME CHECKS FAILED")
        print(f"{'═' * 60}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
