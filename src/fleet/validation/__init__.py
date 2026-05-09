"""Validation module for Fleet."""

from fleet.validation.engine import discover_engine, doctor, install_engine, uninstall_engine
from fleet.validation.models import Severity, ValidationIssue, ValidationResult
from fleet.validation.providers import (
    OfficialRulesEngineProvider,
    ValidationProvider,
    ValidationProviderRegistry,
)
from fleet.validation.service import ValidationService

__all__ = [
    "Severity",
    "ValidationIssue",
    "ValidationResult",
    "ValidationProvider",
    "OfficialRulesEngineProvider",
    "ValidationProviderRegistry",
    "ValidationService",
    "discover_engine",
    "install_engine",
    "uninstall_engine",
    "doctor",
]
