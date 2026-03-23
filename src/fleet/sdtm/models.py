"""SDTM data models: algorithm enum and YAML specification structures."""

from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, field_validator


class SDTMAlgorithm(str, Enum):
    """Derivation verbs for SDTM variable mappings."""
    ASSIGN_NO_CT = "assign_no_ct"
    ASSIGN_CT = "assign_ct"
    ASSIGN_DTC = "assign_dtc"
    ASSIGN_DATETIME = "assign_datetime"  # legacy alias
    HARDCODE_CT = "hardcode_ct"
    HARDCODE_NO_CT = "hardcode_no_ct"
    CONDITION_ADD = "condition_add"
    IF_THEN_ELSE = "if_then_else"
    AE_AEREL = "ae_aerel"
    MERGE = "merge"
    REMOVE_DUP = "remove_dup"
    GROUP_BY = "group_by"
    DATASET_LEVEL = "dataset_level"
    NOTSUBMITTED = "notsubmitted"
    MULTIPLE_RESPONSES = "multiple_responses"


class SDTMVariableSpec(BaseModel):
    """Specification for a single SDTM variable derivation."""
    target: str
    algorithm: SDTMAlgorithm

    # assign_no_ct / assign_ct / assign_dtc
    source: Optional[str] = None

    # assign_ct / hardcode_ct
    ct_codelist: Optional[str] = None
    ct_mapping: Optional[dict[str, str]] = None

    # hardcode_no_ct / hardcode_ct / dataset_level
    value: Optional[Any] = None

    # condition_add
    condition: Optional[str] = None
    then_value: Optional[str] = None

    # if_then_else
    when: Optional[list[dict[str, str]]] = None
    else_value: Optional[str] = None

    # ae_aerel
    aerel_source: Optional[str] = None
    aerel_map: Optional[dict[str, str]] = None

    # merge
    merge_dataset: Optional[str] = None
    merge_key: Optional[str | list[str]] = None
    merge_columns: Optional[list[str]] = None

    # remove_dup
    keep: str = "first"
    subset_vars: Optional[list[str]] = None

    # group_by
    group_cols: Optional[list[str]] = None
    agg_expr: Optional[str] = None

    # multiple_responses
    delimiter: Optional[str] = None

    # assign_dtc
    input_format: Optional[str] = None   # e.g. "%Y-%m-%d"
    output_format: Optional[str] = None  # e.g. "ISO8601"

    model_config = {"extra": "allow"}


class SDTMDomainSpec(BaseModel):
    """Full specification for an SDTM domain derivation."""
    domain: str
    description: Optional[str] = None
    variables: list[SDTMVariableSpec]

    model_config = {"extra": "allow"}
