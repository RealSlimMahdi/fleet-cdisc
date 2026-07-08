"""Tests for the ``fleet`` CLI (``fleet.cli``).

All tests are network-free: commands that would hit the CDISC Library or
the rules engine are exercised only through their argument-parsing /
config-discovery / error-handling paths, or with the relevant collaborator
monkeypatched.  The rest run real end-to-end logic against on-disk fixtures
built in ``tmp_path``.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from fleet import cli

# ------------------------------------------------------------------ #
# Fixtures                                                             #
# ------------------------------------------------------------------ #

_SDTM_DEFINE = """\
study:
  id: TESTRUN
  name: TESTRUN
  description: Test study for the CLI suite
  protocol_name: TESTRUN
  originator: Test Co
  standard: SDTMIG
  standard_version: "3.4"
datasets:
  - name: DM
    label: Demographics
    structure: One record per subject
    class: SPECIAL PURPOSE
    keys: [STUDYID, USUBJID]
    inputs:
      - name: dm
        type: dataset
    variables:
      - name: STUDYID
        label: Study Identifier
        type: text
        mandatory: true
        derivation:
          algorithm: hardcode_no_ct
          value: "TESTRUN"
      - name: DOMAIN
        label: Domain Abbreviation
        type: text
        mandatory: true
        derivation:
          algorithm: hardcode_no_ct
          value: "DM"
      - name: USUBJID
        label: Unique Subject Identifier
        type: text
        mandatory: true
        derivation:
          algorithm: assign_no_ct
          source: patient_number
      - name: AGE
        label: Age
        type: integer
        mandatory: false
        derivation:
          algorithm: assign_no_ct
          source: age
"""

_CONFIG = """\
study_id: TESTRUN
company: Test Co
sdtm:
  ig_version: "3-4"
  domains: [DM]
"""


@pytest.fixture
def study(tmp_path: Path) -> Path:
    """A minimal, schema-valid study workspace with a runnable DM define."""
    (tmp_path / "study_config.yaml").write_text(_CONFIG, encoding="utf-8")
    sdtm_dir = tmp_path / "metadata" / "sdtm"
    sdtm_dir.mkdir(parents=True)
    (sdtm_dir / "define.yaml").write_text(_SDTM_DEFINE, encoding="utf-8")
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    pl.DataFrame({"patient_number": ["P1", "P2"], "age": [45, 60]}).write_csv(raw / "dm.csv")
    return tmp_path


@pytest.fixture
def tlg_data(tmp_path: Path) -> tuple[Path, Path]:
    """Synthetic ADSL + ADAE CSVs whose treatment arms align (aet01)."""
    adsl = pl.DataFrame(
        {
            "USUBJID": [f"S{i:03d}" for i in range(1, 9)],
            "TRTA": (["Placebo"] * 4) + (["Drug A"] * 4),
            "SAFFL": ["Y"] * 8,
        }
    )
    adae = pl.DataFrame(
        {
            "USUBJID": ["S001", "S002", "S005", "S006"],
            "TRTA": ["Placebo", "Placebo", "Drug A", "Drug A"],
            "AESER": ["N", "Y", "N", "Y"],
            "AEACN": ["DOSE NOT CHANGED", "DRUG WITHDRAWN", "DOSE NOT CHANGED", "DRUG WITHDRAWN"],
        }
    )
    adsl_path = tmp_path / "adsl.csv"
    adae_path = tmp_path / "adae.csv"
    adsl.write_csv(adsl_path)
    adae.write_csv(adae_path)
    return adsl_path, adae_path


def _run(argv: list[str]) -> int:
    """Invoke ``cli.main`` and return its exit code (0 when it returns)."""
    try:
        cli.main(argv)
    except SystemExit as exc:  # noqa: PERF203
        return int(exc.code or 0)
    return 0


# ------------------------------------------------------------------ #
# --version / usage / exit codes                                      #
# ------------------------------------------------------------------ #


def test_version(capsys: pytest.CaptureFixture) -> None:
    from fleet._version import __version__

    assert _run(["--version"]) == 0
    assert __version__ in capsys.readouterr().out


def test_bare_command_exits_2(capsys: pytest.CaptureFixture) -> None:
    assert _run([]) == 2
    assert "usage: fleet" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["init"], ["tlg"], ["derivation"]])
def test_bare_subcommand_exits_2(argv: list[str], capsys: pytest.CaptureFixture) -> None:
    assert _run(argv) == 2
    assert "error:" in capsys.readouterr().err


def test_unknown_command_exits_2(capsys: pytest.CaptureFixture) -> None:
    assert _run(["frobnicate"]) == 2
    assert "err" in capsys.readouterr().err.lower()


# ------------------------------------------------------------------ #
# Config discovery                                                    #
# ------------------------------------------------------------------ #


def test_find_study_config_walks_parents(study: Path) -> None:
    nested = study / "programs" / "adam"
    nested.mkdir(parents=True)
    found = cli.find_study_config(start=nested)
    assert found == study / "study_config.yaml"


def test_find_study_config_absent(tmp_path: Path) -> None:
    assert cli.find_study_config(start=tmp_path) is None


def test_config_missing_errors_to_stderr(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.chdir(tmp_path)
    code = _run(["check"])
    captured = capsys.readouterr()
    # `check` runs fully but reports the missing config as a FAIL row → exit 1.
    assert code == 1
    assert "study_config.yaml" in (captured.out + captured.err)


def test_run_without_config_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.chdir(tmp_path)
    assert _run(["run"]) == 1
    assert "no study_config.yaml" in capsys.readouterr().err


# ------------------------------------------------------------------ #
# fleet run — happy path                                              #
# ------------------------------------------------------------------ #


def test_run_happy_path(
    study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.chdir(study)
    assert _run(["run", "--format", "parquet"]) == 0
    out = capsys.readouterr().out
    assert "DM (sdtm" in out

    result = pl.read_parquet(study / "data" / "sdtm" / "dm.parquet")
    assert result.columns == ["STUDYID", "DOMAIN", "USUBJID", "AGE"]
    assert result["STUDYID"].to_list() == ["TESTRUN", "TESTRUN"]
    assert result["USUBJID"].to_list() == ["P1", "P2"]


def test_run_out_override(study: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(study)
    out_dir = study / "custom_out"
    assert _run(["run", "--dataset", "DM", "--out", str(out_dir), "--format", "parquet"]) == 0
    assert (out_dir / "dm.parquet").is_file()


def test_run_unknown_dataset_errors(
    study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.chdir(study)
    assert _run(["run", "--dataset", "NOSUCH"]) == 1
    assert "unknown dataset" in capsys.readouterr().err


# ------------------------------------------------------------------ #
# fleet check                                                         #
# ------------------------------------------------------------------ #


def test_check_passes(
    study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    # No custom-rules dir / API key → warnings only, not failures.
    monkeypatch.chdir(study)
    assert _run(["check"]) == 0
    out = capsys.readouterr().out
    assert "study config" in out
    assert "define (sdtm)" in out
    assert "0 failure(s)" in out


def test_check_bad_define_fails(
    study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    # Break the define so JSON-schema validation fails.
    (study / "metadata" / "sdtm" / "define.yaml").write_text(
        "datasets: [{name: DM}]\n", encoding="utf-8"
    )
    monkeypatch.chdir(study)
    assert _run(["check"]) == 1
    assert "FAIL" in capsys.readouterr().out


# ------------------------------------------------------------------ #
# fleet tlg list / schema / run                                      #
# ------------------------------------------------------------------ #


def test_tlg_list(capsys: pytest.CaptureFixture) -> None:
    assert _run(["tlg", "list"]) == 0
    out = capsys.readouterr().out
    assert "aet01" in out
    assert "vst01" in out
    assert "templates." in out


def test_tlg_schema_stdout(capsys: pytest.CaptureFixture) -> None:
    import json

    assert _run(["tlg", "schema", "aet01"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "properties" in payload


def test_tlg_schema_unknown_errors(capsys: pytest.CaptureFixture) -> None:
    assert _run(["tlg", "schema", "does-not-exist"]) == 1
    assert "Unknown template id" in capsys.readouterr().err


def test_tlg_run_happy_path(
    tmp_path: Path, tlg_data: tuple[Path, Path], capsys: pytest.CaptureFixture
) -> None:
    adsl_path, adae_path = tlg_data
    spec = Path("examples/tlg_specs/aet01.yaml").resolve()
    out_dir = tmp_path / "tlg_out"
    code = _run(
        [
            "tlg",
            "run",
            str(spec),
            "--data",
            str(adae_path),
            "--adsl",
            str(adsl_path),
            "-o",
            str(out_dir),
            "--format",
            "html",
        ]
    )
    assert code == 0
    assert (out_dir / "aet01.html").is_file()
    assert "aet01" in capsys.readouterr().out


def test_tlg_run_rtf_format(tmp_path: Path, tlg_data: tuple[Path, Path]) -> None:
    adsl_path, adae_path = tlg_data
    spec = Path("examples/tlg_specs/aet01.yaml").resolve()
    out_dir = tmp_path / "tlg_out"
    code = _run(
        [
            "tlg",
            "run",
            str(spec),
            "--data",
            f"ADAE={adae_path}",
            "--adsl",
            str(adsl_path),
            "-o",
            str(out_dir),
            "--format",
            "rtf",
        ]
    )
    assert code == 0
    assert (out_dir / "aet01.rtf").is_file()


# ------------------------------------------------------------------ #
# fleet tlg export — C9 groupby detection                            #
# ------------------------------------------------------------------ #


def test_tlg_export_groupby_missing_errors(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    # ADAE without any known arm column → clear error listing candidates.
    adae = pl.DataFrame({"USUBJID": ["S001"], "AESER": ["N"], "AEACN": ["DOSE NOT CHANGED"]})
    adsl = pl.DataFrame({"USUBJID": ["S001"], "SAFFL": ["Y"]})
    adae_path = tmp_path / "adae.csv"
    adsl_path = tmp_path / "adsl.csv"
    adae.write_csv(adae_path)
    adsl.write_csv(adsl_path)

    code = _run(
        [
            "tlg",
            "export",
            "--domain",
            "ae",
            "--data",
            str(adae_path),
            "--adsl",
            str(adsl_path),
            "-o",
            str(tmp_path / "x.html"),
        ]
    )
    err = capsys.readouterr().err
    assert code == 1
    assert "auto-detect" in err
    assert "USUBJID" in err  # candidate columns listed


# ------------------------------------------------------------------ #
# Error routing / top-level handler                                  #
# ------------------------------------------------------------------ #


def test_define_xml_missing_spec_errors(capsys: pytest.CaptureFixture) -> None:
    code = _run(["define-xml", "--spec", "nope.yaml", "--output", "out.xml"])
    assert code == 1
    assert "spec file not found" in capsys.readouterr().err


def test_check_rule_missing_file_errors(capsys: pytest.CaptureFixture) -> None:
    code = _run(["check-rule", "nope.yaml"])
    assert code == 1
    assert "not found" in capsys.readouterr().err


def test_fleet_error_reaches_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """A FleetError raised inside a command surfaces as one clean stderr line."""
    from fleet.core.exceptions import SpecError

    def _boom(_args: object) -> None:
        raise SpecError("kaboom in the pipeline")

    monkeypatch.setattr(cli, "_run_tlg_list", _boom)
    code = _run(["tlg", "list"])
    captured = capsys.readouterr()
    assert code == 1
    assert "kaboom in the pipeline" in captured.err
    assert captured.out == ""  # nothing leaked to stdout
