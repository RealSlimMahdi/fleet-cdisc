"""ADaM module — imports trigger Polars namespace registration for df.adam."""

from .models import ADAMAlgorithm, ADAMDatasetSpec, ADAMVariableSpec
from .namespace import AdamNamespace
from .transforms import register_transform, get_transform, list_transforms, clear_transforms
from .adsl_namespace import ADSLNamespace       # accessed via df.adam.adsl
from .occds_namespace import OCCDSNamespace     # accessed via df.adam.occds
# TA-specific namespace classes (accessed via df.adam.<ta>, no longer top-level)
from .onco_namespace import OncoNamespace
from .ophtha_namespace import OphthaNamespace
from .peds_namespace import PedsNamespace
from .vaccine_namespace import VaccineNamespace
from .metabolic_namespace import MetabolicNamespace
from .neuro_namespace import NeuroNamespace

__all__ = [
    "ADAMAlgorithm",
    "ADAMDatasetSpec",
    "ADAMVariableSpec",
    "AdamNamespace",
    "ADSLNamespace",
    "OCCDSNamespace",
    # Transform registry
    "register_transform",
    "get_transform",
    "list_transforms",
    "clear_transforms",
    # TA namespaces
    "OncoNamespace",
    "OphthaNamespace",
    "PedsNamespace",
    "VaccineNamespace",
    "MetabolicNamespace",
    "NeuroNamespace",
]
