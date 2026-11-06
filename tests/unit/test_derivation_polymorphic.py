"""Unit tests for the polymorphic .derivation() verb on SDTM and ADaM namespaces."""

from __future__ import annotations

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration
from fleet.adam.transforms import clear_transforms
from fleet.core.derivation import derivation


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure each test starts with a clean transform registry."""
    yield
    clear_transforms()


@pytest.fixture
def simple_df():
    """Minimal frame for derivation tests."""
    return pl.from_repr("""\
┌─────────┬─────┬──────────┐
│ USUBJID ┆ AGE ┆ VSSTRESN │
│ ---     ┆ --- ┆ ---      │
│ str     ┆ i64 ┆ f64      │
╞═════════╪═════╪══════════╡
│ 01-001  ┆ 45  ┆ 120.0    │
│ 01-002  ┆ 72  ┆ 130.0    │
│ 01-003  ┆ 30  ┆ 115.0    │
└─────────┴─────┴──────────┘
""")


# ── Case 1: string expression ─────────────────────────────────────────────


class TestCase1StringExpression:
    def test_adam_string_expression(self, simple_df):
        result = simple_df.adam.derivation(
            "AVAL", expression="pl.col('VSSTRESN').cast(pl.Float64)"
        ).to_frame()
        assert "AVAL" in result.columns
        assert result["AVAL"].dtype == pl.Float64

    def test_sdtm_string_expression(self, simple_df):
        result = simple_df.sdtm.derivation(
            "MYVAR", expression="pl.col('AGE').cast(pl.String)"
        ).to_frame()
        assert "MYVAR" in result.columns
        assert result["MYVAR"].dtype == pl.String


# ── Case 2: direct pl.Expr ────────────────────────────────────────────────


class TestCase2DirectExpr:
    def test_adam_direct_expr(self, simple_df):
        result = simple_df.adam.derivation(
            "AVAL", expression=pl.col("VSSTRESN").cast(pl.Float64)
        ).to_frame()
        assert "AVAL" in result.columns

    def test_sdtm_direct_expr(self, simple_df):
        result = simple_df.sdtm.derivation(
            "MYVAR", expression=pl.col("AGE").cast(pl.String)
        ).to_frame()
        assert "MYVAR" in result.columns
        assert result["MYVAR"][0] == "45"


# ── Case 3: lambda returning pl.Expr ─────────────────────────────────────


class TestCase3Lambda:
    def test_adam_lambda(self, simple_df):
        result = simple_df.adam.derivation(
            "AGEGR1",
            expression=lambda: (
                pl.when(pl.col("AGE") < 65).then(pl.lit("<65 yrs")).otherwise(pl.lit(">=65 yrs"))
            ),
        ).to_frame()
        assert "AGEGR1" in result.columns
        assert result["AGEGR1"][0] == "<65 yrs"
        assert result["AGEGR1"][1] == ">=65 yrs"

    def test_sdtm_lambda(self, simple_df):
        result = simple_df.sdtm.derivation(
            "AGEGR1",
            expression=lambda: (
                pl.when(pl.col("AGE") < 65).then(pl.lit("<65")).otherwise(pl.lit(">=65"))
            ),
        ).to_frame()
        assert "AGEGR1" in result.columns

    def test_lambda_non_expr_raises_type_error(self, simple_df):
        with pytest.raises(TypeError, match="must return pl.Expr"):
            simple_df.adam.derivation("BAD", expression=lambda: "not an expr").to_frame()

    def test_sdtm_lambda_non_expr_raises(self, simple_df):
        with pytest.raises(TypeError, match="must return pl.Expr"):
            simple_df.sdtm.derivation("BAD", expression=lambda: 42).to_frame()


# ── Case 4: Derivation object ─────────────────────────────────────────────


class TestCase4DerivationObject:
    def test_adam_column_kind(self, simple_df):
        @derivation
        def AGEGR1() -> pl.Expr:
            return (
                pl.when(pl.col("AGE") < 65).then(pl.lit("<65 yrs")).otherwise(pl.lit(">=65 yrs"))
            ).alias("AGEGR1")

        result = simple_df.adam.derivation(AGEGR1).to_frame()
        assert "AGEGR1" in result.columns
        assert result["AGEGR1"][0] == "<65 yrs"

    def test_sdtm_column_kind(self, simple_df):
        @derivation
        def MYCOLVAR() -> pl.Expr:
            return pl.col("AGE").cast(pl.String).alias("MYCOLVAR")

        result = simple_df.sdtm.derivation(MYCOLVAR).to_frame()
        assert "MYCOLVAR" in result.columns

    def test_adam_frame_kind(self, simple_df):
        @derivation(targets=["NEW_COL"])
        def add_new_col(df: pl.DataFrame) -> pl.DataFrame:
            return df.with_columns(pl.lit("ADDED").alias("NEW_COL"))

        result = simple_df.adam.derivation(add_new_col).to_frame()
        assert "NEW_COL" in result.columns
        assert result["NEW_COL"][0] == "ADDED"

    def test_sdtm_frame_kind(self, simple_df):
        @derivation(targets=["EXTRA"])
        def add_extra(df: pl.DataFrame) -> pl.DataFrame:
            return df.with_columns(pl.lit("X").alias("EXTRA"))

        result = simple_df.sdtm.derivation(add_extra).to_frame()
        assert "EXTRA" in result.columns

    def test_adam_param_kind_is_refused(self, simple_df):
        """c1-44: kind param overwrote AVAL and added no row; derive_param adds the row."""
        from fleet.core.exceptions import VerbUsageError

        with pytest.raises(VerbUsageError, match="derive_param"):

            @derivation(by=["USUBJID"], set_values_to={"PARAMCD": "BMI"})
            def BMI_DRV(df: pl.DataFrame) -> pl.DataFrame:
                return df.with_columns(pl.lit(22.5).alias("AVAL"))

    def test_frame_kind_wrong_return_type_raises(self, simple_df):
        @derivation(targets=["BAD"])
        def bad_fn(df: pl.DataFrame) -> pl.DataFrame:
            return "not a dataframe"  # type: ignore[return-value]

        with pytest.raises(TypeError, match="expected pl.DataFrame"):
            simple_df.adam.derivation(bad_fn).to_frame()


# ── Error paths ───────────────────────────────────────────────────────────


class TestErrorPaths:
    def test_missing_expression_raises(self, simple_df):
        with pytest.raises(ValueError, match="expression is required"):
            simple_df.adam.derivation("FOO")

    def test_missing_target_raises(self, simple_df):
        with pytest.raises(ValueError, match="target is required"):
            simple_df.adam.derivation(None, expression="pl.col('AGE')")

    def test_sdtm_missing_expression_raises(self, simple_df):
        with pytest.raises(ValueError, match="expression is required"):
            simple_df.sdtm.derivation("FOO")


# ── Lineage nodes for frame kind ──────────────────────────────────────────


class TestLineageForFrameKind:
    def test_lineage_injected_after_frame_derivation(self, simple_df):
        from fleet.core.lineage import lineage_of

        @derivation(targets=["MY_TARGET"], sources=["USUBJID"])
        def my_frame_drv(df: pl.DataFrame) -> pl.DataFrame:
            return df.with_columns(pl.lit("Z").alias("MY_TARGET"))

        ns = simple_df.adam.derivation(my_frame_drv)
        nodes = lineage_of(ns)
        target_nodes = [n for n in nodes if n.name == "MY_TARGET"]
        assert len(target_nodes) == 1
        assert target_nodes[0].verb == "derivation"
        assert target_nodes[0].sources == ["USUBJID"]


# ── Chaining across cases ─────────────────────────────────────────────────


class TestChainingAcrossCases:
    def test_chain_string_then_expr(self, simple_df):
        result = (
            simple_df.adam.derivation("A", expression="pl.col('AGE').cast(pl.Float64)")
            .derivation("B", expression=pl.col("VSSTRESN") * 2)
            .to_frame()
        )
        assert "A" in result.columns
        assert "B" in result.columns

    def test_chain_derivation_object_then_string(self, simple_df):
        @derivation
        def COL_DRV() -> pl.Expr:
            return pl.col("AGE").cast(pl.String).alias("COL_DRV")

        result = (
            simple_df.adam.derivation(COL_DRV)
            .derivation("FOLLOW_UP", expression=pl.col("VSSTRESN") + 1)
            .to_frame()
        )
        assert "COL_DRV" in result.columns
        assert "FOLLOW_UP" in result.columns
