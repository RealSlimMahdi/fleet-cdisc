"""Core exceptions for fleet."""


class FleetError(Exception):
    """Base exception for all fleet errors."""


class SDTMError(FleetError):
    """Raised when SDTM namespace operations fail."""


class ADAMError(FleetError):
    """Raised when ADaM namespace operations fail."""


class CTError(FleetError):
    """Raised when controlled terminology operations fail."""


class IOError(FleetError):  # noqa: A001
    """Raised when data loading or saving fails."""


class SpecError(FleetError):
    """Raised when a YAML specification is invalid."""


class ValidationError(FleetError):
    """Raised when CDISC validation encounters a fatal error."""


class TLGError(FleetError):
    """Raised when TLG namespace operations fail."""


class SchemaError(TLGError):
    """Raised when a DataFrame fails TLG spec validation."""
