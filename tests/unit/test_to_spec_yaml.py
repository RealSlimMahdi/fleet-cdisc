"""Round-trip tests: inline pipeline → ``to_spec_yaml()`` → ``from_spec()``.

Covers the §4.3 code→spec path:

* the emitted YAML validates against the generated define-spec JSON schema;
* registry-covered verbs emit real ``derivation:`` blocks that re-execute
  to the same frame via ``from_spec()``;
* non-expressible verbs emit ``algorithm: derivation`` stubs with a
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
    STUBS = {"ARMCD"}  # SITEID is a string-expression derivation: spec-expressible since ADR-0008

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
        is_stub = lambda v: str(v["derivation"].get("callable", "")).startswith("TODO_")  # noqa: E731
        real = [v for v in derived if not is_stub(v)]
        stubs = {v["name"] for v in derived if is_stub(v)}
        assert stubs == self.STUBS
        assert len(real) / len(derived) >= 0.80

    def test_stub_comment_carries_verb_and_sources(self, dm_pipeline):
        text = dm_pipeline.to_spec_yaml(dataset="DM")
        assert "# TODO: verb 'case_when' (sources: arm_code)" in text

    def test_emitted_blocks_use_registry_spellings(self, dm_pipeline):
        data = yaml.safe_load(dm_pipeline.to_spec_yaml(dataset="DM"))
        by_name = {v["name"]: v.get("derivation") for v in data["datasets"][0]["variables"]}
        assert by_name["STUDYID"] == {"algorithm": "assign", "value": "CDISCPILOT01"}
        assert by_name["USUBJID"] == {"algorithm": "assign", "source": "patient_number"}
        assert by_name["SEX"] == {
            "algorithm": "assign",
            "source": "sex",
            "ct": "C66731",
            "ct_map": {"F": "F", "M": "M"},
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
                                "algorithm": "duration",
                                "end": "ADT",
                                "start": "TRTSDT",
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
            "algorithm": "duration",
            "end": "ADT",
            "start": "TRTSDT",
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
        assert var["derivation"]["algorithm"] == "derivation"
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
            "by": ["USUBJID", "PARAMCD"],
        }
        assert by_name["BASE"] == {
            "algorithm": "baseline",
            "by": ["USUBJID", "PARAMCD"],
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
        assert cols[0]["derivation"] == {"algorithm": "assign", "source": "b"}

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


class TestSourceRoundTrip:
    """c1-168, c1-185: source() wrote callable: TODO_<name>, so the frozen file did not run."""

    @pytest.fixture
    def dm(self) -> pl.DataFrame:
        return pl.from_repr("""\
┌─────────┬─────┬─────┐
│ USUBJID ┆ AGE ┆ age │
│ ---     ┆ --- ┆ --- │
│ str     ┆ i64 ┆ i64 │
╞═════════╪═════╪═════╡
│ S1      ┆ 40  ┆ 41  │
└─────────┴─────┴─────┘
""")

    def test_source_freezes_as_assign_and_reruns(self, dm, tmp_path):
        ns = dm.adam.source("USUBJID", "AGE").source("AGE2", from_col="age")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            text = ns.to_spec_yaml(dataset="ADSL", path=tmp_path / "define.yaml")

        assert "TODO_" not in text and "# TODO:" not in text
        assert [str(w.message) for w in caught if "to_spec_yaml" in str(w.message)] == []
        variables = yaml.safe_load(text)["datasets"][0]["variables"]
        blocks = {v["name"]: v.get("derivation") for v in variables}
        assert blocks["USUBJID"] == {"algorithm": "assign"}
        assert blocks["AGE2"] == {"algorithm": "assign", "source": "age"}

        rerun = dm.adam.from_spec(tmp_path / "define.yaml", dataset="ADSL").to_frame()
        inline = ns.to_frame()
        assert rerun.select("USUBJID", "AGE", "AGE2").equals(
            inline.select("USUBJID", "AGE", "AGE2")
        )

    def test_the_readme_advs_chain_stubs_only_study_day(self):
        vs_sdtm = pl.from_repr("""\
┌─────────┬─────────┬───────┬────────────┬────────────┬──────────┐
│ USUBJID ┆ PARAMCD ┆ AVAL  ┆ ADT        ┆ TRTSDT     ┆ VISITNUM │
│ ---     ┆ ---     ┆ ---   ┆ ---        ┆ ---        ┆ ---      │
│ str     ┆ str     ┆ f64   ┆ date       ┆ date       ┆ i64      │
╞═════════╪═════════╪═══════╪════════════╪════════════╪══════════╡
│ 001     ┆ SYSBP   ┆ 120.0 ┆ 2024-01-15 ┆ 2024-01-15 ┆ 1        │
│ 001     ┆ SYSBP   ┆ 115.0 ┆ 2024-02-15 ┆ 2024-01-15 ┆ 2        │
└─────────┴─────────┴───────┴────────────┴────────────┴──────────┘
""")
        chain = (
            vs_sdtm.adam.source("USUBJID", "PARAMCD", "AVAL")
            .study_day("ADY", date_col="ADT", ref_col="TRTSDT")
            .flag("ABLFL", criteria='pl.col("VISITNUM") == 1', by=["USUBJID", "PARAMCD"])
            .baseline("BASE", aval="AVAL", baseline_flag="ABLFL", by=["USUBJID", "PARAMCD"])
            .chg("CHG", aval="AVAL", base="BASE")
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            text = chain.to_spec_yaml(dataset="ADVS")

        assert "TODO_ADY" in text
        for name in ("USUBJID", "PARAMCD", "AVAL"):
            assert f"TODO_{name}" not in text


class TestVerbsThatBypassChainLeaveANode:
    """c1-695: seq, first_date, last_date and count_events wrote no block and no warning."""

    def test_an_ae_chain_with_seq_round_trips_on_all_columns(self, tmp_path):
        raw = pl.from_repr("""\
┌────────────────┬──────────┬───────────────┬─────────────┐
│ patient_number ┆ ae_term  ┆ ae_start_date ┆ ae_severity │
│ ---            ┆ ---      ┆ ---           ┆ ---         │
│ str            ┆ str      ┆ str           ┆ str         │
╞════════════════╪══════════╪═══════════════╪═════════════╡
│ 01-701-1015    ┆ HEADACHE ┆ 2014-01-05    ┆ MILD        │
│ 01-701-1015    ┆ NAUSEA   ┆ 2014-01-03    ┆ MODERATE    │
└────────────────┴──────────┴───────────────┴─────────────┘
""")
        ae_ns = (
            raw.sdtm.assign("STUDYID", value="CDISCPILOT01")
            .assign("USUBJID", source="patient_number")
            .assign("AETERM", source="ae_term")
            .assign("AESTDTC", source="ae_start_date")
            .seq("AESEQ", order_by=["AESTDTC"])
        )
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            text = ae_ns.to_spec_yaml(dataset="AE", path=tmp_path / "define.yaml")

        assert [str(w.message) for w in caught if "to_spec_yaml" in str(w.message)] == []
        variables = yaml.safe_load(text)["datasets"][0]["variables"]
        aeseq = next(v for v in variables if v["name"] == "AESEQ")
        assert aeseq["derivation"]["algorithm"] == "seq"

        inline = ae_ns.to_frame()
        rerun = raw.sdtm.from_spec(tmp_path / "define.yaml", dataset="AE").to_frame()
        cols = [v["name"] for v in variables]
        assert cols == ["STUDYID", "USUBJID", "AETERM", "AESTDTC", "AESEQ"]
        assert rerun.select(cols).sort("AESEQ").equals(inline.select(cols).sort("AESEQ"))
        assert inline.sort("AESEQ")["AETERM"].to_list() == ["NAUSEA", "HEADACHE"]

    def test_date_and_count_verbs_with_an_inline_frame_are_named_stubs(self):
        dm = pl.from_repr("""\
┌─────────┬─────────┐
│ STUDYID ┆ USUBJID │
│ ---     ┆ ---     │
│ str     ┆ str     │
╞═════════╪═════════╡
│ X       ┆ S1      │
└─────────┴─────────┘
""")
        ex = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ EXSTDTC    │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ S1      ┆ 2024-01-02 │
└─────────┴────────────┘
""")
        ns = (
            dm.adam.adsl.first_date("TRTSDT", from_dataset=ex, date_col="EXSTDTC")
            .last_date("TRTEDT", from_dataset=ex, date_col="EXSTDTC")
            .count_events("NUMEX", from_dataset=ex)
        )
        with pytest.warns(UserWarning, match="TRTSDT, TRTEDT, NUMEX"):
            text = ns.to_spec_yaml(dataset="ADSL")

        assert "verb 'first_date'" in text and "verb 'count_events'" in text
