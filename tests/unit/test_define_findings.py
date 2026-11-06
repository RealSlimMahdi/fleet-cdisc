"""Regression tests for the Define-XML findings of the alpha audit (package define).

Each test names its finding: per-dataset ItemDefs (c1-558), CodeList forms
(c1-559), Repeating and IsReferenceData defaults (c1-561), SDTMIG 3.4
qualifiers (c1-562), aCRF page references (c1-563), the study code import
(c1-565), the CT version check (c1-766), dangling references (c1-778), the
study-day method text (c1-482), the treatment-emergent spec verb (c1-488) and
the pilot methods (c1-680).
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import polars as pl
import pytest
import yaml

import fleet
from fleet import cli
from fleet.core import spec_registry
from fleet.core.exceptions import SpecError
from fleet.core.lineage import latest_lineage_of
from fleet.core.study_context import load_study_context
from fleet.ct.study_codelists import check_codelists, ct_version_problems
from fleet.define_xml import DefineSpecGenerator, semantic_errors

ODM = "{http://www.cdisc.org/ns/odm/v1.3}"
DEF = "{http://www.cdisc.org/ns/def/v2.1}"

PILOT = Path(__file__).parent.parent.parent / "examples" / "cdiscpilot01"


def _study(**extra) -> dict:
    return {
        "id": "S01",
        "name": "S01",
        "description": "Define findings test study",
        "protocol_name": "S01",
        "originator": "Fleet Tests",
        "standard": "ADAMIG",
        "standard_version": "1.1",
        "ct_version": "2023-12-15",
        **extra,
    }


def _var(name: str, **extra) -> dict:
    return {"name": name, "label": name, "type": "text", "length": 8, **extra}


def _dataset(name: str, variables: list[dict], **extra) -> dict:
    return {
        "name": name,
        "label": name,
        "structure": "One record per subject",
        "keys": [variables[0]["name"]],
        "variables": variables,
        **extra,
    }


def _write(tmp_path: Path, datasets: list[dict], **top) -> Path:
    spec = {"study": top.pop("study", _study()), "datasets": datasets, **top}
    path = tmp_path / "define.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return path


def _root(path: Path, **kwargs) -> ET.Element:
    return ET.fromstring(DefineSpecGenerator(path, **kwargs).to_xml_string())


def _by_oid(root: ET.Element, tag: str) -> dict[str, ET.Element]:
    return {e.get("OID"): e for e in root.iter(tag)}


# --------------------------------------------------------------------- #
# c1-558: each dataset variable has its own ItemDef                       #
# --------------------------------------------------------------------- #


def test_c1_558_each_dataset_keeps_its_own_itemdef(tmp_path):
    path = _write(
        tmp_path,
        [
            _dataset(
                "ADSL",
                [
                    _var("USUBJID", origin="Predecessor", predecessor="DM.USUBJID"),
                    _var(
                        "AGE", type="integer", length=3, origin="Predecessor", predecessor="DM.AGE"
                    ),
                ],
            ),
            _dataset(
                "ADAE",
                [
                    _var("USUBJID", origin="Predecessor", predecessor="AE.USUBJID"),
                    _var("AGE", origin="Derived", comment="Age at the event, in years."),
                ],
            ),
        ],
    )
    items = _by_oid(_root(path), f"{ODM}ItemDef")

    assert items["IT.ADSL.AGE"].get("DataType") == "integer"
    assert items["IT.ADAE.AGE"].get("DataType") == "text"
    assert items["IT.ADSL.AGE"].find(f"{DEF}Origin").get("Type") == "Predecessor"
    assert items["IT.ADAE.AGE"].find(f"{DEF}Origin").get("Type") == "Derived"
    assert "IT.AGE" not in items


# --------------------------------------------------------------------- #
# c1-559: CodeListItem, EnumeratedItem, ExternalCodeList, Alias           #
# --------------------------------------------------------------------- #


def _codelist_root(tmp_path, codelist: dict, var_type: str = "text") -> ET.Element:
    path = _write(
        tmp_path,
        [_dataset("ADSL", [_var("USUBJID", origin="Assigned"), _var("X", type=var_type)])],
        codelists=[codelist],
    )
    spec = yaml.safe_load(path.read_text())
    spec["datasets"][0]["variables"][1].update(codelist=codelist["oid"], origin="Assigned")
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return _root(path)


def test_c1_559_terms_with_no_decode_give_enumerated_items(tmp_path):
    root = _codelist_root(
        tmp_path,
        {"oid": "CL.UNIT", "name": "Unit", "type": "text", "items": [{"coded_value": "mg"}]},
    )
    codelist = _by_oid(root, f"{ODM}CodeList")["CL.UNIT"]
    assert [e.get("CodedValue") for e in codelist.iter(f"{ODM}EnumeratedItem")] == ["mg"]
    assert list(codelist.iter(f"{ODM}CodeListItem")) == []


def test_c1_559_a_mix_of_decoded_and_bare_terms_names_the_list_and_term(tmp_path):
    codelist = {
        "oid": "CL.UNIT",
        "name": "Unit",
        "type": "text",
        "items": [{"coded_value": "mg", "decode": "Milligram"}, {"coded_value": "kg"}],
    }
    with pytest.raises(SpecError, match=r"codelist CL\.UNIT mixes .*'kg' has none"):
        _codelist_root(tmp_path, codelist)


def test_c1_559_a_cdisc_list_carries_its_standard_alias_and_extended_term(tmp_path):
    root = _codelist_root(
        tmp_path,
        {
            "oid": "C66731",
            "name": "Sex",
            "type": "text",
            "nci_code": "C66731",
            "items": [
                {"coded_value": "F", "decode": "Female", "nci_code": "C16576"},
                {"coded_value": "X", "decode": "X", "extended": True},
            ],
        },
    )
    codelist = _by_oid(root, f"{ODM}CodeList")["C66731"]
    assert codelist.get(f"{DEF}StandardOID") == "STD.CT"
    assert codelist.find(f"{ODM}Alias").get("Name") == "C66731"
    female, extra = codelist.findall(f"{ODM}CodeListItem")
    assert female.find(f"{ODM}Alias").attrib == {"Context": "nci:ExtCodeID", "Name": "C16576"}
    assert extra.get(f"{DEF}ExtendedValue") == "Yes"


def test_c1_559_an_external_dictionary_gives_external_codelist(tmp_path):
    root = _codelist_root(
        tmp_path,
        {
            "oid": "CL.AEDICT",
            "name": "MedDRA",
            "type": "text",
            "external": {"dictionary": "MedDRA", "version": "26.0"},
        },
    )
    external = _by_oid(root, f"{ODM}CodeList")["CL.AEDICT"].find(f"{ODM}ExternalCodeList")
    assert external.attrib == {"Dictionary": "MedDRA", "Version": "26.0"}


def test_c1_559_a_standard_oid_that_is_not_declared_raises(tmp_path):
    codelist = {
        "oid": "C66731",
        "name": "Sex",
        "type": "text",
        "standard_oid": "STD.CT.ADAM",
        "items": [{"coded_value": "F", "decode": "Female"}],
    }
    with pytest.raises(SpecError, match=r"standard_oid names no declared standard"):
        _codelist_root(tmp_path, codelist)


# --------------------------------------------------------------------- #
# c1-561: Repeating and IsReferenceData defaults                          #
# --------------------------------------------------------------------- #


def test_c1_561_trial_design_dm_and_adsl_defaults(tmp_path):
    path = _write(
        tmp_path,
        [
            _dataset("TS", [_var("TSPARMCD", origin="Assigned")]),
            _dataset("XX", [_var("XXVAR", origin="Assigned")], **{"class": "TRIAL DESIGN"}),
            _dataset("DM", [_var("USUBJID", origin="Assigned")]),
            _dataset("ADSL", [_var("USUBJID", origin="Assigned")]),
            _dataset("AE", [_var("USUBJID", origin="Assigned")]),
            _dataset("TA", [_var("ARMCD", origin="Assigned")], repeating=True),
            _dataset("ZZ", [_var("ZZVAR", origin="Assigned")], is_reference_data=True),
        ],
        study=_study(standard="SDTMIG", standard_version="3.4"),
    )
    groups = {
        g.get("Name"): (g.get("Repeating"), g.get("IsReferenceData"))
        for g in _root(path).iter(f"{ODM}ItemGroupDef")
    }
    assert groups == {
        "TS": ("No", "Yes"),
        "XX": ("Yes", "Yes"),
        "DM": ("No", "No"),
        "ADSL": ("No", "No"),
        "AE": ("Yes", "No"),
        "TA": ("Yes", "Yes"),
        "ZZ": ("Yes", "Yes"),
    }


# --------------------------------------------------------------------- #
# c1-562: SDTMIG 3.4 qualifiers go to SUPP--                              #
# --------------------------------------------------------------------- #


def _ae_with_qualifier(tmp_path, version: str, *, seq: bool = True) -> Path:
    return _write(
        tmp_path,
        [
            _dataset(
                "AE",
                [
                    _var("STUDYID", origin="Assigned"),
                    _var("USUBJID", origin="Assigned"),
                    *([_var("AESEQ", type="integer", origin="Assigned")] if seq else []),
                    _var(
                        "AETRTEM",
                        label="Treatment Emergent Flag",
                        length=1,
                        role="qualifier",
                        evaluator="INVESTIGATOR",
                        origin="Assigned",
                    ),
                ],
            )
        ],
        study=_study(standard="SDTMIG", standard_version=version),
    )


def test_c1_562_a_qualifier_that_cannot_move_to_supp_is_refused_for_ig_3_4(tmp_path):
    with pytest.raises(SpecError, match=r"cannot move.*SUPPAE: AE\.AESEQ \(the IDVAR\)"):
        DefineSpecGenerator(_ae_with_qualifier(tmp_path, "3.4", seq=False)).to_xml_string()


def test_c1_105_a_parent_qualifier_is_described_in_a_generated_supp_dataset(tmp_path):
    root = _root(_ae_with_qualifier(tmp_path, "3.4"))
    groups = _by_oid(root, f"{ODM}ItemGroupDef")
    ae_refs = [r.get("ItemOID") for r in groups["IG.AE"].iter(f"{ODM}ItemRef")]
    supp = groups["IG.SUPPAE"]
    supp_refs = {r.get("ItemOID"): r.get("KeySequence") for r in supp.iter(f"{ODM}ItemRef")}
    items = _by_oid(root, f"{ODM}ItemDef")
    where = _by_oid(root, f"{DEF}WhereClauseDef")["WC.SUPPAE.QNAM.AETRTEM"]
    value_list = _by_oid(root, f"{DEF}ValueListDef")["VL.SUPPAE.QVAL"]

    assert ae_refs == ["IT.AE.STUDYID", "IT.AE.USUBJID", "IT.AE.AESEQ"]
    assert (supp.get("Domain"), supp.find(f"{DEF}Class").get("Name")) == ("AE", "RELATIONSHIP")
    assert supp_refs == {
        "IT.SUPPAE.STUDYID": "1",
        "IT.SUPPAE.RDOMAIN": "2",
        "IT.SUPPAE.USUBJID": "3",
        "IT.SUPPAE.IDVAR": "4",
        "IT.SUPPAE.IDVARVAL": "5",
        "IT.SUPPAE.QNAM": "6",
        "IT.SUPPAE.QLABEL": None,
        "IT.SUPPAE.QVAL": None,
        "IT.SUPPAE.QORIG": None,
        "IT.SUPPAE.QEVAL": None,
    }
    assert where.find(f"{ODM}RangeCheck").get(f"{DEF}ItemOID") == "IT.SUPPAE.QNAM"
    assert [c.text for c in where.iter(f"{ODM}CheckValue")] == ["AETRTEM"]
    assert value_list.find(f"{ODM}ItemRef").get("ItemOID") == "IT.SUPPAE.QVAL.AETRTEM"
    qval = items["IT.SUPPAE.QVAL.AETRTEM"]
    assert qval.find(f"{ODM}Description/{ODM}TranslatedText").text == "Treatment Emergent Flag"
    assert qval.find(f"{DEF}Origin").get("Type") == "Assigned"
    assert "IT.AE.AETRTEM" not in items


def test_c1_105_dm_qualifiers_have_no_idvar(tmp_path):
    path = _write(
        tmp_path,
        [
            _dataset(
                "DM",
                [
                    _var("STUDYID", origin="Assigned"),
                    _var("USUBJID", origin="Assigned"),
                    _var("COMPLT16", label="Completers of Week 16", length=1, role="qualifier"),
                ],
            )
        ],
        study=_study(standard="SDTMIG", standard_version="3.4"),
    )
    idvar = _by_oid(_root(path), f"{ODM}ItemDef")["IT.SUPPDM.IDVAR"]
    text = idvar.find(f"{DEF}Origin/{ODM}Description/{ODM}TranslatedText").text
    assert text == "Null: the qualifier applies to the subject."


def test_c1_105_a_declared_supp_and_a_parent_qualifier_together_are_refused(tmp_path):
    path = _ae_with_qualifier(tmp_path, "3.4")
    spec = yaml.safe_load(path.read_text())
    spec["datasets"].append(_dataset("SUPPAE", [_var("USUBJID", origin="Assigned")]))
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    with pytest.raises(SpecError, match=r"SUPPAE: the spec also declares it"):
        DefineSpecGenerator(path).to_xml_string()


def test_c1_105_one_define_serves_run_define_xml_and_check(tmp_path):
    path = _ae_with_qualifier(tmp_path, "3.4")
    ae = pl.from_repr("""
┌─────────┬─────────┬───────┬─────────┐
│ STUDYID ┆ USUBJID ┆ AESEQ ┆ AETRTEM │
│ ---     ┆ ---     ┆ ---   ┆ ---     │
│ str     ┆ str     ┆ i64   ┆ str     │
╞═════════╪═════════╪═══════╪═════════╡
│ S01     ┆ S01-1   ┆ 1     ┆ Y       │
└─────────┴─────────┴───────┴─────────┘
""")
    # What fleet run writes from the same define.
    suppae = ae.sdtm.export_supp(spec=path, dataset="AE", idvar="AESEQ", domain="AE")
    gen = DefineSpecGenerator(path, strict=True, import_study_code=False)  # as fleet check
    items = _by_oid(ET.fromstring(gen.to_xml_string()), f"{ODM}ItemDef")

    assert suppae.select("IDVAR", "QNAM", "QLABEL").row(0) == (
        items["IT.SUPPAE.IDVAR"].find(f"{DEF}Origin/{ODM}Description/{ODM}TranslatedText").text,
        "AETRTEM",
        items["IT.SUPPAE.QVAL.AETRTEM"].find(f"{ODM}Description/{ODM}TranslatedText").text,
    )
    assert gen.leaf_hrefs()["SUPPAE"] == "suppae.parquet"


def test_c1_562_a_supp_dataset_describes_its_parent_domain(tmp_path):
    path = _write(
        tmp_path,
        [_dataset("SUPPAE", [_var("USUBJID", origin="Assigned")])],
        study=_study(standard="SDTMIG", standard_version="3.4"),
    )
    group = next(_root(path).iter(f"{ODM}ItemGroupDef"))
    assert (group.get("Name"), group.get("Domain")) == ("SUPPAE", "AE")


# --------------------------------------------------------------------- #
# c1-563: aCRF page references reach the define or Fleet says why        #
# --------------------------------------------------------------------- #


def _pages(root: ET.Element, item_oid: str) -> str | None:
    ref = _by_oid(root, f"{ODM}ItemDef")[item_oid].find(f"{DEF}Origin/{DEF}DocumentRef")
    page = ref.find(f"{DEF}PDFPageRef") if ref is not None else None
    return page.get("PageRefs") if page is not None else None


def test_c1_563_an_integer_page_in_the_page_map_is_kept(tmp_path):
    (tmp_path / "pm.yaml").write_text("DM.SEX: 7\n", encoding="utf-8")
    path = _write(
        tmp_path,
        [_dataset("DM", [_var("USUBJID", origin="Assigned"), _var("SEX", origin="Collected")])],
        study=_study(documents={"annotated_crf": {"href": "acrf.pdf", "page_map": "pm.yaml"}}),
    )
    assert _pages(_root(path), "IT.DM.SEX") == "7"


def test_c1_563_page_map_keys_that_match_no_variable_warn(tmp_path):
    (tmp_path / "pm.yaml").write_text("DM.SEX: '7'\nDM.SEXX: '9'\n", encoding="utf-8")
    path = _write(
        tmp_path,
        [_dataset("DM", [_var("USUBJID", origin="Assigned"), _var("SEX", origin="Collected")])],
        study=_study(documents={"annotated_crf": {"href": "acrf.pdf", "page_map": "pm.yaml"}}),
    )
    with pytest.warns(UserWarning, match=r"1 page map key\(s\) match no variable.*DM\.SEXX"):
        DefineSpecGenerator(path)


def test_c1_563_value_level_pages_are_read_under_the_where_key(tmp_path):
    path = _write(
        tmp_path,
        [
            _dataset(
                "LB",
                [_var("LBTESTCD", origin="Collected"), _var("LBORRES", origin="Collected")],
                value_level=[
                    {
                        "where": {"variable": "LBTESTCD", "value": "ALB"},
                        "variables": [_var("LBORRES", origin="Collected", crf_pages="12")],
                    }
                ],
            )
        ],
        study=_study(documents={"annotated_crf": {"href": "acrf.pdf"}}),
    )
    assert _pages(_root(path), "IT.LB.LBORRES.ALB") == "12"


# --------------------------------------------------------------------- #
# c1-565: study code is imported only to write methods                    #
# --------------------------------------------------------------------- #


@pytest.fixture
def marker_study(tmp_path, monkeypatch):
    """A define whose derivations_module writes a marker file on import."""
    marker = tmp_path / "imported.txt"
    (tmp_path / "audit_marker_mod.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('x')\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "audit_marker_mod", raising=False)
    path = _write(
        tmp_path,
        [_dataset("ADSL", [_var("USUBJID", origin="Assigned")])],
        derivations_module="audit_marker_mod",
    )
    return path, marker


def test_c1_565_no_import_when_methods_are_off(marker_study):
    path, marker = marker_study
    DefineSpecGenerator(path, enrich_methods=False).to_xml_string()
    assert not marker.exists()


def test_c1_565_no_import_for_a_read_only_check(marker_study):
    path, marker = marker_study
    DefineSpecGenerator(path, strict=True, import_study_code=False).to_xml_string()
    assert not marker.exists()


def test_c1_565_a_missing_module_does_not_stop_a_build_without_methods(tmp_path):
    path = _write(
        tmp_path,
        [_dataset("ADSL", [_var("USUBJID", origin="Assigned")])],
        derivations_module="no_such_module_c1_565",
    )
    assert DefineSpecGenerator(path, enrich_methods=False).to_xml_string()


def test_c1_565_a_callable_has_method_text_without_the_import(tmp_path):
    path = _write(
        tmp_path,
        [
            _dataset(
                "ADSL",
                [
                    _var("USUBJID", origin="Assigned"),
                    _var("X", origin="Derived", derivation={"callable": "study.derive.x"}),
                ],
            )
        ],
    )
    methods = _by_oid(_root(path, strict=True, import_study_code=False), f"{ODM}MethodDef")
    assert methods["MT.ADSL.X"].find(f"{ODM}FormalExpression").text == "study.derive.x"


# --------------------------------------------------------------------- #
# c1-766: fleet check compares define.yaml CT versions with the pins      #
# --------------------------------------------------------------------- #


def test_c1_766_a_define_that_keeps_the_old_ct_date_is_reported(tmp_path):
    (tmp_path / "study_config.yaml").write_text(
        "study_id: S01\nct:\n  package: sdtmct-2024-09-27\n", encoding="utf-8"
    )
    define = tmp_path / "metadata" / "sdtm" / "define.yaml"
    define.parent.mkdir(parents=True)
    define.write_text(
        yaml.safe_dump({"study": _study(standard="SDTMIG", standard_version="3.4")}),
        encoding="utf-8",
    )
    ctx = load_study_context(tmp_path / "study_config.yaml")

    problems = ct_version_problems(ctx)

    assert problems == [
        f"{define} states CT 2023-12-15, but study_config.yaml pins sdtmct-2024-09-27. "
        f"Edit study.ct_version in {define}."
    ]
    assert problems[0] in check_codelists(ctx, references=True)
    assert check_codelists(ctx) == []


# --------------------------------------------------------------------- #
# c1-778: every reference resolves, or SpecError names DATASET.VARIABLE   #
# --------------------------------------------------------------------- #


def test_c1_778_a_crf_document_that_is_not_declared_raises(tmp_path):
    path = _write(
        tmp_path,
        [
            _dataset(
                "DM",
                [
                    _var("USUBJID", origin="Assigned"),
                    _var("SEX", origin="Collected", crf_pages={"doc": "other.pdf", "pages": "3"}),
                ],
            )
        ],
        study=_study(documents={"annotated_crf": {"href": "acrf.pdf"}}),
    )
    with pytest.raises(SpecError, match=r"DM\.SEX crf_pages doc other\.pdf matches no"):
        DefineSpecGenerator(path).to_xml_string()


def test_c1_778_a_supplemental_document_is_a_valid_crf_target(tmp_path):
    path = _write(
        tmp_path,
        [
            _dataset(
                "DM",
                [
                    _var("USUBJID", origin="Assigned"),
                    _var("SEX", origin="Collected", crf_pages={"doc": "other.pdf", "pages": "3"}),
                ],
            )
        ],
        study=_study(
            documents={
                "supplemental_docs": [{"id": "LF.Other", "href": "other.pdf", "title": "Other"}]
            }
        ),
    )
    ref = _by_oid(_root(path), f"{ODM}ItemDef")["IT.DM.SEX"].find(f"{DEF}Origin/{DEF}DocumentRef")
    assert ref.get("leafID") == "LF.Other"


def test_c1_778_keys_and_where_variables_must_be_declared(tmp_path):
    path = _write(
        tmp_path,
        [
            _dataset(
                "LB",
                [_var("USUBJID", origin="Assigned"), _var("LBSTRESC", origin="Collected")],
                keys=["USUBJID", "LBFOO"],
                value_level=[
                    {
                        "where": {"variable": "LBTEST", "value": "ALB"},
                        "variables": [_var("LBSTRESC", origin="Collected")],
                    }
                ],
            )
        ],
    )
    with pytest.raises(SpecError, match=r"LB\.LBFOO \(keys\); LB\.LBTEST \(value_level where\)"):
        DefineSpecGenerator(path).to_xml_string()


def _doc(body: str) -> str:
    return (
        '<ODM xmlns="http://www.cdisc.org/ns/odm/v1.3" '
        'xmlns:def="http://www.cdisc.org/ns/def/v2.1">'
        f'<Study OID="S"><MetaDataVersion OID="M" Name="m">{body}'
        "</MetaDataVersion></Study></ODM>"
    )


def test_c1_778_the_lint_names_dangling_references_and_unused_value_lists():
    xml = _doc(
        '<def:ValueListDef OID="VL.LB.X"/>'
        '<ItemGroupDef OID="IG.LB" Name="LB"><ItemRef ItemOID="IT.LB.GONE"/></ItemGroupDef>'
    )
    assert semantic_errors(xml) == [
        "ItemOID IT.LB.GONE refers to an element that does not exist",
        "ValueListDef VL.LB.X is not referenced by any ItemDef",
    ]


def test_c1_778_the_lint_names_long_value_level_items_and_codelist_types():
    xml = _doc(
        '<def:ValueListDef OID="VL.LB.X"><ItemRef ItemOID="IT.LB.X.A"/></def:ValueListDef>'
        '<ItemDef OID="IT.LB.X" Name="X" DataType="text" Length="8">'
        '<CodeListRef CodeListOID="CL.X"/><def:ValueListRef ValueListOID="VL.LB.X"/></ItemDef>'
        '<ItemDef OID="IT.LB.X.A" Name="X" DataType="text" Length="200"/>'
        '<CodeList OID="CL.X" Name="X" DataType="integer"/>'
    )
    assert semantic_errors(xml) == [
        "ItemDef IT.LB.X.A has Length 200, more than the Length 8 of its parent IT.LB.X",
        "ItemDef IT.LB.X has DataType text but its CodeList CL.X has DataType integer",
    ]


# --------------------------------------------------------------------- #
# c1-482: a study day reads as a study day                                #
# --------------------------------------------------------------------- #


def test_c1_482_a_dy_target_gets_the_study_day_sentence(tmp_path):
    path = _write(
        tmp_path,
        [
            _dataset(
                "ADAE",
                [
                    _var("USUBJID", origin="Assigned"),
                    _var(
                        "ADY",
                        type="integer",
                        length=3,
                        origin="Derived",
                        derivation={"algorithm": "duration", "start": "TRTSDT", "end": "ASTDT"},
                    ),
                    _var(
                        "ADURN",
                        type="integer",
                        length=3,
                        origin="Derived",
                        derivation={"algorithm": "duration", "start": "ASTDT", "end": "AENDT"},
                    ),
                ],
            )
        ],
    )
    methods = _by_oid(_root(path), f"{ODM}MethodDef")
    text = {oid: m.find(f"{ODM}Description/{ODM}TranslatedText").text for oid, m in methods.items()}
    assert text["MT.ADAE.ADY"] == "Study day of ASTDT relative to TRTSDT."
    assert text["MT.ADAE.ADURN"] == "Duration from ASTDT to AENDT, in days."


# --------------------------------------------------------------------- #
# c1-488 / c1-680: the define names the method the pilot runs             #
# --------------------------------------------------------------------- #


_DM = """\
┌─────────┬─────────────┐
│ USUBJID ┆ ARM         │
│ ---     ┆ ---         │
│ str     ┆ str         │
╞═════════╪═════════════╡
│ S1      ┆ Placebo     │
│ S2      ┆ Xanomeline  │
└─────────┴─────────────┘
"""

_EX = """\
┌─────────┬────────────┬────────────┐
│ USUBJID ┆ EXSTDTC    ┆ EXENDTC    │
│ ---     ┆ ---        ┆ ---        │
│ str     ┆ str        ┆ str        │
╞═════════╪════════════╪════════════╡
│ S1      ┆ 2014-01-02 ┆ 2014-07-02 │
│ S2      ┆ 2014-01-03 ┆ 2014-07-04 │
└─────────┴────────────┴────────────┘
"""

_AE = """\
┌─────────┬────────────┬────────────┬────────────┬────────────┐
│ USUBJID ┆ AESTDTC    ┆ AEENDTC    ┆ TRTSDT     ┆ TRTEDT     │
│ ---     ┆ ---        ┆ ---        ┆ ---        ┆ ---        │
│ str     ┆ str        ┆ str        ┆ date       ┆ date       │
╞═════════╪════════════╪════════════╪════════════╪════════════╡
│ S1      ┆ 2014-01-10 ┆ 2014-01-12 ┆ 2014-01-02 ┆ 2014-07-02 │
│ S2      ┆ 2013-12-01 ┆ 2013-12-02 ┆ 2014-01-03 ┆ 2014-07-04 │
└─────────┴────────────┴────────────┴────────────┴────────────┘
"""


def test_c1_680_each_pilot_methoddef_names_the_method_lineage_records():
    spec = PILOT / "adam" / "define.yaml"
    adsl = (
        fleet.frame(pl.from_repr(_DM))
        .adam.pin("EX", pl.from_repr(_EX))
        .from_spec(spec, dataset="ADSL", only=["TRTSDT", "TRTEDT"])
    )
    adae = fleet.frame(pl.from_repr(_AE)).adam.from_spec(
        spec, dataset="ADAE", only=["ASTDT", "AENDT", "TRTEMFL"]
    )
    recorded = {
        f"MT.ADSL.{n.name}": n.method
        for n in latest_lineage_of(adsl)
        if n.name in ("TRTSDT", "TRTEDT")
    } | {f"MT.ADAE.{n.name}": n.method for n in latest_lineage_of(adae) if n.name == "TRTEMFL"}

    methods = _by_oid(_root(spec), f"{ODM}MethodDef")
    stated = {oid: methods[oid].find(f"{ODM}FormalExpression").text for oid in recorded}

    assert {oid: text.split("(")[0] for oid, text in stated.items()} == recorded
    assert recorded["MT.ADAE.TRTEMFL"].endswith("OCCDSNamespace.treatment_emergent")
    assert adae.to_frame()["TRTEMFL"].to_list() == ["Y", None]


def test_c1_488_treatment_emergent_has_a_spec_form_and_method_text():
    text = spec_registry.render_method_text(
        "adam",
        "occds.treatment_emergent",
        {
            "start_date": "ASTDT",
            "end_date": "AENDT",
            "trtsdt": "TRTSDT",
            "trtedt": "TRTEDT",
            "end_window": 0,
        },
        target="TRTEMFL",
    )
    assert text == (
        "Set to 'Y' when ASTDT is on or after TRTSDT and on or before TRTEDT + 0 days, "
        "or when ASTDT is missing; null when TRTSDT is missing or AENDT is before TRTSDT."
    )


def test_c1_565_fleet_check_imports_no_study_code(tmp_path, monkeypatch):
    marker = tmp_path / "imported.txt"
    (tmp_path / "audit_check_mod.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('x')\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "audit_check_mod", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "study_config.yaml").write_text("study_id: S01\n", encoding="utf-8")
    define = tmp_path / "metadata" / "sdtm" / "define.yaml"
    define.parent.mkdir(parents=True)
    _write(
        define.parent,
        [_dataset("DM", [_var("USUBJID", origin="Assigned")])],
        derivations_module="audit_check_mod",
        study=_study(standard="SDTMIG", standard_version="3.4"),
    )
    try:
        cli.main(["check"])
    except SystemExit:
        pass
    assert not marker.exists()
