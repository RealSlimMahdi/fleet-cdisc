"""Core exceptions for pymaverse."""


class PymaverseError(Exception):
    """Base exception for all pymaverse errors."""


class SDTMError(PymaverseError):
    """Raised when SDTM namespace operations fail."""


class ADAMError(PymaverseError):
    """Raised when ADaM namespace operations fail."""


class CTError(PymaverseError):
    """Raised when controlled terminology operations fail."""


class IOError(PymaverseError):  # noqa: A001
    """Raised when data loading or saving fails."""


class SpecError(PymaverseError):
    """Raised when a YAML specification is invalid."""


class ValidationError(PymaverseError):
    """Raised when CDISC validation encounters a fatal error."""
