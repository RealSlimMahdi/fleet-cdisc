"""ADaM data models: algorithm enum and YAML specification structures."""

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel


class ADAMAlgorithm(str, Enum):
    """Derivation verbs for ADaM variable derivations."""

    # Base verbs
    SOURCE = "source"
    DERIVATION = "derivation"
    ASSIGNED = "assigned"
    RECODE = "recode"
    RENAME = "rename"
    CONDDERIVATION = "condderivation"
    LOOKUP = "lookup"
    STD_FUNCTION = "std_function"  # YAML backward compat; dispatches to typed methods
    WHERECLAUSES = "whereclauses"
    # BDS first-class methods (also valid as direct YAML algorithm keys)
    STUDY_DAY = "study_day"
    BASELINE = "baseline"
    CHG = "chg"
    PCHG = "pchg"
    FLAG = "flag"
    BMI = "bmi"
    NRIND = "nrind"
    ON_TREATMENT = "on_treatment"
    SHIFT = "shift"
    ATOXGR = "atoxgr"
    COMBINE_GRADES = "combine_grades"


class ADAMVariableSpec(BaseModel):
    """Specification for a single ADaM variable derivation."""

    target: str
    algorithm: ADAMAlgorithm

    # source / rename
    source: Optional[str] = None

    # derivation / assigned
    expression: Optional[str] = None
    value: Optional[Any] = None

    # recode
    recode_map: Optional[dict[str, Any]] = None
    default: Optional[Any] = None

    # condderivation
    conditions: Optional[list[dict[str, Any]]] = None
    else_value: Optional[Any] = None

    # lookup
    lookup_dataset: Optional[str] = None
    lookup_key: Optional[str | list[str]] = None
    lookup_columns: Optional[list[str]] = None
    lookup_where: Optional[str] = None

    # std_function / study_day
    func: Optional[str] = None
    analysis_date: Optional[str] = None
    reference_date: Optional[str] = None
    aval: Optional[str] = None
    base: Optional[str] = None
    height: Optional[str] = None
    weight: Optional[str] = None
    baseline_flag: Optional[str] = None
    baseline_criteria: Optional[str] = None
    groups: Optional[list[str]] = None  # shared partition columns

    # flag()
    criteria: Optional[str] = None  # row expression or "first"/"last"/"max"/"min"
    flag_order_by: Optional[str] = None  # column for first/last ordering
    flag_value_col: Optional[str] = None  # column for max/min comparison
    flag_where: Optional[str] = None  # candidate pre-filter expression
    flag_value: str = "Y"

    # nrind()
    low: Optional[str] = None  # lower normal range column
    high: Optional[str] = None  # upper normal range column

    # on_treatment()
    trtedt: Optional[str] = None  # end-of-treatment date column

    # shift()
    baseline_cat: Optional[str] = None  # baseline category column
    post_cat: Optional[str] = None  # post-baseline category column

    # atoxgr()
    system: Optional[str] = None  # grading system (e.g. "ctcae_v5")
    direction: Optional[str] = None  # "L" or "H"
    term_var: Optional[str] = None  # toxicity description variable
    unit_var: Optional[str] = None  # unit of measure variable
    high_indicator: Optional[list[str]] = None  # BNRIND values for high baseline
    low_indicator: Optional[list[str]] = None  # BNRIND values for low baseline
    signif_dig: int = 5  # significant figures for comparison

    # combine_grades()
    low_var: Optional[str] = None  # low-direction grade column
    high_var: Optional[str] = None  # high-direction grade column
    low_desc_var: Optional[str] = None  # low-direction description column
    high_desc_var: Optional[str] = None  # high-direction description column

    # whereclauses
    where: Optional[str] = None

    # auto-staging: columns that must be committed to the frame before this derivation runs
    depends_on: Optional[list[str]] = None

    model_config = {"extra": "allow"}


class ADAMDatasetSpec(BaseModel):
    """Full specification for an ADaM dataset derivation."""

    dataset: str
    description: Optional[str] = None
    variables: list[ADAMVariableSpec]

    model_config = {"extra": "allow"}
