"""
Shared ADaM namespace verbs — mixin classes.

Architecture
------------
Fleet registers ``df.adam`` on every Polars DataFrame; sub-structures are
accessed as properties: ``df.adam.adsl``, ``df.adam.occds``, ``df.adam.onco``,
etc.  Each sub-namespace is its own class, but many verbs are **identical**
across domains (``source``, ``derivation``, ``condderivation``, …).

This module provides **mixin classes** that consolidate the shared logic so
that each namespace class only defines its domain-specific methods.

Adding or removing a shared verb
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
1. **To add** a new shared verb: add the method to
   ``SharedADaMVerbsMixin`` below.  Every namespace class that inherits
   from the mixin gets the verb automatically — no per-class edits needed.

2. **To remove** a shared verb from a *specific* namespace: override it in
   that class's body and raise ``NotImplementedError``, or refactor the
   verb into a *separate* mixin that is only inherited by the classes that
   need it.

3. **To extend** a shared verb in one namespace: override the method and
   call ``super().method_name(...)`` if you need the base logic::

       class ADSLNamespace(SharedADaMVerbsMixin):
           def derivation(self, target, *, expression):
               # extra ADSL-specific validation
               ...
               return super().derivation(target, expression=expression)

Controlling verb visibility per namespace
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Every namespace class declares which mixin(s) it inherits from.  That
single inheritance list is the **authoritative control** over which
shared verbs appear on that namespace:

    class OCCDSNamespace(SharedADaMVerbsMixin):  # ← gets all shared verbs
        ...

    class OncoNamespace(SharedADaMVerbsMixin):   # ← same mixin, same verbs
        ...

If a future group of verbs only makes sense for some namespaces, factor
them into a **separate** mixin (e.g. ``DateDerivationMixin``) and inherit
selectively::

    class ADSLNamespace(SharedADaMVerbsMixin, DateDerivationMixin):
        ...

    class OncoNamespace(SharedADaMVerbsMixin):  # no date verbs
        ...

Cross-module mixins
~~~~~~~~~~~~~~~~~~~~
``FlagCriterionMixin`` (now defined in :mod:`fleet.core._flag_mixin`,
re-exported here for backward compatibility) provides ``flag()`` and
``criterion()`` to both ADaM namespaces (via ``SharedADaMVerbsMixin``
inheritance) **and** the SDTM namespace.  Any namespace that exposes
``_chain()`` / ``_with_lazy()`` / ``_materialise_then()`` can inherit it.

Return types & IDE support
~~~~~~~~~~~~~~~~~~~~~~~~~~~
All shared methods use ``typing.Self`` as their return type.  IDEs resolve
``Self`` to the concrete class at each call-site — so
``df.adam.adsl.source(...)`` auto-completes to ``ADSLNamespace`` methods,
and ``df.adam.onco.source(...)`` auto-completes to ``OncoNamespace``
methods.  No ``if TYPE_CHECKING`` stubs or protocol tricks are needed.
"""

from __future__ import annotations

import copy
import difflib
from typing import TYPE_CHECKING, Any, Self

import polars as pl

from fleet.core._deprecation import deprecated_kwargs, deprecated_verb
from fleet.core._flag_mixin import (
    _FLAG_CRITERIA_KEYWORDS,  # noqa: F401  — backward-compat re-export
    FlagCriterionMixin,
)
from fleet.core._pin_mixin import PinMixin
from fleet.core._verb_mixin import SharedVerbsMixin
from fleet.core.exceptions import DerivationError

if TYPE_CHECKING:
    pass


class SharedADaMVerbsMixin(SharedVerbsMixin, PinMixin, FlagCriterionMixin):
    """Base mixin providing the shared verbs and chaining infrastructure.

    Inherits algorithmic and infrastructure verbs from ``SharedVerbsMixin``
    (derivation, duration, study_day, seq, validate, select, inspect,
    explain, to_frame, to_dataset_json, write_parquet, _chain,
    _materialise_then).

    Concrete namespace classes inherit from this mixin.  The ``_chain``
    and ``_materialise_then`` helpers use ``copy.copy(self)`` so the
    returned instance stays the correct sub-type for continued chaining.

    Required instance attribute
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~
    ``_lazy: pl.LazyFrame``  — set by ``__init__``.
    """

    _lazy: pl.LazyFrame

    _FK_RULES: dict[str, dict[str, str]] = {
        "USUBJID": {"pin": "ADSL", "ref_col": "USUBJID"},
    }

    # -- SharedVerbsMixin configuration for ADaM --
    _STUDY_DAY_REF_COL: str = "TRTSDT"
    _STUDY_DAY_REF_PIN: str = "ADSL"
    _SEQ_DEFAULT_GROUPS: list[str] = ["USUBJID"]
    _VALIDATE_STANDARD: str = "adam"
    _VALIDATE_DEFAULT_VERSION: str = "1.3"

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def __init__(self, df: pl.DataFrame | pl.LazyFrame) -> None:
        self._lazy = df.lazy()
        self._domain: str | None = None
        self._pinned: dict[str, tuple[pl.DataFrame, list[str]]] = {}
        self._pin_lineage: list = []
        self._pending_fk_checks: list[tuple[str, str, str, str]] = []

    def __call__(self, domain: str) -> Self:
        """Return a copy of this namespace with *domain* set for CDISC lineage.

        Args:
            domain: CDISC domain code (e.g. ``"ADAE"``, ``"ADVS"``).

        Returns:
            Self: A shallow copy whose lineage records will carry *domain*.

        Examples:
            Tag an OCCDS pipeline as ADAE::

                adae = (
                    ae_with_trt.adam.occds("ADAE")
                    .source("USUBJID")
                    .treatment_emergent("TRTEMFL", start_date="AESTDTC",
                                        trtsdt="TRTSDT", trtedt="TRTEDT")
                    .to_frame()
                )
        """
        new = copy.copy(self)
        new._domain = domain
        return new

    # ------------------------------------------------------------------ #
    # Cross-domain: pin-powered verbs                                      #
    # ------------------------------------------------------------------ #

    def join_adsl(self, *cols: str) -> Self:
        """Pull columns from pinned ADSL into this pipeline.

        Performs a left join on the pinned join key, keeps only the
        requested columns, and records ``carry_forward`` lineage for
        each column.

        Args:
            *cols: Column names to carry forward from ADSL
                (e.g. ``"TRTSDT"``, ``"TRTEDT"``, ``"SAFFL"``).

        Returns:
            Self: The namespace with ADSL columns attached; call
                ``.to_frame()`` to materialise.

        Raises:
            LookupError: If ADSL is not pinned.

        Examples:
            Carry TRTSDT and SAFFL from ADSL into an ADAE pipeline::

                adae = (
                    ae_df.adam.occds("ADAE")
                    .pin("ADSL", adsl_df)
                    .source("USUBJID")
                    .join_adsl("TRTSDT", "TRTEDT", "SAFFL")
                    .to_frame()
                )
        """
        from fleet.core.lineage import record_pin_lineage

        ref_df = self._require_pin("ADSL", "join_adsl", columns=list(cols))
        join_key = self._pin_join_key("ADSL")

        ref_slim = ref_df.select(
            [c for c in dict.fromkeys(join_key + list(cols)) if c in ref_df.columns]
        ).unique(subset=join_key)

        df = self._lazy.collect().join(ref_slim, on=join_key, how="left")
        new = self._materialise_then(df)

        for col in cols:
            record_pin_lineage(
                new,
                target_col=col,
                verb="join_adsl",
                source_domain="ADSL",
                source_cols=[col],
                join_key=join_key,
                relationship="carry_forward",
            )
        return new

    # study_day is inherited from SharedVerbsMixin (one shared
    # implementation; `adsl=` / `dm=` are documented ref_df aliases).

    # ------------------------------------------------------------------ #
    # Shared verbs                                                         #
    # ------------------------------------------------------------------ #

    def source(self, *targets: str, from_col: str | None = None) -> Self:
        """Carry one or more source columns into the ADaM dataset.

        With a single name and ``from_col=``, copies *from_col* to the
        target (legacy 1:1 form — prefer ``assign(target, source=...)``).
        With multiple names, each column is carried through as-is::

            .source("STUDYID", "USUBJID", "AETERM")

        Args:
            *targets: Output ADaM variable name(s).  Without *from_col*
                each is an identity copy of the same-named input column.
            from_col: Name of the input column to copy from (single
                target only).  Defaults to the target name.

        Returns:
            Self: The namespace with the target(s) appended; call
                ``.to_frame()`` to materialise.

        Raises:
            DerivationError: When no target is given, or *from_col* is
                combined with more than one target.

        Examples:
            Carry the key variables through in one call::

                adae = (
                    ae_df.adam
                    .source("STUDYID", "USUBJID", "AEDECOD")
                    .to_frame()
                )
        """
        if not targets:
            raise DerivationError("source() requires at least one column name.")
        if from_col is not None:
            if len(targets) > 1:
                raise DerivationError(
                    "source(): from_col= applies to a single target — got "
                    f"{len(targets)} targets. Use assign(target, source=...) "
                    "for renames, or list the columns without from_col."
                )
            return self._chain(pl.col(from_col).alias(targets[0]), verb="source")
        exprs = [pl.col(t).alias(t) for t in targets]
        return self._chain(*exprs, verb="source")

    @deprecated_verb("assigned", use="assign(target, value=...)")
    def assigned(self, target: str, *, value: Any) -> Self:
        """Set *target* to a constant *value* for every record.

        Deprecated alias of
        :meth:`~fleet.core._verb_mixin.SharedVerbsMixin.assign`.

        Args:
            target: Name of the output ADaM variable.
            value: The literal value to broadcast.

        Returns:
            Self: The namespace with *target* appended; call ``.to_frame()``
                to materialise.

        Examples:
            Set a constant ``PARAMCD``::

                advs = (
                    vs_df.adam
                    .assign("PARAMCD", value="SYSBP")
                    .to_frame()
                )
        """
        return self._assign_impl(target, value=value, verb="assigned", fk=False)

    def recode(
        self,
        target: str,
        *,
        source: str,
        recode_map: dict[Any, Any],
        default: Any = None,
    ) -> Self:
        """Map values in *source* to recoded values in *target*.

        Unmapped values fall back to *default*.

        Args:
            target: Name of the output ADaM variable.
            source: Name of the input column containing coded values.
            recode_map: ``{old_value: new_value}`` mapping.
            default: Value for entries not present in *recode_map*.

        Returns:
            Self: The namespace with *target* appended; call ``.to_frame()``
                to materialise.

        Examples:
            Recode numeric sex to character::

                adsl = (
                    dm_df.adam.adsl
                    .recode("SEX", source="SEXN",
                            recode_map={1: "M", 2: "F"})
                    .to_frame()
                )
        """
        if recode_map:
            default_expr = default if isinstance(default, pl.Expr) else pl.lit(default)
            expr = (
                pl.col(source)
                .replace_strict(recode_map, default=default_expr, return_dtype=pl.String)
                .alias(target)
            )
        else:
            default_expr = default if isinstance(default, pl.Expr) else pl.lit(default)
            expr = default_expr.alias(target)
        return self._chain(expr, verb="recode")

    @deprecated_verb("rename", use="assign(target, source=...)")
    def rename(self, target: str, *, source: str) -> Self:
        """Create *target* as a copy of *source* (variable renaming).

        Deprecated alias of
        :meth:`~fleet.core._verb_mixin.SharedVerbsMixin.assign`.

        Args:
            target: Name of the output ADaM variable.
            source: Name of the existing column to rename.

        Returns:
            Self: The namespace with *target* appended; call ``.to_frame()``
                to materialise.

        Examples:
            Rename ``VSTEST`` to ``PARAM``::

                advs = (
                    vs_df.adam
                    .assign("PARAM", source="VSTEST")
                    .to_frame()
                )
        """
        return self._assign_impl(target, source=source, verb="rename", fk=False)

    @deprecated_verb("condderivation", use="case_when(target, when=[...], else_=...)")
    def condderivation(
        self,
        target: str,
        *,
        conditions: list[dict[str, Any]],
        else_value: Any = None,
    ) -> Self:
        """Multi-branch conditional derivation (when/then/otherwise chain).

        Deprecated alias of
        :meth:`~fleet.core._verb_mixin.SharedVerbsMixin.case_when` — pass
        ``when=`` / ``else_=`` instead of ``conditions=`` / ``else_value=``.

        Args:
            target: Name of the output ADaM variable.
            conditions: List of ``{"condition": expr, "value": any}`` dicts.
            else_value: Fallback value when no condition matches.

        Returns:
            Self: The namespace with *target* appended; call ``.to_frame()``
                to materialise.

        Examples:
            Derive ``DTYPE`` based on imputation method::

                advs = (
                    vs_df.adam
                    .case_when("DTYPE", when=[
                        {"condition": 'pl.col("LOCF_FLAG") == "Y"', "value": "LOCF"},
                        {"condition": 'pl.col("WOCF_FLAG") == "Y"', "value": "WOCF"},
                    ], else_=None)
                    .to_frame()
                )
        """
        return self._case_when_impl(
            target, when=conditions, else_=else_value, verb="condderivation"
        )

    # ------------------------------------------------------------------ #
    # pick — priority-ordered event selection across sources               #
    # ------------------------------------------------------------------ #

    def pick(
        self,
        targets: str | list[str],
        *,
        events: list[dict[str, Any]],
        by: list[str] | None = None,
        order: str | list[str] | None = None,
        mode: str = "first",
    ) -> Self:
        """Derive targets from the highest-priority matching event per group.

        Each event in the ordered list defines a candidate source, a filter
        condition, and values to set when that event is selected.  Events are
        evaluated in list order (first = highest priority).  Within each
        event's matching records, *mode* and *order* select which record
        provides the final values.

        This is Fleet's answer to multi-source cascading derivations such as
        last-date-known-alive (LSTALVDT), death cause (DTHCAUS), or any
        variable that requires "try source A first, else B, else C" logic.

        Event dict keys:

        - ``"when"`` (required): Boolean expression (``str | pl.Expr``)
          filtering which records qualify.
        - ``"set"`` (required): ``dict[str, str | pl.Expr | Any]`` mapping
          each target name to a column reference, expression, or literal.
          Column references use bare names (``"DTHDT"``); literals must be
          wrapped in ``pl.lit()``.
        - ``"source"`` (optional): External ``pl.DataFrame`` to scan for
          this event.  When omitted, the current pipeline frame is used.
        - ``"mode"`` (optional): Override the top-level *mode* for this
          event only (``"first"`` | ``"last"``).
        - ``"order"`` (optional): Override the top-level *order* for this
          event only.
        - ``"label"`` (optional): Documentation-only description.

        Args:
            targets: Target column name(s) to derive.
            events: Ordered list of event dicts (highest priority first).
            by: Grouping columns (default ``["USUBJID"]``).
            order: Sort column(s) for selecting within an event's matches.
                Required when multiple records may match a single event.
            mode: ``"first"`` or ``"last"`` — which record to select
                after sorting by *order* (default ``"first"``).

        Returns:
            Self: A fresh namespace with *targets* added; call
                ``.to_frame()`` to materialise.

        Raises:
            DerivationError: If *events* is empty, a required key is
                missing, or an event contains an unknown key (with a
                did-you-mean suggestion).  Also catchable as
                ``ValueError``.

        Examples:
            Derive last date known alive from death, AE, and treatment::

                adsl = (
                    dm.adam.adsl
                    .source("USUBJID")
                    .pick(
                        ["LSTALVDT", "DTHFL"],
                        events=[
                            {"when": pl.col("DTHDT").is_not_null(),
                             "set": {"LSTALVDT": "DTHDT", "DTHFL": pl.lit("Y")},
                             "source": adsl_df, "label": "Death date"},
                            {"when": pl.col("AEENDTC").is_not_null(),
                             "set": {"LSTALVDT": "AEENDTC", "DTHFL": pl.lit("N")},
                             "source": ae, "mode": "last", "order": ["AEENDTC"]},
                            {"when": pl.col("TRTEDT").is_not_null(),
                             "set": {"LSTALVDT": "TRTEDT", "DTHFL": pl.lit("N")},
                             "source": adsl_df},
                        ],
                        by=["USUBJID"],
                        order=["LSTALVDT"],
                        mode="last",
                    )
                    .to_frame()
                )

            Simple single-target with string conditions (YAML-friendly)::

                adsl = (
                    dm.adam.adsl
                    .pick(
                        "DTHCAUS",
                        events=[
                            {"when": 'pl.col("AEOUT") == "FATAL"',
                             "set": {"DTHCAUS": "AEDECOD"},
                             "source": ae},
                            {"when": 'pl.col("DSDECOD") == "DEATH"',
                             "set": {"DTHCAUS": "DSTERM"},
                             "source": ds},
                        ],
                        by=["USUBJID"],
                    )
                    .to_frame()
                )
        """
        from fleet.sdtm.utils import parse_expression

        if not events:
            raise DerivationError("pick() requires at least one event.")

        target_list = [targets] if isinstance(targets, str) else list(targets)
        by_vars = by or ["USUBJID"]
        global_order: list[str] | None = (
            [order] if isinstance(order, str) else list(order) if order else None
        )

        df = self.to_frame()

        # Collect one candidate row per event per group.
        candidate_frames: list[pl.DataFrame] = []

        valid_event_keys = {"when", "set", "source", "mode", "order", "label"}
        for event_nr, event in enumerate(events):
            unknown = sorted(set(event) - valid_event_keys)
            if unknown:
                hints = []
                for key in unknown:
                    close = difflib.get_close_matches(str(key), sorted(valid_event_keys), n=1)
                    hints.append(f"'{key}'" + (f" (did you mean '{close[0]}'?)" if close else ""))
                raise DerivationError(
                    f"pick() event #{event_nr} contains unknown key(s): {', '.join(hints)}. "
                    f"Valid keys: {sorted(valid_event_keys)}."
                )
            if "when" not in event or "set" not in event:
                raise DerivationError(
                    f"Event #{event_nr} must contain 'when' and 'set' keys. "
                    f"Got keys: {list(event.keys())}"
                )

            # Resolve source frame
            source_df: pl.DataFrame = event.get("source", df)

            # Resolve condition
            when_raw = event["when"]
            when_expr: pl.Expr = (
                when_raw if isinstance(when_raw, pl.Expr) else parse_expression(str(when_raw))
            )

            # Filter candidates
            candidates = source_df.filter(when_expr)
            if candidates.is_empty():
                continue

            # Build set-values expressions
            set_exprs: list[pl.Expr] = []
            set_spec: dict[str, Any] = event["set"]
            for tgt in target_list:
                if tgt not in set_spec:
                    # Target not produced by this event → null placeholder
                    set_exprs.append(pl.lit(None).alias(tgt))
                    continue
                val = set_spec[tgt]
                if isinstance(val, pl.Expr):
                    set_exprs.append(val.alias(tgt))
                elif isinstance(val, str):
                    # String → parse as expression or column reference.
                    # parse_expression handles both: bare names ("AEENDTC")
                    # become pl.col("AEENDTC"); expression strings like
                    # 'pl.lit("Y")' are evaluated via sandboxed AST.
                    set_exprs.append(parse_expression(val).alias(tgt))
                else:
                    # Literal value
                    set_exprs.append(pl.lit(val).alias(tgt))

            # Apply set expressions + add event priority marker
            candidates = candidates.with_columns(
                *set_exprs,
                pl.lit(event_nr).cast(pl.UInt32).alias("__pick_event_nr__"),
            )

            # Resolve per-event mode/order
            evt_mode = event.get("mode", mode)
            evt_order_raw = event.get("order", global_order)
            evt_order: list[str] | None = (
                [evt_order_raw] if isinstance(evt_order_raw, str) else evt_order_raw
            )

            # Within-event selection: pick one record per group
            if evt_order:
                descending = evt_mode == "last"
                candidates = candidates.sort(
                    evt_order,
                    descending=[descending] * len(evt_order),
                    nulls_last=True,
                )
            candidates = candidates.group_by(by_vars, maintain_order=True).first()

            # Keep only by_vars + targets + event_nr
            keep = by_vars + target_list + ["__pick_event_nr__"]
            available = [c for c in keep if c in candidates.columns]
            candidates = candidates.select(available)

            candidate_frames.append(candidates)

        # No events matched at all — set all targets to null
        if not candidate_frames:
            null_exprs = [pl.lit(None).alias(t) for t in target_list]
            return self._materialise_then(df.with_columns(null_exprs))

        # Stack all candidates and pick the winning event per group
        all_candidates = pl.concat(candidate_frames, how="diagonal_relaxed")

        # Sort by event priority (lowest nr = highest priority), then order
        sort_cols = ["__pick_event_nr__"]
        sort_desc = [False]
        if global_order:
            sort_cols.extend(global_order)
            global_mode_desc = mode == "last"
            sort_desc.extend([global_mode_desc] * len(global_order))

        all_candidates = all_candidates.sort(sort_cols, descending=sort_desc, nulls_last=True)
        winners = all_candidates.group_by(by_vars, maintain_order=True).first()
        winners = winners.select(by_vars + target_list)

        # Drop pre-existing target columns from base frame before join
        drop_existing = [t for t in target_list if t in df.columns]
        if drop_existing:
            df = df.drop(drop_existing)

        result = df.join(winners, on=by_vars, how="left")
        return self._materialise_then(result)

    def whereclauses(self, *, where: str | pl.Expr) -> Self:
        """Filter records by a *where* expression.

        Materialises the pipeline before applying the filter.

        Args:
            where: A Polars expression (or string) that evaluates to a
                boolean mask.

        Returns:
            Self: A fresh namespace wrapping the filtered frame.

        Examples:
            Subset to on-treatment records only::

                advs = (
                    vs_df.adam
                    .whereclauses(where='pl.col("ONTRTFL") == "Y"')
                    .to_frame()
                )
        """
        from fleet.sdtm.utils import parse_expression

        df = self.to_frame()
        filter_expr = where if isinstance(where, pl.Expr) else parse_expression(str(where))
        return self._materialise_then(df.filter(filter_expr))

    @deprecated_kwargs(keep_cols="keep")
    def merge_adsl(
        self,
        adsl: pl.DataFrame,
        *,
        by: list[str] | None = None,
        keep: list[str] | None = None,
    ) -> Self:
        """Left-join ADSL columns onto the current dataset.

        Materialises the pipeline, left-joins *adsl* (optionally restricted to
        *keep* plus the *by* key columns), and returns a fresh namespace.

        Args:
            adsl: The ADSL ``pl.DataFrame`` to merge in.
            by: Key column(s) for the join (default ``["USUBJID"]``).
            keep: Subset of ADSL columns to bring in (excluding *by*
                keys, which are always included).  When ``None``, all ADSL
                columns are merged.  The legacy ``keep_cols=`` spelling is
                accepted with a ``FutureWarning``.

        Returns:
            Self: A fresh namespace wrapping the joined frame.

        Examples:
            Merge treatment date columns from ADSL::

                advs = (
                    vs_df.adam
                    .merge_adsl(adsl_df, keep=["TRTSDT", "TRTEDT", "TRT01P"])
                    .to_frame()
                )
        """
        join_keys = by if by is not None else ["USUBJID"]
        if keep is not None:
            extra = [c for c in join_keys if c not in keep]
            adsl = adsl.select(keep + extra)
        df = self.to_frame()
        joined = df.join(adsl, on=join_keys, how="left")
        return self._materialise_then(joined)

    # ------------------------------------------------------------------ #
    # Subject-level event aggregations (first_date / last_date / count)    #
    # ------------------------------------------------------------------ #

    @deprecated_kwargs(groups="by")
    def first_date(
        self,
        target: str,
        *,
        from_dataset: pl.DataFrame,
        date_col: str,
        where: str | pl.Expr | None = None,
        by: list[str] | None = None,
    ) -> Self:
        """Derive *target* as the earliest date in *date_col* from *from_dataset*.

        Materialises the current pipeline, aggregates *from_dataset* to
        subject level, then left-joins.  Useful for ASTDTM, TRTSDT, etc.

        Args:
            target: Name of the output date column.
            from_dataset: Source ``pl.DataFrame`` to aggregate.
            date_col: Date column to take the minimum of.
            where: Optional filter applied to *from_dataset* before aggregation.
            by: Join key columns (default ``["USUBJID"]``).  The legacy
                ``groups=`` spelling is accepted with a ``FutureWarning``.

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive earliest serious AE start date::

                adsl = (
                    dm_raw.adam.adsl
                    .first_date("AESTDTM", from_dataset=ae_sdtm,
                                date_col="AESTDTC",
                                where='pl.col("AESER") == "Y"')
                    .to_frame()
                )
        """
        return self._date_agg(
            target,
            from_dataset=from_dataset,
            date_col=date_col,
            where=where,
            by=by,
            agg_fn="min",
        )

    @deprecated_kwargs(groups="by")
    def last_date(
        self,
        target: str,
        *,
        from_dataset: pl.DataFrame,
        date_col: str,
        where: str | pl.Expr | None = None,
        by: list[str] | None = None,
    ) -> Self:
        """Derive *target* as the latest date in *date_col* from *from_dataset*.

        Useful for AENDTM, TRTEDT, DTHDT, etc.

        Args:
            target: Name of the output date column.
            from_dataset: Source ``pl.DataFrame`` to aggregate.
            date_col: Date column to take the maximum of.
            where: Optional filter applied to *from_dataset* before aggregation.
            by: Join key columns (default ``["USUBJID"]``).  The legacy
                ``groups=`` spelling is accepted with a ``FutureWarning``.

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Derive latest treatment end date::

                adsl = (
                    dm_raw.adam.adsl
                    .last_date("TRTEDT", from_dataset=ex_sdtm,
                               date_col="EXENDTC")
                    .to_frame()
                )
        """
        return self._date_agg(
            target,
            from_dataset=from_dataset,
            date_col=date_col,
            where=where,
            by=by,
            agg_fn="max",
        )

    def _date_agg(
        self,
        target: str,
        *,
        from_dataset: pl.DataFrame,
        date_col: str,
        where: str | pl.Expr | None,
        by: list[str] | None,
        agg_fn: str,
    ) -> Self:
        """Shared implementation for first_date/last_date."""
        from fleet.sdtm.utils import parse_expression

        grps = by or ["USUBJID"]
        src = from_dataset
        if where is not None:
            where_expr = where if isinstance(where, pl.Expr) else parse_expression(str(where))
            src = src.filter(where_expr)
        col = pl.col(date_col)
        agg_expr = (col.min() if agg_fn == "min" else col.max()).alias(target)
        agg_df = src.group_by(grps).agg(agg_expr)
        df = self.to_frame().join(agg_df, on=grps, how="left")
        return self._materialise_then(df)

    @deprecated_kwargs(groups="by")
    def count_events(
        self,
        target: str,
        *,
        from_dataset: pl.DataFrame,
        where: str | pl.Expr | None = None,
        by: list[str] | None = None,
    ) -> Self:
        """Derive *target* as the count of matching records in *from_dataset*.

        Returns 0 for subjects with no matching records (never null).

        Args:
            target: Name of the output count column.
            from_dataset: Source ``pl.DataFrame`` to count.
            where: Optional filter applied before counting.
            by: Join key columns (default ``["USUBJID"]``).  The legacy
                ``groups=`` spelling is accepted with a ``FutureWarning``.

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Count total AE records per subject::

                adsl = (
                    dm_raw.adam.adsl
                    .count_events("NUMAE", from_dataset=ae_sdtm)
                    .to_frame()
                )
        """
        from fleet.sdtm.utils import parse_expression

        grps = by or ["USUBJID"]
        src = from_dataset
        if where is not None:
            where_expr = where if isinstance(where, pl.Expr) else parse_expression(str(where))
            src = src.filter(where_expr)
        agg_df = src.group_by(grps).agg(pl.len().alias(target))
        df = self.to_frame().join(agg_df, on=grps, how="left")
        df = df.with_columns(pl.col(target).fill_null(0))
        return self._materialise_then(df)

    # ------------------------------------------------------------------ #
    # Date derivation verbs                                                #
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # Unified date / duration verbs                                        #
    # ------------------------------------------------------------------ #

    def date(
        self,
        target: str,
        *,
        source: str | None = None,
        value: str | None = None,
        output: str | None = None,
        time: str | None = None,
        impute: str = "first",
        impute_time: str | None = None,
        highest: str | None = None,
        flag: bool | str = True,
        min_date: str | None = None,
        max_date: str | None = None,
    ) -> Self:
        """Parse, convert, impute, and flag a date or datetime column.

        Dispatches behavior based on the CDISC suffix of *target* (DT, DTM)
        or an explicit *output* override.  Supports both column references
        (``source=``) and literal values (``value=``).

        Args:
            target: Name of the output column.
            source: Column name to read values from.  Mutually exclusive
                with *value*.
            value: Literal date value to broadcast.  Mutually exclusive
                with *source*.
            output: Explicit output type override: ``"dt"`` or ``"dtm"``.
                When omitted, inferred from the *target* suffix.
            time: Time column name or ``"HH:MM:SS"`` literal to combine
                with the date from *source* (DTM targets only).
            impute: Imputation strategy for missing date components:
                ``"first"`` (default), ``"mid"``, ``"last"``, ``"none"``.
            impute_time: Override for time-part imputation, separate from
                *impute*.  Only relevant for DTM targets.
            highest: Maximum imputation ceiling (``"D"``, ``"M"``, ``"Y"``,
                ``"h"``, ``"m"``, ``"s"``).  Rows that exceed the ceiling
                are set to null.
            flag: ``True`` to auto-generate DTF/TMF flag columns,
                ``False`` to suppress, or a string to name the DTF flag
                explicitly.
            min_date: Lower clamp bound (column name or date literal).
            max_date: Upper clamp bound (column name or date literal).

        Returns:
            Self: The namespace with *target* (and optionally flag columns)
                appended; call ``.to_frame()`` to materialise.

        Examples:
            Derive ADT from a DTC source with default imputation::

                advs = (
                    vs_df.adam
                    .date("ADT", source="VSDTC")
                    .to_frame()
                )

            Non-standard target with explicit output and flag::

                df = (
                    raw.adam
                    .date("XYZ", source="raw_date", output="dt",
                          flag="XYZDTF")
                    .to_frame()
                )

            Broadcast a literal date::

                adsl = (
                    dm.adam.adsl
                    .date("RFSTDT", value="2024-01-15", output="dt",
                          flag=False)
                    .to_frame()
                )
        """
        from datetime import date as _date
        from datetime import datetime as _datetime

        from fleet.adam.utils import (
            _resolve_output_type,
            impute_and_flag,
        )

        # ── validate source / value mutual exclusivity ──
        if source is not None and value is not None:
            raise DerivationError("Cannot specify both source= and value=. Choose one.")
        if source is None and value is None:
            raise DerivationError("Must specify either source= or value=.")

        output_type = _resolve_output_type(target, output)

        # DTC targets belong in SDTM, not ADaM
        if output_type == "dtc":
            raise DerivationError(
                f"DTC output type is not supported on ADaM namespaces. "
                f"Use the SDTM .date() verb for target '{target}'."
            )

        # time= only valid for DTM
        if time is not None and output_type != "dtm":
            raise DerivationError(
                f"time= parameter is only valid for DTM targets, "
                f"but target '{target}' resolves to output='{output_type}'."
            )

        # value= path: broadcast literal, skip imputation
        if value is not None:
            # Default flags to False for value= (no imputation)
            if flag is True:
                flag = False
            # Parse string values to appropriate Python types
            val: str | _date | _datetime = value
            if isinstance(value, str):
                val = value
            exprs = impute_and_flag(
                None,
                target,
                value=val,
                output_type=output_type,
                flag=flag,
            )
            return self._chain(*exprs, verb="date")

        # source= path
        assert source is not None

        if output_type == "dt":
            exprs = impute_and_flag(
                source,
                target,
                output_type="dt",
                impute=impute,
                highest=highest,
                min_date=min_date,
                max_date=max_date,
                flag=flag,
            )
            return self._chain(*exprs, verb="date")

        # output_type == "dtm"
        # DTM with partial dates requires materialisation (same as derive_dtm)
        from fleet.adam.utils import (
            _resolve_flag_names,
            _resolve_time,
            dtf_expr,
            impute_dtc_to_date,
            impute_dtc_to_datetime,
            tmf_expr,
        )

        dtf_name, tmf_name = _resolve_flag_names(target, flag, output_type)
        effective_time_impute = impute_time or impute

        col = pl.col(source)
        length = col.str.len_chars()

        # Materialise for partial date handling
        date_expr = impute_dtc_to_date(
            source,
            "__dtm_date_tmp__",
            day_imputation=impute,
            month_imputation=impute,
        )
        df = self._lazy.with_columns(date_expr).collect()

        # Build datetime expression
        dtm_expr = impute_dtc_to_datetime(
            source,
            target,
            day_imputation=impute,
            month_imputation=impute,
            time_imputation=effective_time_impute,
        )

        time_suffix = _resolve_time(effective_time_impute)
        if effective_time_impute == "none":
            partial_dtm = pl.lit(None, dtype=pl.Datetime("us"))
        elif isinstance(time_suffix, str) and time_suffix.startswith("T"):
            partial_dtm = (
                pl.col("__dtm_date_tmp__").dt.to_string("%Y-%m-%d") + pl.lit(time_suffix)
            ).str.to_datetime("%Y-%m-%dT%H:%M:%S", strict=False)
        else:
            partial_dtm = (
                pl.col("__dtm_date_tmp__").dt.to_string("%Y-%m-%d")
                + pl.lit("T")
                + pl.col(time_suffix).cast(pl.Time).cast(pl.String)
            ).str.to_datetime("%Y-%m-%dT%H:%M:%S", strict=False)

        dtm_full = (
            pl.when(col.is_null() | (length == 0))
            .then(pl.lit(None, dtype=pl.Datetime("us")))
            .when(length >= 10)
            .then(dtm_expr)
            .otherwise(partial_dtm)
            .alias(target)
        )

        exprs_list: list[pl.Expr] = [dtm_full]
        if dtf_name is not None:
            exprs_list.append(dtf_expr(source, dtf_name))
        if tmf_name is not None:
            exprs_list.append(tmf_expr(source, tmf_name))

        result = df.with_columns(exprs_list)
        if "__dtm_date_tmp__" in result.columns:
            result = result.drop("__dtm_date_tmp__")
        return self._materialise_then(result)


class MultiRowMixin:
    """
    Mixin for ADaM datasets with multiple rows per subject (OCCDS, PK, etc.).

    Previously provided ``seq()`` which has been moved to
    ``SharedVerbsMixin``.  Retained as a marker interface for multi-row
    namespace classes (OCCDS, PK, etc.).
    """

    pass
