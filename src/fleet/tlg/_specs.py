"""
TLG specification models — Vega-Lite-inspired declarative specs.

Each TLG output is defined by a Pydantic model that declares field→role
mappings, statistics, and data requirements.  This module holds the base
classes and the building blocks; each domain's spec classes live in its
own namespace module, next to the method that consumes them.  The spec carries both structural validation (column
presence/types) and content validation (required PARAM/PARAMCD values,
flag values, pool arm existence).
"""

from __future__ import annotations

from enum import Enum
from typing import Any, ClassVar, Literal, Self

import polars as pl
import yaml
from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

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


def _check_filter_field(value: Any, info: ValidationInfo) -> Any:
    """Shared Pydantic validator body for filter-carrying spec fields.

    Runs string filters through :func:`resolve_filter` at model-validation
    time so a malformed expression fails at construction, naming the
    field — instead of exploding later, mid-computation, without context.
    The original value is returned unchanged (strings stay strings so
    ``to_yaml()`` keeps working).
    """
    try:
        resolve_filter(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"invalid filter for field '{info.field_name}': {exc}. Pass a "
            "pl.Expr or a parseable expression string such as "
            '\'pl.col("SAFFL") == "Y"\'.'
        ) from exc
    return value


class Statistic(str, Enum):  # noqa: UP042
    """Statistics available for summary tables.

    ``N_SUBJECTS`` (n) counts distinct subjects on a count table.  On a
    table with continuous statistics it is the count of non-missing
    values in the cell, as PROC MEANS N (ADR-0016).  ``Q1`` and ``Q3``
    follow SAS QNTLDEF=5.
    """

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
    decimals: dict[str, str] | None = Field(
        default=None,
        description=(
            'Per-row format overrides — ARD ``stat_name`` (e.g. ``"mean"``) '
            'to format string (e.g. ``"xx.xx"``).  Merged over the spec-level '
            ":attr:`SummarySpecBase.decimals` for this row only, so the "
            "pharma one-more-decimal-than-collected rule is expressible per "
            "parameter."
        ),
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

    _validate_filter = field_validator("filter")(_check_filter_field)


#: GDSR label for a coding term that is still null at analysis time.
NO_CODING_LABEL = "No Coding Available"


class Uncoded(BaseModel):
    """The uncoded rule: give a null coding term a visible level.

    GDSR templates recode a missing MedDRA or ATC term to
    ``"No Coding Available"`` instead of dropping the record, so a
    subject whose only events are uncoded is still counted.  A spec
    carries one ``Uncoded`` (or ``None`` to switch the rule off); set
    inline via [`TLGBuilder.uncoded()`][fleet.tlg.TLGBuilder.uncoded].
    """

    columns: list[str] = Field(
        ...,
        description=(
            "Coding columns to fill when null (e.g. ``AEBODSYS`` and "
            "``AEDECOD``).  Names absent from the dataset are skipped."
        ),
    )
    label: str = Field(
        default=NO_CODING_LABEL,
        description="Replacement level written into every null coding column.",
    )

    model_config = {"extra": "forbid"}


class ChoiceOption(BaseModel):
    """One selectable value for an ``interactive:`` axis.

    Each option maps to a value for an *existing* spec field —
    ``filter`` for the ``population``/``dataset_filter`` axes,
    ``statistics`` for the ``stats`` axis.  A widget in the explorer is
    a spec-field editor, never new semantics.
    """

    label: str = Field(
        ...,
        description="Display label for this choice in the explorer widget bar.",
    )
    filter: str | None = Field(
        default=None,
        description=(
            "Filter expression string (the YAML-serializable form, e.g. "
            '``\'pl.col("AESER") == "Y"\'``); ``None`` means no filter. '
            "Used by the ``population``/``dataset_filter`` axes."
        ),
    )
    statistics: list[Statistic] | None = Field(
        default=None,
        description="Statistics list for this choice.  Used by the ``stats`` axis.",
    )
    default: bool = Field(
        default=False,
        description=(
            "Marks the batch default — exactly one option per axis. The "
            "default variant is the submission output."
        ),
    )

    model_config = {"extra": "forbid"}

    _validate_filter = field_validator("filter")(_check_filter_field)


class GroupbyChoice(BaseModel):
    """The ``groupby`` axis of an ``interactive:`` block.

    Each choice is a treatment-arm column name mapped onto the spec's
    ``columns`` field.
    """

    choices: list[str] = Field(
        ...,
        min_length=1,
        description="Candidate treatment-arm columns (e.g. ``[TRTA, TRT01A]``).",
    )
    default: str = Field(
        ...,
        description="The batch-default column.  Must be one of *choices*.",
    )

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _default_in_choices(self) -> GroupbyChoice:
        """Reject a default column that is not one of the choices."""
        if self.default not in self.choices:
            raise ValueError(
                f"interactive.groupby: default {self.default!r} is not in choices {self.choices!r}."
            )
        return self


class InteractiveBlock(BaseModel):
    """Declared degrees of freedom for the TLG explorer.

    Every axis maps onto one existing :class:`TLGSpec` field
    (``groupby``→``columns``, ``population``→``adsl_filter``,
    ``dataset_filter``→``dataset_filter``, ``stats``→``statistics``), so
    the interactive variant space is spanned by the same engine that
    produces the batch output — no second body of table logic exists.
    An absent axis stays fixed at the spec's value.
    """

    groupby: GroupbyChoice | None = Field(
        default=None,
        description="Treatment-arm column choices (→ spec ``columns``).",
    )
    population: list[ChoiceOption] | None = Field(
        default=None,
        description="ADSL population presets (→ spec ``adsl_filter``).",
    )
    dataset_filter: list[ChoiceOption] | None = Field(
        default=None,
        description="Analysis-dataset filter presets (→ spec ``dataset_filter``).",
    )
    stats: list[ChoiceOption] | None = Field(
        default=None,
        description="Statistics presets (→ spec ``statistics``).",
    )

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def _check_axes(self) -> InteractiveBlock:
        """Require at least one axis, one default per axis, stats lists."""
        if all(v is None for v in (self.groupby, self.population, self.dataset_filter, self.stats)):
            raise ValueError("interactive: declare at least one axis (or drop the block).")
        for axis in ("population", "dataset_filter", "stats"):
            options = getattr(self, axis)
            if options is None:
                continue
            n_default = sum(o.default for o in options)
            if n_default != 1:
                raise ValueError(
                    f"interactive.{axis}: exactly one option must set "
                    f"'default: true' (got {n_default}) — the default variant "
                    "is the batch/submission output."
                )
        if self.stats is not None:
            missing = [o.label for o in self.stats if not o.statistics]
            if missing:
                raise ValueError(
                    f"interactive.stats: options {missing} must declare a 'statistics' list."
                )
        return self


class TLGSpec(BaseModel):
    """Base specification for all TLG outputs.

    Subclasses define output-type-specific defaults and required
    columns.  Every field below is also settable inline through the
    fluent [`TLGBuilder`][fleet.tlg.TLGBuilder] — the cross-references
    in each field's description point to the matching builder method.
    """

    #: Spec fields defined on the model but ignored by the owning
    #: template method (e.g. ``rows`` on the fixed-hierarchy shift
    #: table).  ``TLGBuilder.to_spec()`` raises when accumulated builder
    #: state maps onto one of these instead of silently dropping it.
    _unconsumed_spec_fields: ClassVar[frozenset[str]] = frozenset()

    template: str | None = Field(
        default=None,
        description=(
            'Registry template id (e.g. ``"aet01"``).  Carrying it in '
            "the YAML makes the file self-executing: "
            "[`load_spec()`][fleet.tlg.load_spec] resolves the spec "
            "class and [`run_spec()`][fleet.tlg.run_spec] dispatches to "
            "the template's method through the registry."
        ),
    )
    schema_version: Literal[1] = Field(
        default=1,
        description=(
            "TLG spec schema version.  Bump-guarded so a future breaking "
            "layout change can be detected at load time."
        ),
    )
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
            "Population filter on ADSL — a "
            "``pl.Expr`` or a string expression such as "
            '``\'pl.col("SAFFL") == "Y"\'`` (the YAML-serializable form).  '
            "It selects the subjects for the big N, and only their "
            "analysis records are counted (ADR-0016).  Set inline via "
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
    interactive: InteractiveBlock | None = Field(
        default=None,
        description=(
            "Declared degrees of freedom for the explorer "
            "(``fleet tlg explore``).  Each axis maps onto one existing "
            "spec field; the all-defaults variant is the batch output.  "
            "Set inline via "
            "[`TLGBuilder.interactive()`][fleet.tlg.TLGBuilder.interactive]."
        ),
    )

    model_config = {"extra": "forbid", "arbitrary_types_allowed": True}

    _validate_filters = field_validator("adsl_filter", "dataset_filter")(_check_filter_field)

    #: interactive axis name → the spec field its choices map onto.
    _INTERACTIVE_AXIS_FIELDS: ClassVar[dict[str, str]] = {
        "groupby": "columns",
        "population": "adsl_filter",
        "dataset_filter": "dataset_filter",
        "stats": "statistics",
    }

    @model_validator(mode="after")
    def _check_interactive_applies(self) -> TLGSpec:
        """Reject interactive axes mapping to fields this spec cannot consume.

        Variants are built with ``model_copy(update=...)`` (no
        re-validation), so an axis targeting a missing or unconsumed
        field must fail here, at construction, naming the axis.
        """
        if self.interactive is None:
            return self
        fields = type(self).model_fields
        for axis, target in self._INTERACTIVE_AXIS_FIELDS.items():
            if getattr(self.interactive, axis) is None:
                continue
            if target not in fields or target in self._unconsumed_spec_fields:
                raise ValueError(
                    f"interactive.{axis} maps to spec field {target!r}, which "
                    f"{type(self).__name__} does not consume — the axis would "
                    "be silently ignored. Remove it or target a template that "
                    "consumes it."
                )
        if self.interactive.groupby is not None and "statistics" not in fields:
            raise ValueError(
                "interactive.groupby needs a summary spec — listings have no "
                "column grouping. Remove the axis."
            )
        return self

    @field_validator("schema_version", mode="before")
    @classmethod
    def _coerce_schema_version(cls, value: Any) -> Any:
        """Accept ``schema_version: "1"`` (string form) as version 1."""
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        return value

    def validate_dataframe(self, df: pl.DataFrame, *, group_col: str | None = None) -> None:
        """Run structural + content validation against *df*.

        Args:
            df: The analysis DataFrame.
            group_col: Effective treatment-arm column.  When it overrides
                the spec's default arm column (``columns[0]``), the
                default is substituted in the required-columns check so
                ``groupby="TRT01A"`` works on data without ``TRTA``.

        Raises:
            SchemaError: If required columns are missing, required flag
                values are absent, or other data constraints are violated.
        """
        self._validate_structural(df, group_col=group_col)
        self._validate_content(df)

    def _validate_structural(self, df: pl.DataFrame, *, group_col: str | None = None) -> None:
        """Tier 1: check required columns exist."""
        required = list(self.required_columns)
        default_group = getattr(self, "columns", None)
        if group_col and default_group and isinstance(default_group[0], str):
            required = [group_col if c == default_group[0] else c for c in required]
        available = set(df.columns)
        missing = [c for c in required if c not in available]
        if missing:
            raise SchemaError(
                f"{self.__class__.__name__} requires columns {required} "
                f"but DataFrame is missing {missing}. "
                f"Available: {sorted(available)}"
            )
        prefilter_missing = [c for c in self.prefilter_columns() if c not in available]
        if prefilter_missing:
            raise SchemaError(
                f"{self.__class__.__name__}'s prefilter names columns "
                f"{self.prefilter_columns()} but DataFrame is missing "
                f"{prefilter_missing}. Add the column, or set prefilter=None "
                "to switch the rule off (visible in the spec)."
                f"{getattr(self, 'prefilter_hint', '')} "
                f"Available: {sorted(available)}"
            )

    def prefilter_columns(self) -> list[str]:
        """Return the columns the spec's prefilter names.

        Every one of them is a required column of the template.  A
        listing has no prefilter, so the base returns none; summary
        specs override this.

        Returns:
            list[str]: Column names in first-seen order; empty here.

        Examples:
            ``AEListingSpec().prefilter_columns() == []``
        """
        return []

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
        prefilter_missing = [c for c in self.prefilter_columns() if c not in available]
        if prefilter_missing:
            diagnostics.append(
                f"MISSING PREFILTER COLUMNS: {prefilter_missing} named by the "
                f"{self.__class__.__name__} prefilter are not present."
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

        Filters (``adsl_filter``, ``dataset_filter``, ``prefilter``,
        header-row ``filter``) serialize only in their string-expression form.  A
        live ``pl.Expr`` cannot be serialized faithfully, and silently
        dropping it would change the numbers a reloaded spec computes —
        so it raises instead.

        Returns:
            str: YAML representation of the spec.

        Raises:
            ValueError: If any filter field holds a ``pl.Expr``.  Pass
                the filter as a string, e.g. ``'pl.col("SAFFL") == "Y"'``.
        """
        for field_name in ("adsl_filter", "dataset_filter", "prefilter"):
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
        # An explicit None switches a template's default rule off;
        # dropping it would bring the default back on reload.
        for field_name in ("prefilter", "uncoded"):
            if field_name in self.model_fields_set and getattr(self, field_name, 0) is None:
                data[field_name] = None
        # Convert enums to their values
        data = _enum_to_value(data)
        return yaml.dump(data, default_flow_style=False, sort_keys=False)

    @classmethod
    def from_yaml(cls, yaml_str: str) -> Self:
        """Deserialize a spec from a YAML string.

        Args:
            yaml_str: YAML text.

        Returns:
            Self: The reconstructed spec instance (the class it is called on).
        """
        data = yaml.safe_load(yaml_str)
        return cls.model_validate(data)


class SummarySpecBase(TLGSpec):
    """Shared fields for every summary-table spec.

    Domain specs subclass this and override only their defaults (rows,
    statistics, required columns, the uncoded rule, the prefilter) —
    one declaration of the shared shape instead of nine divergent
    copies.  Every field is also settable inline through
    [`TLGBuilder`][fleet.tlg.TLGBuilder].  The spec is the whole engine
    contract: [`summarize_spec()`][fleet.tlg.summarize_spec] reads every
    engine argument from it (ADR-0005).
    """

    #: The cards ``context`` tag written to every ARD row.  One spec
    #: class serves one template method, so the tag is a class fact,
    #: not a YAML field.
    context: ClassVar[str] = ""
    #: ``True`` when ``rows`` is a hierarchy (SOC → PT, PARAM → visit);
    #: ``False`` when each row field is an independent flat breakdown.
    nested: ClassVar[bool] = False
    #: Extra text for the missing-prefilter-column error (e.g. how to
    #: state a post-baseline rule without ONTRTFL).
    prefilter_hint: ClassVar[str] = ""

    output_type: str = "summary"
    rows: list[Row] = Field(
        default_factory=list,
        description=(
            "Row groupings (hierarchy for nested templates).  Set inline "
            "via [`TLGBuilder.rows()`][fleet.tlg.TLGBuilder.rows]."
        ),
    )
    uncoded: Uncoded | None = Field(
        default=None,
        description=(
            "The uncoded rule: coding columns whose nulls become a "
            "visible level before counting.  Each template sets its own "
            "default; ``null`` switches the rule off.  Set inline via "
            "[`TLGBuilder.uncoded()`][fleet.tlg.TLGBuilder.uncoded]."
        ),
    )
    prefilter: Any | None = Field(
        default=None,
        description=(
            "The template's own record filter, applied after "
            "``dataset_filter`` — a ``pl.Expr`` or a string expression "
            '(e.g. ``\'pl.col("ABLFL").ne_missing("Y")\'`` on a '
            "change-from-baseline table).  Each template sets its own "
            "default; ``null`` switches it off.  Every column it names "
            "is a required column.  Set inline via "
            "[`TLGBuilder.prefilter()`][fleet.tlg.TLGBuilder.prefilter]."
        ),
    )

    _validate_prefilter = field_validator("prefilter")(_check_filter_field)
    columns: list[str] = Field(
        default_factory=lambda: ["TRTA"],
        description=(
            "Column-grouping variables (typically a treatment column).  "
            "Exactly one entry — multi-column grouping is not implemented "
            "yet, and the engine would silently read only the first.  "
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
    value_col: str = Field(
        default="AVAL",
        description=(
            "Analysis-value column used for continuous statistics "
            "(mean/SD/median/…).  Summarize ``CHG``, ``PCHG`` or ``BASE`` "
            "by pointing this at the column — no pre-renaming needed.  "
            "When the column is missing but continuous statistics are "
            "requested, the engine raises instead of emitting null stats."
        ),
    )
    label_col: str | None = Field(
        default=None,
        description=(
            "Column holding display labels for the first row field's "
            'values (e.g. ``"PARAM"`` when the row field is '
            '``"PARAMCD"``) so stubs show display names instead of '
            "codes.  ``None`` shows the raw values."
        ),
    )
    decimals: dict[str, str] | None = Field(
        default=None,
        description=(
            "Per-statistic format overrides — ARD ``stat_name`` (e.g. "
            '``"mean"``, ``"sd"``, ``"pct"``) to format string (e.g. '
            '``"xx.xx"``).  Overrides the built-in defaults for this '
            "table; individual rows may override again via "
            ":attr:`Row.decimals`."
        ),
    )

    def prefilter_columns(self) -> list[str]:
        """Return the columns the spec's prefilter names.

        Every one of them is a required column of the template, so a
        change table's ``ABLFL`` guard makes ``ABLFL`` required and
        ``prefilter=None`` lifts that requirement with it.

        Returns:
            list[str]: Column names in first-seen order; empty when the
                prefilter is ``None``.

        Examples:
            ``LBChgSpec().prefilter_columns() == ["ABLFL", "CHG"]``
        """
        expr = resolve_filter(self.prefilter)
        if expr is None:
            return []
        return list(dict.fromkeys(expr.meta.root_names()))

    def check(self, df: pl.DataFrame) -> list[str]:
        """Run the pre-validation diagnostic without computing.

        The base checks (required columns, prefilter columns, required
        flag values) plus one warning per row field absent from *df*,
        whose sub-analysis the engine would skip.

        Args:
            df: The DataFrame to check.

        Returns:
            list[str]: Diagnostic messages (empty if all checks pass).

        Examples:
            ``MHSummarySpec().check(admh)``
        """
        diagnostics = super().check(df)
        available = set(df.columns)
        for row_def in self.rows:
            if row_def.field not in available:
                diagnostics.append(
                    f"WARNING: Column '{row_def.field}' not present — "
                    f"'{row_def.label or row_def.field}' sub-analysis will be skipped."
                )
        return diagnostics

    @field_validator("columns")
    @classmethod
    def _single_group_column(cls, value: list[str]) -> list[str]:
        """Reject multi-column (or empty) grouping loudly.

        The engine reads only ``columns[0]``; accepting more would
        silently discard the rest of the grouping.
        """
        if len(value) != 1:
            raise ValueError(
                f"'columns' must contain exactly one treatment-arm column "
                f"(got {value!r}). Multi-column grouping is not implemented "
                "— the engine would silently read only the first entry. "
                "Move additional grouping into the row hierarchy ('rows') "
                "or file a feature request."
            )
        return value


def change_from_baseline_prefilter(value_col: str) -> str:
    """Return the prefilter every change-from-baseline table starts from.

    Drops the baseline record (``ABLFL`` is ``Y``; ADaM codes the flag
    as Y / null, so the test is null-safe) and records with no change
    value, so the paired n counts subjects with a change at the visit.

    Args:
        value_col: The change column the table summarises (``CHG``,
            ``PCHG``).

    Returns:
        str: The expression string, YAML-serialisable.

    Examples:
        ``change_from_baseline_prefilter("CHG")`` gives
        ``'pl.col("ABLFL").ne_missing("Y") & pl.col("CHG").is_not_null()'``.
    """
    return f'pl.col("ABLFL").ne_missing("Y") & pl.col("{value_col}").is_not_null()'


def _enum_to_value(obj: Any) -> Any:
    """Recursively convert Enum instances to their ``.value``."""
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, dict):
        return {k: _enum_to_value(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_enum_to_value(v) for v in obj]
    return obj
