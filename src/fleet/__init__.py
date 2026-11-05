"""
Fleet — CDISC-compliant clinical data derivation using Polars.

Importing this package registers the following Polars namespace extensions
(each namespace lists its own verbs — call ``.verbs()`` on any of them,
e.g. ``df.sdtm.verbs()``, for the always-current catalogue):

  - ``df.sdtm``           — SDTM derivation verbs (BDS/domain mapping)
  - ``df.adam``           — ADaM derivation verbs (BDS datasets)
  - ``df.adam.adsl``      — patient-level verbs (one row per subject)
  - ``df.adam.occds``     — occurrence verbs (one row per event)
  - ``df.adam.onco``      — Oncology (admiralonco-inspired)
  - ``df.adam.ophtha``    — Ophthalmology (admiralophtha)
  - ``df.adam.peds``      — Pediatrics (admiralpeds)
  - ``df.adam.vaccine``   — Vaccine (admiralvaccine)
  - ``df.adam.metabolic`` — Metabolic (admiralmetabolic)
  - ``df.adam.neuro``     — Neuroscience (admiralneuro)
  - ``df.adam.pk``        — Pharmacokinetics (ADPC, ADPP)
  - ``df.adam.tte``       — Time-to-event (ADTTE)
  - ``df.tlg``            — Tables, listings and their ARDs (``df.tlg.ae``, …)

The ``sdtm``, ``adam``, ``adsl``, and ``occds`` namespaces are also
registered on ``pl.LazyFrame``, so ``pl.scan_parquet(...).sdtm`` chains
fully lazily.

Usage
-----
    import fleet

    result = (
        raw_df.sdtm
        .assign("USUBJID", source="patient_number")
        .assign("DOMAIN", value="DM")
        .to_frame()
    )

    advs = (
        vs_df.adam
        .source("USUBJID")
        .study_day("ADY", date_col="ADT")
        .flag("ABLFL", criteria='pl.col("VISITNUM") == 1')
        .baseline("BASE", aval="AVAL", baseline_flag="ABLFL")
        .chg("CHG", aval="AVAL", base="BASE")
        .to_frame()
    )
"""

import sys

import polars as _pl

# Importing sdtm/adam triggers the @pl.api.register_dataframe_namespace decorators
from . import (
    adam,  # noqa: F401  (registers df.adam)
    sdtm,  # noqa: F401  (registers df.sdtm)
    tlg,  # noqa: F401  (registers df.tlg)
)
from ._version import __version__
from .adam import (
    AdamNamespace,
    ADSLNamespace,
    MetabolicNamespace,
    NeuroNamespace,
    OCCDSNamespace,
    OncoNamespace,
    OphthaNamespace,
    PedsNamespace,
    VaccineNamespace,
)
from .comparison import ComparisonReport, compare
from .core import (
    PipelineDAG,
    PipelineNode,
    StudyContext,
    build_dag,
    load_study_context,
    to_repr,
)
from .core.frames import DataFrame, LazyFrame, frame
from .core.spec_registry import SPEC_UNSUPPORTED
from .core.spec_registry import algorithm_names as spec_algorithms
from .core.spec_registry import coverage_matrix as spec_coverage
from .ct import CTValidator, get_validator, import_codelists, load_controlled_terminology

# TA namespace classes are also importable directly for type hints / isinstance
from .define_xml import (
    CheckResult,
    DatasetChecker,
    DefineSpecGenerator,
    TypeMismatch,
)
from .io import load_datasets, load_raw_data, save_dataset_json, save_parquet
from .run import BuiltDataset, ResolvedInput, Step, StudyPlan, plan_study, run_study
from .sdtm import SDTMNamespace, StudyDesign
from .tlg import (
    AEListingSpec,
    AESummarySpec,
    AETLGNamespace,
    Column,
    GroupPool,
    Row,
    Statistic,
    TLGNamespace,
    TLGSpec,
    VSSummarySpec,
)
from .validation import ValidationResult, ValidationService


def _check_python_and_polars(python: tuple[int, int], polars: str) -> None:
    """Polars 1.x cannot dispatch Series methods on Python 3.15: they return None."""
    if python >= (3, 15) and polars.startswith("1."):
        raise ImportError(
            f"Fleet needs Python 3.12 to 3.14: Polars {polars} does not work on Python "
            f"{python[0]}.{python[1]}. In a new folder, run: uv init --python 3.12"
        )


# Remove with the polars<2 pin.
_check_python_and_polars(sys.version_info[:2], _pl.__version__)

__all__ = [
    "__version__",
    # Typed entry points (zero-cost casts — see fleet.core.frames)
    "DataFrame",
    "LazyFrame",
    "frame",
    # Core
    "StudyContext",
    "load_study_context",
    # Study run (fleet.run)
    "plan_study",
    "run_study",
    "StudyPlan",
    "Step",
    "BuiltDataset",
    "ResolvedInput",
    "build_dag",
    "PipelineDAG",
    "PipelineNode",
    # Spec registry discovery
    "spec_algorithms",
    "spec_coverage",
    "SPEC_UNSUPPORTED",
    # CT
    "CTValidator",
    "get_validator",
    "import_codelists",
    "load_controlled_terminology",
    # IO
    "load_raw_data",
    "load_datasets",
    "save_parquet",
    "save_dataset_json",
    # SDTM
    "SDTMNamespace",
    "StudyDesign",
    # ADaM core + sub-structures (accessed via df.adam, df.adam.adsl, df.adam.occds)
    "AdamNamespace",
    "ADSLNamespace",
    "OCCDSNamespace",
    # ADaM TA extensions (accessed via df.adam.<ta>)
    "OncoNamespace",
    "OphthaNamespace",
    "PedsNamespace",
    "VaccineNamespace",
    "MetabolicNamespace",
    "NeuroNamespace",
    # TLG namespace (accessed via df.tlg, df.tlg.ae)
    "TLGNamespace",
    "AETLGNamespace",
    "TLGSpec",
    "AESummarySpec",
    "AEListingSpec",
    "VSSummarySpec",
    "Row",
    "Column",
    "Statistic",
    "GroupPool",
    # Define-XML — simplified spec workflow
    "DefineSpecGenerator",
    "DatasetChecker",
    "CheckResult",
    "TypeMismatch",
    # Validation
    "ValidationResult",
    "ValidationService",
    # Comparison (PROC COMPARE analogue)
    "compare",
    "ComparisonReport",
    # Utilities
    "to_repr",
]
