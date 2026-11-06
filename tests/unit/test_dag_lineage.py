"""DAG and lineage behaviour: recursive trace, reconciliation, outputs.

Covers §4.3 items:

* ``PipelineDAG.trace`` — real recursive provenance (multi-hop,
  cross-domain via pin sources, cycle-safe, deduped);
* ``inject_lineage`` — a runtime pin missing from the declared
  ``inputs:`` warns and adds the edge; an unknown node name raises;
* ``build_dag`` — per-dataset ``output:`` and ``output_format:`` keys
  drive node paths, threaded through the JSON/Snakemake exports;
* spec-dispatch attribution — a spec ``duration`` records the verb
  ``duration`` and carries the validated block (ADR-0008);
* lineage re-derivation policy — ``_lineage`` keeps full history,
  consumers dedupe last-write-wins.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import polars as pl
import pytest
import yaml

import fleet  # noqa: F401 — triggers namespace registration
from fleet.core.dag import PipelineDAG, PipelineNode, VariableNode, build_dag
from fleet.core.lineage import latest_lineage_of, lineage_of
from tests.assertions import assert_valid_cdisc_refs


def _node(name: str, verb: str, sources: list[str]) -> VariableNode:
    return VariableNode(name=name, verb=verb, sources=sources, method=f"m.{verb}")


class TestTrace:
    def test_multi_hop_recursion(self):
        dag = PipelineDAG(
            nodes={
                "ADVS": PipelineNode(name="ADVS", node_type="adam", path=None, inputs=[]),
            }
        )
        vars_ = dag.nodes["ADVS"].variables
        vars_["PCHG"] = _node("PCHG", "pchg", ["AVAL", "BASE"])
        vars_["BASE"] = _node("BASE", "baseline", ["AVAL", "ABLFL"])
        vars_["ABLFL"] = _node("ABLFL", "flag", ["vsdy"])
        vars_["AVAL"] = _node("AVAL", "derivation", ["vsorres"])

        chain = dag.trace("ADVS", "PCHG")
        names = [c["name"] for c in chain]
        # Depth-first from the output back to sources; AVAL visited once
        # even though both PCHG and BASE consume it (dedup).
        assert names == ["PCHG", "AVAL", "BASE", "ABLFL"]

    def test_cycle_safe(self):
        dag = PipelineDAG(
            nodes={"X": PipelineNode(name="X", node_type="adam", path=None, inputs=[])}
        )
        dag.nodes["X"].variables["A"] = _node("A", "derivation", ["B"])
        dag.nodes["X"].variables["B"] = _node("B", "derivation", ["A"])
        chain = dag.trace("X", "A")
        assert [c["name"] for c in chain] == ["A", "B"]

    def test_cross_domain_pin_recursion(self, dm_raw):
        """AESTDY traces through the pinned DM domain's own lineage."""
        dm_ns = (
            dm_raw.sdtm.assign("DOMAIN", value="DM")
            .assign("USUBJID", source="patient_number")
            .date("RFSTDTC", source="first_dose_date")
        )
        dm = dm_ns.to_frame()

        ae_raw = pl.from_repr("""\
┌────────────────┬───────────────┐
│ patient_number ┆ ae_start_date │
│ ---            ┆ ---           │
│ str            ┆ str           │
╞════════════════╪═══════════════╡
│ 01-701-1015    ┆ 2014-01-10    │
└────────────────┴───────────────┘
""")
        ae_ns = (
            ae_raw.sdtm.assign("DOMAIN", value="AE")
            .assign("USUBJID", source="patient_number")
            .date("AESTDTC", source="ae_start_date")
            .pin("DM", dm)
            .study_day("AESTDY", date_col="AESTDTC")
        )

        dag = PipelineDAG(
            nodes={
                "DM": PipelineNode(name="DM", node_type="sdtm", path=None, inputs=[]),
                "AE": PipelineNode(name="AE", node_type="sdtm", path=None, inputs=["DM"]),
            }
        )
        dag.inject_lineage(dm_ns, "DM")
        dag.inject_lineage(ae_ns, "AE")

        chain = dag.trace("AE", "AESTDY")
        entries = {(c["dataset"], c["name"]) for c in chain}
        assert ("AE", "AESTDY") in entries
        assert ("AE", "AESTDTC") in entries
        # The pinned reference column resolves inside the DM node.
        assert ("DM", "RFSTDTC") in entries

    def test_unknown_variable_returns_empty(self):
        dag = PipelineDAG(
            nodes={"X": PipelineNode(name="X", node_type="sdtm", path=None, inputs=[])}
        )
        assert dag.trace("X", "NOPE") == []
        assert dag.trace("NOPE", "Y") == []


class TestInjectLineageReconciliation:
    @pytest.fixture
    def ae_ns(self, dm_raw):
        dm = pl.from_repr("""\
┌─────────────┬────────────┐
│ USUBJID     ┆ RFSTDTC    │
│ ---         ┆ ---        │
│ str         ┆ str        │
╞═════════════╪════════════╡
│ 01-701-1015 ┆ 2014-01-02 │
└─────────────┴────────────┘
""")
        ae_raw = pl.from_repr("""\
┌────────────────┬───────────────┐
│ patient_number ┆ ae_start_date │
│ ---            ┆ ---           │
│ str            ┆ str           │
╞════════════════╪═══════════════╡
│ 01-701-1015    ┆ 2014-01-10    │
└────────────────┴───────────────┘
""")
        return (
            ae_raw.sdtm.assign("DOMAIN", value="AE")
            .assign("USUBJID", source="patient_number")
            .date("AESTDTC", source="ae_start_date")
            .pin("DM", dm)
            .study_day("AESTDY", date_col="AESTDTC")
        )

    def test_runtime_edge_missing_from_declaration_warns_and_adds(self, ae_ns):
        dag = PipelineDAG(
            nodes={
                "DM": PipelineNode(name="DM", node_type="sdtm", path=None, inputs=[]),
                "AE": PipelineNode(name="AE", node_type="sdtm", path=None, inputs=[]),
            }
        )
        with pytest.warns(UserWarning, match=r"dependency on 'DM'.*not declared"):
            dag.inject_lineage(ae_ns, "AE")
        assert "DM" in dag.nodes["AE"].inputs

    def test_declared_but_unused_dataset_input_is_not_reported(self, ae_ns, recwarn):
        """No pin evidence is no proof of no use (c1-735): no warning."""
        dag = PipelineDAG(
            nodes={
                "DM": PipelineNode(name="DM", node_type="sdtm", path=None, inputs=[]),
                "VS": PipelineNode(name="VS", node_type="sdtm", path=None, inputs=[]),
                "AE": PipelineNode(name="AE", node_type="sdtm", path=None, inputs=["DM", "VS"]),
            }
        )
        dag.inject_lineage(ae_ns, "AE")
        assert not any("VS" in str(w.message) for w in recwarn.list)

    def test_unknown_dataset_name_raises(self, ae_ns):
        dag = PipelineDAG(
            nodes={"AE": PipelineNode(name="AE", node_type="sdtm", path=None, inputs=[])}
        )
        with pytest.raises(KeyError, match=r"no DAG node named 'adae_typo'.*\['AE'\]"):
            dag.inject_lineage(ae_ns, "adae_typo")

    def test_raw_inputs_exempt_from_unused_warning(self, ae_ns, recwarn):
        dag = PipelineDAG(
            nodes={
                "ae_raw": PipelineNode(name="ae_raw", node_type="raw", path=None, inputs=[]),
                "DM": PipelineNode(name="DM", node_type="sdtm", path=None, inputs=[]),
                "AE": PipelineNode(name="AE", node_type="sdtm", path=None, inputs=["ae_raw", "DM"]),
            }
        )
        dag.inject_lineage(ae_ns, "AE")
        messages = [str(w.message) for w in recwarn.list]
        assert not any("ae_raw" in m for m in messages)

    def test_last_write_wins_in_dag_variables(self):
        df = pl.from_repr("""\
┌─────┬─────┐
│ a   ┆ b   │
│ --- ┆ --- │
│ str ┆ str │
╞═════╪═════╡
│ x   ┆ y   │
└─────┴─────┘
""")
        ns = df.sdtm.assign("COL", source="a").assign("COL", source="b")
        # Full history in the namespace lineage…
        assert [n.sources for n in lineage_of(ns) if n.name == "COL"] == [["a"], ["b"]]
        # …deduped last-write-wins at the consumers.
        assert [n.sources for n in latest_lineage_of(ns)] == [["b"]]
        dag = PipelineDAG(
            nodes={"DM": PipelineNode(name="DM", node_type="sdtm", path=None, inputs=[])}
        )
        dag.inject_lineage(ns, "DM")
        assert dag.nodes["DM"].variables["COL"].sources == ["b"]


class TestBuildDagOutputs:
    def _write_spec(self, tmp_path: Path, **extra) -> Path:
        spec = {
            "study": {"standard": "SDTMIG"},
            "datasets": [
                {
                    "name": "DM",
                    "inputs": [{"name": "dm_raw", "type": "raw", "path": "raw/dm.csv"}],
                    **extra.get("dm", {}),
                },
                {"name": "AE", "inputs": [], **extra.get("ae", {})},
            ],
            **{k: v for k, v in extra.items() if k not in ("dm", "ae")},
        }
        p = tmp_path / "define.yaml"
        p.write_text(yaml.safe_dump(spec))
        return p

    def test_default_convention_parquet(self, tmp_path):
        p = self._write_spec(tmp_path)
        dag = build_dag(p, output_dir=tmp_path / "out")
        assert dag.nodes["DM"].path == str(tmp_path / "out" / "dm.parquet")

    def test_per_dataset_output_key(self, tmp_path):
        p = self._write_spec(tmp_path, dm={"output": "exports/dm_final.parquet"})
        dag = build_dag(p, output_dir=tmp_path / "out")
        assert dag.nodes["DM"].path == str(tmp_path / "out" / "exports" / "dm_final.parquet")
        # threaded through the JSON + Snakemake exports
        assert dag.to_dict()["DM"]["path"] == dag.nodes["DM"].path
        assert dag.to_snakemake()["DM"]["output"] == dag.nodes["DM"].path

    def test_spec_level_output_format(self, tmp_path):
        p = self._write_spec(tmp_path, output_format="xpt")
        dag = build_dag(p, output_dir=tmp_path / "out")
        assert dag.nodes["DM"].path == str(tmp_path / "out" / "dm.xpt")
        assert dag.nodes["AE"].path == str(tmp_path / "out" / "ae.xpt")

    def test_per_dataset_output_format_overrides_spec_level(self, tmp_path):
        p = self._write_spec(tmp_path, output_format="xpt", ae={"output_format": "dataset-json"})
        dag = build_dag(p, output_dir=tmp_path / "out")
        assert dag.nodes["DM"].path == str(tmp_path / "out" / "dm.xpt")
        assert dag.nodes["AE"].path == str(tmp_path / "out" / "ae.json")

    def test_unknown_output_format_is_refused(self, tmp_path):
        """c1-647: ``output_format: json`` is not silently written as parquet."""
        from fleet.core.exceptions import SpecError

        p = self._write_spec(tmp_path, output_format="json")
        with pytest.raises(SpecError, match="output_format"):
            build_dag(p, output_dir=tmp_path / "out")


class TestSpecDispatchAttribution:
    def test_spec_duration_records_the_verb_and_its_block(self, tmp_path):
        spec = {
            "datasets": [
                {
                    "name": "ADVS",
                    "variables": [
                        {
                            "name": "ADY",
                            "derivation": {
                                "algorithm": "duration",
                                "end": "ADT",
                                "start": "TRTSDT",
                            },
                        }
                    ],
                }
            ]
        }
        p = tmp_path / "define.yaml"
        p.write_text(yaml.safe_dump(spec))
        df = pl.from_repr("""\
┌─────────┬────────────┬────────────┐
│ USUBJID ┆ ADT        ┆ TRTSDT     │
│ ---     ┆ ---        ┆ ---        │
│ str     ┆ str        ┆ str        │
╞═════════╪════════════╪════════════╡
│ S1      ┆ 2024-01-10 ┆ 2024-01-01 │
└─────────┴────────────┴────────────┘
""")
        ns = df.adam.from_spec(p, dataset="ADVS")
        (node,) = [n for n in lineage_of(ns) if n.name == "ADY"]
        assert node.verb == "duration"
        assert node.spec == {"algorithm": "duration", "end": "ADT", "start": "TRTSDT"}

    def test_inline_duration_still_records_duration(self):
        df = pl.from_repr("""\
┌────────────┬────────────┐
│ TRTSDT     ┆ ADT        │
│ ---        ┆ ---        │
│ str        ┆ str        │
╞════════════╪════════════╡
│ 2024-01-01 ┆ 2024-01-10 │
└────────────┴────────────┘
""")
        ns = df.adam.duration("ADY", start="TRTSDT", end="ADT")
        (node,) = [n for n in lineage_of(ns) if n.name == "ADY"]
        assert node.verb == "duration"

    def test_a_frame_argument_is_recorded_without_a_polars_warning(self):
        """A frame against a None default is compared by identity, not with ==.

        Not filterwarnings("error"): the capture swallows exceptions, so an
        error would hide the comparison.
        """
        adsl = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ P1      │
│ P2      │
└─────────┘
""")
        ex = pl.from_repr("""\
┌─────────┬────────┐
│ USUBJID ┆ EXDOSE │
│ ---     ┆ ---    │
│ str     ┆ i64    │
╞═════════╪════════╡
│ P1      ┆ 54     │
│ P2      ┆ 0      │
└─────────┴────────┘
""")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            ns = adsl.adam.adsl.flag_exists(
                "SAFFL", from_dataset=ex, on=["USUBJID"], source_filter=pl.col("EXDOSE") > 0
            )

        assert [str(w.message) for w in caught if "None" in str(w.message)] == []
        assert ns.to_frame()["SAFFL"].to_list() == ["Y", None]
        (node,) = [n for n in lineage_of(ns) if n.name == "SAFFL"]
        assert node.verb == "flag"


class TestOrchestrationExports:
    """c1-736: the DAG exports the graph; it writes no Snakefile and no Airflow module."""

    @pytest.fixture
    def dag(self, tmp_path: Path) -> PipelineDAG:
        spec = {
            "study": {"id": "S1", "standard": "SDTMIG", "standard_version": "3.4"},
            "datasets": [
                {
                    "name": "DM",
                    "inputs": [{"name": "dm_raw", "type": "raw"}],
                    "variables": [],
                },
                {
                    "name": "AE",
                    "inputs": [{"name": "ae_raw", "type": "raw"}, {"name": "DM"}],
                    "variables": [],
                },
            ],
        }
        p = tmp_path / "define.yaml"
        p.write_text(yaml.safe_dump(spec))
        return build_dag(p, output_dir=tmp_path / "out")

    def test_the_graph_exports_keep_the_dependencies(self, dag: PipelineDAG):
        assert dag.to_airflow()["AE"] == ["ae_raw", "DM"]
        assert dag.to_snakemake()["AE"]["input"][1] == dag.nodes["DM"].path

    def test_the_draft_file_writers_are_removed(self, dag: PipelineDAG):
        """The Snakefile paths differed from fleet run, and an IS task id did not compile."""
        assert not hasattr(dag, "to_snakefile")
        assert not hasattr(dag, "to_airflow_dag")


class TestCdiscRefs:
    def test_cdisc_refs_are_well_formed(self, dm_raw):
        """Every VariableNode produced by a namespace pipeline has a valid cdisc_ref."""
        ns = (
            dm_raw.sdtm.assign("DOMAIN", value="DM")
            .assign("USUBJID", source="patient_number")
            .date("RFSTDTC", source="first_dose_date")
        )
        assert_valid_cdisc_refs(list(latest_lineage_of(ns)))
