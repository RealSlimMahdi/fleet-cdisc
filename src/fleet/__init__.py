"""
Fleet — CDISC-compliant clinical data derivation using Polars.

Importing this package registers the following Polars namespace extensions:
  - ``df.sdtm``      — 14 SDTM derivation verbs (BDS/domain mapping)
  - ``df.adam``      — 16 ADaM derivation verbs (BDS datasets)
  - ``df.adsl``      —  6 patient-level verbs (one row per subject)
  - ``df.occds``     —  5 occurrence verbs (one row per event)
  - ``df.onco``      — Oncology (admiralonco-inspired): aval_resp, BOR, filter_pd
  - ``df.ophtha``    — Ophthalmology (admiralophtha): ETDRS/LogMAR, study eye
  - ``df.peds``      — Pediatrics (admiralpeds): age derivations, prematurity
  - ``df.vaccine``   — Vaccine (admiralvaccine): fever, seroconversion, ADIS AVAL
  - ``df.metabolic`` — Metabolic (admiralmetabolic): waist ratios, body fat %
  - ``df.neuro``     — Neuroscience (admiralneuro): Centiloid, MMSE, CDR-SoB

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

from ._version import __version__

# Importing sdtm/adam triggers the @pl.api.register_dataframe_namespace decorators
from . import sdtm  # noqa: F401
from . import adam  # noqa: F401

from .core import (
    StudyContext,
    load_study_context,
    build_dag,
    PipelineDAG,
    PipelineNode,
)
from .ct import CTValidator, get_validator, load_controlled_terminology
from .io import load_raw_data, load_datasets, save_parquet
from .sdtm import SDTMAlgorithm, SDTMNamespace
from .adam import (
    ADAMAlgorithm, AdamNamespace, ADSLNamespace, OCCDSNamespace,
    OncoNamespace, OphthaNamespace, PedsNamespace,
    VaccineNamespace, MetabolicNamespace, NeuroNamespace,
)
from .define_xml import (
    CheckResult, DatasetChecker, TypeMismatch,
    DefineSpecGenerator,
    DefineValidator, DefineXMLGenerator,
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
    "load_controlled_terminology",
    # IO
    "load_raw_data",
    "load_datasets",
    "save_parquet",
    # SDTM
    "SDTMAlgorithm",
    "SDTMNamespace",
    # ADaM core
    "ADAMAlgorithm",
    "AdamNamespace",
    "ADSLNamespace",
    "OCCDSNamespace",
    # ADaM TA extensions
    "OncoNamespace",
    "OphthaNamespace",
    "PedsNamespace",
    "VaccineNamespace",
    "MetabolicNamespace",
    "NeuroNamespace",
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
