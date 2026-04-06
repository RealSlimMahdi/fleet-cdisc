"""Core module: shared utilities and study context."""

from .dag import PipelineDAG, PipelineNode, build_dag
from .exceptions import (
    ADAMError,
    CTError,
    FleetError,
    SchemaError,
    SDTMError,
    SpecError,
    TLGError,
    ValidationError,
)
from .scaffolder import parse_ig_dataset, parse_ig_variable
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
    "PipelineDAG",
    "PipelineNode",
]
