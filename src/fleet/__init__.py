"""
Fleet — CDISC-compliant clinical data derivation using Polars.

Importing this package registers the following Polars namespace extensions:
  - ``df.sdtm``           — 14 SDTM derivation verbs (BDS/domain mapping)
  - ``df.adam``           — 16 ADaM derivation verbs (BDS datasets)
  - ``df.adam.adsl``      —  6 patient-level verbs (one row per subject)
  - ``df.adam.occds``     —  5 occurrence verbs (one row per event)
  - ``df.adam.onco``      — Oncology (admiralonco-inspired)
  - ``df.adam.ophtha``    — Ophthalmology (admiralophtha)
  - ``df.adam.peds``      — Pediatrics (admiralpeds)
  - ``df.adam.vaccine``   — Vaccine (admiralvaccine)
  - ``df.adam.metabolic`` — Metabolic (admiralmetabolic)
  - ``df.adam.neuro``     — Neuroscience (admiralneuro)

Usage
-----
    import fleet

    result = (
        raw_df.sdtm
        .assign_no_ct("USUBJID", source="patient_number")
        .hardcode_no_ct("DOMAIN", value="DM")
        .to_frame()
    )

    advs = (
        vs_df.adam
        .source("USUBJID")
        .study_day("ADY", analysis_date="ADT", reference_date="TRTSDT")
        .flag("ABLFL", criteria='pl.col("VISITNUM") == 1',
              groups=["USUBJID", "PARAMCD"])
        .baseline("BASE", aval="AVAL", baseline_flag="ABLFL")
        .chg("CHG", aval="AVAL", base="BASE")
        .to_frame()
    )
"""

# Importing sdtm/adam triggers the @pl.api.register_dataframe_namespace decorators
from fleet import (
    adam,  # noqa: F401  (registers df.adam)
    sdtm,  # noqa: F401  (registers df.sdtm)
    tlg,  # noqa: F401  (registers df.tlg)
)
from fleet._version import __version__
from fleet.adam import (
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
from fleet.core import (
    PipelineDAG,
    PipelineNode,
    StudyContext,
    build_dag,
    load_study_context,
)
from fleet.ct import CTValidator, get_validator, load_controlled_terminology

# TA namespace classes are also importable directly for type hints / isinstance
from fleet.define_xml import (
    CheckResult,
    DatasetChecker,
    DefineSpecGenerator,
    DefineValidator,
    DefineXMLGenerator,
    TypeMismatch,
)
from fleet.io import load_datasets, load_raw_data, save_parquet
from fleet.sdtm import SDTMAlgorithm, SDTMNamespace
from fleet.tlg import (
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
from fleet.validation import ValidationResult, ValidationService

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
    "load_controlled_terminology",
    # IO
    "load_raw_data",
    "load_datasets",
    "save_parquet",
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
]
