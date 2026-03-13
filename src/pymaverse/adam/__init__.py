"""ADaM module — imports trigger Polars namespace registration."""

from .models import ADAMAlgorithm, ADAMDatasetSpec, ADAMVariableSpec
from .namespace import AdamNamespace
from .adsl_namespace import ADSLNamespace       # registers df.adsl
from .occds_namespace import OCCDSNamespace     # registers df.occds
# TA-specific namespace extensions
from .onco_namespace import OncoNamespace       # registers df.onco
from .ophtha_namespace import OphthaNamespace   # registers df.ophtha
from .peds_namespace import PedsNamespace       # registers df.peds
from .vaccine_namespace import VaccineNamespace  # registers df.vaccine
from .metabolic_namespace import MetabolicNamespace  # registers df.metabolic
from .neuro_namespace import NeuroNamespace     # registers df.neuro

__all__ = [
    "ADAMAlgorithm",
    "ADAMDatasetSpec",
    "ADAMVariableSpec",
    "AdamNamespace",
    "ADSLNamespace",
    "OCCDSNamespace",
    # TA namespaces
    "OncoNamespace",
    "OphthaNamespace",
    "PedsNamespace",
    "VaccineNamespace",
    "MetabolicNamespace",
    "NeuroNamespace",
]
