"""Define-XML module for Fleet."""

from fleet.define_xml.checker import CheckResult, DatasetChecker, TypeMismatch
from fleet.define_xml.generator import DefineXMLGenerator
from fleet.define_xml.semantic_checks import semantic_errors
from fleet.define_xml.spec_generator import DefineSpecGenerator
from fleet.define_xml.validator import DefineIssue, DefineValidator
from fleet.define_xml.xsd import validate_define_xml

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
    # Validation of generated Define-XML (structure + reviewer-facing content)
    "validate_define_xml",
    "semantic_errors",
]
