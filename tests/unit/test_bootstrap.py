"""Alpha audit package H, part 3: the study bootstrap.

* c1-533 (Mahdi: C): a scaffolded ``define.yaml`` keeps ``study.description``
  and ``study.originator`` empty when the user gave none. One clean message
  names the empty fields, with no traceback. ``--description`` and
  ``--company`` fill them at creation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from fleet import cli
from fleet.core.exceptions import SpecSchemaError
from fleet.core.scaffolder import DefineScaffolder
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
