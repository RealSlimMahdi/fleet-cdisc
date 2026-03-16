"""ADaM module — imports trigger Polars namespace registration for df.adam."""

from ._mixins import MultiRowMixin, SharedADaMVerbsMixin
from .adsl_namespace import ADSLNamespace  # accessed via df.adam.adsl
from .metabolic_namespace import MetabolicNamespace
from .models import ADAMAlgorithm, ADAMDatasetSpec, ADAMVariableSpec
from .namespace import AdamNamespace
from .neuro_namespace import NeuroNamespace
from .occds_namespace import OCCDSNamespace  # accessed via df.adam.occds

# TA-specific namespace classes (accessed via df.adam.<ta>, no longer top-level)
from .onco_namespace import OncoNamespace
from .ophtha_namespace import OphthaNamespace
from .peds_namespace import PedsNamespace
from .pk_namespace import PKNamespace  # accessed via df.adam.pk
from .transforms import clear_transforms, get_transform, list_transforms, register_transform
from .vaccine_namespace import VaccineNamespace

__all__ = [
    # Mixins
    "SharedADaMVerbsMixin",
    "MultiRowMixin",
    # Spec models
    "ADAMAlgorithm",
    "ADAMDatasetSpec",
    "ADAMVariableSpec",
    "AdamNamespace",
    "ADSLNamespace",
    "OCCDSNamespace",
    "PKNamespace",
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
