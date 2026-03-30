"""
TLG specification models — Vega-Lite-inspired declarative specs.

Each TLG output (AE summary, AE listing, VS summary, etc.) is defined by
a Pydantic model that declares field→role mappings, statistics, and data
requirements.  The spec carries both structural validation (column
presence/types) and content validation (required PARAM/PARAMCD values,
flag values, pool arm existence).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

import polars as pl
import yaml
from pydantic import BaseModel

from ..core.exceptions import SchemaError


class Statistic(str, Enum):  # noqa: UP042
    """Statistics available for summary tables."""

    N_SUBJECTS = "n_subjects"
    N_EVENTS = "n_events"
    N_PCT = "n_pct"
    MEAN = "mean"
    SD = "sd"
    MEDIAN = "median"
    MIN = "min"
    MAX = "max"
    Q1 = "q1"
    Q3 = "q3"


class Row(BaseModel):
    """A row-level field mapping for a summary table."""

    field: str
    label: str | None = None
    filter_value: str | None = None

    model_config = {"extra": "forbid"}


class Column(BaseModel):
    """A column specification for a listing."""

    field: str
    label: str | None = None
    format: str | None = None

    model_config = {"extra": "forbid"}


class GroupPool(BaseModel):
    """A composite treatment group (pooled arms).

    Args:
        label: Display label for the pooled group.
        arms: List of arm labels to combine, or ``"*"`` for all arms.
    """

    label: str
    arms: list[str] | Literal["*"]

    model_config = {"extra": "forbid"}


class TLGSpec(BaseModel):
    """Base specification for all TLG outputs.

    Subclasses define output-type-specific defaults and required columns.
    """

    output_type: str = "base"
    filter: Any | None = None
    required_columns: list[str] = []
    required_flags: dict[str, list[str]] = {}

    model_config = {"extra": "forbid", "arbitrary_types_allowed": True}

    def validate_dataframe(self, df: pl.DataFrame) -> None:
        """Run structural + content validation against *df*.

        Raises:
            SchemaError: If required columns are missing, required flag
                values are absent, or other data constraints are violated.
        """
        self._validate_structural(df)
        self._validate_content(df)

    def _validate_structural(self, df: pl.DataFrame) -> None:
        """Tier 1: check required columns exist."""
        available = set(df.columns)
        missing = [c for c in self.required_columns if c not in available]
        if missing:
            raise SchemaError(
                f"{self.__class__.__name__} requires columns {self.required_columns} "
                f"but DataFrame is missing {missing}. "
                f"Available: {sorted(available)}"
            )

    def _validate_content(self, df: pl.DataFrame) -> None:
        """Tier 2: check required flag/PARAMCD values exist in data."""
        for col, required_vals in self.required_flags.items():
            if col not in df.columns:
                raise SchemaError(
                    f"{self.__class__.__name__} requires column '{col}' for "
                    f"content validation but it is missing."
                )
            actual = set(df[col].drop_nulls().unique().to_list())
            missing = [v for v in required_vals if v not in actual]
            if missing:
                raise SchemaError(
                    f"{self.__class__.__name__} requires {col} values "
                    f"{required_vals} but data is missing {missing}. "
                    f"Available: {sorted(actual)}"
                )

    def check(self, df: pl.DataFrame) -> list[str]:
        """Pre-validation diagnostic — returns warnings without raising.

        Args:
            df: The DataFrame to check.

        Returns:
            list[str]: Diagnostic messages (empty if all checks pass).
        """
        diagnostics: list[str] = []
        available = set(df.columns)
        missing = [c for c in self.required_columns if c not in available]
        if missing:
            diagnostics.append(
                f"MISSING COLUMNS: {missing} required by {self.__class__.__name__} are not present."
            )
        for col, required_vals in self.required_flags.items():
            if col not in available:
                diagnostics.append(f"MISSING FLAG COLUMN: '{col}' not in DataFrame.")
            else:
                actual = set(df[col].drop_nulls().unique().to_list())
                absent = [v for v in required_vals if v not in actual]
                if absent:
                    diagnostics.append(f"MISSING VALUES: {col} missing {absent}.")
        return diagnostics

    def to_yaml(self) -> str:
        """Serialize this spec to a YAML string.

        Returns:
            str: YAML representation of the spec.
        """
        data = self.model_dump(exclude_none=True, exclude_defaults=False)
        # Remove filter (not YAML-serializable as Polars Expr)
        data.pop("filter", None)
        # Convert enums to their values
        data = _enum_to_value(data)
        return yaml.dump(data, default_flow_style=False, sort_keys=False)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> TLGSpec:
        """Deserialize a spec from a YAML string.

        Args:
            yaml_str: YAML text.

        Returns:
            TLGSpec: The reconstructed spec instance.
        """
        data = yaml.safe_load(yaml_str)
        return cls.model_validate(data)


class AESummarySpec(TLGSpec):
    """Spec for an AE summary table (t_ae_summary).

    Defaults provide zero-config convenience for a standard SOC→PT table.
    """

    output_type: str = "summary"
    rows: list[Row] = [
        Row(field="AEBODSYS", label="System Organ Class"),
        Row(field="AEDECOD", label="Preferred Term"),
    ]
    columns: list[str] = ["TRTA"]
    statistics: list[Statistic] = [Statistic.N_SUBJECTS, Statistic.N_PCT]
    pools: list[GroupPool] = []
    column_order: list[str] = []
    denominator: str = "TRTA"
    required_columns: list[str] = ["USUBJID", "TRTA", "AEDECOD", "AEBODSYS"]


class AEListingSpec(TLGSpec):
    """Spec for an AE listing (l_ae_listing)."""

    output_type: str = "listing"
    columns: list[Column] = [
        Column(field="USUBJID", label="Subject"),
        Column(field="TRTA", label="Treatment"),
        Column(field="AEBODSYS", label="SOC"),
        Column(field="AEDECOD", label="Preferred Term"),
        Column(field="AESEV", label="Severity"),
        Column(field="AESER", label="Serious"),
    ]
    sort_by: list[str] = ["USUBJID", "AEBODSYS", "AEDECOD"]
    required_columns: list[str] = ["USUBJID", "TRTA", "AEDECOD"]


class VSSummarySpec(TLGSpec):
    """Spec for a vital-signs summary table."""

    output_type: str = "summary"
    rows: list[Row] = [
        Row(field="PARAMCD", label="Parameter"),
    ]
    columns: list[str] = ["TRTA"]
    statistics: list[Statistic] = [
        Statistic.N_SUBJECTS,
        Statistic.MEAN,
        Statistic.SD,
        Statistic.MEDIAN,
        Statistic.MIN,
        Statistic.MAX,
    ]
    pools: list[GroupPool] = []
    column_order: list[str] = []
    denominator: str = "TRTA"
    required_columns: list[str] = ["USUBJID", "TRTA", "PARAMCD", "AVAL"]
    required_flags: dict[str, list[str]] = {}


def _enum_to_value(obj: Any) -> Any:
    """Recursively convert Enum instances to their ``.value``."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: _enum_to_value(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_enum_to_value(v) for v in obj]
    return obj
