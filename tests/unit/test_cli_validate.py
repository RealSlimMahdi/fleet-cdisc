"""``fleet validate``: a sweep built from the run setup, one engine run per standard.

``fleet doctor`` and ``fleet check`` build the same run setup with no datasets.
The tests drive the CLI entry point in a temporary study with a fake engine:
``subprocess.run`` is captured, and the engine path is a plain file.  The fake
engine records the datasets it received and can write a raw report.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl
import pytest

from fleet import cli

_SUBJECTS = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ S01-001 │
└─────────┘
""")

#: What the engine writes when no rule fires: one rule executed, no finding.
_CLEAN_REPORT = {"Issue_Details": [], "Rules_Report": [{"core_id": "X", "status": "SUCCESS"}]}


@dataclass
class FakeEngine:
    """Captured validate calls; *report* is written as the engine's raw JSON report.

    A call with ``-lr`` writes *custom_report* instead.  Other commands
    (``version``, ``validate --help``) are answered and not recorded.
    """

    calls: list[list[str]] = field(default_factory=list)
    datasets: list[list[str]] = field(default_factory=list)
    report: dict | None = None
    custom_report: dict | None = None

    def standards(self) -> list[str]:
        return [cmd[cmd.index("-s") + 1] for cmd in self.calls]


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    fake = FakeEngine()

    def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "validate" not in cmd or "--help" in cmd:
            return subprocess.CompletedProcess(cmd, 0, "0.15.0\n", "")
        fake.calls.append(cmd)
        data_dir = Path(cmd[cmd.index("-d") + 1])
        fake.datasets.append(sorted(p.name for p in data_dir.iterdir()))
        report = fake.custom_report if "-lr" in cmd else fake.report
        out = Path(cmd[cmd.index("-o") + 1]).with_suffix(".json")
        out.write_text(json.dumps(report or _CLEAN_REPORT), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("fleet.validation.official.subprocess.run", run)
    monkeypatch.setattr("fleet.validation.official._run_command", run)
    monkeypatch.delenv("FLEET_RULES_ENGINE", raising=False)
    return fake


@pytest.fixture
def study(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A study with 3 SDTM and 2 ADaM datasets and an engine in its config."""
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "core").touch()
    (tmp_path / "study_config.yaml").write_text(
        "study_id: S01\nvalidation:\n  engine_path: bin/core\n", encoding="utf-8"
    )
    for sub, names in (("sdtm", ("dm", "ae", "vs")), ("adam", ("adsl", "adae"))):
        data_dir = tmp_path / "data" / sub
        data_dir.mkdir(parents=True)
        for name in names:
            _SUBJECTS.write_parquet(data_dir / f"{name}.parquet")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _run(argv: list[str]) -> int:
    try:
        cli.main(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


class TestSweep:
    def test_one_engine_run_per_standard_and_one_result_per_dataset(
        self, study: Path, engine: FakeEngine, capsys: pytest.CaptureFixture
    ) -> None:
        assert _run(["validate"]) == 0

        assert engine.standards() == ["sdtmig", "adamig"]
        assert engine.datasets == [["AE.json", "DM.json", "VS.json"], ["ADAE.json", "ADSL.json"]]
        out = capsys.readouterr().out
        assert out.count("CDISC Validation Report:") == 5
        assert (
            "5 passed, 0 with accepted findings, 0 not assessed, 0 failed, 0 could not run" in out
        )

    def test_the_directory_names_the_standard_in_the_header(
        self, study: Path, engine: FakeEngine, capsys: pytest.CaptureFixture
    ) -> None:
        _run(["validate"])

        out = capsys.readouterr().out
        assert "Standard:     SDTMIG (data directory)" in out
        assert "Standard:     ADaMIG (data directory)" in out
        assert f"Engine:       {study / 'bin' / 'core'} (study config)" in out
        assert "CORE version: 0.15.0" in out
        assert f"Study config: {study / 'study_config.yaml'}" in out

    def test_findings_are_split_to_their_dataset(
        self, study: Path, engine: FakeEngine, capsys: pytest.CaptureFixture
    ) -> None:
        engine.report = {
            "Issue_Details": [
                {
                    "core_id": "CORE-000001",
                    "message": "AESTDTC after AEENDTC",
                    "dataset": "ae.json",
                }
            ]
        }

        assert _run(["validate", "data/sdtm"]) == 1

        out = capsys.readouterr().out
        ae_report = out.split("CDISC Validation Report: AE")[1].split("CDISC Validation Report:")[0]
        assert "CORE-000001" in ae_report
        assert "2 passed, 0 with accepted findings, 0 not assessed, 1 failed" in out

    def test_directory_and_name_conflict_could_not_run_and_others_run(
        self, study: Path, engine: FakeEngine, capsys: pytest.CaptureFixture
    ) -> None:
        _SUBJECTS.write_parquet(study / "data" / "sdtm" / "adsl.parquet")

        assert _run(["validate"]) == 2

        captured = capsys.readouterr()
        assert "standard unclear" in captured.err
        assert "--standard" in captured.err
        assert captured.out.count("CDISC Validation Report:") == 5
        assert "1 could not run" in captured.out

    def test_unsupported_version_could_not_run_with_the_supported_list(
        self, study: Path, engine: FakeEngine, capsys: pytest.CaptureFixture
    ) -> None:
        assert _run(["validate", "data/sdtm", "--version", "3.1.3"]) == 2

        assert "3.2, 3.3, 3.4" in capsys.readouterr().err
        assert engine.calls == []

    def test_html_report_lists_could_not_run(
        self, study: Path, engine: FakeEngine, tmp_path: Path
    ) -> None:
        _SUBJECTS.write_parquet(study / "data" / "sdtm" / "adsl.parquet")
        report = tmp_path / "report.html"

        _run(["validate", "--report", str(report)])

        assert "Could not run" in report.read_text(encoding="utf-8")


class TestExplicitPaths:
    @pytest.fixture
    def adtte(self, study: Path) -> Path:
        outputs = study / "outputs"
        outputs.mkdir()
        _SUBJECTS.write_parquet(outputs / "adtte.parquet")
        return outputs / "adtte.parquet"

    def test_ad_prefix_names_adam(
        self, adtte: Path, engine: FakeEngine, capsys: pytest.CaptureFixture
    ) -> None:
        assert _run(["validate", str(adtte)]) == 0

        assert engine.standards() == ["adamig"]
        assert "ADaMIG (dataset name)" in capsys.readouterr().out

    def test_standard_flag_forces_sdtm(
        self, adtte: Path, engine: FakeEngine, capsys: pytest.CaptureFixture
    ) -> None:
        assert _run(["validate", str(adtte), "--standard", "sdtm"]) == 0

        assert engine.standards() == ["sdtmig"]
        assert "SDTMIG (argument)" in capsys.readouterr().out


def test_no_paths_outside_a_study_could_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: FakeEngine
) -> None:
    monkeypatch.chdir(tmp_path)

    assert _run(["validate"]) == 2
    assert engine.calls == []


def _finding(rule: str, dataset: str) -> dict:
    return {"core_id": rule, "message": f"{rule} fired", "dataset": dataset}


class TestCustomRules:
    """CORE runs only the ``-lr`` rules when given, so custom rules get their own run."""

    @pytest.fixture
    def rules_study(self, study: Path) -> Path:
        (study / "rules").mkdir()
        (study / "study_config.yaml").write_text(
            "study_id: S01\nvalidation:\n  engine_path: bin/core\n  custom_rules: rules\n",
            encoding="utf-8",
        )
        return study

    def test_one_dataset_makes_an_official_and_a_custom_run(
        self, rules_study: Path, engine: FakeEngine
    ) -> None:
        assert _run(["validate", "data/sdtm/ae.parquet"]) == 0

        official, custom = engine.calls
        assert "-lr" not in official
        assert Path(custom[custom.index("-lr") + 1]) == (rules_study / "rules").resolve()

    def test_findings_of_both_runs_join_in_one_report_with_their_source(
        self, rules_study: Path, engine: FakeEngine, capsys: pytest.CaptureFixture
    ) -> None:
        engine.report = {"Issue_Details": [_finding("CORE-000001", "ae.json")]}
        engine.custom_report = {"Issue_Details": [_finding("FLEET-AE-001", "ae.json")]}
        report = rules_study / "report.html"

        assert _run(["validate", "data/sdtm/ae.parquet", "--report", str(report)]) == 1

        out = capsys.readouterr().out
        assert out.count("CDISC Validation Report: AE") == 1
        assert "[CORE-000001] (official)" in out
        assert "[FLEET-AE-001] (custom)" in out
        html = report.read_text(encoding="utf-8")
        assert "<td>FLEET-AE-001</td><td>custom</td>" in html
        assert "CORE version: 0.15.0" in html

    def test_a_sweep_of_both_standards_makes_four_runs(
        self, rules_study: Path, engine: FakeEngine, capsys: pytest.CaptureFixture
    ) -> None:
        assert _run(["validate"]) == 0

        assert engine.standards() == ["sdtmig", "sdtmig", "adamig", "adamig"]
        assert ["-lr" in cmd for cmd in engine.calls] == [False, True, False, True]
        out = capsys.readouterr().out
        assert out.count("CDISC Validation Report:") == 5
        assert (
            "5 passed, 0 with accepted findings, 0 not assessed, 0 failed, 0 could not run" in out
        )

    def test_without_custom_rules_one_run_per_standard(
        self, study: Path, engine: FakeEngine
    ) -> None:
        _run(["validate"])

        assert len(engine.calls) == 2
        assert not any("-lr" in cmd for cmd in engine.calls)


def test_doctor_prints_the_engine_of_the_run_setup(
    study: Path, engine: FakeEngine, capsys: pytest.CaptureFixture
) -> None:
    _run(["doctor"])

    out = capsys.readouterr().out
    assert f"{study / 'bin' / 'core'} (study config)" in out
    assert "version: 0.15.0" in out


def test_doctor_still_prints_the_engine_when_the_run_setup_is_refused(
    study: Path, engine: FakeEngine, capsys: pytest.CaptureFixture
) -> None:
    (study / "study_config.yaml").write_text(
        "study_id: S01\nvalidation:\n  engine_path: bin/core\n  custom_rules: nowhere\n",
        encoding="utf-8",
    )

    _run(["doctor"])

    out = capsys.readouterr().out
    assert "run setup" in out
    assert "nowhere" in out
    assert str(study / "bin" / "core") in out


class TestCheck:
    """``fleet check`` builds a run setup with no datasets and gates on its refusals."""

    def _config(self, study: Path, body: str) -> None:
        (study / "study_config.yaml").write_text(
            f"study_id: S01\nvalidation:\n  engine_path: bin/core\n{body}", encoding="utf-8"
        )

    def test_a_valid_setup_passes_with_the_engine_of_the_run_setup(
        self, study: Path, engine: FakeEngine, capsys: pytest.CaptureFixture
    ) -> None:
        assert _run(["check"]) == 0

        out = capsys.readouterr().out
        assert "SDTMIG 3.4 (default)" in out
        assert "ADaMIG 1.3 (default)" in out
        assert f"{study / 'bin' / 'core'} (study config)" in out

    def test_unsupported_ig_version_fails(
        self, study: Path, engine: FakeEngine, capsys: pytest.CaptureFixture
    ) -> None:
        self._config(study, "sdtm:\n  ig_version: 3-5\n")

        assert _run(["check"]) == 1

        out = capsys.readouterr().out
        assert "[FAIL] run setup" in out
        assert "SDTMIG 3-5" in out
        assert "3.2, 3.3, 3.4" in out

    def test_missing_custom_rules_directory_fails_once(
        self, study: Path, engine: FakeEngine, capsys: pytest.CaptureFixture
    ) -> None:
        self._config(study, "  custom_rules: nowhere\n")

        assert _run(["check"]) == 1

        out = capsys.readouterr().out
        assert out.count("nowhere") == 1
        assert "1 failure(s)" in out

    def test_missing_engine_warns_and_does_not_fail(
        self,
        study: Path,
        engine: FakeEngine,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        (study / "bin" / "core").unlink()
        monkeypatch.setattr("fleet.validation.engine.ENGINE_DIR", study / "no-engine")

        assert _run(["check"]) == 0

        out = capsys.readouterr().out
        assert "[WARN] rules engine" in out
        assert "0 failure(s)" in out
