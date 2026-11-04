"""Tests for custom validation rules integration."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from fleet.core.study_context import (
    StudyConfig,
    StudyContext,
    ValidationConfig,
)
from fleet.validation.rule_scaffolder import (
    _next_sequence,
    _scan_existing_ids,
    check_rule,
    scaffold_rule,
)

# ── ValidationConfig tests ────────────────────────────────────────────


class TestValidationConfig:
    def test_custom_rules_default_none(self):
        cfg = ValidationConfig()
        assert cfg.custom_rules is None

    def test_custom_rules_set(self):
        cfg = ValidationConfig(custom_rules="metadata/custom_rules")
        assert cfg.custom_rules == "metadata/custom_rules"

    def test_study_context_custom_rules_dir_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = StudyConfig(study_id="TEST01")
            ctx = StudyContext(study_root=Path(tmpdir), config=cfg)
            assert ctx.custom_rules_dir is None

    def test_study_context_custom_rules_dir_resolved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = StudyConfig(
                study_id="TEST01",
                validation=ValidationConfig(custom_rules="metadata/custom_rules"),
            )
            ctx = StudyContext(study_root=Path(tmpdir), config=cfg)
            expected = (Path(tmpdir) / "metadata" / "custom_rules").resolve()
            assert ctx.custom_rules_dir == expected


# ── Rule scaffolder tests ─────────────────────────────────────────────


class TestRuleScaffolder:
    def test_scaffold_basic(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = scaffold_rule(
                domain="AE",
                description="Test rule description",
                output_dir=Path(tmpdir),
                prefix="TEST",
            )
            assert out.exists()
            assert out.name == "TEST-AE-001.yaml"

            # Verify it's valid YAML
            with open(out) as f:
                rule = yaml.safe_load(f)
            assert rule["Core"]["Id"] == "TEST-AE-001"
            assert rule["Core"]["Status"] == "Draft"
            assert rule["Description"] == "Test rule description"
            assert rule["Scope"]["Domains"]["Include"] == ["AE"]
            assert rule["Rule Type"] == "Record Data"

    @pytest.mark.parametrize("domain", ["DM", "VS", "ADSL"])
    def test_scaffold_scopes_by_domain_not_by_class(self, domain, tmp_path):
        """c1-526: Classes EVENTS made a DM or VS rule never fire."""
        out = scaffold_rule(domain=domain, description="x", output_dir=tmp_path)

        scope = yaml.safe_load(out.read_text(encoding="utf-8"))["Scope"]

        assert scope == {"Classes": {"Include": ["ALL"]}, "Domains": {"Include": [domain]}}

    def test_scaffold_auto_increment(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create first rule
            scaffold_rule(
                domain="AE",
                description="First",
                output_dir=Path(tmpdir),
                prefix="FLEET",
            )
            # Create second rule — should auto-increment
            out = scaffold_rule(
                domain="AE",
                description="Second",
                output_dir=Path(tmpdir),
                prefix="FLEET",
            )
            assert out.name == "FLEET-AE-002.yaml"

    def test_scaffold_explicit_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = scaffold_rule(
                domain="DM",
                description="Custom ID rule",
                output_dir=Path(tmpdir),
                rule_id="ACME-DM-042",
            )
            assert out.name == "ACME-DM-042.yaml"
            with open(out) as f:
                rule = yaml.safe_load(f)
            assert rule["Core"]["Id"] == "ACME-DM-042"

    def test_scaffold_duplicate_id_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            scaffold_rule(
                domain="AE",
                description="First",
                output_dir=Path(tmpdir),
                rule_id="FLEET-AE-001",
            )
            with pytest.raises(FileExistsError, match="FLEET-AE-001"):
                scaffold_rule(
                    domain="AE",
                    description="Duplicate",
                    output_dir=Path(tmpdir),
                    rule_id="FLEET-AE-001",
                )

    def test_scaffold_with_organization(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out = scaffold_rule(
                domain="VS",
                description="Org test",
                output_dir=Path(tmpdir),
                organization="Acme",
            )
            with open(out) as f:
                rule = yaml.safe_load(f)
            assert rule["Authorities"][0]["Organization"] == "Acme"

    def test_scan_existing_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rule_file = Path(tmpdir) / "TEST-AE-001.yaml"
            rule_file.write_text(yaml.dump({"Core": {"Id": "TEST-AE-001", "Status": "Draft"}}))
            ids = _scan_existing_ids(Path(tmpdir))
            assert "TEST-AE-001" in ids

    def test_next_sequence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Empty dir → sequence 1
            assert _next_sequence(Path(tmpdir), "FLEET", "AE") == 1

            # After creating one rule
            scaffold_rule(
                domain="AE",
                description="Test",
                output_dir=Path(tmpdir),
                prefix="FLEET",
            )
            assert _next_sequence(Path(tmpdir), "FLEET", "AE") == 2


# ── Engine command integration test ───────────────────────────────────


class TestCustomRulesEngineIntegration:
    """Test that custom_rules parameter correctly appends -lr to engine cmd."""

    def test_validate_dataset_appends_lr_flag(self):
        """Verify -lr is added to command when custom_rules is set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = Path(tmpdir) / "rules"
            rules_dir.mkdir()

            # Mock the engine run to capture the command
            with patch("fleet.validation.official._run_command") as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = ""
                mock_run.return_value.stderr = ""

                from fleet.validation.official import OfficialCDISCValidator

                with patch.object(OfficialCDISCValidator, "__init__", lambda self, **kw: None):
                    validator = OfficialCDISCValidator()
                    validator._executable = Path("/fake/engine")
                    validator._is_legacy = False

                    import polars as pl

                    df = pl.from_repr("""\
┌────────┬─────────┐
│ DOMAIN ┆ USUBJID │
│ ---    ┆ ---     │
│ str    ┆ str     │
╞════════╪═════════╡
│ AE     ┆ 001     │
└────────┴─────────┘
""")

                    # Call with custom_rules
                    with patch.object(validator, "_write_dataset_json"):
                        try:
                            validator.validate_dataset(
                                data=df,
                                standard="sdtmig",
                                version="3-4",
                                domain="AE",
                                custom_rules=rules_dir,
                            )
                        except Exception:
                            pass  # May fail on output parsing — that's fine

                    # Check the command included -lr
                    assert mock_run.called
                    cmd = mock_run.call_args[0][0]
                    assert "-lr" in cmd
                    lr_idx = cmd.index("-lr")
                    assert cmd[lr_idx + 1] == str(rules_dir.resolve())

    def test_validate_dataset_no_lr_without_custom_rules(self):
        """Verify -lr is NOT added when custom_rules is None."""
        with patch("fleet.validation.official._run_command") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""

            from fleet.validation.official import OfficialCDISCValidator

            with patch.object(OfficialCDISCValidator, "__init__", lambda self, **kw: None):
                validator = OfficialCDISCValidator()
                validator._executable = Path("/fake/engine")
                validator._is_legacy = False

                import polars as pl

                df = pl.from_repr("""\
┌────────┬─────────┐
│ DOMAIN ┆ USUBJID │
│ ---    ┆ ---     │
│ str    ┆ str     │
╞════════╪═════════╡
│ AE     ┆ 001     │
└────────┴─────────┘
""")

                with patch.object(validator, "_write_dataset_json"):
                    try:
                        validator.validate_dataset(
                            data=df,
                            standard="sdtmig",
                            version="3-4",
                            domain="AE",
                            custom_rules=None,
                        )
                    except Exception:
                        pass

                assert mock_run.called
                cmd = mock_run.call_args[0][0]
                assert "-lr" not in cmd

    def test_custom_rules_invalid_path_raises(self):
        """Verify error when custom_rules path doesn't exist."""
        from fleet.validation.official import OfficialCDISCValidator

        with patch.object(OfficialCDISCValidator, "__init__", lambda self, **kw: None):
            validator = OfficialCDISCValidator()
            validator._executable = Path("/fake/engine")
            validator._is_legacy = False

            import polars as pl

            df = pl.from_repr("""\
┌────────┬─────────┐
│ DOMAIN ┆ USUBJID │
│ ---    ┆ ---     │
│ str    ┆ str     │
╞════════╪═════════╡
│ AE     ┆ 001     │
└────────┴─────────┘
""")

            with patch.object(validator, "_write_dataset_json"):
                with pytest.raises(FileNotFoundError, match="does not exist"):
                    validator.validate_dataset(
                        data=df,
                        standard="sdtmig",
                        version="3-4",
                        domain="AE",
                        custom_rules=Path("/nonexistent/path"),
                    )

    def test_custom_rules_file_not_dir_raises(self):
        """Verify error when custom_rules is a file, not a directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            file_path = Path(tmpdir) / "not_a_dir.yaml"
            file_path.write_text("test")

            from fleet.validation.official import OfficialCDISCValidator

            with patch.object(OfficialCDISCValidator, "__init__", lambda self, **kw: None):
                validator = OfficialCDISCValidator()
                validator._executable = Path("/fake/engine")
                validator._is_legacy = False

                import polars as pl

                df = pl.from_repr("""\
┌────────┬─────────┐
│ DOMAIN ┆ USUBJID │
│ ---    ┆ ---     │
│ str    ┆ str     │
╞════════╪═════════╡
│ AE     ┆ 001     │
└────────┴─────────┘
""")

                with patch.object(validator, "_write_dataset_json"):
                    with pytest.raises(NotADirectoryError, match="must be a directory"):
                        validator.validate_dataset(
                            data=df,
                            standard="sdtmig",
                            version="3-4",
                            domain="AE",
                            custom_rules=file_path,
                        )


# ── CLI test ──────────────────────────────────────────────────────────


class TestAddRuleCLI:
    def test_cli_add_rule_with_output(self):
        """Test fleet add-rule --domain AE --description ... --output ..."""
        with tempfile.TemporaryDirectory() as tmpdir:
            from unittest.mock import patch as mock_patch

            from fleet.cli import main

            test_args = [
                "fleet",
                "add-rule",
                "--domain",
                "AE",
                "--description",
                "Test severity check",
                "--prefix",
                "TEST",
                "--output",
                tmpdir,
            ]
            with mock_patch("sys.argv", test_args):
                main()

            # Verify file was created
            rule_file = Path(tmpdir) / "TEST-AE-001.yaml"
            assert rule_file.exists()


# ── check_rule tests ──────────────────────────────────────────────────


class TestCheckRule:
    def test_valid_rule_no_errors(self):
        """Scaffolded rule should pass check_rule with no errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rule_path = scaffold_rule(
                domain="AE",
                description="Test rule",
                output_dir=Path(tmpdir),
                prefix="TEST",
            )
            errors = check_rule(rule_path)
            assert errors == []

    def test_yaml_syntax_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_file = Path(tmpdir) / "bad.yaml"
            bad_file.write_text("bad: yaml: {[broken")
            errors = check_rule(bad_file)
            assert len(errors) == 1
            assert "YAML syntax error" in errors[0]

    def test_missing_required_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rule_file = Path(tmpdir) / "incomplete.yaml"
            rule_file.write_text(
                yaml.dump({"Check": {"all": [{"name": "X", "operator": "empty"}]}})
            )
            errors = check_rule(rule_file)
            assert any("Missing required top-level keys" in e for e in errors)
            assert any("Core" in e for e in errors)

    def test_empty_domains_warning(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rule_file = Path(tmpdir) / "nodomain.yaml"
            rule = {
                "Core": {"Id": "TEST-001", "Version": "1"},
                "Check": {"all": [{"name": "X", "operator": "empty"}]},
                "Rule Type": "Record Data",
                "Scope": {"Domains": {"Include": []}},
            }
            rule_file.write_text(yaml.dump(rule))
            errors = check_rule(rule_file)
            assert any("Scope.Domains.Include is empty" in e for e in errors)

    def test_check_block_no_combinator(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rule_file = Path(tmpdir) / "nocomb.yaml"
            rule = {
                "Core": {"Id": "TEST-001", "Version": "1"},
                "Check": {"name": "X", "operator": "empty"},
                "Rule Type": "Record Data",
                "Scope": {"Domains": {"Include": ["AE"]}},
            }
            rule_file.write_text(yaml.dump(rule))
            errors = check_rule(rule_file)
            assert any("combinator" in e for e in errors)
