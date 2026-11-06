"""Behavioural tests for the shared, registry-driven ``from_spec`` engine.

Covers the DX-review items implemented on top of the algorithm registry:

* C6  — typo-tolerant flat bags are gone: unknown derivation keys and
  missing required fields raise ``SpecError`` with full context.
* C14 — unknown ``algorithm:`` raises by default; ``strict=False``
  restores warn-and-skip.
* C7  — spec variables refuse to overwrite existing columns unless
  ``overwrite=True`` (or the variable is a declared carry-through /
  listed in ``omit=``); SDTM gains the same ``only=``/``omit=`` as ADaM.
* §4.2 — every per-variable failure is re-raised as
  ``SpecError("<file> → dataset <ds> → variable <name>: ...")``.
* Spec versioning (``fleet_spec_version``) and the spec-level
  ``derivations_module:`` escape hatch.
* ``select(spec=...)`` warns on dropped computed columns and on
  spec-declared columns absent from the frame.
* Duplicate transform registrations warn instead of silently shadowing.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import polars as pl
import pytest
import yaml

import fleet  # noqa: F401 — triggers namespace registration
from fleet.adam.transforms import clear_transforms, register_transform
from fleet.core.exceptions import SpecError


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    clear_transforms()


@pytest.fixture
def write_spec(tmp_path: Path):
    """Factory writing a spec dict to a temporary YAML file."""

    def _write(spec: dict, name: str = "define.yaml") -> Path:
        p = tmp_path / name
        p.write_text(yaml.dump(spec, allow_unicode=True), encoding="utf-8")
        return p

    return _write


def _define(variables: list[dict], dataset: str = "ADSL", **top: object) -> dict:
    return {
        "datasets": [{"name": dataset, "variables": variables}],
        **top,
    }


@pytest.fixture
def subjects() -> pl.DataFrame:
    return pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ AGE │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ S1      ┆ 70  │
│ S2      ┆ 50  │
└─────────┴─────┘
""")


# ──────────────────────────────────────────────────────────────────────
# C6 — strict per-algorithm models
# ──────────────────────────────────────────────────────────────────────


class TestStrictModels:
    def test_misspelled_key_raises_with_context(self, subjects, write_spec):
        """`recod_map` (typo) is a SpecError naming file, dataset, variable."""
        spec = write_spec(
            _define(
                [
                    {
                        "name": "SEXN",
                        "derivation": {
                            "algorithm": "recode",
                            "source": "AGE",
                            "recod_map": {"70": "old"},
                        },
                    }
                ]
            )
        )
        with pytest.raises(SpecError, match=r"dataset ADSL → variable SEXN"):
            subjects.adam.from_spec(spec, dataset="ADSL")

    def test_missing_required_field_raises_with_context(self, subjects, write_spec):
        """bmi without weight/height fails validation, not silently."""
        spec = write_spec(
            _define([{"name": "BMI", "derivation": {"algorithm": "bmi", "weight": "WT"}}])
        )
        with pytest.raises(SpecError, match=r"(?s)variable BMI.*height"):
            subjects.adam.from_spec(spec, dataset="ADSL")


# ──────────────────────────────────────────────────────────────────────
# C14 — unknown algorithm: hard error by default, warn-and-skip opt-in
# ──────────────────────────────────────────────────────────────────────


class TestUnknownAlgorithm:
    def test_unknown_algorithm_raises_by_default(self, subjects, write_spec):
        spec = write_spec(
            _define([{"name": "X", "derivation": {"algorithm": "recde", "source": "AGE"}}])
        )
        with pytest.raises(SpecError, match=r"unknown algorithm 'recde'.*Did you mean 'recode'"):
            subjects.adam.from_spec(spec, dataset="ADSL")

    def test_strict_false_warns_and_skips(self, subjects, write_spec):
        spec = write_spec(
            _define(
                [
                    {"name": "X", "derivation": {"algorithm": "frobnicate"}},
                    {"name": "STUDYID", "derivation": {"algorithm": "assign", "value": "S01"}},
                ]
            )
        )
        with pytest.warns(UserWarning, match="not supported in spec-driven mode"):
            result = subjects.adam.from_spec(spec, dataset="ADSL", strict=False).to_frame()
        assert "X" not in result.columns
        assert result["STUDYID"].to_list() == ["S01", "S01"]


# ──────────────────────────────────────────────────────────────────────
# C7 — overwrite guard + only=/omit= on both standards
# ──────────────────────────────────────────────────────────────────────


class TestOverwriteGuard:
    def _trtsdt_spec(self, write_spec) -> Path:
        return write_spec(
            _define(
                [
                    {
                        "name": "TRTSDT",
                        "derivation": {"algorithm": "derivation", "expression": "AGE"},
                    }
                ]
            )
        )

    def test_overwrite_raises(self, write_spec):
        df = pl.from_repr("""\
┌─────────┬─────┬────────┐
│ USUBJID ┆ AGE ┆ TRTSDT │
│ ---     ┆ --- ┆ ---    │
│ str     ┆ i64 ┆ str    │
╞═════════╪═════╪════════╡
│ S1      ┆ 70  ┆ inline │
└─────────┴─────┴────────┘
""")
        spec = self._trtsdt_spec(write_spec)
        with pytest.raises(SpecError, match=r"variable TRTSDT.*overwrite.*omit"):
            df.adam.from_spec(spec, dataset="ADSL")

    def test_overwrite_true_allows(self, write_spec):
        df = pl.from_repr("""\
┌─────────┬─────┬────────┐
│ USUBJID ┆ AGE ┆ TRTSDT │
│ ---     ┆ --- ┆ ---    │
│ str     ┆ i64 ┆ str    │
╞═════════╪═════╪════════╡
│ S1      ┆ 70  ┆ inline │
└─────────┴─────┴────────┘
""")
        spec = self._trtsdt_spec(write_spec)
        result = df.adam.from_spec(spec, dataset="ADSL", overwrite=True).to_frame()
        assert result["TRTSDT"].to_list() == [70]

    def test_omit_keeps_inline_derivation(self, write_spec):
        df = pl.from_repr("""\
┌─────────┬─────┬────────┐
│ USUBJID ┆ AGE ┆ TRTSDT │
│ ---     ┆ --- ┆ ---    │
│ str     ┆ i64 ┆ str    │
╞═════════╪═════╪════════╡
│ S1      ┆ 70  ┆ inline │
└─────────┴─────┴────────┘
""")
        spec = self._trtsdt_spec(write_spec)
        result = df.adam.from_spec(spec, dataset="ADSL", omit=["TRTSDT"]).to_frame()
        assert result["TRTSDT"].to_list() == ["inline"]

    def test_identity_carry_through_allowed(self, subjects, write_spec):
        """source: USUBJID on variable USUBJID is a declared carry-through."""
        spec = write_spec(
            _define(
                [{"name": "USUBJID", "derivation": {"algorithm": "assign", "source": "USUBJID"}}]
            )
        )
        result = subjects.adam.from_spec(spec, dataset="ADSL").to_frame()
        assert result["USUBJID"].to_list() == ["S1", "S2"]

    def test_sdtm_gets_only_and_omit(self, write_spec):
        """SDTM from_spec now has the same only=/omit= affordances as ADaM."""
        raw = pl.from_repr("""\
┌────────────┐
│ subject_id │
│ ---        │
│ str        │
╞════════════╡
│ A          │
└────────────┘
""")
        spec = write_spec(
            _define(
                [
                    {
                        "name": "USUBJID",
                        "derivation": {"algorithm": "assign", "source": "subject_id"},
                    },
                    {
                        "name": "DOMAIN",
                        "derivation": {"algorithm": "assign", "value": "DM"},
                    },
                ],
                dataset="DM",
            )
        )
        only = raw.sdtm.from_spec(spec, dataset="DM", only=["USUBJID"]).to_frame()
        assert "DOMAIN" not in only.columns
        omitted = raw.sdtm.from_spec(spec, dataset="DM", omit=["DOMAIN"]).to_frame()
        assert "DOMAIN" not in omitted.columns
        with pytest.raises(ValueError, match="Cannot specify both"):
            raw.sdtm.from_spec(spec, dataset="DM", only=["USUBJID"], omit=["DOMAIN"])


# ──────────────────────────────────────────────────────────────────────
# §4.2 — per-variable error context
# ──────────────────────────────────────────────────────────────────────


class TestErrorContext:
    def test_execution_error_names_file_dataset_variable(self, subjects, write_spec):
        """A failure inside the verb surfaces as SpecError with full context."""
        spec = write_spec(
            _define(
                [
                    {
                        "name": "AVAL",
                        "derivation": {
                            "algorithm": "derivation",
                            "expression": "pl.col('AGE') +* 2",  # syntax error
                        },
                    }
                ]
            )
        )
        with pytest.raises(SpecError) as excinfo:
            subjects.adam.from_spec(spec, dataset="ADSL")
        message = str(excinfo.value)
        assert "define.yaml" in message
        assert "dataset ADSL" in message
        assert "variable AVAL" in message

    def test_missing_pin_names_variable(self, subjects, write_spec):
        spec = write_spec(
            _define(
                [
                    {
                        "name": "TRTSDT",
                        "derivation": {
                            "algorithm": "first_date",
                            "from_dataset": "EX",
                            "date_col": "EXSTDTC",
                        },
                    }
                ]
            )
        )
        with pytest.raises(SpecError, match=r"variable TRTSDT.*pinned 'EX'"):
            subjects.adam.from_spec(spec, dataset="ADSL")


# ──────────────────────────────────────────────────────────────────────
# Spec versioning
# ──────────────────────────────────────────────────────────────────────


class TestSpecVersion:
    def test_version_2_accepted(self, subjects, write_spec):
        spec = write_spec(
            _define(
                [{"name": "STUDYID", "derivation": {"algorithm": "assign", "value": "S01"}}],
                fleet_spec_version=2,
            )
        )
        result = subjects.adam.from_spec(spec, dataset="ADSL").to_frame()
        assert result["STUDYID"].to_list() == ["S01", "S01"]

    def test_version_1_names_the_migration(self, subjects, write_spec):
        """The pre-ADR-0008 dialect is a hard cut: the error says how to rewrite the file."""
        spec = write_spec(
            _define(
                [{"name": "STUDYID", "derivation": {"algorithm": "assigned", "value": "S01"}}],
                fleet_spec_version=1,
            )
        )
        with pytest.raises(SpecError, match=r"fleet_spec_version 1.*fleet migrate --spec"):
            subjects.adam.from_spec(spec, dataset="ADSL")

    def test_old_algorithm_name_names_the_migration(self, subjects, write_spec):
        spec = write_spec(
            _define([{"name": "STUDYID", "derivation": {"algorithm": "assigned", "value": "S01"}}])
        )
        with pytest.raises(SpecError, match=r"'assigned' is the pre-ADR-0008 spelling of 'assign'"):
            subjects.adam.from_spec(spec, dataset="ADSL")

    def test_future_version_rejected(self, subjects, write_spec):
        spec = write_spec(_define([], fleet_spec_version=3))
        with pytest.raises(SpecError, match="unsupported fleet_spec_version 3"):
            subjects.adam.from_spec(spec, dataset="ADSL")

    def test_define_spec_generator_rejects_future_version(self, tmp_path):
        from fleet.define_xml.spec_generator import DefineSpecGenerator

        p = tmp_path / "define.yaml"
        p.write_text(yaml.dump({"fleet_spec_version": 99, "study": {}, "datasets": []}))
        with pytest.raises(SpecError, match="unsupported fleet_spec_version 99"):
            DefineSpecGenerator(p)


# ──────────────────────────────────────────────────────────────────────
# derivations_module escape hatch
# ──────────────────────────────────────────────────────────────────────


class TestDerivationsModule:
    def test_module_imported_before_execution(self, subjects, write_spec, tmp_path, monkeypatch):
        """from_spec imports the declared module itself — no import-order footgun."""
        module_dir = tmp_path / "studypkg"
        module_dir.mkdir()
        (module_dir / "__init__.py").write_text("")
        (module_dir / "derivs.py").write_text(
            "import polars as pl\n"
            "from fleet.core.derivation import derivation\n\n"
            "@derivation\n"
            "def SPECMODCOL() -> pl.Expr:\n"
            "    return pl.lit('Y').alias('SPECMODCOL')\n"
        )
        monkeypatch.syspath_prepend(str(tmp_path))

        spec = write_spec(
            _define(
                [{"name": "SPECMODCOL", "derivation": {"callable": "SPECMODCOL"}}],
                derivations_module="studypkg.derivs",
            )
        )
        result = subjects.adam.from_spec(spec, dataset="ADSL").to_frame()
        assert result["SPECMODCOL"].to_list() == ["Y", "Y"]

    def test_unimportable_module_raises(self, subjects, write_spec):
        spec = write_spec(_define([], derivations_module="no.such.module"))
        with pytest.raises(SpecError, match="cannot import derivations_module 'no.such.module'"):
            subjects.adam.from_spec(spec, dataset="ADSL")


# ──────────────────────────────────────────────────────────────────────
# select(spec=...) warnings
# ──────────────────────────────────────────────────────────────────────


class TestSelectSpecWarnings:
    @pytest.fixture
    def select_spec(self, write_spec) -> Path:
        return write_spec(
            {
                "datasets": [
                    {
                        "name": "ADSL",
                        "variables": [{"name": "USUBJID"}, {"name": "GHOSTCOL"}],
                    }
                ]
            }
        )

    def test_warns_on_dropped_computed_column(self, subjects, select_spec):
        ns = subjects.adam.assign("AGEGR1", value="<65")
        with pytest.warns(UserWarning, match=r"dropping computed column.*AGEGR1"):
            ns.select(spec=select_spec, dataset="ADSL")

    def test_warns_on_spec_declared_column_absent(self, subjects, select_spec):
        with pytest.warns(UserWarning, match=r"absent from the frame.*GHOSTCOL"):
            subjects.adam.select(spec=select_spec, dataset="ADSL")

    def test_no_warning_when_aligned(self, subjects, write_spec):
        spec = write_spec(
            {"datasets": [{"name": "ADSL", "variables": [{"name": "USUBJID"}, {"name": "AGE"}]}]}
        )
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            out = subjects.adam.select(spec=spec, dataset="ADSL").to_frame()
        assert out.columns == ["USUBJID", "AGE"]


# ──────────────────────────────────────────────────────────────────────
# Transform registry: duplicate registration warns
# ──────────────────────────────────────────────────────────────────────


class TestDuplicateTransformWarning:
    def test_duplicate_registration_warns(self):
        def first(df: pl.DataFrame) -> pl.DataFrame:
            return df

        def second(df: pl.DataFrame) -> pl.DataFrame:
            return df

        register_transform("agegr1_dup", first)
        with pytest.warns(UserWarning, match="already registered"):
            register_transform("agegr1_dup", second)

    def test_reregistering_same_function_is_silent(self):
        def fn(df: pl.DataFrame) -> pl.DataFrame:
            return df

        register_transform("agegr1_same", fn)
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            register_transform("agegr1_same", fn)


# ──────────────────────────────────────────────────────────────────────
# depends_on is removed: the key is refused (c1-54)
# ──────────────────────────────────────────────────────────────────────


class TestDependsOn:
    def test_depends_on_key_is_refused(self, write_spec):
        df = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ vsdtc      │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ S1      ┆ 2024-01-10 │
└─────────┴────────────┘
""")
        spec = write_spec(
            _define(
                [
                    {"name": "ADTC", "derivation": {"algorithm": "assign", "source": "vsdtc"}},
                    {
                        "name": "ADY",
                        "derivation": {
                            "algorithm": "duration",
                            "start": "ADTC",
                            "end": "ADTC",
                            "depends_on": ["ADTC"],
                        },
                    },
                ],
                dataset="ADVS",
            )
        )
        with pytest.raises(SpecError, match="depends_on"):
            df.adam.from_spec(spec, dataset="ADVS")


# ──────────────────────────────────────────────────────────────────────
# ADR-0008: ct defaults to the variable's codelist
# ──────────────────────────────────────────────────────────────────────


class TestCodelistDefault:
    def test_assign_without_ct_checks_the_variable_codelist(self, subjects, write_spec):
        """DM.SEX with ``codelist: C66731`` and no ``ct:`` still maps and checks the values."""
        spec = write_spec(
            _define(
                [
                    {
                        "name": "SEX",
                        "codelist": "C66731",
                        "derivation": {
                            "algorithm": "assign",
                            "source": "sex_raw",
                            "ct_map": {"male": "M", "female": "F"},
                        },
                    }
                ]
            )
        )
        frame = subjects.with_columns(pl.Series("sex_raw", ["male", "female"]))
        ns = frame.adam.from_spec(spec, dataset="ADSL")
        assert ns.to_frame()["SEX"].to_list() == ["M", "F"]
        (node,) = [n for n in ns._lineage if n.name == "SEX"]
        assert node.spec["ct"] == "C66731"

    def test_ct_map_without_any_codelist_is_a_load_error(self, subjects, write_spec):
        spec = write_spec(
            _define(
                [
                    {
                        "name": "SEX",
                        "derivation": {
                            "algorithm": "assign",
                            "source": "sex_raw",
                            "ct_map": {"male": "M"},
                        },
                    }
                ]
            )
        )
        with pytest.raises(SpecError, match="ct_map needs a codelist"):
            subjects.adam.from_spec(spec, dataset="ADSL")
