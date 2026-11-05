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


class CTNotFoundError(CTError, LookupError):
    """Raised when the CDISC Library has no such resource (HTTP 404), unlike a 401 or a network error."""


class IOError(FleetError):  # noqa: A001
    """Raised when data loading or saving fails."""


class SpecError(FleetError):
    """Raised when a YAML specification is invalid."""


class SpecSchemaError(SpecError, ValueError):
    """Raised when a define.yaml fails its JSON schema.

    A ``ValueError`` too, so code written for the earlier ``ValueError``
    keeps working; the CLI prints it as one clean message, with no traceback.
    """


class ValidationError(FleetError):
    """Raised when CDISC validation encounters a fatal error."""


class ValidationSetupError(FleetError, ValueError):
    """Raised when a validation could not run: its run setup was refused.

    Examples: the namespace and the dataset name point to different
    standards, or the IG version is not supported.  The verb raises it in
    every ``on_fail`` mode, because no rule was reached.
    """


class StudyRunError(FleetError):
    """Raised when a study run cannot plan or build a dataset.

    Examples: no define file under the study's metadata directories, a
    dataset name the define files do not declare, an input that no seed,
    earlier step, declared path or data directory provides, or a seed
    that is also a step of the plan.
    """


class ComparisonError(FleetError, ValueError):
    """Raised when a comparison cannot run: keys missing, duplicated or
    incompatible between the base and the candidate.

    Differences between the two datasets never raise from
    :func:`fleet.compare`; they are reported.  The pipeline verb
    ``.compare(..., on_fail="raise")`` is the one place that turns a
    difference into this error, on request.  Dual-inherits from
    ``ValueError`` so ``except ValueError`` handlers keep working.
    """


class ComparisonFailed(ComparisonError):  # noqa: N818
    """Raised by ``.compare(..., on_fail="raise")`` when the datasets differ.

    This is the QC finding: the comparison ran and the result is NOT
    EQUAL.  A comparison that could not run raises the parent
    :class:`ComparisonError`, so ``except ComparisonFailed`` catches the
    finding only.
    """


class TLGError(FleetError):
    """Raised when TLG namespace operations fail."""


class SchemaError(TLGError):
    """Raised when a DataFrame fails TLG spec validation."""
