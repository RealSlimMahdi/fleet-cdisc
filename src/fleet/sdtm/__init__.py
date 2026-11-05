"""SDTM module — imports trigger Polars namespace registration."""

from fleet.sdtm._tdd_mixin import TrialDesignMixin
from fleet.sdtm.design import StudyDesign
from fleet.sdtm.models import NSVMeta, SDTMAlgorithm, SDTMVariableSpec
from fleet.sdtm.namespace import SDTMNamespace
from fleet.sdtm.tdd import (
    Epoch,
    TrialArm,
    TrialArms,
    TrialCriteria,
    TrialCriterion,
    TrialDiseaseAssessment,
    TrialDiseaseAssessments,
    TrialElement,
    TrialElements,
    TrialMilestone,
    TrialMilestones,
    TrialParameter,
    TrialParameters,
    TrialVisit,
    TrialVisits,
    parse_trial_design,
)
from fleet.sdtm.tdd_audit import audit as trial_design_audit

__all__ = [
    "NSVMeta",
    "SDTMAlgorithm",
    "SDTMVariableSpec",
    "SDTMNamespace",
    "Epoch",
    "StudyDesign",
    "TrialArm",
    "TrialArms",
    "TrialCriterion",
    "TrialCriteria",
    "TrialDesignMixin",
    "TrialDiseaseAssessment",
    "TrialDiseaseAssessments",
    "TrialElement",
    "TrialElements",
    "TrialMilestone",
    "TrialMilestones",
    "TrialParameter",
    "TrialParameters",
    "TrialVisit",
    "TrialVisits",
    "parse_trial_design",
    "trial_design_audit",
]
