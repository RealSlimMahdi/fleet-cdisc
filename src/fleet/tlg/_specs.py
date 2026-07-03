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
from pydantic import BaseModel, Field

from fleet.core.exceptions import SchemaError
from fleet.sdtm.utils import parse_expression


def resolve_filter(value: Any) -> pl.Expr | None:
    """Resolve a spec filter field to a Polars expression.

    Filters may be given as a ``pl.Expr`` (inline use) or as a string
    expression such as ``'pl.col("SAFFL") == "Y"'`` — the string form is
    the YAML-serializable one, parsed through the same AST-whitelisted
    ``parse_expression`` used by the SDTM/ADaM YAML specs.

    Args:
        value: ``None``, a ``pl.Expr``, or an expression string.

    Returns:
        pl.Expr | None: The resolved expression.

    Raises:
        ValueError: If a string expression cannot be parsed.
        TypeError: If the value is neither ``None``, ``str`` nor ``pl.Expr``.
    """
    if value is None:
        return None
    if isinstance(value, pl.Expr):
        return value
    if isinstance(value, str):
        return parse_expression(value)
    raise TypeError(
        f"Filter must be a pl.Expr or an expression string, got {type(value).__name__!r}"
    )


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
    """A row-level field mapping for a summary table.

    Used as an entry in :attr:`TLGSpec.rows` (set inline via
    [`TLGBuilder.rows()`][fleet.tlg.TLGBuilder.rows]).
    """

    field: str = Field(
        ...,
        description="Source column name in the analysis dataset (e.g. ``AEBODSYS``).",
    )
    label: str | None = Field(
        default=None,
        description="Display label for this row group.  Defaults to *field*.",
    )
    filter_value: str | None = Field(
        default=None,
        description="Optional value used to subset the row to a single category.",
    )

    model_config = {"extra": "forbid"}


class Column(BaseModel):
    """A column specification for a listing.

    Used as an entry in :attr:`AEListingSpec.columns`.
    """

    field: str = Field(
        ...,
        description="Source column name in the analysis dataset (e.g. ``USUBJID``).",
    )
    label: str | None = Field(
        default=None,
        description="Display label for this column.  Defaults to *field*.",
    )
    format: str | None = Field(
        default=None,
        description="Optional Polars/Python format string applied at render time.",
    )

    model_config = {"extra": "forbid"}


class GroupPool(BaseModel):
    """A composite treatment group (pooled arms).

    Used as an entry in :attr:`TLGSpec.pools` (set inline via
    [`TLGBuilder.pools()`][fleet.tlg.TLGBuilder.pools]).
    """

    label: str = Field(
        ...,
        description='Display label for the pooled treatment column (e.g. ``"Total"``).',
    )
    arms: list[str] | Literal["*"] = Field(
        ...,
        description=(
            'List of arm labels to combine, or ``"*"`` to pool every arm present in the data.'
        ),
    )

    model_config = {"extra": "forbid"}


class OverallStat(BaseModel):
    """A whole-dataset aggregate row for summary header sections.

    Each ``OverallStat`` emits a flat ARD row with ``variable=""`` and
    ``variable_level=label``, rendered as a header row above the
    hierarchy.  Used as an entry in :attr:`TLGSpec.header_rows` (set
    inline via
    [`TLGBuilder.header_rows()`][fleet.tlg.TLGBuilder.header_rows]).
    """

    label: str = Field(
        ...,
        description="Display text for the header row (\u2192 ``variable_level``).",
    )
    filter: Any | None = Field(
        default=None,
        description=(
            "Optional filter to subset the dataset before counting — a "
            "``pl.Expr`` or a string expression (the YAML-serializable "
            "form).  ``None`` means count all subjects."
        ),
    )
    statistics: list[Statistic] | None = Field(
        default=None,
        description=(
            "Per-row stat override.  ``None`` inherits from the parent spec's ``statistics`` list."
        ),
    )

    model_config = {"extra": "forbid", "arbitrary_types_allowed": True}


class TLGSpec(BaseModel):
    """Base specification for all TLG outputs.

    Subclasses define output-type-specific defaults and required
    columns.  Every field below is also settable inline through the
    fluent [`TLGBuilder`][fleet.tlg.TLGBuilder] — the cross-references
    in each field's description point to the matching builder method.
    """

    output_type: str = Field(
        default="base",
        description=(
            "Discriminator distinguishing summary vs listing layouts. "
            "Subclasses override this default."
        ),
    )
    adsl_filter: Any | None = Field(
        default=None,
        description=(
            "Filter applied to ADSL before subject counting — a "
            "``pl.Expr`` or a string expression such as "
            '``\'pl.col("SAFFL") == "Y"\'`` (the YAML-serializable form). '
            "Set inline via "
            "[`TLGBuilder.population()`][fleet.tlg.TLGBuilder.population]."
        ),
    )
    dataset_filter: Any | None = Field(
        default=None,
        description=(
            "Filter applied to the analysis dataset (e.g. ADAE) — a "
            "``pl.Expr`` or a string expression (the YAML-serializable "
            "form).  Set inline via "
            "[`TLGBuilder.filter()`][fleet.tlg.TLGBuilder.filter]."
        ),
    )
    header_rows: list[OverallStat] = Field(
        default_factory=list,
        description=(
            "Whole-dataset aggregate rows rendered above the hierarchy.  "
            "Set inline via "
            "[`TLGBuilder.header_rows()`][fleet.tlg.TLGBuilder.header_rows]."
        ),
    )
    required_columns: list[str] = Field(
        default_factory=list,
        description=(
            "Columns that must be present in the dataset; checked by :meth:`validate_dataframe`."
        ),
    )
    required_flags: dict[str, list[str]] = Field(
        default_factory=dict,
        description=(
            "Per-column lists of values that must be present in the data "
            "(content validation).  Empty by default."
        ),
    )

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

        Filters (``adsl_filter``, ``dataset_filter``, header-row
        ``filter``) serialize only in their string-expression form.  A
        live ``pl.Expr`` cannot be serialized faithfully, and silently
        dropping it would change the numbers a reloaded spec computes —
        so it raises instead.

        Returns:
            str: YAML representation of the spec.

        Raises:
            ValueError: If any filter field holds a ``pl.Expr``.  Pass
                the filter as a string, e.g. ``'pl.col("SAFFL") == "Y"'``.
        """
        for field_name in ("adsl_filter", "dataset_filter"):
            value = getattr(self, field_name, None)
            if value is not None and not isinstance(value, str):
                raise ValueError(
                    f"{field_name} holds a {type(value).__name__} and cannot be "
                    "YAML-serialized. Use a string expression instead, e.g. "
                    'adsl_filter=\'pl.col("SAFFL") == "Y"\'.'
                )
        for hr in getattr(self, "header_rows", []):
            if hr.filter is not None and not isinstance(hr.filter, str):
                raise ValueError(
                    f"header_rows[{hr.label!r}].filter holds a "
                    f"{type(hr.filter).__name__} and cannot be YAML-serialized. "
                    "Use a string expression instead."
                )
        data = self.model_dump(exclude_none=True, exclude_defaults=False)
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

    Defaults provide zero-config convenience for a standard SOC→PT
    table.  Every field is also settable inline through
    [`TLGBuilder`][fleet.tlg.TLGBuilder].
    """

    output_type: str = "summary"
    rows: list[Row] = Field(
        default_factory=lambda: [
            Row(field="AEBODSYS", label="System Organ Class"),
            Row(field="AEDECOD", label="Preferred Term"),
        ],
        description=(
            "Hierarchy of row groupings.  Set inline via "
            "[`TLGBuilder.rows()`][fleet.tlg.TLGBuilder.rows]."
        ),
    )
    columns: list[str] = Field(
        default_factory=lambda: ["TRTA"],
        description=(
            "Column-grouping variables (typically a treatment column).  "
            "Set inline via [`TLGBuilder.by()`][fleet.tlg.TLGBuilder.by]."
        ),
    )
    statistics: list[Statistic] = Field(
        default_factory=lambda: [Statistic.N_SUBJECTS, Statistic.N_PCT],
        description=(
            "Statistics computed for each row.  Set inline via "
            "[`TLGBuilder.stats()`][fleet.tlg.TLGBuilder.stats]."
        ),
    )
    pools: list[GroupPool] = Field(
        default_factory=list,
        description=(
            "Composite (pooled) treatment groups.  Set inline via "
            "[`TLGBuilder.pools()`][fleet.tlg.TLGBuilder.pools]."
        ),
    )
    column_order: list[str] = Field(
        default_factory=list,
        description=(
            "Explicit ordering of column labels in the rendered output.  "
            "Set inline via "
            "[`TLGBuilder.column_order()`][fleet.tlg.TLGBuilder.column_order]."
        ),
    )
    denominator: str = Field(
        default="TRTA",
        description="Column used as the denominator when computing percentages.",
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "AEDECOD", "AEBODSYS"],
        description="Columns required in the analysis dataset for this spec.",
    )


class AEListingSpec(TLGSpec):
    """Spec for an AE listing (l_ae_listing)."""

    output_type: str = "listing"
    columns: list[Column] = Field(
        default_factory=lambda: [
            Column(field="USUBJID", label="Subject"),
            Column(field="TRTA", label="Treatment"),
            Column(field="AEBODSYS", label="SOC"),
            Column(field="AEDECOD", label="Preferred Term"),
            Column(field="AESEV", label="Severity"),
            Column(field="AESER", label="Serious"),
        ],
        description="Ordered list of columns to include in the listing.",
    )
    sort_by: list[str] = Field(
        default_factory=lambda: ["USUBJID", "AEBODSYS", "AEDECOD"],
        description="Sort order applied before rendering.",
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "AEDECOD"],
        description="Columns required in the analysis dataset for this spec.",
    )


class VSSummarySpec(TLGSpec):
    """Spec for a vital-signs summary table."""

    output_type: str = "summary"
    rows: list[Row] = Field(
        default_factory=lambda: [Row(field="PARAMCD", label="Parameter")],
        description=(
            "Hierarchy of row groupings.  Set inline via "
            "[`TLGBuilder.rows()`][fleet.tlg.TLGBuilder.rows]."
        ),
    )
    columns: list[str] = Field(
        default_factory=lambda: ["TRTA"],
        description=(
            "Column-grouping variables.  Set inline via "
            "[`TLGBuilder.by()`][fleet.tlg.TLGBuilder.by]."
        ),
    )
    statistics: list[Statistic] = Field(
        default_factory=lambda: [
            Statistic.N_SUBJECTS,
            Statistic.MEAN,
            Statistic.SD,
            Statistic.MEDIAN,
            Statistic.MIN,
            Statistic.MAX,
        ],
        description=(
            "Statistics computed per row.  Set inline via "
            "[`TLGBuilder.stats()`][fleet.tlg.TLGBuilder.stats]."
        ),
    )
    pools: list[GroupPool] = Field(
        default_factory=list,
        description=(
            "Composite (pooled) treatment groups.  Set inline via "
            "[`TLGBuilder.pools()`][fleet.tlg.TLGBuilder.pools]."
        ),
    )
    column_order: list[str] = Field(
        default_factory=list,
        description=(
            "Explicit ordering of column labels.  Set inline via "
            "[`TLGBuilder.column_order()`][fleet.tlg.TLGBuilder.column_order]."
        ),
    )
    denominator: str = Field(
        default="TRTA",
        description="Column used as the denominator when computing percentages.",
    )
    required_columns: list[str] = Field(
        default_factory=lambda: ["USUBJID", "TRTA", "PARAMCD", "AVAL"],
        description="Columns required in the analysis dataset for this spec.",
    )
    required_flags: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Per-column lists of required values (content validation).",
    )


def _enum_to_value(obj: Any) -> Any:
    """Recursively convert Enum instances to their ``.value``."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: _enum_to_value(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_enum_to_value(v) for v in obj]
    return obj
