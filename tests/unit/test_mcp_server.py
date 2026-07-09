"""Tests for the ``fleet mcp`` tool functions (``fleet.mcp_server``).

The MCP tools are thin wrappers over existing public APIs, so they are
called directly (no running server) against the repo's example specs and
fixtures.  ``fleet_validate`` is not covered — it needs the external
CDISC Rules Engine binary.
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl
import pytest

pytest.importorskip("mcp", reason="mcp extra (mcp SDK) not installed")

from fleet.core.dag import build_dag  # noqa: E402
from fleet.mcp_server import (  # noqa: E402
    TOOLS,
    create_server,
    fleet_ct_terms,
    fleet_dataset_check,
    fleet_execution_order,
    fleet_impacted_by,
    fleet_lineage,
    fleet_tlg_catalog,
    fleet_tlg_run,
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


class TestServerWiring:
    def test_create_server_registers_every_tool(self):
        import asyncio

        server = create_server()
        registered = {tool.name for tool in asyncio.run(server.list_tools())}
        assert registered == {fn.__name__ for fn in TOOLS}
