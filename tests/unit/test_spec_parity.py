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
    """Enum values == registry names (including accepted aliases)."""
    enum_values = {a.value for a in algorithm_enum}
    registry_values = set(spec_registry.algorithm_names(standard, include_aliases=True))
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
    # Alias spellings that are also real methods (e.g. dataset_level) count
    # as covered — they are reachable from a spec under their own name.
    registry_names = set(spec_registry.algorithm_names(standard, include_aliases=True))
    allowlisted = spec_registry.SPEC_UNSUPPORTED[standard]

    unaccounted = public - registry_verbs - registry_names - allowlisted - _INFRASTRUCTURE
    assert not unaccounted, (
        f"{namespace_cls.__name__} verbs with no spec story: {sorted(unaccounted)}. "
        "Register them in fleet.core.spec_registry or add them to SPEC_UNSUPPORTED."
    )

    # Every registry verb must actually exist on the namespace.
    missing = {v for v in registry_verbs if not callable(getattr(namespace_cls, v, None))}
    assert not missing, f"Registry references verbs missing on {namespace_cls.__name__}: {missing}"

    # The allowlist must stay honest: no overlap, no stale entries.
    assert not (allowlisted & registry_verbs), "SPEC_UNSUPPORTED overlaps registered verbs"
    stale = {v for v in allowlisted if not hasattr(namespace_cls, v)}
    assert not stale, f"SPEC_UNSUPPORTED lists verbs that no longer exist: {stale}"


def test_coverage_matrix_shape() -> None:
    """The published matrix has one well-formed row per canonical algorithm."""
    matrix = spec_registry.coverage_matrix()
    keys = {"standard", "algorithm", "aliases", "verb", "params", "required"}
    assert all(keys <= set(row) for row in matrix)
    per_standard = {
        s: {r["algorithm"] for r in matrix if r["standard"] == s} for s in ("sdtm", "adam")
    }
    assert per_standard["sdtm"] == set(spec_registry.algorithm_names("sdtm"))
    assert per_standard["adam"] == set(spec_registry.algorithm_names("adam"))


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
    return pl.DataFrame({"USUBJID": ["S1", "S2"], "AGE": [70, 50]})


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
        "assign_no_ct",
        lambda: pl.DataFrame({"subject_id": ["A", "B"]}),
        [{"target": "USUBJID", "algorithm": "assign_no_ct", "source": "subject_id"}],
        lambda df: df["USUBJID"].to_list() == ["A", "B"],
    ),
    Case(
        "assign_ct",
        lambda: pl.DataFrame({"sex_raw": ["male", "female"]}),
        [
            {
                "target": "SEX",
                "algorithm": "assign_ct",
                "source": "sex_raw",
                "ct_mapping": {"male": "M", "female": "F"},
            }
        ],
        lambda df: df["SEX"].to_list() == ["M", "F"],
    ),
    Case(
        "date",
        lambda: pl.DataFrame({"birth_date": ["2024-01-02"]}),
        [{"target": "BRTHDTC", "algorithm": "assign_dtc", "source": "birth_date"}],
        lambda df: df["BRTHDTC"].to_list() == ["2024-01-02"],
    ),
    Case(
        "hardcode_ct",
        lambda: _subjects(),
        [{"target": "SEX", "algorithm": "hardcode_ct", "value": "M"}],
        lambda df: df["SEX"].to_list() == ["M", "M"],
    ),
    Case(
        "hardcode_no_ct",
        lambda: _subjects(),
        [{"target": "DOMAIN", "algorithm": "hardcode_no_ct", "value": "DM"}],
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
        "if_then_else",
        lambda: _subjects(),
        [
            {
                "target": "AGEGR1",
                "algorithm": "if_then_else",
                "when": [{"condition": 'pl.col("AGE") > 64', "value": ">=65"}],
                "else_value": "<65",
            }
        ],
        lambda df: df["AGEGR1"].to_list() == [">=65", "<65"],
    ),
    Case(
        "ae_aerel",
        lambda: pl.DataFrame({"ae_relationship": ["related"]}),
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
        pins={"SUPP": lambda: pl.DataFrame({"USUBJID": ["S1", "S2"], "EXTRA": ["x", "y"]})},
    ),
    Case(
        "group_by",
        lambda: pl.DataFrame({"USUBJID": ["S1", "S1", "S2"], "val": [1, 5, 3]}),
        [
            {
                "target": "VAL",
                "algorithm": "group_by",
                "group_cols": ["USUBJID"],
                "agg": ["pl.col('val').max()"],
            }
        ],
        lambda df: df.height == 2,
    ),
    Case(
        "notsubmitted",
        lambda: pl.DataFrame({"scratch": ["a", "b"]}),
        [{"target": "scratch", "algorithm": "notsubmitted"}],
        lambda df: df["scratch"].to_list() == [None, None],
    ),
    Case(
        "multiple_responses",
        lambda: pl.DataFrame({"USUBJID": ["S1"], "ae_terms": ["fever|rash"]}),
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
        lambda: pl.DataFrame({"USUBJID": ["S1", "S1", "S2"]}),
        [
            {
                "target": "AESEQ",
                "algorithm": "seq",
                "groups": ["USUBJID"],
                "order_by": ["USUBJID"],
            }
        ],
        lambda df: df["AESEQ"].to_list() == [1, 2, 1],
    ),
    Case(
        "nsv",
        lambda: pl.DataFrame({"USUBJID": ["S1"], "safety_flag": ["Y"]}),
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
        lambda: pl.DataFrame({"AESTDTC": ["2024-01-01"], "AEENDTC": ["2024-01-05"]}),
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
        "callable",
        lambda: _subjects(),
        [{"target": "SPEC_RT_SDTM", "algorithm": "callable", "callable": "SPEC_RT_SDTM"}],
        lambda df: df["SPEC_RT_SDTM"].to_list() == ["70", "50"],
        setup=_register_sdtm_callable,
    ),
]


def _vs_frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "USUBJID": ["S1", "S1", "S2"],
            "PARAMCD": ["SYSBP", "SYSBP", "SYSBP"],
            "VISITNUM": [1, 2, 1],
            "AVAL": [120.0, 130.0, 110.0],
        }
    )


ADAM_CASES: list[Case] = [
    Case(
        "source",
        lambda: pl.DataFrame({"subject_id": ["A"]}),
        [{"target": "USUBJID", "algorithm": "source", "source": "subject_id"}],
        lambda df: df["USUBJID"].to_list() == ["A"],
    ),
    Case(
        "derivation",
        lambda: pl.DataFrame({"vs_value": [2.0]}),
        [{"target": "AVAL", "algorithm": "derivation", "expression": "pl.col('vs_value') * 2"}],
        lambda df: df["AVAL"].to_list() == [4.0],
    ),
    Case(
        "assigned",
        lambda: _subjects(),
        [{"target": "STUDYID", "algorithm": "assigned", "value": "S01"}],
        lambda df: df["STUDYID"].to_list() == ["S01", "S01"],
    ),
    Case(
        "recode",
        lambda: pl.DataFrame({"sex": ["M", "F"]}),
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
        "rename",
        lambda: pl.DataFrame({"vsdtc": ["2024-01-01"]}),
        [{"target": "ADTC", "algorithm": "rename", "source": "vsdtc"}],
        lambda df: df["ADTC"].to_list() == ["2024-01-01"],
    ),
    Case(
        "condderivation",
        lambda: _subjects(),
        [
            {
                "target": "AGEGR1",
                "algorithm": "condderivation",
                "conditions": [{"condition": 'pl.col("AGE") < 65', "value": "<65"}],
                "else_value": ">=65",
            }
        ],
        lambda df: df["AGEGR1"].to_list() == [">=65", "<65"],
    ),
    Case(
        "lookup",
        lambda: _subjects(),
        [
            {
                "target": "TRTSDT",
                "algorithm": "lookup",
                "dataset": "ADSL",
                "on": "USUBJID",
            }
        ],
        lambda df: "TRTSDT" in df.columns,
        pins={
            "ADSL": lambda: pl.DataFrame(
                {"USUBJID": ["S1", "S2"], "TRTSDT": [date(2024, 1, 1), date(2024, 1, 2)]}
            )
        },
    ),
    Case(
        "whereclauses",
        lambda: _subjects(),
        [{"target": "AGE", "algorithm": "whereclauses", "where": 'pl.col("AGE") > 60'}],
        lambda df: df.height == 1,
    ),
    Case(
        "study_day",
        lambda: pl.DataFrame({"ADT": [date(2024, 1, 10)], "TRTSDT": [date(2024, 1, 1)]}),
        [
            {
                "target": "ADY",
                "algorithm": "study_day",
                "analysis_date": "ADT",
                "reference_date": "TRTSDT",
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
                "groups": ["USUBJID", "PARAMCD"],
            }
        ],
        lambda df: df.sort("USUBJID", "VISITNUM")["BASE"].to_list() == [120.0, 120.0, 110.0],
    ),
    Case(
        "chg",
        lambda: pl.DataFrame({"AVAL": [130.0], "BASE": [120.0]}),
        [{"target": "CHG", "algorithm": "chg"}],
        lambda df: df["CHG"].to_list() == [10.0],
    ),
    Case(
        "pchg",
        lambda: pl.DataFrame({"AVAL": [130.0], "BASE": [100.0]}),
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
                "groups": ["USUBJID"],
            }
        ],
        lambda df: df.sort("USUBJID", "VISITNUM")["ABLFL"].to_list() == ["Y", None, "Y"],
    ),
    Case(
        "bmi",
        lambda: pl.DataFrame({"WEIGHT": [80.0], "HEIGHT": [200.0]}),
        [{"target": "BMI", "algorithm": "bmi", "weight": "WEIGHT", "height": "HEIGHT"}],
        lambda df: df["BMI"].to_list() == [20.0],
    ),
    Case(
        "nrind",
        lambda: pl.DataFrame(
            {
                "AVAL": [50.0, 100.0, 200.0],
                "LBSTNRLO": [60.0, 60.0, 60.0],
                "LBSTNRHI": [140.0, 140.0, 140.0],
            }
        ),
        [{"target": "LBNRIND", "algorithm": "nrind"}],
        lambda df: df["LBNRIND"].to_list() == ["LOW", "NORMAL", "HIGH"],
    ),
    Case(
        "on_treatment",
        lambda: pl.DataFrame(
            {
                "ADT": [date(2024, 1, 5), date(2024, 3, 1)],
                "TRTSDT": [date(2024, 1, 1)] * 2,
                "TRTEDT": [date(2024, 2, 1)] * 2,
            }
        ),
        [{"target": "ONTRTFL", "algorithm": "on_treatment"}],
        lambda df: df["ONTRTFL"].to_list() == ["Y", None],
    ),
    Case(
        "shift",
        lambda: pl.DataFrame({"BNRIND": ["NORMAL"], "ANRIND": ["HIGH"]}),
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
        lambda: pl.DataFrame({"USUBJID": ["S1", "S1"]}),
        [{"target": "ASEQ", "algorithm": "seq", "groups": ["USUBJID"]}],
        lambda df: df["ASEQ"].to_list() == [1, 2],
    ),
    Case(
        "bsa",
        lambda: pl.DataFrame({"WEIGHT": [80.0], "HEIGHT": [180.0]}),
        [{"target": "BSA", "algorithm": "bsa", "weight": "WEIGHT", "height": "HEIGHT"}],
        lambda df: 1.5 < df["BSA"][0] < 2.5,
    ),
    Case(
        "map",
        lambda: pl.DataFrame({"SYSBP": [120.0], "DIABP": [80.0]}),
        [{"target": "MAP", "algorithm": "mean_arterial_pressure"}],
        lambda df: 90 < df["MAP"][0] < 96,
    ),
    Case(
        "qtc",
        lambda: pl.DataFrame({"QT": [400.0], "RR": [1000.0]}),
        [{"target": "QTCF", "algorithm": "qtc"}],
        lambda df: df["QTCF"][0] is not None,
    ),
    Case(
        "atoxgr",
        lambda: pl.DataFrame(
            {
                "USUBJID": ["S1", "S2"],
                "PARAMCD": ["Anemia", "Anemia"],
                "AVAL": [75.0, 150.0],
                "ANRLO": [140.0, 140.0],
                "AVALU": ["g/L", "g/L"],
            }
        ),
        [
            {
                "target": "ATOXGRL",
                "algorithm": "atoxgr",
                "direction": "L",
                "unit_var": "AVALU",
            }
        ],
        lambda df: df.sort("USUBJID")["ATOXGRL"].to_list() == ["3", "0"],
    ),
    Case(
        "combine_grades",
        lambda: pl.DataFrame(
            {"ATOXGRL": ["3"], "ATOXGRH": [None]},
            schema={"ATOXGRL": pl.String, "ATOXGRH": pl.String},
        ),
        [{"target": "ATOXGR", "algorithm": "combine_grades"}],
        lambda df: df["ATOXGR"].to_list() == ["-3"],
    ),
    Case(
        "date",
        lambda: pl.DataFrame({"vsdtc": ["2024-01-02"]}),
        [{"target": "ADT", "algorithm": "date", "source": "vsdtc"}],
        lambda df: df["ADT"].to_list() == [date(2024, 1, 2)],
    ),
    Case(
        "duration",
        lambda: pl.DataFrame({"TRTSDT": [date(2024, 1, 1)], "TRTEDT": [date(2024, 1, 10)]}),
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
        lambda: pl.DataFrame({"USUBJID": ["S1", "S2"], "DTHDT": [date(2024, 1, 1), None]}),
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
        lambda df: df.sort("USUBJID")["TRTSDT"].to_list() == ["2024-01-01", "2024-01-03"],
        pins={
            "EX": lambda: pl.DataFrame(
                {
                    "USUBJID": ["S1", "S1", "S2"],
                    "EXSTDTC": ["2024-01-01", "2024-01-05", "2024-01-03"],
                }
            )
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
        lambda df: df.sort("USUBJID")["TRTEDT"].to_list() == ["2024-01-05", "2024-01-03"],
        pins={
            "EX": lambda: pl.DataFrame(
                {
                    "USUBJID": ["S1", "S1", "S2"],
                    "EXSTDTC": ["2024-01-01", "2024-01-05", "2024-01-03"],
                }
            )
        },
    ),
    Case(
        "count_events",
        lambda: _subjects(),
        [
            {
                "target": "NUMAE",
                "algorithm": "count",  # documented alias of count_events
                "from_dataset": "AE",
                "where": 'pl.col("AESER") == "Y"',
            }
        ],
        lambda df: df.sort("USUBJID")["NUMAE"].to_list() == [1, 0],
        pins={
            "AE": lambda: pl.DataFrame({"USUBJID": ["S1", "S1", "S2"], "AESER": ["Y", "N", "N"]})
        },
    ),
    Case(
        "callable",
        lambda: _subjects(),
        [{"target": "SPEC_RT_ADAM", "algorithm": "callable", "callable": "SPEC_RT_ADAM"}],
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
    """seq + pin-resolved merge run end-to-end from YAML (legacy join_on key)."""
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
        "    algorithm: assign_no_ct\n"
        "    source: subject_id\n"
        "  - target: AESEQ\n"
        "    algorithm: seq\n"
        "    groups: [USUBJID]\n"
        "    order_by: [USUBJID]\n"
        "  - target: EXTRA\n"
        "    algorithm: merge\n"
        "    dataset: SUPP\n"
        "    join_on: USUBJID\n"
    )
    out = raw.sdtm.pin("SUPP", supp, join_on="USUBJID").from_spec(spec, dataset="AE").to_frame()
    assert {"AESEQ", "EXTRA"} <= set(out.columns)
