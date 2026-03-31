"""Criteria registry — discover and load bundled grading JSON files."""

from __future__ import annotations

import json
from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from fleet.adam.grading._models import CriteriaFile

_CRITERIA_DIR: Path = Path(__file__).parent / "criteria"


class GradingSystem(StrEnum):
    """Supported toxicity-grading systems."""

    CTCAE_V4 = "ctcae_v4"
    CTCAE_V4_USCV = "ctcae_v4_uscv"
    CTCAE_V5 = "ctcae_v5"
    CTCAE_V5_USCV = "ctcae_v5_uscv"
    CTCAE_V6 = "ctcae_v6"
    CTCAE_V6_USCV = "ctcae_v6_uscv"
    DAIDS = "daids"
    DAIDS_USCV = "daids_uscv"


_REGISTRY: dict[GradingSystem, str] = {
    GradingSystem.CTCAE_V4: "ctcae_v4.json",
    GradingSystem.CTCAE_V4_USCV: "ctcae_v4_uscv.json",
    GradingSystem.CTCAE_V5: "ctcae_v5.json",
    GradingSystem.CTCAE_V5_USCV: "ctcae_v5_uscv.json",
    GradingSystem.CTCAE_V6: "ctcae_v6.json",
    GradingSystem.CTCAE_V6_USCV: "ctcae_v6_uscv.json",
    GradingSystem.DAIDS: "daids.json",
    GradingSystem.DAIDS_USCV: "daids_uscv.json",
}


def _is_file_path(value: str) -> bool:
    return "/" in value or value.endswith(".json")


@lru_cache(maxsize=32)
def _load_from_path(resolved: str) -> CriteriaFile:
    """Load and validate a criteria JSON file (cached by resolved path)."""
    path = Path(resolved)
    if not path.exists():
        raise FileNotFoundError(f"Criteria file not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return CriteriaFile.model_validate(raw)


def load_criteria(system: str | GradingSystem | Path) -> CriteriaFile:
    """Load and validate a grading-criteria file.

    Args:
        system: A ``GradingSystem`` enum member, its string value
            (e.g. ``"ctcae_v5"``), or a file-system path to a custom
            JSON criteria file.

    Returns:
        CriteriaFile: Validated criteria ready for the grading engine.

    Raises:
        ValueError: If *system* is a string that does not match any
            registered ``GradingSystem`` and is not a file path.
        FileNotFoundError: If the resolved JSON file does not exist.

    Examples:
        Load a bundled system by enum::

            criteria = load_criteria(GradingSystem.CTCAE_V5)

        Load by string shorthand::

            criteria = load_criteria("ctcae_v5")

        Load a custom file::

            criteria = load_criteria("./my_criteria/custom.json")
    """
    if isinstance(system, Path):
        return _load_from_path(str(system.resolve()))

    if isinstance(system, GradingSystem):
        path = _CRITERIA_DIR / _REGISTRY[system]
        return _load_from_path(str(path.resolve()))

    # Plain string — either a file path or a system name.
    if _is_file_path(system):
        return _load_from_path(str(Path(system).resolve()))

    try:
        gs = GradingSystem(system)
    except ValueError:
        known = ", ".join(s.value for s in GradingSystem)
        raise ValueError(f"Unknown grading system {system!r}. Available systems: {known}") from None

    path = _CRITERIA_DIR / _REGISTRY[gs]
    return _load_from_path(str(path.resolve()))


def list_systems() -> list[str]:
    """Return the names of all registered grading systems.

    Returns:
        list[str]: Sorted system-name strings (e.g. ``["ctcae_v4", ...]``).
    """
    return sorted(s.value for s in GradingSystem)
