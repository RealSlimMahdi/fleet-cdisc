"""
TLG fluent builder — inline alternative to spec-driven ``t_summary()``.

``TLGBuilder`` accumulates state that maps 1:1 to a spec Pydantic model.
The builder is returned by the first verb call on a sub-namespace and
chains through to ``.to_ard()`` which materialises by constructing the
equivalent spec and delegating to ``t_summary()``.

The verb set is a *down-product* of the ARD schema — each verb maps
directly to one or more ARD columns.
"""

from __future__ import annotations

import copy
import warnings
from typing import TYPE_CHECKING, Any

import polars as pl

from ._specs import (
    MISSING_LABEL,
    NO_CODING_LABEL,
    Column,
    GroupPool,
    InteractiveBlock,
    MissingLevel,
    OverallStat,
    Row,
    SchemaError,
    Statistic,
    SummarySpecBase,
    Uncoded,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ._specs import TLGSpec
    from .render._models import RenderMetadata


#: Marks a builder field the user never set, so the spec default applies.
#: ``None`` is a real value for ``uncoded()`` and ``prefilter()`` (it
#: switches the rule off), so absence needs its own marker.
_UNSET: Any = object()


class TLGBuilder:
    """Fluent builder for constructing TLG ARDs inline.

    This is a shared base class composed into every TLG sub-namespace.
    Domain-specific defaults (required columns, default statistics,
    ``context`` label) are baked into the sub-namespace rather than the
    builder.

    Args:
        df: The primary analysis DataFrame.
        context: Domain context label (e.g. ``"t_ae_summary"``).
        spec_cls: The spec Pydantic model class for this domain.
        namespace_cls: The namespace class that implements ``t_summary()``.
        defaults: Domain-specific default kwargs for spec construction.
    """

    def __init__(
        self,
        df: pl.DataFrame,
        *,
        context: str,
        spec_cls: type[TLGSpec],
        namespace_cls: type[Any],
        defaults: dict[str, Any] | None = None,
    ) -> None:
        self._df = df
        self._context = context
        self._spec_cls = spec_cls
        self._namespace_cls = namespace_cls
        self._defaults: dict[str, Any] = defaults or {}
        self._method = "t_summary"
        self._adsl: pl.DataFrame | None = None
        self._adsl_filter: pl.Expr | str | None = None
        self._adsl_group_col: str | None = None
        self._dataset_filter: pl.Expr | str | None = None
        self._group_col: str | None = None
        self._header_rows_list: list[OverallStat] = []
        self._rows_fields: list[str | Row] = []
        self._statistics: list[Statistic] | None = None
        self._pools: list[GroupPool] = []
        self._column_order: list[str] = []
        self._value_col: str | None = None
        self._label_col: str | None = None
        self._decimals: dict[str, str] | None = None
        self._uncoded: Uncoded | None = _UNSET
        self._missing: MissingLevel | None = _UNSET
        self._prefilter: pl.Expr | str | None = _UNSET
        self._listing_columns: list[str | Column] | None = None
        self._sort_by: list[str] | None = None
        self._template_id: str | None = None
        self._template_fn: Callable[..., pl.DataFrame] | None = None
        self._interactive: InteractiveBlock | None = None

    def _clone(self) -> TLGBuilder:
        return copy.copy(self)

    def _targets_listing(self) -> bool:
        """True when the current spec class describes a listing layout."""
        field = self._spec_cls.model_fields.get("output_type")
        return field is not None and field.default == "listing"

    def _has_reinterpretable_state(self) -> bool:
        """True when row/stat/format verbs have already accumulated state."""
        return bool(
            self._rows_fields
            or self._statistics is not None
            or self._header_rows_list
            or self._pools
            or self._column_order
            or self._value_col is not None
            or self._label_col is not None
            or self._decimals is not None
            or self._uncoded is not _UNSET
            or self._missing is not _UNSET
            or self._prefilter is not _UNSET
            or self._listing_columns is not None
            or self._sort_by is not None
        )

    def _require_consumed_field(self, field: str, verb: str) -> None:
        """Raise when builder state maps to a field the target won't consume."""
        cls = self._spec_cls
        if field not in cls.model_fields:
            raise SchemaError(
                f"{verb} maps to spec field '{field}', which {cls.__name__} "
                f"does not define — the target template method "
                f"'{self._method}' would silently ignore it. Remove the verb "
                "or target a template that consumes it."
            )
        if field in cls._unconsumed_spec_fields:
            raise SchemaError(
                f"{verb} maps to spec field '{field}', which the target "
                f"template method '{self._method}' does not consume — it "
                "would be silently ignored. Remove the verb or target a "
                "different template."
            )

    # ------------------------------------------------------------------ #
    # Data input verbs                                                     #
    # ------------------------------------------------------------------ #

    def population(
        self,
        adsl: pl.DataFrame,
        *,
        adsl_filter: pl.Expr | str | None = None,
        group_col: str | None = None,
    ) -> TLGBuilder:
        """Set the ADSL population and optional denominator filter.

        Args:
            adsl: ADSL DataFrame for big-N denominators.
            adsl_filter: Optional population filter on ADSL — a
                ``pl.Expr`` or a string expression (the
                YAML-serializable form).  Only the analysis records of
                the selected subjects are counted.
            group_col: Arm column of ADSL when it differs from the
                analysis arm (``TRT01A`` for an ADAE grouped by
                ``TRTA``).  Maps to the spec's ``adsl_group_col``.

        Returns:
            TLGBuilder: Builder with population set.

        Examples:
            Use ADSL for the big-N denominators::

                ard = (
                    adae.tlg.ae
                    .population(adsl)
                    .by("TRTA")
                    .to_ard()
                )

            ADAE grouped by TRTA, ADSL with TRT01A only::

                ard = (
                    adae.tlg.ae
                    .population(adsl, group_col="TRT01A")
                    .by("TRTA")
                    .template("aet02")
                    .to_ard()
                )
        """
        new = self._clone()
        new._adsl = adsl
        new._adsl_filter = adsl_filter
        new._adsl_group_col = group_col
        return new

    def filter(self, expr: pl.Expr | str) -> TLGBuilder:
        """Set the dataset filter (applied to the primary dataset only).

        Args:
            expr: Polars expression (or string expression — the
                YAML-serializable form) filtering the primary dataset.

        Returns:
            TLGBuilder: Builder with dataset filter set.

        Examples:
            Restrict the table to treatment-emergent events::

                ard = (
                    adae.tlg.ae
                    .population(adsl)
                    .filter('pl.col("TRTEMFL") == "Y"')
                    .by("TRTA")
                    .to_ard()
                )
        """
        new = self._clone()
        new._dataset_filter = expr
        return new

    # ------------------------------------------------------------------ #
    # Grouping verbs                                                       #
    # ------------------------------------------------------------------ #

    def by(self, col: str) -> TLGBuilder:
        """Set the primary grouping column (treatment arm).

        Args:
            col: Column name for group1 (e.g. ``"TRTA"``).

        Returns:
            TLGBuilder: Builder with group1 set.

        Raises:
            SchemaError: If *col* is not a single column name —
                multi-column grouping is not implemented, and accepting a
                list would silently read only the first entry.

        Examples:
            Split columns by actual treatment arm::

                ard = (
                    adae.tlg.ae
                    .population(adsl)
                    .by("TRTA")
                    .to_ard()
                )
        """
        if not isinstance(col, str):
            raise SchemaError(
                f"by() takes a single treatment-arm column name, got "
                f"{col!r}. Multi-column grouping is not implemented — move "
                "additional grouping into the row hierarchy (rows())."
            )
        new = self._clone()
        new._group_col = col
        return new

    def template(self, template_id: str) -> TLGBuilder:
        """Target a registered template so materialisation runs its method.

        Resolves *template_id* through the template registry (built-ins
        and user registrations alike): the builder will materialise via
        that template's namespace method (e.g. ``lbt02`` → ``t_chg``) —
        or its registered function for user templates — with the
        template's spec class.  Listing templates (e.g. ``ael01``)
        materialise via :meth:`to_listing`.

        **Ordering**: call ``template()`` *before* row/stat/format verbs.
        It swaps the builder's spec class, so state accumulated earlier
        is re-validated against — and interpreted by — the new target's
        spec; a ``UserWarning`` is emitted when that happens.

        Args:
            template_id: Registry id (e.g. ``"aet02"``, ``"lbt02"``).

        Returns:
            TLGBuilder: Builder targeting the template's method and spec.

        Raises:
            SchemaError: If the id is unknown, belongs to a different
                namespace, or is a graph template.

        Examples:
            Materialise the AET02 shell::

                ard = (
                    adae.tlg.ae
                    .population(adsl)
                    .by("TRTA")
                    .template("aet02")
                    .to_ard()
                )
        """
        from ._registry import TEMPLATES, OutputType

        meta = TEMPLATES.get(template_id)
        if meta is None:
            raise SchemaError(
                f"Unknown template id {template_id!r}. Known ids: {sorted(TEMPLATES)}"
            )
        if meta.output_type is OutputType.GRAPH:
            raise SchemaError(
                f"Template {template_id!r} is a graph, which the inline builder cannot materialise."
            )
        new = self._clone()
        if meta.func is not None:
            # User-registered template: self-contained function, not bound
            # to a namespace method.
            new._template_fn = meta.func
            new._spec_cls = meta.spec_cls or SummarySpecBase
        else:
            spec_classes = getattr(self._namespace_cls, "_builder_specs", {})
            if meta.method not in spec_classes:
                raise SchemaError(
                    f"Template {template_id!r} ({meta.namespace}.{meta.method}) does "
                    f"not belong to this namespace ({self._context})."
                )
            new._method = meta.method
            new._spec_cls = meta.spec_cls or spec_classes[meta.method]
        new._template_id = meta.id
        if self._has_reinterpretable_state():
            warnings.warn(
                f"template({template_id!r}) was called after row/stat/format "
                "verbs — the accumulated state will be reinterpreted by "
                f"{new._spec_cls.__name__}. Call .template() first to avoid "
                "surprises.",
                UserWarning,
                stacklevel=2,
            )
        return new

    # ------------------------------------------------------------------ #
    # Row / stat / format verbs                                            #
    # ------------------------------------------------------------------ #

    def header_rows(self, overall_stats: list[OverallStat]) -> TLGBuilder:
        """Set header rows (whole-dataset aggregate rows).

        Args:
            overall_stats: List of ``OverallStat`` definitions.

        Returns:
            TLGBuilder: Builder with header rows set.

        Examples:
            Add a whole-dataset aggregate row::

                from fleet.tlg import OverallStat

                ard = (
                    adlb.tlg.lb
                    .population(adsl)
                    .by("TRTA")
                    .header_rows([OverallStat(label="Any abnormal")])
                    .to_ard()
                )
        """
        new = self._clone()
        new._header_rows_list = list(overall_stats)
        return new

    def rows(self, fields: list[str | Row]) -> TLGBuilder:
        """Set the row hierarchy fields.

        A single field maps to ``variable``.  Two fields drive two-level
        nesting: the first maps to ``variable``, the second to ``group2``.
        Entries may be plain column names or full ``Row`` objects
        carrying ``label`` / ``filter_value`` / ``decimals``.

        Args:
            fields: One or two field names (or ``Row`` objects) for the
                row hierarchy.

        Returns:
            TLGBuilder: Builder with row fields set.

        Examples:
            Two-level SOC → preferred-term hierarchy::

                ard = (
                    adae.tlg.ae
                    .population(adsl)
                    .by("TRTA")
                    .rows(["AEBODSYS", "AEDECOD"])
                    .to_ard()
                )
        """
        new = self._clone()
        new._rows_fields = list(fields)
        return new

    def value(self, col: str) -> TLGBuilder:
        """Set the analysis-value column for continuous statistics.

        Maps to the spec's ``value_col`` — point it at ``CHG``, ``PCHG``
        or ``BASE`` to summarize those without pre-renaming.

        Args:
            col: Analysis-value column name (e.g. ``"CHG"``).

        Returns:
            TLGBuilder: Builder with the value column set.

        Examples:
            Summarise change from baseline instead of AVAL::

                ard = (
                    advs.tlg.vs
                    .population(adsl)
                    .by("TRTA")
                    .value("CHG")
                    .to_ard()
                )
        """
        new = self._clone()
        new._value_col = col
        return new

    def label(self, col: str) -> TLGBuilder:
        """Set the display-label column for the first row field's values.

        Maps to the spec's ``label_col`` — e.g. ``"PARAM"`` when the row
        field is ``"PARAMCD"`` so stubs show display names, not codes.

        Args:
            col: Column holding display labels.

        Returns:
            TLGBuilder: Builder with the label column set.

        Examples:
            Show PARAM display names for PARAMCD rows::

                ard = (
                    advs.tlg.vs
                    .population(adsl)
                    .by("TRTA")
                    .rows(["PARAMCD"])
                    .label("PARAM")
                    .to_ard()
                )
        """
        new = self._clone()
        new._label_col = col
        return new

    def decimals(self, mapping: dict[str, str]) -> TLGBuilder:
        """Set per-statistic display-format overrides.

        Maps to the spec's ``decimals`` — ARD ``stat_name`` (e.g.
        ``"mean"``) to format string (e.g. ``"xx.xx"``).

        Args:
            mapping: Stat-name → format-string overrides.

        Returns:
            TLGBuilder: Builder with format overrides set.

        Examples:
            Report means with two decimal places::

                ard = (
                    advs.tlg.vs
                    .population(adsl)
                    .by("TRTA")
                    .decimals({"mean": "xx.xx"})
                    .to_ard()
                )
        """
        new = self._clone()
        new._decimals = dict(mapping)
        return new

    # ------------------------------------------------------------------ #
    # Record-rule verbs                                                    #
    # ------------------------------------------------------------------ #

    def uncoded(self, columns: list[str] | None, *, label: str = NO_CODING_LABEL) -> TLGBuilder:
        """Set the uncoded rule: the coding columns whose nulls become a level.

        Maps to the spec's ``uncoded``.  Each template has its own
        default (the AE tables fill ``AEBODSYS`` and ``AEDECOD`` with
        ``"No Coding Available"``); ``uncoded(None)`` switches the rule
        off so uncoded records are not counted.

        Args:
            columns: Coding columns to fill when null, or ``None`` to
                switch the rule off.
            label: Replacement level for a null coding term.

        Returns:
            TLGBuilder: Builder with the uncoded rule set.

        Examples:
            Use the sponsor's label for uncoded events::

                ard = (
                    adae.tlg.ae
                    .population(adsl)
                    .by("TRTA")
                    .uncoded(["AEBODSYS", "AEDECOD"], label="UNCODED")
                    .to_ard()
                )
        """
        new = self._clone()
        new._uncoded = None if columns is None else Uncoded(columns=list(columns), label=label)
        return new

    def missing(
        self, columns: list[str] | None, *, label: str | None = MISSING_LABEL
    ) -> TLGBuilder:
        """Set the missing-level rule: the category columns whose nulls get a row.

        Maps to the spec's ``missing``.  Each template has its own
        default (DM: SEX, AGEGR1, RACE, ETHNIC; AET03: the intensity).
        ``label=None`` adds no row and writes the count to the ARD
        warning column; ``missing(None)`` switches the rule off.

        Args:
            columns: Category columns, or ``None`` to switch the rule off.
            label: Row label of the missing level, or ``None``.

        Returns:
            TLGBuilder: Builder with the missing-level rule set.

        Examples:
            Count a null RACE under "Not reported"::

                ard = (
                    adsl.tlg.dm
                    .population(adsl)
                    .by("TRT01A")
                    .missing(["RACE"], label="Not reported")
                    .to_ard()
                )
        """
        new = self._clone()
        new._missing = None if columns is None else MissingLevel(columns=list(columns), label=label)
        return new

    def prefilter(self, expr: pl.Expr | str | None) -> TLGBuilder:
        """Set the template's own record filter, applied after ``filter()``.

        Maps to the spec's ``prefilter``.  Each template has its own
        default (the change-from-baseline tables drop the ``ABLFL`` = Y
        record); every column the expression names becomes a required
        column.  ``prefilter(None)`` switches the rule off.

        Args:
            expr: Polars expression, string expression (the
                YAML-serializable form), or ``None``.

        Returns:
            TLGBuilder: Builder with the prefilter set.

        Examples:
            Keep on-treatment records only in a change table::

                ard = (
                    adlb.tlg.lb
                    .population(adsl)
                    .by("TRTA")
                    .template("lbt02")
                    .prefilter('pl.col("ONTRTFL") == "Y"')
                    .to_ard()
                )
        """
        new = self._clone()
        new._prefilter = expr
        return new

    # ------------------------------------------------------------------ #
    # Listing verbs                                                        #
    # ------------------------------------------------------------------ #

    def columns(self, cols: list[str | Column]) -> TLGBuilder:
        """Set the display columns for a listing.

        Entries may be plain column names or full ``Column`` objects
        carrying display labels.  Applies to the listing path only —
        for table grouping use :meth:`by`.

        Args:
            cols: Ordered listing columns.

        Returns:
            TLGBuilder: Builder with listing columns set.

        Examples:
            A subject-level AE listing::

                listing = (
                    adae.tlg.ae
                    .template("ael01")
                    .columns(["USUBJID", "AEDECOD", "AESEV"])
                    .to_listing()
                )
        """
        new = self._clone()
        new._listing_columns = list(cols)
        return new

    def sort_by(self, cols: list[str]) -> TLGBuilder:
        """Set the sort order for a listing.

        Args:
            cols: Column names to sort the listing by, in order.

        Returns:
            TLGBuilder: Builder with the sort order set.

        Examples:
            Sort the listing by subject then onset date::

                listing = (
                    adae.tlg.ae
                    .template("ael01")
                    .sort_by(["USUBJID", "ASTDT"])
                    .to_listing()
                )
        """
        new = self._clone()
        new._sort_by = list(cols)
        return new

    def stats(self, statistics: list[Statistic]) -> TLGBuilder:
        """Set the statistics to compute.

        Args:
            statistics: List of ``Statistic`` enum values.

        Returns:
            TLGBuilder: Builder with statistics set.

        Examples:
            Report subject counts and percentages::

                from fleet.tlg import Statistic

                ard = (
                    adae.tlg.ae
                    .population(adsl)
                    .by("TRTA")
                    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
                    .to_ard()
                )
        """
        new = self._clone()
        new._statistics = list(statistics)
        return new

    def pools(self, pool_defs: list[GroupPool]) -> TLGBuilder:
        """Set pooled treatment group definitions.

        Args:
            pool_defs: List of ``GroupPool`` definitions.

        Returns:
            TLGBuilder: Builder with pools set.

        Examples:
            Add a pooled Total column across all arms::

                from fleet.tlg import GroupPool

                ard = (
                    adae.tlg.ae
                    .population(adsl)
                    .by("TRTA")
                    .pools([GroupPool(label="Total", arms="*")])
                    .to_ard()
                )
        """
        new = self._clone()
        new._pools = list(pool_defs)
        return new

    def column_order(self, order: list[str]) -> TLGBuilder:
        """Set the display column order.

        Args:
            order: Ordered list of arm labels.

        Returns:
            TLGBuilder: Builder with column order set.

        Examples:
            Force placebo first::

                ard = (
                    adae.tlg.ae
                    .population(adsl)
                    .by("TRTA")
                    .column_order(["Placebo", "Low Dose", "High Dose"])
                    .to_ard()
                )
        """
        new = self._clone()
        new._column_order = list(order)
        return new

    def interactive(
        self,
        *,
        groupby: Any | None = None,
        population: list[Any] | None = None,
        dataset_filter: list[Any] | None = None,
        stats: list[Any] | None = None,
    ) -> TLGBuilder:
        """Declare the explorer's degrees of freedom (``interactive:`` block).

        Each axis maps onto an existing spec field — ``groupby`` →
        ``columns``, ``population`` → ``adsl_filter``, ``dataset_filter``
        → ``dataset_filter``, ``stats`` → ``statistics`` — so every
        explorer variant runs through the same engine as the batch
        output.  Values may be plain dicts (the YAML shapes) or
        ``GroupbyChoice``/``ChoiceOption`` instances.

        Args:
            groupby: ``{"choices": [...], "default": ...}`` — candidate
                treatment-arm columns.
            population: ADSL filter presets, each
                ``{"label": ..., "filter": ..., "default": ...}``.
            dataset_filter: Analysis-dataset filter presets (same shape).
            stats: Statistics presets, each
                ``{"label": ..., "statistics": [...], "default": ...}``.

        Returns:
            TLGBuilder: Builder with the interactive block set.

        Examples:
            Declare a two-axis explorer and save the spec::

                spec = (
                    adae.tlg.ae
                    .population(adsl, adsl_filter='pl.col("SAFFL") == "Y"')
                    .by("TRTA")
                    .template("aet01")
                    .interactive(
                        groupby={"choices": ["TRTA", "TRT01A"], "default": "TRTA"},
                        stats=[
                            {"label": "n (%)", "statistics": ["n_subjects", "n_pct"],
                             "default": True},
                            {"label": "+ events",
                             "statistics": ["n_subjects", "n_pct", "n_events"]},
                        ],
                    )
                    .to_spec()
                )
        """
        new = self._clone()
        new._interactive = InteractiveBlock(
            groupby=groupby,
            population=population,
            dataset_filter=dataset_filter,
            stats=stats,
        )
        return new

    # ------------------------------------------------------------------ #
    # Materialisation                                                      #
    # ------------------------------------------------------------------ #

    def to_spec(self) -> TLGSpec:
        """Serialise accumulated builder state to the equivalent spec.

        Every verb the user called must land on a spec field the target
        template's method actually consumes — otherwise this raises
        instead of silently dropping state (e.g. ``rows()`` on the
        fixed-hierarchy ``lbt03`` shift table).

        Returns:
            TLGSpec: A spec instance matching the builder configuration
                (carrying ``template=<id>`` when targeted via
                :meth:`template`).

        Raises:
            SchemaError: If accumulated builder state maps to a spec
                field the target template's method does not consume, or
                to no field at all.

        Examples:
            Capture the builder state as a reusable spec::

                spec = (
                    adae.tlg.ae
                    .population(adsl)
                    .by("TRTA")
                    .template("aet02")
                    .to_spec()
                )
        """
        is_listing = self._targets_listing()
        kwargs: dict[str, Any] = dict(self._defaults)

        if self._template_id is not None:
            kwargs["template"] = self._template_id
        if self._adsl_filter is not None:
            self._require_consumed_field("adsl_filter", "population(adsl_filter=...)")
            kwargs["adsl_filter"] = self._adsl_filter
        if self._adsl_group_col is not None:
            self._require_consumed_field("adsl_group_col", "population(group_col=...)")
            kwargs["adsl_group_col"] = self._adsl_group_col
        if self._dataset_filter is not None:
            self._require_consumed_field("dataset_filter", "filter()")
            kwargs["dataset_filter"] = self._dataset_filter
        if self._header_rows_list:
            self._require_consumed_field("header_rows", "header_rows()")
            kwargs["header_rows"] = self._header_rows_list
        if self._group_col:
            if is_listing:
                raise SchemaError(
                    "by() sets a grouping column, but the target template is "
                    "a listing — listings have no column grouping. Remove "
                    "by() or target a table template."
                )
            if "columns" in self._spec_cls.model_fields:
                kwargs["columns"] = [self._group_col]
        if self._rows_fields:
            kwargs.update(self._rows_kwargs())
        if self._statistics is not None:
            self._require_consumed_field("statistics", "stats()")
            kwargs["statistics"] = self._statistics
        if self._pools:
            self._require_consumed_field("pools", "pools()")
            kwargs["pools"] = self._pools
        if self._column_order:
            self._require_consumed_field("column_order", "column_order()")
            kwargs["column_order"] = self._column_order
        if self._value_col is not None:
            self._require_consumed_field("value_col", "value()")
            kwargs["value_col"] = self._value_col
        if self._label_col is not None:
            self._require_consumed_field("label_col", "label()")
            kwargs["label_col"] = self._label_col
        if self._decimals is not None:
            self._require_consumed_field("decimals", "decimals()")
            kwargs["decimals"] = self._decimals
        if self._uncoded is not _UNSET:
            self._require_consumed_field("uncoded", "uncoded()")
            kwargs["uncoded"] = self._uncoded
        if self._missing is not _UNSET:
            self._require_consumed_field("missing", "missing()")
            kwargs["missing"] = self._missing
        if self._prefilter is not _UNSET:
            self._require_consumed_field("prefilter", "prefilter()")
            kwargs["prefilter"] = self._prefilter
        if self._listing_columns is not None:
            if not is_listing:
                raise SchemaError(
                    "columns() defines listing display columns, but the "
                    "target template is a table. Use by() for the grouping "
                    'column, or target a listing template (.template("ael01") '
                    "/ .to_listing())."
                )
            kwargs["columns"] = [
                c if isinstance(c, Column) else Column(field=c) for c in self._listing_columns
            ]
        if self._sort_by is not None:
            self._require_consumed_field("sort_by", "sort_by()")
            kwargs["sort_by"] = list(self._sort_by)
        if self._interactive is not None:
            kwargs["interactive"] = self._interactive

        return self._spec_cls(**kwargs)

    def _rows_kwargs(self) -> dict[str, Any]:
        """Map ``rows()`` state onto the target spec's row field(s).

        DM summarises independent categorical variables, not a row
        hierarchy — map the builder's rows() onto ``categorical_vars``
        (merging any ``Row.label`` into ``category_labels``).
        """
        row_objs = [f if isinstance(f, Row) else Row(field=f) for f in self._rows_fields]
        if "categorical_vars" not in self._spec_cls.model_fields:
            self._require_consumed_field("rows", "rows()")
            return {"rows": row_objs}
        unsupported = [
            r.field for r in row_objs if r.filter_value is not None or r.decimals is not None
        ]
        if unsupported:
            raise SchemaError(
                f"rows() entries {unsupported} carry filter_value/decimals, "
                f"which {self._spec_cls.__name__}'s categorical breakdown "
                "does not consume — they would be silently ignored."
            )
        kwargs: dict[str, Any] = {"categorical_vars": [r.field for r in row_objs]}
        labels = {r.field: r.label for r in row_objs if r.label}
        if labels:
            default_field = self._spec_cls.model_fields["category_labels"]
            defaults = default_field.get_default(call_default_factory=True) or {}
            kwargs["category_labels"] = {**defaults, **labels}
        return kwargs

    def to_ard(self) -> pl.DataFrame:
        """Materialise the builder to an ARD DataFrame.

        Constructs the equivalent spec and delegates to the targeted
        namespace method — ``t_summary()`` by default, the method
        selected via :meth:`template`, or the registered function for a
        user template.

        Returns:
            pl.DataFrame: Long-format {cards}-compatible ARD.

        Raises:
            SchemaError: If the target template is a listing — call
                :meth:`to_listing` instead.

        Examples:
            Inline AE summary::

                ard = (
                    adae.tlg.ae
                    .population(adsl, adsl_filter=pl.col("SAFFL") == "Y")
                    .by("TRTA")
                    .rows(["AEBODSYS", "AEDECOD"])
                    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
                    .to_ard()
                )
        """
        if self._template_fn is not None:
            return self._template_fn(
                self._df,
                adsl=self._adsl,
                spec=self.to_spec(),
                groupby=self._group_col,
            )
        if self._targets_listing():
            raise SchemaError(
                f"Template {self._template_id!r} is a listing — call "
                ".to_listing() instead of .to_ard()."
            )
        spec = self.to_spec()
        ns = self._namespace_cls(self._df)
        kwargs: dict[str, Any] = {"adsl": self._adsl, "spec": spec}
        if self._group_col is not None:
            kwargs["groupby"] = self._group_col
        return getattr(ns, self._method)(**kwargs)

    def to_listing(self) -> pl.DataFrame:
        """Materialise the builder to a listing DataFrame.

        Uses the listing template targeted via :meth:`template` (e.g.
        ``ael01``), or the namespace's default listing when none was
        targeted.  Listings ignore population/grouping by design, so
        ``by()`` and ``population(adsl_filter=...)`` state raises here.

        Returns:
            pl.DataFrame: A plain DataFrame with the requested columns,
                sorted per spec.

        Raises:
            SchemaError: If a table template was targeted, or the
                namespace ships no listing template.

        Examples:
            Inline AE listing::

                listing = (
                    adae.tlg.ae
                    .columns(["USUBJID", "AEDECOD", "AESEV"])
                    .sort_by(["USUBJID"])
                    .to_listing()
                )
        """
        builder = self
        if not self._targets_listing():
            if self._template_id is not None or self._template_fn is not None:
                raise SchemaError(
                    f"Template {self._template_id!r} is not a listing — call "
                    ".to_ard() instead of .to_listing()."
                )
            spec_classes = getattr(self._namespace_cls, "_builder_specs", {})
            listing_cls = spec_classes.get("l_listing")
            if listing_cls is None:
                raise SchemaError(
                    f"{self._context}: this namespace ships no listing "
                    "template, so .to_listing() is unavailable."
                )
            builder = self._clone()
            builder._method = "l_listing"
            builder._spec_cls = listing_cls
        spec = builder.to_spec()
        ns = self._namespace_cls(self._df)
        return getattr(ns, builder._method)(spec=spec)

    def to_html(
        self,
        path: str | Path | None = None,
        *,
        metadata: RenderMetadata | None = None,
        html_wrapper: str | None = None,
    ) -> str:
        """Render the builder result as a pharma-style HTML table.

        Materialises the ARD via ``.to_ard()``, shapes it into a
        ``TableModel``, and renders to HTML.

        Args:
            path: Optional file path.  If given, HTML is written to disk.
            metadata: Optional ``RenderMetadata`` for title, subtitle,
                footnotes, etc.
            html_wrapper: Optional HTML template with ``{table}``
                placeholder for injection.

        Returns:
            str: The rendered HTML string.

        Examples:
            Inline AE summary to HTML::

                html = (
                    adae.tlg.ae
                    .population(adsl)
                    .by("TRTA")
                    .rows(["AEBODSYS", "AEDECOD"])
                    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
                    .to_html(metadata=RenderMetadata(title="Table 14.3.1"))
                )
        """
        from pathlib import Path as _Path

        from .render._models import RenderMetadata as _RM
        from .render._models import ard_to_table_model
        from .render.html import render_html

        ard = self.to_ard()
        meta = metadata or _RM()
        model = ard_to_table_model(ard, meta)
        html = render_html(model, html_wrapper=html_wrapper)

        if path is not None:
            p = _Path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(html, encoding="utf-8")

        return html

    def to_rtf(
        self,
        path: str | Path | None = None,
        *,
        metadata: RenderMetadata | None = None,
    ) -> str:
        """Render the builder result as a pharma-style RTF table.

        Materialises the ARD via ``.to_ard()``, shapes it into a
        ``TableModel``, and renders to RTF (Courier New 9pt, cell
        borders, repeated headers, ``Page X of Y``) — the de facto
        submission/QC format.  Pure stdlib.

        Args:
            path: Optional file path.  If given, RTF is written to disk.
            metadata: Optional ``RenderMetadata`` for title, subtitle,
                footnotes, etc.

        Returns:
            str: The rendered RTF document.

        Examples:
            Inline AE summary to a submission RTF::

                rtf = (
                    adae.tlg.ae
                    .population(adsl)
                    .by("TRTA")
                    .rows(["AEBODSYS", "AEDECOD"])
                    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
                    .to_rtf("t_ae_summary.rtf",
                            metadata=RenderMetadata(title="Table 14.3.1"))
                )
        """
        from .render._models import RenderMetadata as _RM
        from .render._models import ard_to_table_model
        from .render.rtf import render_rtf

        ard = self.to_ard()
        meta = metadata or _RM()
        model = ard_to_table_model(ard, meta)
        return render_rtf(model, path)

    def to_pdf(
        self,
        path: str | Path,
        *,
        metadata: RenderMetadata | None = None,
    ) -> Path:
        """Render the builder result as a PDF file via WeasyPrint.

        Args:
            path: Output PDF file path.
            metadata: Optional ``RenderMetadata`` for title, subtitle,
                footnotes, etc.

        Returns:
            Path: The written PDF path.

        Raises:
            ImportError: If WeasyPrint is not installed.

        Examples:
            Inline AE summary to PDF::

                path = (
                    adae.tlg.ae
                    .population(adsl)
                    .by("TRTA")
                    .rows(["AEBODSYS", "AEDECOD"])
                    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
                    .to_pdf("ae_summary.pdf",
                            metadata=RenderMetadata(title="Table 14.3.1"))
                )
        """

        from .render._models import RenderMetadata as _RM
        from .render._models import ard_to_table_model
        from .render.pdf import render_pdf

        ard = self.to_ard()
        meta = metadata or _RM()
        model = ard_to_table_model(ard, meta)
        return render_pdf(model, path)

    def to_pptx(
        self,
        path: str | Path,
        *,
        metadata: RenderMetadata | None = None,
        theme: dict[str, Any] | None = None,
    ) -> Path:
        """Render the builder result as an editable PPTX slide deck.

        Args:
            path: Output ``.pptx`` file path.
            metadata: Optional ``RenderMetadata`` for title, subtitle,
                footnotes, etc.
            theme: Optional dict of style overrides (font, colours, sizes).

        Returns:
            Path: The written ``.pptx`` path.

        Raises:
            ImportError: If ``python-pptx`` is not installed.

        Examples:
            Inline AE summary to editable slides::

                path = (
                    adae.tlg.ae
                    .population(adsl)
                    .by("TRTA")
                    .rows(["AEBODSYS", "AEDECOD"])
                    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
                    .to_pptx("ae_summary.pptx",
                             metadata=RenderMetadata(title="Table 14.3.1"))
                )
        """

        from .render._models import RenderMetadata as _RM
        from .render._models import ard_to_table_model
        from .render.slides import render_pptx

        ard = self.to_ard()
        meta = metadata or _RM()
        model = ard_to_table_model(ard, meta)
        return render_pptx(model, path, theme=theme)


class BuilderVerbsMixin:
    """Inline-builder entry verbs shared by every TLG sub-namespace.

    A namespace declares ``_builder_specs`` (method name → spec class;
    must include ``"t_summary"``, whose class carries the namespace's
    context label) and inherits ``population()`` / ``filter()`` /
    ``by()`` — so no domain can ship without the inline path.
    """

    _df: pl.DataFrame
    _builder_specs: dict[str, type[TLGSpec]]

    def _builder(self) -> TLGBuilder:
        """Return a ``TLGBuilder`` pre-configured for this namespace."""
        spec_cls = self._builder_specs["t_summary"]
        return TLGBuilder(
            self._df,
            context=getattr(spec_cls, "context", ""),
            spec_cls=spec_cls,
            namespace_cls=type(self),
        )

    def population(
        self,
        adsl: pl.DataFrame,
        *,
        adsl_filter: pl.Expr | str | None = None,
        group_col: str | None = None,
    ) -> TLGBuilder:
        """Start the inline builder with an ADSL population.

        Args:
            adsl: ADSL DataFrame for big-N denominators.
            adsl_filter: Optional population filter on ADSL — a
                ``pl.Expr`` or a string expression.  Only the analysis
                records of the selected subjects are counted.
            group_col: Arm column of ADSL when it differs from the
                analysis arm (``TRT01A`` for an ADAE grouped by ``TRTA``).

        Returns:
            TLGBuilder: A new builder with population set.

        Examples:
            ``df.tlg.ae.population(adsl).by("TRTA").to_ard()``
        """
        return self._builder().population(adsl, adsl_filter=adsl_filter, group_col=group_col)

    def filter(self, expr: pl.Expr | str) -> TLGBuilder:
        """Start the inline builder with a dataset filter.

        Args:
            expr: Polars expression (or string expression) filtering the
                primary dataset.

        Returns:
            TLGBuilder: A new builder with dataset filter set.

        Examples:
            Treatment-emergent AEs only::

                ard = (
                    adae.tlg.ae
                    .filter('pl.col("TRTEMFL") == "Y"')
                    .population(adsl)
                    .by("TRTA")
                    .to_ard()
                )
        """
        return self._builder().filter(expr)

    def by(self, col: str) -> TLGBuilder:
        """Start the inline builder with a primary grouping column.

        Args:
            col: Column name for group1 (e.g. ``"TRTA"``).

        Returns:
            TLGBuilder: A new builder with group1 set.

        Examples:
            Group by actual treatment arm::

                ard = (
                    adae.tlg.ae
                    .by("TRTA")
                    .population(adsl)
                    .to_ard()
                )
        """
        return self._builder().by(col)

    def template(self, template_id: str) -> TLGBuilder:
        """Start the inline builder targeting a registered template.

        Args:
            template_id: Registry id (e.g. ``"aet02"``, ``"ael01"``).

        Returns:
            TLGBuilder: A new builder targeting the template.

        Examples:
            ``listing = adae.tlg.ae.template("ael01").to_listing()``
        """
        return self._builder().template(template_id)

    def columns(self, cols: list[str | Column]) -> TLGBuilder:
        """Start the inline builder with listing display columns.

        Args:
            cols: Ordered listing columns (names or ``Column`` objects).

        Returns:
            TLGBuilder: A new builder with listing columns set.

        Examples:
            ``adae.tlg.ae.columns(["USUBJID", "AEDECOD"]).to_listing()``
        """
        return self._builder().columns(cols)

    def sort_by(self, cols: list[str]) -> TLGBuilder:
        """Start the inline builder with a listing sort order.

        Args:
            cols: Column names to sort the listing by, in order.

        Returns:
            TLGBuilder: A new builder with the sort order set.

        Examples:
            Order the listing by subject::

                listing = (
                    adae.tlg.ae
                    .template("ael01")
                    .sort_by(["USUBJID"])
                    .to_listing()
                )
        """
        return self._builder().sort_by(cols)
