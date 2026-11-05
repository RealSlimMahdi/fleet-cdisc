"""Contract tests for ``fleet.introspect`` (ADR-0001).

``fleet.introspect`` is the only Fleet surface protocol adapters may
consume.  Three things are pinned here: the exported names (a shipped
client declares a *minimum* Fleet version against them), the import
boundary of ``fleet.lsp_server`` (an AST sweep, so nothing slips back
into the registries), and the ``initialize`` handshake the client reads
to enforce that minimum.
"""

from __future__ import annotations

import ast
import dataclasses
import subprocess
import sys
from pathlib import Path

import pytest

import fleet
from fleet import introspect

LSP_SERVER_SOURCE = Path(fleet.__file__).parent / "lsp_server.py"

#: The contract.  Additive-only within a major version: entries may be
#: added, never removed or renamed (ADR-0001).
EXPECTED_ALL = [
    "AlgorithmDoc",
    "AlgorithmInfo",
    "ParamInfo",
    "Standard",
    "algorithm_doc",
    "algorithms",
    "define_schema",
    "get_algorithm",
    "load_spec_yaml",  # ADR-0008: tools parse define.yaml with Fleet's loader (on: stays a key)
    "suggest_algorithm",
]

#: Fleet modules ``lsp_server.py`` is allowed to import.  The adapter
#: speaks the surface and nothing else.
ALLOWED_IMPORTS = {"fleet", "fleet.introspect"}

#: Grandfathered reaches past the surface, each with a stated reason —
#: same pattern as ``_POSITIONAL_ALLOWANCE`` in ``test_api_conventions``.
#: Empty by design: a new entry here is a reviewed decision.
IMPORT_ALLOWANCE: dict[str, str] = {}


def _fleet_imports(source: Path) -> set[str]:
    """Every ``fleet`` module imported by *source*, including local imports.

    *source* is a top-level module of the ``fleet`` package, so a relative
    ``from .core import ...`` resolves against ``fleet`` itself — it is the
    natural spelling from inside the package and must not slip the sweep.
    """
    tree = ast.parse(source.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level and not node.module:
                modules.update(f"fleet.{alias.name}" for alias in node.names)
                continue
            base = "fleet." if node.level else ""
            module = f"{base}{node.module}"
            if module == "fleet" or module.startswith("fleet."):
                modules.add(module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "fleet" or alias.name.startswith("fleet."):
                    modules.add(alias.name)
    return modules


# ------------------------------------------------------------------ #
# The exported contract                                                #
# ------------------------------------------------------------------ #


def test_all_pins_the_contract() -> None:
    assert introspect.__all__ == EXPECTED_ALL


def test_every_exported_name_exists() -> None:
    missing = [name for name in introspect.__all__ if not hasattr(introspect, name)]
    assert missing == []


def test_surface_is_not_reexported_from_the_package_root() -> None:
    """Analysts get ``fleet.sdtm`` / ``fleet.adam``; tooling opts in explicitly."""
    leaked = [name for name in introspect.__all__ if name in getattr(fleet, "__all__", [])]
    assert leaked == []


# ------------------------------------------------------------------ #
# Algorithm catalogue                                                  #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize("standard", ["sdtm", "adam"])
def test_algorithms_returns_populated_algorithm_info(standard: str) -> None:
    entries = introspect.algorithms(standard)

    assert isinstance(entries, tuple)
    assert entries, f"no {standard} algorithms registered"
    assert all(isinstance(entry, introspect.AlgorithmInfo) for entry in entries)
    assert all(entry.standard == standard for entry in entries)
    assert all(isinstance(entry.params, tuple) for entry in entries)


def test_algorithms_exposes_parameter_metadata() -> None:
    algo = introspect.get_algorithm("sdtm", "assign")

    assert algo is not None
    assert algo.name == "assign"
    assert all(isinstance(param, introspect.ParamInfo) for param in algo.params)
    assert "ct" in {param.name for param in algo.params}


def test_required_parameters_stay_flagged() -> None:
    """Completions sort required params first, so the flag must survive the copy."""
    algo = introspect.get_algorithm("sdtm", "duration")

    assert algo is not None
    assert {param.name for param in algo.params if param.required} == {"start", "end"}


def test_get_algorithm_knows_only_verb_names() -> None:
    """The verb is the algorithm (ADR-0008): an old spec name is unknown."""
    assert introspect.get_algorithm("sdtm", "date") is not None
    assert introspect.get_algorithm("sdtm", "assign_dtc") is None


def test_get_algorithm_returns_none_for_unknown_name() -> None:
    assert introspect.get_algorithm("sdtm", "not_an_algorithm") is None


def test_algorithm_doc_returns_summary_and_verb_path() -> None:
    doc = introspect.algorithm_doc("assign")

    assert doc is not None
    assert doc.summary
    assert doc.verb_path.startswith("fleet.")


def test_algorithm_doc_returns_none_for_unknown_name() -> None:
    assert introspect.algorithm_doc("not_an_algorithm") is None


def test_suggest_algorithm_finds_the_near_miss() -> None:
    assert introspect.suggest_algorithm("sdtm", "asign") == "assign"


def test_suggest_algorithm_returns_none_when_nothing_is_close() -> None:
    assert introspect.suggest_algorithm("sdtm", "zzzzzzzz") is None


# ------------------------------------------------------------------ #
# Unknown standards fail the same way everywhere                       #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize(
    "call",
    [
        lambda: introspect.algorithms("nope"),
        lambda: introspect.get_algorithm("nope", "assign"),
        lambda: introspect.suggest_algorithm("nope", "assign"),
    ],
    ids=["algorithms", "get_algorithm", "suggest_algorithm"],
)
def test_unknown_standard_raises_value_error_naming_the_valid_values(call) -> None:
    """The delegates disagreed (``None`` vs ``KeyError``); the surface does not."""
    with pytest.raises(ValueError, match="sdtm.*adam|adam.*sdtm"):
        call()


# ------------------------------------------------------------------ #
# Define schema                                                        #
# ------------------------------------------------------------------ #


def test_define_schema_returns_the_parsed_schema() -> None:
    schema = introspect.define_schema()

    assert schema["$schema"]
    assert "properties" in schema


def test_define_schema_is_cached() -> None:
    assert introspect.define_schema() is introspect.define_schema()


def test_schema_path_stays_internal() -> None:
    assert "SCHEMA_PATH" not in introspect.__all__


# ------------------------------------------------------------------ #
# DTOs are frozen: they are a contract, not a mutable view             #
# ------------------------------------------------------------------ #


@pytest.mark.parametrize(
    "dto",
    [introspect.AlgorithmInfo, introspect.ParamInfo, introspect.AlgorithmDoc],
    ids=lambda dto: dto.__name__,
)
def test_dtos_are_frozen_dataclasses(dto: type) -> None:
    assert dataclasses.is_dataclass(dto)
    assert dto.__dataclass_params__.frozen


def test_algorithm_info_rejects_mutation() -> None:
    algo = introspect.algorithms("adam")[0]

    with pytest.raises(dataclasses.FrozenInstanceError):
        algo.name = "hacked"  # type: ignore[misc]


# ------------------------------------------------------------------ #
# The import boundary                                                  #
# ------------------------------------------------------------------ #


def test_lsp_server_imports_only_the_surface() -> None:
    """A reach past ``fleet.introspect`` is an unversioned dependency."""
    offenders = sorted(_fleet_imports(LSP_SERVER_SOURCE) - ALLOWED_IMPORTS - set(IMPORT_ALLOWANCE))

    assert offenders == [], (
        f"{LSP_SERVER_SOURCE.name} reaches past the introspection surface: {offenders}. "
        "Add the name to fleet.introspect, or grandfather it in IMPORT_ALLOWANCE with a reason."
    )


def test_introspect_imports_without_the_lsp_extra() -> None:
    """Tooling consumes the surface, but it must not drag in ``pygls``."""
    script = (
        "import sys;"
        "sys.modules['pygls'] = None;"
        "sys.modules['lsprotocol'] = None;"
        "from fleet import introspect;"
        "introspect.algorithms('sdtm');"
        "introspect.get_algorithm('adam', 'chg');"
        "introspect.algorithm_doc('baseline');"
        "introspect.define_schema()"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)

    assert result.returncode == 0, result.stderr


# ------------------------------------------------------------------ #
# The handshake a shipped client reads                                 #
# ------------------------------------------------------------------ #


def test_initialize_handshake_announces_the_fleet_version() -> None:
    """#64: the client enforces its minimum from ``serverInfo``, not a shell-out."""
    pytest.importorskip("pygls", reason="lsp extra (pygls) not installed")

    from fleet.lsp_server import create_server

    server = create_server()

    assert server.name == "fleet-lsp"
    assert server.version == fleet.__version__


def test_every_public_name_is_on_the_api_page():
    """c1-641: the introspect API page names every entry of ``__all__``."""
    from pathlib import Path

    import fleet.introspect

    page = (Path(__file__).resolve().parents[2] / "docs" / "api" / "introspect.md").read_text(
        encoding="utf-8"
    )
    missing = [name for name in fleet.introspect.__all__ if f"## {name}\n" not in page]
    assert missing == []
