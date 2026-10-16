"""``fleet migrate --spec``: the pre-ADR-0008 vocabulary becomes the verb vocabulary."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet.cli import main as cli_main
from fleet.core.define_spec import load_spec_yaml
from fleet.tools.migrate_spec import migrate_block, migrate_spec_text

OLD_DEFINE = """\
# yaml-language-server: $schema=define_spec_schema.json
# CDISCPILOT01 — the DM domain
study:
  id: CDISCPILOT01
  standard: SDTMIG
datasets:
  - name: DM
    variables:
      - name: DOMAIN
        derivation:
          algorithm: hardcode_no_ct
          value: "DM"   # the domain code
      - name: SEX
        codelist: C66731
        derivation:
          source: sex
          algorithm: assign_ct
          ct_codelist: C66731
          ct_mapping:
            "F": "F"
            "M": "M"
      - name: ARMCD
        derivation:
          algorithm: if_then_else
          when:
            - condition: pl.col("arm") == "Pbo"
              value: PBO
          else_value: X
      - name: AESEQ
        derivation:
          algorithm: seq
          groups: [USUBJID]
"""


class TestMigrateBlock:
    def test_the_dm_sex_block_of_adr_0008(self):
        new, changes = migrate_block(
            {"algorithm": "assign_ct", "source": "sex", "ct_codelist": "C66731"},
            codelist="C66731",
        )
        assert new == {"algorithm": "assign", "source": "sex"}
        assert changes

    def test_a_block_in_the_verb_vocabulary_is_left_alone(self):
        block = {"algorithm": "assign", "source": "sex", "ct": "C66731"}
        assert migrate_block(block) == (block, [])

    def test_study_day_becomes_duration_with_start_and_end(self):
        new, _ = migrate_block(
            {"algorithm": "study_day", "analysis_date": "ADT", "reference_date": "TRTSDT"}
        )
        assert new == {"algorithm": "duration", "end": "ADT", "start": "TRTSDT"}

    def test_an_existing_new_key_wins_over_the_old_one(self):
        new, _ = migrate_block({"algorithm": "seq", "groups": ["A"], "by": ["B"]})
        assert new == {"algorithm": "seq", "groups": ["A"], "by": ["B"]}


class TestMigrateSpecText:
    def test_comments_and_layout_survive(self):
        new, changes = migrate_spec_text(OLD_DEFINE)
        assert new.startswith("# yaml-language-server:")
        assert "# CDISCPILOT01 — the DM domain" in new
        assert 'value: "DM"   # the domain code' in new
        assert len(changes) == 9  # 7 lines rewritten, one ct line dropped, the version added

    def test_blocks_are_rewritten_whatever_the_key_order(self):
        new, _ = migrate_spec_text(OLD_DEFINE)
        data = load_spec_yaml(new)
        by_name = {v["name"]: v["derivation"] for v in data["datasets"][0]["variables"]}
        assert by_name["DOMAIN"] == {"algorithm": "assign", "value": "DM"}
        # ct equal to the variable's codelist: is dropped, the keys before algorithm: too
        assert by_name["SEX"] == {
            "algorithm": "assign",
            "source": "sex",
            "ct_map": {"F": "F", "M": "M"},
        }
        assert by_name["ARMCD"]["algorithm"] == "case_when"
        assert by_name["ARMCD"]["else"] == "X"
        assert by_name["AESEQ"] == {"algorithm": "seq", "by": ["USUBJID"]}

    def test_the_version_is_written_before_the_first_top_level_key(self):
        new, _ = migrate_spec_text(OLD_DEFINE)
        assert new.index("fleet_spec_version: 2\n") < new.index("study:")
        again, changes = migrate_spec_text(new)
        assert again == new
        assert changes == []

    def test_version_1_is_bumped_in_place(self):
        new, changes = migrate_spec_text("fleet_spec_version: 1\ndatasets: []\n")
        assert new == "fleet_spec_version: 2\ndatasets: []\n"
        assert changes == ["line 1: fleet_spec_version -> 2"]

    def test_fragments_keep_no_version(self):
        text = "derivation:\n  algorithm: assigned\n  value: S01\n"
        new, _ = migrate_spec_text(text, set_version=False)
        assert new == "derivation:\n  algorithm: assign\n  value: S01\n"

    def test_simplified_single_dataset_format(self):
        text = (
            "domain: AE\nvariables:\n  - target: USUBJID\n    algorithm: assign_no_ct\n"
            "    source: subject_id\n  - algorithm: merge\n    target: EXTRA\n"
            "    dataset: SUPP\n    join_on: USUBJID\n"
        )
        new, _ = migrate_spec_text(text)
        data = load_spec_yaml(new)
        assert data["fleet_spec_version"] == 2
        assert data["variables"][0]["algorithm"] == "assign"
        assert data["variables"][1] == {
            "algorithm": "merge",
            "target": "EXTRA",
            "dataset": "SUPP",
            "on": "USUBJID",
        }


class TestCli:
    def test_diff_mode_leaves_the_file_alone(self, tmp_path: Path, capsys):
        spec = tmp_path / "define.yaml"
        spec.write_text(OLD_DEFINE, encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            cli_main(["migrate", "--spec", str(spec)])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "-          algorithm: hardcode_no_ct" in out
        assert "+          algorithm: assign" in out
        assert spec.read_text(encoding="utf-8") == OLD_DEFINE

    def test_write_rewrites_the_file(self, tmp_path: Path):
        spec = tmp_path / "define.yaml"
        spec.write_text(OLD_DEFINE, encoding="utf-8")
        with pytest.raises(SystemExit) as exc:
            cli_main(["migrate", "--spec", str(spec), "--write"])
        assert exc.value.code == 0
        assert "hardcode_no_ct" not in spec.read_text(encoding="utf-8")
        assert "fleet_spec_version: 2" in spec.read_text(encoding="utf-8")


def test_the_join_key_on_stays_a_string():
    """``on:`` is a YAML 1.1 boolean; the spec loader keeps it a key (#87)."""
    data = load_spec_yaml("algorithm: merge\non: USUBJID\nflag: true\nmode: yes\n")
    assert data == {"algorithm": "merge", "on": "USUBJID", "flag": True, "mode": "yes"}


class TestReviewFindings:
    def test_sibling_items_of_the_simplified_format_do_not_share_keys(self):
        """A `ct:` on the first item must not stop the rename of `ct_codelist:` on the second."""
        text = (
            "domain: DM\nvariables:\n"
            "  - target: SEX\n    algorithm: assign_ct\n    source: sex\n    ct: C66731\n"
            "  - target: RACE\n    algorithm: assign_ct\n    source: race\n    ct_codelist: C74457\n"
        )
        new, _ = migrate_spec_text(text)
        data = load_spec_yaml(new)
        assert data["variables"][1] == {
            "target": "RACE",
            "algorithm": "assign",
            "source": "race",
            "ct": "C74457",
        }

    def test_a_quoted_algorithm_value_is_rewritten(self):
        new, changes = migrate_spec_text(
            'derivation:\n  algorithm: "assign_ct"\n  source: sex\n  ct_codelist: C66731\n',
            set_version=False,
        )
        assert new == 'derivation:\n  algorithm: "assign"\n  source: sex\n  ct: C66731\n'
        assert len(changes) == 2

    def test_old_and_new_key_together_are_reported_not_hidden(self):
        text = "derivation:\n  algorithm: assign_ct\n  ct_codelist: C66731\n  ct: C66731\n"
        new, changes = migrate_spec_text(text, set_version=False)
        assert "ct_codelist: C66731" in new
        assert any("resolve by hand" in c for c in changes)
        _, block_changes = migrate_block({"algorithm": "assign_ct", "ct_codelist": "A", "ct": "B"})
        assert any("resolve by hand" in c for c in block_changes)
