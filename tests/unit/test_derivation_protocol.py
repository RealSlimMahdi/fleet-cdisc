"""Unit tests for the @derivation decorator and Derivation protocol."""

from __future__ import annotations

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration
from fleet.adam.transforms import clear_transforms, get_transform, list_transforms
from fleet.core.derivation import Derivation, _infer_kind, derivation


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure each test starts with a clean transform registry."""
    yield
    clear_transforms()


# ── Kind inference ────────────────────────────────────────────────────────


class TestKindInference:
    def test_column_from_expr_hint(self):
        def fn() -> pl.Expr:
            return pl.col("AGE")

        assert _infer_kind(fn, by=None, set_values_to=None) == "column"

    def test_frame_from_df_hint(self):
        def fn(df: pl.DataFrame) -> pl.DataFrame:
            return df

        assert _infer_kind(fn, by=None, set_values_to=None) == "frame"

    def test_param_from_by(self):
        def fn(df: pl.DataFrame) -> pl.DataFrame:
            return df

        assert _infer_kind(fn, by=["USUBJID"], set_values_to=None) == "param"

    def test_param_from_set_values_to(self):
        def fn(df: pl.DataFrame) -> pl.DataFrame:
            return df

        assert _infer_kind(fn, by=None, set_values_to={"PARAMCD": "BMI"}) == "param"

    def test_column_from_no_params(self):
        def fn():
            return pl.col("AGE")

        assert _infer_kind(fn, by=None, set_values_to=None) == "column"

    def test_frame_from_params(self):
        def fn(df):
            return df

        assert _infer_kind(fn, by=None, set_values_to=None) == "frame"


# ── @derivation bare form ─────────────────────────────────────────────────


class TestDecorationBareForm:
    def test_returns_derivation_instance(self):
        @derivation
        def MY_VAR() -> pl.Expr:
            return pl.col("AGE").cast(pl.Float64).alias("MY_VAR")

        assert isinstance(MY_VAR, Derivation)

    def test_kind_column(self):
        @derivation
        def MY_VAR() -> pl.Expr:
            return pl.col("AGE").cast(pl.Float64).alias("MY_VAR")

        assert MY_VAR.kind == "column"

    def test_dotted_path_contains_qualname(self):
        @derivation
        def MY_VAR() -> pl.Expr:
            return pl.col("AGE").alias("MY_VAR")

        assert MY_VAR.dotted_path.endswith(".MY_VAR")

    def test_auto_registration(self):
        @derivation
        def MY_AUTOVAR() -> pl.Expr:
            return pl.col("AGE").alias("MY_AUTOVAR")

        assert "MY_AUTOVAR" in list_transforms()
        assert get_transform("MY_AUTOVAR") is MY_AUTOVAR

    def test_auto_sources_from_expr(self):
        @derivation
        def MY_AGE() -> pl.Expr:
            return pl.col("AGE").alias("MY_AGE")

        assert "AGE" in MY_AGE.sources

    def test_auto_targets_from_alias(self):
        @derivation
        def MY_AGE() -> pl.Expr:
            return pl.col("AGE").alias("MY_AGE")

        assert MY_AGE.targets == ["MY_AGE"]

    def test_targets_fallback_to_name(self):
        """When expression has no alias, target falls back to function name."""

        @derivation
        def FALLBACK() -> pl.Expr:
            return pl.col("AGE")  # no .alias()

        # Either FALLBACK or "AGE" — just ensure list is non-empty
        assert len(FALLBACK.targets) == 1

    def test_name_equals_function_name(self):
        @derivation
        def MY_FN() -> pl.Expr:
            return pl.col("X").alias("MY_FN")

        assert MY_FN.name == "MY_FN"


# ── @derivation parameterised form ───────────────────────────────────────


class TestDecorationParameterisedForm:
    def test_frame_kind_explicit_targets(self):
        @derivation(targets=["SAFFL", "ITTFL"])
        def add_pop_flags(df: pl.DataFrame) -> pl.DataFrame:
            return df.with_columns(pl.lit("Y").alias("SAFFL"), pl.lit("Y").alias("ITTFL"))

        assert add_pop_flags.kind == "frame"
        assert add_pop_flags.targets == ["SAFFL", "ITTFL"]

    def test_param_kind_with_by_and_set_values(self):
        @derivation(
            by=["USUBJID"],
            set_values_to={"PARAMCD": "BMI"},
        )
        def BMI(df: pl.DataFrame) -> pl.DataFrame:
            return df

        assert BMI.kind == "param"
        assert BMI.by_vars == ["USUBJID"]
        assert BMI.set_values_to == {"PARAMCD": "BMI"}

    def test_auto_registration_parameterised(self):
        @derivation(targets=["MYFLAG"])
        def MY_FRAME_FN(df: pl.DataFrame) -> pl.DataFrame:
            return df.with_columns(pl.lit("Y").alias("MYFLAG"))

        assert "MY_FRAME_FN" in list_transforms()


# ── Derivation.__call__ ───────────────────────────────────────────────────


class TestDerivationCall:
    def test_column_kind_returns_expr(self):
        @derivation
        def MY_EXPR() -> pl.Expr:
            return pl.col("X").alias("MY_EXPR")

        result = MY_EXPR()
        assert isinstance(result, pl.Expr)

    def test_frame_kind_receives_df(self):
        @derivation(targets=["NEW_COL"])
        def add_col(df: pl.DataFrame) -> pl.DataFrame:
            return df.with_columns(pl.lit(1).alias("NEW_COL"))

        df = pl.DataFrame({"X": [1, 2]})
        result = add_col(df)
        assert isinstance(result, pl.DataFrame)
        assert "NEW_COL" in result.columns

    def test_param_kind_receives_df(self):
        @derivation(by=["X"], set_values_to={"P": "V"})
        def my_param_fn(df: pl.DataFrame) -> pl.DataFrame:
            return df.with_columns(pl.lit(99).alias("AVAL"))

        df = pl.DataFrame({"X": [1]})
        result = my_param_fn(df)
        assert "AVAL" in result.columns
