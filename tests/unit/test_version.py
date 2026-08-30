"""The version contract (#70): one source of truth, derived from git tags.

Fleet's version travels over the wire — ``lsp_server.create_server()`` puts
it in ``serverInfo.version`` and the shipped VS Code client parses its PEP
440 release segment to enforce a minimum Fleet.  A hand-edited literal that
can drift from the built artefact makes that promise meaningless, so the
number lives in exactly one place: the git tag, read back at runtime through
the installed distribution's metadata.
"""

from __future__ import annotations

import re
import tomllib
from importlib.metadata import version
from pathlib import Path

import fleet

PYPROJECT = Path(__file__).parent.parent.parent / "pyproject.toml"
VERSION_MODULE = Path(fleet.__file__).parent / "_version.py"


def _pyproject() -> dict:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_package_version_is_the_installed_distribution_version() -> None:
    """``import fleet`` and ``pip show fleet-cdisc`` must never disagree."""
    assert fleet.__version__ == version("fleet-cdisc")


def test_pyproject_declares_no_static_version() -> None:
    project = _pyproject()["project"]

    assert "version" not in project, "a static version re-introduces the second copy"
    assert project["dynamic"] == ["version"]


def test_build_reads_the_version_from_git() -> None:
    assert _pyproject()["tool"]["hatch"]["version"]["source"] == "vcs"


def test_published_versions_carry_no_local_segment() -> None:
    """PyPI rejects ``+g1234567``, which is hatch-vcs's default for untagged builds."""
    raw_options = _pyproject()["tool"]["hatch"]["version"]["raw-options"]

    assert raw_options["local_scheme"] == "no-local-version"


def test_version_module_assigns_no_release_literal() -> None:
    """AGENTS.md: 'Version comes from git tags — never edit version strings manually.'"""
    source = VERSION_MODULE.read_text(encoding="utf-8")
    literals = re.findall(r"""__version__\s*=\s*["'](.+?)["']""", source)

    assert [lit for lit in literals if re.match(r"^\d+\.\d+", lit)] == []


def test_version_starts_with_a_pep440_release_segment() -> None:
    """The client compares release segments; anything else it can only log."""
    assert re.match(r"^\d+(\.\d+)*", fleet.__version__)
