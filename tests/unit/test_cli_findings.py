"""``fleet`` CLI: regressions of the medium and low audit findings (package ml-cli)."""

from __future__ import annotations

import sys
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


class TestRun:
    def test_c1_294_inputs_show_their_row_count_and_the_run_its_times(
        self, study: Path, monkeypatch, capsys
    ) -> None:
        monkeypatch.chdir(study)

        assert _run(["run"]) == 0

        out = capsys.readouterr().out
        assert f"input dm_raw -> {study / 'data' / 'raw' / 'dm.csv'} (2 rows)" in out
        assert "Start:   " in out
        assert "End: " in out

    def test_c1_295_an_empty_datasets_list_is_an_error(
        self, study: Path, monkeypatch, capsys
    ) -> None:
        head = _SDTM_DEFINE.split("datasets:\n")[0]
        (study / "metadata" / "sdtm" / "define.yaml").write_text(
            head + "datasets: []\n", encoding="utf-8"
        )
        monkeypatch.chdir(study)

        assert _run(["run"]) == 1

        assert "no dataset to build in" in capsys.readouterr().err

    def test_c1_316_a_type_mismatch_warns_and_stops_with_check(
        self, study: Path, monkeypatch, capsys
    ) -> None:
        pl.from_repr("""\
┌────────────────┬───────┐
│ patient_number ┆ age   │
│ ---            ┆ ---   │
│ str            ┆ str   │
╞════════════════╪═══════╡
│ P1             ┆ 34    │
│ P2             ┆ abc   │
└────────────────┴───────┘
""").write_csv(study / "data" / "raw" / "dm.csv")
        monkeypatch.chdir(study)

        assert _run(["run"]) == 0
        assert "warning: DM.AGE: define type integer" in capsys.readouterr().err

        assert _run(["run", "--check"]) == 1
        assert "do not match their define type (--check)" in capsys.readouterr().err


class TestCheckDerivations:
    @pytest.mark.parametrize(
        ("block", "reason"),
        [
            (
                "        derivation:\n          algorithm: assign\n          source: age\n"
                "          ct_map: {a: b}\n",
                "ct_map",
            ),
            (
                "        derivation:\n          algorithm: assign\n          source: age\n"
                "          value: 5\n",
                "exclude each other",
            ),
        ],
    )
    def test_c1_299_a_block_that_fleet_run_refuses_fails_the_gate(
        self, block: str, reason: str, study: Path, monkeypatch, capsys
    ) -> None:
        spec = study / "metadata" / "sdtm" / "define.yaml"
        old = "        derivation:\n          algorithm: assign\n          source: age\n"
        spec.write_text(_SDTM_DEFINE.replace(old, block), encoding="utf-8")
        monkeypatch.chdir(study)

        assert _run(["check"]) == 1

        out = capsys.readouterr().out
        assert "[FAIL] define (sdtm)" in out
        assert "DM.AGE:" in out and reason in out


def test_c1_289_validate_finds_an_upper_case_extension(tmp_path: Path) -> None:
    from fleet.validation.run_setup import _collect_files

    pl.from_repr(_ADSL).write_parquet(tmp_path / "DM.PARQUET")
    (tmp_path / "notes.txt").write_text("not data", encoding="utf-8")

    assert _collect_files([tmp_path]) == ([tmp_path / "DM.PARQUET"], [tmp_path / "notes.txt"])


_DM_IG = {
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
        },
        {
            "name": "SEX",
            "label": "Sex",
            "type": "text",
            "length": 1,
            "codelist": "C66731",
            "origin": "Collected",
        },
    ],
}

#: One rule as the CDISC Library rules endpoint returns it, cut to what Fleet reads.
_RULES = {
    "rules": {
        "CORE-000001": {
            "Core": {"Id": "CORE-000001", "Version": "1", "Status": "Published"},
            "Description": "SEX is in the Sex codelist.",
            "Scope": {"Domains": {"Include": ["DM"]}},
            "Outcome": {"Message": "SEX is not in the codelist."},
        }
    }
}


class _OfflineLibrary:
    """The CDISC Library for one SDTM study: DM, the Sex codelist and one rule."""

    def __enter__(self) -> _OfflineLibrary:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get_codelist(self, concept_id: str, *, package: str) -> dict:
        assert concept_id == "C66731"
        return {
            "conceptId": "C66731",
            "name": "Sex",
            "submissionValue": "SEX",
            "terms": [
                {"submissionValue": "F", "preferredTerm": "Female"},
                {"submissionValue": "M", "preferredTerm": "Male"},
            ],
        }

    def get(self, path: str) -> dict:
        assert path == "/mdr/rules/sdtmig/3-4", path
        return _RULES


class TestFirstRun:
    def test_c1_313_new_then_check_then_check_rule(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        from fleet.core.scaffolder import DefineScaffolder

        monkeypatch.setenv("CDISC_API_KEY", "offline")
        monkeypatch.setattr("fleet.ct.api.CDISCClient", _OfflineLibrary)
        monkeypatch.setattr(DefineScaffolder, "_fetch_sdtm_datasets", lambda *_: [_DM_IG])
        monkeypatch.chdir(tmp_path)

        new = ["new", "S01", "-y", "--domains", "DM", "--description", "Test", "--company", "P"]
        assert _run(new) == 0
        study = tmp_path / "S01"
        out = capsys.readouterr().out
        assert "CT package: sdtmct-2023-12-15 (default)" in out
        assert (study / "study_config.yaml").is_file()
        assert list((study / "metadata").rglob("DM.yaml"))

        monkeypatch.chdir(study)
        assert _run(["check"]) == 0
        assert "0 failure(s)" in capsys.readouterr().out

        assert _run(["add-rule", "--domain", "DM", "--description", "SEX is F or M."]) == 0
        rule = next((study / "metadata" / "custom_rules").glob("*-DM-*.yaml"))
        # Step 1 of the add-rule hint: the Check names a real variable.
        rule.write_text(rule.read_text(encoding="utf-8").replace("VARIABLE_NAME", "SEX"))
        assert _run(["check-rule", str(rule)]) == 0
        assert _run(["check"]) == 0

    def test_c1_313_init_rules_with_no_define_exits_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        monkeypatch.setattr("fleet.ct.api.CDISCClient", _OfflineLibrary)
        assert _run(["init", "cfg", "--study-id", "S01", "--root", str(tmp_path)]) == 0
        monkeypatch.chdir(tmp_path)

        assert _run(["init", "rules"]) == 1

        assert "no rule file is cached" in capsys.readouterr().err


class TestNewAndInit:
    def test_c1_309_new_creates_the_study_folder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("CDISC_API_KEY", raising=False)
        monkeypatch.chdir(tmp_path)

        assert _run(["new", "STUDY01", "-y"]) == 0
        assert _run(["new", "STUDY02", "-y"]) == 0

        assert (tmp_path / "STUDY01" / "study_config.yaml").is_file()
        assert (tmp_path / "STUDY02" / "study_config.yaml").is_file()
        assert not (tmp_path / "study_config.yaml").exists()

    def test_c1_309_root_dot_keeps_the_current_folder(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        monkeypatch.delenv("CDISC_API_KEY", raising=False)
        monkeypatch.chdir(tmp_path)

        assert _run(["new", "STUDY01", "-y", "--root", "."]) == 0
        assert (tmp_path / "study_config.yaml").is_file()

        assert _run(["new", "STUDY02", "-y", "--root", "."]) == 1
        err = capsys.readouterr().err
        assert "fleet init define" in err

    @pytest.mark.parametrize("command", ["new", "init"])
    def test_c1_310_new_and_init_say_when_to_use_them(self, command: str, capsys) -> None:
        assert _run([command, "--help"]) == 0

        assert "Use it" in capsys.readouterr().out

    @pytest.mark.parametrize("step", ["rules", "define"])
    def test_c1_311_sdtm_only_and_adam_only_exclude_each_other(self, step: str, capsys) -> None:
        assert _run(["init", step, "--sdtm-only", "--adam-only"]) == 2

        assert "not allowed with argument" in capsys.readouterr().err

    def test_c1_311_a_dotted_ig_version_is_stored_dashed(self) -> None:
        from fleet.core.study_context import ADAMConfig, SDTMConfig

        assert SDTMConfig(ig_version="3.4").ig_version == "3-4"
        assert ADAMConfig(ig_version="1.3").ig_version == "1-3"


class TestAddCt:
    PINNED = "sdtmct-2026-09-25"

    def _codelists(self, path: Path) -> None:
        path.write_text(f'__ct_package__ = "{self.PINNED}"\n', encoding="utf-8")

    def test_c1_283_outside_a_study_the_file_package_is_used(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        from fleet.ct import generator

        self._codelists(tmp_path / "codelists.py")
        monkeypatch.chdir(tmp_path)
        seen: dict[str, str] = {}

        def fake_from_ids(client, ids, *, package, include_docs):
            seen["package"] = package
            raise SystemExit(0)

        monkeypatch.setattr("fleet.ct.api.CDISCClient", _OfflineLibrary)
        monkeypatch.setattr(generator, "extract_ig_concept_ids", lambda *a: {"C66731"})
        monkeypatch.setattr(generator.CodelistGenerator, "from_concept_ids", fake_from_ids)

        assert _run(["add-ct", "--domains", "DM"]) == 0

        assert f"IG / package:   3-4 / {self.PINNED}" in capsys.readouterr().out
        assert seen["package"] == self.PINNED

    def test_c1_283_inside_a_study_another_pin_is_refused(
        self, study: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        self._codelists(study / "metadata" / "sdtm" / "codelists.py")
        monkeypatch.chdir(study)

        assert _run(["add-ct", "--domains", "DM"]) == 1

        assert f"was generated from {self.PINNED}, not sdtmct-2023-12-15" in capsys.readouterr().err


_ADAE = """\
┌─────────┬─────────┬───────┬──────────────────┬──────────┬──────────┐
│ USUBJID ┆ TRTA    ┆ AESER ┆ AEACN            ┆ AEBODSYS ┆ AEDECOD  │
│ ---     ┆ ---     ┆ ---   ┆ ---              ┆ ---      ┆ ---      │
│ str     ┆ str     ┆ str   ┆ str              ┆ str      ┆ str      │
╞═════════╪═════════╪═══════╪══════════════════╪══════════╪══════════╡
│ S001    ┆ Placebo ┆ N     ┆ DOSE NOT CHANGED ┆ CARDIAC  ┆ PALPIT   │
│ S002    ┆ Drug A  ┆ Y     ┆ DRUG WITHDRAWN   ┆ NERVOUS  ┆ HEADACHE │
└─────────┴─────────┴───────┴──────────────────┴──────────┴──────────┘
"""
_ADSL_ARMS = """\
┌─────────┬─────────┬───────┐
│ USUBJID ┆ TRTA    ┆ SAFFL │
│ ---     ┆ ---     ┆ ---   │
│ str     ┆ str     ┆ str   │
╞═════════╪═════════╪═══════╡
│ S001    ┆ Placebo ┆ Y     │
│ S002    ┆ Drug A  ┆ Y     │
└─────────┴─────────┴───────┘
"""


@pytest.fixture
def ae_files(tmp_path: Path) -> list[str]:
    adae, adsl = tmp_path / "adae.csv", tmp_path / "adsl.csv"
    pl.from_repr(_ADAE).write_csv(adae)
    pl.from_repr(_ADSL_ARMS).write_csv(adsl)
    return ["tlg", "export", "--domain", "ae", "--data", str(adae), "--adsl", str(adsl)]


class TestTlg:
    @pytest.mark.parametrize("value", ["0", "-1", "x"])
    def test_c1_312_rows_per_page_must_be_positive(self, value: str, ae_files, capsys) -> None:
        assert _run([*ae_files, "--rows-per-page", value]) == 2

        assert "--rows-per-page" in capsys.readouterr().err

    @pytest.mark.parametrize("fmt", ["rtf", "pptx"])
    def test_c1_312_wrap_is_refused_for_rtf_and_pptx(
        self, fmt: str, ae_files, tmp_path: Path, capsys
    ) -> None:
        wrap = tmp_path / "w.html"
        wrap.write_text("<main>{table}</main>", encoding="utf-8")

        code = _run([*ae_files, "--format", fmt, "--wrap", str(wrap), "-o", str(tmp_path / "x")])

        assert code == 1
        assert "--wrap is an HTML template" in capsys.readouterr().err

    def test_c1_312_a_wrapper_with_no_placeholder_is_refused(
        self, ae_files, tmp_path: Path, capsys
    ) -> None:
        wrap = tmp_path / "w.html"
        wrap.write_text("<main>no placeholder</main>", encoding="utf-8")
        out = tmp_path / "x.html"

        assert _run([*ae_files, "--wrap", str(wrap), "-o", str(out)]) == 1

        assert "has no {table} placeholder" in capsys.readouterr().err
        assert not out.exists()

    def test_c1_312_render_html_refuses_a_wrapper_with_no_placeholder(self) -> None:
        from fleet.tlg import RenderMetadata, ard_to_table_model, render_html

        adae, adsl = pl.from_repr(_ADAE), pl.from_repr(_ADSL_ARMS)
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)
        model = ard_to_table_model(ard, RenderMetadata(title="T"))

        with pytest.raises(ValueError, match="no \\{table\\} placeholder"):
            render_html(model, html_wrapper="<main></main>")

    def test_c1_312_a_page_by_with_no_group_row_warns(
        self, ae_files, tmp_path: Path, capsys
    ) -> None:
        # The renderer refuses a page_by that names no row variable (ml-tlg).
        assert _run([*ae_files, "--page-by", "NOSUCH", "-o", str(tmp_path / "x.html")]) == 1

        assert "page_by 'NOSUCH' is not a row variable" in capsys.readouterr().err

    def test_c1_306_tlg_export_takes_config(
        self, study: Path, ae_files, tmp_path: Path, monkeypatch
    ) -> None:
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        argv = [a for a in ae_files if a != "-o"]

        assert _run([*argv, "--config", str(study / "study_config.yaml")]) == 0

        assert (study / "outputs" / "ae_summary.html").is_file()


_DERIVATIONS = """\
import polars as pl

from fleet.core.derivation import derivation


@derivation
def AGE_c293() -> pl.Expr:
    \"\"\"Age as given.\"\"\"
    return pl.col("age").alias("AGE")
"""


class TestDerivationsModule:
    def _study(self, study: Path, package: str, body: str) -> None:
        pkg = study / package / "derivations"
        pkg.mkdir(parents=True)
        (study / package / "__init__.py").write_text("", encoding="utf-8")
        (pkg / "__init__.py").write_text(body, encoding="utf-8")
        spec = study / "metadata" / "sdtm" / "define.yaml"
        text = _SDTM_DEFINE.replace(
            "datasets:\n", f"derivations_module: {package}.derivations\ndatasets:\n"
        )
        text = text.replace(
            "        derivation:\n          algorithm: assign\n          source: age\n",
            "        derivation:\n          callable: AGE_c293\n",
        )
        spec.write_text(text, encoding="utf-8")

    def test_c1_293_the_module_imports_from_a_subfolder(
        self, study: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.path", [*sys.path])
        self._study(study, "study_c293a", _DERIVATIONS)
        nested = study / "programs" / "adam"
        nested.mkdir(parents=True)
        monkeypatch.chdir(nested)

        assert _run(["run"]) == 0

        assert pl.read_parquet(study / "data" / "sdtm" / "dm.parquet")["AGE"].to_list() == [45, 60]

    def test_c1_293_an_error_in_the_module_is_one_line(
        self, study: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        monkeypatch.setattr("sys.path", [*sys.path])
        self._study(study, "study_c293b", "raise RuntimeError('broken study module')\n")
        monkeypatch.chdir(study)

        assert _run(["run"]) == 1

        err = capsys.readouterr().err
        assert "cannot import derivations_module 'study_c293b.derivations': RuntimeError" in err
        assert "Traceback" not in err


def test_c1_698_regen_tlg_goldens_prints_each_changed_cell() -> None:
    import importlib.util

    script = Path(__file__).parents[2] / "scripts" / "regen_tlg_goldens.py"
    spec = importlib.util.spec_from_file_location("regen_tlg_goldens", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old = pl.from_repr("""\
┌────────┬──────────────┬──────────┬───────────┬──────┐
│ group1 ┆ group1_level ┆ variable ┆ stat_name ┆ stat │
│ ---    ┆ ---          ┆ ---      ┆ ---       ┆ ---  │
│ str    ┆ str          ┆ str      ┆ str       ┆ f64  │
╞════════╪══════════════╪══════════╪═══════════╪══════╡
│ TRTA   ┆ Drug A       ┆ AESER    ┆ n         ┆ 4.0  │
│ TRTA   ┆ Placebo      ┆ AESER    ┆ n         ┆ 2.0  │
└────────┴──────────────┴──────────┴───────────┴──────┘
""")
    new = pl.from_repr("""\
┌────────┬──────────────┬──────────┬───────────┬──────┐
│ group1 ┆ group1_level ┆ variable ┆ stat_name ┆ stat │
│ ---    ┆ ---          ┆ ---      ┆ ---       ┆ ---  │
│ str    ┆ str          ┆ str      ┆ str       ┆ f64  │
╞════════╪══════════════╪══════════╪═══════════╪══════╡
│ TRTA   ┆ Drug A       ┆ AESER    ┆ n         ┆ 5.0  │
│ TRTA   ┆ Drug B       ┆ AESER    ┆ n         ┆ 1.0  │
└────────┴──────────────┴──────────┴───────────┴──────┘
""")

    lines = module.changed_cells("aet01", old, new)

    assert sorted(lines) == [
        "aet01: group1=TRTA group1_level=Drug A variable=AESER stat_name=n: stat: 4.0 -> 5.0",
        "aet01: row added: group1=TRTA group1_level=Drug B variable=AESER stat_name=n",
        "aet01: row removed: group1=TRTA group1_level=Placebo variable=AESER stat_name=n",
    ]
    assert module.changed_cells("aet01", old, old) == []
