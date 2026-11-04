"""Tests for the ``fleet`` CLI (``fleet.cli``).

All tests are network-free: commands that would hit the CDISC Library or
the rules engine are exercised only through their argument-parsing /
config-discovery / error-handling paths, or with the relevant collaborator
monkeypatched.  The rest run real end-to-end logic against on-disk fixtures
built in ``tmp_path``.
"""

from __future__ import annotations

import json
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
      - name: dm_raw
        type: raw
        path: data/raw/dm.csv
    variables:
      - name: STUDYID
        label: Study Identifier
        type: text
        length: 7
        mandatory: true
        derivation:
          algorithm: assign
          value: "TESTRUN"
      - name: DOMAIN
        label: Domain Abbreviation
        type: text
        length: 2
        mandatory: true
        derivation:
          algorithm: assign
          value: "DM"
      - name: USUBJID
        label: Unique Subject Identifier
        type: text
        length: 20
        mandatory: true
        derivation:
          algorithm: assign
          source: patient_number
      - name: AGE
        label: Age
        type: integer
        length: 3
        mandatory: false
        derivation:
          algorithm: assign
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


@pytest.mark.parametrize("argv", [["--help"], ["doctor"], ["check"]])
def test_a_cp1252_stdout_prints_glyphs_escaped_not_a_traceback(
    argv: list[str], tmp_path: Path
) -> None:
    """c1-314: a Windows pipe or redirect is cp1252; a check mark must not crash."""
    import os
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-c", "from fleet.cli import main; main()", *argv],
        cwd=tmp_path,
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        capture_output=True,
        encoding="cp1252",
        errors="replace",
        timeout=120,
        check=False,
    )

    assert "Traceback" not in result.stderr
    assert "UnicodeEncodeError" not in result.stderr
    if argv == ["doctor"]:
        assert "\\u2713" in result.stdout or "\\u2717" in result.stdout


# ------------------------------------------------------------------ #
# Config discovery                                                    #
# ------------------------------------------------------------------ #


def test_find_study_config_walks_parents(study: Path) -> None:
    from fleet.core.study_context import find_study_config

    nested = study / "programs" / "adam"
    nested.mkdir(parents=True)
    found = find_study_config(start=nested)
    assert found == study / "study_config.yaml"


def test_find_study_config_absent(tmp_path: Path) -> None:
    from fleet.core.study_context import find_study_config

    assert find_study_config(start=tmp_path) is None


def test_init_cfg_writes_both_ig_versions(tmp_path: Path) -> None:
    import yaml

    assert _run(["init", "cfg", "--study-id", "S01", "--root", str(tmp_path)]) == 0

    written = yaml.safe_load((tmp_path / "study_config.yaml").read_text(encoding="utf-8"))
    assert written["sdtm"]["ig_version"] == "3-4"
    assert written["adam"]["ig_version"] == "1-3"


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


def test_run_prints_the_plan_before_the_first_dataset_builds(
    study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.chdir(study)
    assert _run(["run"]) == 0
    out = capsys.readouterr().out
    assert out.index("Plan:    1 dataset(s)") < out.index("[1/1] DM (sdtm, define.yaml)")
    assert out.index("[1/1] DM (sdtm, define.yaml)") < out.index("[1/1] DM: 2 rows")


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


def test_run_reads_the_source_of_a_define_text_variable_as_text(
    study: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """USUBJID is type text: raw 1.10 stays 1.10, not the number 1.1."""
    (study / "data" / "raw" / "dm.csv").write_text(
        "patient_number,age\n1.10,45\n2.50,60\n", encoding="utf-8"
    )
    monkeypatch.chdir(study)

    assert _run(["run", "--format", "parquet"]) == 0

    dm = pl.read_parquet(study / "data" / "sdtm" / "dm.parquet")
    assert dm["USUBJID"].to_list() == ["1.10", "2.50"]
    assert dm["AGE"].to_list() == [45, 60]


def test_run_xpt_writes_v5_with_the_define_labels(
    study: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pyreadstat = pytest.importorskip("pyreadstat")
    monkeypatch.chdir(study)

    assert _run(["run", "--format", "xpt"]) == 0

    _, meta = pyreadstat.read_xport(str(study / "data" / "sdtm" / "dm.xpt"), metadataonly=True)
    assert meta.table_name == "DM"
    assert meta.file_label == "Demographics"
    assert meta.column_names_to_labels["USUBJID"] == "Unique Subject Identifier"


def test_run_dataset_json_writes_the_define_labels_and_oids(
    study: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """c1-576: the Dataset-JSON of fleet run carries the define metadata."""
    monkeypatch.chdir(study)

    assert _run(["run", "--format", "dataset-json"]) == 0

    payload = json.loads((study / "data" / "sdtm" / "dm.json").read_text(encoding="utf-8"))
    cols = {c["name"]: c for c in payload["columns"]}
    assert payload["label"] == "Demographics"
    assert payload["studyOID"] == "STDY.TESTRUN"
    assert payload["metaDataVersionOID"] == "MDV.TESTRUN.1.SDTMIG.3.4"
    assert cols["USUBJID"] == {
        "itemOID": "IT.USUBJID",
        "name": "USUBJID",
        "label": "Unique Subject Identifier",
        "dataType": "string",
        "length": 20,
        "keySequence": 2,
    }
    assert cols["AGE"]["itemOID"] == "IT.AGE"


def test_run_prints_each_input_with_its_file(
    study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """c1-286: the log names the file each input came from."""
    monkeypatch.chdir(study)

    assert _run(["run"]) == 0

    assert f"    input dm_raw -> {study / 'data' / 'raw' / 'dm.csv'}" in capsys.readouterr().out


def test_run_writes_the_format_the_define_declares(
    study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """c1-287: with no --format, output_format: drives the file, as it drives the leaf href."""
    pytest.importorskip("pyreadstat")
    define = study / "metadata" / "sdtm" / "define.yaml"
    define.write_text("output_format: xpt\n" + _SDTM_DEFINE, encoding="utf-8")
    monkeypatch.chdir(study)

    assert _run(["run"]) == 0

    assert (study / "data" / "sdtm" / "dm.xpt").is_file()
    assert not (study / "data" / "sdtm" / "dm.parquet").exists()
    assert "Format:  DM xpt" in capsys.readouterr().out


def test_run_warns_when_the_format_flag_differs_from_the_define(
    study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    define = study / "metadata" / "sdtm" / "define.yaml"
    define.write_text("output_format: xpt\n" + _SDTM_DEFINE, encoding="utf-8")
    monkeypatch.chdir(study)

    assert _run(["run", "--format", "parquet"]) == 0

    assert "--format parquet overrides output_format: xpt" in capsys.readouterr().err


def test_define_xml_warns_when_a_leaf_names_no_file(
    study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """c1-287: the leaf href must name a file the data folder holds."""
    monkeypatch.chdir(study)

    assert _run(["define-xml", "--standard", "sdtm", "--no-preview"]) == 0

    assert "no file in" in capsys.readouterr().err

    assert _run(["run"]) == 0
    capsys.readouterr()
    assert _run(["define-xml", "--standard", "sdtm", "--no-preview"]) == 0
    assert "no file in" not in capsys.readouterr().err


def test_checker_write_xpt_carries_the_define_labels(study: Path) -> None:
    pyreadstat = pytest.importorskip("pyreadstat")
    from fleet.define_xml import DatasetChecker

    checker = DatasetChecker(study / "metadata" / "sdtm" / "define.yaml")
    dm = pl.DataFrame({"USUBJID": ["P1"], "STUDYID": ["TESTRUN"], "_TMP": [1]})

    path = checker.write_xpt(dm, dataset="DM", path=study / "out" / "dm.xpt")

    _, meta = pyreadstat.read_xport(str(path), metadataonly=True)
    assert meta.column_names == ["STUDYID", "USUBJID"]
    assert meta.file_label == "Demographics"
    assert meta.column_names_to_labels["STUDYID"] == "Study Identifier"


def test_checker_write_xpt_refuses_a_file_named_after_another_dataset(study: Path) -> None:
    from fleet.core.exceptions import IOError as FleetIOError
    from fleet.define_xml import DatasetChecker

    checker = DatasetChecker(study / "metadata" / "sdtm" / "define.yaml")

    with pytest.raises(FleetIOError, match="dm.xpt"):
        checker.write_xpt(pl.DataFrame({"USUBJID": ["P1"]}), dataset="DM", path=study / "ae.xpt")


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


def test_define_xml_enriches_project_local_callable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`fleet define-xml --enrich-methods` resolves a project-local callable.

    Regression guard for the bare-``fleet`` console script. Unlike
    ``python -m fleet.cli``, the console-script wrapper does not put the
    current working directory on ``sys.path``, so a spec whose
    ``derivations_module`` is a project-local module (e.g.
    ``fixtures.derivations``) failed to import — and the study's own
    ``callable:`` MethodDef was dropped.

    ``main()`` now appends the cwd to ``sys.path``. This test runs the CLI
    from a project directory whose derivations module is importable *only*
    via the cwd, and asserts the callable's docstring reaches the MethodDef.
    It fails without the fix (the import raises ``SpecError`` → exit 1).
    """
    import sys
    import textwrap
    import xml.etree.ElementTree as ET

    odm = "{http://www.cdisc.org/ns/odm/v1.3}"

    project = tmp_path / "study"
    (project / "house").mkdir(parents=True)
    (project / "house" / "__init__.py").write_text("", encoding="utf-8")
    (project / "house" / "derivations.py").write_text(
        textwrap.dedent(
            '''
            import polars as pl

            from fleet.core.derivation import derivation


            @derivation
            def SAFFL_house() -> pl.Expr:
                """Safety population flag: 'Y' for treated subjects."""
                return pl.lit("Y").alias("SAFFL")
            '''
        ),
        encoding="utf-8",
    )

    spec = """\
study:
  id: HOUSE
  name: House Study
  description: CLI project-local callable regression
  protocol_name: HOUSE
  originator: House Co
  standard: ADAMIG
  standard_version: "1.1"
  ct_version: "2023-12-15"
derivations_module: house.derivations
datasets:
  - name: ADSL
    label: Subject-Level Analysis
    structure: One record per subject
    class: SUBJECT LEVEL ANALYSIS DATASET
    keys: [STUDYID, USUBJID]
    inputs:
      - name: adsl_in
        type: dataset
    variables:
      - name: STUDYID
        label: Study Identifier
        type: text
        mandatory: true
        derivation:
          algorithm: assign
          value: HOUSE
      - name: USUBJID
        label: Unique Subject Identifier
        type: text
        mandatory: true
        derivation:
          algorithm: assign
          source: usubjid
      - name: SAFFL
        label: Safety Population Flag
        type: text
        derivation:
          algorithm: derivation
          callable: SAFFL_house
"""
    (project / "define.yaml").write_text(spec, encoding="utf-8")

    # Precondition: the project-local module is not importable from the
    # current sys.path — only main()'s cwd insert can make it resolvable.
    assert "house.derivations" not in sys.modules
    monkeypatch.chdir(project)

    code = _run(
        [
            "define-xml",
            "--spec",
            "define.yaml",
            "--output",
            "define.xml",
            "--no-preview",
            "--enrich-methods",
        ]
    )
    assert code == 0, "CLI could not import the project-local derivations_module"

    root = ET.fromstring((project / "define.xml").read_text(encoding="utf-8"))
    methods = {m.get("OID"): m for m in root.iter(f"{odm}MethodDef") if m.get("OID") is not None}
    assert "MT.ADSL.SAFFL" in methods
    translated = methods["MT.ADSL.SAFFL"].find(f"{odm}Description/{odm}TranslatedText")
    assert translated is not None
    assert translated.text == "Safety population flag: 'Y' for treated subjects."


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


def test_tdd_build_xpt_carries_the_ig_labels(study: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pyreadstat = pytest.importorskip("pyreadstat")
    (study / "metadata" / "sdtm" / "trial_design.yaml").write_text(_TRIAL_DESIGN, encoding="utf-8")
    monkeypatch.chdir(study)

    assert _run(["tdd", "build", "--force", "--format", "xpt"]) == 0

    _, meta = pyreadstat.read_xport(str(study / "data" / "sdtm" / "te.xpt"), metadataonly=True)
    assert meta.table_name == "TE"
    assert meta.file_label == "Trial Elements"
    assert meta.column_names_to_labels["ETCD"] == "Element Code"


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


def test_tdd_ctgov_write_merges_into_design(
    study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """`fleet tdd ctgov --write`: new (TSPARMCD, TSSEQ) rows merge into the
    config-resolved trial_design.yaml; existing rows are untouched."""
    import yaml

    from fleet.sdtm.tdd import TrialParameter, TrialParameters

    (study / "metadata" / "sdtm" / "trial_design.yaml").write_text(_TRIAL_DESIGN, encoding="utf-8")
    seeded = TrialParameters(
        parameters=[
            TrialParameter(tsparmcd="TITLE", tsparm="Trial Title", tsval="From Registry"),
            TrialParameter(tsparmcd="REGID", tsparm="Registry Identifier", tsval="NCT00000001"),
        ]
    )
    monkeypatch.setattr(
        TrialParameters, "from_ctgov", classmethod(lambda cls, nct_id, **kw: seeded)
    )

    nested = study / "programs" / "tdd"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)

    assert _run(["tdd", "ctgov", "NCT00000001", "--write"]) == 0
    assert "1 parameter(s)" in capsys.readouterr().out  # REGID added, TITLE kept

    data = yaml.safe_load(
        (study / "metadata" / "sdtm" / "trial_design.yaml").read_text(encoding="utf-8")
    )
    params = data["trial_design"]["parameters"]
    by_code = {p["tsparmcd"]: p["tsval"] for p in params}
    assert by_code["REGID"] == "NCT00000001"
    assert by_code["TITLE"] == "Demo"  # pre-existing row wins over registry


def test_tdd_ctgov_prints_yaml(
    study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    import yaml

    from fleet.sdtm.tdd import TrialParameter, TrialParameters

    seeded = TrialParameters(
        parameters=[TrialParameter(tsparmcd="REGID", tsparm="Registry Identifier", tsval="NCT1")]
    )
    monkeypatch.setattr(
        TrialParameters, "from_ctgov", classmethod(lambda cls, nct_id, **kw: seeded)
    )
    monkeypatch.chdir(study)

    assert _run(["tdd", "ctgov", "NCT1"]) == 0
    printed = yaml.safe_load(capsys.readouterr().out)
    assert printed["parameters"][0]["tsparmcd"] == "REGID"


def test_add_acrf_updates_define_yaml(
    study: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """`fleet add-acrf` injects study.documents.annotated_crf, preserving the
    leading comment header of the define.yaml."""
    import yaml

    spec_path = study / "metadata" / "sdtm" / "define.yaml"
    spec_path.write_text("# schema-hint comment\n" + spec_path.read_text(), encoding="utf-8")
    monkeypatch.chdir(study)

    assert _run(["add-acrf", "--href", "blankcrf.pdf", "--page-map", "acrf_pages.yaml"]) == 0

    text = spec_path.read_text(encoding="utf-8")
    assert text.startswith("# schema-hint comment")
    data = yaml.safe_load(text)
    acrf = data["study"]["documents"]["annotated_crf"]
    assert acrf["href"] == "blankcrf.pdf"
    assert acrf["title"] == "Annotated Case Report Form"
    assert acrf["page_map"] == "acrf_pages.yaml"


# ------------------------------------------------------------------ #
# Optional-extra guards (fleet lsp / fleet mcp)                        #
# ------------------------------------------------------------------ #


class TestRequireExtra:
    """`_require_extra` guards the dotted module the server really imports.

    A distribution that is present but too old to expose that module has
    to fail here, with the install hint, rather than as a bare
    ModuleNotFoundError raised from inside the server.
    """

    def test_present_module_passes(self) -> None:
        cli._require_extra("json.decoder", "lsp", "lsp")

    def test_missing_distribution_names_the_extra(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        monkeypatch.setattr(cli.importlib.util, "find_spec", lambda name: None)

        with pytest.raises(SystemExit) as exc:
            cli._require_extra("pygls.lsp.server", "lsp", "lsp")

        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "pygls is required for `fleet lsp`" in err
        assert "uv pip install 'fleet-cdisc[lsp]'" in err

    def test_too_old_distribution_reports_the_version_it_found(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        """pygls 1.x has no ``pygls.lsp.server``; say so instead of importing it."""
        monkeypatch.setattr(
            cli.importlib.util,
            "find_spec",
            lambda name: None if "." in name else object(),
        )
        monkeypatch.setattr(cli, "_distribution_version", lambda dist: "1.3.1")

        with pytest.raises(SystemExit):
            cli._require_extra("pygls.lsp.server", "lsp", "lsp")

        assert "found pygls 1.3.1" in capsys.readouterr().err

    @pytest.mark.parametrize(
        ("command", "module"),
        [("lsp", "pygls.lsp.server"), ("mcp", "mcp.server.fastmcp")],
    )
    def test_guards_the_module_the_server_imports(self, command: str, module: str) -> None:
        """The guard must track the real import, or it waves through a broken env."""
        source = (Path(cli.__file__).parent / f"{command}_server.py").read_text(encoding="utf-8")

        assert f"from {module} import" in source


# ------------------------------------------------------------------ #
# fleet compare — exit code is the verdict                            #
# ------------------------------------------------------------------ #


def _adsl() -> pl.DataFrame:
    return pl.from_repr("""\
┌─────────┬─────┬─────┐
│ USUBJID ┆ AGE ┆ SEX │
│ ---     ┆ --- ┆ --- │
│ str     ┆ i64 ┆ str │
╞═════════╪═════╪═════╡
│ S01     ┆ 34  ┆ M   │
│ S02     ┆ 45  ┆ F   │
│ S03     ┆ 52  ┆ F   │
└─────────┴─────┴─────┘
""")


def test_compare_equal_parquet_files_exit_0_and_print_the_report(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base, candidate = tmp_path / "adsl_prod.parquet", tmp_path / "adsl_qc.parquet"
    _adsl().write_parquet(base)
    _adsl().write_parquet(candidate)

    code = _run(["compare", str(base), str(candidate), "--keys", "USUBJID"])

    captured = capsys.readouterr()
    assert code == 0
    assert "EQUAL: no differences found." in captured.out
    assert captured.err == ""


def test_compare_different_csv_files_exit_1_and_list_the_difference(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base, candidate = tmp_path / "adsl_prod.csv", tmp_path / "adsl_qc.csv"
    _adsl().write_csv(base)
    _adsl().with_columns(pl.lit(99).alias("AGE")).write_csv(candidate)

    code = _run(["compare", str(base), str(candidate), "--keys", "USUBJID"])

    captured = capsys.readouterr()
    assert code == 1
    assert "NOT EQUAL: values_differ" in captured.out
    assert "USUBJID=S01" in captured.out and "34" in captured.out and "99" in captured.out
    assert captured.err == ""


def test_compare_names_each_side_after_its_file(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base, candidate = tmp_path / "adsl_prod.parquet", tmp_path / "adsl_qc.parquet"
    _adsl().write_parquet(base)
    _adsl().write_parquet(candidate)

    _run(["compare", str(base), str(candidate), "--keys", "USUBJID"])

    out = capsys.readouterr().out
    assert f"Base:      {base}" in out
    assert f"Candidate: {candidate}" in out


def test_compare_keys_are_required(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    base = tmp_path / "adsl.parquet"
    _adsl().write_parquet(base)

    code = _run(["compare", str(base), str(base)])

    captured = capsys.readouterr()
    assert code == 2
    assert "--keys" in captured.err and "required" in captured.err
    assert captured.out == ""


def test_compare_accepts_composite_keys_with_spaces(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    adae = pl.from_repr("""\
┌─────────┬───────┬────────┐
│ USUBJID ┆ AESEQ ┆ AETERM │
│ ---     ┆ ---   ┆ ---    │
│ str     ┆ i64   ┆ str    │
╞═════════╪═══════╪════════╡
│ 01      ┆ 1     ┆ a      │
│ 01      ┆ 2     ┆ b      │
└─────────┴───────┴────────┘
""")
    base, candidate = tmp_path / "adae_prod.parquet", tmp_path / "adae_qc.parquet"
    adae.write_parquet(base)
    adae.write_parquet(candidate)

    code = _run(["compare", str(base), str(candidate), "--keys", "USUBJID, AESEQ"])

    assert code == 0
    assert "Keys:      USUBJID, AESEQ" in capsys.readouterr().out


@pytest.mark.parametrize(
    "candidate_frame, expected_reason",
    [
        pytest.param(_adsl().rename({"USUBJID": "SUBJID"}), "USUBJID", id="key-absent"),
        pytest.param(pl.concat([_adsl(), _adsl().head(1)]), "USUBJID=S01", id="duplicate-key"),
    ],
)
def test_compare_exits_2_with_the_reason_on_stderr_when_keys_cannot_pair(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
    candidate_frame: pl.DataFrame,
    expected_reason: str,
) -> None:
    base, candidate = tmp_path / "adsl_prod.parquet", tmp_path / "adsl_qc.parquet"
    _adsl().write_parquet(base)
    candidate_frame.write_parquet(candidate)

    code = _run(["compare", str(base), str(candidate), "--keys", "USUBJID"])

    captured = capsys.readouterr()
    assert code == 2
    assert "candidate" in captured.err and expected_reason in captured.err
    assert captured.out == ""


def test_compare_empty_keys_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    base = tmp_path / "adsl.parquet"
    _adsl().write_parquet(base)

    code = _run(["compare", str(base), str(base), "--keys", " , "])

    captured = capsys.readouterr()
    assert code == 2
    assert "keys" in captured.err
    assert captured.out == ""


@pytest.mark.parametrize(
    "candidate_name, expected_reason",
    [
        pytest.param("missing.parquet", "missing.parquet", id="file-not-found"),
        pytest.param("adsl.txt", ".txt", id="unsupported-format"),
    ],
)
def test_compare_unreadable_file_exits_2_and_names_it(
    tmp_path: Path, capsys: pytest.CaptureFixture, candidate_name: str, expected_reason: str
) -> None:
    base = tmp_path / "adsl_prod.parquet"
    _adsl().write_parquet(base)
    candidate = tmp_path / candidate_name
    if candidate.suffix == ".txt":
        candidate.write_text("not a dataset", encoding="utf-8")

    code = _run(["compare", str(base), str(candidate), "--keys", "USUBJID"])

    captured = capsys.readouterr()
    assert code == 2
    assert expected_reason in captured.err
    assert captured.out == ""


def test_compare_with_only_the_keys_in_common_exits_1_and_prints_the_report(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """One-sided variables are a difference, reported like any other (ADR-0004)."""
    base, candidate = tmp_path / "adsl_prod.parquet", tmp_path / "adsl_qc.parquet"
    _adsl().select("USUBJID", "AGE").write_parquet(base)
    _adsl().select("USUBJID", "SEX").write_parquet(candidate)

    code = _run(["compare", str(base), str(candidate), "--keys", "USUBJID"])

    captured = capsys.readouterr()
    assert code == 1
    assert "No variables were compared besides the keys." in captured.out
    assert "AGE" in captured.out and "SEX" in captured.out
    assert captured.err == ""


def test_compare_key_only_files_with_the_same_keys_exit_0_and_warn(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base = tmp_path / "adsl.parquet"
    _adsl().select("USUBJID").write_parquet(base)

    code = _run(["compare", str(base), str(base), "--keys", "USUBJID"])

    assert code == 0
    assert "No variables were compared besides the keys." in capsys.readouterr().out


def test_compare_two_empty_files_exit_0_and_warn_in_json(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base = tmp_path / "adae.parquet"
    _adsl().clear().write_parquet(base)

    code = _run(["compare", str(base), str(base), "--keys", "USUBJID", "--format", "json"])

    document = json.loads(capsys.readouterr().out)
    assert code == 0
    assert document["is_equal"] is True
    assert document["warnings"] == ["Both datasets have no observations."]


def test_compare_variables_of_keys_only_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base = tmp_path / "adsl.parquet"
    _adsl().write_parquet(base)

    code = _run(["compare", str(base), str(base), "--keys", "USUBJID", "--variables", "USUBJID"])

    captured = capsys.readouterr()
    assert code == 2
    assert "only key variables" in captured.err
    assert captured.out == ""


def test_compare_all_lifts_the_print_limits(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    n = 60
    base_frame = pl.DataFrame({"ID": range(n), "X": [0] * n})
    base, candidate = tmp_path / "base.parquet", tmp_path / "candidate.parquet"
    base_frame.write_parquet(base)
    base_frame.with_columns(pl.lit(1).alias("X")).write_parquet(candidate)

    assert _run(["compare", str(base), str(candidate), "--keys", "ID"]) == 1
    assert "showing 50 of 60 unequal values" in capsys.readouterr().out

    assert _run(["compare", str(base), str(candidate), "--keys", "ID", "--all"]) == 1
    assert "showing all 60 unequal values" in capsys.readouterr().out


@pytest.mark.parametrize(
    "new_age, expected_code, expected_flags",
    [
        pytest.param(None, 0, [], id="equal"),
        pytest.param(99, 1, ["values_differ"], id="different"),
    ],
)
def test_compare_format_json_prints_one_document_and_nothing_else(
    tmp_path: Path,
    capsys: pytest.CaptureFixture,
    new_age: int | None,
    expected_code: int,
    expected_flags: list[str],
) -> None:
    base, candidate = tmp_path / "adsl_prod.parquet", tmp_path / "adsl_qc.parquet"
    _adsl().write_parquet(base)
    candidate_frame = (
        _adsl() if new_age is None else _adsl().with_columns(pl.lit(new_age).alias("AGE"))
    )
    candidate_frame.write_parquet(candidate)

    code = _run(["compare", str(base), str(candidate), "--keys", "USUBJID", "--format", "json"])

    captured = capsys.readouterr()
    assert code == expected_code
    document = json.loads(captured.out)  # the whole of stdout is the document
    assert document["is_equal"] is (expected_code == 0)
    assert document["flags"] == expected_flags
    assert document["settings"]["keys"] == ["USUBJID"]
    assert document["datasets"]["base"]["name"] == str(base)
    assert document["datasets"]["candidate"]["name"] == str(candidate)
    assert captured.err == ""


def test_compare_format_json_keeps_stdout_empty_when_the_comparison_cannot_run(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base, candidate = tmp_path / "adsl_prod.parquet", tmp_path / "adsl_qc.parquet"
    _adsl().write_parquet(base)
    _adsl().rename({"USUBJID": "SUBJID"}).write_parquet(candidate)

    code = _run(["compare", str(base), str(candidate), "--keys", "USUBJID", "--format", "json"])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "USUBJID" in captured.err


def _sixty_rows(tmp_path: Path) -> tuple[Path, Path]:
    """Base and candidate parquet files that differ on every one of 60 rows."""
    n = 60
    base_frame = pl.DataFrame({"ID": range(n), "X": [0] * n})
    base, candidate = tmp_path / "base.parquet", tmp_path / "candidate.parquet"
    base_frame.write_parquet(base)
    base_frame.with_columns(pl.lit(1).alias("X")).write_parquet(candidate)
    return base, candidate


def test_compare_out_writes_the_complete_parquet_listing(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base, candidate = _sixty_rows(tmp_path)
    out = tmp_path / "build" / "differences.parquet"  # parent directory created on the way

    code = _run(["compare", str(base), str(candidate), "--keys", "ID", "--out", str(out)])

    captured = capsys.readouterr()
    assert code == 1
    listing = pl.read_parquet(out)
    assert listing.columns == [
        "ID",
        "group",
        "variable",
        "base",
        "candidate",
        "difference",
        "percent_difference",
    ]
    assert listing.schema["ID"] == pl.Int64 and listing.schema["difference"] == pl.Float64
    assert listing.height == 60  # complete, while the printed report is truncated
    assert "showing 50 of 60 unequal values" in captured.out
    assert f"Value listing → {out}" in captured.out
    assert captured.err == ""


def test_compare_out_with_format_json_prints_only_the_document(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base, candidate = _sixty_rows(tmp_path)
    out = tmp_path / "differences.parquet"

    code = _run(
        [
            "compare",
            str(base),
            str(candidate),
            "--keys",
            "ID",
            "--format",
            "json",
            "--out",
            str(out),
        ]
    )

    captured = capsys.readouterr()
    assert code == 1
    document = json.loads(captured.out)
    assert (document["listing"]["shown"], document["listing"]["truncated"]) == (50, True)
    assert pl.read_parquet(out).height == 60
    assert captured.err == ""


def test_compare_all_lifts_the_json_listing_truncation(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base, candidate = _sixty_rows(tmp_path)

    code = _run(["compare", str(base), str(candidate), "--keys", "ID", "--format", "json", "--all"])

    assert code == 1
    document = json.loads(capsys.readouterr().out)
    listing = document["listing"]
    assert (listing["shown"], listing["total"], listing["truncated"]) == (60, 60, False)
    assert document["settings"]["max_print"] is None


def test_compare_out_that_cannot_be_written_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base, candidate = _sixty_rows(tmp_path)
    blocker = tmp_path / "build"
    blocker.write_text("a file where the output directory should be", encoding="utf-8")
    out = blocker / "differences.parquet"

    code = _run(["compare", str(base), str(candidate), "--keys", "ID", "--out", str(out)])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert str(out) in captured.err


def test_compare_report_writes_a_self_contained_html_page(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base, candidate = tmp_path / "adsl_prod.parquet", tmp_path / "adsl_qc.parquet"
    _adsl().write_parquet(base)
    _adsl().with_columns(pl.lit(99).alias("AGE")).write_parquet(candidate)
    report = tmp_path / "build" / "adsl_compare.html"  # parent directory created on the way

    code = _run(
        ["compare", str(base), str(candidate), "--keys", "USUBJID", "--report", str(report)]
    )

    captured = capsys.readouterr()
    assert code == 1
    page = report.read_text(encoding="utf-8")
    assert "NOT EQUAL" in page
    assert "S01" in page and "34" in page and "99" in page
    assert "http" not in page and "<script" not in page and "<link" not in page
    assert "NOT EQUAL" in captured.out
    assert f"HTML report → {report}" in captured.out
    assert captured.err == ""


def test_compare_report_with_format_json_prints_only_the_document(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base, candidate = _sixty_rows(tmp_path)
    report = tmp_path / "compare.html"

    code = _run(
        [
            "compare",
            str(base),
            str(candidate),
            "--keys",
            "ID",
            "--format",
            "json",
            "--report",
            str(report),
        ]
    )

    captured = capsys.readouterr()
    assert code == 1
    assert json.loads(captured.out)["is_equal"] is False
    page = report.read_text(encoding="utf-8")
    assert "NOT EQUAL" in page and "X" in page
    assert captured.err == ""


def test_compare_report_that_cannot_be_written_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base, candidate = _sixty_rows(tmp_path)
    blocker = tmp_path / "build"
    blocker.write_text("a file where the output directory should be", encoding="utf-8")
    report = blocker / "compare.html"

    code = _run(["compare", str(base), str(candidate), "--keys", "ID", "--report", str(report)])

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert str(report) in captured.err


def test_compare_reads_xpt_through_the_io_extra(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    pytest.importorskip("pyreadstat")
    from fleet.io import save_xpt

    base, candidate = tmp_path / "adsl.xpt", tmp_path / "adsl_qc.parquet"
    save_xpt(_adsl(), base)
    _adsl().with_columns(pl.col("AGE").cast(pl.Float64)).write_parquet(candidate)

    code = _run(["compare", str(base), str(candidate), "--keys", "USUBJID"])

    captured = capsys.readouterr()
    assert code == 0, captured
    assert "EQUAL: no differences found." in captured.out


def test_compare_a_sas_blank_equals_a_parquet_null(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """An XPT cannot tell a blank from a missing value: both are the SAS missing value."""
    pytest.importorskip("pyreadstat")
    from fleet.io import save_xpt

    adae = pl.from_repr("""
┌─────────┬───────┬───────────────────────────┐
│ USUBJID ┆ AESEQ ┆ AEOUT                     │
│ ---     ┆ ---   ┆ ---                       │
│ str     ┆ f64   ┆ str                       │
╞═════════╪═══════╪═══════════════════════════╡
│ 01-002  ┆ 1.0   ┆ null                      │
│ 01-003  ┆ 1.0   ┆ RECOVERED/RESOLVED        │
└─────────┴───────┴───────────────────────────┘
""")
    base, candidate = tmp_path / "adae.xpt", tmp_path / "adae_qc.parquet"
    save_xpt(adae.with_columns(pl.col("AEOUT").fill_null("")), base)
    adae.write_parquet(candidate)

    code = _run(["compare", str(base), str(candidate), "--keys", "USUBJID,AESEQ"])

    assert code == 0, capsys.readouterr()


def test_compare_tolerance_flags_reach_the_engine(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Float noise between two engines is absorbed by --abs-tol; the settings line says so."""
    base, candidate = tmp_path / "adsl_prod.parquet", tmp_path / "adsl_qc.parquet"
    _adsl().with_columns(pl.col("AGE").cast(pl.Float64)).write_parquet(base)
    _adsl().with_columns(pl.col("AGE").cast(pl.Float64) + 0.0004).write_parquet(candidate)

    assert _run(["compare", str(base), str(candidate), "--keys", "USUBJID"]) == 1
    capsys.readouterr()

    code = _run(["compare", str(base), str(candidate), "--keys", "USUBJID", "--abs-tol", "0.001"])

    captured = capsys.readouterr()
    assert code == 0
    assert "EQUAL: no differences found." in captured.out
    assert "abs_tol=0.001" in captured.out


def test_compare_rel_tol_flag_reaches_the_engine(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base, candidate = tmp_path / "prod.parquet", tmp_path / "qc.parquet"
    pl.DataFrame({"ID": [1], "X": [200.0]}).write_parquet(base)
    pl.DataFrame({"ID": [1], "X": [202.0]}).write_parquet(candidate)

    code = _run(["compare", str(base), str(candidate), "--keys", "ID", "--rel-tol", "0.01"])

    assert code == 0
    assert "rel_tol=0.01" in capsys.readouterr().out


def test_compare_ignore_trailing_whitespace_flag_reaches_the_engine(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """SAS pads character values; Fleet strips them, and the flag makes the two compare equal."""
    base, candidate = tmp_path / "prod.parquet", tmp_path / "qc.parquet"
    pl.DataFrame({"USUBJID": ["S01"], "SEX": ["M   "]}).write_parquet(base)
    pl.DataFrame({"USUBJID": ["S01"], "SEX": ["M"]}).write_parquet(candidate)

    assert _run(["compare", str(base), str(candidate), "--keys", "USUBJID"]) == 1
    capsys.readouterr()

    code = _run(
        [
            "compare",
            str(base),
            str(candidate),
            "--keys",
            "USUBJID",
            "--ignore-trailing-whitespace",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    assert "ignoring trailing whitespace" in captured.out


def test_compare_json_settings_carry_the_three_options(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base = tmp_path / "adsl.parquet"
    _adsl().write_parquet(base)

    code = _run(
        [
            "compare",
            str(base),
            str(base),
            "--keys",
            "USUBJID",
            "--format",
            "json",
            "--abs-tol",
            "0.5",
            "--rel-tol",
            "0.01",
            "--ignore-trailing-whitespace",
        ]
    )

    settings = json.loads(capsys.readouterr().out)["settings"]
    assert code == 0
    assert settings["abs_tol"] == 0.5
    assert settings["rel_tol"] == 0.01
    assert settings["ignore_trailing_whitespace"] is True


def test_compare_a_negative_tolerance_exits_2(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base = tmp_path / "adsl.parquet"
    _adsl().write_parquet(base)

    code = _run(["compare", str(base), str(base), "--keys", "USUBJID", "--abs-tol", "-1"])

    captured = capsys.readouterr()
    assert code == 2
    assert "abs_tol" in captured.err
    assert captured.out == ""


def test_compare_allow_duplicates_pairs_by_position_instead_of_exiting_2(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base, candidate = tmp_path / "adsl_prod.parquet", tmp_path / "adsl_qc.parquet"
    _adsl().write_parquet(base)
    pl.concat([_adsl(), _adsl().head(1)]).write_parquet(candidate)

    assert _run(["compare", str(base), str(candidate), "--keys", "USUBJID"]) == 2
    assert "allow_duplicates" in capsys.readouterr().err

    code = _run(["compare", str(base), str(candidate), "--keys", "USUBJID", "--allow-duplicates"])

    captured = capsys.readouterr()
    assert code == 1  # the extra observation is now a candidate-only one, not a refusal
    assert "Duplicate keys were paired by position" in captured.out
    assert "Duplicate observations in candidate: 1" in captured.out
    assert captured.err == ""


def test_compare_by_sections_the_report_per_group(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base, candidate = tmp_path / "adsl_prod.parquet", tmp_path / "adsl_qc.parquet"
    _adsl().write_parquet(base)
    _adsl().with_columns(
        pl.when(pl.col("SEX") == "F").then(99).otherwise(pl.col("AGE")).alias("AGE")
    ).write_parquet(candidate)

    code = _run(
        [
            "compare",
            str(base),
            str(candidate),
            "--keys",
            "USUBJID",
            "--by",
            "SEX",
            "--format",
            "json",
        ]
    )

    document = json.loads(capsys.readouterr().out)
    assert code == 1
    assert document["settings"]["by"] == ["SEX"]
    assert document["settings"]["keys"] == ["SEX", "USUBJID"]
    assert document["values"]["per_group"] == [
        {
            "group": "SEX=F",
            "variables_with_differences": 1,
            "observations_with_differences": 2,
            "differences": 2,
        },
        {
            "group": "SEX=M",
            "variables_with_differences": 0,
            "observations_with_differences": 0,
            "differences": 0,
        },
    ]


def test_compare_pairs_compare_a_renamed_variable_instead_of_reporting_it_missing(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base, candidate = tmp_path / "adsl_prod.parquet", tmp_path / "adsl_qc.parquet"
    _adsl().write_parquet(base)
    _adsl().rename({"AGE": "AGEN"}).write_parquet(candidate)

    assert _run(["compare", str(base), str(candidate), "--keys", "USUBJID"]) == 1
    capsys.readouterr()

    code = _run(["compare", str(base), str(candidate), "--keys", "USUBJID", "--pairs", "AGE=AGEN"])

    captured = capsys.readouterr()
    assert code == 0
    assert "Pairs:     AGE = AGEN" in captured.out
    assert captured.err == ""


def test_compare_pairs_that_are_not_pairs_exit_2(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base = tmp_path / "adsl.parquet"
    _adsl().write_parquet(base)

    code = _run(["compare", str(base), str(base), "--keys", "USUBJID", "--pairs", "AGE"])

    captured = capsys.readouterr()
    assert code == 2
    assert "--pairs" in captured.err
    assert captured.out == ""


def test_compare_variables_restricts_the_comparison(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base, candidate = tmp_path / "adsl_prod.parquet", tmp_path / "adsl_qc.parquet"
    _adsl().write_parquet(base)
    _adsl().with_columns(pl.lit(99).alias("AGE")).write_parquet(candidate)

    assert _run(["compare", str(base), str(candidate), "--keys", "USUBJID"]) == 1
    capsys.readouterr()

    code = _run(["compare", str(base), str(candidate), "--keys", "USUBJID", "--variables", "SEX"])

    captured = capsys.readouterr()
    assert code == 0  # AGE differs, but it is outside the restriction
    assert "Variables: SEX" in captured.out
    assert captured.err == ""


def test_compare_json_settings_carry_the_pairs_and_the_restriction(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    base, candidate = tmp_path / "adsl_prod.parquet", tmp_path / "adsl_qc.parquet"
    _adsl().write_parquet(base)
    _adsl().rename({"AGE": "AGEN"}).write_parquet(candidate)

    code = _run(
        [
            "compare",
            str(base),
            str(candidate),
            "--keys",
            "USUBJID",
            "--format",
            "json",
            "--pairs",
            "AGE=AGEN",
            "--variables",
            "AGE, SEX",
        ]
    )

    settings = json.loads(capsys.readouterr().out)["settings"]
    assert code == 0
    assert settings["pairs"] == {"AGE": "AGEN"}
    assert settings["variables"] == ["AGE", "SEX"]
