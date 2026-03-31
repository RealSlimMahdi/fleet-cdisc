"""SDTM module — imports trigger Polars namespace registration."""

from fleet.sdtm._tdd_mixin import TrialDesignMixin
from fleet.sdtm.models import SDTMAlgorithm, SDTMDomainSpec, SDTMVariableSpec
from fleet.sdtm.namespace import SDTMNamespace
from fleet.sdtm.tdd import (
    Epoch,
    TrialArm,
    TrialArms,
    TrialCriteria,
    TrialCriterion,
    TrialElement,
    TrialElements,
    TrialParameter,
    TrialParameters,
    TrialVisit,
    TrialVisits,
    parse_trial_design,
)

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
