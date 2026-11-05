"""YAML-as-workflow, open registry, and builder-contract tests.

Covers the DX-review §3.1/§3.2 commitments: a YAML file alone reproduces
a table (``load_spec`` → ``run_spec``), the template registry is open to
user registrations, filter strings fail at spec construction naming the
field, ``columns`` is honest about single-column grouping, builder state
the target template won't consume raises instead of vanishing, and the
root ``df.tlg`` namespace routes ``catalog()``/``check()`` correctly.
"""

from __future__ import annotations

import sys
from pathlib import Path

import polars as pl
import pytest
from pydantic import ValidationError

import fleet  # noqa: F401 — registers df.tlg
from fleet.core.exceptions import SchemaError
from fleet.tlg import (
    TEMPLATES,
    AEListingSpec,
    AEOverviewSpec,
    AESummarySpec,
    CDISCClass,
    OutputType,
    OverallStat,
    Status,
    TemplateMeta,
    catalog,
    load_spec,
    register_template,
    run_spec,
    spec_schema,
    unregister_template,
)

sys.path.insert(0, str(Path(__file__).parent.parent))
from fixtures.study import ADAE, ADLB, ADSL, FRAMES  # noqa: E402

SPEC_DIR = Path(__file__).parent.parent.parent / "examples" / "tlg_specs"

#: Example spec file → fixture frame it runs on.
EXAMPLE_SPECS = {
    "aet01.yaml": "ADAE",
    "vst01.yaml": "ADVS",
    "lbt02.yaml": "ADLB",
}


# ================================================================== #
# load_spec / run_spec — the YAML file is the workflow                 #
# ================================================================== #


class TestLoadSpec:
    @pytest.mark.parametrize("filename", sorted(EXAMPLE_SPECS))
    def test_example_specs_load_and_run(self, filename: str) -> None:
        """Every shipped example spec loads, dispatches, and computes."""
        spec = load_spec(SPEC_DIR / filename)
        assert spec.template is not None
        assert spec.schema_version == 1
        out = run_spec(spec, FRAMES[EXAMPLE_SPECS[filename]], adsl=ADSL)
        assert isinstance(out, pl.DataFrame)
        assert out.height > 0

    def test_resolves_concrete_spec_class(self) -> None:
        spec = load_spec(SPEC_DIR / "aet01.yaml")
        assert isinstance(spec, AEOverviewSpec)

    def test_missing_file_names_path(self) -> None:
        with pytest.raises(SchemaError, match="no_such.yaml"):
            load_spec(SPEC_DIR / "no_such.yaml")

    def test_invalid_yaml_names_path(self, tmp_path: Path) -> None:
        p = tmp_path / "broken.yaml"
        p.write_text("template: aet01\nrows: [", encoding="utf-8")
        with pytest.raises(SchemaError, match="broken.yaml.*invalid YAML"):
            load_spec(p)

    def test_missing_template_key_names_path(self, tmp_path: Path) -> None:
        p = tmp_path / "anon.yaml"
        p.write_text("rows: []", encoding="utf-8")
        with pytest.raises(SchemaError, match="anon.yaml.*missing 'template:'"):
            load_spec(p)

    def test_unknown_template_names_path(self, tmp_path: Path) -> None:
        p = tmp_path / "typo.yaml"
        p.write_text("template: aet99", encoding="utf-8")
        with pytest.raises(SchemaError, match="typo.yaml.*unknown template"):
            load_spec(p)

    def test_invalid_field_names_path_and_class(self, tmp_path: Path) -> None:
        p = tmp_path / "badfield.yaml"
        p.write_text("template: aet01\nbogus: 1", encoding="utf-8")
        with pytest.raises(SchemaError, match="badfield.yaml.*AEOverviewSpec"):
            load_spec(p)

    def test_schema_version_string_form_accepted(self, tmp_path: Path) -> None:
        p = tmp_path / "strver.yaml"
        p.write_text('template: aet02\nschema_version: "1"', encoding="utf-8")
        assert load_spec(p).schema_version == 1

    def test_unknown_schema_version_rejected(self, tmp_path: Path) -> None:
        p = tmp_path / "badver.yaml"
        p.write_text("template: aet02\nschema_version: 2", encoding="utf-8")
        with pytest.raises(SchemaError, match="badver.yaml"):
            load_spec(p)


class TestRunSpec:
    def test_requires_template_id(self) -> None:
        with pytest.raises(SchemaError, match="spec.template"):
            run_spec(AESummarySpec(), ADAE, adsl=ADSL)

    def test_rejects_spec_class_mismatch(self) -> None:
        spec = AESummarySpec(template="vst01")
        with pytest.raises(SchemaError, match="VSSummarySpec"):
            run_spec(spec, ADAE, adsl=ADSL)

    def test_matches_direct_method_call(self) -> None:
        spec = load_spec(SPEC_DIR / "lbt02.yaml")
        via_runner = run_spec(spec, ADLB, adsl=ADSL, groupby="TRTA")
        direct = ADLB.tlg.lb.t_chg(groupby="TRTA", adsl=ADSL, spec=spec)
        assert via_runner.equals(direct)

    def test_dispatches_listing_templates(self) -> None:
        spec = AEListingSpec(template="ael01")
        listing = run_spec(spec, ADAE)
        assert listing.equals(ADAE.tlg.ae.l_listing(spec=spec))


class TestYamlRoundTrip:
    def test_to_yaml_carries_template_and_version(self) -> None:
        spec = AESummarySpec(template="aet02")
        yaml_str = spec.to_yaml()
        assert "template: aet02" in yaml_str
        assert "schema_version: 1" in yaml_str
        restored = AESummarySpec.from_yaml(yaml_str)
        assert restored.template == "aet02"
        assert restored.schema_version == 1

    def test_specs_without_new_keys_still_validate(self) -> None:
        """Back-compat: pre-existing YAML without template/schema_version."""
        restored = AESummarySpec.from_yaml("rows:\n  - field: AEBODSYS\n")
        assert restored.template is None
        assert restored.schema_version == 1

    def test_builder_template_id_lands_in_spec(self) -> None:
        spec = ADAE.tlg.ae.population(ADSL).by("TRTA").template("aet02").to_spec()
        assert spec.template == "aet02"


def test_spec_schema_export() -> None:
    schema = spec_schema("aet01")
    assert schema["title"] == "AEOverviewSpec"
    assert "header_rows" in schema["properties"]
    with pytest.raises(SchemaError, match="Unknown template"):
        spec_schema("nope01")


# ================================================================== #
# Open registry                                                        #
# ================================================================== #


def _sponsor_meta(template_id: str = "spon01") -> TemplateMeta:
    return TemplateMeta(
        id=template_id,
        title="Sponsor AE Shell",
        cdisc_class=CDISCClass.EVENTS,
        namespace="ae",
        method="sponsor_fn",
        output_type=OutputType.TABLE,
        domains=("ADSL", "ADAE"),
        source_ref="sponsor",
        status=Status.DONE,
    )


def _sponsor_fn(df, *, adsl, spec, groupby):
    return df.tlg.ae.t_summary(groupby=groupby, adsl=adsl)


class TestOpenRegistry:
    def test_register_run_and_unregister(self) -> None:
        register_template(_sponsor_meta(), _sponsor_fn)
        try:
            assert "spon01" in catalog()["id"].to_list()
            inline = ADAE.tlg.ae.population(ADSL).by("TRTA").template("spon01").to_ard()
            direct = ADAE.tlg.ae.t_summary(groupby="TRTA", adsl=ADSL)
            assert inline.equals(direct)
        finally:
            unregister_template("spon01")
        assert "spon01" not in TEMPLATES

    def test_run_spec_dispatches_user_template(self, tmp_path: Path) -> None:
        register_template(_sponsor_meta("spon02"), _sponsor_fn)
        try:
            p = tmp_path / "spon02.yaml"
            p.write_text("template: spon02\n", encoding="utf-8")
            spec = load_spec(p)
            out = run_spec(spec, ADAE, adsl=ADSL, groupby="TRTA")
            assert out.equals(ADAE.tlg.ae.t_summary(groupby="TRTA", adsl=ADSL))
        finally:
            unregister_template("spon02")

    def test_duplicate_id_raises(self) -> None:
        with pytest.raises(SchemaError, match="already registered"):
            register_template(_sponsor_meta("aet01"), _sponsor_fn)

    def test_unregister_builtin_raises(self) -> None:
        with pytest.raises(SchemaError, match="built-in"):
            unregister_template("aet01")

    def test_non_callable_raises(self) -> None:
        with pytest.raises(SchemaError, match="callable"):
            register_template(_sponsor_meta("spon03"), "not a function")  # type: ignore[arg-type]


# ================================================================== #
# Construction-time contracts                                          #
# ================================================================== #


class TestFilterValidationAtConstruction:
    def test_bad_adsl_filter_names_field(self) -> None:
        with pytest.raises(ValidationError, match="adsl_filter"):
            AESummarySpec(adsl_filter='pl.col("SAFFL" ==')

    def test_bad_dataset_filter_names_field(self) -> None:
        with pytest.raises(ValidationError, match="dataset_filter"):
            AESummarySpec(dataset_filter="__import__('os')")

    def test_bad_header_row_filter_names_field(self) -> None:
        with pytest.raises(ValidationError, match="filter"):
            OverallStat(label="Serious", filter="pl.col(")

    def test_wrong_type_rejected(self) -> None:
        with pytest.raises(ValidationError, match="dataset_filter"):
            AESummarySpec(dataset_filter=42)

    def test_valid_forms_still_pass(self) -> None:
        AESummarySpec(dataset_filter='pl.col("TRTEMFL") == "Y"')
        AESummarySpec(dataset_filter=pl.col("TRTEMFL") == "Y")
        AESummarySpec(dataset_filter=None)


class TestColumnsHonesty:
    def test_multi_column_grouping_rejected(self) -> None:
        with pytest.raises(ValidationError, match="exactly one"):
            AESummarySpec(columns=["TRTA", "SEX"])

    def test_empty_columns_rejected(self) -> None:
        with pytest.raises(ValidationError, match="exactly one"):
            AESummarySpec(columns=[])

    def test_builder_by_rejects_list(self) -> None:
        with pytest.raises(SchemaError, match="single treatment-arm column"):
            ADAE.tlg.ae.by(["TRTA", "SEX"])  # type: ignore[arg-type]


class TestUnconsumedBuilderState:
    def test_rows_on_abnormal_raises(self) -> None:
        with pytest.raises(SchemaError, match="rows\\(\\).*t_abnormal"):
            ADLB.tlg.lb.population(ADSL).by("TRTA").template("lbt04").rows(["PARAMCD"]).to_spec()

    def test_value_on_shift_raises(self) -> None:
        with pytest.raises(SchemaError, match="value\\(\\).*t_shift"):
            ADLB.tlg.lb.population(ADSL).by("TRTA").template("lbt03").value("CHG").to_spec()

    def test_header_rows_on_shift_raises(self) -> None:
        with pytest.raises(SchemaError, match="header_rows"):
            (
                ADLB.tlg.lb.population(ADSL)
                .by("TRTA")
                .template("lbt03")
                .header_rows([OverallStat(label="Any abnormal")])
                .to_spec()
            )

    def test_t_shift_method_rejects_header_rows_like_t_abnormal(self) -> None:
        from pydantic import ValidationError

        from fleet.tlg import LBShiftSpec

        # c1-465: the spec refuses the unused field at construction.
        with pytest.raises(ValidationError, match="header_rows"):
            LBShiftSpec(header_rows=[OverallStat(label="Any")])

    def test_template_after_row_verbs_warns(self) -> None:
        with pytest.warns(UserWarning, match="reinterpreted"):
            ADLB.tlg.lb.population(ADSL).by("TRTA").rows(["PARAMCD"]).template("lbt02")


# ================================================================== #
# Root namespace routing                                               #
# ================================================================== #


class TestRootNamespace:
    def test_catalog_passthrough(self) -> None:
        assert ADAE.tlg.catalog().equals(catalog())

    def test_check_scopes_to_applicable_namespaces(self) -> None:
        # ADSL satisfies dm/ds required columns and passes their checks.
        assert ADSL.tlg.check() == []

    def test_check_reports_when_nothing_applies(self) -> None:
        df = pl.from_repr("""\
┌─────┐
│ X   │
│ --- │
│ i64 │
╞═════╡
│ 1   │
└─────┘
""")
        report = df.tlg.check()
        assert len(report) == 1
        assert "NO APPLICABLE NAMESPACE" in report[0]
