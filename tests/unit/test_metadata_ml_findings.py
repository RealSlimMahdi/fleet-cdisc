"""Regression tests for the metadata findings of the alpha audit.

The shipped sponsor rules and the docs sample rule pass ``fleet check-rule``,
and a failure names the missing key (c1-687).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from fleet.validation.rule_scaffolder import check_rule

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "metadata" / "custom_rules"
DOCS = ROOT / "docs" / "concepts" / "custom-rules.md"

pytestmark = pytest.mark.skipif(not RULES.is_dir(), reason="metadata/ is not in the sdist")


@pytest.mark.parametrize("rule", sorted(RULES.glob("*.yaml")), ids=lambda p: p.stem)
def test_c1_687_each_shipped_rule_passes_check_rule(rule):
    assert check_rule(rule) == []


def test_c1_687_the_docs_sample_rule_passes_check_rule(tmp_path):
    blocks = re.findall(r"```yaml\n(Core:.*?)```", DOCS.read_text(encoding="utf-8"), re.S)
    path = tmp_path / "FLEET-AE-001.yaml"
    path.write_text(blocks[0], encoding="utf-8")

    assert check_rule(path) == []


def test_c1_687_a_missing_category_is_named(tmp_path):
    rule = yaml.safe_load((RULES / "SDTMCHK-AE-001.yaml").read_text(encoding="utf-8"))
    del rule["Authorities"][0]["Category"]
    path = tmp_path / "rule.yaml"
    path.write_text(yaml.safe_dump(rule, sort_keys=False), encoding="utf-8")

    assert check_rule(path) == ["Schema: Authorities.0: 'Category' is a required property"]
