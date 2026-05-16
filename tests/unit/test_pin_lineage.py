"""Unit tests for pin lineage and DAG integration."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration
from fleet.core.dag import PinDependency, PipelineDAG, PipelineNode
from fleet.core.lineage import pin_lineage_of

# ── Fixtures ────────────────────────────────────────────────────────────── #


@pytest.fixture
def dm_df():
    return pl.DataFrame(
        {
            "USUBJID": ["S001", "S002"],
            "RFSTDTC": ["2014-01-02", "2014-01-03"],
        }
    )


@pytest.fixture
def adsl_df():
    return pl.DataFrame(
        {
            "USUBJID": ["S001", "S002"],
            "TRTSDT": ["2014-01-02", "2014-01-03"],
            "SAFFL": ["Y", "Y"],
        }
    )


# ── Pin lineage recording ───────────────────────────────────────────── #


class TestPinLineage:
    def test_study_day_records_pin_lineage(self, dm_df):
        ae_raw = pl.DataFrame(
            {
                "patient_number": ["S001", "S002"],
                "ae_start_date": ["2014-01-10", "2014-02-15"],
            }
        )
        ns = (
            ae_raw.sdtm.hardcode_no_ct("DOMAIN", value="AE")
            .assign_no_ct("USUBJID", source="patient_number")
            .date("AESTDTC", source="ae_start_date")
            .pin("DM", dm_df)
            .study_day("AESTDY", date_col="AESTDTC")
        )
        pl_entries = pin_lineage_of(ns)
        assert len(pl_entries) == 1
        dep = pl_entries[0]
        assert isinstance(dep, PinDependency)
        assert dep.target_col == "AESTDY"
        assert dep.source_domain == "DM"
        assert dep.source_cols == ["RFSTDTC"]
        assert dep.join_key == ["USUBJID"]
        assert dep.relationship == "derivation"

    def test_join_adsl_records_carry_forward(self, adsl_df):
        ae_df = pl.DataFrame({"USUBJID": ["S001", "S002"], "AETERM": ["HA", "NA"]})
        ns = (
            ae_df.adam.occds("ADAE")
            .pin("ADSL", adsl_df)
            .source("USUBJID")
            .join_adsl("TRTSDT", "SAFFL")
        )
        pl_entries = pin_lineage_of(ns)
        assert len(pl_entries) == 2
        assert all(d.relationship == "carry_forward" for d in pl_entries)
        assert {d.target_col for d in pl_entries} == {"TRTSDT", "SAFFL"}

    def test_pin_lineage_survives_chain(self, dm_df):
        ae_raw = pl.DataFrame(
            {
                "patient_number": ["S001"],
                "ae_start_date": ["2014-01-10"],
            }
        )
        ns = (
            ae_raw.sdtm.assign_no_ct("USUBJID", source="patient_number")
            .date("AESTDTC", source="ae_start_date")
            .pin("DM", dm_df)
            .study_day("AESTDY", date_col="AESTDTC")
            .hardcode_no_ct("DOMAIN", value="AE")
        )
        # Pin lineage should survive the hardcode_no_ct chain
        pl_entries = pin_lineage_of(ns)
        assert len(pl_entries) == 1

    def test_no_pin_lineage_without_pin(self):
        df = pl.DataFrame({"USUBJID": ["S001"]})
        ns = df.sdtm.assign_no_ct("SUBJID", source="USUBJID")
        assert pin_lineage_of(ns) == []


# ── DAG injection ────────────────────────────────────────────────────── #


class TestDAGInjection:
    def test_inject_lineage_adds_pin_edges(self, dm_df):
        ae_raw = pl.DataFrame(
            {
                "patient_number": ["S001", "S002"],
                "ae_start_date": ["2014-01-10", "2014-02-15"],
            }
        )
        ns = (
            ae_raw.sdtm.hardcode_no_ct("DOMAIN", value="AE")
            .assign_no_ct("USUBJID", source="patient_number")
            .date("AESTDTC", source="ae_start_date")
            .pin("DM", dm_df)
            .study_day("AESTDY", date_col="AESTDTC")
        )

        dag = PipelineDAG(
            nodes={
                "DM": PipelineNode(name="DM", node_type="sdtm", path=None, inputs=[]),
                "AE": PipelineNode(name="AE", node_type="sdtm", path=None, inputs=[]),
            }
        )

        dag.inject_lineage(ns, "AE")

        # AE should now have DM as an input
        assert "DM" in dag.nodes["AE"].inputs

        # AESTDY variable should have pin_sources
        assert "AESTDY" in dag.nodes["AE"].variables
        vnode = dag.nodes["AE"].variables["AESTDY"]
        assert len(vnode.pin_sources) == 1
        assert vnode.pin_sources[0].source_domain == "DM"

    def test_trace_returns_provenance(self, dm_df):
        ae_raw = pl.DataFrame(
            {
                "patient_number": ["S001"],
                "ae_start_date": ["2014-01-10"],
            }
        )
        ns = (
            ae_raw.sdtm.hardcode_no_ct("DOMAIN", value="AE")
            .assign_no_ct("USUBJID", source="patient_number")
            .date("AESTDTC", source="ae_start_date")
            .pin("DM", dm_df)
            .study_day("AESTDY", date_col="AESTDTC")
        )

        dag = PipelineDAG(
            nodes={
                "DM": PipelineNode(name="DM", node_type="sdtm", path=None, inputs=[]),
                "AE": PipelineNode(name="AE", node_type="sdtm", path=None, inputs=[]),
            }
        )
        dag.inject_lineage(ns, "AE")

        chain = dag.trace("AE", "AESTDY")
        assert len(chain) == 1
        assert chain[0]["name"] == "AESTDY"
        assert chain[0]["pin_sources"][0]["source_domain"] == "DM"

    def test_to_dict_includes_pin_sources(self, dm_df):
        ae_raw = pl.DataFrame(
            {
                "patient_number": ["S001"],
                "ae_start_date": ["2014-01-10"],
            }
        )
        ns = (
            ae_raw.sdtm.hardcode_no_ct("DOMAIN", value="AE")
            .assign_no_ct("USUBJID", source="patient_number")
            .date("AESTDTC", source="ae_start_date")
            .pin("DM", dm_df)
            .study_day("AESTDY", date_col="AESTDTC")
        )

        dag = PipelineDAG(
            nodes={
                "DM": PipelineNode(name="DM", node_type="sdtm", path=None, inputs=[]),
                "AE": PipelineNode(name="AE", node_type="sdtm", path=None, inputs=[]),
            }
        )
        dag.inject_lineage(ns, "AE")

        d = dag.to_dict()
        ae_vars = d["AE"]["variables"]
        assert "AESTDY" in ae_vars
        assert "pin_sources" in ae_vars["AESTDY"]
