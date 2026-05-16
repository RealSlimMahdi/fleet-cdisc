"""Unit tests for from_spec() callable dispatch."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest
import yaml

import fleet  # noqa: F401 — triggers namespace registration
from fleet.adam.transforms import clear_transforms, register_transform
from fleet.core.derivation import derivation


@pytest.fixture(autouse=True)
def _clean_registry():
    """Ensure each test starts with a clean transform registry."""
    yield
    clear_transforms()


@pytest.fixture
def simple_df():
    return pl.DataFrame(
        {
            "USUBJID": ["01-001", "01-002"],
            "AGE": [45, 72],
        }
    )


@pytest.fixture
def spec_file(tmp_path: Path):
    """Return a factory that writes a temporary define.yaml and returns its path."""

    def _write(spec_dict: dict) -> Path:
        p = tmp_path / "define.yaml"
        p.write_text(yaml.dump(spec_dict, allow_unicode=True), encoding="utf-8")
        return p

    return _write


# ── algorithm: callable with registered Derivation ───────────────────────


class TestFromSpecCallableRegistered:
    def test_column_kind_dispatched(self, simple_df, spec_file):
        @derivation
        def AGEGR1() -> pl.Expr:
            return (
                pl.when(pl.col("AGE") < 65).then(pl.lit("<65")).otherwise(pl.lit(">=65"))
            ).alias("AGEGR1")

        spec = {
            "datasets": [
                {
                    "name": "ADSL",
                    "variables": [
                        {
                            "name": "AGEGR1",
                            "derivation": {"algorithm": "callable", "callable": "AGEGR1"},
                        }
                    ],
                }
            ]
        }
        result = simple_df.adam.from_spec(spec_file(spec), dataset="ADSL").to_frame()
        assert "AGEGR1" in result.columns
        assert result["AGEGR1"][0] == "<65"

    def test_frame_kind_dispatched(self, simple_df, spec_file):
        @derivation(targets=["MYFLAG"])
        def add_myflag(df: pl.DataFrame) -> pl.DataFrame:
            return df.with_columns(pl.lit("Y").alias("MYFLAG"))

        spec = {
            "datasets": [
                {
                    "name": "ADSL",
                    "variables": [
                        {
                            "name": "MYFLAG",
                            "derivation": {"algorithm": "callable", "callable": "add_myflag"},
                        }
                    ],
                }
            ]
        }
        result = simple_df.adam.from_spec(spec_file(spec), dataset="ADSL").to_frame()
        assert "MYFLAG" in result.columns

    def test_plain_callable_without_kind(self, simple_df, spec_file):
        """Plain register_transform callables (not Derivation objects) still work."""

        def plain_fn(df: pl.DataFrame) -> pl.DataFrame:
            return df.with_columns(pl.lit("P").alias("PLAIN_COL"))

        register_transform("plain_fn", plain_fn)

        spec = {
            "datasets": [
                {
                    "name": "ADSL",
                    "variables": [
                        {
                            "name": "PLAIN_COL",
                            "derivation": {"algorithm": "callable", "callable": "plain_fn"},
                        }
                    ],
                }
            ]
        }
        result = simple_df.adam.from_spec(spec_file(spec), dataset="ADSL").to_frame()
        assert "PLAIN_COL" in result.columns


# ── Backward compat: callable: without algorithm: ─────────────────────────


class TestBackwardCompatNoAlgorithm:
    def test_callable_without_algorithm_injected(self, simple_df, spec_file):
        """YAML with callable: but no algorithm: should still dispatch correctly."""

        @derivation
        def MY_COMPAT_VAR() -> pl.Expr:
            return pl.col("AGE").cast(pl.String).alias("MY_COMPAT_VAR")

        spec = {
            "datasets": [
                {
                    "name": "ADSL",
                    "variables": [
                        {
                            "name": "MY_COMPAT_VAR",
                            "derivation": {
                                # No algorithm: key — backward compat
                                "callable": "MY_COMPAT_VAR"
                            },
                        }
                    ],
                }
            ]
        }
        result = simple_df.adam.from_spec(spec_file(spec), dataset="ADSL").to_frame()
        assert "MY_COMPAT_VAR" in result.columns


# ── Dotted import path fallback ──────────────────────────────────────────


class TestDottedImportFallback:
    def test_unregistered_raises_value_error(self, simple_df):
        from fleet.adam.namespace import _resolve_callable

        with pytest.raises(ValueError, match="not registered"):
            _resolve_callable("COMPLETELY_UNKNOWN_FUNCTION_XYZ")

    def test_dotted_path_resolved(self):
        """A dotted path that is importable should be resolved successfully."""
        from fleet.adam.namespace import _resolve_callable

        # polars itself is importable; use a simple attribute as test
        result = _resolve_callable("polars.col")
        assert result is pl.col


# ── SDTM from_spec callable dispatch ─────────────────────────────────────


class TestSDTMFromSpecCallable:
    def test_column_kind_dispatched(self, simple_df, spec_file):
        @derivation
        def SDTM_DRV() -> pl.Expr:
            return pl.col("AGE").cast(pl.String).alias("SDTM_DRV")

        spec = {
            "datasets": [
                {
                    "name": "DM",
                    "variables": [
                        {
                            "name": "SDTM_DRV",
                            "derivation": {"algorithm": "callable", "callable": "SDTM_DRV"},
                        }
                    ],
                }
            ]
        }
        result = simple_df.sdtm.from_spec(spec_file(spec), dataset="DM").to_frame()
        assert "SDTM_DRV" in result.columns
