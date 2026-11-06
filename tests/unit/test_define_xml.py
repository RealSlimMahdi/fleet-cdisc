"""Define-XML generation tests against an in-repo fixture spec.

Parsed-XML structural assertions on ``DefineSpecGenerator`` output:

* Define-XML 2.1 element placement — ``MethodOID`` on ``ItemRef`` (never
  on ``ItemDef``), every referenced OID backed by a ``MethodDef``;
* value-level metadata — ``def:ValueListDef`` / ``def:WhereClauseDef``
  wiring via ``def:ValueListRef`` / ``def:WhereClauseRef`` (the ADVS
  PARAMCD-dependent derivation case);
* ``def:leaf`` hrefs derived from the actual export format
  (spec-level / per-dataset ``output_format:`` and ``output:``);
* ``CodeList`` OIDs and the loud error on undeclared ``CodeListRef``.

No ODM/Define XSD is vendored in the repository, so schema validation is
intentionally out of scope — structural assertions on the parsed tree
stand in (do NOT add a network fetch here).
"""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

import fleet  # noqa: F401
from fleet.core.exceptions import SpecError
from fleet.define_xml import DefineSpecGenerator

ODM = "{http://www.cdisc.org/ns/odm/v1.3}"
DEF = "{http://www.cdisc.org/ns/def/v2.1}"
XLINK = "{http://www.w3.org/1999/xlink}"


FIXTURE_SPEC: dict = {
    "study": {
        "id": "TESTSTUDY",
        "name": "Test Study",
        "description": "Fixture study for Define-XML structural tests",
        "protocol_name": "TESTSTUDY",
        "originator": "Fleet Tests",
        "standard": "ADAMIG",
        "standard_version": "1.1",
        "ct_version": "2023-12-15",
    },
    "output_format": "xpt",
    "codelists": [
        {
            "oid": "CL.PARAMCD",
            "name": "Parameter Code",
            "type": "text",
            "items": [
                {"coded_value": "SYSBP", "decode": "Systolic Blood Pressure"},
                {"coded_value": "DIABP", "decode": "Diastolic Blood Pressure"},
            ],
        },
        {
            "oid": "C66731",
            "name": "Sex",
            "type": "text",
            "items": [
                {"coded_value": "M", "decode": "Male"},
                {"coded_value": "F", "decode": "Female"},
            ],
        },
    ],
    "datasets": [
        {
            "name": "ADVS",
            "label": "Vital Signs Analysis",
            "structure": "One record per subject per parameter per timepoint",
            "keys": ["STUDYID", "USUBJID", "PARAMCD"],
            "output": "exports/advs_custom.parquet",
            "variables": [
                {
                    "name": "STUDYID",
                    "label": "Study Identifier",
                    "type": "text",
                    "mandatory": True,
                    "derivation": {"algorithm": "assign", "value": "TESTSTUDY"},
                },
                {
                    "name": "USUBJID",
                    "label": "Unique Subject Identifier",
                    "type": "text",
                    "mandatory": True,
                    "derivation": {"algorithm": "assign", "source": "USUBJID"},
                },
                {
                    "name": "PARAMCD",
                    "label": "Parameter Code",
                    "type": "text",
                    "codelist": "CL.PARAMCD",
                    "derivation": {"algorithm": "assign", "source": "vstestcd"},
                },
                {
                    "name": "SEX",
                    "label": "Sex",
                    "type": "text",
                    "codelist": "C66731",
                },
                {
                    "name": "AVAL",
                    "label": "Analysis Value",
                    "type": "float",
                },
                {
                    "name": "CUSTOM",
                    "label": "Custom Derived Column",
                    "type": "text",
                    # Importable dotted path — the callable enrichment branch.
                    "derivation": {
                        "algorithm": "derivation",
                        "callable": "fleet.core.lineage.lineage_of",
                    },
                },
            ],
            # The core of a BDS ADaM define: PARAMCD-dependent derivations.
            "value_level": [
                {
                    "param": "SYSBP",
                    "variables": [
                        {
                            "name": "AVAL",
                            "label": "Analysis Value (Systolic BP)",
                            "type": "float",
                            "derivation": {
                                "algorithm": "derivation",
                                "expression": "pl.col('sysbp_raw')",
                            },
                        }
                    ],
                },
                {
                    "where": {"variable": "PARAMCD", "value": ["DIABP", "MAP"]},
                    "variables": [
                        {
                            "name": "AVAL",
                            "label": "Analysis Value (Diastolic BP / MAP)",
                            "type": "float",
                            "derivation": {
                                "algorithm": "derivation",
                                "expression": "pl.col('diabp_raw')",
                            },
                        }
                    ],
                },
            ],
        },
        {
            "name": "ADSL",
            "label": "Subject-Level Analysis",
            "structure": "One record per subject",
            "keys": ["STUDYID", "USUBJID"],
            "output_format": "dataset-json",
            "variables": [
                {
                    "name": "STUDYID",
                    "label": "Study Identifier",
                    "type": "text",
                    "derivation": {"algorithm": "assign", "value": "TESTSTUDY"},
                },
                {
                    "name": "USUBJID",
                    "label": "Unique Subject Identifier",
                    "type": "text",
                    "derivation": {"algorithm": "assign", "source": "USUBJID"},
                },
            ],
        },
    ],
}


@pytest.fixture
def spec_path(tmp_path: Path) -> Path:
    p = tmp_path / "define.yaml"
    p.write_text(yaml.safe_dump(FIXTURE_SPEC, sort_keys=False), encoding="utf-8")
    return p


@pytest.fixture
def root(spec_path: Path) -> ET.Element:
    """Generated + parsed ODM tree (method enrichment on)."""
    gen = DefineSpecGenerator(spec_path, enrich_methods=True)
    return ET.fromstring(gen.to_xml_string())


def _mdv(root: ET.Element) -> ET.Element:
    mdv = root.find(f"{ODM}Study/{ODM}MetaDataVersion")
    assert mdv is not None
    return mdv


class TestDocumentSkeleton:
    def test_odm_root_and_define_version(self, root):
        assert root.tag == f"{ODM}ODM"
        assert root.get(f"{DEF}Context") == "Submission"
        mdv = _mdv(root)
        assert mdv.get(f"{DEF}DefineVersion") == "2.1.0"

    def test_generate_writes_file(self, spec_path, tmp_path):
        out = tmp_path / "define.xml"
        DefineSpecGenerator(spec_path).generate(out, html_preview=False)
        content = out.read_text(encoding="utf-8")
        assert "MetaDataVersion" in content
        # Well-formed XML end to end
        ET.fromstring(content.split("?>", 2)[-1])


class TestMethodPlacement:
    """C15: MethodOID belongs on ItemRef (Define-XML 2.1), not ItemDef."""

    def test_no_itemdef_carries_methodoid(self, root):
        offenders = [e.get("OID") for e in root.iter(f"{ODM}ItemDef") if e.get("MethodOID")]
        assert offenders == []

    def test_derived_itemrefs_carry_methodoid(self, root):
        mdv = _mdv(root)
        advs = next(g for g in mdv.findall(f"{ODM}ItemGroupDef") if g.get("OID") == "IG.ADVS")
        by_item = {r.get("ItemOID"): r for r in advs.findall(f"{ODM}ItemRef")}
        # One MethodDef per derived variable — OID carries the usage site,
        # never the Fleet-internal algorithm id.
        assert by_item["IT.ADVS.STUDYID"].get("MethodOID") == "MT.ADVS.STUDYID"
        assert by_item["IT.ADVS.CUSTOM"].get("MethodOID") == "MT.ADVS.CUSTOM"
        # Variables without a derivation get no MethodOID.
        assert by_item["IT.ADVS.AVAL"].get("MethodOID") is None

    def test_methoddef_names_are_reviewer_facing(self, root):
        for m in root.iter(f"{ODM}MethodDef"):
            assert m.get("Name", "").startswith("Algorithm for ")

    def test_every_methodoid_is_backed_by_a_methoddef(self, root):
        declared = {m.get("OID") for m in root.iter(f"{ODM}MethodDef")}
        referenced = {r.get("MethodOID") for r in root.iter(f"{ODM}ItemRef") if r.get("MethodOID")}
        assert referenced, "fixture should exercise method enrichment"
        assert referenced <= declared

    def test_methoddef_has_description_and_formal_expression(self, root):
        methods = list(root.iter(f"{ODM}MethodDef"))
        assert methods
        for m in methods:
            assert m.get("Type") == "Computation"
            assert m.find(f"{ODM}Description/{ODM}TranslatedText") is not None
            assert m.find(f"{ODM}FormalExpression") is not None

    def test_distinct_expressions_get_distinct_methods(self, root):
        """Two value-level `derivation` entries with different expressions
        must not share one MethodDef."""
        vl = next(v for v in root.iter(f"{DEF}ValueListDef") if v.get("OID") == "VL.ADVS.AVAL")
        oids = [r.get("MethodOID") for r in vl.findall(f"{ODM}ItemRef")]
        assert len(oids) == len(set(oids)) == 2


class TestDocstringXML:
    def test_callable_derivation_uses_wrapped_function_docstring(self, tmp_path, monkeypatch):
        module_path = tmp_path / "tmp_derivations.py"
        module_path.write_text(
            "\n".join(
                [
                    "from __future__ import annotations",
                    "",
                    "import polars as pl",
                    "",
                    "from fleet.core.derivation import derivation",
                    "",
                    "",
                    "@derivation",
                    "def AGE65FL() -> pl.Expr:",
                    '    """Flag subjects aged 65 years or older as \'Y\'',
                    '    and younger subjects as null."""',
                    "    return (",
                    "        pl.when(pl.col('AGE') >= 65)",
                    "        .then(pl.lit('Y'))",
                    "        .otherwise(None)",
                    "        .alias('AGE65FL')",
                    "    )",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.syspath_prepend(str(tmp_path))

        spec = copy.deepcopy(FIXTURE_SPEC)
        spec["datasets"][0]["variables"].append(
            {
                "name": "AGE65FL",
                "label": "Age 65+ Flag",
                "type": "text",
                "derivation": {
                    "algorithm": "derivation",
                    "callable": "tmp_derivations.AGE65FL",
                },
            }
        )
        spec_file = tmp_path / "define.yaml"
        spec_file.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")

        root = ET.fromstring(DefineSpecGenerator(spec_file, enrich_methods=True).to_xml_string())
        methods = {
            method.get("OID"): method
            for method in root.iter(f"{ODM}MethodDef")
            if method.get("OID") is not None
        }
        method = methods["MT.ADVS.AGE65FL"]
        translated = method.find(f"{ODM}Description/{ODM}TranslatedText")
        assert translated is not None
        assert (
            translated.text
            == "Flag subjects aged 65 years or older as 'Y' and younger subjects as null."
        )
        formal = method.find(f"{ODM}FormalExpression")
        assert formal is not None
        assert formal.get("Context") == "Python"
        assert formal.text == "tmp_derivations.AGE65FL"

        expected = (
            "Flag subjects aged 65 years or older as 'Y' and younger subjects as null.",
            "tmp_derivations.AGE65FL",
        )
        assert DefineSpecGenerator._resolve_callable("AGE65FL") == expected
        assert DefineSpecGenerator._resolve_callable("tmp_derivations.AGE65FL") == expected

    def test_short_name_callable_needs_derivations_module_import(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """generate() imports the spec's ``derivations_module`` first.

        Regression guard. A ``callable:`` referenced by its *short* registry
        name (``POP_FLAG``, not a dotted path) only resolves if the spec's
        ``derivations_module`` has been imported so the ``@derivation``
        registration has run. ``from_spec()`` did this; the Define-XML
        generator did not, so the study's own MethodDef was silently dropped.

        The module is written to a fresh, never-imported name and the short
        name is asserted *unregistered* up front, so this fails (no
        MT.ADSL.POPFL MethodDef) unless ``generate()`` performs the import.
        """
        import sys
        import textwrap

        from fleet.adam.transforms import _TRANSFORMS

        modname = "regr_derivations_module_probe"
        (tmp_path / f"{modname}.py").write_text(
            textwrap.dedent(
                '''
                import polars as pl

                from fleet.core.derivation import derivation


                @derivation
                def POP_FLAG() -> pl.Expr:
                    """Flag subjects in the safety population as 'Y'."""
                    return pl.lit("Y").alias("POP_FLAG")
                '''
            ),
            encoding="utf-8",
        )
        # Preconditions that make the assertion meaningful: neither the module
        # nor the short registry name exists before the generator runs.
        assert modname not in sys.modules
        assert "POP_FLAG" not in _TRANSFORMS
        monkeypatch.syspath_prepend(str(tmp_path))

        spec = copy.deepcopy(FIXTURE_SPEC)
        spec["derivations_module"] = modname
        # Append to ADSL (datasets[1]); reference by SHORT name, not dotted path.
        spec["datasets"][1]["variables"].append(
            {
                "name": "POPFL",
                "label": "Population Flag",
                "type": "text",
                "derivation": {"algorithm": "derivation", "callable": "POP_FLAG"},
            }
        )
        spec_file = tmp_path / "define.yaml"
        spec_file.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")

        out = tmp_path / "define.xml"
        DefineSpecGenerator(str(spec_file), enrich_methods=True).generate(
            str(out), html_preview=False
        )
        root = ET.fromstring(out.read_text(encoding="utf-8"))
        methods = {
            method.get("OID"): method
            for method in root.iter(f"{ODM}MethodDef")
            if method.get("OID") is not None
        }
        assert "MT.ADSL.POPFL" in methods, (
            "generate() did not import derivations_module: the short-name "
            "callable POP_FLAG never registered, so its MethodDef was dropped."
        )
        translated = methods["MT.ADSL.POPFL"].find(f"{ODM}Description/{ODM}TranslatedText")
        assert translated is not None
        assert translated.text == "Flag subjects in the safety population as 'Y'."


class TestValueLevelMetadata:
    """Item 10: ValueListDef + WhereClauseDef wiring (BDS ADaM core)."""

    def test_valuelistdef_present_with_itemrefs(self, root):
        vls = {v.get("OID"): v for v in root.iter(f"{DEF}ValueListDef")}
        assert set(vls) == {"VL.ADVS.AVAL"}
        refs = vls["VL.ADVS.AVAL"].findall(f"{ODM}ItemRef")
        assert [r.get("ItemOID") for r in refs] == [
            "IT.ADVS.AVAL.SYSBP",
            "IT.ADVS.AVAL.DIABP_MAP",
        ]
        assert [r.get("OrderNumber") for r in refs] == ["1", "2"]

    def test_whereclause_wiring(self, root):
        wcs = {w.get("OID"): w for w in root.iter(f"{DEF}WhereClauseDef")}
        assert set(wcs) == {"WC.ADVS.PARAMCD.SYSBP", "WC.ADVS.PARAMCD.DIABP_MAP"}

        eq = wcs["WC.ADVS.PARAMCD.SYSBP"].find(f"{ODM}RangeCheck")
        assert eq.get("Comparator") == "EQ"
        assert eq.get(f"{DEF}ItemOID") == "IT.ADVS.PARAMCD"
        assert [c.text for c in eq.findall(f"{ODM}CheckValue")] == ["SYSBP"]

        isin = wcs["WC.ADVS.PARAMCD.DIABP_MAP"].find(f"{ODM}RangeCheck")
        assert isin.get("Comparator") == "IN"
        assert [c.text for c in isin.findall(f"{ODM}CheckValue")] == ["DIABP", "MAP"]

        # Every ItemRef inside the ValueListDef points at a declared WhereClauseDef.
        vl = next(v for v in root.iter(f"{DEF}ValueListDef"))
        for ref in vl.findall(f"{ODM}ItemRef"):
            wc_ref = ref.find(f"{DEF}WhereClauseRef")
            assert wc_ref is not None
            assert wc_ref.get("WhereClauseOID") in wcs

    def test_parent_itemdef_gets_valuelistref(self, root):
        aval = next(i for i in root.iter(f"{ODM}ItemDef") if i.get("OID") == "IT.ADVS.AVAL")
        ref = aval.find(f"{DEF}ValueListRef")
        assert ref is not None
        assert ref.get("ValueListOID") == "VL.ADVS.AVAL"

    def test_value_level_itemdefs_exist(self, root):
        oids = {i.get("OID") for i in root.iter(f"{ODM}ItemDef")}
        assert {"IT.ADVS.AVAL.SYSBP", "IT.ADVS.AVAL.DIABP_MAP"} <= oids

    def test_value_level_defs_precede_itemgroupdefs(self, root):
        """Define-XML 2.1 orders ValueListDef/WhereClauseDef before ItemGroupDef."""
        tags = [child.tag for child in _mdv(root)]
        assert tags.index(f"{DEF}ValueListDef") < tags.index(f"{ODM}ItemGroupDef")
        assert tags.index(f"{DEF}WhereClauseDef") < tags.index(f"{ODM}ItemGroupDef")


class TestLeafHrefs:
    """Item 9 / C15: hrefs follow the actual export format, not .xpt."""

    def test_explicit_output_used_verbatim(self, root):
        leaves = {e.get("ID"): e.get(f"{XLINK}href") for e in root.iter(f"{DEF}leaf")}
        assert leaves["LF.ADVS"] == "exports/advs_custom.parquet"

    def test_per_dataset_output_format_override(self, root):
        leaves = {e.get("ID"): e.get(f"{XLINK}href") for e in root.iter(f"{DEF}leaf")}
        assert leaves["LF.ADSL"] == "adsl.json"

    def test_default_is_parquet(self, tmp_path):
        spec = {**FIXTURE_SPEC}
        spec.pop("output_format")
        spec = yaml.safe_load(yaml.safe_dump(spec))  # deep copy
        spec["datasets"][0].pop("output")
        spec["datasets"][1].pop("output_format")
        p = tmp_path / "define.yaml"
        p.write_text(yaml.safe_dump(spec, sort_keys=False))
        root = ET.fromstring(DefineSpecGenerator(p).to_xml_string())
        leaves = {e.get("ID"): e.get(f"{XLINK}href") for e in root.iter(f"{DEF}leaf")}
        assert leaves["LF.ADVS"] == "advs.parquet"
        assert leaves["LF.ADSL"] == "adsl.parquet"

    def test_itemgroup_archive_location_matches_leaf(self, root):
        mdv = _mdv(root)
        for group in mdv.findall(f"{ODM}ItemGroupDef"):
            leaf = group.find(f"{DEF}leaf")
            assert leaf is not None
            assert group.get(f"{DEF}ArchiveLocationID") == leaf.get("ID")


class TestCodeLists:
    def test_declared_codelists_rendered_with_items(self, root):
        codelists = {c.get("OID"): c for c in root.iter(f"{ODM}CodeList")}
        assert set(codelists) == {"CL.PARAMCD", "C66731"}
        items = codelists["CL.PARAMCD"].findall(f"{ODM}CodeListItem")
        assert {i.get("CodedValue") for i in items} == {"SYSBP", "DIABP"}

    def test_every_codelistref_resolves(self, root):
        declared = {c.get("OID") for c in root.iter(f"{ODM}CodeList")}
        referenced = {r.get("CodeListOID") for r in root.iter(f"{ODM}CodeListRef")}
        assert referenced
        assert referenced <= declared

    def test_undeclared_codelistref_raises_listing_declared_oids(self, tmp_path):
        """Item 11: dangling CodeListRef is a loud generation error."""
        spec = yaml.safe_load(yaml.safe_dump(FIXTURE_SPEC))
        spec["datasets"][0]["variables"][3]["codelist"] = "C99999"
        p = tmp_path / "define.yaml"
        p.write_text(yaml.safe_dump(spec, sort_keys=False))
        with pytest.raises(SpecError) as excinfo:
            DefineSpecGenerator(p).to_xml_string()
        message = str(excinfo.value)
        assert "C99999" in message
        assert "ADVS.SEX" in message
        assert "CL.PARAMCD" in message and "C66731" in message  # declared OIDs listed


class TestItemRefRole:
    """c1-268 (ADR 0042): the SDTM role of a variable is the ItemRef Role (CORE CG0010)."""

    def test_sdtm_role_becomes_the_itemref_role_and_the_file_validates(self, tmp_path):
        spec = yaml.safe_load(yaml.safe_dump(FIXTURE_SPEC))
        spec["datasets"][0]["variables"][0]["sdtm_role"] = "Identifier"
        p = tmp_path / "define.yaml"
        p.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
        out = tmp_path / "define.xml"

        DefineSpecGenerator(p).generate(out, html_preview=False)

        root = ET.fromstring(out.read_text(encoding="utf-8"))
        name = spec["datasets"][0]["variables"][0]["name"]
        refs = {
            r.get("ItemOID"): r
            for g in root.iter(f"{ODM}ItemGroupDef")
            if g.get("Name") == spec["datasets"][0]["name"]
            for r in g.iter(f"{ODM}ItemRef")
        }
        roles = {oid: r.get("Role") for oid, r in refs.items()}
        assert [oid for oid, role in roles.items() if role] == [next(iter(refs))]
        assert roles[next(iter(refs))] == "Identifier"
        assert name in next(iter(refs))

    def test_a_variable_without_sdtm_role_has_no_role(self, root):
        assert all(r.get("Role") is None for r in root.iter(f"{ODM}ItemRef"))

    def test_fleet_init_define_fills_the_role_from_the_library(self):
        from fleet.core.scaffolder import parse_ig_variable

        var = {"name": "STUDYID", "label": "Study Identifier", "core": "Req", "role": "Identifier"}

        assert parse_ig_variable(var)["sdtm_role"] == "Identifier"
        assert "sdtm_role" not in parse_ig_variable({"name": "AVAL", "core": "Cond"})
