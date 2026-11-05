"""RulesScaffolder with a fake CDISC Library client (c1-751)."""

from __future__ import annotations

from pathlib import Path

import yaml

from fleet.core.rules_scaffolder import RulesScaffolder
from fleet.core.study_context import StudyContext


class _Client:
    """Answers every path with two rules: one for DM, one for every domain."""

    def __init__(self) -> None:
        self.paths: list[str] = []

    def get(self, path: str) -> dict:
        self.paths.append(path)
        return {
            "rules": {
                "CORE-000001": {
                    "Core": {"Id": "CORE-000001", "Status": "Published"},
                    "Scope": {"Domains": {"Include": ["DM"]}},
                    "Description": "DM rule",
                },
                "CORE-000002": {
                    "Core": {"Id": "CORE-000002", "Status": "Published"},
                    "Scope": {"Domains": {"Include": ["ALL"]}},
                    "Description": "Every domain",
                },
            }
        }


def _study(tmp_path: Path) -> StudyContext:
    ctx = StudyContext.init(tmp_path, study_id="S")
    (ctx.metadata_sdtm_dir / "define.yaml").write_text(
        "study:\n  standard_version: '3.4'\n", encoding="utf-8"
    )
    return ctx


def test_rules_are_grouped_by_domain_with_an_all_bucket(tmp_path):
    ctx = _study(tmp_path)
    client = _Client()

    out = RulesScaffolder(client).scaffold_sdtm(ctx)

    assert client.paths == ["/mdr/rules/sdtmig/3-4"]
    assert sorted(p.name for p in out.glob("*.yaml")) == ["DM.yaml", "_ALL.yaml"]
    dm = yaml.safe_load((out / "DM.yaml").read_text(encoding="utf-8"))
    assert [r["core_id"] for r in dm["rules"]] == ["CORE-000001"]
    every = yaml.safe_load((out / "_ALL.yaml").read_text(encoding="utf-8"))
    assert [r["core_id"] for r in every["rules"]] == ["CORE-000002"]


def test_an_existing_file_is_kept_without_force(tmp_path):
    ctx = _study(tmp_path)
    dm = ctx.rules_sdtm_dir / "DM.yaml"
    dm.parent.mkdir(parents=True, exist_ok=True)
    dm.write_text("kept\n", encoding="utf-8")

    RulesScaffolder(_Client()).scaffold_sdtm(ctx)
    assert dm.read_text(encoding="utf-8") == "kept\n"

    RulesScaffolder(_Client()).scaffold_sdtm(ctx, force=True)
    assert "CORE-000001" in dm.read_text(encoding="utf-8")
