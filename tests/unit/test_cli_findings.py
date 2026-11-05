"""``fleet`` CLI: regressions of the medium and low audit findings (package ml-cli)."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from fleet import cli
from tests.unit.test_cli import _CONFIG, _SDTM_DEFINE, _TRIAL_DESIGN


def _run(argv: list[str]) -> int:
    """Invoke ``cli.main`` and return its exit code (0 when it returns)."""
    try:
        cli.main(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


_ADSL = """\
┌─────────┬─────┐
│ USUBJID ┆ AGE │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ S01     ┆ 34  │
│ S02     ┆ 45  │
└─────────┴─────┘
"""


@pytest.fixture
def adsl_pair(tmp_path: Path) -> tuple[Path, Path]:
    base, candidate = tmp_path / "a.parquet", tmp_path / "b.parquet"
    pl.from_repr(_ADSL).write_parquet(base)
    pl.from_repr(_ADSL).write_parquet(candidate)
    return base, candidate


class TestCompare:
    def test_c1_275_an_internal_error_exits_2_not_1(
        self, adsl_pair, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        def boom(*args, **kwargs):
            raise RuntimeError("engine defect")

        monkeypatch.setattr("fleet.comparison.compare", boom)
        monkeypatch.delenv("FLEET_DEBUG", raising=False)
        base, candidate = adsl_pair

        assert _run(["compare", str(base), str(candidate), "--keys", "USUBJID"]) == 2

        err = capsys.readouterr().err
        assert "internal error in fleet compare: RuntimeError: engine defect" in err
        assert "Traceback" not in err

    def test_c1_275_fleet_debug_shows_the_traceback(
        self, adsl_pair, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(*args, **kwargs):
            raise RuntimeError("engine defect")

        monkeypatch.setattr("fleet.comparison.compare", boom)
        monkeypatch.setenv("FLEET_DEBUG", "1")
        base, candidate = adsl_pair

        with pytest.raises(RuntimeError, match="engine defect"):
            cli.main(["compare", str(base), str(candidate), "--keys", "USUBJID"])

    def test_c1_276_a_corrupt_file_is_named_with_its_side(
        self, adsl_pair, capsys: pytest.CaptureFixture
    ) -> None:
        base, candidate = adsl_pair
        candidate.write_bytes(b"PAR1 not a parquet file")

        assert _run(["compare", str(base), str(candidate), "--keys", "USUBJID"]) == 2

        assert f"cannot read the candidate {candidate}" in capsys.readouterr().err

    @pytest.mark.parametrize(
        ("flag", "side"),
        [
            ("--out", "base"),
            ("--out", "candidate"),
            ("--report", "base"),
            ("--report", "candidate"),
        ],
    )
    def test_c1_278_an_output_may_not_overwrite_an_input(
        self, flag: str, side: str, adsl_pair, capsys: pytest.CaptureFixture
    ) -> None:
        base, candidate = adsl_pair
        target = base if side == "base" else candidate
        before = target.read_bytes()

        code = _run(["compare", str(base), str(candidate), "--keys", "USUBJID", flag, str(target)])

        assert code == 2
        assert f"{flag} is the {side} file" in capsys.readouterr().err
        assert target.read_bytes() == before

    def test_c1_278_out_and_report_may_not_name_one_file(
        self, adsl_pair, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        base, candidate = adsl_pair
        same = str(tmp_path / "x.out")

        code = _run(
            [
                "compare",
                str(base),
                str(candidate),
                "--keys",
                "USUBJID",
                "--out",
                same,
                "--report",
                same,
            ]
        )

        assert code == 2
        assert "--out and --report name the same file" in capsys.readouterr().err

    def test_c1_277_the_save_methods_create_the_parent_folder(self, tmp_path: Path) -> None:
        from fleet.comparison import compare

        frame = pl.from_repr(_ADSL)
        report = compare(frame, frame, keys=["USUBJID"])

        report.save_json(tmp_path / "a" / "x.json")
        report.save_html_report(tmp_path / "b" / "x.html")
        report.save_listing(tmp_path / "c" / "x.parquet")

        assert (tmp_path / "a" / "x.json").is_file()
        assert (tmp_path / "b" / "x.html").is_file()
        assert (tmp_path / "c" / "x.parquet").is_file()


@pytest.fixture
def study(tmp_path: Path) -> Path:
    """A minimal study workspace with a runnable DM define and its raw CSV."""
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


def _seed_ctgov(monkeypatch: pytest.MonkeyPatch, *codes: str) -> None:
    from fleet.sdtm.tdd import TrialParameter, TrialParameters

    seeded = TrialParameters(
        parameters=[TrialParameter(tsparmcd=c, tsparm=f"{c} name", tsval="V") for c in codes]
    )
    monkeypatch.setattr(
        TrialParameters, "from_ctgov", classmethod(lambda cls, nct_id, **kw: seeded)
    )


class TestTrialDesign:
    @pytest.mark.parametrize("command", ["audit", "build"])
    def test_c1_270_a_duplicate_visitnum_is_one_line_not_a_traceback(
        self, command: str, study: Path, monkeypatch, capsys
    ) -> None:
        design = study / "metadata" / "sdtm" / "trial_design.yaml"
        design.write_text(
            _TRIAL_DESIGN
            + "  visits:\n    - {visitnum: 1, visit: SCREENING}\n    - {visitnum: 1, visit: WEEK 1}\n",
            encoding="utf-8",
        )
        monkeypatch.chdir(study)

        assert _run(["tdd", command, "--force"] if command == "build" else ["tdd", command]) == 1

        err = capsys.readouterr().err
        assert err.strip().splitlines() == [
            f"Error: {design}: invalid TrialVisits: Duplicate VISITNUM values"
        ]

    @pytest.mark.parametrize("argv", [["tdd", "audit"], ["tdd", "ctgov", "NCT1", "--write"]])
    def test_c1_270_an_empty_design_file_is_named(
        self, argv: list[str], study: Path, monkeypatch, capsys
    ) -> None:
        (study / "metadata" / "sdtm" / "trial_design.yaml").write_text("", encoding="utf-8")
        _seed_ctgov(monkeypatch, "REGID")
        monkeypatch.chdir(study)

        assert _run(argv) == 1

        err = capsys.readouterr().err
        assert "the file is empty" in err
        assert "Traceback" not in err

    def test_c1_271_nothing_new_writes_nothing(self, study: Path, monkeypatch, capsys) -> None:
        design = study / "metadata" / "sdtm" / "trial_design.yaml"
        design.write_text("# QC note: reviewed by Mahdi\n" + _TRIAL_DESIGN, encoding="utf-8")
        before = design.read_bytes()
        _seed_ctgov(monkeypatch, "TITLE")
        monkeypatch.chdir(study)

        assert _run(["tdd", "ctgov", "NCT1", "--write"]) == 0

        assert "is not changed" in capsys.readouterr().out
        assert design.read_bytes() == before

    def test_c1_272_ctgov_write_keeps_the_comments(self, study: Path, monkeypatch, capsys) -> None:
        import yaml

        design = study / "metadata" / "sdtm" / "trial_design.yaml"
        text = _TRIAL_DESIGN.replace(
            "  arms:\n", "  # Arms agreed at the design review\n  arms:  # one arm\n"
        )
        design.write_text("# QC note: reviewed by Mahdi\n" + text, encoding="utf-8")
        _seed_ctgov(monkeypatch, "REGID")
        monkeypatch.chdir(study)

        assert _run(["tdd", "ctgov", "NCT1", "--write"]) == 0

        new = design.read_text(encoding="utf-8")
        for comment in ("# QC note", "# Arms agreed", "# one arm"):
            assert comment in new
        params = yaml.safe_load(new)["trial_design"]["parameters"]
        assert [p["tsparmcd"] for p in params] == ["TITLE", "SSTDTC", "REGID"]
        assert "warning" not in capsys.readouterr().err


class TestAddAcrf:
    def test_c1_272_every_comment_stays(self, study: Path, monkeypatch, capsys) -> None:
        import yaml

        spec = study / "metadata" / "sdtm" / "define.yaml"
        text = "# header\n" + _SDTM_DEFINE.replace(
            "  originator: Test Co\n", "  originator: Test Co  # sponsor\n"
        ).replace(
            "      - name: AGE\n",
            "      # AGE comes from the CRF, sponsor decision\n      - name: AGE\n",
        )
        spec.write_text(text, encoding="utf-8")
        monkeypatch.chdir(study)

        assert _run(["add-acrf", "--href", "acrf.pdf"]) == 0
        assert _run(["add-acrf", "--href", "acrf2.pdf", "--title", "aCRF"]) == 0

        new = spec.read_text(encoding="utf-8")
        for comment in ("# header", "# sponsor", "# AGE comes from the CRF, sponsor decision"):
            assert comment in new
        acrf = yaml.safe_load(new)["study"]["documents"]["annotated_crf"]
        assert acrf == {"href": "acrf2.pdf", "title": "aCRF"}
        assert new.count("annotated_crf:") == 1
        assert "warning" not in capsys.readouterr().err

    def test_c1_272_a_flow_style_study_is_dumped_with_a_warning(
        self, study: Path, monkeypatch, capsys
    ) -> None:
        spec = study / "metadata" / "sdtm" / "define.yaml"
        head, rest = _SDTM_DEFINE.split("datasets:\n", 1)
        spec.write_text(
            "study: {id: TESTRUN, standard: SDTMIG}  # flow\ndatasets:\n" + rest, encoding="utf-8"
        )
        monkeypatch.chdir(study)

        assert _run(["add-acrf", "--href", "acrf.pdf"]) == 0

        assert "1 line(s) with a comment are lost" in capsys.readouterr().err


class TestErrors:
    def test_c1_300_a_broken_config_is_an_error_not_no_study(
        self, study: Path, monkeypatch, capsys
    ) -> None:
        (study / "study_config.yaml").write_text("study_id: [unclosed\n", encoding="utf-8")
        monkeypatch.chdir(study)

        assert _run(["tlg", "export", "--domain", "ae"]) == 1

        err = capsys.readouterr().err
        assert "study_config.yaml" in err
        assert "no dataset for domain" not in err

    def test_c1_315_a_yaml_error_in_define_xml_is_one_line(
        self, study: Path, monkeypatch, capsys
    ) -> None:
        spec = study / "metadata" / "sdtm" / "define.yaml"
        spec.write_text(
            _SDTM_DEFINE.replace("  - name: DM\n", "  - name: DM\n   bad: [\n"), encoding="utf-8"
        )
        monkeypatch.chdir(study)

        assert _run(["define-xml", "--no-preview"]) == 1

        err = capsys.readouterr().err
        assert err.startswith("Error: invalid YAML")
        assert "line " in err
        assert "Traceback" not in err

    def test_c1_315_a_variable_with_no_label_does_not_stop_the_run(
        self, study: Path, monkeypatch, capsys
    ) -> None:
        spec = study / "metadata" / "sdtm" / "define.yaml"
        spec.write_text(_SDTM_DEFINE.replace("        label: Age\n", ""), encoding="utf-8")
        monkeypatch.chdir(study)

        assert _run(["run"]) == 0

    def test_c1_296_a_corrupt_input_names_the_dataset(
        self, study: Path, monkeypatch, capsys
    ) -> None:
        spec = study / "metadata" / "sdtm" / "define.yaml"
        spec.write_text(_SDTM_DEFINE.replace("dm.csv", "dm.parquet"), encoding="utf-8")
        (study / "data" / "raw" / "dm.parquet").write_bytes(b"PAR1 not parquet")
        monkeypatch.chdir(study)
        monkeypatch.delenv("FLEET_DEBUG", raising=False)

        assert _run(["run"]) == 1

        err = capsys.readouterr().err
        assert err.startswith("Error: ")
        assert "Traceback" not in err

    def test_c1_296_an_unwritable_folder_is_one_line(
        self, study: Path, monkeypatch, capsys
    ) -> None:
        import os

        if os.geteuid() == 0:
            pytest.skip("root writes a read-only folder")
        out = study / "locked"
        out.mkdir()
        out.chmod(0o555)
        monkeypatch.chdir(study)
        try:
            assert _run(["run", "--out", str(out)]) == 1
        finally:
            out.chmod(0o755)

        err = capsys.readouterr().err
        assert "Permission denied" in err
        assert "Traceback" not in err


class TestDoctor:
    def _no_engine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from fleet.core.exceptions import ValidationSetupError

        def refuse(**kwargs):
            raise ValidationSetupError("no engine")

        monkeypatch.setattr("fleet.validation.build_run_setup", refuse)
        monkeypatch.setattr("fleet.validation.engine.discover_engine", lambda root: None)

    def test_c1_282_no_engine_exits_1(self, study: Path, monkeypatch, capsys) -> None:
        self._no_engine(monkeypatch)
        monkeypatch.chdir(study)

        assert _run(["doctor"]) == 1

        assert "NOT FOUND" in capsys.readouterr().out

    def test_c1_282_a_yaml_error_in_define_is_a_cross_not_a_traceback(
        self, study: Path, monkeypatch, capsys
    ) -> None:
        self._no_engine(monkeypatch)
        (study / "metadata" / "sdtm" / "define.yaml").write_text("study: [\n", encoding="utf-8")
        monkeypatch.chdir(study)

        _run(["doctor"])

        captured = capsys.readouterr()
        assert "✗ codelists.py ....... invalid YAML" in captured.out
        assert "Optional extras" in captured.out
        assert "Traceback" not in captured.err

    def test_c1_282_an_invalid_config_is_a_cross(self, study: Path, monkeypatch, capsys) -> None:
        self._no_engine(monkeypatch)
        (study / "study_config.yaml").write_text("study_id: [\n", encoding="utf-8")
        monkeypatch.chdir(study)

        assert _run(["doctor"]) == 1

        assert "✗ study config" in capsys.readouterr().out
