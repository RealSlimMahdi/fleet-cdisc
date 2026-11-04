"""Envelope validation for define.yaml / simplified spec files.

The derivation half of a spec is validated by the algorithm registry;
these tests cover the envelope around it — the half that used to fail
silently (a typo'd top-level key produced zero derivations and returned
the input frame unchanged).
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
import yaml

import fleet  # noqa: F401 — triggers namespace registration
from fleet.core.define_spec import load_define_spec
from fleet.core.exceptions import SpecError

SCHEMA_PATH = Path(fleet.__file__).parent / "define_xml" / "schemas" / "define_spec_schema.json"


@pytest.fixture
def raw() -> pl.DataFrame:
    return pl.from_repr("""\
┌────────────┬─────┐
│ subject_id ┆ sex │
│ ---        ┆ --- │
│ str        ┆ str │
╞════════════╪═════╡
│ S001       ┆ M   │
└────────────┴─────┘
""")


def _write(tmp_path: Path, spec: dict) -> Path:
    p = tmp_path / "define.yaml"
    p.write_text(yaml.dump(spec, allow_unicode=True), encoding="utf-8")
    return p


class TestEnvelopeErrors:
    def test_misspelled_top_level_key_raises_instead_of_silent_no_op(self, raw, tmp_path):
        """`datsets:` used to yield the input frame back with no warning."""
        spec = _write(
            tmp_path,
            {"datsets": [{"name": "DM", "variables": [{"name": "USUBJID"}]}]},
        )
        with pytest.raises(SpecError, match="datsets"):
            raw.sdtm.from_spec(spec, dataset="DM").to_frame()

    def test_misspelled_dataset_key_raises(self, raw, tmp_path):
        """`varibles:` used to skip the whole dataset silently."""
        spec = _write(
            tmp_path,
            {"datasets": [{"name": "DM", "varibles": [{"name": "USUBJID"}]}]},
        )
        with pytest.raises(SpecError, match="varibles"):
            raw.sdtm.from_spec(spec, dataset="DM").to_frame()

    def test_variable_without_name_names_its_location(self, raw, tmp_path):
        """Used to surface as a bare ``KeyError: 'name'``."""
        spec = _write(
            tmp_path,
            {
                "datasets": [
                    {
                        "name": "DM",
                        "variables": [
                            {"derivation": {"algorithm": "assign", "source": "subject_id"}}
                        ],
                    }
                ]
            },
        )
        with pytest.raises(SpecError, match="name"):
            raw.sdtm.from_spec(spec, dataset="DM").to_frame()

    def test_spec_with_no_datasets_or_variables_raises(self, raw, tmp_path):
        spec = _write(tmp_path, {"study": {"id": "PILOT01"}})
        with pytest.raises(SpecError, match="neither 'datasets:'"):
            raw.sdtm.from_spec(spec, dataset="DM").to_frame()

    def test_non_mapping_spec_raises(self, raw, tmp_path):
        p = tmp_path / "define.yaml"
        p.write_text("- just\n- a list\n", encoding="utf-8")
        with pytest.raises(SpecError, match="must be a YAML mapping"):
            raw.sdtm.from_spec(p, dataset="DM").to_frame()


class TestBothFormatsStillLoad:
    def test_define_yaml_format(self, raw, tmp_path):
        spec = _write(
            tmp_path,
            {
                "datasets": [
                    {
                        "name": "DM",
                        "variables": [
                            {
                                "name": "USUBJID",
                                "derivation": {
                                    "algorithm": "assign",
                                    "source": "subject_id",
                                },
                            }
                        ],
                    }
                ]
            },
        )
        out = raw.sdtm.from_spec(spec, dataset="DM").to_frame()
        assert out["USUBJID"].to_list() == ["S001"]

    def test_simplified_format(self, raw, tmp_path):
        spec = _write(
            tmp_path,
            {
                "domain": "DM",
                "variables": [{"target": "USUBJID", "algorithm": "assign", "source": "subject_id"}],
            },
        )
        out = raw.sdtm.from_spec(spec).to_frame()
        assert out["USUBJID"].to_list() == ["S001"]

    def test_ct_block_alias(self, tmp_path):
        spec = _write(
            tmp_path,
            {"ct": {"validate": True}, "datasets": [{"name": "DM", "variables": []}]},
        )
        assert load_define_spec(spec).ct.enabled is True

    def test_unknown_ct_key_raises(self, tmp_path):
        spec = _write(
            tmp_path,
            {"ct": {"valdate": True}, "datasets": [{"name": "DM", "variables": []}]},
        )
        with pytest.raises(SpecError, match="valdate"):
            load_define_spec(spec)


def test_model_accepts_every_key_the_published_schema_allows():
    """Anti-drift: the JSON schema is the published contract for spec files.

    Both directions matter — a key the schema allows must execute, and a
    key the model reads must not be flagged as invalid in the editor
    (``fleet lsp`` validates the whole document against this schema).
    """
    from fleet.core.define_spec import DatasetEntry, DefineSpec

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    model_keys = {f.alias or n for n, f in DefineSpec.model_fields.items()}
    assert set(schema["properties"]) == model_keys

    dataset_keys = {f.alias or n for n, f in DatasetEntry.model_fields.items()}
    assert set(schema["$defs"]["dataset"]["properties"]) == dataset_keys

    from fleet.core.define_spec import VariableEntry

    assert set(schema["$defs"]["variable"]["properties"]) == set(VariableEntry.model_fields)


class TestUnknownVariableKey:
    """c1-743: a misspelled variable key used to drop its derivation with no message."""

    @pytest.mark.parametrize(
        ("key", "hint"),
        [("derivaton", "derivation"), ("derviation", "derivation"), ("codelst", "codelist")],
    )
    def test_misspelled_variable_key_names_the_variable(self, raw, tmp_path, key, hint):
        spec = _write(
            tmp_path,
            {
                "datasets": [
                    {
                        "name": "TEST",
                        "variables": [
                            {"name": "MYVAR", key: {"algorithm": "assign", "value": "X"}}
                        ],
                    }
                ]
            },
        )
        with pytest.raises(SpecError, match=rf"TEST\.MYVAR: unknown key '{key}'.*'{hint}'"):
            raw.sdtm.from_spec(spec, dataset="TEST").to_frame()

    def test_pick_keys_on_the_variable_level_are_refused(self, raw, tmp_path):
        """c1-651: ``algorithm: pick`` beside ``name:`` used to derive nothing."""
        spec = _write(
            tmp_path,
            {
                "datasets": [
                    {
                        "name": "ADSL",
                        "variables": [{"name": "LSTALVDT", "algorithm": "pick", "events": []}],
                    }
                ]
            },
        )
        with pytest.raises(SpecError, match=r"ADSL\.LSTALVDT: unknown key 'algorithm'"):
            load_define_spec(spec)


class TestYamlValuesStayAsWritten:
    """c1-741: YAML 1.1 read 010 as 8, 12:30 as 750 and a bare date as a date."""

    def test_bare_constants_stay_text(self):
        from fleet.core.define_spec import load_spec_yaml

        doc = load_spec_yaml(
            "a: 010\nb: 12:30\nc: 12:30.5\nd: 2024-01-15\ne: {001: A, 002: B}\n"
            "f: 10\ng: 0.5\nh: -3\ni: true\n"
        )
        assert doc == {
            "a": "010",
            "b": "12:30",
            "c": "12:30.5",
            "d": "2024-01-15",
            "e": {"001": "A", "002": "B"},
            "f": 10,
            "g": 0.5,
            "h": -3,
            "i": True,
        }

    def test_siteid_constant_keeps_its_leading_zero(self, raw, tmp_path):
        p = tmp_path / "define.yaml"
        p.write_text(
            "datasets:\n"
            "  - name: DM\n"
            "    variables:\n"
            "      - name: SITEID\n"
            "        type: text\n"
            "        derivation:\n"
            "          algorithm: assign\n"
            "          value: 010\n",
            encoding="utf-8",
        )
        out = raw.sdtm.from_spec(p, dataset="DM").to_frame()
        assert out["SITEID"].to_list() == ["010"]

    def test_duplicate_key_is_refused_with_its_line(self, tmp_path):
        p = tmp_path / "define.yaml"
        p.write_text(
            "datasets:\n"
            "  - name: DM\n"
            "    variables:\n"
            "      - name: USUBJID\n"
            "        derivation:\n"
            "          algorithm: assign\n"
            "          source: FIRST\n"
            "          source: SECOND\n",
            encoding="utf-8",
        )
        with pytest.raises(SpecError, match=r"duplicate key 'source'[\s\S]*line 8"):
            load_define_spec(p)


def test_nsv_metadata_keys_are_valid_against_the_published_schema():
    """``role:``/``evaluator:`` drive supp() but used to fail schema validation."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    doc = yaml.safe_load("""
study:
  id: PILOT01
  name: Pilot
  description: Pilot study
  protocol_name: PILOT
  originator: Sponsor
  standard: SDTMIG
  standard_version: "3.4"
datasets:
  - name: DM
    label: Demographics
    structure: One record per subject
    keys: [STUDYID, USUBJID]
    variables:
      - name: SAFETY
        label: Safety Population Flag
        type: text
        role: qualifier
        evaluator: INVESTIGATOR
        derivation:
          algorithm: nsv
          source: safety_flag
""")
    jsonschema.validate(doc, schema)


def test_legacy_define_xml_20_origin_values_are_rejected():
    """One origin vocabulary: Define-XML 2.1 Types, shared with QORIG."""
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    enum = schema["$defs"]["variable"]["properties"]["origin"]["enum"]
    assert enum == ["Collected", "Derived", "Assigned", "Protocol", "Predecessor"]
    assert "CRF" not in enum and "eDT" not in enum

    doc = {"origin": "CRF"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, schema["$defs"]["variable"])
