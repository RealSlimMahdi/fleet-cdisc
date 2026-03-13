"""Unit tests for CT loading and validation."""

from pathlib import Path

import pytest

import pymaverse  # noqa: F401


class TestLoadControlledTerminology:
    def test_load_yaml(self, ct_sample_path):
        from pymaverse.ct import load_controlled_terminology

        ct = load_controlled_terminology(ct_sample_path)
        assert isinstance(ct, dict)
        assert len(ct) > 0

    def test_load_specific_codelist(self, ct_sample_path):
        from pymaverse.ct import load_controlled_terminology

        ct = load_controlled_terminology(ct_sample_path, codelist_name="C66731")
        # load_controlled_terminology returns {"C66731": {"M": ..., "F": ...}}
        inner = ct.get("C66731", ct)  # handle both flat and nested
        assert "M" in inner or "F" in inner


class TestCTValidator:
    def test_singleton(self):
        from pymaverse.ct import CTValidator

        v1 = CTValidator.get_instance()
        v2 = CTValidator.get_instance()
        assert v1 is v2

    def test_load_file(self, ct_sample_path):
        from pymaverse.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)
        info = validator.get_cache_info()
        # get_cache_info returns 'codelists_loaded' key
        assert len(info["codelists_loaded"]) >= 1

    def test_validate_valid_value(self, ct_sample_path):
        from pymaverse.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)
        # C66731 = Sex; "F" and "M" are valid
        is_valid, _ = validator.validate_value("C66731", "F")
        assert is_valid

    def test_validate_invalid_value(self, ct_sample_path):
        from pymaverse.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)
        is_valid, msg = validator.validate_value("C66731", "UNKNOWN_VAL")
        assert not is_valid
        assert "C66731" in msg

    def test_validate_null_allowed(self, ct_sample_path):
        from pymaverse.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)
        is_valid, _ = validator.validate_value("C66731", None, allow_null=True)
        assert is_valid

    def test_get_valid_values(self, ct_sample_path):
        from pymaverse.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)
        vals = validator.get_valid_values("C66731")
        assert isinstance(vals, list)
        assert len(vals) > 0

    def test_register_alias(self, ct_sample_path):
        from pymaverse.ct import CTValidator

        validator = CTValidator.get_instance()
        validator.load_ct_file(ct_sample_path)
        validator.register_alias("sex_codelist", "C66731")
        is_valid, _ = validator.validate_value("sex_codelist", "M")
        assert is_valid
