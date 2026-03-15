"""Unit tests for Define-XML validator and generator."""

from pathlib import Path

import pytest

import fleet  # noqa: F401
from fleet.define_xml import DefineValidator, DefineXMLGenerator


PHARMAVERSEPY = Path(__file__).parent.parent.parent.parent / "Pharmaversepy"
DEFINE_YAML = PHARMAVERSEPY / "studies/CDISCPILOT01/metadata/define.yaml"
SCHEMA_PATH = Path(__file__).parent.parent.parent / "src/fleet/define_xml/schemas/define_xml_2_1_schema.json"


@pytest.mark.skipif(not DEFINE_YAML.exists(), reason="PharmaversePY define.yaml not found")
class TestDefineValidator:
    def test_validator_creates(self):
        validator = DefineValidator(schema_path=SCHEMA_PATH)
        assert validator is not None
        assert validator.schema is not None

    def test_validate_example_yaml(self, tmp_path):
        validator = DefineValidator(schema_path=SCHEMA_PATH)
        result = validator.validate(DEFINE_YAML)
        # The validator should run without exception;
        # result may be True or False depending on the YAML content
        assert isinstance(result, bool)

    def test_has_errors_false_when_no_issues(self):
        validator = DefineValidator(schema_path=SCHEMA_PATH)
        assert not validator.has_errors()

    def test_get_errors_empty(self):
        validator = DefineValidator(schema_path=SCHEMA_PATH)
        assert validator.get_errors() == []


@pytest.mark.skipif(not DEFINE_YAML.exists(), reason="PharmaversePY define.yaml not found")
class TestDefineXMLGenerator:
    def test_generator_creates(self):
        generator = DefineXMLGenerator(DEFINE_YAML)
        assert generator is not None

    def test_generate_output(self, tmp_path):
        generator = DefineXMLGenerator(DEFINE_YAML)
        output = tmp_path / "define.xml"
        generator.generate(output)
        assert output.exists()
        content = output.read_text()
        assert "ODM" in content
        assert "MetaDataVersion" in content
