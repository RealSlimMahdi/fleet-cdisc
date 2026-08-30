"""Tests for the shared treatment-arm auto-detection (``fleet.tlg``).

`fleet tlg run` and the MCP `fleet_tlg_run` tool both need it; before
#68 each carried its own copy and the MCP server reached into
``fleet.cli`` for the candidate list.
"""

from __future__ import annotations

import ast
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
        "fleet.ct.validator",
        "fleet.define_xml",
        "fleet.io",
        "fleet.tlg",
        "fleet.validation",
    }

    def _fleet_imports(self, source: Path) -> set[str]:
        tree = ast.parse(source.read_text(encoding="utf-8"))
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "fleet" or node.module.startswith("fleet."):
                    modules.add(node.module)
            elif isinstance(node, ast.Import):
                modules.update(
                    a.name for a in node.names if a.name == "fleet" or a.name.startswith("fleet.")
                )
        return modules

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
        tree = ast.parse(source)

        private = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("fleet")
            for alias in node.names
            if alias.name.startswith("_")
        }

        assert not private, f"mcp_server.py imports private names: {sorted(private)}"
