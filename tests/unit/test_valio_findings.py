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
            def _get(self, path: str) -> dict:
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
