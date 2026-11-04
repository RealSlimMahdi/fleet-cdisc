"""Controlled terminology module."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from fleet.ct.api import CDISCClient, CDISCClientConfig
from fleet.ct.generator import CodelistGenerator
from fleet.ct.loader import create_ct_lookup, load_controlled_terminology
from fleet.ct.validator import CTValidator, get_validator


def import_codelists(
    path: str | Path | None = None,
    *,
    module_name: str = "codelists",
) -> ModuleType:
    """Dynamically import a generated ``codelists.py`` module.

    Resolves the codelist module location using these strategies (in order):

    1. If *path* is given explicitly, use it directly.
    2. Look for ``study_config.yaml`` in the current working directory or in
       a parent folder (git-style, as the CLI does), and resolve the SDTM
       metadata path from it. A program in ``programs/sdtm`` finds the
       study at the root.
    3. Fall back to ``metadata/sdtm/codelists.py`` relative to CWD.

    The module is registered in ``sys.modules`` under *module_name* so that
    subsequent ``from codelists import SEX`` statements work as expected
    throughout the session.

    Args:
        path: Explicit path to the ``codelists.py`` file.  When ``None``,
            auto-discovery is attempted.
        module_name: Name to register the module under in ``sys.modules``.
            Defaults to ``"codelists"``.

    Returns:
        The imported codelists module.

    Raises:
        FileNotFoundError: If no ``codelists.py`` could be located.

    Examples:
        Auto-discover from study config::

            from fleet.ct import import_codelists

            ct = import_codelists()
            SEX = ct.SEX

        Or register so bare imports work::

            from fleet.ct import import_codelists

            import_codelists()  # registers as 'codelists' in sys.modules
            from codelists import SEX, RACE  # now works anywhere
    """
    resolved = _resolve_codelists_path(path)
    if not resolved.is_file():
        raise FileNotFoundError(
            f"Codelists module not found at: {resolved}\n"
            "Run `fleet init ct` to generate it, or pass an explicit path."
        )

    spec = importlib.util.spec_from_file_location(module_name, resolved)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec for: {resolved}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _resolve_codelists_path(path: str | Path | None) -> Path:
    """Resolve the codelists.py path from explicit arg or study config."""
    if path is not None:
        return Path(path).resolve()

    from fleet.core.study_context import find_study_config, load_study_context

    config_file = find_study_config()
    if config_file is not None:
        return load_study_context(config_file).codelists_file

    # Fallback: conventional location
    return (Path.cwd() / "metadata" / "sdtm" / "codelists.py").resolve()


__all__ = [
    "CDISCClient",
    "CDISCClientConfig",
    "CTValidator",
    "CodelistGenerator",
    "get_validator",
    "import_codelists",
    "load_controlled_terminology",
    "create_ct_lookup",
]
