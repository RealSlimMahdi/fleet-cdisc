"""Tests for static spec ↔ source conversion (``fleet.core.spec_source``)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet.core.spec_source import derivations_from_source, program_from_spec

REPO = Path(__file__).parent.parent.parent
SDTM_SPEC = REPO / "examples" / "cdiscpilot01" / "sdtm" / "define.yaml"
ADAM_SPEC = REPO / "examples" / "cdiscpilot01" / "adam" / "define.yaml"

PROGRAM = """
import polars as pl

ae = (
    ae_raw.sdtm.hardcode_no_ct("DOMAIN", value="AE")
    .assign("STUDYID", source="study_id")
    .derivation("USUBJID", expression=pl.concat_str([pl.col("STUDY"), pl.col("SUBJ")]))
    .assign_ct("AESEV", source="severity", ct_codelist="C66769", ct_mapping={"Yes": "Y"})
    .export_supp("AESPID")
    .frobnicate("AEFROB")
    .to_frame()
    .drop("AETERM")
)
adsl = dm.adam.chg("CHG", aval="AVALX", base="BASEX")
"""


def test_rows_follow_call_order_and_map_through_the_registry():
    rows = derivations_from_source(PROGRAM)
    assert [r["name"] for r in rows] == [
        "DOMAIN",
        "STUDYID",
        "USUBJID",
        "AESEV",
        "AESPID",
        "AEFROB",
        "CHG",
    ]
    by = {r["name"]: r for r in rows}
    assert by["DOMAIN"]["block"] == {"algorithm": "hardcode_no_ct", "value": "AE"}
    assert by["DOMAIN"]["line"] == 5
    assert by["STUDYID"]["block"] == {"algorithm": "assign_no_ct", "source": "study_id"}
    assert by["AESEV"]["block"]["ct_mapping"] == {"Yes": "Y"}
    assert by["CHG"]["standard"] == "adam"
    # Params at their registry default stay implicit, as in to_spec_yaml().
    assert by["CHG"]["block"] == {"algorithm": "chg", "aval": "AVALX", "base": "BASEX"}
    assert derivations_from_source('x = dm.adam.chg("CHG", aval="AVAL")')[0]["block"] == {
        "algorithm": "chg"
    }


def test_statuses_tell_expression_unsupported_and_unknown_apart():
    by = {r["name"]: r for r in derivations_from_source(PROGRAM)}
    assert by["USUBJID"]["status"] == "stub"
    assert "literal" in by["USUBJID"]["reason"]
    assert by["AESPID"]["status"] == "unsupported"
    assert by["AEFROB"]["status"] == "unknown"


def test_frame_methods_and_expression_calls_are_not_derivations():
    names = [r["name"] for r in derivations_from_source(PROGRAM)]
    assert "AETERM" not in names  # a frame method after to_frame()
    assert "STUDY" not in names  # pl.col("STUDY") inside an expression


def test_positional_and_star_arguments_are_stubs():
    rows = derivations_from_source('x = raw.sdtm.assign("A", "src").assign("B", **kw)')
    assert [r["status"] for r in rows] == ["stub", "stub"]
    assert "positional" in rows[0]["reason"]
    assert "kwargs" in rows[1]["reason"]


def test_program_from_spec_renders_one_call_per_derivation():
    code = program_from_spec(ADAM_SPEC, "adsl")
    assert code.startswith("# ADSL")
    assert "dm.adam" in code
    assert ".assign('STUDYID', value='CDISCPILOT01')" in code
    assert code.rstrip().endswith(".to_frame()\n)")


def test_program_from_spec_pins_cross_domain_inputs(tmp_path):
    spec = tmp_path / "define.yaml"
    spec.write_text(
        "study:\n  id: X\n  standard: ADAMIG\n"
        "datasets:\n  - name: ADAE\n    inputs:\n      - name: AE\n      - name: ADSL\n"
        "    variables:\n      - name: TRTSDT\n        derivation:\n"
        "          algorithm: lookup\n          dataset: ADSL\n          'on': [USUBJID]\n"
        "          target_cols: [TRTSDT]\n",
        encoding="utf-8",
    )
    code = program_from_spec(spec, "ADAE")
    assert 'adsl = fleet.frame(pl.read_parquet("TODO/adsl.parquet"))' in code
    assert "    ae.adam\n" in code
    assert '    .pin("ADSL", adsl)\n' in code
    # The call the registry would make, not the algorithm's spelling.
    assert "    .merge(dataset='ADSL', on=['USUBJID'], keep=['TRTSDT'])\n" in code


def test_program_from_spec_unknown_dataset_raises():
    with pytest.raises(ValueError, match="Known: "):
        program_from_spec(SDTM_SPEC, "NOPE")
