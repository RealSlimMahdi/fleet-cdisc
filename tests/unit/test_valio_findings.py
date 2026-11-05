"""Regression tests for the alpha-audit medium and low findings in validation and io."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
import yaml

from fleet.validation.rule_scaffolder import (
    HEADER_RULE_TYPES,
    check_rule,
    scaffold_rule,
)


def _edit_check(path: Path, variable: str = "AETERM") -> None:
    rule = yaml.safe_load(path.read_text(encoding="utf-8"))
    rule["Check"] = {"all": [{"name": variable, "operator": "empty"}]}
    path.write_text(yaml.safe_dump(rule, sort_keys=False), encoding="utf-8")


# ── c1-527 c1-528: add-rule never replaces a file, and sees .yml ──


class TestAddRuleKeepsFiles:
    def test_a_broken_rule_file_is_kept_and_the_next_id_is_taken(self, tmp_path: Path) -> None:
        broken = tmp_path / "FLEET-AE-001.yaml"
        broken.write_text("Core: {Id: FLEET-AE-001\n# MARKER\n", encoding="utf-8")

        out = scaffold_rule(domain="AE", description="d", output_dir=tmp_path)

        assert out.name == "FLEET-AE-002.yaml"
        assert "MARKER" in broken.read_text(encoding="utf-8")

    def test_an_explicit_id_whose_file_holds_another_id_is_refused(self, tmp_path: Path) -> None:
        keep = tmp_path / "KEEP-1.yaml"
        keep.write_text("Core: {Id: SPONSOR-77}\n# MARKER\n", encoding="utf-8")

        with pytest.raises(FileExistsError, match="already exists"):
            scaffold_rule(domain="AE", description="d", output_dir=tmp_path, rule_id="KEEP-1")
        assert "MARKER" in keep.read_text(encoding="utf-8")

    def test_an_existing_yml_rule_blocks_its_id(self, tmp_path: Path) -> None:
        (tmp_path / "FLEET-AE-001.yml").write_text("Core: {Id: FLEET-AE-001}\n", encoding="utf-8")

        out = scaffold_rule(domain="AE", description="d", output_dir=tmp_path)

        assert out.name == "FLEET-AE-002.yaml"

    def test_fleet_check_fails_on_a_duplicate_core_id(self, tmp_path: Path, capsys) -> None:
        from fleet.cli import main

        rules = tmp_path / "rules"
        first = scaffold_rule(domain="AE", description="d", output_dir=rules)
        _edit_check(first)
        second = rules / "copy.yml"
        second.write_text(first.read_text(encoding="utf-8"), encoding="utf-8")
        config = tmp_path / "study_config.yaml"
        config.write_text("study_id: S\nvalidation:\n  custom_rules: rules\n", encoding="utf-8")

        with patch("sys.argv", ["fleet", "check", "--config", str(config)]):
            with pytest.raises(SystemExit) as exc:
                main()

        assert exc.value.code == 1
        assert "duplicate Core.Id FLEET-AE-001" in capsys.readouterr().out


# ── c1-529 c1-530: check_rule placeholder and Exclude scope ──


class TestCheckRuleScope:
    def test_an_unedited_scaffold_gives_one_error(self, tmp_path: Path) -> None:
        out = scaffold_rule(domain="AE", description="d", output_dir=tmp_path)

        errors = check_rule(out)

        assert errors == ["Check still holds the placeholder VARIABLE_NAME: name a real variable"]

    def test_a_rule_scoped_by_exclude_passes(self, tmp_path: Path) -> None:
        out = scaffold_rule(domain="AE", description="d", output_dir=tmp_path)
        _edit_check(out)
        rule = yaml.safe_load(out.read_text(encoding="utf-8"))
        rule["Scope"]["Domains"] = {"Exclude": ["DS"]}
        out.write_text(yaml.safe_dump(rule, sort_keys=False), encoding="utf-8")

        assert check_rule(out) == []


# ── c1-531 c1-532: scaffold header and arguments ──


class TestScaffoldHeader:
    def test_every_rule_type_in_the_header_passes_check_rule(self, tmp_path: Path) -> None:
        out = scaffold_rule(domain="AE", description="d", output_dir=tmp_path)
        header = out.read_text(encoding="utf-8")
        _edit_check(out)
        rule = yaml.safe_load(out.read_text(encoding="utf-8"))

        for rule_type in HEADER_RULE_TYPES:
            assert f"#   {rule_type} " in header
            rule["Rule Type"] = rule_type
            out.write_text(yaml.safe_dump(rule, sort_keys=False), encoding="utf-8")
            assert check_rule(out) == [], rule_type

    def test_the_header_holds_no_machine_path(self, tmp_path: Path) -> None:
        out = scaffold_rule(domain="AE", description="d", output_dir=tmp_path)

        text = out.read_text(encoding="utf-8")

        assert "yaml-language-server" not in text

    @pytest.mark.parametrize(
        ("kwargs", "label"),
        [
            ({"rule_id": "../escaped"}, "rule ID"),
            ({"domain": "A E"}, "domain"),
            ({"prefix": "X/Y"}, "prefix"),
        ],
    )
    def test_a_path_or_space_in_an_id_part_is_refused(
        self, tmp_path: Path, kwargs: dict, label: str
    ) -> None:
        args: dict[str, Any] = {"domain": "AE", "description": "d", "output_dir": tmp_path}
        args.update(kwargs)

        with pytest.raises(ValueError, match=f"Invalid {label}"):
            scaffold_rule(**args)
        assert not (tmp_path.parent / "escaped.yaml").exists()

    def test_add_rule_with_a_path_id_exits_1(self, tmp_path: Path) -> None:
        from fleet.cli import main

        argv = ["fleet", "add-rule", "--domain", "AE", "--description", "d"]
        argv += ["--output", str(tmp_path), "--id", "../x"]
        with patch("sys.argv", argv):
            with pytest.raises(SystemExit) as exc:
                main()

        assert exc.value.code == 1

    def test_each_description_line_is_a_comment(self, tmp_path: Path) -> None:
        out = scaffold_rule(domain="AE", description="first\nCheck: {all: []}", output_dir=tmp_path)

        lines = out.read_text(encoding="utf-8").splitlines()

        assert lines[0] == "# FLEET-AE-001: first"
        assert lines[1] == "# Check: {all: []}"

    @pytest.mark.parametrize(("method", "version"), [("sdtm", "3.4"), ("adam", "1.3")])
    def test_a_dotted_ig_version_asks_the_dashed_library_path(
        self, method: str, version: str
    ) -> None:
        from fleet.core.scaffolder import DefineScaffolder

        asked: list[str] = []

        class _Client:
            def _get(self, path: str) -> dict:
                asked.append(path)
                return {}

        scaffolder = DefineScaffolder(cast(Any, _Client()))
        getattr(scaffolder, f"_fetch_{method}_datasets")(version, [])

        assert asked == (
            ["/mdr/sdtmig/3-4/datasets"] if method == "sdtm" else ["/mdr/adam/adamig-1-3"]
        )
