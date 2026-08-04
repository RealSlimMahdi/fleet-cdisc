"""Round-trip tests: inline pipeline → ``to_spec_yaml()`` → ``from_spec()``.

Covers the §4.3 code→spec path:

* the emitted YAML validates against the generated define-spec JSON schema;
* registry-covered verbs emit real ``derivation:`` blocks that re-execute
  to the same frame via ``from_spec()``;
* non-expressible verbs emit ``algorithm: callable`` stubs with a
  ``# TODO`` comment carrying the verb name and sources;
* spec-driven pipelines round-trip their validated blocks verbatim;
* re-derived targets dedupe last-write-wins.

Coverage measured on the CDISCPILOT01 DM pipeline (mirroring
``examples/cdiscpilot01_inline.py`` — the examples themselves are not
imported): 15 of 17 derived variables emit real blocks (~88%, above the
80% DX target); the two stubs are SITEID (string ``derivation`` has no
SDTM spec algorithm) and ARMCD (``if_then_else`` with inline Polars
expressions).
"""

from __future__ import annotations

import warnings

import jsonschema
import polars as pl
import pytest
import yaml

import fleet  # noqa: F401 — registers namespaces


def _schema() -> dict:
    from fleet.define_xml.schema_builder import build_schema

    return build_schema()


@pytest.fixture
def dm_pipeline(dm_raw: pl.DataFrame):
    """Inline CDISCPILOT01 DM pipeline (mirrors the shipped example)."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ns = (
            dm_raw.sdtm.assign("STUDYID", value="CDISCPILOT01")
            .assign("DOMAIN", value="DM")
            .assign("USUBJID", source="patient_number")
            .assign("SUBJID", source="patient_number")
            .derivation("SITEID", expression="pl.col('site_id').cast(pl.String)")
            .assign("AGE", source="age")
            .assign("AGEU", value="YEARS")
            .assign("SEX", source="sex", ct="C66731", ct_map={"F": "F", "M": "M"})
            .assign(
                "RACE",
                source="race",
                ct="C74457",
                ct_map={
                    "WHITE": "WHITE",
                    "BLACK OR AFRICAN AMERICAN": "BLACK OR AFRICAN AMERICAN",
                },
            )
            .assign(
                "ETHNIC",
                source="ethnic",
                ct="C66790",
                ct_map={
                    "HISPANIC OR LATINO": "HISPANIC OR LATINO",
                    "NOT HISPANIC OR LATINO": "NOT HISPANIC OR LATINO",
                },
            )
            .case_when(
                "ARMCD",
                when=[
                    {"condition": pl.col("arm_code") == "Pbo", "value": "PBO"},
                    {"condition": pl.col("arm_code") == "Xan_Lo", "value": "XAN_LO"},
                    {"condition": pl.col("arm_code") == "Xan_Hi", "value": "XAN_HI"},
                ],
                else_="SCRNFAIL",
            )
            .assign("ARM", source="arm_description")
            .assign("ACTARMCD", source="arm_code")
            .assign("ACTARM", source="arm_description")
            .date("RFSTDTC", source="first_dose_date")
            .date("RFENDTC", source="last_dose_date")
            .date("RFICDTC", source="informed_consent_date")
        )
    return ns


class TestDMRoundTrip:
    #: The two DM variables that cannot be expressed in a spec today.
    STUBS = {"SITEID", "ARMCD"}

    def test_output_validates_against_generated_schema(self, dm_pipeline):
        data = yaml.safe_load(dm_pipeline.to_spec_yaml(dataset="DM"))
        jsonschema.Draft202012Validator(_schema()).validate(data)

    def test_round_trip_reproduces_frame(self, dm_pipeline, dm_raw, tmp_path):
        spec_path = tmp_path / "define_dm.yaml"
        dm_pipeline.to_spec_yaml(dataset="DM", path=spec_path)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            redo = dm_raw.sdtm.from_spec(
                spec_path, dataset="DM", omit=sorted(self.STUBS)
            ).to_frame()
        original = dm_pipeline.to_frame()

        clean = [n.name for n in dm_pipeline._lineage if n.name not in self.STUBS]
        assert redo.select(clean).equals(original.select(clean))

    def test_coverage_at_least_80_percent(self, dm_pipeline):
        data = yaml.safe_load(dm_pipeline.to_spec_yaml(dataset="DM"))
        variables = data["datasets"][0]["variables"]
        derived = [v for v in variables if "derivation" in v]
        real = [v for v in derived if v["derivation"].get("algorithm") != "callable"]
        stubs = {v["name"] for v in derived if v["derivation"].get("algorithm") == "callable"}
        assert stubs == self.STUBS
        assert len(real) / len(derived) >= 0.80

    def test_stub_comment_carries_verb_and_sources(self, dm_pipeline):
        text = dm_pipeline.to_spec_yaml(dataset="DM")
        assert "# TODO: verb 'case_when' (sources: arm_code)" in text
        assert "# TODO: verb 'derivation' (sources: site_id)" in text

    def test_emitted_blocks_use_registry_spellings(self, dm_pipeline):
        data = yaml.safe_load(dm_pipeline.to_spec_yaml(dataset="DM"))
        by_name = {v["name"]: v.get("derivation") for v in data["datasets"][0]["variables"]}
        assert by_name["STUDYID"] == {"algorithm": "hardcode_no_ct", "value": "CDISCPILOT01"}
        assert by_name["USUBJID"] == {"algorithm": "assign_no_ct", "source": "patient_number"}
        assert by_name["SEX"] == {
            "algorithm": "assign_ct",
            "source": "sex",
            "ct_codelist": "C66731",
            "ct_mapping": {"F": "F", "M": "M"},
        }
        assert by_name["RFSTDTC"] == {"algorithm": "date", "source": "first_dose_date"}

    def test_path_argument_writes_file(self, dm_pipeline, tmp_path):
        dest = tmp_path / "specs" / "define_dm.yaml"
        text = dm_pipeline.to_spec_yaml(dataset="DM", path=dest)
        assert dest.read_text(encoding="utf-8") == text


class TestSpecDrivenRoundTrip:
    """from_spec pipelines re-emit their validated blocks verbatim."""

    def test_blocks_round_trip_verbatim(self, tmp_path):
        spec = {
            "datasets": [
                {
                    "name": "ADVS",
                    "variables": [
                        {
                            "name": "ADY",
                            "derivation": {
                                "algorithm": "study_day",
                                "analysis_date": "ADT",
                                "reference_date": "TRTSDT",
                            },
                        },
                        {
                            "name": "CHG",
                            "derivation": {"algorithm": "chg", "aval": "AVAL", "base": "BASE"},
                        },
                    ],
                }
            ]
        }
        p = tmp_path / "define.yaml"
        p.write_text(yaml.safe_dump(spec))
        df = pl.from_repr("""\
┌─────────┬────────────┬────────────┬──────┬──────┐
│ USUBJID ┆ ADT        ┆ TRTSDT     ┆ AVAL ┆ BASE │
│ ---     ┆ ---        ┆ ---        ┆ ---  ┆ ---  │
│ str     ┆ str        ┆ str        ┆ f64  ┆ f64  │
╞═════════╪════════════╪════════════╪══════╪══════╡
│ S1      ┆ 2024-01-10 ┆ 2024-01-01 ┆ 7    ┆ 5    │
└─────────┴────────────┴────────────┴──────┴──────┘
""")
        ns = df.adam.from_spec(p, dataset="ADVS")
        data = yaml.safe_load(ns.to_spec_yaml(dataset="ADVS"))
        by_name = {v["name"]: v.get("derivation") for v in data["datasets"][0]["variables"]}
        assert by_name["ADY"] == {
            "algorithm": "study_day",
            "analysis_date": "ADT",
            "reference_date": "TRTSDT",
        }
        assert by_name["CHG"] == {"algorithm": "chg", "aval": "AVAL", "base": "BASE"}

    def test_registered_derivation_round_trips_as_callable(self):
        from fleet.core.derivation import derivation

        @derivation
        def RTCOL() -> pl.Expr:
            """Round-trip fixture column."""
            return pl.lit("Y").alias("RTCOL")

        df = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ S1      │
└─────────┘
""")
        ns = df.adam.derivation(RTCOL)
        data = yaml.safe_load(ns.to_spec_yaml(dataset="ADSL"))
        (var,) = [v for v in data["datasets"][0]["variables"] if v["name"] == "RTCOL"]
        assert var["derivation"]["algorithm"] == "callable"
        assert var["derivation"]["callable"].endswith("RTCOL")


class TestAdamInlineRoundTrip:
    def test_frame_capture_covers_bds_verbs(self, tmp_path):
        """date/duration/flag/baseline/chg/pchg emit real blocks from inline code."""
        vs = pl.from_repr("""\
┌─────────┬─────────┬──────┬──────┬────────────┬────────────┐
│ USUBJID ┆ PARAMCD ┆ AVAL ┆ vsdy ┆ vsdtc      ┆ TRTSDT     │
│ ---     ┆ ---     ┆ ---  ┆ ---  ┆ ---        ┆ ---        │
│ str     ┆ str     ┆ f64  ┆ i64  ┆ str        ┆ str        │
╞═════════╪═════════╪══════╪══════╪════════════╪════════════╡
│ S1      ┆ SYSBP   ┆ 120  ┆ -1   ┆ 2024-01-01 ┆ 2024-01-02 │
│ S1      ┆ SYSBP   ┆ 132  ┆ 10   ┆ 2024-01-12 ┆ 2024-01-02 │
└─────────┴─────────┴──────┴──────┴────────────┴────────────┘
""")
        ns = (
            vs.adam.date("ADT", source="vsdtc")
            .duration("ADY", start="TRTSDT", end="ADT")
            .flag("ABLFL", criteria="pl.col('vsdy') <= 0", by=["USUBJID", "PARAMCD"])
            .baseline("BASE", aval="AVAL", baseline_flag="ABLFL", by=["USUBJID", "PARAMCD"])
            .chg("CHG")
            .pchg("PCHG")
        )
        text = ns.to_spec_yaml(dataset="ADVS")
        data = yaml.safe_load(text)
        jsonschema.Draft202012Validator(_schema()).validate(data)
        by_name = {v["name"]: v.get("derivation") for v in data["datasets"][0]["variables"]}

        assert by_name["ADT"] == {"algorithm": "date", "source": "vsdtc"}
        assert by_name["ADY"] == {
            "algorithm": "duration",
            "start": "TRTSDT",
            "end": "ADT",
        }
        assert by_name["ABLFL"] == {
            "algorithm": "flag",
            "criteria": "pl.col('vsdy') <= 0",
            "groups": ["USUBJID", "PARAMCD"],
        }
        assert by_name["BASE"] == {
            "algorithm": "baseline",
            "groups": ["USUBJID", "PARAMCD"],
        }
        assert by_name["CHG"] == {"algorithm": "chg"}
        assert by_name["PCHG"] == {"algorithm": "pchg"}
        # ADTF is the date verb's auto-generated by-product: listed, no block.
        assert "ADTF" in by_name and by_name["ADTF"] is None

        # Re-execute and compare.
        p = tmp_path / "define_advs.yaml"
        p.write_text(text, encoding="utf-8")
        redo = vs.adam.from_spec(p, dataset="ADVS").to_frame()
        original = ns.to_frame()
        cols = ["ADT", "ADY", "ABLFL", "BASE", "CHG", "PCHG"]
        assert redo.select(cols).equals(original.select(cols))


class TestDedupAndEdgeCases:
    def test_last_write_wins_on_rederived_target(self, tmp_path):
        df = pl.from_repr("""\
┌─────────┬─────┬─────┐
│ USUBJID ┆ a   ┆ b   │
│ ---     ┆ --- ┆ --- │
│ str     ┆ str ┆ str │
╞═════════╪═════╪═════╡
│ S1      ┆ x   ┆ y   │
└─────────┴─────┴─────┘
""")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ns = df.sdtm.assign("COL", source="a").assign("COL", source="b")
        data = yaml.safe_load(ns.to_spec_yaml(dataset="DM"))
        cols = [v for v in data["datasets"][0]["variables"] if v["name"] == "COL"]
        assert len(cols) == 1
        assert cols[0]["derivation"] == {"algorithm": "assign_no_ct", "source": "b"}

    def test_dropped_columns_are_not_emitted(self):
        df = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ a   │
│ ---     ┆ --- │
│ str     ┆ str │
╞═════════╪═════╡
│ S1      ┆ x   │
└─────────┴─────┘
""")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ns = df.sdtm.assign("TMP", source="a").keep("USUBJID")
        data = yaml.safe_load(ns.to_spec_yaml(dataset="DM"))
        names = [v["name"] for v in data["datasets"][0]["variables"]]
        assert "TMP" not in names

    def test_empty_pipeline_still_valid(self):
        df = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ AGE │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ S1      ┆ 64  │
└─────────┴─────┘
""")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ns = df.sdtm.assign("SUBJID", source="USUBJID")
        data = yaml.safe_load(ns.to_spec_yaml())
        jsonschema.Draft202012Validator(_schema()).validate(data)
        assert data["datasets"][0]["name"] == "DATASET"


@pytest.fixture(autouse=True)
def _clean_registry():
    yield
    from fleet.adam.transforms import clear_transforms
    clear_transforms()


class TestDerivationCallableRoundTrip:
    """A @derivation round-trips: inline → callable: block → from_spec() → equal frame."""

    def test_callable_block_emitted_verbatim(self):
        """to_spec_yaml() sets algorithm:callable for a @derivation object."""
        from fleet.core.derivation import derivation

        @derivation
        def AGEGR1_rt() -> pl.Expr:
            """Classify age into two groups for round-trip test.

            Assigns '<65' for subjects under 65, '>=65' otherwise.
            """
            return (
                pl.when(pl.col("AGE") < 65)
                .then(pl.lit("<65"))
                .otherwise(pl.lit(">=65"))
                .alias("AGEGR1_rt")
            )

        df = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ AGE │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ S1      ┆ 52  │
│ S2      ┆ 68  │
└─────────┴─────┘
""")
        ns = df.adam.derivation(AGEGR1_rt)
        data = yaml.safe_load(ns.to_spec_yaml(dataset="ADSL"))
        by_name = {v["name"]: v.get("derivation")
                   for v in data["datasets"][0]["variables"]}

        assert by_name["AGEGR1_rt"]["algorithm"] == "callable"
        assert by_name["AGEGR1_rt"]["callable"].endswith("AGEGR1_rt")

    def test_full_round_trip_produces_equal_frame(self, tmp_path):
        """from_spec() re-executing a callable: block yields the same data."""
        from fleet.core.derivation import derivation

        @derivation
        def AGEGR1_rt2() -> pl.Expr:
            """Two-group age classification for round-trip equality test."""
            return (
                pl.when(pl.col("AGE") < 65)
                .then(pl.lit("<65"))
                .otherwise(pl.lit(">=65"))
                .alias("AGEGR1_rt2")
            )

        df = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ AGE │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ S1      ┆ 52  │
│ S2      ┆ 68  │
└─────────┴─────┘
""")
        ns = df.adam.assign("AGE", source="AGE").derivation(AGEGR1_rt2)
        # The dotted_path for a locally-scoped function includes the enclosing
        # class and method in __qualname__, making it non-importable.  Override
        # node.spec to use the short registered name so resolve_callable() takes
        # the registry-lookup path instead of the import-path branch.
        for node in ns._lineage:
            if node.name == "AGEGR1_rt2":
                node.spec["callable"] = AGEGR1_rt2.name

        spec_path = tmp_path / "define_rt.yaml"
        ns.to_spec_yaml(dataset="ADSL", path=spec_path)

        redo = df.adam.from_spec(spec_path, dataset="ADSL").to_frame()
        original = ns.to_frame()

        assert redo["AGEGR1_rt2"].equals(original["AGEGR1_rt2"])

    def test_methoddef_description_matches_docstring(self, tmp_path):
        """The @derivation docstring's first sentence appears in MethodDef Description."""
        from fleet.core.derivation import derivation
        from fleet.define_xml.spec_generator import DefineSpecGenerator

        @derivation
        def BMIGRP() -> pl.Expr:
            """Classify BMI into WHO standard groups for Define-XML method test.

            Assigns 'Underweight' below 18.5, 'Normal' 18.5-24.9,
            'Overweight' 25-29.9, and 'Obese' 30 or above.
            """
            return (
                pl.when(pl.col("BMI") < 18.5).then(pl.lit("Underweight"))
                .when(pl.col("BMI") < 25.0).then(pl.lit("Normal"))
                .when(pl.col("BMI") < 30.0).then(pl.lit("Overweight"))
                .otherwise(pl.lit("Obese"))
                .alias("BMIGRP")
            )

        spec = {
            "fleet_spec_version": 1,
            "study": {
                "id": "TEST01",
                "name": "Test Study",
                "description": "Unit test for MethodDef docstring flow.",
                "protocol_name": "TEST01",
                "originator": "Fleet",
                "standard": "ADAMIG",
                "standard_version": "1.3",
            },
            "datasets": [{
                "name": "ADSL",
                "label": "Subject Level",
                "structure": "One record per subject",
                "repeating": False,
                "keys": ["USUBJID"],
                "variables": [
                    {"name": "USUBJID", "label": "Subject ID",
                     "type": "text",  "origin": "Collected"},
                    {"name": "BMIGRP", "label": "BMI Group",
                     "type": "text",  "origin": "Derived",
                     "derivation": {"algorithm": "callable", "callable": "BMIGRP"}},
                ],
            }],
        }
        define_path = tmp_path / "define_bmi.yaml"
        define_path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")

        gen = DefineSpecGenerator(
            define_path, validate_xml=False, enrich_methods=True
        )
        xml_text = gen.to_xml_string()

        assert "Classify BMI into WHO standard groups" in xml_text
        assert "BMIGRP" in xml_text
