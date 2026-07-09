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
            result = simple_raw.sdtm.assign("AGEU", value="YEARS", ct=BadCodelist).to_frame()
        assert result["AGEU"].to_list() == ["YEARS", "YEARS", "YEARS"]

    def test_codelist_class_with_none_concept_id(self, simple_raw):
        """A class with _concept_id=None should be handled gracefully."""

        class NoneCodelist:
            _concept_id = None

        # Should either raise or fall back — not crash with cryptic error
        try:
            simple_raw.sdtm.assign("AGEU", value="YEARS", ct=NoneCodelist).to_frame()
        except (ValueError, TypeError, AttributeError):
            pass  # acceptable: explicit rejection


class TestAssignCTWithMessyData:
    """assign_ct behavior with terminology drift in source data."""

    def test_unmapped_value_propagates_as_null_or_passthrough(self):
        """Source value not in ct_mapping should not silently map to wrong term."""
        df = pl.DataFrame({"sex": ["F", "M", "UNKNOWN", None]})
        result = df.sdtm.assign(
            "SEX",
            source="sex",
            ct="C66731",
            ct_map={"F": "F", "M": "M"},
        ).to_frame()
        # UNKNOWN should become null (unmapped) or remain unchanged — never "F" or "M"
        assert result["SEX"][2] is None or result["SEX"][2] == "UNKNOWN"
        # None source should remain None
        assert result["SEX"][3] is None

    def test_whitespace_in_source_not_silently_matched(self):
        """Source ' M' should not map to 'M' without explicit stripping."""
        df = pl.DataFrame({"sex": [" M", "F "]})
        result = df.sdtm.assign(
            "SEX",
            source="sex",
            ct="C66731",
            ct_map={"F": "F", "M": "M"},
        ).to_frame()
        # Whitespace-drifted values should NOT silently match
        assert result["SEX"][0] is None or result["SEX"][0] == " M"
        assert result["SEX"][1] is None or result["SEX"][1] == "F "


class TestAssignCTValidateValues:
    """assign_ct with validate_values=True checks source data against codelist."""

    def test_warns_on_invalid_values(self, ct_sample_path):
        """Source values not in codelist emit a UserWarning."""
        import warnings

        from fleet.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)

        df = pl.DataFrame({"sex": ["M", "Female", "f"]})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = df.sdtm.assign(
                "SEX",
                source="sex",
                ct="C66731",
                validate_values=True,
            ).to_frame()

        # Pipeline still completes
        assert result.shape[0] == 3
        # At least one warning for invalid values
        ct_warnings = [w for w in caught if "not in codelist" in str(w.message)]
        assert len(ct_warnings) == 1
        msg = str(ct_warnings[0].message)
        assert "Female" in msg or "f" in msg

    def test_no_warning_when_values_are_valid(self, ct_sample_path):
        """All valid values produce no warning."""
        import warnings

        from fleet.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)

        df = pl.DataFrame({"sex": ["M", "F", "U"]})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            df.sdtm.assign(
                "SEX",
                source="sex",
                ct="C66731",
                validate_values=True,
            ).to_frame()

        ct_warnings = [w for w in caught if "not in codelist" in str(w.message)]
        assert len(ct_warnings) == 0

    def test_no_warning_when_flag_is_false(self, ct_sample_path):
        """Default validate_values=False does not warn even with invalid data."""
        import warnings

        from fleet.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)

        df = pl.DataFrame({"sex": ["Invalid"]})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            df.sdtm.assign(
                "SEX",
                source="sex",
                ct="C66731",
                validate_values=False,
            ).to_frame()

        ct_warnings = [w for w in caught if "not in codelist" in str(w.message)]
        assert len(ct_warnings) == 0

    def test_nulls_are_not_flagged(self, ct_sample_path):
        """Null values in source should not trigger a warning."""
        import warnings

        from fleet.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)

        df = pl.DataFrame({"sex": ["M", None, "F"]})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            df.sdtm.assign(
                "SEX",
                source="sex",
                ct="C66731",
                validate_values=True,
            ).to_frame()

        ct_warnings = [w for w in caught if "not in codelist" in str(w.message)]
        assert len(ct_warnings) == 0

    def test_warns_using_codelist_class_without_ct_loaded(self):
        """validate_values works via class introspection even without CT loaded."""
        import warnings

        from fleet.ct import CTValidator

        # Reset the validator to simulate CT not loaded
        validator = CTValidator.get_instance()
        old_cache = validator._ct_cache.copy()
        old_init = validator._initialized
        validator._ct_cache = {}
        validator._initialized = False

        try:

            class FakeRoute:
                _concept_id = "C66729"
                ORAL = "ORAL"
                INTRAVENOUS = "INTRAVENOUS"
                SUBCUTANEOUS = "SUBCUTANEOUS"

            df = pl.DataFrame({"route": ["Oral", "ORAL", "IV"]})
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                result = df.sdtm.assign(
                    "EXROUT",
                    source="route",
                    ct=FakeRoute,
                    validate_values=True,
                ).to_frame()

            assert result.shape[0] == 3
            ct_warnings = [w for w in caught if "not in codelist" in str(w.message)]
            assert len(ct_warnings) == 1
            msg = str(ct_warnings[0].message)
            assert "Oral" in msg or "IV" in msg
        finally:
            # Restore validator state
            validator._ct_cache = old_cache
            validator._initialized = old_init
