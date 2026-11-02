"""Tests for custom CDISC rule YAML validation against the vendored JSON Schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

SCHEMA_PATH = (
    Path(__file__).parents[2]
    / "src"
    / "fleet"
    / "validation"
    / "schemas"
    / "cdisc_rule_schema.json"
)

RULE_FILE = (
    Path(__file__).parents[2]
    / "examples"
    / "cdiscpilot01"
    / "sdtm"
    / "custom_rules"
    / "FLEET-AE-001.yaml"
)


def _validate_rule_schema(rule: dict) -> list[str]:
    """Validate rule dict against the vendored CDISC rule JSON Schema."""
    from jsonschema import Draft202012Validator

    schema = json.loads(SCHEMA_PATH.read_text())
    validator = Draft202012Validator(schema)
    errors = []
    for error in sorted(validator.iter_errors(rule), key=lambda e: list(e.path)):
        path = ".".join(str(p) for p in error.absolute_path) or "(root)"
        errors.append(f"{path}: {error.message}")
    return errors


@pytest.fixture()
def rule() -> dict:
    """Load the FLEET-AE-001 custom rule YAML."""
    with open(RULE_FILE) as f:
        return yaml.safe_load(f)


class TestCustomRuleSchema:
    """Schema and structural validation of custom CDISC rules."""

    def test_rule_file_exists(self) -> None:
        assert RULE_FILE.exists(), f"Rule file not found: {RULE_FILE}"

    def test_schema_file_exists(self) -> None:
        assert SCHEMA_PATH.exists(), f"Schema file not found: {SCHEMA_PATH}"

    def test_yaml_parses_to_dict(self, rule: dict) -> None:
        assert isinstance(rule, dict), f"Expected dict, got {type(rule).__name__}"

    def test_rule_has_required_top_level_keys(self, rule: dict) -> None:
        assert "Core" in rule
        assert "Rule Type" in rule
        assert "Scope" in rule

    def test_core_id_present(self, rule: dict) -> None:
        assert rule.get("Core", {}).get("Id") == "FLEET-AE-001"

    def test_rule_conforms_to_cdisc_schema(self, rule: dict) -> None:
        errors = _validate_rule_schema(rule)
        assert not errors, "Schema validation errors:\n" + "\n".join(f"  - {e}" for e in errors)


class TestCustomRuleEngine:
    """Integration tests that run the rule against the CDISC Rules Engine."""

    @pytest.fixture()
    def engine(self):
        """Discover the CDISC Rules Engine or skip."""
        from fleet.validation.engine import discover_engine

        eng = discover_engine()
        if eng is None:
            pytest.skip("CDISC Rules Engine not installed (run: fleet install-engine)")
        return eng

    @pytest.fixture()
    def test_xpt(self, tmp_path: Path) -> Path:
        """Create a minimal AE XPT with one passing and one failing record."""
        pyreadstat = pytest.importorskip("pyreadstat")
        import polars as pl

        ae_data = pl.from_repr("""\
┌──────────────┬────────┬────────────────┬───────┬──────────┬──────────┬───────┐
│ STUDYID      ┆ DOMAIN ┆ USUBJID        ┆ AESEQ ┆ AETERM   ┆ AESEV    ┆ AESER │
│ ---          ┆ ---    ┆ ---            ┆ ---   ┆ ---      ┆ ---      ┆ ---   │
│ str          ┆ str    ┆ str            ┆ f64   ┆ str      ┆ str      ┆ str   │
╞══════════════╪════════╪════════════════╪═══════╪══════════╪══════════╪═══════╡
│ CDISCPILOT01 ┆ AE     ┆ CDISC01.100001 ┆ 1.0   ┆ HEADACHE ┆ MODERATE ┆ Y     │
│ CDISCPILOT01 ┆ AE     ┆ CDISC01.100002 ┆ 2.0   ┆ NAUSEA   ┆ null     ┆ Y     │
│ CDISCPILOT01 ┆ AE     ┆ CDISC01.100003 ┆ 3.0   ┆ RASH     ┆ MILD     ┆ N     │
└──────────────┴────────┴────────────────┴───────┴──────────┴──────────┴───────┘
""")
        out = tmp_path / "ae.xpt"
        pyreadstat.write_xport(ae_data, str(out), file_format_version=5, table_name="AE")
        return out

    def test_engine_runs_rule(self, engine: Path, test_xpt: Path, tmp_path: Path) -> None:
        """Run the custom rule and verify the engine produces output."""
        import subprocess

        output_path = tmp_path / "result"
        cmd = [
            str(engine),
            "validate",
            "-s",
            "sdtmig",
            "-v",
            "3-4",
            "-dp",
            str(test_xpt),
            "-lr",
            str(RULE_FILE),
            "-o",
            str(output_path),
            "-of",
            "JSON",
            "-rr",
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(engine.parent),
            timeout=120,
        )

        json_result = output_path.with_suffix(".json")
        assert json_result.exists(), (
            f"Engine produced no output (exit={result.returncode})\nstderr: {result.stderr[:500]}"
        )

        report = json.loads(json_result.read_text())
        rules_report = report.get("Rules_Report", [])
        our_rule = [r for r in rules_report if r.get("core_id") == "FLEET-AE-001"]
        assert our_rule, (
            f"FLEET-AE-001 not in Rules_Report. Found: {[r.get('core_id') for r in rules_report]}"
        )

        status = our_rule[0].get("status", "UNKNOWN")
        assert status != "EXECUTION_ERROR", f"Rule execution error: {our_rule[0].get('message')}"
