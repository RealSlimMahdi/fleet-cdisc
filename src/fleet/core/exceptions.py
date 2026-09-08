"""Core exceptions for fleet.

The verb-layer exceptions use **dual inheritance** so both catch styles
work: ``except FleetError`` (the Fleet-native style) and the legacy
builtin style (``except ValueError`` / ``except TypeError`` /
``except LookupError``) that predates the hierarchy.

* :class:`DerivationError` — a verb received invalid values or arguments
  (missing column, unparseable expression, unsupported option, ...).
  Catchable as ``ValueError``.
* :class:`VerbUsageError` — a verb was called with a wrong *type*.
  Catchable as ``TypeError``.
* :class:`PinError` — a cross-domain verb could not resolve a pinned
  reference domain.  Catchable as ``LookupError``.
"""


class FleetError(Exception):
    """Base exception for all fleet errors."""


class DerivationError(FleetError, ValueError):
    """Raised when a derivation verb receives invalid values or arguments.

    Dual-inherits from ``ValueError`` so legacy ``except ValueError``
    handlers keep working.
    """


class VerbUsageError(FleetError, TypeError):
    """Raised when a verb is called with arguments of the wrong type.

    Dual-inherits from ``TypeError`` so legacy ``except TypeError``
    handlers keep working.
    """


class PinError(FleetError, LookupError):
    """Raised when a pinned reference domain cannot be resolved.

    Dual-inherits from ``LookupError`` so legacy ``except LookupError``
    handlers keep working.
    """


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


class ComparisonError(FleetError, ValueError):
    """Raised when a comparison cannot run: keys missing, duplicated or
    incompatible between the base and the candidate.

    Differences between the two datasets never raise; they are reported.
    Dual-inherits from ``ValueError`` so ``except ValueError`` handlers
    keep working.
    """


class TLGError(FleetError):
    """Raised when TLG namespace operations fail."""


class SchemaError(TLGError):
    """Raised when a DataFrame fails TLG spec validation."""
