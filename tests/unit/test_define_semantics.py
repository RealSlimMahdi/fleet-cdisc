"""Reviewer-facing Define-XML content: lint, output reproducibility, route parity.

Locks in the method/origin conformance contract:

* the semantic lint (:mod:`fleet.define_xml.semantic_checks`) rejects the
  defect classes it exists for and passes the shipped examples;
* every registry algorithm renders clean submission text (no unfilled
  placeholders, no API markup) — a new algorithm cannot ship without
  reviewer-safe text;
* the committed example defines (``outputs/cdiscpilot01/define_*.xml``)
  are reproducible from their specs — any change to submission-facing
  text lands as a reviewed diff on the real artifact, never as silent
  drift (same pattern as the JSON-schema sync test);
* the inline route (pipeline → ``to_spec_yaml()`` → define.xml) yields
  text identical to the spec-driven route.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import polars as pl
import pytest
import yaml

import fleet
from fleet.core import spec_registry
from fleet.core.lineage import latest_lineage_of
from fleet.define_xml import DefineSpecGenerator, semantic_errors
from fleet.define_xml.xsd import missing_files

ODM = "{http://www.cdisc.org/ns/odm/v1.3}"
DEF = "{http://www.cdisc.org/ns/def/v2.1}"

EXAMPLES = Path(__file__).parent.parent.parent / "examples" / "cdiscpilot01"
OUTPUTS = Path(__file__).parent.parent.parent / "outputs" / "cdiscpilot01"

schemas_present = pytest.mark.skipif(bool(missing_files()), reason="CDISC schema set not installed")


# ===================================================================== #
# Registry text rendering                                                #
# ===================================================================== #


class TestRegistryRendering:
    """Every algorithm has reviewer-safe text by construction."""

    @pytest.mark.parametrize("standard", ["sdtm", "adam"])
    def test_every_algorithm_renders_clean_text(self, standard):
        for algo in spec_registry.algorithms(standard):
            for params in ({}, {p.name: "X" for p in algo.params}):
                text = spec_registry.render_method_text(
                    standard, algo.name, params, target="TARGET"
                )
                assert text, f"{standard}:{algo.name} rendered empty text"
                assert "{" not in text and "}" not in text, (
                    f"{standard}:{algo.name} left an unfilled placeholder: {text!r}"
                )
                assert "`" not in text and not re.search(r"\*\S[^*]*\*", text), (
                    f"{standard}:{algo.name} rendered API markup: {text!r}"
                )

    @pytest.mark.parametrize("standard", ["sdtm", "adam"])
    def test_templates_reference_only_declared_params(self, standard):
        for algo in spec_registry.algorithms(standard):
            for shape_keys, template in algo.method_text:
                keys = set(re.findall(r"{(\w+)}", template)) | set(shape_keys)
                declared = {p.name for p in algo.params} | {"target"}
            assert keys <= declared, (
                f"{standard}:{algo.name} template names unknown params {keys - declared}"
            )

    def test_comment_free_defaults_read_as_submission_text(self):
        assert (
            spec_registry.render_method_text("adam", "chg", {})
            == "Change from baseline: AVAL - BASE."
        )
        assert (
            spec_registry.render_method_text("sdtm", "assign", {"source": "raw_sex"})
            == "Direct copy of raw_sex."
        )

    def test_formal_expression_is_a_faithful_call(self):
        expr = spec_registry.render_formal_expression(
            "sdtm", "assign", {"source": "subject_id"}, target="USUBJID"
        )
        assert expr == (
            "fleet.core._verb_mixin.SharedVerbsMixin.assign('USUBJID', source='subject_id')"
        )

    def test_unknown_algorithm_returns_none(self):
        assert spec_registry.render_method_text("sdtm", "nope", {}) is None
        assert spec_registry.render_formal_expression("sdtm", "nope", {}) is None


# ===================================================================== #
# Semantic lint                                                          #
# ===================================================================== #


def _doc(body: str) -> str:
    return (
        '<ODM xmlns="http://www.cdisc.org/ns/odm/v1.3" '
        'xmlns:def="http://www.cdisc.org/ns/def/v2.1">'
        f'<Study OID="S"><MetaDataVersion OID="M" Name="m">{body}'
        "</MetaDataVersion></Study></ODM>"
    )


def _item_def(oid: str, origin: str, desc: str | None = None) -> str:
    desc_xml = (
        f"<Description><TranslatedText xml:lang='en'>{desc}</TranslatedText></Description>"
        if desc
        else ""
    )
    return (
        f'<ItemDef OID="{oid}" Name="X" DataType="text">'
        f'<def:Origin Type="{origin}">{desc_xml}</def:Origin></ItemDef>'
    )


def _method_def(oid: str) -> str:
    return (
        f'<MethodDef OID="{oid}" Name="Algorithm for X" Type="Computation">'
        "<Description><TranslatedText xml:lang='en'>t</TranslatedText></Description>"
        "</MethodDef>"
    )


class TestSemanticLint:
    def test_method_on_non_derived_is_flagged(self):
        xml = _doc(
            '<ItemGroupDef OID="IG.DM" Name="DM" Repeating="No">'
            '<ItemRef ItemOID="IT.DM.SEX" MethodOID="MT.DM.SEX"/></ItemGroupDef>'
            + _item_def("IT.DM.SEX", "Collected")
            + _method_def("MT.DM.SEX")
        )
        problems = semantic_errors(xml)
        assert len(problems) == 1 and "Collected" in problems[0]

    def test_method_on_derived_is_clean(self):
        xml = _doc(
            '<ItemGroupDef OID="IG.DM" Name="DM" Repeating="No">'
            '<ItemRef ItemOID="IT.DM.AGEGR1" MethodOID="MT.DM.AGEGR1"/></ItemGroupDef>'
            + _item_def("IT.DM.AGEGR1", "Derived")
            + _method_def("MT.DM.AGEGR1")
        )
        assert semantic_errors(xml) == []

    @pytest.mark.parametrize(
        "text",
        [
            "Assign *target* from a source column.",
            "Derive using a ``Derivation`` object.",
            "See `ref` for details.",
        ],
    )
    def test_api_markup_in_translated_text_is_flagged(self, text):
        xml = _doc(_item_def("IT.X", "Derived", text))
        assert any("markup" in p for p in semantic_errors(xml))

    def test_plain_asterisk_is_not_markup(self):
        xml = _doc(_item_def("IT.X", "Derived", "BMI = weight / height * height."))
        assert semantic_errors(xml) == []

    def test_algorithm_id_as_method_name_is_flagged(self):
        """A method Fleet produced must not be named after the verb it ran."""
        xml = _doc(
            '<MethodDef OID="MT.X" Name="assign" Type="Computation">'
            "<Description><TranslatedText xml:lang='en'>t</TranslatedText></Description>"
            "<FormalExpression Context=\"Python/Fleet\">x.assign('A')</FormalExpression>"
            "</MethodDef>"
        )
        assert any("algorithm id" in p for p in semantic_errors(xml))
        clean = xml.replace('Name="assign"', 'Name="Algorithm for AGEGR1"')
        assert semantic_errors(clean) == []

    def test_a_sponsor_method_named_map_or_date_is_not_flagged(self):
        """Verb names are ordinary words; a hand-written Define-XML may use them."""
        xml = _doc(
            '<MethodDef OID="MT.X" Name="date" Type="Computation">'
            "<Description><TranslatedText xml:lang='en'>t</TranslatedText></Description>"
            "</MethodDef>"
        )
        assert semantic_errors(xml) == []

    def test_the_merge_join_key_reaches_the_formal_expression(self, tmp_path):
        """``on:`` is read as a key, not as the boolean True, by the Define-XML generator (#87)."""
        spec = {
            "study": {
                "id": "S",
                "name": "S",
                "description": "on test",
                "protocol_name": "S",
                "originator": "Fleet",
                "standard": "ADAMIG",
                "standard_version": "1.1",
            },
            "datasets": [
                {
                    "name": "ADAE",
                    "label": "Adverse Events Analysis",
                    "structure": "One record per event",
                    "keys": ["USUBJID"],
                    "variables": [
                        {
                            "name": "TRTSDT",
                            "label": "Date of First Exposure",
                            "type": "date",
                            "origin": "Derived",
                            "derivation": {
                                "algorithm": "merge",
                                "dataset": "ADSL",
                                "on": "USUBJID",
                            },
                        }
                    ],
                }
            ],
        }
        path = tmp_path / "define.yaml"
        path.write_text(
            "study:\n  id: S\n  name: S\n  description: on test\n  protocol_name: S\n"
            "  originator: Fleet\n  standard: ADAMIG\n  standard_version: '1.1'\n"
            "datasets:\n  - name: ADAE\n    label: Adverse Events Analysis\n"
            "    structure: One record per event\n    keys: [USUBJID]\n    variables:\n"
            "      - name: USUBJID\n        label: Unique Subject Identifier\n        type: text\n"
            "        length: 20\n        origin: Predecessor\n        predecessor: ADSL.USUBJID\n"
            "      - name: TRTSDT\n        label: Date of First Exposure\n        type: date\n"
            "        origin: Derived\n        derivation:\n          algorithm: merge\n"
            "          dataset: ADSL\n          on: USUBJID\n"
        )
        del spec
        root = ET.fromstring(DefineSpecGenerator(path, enrich_methods=True).to_xml_string())
        expressions = [f.text for f in root.iter(f"{ODM}FormalExpression")]
        assert any("on='USUBJID'" in e for e in expressions), expressions
        texts = [e.text for e in root.iter(f"{ODM}TranslatedText")]
        assert "Records merged from ADSL (join key: USUBJID)." in texts

    def test_predecessor_description_must_be_dataset_variable(self):
        assert semantic_errors(_doc(_item_def("IT.X", "Predecessor", "DM.COUNTRY"))) == []
        assert any(
            "Predecessor" in p
            for p in semantic_errors(_doc(_item_def("IT.X", "Predecessor", "carried over")))
        )
        assert any(
            "Predecessor" in p for p in semantic_errors(_doc(_item_def("IT.X", "Predecessor")))
        )


# ===================================================================== #
# Generator semantics (fixture specs)                                    #
# ===================================================================== #

_STUDY = {
    "id": "T01",
    "name": "T01",
    "description": "Fixture",
    "protocol_name": "T01",
    "originator": "Fleet Tests",
    "standard": "SDTMIG",
    "standard_version": "3.4",
}


def _generate(spec: dict, tmp_path: Path, **kwargs) -> ET.Element:
    path = tmp_path / "define.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True))
    return ET.fromstring(DefineSpecGenerator(path, **kwargs).to_xml_string())


def _origin(root: ET.Element, name: str) -> ET.Element:
    item = next(i for i in root.iter(f"{ODM}ItemDef") if i.get("Name") == name)
    return item.find(f"{DEF}Origin")


def _origin_desc(root: ET.Element, name: str) -> str | None:
    desc = _origin(root, name).find(f"{ODM}Description/{ODM}TranslatedText")
    return None if desc is None else desc.text


@schemas_present
class TestGeneratorSemantics:
    def _spec(self, *variables: dict) -> dict:
        return {
            "study": dict(_STUDY),
            "datasets": [
                {
                    "name": "DM",
                    "label": "Demographics",
                    "structure": "One record per subject",
                    "keys": ["USUBJID"],
                    "variables": [
                        {
                            "name": "USUBJID",
                            "label": "Unique Subject Identifier",
                            "type": "text",
                            "origin": "Derived",
                            "mandatory": True,
                        },
                        *variables,
                    ],
                }
            ],
        }

    def test_a_failed_validation_names_no_option_the_cli_lacks(self, tmp_path):
        """c1-536: the error told a CLI user to pass validate_xml=False."""
        spec = self._spec(
            {
                "name": "SEX",
                "label": "Sex",
                "type": "text",
                "length": 1,
                "origin": "Derived",
                "comment": "Copy of ``sex``",
            }
        )
        with pytest.raises(Exception, match="Correct define.yaml") as err:
            _generate(spec, tmp_path)
        assert "Pass validate_xml=False" not in str(err.value)

    def test_comment_becomes_the_method_description(self, tmp_path):
        spec = self._spec(
            {
                "name": "AGEGR1",
                "label": "Pooled Age Group 1",
                "type": "text",
                "origin": "Derived",
                "comment": "AGE grouped as <65, 65-80, >80 years",
                "derivation": {"algorithm": "assign", "source": "age_group"},
            }
        )
        root = _generate(spec, tmp_path, enrich_methods=True)
        method = next(m for m in root.iter(f"{ODM}MethodDef") if m.get("OID") == "MT.DM.AGEGR1")
        assert method.get("Name") == "Algorithm for AGEGR1"
        text = method.find(f"{ODM}Description/{ODM}TranslatedText").text
        assert text == "AGE grouped as <65, 65-80, >80 years"
        # Consumed by the MethodDef — not repeated in the Origin.
        assert _origin_desc(root, "AGEGR1") is None

    def test_comment_stays_in_origin_without_enrichment(self, tmp_path):
        spec = self._spec(
            {
                "name": "AGEGR1",
                "label": "Pooled Age Group 1",
                "type": "text",
                "origin": "Derived",
                "comment": "AGE grouped as <65, 65-80, >80 years",
                "derivation": {"algorithm": "assign", "source": "age_group"},
            }
        )
        with pytest.warns(UserWarning, match=r"DM\.AGEGR1: no MethodDef"):
            root = _generate(spec, tmp_path, enrich_methods=False)
        assert _origin_desc(root, "AGEGR1") == "AGE grouped as <65, 65-80, >80 years"
        assert list(root.iter(f"{ODM}MethodDef")) == []

    def test_non_derived_variable_gets_no_method(self, tmp_path):
        spec = self._spec(
            {
                "name": "SITEID",
                "label": "Study Site Identifier",
                "type": "text",
                "origin": "Assigned",
                "derivation": {"algorithm": "assign", "source": "site"},
            }
        )
        root = _generate(spec, tmp_path, enrich_methods=True)
        assert list(root.iter(f"{ODM}MethodDef")) == []
        refs = [r for r in root.iter(f"{ODM}ItemRef") if r.get("MethodOID")]
        assert refs == []

    def test_collected_without_pages_names_the_crf(self, tmp_path):
        spec = self._spec({"name": "SEX", "label": "Sex", "type": "text", "origin": "Collected"})
        root = _generate(spec, tmp_path)
        assert _origin_desc(root, "SEX") == "Case Report Form"

    def test_collected_vendor_source_gets_no_crf_placeholder(self, tmp_path):
        spec = self._spec(
            {
                "name": "LBORRES",
                "label": "Result or Finding in Original Units",
                "type": "text",
                "origin": "Collected",
                "origin_source": "Vendor",
            }
        )
        root = _generate(spec, tmp_path)
        assert _origin(root, "LBORRES").get("Source") == "Vendor"
        assert _origin_desc(root, "LBORRES") is None

    def test_predecessor_origin_names_its_source(self, tmp_path):
        spec = self._spec(
            {
                "name": "COUNTRY",
                "label": "Country",
                "type": "text",
                "origin": "Predecessor",
                "predecessor": "DM.COUNTRY",
            }
        )
        root = _generate(spec, tmp_path)
        origin = _origin(root, "COUNTRY")
        assert origin.get("Type") == "Predecessor"
        assert origin.get("Source") is None
        assert _origin_desc(root, "COUNTRY") == "DM.COUNTRY"

    def test_predecessor_without_reference_fails_schema_validation(self, tmp_path):
        spec = self._spec(
            {
                "name": "COUNTRY",
                "label": "Country",
                "type": "text",
                "origin": "Predecessor",
            }
        )
        path = tmp_path / "define.yaml"
        path.write_text(yaml.safe_dump(spec, sort_keys=False))
        with pytest.raises(ValueError, match="predecessor"):
            DefineSpecGenerator(path)

    def test_value_level_parent_points_at_vlm(self, tmp_path):
        spec = self._spec(
            {"name": "AVAL", "label": "Analysis Value", "type": "float"},
            {"name": "PARAMCD", "label": "Parameter Code", "type": "text"},
        )
        spec["datasets"][0]["value_level"] = [
            {
                "param": "SYSBP",
                "variables": [
                    {
                        "name": "AVAL",
                        "label": "Analysis Value (SYSBP)",
                        "type": "float",
                        "derivation": {
                            "algorithm": "derivation",
                            "callable": "fleet.core.lineage.lineage_of",
                        },
                    }
                ],
            }
        ]
        root = _generate(spec, tmp_path)
        parent = next(i for i in root.iter(f"{ODM}ItemDef") if i.get("OID") == "IT.DM.AVAL")
        assert parent.find(f"{DEF}ValueListRef") is not None
        desc = parent.find(f"{DEF}Origin/{ODM}Description/{ODM}TranslatedText")
        assert desc is not None and desc.text == "See Value Level Metadata"

    def test_adam_collected_source_variables_warn_predecessor(self, tmp_path):
        spec = self._spec(
            {
                "name": "AGE",
                "label": "Age",
                "type": "integer",
                "origin": "Collected",
                "derivation": {"algorithm": "assign", "source": "AGE"},
            }
        )
        spec["study"]["standard"] = "ADAMIG"
        spec["study"]["standard_version"] = "1.1"
        spec["datasets"][0]["name"] = "ADSL"
        with pytest.warns(UserWarning, match="Predecessor"):
            _generate(spec, tmp_path)


# ===================================================================== #
# Committed outputs stay reproducible from their specs                   #
# ===================================================================== #


@schemas_present
@pytest.mark.parametrize("standard", ["sdtm", "adam"])
def test_committed_define_outputs_are_reproducible(standard):
    """The committed define.xml must match what the code generates from its spec.

    Same pattern as the JSON-schema sync test: ``outputs/cdiscpilot01`` is a
    build artifact of ``examples/``.  A template, renderer, or spec change
    fails here until the artifact is regenerated —
    ``uv run python examples/cdiscpilot01_spec_driven.py`` — so every change
    to submission-facing content is reviewed on the real define.xml diff.
    """
    committed = (OUTPUTS / f"define_{standard}.xml").read_text(encoding="utf-8")
    regenerated = DefineSpecGenerator(
        EXAMPLES / standard / "define.yaml", enrich_methods=True
    ).to_xml_string()

    def stamp_free(xml: str) -> str:
        # Canonical XML: the same document gives the same text on every Python (c1-617).
        from lxml import etree

        stamped = re.sub(r'CreationDateTime="[^"]*"', 'CreationDateTime=""', xml)
        return etree.canonicalize(xml_data=stamped, strip_text=True)

    assert stamp_free(regenerated) == stamp_free(committed), (
        f"outputs/cdiscpilot01/define_{standard}.xml is stale — regenerate with "
        "`uv run python examples/cdiscpilot01_spec_driven.py` and review the diff"
    )


@schemas_present
@pytest.mark.parametrize("standard", ["sdtm", "adam"])
def test_examples_pass_the_semantic_lint(standard):
    xml = DefineSpecGenerator(
        EXAMPLES / standard / "define.yaml", enrich_methods=True
    ).to_xml_string()
    assert semantic_errors(xml) == []


# ===================================================================== #
# FormalExpression names the method lineage records (#93)                #
# ===================================================================== #


@schemas_present
def test_the_adam_example_define_names_no_sdtm_class():
    xml = DefineSpecGenerator(EXAMPLES / "adam" / "define.yaml", enrich_methods=True)
    expressions = [
        f.text for f in ET.fromstring(xml.to_xml_string()).iter(f"{ODM}FormalExpression")
    ]
    assert expressions
    assert [e for e in expressions if e.startswith("fleet.sdtm.")] == []


@pytest.mark.parametrize(
    ("target", "block"),
    [
        ("USUBJID", {"algorithm": "assign"}),  # runs assign
        ("ASTDT", {"algorithm": "date", "source": "AESTDTC"}),  # the ADaM override of date
        ("ADY", {"algorithm": "duration", "end": "ASTDT", "start": "TRTSDT"}),
    ],
)
def test_formal_expression_names_the_method_lineage_records(target, block):
    raw = fleet.frame(
        pl.from_repr("""\
┌─────────┬────────────┬────────────┬────────────┐
│ USUBJID ┆ AESTDTC    ┆ ASTDT      ┆ TRTSDT     │
│ ---     ┆ ---        ┆ ---        ┆ ---        │
│ str     ┆ str        ┆ date       ┆ date       │
╞═════════╪════════════╪════════════╪════════════╡
│ 01-701  ┆ 2024-01-09 ┆ 2024-01-09 ┆ 2024-01-01 │
└─────────┴────────────┴────────────┴────────────┘
""")
    )
    var = spec_registry.parse_variable_spec("adam", {"target": target, **block})
    recorded = {
        n.name: n.method for n in latest_lineage_of(spec_registry.execute_variable(raw.adam, var))
    }

    params = {k: v for k, v in block.items() if k != "algorithm"}
    expression = spec_registry.render_formal_expression(
        "adam", block["algorithm"], params, target=target
    )

    assert expression.split("(")[0] == recorded[target]


# ===================================================================== #
# Inline route parity (pipeline → to_spec_yaml → define.xml)             #
# ===================================================================== #


@schemas_present
class TestInlineParity:
    def _method_texts(self, root: ET.Element) -> dict[str, str]:
        texts: dict[str, str] = {}
        for m in root.iter(f"{ODM}MethodDef"):
            var = m.get("OID", "").split(".")[-1]
            texts[var] = m.find(f"{ODM}Description/{ODM}TranslatedText").text or ""
        return texts

    def test_inline_and_spec_routes_render_identical_text(self, tmp_path):
        raw = fleet.frame(
            pl.from_repr("""\
┌────────────┬────────────┐
│ subject_id ┆ visit_date │
│ ---        ┆ ---        │
│ str        ┆ str        │
╞════════════╪════════════╡
│ 01-701     ┆ 2024-01-02 │
│ 01-702     ┆ 2024-01-05 │
└────────────┴────────────┘
""")
        )
        ns = (
            raw.sdtm.assign("DOMAIN", value="DM")
            .assign("USUBJID", source="subject_id")
            .date("RFSTDTC", source="visit_date")
        )
        inline_yaml = tmp_path / "inline.yaml"
        ns.to_spec_yaml(dataset="DM", path=inline_yaml)
        inline_root = ET.fromstring(
            DefineSpecGenerator(inline_yaml, enrich_methods=True).to_xml_string()
        )

        hand_spec = {
            "study": {**_STUDY, "id": "STUDY", "name": "STUDY", "protocol_name": "STUDY"},
            "datasets": [
                {
                    "name": "DM",
                    "label": "Demographics",
                    "structure": "One record per subject",
                    "keys": ["USUBJID"],
                    "variables": [
                        {
                            "name": "DOMAIN",
                            "label": "Domain Abbreviation",
                            "type": "text",
                            "derivation": {"algorithm": "assign", "value": "DM"},
                        },
                        {
                            "name": "USUBJID",
                            "label": "Unique Subject Identifier",
                            "type": "text",
                            "derivation": {"algorithm": "assign", "source": "subject_id"},
                        },
                        {
                            "name": "RFSTDTC",
                            "label": "Subject Reference Start Date/Time",
                            "type": "text",
                            "derivation": {"algorithm": "date", "source": "visit_date"},
                        },
                    ],
                }
            ],
        }
        inline_texts = self._method_texts(inline_root)
        hand_texts = self._method_texts(_generate(hand_spec, tmp_path, enrich_methods=True))
        for var in ("DOMAIN", "USUBJID", "RFSTDTC"):
            assert inline_texts[var] == hand_texts[var], f"{var} text diverged between routes"
        assert inline_texts["USUBJID"] == "Direct copy of subject_id."

    def test_stub_variables_warn_at_authoring_time(self):
        raw = fleet.frame(
            pl.from_repr("""\
┌────────────┐
│ subject_id │
│ ---        │
│ str        │
╞════════════╡
│ 01-701     │
└────────────┘
""")
        )
        ns = raw.sdtm.assign("USUBJID", source="subject_id").derivation(
            "SITEID", expression=pl.col("subject_id").str.slice(0, 2)
        )
        with pytest.warns(UserWarning, match="SITEID"):
            ns.to_spec_yaml(dataset="DM")


# ===================================================================== #
# Predecessor population (to_spec_yaml(predecessor=...))                 #
# ===================================================================== #


class TestPredecessorPopulate:
    def _adsl_ns(self):
        dm = fleet.frame(
            pl.from_repr("""\
┌─────────┬─────┬─────────┬─────┬────────────────┐
│ USUBJID ┆ AGE ┆ COUNTRY ┆ ARM ┆ patient_number │
│ ---     ┆ --- ┆ ---     ┆ --- ┆ ---            │
│ str     ┆ i64 ┆ str     ┆ str ┆ str            │
╞═════════╪═════╪═════════╪═════╪════════════════╡
│ 01-701  ┆ 30  ┆ USA     ┆ A   ┆ P1             │
└─────────┴─────┴─────────┴─────┴────────────────┘
""")
        )
        return (
            dm.adam.assign("AGE", source="AGE")
            .assign("TRT01P", source="ARM")
            .assign("SUBJID", source="patient_number")
        )

    def test_carry_throughs_and_source_copies_are_labeled(self):
        spec = yaml.safe_load(self._adsl_ns().to_spec_yaml(dataset="ADSL", predecessor="DM"))
        entries = {v["name"]: v for v in spec["datasets"][0]["variables"]}
        # Metadata-only carry-through and identity copy → Predecessor.
        assert entries["COUNTRY"]["origin"] == "Predecessor"
        assert entries["COUNTRY"]["predecessor"] == "DM.COUNTRY"
        assert entries["AGE"]["predecessor"] == "DM.AGE"
        # The predecessor names the *source* column, not the target.
        assert entries["TRT01P"]["predecessor"] == "DM.ARM"
        # A raw-named source is not a carried CDISC variable.
        assert "predecessor" not in entries["SUBJID"]
        assert "origin" not in entries["SUBJID"]

    @schemas_present
    def test_emitted_spec_generates_a_valid_define(self, tmp_path):
        spec_path = tmp_path / "adsl.yaml"
        self._adsl_ns().to_spec_yaml(dataset="ADSL", predecessor="DM", path=spec_path)
        root = ET.fromstring(DefineSpecGenerator(spec_path).to_xml_string())
        origin = _origin(root, "COUNTRY")
        assert origin.get("Type") == "Predecessor"
        assert _origin_desc(root, "COUNTRY") == "DM.COUNTRY"

    def test_a_merged_column_is_a_stub_not_a_predecessor(self):
        """c1-40: TRTSDT does not exist in DM, so it is no DM.TRTSDT Predecessor."""
        ex = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ TRTSDT     │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ 01-701  ┆ 2024-01-02 │
└─────────┴────────────┘
""")
        ns = self._adsl_ns().merge(ex, on="USUBJID")
        with pytest.warns(UserWarning, match="TRTSDT"):
            text = ns.to_spec_yaml(dataset="ADSL", predecessor="DM")
        entries = {v["name"]: v for v in yaml.safe_load(text)["datasets"][0]["variables"]}

        assert "predecessor" not in entries["TRTSDT"]
        assert "origin" not in entries["TRTSDT"]
        assert entries["TRTSDT"]["derivation"]["callable"] == "TODO_TRTSDT"
        assert "# TODO: column TRTSDT was added by a verb that records no lineage" in text
        assert entries["COUNTRY"]["predecessor"] == "DM.COUNTRY"

    def test_a_new_column_with_no_node_gets_no_predecessor(self):
        """c1-40: first_date and count_events columns were labelled DM.TRTSDT and DM.NUMAE."""
        dm = pl.from_repr("""\
┌─────────┬─────────┬─────┐
│ STUDYID ┆ USUBJID ┆ AGE │
│ ---     ┆ ---     ┆ --- │
│ str     ┆ str     ┆ i64 │
╞═════════╪═════════╪═════╡
│ X       ┆ S1      ┆ 40  │
│ X       ┆ S2      ┆ 50  │
└─────────┴─────────┴─────┘
""")
        ex = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ EXSTDTC    │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ S1      ┆ 2024-01-02 │
└─────────┴────────────┘
""")
        ae = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ S1      │
└─────────┘
""")
        ns = dm.adam.adsl.first_date("TRTSDT", from_dataset=ex, date_col="EXSTDTC").count_events(
            "NUMAE", from_dataset=ae
        )
        with pytest.warns(UserWarning, match="TRTSDT, NUMAE"):
            text = ns.to_spec_yaml(dataset="ADSL", predecessor="DM")
        entries = {v["name"]: v for v in yaml.safe_load(text)["datasets"][0]["variables"]}

        for name in ("TRTSDT", "NUMAE"):
            assert "predecessor" not in entries[name]
            assert entries[name].get("origin") != "Predecessor"
        for name in ("STUDYID", "USUBJID", "AGE"):
            assert entries[name]["predecessor"] == f"DM.{name}"

    def test_sdtm_pipeline_rejects_predecessor(self):
        raw = fleet.frame(
            pl.from_repr("""\
┌────────────┐
│ subject_id │
│ ---        │
│ str        │
╞════════════╡
│ 01-701     │
└────────────┘
""")
        )
        ns = raw.sdtm.assign("USUBJID", source="subject_id")
        with pytest.raises(Exception, match="ADaM pipelines only"):
            ns.to_spec_yaml(dataset="DM", predecessor="DM")

    def test_invalid_predecessor_name_rejected(self):
        with pytest.raises(Exception, match="not a valid"):
            self._adsl_ns().to_spec_yaml(dataset="ADSL", predecessor="dm raw!")


class TestMethodTextShapes:
    """One verb, several reviewer texts: the keys given in the block pick the shape."""

    @pytest.mark.parametrize(
        "doc",
        [
            "Y when baseline BMI >= 18.5 kg/m2 and AGE >= 65.",
            "Derived per SAP v2.1 section 3.4 using the LOCF rule.",
            # formula case: asterisks are multiplication, not reST emphasis
            "Dose per kg = AVAL*1000/WEIGHT*FREQ, rounded to 2 decimals.",
            "BSA = 0.007184*HEIGHT**0.725*WEIGHT**0.425 (DuBois).",
        ],
    )
    def test_a_docstring_method_text_keeps_numbers_and_operators(self, doc):
        """c1-732: the summary cut at 18.5 and the markup strip removed asterisks."""
        from fleet.core.algorithm_resolver import docstring_summary
        from fleet.define_xml.semantic_checks import REST_EMPHASIS
        from fleet.define_xml.spec_generator import _strip_rest_markup

        text = _strip_rest_markup(docstring_summary(doc + "\n\nMore detail. Not in the text."))
        assert text == doc
        assert REST_EMPHASIS.search(text) is None

    def test_rest_markup_is_still_stripped(self):
        from fleet.define_xml.spec_generator import _strip_rest_markup

        assert _strip_rest_markup("Copy of ``AGE`` into *target*.") == "Copy of AGE into target."

    @pytest.mark.parametrize(
        ("params", "text"),
        [
            ({"source": "sex"}, "Direct copy of sex."),
            ({"source": "sex", "ct": "C66731"}, "Value of sex mapped to controlled terminology."),
            ({"value": "DM"}, "Set to 'DM' for all records."),
            (
                {"value": "M", "ct": "C66731"},
                "Set to the controlled terminology value 'M' for all records.",
            ),
            ({}, "Direct copy of SEX."),
        ],
    )
    def test_assign_shapes(self, params, text):
        assert spec_registry.render_method_text("sdtm", "assign", params, target="SEX") == text

    def test_the_variable_codelist_reaches_the_method_text(self, tmp_path):
        """``codelist:`` on the variable is the ``ct`` of its assign (ADR-0008)."""
        spec = {
            "study": {
                "id": "S",
                "name": "S",
                "description": "Shape test",
                "protocol_name": "S",
                "originator": "Fleet",
                "standard": "SDTMIG",
                "standard_version": "3.4",
            },
            "datasets": [
                {
                    "name": "DM",
                    "label": "Demographics",
                    "structure": "One record per subject",
                    "keys": ["SEX"],
                    "variables": [
                        {
                            "name": "SEX",
                            "label": "Sex",
                            "type": "text",
                            "origin": "Derived",
                            "codelist": "C66731",
                            "derivation": {"algorithm": "assign", "source": "sex"},
                        }
                    ],
                }
            ],
            "codelists": [
                {
                    "oid": "C66731",
                    "name": "Sex",
                    "type": "text",
                    "items": [{"coded_value": "M", "decode": "Male"}],
                }
            ],
        }
        root = _generate(spec, tmp_path, enrich_methods=True)
        texts = [e.text for e in root.iter(f"{ODM}TranslatedText")]
        assert "Value of sex mapped to controlled terminology." in texts


@schemas_present
def test_row_steps_become_the_dataset_comment(tmp_path):
    """c1-39 (ADR-0034): a frozen record filter reaches Define-XML as a def:CommentDef."""
    spec = {
        "study": dict(_STUDY),
        "datasets": [
            {
                "name": "DM",
                "label": "Demographics",
                "structure": "One record per subject",
                "keys": ["USUBJID"],
                "row_steps": [
                    {
                        "algorithm": "whereclauses",
                        "where": "ARMCD != 'SCRNFAIL'",
                        "after": "USUBJID",
                    }
                ],
                "variables": [
                    {
                        "name": "USUBJID",
                        "label": "Unique Subject Identifier",
                        "type": "text",
                        "length": 20,
                        "origin": "Collected",
                    }
                ],
            }
        ],
    }
    root = _generate(spec, tmp_path)
    group = next(root.iter(f"{ODM}ItemGroupDef"))
    assert group.get(f"{DEF}CommentOID") == "COM.DM.ROWS"
    comment = next(c for c in root.iter(f"{DEF}CommentDef") if c.get("OID") == "COM.DM.ROWS")
    text = comment.find(f"{ODM}Description/{ODM}TranslatedText").text
    assert text == (
        "Record selection, in derivation order: after USUBJID, keep the records where "
        "ARMCD != 'SCRNFAIL'."
    )
