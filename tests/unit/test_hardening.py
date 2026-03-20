"""Tests for API hardening changes: copy.copy chaining, inspect/explain, and AST whitelist."""

from __future__ import annotations

import polars as pl
import pytest

import fleet  # noqa: F401  — triggers namespace registration


# ====================================================================
# Phase 1 — copy.copy preserves subclass state
# ====================================================================


class TestCopyChainPreservesState:
    """Verify that _chain and _materialise_then preserve instance attrs."""

    def test_adam_chain_preserves_custom_attr(self):
        """ADaM mixin _chain should carry forward extra instance attrs."""
        df = pl.DataFrame({"USUBJID": ["S01"], "AVAL": [1.0]})
        ns = df.adam
        ns._custom_marker = "hello"  # simulate subclass state
        chained = ns.source("USUBJID")
        assert getattr(chained, "_custom_marker", None) == "hello"

    def test_adam_materialise_then_preserves_custom_attr(self):
        df = pl.DataFrame({"USUBJID": ["S01"], "AVAL": [1.0]})
        ns = df.adam
        ns._custom_marker = 42
        new_ns = ns._materialise_then(df)
        assert getattr(new_ns, "_custom_marker", None) == 42

    def test_sdtm_chain_preserves_custom_attr(self):
        df = pl.DataFrame({"subject_id": ["S01"]})
        ns = df.sdtm
        ns._custom_marker = "sdtm_state"
        chained = ns.assign_no_ct("USUBJID", source="subject_id")
        assert getattr(chained, "_custom_marker", None) == "sdtm_state"

    def test_sdtm_materialise_then_preserves_custom_attr(self):
        df = pl.DataFrame({"USUBJID": ["S01"]})
        ns = df.sdtm
        ns._custom_marker = [1, 2, 3]
        new_ns = ns._materialise_then(df)
        assert getattr(new_ns, "_custom_marker", None) == [1, 2, 3]

    def test_tdd_state_survives_chain(self):
        """TDD mixin attrs should survive _chain (via copy.copy)."""
        df = pl.DataFrame({"STUDYID": ["S01"], "DOMAIN": ["TE"]})
        ns = df.sdtm
        ns._tdd_stage = 2
        ns._domain_meta = {"domain": "TE"}
        ns._reconciliation_report = ["warn1"]
        chained = ns._chain(pl.lit("X").alias("EXTRA"))
        assert chained._tdd_stage == 2
        assert chained._domain_meta == {"domain": "TE"}
        assert chained._reconciliation_report == ["warn1"]


# ====================================================================
# Phase 2 — inspect / explain debug verbs
# ====================================================================


class TestInspectExplain:
    """Verify inspect and explain verbs work on both namespaces."""

    def test_adam_inspect_creates_checkpoint(self):
        df = pl.DataFrame({"USUBJID": ["S01", "S02"], "AVAL": [1.0, 2.0]})
        result = df.adam.source("USUBJID").inspect().to_frame()
        assert result.shape == (2, 2)
        assert "USUBJID" in result.columns

    def test_adam_explain_returns_self(self):
        df = pl.DataFrame({"USUBJID": ["S01"], "AVAL": [1.0]})
        ns = df.adam.source("USUBJID")
        returned = ns.explain()
        assert returned is ns

    def test_sdtm_inspect_creates_checkpoint(self):
        df = pl.DataFrame({"subject_id": ["S01", "S02"]})
        result = (
            df.sdtm
            .assign_no_ct("USUBJID", source="subject_id")
            .inspect()
            .hardcode_no_ct("DOMAIN", value="DM")
            .to_frame()
        )
        assert "USUBJID" in result.columns
        assert "DOMAIN" in result.columns

    def test_sdtm_explain_returns_self(self):
        df = pl.DataFrame({"subject_id": ["S01"]})
        ns = df.sdtm.assign_no_ct("USUBJID", source="subject_id")
        returned = ns.explain()
        assert returned is ns

    def test_inspect_prints_output(self, capsys):
        df = pl.DataFrame({"USUBJID": ["S01"], "AVAL": [1.0]})
        df.adam.source("USUBJID").inspect(prefix="TEST")
        captured = capsys.readouterr()
        assert "[TEST] Schema:" in captured.out
        assert "[TEST] Shape:" in captured.out

    def test_explain_prints_output(self, capsys):
        df = pl.DataFrame({"USUBJID": ["S01"]})
        df.adam.source("USUBJID").explain()
        captured = capsys.readouterr()
        assert len(captured.out.strip()) > 0


# ====================================================================
# Phase 3 — AST whitelist for parse_expression
# ====================================================================


class TestASTWhitelist:
    """Verify the AST safety gate in parse_expression."""

    def test_bare_column_name(self):
        from fleet.sdtm.utils import parse_expression

        expr = parse_expression("VSSTRESN")
        # Should produce pl.col("VSSTRESN")
        df = pl.DataFrame({"VSSTRESN": [1.0]})
        result = df.select(expr)
        assert result["VSSTRESN"][0] == 1.0

    def test_polars_col_expression(self):
        from fleet.sdtm.utils import parse_expression

        expr = parse_expression("pl.col('VSSTRESN').cast(pl.Float64)")
        df = pl.DataFrame({"VSSTRESN": [1]})
        result = df.select(expr)
        assert result["VSSTRESN"].dtype == pl.Float64

    def test_polars_arithmetic(self):
        from fleet.sdtm.utils import parse_expression

        expr = parse_expression("pl.col('A') + 1")
        df = pl.DataFrame({"A": [10]})
        result = df.select(expr)
        assert result["A"][0] == 11

    def test_polars_when_then(self):
        from fleet.sdtm.utils import parse_expression

        expr = parse_expression(
            'pl.when(pl.col("A") > 0).then(pl.lit("POS")).otherwise(pl.lit("NEG"))'
        )
        df = pl.DataFrame({"A": [1, -1]})
        result = df.select(expr.alias("R"))
        assert result["R"].to_list() == ["POS", "NEG"]

    def test_polars_cast_strict_false(self):
        """Verify the actual YAML expression pattern used in specs works."""
        from fleet.sdtm.utils import parse_expression

        expr = parse_expression("pl.col('vsorres').cast(pl.Float64, strict=False)")
        df = pl.DataFrame({"vsorres": ["1.5", "bad"]})
        result = df.select(expr)
        assert result["vsorres"][0] == 1.5

    # --- Rejection tests ---

    def test_rejects_import(self):
        from fleet.sdtm.utils import parse_expression

        with pytest.raises(ValueError, match="Dunder identifier"):
            parse_expression("__import__('os').system('echo pwned')")

    def test_rejects_dunder_attr_traversal(self):
        from fleet.sdtm.utils import parse_expression

        with pytest.raises(ValueError):
            parse_expression("().__class__.__bases__")

    def test_rejects_lambda(self):
        from fleet.sdtm.utils import parse_expression

        with pytest.raises(ValueError, match="Disallowed construct"):
            parse_expression("(lambda: pl.col('A'))()")

    def test_rejects_list_comprehension(self):
        from fleet.sdtm.utils import parse_expression

        with pytest.raises(ValueError, match="Disallowed construct"):
            parse_expression("[x for x in [1,2,3]]")

    def test_rejects_generator_expression(self):
        from fleet.sdtm.utils import parse_expression

        with pytest.raises(ValueError, match="Disallowed construct"):
            parse_expression("list(x for x in [1,2,3])")
