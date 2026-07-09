"""Unit tests for the ``.trail()`` variable-lineage display verb."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration


@pytest.fixture
def dm_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "USUBJID": ["S001", "S002"],
            "RFSTDTC": ["2014-01-02", "2014-01-03"],
        }
    )


@pytest.fixture
def ae_raw() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "patient_number": ["S001", "S002"],
            "ae_term": ["HEADACHE", "NAUSEA"],
            "ae_start_date": ["2014-01-10", "2014-01-12"],
        }
    )


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
        adsl_raw = pl.DataFrame({"USUBJID": ["S001", "S002"]})
        adsl_raw.adam.adsl.source("USUBJID").trail()
        out = capsys.readouterr().out
        assert "Domain" in out
        assert "ADSL" in out
