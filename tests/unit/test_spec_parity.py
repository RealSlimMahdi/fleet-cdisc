"""Spec-path parity: registry ↔ enums ↔ JSON schema ↔ runtime behaviour.

Three layers of guarantees, all driven by ``fleet.core.spec_registry``
(the single source of truth for spec-executable algorithms):

1. **Sync tests** — the ``SDTMAlgorithm`` / ``ADAMAlgorithm`` enums and the
   published JSON schema must exactly match the registry, so none of the
   six former copies of verb knowledge can drift again.
2. **Reverse parity** — every public namespace verb is either the target
   of a registered algorithm or explicitly listed in
   ``SPEC_UNSUPPORTED`` (the machine-checked coverage matrix).
3. **Functional round-trips** — every registered algorithm executes from a
   minimal YAML spec and produces the expected column/values (replaces
   the old substring scan of the dispatch source).
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import polars as pl
import pytest
import yaml

import fleet  # noqa: F401 — triggers namespace registration
from fleet.adam.models import ADAMAlgorithm
from fleet.adam.namespace import AdamNamespace
from fleet.adam.transforms import clear_transforms
from fleet.core import spec_registry
from fleet.core.derivation import derivation
from fleet.sdtm.models import SDTMAlgorithm
from fleet.sdtm.namespace import SDTMNamespace

# ──────────────────────────────────────────────────────────────────────
# 1. Sync: enums and JSON schema must match the registry
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("algorithm_enum", "standard"),
    [(SDTMAlgorithm, "sdtm"), (ADAMAlgorithm, "adam")],
)
def test_enum_matches_registry(algorithm_enum: type, standard: str) -> None:
    """Enum values == registry names: the verb names (ADR-0008)."""
    enum_values = {a.value for a in algorithm_enum}
    registry_values = set(spec_registry.algorithm_names(standard))
    assert enum_values == registry_values, (
        f"{algorithm_enum.__name__} out of sync with spec_registry: "
        f"enum-only={sorted(enum_values - registry_values)}, "
        f"registry-only={sorted(registry_values - enum_values)}"
    )


def test_json_schema_in_sync() -> None:
    """The shipped JSON schema equals a fresh build from the registry.

    Regenerate with: ``uv run python -m fleet.define_xml.schema_builder``.
    """
    from fleet.define_xml.schema_builder import SCHEMA_PATH, build_schema

    shipped = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert shipped == build_schema(), (
        "define_spec_schema.json is stale — regenerate it with "
        "`uv run python -m fleet.define_xml.schema_builder`."
    )


def test_schema_enum_covers_registry() -> None:
    """Every registered algorithm validates against the derivation schema."""
    import jsonschema

    from fleet.define_xml.schema_builder import SCHEMA_PATH

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(
        {"$ref": "#/$defs/derivation", "$defs": schema["$defs"]}
    )
    # An unknown algorithm must be rejected.
    assert list(validator.iter_errors({"algorithm": "frobnicate"}))
    # A known algorithm with a misspelled key must be rejected (C6).
    assert list(validator.iter_errors({"algorithm": "recode", "recod_map": {}}))


# ──────────────────────────────────────────────────────────────────────
# 2. Reverse parity: public verbs ↔ registry ↔ SPEC_UNSUPPORTED
# ──────────────────────────────────────────────────────────────────────

#: Chaining / IO / debugging / configuration methods — not derivation
#: verbs, so they are outside the spec-coverage question entirely.
_INFRASTRUCTURE: set[str] = {
    "to_frame",
    "to_dataset_json",
    "write_parquet",
    "inspect",
    "explain",
    "trail",
    "validate",
    "compare",  # QC step: reports against a base, derives nothing
    "select",
    "nodup",
    "from_spec",
    "to_spec_yaml",
    "pin",
    "repin",
    "pins",
    "fk_policy",
}


def _public_verbs(namespace_cls: type) -> set[str]:
    """Public callables on the namespace class (properties excluded)."""
    return {
        name
        for name in dir(namespace_cls)
        if not name.startswith("_") and callable(getattr(namespace_cls, name, None))
    }


@pytest.mark.parametrize(
    ("namespace_cls", "standard"),
    [(SDTMNamespace, "sdtm"), (AdamNamespace, "adam")],
)
def test_every_public_verb_is_registered_or_allowlisted(namespace_cls: type, standard: str) -> None:
    """The coverage matrix is complete: verb → algorithm or explicit opt-out."""
    public = _public_verbs(namespace_cls)
    registry_verbs = {a.verb for a in spec_registry.algorithms(standard)}
    allowlisted = spec_registry.SPEC_UNSUPPORTED[standard]

    unaccounted = public - registry_verbs - allowlisted - _INFRASTRUCTURE
    assert not unaccounted, (
        f"{namespace_cls.__name__} verbs with no spec story: {sorted(unaccounted)}. "
        "Register them in fleet.core.spec_registry or add them to SPEC_UNSUPPORTED."
    )

    # Every registry verb must actually exist on the namespace (a dotted
    # verb on its sub-namespace, ADR-0008).
    missing = {v for v in registry_verbs if spec_registry._namespace_method(standard, v) is None}
    assert not missing, f"Registry references verbs missing on {namespace_cls.__name__}: {missing}"

    # The allowlist must stay honest: no overlap, no stale entries.
    assert not (allowlisted & registry_verbs), "SPEC_UNSUPPORTED overlaps registered verbs"
    stale = {v for v in allowlisted if not hasattr(namespace_cls, v)}
    assert not stale, f"SPEC_UNSUPPORTED lists verbs that no longer exist: {stale}"


def test_coverage_matrix_shape() -> None:
    """The published matrix has one well-formed row per canonical algorithm."""
    matrix = spec_registry.coverage_matrix()
    keys = {"standard", "algorithm", "verb", "params", "required"}
    assert all(keys <= set(row) for row in matrix)
    per_standard = {
        s: {r["algorithm"] for r in matrix if r["standard"] == s} for s in ("sdtm", "adam")
    }
    assert per_standard["sdtm"] == set(spec_registry.algorithm_names("sdtm"))
    assert per_standard["adam"] == set(spec_registry.algorithm_names("adam"))


# ──────────────────────────────────────────────────────────────────────
# 2b. The verb is the algorithm: YAML keys == verb keywords (ADR-0008)
# ──────────────────────────────────────────────────────────────────────

_NAMESPACES: dict[str, type] = {"sdtm": SDTMNamespace, "adam": AdamNamespace}

#: Keyword arguments no spec exposes: validators and runtime switches.
_NEVER_IN_YAML = {"ct_validator", "validate_values", "check_uniqueness"}


def _all_algorithms() -> list[spec_registry.SpecAlgorithm]:
    return [algo for standard in ("sdtm", "adam") for algo in spec_registry.algorithms(standard)]


def _signature_facts(algo: spec_registry.SpecAlgorithm) -> dict[str, inspect.Parameter]:
    verb = spec_registry._namespace_method(algo.standard, algo.verb)
    params = [p for name, p in inspect.signature(verb).parameters.items() if name != "self"]
    if algo.takes_target:
        params = params[1:]  # the first argument is the variable name
    return {p.name: p for p in params if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)}


@pytest.mark.parametrize("algo", _all_algorithms(), ids=lambda a: f"{a.standard}.{a.name}")
def test_yaml_keys_are_the_verb_keywords(algo: spec_registry.SpecAlgorithm) -> None:
    """ADR-0008: the ``algorithm:`` value is the verb, the keys are its keywords.

    1. The algorithm name is the verb name.
    2. Every keyword of the verb is a YAML key, except the ones the
       declaration excludes and the validators no spec exposes.
    3. A YAML key is the keyword without a trailing underscore (``else``).
    4. ``required`` and ``default`` come from the signature. A declared
       ``required`` may make the spec stricter, a ``target_default`` makes
       the key optional, nothing else may differ.
    """
    assert algo.name == algo.verb
    sig = _signature_facts(algo)
    excluded = set(algo.exclude) | _NEVER_IN_YAML
    expected = {name for name in sig if name not in excluded}
    declared = {f.kwarg for f in algo.params if not f.extra}
    assert declared == expected, (
        f"{algo.standard}.{algo.name}: YAML keys {sorted(declared)} != "
        f"verb keywords {sorted(expected)}"
    )
    for f in algo.params:
        if f.extra:
            continue
        sp = sig[f.kwarg]
        assert f.name == (f.kwarg[:-1] if f.kwarg.endswith("_") else f.kwarg)
        if f.kwarg in algo.target_default:
            assert not f.required, f"{f.kwarg} defaults to the target, so it is optional"
            continue
        if f.kwarg in algo.required:
            assert f.required, f"{f.kwarg} is declared required"
            continue
        sig_required = sp.default is inspect.Parameter.empty
        assert f.required == sig_required, f"{f.kwarg}: required differs from the signature"
        if not sig_required:
            assert f.default == sp.default, f"{f.kwarg}: default differs from the signature"


def test_assign_model_has_the_verb_keywords() -> None:
    """The DM.SEX block of ADR-0008 validates: ``ct`` and ``ct_map`` are the keys."""
    var = spec_registry.parse_variable_spec(
        "sdtm",
        {
            "target": "SEX",
            "algorithm": "assign",
            "source": "sex",
            "ct": "C66731",
            "ct_map": {"F": "F", "M": "M"},
        },
    )
    assert var.source == "sex"
    assert var.ct == "C66731"
    assert var.ct_map == {"F": "F", "M": "M"}
    keys = set(spec_registry.model_for("sdtm", "assign").model_fields)
    assert {"algorithm", "target", "source", "value", "ct", "ct_map"} <= keys
    assert not {"ct_validator", "validate_values", "ct_codelist", "ct_mapping"} & keys


def test_else_is_written_without_the_underscore() -> None:
    """``else_`` of case_when is ``else:`` in YAML, and comes back as ``else`` in a block."""
    var = spec_registry.parse_variable_spec(
        "sdtm",
        {
            "target": "ARMCD",
            "algorithm": "case_when",
            "when": [{"condition": 'pl.col("ARM") == "Placebo"', "value": "Pbo"}],
            "else": "X",
        },
    )
    assert var.else_ == "X"
    assert spec_registry._spec_block(var)["else"] == "X"
    with pytest.raises(Exception, match="else_"):
        spec_registry.parse_variable_spec(
            "sdtm", {"target": "ARMCD", "algorithm": "case_when", "when": [], "else_": "X"}
        )


def test_assign_source_and_value_exclude_each_other() -> None:
    """One assign cannot both copy a column and set a constant."""
    with pytest.raises(Exception, match="source, value"):
        spec_registry.parse_variable_spec(
            "sdtm", {"target": "DOMAIN", "algorithm": "assign", "source": "dom", "value": "DM"}
        )


def test_derivation_needs_an_expression_or_a_callable() -> None:
    """``derivation`` with neither key is a load-time error, not a null column."""
    with pytest.raises(Exception, match="expression, callable"):
        spec_registry.parse_variable_spec("adam", {"target": "AVAL", "algorithm": "derivation"})


def test_old_spec_names_are_not_algorithms() -> None:
    """The hard cut of ADR-0008: the old spec vocabulary is gone from the registry."""
    for standard, old in (
        ("sdtm", "assign_ct"),
        ("sdtm", "hardcode_no_ct"),
        ("sdtm", "if_then_else"),
        ("adam", "source"),
        ("adam", "lookup"),
        ("adam", "study_day"),
    ):
        assert spec_registry.get_algorithm(standard, old) is None


# ──────────────────────────────────────────────────────────────────────
# 3. Functional round-trips: minimal spec → execute → expected output
# ──────────────────────────────────────────────────────────────────────


@dataclass
class Case:
    """One minimal spec → execution → assertion round-trip."""

    algorithm: str
    frame: Callable[[], pl.DataFrame]
    variables: list[dict]
    check: Callable[[pl.DataFrame], object]
    pins: dict[str, Callable[[], pl.DataFrame]] = field(default_factory=dict)
    setup: Callable[[], None] | None = None


def _subjects() -> pl.DataFrame:
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


def _register_sdtm_callable() -> None:
    @derivation
    def SPEC_RT_SDTM() -> pl.Expr:
        return pl.col("AGE").cast(pl.String).alias("SPEC_RT_SDTM")


def _register_adam_callable() -> None:
    @derivation
    def SPEC_RT_ADAM() -> pl.Expr:
        return pl.col("AGE").cast(pl.String).alias("SPEC_RT_ADAM")


SDTM_CASES: list[Case] = [
    Case(
        "assign",
        lambda: pl.from_repr("""\
┌────────────┐
│ subject_id │
│ ---        │
│ str        │
╞════════════╡
│ A          │
│ B          │
└────────────┘
"""),
        [{"target": "USUBJID", "algorithm": "assign", "source": "subject_id"}],
        lambda df: df["USUBJID"].to_list() == ["A", "B"],
    ),
    Case(
        "assign",
        lambda: pl.from_repr("""\
┌─────────┐
│ sex_raw │
│ ---     │
│ str     │
╞═════════╡
│ male    │
│ female  │
└─────────┘
"""),
        [
            {
                "target": "SEX",
                "algorithm": "assign",
                "source": "sex_raw",
                "ct": "C66731",
                "ct_map": {"male": "M", "female": "F"},
            }
        ],
        lambda df: df["SEX"].to_list() == ["M", "F"],
    ),
    Case(
        "date",
        lambda: pl.from_repr("""\
┌────────────┐
│ birth_date │
│ ---        │
│ str        │
╞════════════╡
│ 2024-01-02 │
└────────────┘
"""),
        [{"target": "BRTHDTC", "algorithm": "date", "source": "birth_date"}],
        lambda df: df["BRTHDTC"].to_list() == ["2024-01-02"],
    ),
    Case(
        "assign",
        lambda: _subjects(),
        [{"target": "SEX", "algorithm": "assign", "value": "M", "ct": "C66731"}],
        lambda df: df["SEX"].to_list() == ["M", "M"],
    ),
    Case(
        "assign",
        lambda: _subjects(),
        [{"target": "DOMAIN", "algorithm": "assign", "value": "DM"}],
        lambda df: df["DOMAIN"].to_list() == ["DM", "DM"],
    ),
    Case(
        "condition_add",
        lambda: _subjects(),
        [
            {
                "target": "AGEGRP",
                "algorithm": "condition_add",
                "condition": 'pl.col("AGE") > 64',
                "then_value": "ELDERLY",
            }
        ],
        lambda df: df["AGEGRP"].to_list() == ["ELDERLY", None],
    ),
    Case(
        "case_when",
        lambda: _subjects(),
        [
            {
                "target": "AGEGR1",
                "algorithm": "case_when",
                "when": [{"condition": 'pl.col("AGE") > 64', "value": ">=65"}],
                "else": "<65",
            }
        ],
        lambda df: df["AGEGR1"].to_list() == [">=65", "<65"],
    ),
    Case(
        "ae_aerel",
        lambda: pl.from_repr("""\
┌─────────────────┐
│ ae_relationship │
│ ---             │
│ str             │
╞═════════════════╡
│ related         │
└─────────────────┘
"""),
        [
            {
                "target": "AEREL",
                "algorithm": "ae_aerel",
                "aerel_map": {"related": "RELATED"},
            }
        ],
        lambda df: df["AEREL"].to_list() == ["RELATED"],
    ),
    Case(
        "merge",
        lambda: _subjects(),
        [{"target": "EXTRA", "algorithm": "merge", "dataset": "SUPP", "on": "USUBJID"}],
        lambda df: df["EXTRA"].to_list() == ["x", "y"],
        pins={
            "SUPP": lambda: pl.from_repr("""\
┌─────────┬───────┐
│ USUBJID ┆ EXTRA │
│ ---     ┆ ---   │
│ str     ┆ str   │
╞═════════╪═══════╡
│ S1      ┆ x     │
│ S2      ┆ y     │
└─────────┴───────┘
""")
        },
    ),
    Case(
        "group_by",
        lambda: pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ val │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ S1      ┆ 1   │
│ S1      ┆ 5   │
│ S2      ┆ 3   │
└─────────┴─────┘
"""),
        [
            {
                "target": "VAL",
                "algorithm": "group_by",
                "by": ["USUBJID"],
                "agg": ["pl.col('val').max()"],
            }
        ],
        lambda df: df.height == 2,
    ),
    Case(
        "notsubmitted",
        lambda: pl.from_repr("""\
┌─────────┐
│ scratch │
│ ---     │
│ str     │
╞═════════╡
│ a       │
│ b       │
└─────────┘
"""),
        [{"target": "scratch", "algorithm": "notsubmitted"}],
        lambda df: df["scratch"].to_list() == [None, None],
    ),
    Case(
        "multiple_responses",
        lambda: pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ ae_terms   │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ S1      ┆ fever|rash │
└─────────┴────────────┘
"""),
        [
            {
                "target": "AETERM",
                "algorithm": "multiple_responses",
                "source": "ae_terms",
                "delimiter": "|",
            }
        ],
        lambda df: sorted(df["AETERM"].to_list()) == ["fever", "rash"],
    ),
    Case(
        "seq",
        lambda: pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ S1      │
│ S1      │
│ S2      │
└─────────┘
"""),
        [
            {
                "target": "AESEQ",
                "algorithm": "seq",
                "by": ["USUBJID"],
                "order_by": ["USUBJID"],
            }
        ],
        lambda df: df["AESEQ"].to_list() == [1, 2, 1],
    ),
    Case(
        "nsv",
        lambda: pl.from_repr("""\
┌─────────┬─────────────┐
│ USUBJID ┆ safety_flag │
│ ---     ┆ ---         │
│ str     ┆ str         │
╞═════════╪═════════════╡
│ S1      ┆ Y           │
└─────────┴─────────────┘
"""),
        [
            {
                "target": "SAFETY",
                "algorithm": "nsv",
                "source": "safety_flag",
                "label": "Safety Population Flag",
            }
        ],
        lambda df: df["SAFETY"].to_list() == ["Y"],
    ),
    Case(
        "duration",
        lambda: pl.from_repr("""\
┌────────────┬────────────┐
│ AESTDTC    ┆ AEENDTC    │
│ ---        ┆ ---        │
│ str        ┆ str        │
╞════════════╪════════════╡
│ 2024-01-01 ┆ 2024-01-05 │
└────────────┴────────────┘
"""),
        [
            {
                "target": "AEDUR",
                "algorithm": "duration",
                "start": "AESTDTC",
                "end": "AEENDTC",
            }
        ],
        lambda df: df["AEDUR"].to_list() == [5],
    ),
    Case(
        "derivation",
        lambda: _subjects(),
        [{"target": "SPEC_RT_SDTM", "algorithm": "derivation", "callable": "SPEC_RT_SDTM"}],
        lambda df: df["SPEC_RT_SDTM"].to_list() == ["70", "50"],
        setup=_register_sdtm_callable,
    ),
]


def _vs_frame() -> pl.DataFrame:
    return pl.from_repr("""\
┌─────────┬─────────┬──────────┬──────┐
│ USUBJID ┆ PARAMCD ┆ VISITNUM ┆ AVAL │
│ ---     ┆ ---     ┆ ---      ┆ ---  │
│ str     ┆ str     ┆ i64      ┆ f64  │
╞═════════╪═════════╪══════════╪══════╡
│ S1      ┆ SYSBP   ┆ 1        ┆ 120  │
│ S1      ┆ SYSBP   ┆ 2        ┆ 130  │
│ S2      ┆ SYSBP   ┆ 1        ┆ 110  │
└─────────┴─────────┴──────────┴──────┘
""")


ADAM_CASES: list[Case] = [
    Case(
        "assign",
        lambda: pl.from_repr("""\
┌────────────┐
│ subject_id │
│ ---        │
│ str        │
╞════════════╡
│ A          │
└────────────┘
"""),
        [{"target": "USUBJID", "algorithm": "assign", "source": "subject_id"}],
        lambda df: df["USUBJID"].to_list() == ["A"],
    ),
    Case(
        "derivation",
        lambda: pl.from_repr("""\
┌──────────┐
│ vs_value │
│ ---      │
│ f64      │
╞══════════╡
│ 2.0      │
└──────────┘
"""),
        [{"target": "AVAL", "algorithm": "derivation", "expression": "pl.col('vs_value') * 2"}],
        lambda df: df["AVAL"].to_list() == [4.0],
    ),
    Case(
        "assign",
        lambda: _subjects(),
        [{"target": "STUDYID", "algorithm": "assign", "value": "S01"}],
        lambda df: df["STUDYID"].to_list() == ["S01", "S01"],
    ),
    Case(
        "recode",
        lambda: pl.from_repr("""\
┌─────┐
│ sex │
│ --- │
│ str │
╞═════╡
│ M   │
│ F   │
└─────┘
"""),
        [
            {
                "target": "SEXN",
                "algorithm": "recode",
                "source": "sex",
                "recode_map": {"M": "Male", "F": "Female"},
            }
        ],
        lambda df: df["SEXN"].to_list() == ["Male", "Female"],
    ),
    Case(
        "assign",
        lambda: pl.from_repr("""\
┌────────────┐
│ vsdtc      │
│ ---        │
│ str        │
╞════════════╡
│ 2024-01-01 │
└────────────┘
"""),
        [{"target": "ADTC", "algorithm": "assign", "source": "vsdtc"}],
        lambda df: df["ADTC"].to_list() == ["2024-01-01"],
    ),
    Case(
        "case_when",
        lambda: _subjects(),
        [
            {
                "target": "AGEGR1",
                "algorithm": "case_when",
                "when": [{"condition": 'pl.col("AGE") < 65', "value": "<65"}],
                "else": ">=65",
            }
        ],
        lambda df: df["AGEGR1"].to_list() == [">=65", "<65"],
    ),
    Case(
        "merge",
        lambda: _subjects(),
        [
            {
                "target": "TRTSDT",
                "algorithm": "merge",
                "dataset": "ADSL",
                "on": "USUBJID",
            }
        ],
        lambda df: "TRTSDT" in df.columns,
        pins={
            "ADSL": lambda: pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ TRTSDT     │
│ ---     ┆ ---        │
│ str     ┆ date       │
╞═════════╪════════════╡
│ S1      ┆ 2024-01-01 │
│ S2      ┆ 2024-01-02 │
└─────────┴────────────┘
""")
        },
    ),
    Case(
        "whereclauses",
        lambda: _subjects(),
        [{"target": "AGE", "algorithm": "whereclauses", "where": 'pl.col("AGE") > 60'}],
        lambda df: df.height == 1,
    ),
    Case(
        "duration",
        lambda: pl.from_repr("""\
┌────────────┬────────────┐
│ ADT        ┆ TRTSDT     │
│ ---        ┆ ---        │
│ date       ┆ date       │
╞════════════╪════════════╡
│ 2024-01-10 ┆ 2024-01-01 │
└────────────┴────────────┘
"""),
        [
            {
                "target": "ADY",
                "algorithm": "duration",
                "end": "ADT",
                "start": "TRTSDT",
            }
        ],
        lambda df: df["ADY"].to_list() == [10],
    ),
    Case(
        "baseline",
        lambda: _vs_frame().with_columns(
            pl.when(pl.col("VISITNUM") == 1).then(pl.lit("Y")).alias("ABLFL")
        ),
        [
            {
                "target": "BASE",
                "algorithm": "baseline",
                "by": ["USUBJID", "PARAMCD"],
            }
        ],
        lambda df: df.sort("USUBJID", "VISITNUM")["BASE"].to_list() == [120.0, 120.0, 110.0],
    ),
    Case(
        "chg",
        lambda: pl.from_repr("""\
┌──────┬──────┐
│ AVAL ┆ BASE │
│ ---  ┆ ---  │
│ f64  ┆ f64  │
╞══════╪══════╡
│ 130  ┆ 120  │
└──────┴──────┘
"""),
        [{"target": "CHG", "algorithm": "chg"}],
        lambda df: df["CHG"].to_list() == [10.0],
    ),
    Case(
        "pchg",
        lambda: pl.from_repr("""\
┌──────┬──────┐
│ AVAL ┆ BASE │
│ ---  ┆ ---  │
│ f64  ┆ f64  │
╞══════╪══════╡
│ 130  ┆ 100  │
└──────┴──────┘
"""),
        [{"target": "PCHG", "algorithm": "pchg"}],
        lambda df: df["PCHG"].to_list() == [30.0],
    ),
    Case(
        "flag",
        lambda: _vs_frame(),
        [
            {
                "target": "ABLFL",
                "algorithm": "flag",
                "criteria": 'pl.col("VISITNUM") == 1',
                "by": ["USUBJID"],
            }
        ],
        lambda df: df.sort("USUBJID", "VISITNUM")["ABLFL"].to_list() == ["Y", None, "Y"],
    ),
    Case(
        "bmi",
        lambda: pl.from_repr("""\
┌────────┬────────┐
│ WEIGHT ┆ HEIGHT │
│ ---    ┆ ---    │
│ f64    ┆ f64    │
╞════════╪════════╡
│ 80     ┆ 200    │
└────────┴────────┘
"""),
        [{"target": "BMI", "algorithm": "bmi", "weight": "WEIGHT", "height": "HEIGHT"}],
        lambda df: df["BMI"].to_list() == [20.0],
    ),
    Case(
        "nrind",
        lambda: pl.from_repr("""\
┌──────┬──────────┬──────────┐
│ AVAL ┆ LBSTNRLO ┆ LBSTNRHI │
│ ---  ┆ ---      ┆ ---      │
│ f64  ┆ f64      ┆ f64      │
╞══════╪══════════╪══════════╡
│ 50   ┆ 60       ┆ 140      │
│ 100  ┆ 60       ┆ 140      │
│ 200  ┆ 60       ┆ 140      │
└──────┴──────────┴──────────┘
"""),
        [
            {
                "target": "LBNRIND",
                "algorithm": "nrind",
                "value": "AVAL",
                "low": "LBSTNRLO",
                "high": "LBSTNRHI",
            }
        ],
        lambda df: df["LBNRIND"].to_list() == ["LOW", "NORMAL", "HIGH"],
    ),
    Case(
        "on_treatment",
        lambda: pl.from_repr("""\
┌────────────┬────────────┬────────────┐
│ ADT        ┆ TRTSDT     ┆ TRTEDT     │
│ ---        ┆ ---        ┆ ---        │
│ date       ┆ date       ┆ date       │
╞════════════╪════════════╪════════════╡
│ 2024-01-05 ┆ 2024-01-01 ┆ 2024-02-01 │
│ 2024-03-01 ┆ 2024-01-01 ┆ 2024-02-01 │
└────────────┴────────────┴────────────┘
"""),
        [
            {
                "target": "ONTRTFL",
                "algorithm": "on_treatment",
                "adt": "ADT",
                "trtsdt": "TRTSDT",
                "trtedt": "TRTEDT",
            }
        ],
        lambda df: df["ONTRTFL"].to_list() == ["Y", None],
    ),
    Case(
        "shift",
        lambda: pl.from_repr("""\
┌────────┬────────┐
│ BNRIND ┆ ANRIND │
│ ---    ┆ ---    │
│ str    ┆ str    │
╞════════╪════════╡
│ NORMAL ┆ HIGH   │
└────────┴────────┘
"""),
        [
            {
                "target": "SHIFT1",
                "algorithm": "shift",
                "baseline_cat": "BNRIND",
                "post_cat": "ANRIND",
            }
        ],
        lambda df: df["SHIFT1"].to_list() == ["NORMAL to HIGH"],
    ),
    Case(
        "seq",
        lambda: pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ S1      │
│ S1      │
└─────────┘
"""),
        [{"target": "ASEQ", "algorithm": "seq", "by": ["USUBJID"]}],
        lambda df: df["ASEQ"].to_list() == [1, 2],
    ),
    Case(
        "bsa",
        lambda: pl.from_repr("""\
┌────────┬────────┐
│ WEIGHT ┆ HEIGHT │
│ ---    ┆ ---    │
│ f64    ┆ f64    │
╞════════╪════════╡
│ 80     ┆ 180    │
└────────┴────────┘
"""),
        [{"target": "BSA", "algorithm": "bsa", "weight": "WEIGHT", "height": "HEIGHT"}],
        lambda df: 1.5 < df["BSA"][0] < 2.5,
    ),
    Case(
        "map",
        lambda: pl.from_repr("""\
┌───────┬───────┐
│ SYSBP ┆ DIABP │
│ ---   ┆ ---   │
│ f64   ┆ f64   │
╞═══════╪═══════╡
│ 120   ┆ 80    │
└───────┴───────┘
"""),
        [{"target": "MAP", "algorithm": "map"}],
        lambda df: 90 < df["MAP"][0] < 96,
    ),
    Case(
        "qtc",
        lambda: pl.from_repr("""\
┌─────┬──────┐
│ QT  ┆ RR   │
│ --- ┆ ---  │
│ f64 ┆ f64  │
╞═════╪══════╡
│ 400 ┆ 1000 │
└─────┴──────┘
"""),
        [{"target": "QTCF", "algorithm": "qtc"}],
        lambda df: df["QTCF"][0] == 400.0,
    ),
    Case(
        "atoxgr",
        lambda: pl.from_repr("""\
┌─────────┬─────────┬──────┬───────┬───────┐
│ USUBJID ┆ PARAMCD ┆ AVAL ┆ ANRLO ┆ AVALU │
│ ---     ┆ ---     ┆ ---  ┆ ---   ┆ ---   │
│ str     ┆ str     ┆ f64  ┆ f64   ┆ str   │
╞═════════╪═════════╪══════╪═══════╪═══════╡
│ S1      ┆ Anemia  ┆ 75   ┆ 140   ┆ g/L   │
│ S2      ┆ Anemia  ┆ 150  ┆ 140   ┆ g/L   │
└─────────┴─────────┴──────┴───────┴───────┘
"""),
        [
            {
                "target": "ATOXGRL",
                "algorithm": "atoxgr",
                "direction": "L",
                "term_var": "PARAMCD",
                "unit_var": "AVALU",
            }
        ],
        lambda df: df.sort("USUBJID")["ATOXGRL"].to_list() == ["3", "0"],
    ),
    Case(
        "combine_grades",
        lambda: pl.from_repr("""\
┌─────────┬─────────┐
│ ATOXGRL ┆ ATOXGRH │
│ ---     ┆ ---     │
│ str     ┆ str     │
╞═════════╪═════════╡
│ 3       ┆ null    │
└─────────┴─────────┘
"""),
        [{"target": "ATOXGR", "algorithm": "combine_grades"}],
        lambda df: df["ATOXGR"].to_list() == ["-3"],
    ),
    Case(
        "date",
        lambda: pl.from_repr("""\
┌────────────┐
│ vsdtc      │
│ ---        │
│ str        │
╞════════════╡
│ 2024-01-02 │
└────────────┘
"""),
        [{"target": "ADT", "algorithm": "date", "source": "vsdtc"}],
        lambda df: df["ADT"].to_list() == [date(2024, 1, 2)],
    ),
    Case(
        "duration",
        lambda: pl.from_repr("""\
┌────────────┬────────────┐
│ TRTSDT     ┆ TRTEDT     │
│ ---        ┆ ---        │
│ date       ┆ date       │
╞════════════╪════════════╡
│ 2024-01-01 ┆ 2024-01-10 │
└────────────┴────────────┘
"""),
        [
            {
                "target": "TRTDURD",
                "algorithm": "duration",
                "start": "TRTSDT",
                "end": "TRTEDT",
            }
        ],
        lambda df: df["TRTDURD"].to_list() == [10],
    ),
    Case(
        "pick",
        lambda: pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ DTHDT      │
│ ---     ┆ ---        │
│ str     ┆ date       │
╞═════════╪════════════╡
│ S1      ┆ 2024-01-01 │
│ S2      ┆ null       │
└─────────┴────────────┘
"""),
        [
            {
                "target": "LSTALVDT",
                "algorithm": "pick",
                "events": [
                    {
                        "when": 'pl.col("DTHDT").is_not_null()',
                        "set": {"LSTALVDT": "DTHDT"},
                    }
                ],
            }
        ],
        lambda df: df.sort("USUBJID")["LSTALVDT"].to_list() == [date(2024, 1, 1), None],
    ),
    Case(
        "first_date",
        lambda: _subjects(),
        [
            {
                "target": "TRTSDT",
                "algorithm": "first_date",
                "from_dataset": "EX",
                "date_col": "EXSTDTC",
            }
        ],
        lambda df: df.sort("USUBJID")["TRTSDT"].to_list() == [date(2024, 1, 1), date(2024, 1, 3)],
        pins={
            "EX": lambda: pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ EXSTDTC    │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ S1      ┆ 2024-01-01 │
│ S1      ┆ 2024-01-05 │
│ S2      ┆ 2024-01-03 │
└─────────┴────────────┘
""")
        },
    ),
    Case(
        "last_date",
        lambda: _subjects(),
        [
            {
                "target": "TRTEDT",
                "algorithm": "last_date",
                "from_dataset": "EX",
                "date_col": "EXSTDTC",
            }
        ],
        lambda df: df.sort("USUBJID")["TRTEDT"].to_list() == [date(2024, 1, 5), date(2024, 1, 3)],
        pins={
            "EX": lambda: pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ EXSTDTC    │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ S1      ┆ 2024-01-01 │
│ S1      ┆ 2024-01-05 │
│ S2      ┆ 2024-01-03 │
└─────────┴────────────┘
""")
        },
    ),
    Case(
        "count_events",
        lambda: _subjects(),
        [
            {
                "target": "NUMAE",
                "algorithm": "count_events",
                "from_dataset": "AE",
                "where": 'pl.col("AESER") == "Y"',
            }
        ],
        lambda df: df.sort("USUBJID")["NUMAE"].to_list() == [1, 0],
        pins={
            "AE": lambda: pl.from_repr("""\
┌─────────┬───────┐
│ USUBJID ┆ AESER │
│ ---     ┆ ---   │
│ str     ┆ str   │
╞═════════╪═══════╡
│ S1      ┆ Y     │
│ S1      ┆ N     │
│ S2      ┆ N     │
└─────────┴───────┘
""")
        },
    ),
    Case(
        "occds.treatment_emergent",
        lambda: pl.from_repr("""\
┌─────────┬────────────┬────────────┬────────────┬────────────┐
│ USUBJID ┆ ASTDT      ┆ AENDT      ┆ TRTSDT     ┆ TRTEDT     │
│ ---     ┆ ---        ┆ ---        ┆ ---        ┆ ---        │
│ str     ┆ date       ┆ date       ┆ date       ┆ date       │
╞═════════╪════════════╪════════════╪════════════╪════════════╡
│ S1      ┆ 2024-01-05 ┆ 2024-01-06 ┆ 2024-01-01 ┆ 2024-01-31 │
│ S2      ┆ 2023-12-01 ┆ 2023-12-02 ┆ 2024-01-01 ┆ 2024-01-31 │
└─────────┴────────────┴────────────┴────────────┴────────────┘
"""),
        [
            {
                "target": "TRTEMFL",
                "algorithm": "occds.treatment_emergent",
                "start_date": "ASTDT",
                "end_date": "AENDT",
                "trtsdt": "TRTSDT",
                "trtedt": "TRTEDT",
                "end_window": 0,
            }
        ],
        lambda df: df.sort("USUBJID")["TRTEMFL"].to_list() == ["Y", None],
    ),
    Case(
        "derivation",
        lambda: _subjects(),
        [{"target": "SPEC_RT_ADAM", "algorithm": "derivation", "callable": "SPEC_RT_ADAM"}],
        lambda df: df["SPEC_RT_ADAM"].to_list() == ["70", "50"],
        setup=_register_adam_callable,
    ),
]


def test_round_trip_cases_cover_every_algorithm() -> None:
    """A new registry algorithm without a round-trip test fails here."""
    for standard, cases in (("sdtm", SDTM_CASES), ("adam", ADAM_CASES)):
        covered = {c.algorithm for c in cases}
        registered = set(spec_registry.algorithm_names(standard))
        assert covered == registered, (
            f"{standard} round-trip coverage gap: "
            f"untested={sorted(registered - covered)}, "
            f"unknown={sorted(covered - registered)}"
        )


def _run_case(tmp_path, standard: str, case: Case) -> None:
    dataset_key = "domain" if standard == "sdtm" else "dataset"
    spec = {dataset_key: "TESTDS", "variables": case.variables}
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.dump(spec, allow_unicode=True), encoding="utf-8")

    if case.setup is not None:
        case.setup()
    try:
        frame = case.frame()
        ns = getattr(frame, standard)
        for pin_name, pin_frame in case.pins.items():
            ns = ns.pin(pin_name, pin_frame())
        result = ns.from_spec(path).to_frame()
        assert case.check(result) is not False, f"check failed for {case.algorithm}:\n{result}"
    finally:
        if case.setup is not None:
            clear_transforms()


@pytest.mark.parametrize("case", SDTM_CASES, ids=lambda c: c.algorithm)
def test_sdtm_round_trip(tmp_path, case: Case) -> None:
    """Minimal SDTM spec → from_spec → expected column present and sane."""
    _run_case(tmp_path, "sdtm", case)


@pytest.mark.parametrize("case", ADAM_CASES, ids=lambda c: c.algorithm)
def test_adam_round_trip(tmp_path, case: Case) -> None:
    """Minimal ADaM spec → from_spec → expected column present and sane."""
    _run_case(tmp_path, "adam", case)


def test_seq_and_pin_merge_from_yaml(tmp_path) -> None:
    """seq + pin-resolved merge run end-to-end from the simplified single-dataset YAML."""
    raw = pl.from_repr("""
    ┌────────────┬─────┐
    │ subject_id ┆ val │
    │ ---        ┆ --- │
    │ str        ┆ str │
    ╞════════════╪═════╡
    │ 1          ┆ a   │
    │ 2          ┆ b   │
    └────────────┴─────┘
    """)
    supp = pl.from_repr("""
    ┌─────────┬───────┐
    │ USUBJID ┆ EXTRA │
    │ ---     ┆ ---   │
    │ str     ┆ str   │
    ╞═════════╪═══════╡
    │ 1       ┆ x     │
    │ 2       ┆ y     │
    └─────────┴───────┘
    """)
    spec = tmp_path / "ae.yaml"
    spec.write_text(
        "domain: AE\n"
        "variables:\n"
        "  - target: USUBJID\n"
        "    algorithm: assign\n"
        "    source: subject_id\n"
        "  - target: AESEQ\n"
        "    algorithm: seq\n"
        "    by: [USUBJID]\n"
        "    order_by: [USUBJID]\n"
        "  - target: EXTRA\n"
        "    algorithm: merge\n"
        "    dataset: SUPP\n"
        "    on: USUBJID\n"
    )
    out = raw.sdtm.pin("SUPP", supp, join_on="USUBJID").from_spec(spec, dataset="AE").to_frame()
    assert {"AESEQ", "EXTRA"} <= set(out.columns)


def test_type_checking_only_names_do_not_erase_the_yaml_type() -> None:
    """``expression`` is typed through ``Callable`` imported under TYPE_CHECKING: still a string."""
    (field,) = [
        f
        for f in spec_registry.get_algorithm("adam", "derivation").params
        if f.name == "expression"
    ]
    assert field.annotation == (str | None)
    with pytest.raises(Exception, match="expression"):
        spec_registry.parse_variable_spec(
            "adam", {"target": "AVAL", "algorithm": "derivation", "expression": 42}
        )
