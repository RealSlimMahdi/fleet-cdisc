"""Define-XML module for Fleet."""

from fleet.define_xml.checker import CheckResult, DatasetChecker, TypeMismatch
from fleet.define_xml.generator import DefineXMLGenerator
from fleet.define_xml.spec_generator import DefineSpecGenerator
from fleet.define_xml.validator import DefineIssue, DefineValidator

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
