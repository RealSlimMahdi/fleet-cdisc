"""Unit tests for the ``.trail()`` variable-lineage display verb."""

import warnings

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration


@pytest.fixture
def dm_df() -> pl.DataFrame:
    return pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ RFSTDTC    │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ S001    ┆ 2014-01-02 │
│ S002    ┆ 2014-01-03 │
└─────────┴────────────┘
""")


@pytest.fixture
def ae_raw() -> pl.DataFrame:
    return pl.from_repr("""\
┌────────────────┬──────────┬───────────────┐
│ patient_number ┆ ae_term  ┆ ae_start_date │
│ ---            ┆ ---      ┆ ---           │
│ str            ┆ str      ┆ str           │
╞════════════════╪══════════╪═══════════════╡
│ S001           ┆ HEADACHE ┆ 2014-01-10    │
│ S002           ┆ NAUSEA   ┆ 2014-01-12    │
└────────────────┴──────────┴───────────────┘
""")


class TestTrail:
    def test_returns_self_and_leaves_frame_unchanged(self, ae_raw):
        base = ae_raw.sdtm.assign("USUBJID", source="patient_number")
        expected = base.to_frame()
        got = base.trail().to_frame()
        assert got.equals(expected)

    def test_lists_derived_variables_with_origin(self, ae_raw, capsys):
        (
            ae_raw.sdtm.assign("USUBJID", source="patient_number").assign(
                "AETERM", source="ae_term"
            )
        ).trail()
        out = capsys.readouterr().out
        assert "Variable trail (2 derivation(s)):" in out
        assert "USUBJID" in out and "patient_number" in out
        assert "AETERM" in out and "ae_term" in out

    def test_literal_variable_marked(self, ae_raw, capsys):
        ae_raw.sdtm.assign("DOMAIN", value="AE").trail()
        out = capsys.readouterr().out
        assert "DOMAIN" in out
        assert "(literal)" in out

    def test_empty_pipeline_prints_friendly_message(self, ae_raw, capsys):
        ae_raw.sdtm.trail()
        out = capsys.readouterr().out
        assert "empty" in out.lower()

    def test_cross_domain_pin_origin_suppresses_bare_local(self, ae_raw, dm_df, capsys):
        (
            ae_raw.sdtm.assign("DOMAIN", value="AE")
            .assign("USUBJID", source="patient_number")
            .assign("AESTDTC", source="ae_start_date")
            .pin("DM", dm_df)
            .study_day("AESTDY", date_col="AESTDTC")
        ).trail()
        out = capsys.readouterr().out
        assert "AESTDY" in out
        assert "DM.RFSTDTC" in out
        # The locally-joined RFSTDTC is attributed to DM, not listed twice.
        assert "RFSTDTC, DM.RFSTDTC" not in out

    def test_redefinition_shown_once_per_derivation(self, ae_raw, capsys):
        (
            ae_raw.sdtm.assign("USUBJID", source="patient_number").assign(
                "USUBJID", source="patient_number"
            )
        ).trail()
        out = capsys.readouterr().out
        assert "Variable trail (2 derivation(s)):" in out
        assert out.count("USUBJID") >= 2

    def test_domain_column_present_for_adam(self, capsys):
        adsl_raw = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ S001    │
│ S002    │
└─────────┘
""")
        adsl_raw.adam.adsl.source("USUBJID").trail()
        out = capsys.readouterr().out
        assert "Domain" in out
        assert "ADSL" in out


    def test_pin_sources_populated_on_namespace_lineage(self, ae_raw, dm_df):
        """pin_sources should be available on nodes before inject_lineage() is called.

        This tests that record_pin_lineage() immediately populates the VariableNode's
        pin_sources field, not just the separate _pin_lineage list. This makes pin
        information available to users inspecting lineage_of()/latest_lineage_of()
        without needing to build a DAG.
        """

        ns = (
            ae_raw.sdtm.assign("DOMAIN", value="AE")
            .assign("USUBJID", source="patient_number")
            .assign("AESTDTC", source="ae_start_date")
            .pin("DM", dm_df)
            .study_day("AESTDY", date_col="AESTDTC")
        )
        
        # Check pin_sources directly from latest_lineage_of (before any DAG)
        for node in fleet.core.lineage.latest_lineage_of(ns):
            if node.name == "AESTDY":
                # pin_sources should be populated immediately
                assert len(node.pin_sources) > 0, "pin_sources is empty — fix not applied"
                assert node.pin_sources[0].source_domain == "DM"
                assert "RFSTDTC" in node.pin_sources[0].source_cols
                return
        
        pytest.fail("AESTDY node not found in lineage")

    def test_keep_does_not_prune_lineage(self):
        """keep() removes columns from the frame but not from lineage.

        Both lineage_of() and latest_lineage_of() include dropped columns —
        filtering to surviving columns only happens in to_spec_yaml(), which
        iterates schema.names(), not the lineage list.
        """
        from fleet.core.lineage import latest_lineage_of, lineage_of

        df = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ a   │
│ ---     ┆ --- │
│ str     ┆ str │
╞═════════╪═════╡
│ S001    ┆ x   │
└─────────┴─────┘
""")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ns = df.sdtm.assign("TMP", source="a").keep("USUBJID")

        assert "TMP" not in ns.to_frame().columns
        assert any(n.name == "TMP" for n in lineage_of(ns))
        assert any(n.name == "TMP" for n in latest_lineage_of(ns))  # not frame-aware by design
