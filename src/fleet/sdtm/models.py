"""SDTM data models: algorithm enum and YAML specification structures."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class SDTMAlgorithm(StrEnum):
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
    DATE = "date"
    DURATION = "duration"


class SDTMVariableSpec(BaseModel):
    """Specification for a single SDTM variable derivation."""

    target: str
    algorithm: SDTMAlgorithm

    # assign_no_ct / assign_ct / assign_dtc
    source: str | None = None

    # assign_ct / hardcode_ct
    ct_codelist: str | None = None
    ct_mapping: dict[str, str] | None = None

    # hardcode_no_ct / hardcode_ct / dataset_level
    value: Any | None = None

    # condition_add
    condition: str | None = None
    then_value: str | None = None

    # if_then_else
    when: list[dict[str, str]] | None = None
    else_value: str | None = None

    # ae_aerel
    aerel_source: str | None = None
    aerel_map: dict[str, str] | None = None

    # merge
    merge_dataset: str | None = None
    merge_key: str | list[str] | None = None
    merge_columns: list[str] | None = None

    # remove_dup
    keep: str = "first"
    subset_vars: list[str] | None = None

    # group_by
    group_cols: list[str] | None = None
    agg_expr: str | None = None

    # multiple_responses
    delimiter: str | None = None

    # assign_dtc
    input_format: str | None = None  # e.g. "%Y-%m-%d"
    output_format: str | None = None  # e.g. "ISO8601"

    model_config = {"extra": "allow"}


class SDTMDomainSpec(BaseModel):
    """Full specification for an SDTM domain derivation."""

    domain: str
    description: str | None = None
    variables: list[SDTMVariableSpec]

    model_config = {"extra": "allow"}
