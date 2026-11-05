"""Regression tests for the medium and low Define-XML findings of the alpha audit.

Each test names its finding: SENDIG Purpose (c1-560), FileOID and version
(c1-572), Submission hrefs (c1-568), Domain, class and subclass (c1-567),
value-level conditions (c1-570), conditional Predecessor (c1-779), spec
read errors (c1-564), the packaged stylesheet (c1-569), text with blank
lines or control characters (c1-573), targeted value-level tests (c1-574),
the dataset checker (c1-574, c1-770, c1-772, c1-773) and document links
(c1-777).
"""

from __future__ import annotations

import warnings
import xml.etree.ElementTree as ET
from pathlib import Path

import polars as pl
import pytest
import yaml

import fleet
from fleet import cli
from fleet.core.exceptions import SpecError, SpecSchemaError
from fleet.define_xml import DatasetChecker, DefineSpecGenerator, semantic_errors
from fleet.define_xml.xsd import validate_define_xml

ODM = "{http://www.cdisc.org/ns/odm/v1.3}"
DEF = "{http://www.cdisc.org/ns/def/v2.1}"


def _study(**extra) -> dict:
    return {
        "id": "S01",
        "name": "S01",
        "description": "Define ml findings test study",
        "protocol_name": "S01",
        "originator": "Fleet Tests",
        "standard": "ADAMIG",
        "standard_version": "1.1",
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


def _write(tmp_path: Path, datasets: list[dict], name: str = "define.yaml", **top) -> Path:
    spec = {"study": top.pop("study", _study()), "datasets": datasets, **top}
    path = tmp_path / name
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return path


def _root(path: Path, **kwargs) -> ET.Element:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return ET.fromstring(DefineSpecGenerator(path, **kwargs).to_xml_string())


def _group(root: ET.Element, name: str) -> ET.Element:
    return next(g for g in root.iter(f"{ODM}ItemGroupDef") if g.get("Name") == name)


_SDTM = {"standard": "SDTMIG", "standard_version": "3.4"}


# --------------------------------------------------------------------- #
# c1-560: a SENDIG define is Tabulation                                   #
# --------------------------------------------------------------------- #


def test_c1_560_a_sendig_dataset_has_purpose_tabulation(tmp_path):
    path = _write(
        tmp_path,
        [_dataset("DM", [_var("USUBJID")], **{"class": "SPECIAL PURPOSE"})],
        study=_study(standard="SENDIG", standard_version="3.1"),
    )

    assert _group(_root(path), "DM").get("Purpose") == "Tabulation"


# --------------------------------------------------------------------- #
# c1-572: one FileOID per standard; the running Fleet version            #
# --------------------------------------------------------------------- #


def test_c1_572_two_standards_give_two_file_oids_and_the_running_version(tmp_path):
    adam = _write(tmp_path, [_dataset("ADSL", [_var("USUBJID")])], name="adam.yaml")
    sdtm = _write(
        tmp_path, [_dataset("DM", [_var("USUBJID")])], name="sdtm.yaml", study=_study(**_SDTM)
    )

    adam_root, sdtm_root = _root(adam), _root(sdtm)

    assert adam_root.get("FileOID") == "CDISC.S01.ADAMIG.1.Define-XML_2.1.0"
    assert sdtm_root.get("FileOID") == "CDISC.S01.SDTMIG.1.Define-XML_2.1.0"
    assert adam_root.get("SourceSystemVersion") == fleet.__version__


def test_c1_572_source_system_version_stays_an_override(tmp_path):
    path = _write(
        tmp_path, [_dataset("ADSL", [_var("USUBJID")])], study=_study(source_system_version="9.9")
    )

    assert _root(path).get("SourceSystemVersion") == "9.9"


# --------------------------------------------------------------------- #
# c1-568: a Submission define that names parquet files warns once        #
# --------------------------------------------------------------------- #


def test_c1_568_a_parquet_href_warns_once_and_is_kept(tmp_path):
    path = _write(tmp_path, [_dataset("ADSL", [_var("USUBJID")])])

    with pytest.warns(UserWarning, match=r"names adsl\.parquet; FDA accepts XPT") as record:
        xml = DefineSpecGenerator(path).to_xml_string()

    assert sum("FDA accepts XPT" in str(w.message) for w in record) == 1
    assert 'xlink:href="adsl.parquet"' in xml


def test_c1_568_an_xpt_href_gives_no_submission_warning(tmp_path):
    path = _write(tmp_path, [_dataset("ADSL", [_var("USUBJID")])], output_format="xpt")

    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        DefineSpecGenerator(path).to_xml_string()

    assert not [w for w in record if "FDA accepts XPT" in str(w.message)]


# --------------------------------------------------------------------- #
# c1-567: Domain, def:Class and def:SubClass                             #
# --------------------------------------------------------------------- #


def test_c1_567_an_adam_dataset_has_no_domain_and_gets_its_subclass(tmp_path):
    path = _write(
        tmp_path,
        [
            _dataset(
                "ADAE",
                [_var("USUBJID")],
                **{"class": "OCCURRENCE DATA STRUCTURE", "subclass": "ADVERSE EVENT"},
            )
        ],
    )

    group = _group(_root(path), "ADAE")

    assert group.get("Domain") is None
    cls = group.find(f"{DEF}Class")
    assert cls.get("Name") == "OCCURRENCE DATA STRUCTURE"
    assert cls.find(f"{DEF}SubClass").get("Name") == "ADVERSE EVENT"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        assert validate_define_xml(DefineSpecGenerator(path).to_xml_string()) == []


def test_c1_567_a_split_sdtm_dataset_names_its_domain(tmp_path):
    path = _write(
        tmp_path,
        [_dataset("QSPH", [_var("USUBJID")], **{"class": "FINDINGS", "domain": "QS"})],
        study=_study(**_SDTM),
    )

    assert _group(_root(path), "QSPH").get("Domain") == "QS"


def test_c1_567_a_dataset_with_no_class_warns(tmp_path):
    path = _write(tmp_path, [_dataset("ADSL", [_var("USUBJID")])])

    with pytest.warns(UserWarning, match="ADSL have no class:"):
        DefineSpecGenerator(path).to_xml_string()


def test_c1_567_a_tabulation_class_on_an_adam_dataset_is_refused(tmp_path):
    path = _write(tmp_path, [_dataset("ADSL", [_var("USUBJID")], **{"class": "FINDINGS"})])

    with pytest.raises(SpecError, match=r"ADSL \(FINDINGS\)"):
        DefineSpecGenerator(path).to_xml_string()


# --------------------------------------------------------------------- #
# c1-570: value-level conditions                                         #
# --------------------------------------------------------------------- #


def _lb(value_level: list[dict]) -> list[dict]:
    variables = [_var("USUBJID"), _var("LBTESTCD"), _var("LBSPEC"), _var("LBORRES")]
    return [_dataset("LB", variables, value_level=value_level, **{"class": "FINDINGS"})]


def _orres(name: str = "LBORRES") -> list[dict]:
    return [{"name": name, "label": "Result", "type": "text", "length": 8, "origin": "Collected"}]


def test_c1_570_two_conditions_with_one_oid_are_refused(tmp_path):
    path = _write(
        tmp_path,
        _lb(
            [
                {"where": {"variable": "LBTESTCD", "value": ["A", "B"]}, "variables": _orres()},
                {"where": {"variable": "LBTESTCD", "value": "A_B"}, "variables": _orres()},
            ]
        ),
        study=_study(**_SDTM),
    )

    with pytest.raises(SpecError, match=r"same WhereClauseDef OID WC\.LB\.LBTESTCD\.A_B"):
        DefineSpecGenerator(path).to_xml_string()


def test_c1_570_a_list_of_conditions_gives_one_where_clause_with_two_range_checks(tmp_path):
    where = [
        {"variable": "LBTESTCD", "value": "GLUC"},
        {"variable": "LBSPEC", "value": "URINE", "comparator": "EQ"},
    ]
    path = _write(tmp_path, _lb([{"where": where, "variables": _orres()}]), study=_study(**_SDTM))

    root = _root(path)

    wc = next(root.iter(f"{DEF}WhereClauseDef"))
    assert wc.get("OID") == "WC.LB.LBTESTCD.GLUC.LBSPEC.URINE"
    checks = [
        (rc.get(f"{DEF}ItemOID"), rc.get("Comparator"), rc.find(f"{ODM}CheckValue").text)
        for rc in wc.iter(f"{ODM}RangeCheck")
    ]
    assert checks == [("IT.LB.LBTESTCD", "EQ", "GLUC"), ("IT.LB.LBSPEC", "EQ", "URINE")]
    assert "IT.LB.LBORRES.GLUC_URINE" in {i.get("OID") for i in root.iter(f"{ODM}ItemDef")}


def test_c1_570_a_comparator_is_written_and_named_in_the_oid(tmp_path):
    where = {"variable": "LBTESTCD", "value": "GLUC", "comparator": "NE"}
    path = _write(tmp_path, _lb([{"where": where, "variables": _orres()}]), study=_study(**_SDTM))

    wc = next(_root(path).iter(f"{DEF}WhereClauseDef"))

    assert wc.get("OID") == "WC.LB.LBTESTCD.NE_GLUC"
    assert next(wc.iter(f"{ODM}RangeCheck")).get("Comparator") == "NE"


def test_c1_570_a_single_value_comparator_with_a_list_is_refused(tmp_path):
    where = {"variable": "LBTESTCD", "value": ["A", "B"], "comparator": "EQ"}
    path = _write(tmp_path, _lb([{"where": where, "variables": _orres()}]), study=_study(**_SDTM))

    with pytest.raises(SpecError, match="comparator EQ takes one value"):
        DefineSpecGenerator(path)


# --------------------------------------------------------------------- #
# c1-574: a where clause on AVISIT                                       #
# --------------------------------------------------------------------- #


def test_c1_574_a_where_clause_on_avisit_points_at_avisit(tmp_path):
    variables = [_var("USUBJID"), _var("AVISIT", length=20), _var("AVALC")]
    value_level = [
        {
            "where": {"variable": "AVISIT", "value": "WEEK 2"},
            "variables": [
                {**_var("AVALC"), "origin": "Collected", "mandatory": True},
            ],
        },
        {
            "where": {"variable": "AVISIT", "value": "WEEK 4"},
            "variables": [{**_var("AVALC"), "origin": "Collected", "mandatory": False}],
        },
    ]
    path = _write(
        tmp_path,
        [
            _dataset(
                "ADQS",
                variables,
                value_level=value_level,
                **{"class": "BASIC DATA STRUCTURE"},
            )
        ],
    )

    root = _root(path)

    checks = {rc.get(f"{DEF}ItemOID") for rc in root.iter(f"{ODM}RangeCheck")}
    assert checks == {"IT.ADQS.AVISIT"}
    assert {rc.get("SoftHard") for rc in root.iter(f"{ODM}RangeCheck")} == {"Soft"}
    vl = next(root.iter(f"{DEF}ValueListDef"))
    mandatory = {ref.get("ItemOID"): ref.get("Mandatory") for ref in vl.iter(f"{ODM}ItemRef")}
    assert mandatory == {"IT.ADQS.AVALC.WEEK 2": "Yes", "IT.ADQS.AVALC.WEEK 4": "No"}


# --------------------------------------------------------------------- #
# c1-779: a conditional Predecessor; MethodOID only on Derived           #
# --------------------------------------------------------------------- #


def test_c1_779_a_conditional_predecessor_is_written_as_its_description(tmp_path):
    ref = "DS.DSDECOD where DS.DSCAT='DISPOSITION EVENT'"
    path = _write(
        tmp_path,
        [
            _dataset(
                "ADSL",
                [_var("USUBJID"), _var("EOSSTT", origin="Predecessor", predecessor=ref)],
                **{"class": "SUBJECT LEVEL ANALYSIS DATASET"},
            )
        ],
    )

    root = _root(path)

    item = next(i for i in root.iter(f"{ODM}ItemDef") if i.get("OID") == "IT.ADSL.EOSSTT")
    assert item.find(f"{DEF}Origin/{ODM}Description/{ODM}TranslatedText").text == ref


def test_c1_779_the_generator_writes_methodoid_only_for_derived(tmp_path):
    variables = [
        _var("USUBJID", origin="Collected", comment="Copied from the CRF."),
        _var("AGEGR1", origin="Derived", comment="Age group from AGE."),
    ]
    path = _write(
        tmp_path,
        [_dataset("ADSL", variables, **{"class": "SUBJECT LEVEL ANALYSIS DATASET"})],
    )

    refs = {r.get("ItemOID"): r.get("MethodOID") for r in _root(path).iter(f"{ODM}ItemRef")}

    assert refs == {"IT.ADSL.USUBJID": None, "IT.ADSL.AGEGR1": "MT.ADSL.AGEGR1"}


# --------------------------------------------------------------------- #
# c1-564: a bad spec file gives one clean message                        #
# --------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "this file is an empty file"),
        ("- a\n- b\n", "this file is a list"),
        ("study:\n  id: S\n bad: indent\n", "invalid YAML"),
        ("variables:\n  - name: A\n", "a mapping with no datasets:"),
    ],
)
def test_c1_564_a_spec_that_is_not_a_define_raises_a_schema_error(tmp_path, text, message):
    path = tmp_path / "define.yaml"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(SpecSchemaError, match=message):
        DefineSpecGenerator(path)
    with pytest.raises(SpecSchemaError, match=message):
        DatasetChecker(path)


def test_c1_564_an_old_algorithm_name_names_fleet_migrate(tmp_path):
    variables = [_var("USUBJID"), _var("FLAG", derivation={"algorithm": "if_then_else"})]
    path = _write(tmp_path, [_dataset("ADSL", variables)])

    with pytest.raises(
        SpecSchemaError, match=r"old name of 'case_when'. Run: fleet migrate --spec"
    ):
        DefineSpecGenerator(path)


def test_c1_564_the_cli_prints_one_line_for_an_empty_spec(tmp_path, capsys):
    path = tmp_path / "empty.yaml"
    path.write_text("", encoding="utf-8")

    with pytest.raises(SystemExit) as exit_info:
        cli.main(["define-xml", "--spec", str(path), "--output", str(tmp_path / "d.xml")])

    assert exit_info.value.code == 1
    err = capsys.readouterr().err
    assert "a define.yaml is a mapping with study: and datasets:" in err
    assert "Traceback" not in err


# --------------------------------------------------------------------- #
# c1-569: the packaged define2-1.xsl                                      #
# --------------------------------------------------------------------- #


def test_c1_569_generate_copies_the_stylesheet_and_writes_the_preview(tmp_path):
    path = _write(tmp_path, [_dataset("ADSL", [_var("USUBJID")])])
    out = tmp_path / "out" / "define.xml"

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        DefineSpecGenerator(path).generate(out)

    assert (out.parent / "define2-1.xsl").read_text(encoding="utf-8").count("MIT") >= 1
    assert (out.parent / "define_preview.html").is_file()


def test_c1_569_a_sponsor_stylesheet_is_not_replaced(tmp_path):
    path = _write(tmp_path, [_dataset("ADSL", [_var("USUBJID")])])
    sponsor = tmp_path / "define2-1.xsl"
    sponsor.write_text("<sponsor/>", encoding="utf-8")

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        DefineSpecGenerator(path).generate(tmp_path / "define.xml", html_preview=False)

    assert sponsor.read_text(encoding="utf-8") == "<sponsor/>"


# --------------------------------------------------------------------- #
# c1-573: blank lines stay; a control character names its field          #
# --------------------------------------------------------------------- #


def test_c1_573_a_blank_line_in_a_description_stays(tmp_path):
    path = _write(
        tmp_path, [_dataset("ADSL", [_var("USUBJID")])], study=_study(description="L1\n\nL2")
    )

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        xml = DefineSpecGenerator(path).to_xml_string()

    assert "L1\n\nL2" in xml


def test_c1_573_a_control_character_raises_a_spec_error_that_names_the_field(tmp_path):
    variables = [_var("USUBJID", origin="Collected", comment="bad\vtext")]
    path = _write(tmp_path, [_dataset("ADSL", variables)])

    with pytest.raises(SpecError, match=r"IT\.ADSL\.USUBJID TranslatedText text"):
        DefineSpecGenerator(path).to_xml_string()


# --------------------------------------------------------------------- #
# c1-777: a document link is a relative path or an https link            #
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("href", ["blankcrf.pdf", "../a/b c.pdf", "https://x/y.pdf", "a/b:c.pdf"])
def test_c1_777_a_relative_path_or_https_link_is_accepted(tmp_path, href):
    path = _write(
        tmp_path,
        [_dataset("ADSL", [_var("USUBJID")])],
        study=_study(documents={"annotated_crf": {"href": href}}),
    )

    DefineSpecGenerator(path)


@pytest.mark.parametrize(
    "href",
    [
        "javascript:alert(1)",
        "JAVASCRIPT:alert(1)",
        "data:text/html,x",
        "file:///etc/passwd",
        "java\tscript:alert(1)",
        " javascript:alert(1)",
        "\njavascript:alert(1)",
    ],
)
def test_c1_777_a_script_or_file_link_is_refused(tmp_path, href):
    docs = {
        "annotated_crf": {"href": "blankcrf.pdf"},
        "supplemental_docs": [{"id": "LF.SDRG", "href": href, "title": "Guide"}],
    }
    path = _write(tmp_path, [_dataset("ADSL", [_var("USUBJID")])], study=_study(documents=docs))

    with pytest.raises(SpecSchemaError, match="supplemental_docs"):
        DefineSpecGenerator(path)


# --------------------------------------------------------------------- #
# c1-773: str and Path inputs; a LazyFrame                               #
# --------------------------------------------------------------------- #


def test_c1_773_both_validators_read_a_str_or_path_file(tmp_path):
    spec = _write(
        tmp_path,
        [_dataset("ADSL", [_var("USUBJID")], **{"class": "SUBJECT LEVEL ANALYSIS DATASET"})],
        output_format="xpt",
    )
    out = tmp_path / "define.xml"
    DefineSpecGenerator(spec).generate(out, html_preview=False)

    assert validate_define_xml(str(out)) == []
    assert semantic_errors(out) == []
    assert semantic_errors(str(out)) == []


# --------------------------------------------------------------------- #
# DatasetChecker: types (c1-574, c1-770), values (c1-772), LazyFrame      #
# --------------------------------------------------------------------- #


def _checker(
    tmp_path: Path, variables: list[dict], keys: list[str] | None = None
) -> DatasetChecker:
    ds = _dataset("ADSL", variables)
    if keys:
        ds["keys"] = keys
    codelist = {
        "oid": "CL.TRT01PN",
        "name": "TRT01PN",
        "type": "integer",
        "items": [{"coded_value": "0"}, {"coded_value": "54"}],
    }
    return DatasetChecker(_write(tmp_path, [ds], codelists=[codelist]))


def _int_var(name: str, **extra) -> dict:
    return {"name": name, "label": name, "type": "integer", "length": 8, **extra}


def test_c1_770_whole_floats_pass_an_integer_variable_and_its_codelist(tmp_path):
    adsl = pl.from_repr("""
┌─────────┬─────────┐
│ USUBJID ┆ TRT01PN │
│ ---     ┆ ---     │
│ str     ┆ f64     │
╞═════════╪═════════╡
│ 1       ┆ 0.0     │
│ 2       ┆ 54.0    │
└─────────┴─────────┘
""")
    checker = _checker(tmp_path, [_var("USUBJID"), _int_var("TRT01PN", codelist="CL.TRT01PN")])

    result = checker.check(adsl, "ADSL")

    assert result.errors == []


def test_c1_574_c1_770_a_fraction_in_an_integer_variable_fails(tmp_path):
    adsl = pl.from_repr("""
┌─────────┬─────────┐
│ USUBJID ┆ TRT01PN │
│ ---     ┆ ---     │
│ str     ┆ f64     │
╞═════════╪═════════╡
│ 1       ┆ 1.5     │
└─────────┴─────────┘
""")
    checker = _checker(tmp_path, [_var("USUBJID"), _int_var("TRT01PN")])

    result = checker.check(adsl, "ADSL")

    assert [m.variable for m in result.type_mismatches] == ["TRT01PN"]


def test_c1_574_a_string_in_a_date_variable_fails(tmp_path):
    adsl = pl.from_repr("""
┌─────────┬────────────┐
│ USUBJID ┆ TRTSDT     │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ 1       ┆ 2024-01-15 │
└─────────┴────────────┘
""")
    date_var = {"name": "TRTSDT", "label": "TRTSDT", "type": "date"}
    checker = _checker(tmp_path, [_var("USUBJID"), date_var])

    result = checker.check(adsl, "ADSL")

    assert [m.variable for m in result.type_mismatches] == ["TRTSDT"]


@pytest.mark.parametrize(
    ("core", "bucket"), [("Req", "errors"), ("Exp", "warnings"), ("Perm", "info")]
)
def test_c1_574_a_missing_column_follows_its_core(tmp_path, core, bucket):
    adsl = pl.from_repr("""
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ 1       │
└─────────┘
""")
    checker = _checker(tmp_path, [_var("USUBJID"), _var("AGEGR1", core=core)])

    result = checker.check(adsl, "ADSL")

    assert any("AGEGR1" in m for m in getattr(result, bucket))


def test_c1_772_length_mandatory_and_duplicate_keys_are_errors(tmp_path):
    adsl = pl.from_repr("""
┌─────────┬──────────────┬─────────┐
│ STUDYID ┆ USUBJID      ┆ TRT01PN │
│ ---     ┆ ---          ┆ ---     │
│ str     ┆ str          ┆ i64     │
╞═════════╪══════════════╪═════════╡
│ S01     ┆ 123456789012 ┆ null    │
│ S01     ┆ 123456789012 ┆ 54      │
└─────────┴──────────────┴─────────┘
""")
    variables = [_var("STUDYID"), _var("USUBJID"), _int_var("TRT01PN", mandatory=True)]
    checker = _checker(tmp_path, variables, keys=["STUDYID", "USUBJID"])

    result = checker.check(adsl, "ADSL")

    assert result.is_valid is False
    assert any("USUBJID" in e and "longer than the define Length 8" in e for e in result.errors)
    assert any("TRT01PN" in e and "Mandatory" in e for e in result.errors)
    assert any("share their key" in e for e in result.errors)


def test_c1_772_a_null_key_alone_is_not_a_duplicate(tmp_path):
    adsl = pl.from_repr("""
┌─────────┬─────────┬───────┐
│ STUDYID ┆ USUBJID ┆ ASEQ  │
│ ---     ┆ ---     ┆ ---   │
│ str     ┆ str     ┆ i64   │
╞═════════╪═════════╪═══════╡
│ S01     ┆ 1       ┆ null  │
│ S01     ┆ 1       ┆ 1     │
└─────────┴─────────┴───────┘
""")
    variables = [_var("STUDYID"), _var("USUBJID"), _int_var("ASEQ")]
    checker = _checker(tmp_path, variables, keys=["STUDYID", "USUBJID", "ASEQ"])

    assert checker.check(adsl, "ADSL").errors == []
    doubled = pl.concat([adsl.head(1), adsl.head(1)])
    assert any("share their key" in e for e in checker.check(doubled, "ADSL").errors)


def test_c1_773_check_collects_a_lazyframe(tmp_path):
    adsl = pl.from_repr("""
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ 1       │
└─────────┘
""")
    checker = _checker(tmp_path, [_var("USUBJID")])

    assert checker.check(adsl.lazy(), "ADSL").errors == []


# --------------------------------------------------------------------- #
# c1-574: Dataset-JSON types, raw dates and SE element boundaries         #
# --------------------------------------------------------------------- #


def test_c1_574_dataset_json_writes_the_type_label_length_and_iso_text(tmp_path):
    import json
    from datetime import date, datetime

    from fleet.io import save_dataset_json

    adsl = pl.DataFrame(
        {
            "USUBJID": ["S1", "S22"],
            "AGE": [54, None],
            "TRTSDT": [date(2024, 1, 15), None],
            "TRTSDTM": [datetime(2024, 1, 15, 8, 30, 5), None],
        }
    )

    out = save_dataset_json(
        adsl, tmp_path / "adsl.json", domain="ADSL", columns={"AGE": {"label": "Age"}}
    )

    doc = json.loads(out.read_text())
    columns = {c["name"]: c for c in doc["columns"]}
    assert columns["USUBJID"]["dataType"] == "string" and columns["USUBJID"]["length"] == 3
    assert columns["AGE"]["dataType"] == "integer" and columns["AGE"]["label"] == "Age"
    assert columns["TRTSDT"]["dataType"] == "date"
    assert columns["TRTSDTM"]["dataType"] == "datetime"
    assert doc["rows"][0] == ["S1", 54, "2024-01-15", "2024-01-15T08:30:05"]


def test_c1_574_dtc_text_keeps_seconds_and_drops_an_unparsable_date():
    from fleet.sdtm.utils import dtc_text

    raw = pl.from_repr("""
┌─────────────────────┐
│ raw                 │
│ ---                 │
│ str                 │
╞═════════════════════╡
│ 15/01/2024 08:30:45 │
│ not a date          │
└─────────────────────┘
""")

    out = raw.select(dtc_text(pl.col("raw"), input_format="%d/%m/%Y %H:%M:%S"))

    assert out.to_series().to_list() == ["2024-01-15T08:30:45", None]


def test_c1_574_element_boundaries_end_within_each_subject():
    se = pl.from_repr("""
┌─────────┬──────┬────────────┬────────────┐
│ USUBJID ┆ ETCD ┆ scr        ┆ trt        │
│ ---     ┆ ---  ┆ ---        ┆ ---        │
│ str     ┆ str  ┆ str        ┆ str        │
╞═════════╪══════╪════════════╪════════════╡
│ S1      ┆ SCRN ┆ 2024-01-01 ┆ 2024-01-08 │
│ S1      ┆ TRT  ┆ 2024-01-01 ┆ 2024-01-08 │
│ S2      ┆ SCRN ┆ 2024-02-01 ┆ 2024-02-08 │
│ S2      ┆ TRT  ┆ 2024-02-01 ┆ 2024-02-08 │
└─────────┴──────┴────────────┴────────────┘
""")

    out = se.sdtm.element_boundaries(
        "SESTDTC", "SEENDTC", milestones={"SCRN": "scr", "TRT": "trt"}
    ).to_frame()

    assert out["SEENDTC"].to_list() == ["2024-01-08", None, "2024-02-08", None]
