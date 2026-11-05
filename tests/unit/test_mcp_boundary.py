"""Tests for the shared treatment-arm auto-detection (``fleet.tlg``).

`fleet tlg run` and the MCP `fleet_tlg_run` tool both need it; before
#68 each carried its own copy and the MCP server reached into
``fleet.cli`` for the candidate list.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

import polars as pl
import pytest

import fleet
from fleet.tlg import GROUPBY_CANDIDATES, detect_groupby


class TestDetectGroupby:
    def test_candidates_are_tried_in_order(self) -> None:
        df = pl.DataFrame({"TRT01P": ["A"], "TRTA": ["B"], "TRT01A": ["C"]})

        assert detect_groupby(df.columns) == "TRTA"

    @pytest.mark.parametrize("column", GROUPBY_CANDIDATES)
    def test_each_candidate_is_detected_alone(self, column: str) -> None:
        assert detect_groupby([column, "USUBJID"]) == column

    def test_no_candidate_returns_none(self) -> None:
        assert detect_groupby(["USUBJID", "AEDECOD"]) is None

    def test_candidates_are_the_documented_order(self) -> None:
        assert GROUPBY_CANDIDATES == ("TRTA", "TRT01A", "TRT01P")

    def test_both_names_are_public(self) -> None:
        import fleet.tlg as tlg

        assert "GROUPBY_CANDIDATES" in tlg.__all__
        assert "detect_groupby" in tlg.__all__


class TestMcpImportBoundary:
    """``mcp_server`` is a protocol adapter: it may use Fleet's public
    packages, never the CLI and never a private submodule (#68, ADR-0001)."""

    #: Public packages the MCP tools are built from.
    ALLOWED = {
        "fleet",
        "fleet.core.dag",
        "fleet.core.spec_source",  # static spec <-> code conversion tools (#139)
        "fleet.ct.terms",  # one term lookup across the CT stores (c1-35)
        "fleet.ct.validator",
        "fleet.define_xml",
        "fleet.io",
        "fleet.tlg",
        "fleet.validation",
    }

    @staticmethod
    def _module(node: ast.ImportFrom) -> str:
        """The absolute module of an import; ``mcp_server`` sits directly in ``fleet``."""
        if node.level:
            return f"fleet.{node.module}" if node.module else "fleet"
        return node.module or ""

    def _fleet_imports(self, source: Path) -> set[str]:
        tree = ast.parse(source.read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = self._module(node)
                if module != "fleet" and not module.startswith("fleet."):
                    continue
                for alias in node.names:
                    # ``from fleet import cli`` imports the module fleet.cli.
                    sub = f"fleet.{alias.name}"
                    is_module = module == "fleet" and importlib.util.find_spec(sub) is not None
                    modules.add(sub if is_module else module)
            elif isinstance(node, ast.Import):
                modules.update(
                    a.name for a in node.names if a.name == "fleet" or a.name.startswith("fleet.")
                )
        return modules

    @staticmethod
    def _private_names(tree: ast.AST) -> set[str]:
        return {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and TestMcpImportBoundary._module(node).startswith("fleet")
            for alias in node.names
            if alias.name.startswith("_") and alias.name != "__version__"
        }

    @pytest.mark.parametrize(
        ("line", "offender"),
        [
            ("from .cli import main", "fleet.cli"),
            ("from fleet import cli", "fleet.cli"),
            ("from .core.spec_registry import get_algorithm", "fleet.core.spec_registry"),
        ],
    )
    def test_the_sweep_resolves_relative_and_submodule_imports(
        self, tmp_path: Path, line: str, offender: str
    ) -> None:
        """c1-851: a relative import has no "fleet" module name; the sweep resolves it."""
        source = tmp_path / "adapter.py"
        source.write_text(f"{line}\nfrom fleet.io import load_raw_data\n", encoding="utf-8")

        assert self._fleet_imports(source) - self.ALLOWED == {offender}

    def test_the_private_name_check_sees_a_relative_import(self) -> None:
        tree = ast.parse("from .core.spec_registry import _DECLARED\nfrom fleet import __version__")

        assert self._private_names(tree) == {"_DECLARED"}

    def test_mcp_server_imports_stay_on_public_packages(self) -> None:
        source = Path(fleet.__file__).parent / "mcp_server.py"

        offenders = sorted(self._fleet_imports(source) - self.ALLOWED)

        assert not offenders, (
            f"mcp_server.py reaches outside Fleet's public packages: {offenders}. "
            "Promote what it needs, or widen ALLOWED with a stated reason."
        )

    def test_mcp_server_imports_nothing_private(self) -> None:
        """A public module path is not enough; the *names* must be public too."""
        source = (Path(fleet.__file__).parent / "mcp_server.py").read_text(encoding="utf-8")

        private = self._private_names(ast.parse(source))

        assert not private, f"mcp_server.py imports private names: {sorted(private)}"
