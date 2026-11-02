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
    ae_raw.sdtm.assign("DOMAIN", value="AE")
    .assign("STUDYID", source="study_id")
    .derivation("USUBJID", expression=pl.concat_str([pl.col("STUDY"), pl.col("SUBJ")]))
    .assign("AESEV", source="severity", ct="C66769", ct_map={"Yes": "Y"})
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
    assert by["DOMAIN"]["block"] == {"algorithm": "assign", "value": "AE"}
    assert by["DOMAIN"]["line"] == 5
    assert by["STUDYID"]["block"] == {"algorithm": "assign", "source": "study_id"}
    assert by["AESEV"]["block"]["ct_map"] == {"Yes": "Y"}
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


DERIVATIONS = """
from programs.derivations import TRTDURD, add_pop_flags
import programs.derivations as drv
from fleet.core.derivation import derivation
import polars as pl


@derivation
def AGEGR1() -> pl.Expr:
    return pl.lit("x").alias("AGEGR1")


adsl = (
    dm.adam.pin("EX", ex)
    .derivation(TRTDURD)
    .derivation(drv.BMI)
    .derivation(add_pop_flags)
    .derivation(AGEGR1)
    .derivation("TRTSDT2", expression=TRTDURD)
    .to_frame()
)
"""


def test_study_derivation_objects_become_callable_blocks():
    rows = derivations_from_source(DERIVATIONS)
    # pin() is plumbing, not a derivation.
    assert [r["name"] for r in rows] == ["TRTDURD", "BMI", "add_pop_flags", "AGEGR1", "TRTSDT2"]
    by = {r["name"]: r for r in rows}
    assert by["TRTDURD"]["status"] == "ok"
    assert by["TRTDURD"]["block"] == {
        "algorithm": "derivation",
        "callable": "programs.derivations.TRTDURD",
    }
    assert by["BMI"]["block"] == {"algorithm": "derivation", "callable": "programs.derivations.BMI"}
    assert by["add_pop_flags"]["status"] == "stub"
    assert "runtime" in by["add_pop_flags"]["reason"]
    assert by["AGEGR1"]["status"] == "stub"
    assert "defined in this file" in by["AGEGR1"]["reason"]
    # expression=<name> may be a Derivation or a plain callable: not decided statically.
    assert by["TRTSDT2"]["status"] == "stub"


def test_program_from_spec_imports_study_callables(tmp_path):
    spec = tmp_path / "define.yaml"
    spec.write_text(
        "study:\n  id: X\n  standard: ADAMIG\nderivations_module: programs.derivations\n"
        "datasets:\n  - name: ADSL\n    variables:\n"
        "      - name: AGEGR1\n        derivation:\n          callable: AGEGR1\n"
        "          algorithm: derivation\n"
        "      - name: BMI\n        derivation:\n          algorithm: derivation\n"
        "          callable: study.derivs.BMI\n",
        encoding="utf-8",
    )
    code = program_from_spec(spec, "ADSL")
    assert "from programs.derivations import AGEGR1\n" in code
    assert "from study.derivs import BMI\n" in code
    assert "    .derivation(AGEGR1)\n    .derivation(BMI)\n    .to_frame()" in code

    spec.write_text(
        "study:\n  id: X\n  standard: ADAMIG\ndatasets:\n  - name: ADSL\n    variables:\n"
        "      - name: AGEGR1\n        derivation:\n          algorithm: derivation\n"
        "          callable: AGEGR1\n",
        encoding="utf-8",
    )
    assert "    .derivation(AGEGR1)  # TODO: import AGEGR1" in program_from_spec(spec, "ADSL")


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
        "          algorithm: merge\n          dataset: ADSL\n          on: [USUBJID]\n"
        "          keep: [TRTSDT]\n",
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


def test_program_from_spec_applies_the_variable_codelist(tmp_path):
    """The generated program carries the ct= that from_spec fills from codelist: (ADR-0008)."""
    spec = tmp_path / "define.yaml"
    spec.write_text(
        "study:\n  id: X\n  standard: SDTMIG\ndatasets:\n  - name: DM\n    variables:\n"
        "      - name: SEX\n        codelist: C66731\n        derivation:\n"
        "          algorithm: assign\n          source: sex\n",
        encoding="utf-8",
    )
    assert "    .assign('SEX', source='sex', ct='C66731')\n" in program_from_spec(spec, "DM")
