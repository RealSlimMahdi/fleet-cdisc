"""XSD validation of generated Define-XML.

The schema-content tests skip until the CDISC schema set is dropped into
``fleet/define_xml/schemas/xsd`` (see ``SOURCES.txt`` there).  The
*plumbing* tests never skip: they guard the part that breaks silently
after installation — resolution order and packaging.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fleet.core.exceptions import SpecError
from fleet.define_xml import DefineSpecGenerator, validate_define_xml
from fleet.define_xml.xsd import REQUIRED_FILES, ROOT_XSD, missing_files, xsd_dir

EXAMPLES = Path(__file__).parent.parent.parent / "examples" / "cdiscpilot01"

schemas_present = pytest.mark.skipif(
    bool(missing_files()),
    reason=f"CDISC schema set not installed (missing {', '.join(missing_files())})",
)


class TestResolution:
    """Location must stay valid once Fleet is installed elsewhere."""

    def test_packaged_dir_resolves_to_a_real_directory(self):
        with xsd_dir() as d:
            assert d.is_dir(), f"packaged schema dir not resolvable: {d}"

    def test_packaged_dir_lives_inside_the_package(self):
        """Not next to the repo, not in the cwd — inside fleet/define_xml."""
        import fleet.define_xml as pkg

        with xsd_dir() as d:
            assert d.resolve() == (Path(pkg.__file__).parent / "schemas" / "xsd").resolve()

    def test_env_var_overrides(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FLEET_DEFINE_XSD", str(tmp_path))
        with xsd_dir() as d:
            assert d == tmp_path

    def test_missing_files_names_what_is_absent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FLEET_DEFINE_XSD", str(tmp_path))
        assert missing_files() == list(REQUIRED_FILES)

    def test_incomplete_set_raises_with_guidance(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FLEET_DEFINE_XSD", str(tmp_path))
        with pytest.raises(SpecError, match="schema set incomplete"):
            validate_define_xml("<ODM/>")


class TestPackaging:
    def test_sources_manifest_ships_with_the_package(self):
        """A file in the xsd dir proves the directory is packaged, not just gitignored."""
        with xsd_dir() as d:
            assert (d / "SOURCES.txt").is_file()

    def test_every_required_file_is_present_in_its_published_layout(self):
        """Define-XML imports ODM by relative path — the nested layout is load-bearing."""
        with xsd_dir() as d:
            assert (d / ROOT_XSD).is_file()
            assert missing_files() == []


@schemas_present
class TestValidation:
    def test_generated_sdtm_define_is_schema_valid(self):
        xml = DefineSpecGenerator(EXAMPLES / "sdtm" / "define.yaml").to_xml_string()
        assert validate_define_xml(xml) == []

    def test_generated_adam_define_is_schema_valid(self):
        xml = DefineSpecGenerator(EXAMPLES / "adam" / "define.yaml").to_xml_string()
        assert validate_define_xml(xml) == []

    def test_invalid_origin_type_is_caught(self):
        """The Type='CRF' class of defect fails here without a human reading enums."""
        xml = DefineSpecGenerator(EXAMPLES / "sdtm" / "define.yaml").to_xml_string()
        broken = xml.replace('Type="Collected"', 'Type="CRF"', 1)
        assert validate_define_xml(broken) != []


class TestAutomaticValidation:
    """Generation validates by default — a non-conformant define.xml never ships."""

    def test_generate_validates_by_default(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FLEET_DEFINE_XSD", str(tmp_path))  # break the schema set
        gen = DefineSpecGenerator(EXAMPLES / "sdtm" / "define.yaml")
        with pytest.raises(SpecError, match="schema set incomplete"):
            gen.to_xml_string()

    def test_validate_xml_false_bypasses(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FLEET_DEFINE_XSD", str(tmp_path))
        gen = DefineSpecGenerator(EXAMPLES / "sdtm" / "define.yaml", validate_xml=False)
        assert gen.to_xml_string().startswith("<?xml")

    @schemas_present
    def test_shipped_examples_generate_clean(self, tmp_path):
        """No exception means the document validated on the way out."""
        for std in ("sdtm", "adam"):
            DefineSpecGenerator(EXAMPLES / std / "define.yaml").generate(
                tmp_path / f"define_{std}.xml", html_preview=False
            )
            assert (tmp_path / f"define_{std}.xml").is_file()
