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
        .flag("ABLFL", criteria='pl.col("VISITNUM") == 1',
              by=["USUBJID", "PARAMCD"])
        .baseline("BASE", aval="AVAL", baseline_flag="ABLFL")
        .chg("CHG", aval="AVAL", base="BASE")
        .to_frame()
    )
"""

# Importing sdtm/adam triggers the @pl.api.register_dataframe_namespace decorators
from typing import TYPE_CHECKING

from . import (
    adam,  # noqa: F401  (registers df.adam)
    sdtm,  # noqa: F401  (registers df.sdtm)
    tlg,  # noqa: F401  (registers df.tlg)
)

# ---------------------------------------------------------------------------
# TYPE_CHECKING augmentation: teach Pylance about .sdtm / .adam / .tlg
# ---------------------------------------------------------------------------
if TYPE_CHECKING:
    import polars as pl

    from fleet.adam.namespace import AdamNamespace as _AdamNS
    from fleet.sdtm.namespace import SDTMNamespace as _SDTMNS
    from fleet.tlg.namespace import TLGNamespace as _TLGNS

    class DataFrame(pl.DataFrame):
        sdtm: _SDTMNS
        adam: _AdamNS
        tlg: _TLGNS


from ._version import __version__
from .adam import (
    ADAMAlgorithm,
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
from .core import (
    PipelineDAG,
    PipelineNode,
    StudyContext,
    build_dag,
    load_study_context,
    to_repr,
)
from .ct import CTValidator, get_validator, import_codelists, load_controlled_terminology

# TA namespace classes are also importable directly for type hints / isinstance
from .define_xml import (
    CheckResult,
    DatasetChecker,
    DefineSpecGenerator,
    DefineValidator,
    DefineXMLGenerator,
    TypeMismatch,
)
from .io import load_datasets, load_raw_data, save_dataset_json, save_parquet
from .sdtm import SDTMAlgorithm, SDTMNamespace
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

__all__ = [
    "__version__",
    # Core
    "StudyContext",
    "load_study_context",
    "build_dag",
    "PipelineDAG",
    "PipelineNode",
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
    "SDTMAlgorithm",
    "SDTMNamespace",
    # ADaM core + sub-structures (accessed via df.adam, df.adam.adsl, df.adam.occds)
    "ADAMAlgorithm",
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
    # Define-XML — full Pharmaversepy-format workflow
    "DefineValidator",
    "DefineXMLGenerator",
    # Validation
    "ValidationResult",
    "ValidationService",
    # Utilities
    "to_repr",
]
