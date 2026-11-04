"""Alpha audit package H, part 3: the study bootstrap.

* c1-533 (Mahdi: C): a scaffolded ``define.yaml`` keeps ``study.description``
  and ``study.originator`` empty when the user gave none. One clean message
  names the empty fields, with no traceback. ``--description`` and
  ``--company`` fill them at creation.
* c1-297 (Mahdi: A, and A to the five engineering questions): a study pins
  an SDTM and an ADaM CT package. The ADaM default is the latest ADaM
  package on or before the SDTM date, adamct-2023-06-30. ``fleet init ct``
  takes each codelist from the first pinned package that holds it, stops on
  a codelist no pin holds, and writes the terms into ``define.yaml``.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest
import yaml

from fleet import cli
from fleet.core.exceptions import CTError, CTNotFoundError, SpecError, SpecSchemaError
from fleet.core.scaffolder import DefineScaffolder
from fleet.core.study_context import load_study_context
from fleet.ct.generator import CodelistGenerator
from fleet.ct.study_codelists import check_codelists, load_codelists
from fleet.define_xml import DefineSpecGenerator

_DM: dict[str, Any] = {
    "name": "DM",
    "label": "Demographics",
    "structure": "One record per subject",
    "keys": ["USUBJID"],
    "variables": [
        {
            "name": "USUBJID",
            "label": "Unique Subject Identifier",
            "type": "text",
            "length": 11,
            "mandatory": True,
            "origin": "Collected",
        }
    ],
}


def _run(argv: list[str]) -> int:
    try:
        cli.main(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _spec(tmp_path: Path, *, description: str, originator: str) -> Path:
    spec = {
        "study": {
            "id": "S01",
            "name": "S01",
            "description": description,
            "protocol_name": "S01",
            "originator": originator,
            "standard": "SDTMIG",
            "standard_version": "3.4",
        },
        "datasets": [_DM],
    }
    path = tmp_path / "define.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return path


class _NoClient:
    """Stands in for ``CDISCClient``: the IG fetchers are patched, so it is never called."""

    def __enter__(self) -> _NoClient:
        return self

    def __exit__(self, *_: object) -> None:
        return None


# ── c1-533: empty study fields ──────────────────────────────────────────────


def test_empty_study_fields_give_one_message_that_names_them(tmp_path: Path) -> None:
    path = _spec(tmp_path, description="", originator="")

    with pytest.raises(SpecSchemaError) as caught:
        DefineSpecGenerator(path)

    message = str(caught.value)
    assert "study.description" in message
    assert "study.originator" in message
    assert "--description" in message
    assert "should be non-empty" not in message


def test_one_empty_field_names_only_that_field(tmp_path: Path) -> None:
    path = _spec(tmp_path, description="A test study", originator="")

    with pytest.raises(SpecSchemaError, match=r"study\.originator") as caught:
        DefineSpecGenerator(path)

    assert "study.description" not in str(caught.value)


def test_define_xml_on_empty_fields_exits_1_with_no_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _spec(tmp_path, description="", originator="")

    code = _run(["define-xml", "--spec", str(path), "--output", str(tmp_path / "d.xml")])

    err = capsys.readouterr().err
    assert code == 1
    assert "Error:" in err
    assert "study.description" in err
    assert "Traceback" not in err


def test_the_scaffold_writes_the_description_it_is_given(tmp_path: Path) -> None:
    path = DefineScaffolder(_NoClient())._write_define(  # type: ignore[arg-type]
        study_id="S01",
        company="Pharma Inc",
        description="Phase II study of drug X",
        standard="SDTMIG",
        standard_version="3.4",
        ct_version="2023-12-15",
        datasets=[_DM],
        output_path=tmp_path / "define.yaml",
    )

    study = yaml.safe_load(path.read_text(encoding="utf-8"))["study"]
    assert study["description"] == "Phase II study of drug X"
    assert study["originator"] == "Pharma Inc"
    DefineSpecGenerator(path).to_xml_string()


def test_the_scaffold_keeps_fields_empty_when_none_is_given(tmp_path: Path) -> None:
    path = DefineScaffolder(_NoClient())._write_define(  # type: ignore[arg-type]
        study_id="S01",
        company="",
        standard="SDTMIG",
        standard_version="3.4",
        ct_version="2023-12-15",
        datasets=[_DM],
        output_path=tmp_path / "define.yaml",
    )

    study = yaml.safe_load(path.read_text(encoding="utf-8"))["study"]
    assert study["description"] == ""
    assert study["originator"] == ""


def test_init_cfg_writes_the_description(tmp_path: Path) -> None:
    argv = ["init", "cfg", "--study-id", "S01", "--root", str(tmp_path)]
    argv += ["--description", "Phase II study of drug X", "--company", "Pharma Inc"]

    assert _run(argv) == 0

    config = yaml.safe_load((tmp_path / "study_config.yaml").read_text(encoding="utf-8"))
    assert config["description"] == "Phase II study of drug X"
    assert config["company"] == "Pharma Inc"


def test_new_passes_the_description_to_the_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CDISC_API_KEY", raising=False)
    argv = ["new", "S01", "--root", str(tmp_path), "--yes", "--domains", "DM"]
    argv += ["--description", "Phase II study of drug X"]

    assert _run(argv) == 0

    config = yaml.safe_load((tmp_path / "study_config.yaml").read_text(encoding="utf-8"))
    assert config["description"] == "Phase II study of drug X"


def test_init_define_writes_the_config_description(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv = ["init", "cfg", "--study-id", "S01", "--root", str(tmp_path), "--domains", "DM"]
    assert _run([*argv, "--description", "Phase II study of drug X", "--company", "P"]) == 0
    monkeypatch.setattr("fleet.ct.api.CDISCClient", _NoClient)
    monkeypatch.setattr(DefineScaffolder, "_fetch_sdtm_datasets", lambda *_: [_DM])

    code = _run(["init", "define", "--config", str(tmp_path / "study_config.yaml")])

    assert code == 0
    define = tmp_path / "metadata" / "sdtm" / "define.yaml"
    study = yaml.safe_load(define.read_text(encoding="utf-8"))["study"]
    assert study["description"] == "Phase II study of drug X"


# ── c1-297: an SDTM and an ADaM CT package ─────────────────────────────────────────

SDTM_CT = "sdtmct-2023-12-15"
ADAM_CT = "adamct-2023-06-30"


def _library_codelist(concept_id: str, name: str, *terms: tuple[str, str]) -> dict[str, Any]:
    """A codelist as the CDISC Library API returns it, cut to what Fleet reads."""
    return {
        "conceptId": concept_id,
        "name": name,
        "submissionValue": name.upper(),
        "terms": [{"submissionValue": v, "preferredTerm": d} for v, d in terms],
    }


#: SEX is only in SDTM CT; DTYPE (C81224) is only in ADaM CT.
_LIBRARY = {
    (SDTM_CT, "C66731"): _library_codelist("C66731", "Sex", ("F", "Female"), ("M", "Male")),
    (ADAM_CT, "C81224"): _library_codelist(
        "C81224",
        "Derivation Type",
        ("LOCF", "Last Observation Carried Forward"),
        ("WOCF", "Worst Observation Carried Forward"),
    ),
}


class _FakeLibrary(_NoClient):
    """The CDISC Library for the ids in ``_LIBRARY``: any other id is not found."""

    def get_codelist(self, concept_id: str, *, package: str) -> dict[str, Any]:
        try:
            return _LIBRARY[(package, concept_id)]
        except KeyError:
            raise CTNotFoundError(f"Resource not found: {package}/{concept_id}") from None


class _NoKey(_NoClient):
    def get_codelist(self, concept_id: str, *, package: str) -> dict[str, Any]:
        raise CTError("CDISC API authentication failed (401). Check your CDISC_API_KEY.")


def _define(standard: str, dataset: str, variable: str, codelist: str) -> dict[str, Any]:
    """A scaffolded define: the codelist entry has no terms yet."""
    return {
        "study": {
            "id": "S01",
            "name": "S01",
            "description": "Test study",
            "protocol_name": "S01",
            "originator": "Test Co",
            "standard": standard,
            "standard_version": "3.4" if standard == "SDTMIG" else "1.3",
            "ct_version": "2023-12-15",
        },
        "codelists": [{"oid": codelist, "name": codelist, "type": "text"}],
        "datasets": [
            {
                "name": dataset,
                "label": dataset,
                "structure": "One record per subject",
                "keys": [variable],
                "variables": [
                    {"name": variable, "label": variable, "type": "text", "codelist": codelist}
                ],
            }
        ],
    }


@pytest.fixture
def ct_study(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A study with an SDTM define (SEX) and an ADaM define (DTYPE), before ``fleet init ct``."""
    (tmp_path / "study_config.yaml").write_text(
        f"study_id: S01\nct:\n  package: {SDTM_CT}\n  adam_package: {ADAM_CT}\n", encoding="utf-8"
    )
    for standard, folder, dataset, variable, codelist in (
        ("SDTMIG", "sdtm", "DM", "SEX", "C66731"),
        ("ADAMIG", "adam", "ADVS", "DTYPE", "C81224"),
    ):
        path = tmp_path / "metadata" / folder / "define.yaml"
        path.parent.mkdir(parents=True)
        spec = _define(standard, dataset, variable, codelist)
        path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr("fleet.ct.api.CDISCClient", _FakeLibrary)
    return tmp_path


def _config(root: Path) -> dict[str, Any]:
    return yaml.safe_load((root / "study_config.yaml").read_text(encoding="utf-8"))


def test_init_cfg_pins_the_adam_package_for_adam_datasets(tmp_path: Path) -> None:
    argv = ["init", "cfg", "--study-id", "S01", "--root", str(tmp_path), "--adam-datasets", "ADSL"]

    assert _run(argv) == 0

    assert _config(tmp_path)["ct"] == {"package": SDTM_CT, "adam_package": ADAM_CT}


def test_init_cfg_without_adam_datasets_pins_no_adam_package(tmp_path: Path) -> None:
    assert _run(["init", "cfg", "--study-id", "S01", "--root", str(tmp_path)]) == 0

    assert _config(tmp_path)["ct"] == {"package": SDTM_CT}


def test_another_sdtm_package_needs_the_adam_package(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["init", "cfg", "--study-id", "S01", "--root", str(tmp_path), "--adam-datasets", "ADSL"]

    code = _run([*argv, "--package", "sdtmct-2024-03-29"])

    assert code == 1
    assert "--adam-package" in capsys.readouterr().err
    assert not (tmp_path / "study_config.yaml").exists()


def test_an_explicit_adam_package_is_pinned(tmp_path: Path) -> None:
    argv = ["init", "cfg", "--study-id", "S01", "--root", str(tmp_path), "--adam-datasets", "ADSL"]
    argv += ["--package", "sdtmct-2024-03-29", "--adam-package", "adamct-2024-03-29"]

    assert _run(argv) == 0

    assert _config(tmp_path)["ct"]["adam_package"] == "adamct-2024-03-29"


def test_each_codelist_comes_from_the_first_pin_that_holds_it() -> None:
    gen = CodelistGenerator.from_concept_ids(
        _FakeLibrary(),  # type: ignore[arg-type]
        {"C66731", "C81224"},
        package=SDTM_CT,
        adam_package=ADAM_CT,
        include_docs=False,
    )

    assert f"__ct_packages__ = ({ADAM_CT!r}, {SDTM_CT!r})" in gen.render()


def test_a_codelist_no_pin_holds_stops_with_its_id() -> None:
    with pytest.raises(CTError, match=rf"{SDTM_CT}, {ADAM_CT}\): C99999\."):
        CodelistGenerator.from_concept_ids(
            _FakeLibrary(),  # type: ignore[arg-type]
            {"C66731", "C99999"},
            package=SDTM_CT,
            adam_package=ADAM_CT,
        )


def test_an_authentication_error_is_not_read_as_not_found() -> None:
    with pytest.raises(CTError, match="401"):
        CodelistGenerator.from_concept_ids(
            _NoKey(),  # type: ignore[arg-type]
            {"C66731"},
            package=SDTM_CT,
            adam_package=ADAM_CT,
        )


def test_init_ct_writes_the_codelists_and_the_define_terms(ct_study: Path) -> None:
    assert _run(["init", "ct", "--config", str(ct_study / "study_config.yaml")]) == 0

    ctx = load_study_context(ct_study / "study_config.yaml")
    assert load_codelists(ctx.codelists_file)[0] == (ADAM_CT, SDTM_CT)
    assert check_codelists(ctx, references=True) == []
    sdtm = yaml.safe_load((ctx.metadata_sdtm_dir / "define.yaml").read_text(encoding="utf-8"))
    assert sdtm["codelists"] == [
        {
            "oid": "C66731",
            "name": "Sex",
            "type": "text",
            "items": [
                {"coded_value": "F", "decode": "Female"},
                {"coded_value": "M", "decode": "Male"},
            ],
        }
    ]
    adam = yaml.safe_load((ctx.metadata_adam_dir / "define.yaml").read_text(encoding="utf-8"))
    assert [i["coded_value"] for i in adam["codelists"][0]["items"]] == ["LOCF", "WOCF"]


def test_init_ct_writes_nothing_when_no_pin_holds_a_codelist(
    ct_study: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    adam_define = ct_study / "metadata" / "adam" / "define.yaml"
    before = adam_define.read_text(encoding="utf-8").replace("C81224", "C99999")
    adam_define.write_text(before, encoding="utf-8")

    code = _run(["init", "ct", "--config", str(ct_study / "study_config.yaml")])

    assert code == 1
    assert "C99999" in capsys.readouterr().err
    assert not (ct_study / "metadata" / "sdtm" / "codelists.py").exists()
    assert adam_define.read_text(encoding="utf-8") == before


def test_check_names_the_adam_pin_when_it_is_not_set(ct_study: Path) -> None:
    (ct_study / "study_config.yaml").write_text(
        f"study_id: S01\nct:\n  package: {SDTM_CT}\n", encoding="utf-8"
    )
    ctx = load_study_context(ct_study / "study_config.yaml")
    CodelistGenerator.from_concept_ids(
        _FakeLibrary(),  # type: ignore[arg-type]
        {"C66731"},
        package=SDTM_CT,
    ).write(ctx.codelists_file)

    problems = check_codelists(ctx, references=True)

    assert problems == [
        "ADVS.DTYPE references codelist C81224, which is not in codelists.py, and "
        "study_config.yaml pins no ADaM CT package. Set ct.adam_package (for example "
        f"{ADAM_CT}), then run: fleet init ct --force"
    ]


def test_a_codelist_without_terms_names_the_fix(tmp_path: Path) -> None:
    spec = _define("SDTMIG", "DM", "SEX", "C66731")
    path = tmp_path / "define.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")

    with pytest.raises(SpecError, match=r"C66731.*fleet init ct"):
        DefineSpecGenerator(path).to_xml_string()


def test_an_adam_define_states_the_sdtm_and_the_adam_ct(tmp_path: Path) -> None:
    spec = _define("ADAMIG", "ADVS", "DTYPE", "C81224")
    spec["study"]["adam_ct_version"] = "2023-06-30"
    spec["codelists"][0]["items"] = [{"coded_value": "LOCF", "decode": "LOCF"}]
    path = tmp_path / "define.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")

    root = ET.fromstring(DefineSpecGenerator(path).to_xml_string().encode("utf-8"))

    ct = [
        (s.get("PublishingSet"), s.get("Version"))
        for s in root.iter("{http://www.cdisc.org/ns/def/v2.1}Standard")
        if s.get("Type") == "CT"
    ]
    assert ct == [("SDTM", "2023-12-15"), ("ADaM", "2023-06-30")]


def test_the_adam_scaffold_writes_the_adam_ct_date(tmp_path: Path) -> None:
    path = DefineScaffolder(_NoClient())._write_define(  # type: ignore[arg-type]
        study_id="S01",
        company="P",
        standard="ADAMIG",
        standard_version="1.3",
        ct_version="2023-12-15",
        adam_ct_version="2023-06-30",
        datasets=[_DM],
        output_path=tmp_path / "define.yaml",
    )

    study = yaml.safe_load(path.read_text(encoding="utf-8"))["study"]
    assert (study["ct_version"], study["adam_ct_version"]) == ("2023-12-15", "2023-06-30")


def test_init_define_writes_the_pinned_adam_ct_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    argv = ["init", "cfg", "--study-id", "S01", "--root", str(tmp_path), "--adam-datasets", "ADVS"]
    assert _run(argv) == 0
    monkeypatch.setattr("fleet.ct.api.CDISCClient", _NoClient)
    monkeypatch.setattr(DefineScaffolder, "_fetch_adam_datasets", lambda *_: [_DM])

    code = _run(["init", "define", "--adam-only", "--config", str(tmp_path / "study_config.yaml")])

    assert code == 0
    define = tmp_path / "metadata" / "adam" / "define.yaml"
    study = yaml.safe_load(define.read_text(encoding="utf-8"))["study"]
    assert (study["ct_version"], study["adam_ct_version"]) == ("2023-12-15", "2023-06-30")


def test_the_adam_scaffold_skips_template_names() -> None:
    names = ["TRTSDT", "TRxxSDT", "ANLzzFL", "PARCATy", "*"]
    structure = {
        "name": "ADSL",
        "analysisVariableSets": [{"analysisVariables": [{"name": n} for n in names]}],
    }

    parsed = DefineScaffolder(_NoClient())._parse_adam_structure(structure)  # type: ignore[arg-type]

    assert [v["name"] for v in parsed["variables"]] == ["TRTSDT"]
