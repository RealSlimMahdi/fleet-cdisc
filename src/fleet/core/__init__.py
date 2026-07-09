"""Core module: shared utilities and study context."""

from .dag import PinDependency, PipelineDAG, PipelineNode, build_dag
from .exceptions import (
    ADAMError,
    CTError,
    DerivationError,
    FleetError,
    PinError,
    SchemaError,
    SDTMError,
    SpecError,
    TLGError,
    ValidationError,
    VerbUsageError,
)
from .repr_utils import to_repr
from .scaffolder import parse_ig_dataset, parse_ig_variable  # noqa: F401 — public API
from .study_context import (
    ADAMConfig,
    CTConfig,
    SDTMConfig,
    StudyConfig,
    StudyContext,
    StudyPathConfig,
    ValidationConfig,
    load_study_context,
)
from .study_context import StudyConfigError as StudyContextError

__all__ = [
    "FleetError",
    "DerivationError",
    "VerbUsageError",
    "PinError",
    "SDTMError",
    "ADAMError",
    "CTError",
    "SpecError",
    "TLGError",
    "SchemaError",
    "ValidationError",
    "StudyConfig",
    "StudyPathConfig",
    "SDTMConfig",
    "ADAMConfig",
    "CTConfig",
    "ValidationConfig",
    "StudyContext",
    "StudyContextError",
    "load_study_context",
    "build_dag",
    "PinDependency",
    "PipelineDAG",
    "PipelineNode",
    "to_repr",
]
