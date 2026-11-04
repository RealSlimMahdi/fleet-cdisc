"""A study package from someone else runs no code on read-only commands (alpha audit 5.2).

Each test plants what a hostile study file could hold, then asserts that
the marker file the payload would write does not exist.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import polars as pl
import pytest

import fleet  # noqa: F401 — registers the namespaces
from fleet.core.define_spec import load_define_spec
from fleet.core.exceptions import DerivationError, SpecError
from fleet.sdtm.utils import parse_expression


def _main(argv: list[str]) -> int:
    from fleet.cli import main

    try:
        main(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _marker_engine(path: Path, marker: Path) -> Path:
    """An engine executable that only writes *marker*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
    path.chmod(0o755)
    return path


# ── c1-88: an expression string reaches only Polars expressions ───────────


_ESCAPES = [
    "pl.dataframe.frame.os.system('touch {m}')",
    "pl.os.mkdir('{m}')",
    "pl.config.os.mkdir('{m}')",
    "pl._dependencies.subprocess.run(['touch', '{m}'])",
    "pl.DataFrame({{'a': [1]}}).write_csv('{m}')",
    "pl.selectors.builtins.open('{m}', 'w')",
    "pl.col('AGE') * 2 + 0 * pl.os.system('touch {m}')",
    "pl.lit(pl.read_csv('{m}').columns[0])",
    "pl.col('a').meta.serialize('{m}')",
    "pl.col('a').pipe(print)",
    "pl.col('a').map_elements(print)",
    "pl.col('a').name.map(str)",
    "'{{0.__spec__}}'.format(pl)",
    "pl.lit(pl)",
]


@pytest.mark.parametrize("payload", _ESCAPES)
def test_an_expression_string_cannot_reach_files_or_commands(payload: str, tmp_path: Path) -> None:
    marker = tmp_path / "marker"

    with pytest.raises(DerivationError, match="not allowed|can only start"):
        parse_expression(payload.format(m=marker))

    assert not marker.exists()


@pytest.mark.parametrize(
    "expression",
    [
        "AVAL * 2",
        "pl.when(pl.col('AGE') < 65).then(pl.lit('<65')).when(pl.col('AGE') < 80)"
        ".then(pl.lit('65-80')).otherwise(pl.lit('>=80'))",
        "pl.col('AETERM').str.to_uppercase().str.strip_chars()",
        "pl.col('AESTDTC').str.strptime(pl.Date, '%Y-%m-%d').dt.year() >= 2020",
        "pl.col('ARM').is_in(['A', 'B']) & pl.col('TRTSDT').is_not_null()",
        "pl.concat_str([pl.col('STUDYID'), pl.lit('-'), pl.col('SUBJID')])",
        "pl.coalesce(pl.col('A'), pl.col('B')).cast(pl.Int64)",
    ],
)
def test_ordinary_expressions_still_parse(expression: str) -> None:
    assert isinstance(parse_expression(expression), pl.Expr)


def test_a_define_yaml_expression_cannot_run_a_command(tmp_path: Path) -> None:
    marker = tmp_path / "marker"
    spec = tmp_path / "define.yaml"
    spec.write_text(
        "datasets:\n"
        "  - name: DM\n"
        "    variables:\n"
        "      - name: AGE2\n"
        "        derivation:\n"
        "          algorithm: derivation\n"
        f"          expression: \"pl.dataframe.frame.os.system('touch {marker}')\"\n",
        encoding="utf-8",
    )
    dm = pl.from_repr("""
        ┌─────────┬─────┐
        │ USUBJID ┆ AGE │
        │ ---     ┆ --- │
        │ str     ┆ i64 │
        ╞═════════╪═════╡
        │ 01-001  ┆ 64  │
        └─────────┴─────┘
        """)

    with pytest.raises((DerivationError, SpecError)):
        dm.sdtm.from_spec(str(spec), dataset="DM").to_frame()

    assert not marker.exists()


# ── c1-298, c1-763: the CLI start-up reads no study code and one .env key ──


def test_a_dotenv_gives_only_the_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fleet.ct.api import try_load_dotenv

    (tmp_path / ".env").write_text(
        "CDISC_BASE_URL=http://attacker.example/api\n"
        "HTTPS_PROXY=http://attacker.example:8080\n"
        "FLEET_RULES_ENGINE=/tmp/evil\n"
        "export CDISC_API_KEY='key-from-dotenv'\n",
        encoding="utf-8",
    )
    sub = tmp_path / "programs" / "adam"
    sub.mkdir(parents=True)
    monkeypatch.chdir(sub)
    for key in ("CDISC_API_KEY", "CDISC_BASE_URL", "HTTPS_PROXY", "FLEET_RULES_ENGINE"):
        monkeypatch.delenv(key, raising=False)

    try_load_dotenv()

    assert os.environ["CDISC_API_KEY"] == "key-from-dotenv"
    for key in ("CDISC_BASE_URL", "HTTPS_PROXY", "FLEET_RULES_ENGINE"):
        assert key not in os.environ


def test_a_dotenv_never_replaces_the_shell_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fleet.ct.api import try_load_dotenv

    (tmp_path / ".env").write_text("CDISC_API_KEY=from-file\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CDISC_API_KEY", "from-shell")

    try_load_dotenv()

    assert os.environ["CDISC_API_KEY"] == "from-shell"


def test_the_study_folder_comes_last_on_the_import_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p not in ("", str(tmp_path))])

    _main(["tlg", "list"])

    assert sys.path[-1] == str(tmp_path)


# ── c1-744: dataset and input names stay names ─────────────────────────────


@pytest.mark.parametrize(
    ("dataset", "inputs"),
    [
        ("../../../another_study/data/ADSL", ""),
        ("DM; touch x", ""),
        ("adsl", ""),
        ("ADSL", "    inputs:\n      - {name: ../../../another_study/data/randlist, type: raw}\n"),
        ("ADSL", '    inputs:\n      - {name: "DM; touch x", type: dataset}\n'),
    ],
)
def test_a_name_that_is_not_a_sas_name_is_refused(
    dataset: str, inputs: str, tmp_path: Path
) -> None:
    spec = tmp_path / "define.yaml"
    spec.write_text(
        f'datasets:\n  - name: "{dataset}"\n{inputs}    variables:\n      - name: USUBJID\n',
        encoding="utf-8",
    )

    with pytest.raises(SpecError):
        load_define_spec(spec)


# ── c1-768: codelists.py is read as data ───────────────────────────────────


_CODELISTS = '''"""Generated."""

__ct_package__ = "sdtmct-2023-12-15"


class C66731:
    """SEX (C66731)."""

    _concept_id = "C66731"
    _cdisc_url = "https://library.cdisc.org/browser/#/mdr/ct/2023-12-15/packages/sdtmct-2023-12-15/codelists/C66731"
    _terms = ("F", "M")

    F = "F"
    M = "M"


SEX = C66731
__all__ = ["C66731", "SEX"]
'''


def test_a_generated_codelists_file_reads_without_running(tmp_path: Path) -> None:
    from fleet.ct.study_codelists import load_codelists

    path = tmp_path / "codelists.py"
    path.write_text(_CODELISTS, encoding="utf-8")

    packages, classes = load_codelists(path)

    assert packages == ("sdtmct-2023-12-15",)
    assert classes["C66731"]._terms == ("F", "M")
    assert classes["C66731"].M == "M"


@pytest.mark.parametrize(
    "extra",
    [
        "open({marker!r}, 'w').close()",
        "import os; os.system('touch {marker}')",
        "raise SystemExit(0)",
        "X = open({marker!r}, 'w')",
    ],
)
def test_a_codelists_file_with_code_is_refused_unrun(extra: str, tmp_path: Path) -> None:
    from fleet.ct.study_codelists import load_codelists

    marker = tmp_path / "marker"
    path = tmp_path / "codelists.py"
    path.write_text(_CODELISTS + extra.format(marker=str(marker)) + "\n", encoding="utf-8")

    with pytest.raises(SpecError, match=r"codelists\.py:\d+: .*fleet init ct --force"):
        load_codelists(path)

    assert not marker.exists()


# ── c1-835: fleet check and fleet doctor start no study program ────────────


def _study(tmp_path: Path, marker: Path) -> Path:
    _marker_engine(tmp_path / "bin" / "core", marker)
    (tmp_path / "study_config.yaml").write_text(
        "study_id: T01\nvalidation:\n  engine_path: bin/core\n", encoding="utf-8"
    )
    return tmp_path


def test_fleet_check_starts_no_engine_a_study_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    marker = tmp_path / "engine_ran"
    monkeypatch.chdir(_study(tmp_path, marker))

    _main(["check"])

    assert "bin/core" in capsys.readouterr().out
    assert not marker.exists()


def test_fleet_doctor_prints_every_line_when_codelists_is_broken(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    study = _study(tmp_path, tmp_path / "engine_ran")
    (study / "metadata" / "sdtm").mkdir(parents=True)
    (study / "metadata" / "sdtm" / "codelists.py").write_text("class (:\n", encoding="utf-8")
    monkeypatch.chdir(study)

    _main(["doctor"])

    out = capsys.readouterr().out
    assert "✗ codelists.py" in out
    assert "rules engine" in out


# ── c1-575: a received stylesheet cannot write or read files ──────────────


_HOSTILE_XSL = """<?xml version="1.0"?>
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
                xmlns:exsl="http://exslt.org/common" extension-element-prefixes="exsl">
  <xsl:template match="/">
    <exsl:document href="{marker}"><x/></exsl:document>
    <html><body><xsl:value-of select="document('{secret}')"/></body></html>
  </xsl:template>
</xsl:stylesheet>
"""


def test_a_received_stylesheet_writes_no_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from fleet.define_xml.spec_generator import DefineSpecGenerator

    marker = tmp_path / "written_by_xslt"
    secret = tmp_path / "secret.xml"
    secret.write_text("<s>SECRET</s>", encoding="utf-8")
    out = tmp_path / "define.xml"
    (tmp_path / "define2-1.xsl").write_text(
        _HOSTILE_XSL.format(marker=marker, secret=secret), encoding="utf-8"
    )
    spec = Path(__file__).parents[2] / "examples" / "cdiscpilot01" / "sdtm" / "define.yaml"

    DefineSpecGenerator(spec).generate(out)

    assert out.is_file()
    assert not marker.exists()
    assert "HTML preview skipped" in capsys.readouterr().out
