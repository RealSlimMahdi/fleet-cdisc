"""SDTM module — imports trigger Polars namespace registration."""

from .models import SDTMAlgorithm, SDTMDomainSpec, SDTMVariableSpec
from .namespace import SDTMNamespace
from .tdd import (
    Epoch,
    TrialArm,
    TrialArms,
    TrialCriterion,
    TrialCriteria,
    TrialElement,
    TrialElements,
    TrialParameter,
    TrialParameters,
    TrialVisit,
    TrialVisits,
    parse_trial_design,
)
from ._tdd_mixin import TrialDesignMixin

__all__ = [
    "SDTMAlgorithm",
    "SDTMDomainSpec",
    "SDTMVariableSpec",
    "SDTMNamespace",
    "Epoch",
    "TrialArm",
    "TrialArms",
    "TrialCriterion",
    "TrialCriteria",
    "TrialDesignMixin",
    "TrialElement",
    "TrialElements",
    "TrialParameter",
    "TrialParameters",
    "TrialVisit",
    "TrialVisits",
    "parse_trial_design",
]
