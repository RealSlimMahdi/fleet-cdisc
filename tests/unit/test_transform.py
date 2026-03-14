"""Unit tests for the transform verb and registry."""

import polars as pl
import pytest

import pymaverse  # noqa: F401 — triggers namespace registration
from pymaverse.adam.transforms import (
    register_transform,
    get_transform,
    list_transforms,
    clear_transforms,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure each test starts with a clean transform registry."""
    yield
    clear_transforms()


@pytest.fixture
def dm_frame():
    """Minimal DM-like frame."""
    return pl.DataFrame({
        "USUBJID": ["01-001", "01-002", "01-003"],
        "AGE": [45, 72, 30],
        "SEX": ["M", "F", "M"],
    })


# ── Registry tests ────────────────────────────────────────────────────────

class TestRegistry:
    def test_decorator_form(self):
        @register_transform("my_fn")
        def my_fn(df: pl.DataFrame) -> pl.DataFrame:
            return df

        assert "my_fn" in list_transforms()
        assert get_transform("my_fn") is my_fn

    def test_imperative_form(self):
        def my_fn(df: pl.DataFrame) -> pl.DataFrame:
            return df

        register_transform("my_fn", my_fn)
        assert get_transform("my_fn") is my_fn

    def test_get_unknown_raises(self):
        with pytest.raises(KeyError, match="not registered"):
            get_transform("nonexistent")

    def test_clear(self):
        register_transform("tmp", lambda df: df)
        assert "tmp" in list_transforms()
        clear_transforms()
        assert list_transforms() == []

    def test_register_non_callable_raises(self):
        with pytest.raises(TypeError, match="callable"):
            register_transform("bad", 42)  # type: ignore[arg-type]


# ── Inline transform tests ────────────────────────────────────────────────

class TestTransformInline:
    def test_direct_callable(self, dm_frame):
        def add_agegr1(df: pl.DataFrame) -> pl.DataFrame:
            return df.with_columns(
                pl.when(pl.col("AGE") < 65)
                .then(pl.lit("<65"))
                .otherwise(pl.lit(">=65"))
                .alias("AGEGR1")
            )

        result = dm_frame.adam.transform(add_agegr1).to_frame()
        assert "AGEGR1" in result.columns
        assert result["AGEGR1"].to_list() == ["<65", ">=65", "<65"]

    def test_registered_name(self, dm_frame):
        @register_transform("add_flag")
        def add_flag(df: pl.DataFrame) -> pl.DataFrame:
            return df.with_columns(pl.lit("Y").alias("MYFLAG"))

        result = dm_frame.adam.transform("add_flag").to_frame()
        assert result["MYFLAG"].to_list() == ["Y", "Y", "Y"]

    def test_unregistered_name_raises(self, dm_frame):
        with pytest.raises(KeyError, match="not registered"):
            dm_frame.adam.transform("bogus").to_frame()

    def test_non_callable_raises(self, dm_frame):
        with pytest.raises(TypeError, match="callable"):
            dm_frame.adam.transform(123).to_frame()  # type: ignore[arg-type]

    def test_bad_return_type_raises(self, dm_frame):
        def bad_fn(df: pl.DataFrame):
            return {"oops": True}

        with pytest.raises(TypeError, match="polars DataFrame"):
            dm_frame.adam.transform(bad_fn).to_frame()

    def test_chaining_before_and_after(self, dm_frame):
        """Transform chains seamlessly with other verbs."""
        def add_elderly(df: pl.DataFrame) -> pl.DataFrame:
            return df.with_columns(
                pl.when(pl.col("AGE") >= 65)
                .then(pl.lit("Y"))
                .otherwise(pl.lit(None))
                .alias("ELDERLYFL")
            )

        result = (
            dm_frame.adam
            .assigned("STUDYID", value="STUDY01")
            .transform(add_elderly, label="Elderly flag")
            .source("USUBJID")
            .to_frame()
        )
        assert "STUDYID" in result.columns
        assert "ELDERLYFL" in result.columns
        assert result["ELDERLYFL"][1] == "Y"   # age 72
        assert result["ELDERLYFL"][0] is None   # age 45

    def test_pipeline_materialises_before_transform(self, dm_frame):
        """Pending expressions are committed before the transform runs."""
        def check_col_exists(df: pl.DataFrame) -> pl.DataFrame:
            assert "MY_COL" in df.columns, "Pipeline was not materialised"
            return df

        dm_frame.adam.assigned("MY_COL", value=1).transform(check_col_exists).to_frame()

    def test_label_is_ignored(self, dm_frame):
        """label= is cosmetic — doesn't affect output."""
        result = dm_frame.adam.transform(lambda df: df, label="noop").to_frame()
        assert result.shape == dm_frame.shape


# ── from_spec omit tests ──────────────────────────────────────────────────

MINI_SPEC_YAML = """\
datasets:
  - name: TEST
    label: Test Dataset
    structure: One record per subject
    class: SUBJECT LEVEL ANALYSIS DATASET
    keys: [STUDYID, USUBJID]
    variables:
      - name: STUDYID
        label: Study Identifier
        type: text
        derivation:
          algorithm: assigned
          value: "STUDY01"

      - name: USUBJID
        label: Unique Subject Identifier
        type: text
        derivation:
          algorithm: source
          source: USUBJID

      - name: MYVAR
        label: A derived variable
        type: text
        derivation:
          algorithm: assigned
          value: "FROM_SPEC"
"""


class TestFromSpecOmit:
    @pytest.fixture
    def spec_path(self, tmp_path):
        p = tmp_path / "define.yaml"
        p.write_text(MINI_SPEC_YAML)
        return str(p)

    @pytest.fixture
    def base_frame(self):
        return pl.DataFrame({
            "USUBJID": ["SUBJ-001", "SUBJ-002"],
        })

    def test_omit_skips_variable(self, base_frame, spec_path):
        """Omitted variables are not derived by from_spec."""
        result = (
            base_frame.adam
            .from_spec(spec_path, dataset="TEST", omit=["MYVAR"])
            .to_frame()
        )
        assert "STUDYID" in result.columns
        assert "MYVAR" not in result.columns

    def test_omit_allows_inline_override(self, base_frame, spec_path):
        """Omit a variable from spec, then derive it with custom logic."""
        result = (
            base_frame.adam
            .from_spec(spec_path, dataset="TEST", omit=["MYVAR"])
            .assigned("MYVAR", value="FROM_INLINE")
            .to_frame()
        )
        assert result["MYVAR"].to_list() == ["FROM_INLINE", "FROM_INLINE"]

    def test_only_and_omit_raises(self, base_frame, spec_path):
        """Specifying both only= and omit= is an error."""
        with pytest.raises(ValueError, match="Cannot specify both"):
            base_frame.adam.from_spec(
                spec_path, dataset="TEST", only=["STUDYID"], omit=["MYVAR"]
            )

    def test_omit_empty_list_processes_all(self, base_frame, spec_path):
        """An empty omit list processes everything (no-op)."""
        result = base_frame.adam.from_spec(spec_path, dataset="TEST", omit=[]).to_frame()
        assert "STUDYID" in result.columns
        assert "MYVAR" in result.columns
