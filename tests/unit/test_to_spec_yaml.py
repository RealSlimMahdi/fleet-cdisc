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
            dm_raw.sdtm.hardcode_no_ct("STUDYID", value="CDISCPILOT01")
            .hardcode_no_ct("DOMAIN", value="DM")
            .assign_no_ct("USUBJID", source="patient_number")
            .assign_no_ct("SUBJID", source="patient_number")
            .derivation("SITEID", expression="pl.col('site_id').cast(pl.String)")
            .assign_no_ct("AGE", source="age")
            .hardcode_no_ct("AGEU", value="YEARS")
            .assign_ct("SEX", source="sex", ct_codelist="C66731", ct_mapping={"F": "F", "M": "M"})
            .assign_ct(
                "RACE",
                source="race",
                ct_codelist="C74457",
                ct_mapping={
                    "WHITE": "WHITE",
                    "BLACK OR AFRICAN AMERICAN": "BLACK OR AFRICAN AMERICAN",
                },
            )
            .assign_ct(
                "ETHNIC",
                source="ethnic",
                ct_codelist="C66790",
                ct_mapping={
                    "HISPANIC OR LATINO": "HISPANIC OR LATINO",
                    "NOT HISPANIC OR LATINO": "NOT HISPANIC OR LATINO",
                },
            )
            .if_then_else(
                "ARMCD",
                when=[
                    {"condition": pl.col("arm_code") == "Pbo", "value": "PBO"},
                    {"condition": pl.col("arm_code") == "Xan_Lo", "value": "XAN_LO"},
                    {"condition": pl.col("arm_code") == "Xan_Hi", "value": "XAN_HI"},
                ],
                else_value="SCRNFAIL",
            )
            .assign_no_ct("ARM", source="arm_description")
            .assign_no_ct("ACTARMCD", source="arm_code")
            .assign_no_ct("ACTARM", source="arm_description")
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
        assert "# TODO: verb 'if_then_else' (sources: arm_code)" in text
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
        df = pl.DataFrame(
            {
                "USUBJID": ["S1"],
                "ADT": ["2024-01-10"],
                "TRTSDT": ["2024-01-01"],
                "AVAL": [7.0],
                "BASE": [5.0],
            }
        )
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

        df = pl.DataFrame({"USUBJID": ["S1"]})
        ns = df.adam.derivation(RTCOL)
        data = yaml.safe_load(ns.to_spec_yaml(dataset="ADSL"))
        (var,) = [v for v in data["datasets"][0]["variables"] if v["name"] == "RTCOL"]
        assert var["derivation"]["algorithm"] == "callable"
        assert var["derivation"]["callable"].endswith("RTCOL")


class TestAdamInlineRoundTrip:
    def test_frame_capture_covers_bds_verbs(self, tmp_path):
        """date/duration/flag/baseline/chg/pchg emit real blocks from inline code."""
        vs = pl.DataFrame(
            {
                "USUBJID": ["S1", "S1"],
                "PARAMCD": ["SYSBP", "SYSBP"],
                "AVAL": [120.0, 132.0],
                "vsdy": [-1, 10],
                "vsdtc": ["2024-01-01", "2024-01-12"],
                "TRTSDT": ["2024-01-02", "2024-01-02"],
            }
        )
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
        p.write_text(text)
        redo = vs.adam.from_spec(p, dataset="ADVS").to_frame()
        original = ns.to_frame()
        cols = ["ADT", "ADY", "ABLFL", "BASE", "CHG", "PCHG"]
        assert redo.select(cols).equals(original.select(cols))


class TestDedupAndEdgeCases:
    def test_last_write_wins_on_rederived_target(self, tmp_path):
        df = pl.DataFrame({"USUBJID": ["S1"], "a": ["x"], "b": ["y"]})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ns = df.sdtm.assign_no_ct("COL", source="a").assign_no_ct("COL", source="b")
        data = yaml.safe_load(ns.to_spec_yaml(dataset="DM"))
        cols = [v for v in data["datasets"][0]["variables"] if v["name"] == "COL"]
        assert len(cols) == 1
        assert cols[0]["derivation"] == {"algorithm": "assign_no_ct", "source": "b"}

    def test_dropped_columns_are_not_emitted(self):
        df = pl.DataFrame({"USUBJID": ["S1"], "a": ["x"]})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ns = df.sdtm.assign_no_ct("TMP", source="a").keep("USUBJID")
        data = yaml.safe_load(ns.to_spec_yaml(dataset="DM"))
        names = [v["name"] for v in data["datasets"][0]["variables"]]
        assert "TMP" not in names

    def test_empty_pipeline_still_valid(self):
        df = pl.DataFrame({"USUBJID": ["S1"], "AGE": [64]})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            ns = df.sdtm.assign_no_ct("SUBJID", source="USUBJID")
        data = yaml.safe_load(ns.to_spec_yaml())
        jsonschema.Draft202012Validator(_schema()).validate(data)
        assert data["datasets"][0]["name"] == "DATASET"
