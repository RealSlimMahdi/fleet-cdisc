"""ADaM module — imports trigger Polars namespace registration for df.adam."""

from fleet.adam._mixins import MultiRowMixin, SharedADaMVerbsMixin
from fleet.adam.adsl_namespace import ADSLNamespace  # accessed via df.adam.adsl

# Grading sub-package
from fleet.adam.grading import GradingSystem
from fleet.adam.metabolic_namespace import MetabolicNamespace
from fleet.adam.models import ADAMAlgorithm, ADAMDatasetSpec, ADAMVariableSpec
from fleet.adam.namespace import AdamNamespace
from fleet.adam.neuro_namespace import NeuroNamespace
from fleet.adam.occds_namespace import OCCDSNamespace  # accessed via df.adam.occds

# TA-specific namespace classes (accessed via df.adam.<ta>, no longer top-level)
from fleet.adam.onco_namespace import OncoNamespace
from fleet.adam.ophtha_namespace import OphthaNamespace
from fleet.adam.peds_namespace import PedsNamespace
from fleet.adam.pk_namespace import PKNamespace  # accessed via df.adam.pk
from fleet.adam.transforms import (
    clear_transforms,
    get_transform,
    list_transforms,
    register_transform,
)
from fleet.adam.vaccine_namespace import VaccineNamespace

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
    # Grading
    "GradingSystem",
]
