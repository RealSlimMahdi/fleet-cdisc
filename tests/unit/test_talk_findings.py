"""Regression tests for the talk package: texts that must match the code."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import polars as pl
import pytest

import fleet  # noqa: F401
from fleet.adam.pk_namespace import PKNamespace

ROOT = Path(__file__).resolve().parents[2]


def _load_run_benchmark():
    spec = importlib.util.spec_from_file_location(
        "run_benchmark", ROOT / "benchmark" / "run_benchmark.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestValidationStrategyText:
    """c1-341: docs/validation-strategy.md names only what the code accepts."""

    def test_every_bsa_method_in_the_parity_table_is_accepted(self):
        text = (ROOT / "docs" / "validation-strategy.md").read_text(encoding="utf-8")
        row = next(line for line in text.splitlines() if line.startswith("| `TestBSA`"))
        methods = re.findall(r"[A-Z][A-Za-z]+(?:-[A-Z][A-Za-z]+)?", row.split("|")[2])
        frame = pl.from_repr("""
┌─────────┬────────┬────────┐
│ USUBJID ┆ HEIGHT ┆ WEIGHT │
│ ---     ┆ ---    ┆ ---    │
│ str     ┆ f64    ┆ f64    │
╞═════════╪════════╪════════╡
│ S1      ┆ 170.0  ┆ 70.0   │
└─────────┴────────┴────────┘
""")
        assert len(methods) == 4
        for method in methods:
            out = frame.adam.bsa("BSA", height="HEIGHT", weight="WEIGHT", method=method)
            assert out.to_frame()["BSA"][0] > 0

    def test_the_page_lists_the_pchg_sign_difference(self):
        text = (ROOT / "docs" / "validation-strategy.md").read_text(encoding="utf-8")
        assert "400+" not in text
        assert "numerically identical" not in text
        assert "AVAL -5, BASE -10 gives PCHG -50" in text


class TestAdncaVerbMap:
    """c1-342: the ADNCA example and the PK docstring name only real verbs."""

    def test_pk_module_docstring_calls_only_existing_verbs(self):
        import fleet.adam.pk_namespace as pk

        called = set(re.findall(r"\.([a-z_]+)\(", pk.__doc__))
        assert "actual_time" not in called
        missing = {name for name in called if not hasattr(PKNamespace, name)}
        assert missing == set()

    def test_example_prints_a_verb_map_without_check_marks(self):
        text = (ROOT / "examples" / "adnca_example.py").read_text(encoding="utf-8")
        assert "\u2713" not in text
        assert "Feature Parity" not in text
        assert "actual_time" not in text


class TestTherapeuticAreaWording:
    """c1-343: TA modules say "inspired by", not "ported from" or "mirrors"."""

    @pytest.mark.parametrize("module", ["onco", "vaccine", "peds", "metabolic", "neuro"])
    def test_module_docstring_does_not_claim_a_port(self, module):
        path = ROOT / "src" / "fleet" / "adam" / f"{module}_namespace.py"
        text = path.read_text(encoding="utf-8")
        assert "ported from" not in text
        assert "mirrors" not in text.lower()

    @pytest.mark.parametrize("page", ["docs/index.md", "docs/api/ta.md"])
    def test_docs_do_not_say_mirror(self, page):
        text = (ROOT / page).read_text(encoding="utf-8")
        assert "mirror" not in text.lower()


class TestCoreTerminologyText:
    """c1-344: no text calls CORE the codelist authority."""

    def test_study_codelists_does_not_call_core_the_authority(self):
        from fleet.ct import study_codelists

        assert "CORE stays the authority" not in study_codelists.spec_codelists.__doc__

    def test_validation_core_page_says_pass_does_not_cover_ct(self):
        text = (ROOT / "docs" / "concepts" / "validation-core.md").read_text(encoding="utf-8")
        assert "What a PASS does not cover: controlled terminology" in text


class TestBenchmark:
    """c1-483, c1-484, c1-487: benchmark rules and the report."""

    def test_anl01fl_tie_rule_flags_one_record(self):
        adae = pl.from_repr("""
┌─────────┬────────┬────────┬───────┐
│ USUBJID ┆ AETERM ┆ AESEVN ┆ AESEQ │
│ ---     ┆ ---    ┆ ---    ┆ ---   │
│ str     ┆ str    ┆ i64    ┆ i64   │
╞═════════╪════════╪════════╪═══════╡
│ S1      ┆ NAUSEA ┆ 2      ┆ 1     │
│ S1      ┆ NAUSEA ┆ 2      ┆ 2     │
│ S1      ┆ NAUSEA ┆ 1      ┆ 3     │
└─────────┴────────┴────────┴───────┘
""")
        out = adae.adam.flag(
            "ANL01FL",
            criteria="last",
            order_by=["AESEVN", "AESEQ"],
            by=["USUBJID", "AETERM"],
        ).to_frame()
        assert out["ANL01FL"].to_list() == [None, "Y", None]

    def test_full_row_comparison_reports_one_changed_value(self):
        run_benchmark = _load_run_benchmark()
        fleet_out = pl.from_repr("""
┌─────────┬───────┬──────┬─────────┐
│ USUBJID ┆ AESEQ ┆ ASEQ ┆ ANL01FL │
│ ---     ┆ ---   ┆ ---  ┆ ---     │
│ str     ┆ i32   ┆ i64  ┆ str     │
╞═════════╪═══════╪══════╪═════════╡
│ S1      ┆ 1     ┆ 1    ┆ Y       │
│ S1      ┆ 2     ┆ 2    ┆ null    │
└─────────┴───────┴──────┴─────────┘
""")
        admiral_out = fleet_out.with_columns(pl.lit("Y").alias("ANL01FL"))
        problems = run_benchmark.compare_outputs(fleet_out, admiral_out)
        assert [p for p in problems if p.startswith("ANL01FL")] == [
            "ANL01FL: 1 row(s) differ, first at USUBJID S1 ASEQ 2: Fleet None, admiral 'Y'"
        ]
        assert run_benchmark.compare_outputs(fleet_out, fleet_out) == [
            p for p in problems if "missing" in p
        ]

    def test_report_states_the_synthetic_data_and_near_linear_scaling(self):
        text = (ROOT / "benchmark" / "REPORT.md").read_text(encoding="utf-8")
        assert "real CDISCPILOT01" not in text
        assert "Super-linear" not in text
        assert "identical" not in text
        assert "synthetic 64-row AE extract" in text
