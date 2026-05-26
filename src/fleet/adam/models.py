"""ADaM data models: algorithm enum and YAML specification structures."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ADAMAlgorithm(StrEnum):
    """Derivation verbs for ADaM variable derivations."""

    # Base verbs
    SOURCE = "source"
    DERIVATION = "derivation"
    ASSIGNED = "assigned"
    RECODE = "recode"
    RENAME = "rename"
    CONDDERIVATION = "condderivation"
    LOOKUP = "lookup"
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
    DATE = "date"
    DURATION = "duration"
    PICK = "pick"
    CALLABLE = "callable"


class ADAMVariableSpec(BaseModel):
    """Specification for a single ADaM variable derivation."""

    target: str
    algorithm: ADAMAlgorithm

    # source / rename
    source: str | None = None

    # derivation / assigned
    expression: str | None = None
    value: Any | None = None

    # recode
    recode_map: dict[str, Any] | None = None
    default: Any | None = None

    # condderivation
    conditions: list[dict[str, Any]] | None = None
    else_value: Any | None = None

    # lookup
    lookup_dataset: str | None = None
    lookup_key: str | list[str] | None = None
    lookup_columns: list[str] | None = None
    lookup_where: str | None = None

    # std_function / study_day
    func: str | None = None
    analysis_date: str | None = None
    reference_date: str | None = None
    aval: str | None = None
    base: str | None = None
    height: str | None = None
    weight: str | None = None
    baseline_flag: str | None = None
    baseline_criteria: str | None = None
    groups: list[str] | None = None  # shared partition columns

    # flag()
    criteria: str | None = None  # row expression or "first"/"last"/"max"/"min"
    flag_order_by: str | None = None  # column for first/last ordering
    flag_value_col: str | None = None  # column for max/min comparison
    flag_where: str | None = None  # candidate pre-filter expression
    flag_value: str = "Y"

    # nrind()
    low: str | None = None  # lower normal range column
    high: str | None = None  # upper normal range column

    # on_treatment()
    trtedt: str | None = None  # end-of-treatment date column

    # shift()
    baseline_cat: str | None = None  # baseline category column
    post_cat: str | None = None  # post-baseline category column

    # atoxgr()
    system: str | None = None  # grading system (e.g. "ctcae_v5")
    direction: str | None = None  # "L" or "H"
    term_var: str | None = None  # toxicity description variable
    unit_var: str | None = None  # unit of measure variable
    high_indicator: list[str] | None = None  # BNRIND values for high baseline
    low_indicator: list[str] | None = None  # BNRIND values for low baseline
    signif_dig: int = 5  # significant figures for comparison

    # combine_grades()
    low_var: str | None = None  # low-direction grade column
    high_var: str | None = None  # high-direction grade column
    low_desc_var: str | None = None  # low-direction description column
    high_desc_var: str | None = None  # high-direction description column

    # pick()
    events: list[dict[str, Any]] | None = None  # ordered event dicts for pick()
    by: list[str] | None = None  # grouping columns for pick()
    order: str | list[str] | None = None  # sort order for pick()
    mode: str | None = None  # "first" or "last" for pick()
    targets: list[str] | None = None  # multi-target list for pick()

    # whereclauses
    where: str | None = None

    # callable: reference to a registered Derivation or dotted-import path
    callable_ref: str | None = Field(None, alias="callable")

    # auto-staging: columns that must be committed to the frame before this derivation runs
    depends_on: list[str] | None = None

    model_config = {"extra": "allow", "populate_by_name": True}


class ADAMDatasetSpec(BaseModel):
    """Full specification for an ADaM dataset derivation."""

    dataset: str
    description: str | None = None
    variables: list[ADAMVariableSpec]

    model_config = {"extra": "allow"}
