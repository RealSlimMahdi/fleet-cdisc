"""Regression tests for the alpha-audit medium and low findings in validation and io."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest
import yaml

from fleet.validation.rule_scaffolder import (
    HEADER_RULE_TYPES,
    check_rule,
    scaffold_rule,
)


def _edit_check(path: Path, variable: str = "AETERM") -> None:
    rule = yaml.safe_load(path.read_text(encoding="utf-8"))
    rule["Check"] = {"all": [{"name": variable, "operator": "empty"}]}
    path.write_text(yaml.safe_dump(rule, sort_keys=False), encoding="utf-8")


# ── c1-527 c1-528: add-rule never replaces a file, and sees .yml ──


class TestAddRuleKeepsFiles:
    def test_a_broken_rule_file_is_kept_and_the_next_id_is_taken(self, tmp_path: Path) -> None:
        broken = tmp_path / "FLEET-AE-001.yaml"
        broken.write_text("Core: {Id: FLEET-AE-001\n# MARKER\n", encoding="utf-8")

        out = scaffold_rule(domain="AE", description="d", output_dir=tmp_path)

        assert out.name == "FLEET-AE-002.yaml"
        assert "MARKER" in broken.read_text(encoding="utf-8")

    def test_an_explicit_id_whose_file_holds_another_id_is_refused(self, tmp_path: Path) -> None:
        keep = tmp_path / "KEEP-1.yaml"
        keep.write_text("Core: {Id: SPONSOR-77}\n# MARKER\n", encoding="utf-8")

        with pytest.raises(FileExistsError, match="already exists"):
            scaffold_rule(domain="AE", description="d", output_dir=tmp_path, rule_id="KEEP-1")
        assert "MARKER" in keep.read_text(encoding="utf-8")

    def test_an_existing_yml_rule_blocks_its_id(self, tmp_path: Path) -> None:
        (tmp_path / "FLEET-AE-001.yml").write_text("Core: {Id: FLEET-AE-001}\n", encoding="utf-8")

        out = scaffold_rule(domain="AE", description="d", output_dir=tmp_path)

        assert out.name == "FLEET-AE-002.yaml"

    def test_fleet_check_fails_on_a_duplicate_core_id(self, tmp_path: Path, capsys) -> None:
        from fleet.cli import main

        rules = tmp_path / "rules"
        first = scaffold_rule(domain="AE", description="d", output_dir=rules)
        _edit_check(first)
        second = rules / "copy.yml"
        second.write_text(first.read_text(encoding="utf-8"), encoding="utf-8")
        config = tmp_path / "study_config.yaml"
        config.write_text("study_id: S\nvalidation:\n  custom_rules: rules\n", encoding="utf-8")

        with patch("sys.argv", ["fleet", "check", "--config", str(config)]):
            with pytest.raises(SystemExit) as exc:
                main()

        assert exc.value.code == 1
        assert "duplicate Core.Id FLEET-AE-001" in capsys.readouterr().out


# ── c1-529 c1-530: check_rule placeholder and Exclude scope ──


class TestCheckRuleScope:
    def test_an_unedited_scaffold_gives_one_error(self, tmp_path: Path) -> None:
        out = scaffold_rule(domain="AE", description="d", output_dir=tmp_path)

        errors = check_rule(out)

        assert errors == ["Check still holds the placeholder VARIABLE_NAME: name a real variable"]

    def test_a_rule_scoped_by_exclude_passes(self, tmp_path: Path) -> None:
        out = scaffold_rule(domain="AE", description="d", output_dir=tmp_path)
        _edit_check(out)
        rule = yaml.safe_load(out.read_text(encoding="utf-8"))
        rule["Scope"]["Domains"] = {"Exclude": ["DS"]}
        out.write_text(yaml.safe_dump(rule, sort_keys=False), encoding="utf-8")

        assert check_rule(out) == []


# ── c1-531 c1-532: scaffold header and arguments ──


class TestScaffoldHeader:
    def test_every_rule_type_in_the_header_passes_check_rule(self, tmp_path: Path) -> None:
        out = scaffold_rule(domain="AE", description="d", output_dir=tmp_path)
        header = out.read_text(encoding="utf-8")
        _edit_check(out)
        rule = yaml.safe_load(out.read_text(encoding="utf-8"))

        for rule_type in HEADER_RULE_TYPES:
            assert f"#   {rule_type} " in header
            rule["Rule Type"] = rule_type
            out.write_text(yaml.safe_dump(rule, sort_keys=False), encoding="utf-8")
            assert check_rule(out) == [], rule_type

    def test_the_header_holds_no_machine_path(self, tmp_path: Path) -> None:
        out = scaffold_rule(domain="AE", description="d", output_dir=tmp_path)

        text = out.read_text(encoding="utf-8")

        assert "yaml-language-server" not in text

    @pytest.mark.parametrize(
        ("kwargs", "label"),
        [
            ({"rule_id": "../escaped"}, "rule ID"),
            ({"domain": "A E"}, "domain"),
            ({"prefix": "X/Y"}, "prefix"),
        ],
    )
    def test_a_path_or_space_in_an_id_part_is_refused(
        self, tmp_path: Path, kwargs: dict, label: str
    ) -> None:
        args: dict[str, Any] = {"domain": "AE", "description": "d", "output_dir": tmp_path}
        args.update(kwargs)

        with pytest.raises(ValueError, match=f"Invalid {label}"):
            scaffold_rule(**args)
        assert not (tmp_path.parent / "escaped.yaml").exists()

    def test_add_rule_with_a_path_id_exits_1(self, tmp_path: Path) -> None:
        from fleet.cli import main

        argv = ["fleet", "add-rule", "--domain", "AE", "--description", "d"]
        argv += ["--output", str(tmp_path), "--id", "../x"]
        with patch("sys.argv", argv):
            with pytest.raises(SystemExit) as exc:
                main()

        assert exc.value.code == 1

    def test_each_description_line_is_a_comment(self, tmp_path: Path) -> None:
        out = scaffold_rule(domain="AE", description="first\nCheck: {all: []}", output_dir=tmp_path)

        lines = out.read_text(encoding="utf-8").splitlines()

        assert lines[0] == "# FLEET-AE-001: first"
        assert lines[1] == "# Check: {all: []}"

    @pytest.mark.parametrize(("method", "version"), [("sdtm", "3.4"), ("adam", "1.3")])
    def test_a_dotted_ig_version_asks_the_dashed_library_path(
        self, method: str, version: str
    ) -> None:
        from fleet.core.scaffolder import DefineScaffolder

        asked: list[str] = []

        class _Client:
            def get(self, path: str) -> dict:
                asked.append(path)
                return {}

        scaffolder = DefineScaffolder(cast(Any, _Client()))
        getattr(scaffolder, f"_fetch_{method}_datasets")(version, [])

        assert asked == (
            ["/mdr/sdtmig/3-4/datasets"] if method == "sdtm" else ["/mdr/adam/adamig-1-3"]
        )


# ── c1-522 c1-524 c1-525: fleet install-engine ──


def _zip_bytes(files: dict[str, bytes]) -> bytes:
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


class TestInstallEngine:
    @pytest.fixture
    def eng(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        from fleet.validation import engine as eng

        monkeypatch.setattr(eng, "ENGINE_DIR", tmp_path / "cdisc-rules-engine")
        old = eng.engine_path()
        old.parent.mkdir(parents=True)
        old.write_text("old binary", encoding="utf-8")
        return eng

    def _serve(self, monkeypatch: pytest.MonkeyPatch, archive: bytes, digest: str | None):
        httpx = pytest.importorskip("httpx")
        from fleet.validation import engine as eng

        keyword = eng._platform_asset_keywords()[0]
        asset = {"name": f"core-{keyword}.zip", "browser_download_url": "https://dl/x.zip"}
        if digest is not None:
            asset["digest"] = digest
        asked: list[str] = []

        def handler(request: Any) -> Any:
            asked.append(str(request.url))
            if request.url.host == "dl":
                return httpx.Response(200, content=archive)
            return httpx.Response(200, json={"tag_name": "v0.15", "assets": [asset]})

        real = httpx.Client
        monkeypatch.setattr(
            httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw)
        )
        return asked

    def test_a_bundle_with_no_executable_keeps_the_old_engine(
        self, eng: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._serve(monkeypatch, _zip_bytes({"bundle/readme.txt": b"x"}), None)

        with pytest.raises(RuntimeError, match="holds no"):
            eng.install_engine(force=True)
        assert eng.engine_path().read_text(encoding="utf-8") == "old binary"

    def test_a_broken_archive_is_a_runtime_error(
        self, eng: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._serve(monkeypatch, b"not a zip", None)

        with pytest.raises(RuntimeError, match="BadZipFile"):
            eng.install_engine(force=True)
        assert eng.engine_path().read_text(encoding="utf-8") == "old binary"

    def test_a_network_error_is_a_runtime_error_with_a_hint(
        self, eng: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        httpx = pytest.importorskip("httpx")

        def refuse(request: Any) -> Any:
            raise httpx.ConnectError("[Errno 61] Connection refused", request=request)

        real = httpx.Client
        monkeypatch.setattr(
            httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(refuse), **kw)
        )

        with pytest.raises(RuntimeError, match="ConnectError.*proxy or the GitHub rate limit"):
            eng.install_engine(force=True)

    def test_a_digest_mismatch_stops_before_extraction(
        self, eng: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        archive = _zip_bytes({"core/core": b"new", "core/core.exe": b"new"})
        self._serve(monkeypatch, archive, "sha256:" + "0" * 64)

        with pytest.raises(RuntimeError, match="digest mismatch"):
            eng.install_engine(force=True)
        assert eng.engine_path().read_text(encoding="utf-8") == "old binary"

    def test_a_matching_digest_installs(self, eng: Any, monkeypatch: pytest.MonkeyPatch) -> None:
        import hashlib

        archive = _zip_bytes({"core/core": b"new", "core/core.exe": b"new"})
        self._serve(monkeypatch, archive, "sha256:" + hashlib.sha256(archive).hexdigest())

        dest = eng.install_engine(force=True)

        assert dest.read_text(encoding="utf-8") == "new"

    def test_the_printed_version_maps_to_its_release_tag(
        self, eng: Any, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        archive = _zip_bytes({"core/core": b"new", "core/core.exe": b"new"})
        asked = self._serve(monkeypatch, archive, None)

        eng.install_engine(version="0.15.0", force=True)

        assert asked[0].endswith("/releases/tags/v0.15")

    def test_an_installed_engine_says_the_requested_version_was_not_installed(
        self, eng: Any, capsys: pytest.CaptureFixture
    ) -> None:
        eng.install_engine(version="v9.9")

        assert "CORE v9.9 was not installed; use --force" in capsys.readouterr().out


# ── c1-244: install hints work in a user project ──


def test_no_install_hint_names_a_repo_only_command_or_a_missing_extra() -> None:
    import fleet

    src = Path(fleet.__file__).parent
    offenders = [
        f"{path.relative_to(src)}: {needle}"
        for path in src.rglob("*.py")
        for needle in ("uv sync --extra", "clinical-io")
        if needle in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


# ── c1-834 c1-241 c1-836: the directory sweep ──


def _write_study(root: Path, body: str = "") -> Path:
    cfg = root / "study_config.yaml"
    cfg.write_text("study_id: S01\n" + body, encoding="utf-8")
    return cfg


def _dataset_json(path: Path) -> None:
    import polars as pl

    from fleet.io.dataset_json import save_dataset_json

    save_dataset_json(pl.DataFrame({"USUBJID": ["S1-001"]}), path, domain=path.stem.upper())


class TestSweep:
    def test_upper_case_suffixes_and_dataset_json_are_swept_others_skipped(
        self, tmp_path: Path
    ) -> None:
        from fleet.validation.run_setup import build_sweep

        data = tmp_path / "mixed"
        data.mkdir()
        for name in ("dm.parquet", "AE.XPT"):
            (data / name).write_bytes(b"x")
        _dataset_json(data / "vs.json")
        (data / "pipeline_dag.json").write_text('{"nodes": []}', encoding="utf-8")
        (data / ".hidden.parquet").write_bytes(b"x")

        sweep = build_sweep([data], environ={}, start=tmp_path)

        assert [d.path.name for d in sweep.datasets] == ["AE.XPT", "dm.parquet", "vs.json"]
        assert [p.name for p in sweep.skipped] == ["pipeline_dag.json"]

    def test_fleet_validate_names_each_skipped_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        from fleet.cli import main

        monkeypatch.chdir(tmp_path)
        (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
        with patch("sys.argv", ["fleet", "validate", str(tmp_path)]):
            with pytest.raises(SystemExit):
                main()

        assert "Skipped: notes.txt" in capsys.readouterr().err

    def test_a_folder_both_standards_share_is_swept_once_by_file_name(self, tmp_path: Path) -> None:
        from fleet.validation.run_setup import build_sweep

        _write_study(tmp_path, "paths:\n  sdtm_data: data\n  adam_data: data\n")
        (tmp_path / "data").mkdir()
        for name in ("dm.parquet", "adsl.parquet"):
            (tmp_path / "data" / name).write_bytes(b"x")
        (tmp_path / "core").touch()

        sweep = build_sweep(
            config=tmp_path / "study_config.yaml", engine=tmp_path / "core", environ={}
        )

        by_name = {d.name: d.setup.standard.value for d in sweep.datasets if d.setup}
        assert by_name == {"ADSL": "adam", "DM": "sdtm"}
        assert sweep.could_not_run == []

    def test_a_nested_adam_folder_names_adam(self, tmp_path: Path) -> None:
        from fleet.validation.run_setup import build_run_setup

        _write_study(tmp_path, "paths:\n  sdtm_data: data\n  adam_data: data/adam\n")
        (tmp_path / "data" / "adam").mkdir(parents=True)

        adsl = build_run_setup(path=tmp_path / "data" / "adam" / "adsl.parquet", start=tmp_path)
        dm = build_run_setup(path=tmp_path / "data" / "dm.parquet", start=tmp_path)

        assert (adsl.standard.value, dm.standard.value) == ("adam", "sdtm")

    def test_an_adam_name_in_the_sdtm_folder_is_still_refused(self, tmp_path: Path) -> None:
        from fleet.core.exceptions import ValidationSetupError
        from fleet.validation.run_setup import build_run_setup

        _write_study(tmp_path)
        (tmp_path / "data" / "sdtm").mkdir(parents=True)

        with pytest.raises(ValidationSetupError, match="standard unclear"):
            build_run_setup(path=tmp_path / "data" / "sdtm" / "adsl.parquet", start=tmp_path)


# ── c1-838: ValidationService refuses an unsupported IG version ──


class TestServiceVersion:
    @pytest.mark.parametrize("version", ["banana", "3.1.3"])
    def test_an_unsupported_version_is_refused(self, version: str) -> None:
        from unittest.mock import MagicMock

        import polars as pl

        from fleet.core.exceptions import ValidationSetupError
        from fleet.validation import ValidationService

        provider = MagicMock()
        svc = ValidationService(provider=provider)

        with pytest.raises(ValidationSetupError, match=f"SDTMIG {version}"):
            svc.validate_sdtm(pl.DataFrame({"A": [1]}), domain="AE", version=version)
        with pytest.raises(ValidationSetupError):
            svc.validate_datasets(
                {"AE": pl.DataFrame({"A": [1]})}, standard="sdtm", version=version
            )
        provider.validate_sdtm.assert_not_called()

    @pytest.mark.parametrize("version", ["3.4", "3-4"])
    def test_a_supported_version_runs(self, version: str) -> None:
        from unittest.mock import MagicMock

        import polars as pl

        from fleet.validation import ValidationService

        provider = MagicMock()
        ValidationService(provider=provider).validate_sdtm(
            pl.DataFrame({"A": [1]}), domain="AE", version=version
        )

        assert provider.validate_sdtm.call_args.kwargs["version"] == "3.4"

    def test_validate_core_refuses_3_1_3(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import polars as pl

        from fleet.core.exceptions import ValidationSetupError
        from fleet.define_xml.checker import DatasetChecker

        monkeypatch.chdir(tmp_path)
        checker = DatasetChecker.__new__(DatasetChecker)
        checker._data = {"study": {"standard": "SDTMIG", "standard_version": "3.1.3"}}

        with pytest.raises(ValidationSetupError, match="SDTMIG 3.1.3"):
            checker.validate_core(pl.DataFrame({"A": [1]}), "AE")


# ── c1-523: an absent pinned engine is refused, never replaced ──


class TestPinnedEngine:
    @pytest.fixture
    def study(self, tmp_path: Path) -> Path:
        _write_study(tmp_path, "validation:\n  engine_path: tools/core/core\n")
        managed = tmp_path / "managed-core"
        managed.touch()
        return tmp_path

    def test_the_run_setup_has_no_engine_and_names_the_pin(self, study: Path) -> None:
        from fleet.validation.run_setup import build_run_setup, missing_engine_reason

        setup = build_run_setup(
            name="AE",
            namespace="sdtm",
            start=study,
            environ={"FLEET_RULES_ENGINE": str(study / "managed-core")},
        )

        assert (setup.engine.value, setup.engine.source) == (None, "study config")
        assert "tools/core/core" in missing_engine_reason(setup)

    def test_the_verb_refuses(self, study: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        import polars as pl

        from fleet.core.exceptions import ValidationSetupError

        monkeypatch.chdir(study)
        monkeypatch.setenv("FLEET_RULES_ENGINE", str(study / "managed-core"))
        ae = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ S1-002  │
└─────────┘
""")

        with pytest.raises(ValidationSetupError, match="tools/core/core"):
            ae.sdtm.validate("AE")

    def test_fleet_check_warns_with_the_pinned_path(
        self, study: Path, monkeypatch: pytest.MonkeyPatch, capsys
    ) -> None:
        from fleet.cli import main

        monkeypatch.setenv("FLEET_RULES_ENGINE", str(study / "managed-core"))
        argv = ["fleet", "check", "--config", str(study / "study_config.yaml")]
        with patch("sys.argv", argv):
            try:
                main()
            except SystemExit:
                pass

        out = capsys.readouterr().out
        assert "[WARN] rules engine" in out
        assert "tools/core/core" in out
        assert "[PASS] rules engine" not in out


# ── c1-265 c1-267 c1-831: reading the engine report ──


def _validator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, report: dict) -> Any:
    import json
    import subprocess

    from fleet.validation import official

    exe = tmp_path / "core"
    exe.touch()

    def fake(cmd: list[str], *, cwd: str, timeout: float) -> Any:
        out = Path(cmd[cmd.index("-o") + 1]).with_suffix(".json")
        out.write_text(json.dumps(report), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(official, "_run_command", fake)
    return official.OfficialCDISCValidator(exe)


def _detail(rule: str, dataset: str, **extra: Any) -> dict:
    return {"core_id": rule, "message": f"{rule} fired", "dataset": dataset, **extra}


def _frames(*names: str) -> dict:
    import polars as pl

    return {name: pl.DataFrame({"USUBJID": ["S1-001"]}) for name in names}


class TestEngineReport:
    def test_an_issue_reported_rule_with_no_readable_finding_could_not_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        report = {
            "Rules_Report": [{"core_id": "CORE-1", "status": "ISSUE REPORTED"}],
            "IssueDetails": [_detail("CORE-1", "AE.json")],
        }

        result = _validator(tmp_path, monkeypatch, report).validate_datasets(
            _frames("AE"), standard="sdtmig", version="3-4"
        )["AE"]

        assert result.could_not_run is not None
        assert "cannot read this CORE report format" in result.could_not_run
        assert not result.is_valid

    def test_a_split_pair_is_attached_once_and_summary_rules_add_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        report = {
            "Rules_Report": [
                {"core_id": rid, "status": "ISSUE_REPORTED"} for rid in ("CORE-1", "CORE-2")
            ],
            "Issue_Details": [
                _detail("CORE-1", "AE.json"),
                _detail("CORE-2", "LBCH.JSON, LBHM"),
                _detail("CORE-1", "STUDY"),
            ],
            "Issue_Summary": [
                {"core_id": "CORE-9", "dataset": "LBCH.JSON, LBHM", "message": "x", "issues": 1}
            ],
        }

        results = _validator(tmp_path, monkeypatch, report).validate_datasets(
            _frames("AE", "LBCH", "LBHM"), standard="sdtmig", version="3-4"
        )

        assert sorted(results) == ["AE", "LBCH", "LBHM", "STUDY"]
        assert sum(len(r.errors) for r in results.values()) == 3
        (pair,) = results["LBCH"].errors
        assert (pair.rule_id, pair.message) == ("CORE-2", "CORE-2 fired (also: LBHM)")

    def test_a_finding_keeps_the_record_the_engine_names(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        detail = _detail(
            "CORE-1", "AE.json", USUBJID="S1-002", SEQ=1, row=3, variables=["AESER"], values=["YES"]
        )
        report = {"Rules_Report": [{"core_id": "CORE-1", "status": "SUCCESS"}]}
        report["Issue_Details"] = [detail]

        (issue,) = (
            _validator(tmp_path, monkeypatch, report)
            .validate_datasets(_frames("AE"), standard="sdtmig", version="3-4")["AE"]
            .errors
        )

        assert (issue.row, issue.usubjid, issue.seq, issue.values) == (3, "S1-002", 1, ["YES"])
        assert issue.variable == "AESER"
        assert "USUBJID: S1-002" in str(issue)

    @pytest.mark.parametrize(
        ("variables", "values", "expected"),
        [
            (
                ["AESTDY", "AESTDTC", "$val_stdy", "RFSTDTC"],
                ["1", "a", "2", "b"],
                "AESTDY, AESTDTC, RFSTDTC",
            ),
            (["$records_in_dataset"], [0], None),
            (["variable_name"], ["AETERM"], None),
        ],
    )
    def test_the_variable_field_holds_only_dataset_variables(
        self, variables: list, values: list, expected: str | None
    ) -> None:
        from fleet.validation.official import _resolve_variable_field

        item = {"core_id": "CORE-7", "variables": variables, "values": values}

        assert _resolve_variable_field(item) == expected


# ── c1-832: the HTML page groups identical findings ──


def test_identical_findings_give_one_html_row(tmp_path: Path) -> None:
    from fleet.validation.models import (
        Severity,
        ValidationIssue,
        ValidationResult,
        write_html_report,
    )

    issues = [
        ValidationIssue(
            Severity.ERROR, "CORE-000701", "EPOCH", variable="EPOCH", row=n, usubjid=f"S-{n}"
        )
        for n in range(1, 1001)
    ]
    result = ValidationResult("LB", "sdtmig", "3-4", total_issues=1000, errors=issues)

    page = Path(write_html_report([result], tmp_path / "r.html")).read_text(encoding="utf-8")

    assert page.count("<td>CORE-000701</td>") == 1
    assert "<td>1-1000 (1000)</td>" in page
    assert "S-20; and 980 more" in page
    assert "S-21" not in page


# ── c1-830: a finding on several variables names the verbs ──


class TestLineageJoin:
    def _issue(self, variable: str) -> Any:
        from fleet.validation.models import Severity, ValidationIssue, ValidationResult

        issue = ValidationIssue(Severity.ERROR, "CORE-000544", "m", variable=variable)
        return issue, ValidationResult("AE", "sdtmig", "3-4", errors=[issue])

    def _lineage(self) -> list:
        from types import SimpleNamespace

        return [
            SimpleNamespace(name=n, verb="assign", method="fleet.x.assign")
            for n in ("AESER", "AESEQ", "USUBJID")
        ]

    def test_several_variables_name_each_verb_with_its_variables(self) -> None:
        from fleet.validation.lineage_join import enrich_with_lineage

        issue, result = self._issue("AESEQ, USUBJID, POOLID")
        enrich_with_lineage(result, self._lineage())

        assert issue.producing_verb == "assign (AESEQ, USUBJID)"
        assert issue.verb_method == "fleet.x.assign"

    def test_one_variable_keeps_the_bare_verb(self) -> None:
        from fleet.validation.lineage_join import enrich_with_lineage

        issue, result = self._issue("AESER")
        enrich_with_lineage(result, self._lineage())

        assert issue.producing_verb == "assign"

    def test_more_than_five_names_get_no_verb(self) -> None:
        from fleet.validation.lineage_join import enrich_with_lineage

        issue, result = self._issue("AESER, AESEQ, USUBJID, A, B, C")
        enrich_with_lineage(result, self._lineage())

        assert issue.producing_verb is None


# ── c1-267: the MCP tool returns the study-level findings ──


def test_fleet_validate_mcp_returns_study_issues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import polars as pl

    from fleet import mcp_server
    from fleet.validation import ValidationService
    from fleet.validation.models import Severity, ValidationIssue, ValidationResult

    exe = tmp_path / "core"
    exe.touch()
    monkeypatch.setenv("FLEET_RULES_ENGINE", str(exe))
    data = tmp_path / "ae.parquet"
    pl.DataFrame({"USUBJID": ["S1-001"]}).write_parquet(data)
    study = ValidationIssue(Severity.ERROR, "CORE-000400", "TS is missing")

    def fake(self: Any, datasets: dict, **kwargs: Any) -> dict:
        return {
            "AE": ValidationResult("AE", "sdtmig", "3-4", rules_executed=1),
            "STUDY": ValidationResult("STUDY", "sdtmig", "3-4", errors=[study]),
        }

    monkeypatch.setattr(ValidationService, "__init__", lambda self, **kw: None)
    monkeypatch.setattr(ValidationService, "validate_datasets", fake)

    out = mcp_server.fleet_validate(str(data))

    assert [i["rule_id"] for i in out["study_issues"]] == ["CORE-000400"]
    assert [i["dataset"] for i in out["issues"]] == ["STUDY"]


# ── io: c1-580 c1-581 c1-582 c1-583 c1-584 Dataset-JSON ──

_DM = """\
┌─────────┬─────────┬─────┐
│ STUDYID ┆ USUBJID ┆ AGE │
│ ---     ┆ ---     ┆ --- │
│ str     ┆ str     ┆ i64 │
╞═════════╪═════════╪═════╡
│ S1      ┆ S1-001  ┆ 63  │
│ S1      ┆ S1-002  ┆ 70  │
│ S1      ┆ S1-003  ┆ 55  │
└─────────┴─────────┴─────┘
"""


class TestDatasetJson:
    def _saved(self, tmp_path: Path) -> tuple[Path, dict]:
        import json

        import polars as pl

        from fleet.io.dataset_json import save_dataset_json

        path = save_dataset_json(pl.from_repr(_DM), tmp_path / "dm.json", domain="DM")
        return path, json.loads(path.read_text(encoding="utf-8"))

    @pytest.mark.parametrize(
        ("edit", "match"),
        [
            (lambda raw: raw["rows"].pop(), "records 3, rows 2"),
            (lambda raw: raw.update(records=1), "records 1, rows 3"),
            (lambda raw: raw["rows"][0].append("extra"), "row 1: 4 cell"),
            (lambda raw: raw["rows"][1].pop(), "row 2: 2 cell"),
        ],
    )
    def test_a_malformed_file_is_refused(self, tmp_path: Path, edit: Any, match: str) -> None:
        import json

        from fleet.core.exceptions import FleetIOError
        from fleet.io.dataset_json import read_dataset_json

        path, raw = self._saved(tmp_path)
        edit(raw)
        path.write_text(json.dumps(raw), encoding="utf-8")

        with pytest.raises(FleetIOError, match=match):
            read_dataset_json(path)

    def test_zero_records_with_no_rows_reads(self, tmp_path: Path) -> None:
        import polars as pl

        from fleet.io.dataset_json import read_dataset_json, save_dataset_json

        empty = pl.from_repr(_DM).head(0)
        path = save_dataset_json(empty, tmp_path / "dm.json", domain="DM")

        assert read_dataset_json(path).height == 0

    def test_ndjson_is_refused_on_write_and_read(self, tmp_path: Path) -> None:
        import polars as pl

        from fleet.core.exceptions import FleetIOError
        from fleet.io.dataset_json import read_dataset_json, save_dataset_json

        with pytest.raises(FleetIOError, match="NDJSON is not supported"):
            save_dataset_json(pl.from_repr(_DM), tmp_path / "w.ndjson", domain="DM")
        (tmp_path / "r.ndjson").write_text("{}\n{}\n", encoding="utf-8")
        with pytest.raises(FleetIOError, match="NDJSON is not supported"):
            read_dataset_json(tmp_path / "r.ndjson")

    def test_decimal_and_float32_are_written_as_shown(self, tmp_path: Path) -> None:
        import json
        from decimal import Decimal

        import polars as pl

        from fleet.io.dataset_json import read_dataset_json, save_dataset_json

        df = pl.DataFrame(
            {
                "C_DEC": pl.Series([Decimal("1.25")], dtype=pl.Decimal(20, 13)),
                "C_F32": pl.Series([1.1], dtype=pl.Float32),
            }
        )
        path = save_dataset_json(df, tmp_path / "x.json", domain="X")
        raw = json.loads(path.read_text(encoding="utf-8"))

        types = {c["name"]: c["dataType"] for c in raw["columns"]}
        assert types == {"C_DEC": "decimal", "C_F32": "float"}
        assert raw["rows"][0][1] == 1.1
        assert read_dataset_json(path)["C_DEC"].to_list() == [1.25]

    def test_header_names_fleet_utc_and_a_unique_file_oid(self, tmp_path: Path) -> None:
        import polars as pl

        from fleet.io.dataset_json import save_dataset_json

        path = save_dataset_json(
            pl.from_repr(_DM), tmp_path / "dm2.json", domain="DM", originator="ACME Pharma"
        )
        import json

        raw = json.loads(path.read_text(encoding="utf-8"))
        created = raw["datasetJSONCreationDateTime"]

        assert raw["sourceSystem"]["name"] == "Fleet"
        assert raw["originator"] == "ACME Pharma"
        assert created.endswith("Z")
        assert raw["fileOID"] == f"S1.DM.{created[:-1]}"

    def test_a_multi_slice_file_reads_back_equal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import polars as pl
        from polars.testing import assert_frame_equal

        from fleet.io import dataset_json
        from fleet.io.dataset_json import read_dataset_json, save_dataset_json

        monkeypatch.setattr(dataset_json, "_SLICE_ROWS", 2)
        dm = pl.from_repr(_DM)

        path = save_dataset_json(dm, tmp_path / "dm.json", domain="DM")

        assert_frame_equal(read_dataset_json(path), dm)


# ── io: c1-240 c1-243 c2-948 c1-239 loaders ──


class TestLoaders:
    @pytest.mark.parametrize("suffix", [".parquet", ".csv"])
    def test_glob_characters_in_a_file_name_are_literal(self, tmp_path: Path, suffix: str) -> None:
        import polars as pl

        from fleet.io.loaders import load_raw_data

        for name, x in ((f"adsl[1]{suffix}", 1), (f"adsl1{suffix}", 999)):
            frame = pl.DataFrame({"X": [x]})
            if suffix == ".csv":
                frame.write_csv(tmp_path / name)
            else:
                frame.write_parquet(tmp_path / name)

        out = load_raw_data(tmp_path / f"adsl[1]{suffix}").collect()

        assert out["X"].to_list() == [1]

    @pytest.mark.parametrize("as_text", [True, False])
    def test_load_study_context_takes_a_text_path(self, tmp_path: Path, as_text: bool) -> None:
        from fleet.core.study_context import load_study_context

        cfg = _write_study(tmp_path)

        ctx = load_study_context(str(cfg) if as_text else cfg)

        assert ctx.study_root == tmp_path

    @pytest.mark.parametrize("as_text", [True, False])
    def test_download_raw_data_takes_a_text_path(self, tmp_path: Path, as_text: bool) -> None:
        from fleet.io.loaders import download_raw_data

        existing = tmp_path / "dm.csv"
        existing.write_text("A\n1\n", encoding="utf-8")

        out = download_raw_data("https://unused", str(existing) if as_text else existing)

        assert out == existing

    def test_file_type_xpt_reads_a_renamed_transport_file(self, tmp_path: Path) -> None:
        import polars as pl

        pyreadstat = pytest.importorskip("pyreadstat")
        from fleet.io.loaders import load_raw_data

        te = tmp_path / "te.sas7bdat"
        pyreadstat.write_xport(
            pl.DataFrame({"ETCD": ["SCRN"]}), str(te), file_format_version=5, table_name="TE"
        )

        assert load_raw_data(te, file_type="xpt").collect()["ETCD"].to_list() == ["SCRN"]

    def test_a_special_missing_value_reads_as_null(self, tmp_path: Path) -> None:
        import polars as pl

        pyreadstat = pytest.importorskip("pyreadstat")
        from fleet.io.loaders import load_raw_data

        qs = tmp_path / "qs.xpt"
        frame = pl.DataFrame({"QSSTRESN": [None]}, schema={"QSSTRESN": pl.Float64})
        pyreadstat.write_xport(frame, str(qs), file_format_version=5, table_name="QS")
        data = bytearray(qs.read_bytes())
        missing = data.rfind(b".\x00\x00\x00\x00\x00\x00\x00")
        assert missing > 0
        data[missing] = ord("A")  # .A: SAS special missing "not asked"
        qs.write_bytes(bytes(data))

        assert load_raw_data(qs).collect()["QSSTRESN"].to_list() == [None]


# ── c1-245: fleet run --overwrite, and library hints in CLI words ──


class TestRunOverwrite:
    @pytest.fixture
    def study(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        import polars as pl

        from tests.unit.test_cli import _CONFIG, _SDTM_DEFINE

        (tmp_path / "study_config.yaml").write_text(_CONFIG, encoding="utf-8")
        sdtm = tmp_path / "metadata" / "sdtm"
        sdtm.mkdir(parents=True)
        (sdtm / "define.yaml").write_text(_SDTM_DEFINE, encoding="utf-8")
        raw = tmp_path / "data" / "raw"
        raw.mkdir(parents=True)
        pl.from_repr("""\
┌────────────────┬─────┬─────┐
│ patient_number ┆ age ┆ AGE │
│ ---            ┆ --- ┆ --- │
│ str            ┆ i64 ┆ i64 │
╞════════════════╪═════╪═════╡
│ P1             ┆ 45  ┆ 1   │
└────────────────┴─────┴─────┘
""").write_csv(raw / "dm.csv")
        monkeypatch.chdir(tmp_path)
        return tmp_path

    def _run(self, *extra: str) -> int:
        from fleet.cli import main

        with patch("sys.argv", ["fleet", "run", "--dataset", "DM", *extra]):
            try:
                main()
            except SystemExit as exc:
                return int(exc.code or 0)
        return 0

    def test_the_guard_names_the_cli_flag(self, study: Path, capsys) -> None:
        assert self._run() == 1

        err = capsys.readouterr().err
        assert "Pass --overwrite to allow spec overwrites" in err
        assert "overwrite=True" not in err

    def test_overwrite_passes_the_guard(self, study: Path) -> None:
        import polars as pl

        assert self._run("--overwrite") == 0
        assert pl.read_parquet(study / "data" / "sdtm" / "dm.parquet")["AGE"].to_list() == [45]

    def test_strict_false_reads_as_no_strict(self) -> None:
        from fleet.cli import _cli_spec_hints
        from fleet.core.exceptions import SpecError

        def built():
            raise SpecError("x: unknown algorithm 'y'. Pass strict=False to warn and skip instead.")
            yield

        with pytest.raises(SpecError, match="Pass --no-strict to warn and skip instead"):
            list(_cli_spec_hints(built()))


# ── c1-837: the bundled rule schema follows CORE 0.15.0 ──


def test_check_rule_accepts_a_core_0_15_operator(tmp_path: Path) -> None:
    import json

    from fleet.validation.rule_scaffolder import _SCHEMA_PATH

    out = scaffold_rule(domain="AE", description="d", output_dir=tmp_path)
    _edit_check(out)
    rule = yaml.safe_load(out.read_text(encoding="utf-8"))
    rule["Check"] = {
        "all": [{"name": "AESEV", "operator": "references_correct_codelist", "value": "C66769"}]
    }
    out.write_text(yaml.safe_dump(rule, sort_keys=False), encoding="utf-8")

    assert check_rule(out) == []
    assert "CORE 0.15.0" in json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))["$comment"]
