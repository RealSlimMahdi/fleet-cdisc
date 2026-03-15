"""Define-XML module for Fleet."""

from .checker import CheckResult, DatasetChecker, TypeMismatch
from .generator import DefineXMLGenerator
from .spec_generator import DefineSpecGenerator
from .validator import DefineIssue, DefineValidator

__all__ = [
    # Simplified spec workflow
    "DefineSpecGenerator",
    "DatasetChecker",
    "CheckResult",
    "TypeMismatch",
    # Full Pharmaversepy-format workflow
    "DefineIssue",
    "DefineValidator",
    "DefineXMLGenerator",
]
