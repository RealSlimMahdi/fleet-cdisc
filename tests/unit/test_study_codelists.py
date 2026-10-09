"""Spec-driven CT through the study's ``codelists.py``, with stale detection (#131).

After ``fleet new`` a study holds ``study_config.yaml``, a ``define.yaml`` and
the ``codelists.py`` that ``fleet init ct`` generated from it.  The tests
build that state offline: the codelists file comes from
:class:`~fleet.ct.generator.CodelistGenerator` fed with CDISC Library JSON
written inline, so no test calls the network.
"""

from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

import polars as pl
import pytest
import yaml

import fleet  # noqa: F401 — registers the namespaces
from fleet import cli
from fleet.core.study_context import load_study_context
from fleet.ct import get_validator, import_codelists, study_codelists
from fleet.ct.generator import CodelistGenerator
from fleet.ct.study_codelists import check_codelists, read_codelists_file

PINNED = "sdtmct-2023-12-15"
NEWER = "sdtmct-2024-09-27"


def _codelist(concept_id: str, name: str, *terms: str) -> dict:
    """A codelist as the CDISC Library API returns it, cut to what the generator reads."""
    return {
        "conceptId": concept_id,
        "submissionValue": name,
        "terms": [{"submissionValue": t} for t in terms],
    }


AESEV = _codelist("C66769", "AESEV", "MILD", "MODERATE", "SEVERE")
NY = _codelist("C66742", "NY", "N", "Y")
OUT = _codelist("C66768", "OUT", "FATAL", "RECOVERED/RESOLVED")

_AE_DEFINE = """\
study:
  id: S01
  name: S01
  description: Test study for the codelists checks
  protocol_name: S01
  originator: Test Co
  standard: SDTMIG
  standard_version: "3.4"
datasets:
  - name: AE
    label: Adverse Events
    structure: One record per adverse event per subject
    class: EVENTS
    keys: [STUDYID, USUBJID, AESEQ]
    inputs:
      - name: ae
        type: dataset
    variables:
      - name: DOMAIN
        label: Domain Abbreviation
        type: text
        mandatory: true
        derivation:
          algorithm: hardcode_no_ct
          value: "AE"
      - name: AESEV
        label: Severity/Intensity
        type: text
        mandatory: false
        origin: Collected
        codelist: C66769
        derivation:
          algorithm: assign_ct
          source: ae_severity
          ct_codelist: C66769
"""

RAW = pl.from_repr("""\
┌─────────────┐
│ ae_severity │
│ ---         │
│ str         │
╞═════════════╡
│ Mild        │
│ SEVERE      │
└─────────────┘
""")


def _write_codelists(path: Path, *codelists: tuple[dict, str]) -> None:
    """Generate ``codelists.py`` as ``fleet init ct`` does, one package per codelist."""
    generator = CodelistGenerator(include_docs=False)
    for codelist, package in codelists:
        generator.add_codelist(codelist, package=package)
    generator.write(path)


def _pin(study: Path, package: str) -> None:
    (study / "study_config.yaml").write_text(
        f"study_id: S01\nct:\n  package: {package}\n", encoding="utf-8"
    )


def _run(argv: list[str]) -> int:
    try:
        cli.main(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


@pytest.fixture(autouse=True)
def _fresh_process(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts as a new process: no CT loaded, nothing warned or resolved, no engine."""
    monkeypatch.setattr(get_validator(), "_ct_cache", {})
    monkeypatch.setattr(get_validator(), "_codelist_aliases", {})
    monkeypatch.setattr(study_codelists, "_WARNED", set())
    monkeypatch.setattr(study_codelists, "_RESOLVED", {})
    study_codelists._pinned_package.cache_clear()
    monkeypatch.delenv("FLEET_RULES_ENGINE", raising=False)
    monkeypatch.setattr("fleet.validation.engine.ENGINE_DIR", Path("/nonexistent/fleet-engine"))


@pytest.fixture
def study(tmp_path: Path) -> Path:
    """A study as ``fleet new`` leaves it: config, SDTM define, generated codelists."""
    root = tmp_path / "study"
    (root / "metadata" / "sdtm").mkdir(parents=True)
    _pin(root, PINNED)
    (root / "metadata" / "sdtm" / "define.yaml").write_text(_AE_DEFINE, encoding="utf-8")
    _write_codelists(root / "metadata" / "sdtm" / "codelists.py", (AESEV, PINNED), (NY, PINNED))
    return root


@pytest.fixture
def inline_codelists(study: Path):
    """The study's codelists module, imported the way an analyst does (``import_codelists``)."""
    yield import_codelists(
        study / "metadata" / "sdtm" / "codelists.py", module_name="codelists_131"
    )
    sys.modules.pop("codelists_131", None)


def _messages(run) -> list[str]:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        run()
    return [str(w.message) for w in caught]


class TestSameTermsInBothNotations:
    def test_spec_and_inline_give_the_same_warning(self, study: Path, inline_codelists) -> None:
        define = study / "metadata" / "sdtm" / "define.yaml"
        aesev = inline_codelists.AESEV

        inline = _messages(
            lambda: (
                RAW.sdtm.assign("DOMAIN", value="AE")
                .assign("AESEV", source="ae_severity", ct=aesev)
                .to_frame()
            )
        )
        spec = _messages(lambda: RAW.sdtm.from_spec(define, dataset="AE").to_frame())

        assert spec == inline
        assert any(
            m.startswith(
                "AE.AESEV: column 'ae_severity' contains values not in codelist 'C66769': ['Mild']"
            )
            for m in spec
        )

    def test_outside_a_study_the_spec_falls_back_to_the_validator(self, tmp_path: Path) -> None:
        define = tmp_path / "define.yaml"
        define.write_text(_AE_DEFINE, encoding="utf-8")

        messages = _messages(lambda: RAW.sdtm.from_spec(define, dataset="AE").to_frame())

        assert any("codelist 'C66769' not found / CT not loaded" in m for m in messages)


class TestStaleCodelists:
    def test_a_stale_marker_warns_once_and_fails_fleet_check(
        self, study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        _pin(study, NEWER)
        define = study / "metadata" / "sdtm" / "define.yaml"

        messages = _messages(lambda: RAW.sdtm.from_spec(define, dataset="AE").to_frame())
        messages += _messages(lambda: RAW.sdtm.from_spec(define, dataset="AE").to_frame())

        stale = [m for m in messages if "study_config.yaml pins" in m]
        assert stale == [
            f"codelists.py was generated from {PINNED}, but study_config.yaml pins {NEWER}. "
            f"CT checks use the {PINNED} terms. Run: fleet init ct --force"
        ]
        # values are still checked against the terms in the file
        assert sum("not in codelist 'C66769'" in m for m in messages) == 2

        monkeypatch.chdir(study)
        assert _run(["check"]) == 1
        assert "fleet init ct --force" in capsys.readouterr().out

    def test_fleet_check_names_the_dataset_variable_and_missing_codelist(
        self, study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        define = study / "metadata" / "sdtm" / "define.yaml"
        spec = yaml.safe_load(define.read_text(encoding="utf-8"))
        spec["datasets"][0]["variables"].append(
            {
                "name": "AEOUT",
                "label": "Outcome of Adverse Event",
                "type": "text",
                "codelist": "C66768",
            }
        )
        define.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
        monkeypatch.chdir(study)

        assert _run(["check"]) == 1

        assert (
            "AE.AEOUT references codelist C66768, which is not in codelists.py. "
            "Run: fleet add-ct --domains AE"
        ) in capsys.readouterr().out

    def test_fleet_check_passes_a_study_whose_codelists_agree(
        self, study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.chdir(study)

        assert _run(["check"]) == 0

        assert f"codelists.py ({PINNED})" in capsys.readouterr().out

    def test_a_file_without_marker_takes_its_package_from_the_class_urls(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "codelists.py"
        _write_codelists(path, (AESEV, PINNED))
        # a file generated before the marker existed
        path.write_text(
            re.sub(r"^__ct_package__ = .*\n", "", path.read_text(encoding="utf-8"), flags=re.M),
            encoding="utf-8",
        )

        codelists = read_codelists_file(path)

        assert codelists.marker is None
        assert codelists.package == PINNED

    def test_a_mixed_package_file_is_detected(self, study: Path) -> None:
        _write_codelists(
            study / "metadata" / "sdtm" / "codelists.py",
            (AESEV, PINNED),
            (NY, PINNED),
            (OUT, NEWER),
        )

        problems = check_codelists(load_study_context(study / "study_config.yaml"))

        assert problems == [
            f"codelists.py mixes {PINNED} (2 classes) and {NEWER} (1 class). "
            "Run: fleet init ct --force"
        ]

    def test_a_missing_file_warns_and_fails_fleet_check(
        self, study: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (study / "metadata" / "sdtm" / "codelists.py").unlink()
        define = study / "metadata" / "sdtm" / "define.yaml"

        messages = _messages(lambda: RAW.sdtm.from_spec(define, dataset="AE").to_frame())

        assert (
            "define.yaml references 1 codelist, but metadata/sdtm/codelists.py does not exist. "
            "Run: fleet init ct"
        ) in messages
        monkeypatch.chdir(study)
        assert _run(["check"]) == 1


class TestInlineClass:
    @pytest.mark.parametrize("where", ["a subfolder of the study", "outside the study"])
    def test_the_study_is_found_from_the_module_not_the_working_directory(
        self, study: Path, inline_codelists, where: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _pin(study, NEWER)
        cwd = study / "programs" / "sdtm" if where == "a subfolder of the study" else study.parent
        cwd.mkdir(parents=True, exist_ok=True)
        monkeypatch.chdir(cwd)
        aesev = inline_codelists.AESEV

        messages = _messages(
            lambda: RAW.sdtm.assign("AESEV", source="ae_severity", ct=aesev).to_frame()
        )

        assert (
            f"codelists.py was generated from {PINNED}, but study_config.yaml pins {NEWER}. "
            f"CT checks use the {PINNED} terms. Run: fleet init ct --force"
        ) in messages

    def test_a_class_of_the_pinned_package_does_not_warn(
        self, study: Path, inline_codelists
    ) -> None:
        aesev = inline_codelists.AESEV

        messages = _messages(
            lambda: RAW.sdtm.assign("AESEV", source="ae_severity", ct=aesev).to_frame()
        )

        assert not [m for m in messages if "study_config.yaml pins" in m]


class TestCommands:
    def test_add_ct_refuses_another_package(
        self, study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.chdir(study)

        assert _run(["add-ct", "--domains", "AE", "--package", NEWER]) == 1

        err = capsys.readouterr().err
        assert f"was generated from {PINNED}, not {NEWER}" in err
        assert "fleet init ct --force" in err

    def test_doctor_shows_the_package_or_the_problem(
        self, study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.chdir(study)

        _run(["doctor"])
        assert f"✓ codelists.py ....... {PINNED} (matches study_config)" in capsys.readouterr().out

        _pin(study, NEWER)
        _run(["doctor"])
        assert (
            f"✗ codelists.py ....... codelists.py was generated from {PINNED}"
            in capsys.readouterr().out
        )

    def test_init_ct_marks_the_package_it_generated_from(self, tmp_path: Path) -> None:
        path = tmp_path / "codelists.py"
        _write_codelists(path, (AESEV, PINNED))

        assert read_codelists_file(path).marker == PINNED
        assert f"__ct_package__ = '{PINNED}'" in path.read_text(encoding="utf-8")
