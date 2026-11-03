"""Run setup: the resolved inputs of one validation, with the source of each.

Builder-seam tests use a temporary study config and data directories and pass
the environment as a mapping. No engine runs. The verb tests at the end run a
fake engine: ``subprocess.run`` is captured, the engine path is a plain file.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import polars as pl
import pytest

from fleet.core.exceptions import ValidationError, ValidationSetupError
from fleet.validation.engine import VERSION_MARKER
from fleet.validation.run_setup import Resolved, build_run_setup


def _study(root: Path, body: str = "") -> Path:
    """Write a study_config.yaml under *root* and return its path."""
    cfg = root / "study_config.yaml"
    cfg.write_text("study_id: S01\n" + body, encoding="utf-8")
    return cfg


class TestOutsideAStudy:
    def test_built_in_defaults_apply(self, tmp_path: Path) -> None:
        setup = build_run_setup(name="AE", namespace="sdtm", start=tmp_path, environ={})

        assert setup.standard.value == "sdtm"
        assert setup.ig_version.value == "3.4"
        assert setup.ig_version.source == "default"
        assert setup.custom_rules.value is None
        assert setup.study_config is None

    def test_adam_default_is_1_3(self, tmp_path: Path) -> None:
        setup = build_run_setup(name="ADSL", namespace="adam", start=tmp_path, environ={})

        assert setup.ig_version.value == "1.3"

    def test_environment_engine_applies(self, tmp_path: Path) -> None:
        env_engine = tmp_path / "env-core"
        env_engine.touch()

        setup = build_run_setup(
            name="AE",
            namespace="sdtm",
            start=tmp_path,
            environ={"FLEET_RULES_ENGINE": str(env_engine)},
        )

        assert setup.engine.value == env_engine
        assert setup.engine.source == "environment"


class TestInsideAStudy:
    @pytest.fixture
    def study(self, tmp_path: Path) -> Path:
        (tmp_path / "rules").mkdir()
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "core").touch()
        _study(
            tmp_path,
            "sdtm:\n  ig_version: 3-3\n"
            "adam:\n  ig_version: 1-1\n"
            "validation:\n  custom_rules: rules\n  engine_path: bin/core\n",
        )
        nested = tmp_path / "programs" / "qc"
        nested.mkdir(parents=True)
        return tmp_path

    def test_study_config_supplies_every_input(self, study: Path) -> None:
        setup = build_run_setup(
            name="ADAE", namespace="adam", start=study / "programs" / "qc", environ={}
        )

        assert setup.ig_version == Resolved("1.1", "study config")
        assert setup.custom_rules.value == study / "rules"
        assert setup.custom_rules.source == "study config"
        assert setup.engine.value == study / "bin" / "core"
        assert setup.engine.source == "study config"
        assert setup.study_config == study / "study_config.yaml"

    def test_arguments_override_the_study_config(self, study: Path, tmp_path: Path) -> None:
        own_rules = study / "my_rules"
        own_rules.mkdir()
        own_engine = study / "own-core"
        own_engine.touch()

        setup = build_run_setup(
            name="AE",
            namespace="sdtm",
            version="3.4",
            custom_rules=own_rules,
            engine=own_engine,
            start=study,
            environ={},
        )

        assert setup.ig_version == Resolved("3.4", "argument")
        assert setup.custom_rules == Resolved(own_rules, "argument")
        assert setup.engine == Resolved(own_engine, "argument")

    def test_study_config_engine_beats_the_environment(self, study: Path) -> None:
        env_engine = study / "env-core"
        env_engine.touch()

        setup = build_run_setup(
            name="AE",
            namespace="sdtm",
            start=study,
            environ={"FLEET_RULES_ENGINE": str(env_engine)},
        )

        assert setup.engine == Resolved(study / "bin" / "core", "study config")

    def test_missing_custom_rules_directory_is_refused(self, tmp_path: Path) -> None:
        _study(tmp_path, "validation:\n  custom_rules: nowhere\n")

        with pytest.raises(ValidationSetupError, match="nowhere"):
            build_run_setup(name="AE", namespace="sdtm", start=tmp_path, environ={})

    def test_invalid_study_config_is_refused(self, tmp_path: Path) -> None:
        (tmp_path / "study_config.yaml").write_text("sdtm: [\n", encoding="utf-8")

        with pytest.raises(ValidationSetupError, match="study config"):
            build_run_setup(name="AE", namespace="sdtm", start=tmp_path, environ={})


class TestIgVersion:
    @pytest.mark.parametrize("given", ["3-4", "3.4"])
    def test_dashed_and_dotted_give_the_same_setup(self, tmp_path: Path, given: str) -> None:
        setup = build_run_setup(
            name="AE", namespace="sdtm", version=given, start=tmp_path, environ={}
        )

        assert setup.ig_version.value == "3.4"
        assert setup.engine_ig_version == "3-4"

    def test_sdtmig_3_1_3_is_refused_with_the_supported_versions(self, tmp_path: Path) -> None:
        with pytest.raises(ValidationSetupError, match=r"3\.2, 3\.3, 3\.4"):
            build_run_setup(name="AE", namespace="sdtm", version="3.1.3", start=tmp_path)

    def test_unsupported_study_version_is_refused(self, tmp_path: Path) -> None:
        _study(tmp_path, "adam:\n  ig_version: 2-0\n")

        with pytest.raises(ValidationSetupError, match="study config"):
            build_run_setup(name="ADSL", namespace="adam", start=tmp_path, environ={})


class TestStandard:
    @pytest.fixture
    def study(self, tmp_path: Path) -> Path:
        _study(tmp_path)
        for sub in ("sdtm", "adam"):
            (tmp_path / "data" / sub).mkdir(parents=True)
        return tmp_path

    @pytest.mark.parametrize(
        ("namespace", "name"), [("adam", "AE"), ("sdtm", "ADAE")], ids=["adam-AE", "sdtm-ADAE"]
    )
    def test_namespace_and_dataset_name_conflict_is_refused(
        self, tmp_path: Path, namespace: str, name: str
    ) -> None:
        with pytest.raises(ValidationSetupError, match="standard unclear"):
            build_run_setup(name=name, namespace=namespace, start=tmp_path, environ={})

    def test_configured_data_directory_names_the_standard(self, study: Path) -> None:
        setup = build_run_setup(
            path=study / "data" / "adam" / "adsl.parquet", start=study, environ={}
        )

        assert setup.standard == Resolved("adam", "data directory")

    def test_ad_prefix_names_the_standard_of_an_explicit_path(self, tmp_path: Path) -> None:
        adae = build_run_setup(path=tmp_path / "adae.parquet", start=tmp_path, environ={})
        ae = build_run_setup(path=tmp_path / "ae.parquet", start=tmp_path, environ={})

        assert adae.standard == Resolved("adam", "dataset name")
        assert ae.standard == Resolved("sdtm", "dataset name")

    def test_directory_and_prefix_conflict_is_refused(self, study: Path) -> None:
        with pytest.raises(ValidationSetupError, match="standard unclear"):
            build_run_setup(path=study / "data" / "adam" / "dm.parquet", start=study, environ={})

    def test_explicit_standard_forces_it(self, study: Path) -> None:
        setup = build_run_setup(
            path=study / "data" / "adam" / "dm.parquet", standard="sdtm", start=study, environ={}
        )

        assert setup.standard == Resolved("sdtm", "argument")


class TestEngineVersion:
    @pytest.fixture
    def engine(self, tmp_path: Path) -> Path:
        exe = tmp_path / "core" / "core"
        exe.parent.mkdir()
        exe.touch()
        return exe

    def _version_command(
        self, monkeypatch: pytest.MonkeyPatch, rc: int, stdout: str = ""
    ) -> list[list[str]]:
        calls: list[list[str]] = []

        def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, rc, stdout, "")

        monkeypatch.setattr("fleet.validation.engine.subprocess.run", run)
        return calls

    def _setup(self, engine: Path, tmp_path: Path):
        return build_run_setup(name="AE", engine=engine, start=tmp_path, environ={})

    def test_from_the_version_command(
        self, engine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = self._version_command(monkeypatch, 0, "0.15.0\n")

        setup = self._setup(engine, tmp_path)

        assert calls == [[str(engine), "version"]]
        assert setup.engine_version == "0.15.0"
        assert "CORE version: 0.15.0" in setup.header_lines()

    def test_from_the_marker_file_when_the_command_fails(
        self, engine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._version_command(monkeypatch, 2)
        (engine.parent / VERSION_MARKER).write_text("v0.14.2\n", encoding="utf-8")

        assert self._setup(engine, tmp_path).engine_version == "0.14.2"

    def test_unknown_when_both_fail(
        self, engine: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._version_command(monkeypatch, 2)

        assert self._setup(engine, tmp_path).engine_version == "unknown"

    def test_install_engine_writes_the_release_tag_marker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        httpx = pytest.importorskip("httpx")
        from fleet.validation import engine as eng

        monkeypatch.setattr(eng, "ENGINE_DIR", tmp_path / "cdisc-rules-engine")
        keyword = eng._platform_asset_keywords()[0]
        release = {
            "tag_name": "v0.15.0",
            "assets": [{"name": f"core-{keyword}.zip", "browser_download_url": "https://x"}],
        }

        class Client:
            def __init__(self, **kwargs: object) -> None: ...
            def __enter__(self) -> Client:
                return self

            def __exit__(self, *exc: object) -> None: ...
            def get(self, url: str, **kwargs: object) -> object:
                return httpx.Response(200, json=release, request=httpx.Request("GET", url))

        def download(url: str, asset_name: str) -> None:
            eng.engine_path().parent.mkdir(parents=True)
            eng.engine_path().touch()

        monkeypatch.setattr(httpx, "Client", Client)
        monkeypatch.setattr(eng, "_download_and_install", download)

        dest = eng.install_engine()

        assert (dest.parent / VERSION_MARKER).read_text(encoding="utf-8").strip() == "v0.15.0"


def test_header_prints_each_input_with_its_source(tmp_path: Path) -> None:
    setup = build_run_setup(name="ADSL", namespace="adam", start=tmp_path, environ={})

    header = "\n".join(setup.header_lines())

    assert "ADaMIG (namespace)" in header
    assert "1.3 (default)" in header
    assert "Custom rules: none (default)" in header
    assert "no study config" in header


# ------------------------------------------------------------------ #
# The verb, with a fake engine                                        #
# ------------------------------------------------------------------ #

_ADAE = """\
┌─────────┬──────────┐
│ USUBJID ┆ AEDECOD  │
│ ---     ┆ ---      │
│ str     ┆ str      │
╞═════════╪══════════╡
│ S01-001 ┆ HEADACHE │
└─────────┴──────────┘
"""


@pytest.fixture
def fake_engine(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Capture each validate command; the engine writes a clean report and exits 0."""
    commands: list[list[str]] = []

    def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "validate" not in cmd:
            return subprocess.CompletedProcess(cmd, 0, "0.15.0\n", "")
        commands.append(cmd)
        out = Path(_flag(cmd, "-o") or "").with_suffix(".json")
        out.write_text('{"Issue_Details": []}', encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("fleet.validation.official.subprocess.run", run)
    monkeypatch.setattr("fleet.validation.official._run_command", run)
    monkeypatch.delenv("FLEET_RULES_ENGINE", raising=False)
    return commands


def _flag(cmd: list[str], flag: str) -> str | None:
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


class TestVerb:
    @pytest.fixture
    def study(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        (tmp_path / "rules").mkdir()
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "core").touch()
        _study(
            tmp_path,
            "adam:\n  ig_version: 1-1\n"
            "validation:\n  custom_rules: rules\n  engine_path: bin/core\n",
        )
        monkeypatch.chdir(tmp_path)
        return tmp_path

    def test_study_config_drives_the_engine(
        self, study: Path, fake_engine: list[list[str]]
    ) -> None:
        pl.from_repr(_ADAE).adam.validate("ADAE")

        official, custom = fake_engine
        assert Path(official[0]) == (study / "bin" / "core").resolve()
        assert _flag(official, "-v") == "1-1"
        assert "-lr" not in official
        assert Path(_flag(custom, "-lr") or "") == (study / "rules").resolve()

    def test_arguments_override_the_study_config(
        self, study: Path, fake_engine: list[list[str]]
    ) -> None:
        (study / "other_rules").mkdir()
        (study / "other-core").touch()

        pl.from_repr(_ADAE).adam.validate(
            "ADAE",
            version="1.3",
            custom_rules=study / "other_rules",
            rules_engine_path=study / "other-core",
        )

        official, custom = fake_engine
        assert Path(official[0]) == study / "other-core"
        assert _flag(official, "-v") == "1-3"
        assert Path(_flag(custom, "-lr") or "") == study / "other_rules"

    def test_custom_findings_join_the_official_ones_with_their_source(
        self, study: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
            if "validate" in cmd:
                rule = "FLEET-AE-001" if "-lr" in cmd else "CORE-000001"
                report = {"Issue_Details": [{"core_id": rule, "message": "m"}]}
                out = Path(_flag(cmd, "-o") or "").with_suffix(".json")
                out.write_text(json.dumps(report), encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr("fleet.validation.official._run_command", run)

        ns = pl.from_repr(_ADAE).adam.validate("ADAE", on_fail="ignore")

        result = ns.last_validation
        assert result is not None
        assert [(i.rule_id, i.source) for i in result.errors] == [
            ("CORE-000001", "official"),
            ("FLEET-AE-001", "custom"),
        ]

    def test_report_names_the_study_config(
        self, study: Path, fake_engine: list[list[str]], capsys: pytest.CaptureFixture
    ) -> None:
        pl.from_repr(_ADAE).adam.validate("ADAE")

        out = capsys.readouterr().out
        assert f"Study config: {study / 'study_config.yaml'}" in out
        assert "1.1 (study config)" in out

    def test_outside_a_study_the_report_says_no_study_config(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_engine: list[list[str]],
        capsys: pytest.CaptureFixture,
    ) -> None:
        engine = tmp_path / "core"
        engine.touch()
        monkeypatch.chdir(tmp_path)

        pl.from_repr(_ADAE).adam.validate("ADAE", rules_engine_path=engine)

        (cmd,) = fake_engine
        assert _flag(cmd, "-v") == "1-3"
        assert "-lr" not in cmd
        assert "no study config" in capsys.readouterr().out

    @pytest.mark.parametrize("on_fail", ["warn", "raise", "ignore"])
    @pytest.mark.parametrize(
        ("namespace", "name"), [("adam", "AE"), ("sdtm", "ADAE")], ids=["adam-AE", "sdtm-ADAE"]
    )
    def test_namespace_conflict_raises_a_setup_error_in_every_mode(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_engine: list[list[str]],
        namespace: str,
        name: str,
        on_fail: str,
    ) -> None:
        monkeypatch.chdir(tmp_path)
        ns = getattr(pl.from_repr(_ADAE), namespace)

        with pytest.raises(ValidationSetupError, match="standard unclear") as info:
            ns.validate(name, on_fail=on_fail)

        assert not isinstance(info.value, ValidationError)
        assert fake_engine == []

    @pytest.mark.parametrize("on_fail", ["warn", "raise", "ignore"])
    def test_unsupported_version_raises_a_setup_error_in_every_mode(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_engine: list[list[str]],
        on_fail: str,
    ) -> None:
        monkeypatch.chdir(tmp_path)

        with pytest.raises(ValidationSetupError, match="3.1.3"):
            pl.from_repr(_ADAE).sdtm.validate("AE", version="3.1.3", on_fail=on_fail)
