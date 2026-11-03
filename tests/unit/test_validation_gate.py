"""Alpha audit package H, PR 1: the validation gate (c1-261, c1-521, c1-266).

Every CORE finding blocks unless ``validation.accepted`` in the study config
lists its rule, its dataset and a reason (Mahdi, Q1 A).  An engine that
crashes, times out or writes no report could not run (exit 2).  The tests
drive the CLI and the verb with a fake engine behind ``_run_command``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path

import polars as pl
import pytest

import fleet  # noqa: F401
from fleet import cli
from fleet.core.exceptions import ValidationError, ValidationSetupError
from fleet.validation.models import Severity, ValidationIssue, ValidationResult

_SUBJECTS = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ S01-001 │
└─────────┘
""")

_EXECUTED = [{"core_id": "CORE-000001", "status": "SUCCESS"}]


def _finding(rule: str, dataset: str) -> dict:
    return {"core_id": rule, "message": f"{rule} fired", "dataset": dataset}


@dataclass
class FakeEngine:
    """The engine behind ``_run_command``: writes *report*, exits *rc*, or times out."""

    report: dict | None = field(default_factory=lambda: {"Rules_Report": _EXECUTED})
    rc: int = 0
    stderr: str = ""
    timeout_after: bool = False
    calls: list[list[str]] = field(default_factory=list)
    timeouts: list[float] = field(default_factory=list)


@pytest.fixture
def engine(monkeypatch: pytest.MonkeyPatch) -> FakeEngine:
    fake = FakeEngine()

    def run(cmd: list[str], *, cwd: str, timeout: float) -> subprocess.CompletedProcess[str]:
        fake.calls.append(cmd)
        fake.timeouts.append(timeout)
        if fake.timeout_after:
            raise subprocess.TimeoutExpired(cmd, timeout)
        if fake.report is not None:
            out = Path(cmd[cmd.index("-o") + 1]).with_suffix(".json")
            out.write_text(json.dumps(fake.report), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, fake.rc, "", fake.stderr)

    def version(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, "0.15.0\n", "")

    monkeypatch.setattr("fleet.validation.official._run_command", run)
    monkeypatch.setattr("fleet.validation.engine.subprocess.run", version)
    monkeypatch.delenv("FLEET_RULES_ENGINE", raising=False)
    return fake


def _study(root: Path, validation_extra: str = "") -> Path:
    (root / "bin").mkdir()
    (root / "bin" / "core").touch()
    (root / "study_config.yaml").write_text(
        "study_id: S01\nvalidation:\n  engine_path: bin/core\n" + validation_extra,
        encoding="utf-8",
    )
    data_dir = root / "data" / "sdtm"
    data_dir.mkdir(parents=True)
    for name in ("dm", "ae"):
        _SUBJECTS.write_parquet(data_dir / f"{name}.parquet")
    return root


@pytest.fixture
def study(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return _study(tmp_path)


def _run(argv: list[str]) -> int:
    try:
        cli.main(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _report_of(out: str, name: str) -> str:
    return out.split(f"CDISC Validation Report: {name}")[1].split("CDISC Validation Report:")[0]


# ── c1-261: every finding blocks unless accepted (Q1 A) ─────────────────────


class TestFindingsBlock:
    def test_a_finding_with_no_severity_fails_the_dataset(
        self, study: Path, engine: FakeEngine, capsys: pytest.CaptureFixture
    ) -> None:
        engine.report = {
            "Issue_Details": [_finding("CORE-000355", "DM.json")],
            "Rules_Report": _EXECUTED,
        }

        assert _run(["validate"]) == 1

        out = capsys.readouterr().out
        assert "Status: FAIL" in _report_of(out, "DM")
        assert "Status: PASS" in _report_of(out, "AE")

    def test_a_listed_finding_is_accepted_with_its_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: FakeEngine, capsys
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _study(
            tmp_path,
            "  accepted:\n"
            "    - rule: CORE-000355\n"
            "      dataset: DM\n"
            "      reason: COUNTRY not collected, see SDRG 4.1\n",
        )
        engine.report = {
            "Issue_Details": [_finding("CORE-000355", "DM.json")],
            "Rules_Report": _EXECUTED,
        }

        assert _run(["validate"]) == 0

        dm = _report_of(capsys.readouterr().out, "DM")
        assert "Status: FINDINGS (1)" in dm
        assert "COUNTRY not collected, see SDRG 4.1" in dm

    def test_an_acceptance_holds_only_for_its_dataset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: FakeEngine
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _study(
            tmp_path,
            "  accepted:\n    - {rule: CORE-000355, dataset: AE, reason: not collected}\n",
        )
        engine.report = {
            "Issue_Details": [_finding("CORE-000355", "DM.json")],
            "Rules_Report": _EXECUTED,
        }

        assert _run(["validate"]) == 1

    def test_an_acceptance_needs_a_reason(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: FakeEngine, capsys
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _study(tmp_path, "  accepted:\n    - {rule: CORE-000355, dataset: DM, reason: ''}\n")

        assert _run(["validate"]) == 2
        assert "reason" in capsys.readouterr().err

    def test_zero_executed_rules_is_not_assessed(
        self, study: Path, engine: FakeEngine, capsys: pytest.CaptureFixture
    ) -> None:
        engine.report = {"Rules_Report": [{"core_id": "CORE-000001", "status": "SKIPPED"}]}

        assert _run(["validate"]) == 0

        assert "Status: NOT ASSESSED" in capsys.readouterr().out

    def test_the_final_line_counts_each_status_and_the_findings(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: FakeEngine, capsys
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _study(tmp_path, "  accepted:\n    - {rule: CORE-000767, dataset: AE, reason: no RELREC}\n")
        engine.report = {
            "Issue_Details": [
                _finding("CORE-000355", "DM.json"),
                _finding("CORE-000767", "AE.json"),
            ],
            "Rules_Report": _EXECUTED,
        }

        _run(["validate"])

        assert (
            "Validated 2 dataset(s): 0 passed, 1 with accepted findings, 0 not assessed, "
            "1 failed, 0 could not run. Findings: 2 (1 accepted)."
        ) in capsys.readouterr().out

    def test_a_study_level_block_is_not_counted_as_a_dataset(
        self, study: Path, engine: FakeEngine, capsys: pytest.CaptureFixture
    ) -> None:
        engine.report = {
            "Issue_Details": [_finding("CORE-000739", "STUDY")],
            "Rules_Report": _EXECUTED,
        }

        assert _run(["validate"]) == 1

        out = capsys.readouterr().out
        assert "Validated 2 dataset(s) and the study-level rules: 2 passed" in out

    def test_the_verb_raises_on_a_finding(self, study: Path, engine: FakeEngine) -> None:
        engine.report = {
            "Issue_Details": [_finding("CORE-000355", "DM.json")],
            "Rules_Report": _EXECUTED,
        }

        with pytest.raises(ValidationError, match="DM"):
            _SUBJECTS.sdtm.validate("DM", on_fail="raise")

    def test_a_study_finding_does_not_block_a_single_dataset_verb(
        self, study: Path, engine: FakeEngine
    ) -> None:
        engine.report = {
            "Issue_Details": [_finding("CORE-000739", "STUDY")],
            "Rules_Report": _EXECUTED,
        }

        ns = _SUBJECTS.sdtm.validate("DM", on_fail="raise")

        result = ns.last_validation
        assert result is not None
        assert result.status == "PASS"
        assert [i.rule_id for i in result.infos] == ["CORE-000739"]


def test_status_words() -> None:
    def result(**kw: object) -> ValidationResult:
        return ValidationResult("DM", "sdtmig", "3-4", **kw)  # type: ignore[arg-type]

    finding = ValidationIssue(Severity.ERROR, "CORE-000355", "m")
    accepted = ValidationIssue(Severity.WARNING, "CORE-000355", "m", accepted="SDRG")

    assert result(rules_executed=3).status == "PASS"
    assert result(rules_executed=0).status == "NOT ASSESSED"
    assert result(errors=[finding]).status == "FAIL"
    assert result(warnings=[accepted]).status == "FINDINGS (1)"
    assert result(could_not_run="timeout").status == "COULD NOT RUN"
    assert not result(could_not_run="timeout").is_valid


# ── c1-521 / c1-266: an engine that does not finish could not run ──────────


class TestCouldNotRun:
    def test_a_non_zero_exit_is_not_parsed(
        self, study: Path, engine: FakeEngine, capsys: pytest.CaptureFixture
    ) -> None:
        engine.rc = 1
        engine.stderr = "IndexError: list index out of range"
        engine.report = {"Issue_Details": []}

        assert _run(["validate"]) == 2

        out = capsys.readouterr().out
        assert "Status: COULD NOT RUN" in out
        assert "IndexError" in out
        assert (
            "0 passed, 0 with accepted findings, 0 not assessed, 0 failed, 2 could not run" in out
        )

    def test_no_file_could_not_run(self, study: Path, engine: FakeEngine) -> None:
        engine.report = None

        assert _run(["validate"]) == 2

    def test_an_engine_with_no_rules_for_the_standard_is_not_assessed(
        self, study: Path, engine: FakeEngine, capsys: pytest.CaptureFixture
    ) -> None:
        engine.rc = 1
        engine.report = None
        engine.stderr = (
            'Traceback (most recent call last):\n  File "core.py", line 1552, in main\n'
            "ValueError: No rules were selected for this standard/version \u2014 nothing to "
            "execute, aborting before report generation\n"
            "[PYI-15145:ERROR] Failed to execute script 'core' due to unhandled exception!"
        )

        assert _run(["validate"]) == 0

        out = capsys.readouterr().out
        assert "Status: NOT ASSESSED" in out
        assert "No rules were selected" in out

    def test_a_crash_names_the_error_line(
        self, study: Path, engine: FakeEngine, capsys: pytest.CaptureFixture
    ) -> None:
        engine.rc = 1
        engine.report = None
        engine.stderr = (
            "Traceback (most recent call last):\n"
            + '  File "click/core.py", line 910, in invoke\n' * 30
            + "IndexError: list index out of range\n[PYI-1:ERROR] Failed to execute script"
        )

        assert _run(["validate"]) == 2

        assert "IndexError: list index out of range" in capsys.readouterr().out

    def test_a_timeout_could_not_run_and_names_the_setting(
        self, study: Path, engine: FakeEngine, capsys: pytest.CaptureFixture
    ) -> None:
        engine.timeout_after = True

        assert _run(["validate", "--timeout", "45"]) == 2

        out = capsys.readouterr().out
        assert engine.timeouts == [45.0]
        assert "45 s" in out
        assert "validation.timeout" in out

    def test_the_timeout_comes_from_the_study_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine: FakeEngine, capsys
    ) -> None:
        monkeypatch.chdir(tmp_path)
        _study(tmp_path, "  timeout: 900\n")

        _run(["validate"])

        assert engine.timeouts == [900.0]
        assert "Timeout:      900 s (study config)" in capsys.readouterr().out

    def test_the_verb_raises_when_the_engine_could_not_run(
        self, study: Path, engine: FakeEngine
    ) -> None:
        engine.timeout_after = True

        with pytest.raises(ValidationSetupError, match="validation.timeout"):
            _SUBJECTS.sdtm.validate("DM", on_fail="ignore")

    def test_the_command_has_no_raw_report_flag(self, study: Path, engine: FakeEngine) -> None:
        _run(["validate"])

        assert all("-rr" not in cmd for cmd in engine.calls)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
def test_a_timeout_stops_the_engine_workers(tmp_path: Path) -> None:
    from fleet.validation.official import _run_command

    pidfile = tmp_path / "child.pid"
    script = tmp_path / "core"
    script.write_text(f"#!/bin/sh\nsleep 30 &\necho $! > {pidfile}\nwait\n", encoding="utf-8")
    script.chmod(0o755)

    with pytest.raises(subprocess.TimeoutExpired):
        _run_command([str(script)], cwd=str(tmp_path), timeout=3)

    child = int(pidfile.read_text())
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(child, 0)


# ── c1-521: a tested engine version ─────────────────────────────────────────


def test_an_untested_engine_version_is_named_in_the_header(
    study: Path, engine: FakeEngine, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    def version(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 0, "0.17.1\n", "")

    monkeypatch.setattr("fleet.validation.engine.subprocess.run", version)
    (study / "bin" / "core").write_text("x", encoding="utf-8")  # new mtime: no cached version

    _run(["validate"])

    assert (
        "CORE version: 0.17.1 (not tested with Fleet; tested: 0.15.0, 1.0.0)"
        in capsys.readouterr().out
    )


def test_the_default_install_tag_is_a_tested_version() -> None:
    from fleet.validation.engine import DEFAULT_ENGINE_TAG, TESTED_ENGINE_VERSIONS

    assert DEFAULT_ENGINE_TAG in TESTED_ENGINE_VERSIONS.values()


# ── c1-31: assign(ct=, ct_map=) checks the mapped values (Q5 A) ─────────────


class SEX:
    """C66731 as a generated class holds it."""

    _concept_id = "C66731"
    F = "F"
    INTERSEX = "INTERSEX"
    M = "M"
    U = "U"


class UNIT:
    """A class whose term starts with a digit, so its attribute starts with ``_``."""

    _concept_id = "C71620"
    _9_L = "10^9/L"
    mg = "mg"


_RAW_SEX = pl.DataFrame({"sex_raw": ["Male", "Female", "Unknown", None, ""]})


def _ct_warnings(record: list[warnings.WarningMessage]) -> list[str]:
    return [str(w.message) for w in record if "codelist" in str(w.message)]


def test_a_raw_value_outside_the_map_warns_and_is_kept() -> None:
    with pytest.warns(UserWarning, match=r"SEX.*C66731.*\['Unknown'\]") as record:
        out = _RAW_SEX.sdtm.assign(
            "SEX", source="sex_raw", ct=SEX, ct_map={"Male": "M", "Female": "F"}
        ).to_frame()

    assert out["SEX"].to_list() == ["M", "F", "Unknown", None, ""]
    assert "ct_map" in _ct_warnings(record)[0]


def test_a_bad_map_target_warns() -> None:
    with pytest.warns(UserWarning, match="MALE"):
        _RAW_SEX.head(1).sdtm.assign("SEX", source="sex_raw", ct=SEX, ct_map={"Male": "MALE"})


@pytest.mark.parametrize(
    ("frame", "kwargs"),
    [
        (pl.DataFrame({"sex_raw": ["F", "Male"]}), {"ct_map": {"Male": "M"}}),
        (pl.DataFrame({"sex_raw": ["Male", None, ""]}), {"ct_map": {"Male": "M"}}),
        (pl.DataFrame({"sex_raw": ["Male", "N/A"]}), {"ct_map": {"Male": "M", "N/A": None}}),
        (
            pl.DataFrame({"sex_raw": ["Unknown"]}),
            {"ct_map": {"Male": "M"}, "validate_values": False},
        ),
    ],
)
def test_valid_null_or_switched_off_values_stay_silent(frame: pl.DataFrame, kwargs: dict) -> None:
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        frame.sdtm.assign("SEX", source="sex_raw", ct=SEX, **kwargs)

    assert _ct_warnings(record) == []


def test_a_term_that_starts_with_a_digit_is_a_valid_term() -> None:
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        pl.DataFrame({"u": ["G/L"]}).sdtm.assign(
            "LBSTRESU", source="u", ct=UNIT, ct_map={"G/L": "10^9/L"}
        )

    assert _ct_warnings(record) == []


def test_a_map_on_a_codelist_with_no_terms_says_it_is_not_validated() -> None:
    with pytest.warns(UserWarning, match="unvalidated"):
        pl.DataFrame({"x": ["a"]}).sdtm.assign("XX", source="x", ct="C99999", ct_map={"a": "A"})
