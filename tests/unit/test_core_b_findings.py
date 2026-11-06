"""Regression tests for the ml-core-b audit findings (core verbs, config, DAG, spec tools)."""

from __future__ import annotations

import logging
import warnings
from pathlib import Path

import polars as pl
import pytest
import yaml

import fleet  # noqa: F401
from fleet.core.exceptions import (
    DerivationError,
    FleetError,
    FleetIOError,
    SpecError,
    ValidationSetupError,
    VerbUsageError,
)

AE = """\
┌─────────┬────────────┬─────────┐
│ USUBJID ┆ AESTDTC    ┆ AETERM  │
│ ---     ┆ ---        ┆ ---     │
│ str     ┆ str        ┆ str     │
╞═════════╪════════════╪═════════╡
│ A       ┆ 2024-01-02 ┆ HEADACHE│
│ A       ┆ 2024-01-01 ┆ NAUSEA  │
└─────────┴────────────┴─────────┘
"""


def _ae() -> pl.DataFrame:
    return pl.from_repr(AE)


class _SEX:
    _concept_id = "C66731"
    M = "M"
    F = "F"
    U = "U"


# ── c1-23 seq and to_spec_yaml check their columns ──────────────────────


def test_seq_names_the_default_by_column_that_is_missing():
    with pytest.raises(DerivationError, match=r"'STUDYID' \(from the default by="):
        _ae().sdtm.seq("AESEQ", order_by=["AESTDTC"])


def test_seq_names_a_misspelled_order_by_column_with_a_hint():
    with pytest.raises(DerivationError, match=r"'AESTDTX' \(did you mean 'AESTDTC'\?\)"):
        _ae().sdtm.seq("AESEQ", by=["USUBJID"], order_by=["AESTDTX"], check_uniqueness=True)


def test_to_spec_yaml_on_a_broken_plan_raises_a_derivation_error():
    ns = _ae().sdtm.derivation("X", expression=pl.col("AETERM"))
    broken = ns._with_lazy(ns._lazy.select(pl.col("NOPE")))
    with pytest.raises(DerivationError, match="NOPE"):
        broken.to_spec_yaml(dataset="AE")


# ── c1-59 seq(check_uniqueness=True) ─────────────────────────────────────


def test_seq_check_uniqueness_warns_on_a_tie_and_names_the_key():
    ae = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ AESTDTC    │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ A       ┆ 2024-01-01 │
│ A       ┆ 2024-01-01 │
└─────────┴────────────┘
""")
    with pytest.warns(UserWarning, match=r"not unique by \['USUBJID', 'AESTDTC'\]"):
        ae.sdtm.seq("AESEQ", by=["USUBJID"], order_by=["AESTDTC"], check_uniqueness=True)


def test_seq_check_uniqueness_is_silent_on_a_unique_key():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = (
            _ae()
            .sdtm.seq("AESEQ", by=["USUBJID"], order_by=["AESTDTC"], check_uniqueness=True)
            .to_frame()
        )
    assert out["AESEQ"].to_list() == [1, 2]


# ── c1-24 a missing column raises at the verb ────────────────────────────


@pytest.mark.parametrize(
    ("call", "match"),
    [
        (lambda ns, r: ns.merge(r, on=["USUBJIX"]), r"merge\(on=...\).*'USUBJIX'"),
        (
            lambda ns, r: ns.merge(
                r.rename({"AETERM": "T"}), on="USUBJID", where="pl.col('Y') > 1"
            ),
            r"merge\(where=...\).*'Y'.*right dataset",
        ),
        (
            lambda ns, r: ns.group_by(by=["USUBJIX"], agg=[pl.len()]),
            r"group_by\(by=...\).*'USUBJIX'",
        ),
        (lambda ns, r: ns.nodup(subset=["USUBJID", "AETERMX"]), r"nodup\(subset=...\).*AETERMX"),
        (
            lambda ns, r: ns.nodup(subset=["USUBJID", "AETERM"], order_by=["AESEQX"], keep="first"),
            r"nodup\(order_by=...\).*AESEQX",
        ),
    ],
)
def test_sdtm_verbs_name_a_missing_column_at_the_call(call, match):
    ae = _ae()
    with pytest.raises(DerivationError, match=match):
        call(ae.sdtm, ae.select("USUBJID", "AETERM"))


def test_whereclauses_names_a_missing_column_at_the_call():
    with pytest.raises(DerivationError, match=r"whereclauses.*'AESTDTX'.*did you mean"):
        _ae().adam.whereclauses(where="pl.col('AESTDTX') == 'x'")


def test_merge_refuses_a_text_key_against_a_number_key():
    right = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ AGE │
│ ---     ┆ --- │
│ i64     ┆ i64 │
╞═════════╪═════╡
│ 1       ┆ 50  │
└─────────┴─────┘
""")
    with pytest.raises(DerivationError, match=r"key 'USUBJID' is String in the pipeline and Int64"):
        _ae().sdtm.merge(right, on="USUBJID")


# ── c1-25 from_spec names the variable of a plan error ──────────────────


def test_from_spec_attributes_a_schema_error_to_its_variable(tmp_path):
    spec = tmp_path / "define.yaml"
    spec.write_text(
        yaml.safe_dump(
            {
                "datasets": [
                    {
                        "name": "AE",
                        "variables": [
                            {
                                "name": "AESEQ",
                                "derivation": {"algorithm": "seq", "order_by": ["AESTDTC"]},
                            },
                            {
                                "name": "DOMAIN",
                                "derivation": {"algorithm": "assign", "value": "AE"},
                            },
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(SpecError, match=r"dataset AE → variable AESEQ.*STUDYID"):
        _ae().sdtm.from_spec(spec, dataset="AE")


# ── c1-29 entry checks ───────────────────────────────────────────────────


def test_flag_exists_refuses_a_dataset_name():
    with pytest.raises(VerbUsageError, match=r"from_dataset must be a DataFrame.*got str 'AE'"):
        _ae().adam.flag_exists("F", from_dataset="AE", on=["USUBJID"])


@pytest.mark.parametrize("verb", ["first_date", "last_date"])
def test_first_and_last_date_refuse_a_dataset_name(verb):
    with pytest.raises(VerbUsageError, match=rf"{verb}\('TRTSDT'\): from_dataset must be"):
        getattr(_ae().adam.adsl, verb)("TRTSDT", from_dataset="EX", date_col="EXSTDTC")


def test_count_events_refuses_a_dataset_name():
    with pytest.raises(VerbUsageError, match=r"count_events\('NUMAE'\): from_dataset must be"):
        _ae().adam.adsl.count_events("NUMAE", from_dataset="AE")


def test_first_date_names_an_unknown_date_col():
    ex = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ EXSTDTC    │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ A       ┆ 2024-01-01 │
└─────────┴────────────┘
""")
    with pytest.raises(DerivationError, match=r"'NOPE' not found in from_dataset"):
        _ae().adam.adsl.first_date("TRTSDT", from_dataset=ex, date_col="NOPE")


def test_nodup_takes_one_column_name_as_text(caplog):
    with caplog.at_level(logging.INFO, logger="fleet"):
        _ae().sdtm.nodup(subset="USUBJID")
    assert "subset: USUBJID" in caplog.text


# ── c1-33 assign(value=, ct=<class>) uses the class terms ────────────────


def test_a_valid_constant_is_silent_with_a_codelist_class():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _ae().sdtm.assign("SEX", value="M", ct=_SEX)


def test_an_invalid_constant_warns_with_the_valid_terms():
    with pytest.warns(UserWarning, match=r"value 'Z' not in codelist 'C66731'.*\['F', 'M', 'U'\]"):
        _ae().sdtm.assign("SEX", value="Z", ct=_SEX)


def test_validate_values_false_silences_the_constant_check():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _ae().sdtm.assign("SEX", value="Z", ct=_SEX, validate_values=False)


# ── c1-36 the CT warning is stable, short and at the user line ───────────


def test_ct_warning_is_sorted_capped_and_at_the_user_line():
    terms = type("BIG", (), {"_concept_id": "C1", **{f"T{i:02d}": f"T{i:02d}" for i in range(25)}})
    df = pl.from_repr("""\
┌─────┐
│ x   │
│ --- │
│ str │
╞═════╡
│ f   │
│ a   │
│ c   │
└─────┘
""")
    with pytest.warns(UserWarning) as record:
        df.sdtm.assign("X", source="x", ct=terms)
    message = str(record[0].message)
    assert "['a', 'c', 'f']" in message
    assert "(and 5 more)" in message
    assert record[0].filename == __file__


def test_an_adam_spec_names_the_dataset_in_the_ct_warning(tmp_path):
    ct = tmp_path / "ct.yaml"
    ct.write_text(yaml.safe_dump({"C66731": {"M": "Male", "F": "Female"}}), encoding="utf-8")
    spec = tmp_path / "define.yaml"
    spec.write_text(
        yaml.safe_dump(
            {
                "ct": {"validate": True, "file": ct.name},
                "datasets": [
                    {
                        "name": "ADSL",
                        "variables": [
                            {
                                "name": "SEX",
                                "derivation": {
                                    "algorithm": "assign",
                                    "source": "sex",
                                    "ct": "C66731",
                                },
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    df = pl.from_repr("""\
┌─────┐
│ sex │
│ --- │
│ str │
╞═════╡
│ X   │
└─────┘
""")
    from fleet.ct.validator import get_validator

    validator = get_validator()
    cache, aliases = dict(validator._ct_cache), dict(validator._codelist_aliases)
    try:
        with pytest.warns(UserWarning, match=r"ADSL\.SEX: column 'sex'"):
            df.adam.from_spec(spec, dataset="ADSL")
    finally:
        validator._ct_cache, validator._codelist_aliases = cache, aliases


# ── c1-41 c1-42 to_spec_yaml keeps the codelist and the evaluator ────────


def test_to_spec_yaml_writes_the_codelist_and_its_terms():
    dm = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ sex │
│ ---     ┆ --- │
│ str     ┆ str │
╞═════════╪═════╡
│ A       ┆ M   │
└─────────┴─────┘
""")
    text = dm.sdtm.assign("SEX", source="sex", ct=_SEX).to_spec_yaml(dataset="DM")
    data = yaml.safe_load(text)
    sex = next(v for v in data["datasets"][0]["variables"] if v["name"] == "SEX")
    assert sex["codelist"] == "C66731"
    assert data["codelists"] == [
        {
            "oid": "C66731",
            "name": "_SEX",
            "type": "text",
            "items": [{"coded_value": "F"}, {"coded_value": "M"}, {"coded_value": "U"}],
        }
    ]


def test_to_spec_yaml_round_trip_gives_a_codelist_ref(tmp_path):
    from fleet.define_xml import DefineSpecGenerator

    dm = pl.from_repr("""\
┌─────────┬─────────┬─────┐
│ STUDYID ┆ USUBJID ┆ sex │
│ ---     ┆ ---     ┆ --- │
│ str     ┆ str     ┆ str │
╞═════════╪═════════╪═════╡
│ S       ┆ A       ┆ M   │
└─────────┴─────────┴─────┘
""")
    path = tmp_path / "define.yaml"
    dm.sdtm.assign("SEX", source="sex", ct=_SEX).to_spec_yaml(dataset="DM", path=path)
    xml = DefineSpecGenerator(path, validate_xml=False).to_xml_string()
    assert xml.count("<CodeListRef") == 1


def test_a_bare_codelist_id_with_no_terms_writes_a_todo_and_no_codelist():
    dm = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ sex │
│ ---     ┆ --- │
│ str     ┆ str │
╞═════════╪═════╡
│ A       ┆ M   │
└─────────┴─────┘
""")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        text = dm.sdtm.assign("SEX", source="sex", ct="C99999").to_spec_yaml(dataset="DM")
    assert "# TODO: no codelist terms were known for SEX (C99999)" in text
    assert "\ncodelists:" not in text
    assert "codelist: C99999" not in text


def test_to_spec_yaml_round_trip_keeps_the_nsv_evaluator(tmp_path):
    ae = pl.from_repr("""\
┌─────────┬────────┬─────────┬───────┬─────┐
│ STUDYID ┆ DOMAIN ┆ USUBJID ┆ AESEQ ┆ tox │
│ ---     ┆ ---    ┆ ---     ┆ ---   ┆ --- │
│ str     ┆ str    ┆ str     ┆ i64   ┆ str │
╞═════════╪════════╪═════════╪═══════╪═════╡
│ S       ┆ AE     ┆ A       ┆ 1     ┆ 3   │
└─────────┴────────┴─────────┴───────┴─────┘
""")
    ns = ae.sdtm.nsv(
        "AETOXG", source="tox", label="Toxicity Grade", origin="Collected", evaluator="INVESTIGATOR"
    )
    path = tmp_path / "define.yaml"
    text = ns.to_spec_yaml(dataset="AE", path=path)
    assert "evaluator: INVESTIGATOR" in text
    supp = ae.sdtm.from_spec(path, dataset="AE").export_supp(idvar="AESEQ")
    row = supp.row(0, named=True)
    assert (row["QNAM"], row["QLABEL"], row["QORIG"], row["QEVAL"], row["QVAL"]) == (
        "AETOXG",
        "Toxicity Grade",
        "Collected",
        "INVESTIGATOR",
        "3",
    )


# ── c1-45 derivation() refuses the wrong forms ───────────────────────────


@pytest.mark.parametrize("target", [lambda d: d, 5])
def test_derivation_refuses_a_target_that_is_not_a_derivation(target):
    with pytest.raises(VerbUsageError, match="derivation\\(\\) takes a target name"):
        _ae().sdtm.derivation(target)


def test_derivation_refuses_a_frame_derivation_as_expression():
    from fleet.core.derivation import derivation

    @derivation
    def add_y(df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(pl.lit(1).alias("Y"))

    with pytest.raises(VerbUsageError, match="kind='frame'"):
        _ae().sdtm.derivation("Y", expression=add_y)


# ── c1-46 the nodup report survives a sub-namespace switch ───────────────


@pytest.mark.parametrize("sub", ["occds", "adsl"])
def test_nodup_report_survives_a_sub_namespace(sub):
    ns = _ae().adam.nodup(subset=["USUBJID"])
    assert getattr(ns, sub).last_nodup_report.height == 2


# ── c1-48 inspect and explain raise the to_frame error ───────────────────


@pytest.mark.parametrize("verb", ["inspect", "explain"])
def test_inspect_and_explain_raise_a_derivation_error(verb):
    ns = _ae().sdtm
    broken = ns._with_lazy(ns._lazy.select(pl.col("STUDYID")))
    with pytest.raises(DerivationError, match="Pipeline collection failed"):
        getattr(broken, verb)()


# ── c1-51 compare and validate run the chain once ────────────────────────


def _counted(calls: list[int]):
    def bump(s: pl.Series) -> pl.Series:
        calls.append(1)
        return s

    return pl.col("AETERM").map_batches(bump, return_dtype=pl.String)


def test_compare_then_to_frame_runs_the_chain_once():
    calls: list[int] = []
    ae = _ae()
    ns = ae.sdtm.derivation("T2", expression=_counted(calls))
    base = ae.with_columns(pl.col("AETERM").alias("T2"))
    ns.compare(base, keys=["USUBJID", "AESTDTC"], on_fail="ignore").to_frame()
    assert len(calls) == 1


def test_validate_then_to_frame_runs_the_chain_once(monkeypatch):
    from fleet.validation import service

    class _Result:
        could_not_run = None
        is_valid = True
        errors: list = []

        def apply_setup(self, setup):
            pass

        def print_report(self, report_type):
            pass

    class _Service:
        def __init__(self, rules_engine_path=None):
            pass

        def validate_sdtm(self, df, **kwargs):
            return _Result()

    monkeypatch.setattr(service, "ValidationService", _Service)
    monkeypatch.setattr("fleet.core._verb_mixin.ValidationSetupError", ValidationSetupError)
    monkeypatch.setattr(
        "fleet.validation.lineage_join.enrich_with_lineage", lambda result, lineage: None
    )
    calls: list[int] = []
    ns = _ae().sdtm.derivation("T2", expression=_counted(calls))
    ns.validate("AE", rules_engine_path=Path(__file__), on_fail="ignore").to_frame()
    assert len(calls) == 1


# ── c1-52 no engine is a setup error ─────────────────────────────────────


def test_validate_with_a_missing_engine_is_a_setup_error():
    with pytest.raises(ValidationSetupError, match="not found"):
        _ae().sdtm.validate("AE", rules_engine_path=Path("/nonexistent/core"), on_fail="ignore")


# ── c1-53 from_spec refuses unknown names ────────────────────────────────


def _advs_spec(tmp_path: Path) -> Path:
    spec = tmp_path / "define.yaml"
    spec.write_text(
        yaml.safe_dump(
            {
                "datasets": [
                    {
                        "name": "ADVS",
                        "variables": [
                            {
                                "name": "CHG",
                                "derivation": {"algorithm": "chg", "aval": "AVAL", "base": "BASE"},
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    return spec


@pytest.mark.parametrize("arg", ["only", "omit"])
def test_from_spec_refuses_an_unknown_name_in_only_and_omit(tmp_path, arg):
    with pytest.raises(SpecError, match=r"names 'CGH' \(did you mean 'CHG'\?\)"):
        _ae().adam.from_spec(_advs_spec(tmp_path), dataset="ADVS", **{arg: ["CGH"]})


def test_from_spec_refuses_another_dataset_in_a_simplified_spec(tmp_path):
    spec = tmp_path / "vs.yaml"
    spec.write_text(
        yaml.safe_dump(
            {"domain": "VS", "variables": [{"target": "VSX", "algorithm": "assign", "value": 1}]}
        ),
        encoding="utf-8",
    )
    with pytest.raises(SpecError, match=r"dataset='LB' was asked.*describes VS"):
        _ae().sdtm.from_spec(spec, dataset="LB")


def test_a_define_with_one_dataset_twice_is_refused(tmp_path):
    spec = tmp_path / "define.yaml"
    spec.write_text(
        yaml.safe_dump({"datasets": [{"name": "ADVS"}, {"name": "ADVS"}]}), encoding="utf-8"
    )
    with pytest.raises(SpecError, match="declared twice"):
        _ae().adam.from_spec(spec, dataset="ADVS")


# ── c1-55 an old key names fleet migrate ─────────────────────────────────


def test_an_old_key_under_an_unchanged_algorithm_names_fleet_migrate(tmp_path):
    spec = tmp_path / "define.yaml"
    spec.write_text(
        "fleet_spec_version: 2\ndatasets:\n  - name: AE\n    variables:\n"
        "      - name: AESEQ\n        derivation: {algorithm: seq, groups: [USUBJID],"
        " order_by: [AESTDTC]}\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecError, match="fleet migrate --spec"):
        _ae().sdtm.from_spec(spec, dataset="AE")


def test_a_typo_in_a_current_spec_gets_no_migrate_hint(tmp_path):
    spec = tmp_path / "define.yaml"
    spec.write_text(
        "datasets:\n  - name: AE\n    variables:\n      - name: AESEQ\n"
        "        derivation:\n          algorithm: seq\n          by: [USUBJID]\n"
        "          order_byy: [AESTDTC]\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecError) as err:
        _ae().sdtm.from_spec(spec, dataset="AE")
    assert "fleet migrate" not in str(err.value)


def test_define_xml_schema_error_names_fleet_migrate(tmp_path):
    from fleet.define_xml import DefineSpecGenerator

    spec = tmp_path / "define.yaml"
    spec.write_text(
        "study: {id: S, name: S, description: d, protocol_name: S, originator: o,"
        " standard: SDTMIG, standard_version: '3.4'}\n"
        "datasets:\n  - name: AE\n    label: AE\n    variables:\n"
        "      - name: AESEQ\n        label: Seq\n        type: integer\n"
        "        derivation: {algorithm: seq, groups: [USUBJID]}\n",
        encoding="utf-8",
    )
    with pytest.raises(SpecError, match="fleet migrate --spec"):
        DefineSpecGenerator(spec).to_xml_string()


# ── c1-64 c1-731 readable namespace and summaries ────────────────────────


def test_a_namespace_prints_as_a_pipeline():
    assert repr(_ae().sdtm) == "SDTM pipeline, not materialised. Call .to_frame() to see the data."
    assert repr(_ae().adam).startswith("ADaM pipeline")


@pytest.mark.parametrize(
    "doc",
    [
        "Derive a new parameter (e.g. BMI) from two others.",
        "Derive TRTDURD, i.e. EXENDT minus EXSTDT plus 1.",
    ],
)
def test_docstring_summary_does_not_cut_at_an_abbreviation(doc):
    from fleet.core.algorithm_resolver import docstring_summary

    assert docstring_summary(doc) == doc


def test_no_verb_summary_ends_in_an_abbreviation():
    summaries = _ae().adam.verbs()["summary"].to_list()
    assert not [s for s in summaries if s.endswith(("e.g.", "i.e.", "etc.", "vs.", "cf."))]


# ── c1-540 c1-751 scaffolder ─────────────────────────────────────────────


def test_adam_structure_starts_with_the_identifier_set():
    from fleet.core.scaffolder import DefineScaffolder

    ds = {
        "name": "BDS",
        "analysisVariableSets": [
            {"ordinal": "2", "analysisVariables": [{"name": "TRTP", "ordinal": "1"}]},
            {
                "ordinal": "1",
                "analysisVariables": [
                    {"name": "STUDYID", "ordinal": "1"},
                    {"name": "USUBJID", "ordinal": "2"},
                ],
            },
        ],
    }
    parsed = DefineScaffolder(client=None)._parse_adam_structure(ds)
    assert [v["name"] for v in parsed["variables"]] == ["STUDYID", "USUBJID", "TRTP"]


def test_an_unknown_domain_warns_and_no_known_domain_stops():
    from fleet.core.scaffolder import DefineScaffolder

    class _Client:
        def get(self, path: str) -> dict:
            if path.endswith("/datasets"):
                return {"_links": {"datasets": [{"href": "/mdr/sdtmig/3-4/datasets/DM"}]}}
            return {"name": "DM", "datasetVariables": []}

    scaffolder = DefineScaffolder(client=_Client())
    with pytest.warns(UserWarning, match="Domain 'XX' not found in SDTM IG 3-4"):
        scaffolder._fetch_sdtm_datasets("3-4", ["DM", "XX"])
    with pytest.warns(UserWarning), pytest.raises(SpecError, match="None of the requested domains"):
        scaffolder._fetch_sdtm_datasets("3-4", ["XX"])


# ── c1-542 c1-545 c1-546 c1-548 c1-549 c1-550 c1-742 study config ────────


def _write_config(tmp_path: Path, text: str, encoding: str = "utf-8") -> Path:
    path = tmp_path / "study_config.yaml"
    path.write_bytes(text.encode(encoding))
    return path


def test_an_unknown_config_key_is_refused_by_its_path(tmp_path):
    from fleet.core.study_context import StudyConfigError, load_study_context

    path = _write_config(tmp_path, "study_id: S\nsdtm:\n  ig_versoin: '3-3'\n")
    with pytest.raises(StudyConfigError, match=r"sdtm\.ig_versoin"):
        load_study_context(path)


def test_the_config_fleet_new_writes_still_loads(tmp_path):
    from fleet.core.study_context import StudyContext, load_study_context

    StudyContext.init(tmp_path, study_id="STUDY01", company="Société Générale")
    assert load_study_context(tmp_path / "study_config.yaml").study_id == "STUDY01"


def test_a_latin1_config_is_a_study_config_error(tmp_path):
    from fleet.core.study_context import StudyConfigError, load_study_context

    path = _write_config(tmp_path, "study_id: S\ncompany: Société\n", encoding="latin-1")
    with pytest.raises(StudyConfigError, match=r"not UTF-8 text \(byte 0xe9"):
        load_study_context(path)


def test_an_impossible_date_in_the_config_is_a_study_config_error(tmp_path):
    from fleet.core.study_context import StudyConfigError, load_study_context

    path = _write_config(tmp_path, "study_id: S\ndescription: 2024-02-30\n")
    with pytest.raises(StudyConfigError, match="Invalid YAML"):
        load_study_context(path)


@pytest.mark.parametrize("written", ["3.4", "'3.4'", "'3-4'"])
def test_ig_version_is_read_in_the_library_form(tmp_path, written):
    from fleet.core.study_context import load_study_context

    path = _write_config(tmp_path, f"study_id: S\nsdtm:\n  ig_version: {written}\n")
    assert load_study_context(path).config.sdtm.ig_version == "3-4"


def test_study_config_error_is_a_fleet_error_exported_from_core():
    from fleet.core import StudyConfigError

    assert issubclass(StudyConfigError, FleetError)


def test_load_study_context_takes_text_and_keeps_its_paths_after_chdir(tmp_path, monkeypatch):
    from fleet.core.study_context import load_study_context

    _write_config(tmp_path, "study_id: S\n")
    monkeypatch.chdir(tmp_path)
    ctx = load_study_context("study_config.yaml")
    before = ctx.metadata_sdtm_dir
    monkeypatch.chdir(tmp_path.parent)
    assert ctx.metadata_sdtm_dir == before
    assert ctx.study_root.is_absolute()


def test_fleet_new_writes_a_gitignore_with_env_and_keeps_an_existing_one(tmp_path):
    from fleet.core.study_context import StudyContext

    StudyContext.init(tmp_path / "a", study_id="A")
    assert (tmp_path / "a" / ".gitignore").read_text(encoding="utf-8") == ".env\n"
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / ".gitignore").write_text("data/\n", encoding="utf-8")
    StudyContext.init(tmp_path / "b", study_id="B")
    assert (tmp_path / "b" / ".gitignore").read_text(encoding="utf-8") == "data/\n"


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("x: !!float abc\n", "could not convert string to float"),
        ("a: &x {b: *x}\n", "alias *x refers to itself"),
    ],
)
def test_a_bad_tag_or_a_recursive_alias_gives_one_diagnostic(text, message):
    from fleet.lsp_server import compute_diagnostics

    diagnostics = compute_diagnostics(text)
    assert len(diagnostics) == 1
    assert message in diagnostics[0]["message"]


# ── c1-747 failures are FleetErrors ──────────────────────────────────────


def test_fleet_failures_are_fleet_errors_and_keep_their_builtin_class():
    from fleet.adam.grading import load_criteria
    from fleet.define_xml.checker import CheckResult

    with pytest.raises(FleetError) as err:
        load_criteria("nope")
    assert isinstance(err.value, ValueError)
    result = CheckResult(dataset="DM")
    result.errors.append("x")
    with pytest.raises(FleetError) as err:
        result.raise_on_errors()
    assert isinstance(err.value, ValueError)
    assert issubclass(FleetIOError, OSError)


# ── c1-748 c1-749 logging recipes ────────────────────────────────────────


@pytest.fixture
def _fresh_fleet_logger(monkeypatch):
    from fleet.core import log

    logger = logging.getLogger("fleet")
    level, handlers = logger.level, list(logger.handlers)
    monkeypatch.setattr(log, "_auto_checked", False)
    monkeypatch.setattr(log, "_console_handler", None)
    logger.handlers = [h for h in handlers if isinstance(h, logging.NullHandler)]
    logger.setLevel(logging.NOTSET)
    yield logger
    logger.handlers = handlers
    logger.setLevel(level)


@pytest.mark.usefixtures("_fresh_fleet_logger")
def test_the_silence_recipe_keeps_warning_level(capsys):
    logging.getLogger("fleet").setLevel(logging.WARNING)
    _ae().sdtm.nodup(subset=["USUBJID"])
    assert logging.getLogger("fleet").level == logging.WARNING
    assert "[NODUP]" not in capsys.readouterr().out


def test_the_route_recipe_receives_info_lines(_fresh_fleet_logger, capsys):
    records: list[logging.LogRecord] = []

    class _Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    _fresh_fleet_logger.addHandler(_Keep())
    _ae().sdtm.nodup(subset=["USUBJID"])
    assert any("[NODUP]" in r.getMessage() for r in records)
    assert "[NODUP]" not in capsys.readouterr().out


def test_the_cli_writes_a_fleet_warning_to_stderr(capsys):
    from fleet.core.log import enable_cli_warnings, get_logger

    enable_cli_warnings()
    get_logger("fleet.core.scaffolder").warning("Domain 'XX' skipped")
    assert "WARNING Domain 'XX' skipped" in capsys.readouterr().err


# ── c1-750 to_repr refuses a table that gives another frame ──────────────


def test_to_repr_round_trips_a_float_in_full():
    from fleet.core.repr_utils import to_repr

    df = pl.DataFrame({"X": [3.141592653589793]})
    assert pl.from_repr(to_repr(df)).equals(df)


@pytest.mark.parametrize(
    "df",
    [
        pl.DataFrame({f"C{i}": [1] for i in range(60)}),
        pl.DataFrame({"AETERM": ["x" * 150]}),
    ],
)
def test_to_repr_raises_when_the_table_is_cut(df):
    from fleet.core.repr_utils import to_repr

    with pytest.raises(DerivationError, match="Widen max_cols"):
        to_repr(df)


# ── c1-734 c1-738 DAG ────────────────────────────────────────────────────

_PILOT = Path(__file__).parents[2] / "examples" / "cdiscpilot01"


def test_the_pilot_adsl_depends_on_ex_through_its_pin():
    from fleet.core import build_dag

    dag = build_dag(_PILOT / "sdtm" / "define.yaml", _PILOT / "adam" / "define.yaml")
    assert "EX" in dag.nodes["ADSL"].inputs
    assert dag.impacted_by("EX") == ["EX", "ADSL", "ADVS", "ADAE", "ADEX"]


def _define(path: Path, datasets: list[dict]) -> Path:
    path.write_text(
        yaml.safe_dump({"study": {"standard": "ADAMIG"}, "datasets": datasets}), encoding="utf-8"
    )
    return path


def test_a_pin_name_with_no_node_adds_no_edge(tmp_path):
    from fleet.core import build_dag

    spec = _define(
        tmp_path / "define.yaml",
        [
            {
                "name": "ADSL",
                "variables": [
                    {
                        "name": "TRTSDT",
                        "derivation": {
                            "algorithm": "first_date",
                            "from_dataset": "EX",
                            "date_col": "EXSTDTC",
                        },
                    }
                ],
            }
        ],
    )
    assert build_dag(spec).nodes["ADSL"].inputs == []


def test_a_dataset_in_two_defines_is_refused(tmp_path):
    from fleet.core import build_dag

    one = _define(tmp_path / "a.yaml", [{"name": "ADSL"}])
    two = _define(tmp_path / "b.yaml", [{"name": "ADSL"}])
    with pytest.raises(ValueError, match="declared in .*a.yaml and in .*b.yaml"):
        build_dag(one, two)


def test_a_repeated_input_is_one_edge_and_a_raw_name_clash_is_refused(tmp_path):
    from fleet.core import build_dag

    spec = _define(
        tmp_path / "define.yaml",
        [
            {"name": "ADSL"},
            {"name": "ADAE", "inputs": [{"name": "ADSL"}, {"name": "ADSL"}]},
        ],
    )
    assert build_dag(spec).nodes["ADAE"].inputs == ["ADSL"]
    clash = _define(
        tmp_path / "clash.yaml",
        [{"name": "ADAE", "inputs": [{"name": "ADAE", "type": "raw", "path": "x.csv"}]}],
    )
    with pytest.raises(ValueError, match="has the name of a dataset"):
        build_dag(clash)


def test_a_cycle_error_names_its_nodes():
    from fleet.core.dag import PipelineDAG, PipelineNode

    dag = PipelineDAG(
        nodes={
            "A": PipelineNode(name="A", node_type="adam", path=None, inputs=["B"]),
            "B": PipelineNode(name="B", node_type="adam", path=None, inputs=["A"]),
        }
    )
    with pytest.raises(ValueError, match=r"\['A', 'B'\]"):
        dag.execution_order()


# ── c1-757 c1-758 spec_source ────────────────────────────────────────────


def _adsl_spec(tmp_path: Path, study: dict) -> Path:
    spec = tmp_path / "define.yaml"
    spec.write_text(
        yaml.safe_dump(
            {
                "study": study,
                "datasets": [
                    {
                        "name": "ADSL",
                        "label": "Subject-Level Analysis Dataset",
                        "inputs": [{"name": "DM"}],
                        "variables": [
                            {
                                "name": "TRTSDT",
                                "derivation": {
                                    "algorithm": "first_date",
                                    "from_dataset": "EX",
                                    "date_col": "EXSTDTC",
                                },
                            },
                            {"name": "AGEGR3", "derivation": {"callable": "mymod.agegr3"}},
                        ],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return spec


def test_program_from_spec_keeps_the_label_the_callable_and_passes_the_frame(tmp_path):
    from fleet.core.spec_source import program_from_spec

    code = program_from_spec(_adsl_spec(tmp_path, {"standard": "ADAMIG"}), "ADSL")
    assert code.startswith("# ADSL — Subject-Level Analysis Dataset")
    assert "from mymod import agegr3" in code
    assert "    .derivation(agegr3)" in code
    assert "from_dataset=ex," in code


def test_program_from_spec_runs_and_matches_from_spec(tmp_path):
    from fleet.core.spec_source import program_from_spec

    spec = tmp_path / "define.yaml"
    spec.write_text(
        yaml.safe_dump(
            {
                "study": {"standard": "ADAMIG"},
                "datasets": [
                    {
                        "name": "ADSL",
                        "inputs": [{"name": "DM"}],
                        "variables": [
                            {
                                "name": "TRTSDT",
                                "derivation": {
                                    "algorithm": "first_date",
                                    "from_dataset": "EX",
                                    "date_col": "EXSTDTC",
                                },
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    dm = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ A       │
└─────────┘
""")
    ex = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ EXSTDTC    │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ A       ┆ 2024-01-03 │
│ A       ┆ 2024-01-02 │
└─────────┴────────────┘
""")
    code = program_from_spec(spec, "ADSL")
    body = code[code.index("adsl = (") :]
    scope: dict = {"dm": dm, "ex": ex, "fleet": fleet, "pl": pl}
    exec(body, scope)  # noqa: S102 — the generated program, with frames in place of the loads
    expected = dm.adam.adsl.pin("EX", ex).from_spec(spec, dataset="ADSL").to_frame()
    assert scope["adsl"].equals(expected)


def test_program_from_spec_refuses_a_spec_with_no_standard(tmp_path):
    from fleet.core.spec_source import program_from_spec

    with pytest.raises(ValueError, match="study.standard is not given"):
        program_from_spec(_adsl_spec(tmp_path, {"id": "X"}), "ADSL")


def test_derivations_from_source_keeps_joins_filters_and_reshapes():
    from fleet.core.spec_source import derivations_from_source

    source = (
        "out = (raw.adam.pin('ADSL', adsl).merge(adsl, on='USUBJID')"
        ".whereclauses(where='x').pick(['A', 'B'], order_by=['ADT'])"
        ".assign('aval_raw', source='x').trail().to_frame())"
    )
    rows = derivations_from_source(source)
    assert [(r["verb"], r["name"]) for r in rows] == [
        ("merge", ""),
        ("whereclauses", ""),
        ("pick", ""),
        ("assign", ""),
    ]
    assert {r["status"] for r in rows} == {"stub"}


# ── c1-543 fleet check compares config and define, and names a pinned engine ──


def test_find_engine_returns_a_pinned_path_that_does_not_exist(tmp_path):
    from fleet.validation.engine import find_engine

    pinned = tmp_path / "nonexistent" / "core"
    assert find_engine(pinned, environ={}) == (pinned, "study config")


def test_config_and_define_disagreement_is_a_fail_row(tmp_path):
    from fleet.cli import _config_vs_define_rows
    from fleet.core.study_context import SDTMConfig, StudyContext

    ctx = StudyContext.init(tmp_path, study_id="S1", sdtm=SDTMConfig(ig_version="3-4"))
    define = tmp_path / "define.yaml"
    define.write_text(
        yaml.safe_dump({"study": {"id": "S2", "standard": "ADAMIG", "standard_version": "3.2"}}),
        encoding="utf-8",
    )
    rows = _config_vs_define_rows(ctx, "define (sdtm)", define)
    details = " | ".join(detail for _, _, detail in rows)
    assert {status for status, _, _ in rows} == {"FAIL"}
    assert "standard ADAMIG" in details
    assert "sdtm.ig_version 3-4, define standard_version 3.2" in details
    assert "study_id S1, define study.id S2" in details
