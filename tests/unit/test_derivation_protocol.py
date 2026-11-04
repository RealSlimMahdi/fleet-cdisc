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

        assert _infer_kind(fn) == "column"

    def test_frame_from_df_hint(self):
        def fn(df: pl.DataFrame) -> pl.DataFrame:
            return df

        assert _infer_kind(fn) == "frame"

    @pytest.mark.parametrize("kwargs", [{"by": ["USUBJID"]}, {"set_values_to": {"PARAMCD": "BMI"}}])
    def test_by_and_set_values_to_are_refused(self, kwargs):
        """c1-44: kind param appended no row and overwrote AVAL; derive_param does it."""
        from fleet.core.exceptions import VerbUsageError

        with pytest.raises(VerbUsageError, match="derive_param"):

            @derivation(**kwargs)
            def BMI(df: pl.DataFrame) -> pl.DataFrame:
                return df

    def test_column_from_no_params(self):
        def fn():
            return pl.col("AGE")

        assert _infer_kind(fn) == "column"

    def test_frame_from_params(self):
        def fn(df):
            return df

        assert _infer_kind(fn) == "frame"


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
        """c1-746: with no alias, the function name is the target, not the source column."""

        @derivation
        def FALLBACK() -> pl.Expr:
            return pl.col("AGE")  # no .alias()

        assert FALLBACK.targets == ["FALLBACK"]

    def test_a_column_derivation_without_alias_writes_the_function_name(self):
        """c1-746: AGEC used to overwrite AGE; a when/then wrote a column 'literal'."""
        adsl = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ AGE │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ S1      ┆ 30  │
│ S2      ┆ 70  │
└─────────┴─────┘
""")

        @derivation
        def AGEC() -> pl.Expr:
            return pl.col("AGE").cast(pl.String)

        @derivation
        def AGEGR1() -> pl.Expr:
            return pl.when(pl.col("AGE") < 65).then(pl.lit("<65")).otherwise(pl.lit(">=65"))

        out = adsl.adam.adsl.derivation(AGEC).derivation(AGEGR1).to_frame()

        assert out.columns == ["USUBJID", "AGE", "AGEC", "AGEGR1"]
        assert out["AGE"].to_list() == [30, 70]
        assert out["AGEC"].to_list() == ["30", "70"]
        assert out["AGEGR1"].to_list() == ["<65", ">=65"]

    def test_an_explicit_alias_still_wins(self):
        @derivation
        def helper() -> pl.Expr:
            return (pl.col("AGE") * 2).alias("AGE2")

        assert helper.targets == ["AGE2"]

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

        df = pl.from_repr("""\
┌─────┐
│ X   │
│ --- │
│ i64 │
╞═════╡
│ 1   │
│ 2   │
└─────┘
""")
        result = add_col(df)
        assert isinstance(result, pl.DataFrame)
        assert "NEW_COL" in result.columns


# ── c1-44 / c1-746: the parameter row verb, the spec target, the scaffold ──


def test_derive_param_adds_the_bmi_row_and_keeps_the_input_aval():
    """c1-44: the tested verb for a new parameter row, in place of kind param."""
    advs = pl.from_repr("""\
┌─────────┬─────┬─────────┬───────┐
│ USUBJID ┆ ADT ┆ PARAMCD ┆ AVAL  │
│ ---     ┆ --- ┆ ---     ┆ ---   │
│ str     ┆ i64 ┆ str     ┆ f64   │
╞═════════╪═════╪═════════╪═══════╡
│ S1      ┆ 1   ┆ WEIGHT  ┆ 70.0  │
│ S1      ┆ 1   ┆ HEIGHT  ┆ 170.0 │
└─────────┴─────┴─────────┴───────┘
""")
    out = advs.adam.derive_param(
        by=["USUBJID", "ADT"],
        set_values_to={"PARAMCD": "BMI"},
        parameter_filter={"WEIGHT": "WEIGHT", "HEIGHT": "HEIGHT"},
        analysis_value=pl.col("WEIGHT") / (pl.col("HEIGHT") / 100) ** 2,
    ).to_frame()

    assert out.height == 3
    assert out["PARAMCD"].to_list() == ["WEIGHT", "HEIGHT", "BMI"]
    assert out["AVAL"].to_list()[:2] == [70.0, 170.0]
    assert out["AVAL"][2] == pytest.approx(24.22145, abs=1e-5)


def test_a_spec_callable_that_writes_another_column_is_refused(tmp_path):
    """c1-746: the spec variable must be the column the callable writes."""
    from fleet.core.exceptions import SpecError

    @derivation
    def AGEC() -> pl.Expr:
        return pl.col("AGE").cast(pl.String)

    adsl = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ AGE │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ S1      ┆ 30  │
└─────────┴─────┘
""")
    spec = tmp_path / "define.yaml"
    spec.write_text(
        "datasets:\n  - name: ADSL\n    variables:\n      - name: AGECAT\n"
        "        derivation:\n          algorithm: derivation\n          callable: AGEC\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecError, match=r"writes \['AGEC'\], not AGECAT"):
        adsl.adam.adsl.from_spec(spec, dataset="ADSL")


def _cli(argv: list[str]) -> int:
    from fleet import cli

    try:
        cli.main(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def test_the_column_scaffold_writes_its_own_column(tmp_path, monkeypatch):
    """c1-746: the template had no alias, so AGEC overwrote AGE."""
    import importlib.util

    assert _cli(["init", "cfg", "--study-id", "S01", "--root", str(tmp_path)]) == 0
    config = str(tmp_path / "study_config.yaml")
    assert _cli(["derivation", "add", "AGEC", "--dataset", "ADSL", "--config", config]) == 0

    path = next(tmp_path.rglob("derivations/AGEC.py"))
    text = path.read_text(encoding="utf-8")
    assert '.alias("AGEC")' in text
    path.write_text(text.replace("REPLACE_ME", "AGE"), encoding="utf-8")
    spec = importlib.util.spec_from_file_location("agec_scaffold", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    adsl = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ AGE │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ S1      ┆ 30  │
└─────────┴─────┘
""")
    out = adsl.adam.adsl.derivation(module.AGEC).to_frame()
    assert out["AGE"].to_list() == [30]
    assert out["AGEC"].to_list() == ["30"]


@pytest.mark.parametrize("name", ["AGE-C", "1AGE", "class"])
def test_the_scaffold_refuses_a_name_that_is_not_an_identifier(tmp_path, name):
    assert _cli(["init", "cfg", "--study-id", "S01", "--root", str(tmp_path)]) == 0
    config = str(tmp_path / "study_config.yaml")

    assert _cli(["derivation", "add", name, "--dataset", "ADSL", "--config", config]) == 1
    assert not list(tmp_path.rglob(f"derivations/{name}.py"))


def test_the_param_scaffold_kind_is_gone(tmp_path):
    assert _cli(["init", "cfg", "--study-id", "S01", "--root", str(tmp_path)]) == 0
    config = str(tmp_path / "study_config.yaml")

    argv = ["derivation", "add", "BMI", "--dataset", "ADVS", "--kind", "param", "--config", config]
    assert _cli(argv) == 2
