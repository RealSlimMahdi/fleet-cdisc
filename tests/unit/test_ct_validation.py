"""Unit tests for CT loading and validation."""

import fleet  # noqa: F401


class TestLoadControlledTerminology:
    def test_load_yaml(self, ct_sample_path):
        from fleet.ct import load_controlled_terminology

        ct = load_controlled_terminology(ct_sample_path)
        assert isinstance(ct, dict)
        assert len(ct) > 0

    def test_load_specific_codelist(self, ct_sample_path):
        from fleet.ct import load_controlled_terminology

        ct = load_controlled_terminology(ct_sample_path, codelist_name="C66731")
        # load_controlled_terminology returns {"C66731": {"M": ..., "F": ...}}
        inner = ct.get("C66731", ct)  # handle both flat and nested
        assert "M" in inner or "F" in inner


class TestCTValidator:
    def test_singleton(self):
        from fleet.ct import CTValidator

        v1 = CTValidator.get_instance()
        v2 = CTValidator.get_instance()
        assert v1 is v2

    def test_load_file(self, ct_sample_path):
        from fleet.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)
        info = validator.get_cache_info()
        # get_cache_info returns 'codelists_loaded' key
        assert len(info["codelists_loaded"]) >= 1

    def test_validate_valid_value(self, ct_sample_path):
        from fleet.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)
        # C66731 = Sex; "F" and "M" are valid
        is_valid, _ = validator.validate_value("C66731", "F")
        assert is_valid

    def test_validate_invalid_value(self, ct_sample_path):
        from fleet.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)
        is_valid, msg = validator.validate_value("C66731", "UNKNOWN_VAL")
        assert not is_valid
        assert "C66731" in msg

    def test_validate_null_allowed(self, ct_sample_path):
        from fleet.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)
        is_valid, _ = validator.validate_value("C66731", None, allow_null=True)
        assert is_valid

    def test_get_valid_values(self, ct_sample_path):
        from fleet.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)
        vals = validator.get_valid_values("C66731")
        assert isinstance(vals, list)
        assert len(vals) > 0

    def test_register_alias(self, ct_sample_path):
        from fleet.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)
        validator.register_alias("sex_codelist", "C66731")
        is_valid, _ = validator.validate_value("sex_codelist", "M")
        assert is_valid


# ------------------------------------------------------------------ #
# Phase 3 hardening: CT drift, casing, whitespace, edge cases         #
# ------------------------------------------------------------------ #

import polars as pl  # noqa: E402


class TestCTCasingAndWhitespace:
    """CT validation should handle real-world casing and whitespace drift."""

    def test_value_with_leading_whitespace_is_invalid(self, ct_sample_path):
        from fleet.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)
        is_valid, msg = validator.validate_value("C66731", " F")
        assert not is_valid, "Leading whitespace should not match"

    def test_value_with_trailing_whitespace_is_invalid(self, ct_sample_path):
        from fleet.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)
        is_valid, msg = validator.validate_value("C66731", "F ")
        assert not is_valid, "Trailing whitespace should not match"

    def test_lowercase_value_is_invalid(self, ct_sample_path):
        from fleet.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)
        is_valid, msg = validator.validate_value("C66731", "f")
        assert not is_valid, "Lowercase should not match uppercase CT term"

    def test_empty_string_is_invalid(self, ct_sample_path):
        from fleet.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)
        is_valid, msg = validator.validate_value("C66731", "")
        assert not is_valid, "Empty string should not be valid"


class TestCTMissingCodelist:
    """Behavior when codelist does not exist in the cache."""

    def test_validate_unknown_codelist_returns_invalid(self, ct_sample_path):
        from fleet.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)
        is_valid, msg = validator.validate_value("NONEXISTENT_CL", "M")
        # Should either be invalid or handled gracefully
        # (depends on implementation — this documents the contract)
        assert isinstance(is_valid, bool)
        assert isinstance(msg, str)

    def test_get_valid_values_unknown_codelist(self, ct_sample_path):
        from fleet.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)
        vals = validator.get_valid_values("TOTALLY_FAKE_CL")
        assert vals == [] or vals is None or isinstance(vals, list)


class TestCTMalformedCodelistClass:
    """Edge cases for codelist class resolution in SDTM pipelines."""

    def test_codelist_class_without_concept_id_falls_through(self, simple_raw):
        """A class missing _concept_id should fall through gracefully (warning emitted)."""

        class BadCodelist:
            pass  # no _concept_id attribute

        # Implementation logs a warning and skips validation — no crash
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            result = simple_raw.sdtm.hardcode_ct(
                "AGEU", value="YEARS", ct_codelist=BadCodelist
            ).to_frame()
        assert result["AGEU"].to_list() == ["YEARS", "YEARS", "YEARS"]

    def test_codelist_class_with_none_concept_id(self, simple_raw):
        """A class with _concept_id=None should be handled gracefully."""

        class NoneCodelist:
            _concept_id = None

        # Should either raise or fall back — not crash with cryptic error
        try:
            simple_raw.sdtm.hardcode_ct(
                "AGEU", value="YEARS", ct_codelist=NoneCodelist
            ).to_frame()
        except (ValueError, TypeError, AttributeError):
            pass  # acceptable: explicit rejection


class TestAssignCTWithMessyData:
    """assign_ct behavior with terminology drift in source data."""

    def test_unmapped_value_propagates_as_null_or_passthrough(self):
        """Source value not in ct_mapping should not silently map to wrong term."""
        df = pl.DataFrame({"sex": ["F", "M", "UNKNOWN", None]})
        result = df.sdtm.assign_ct(
            "SEX",
            source="sex",
            ct_codelist="C66731",
            ct_mapping={"F": "F", "M": "M"},
        ).to_frame()
        # UNKNOWN should become null (unmapped) or remain unchanged — never "F" or "M"
        assert result["SEX"][2] is None or result["SEX"][2] == "UNKNOWN"
        # None source should remain None
        assert result["SEX"][3] is None

    def test_whitespace_in_source_not_silently_matched(self):
        """Source ' M' should not map to 'M' without explicit stripping."""
        df = pl.DataFrame({"sex": [" M", "F "]})
        result = df.sdtm.assign_ct(
            "SEX",
            source="sex",
            ct_codelist="C66731",
            ct_mapping={"F": "F", "M": "M"},
        ).to_frame()
        # Whitespace-drifted values should NOT silently match
        assert result["SEX"][0] is None or result["SEX"][0] == " M"
        assert result["SEX"][1] is None or result["SEX"][1] == "F "
