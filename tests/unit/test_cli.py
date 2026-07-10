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
    pl.from_repr("""\
┌────────────────┬─────┐
│ patient_number ┆ age │
│ ---            ┆ --- │
│ str            ┆ i64 │
╞════════════════╪═════╡
│ P1             ┆ 45  │
│ P2             ┆ 60  │
└────────────────┴─────┘
""").write_csv(raw / "dm.csv")
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
    adae = pl.from_repr("""\
┌─────────┬─────────┬───────┬──────────────────┐
│ USUBJID ┆ TRTA    ┆ AESER ┆ AEACN            │
│ ---     ┆ ---     ┆ ---   ┆ ---              │
│ str     ┆ str     ┆ str   ┆ str              │
╞═════════╪═════════╪═══════╪══════════════════╡
│ S001    ┆ Placebo ┆ N     ┆ DOSE NOT CHANGED │
│ S002    ┆ Placebo ┆ Y     ┆ DRUG WITHDRAWN   │
│ S005    ┆ Drug A  ┆ N     ┆ DOSE NOT CHANGED │
│ S006    ┆ Drug A  ┆ Y     ┆ DRUG WITHDRAWN   │
└─────────┴─────────┴───────┴──────────────────┘
""")
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
# fleet tlg explore — static variant explorer                        #
# ------------------------------------------------------------------ #


def test_tlg_explore_happy_path(
    tmp_path: Path, tlg_data: tuple[Path, Path], capsys: pytest.CaptureFixture
) -> None:
    """The shipped aet01 spec (8 declared variants) renders one HTML file."""
    adsl_path, adae_path = tlg_data
    spec = Path("examples/tlg_specs/aet01.yaml").resolve()
    out = tmp_path / "explorer.html"
    code = _run(
        [
            "tlg",
            "explore",
            str(spec),
            "--data",
            str(adae_path),
            "--adsl",
            str(adsl_path),
            "-o",
            str(out),
        ]
    )
    assert code == 0
    assert "8 variant(s)" in capsys.readouterr().out
    html = out.read_text(encoding="utf-8")
    assert html.count('class="fleet-variant"') == 8
    assert "Download ARD (JSON)" in html
    assert "Show definition (spec YAML)" in html


def test_tlg_explore_default_matches_tlg_run_output(
    tmp_path: Path, tlg_data: tuple[Path, Path]
) -> None:
    """Anti-drift, CLI edition: `tlg run`'s HTML is embedded byte-identical
    as the explorer's default variant fragment."""
    adsl_path, adae_path = tlg_data
    spec = Path("examples/tlg_specs/aet01.yaml").resolve()
    run_dir = tmp_path / "run"
    out = tmp_path / "explorer.html"
    common = ["--data", str(adae_path), "--adsl", str(adsl_path)]
    assert _run(["tlg", "run", str(spec), *common, "-o", str(run_dir)]) == 0
    assert _run(["tlg", "explore", str(spec), *common, "-o", str(out)]) == 0

    batch_html = (run_dir / "aet01.html").read_text(encoding="utf-8")
    explorer_html = out.read_text(encoding="utf-8")
    assert f'id="var-aet01-v0">\n{batch_html}' in explorer_html


def test_tlg_explore_missing_data_errors(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    spec = Path("examples/tlg_specs/aet01.yaml").resolve()
    code = _run(["tlg", "explore", str(spec), "-o", str(tmp_path / "x.html")])
    assert code == 1
    assert "needs the ADAE dataset" in capsys.readouterr().err


# ------------------------------------------------------------------ #
# fleet tlg export — C9 groupby detection                            #
# ------------------------------------------------------------------ #


def test_tlg_export_groupby_missing_errors(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    # ADAE without any known arm column → clear error listing candidates.
    adae = pl.from_repr("""\
┌─────────┬───────┬──────────────────┐
│ USUBJID ┆ AESER ┆ AEACN            │
│ ---     ┆ ---   ┆ ---              │
│ str     ┆ str   ┆ str              │
╞═════════╪═══════╪══════════════════╡
│ S001    ┆ N     ┆ DOSE NOT CHANGED │
└─────────┴───────┴──────────────────┘
""")
    adsl = pl.from_repr("""\
┌─────────┬───────┐
│ USUBJID ┆ SAFFL │
│ ---     ┆ ---   │
│ str     ┆ str   │
╞═════════╪═══════╡
│ S001    ┆ Y     │
└─────────┴───────┘
""")
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


# ------------------------------------------------------------------ #
# fleet tdd — everything resolves through study_config.yaml            #
# ------------------------------------------------------------------ #

_TRIAL_DESIGN = """\
trial_design:
  study_id: TESTRUN
  elements:
    - {etcd: SCRN, element: Screening, tedur: P14D, epoch: SCREENING,
       testrl: INFORMED CONSENT}
    - {etcd: TRT, element: Treatment, tedur: P84D, epoch: TREATMENT,
       testrl: RANDOMIZATION}
  arms:
    A1: [SCRN, TRT]
  parameters:
    - {tsparmcd: TITLE, tsparm: Trial Title, tsval: Demo}
    - {tsparmcd: SSTDTC, tsparm: Study Start Date, tsval: 2026-01-01}
"""


def test_tdd_build_resolves_paths_from_config(
    study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """From a nested subdir, the design is read from the config's metadata_sdtm
    dir and datasets land in the config's sdtm_data dir — never the cwd."""
    (study / "metadata" / "sdtm" / "trial_design.yaml").write_text(_TRIAL_DESIGN, encoding="utf-8")
    nested = study / "programs" / "tdd"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    code = _run(["tdd", "build", "--force"])  # --force: TS FDA profile is incomplete
    assert code == 0
    assert (study / "data" / "sdtm" / "te.parquet").exists()
    assert (study / "data" / "sdtm" / "ta.parquet").exists()
    assert not list(nested.iterdir())  # nothing written to the cwd


def test_tdd_audit_accepts_unquoted_yaml_dates(
    study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """YAML parses `2026-01-01` as datetime.date — must coerce to string."""
    (study / "metadata" / "sdtm" / "trial_design.yaml").write_text(_TRIAL_DESIGN, encoding="utf-8")
    monkeypatch.chdir(study)

    code = _run(["tdd", "audit"])
    err = capsys.readouterr().err
    assert code == 1  # TS FDA profile findings — expected
    assert "SD2232" not in err  # SSTDTC present (the date row survived)
    assert "SD2214" in err  # TPHASE genuinely missing
    assert "Traceback" not in err


def test_tdd_build_missing_design_errors_cleanly(
    study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.chdir(study)
    code = _run(["tdd", "build"])
    err = capsys.readouterr().err
    assert code == 1
    assert "trial design spec not found" in err
    assert str(study / "metadata" / "sdtm" / "trial_design.yaml") in err


# ------------------------------------------------------------------ #
# config-context defaults — validate / define-xml / tlg                #
# ------------------------------------------------------------------ #


class _StubValidationResult:
    def __init__(self, name: str) -> None:
        self.dataset_name = name
        self.errors: list = []
        self.warnings: list = []
        self.infos: list = []

    def print_report(self) -> None:
        pass


def test_validate_defaults_resolve_from_config(
    study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Bare `fleet validate`: datasets from the config's data dirs, custom
    CORE rules from validation.custom_rules, IG version from sdtm.ig_version."""
    import fleet.validation
    import fleet.validation.engine

    sdtm_dir = study / "data" / "sdtm"
    sdtm_dir.mkdir(parents=True)
    pl.DataFrame({"USUBJID": ["1"]}).write_parquet(sdtm_dir / "dm.parquet")
    rules_dir = study / "metadata" / "custom_rules"
    rules_dir.mkdir(parents=True)
    (study / "study_config.yaml").write_text(
        _CONFIG + "validation:\n  custom_rules: metadata/custom_rules\n",
        encoding="utf-8",
    )

    calls: list[dict] = []

    class _StubService:
        def __init__(self, rules_engine_path: object) -> None:
            pass

        def validate_sdtm(self, df: object, name: str, **kwargs: object) -> _StubValidationResult:
            calls.append({"name": name, **kwargs})
            return _StubValidationResult(name)

        validate_adam = validate_sdtm

    monkeypatch.setattr(fleet.validation, "ValidationService", _StubService)
    monkeypatch.setattr(fleet.validation.engine, "discover_engine", lambda root: Path("/fake"))

    nested = study / "programs" / "qc"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    assert _run(["validate"]) == 0
    assert calls and calls[0]["name"] == "DM"
    assert calls[0]["custom_rules"] == str(rules_dir)
    assert calls[0]["version"] == "3.4"  # config ig_version "3-4" → "3.4"


def test_define_xml_defaults_from_config(
    study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Bare `fleet define-xml`: spec from metadata_sdtm, output to define_xml dir."""
    nested = study / "programs" / "meta"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    code = _run(["define-xml"])
    assert code == 0
    assert (study / "metadata" / "define_sdtm.xml").is_file()
    assert not list(nested.iterdir())  # nothing written to the cwd


def test_tlg_run_defaults_from_config(
    study: Path,
    tlg_data: tuple[Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """`fleet tlg run <spec>` with no data/output flags: datasets found in the
    config's adam_data dir, output written to the config's outputs dir."""
    import shutil

    adsl_path, adae_path = tlg_data
    spec = Path("examples/tlg_specs/aet01.yaml").resolve()
    adam_dir = study / "data" / "adam"
    adam_dir.mkdir(parents=True)
    shutil.copy(adae_path, adam_dir / "adae.csv")
    shutil.copy(adsl_path, adam_dir / "adsl.csv")

    nested = study / "programs" / "tlg"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    code = _run(["tlg", "run", str(spec), "--format", "html"])
    assert code == 0
    assert (study / "outputs" / "aet01.html").is_file()
    assert not list(nested.iterdir())  # nothing written to the cwd
