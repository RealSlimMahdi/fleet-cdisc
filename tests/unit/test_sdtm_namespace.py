"""Unit tests for the SDTM Polars namespace extension (df.sdtm)."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration


class TestAssignNoCT:
    def test_basic_rename(self, simple_raw):
        result = simple_raw.sdtm.assign_no_ct("USUBJID", source="patient_number").to_frame()
        assert "USUBJID" in result.columns
        assert result["USUBJID"].to_list() == simple_raw["patient_number"].to_list()

    def test_chained(self, simple_raw):
        result = (
            simple_raw.sdtm.assign_no_ct("USUBJID", source="patient_number")
            .assign_no_ct("SITEID", source="site_id")
            .to_frame()
        )
        assert "USUBJID" in result.columns
        assert "SITEID" in result.columns

    def test_original_frame_unchanged(self, simple_raw):
        simple_raw.sdtm.assign_no_ct("USUBJID", source="patient_number").to_frame()
        assert "USUBJID" not in simple_raw.columns


class TestHardcodeNoCT:
    def test_constant_string(self, simple_raw):
        result = simple_raw.sdtm.hardcode_no_ct("DOMAIN", value="DM").to_frame()
        assert result["DOMAIN"].to_list() == ["DM", "DM", "DM"]

    def test_constant_int(self, simple_raw):
        result = simple_raw.sdtm.hardcode_no_ct("DMSEQ", value=1).to_frame()
        assert result["DMSEQ"].to_list() == [1, 1, 1]


class TestHardcodeCT:
    def test_constant_with_ct(self, simple_raw):
        result = simple_raw.sdtm.hardcode_ct("AGEU", value="YEARS", ct_codelist="C66789").to_frame()
        assert result["AGEU"].to_list() == ["YEARS", "YEARS", "YEARS"]

    def test_warns_on_invalid_value(self, simple_raw):
        """When CT is loaded and the value is not valid, a warning is emitted."""
        from fleet.ct.validator import get_validator

        validator = get_validator()
        # Seed a tiny codelist so validation can fire
        validator._ct_cache["C_TEST"] = {"YEARS": {}, "MONTHS": {}}
        try:
            with pytest.warns(UserWarning, match="not in codelist"):
                simple_raw.sdtm.hardcode_ct(
                    "AGEU", value="INVALID", ct_codelist="C_TEST"
                ).to_frame()
        finally:
            validator._ct_cache.pop("C_TEST", None)

    def test_no_warning_on_valid_value(self, simple_raw):
        """No warning when the value IS in the loaded codelist."""
        from fleet.ct.validator import get_validator

        validator = get_validator()
        validator._ct_cache["C_TEST2"] = {"YEARS": {}, "MONTHS": {}}
        try:
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("error")
                result = simple_raw.sdtm.hardcode_ct(
                    "AGEU", value="YEARS", ct_codelist="C_TEST2"
                ).to_frame()
            assert result["AGEU"].to_list() == ["YEARS", "YEARS", "YEARS"]
        finally:
            validator._ct_cache.pop("C_TEST2", None)

    def test_codelist_class_resolved(self, simple_raw):
        """A codelist class with ``_concept_id`` is resolved to its ID."""
        from fleet.ct.validator import get_validator

        validator = get_validator()
        validator._ct_cache["C99999"] = {"YEARS": {}}
        try:

            class FakeCodelist:
                _concept_id = "C99999"

            result = simple_raw.sdtm.hardcode_ct(
                "AGEU", value="YEARS", ct_codelist=FakeCodelist
            ).to_frame()
            assert result["AGEU"].to_list() == ["YEARS", "YEARS", "YEARS"]
        finally:
            validator._ct_cache.pop("C99999", None)


class TestAssignDtc:
    def test_date_iso(self, simple_raw):
        result = simple_raw.sdtm.date("RFSTDTC", source="first_dose_date").to_frame()
        assert "RFSTDTC" in result.columns
        assert result["RFSTDTC"][0] == "2014-01-02"

    def test_datetime_mode(self, simple_raw):
        result = simple_raw.sdtm.date(
            "RFSTDTC", source="first_dose_date"
        ).to_frame()
        assert result["RFSTDTC"][0].startswith("2014-01-02")

    def test_partial_date_preserved(self):
        df = pl.DataFrame({"dtc": ["2014-01", "2014", "2014-01-02", None]})
        result = df.sdtm.date("OUT", source="dtc", output="dtc").to_frame()
        assert result["OUT"][0] == "2014-01"  # partial preserved
        assert result["OUT"][1] == "2014"  # partial preserved
        assert result["OUT"][2] == "2014-01-02"  # complete parsed
        assert result["OUT"][3] is None

    def test_input_format_shortcut(self, simple_raw):
        result = simple_raw.sdtm.date(
            "RFSTDTC", source="first_dose_date", format="%Y-%m-%d"
        ).to_frame()
        assert result["RFSTDTC"][0] == "2014-01-02"


class TestAssignCT:
    def test_with_explicit_mapping(self, simple_raw):
        result = simple_raw.sdtm.assign_ct(
            "SEX",
            source="sex",
            ct_codelist="C66731",
            ct_mapping={"F": "F", "M": "M"},
        ).to_frame()
        assert result["SEX"].to_list() == ["F", "F", "M"]

    def test_fallback_passthrough(self, simple_raw):
        # Without CT loaded, should pass through the raw value
        result = simple_raw.sdtm.assign_ct(
            "SEX", source="sex", ct_codelist="NONEXISTENT"
        ).to_frame()
        assert "SEX" in result.columns


class TestConditionAdd:
    def test_condition_true(self, simple_raw):
        result = simple_raw.sdtm.condition_add(
            "ARMCD_FLAG",
            condition=pl.col("arm_code") == "Pbo",
            then_value="Y",
        ).to_frame()
        flags = result["ARMCD_FLAG"].to_list()
        assert flags[0] == "Y"
        assert flags[1] is None

    def test_condition_string_expr(self, simple_raw):
        result = simple_raw.sdtm.condition_add(
            "MALE_FLAG",
            condition='pl.col("sex") == "M"',
            then_value="Y",
        ).to_frame()
        flags = result["MALE_FLAG"].to_list()
        assert flags[2] == "Y"


class TestIfThenElse:
    def test_multi_branch(self, simple_raw):
        result = simple_raw.sdtm.if_then_else(
            "ARMFULL",
            when=[
                {"condition": pl.col("arm_code") == "Pbo", "value": "Placebo Group"},
                {"condition": pl.col("arm_code") == "Xan_Lo", "value": "Low Dose Group"},
            ],
            else_value="High Dose Group",
        ).to_frame()
        vals = result["ARMFULL"].to_list()
        assert vals[0] == "Placebo Group"
        assert vals[1] == "Low Dose Group"
        assert vals[2] == "High Dose Group"


class TestAEAerel:
    def test_default_mapping(self):
        df = pl.DataFrame({"ae_relationship": ["yes", "no", "possibly related", None]})
        result = df.sdtm.ae_aerel(target="AEREL", source="ae_relationship").to_frame()
        vals = result["AEREL"].to_list()
        assert vals[0] == "RELATED"
        assert vals[1] == "NOT RELATED"
        assert vals[2] == "POSSIBLY RELATED"
        assert vals[3] is None

    def test_custom_mapping(self):
        df = pl.DataFrame({"rel": ["yes", "no"]})
        result = df.sdtm.ae_aerel(
            target="AEREL",
            source="rel",
            aerel_map={"yes": "Y", "no": "N"},
        ).to_frame()
        assert result["AEREL"].to_list() == ["Y", "N"]


class TestNotsubmitted:
    def test_sets_null(self, simple_raw):
        result = simple_raw.sdtm.notsubmitted("age", "sex").to_frame()
        assert all(v is None for v in result["age"].to_list())
        assert all(v is None for v in result["sex"].to_list())


class TestDatasetLevel:
    def test_alias_for_hardcode(self, simple_raw):
        result = simple_raw.sdtm.dataset_level("STUDYID", value="STUDY01").to_frame()
        assert result["STUDYID"].to_list() == ["STUDY01", "STUDY01", "STUDY01"]


class TestRemoveDup:
    def test_removes_duplicates(self):
        df = pl.DataFrame({"id": [1, 1, 2], "val": ["a", "a", "b"]})
        result = df.sdtm.remove_dup(subset=["id"]).to_frame()
        assert result.height == 2


class TestMultipleResponses:
    def test_expands_rows(self):
        df = pl.DataFrame({"USUBJID": ["S01"], "ae_terms": ["fever|rash"]})
        result = df.sdtm.multiple_responses("AETERM", source="ae_terms", delimiter="|").to_frame()
        assert result.height == 2
        assert set(result["AETERM"].to_list()) == {"fever", "rash"}


class TestFromSpec:
    def test_dm_define_yaml(self, dm_raw, sdtm_define_path):
        """from_spec() works with the unified define.yaml (dataset= selects DM)."""
        result = dm_raw.sdtm.from_spec(sdtm_define_path, dataset="DM").to_frame()
        assert "USUBJID" in result.columns
        assert "DOMAIN" in result.columns
        assert result["DOMAIN"][0] == "DM"
        assert result["STUDYID"][0] == "CDISCPILOT01"

    def test_define_yaml_requires_dataset_arg_for_multi_dataset_file(
        self, dm_raw, sdtm_define_path
    ):
        """Calling from_spec() on a multi-dataset define.yaml without dataset= raises."""
        with pytest.raises(ValueError, match="dataset="):
            dm_raw.sdtm.from_spec(sdtm_define_path).to_frame()


class TestToFrame:
    def test_empty_pipeline_returns_original(self, simple_raw):
        result = simple_raw.sdtm.to_frame()
        assert result.shape == simple_raw.shape
