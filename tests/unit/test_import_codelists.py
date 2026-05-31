"""Unit tests for fleet.ct.import_codelists dynamic module loader."""

import sys
import textwrap
from pathlib import Path

import pytest

from fleet.ct import import_codelists


@pytest.fixture()
def codelists_file(tmp_path: Path) -> Path:
    """Create a minimal codelists.py in a temp directory."""
    cl = tmp_path / "codelists.py"
    cl.write_text(
        textwrap.dedent("""\
            class C66731:
                _concept_id = "C66731"
                M = "M"
                F = "F"

            SEX = C66731
            __all__ = ["C66731", "SEX"]
        """),
        encoding="utf-8",
    )
    return cl


@pytest.fixture()
def study_workspace(tmp_path: Path) -> Path:
    """Create a minimal study workspace with study_config.yaml + codelists."""
    config = tmp_path / "study_config.yaml"
    config.write_text(
        textwrap.dedent("""\
            study_id: TEST01
            paths:
              metadata_sdtm: metadata/sdtm
        """),
        encoding="utf-8",
    )
    meta_dir = tmp_path / "metadata" / "sdtm"
    meta_dir.mkdir(parents=True)
    cl = meta_dir / "codelists.py"
    cl.write_text(
        textwrap.dedent("""\
            class C74457:
                _concept_id = "C74457"
                WHITE = "WHITE"

            RACE = C74457
            __all__ = ["C74457", "RACE"]
        """),
        encoding="utf-8",
    )
    return tmp_path


class TestImportCodelists:
    def test_explicit_path(self, codelists_file: Path):
        mod = import_codelists(codelists_file, module_name="test_cl_explicit")
        assert mod.SEX.M == "M"
        assert mod.SEX._concept_id == "C66731"
        # Clean up sys.modules
        sys.modules.pop("test_cl_explicit", None)

    def test_registers_in_sys_modules(self, codelists_file: Path):
        mod_name = "test_cl_registered"
        import_codelists(codelists_file, module_name=mod_name)
        assert mod_name in sys.modules
        sys.modules.pop(mod_name, None)

    def test_auto_discover_from_study_config(self, study_workspace: Path, monkeypatch):
        monkeypatch.chdir(study_workspace)
        mod = import_codelists(module_name="test_cl_auto")
        assert mod.RACE.WHITE == "WHITE"
        sys.modules.pop("test_cl_auto", None)

    def test_missing_file_raises(self, tmp_path: Path):
        missing = tmp_path / "nonexistent" / "codelists.py"
        with pytest.raises(FileNotFoundError, match="Codelists module not found"):
            import_codelists(missing)

    def test_bare_import_after_registration(self, codelists_file: Path):
        """After import_codelists(), `from codelists import X` works."""
        import_codelists(codelists_file, module_name="codelists_bare_test")
        # Simulate what `from codelists_bare_test import SEX` does
        mod = sys.modules["codelists_bare_test"]
        assert hasattr(mod, "SEX")
        assert mod.SEX.F == "F"
        sys.modules.pop("codelists_bare_test", None)
