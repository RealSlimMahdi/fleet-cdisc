"""Alpha audit package H, PR 2: Define-XML rules (c1-557, c1-776, c1-774).

* c1-557 (Mahdi, Q2 B): a Derived variable with no method text is written
  without a MethodDef, with a warning that names it; ``strict=True`` and
  ``fleet define-xml --strict`` refuse.  Methods are on by default.
* c1-776: ``significant_digits`` exists; Length is required on text,
  integer and float and refused on date and datetime; SignificantDigits is
  required on float and refused elsewhere.
* c1-774: the retired DefineXMLGenerator / DefineValidator are gone, and
  ``fleet check`` runs the real generator.
"""

from __future__ import annotations

import warnings
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
import yaml

import fleet
from fleet import cli
from fleet.core.exceptions import SpecError
from fleet.define_xml import DefineSpecGenerator
from fleet.define_xml.xsd import missing_files

ODM = "{http://www.cdisc.org/ns/odm/v1.3}"
EXAMPLES = Path(__file__).parent.parent.parent / "examples" / "cdiscpilot01"

pytestmark = pytest.mark.skipif(bool(missing_files()), reason="CDISC schema set not installed")

_STUDY = {
    "id": "T01",
    "name": "T01",
    "description": "Fixture",
    "protocol_name": "T01",
    "originator": "Fleet Tests",
    "standard": "SDTMIG",
    "standard_version": "3.4",
}

_USUBJID = {
    "name": "USUBJID",
    "label": "Unique Subject Identifier",
    "type": "text",
    "length": 11,
    "origin": "Collected",
    "mandatory": True,
}


def _spec(*variables: dict, value_level: list | None = None) -> dict:
    dataset = {
        "name": "DM",
        "label": "Demographics",
        "structure": "One record per subject",
        "keys": ["USUBJID"],
        "variables": [_USUBJID, *variables],
    }
    if value_level:
        dataset["value_level"] = value_level
    return {"study": dict(_STUDY), "datasets": [dataset]}


def _write(spec: dict, tmp_path: Path) -> Path:
    path = tmp_path / "define.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return path


def _xml(spec: dict, tmp_path: Path, **kwargs) -> tuple[ET.Element, list[str]]:
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        xml = DefineSpecGenerator(_write(spec, tmp_path), **kwargs).to_xml_string()
    return ET.fromstring(xml), [str(w.message) for w in record]


def _ref(root: ET.Element, item_oid: str) -> ET.Element:
    return next(r for r in root.iter(f"{ODM}ItemRef") if r.get("ItemOID") == item_oid)


def _item(root: ET.Element, name: str) -> ET.Element:
    return next(i for i in root.iter(f"{ODM}ItemDef") if i.get("Name") == name)


_SAFFL_NO_TEXT = {
    "name": "SAFFL",
    "label": "Safety Population Flag",
    "type": "text",
    "length": 1,
    "origin": "Derived",
}


# ── c1-557: every Derived variable gets a method, or a named warning ────────


def test_a_derived_variable_with_no_text_is_named_in_a_warning(tmp_path: Path) -> None:
    root, messages = _xml(_spec(_SAFFL_NO_TEXT), tmp_path)

    assert _ref(root, "IT.DM.SAFFL").get("MethodOID") is None
    assert any("DM.SAFFL" in m and "no method text" in m for m in messages)


def test_strict_refuses_a_derived_variable_with_no_text(tmp_path: Path) -> None:
    with pytest.raises(SpecError, match="DM.SAFFL"):
        DefineSpecGenerator(_write(_spec(_SAFFL_NO_TEXT), tmp_path), strict=True).to_xml_string()


def test_a_comment_alone_gives_a_method_with_no_formal_expression(tmp_path: Path) -> None:
    saffl = {**_SAFFL_NO_TEXT, "comment": "Y if the subject took at least one dose, else N."}

    root, messages = _xml(_spec(saffl), tmp_path)

    assert _ref(root, "IT.DM.SAFFL").get("MethodOID") == "MT.DM.SAFFL"
    method = next(m for m in root.iter(f"{ODM}MethodDef") if m.get("OID") == "MT.DM.SAFFL")
    assert method.find(f"{ODM}FormalExpression") is None
    assert not any("DM.SAFFL" in m for m in messages)


def test_methods_are_on_by_default(tmp_path: Path) -> None:
    agegr1 = {
        "name": "AGEGR1",
        "label": "Pooled Age Group 1",
        "type": "text",
        "length": 5,
        "origin": "Derived",
        "derivation": {"algorithm": "assign", "source": "age_group"},
    }

    root, _ = _xml(_spec(agegr1), tmp_path)

    assert _ref(root, "IT.DM.AGEGR1").get("MethodOID") == "MT.DM.AGEGR1"


def test_a_callable_that_does_not_import_is_named_even_with_a_comment(tmp_path: Path) -> None:
    saffl = {
        **_SAFFL_NO_TEXT,
        "comment": "Y if the subject took at least one dose, else N.",
        "derivation": {"algorithm": "derivation", "callable": "study.derivations.saffl_typo"},
    }

    root, messages = _xml(_spec(saffl), tmp_path)

    assert _ref(root, "IT.DM.SAFFL").get("MethodOID") == "MT.DM.SAFFL"
    assert any("DM.SAFFL" in m and "does not import" in m for m in messages)


def test_value_level_gaps_are_named_and_the_parent_is_judged_there(tmp_path: Path) -> None:
    param = {
        "name": "PARAMCD",
        "label": "Parameter Code",
        "type": "text",
        "length": 8,
        "origin": "Assigned",
    }
    aval = {
        "name": "AVAL",
        "label": "Analysis Value",
        "type": "float",
        "length": 5,
        "significant_digits": 1,
        "origin": "Derived",
    }
    spec = _spec(param, aval, value_level=[{"param": "SYSBP", "variables": [dict(aval)]}])

    _, messages = _xml(spec, tmp_path)

    text = " ".join(messages)
    assert "DM.AVAL (PARAMCD = SYSBP)" in text
    assert "DM.AVAL:" not in text


def test_cli_strict_exits_1_and_default_writes_the_file(tmp_path: Path, capsys) -> None:
    spec = _write(_spec(_SAFFL_NO_TEXT), tmp_path)
    out = tmp_path / "define.xml"

    with pytest.warns(UserWarning, match="DM.SAFFL"):
        assert _main(["define-xml", "--spec", str(spec), "--output", str(out), "--no-preview"]) == 0
    assert out.is_file()

    out.unlink()
    assert (
        _main(["define-xml", "--spec", str(spec), "--output", str(out), "--no-preview", "--strict"])
        == 1
    )
    assert not out.exists()
    assert "DM.SAFFL" in capsys.readouterr().err


def _main(argv: list[str]) -> int:
    try:
        cli.main(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


# ── c1-776: Length and SignificantDigits ────────────────────────────────────


def test_significant_digits_reach_the_item_def(tmp_path: Path) -> None:
    weight = {
        "name": "WEIGHT",
        "label": "Weight",
        "type": "float",
        "length": 5,
        "significant_digits": 1,
        "origin": "Collected",
    }

    root, messages = _xml(_spec(weight), tmp_path)

    item = _item(root, "WEIGHT")
    assert (item.get("Length"), item.get("SignificantDigits")) == ("5", "1")
    assert not any("WEIGHT" in m for m in messages)


@pytest.mark.parametrize(
    ("variable", "named"),
    [
        ({"name": "SEX", "label": "Sex", "type": "text", "origin": "Collected"}, "Length"),
        ({"name": "AGE", "label": "Age", "type": "integer", "origin": "Collected"}, "Length"),
        (
            {
                "name": "WEIGHT",
                "label": "Weight",
                "type": "float",
                "length": 5,
                "origin": "Collected",
            },
            "SignificantDigits",
        ),
    ],
)
def test_a_missing_length_or_significant_digits_is_named(
    tmp_path: Path, variable: dict, named: str
) -> None:
    _, messages = _xml(_spec(variable), tmp_path)

    assert any(f"DM.{variable['name']}" in m and named in m for m in messages)

    with pytest.raises(SpecError, match=named):
        DefineSpecGenerator(_write(_spec(variable), tmp_path), strict=True).to_xml_string()


@pytest.mark.parametrize(
    "variable",
    [
        {
            "name": "BRTHDTC",
            "label": "Date of Birth",
            "type": "date",
            "length": 10,
            "origin": "Collected",
        },
        {
            "name": "AGE",
            "label": "Age",
            "type": "integer",
            "length": 2,
            "significant_digits": 0,
            "origin": "Collected",
        },
    ],
)
def test_the_schema_refuses_length_on_a_date_and_digits_off_float(
    tmp_path: Path, variable: dict
) -> None:
    with pytest.raises(SpecError):
        DefineSpecGenerator(_write(_spec(variable), tmp_path))


# ── c1-557 / c1-776: the shipped pilot specs are complete ──────────────────


@pytest.mark.parametrize("standard", ["sdtm", "adam"])
def test_the_pilot_specs_generate_in_strict_mode(standard: str) -> None:
    DefineSpecGenerator(EXAMPLES / standard / "define.yaml", strict=True).to_xml_string()


# ── c1-774: one generator ───────────────────────────────────────────────────


def test_the_retired_generator_and_validator_are_gone() -> None:
    import fleet.define_xml as define_xml

    for name in ("DefineXMLGenerator", "DefineValidator"):
        assert not hasattr(fleet, name)
        assert not hasattr(define_xml, name)


def test_fleet_check_fails_when_the_generator_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    (tmp_path / "study_config.yaml").write_text("study_id: T01\n", encoding="utf-8")
    meta = tmp_path / "metadata" / "sdtm"
    meta.mkdir(parents=True)
    _write(_spec(_SAFFL_NO_TEXT), meta)
    monkeypatch.chdir(tmp_path)

    _main(["check"])

    out = capsys.readouterr().out
    define_rows = [line for line in out.splitlines() if "define (sdtm)" in line]
    assert define_rows and "FAIL" in define_rows[0]
    assert "DM.SAFFL" in out
