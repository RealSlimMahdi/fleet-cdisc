"""Core module: shared utilities and study context."""

from .dag import PinDependency, PipelineDAG, PipelineNode, build_dag
from .exceptions import (
    ComparisonError,
    CTError,
    DerivationError,
    FleetError,
    PinError,
    SchemaError,
    SpecError,
    TLGError,
    ValidationError,
    ValidationSetupError,
    VerbUsageError,
)
from .repr_utils import to_repr
from .scaffolder import parse_ig_dataset, parse_ig_variable  # noqa: F401 — public API
from .study_context import (
    ADAMConfig,
    CTConfig,
    SDTMConfig,
    StudyConfig,
    StudyConfigError,
    StudyContext,
    StudyPathConfig,
    ValidationConfig,
    find_study_config,
    load_study_context,
)

__all__ = [
    "FleetError",
    "DerivationError",
    "VerbUsageError",
    "PinError",
    "CTError",
    "SpecError",
    "TLGError",
    "SchemaError",
    "ValidationError",
    "ValidationSetupError",
    "ComparisonError",
    "StudyConfig",
    "StudyPathConfig",
    "SDTMConfig",
    "ADAMConfig",
    "CTConfig",
    "ValidationConfig",
    "StudyContext",
    "StudyConfigError",
    "find_study_config",
    "load_study_context",
    "build_dag",
    "PinDependency",
    "PipelineDAG",
    "PipelineNode",
    "to_repr",
]
