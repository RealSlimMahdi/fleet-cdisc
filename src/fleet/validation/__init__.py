"""Validation module for Fleet."""

from fleet.core.exceptions import ValidationSetupError
from fleet.validation.engine import discover_engine, doctor, install_engine, uninstall_engine
from fleet.validation.models import Severity, ValidationIssue, ValidationResult
from fleet.validation.providers import (
    OfficialRulesEngineProvider,
    ValidationProvider,
)
from fleet.validation.run_setup import (
    DEFAULT_IG_VERSIONS,
    SUPPORTED_IG_VERSIONS,
    RunSetup,
    Sweep,
    SweepDataset,
    build_run_setup,
    build_sweep,
    check_ig_version,
    missing_engine_reason,
)
from fleet.validation.service import ValidationService

__all__ = [
    "Severity",
    "ValidationIssue",
    "ValidationResult",
    "ValidationProvider",
    "OfficialRulesEngineProvider",
    "ValidationService",
    "RunSetup",
    "ValidationSetupError",
    "build_run_setup",
    "Sweep",
    "SweepDataset",
    "build_sweep",
    "check_ig_version",
    "missing_engine_reason",
    "DEFAULT_IG_VERSIONS",
    "SUPPORTED_IG_VERSIONS",
    "discover_engine",
    "install_engine",
    "uninstall_engine",
    "doctor",
]
