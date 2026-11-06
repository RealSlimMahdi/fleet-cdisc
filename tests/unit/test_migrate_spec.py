"""``fleet migrate --spec``: the pre-ADR-0008 vocabulary becomes the verb vocabulary."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet.cli import main as cli_main
from fleet.core.define_spec import load_spec_yaml
from fleet.tools.migrate_spec import migrate_block, migrate_spec_text, unmigrated_blocks

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


SEX_FRAGMENT = """\
- name: SEX
  codelist: C66731
  derivation:
    algorithm: assign_ct
    source: sex
    ct_codelist: C66731
"""


def _block(text: str) -> dict:
    return load_spec_yaml(text)["derivation"]


class TestOneBlock:
    def test_the_dm_sex_block_of_adr_0008(self):
        new, changes = migrate_spec_text(SEX_FRAGMENT, set_version=False)
        assert load_spec_yaml(new)[0]["derivation"] == {"algorithm": "assign", "source": "sex"}
        assert changes

    def test_a_block_in_the_verb_vocabulary_is_left_alone(self):
        text = "derivation:\n  algorithm: assign\n  source: sex\n  ct: C66731\n"
        assert migrate_spec_text(text, set_version=False) == (text, [])

    def test_study_day_becomes_duration_with_start_and_end(self):
        text = (
            "derivation:\n  algorithm: study_day\n  analysis_date: ADT\n  reference_date: TRTSDT\n"
        )
        new, _ = migrate_spec_text(text, set_version=False)
        assert _block(new) == {"algorithm": "duration", "end": "ADT", "start": "TRTSDT"}

    def test_an_existing_new_key_wins_over_the_old_one(self):
        text = "derivation:\n  algorithm: seq\n  groups: [A]\n  by: [B]\n"
        new, changes = migrate_spec_text(text, set_version=False)
        assert _block(new) == {"algorithm": "seq", "groups": ["A"], "by": ["B"]}
        assert any("resolve by hand" in c for c in changes)


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


FLOW_DEFINE = """\
datasets:
  - name: DM
    variables:
      - name: DOMAIN
        derivation: {algorithm: hardcode_no_ct, value: DM}
"""


def _migrate_cli(*argv: str) -> int:
    with pytest.raises(SystemExit) as exc:
        cli_main(["migrate", "--spec", *argv])
    return exc.value.code


class TestAuditFindings:
    def test_c1_823_a_flow_block_is_named_and_the_version_is_not_stamped(self, tmp_path, capsys):
        new, changes = migrate_spec_text(FLOW_DEFINE)
        assert (new, changes) == (FLOW_DEFINE, [])
        assert unmigrated_blocks(new) == ["DM.DOMAIN"]
        spec = tmp_path / "define.yaml"
        spec.write_text(FLOW_DEFINE, encoding="utf-8")
        assert _migrate_cli(str(spec), "--write") == 1
        err = capsys.readouterr().err
        assert "left as is, rewrite by hand: DM.DOMAIN" in err
        assert "Nothing to migrate" not in err
        assert spec.read_text(encoding="utf-8") == FLOW_DEFINE

    def test_c1_823_a_quoted_version_is_bumped(self):
        new, _ = migrate_spec_text('fleet_spec_version: "1"\ndatasets: []\n')
        assert new == 'fleet_spec_version: "2"\ndatasets: []\n'
        assert migrate_spec_text(new) == (new, [])

    def test_c1_824_one_bad_file_does_not_stop_the_batch(self, tmp_path, capsys):
        (tmp_path / "a_ok.yaml").write_text(OLD_DEFINE, encoding="utf-8")
        (tmp_path / "b_latin1.yaml").write_bytes("study:\n  id: \xc9TUDE\n".encode("latin-1"))
        (tmp_path / "c_ok.yaml").write_text(OLD_DEFINE, encoding="utf-8")
        assert _migrate_cli(str(tmp_path), "--write") == 1
        err = capsys.readouterr().err
        assert "b_latin1.yaml: cannot read" in err
        assert "Nothing to migrate" not in err
        for name in ("a_ok.yaml", "c_ok.yaml"):
            assert "hardcode_no_ct" not in (tmp_path / name).read_text(encoding="utf-8")

    def test_c1_829_crlf_line_endings_are_kept(self, tmp_path):
        spec = tmp_path / "define.yaml"
        spec.write_bytes(OLD_DEFINE.replace("\n", "\r\n").encode("utf-8"))
        assert _migrate_cli(str(spec), "--write") == 0
        data = spec.read_bytes()
        assert b"fleet_spec_version: 2\r\n" in data
        assert data.count(b"\n") == data.count(b"\r\n")

    def test_c1_827_hidden_folders_and_venvs_are_not_walked(self, tmp_path, capsys):
        for folder in (".venv/lib", "env/lib", "specs"):
            (tmp_path / folder).mkdir(parents=True)
            (tmp_path / folder / "define.yaml").write_text(OLD_DEFINE, encoding="utf-8")
        (tmp_path / "env" / "pyvenv.cfg").write_text("home = /usr\n", encoding="utf-8")
        assert _migrate_cli(str(tmp_path)) == 0
        out = capsys.readouterr().out
        assert "specs/define.yaml" in out
        assert ".venv" not in out
        assert "env/lib" not in out


def test_an_old_flow_style_block_is_reported_and_keeps_the_version():
    """c1-647: a flow block with old names is reported; the version is not raised."""
    text = (
        "datasets:\n"
        "  - name: DM\n"
        "    variables:\n"
        "      - name: SEX\n"
        "        derivation: {algorithm: assign_ct, source: sex, ct_codelist: C66731}\n"
    )
    new_text, changes = migrate_spec_text(text)
    assert (new_text, changes) == (text, [])
    assert unmigrated_blocks(text) == ["DM.SEX"]


def test_a_current_flow_style_block_is_not_reported():
    text = (
        "datasets:\n"
        "  - name: DM\n"
        "    variables:\n"
        "      - name: SEX\n"
        "        derivation: {algorithm: assign, source: sex}\n"
    )
    new_text, changes = migrate_spec_text(text)
    assert "fleet_spec_version: 2" in new_text
    assert not any("flow-style" in c for c in changes)
