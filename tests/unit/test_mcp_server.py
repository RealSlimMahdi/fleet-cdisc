"""Tests for the ``fleet mcp`` tool functions (``fleet.mcp_server``).

The MCP tools are thin wrappers over existing public APIs, so they are
called directly (no running server) against the repo's example specs and
fixtures.  ``fleet_validate`` runs on a fake engine: ``subprocess.run`` is
captured, and the engine path is a plain file.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import polars as pl
import pytest

pytest.importorskip("mcp", reason="mcp extra (mcp SDK) not installed")

from fleet.core.dag import build_dag  # noqa: E402
from fleet.mcp_server import (  # noqa: E402
    TOOLS,
    create_server,
    fleet_code_to_spec,
    fleet_ct_terms,
    fleet_dataset_check,
    fleet_execution_order,
    fleet_impacted_by,
    fleet_lineage,
    fleet_spec_to_code,
    fleet_tlg_catalog,
    fleet_tlg_run,
    fleet_validate,
)

REPO = Path(__file__).parent.parent.parent
SPECS = [
    str(REPO / "examples" / "cdiscpilot01" / "sdtm" / "define.yaml"),
    str(REPO / "examples" / "cdiscpilot01" / "adam" / "define.yaml"),
]
CT_SAMPLE = REPO / "tests" / "fixtures" / "ct" / "cdisc_ct_sample.yaml"

sys.path.insert(0, str(REPO / "tests"))


class TestDagTools:
    def test_execution_order_respects_dependencies(self):
        order = fleet_execution_order(SPECS)
        assert order.index("dm_raw") < order.index("DM") < order.index("ADSL")

    def test_impacted_by_returns_downstream_rerun_list(self):
        impacted = fleet_impacted_by(SPECS, "dm_raw")
        assert impacted[0] == "dm_raw"
        assert "DM" in impacted and "ADSL" in impacted
        assert "AE" not in impacted

    def test_lineage_reads_generated_dag_json(self, tmp_path):
        dag_json = tmp_path / "pipeline_dag.json"
        build_dag(*SPECS).generate(dag_json)
        node = fleet_lineage(str(dag_json), "ADSL")
        assert node["node_type"] == "adam"
        assert node["inputs"] == ["DM"]

    def test_lineage_unknown_dataset_names_known_ones(self, tmp_path):
        dag_json = tmp_path / "pipeline_dag.json"
        build_dag(*SPECS).generate(dag_json)
        with pytest.raises(ValueError, match="ADSL"):
            fleet_lineage(str(dag_json), "NOPE")


class TestCtTools:
    def test_ct_terms_loads_file_and_returns_sorted_values(self):
        terms = fleet_ct_terms("C66731", ct_path=str(CT_SAMPLE))
        assert terms == ["F", "M", "U", "UNDIFFERENTIATED"]

    def test_ct_terms_unloaded_codelist_raises_with_hint(self):
        with pytest.raises(ValueError, match="ct_path"):
            fleet_ct_terms("C0000-NOT-LOADED")


class TestTlgTools:
    def test_catalog_lists_registered_templates(self):
        rows = fleet_tlg_catalog()
        assert any(row["id"] == "aet01" for row in rows)
        assert {"id", "title", "output_type", "domains"} <= set(rows[0])

    def test_tlg_run_renders_html_from_spec_and_data(self, tmp_path):
        from fixtures.study import ADAE, ADSL

        adae_path = tmp_path / "adae.parquet"
        adsl_path = tmp_path / "adsl.parquet"
        ADAE.write_parquet(adae_path)
        ADSL.write_parquet(adsl_path)
        html = fleet_tlg_run(
            str(REPO / "examples" / "tlg_specs" / "aet01.yaml"),
            str(adae_path),
            adsl_path=str(adsl_path),
        )
        assert "<table" in html


class TestDatasetCheck:
    def test_check_reports_missing_columns_json_friendly(self, tmp_path):
        dm = pl.from_repr(
            """
            ┌──────────────┬───────────────┬─────┐
            │ STUDYID      ┆ USUBJID       ┆ SEX │
            │ ---          ┆ ---           ┆ --- │
            │ str          ┆ str           ┆ str │
            ╞══════════════╪═══════════════╪═════╡
            │ CDISCPILOT01 ┆ CDISC01.01001 ┆ M   │
            └──────────────┴───────────────┴─────┘
            """
        )
        data_path = tmp_path / "dm.parquet"
        dm.write_parquet(data_path)
        result = fleet_dataset_check(str(data_path), SPECS[0], "DM")
        assert result["dataset"] == "DM"
        assert result["is_valid"] is False
        assert "AGE" in result["missing_columns"]
        assert result["extra_columns"] == []


_SUBJECTS = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ S01-001 │
└─────────┘
""")


@pytest.fixture
def engine_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Capture each validate command; the engine writes a clean report and exits 0."""
    calls: list[list[str]] = []

    def run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if "validate" in cmd and "--help" not in cmd:
            calls.append(cmd)
            out = Path(cmd[cmd.index("-o") + 1]).with_suffix(".json")
            out.write_text('{"Issue_Details": []}', encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, "0.15.0\n", "")

    monkeypatch.setattr("fleet.validation.official.subprocess.run", run)
    monkeypatch.setattr("fleet.validation.official._run_command", run)
    monkeypatch.delenv("FLEET_RULES_ENGINE", raising=False)
    return calls


def _flag(cmd: list[str], flag: str) -> str | None:
    return cmd[cmd.index(flag) + 1] if flag in cmd else None


class TestValidate:
    @pytest.fixture
    def study(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        """A study with its own IG version, rules and engine; the server runs elsewhere."""
        root = tmp_path / "study"
        (root / "rules").mkdir(parents=True)
        (root / "bin").mkdir()
        (root / "bin" / "core").touch()
        (root / "study_config.yaml").write_text(
            "study_id: S01\nadam:\n  ig_version: 1-1\n"
            "validation:\n  custom_rules: rules\n  engine_path: bin/core\n",
            encoding="utf-8",
        )
        for sub, name in (("sdtm", "dm"), ("adam", "adsl")):
            (root / "data" / sub).mkdir(parents=True)
            _SUBJECTS.write_parquet(root / "data" / sub / f"{name}.parquet")
        elsewhere = tmp_path / "server"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        monkeypatch.setattr("fleet.mcp_server._TRUST_STUDY_ENGINE", True)
        return root

    def test_a_study_engine_runs_only_on_a_trusting_server(
        self, study: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        marker = study / "engine_ran"
        engine = study / "bin" / "core"
        engine.write_text(f"#!/bin/sh\ntouch '{marker}'\n", encoding="utf-8")
        engine.chmod(0o755)
        monkeypatch.setattr("fleet.mcp_server._TRUST_STUDY_ENGINE", False)

        result = fleet_validate(str(study / "data" / "sdtm" / "dm.parquet"))

        assert result["outcome"] == "could not run"
        assert "fleet mcp --trust-study-engine" in result["reason"]
        assert not marker.exists()

    def test_the_dataset_study_drives_the_engine_from_outside_it(
        self, study: Path, engine_calls: list[list[str]]
    ) -> None:
        result = fleet_validate(str(study / "data" / "adam" / "adsl.parquet"))

        official, custom = engine_calls
        assert Path(official[0]).resolve() == (study / "bin" / "core").resolve()
        assert _flag(official, "-s") == "adamig"
        assert _flag(official, "-v") == "1-1"
        assert Path(_flag(custom, "-lr") or "").resolve() == (study / "rules").resolve()
        assert result["outcome"] == "pass"

    def test_result_lists_each_input_with_its_source(
        self, study: Path, engine_calls: list[list[str]]
    ) -> None:
        result = fleet_validate(str(study / "data" / "adam" / "adsl.parquet"))

        setup = result["setup"]
        assert setup["standard"] == {"value": "adam", "source": "data directory"}
        assert setup["ig_version"] == {"value": "1.1", "source": "study config"}
        assert setup["custom_rules"] == {"value": str(study / "rules"), "source": "study config"}
        assert setup["engine"] == {"value": str(study / "bin" / "core"), "source": "study config"}
        assert setup["engine_version"] == "0.15.0"
        assert setup["study_config"] == str(study / "study_config.yaml")

    def test_adsl_without_standard_validates_as_adam(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine_calls: list[list[str]]
    ) -> None:
        engine = tmp_path / "core"
        engine.touch()
        monkeypatch.setenv("FLEET_RULES_ENGINE", str(engine))
        adsl = tmp_path / "adsl.parquet"
        _SUBJECTS.write_parquet(adsl)

        result = fleet_validate(str(adsl))

        (cmd,) = engine_calls
        assert _flag(cmd, "-s") == "adamig"
        assert result["setup"]["standard"] == {"value": "adam", "source": "dataset name"}

    def test_custom_rules_argument_reaches_the_engine(
        self, study: Path, engine_calls: list[list[str]]
    ) -> None:
        own = study / "my_rules"
        own.mkdir()

        result = fleet_validate(str(study / "data" / "sdtm" / "dm.parquet"), custom_rules=str(own))

        _, custom = engine_calls
        assert Path(_flag(custom, "-lr") or "").resolve() == own.resolve()
        assert result["setup"]["custom_rules"] == {"value": str(own), "source": "argument"}

    def test_standard_conflict_could_not_run(
        self, study: Path, engine_calls: list[list[str]]
    ) -> None:
        _SUBJECTS.write_parquet(study / "data" / "adam" / "dm.parquet")

        result = fleet_validate(str(study / "data" / "adam" / "dm.parquet"))

        assert result["outcome"] == "could not run"
        assert "standard unclear" in result["reason"]
        assert engine_calls == []

    def test_unsupported_version_could_not_run(
        self, study: Path, engine_calls: list[list[str]]
    ) -> None:
        result = fleet_validate(str(study / "data" / "sdtm" / "dm.parquet"), version="3.1.3")

        assert result == {
            "outcome": "could not run",
            "reason": result["reason"],
        }
        assert "3.2, 3.3, 3.4" in result["reason"]
        assert engine_calls == []

    def test_missing_engine_could_not_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, engine_calls: list[list[str]]
    ) -> None:
        monkeypatch.setattr("fleet.validation.engine.ENGINE_DIR", tmp_path / "no-engine")
        ae = tmp_path / "ae.parquet"
        _SUBJECTS.write_parquet(ae)

        result = fleet_validate(str(ae))

        assert result["outcome"] == "could not run"
        assert "fleet install-engine" in result["reason"]


class TestServerWiring:
    def test_create_server_registers_every_tool(self):
        import asyncio

        server = create_server()
        registered = {tool.name for tool in asyncio.run(server.list_tools())}
        assert registered == {fn.__name__ for fn in TOOLS}


def test_code_to_spec_rows_carry_registry_blocks():
    rows = fleet_code_to_spec('dm = raw.sdtm.assign("DOMAIN", value="DM")')
    assert rows == [
        {
            "name": "DOMAIN",
            "verb": "assign",
            "standard": "sdtm",
            "line": 1,
            "status": "ok",
            "block": {"algorithm": "assign", "value": "DM"},
            "reason": "",
            "meta": {},
        }
    ]


def test_spec_to_code_renders_a_program_for_the_dataset():
    code = fleet_spec_to_code(SPECS[1], "ADSL")
    assert code.startswith("# ADSL")
    assert ".to_frame()" in code


def test_conversion_tools_are_registered():
    assert {fleet_code_to_spec, fleet_spec_to_code} <= set(TOOLS)
