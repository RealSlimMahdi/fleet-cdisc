"""
Shared ADaM namespace verbs — mixin classes.

Architecture
------------
Fleet registers ``df.adam`` on every Polars DataFrame; sub-structures are
accessed as properties: ``df.adam.adsl``, ``df.adam.occds``, ``df.adam.onco``,
etc.  Each sub-namespace is its own class, but many verbs are **identical**
across domains (``source``, ``derivation``, ``case_when``, …).

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
import warnings
from typing import TYPE_CHECKING, Any, Self

import polars as pl

from fleet.core._flag_mixin import (
    _FLAG_CRITERIA_KEYWORDS,  # noqa: F401  — backward-compat re-export
    FlagCriterionMixin,
)
from fleet.core._pin_mixin import PinMixin
from fleet.core._verb_mixin import SharedVerbsMixin
from fleet.core.exceptions import DerivationError
from fleet.core.joins import refuse_repeated_keys, refuse_shared_columns, require_columns

if TYPE_CHECKING:
    pass

#: What to do when an aggregation target is already a pipeline column.
_CLASH_HINT = "Drop the column from the pipeline first, or choose another target name."


def _value_kind(value: Any) -> str:
    """The kind of a recode value: ``bool``, ``int``, ``float``, ``str`` or its type name."""
    for kind in (bool, int, float, str):
        if isinstance(value, kind):
            return kind.__name__
    return type(value).__name__


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
    _VALIDATE_STANDARD = "adam"

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
                    .treatment_emergent("TRTEMFL", start_date="ASTDT",
                                        end_date="AENDT", trtsdt="TRTSDT")
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
            DerivationError: If a column is not in ADSL (with a
                did-you-mean suggestion), is already in the pipeline, or
                ADSL has two different rows for one subject.

        References:
            ADR-0032 (docs/adr/0032-merge-reads-as-sas-merge-and-stops-on-a-clash.md).
            ADaMIG 1.3: ADSL holds one record per subject.

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

        adsl = self._require_pin("ADSL", "join_adsl")
        join_key = self._pin_join_key("ADSL")
        require_columns("join_adsl()", cols, adsl.columns, where="the pinned ADSL")
        refuse_shared_columns(
            "join_adsl()",
            self._lazy.collect_schema().names(),
            cols,
            join_key,
            hint="Drop the column from the pipeline first, or leave it out of join_adsl().",
        )
        ref_slim = refuse_repeated_keys(
            "join_adsl()",
            adsl.select(list(dict.fromkeys(join_key + list(cols)))),
            join_key,
            source="ADSL",
        )

        df = self._lazy.collect().join(ref_slim, on=join_key, how="left", nulls_equal=True)
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

    def recode(
        self,
        target: str,
        *,
        source: str,
        recode_map: dict[Any, Any],
        default: Any = None,
    ) -> Self:
        """Map values in *source* to recoded values in *target*.

        Unmapped values fall back to *default*.  The output type follows
        the map values and a literal *default*, ignoring ``None``: integers
        give an integer column, integers with floats a float column (ADaM
        ``*N`` variables such as ASEVN and AVISITN are Num), and text gives
        text.  A map that mixes kinds raises, so a typing slip cannot give a
        text ``*N`` variable.

        Args:
            target: Name of the output ADaM variable.
            source: Name of the input column containing coded values.
            recode_map: ``{old_value: new_value}`` mapping.
            default: Value for entries not present in *recode_map*.

        Returns:
            Self: The namespace with *target* appended; call ``.to_frame()``
                to materialise.

        Raises:
            DerivationError: When the map values and *default* mix kinds.

        Examples:
            Recode numeric sex to character::

                adsl = (
                    dm_df.adam.adsl
                    .recode("SEX", source="SEXN",
                            recode_map={1: "M", 2: "F"})
                    .to_frame()
                )

            Code severity to a number::

                adae = (
                    ae_df.adam.occds
                    .recode("ASEVN", source="ASEV",
                            recode_map={"MILD": 1, "MODERATE": 2, "SEVERE": 3})
                    .to_frame()
                )
        """
        default_expr = default if isinstance(default, pl.Expr) else pl.lit(default)
        if not recode_map:
            return self._chain(default_expr.alias(target), verb="recode")
        values = [*recode_map.values(), *([] if isinstance(default, pl.Expr) else [default])]
        kinds = {_value_kind(v) for v in values if v is not None}
        return_dtype: pl.DataType | None = None
        if kinds == {"int", "float"}:
            recode_map = {k: None if v is None else float(v) for k, v in recode_map.items()}
        elif len(kinds) > 1:
            raise DerivationError(
                f"recode('{target}'): the map values and default mix {sorted(kinds)}. "
                f"Give one kind, so {target} is numeric or text."
            )
        elif kinds != {"int"} and kinds != {"float"}:
            return_dtype = pl.String()
        expr = (
            pl.col(source)
            .replace_strict(recode_map, default=default_expr, return_dtype=return_dtype)
            .alias(target)
        )
        return self._chain(expr, verb="recode")

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
        """Derive targets from one event per group, chosen across the events.

        Each event in the list defines a candidate source, a filter
        condition, and values to set when that event is selected.  Within
        each event's matching records, the event's *order* and *mode* (or
        the top-level ones) select one record.  Then one event wins:

        - with a top-level *order*, every event's record competes on that
          order and *mode*, as admiral ``derive_vars_extreme_event`` does:
          ``order=["LSTALVDT"], mode="last"`` gives the latest date over all
          sources.  A tie goes to the first listed event.
        - with no top-level *order*, the first listed event with a matching
          record wins (a priority cascade, as the admiral DTHCAUS template).

        This is Fleet's answer to multi-source derivations such as
        last-date-known-alive (LSTALVDT) or death cause (DTHCAUS).

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
            events: List of event dicts.  List position breaks ties and,
                with no top-level *order*, decides the winner.
            by: Grouping columns (default ``["USUBJID"]``).
            order: Sort column(s).  Within an event they select the record;
                at top level they also select the event (see above).  An
                event with more than one matching record in a group needs
                an order (its own or the top-level one).  A missing order
                value loses in both modes.  Records that tie on the order
                keep their input order, so ``"last"`` takes the last tied
                record, as SAS ``LAST.``; a warning names a tie whose
                records set different values.
            mode: ``"first"`` or ``"last"`` — which record to select
                after sorting by *order* (default ``"first"``).

        Returns:
            Self: A fresh namespace with *targets* added; call
                ``.to_frame()`` to materialise.

        Raises:
            DerivationError: If *events* is empty, a required key is
                missing, an event contains an unknown key (with a
                did-you-mean suggestion), or an event with no order has
                more than one matching record in a group.  Also catchable
                as ``ValueError``.

        References:
            admiral ``derive_vars_extreme_event`` (``order`` is required)
            and SAS ``FIRST.``/``LAST.`` after PROC SORT EQUALS; ADR-0024.

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
                             "source": ae, "order": ["AESTDTC", "AESEQ"]},
                            {"when": 'pl.col("DSDECOD") == "DEATH"',
                             "set": {"DTHCAUS": "DSTERM"},
                             "source": ds, "order": ["DSSTDTC", "DSSEQ"]},
                        ],
                        by=["USUBJID"],
                    )
                    .to_frame()
                )
        """
        from fleet.sdtm.utils import parse_expression

        if not events:
            raise DerivationError("pick() requires at least one event.")
        if mode not in ("first", "last"):
            raise DerivationError(
                f"pick() mode={mode!r} is not supported. Choose 'first' or 'last'."
            )

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
            if evt_mode not in ("first", "last"):
                raise DerivationError(
                    f"pick() event #{event_nr} mode={evt_mode!r} is not supported. "
                    "Choose 'first' or 'last'."
                )
            evt_order_raw = event.get("order", global_order)
            evt_order: list[str] | None = (
                [evt_order_raw] if isinstance(evt_order_raw, str) else evt_order_raw
            )

            # Within-event selection: pick one record per group
            if evt_order:
                # A missing order value loses in both modes; a tie keeps input order,
                # so "last" takes the last tied record (SAS LAST., admiral filter_extreme).
                candidates = candidates.sort(
                    evt_order, nulls_last=evt_mode == "first", maintain_order=True
                )
                self._warn_pick_ties(
                    candidates, event_nr, by_vars, evt_order, evt_mode, target_list
                )
                grouped = candidates.group_by(by_vars, maintain_order=True)
                candidates = grouped.first() if evt_mode == "first" else grouped.last()
            else:
                multi = (
                    candidates.group_by(by_vars, maintain_order=True)
                    .len()
                    .filter(pl.col("len") > 1)
                )
                if not multi.is_empty():
                    first = multi.row(0, named=True)
                    key = ", ".join(f"{c}={first[c]!r}" for c in by_vars)
                    raise DerivationError(
                        f"pick() event #{event_nr} has no order and {multi.height} group(s) "
                        f"with more than one matching record (first: {key}, "
                        f"{first['len']} records). Give 'order' in the event or at top "
                        "level, so the record does not depend on row order."
                    )
                candidates = candidates.group_by(by_vars, maintain_order=True).first()

            # Keep only by_vars + targets + the cross-event order + event_nr
            keep = by_vars + target_list + (global_order or []) + ["__pick_event_nr__"]
            available = [c for c in dict.fromkeys(keep) if c in candidates.columns]
            candidates = candidates.select(available)

            candidate_frames.append(candidates)

        # No events matched at all — set all targets to null
        if not candidate_frames:
            null_exprs = [pl.lit(None).alias(t) for t in target_list]
            return self._materialise_then(df.with_columns(null_exprs))

        # Each event gave at most one row per group.  A top-level order makes
        # them compete (admiral derive_vars_extreme_event); a tie goes to the
        # first listed event.  With no top-level order, list position decides.
        all_candidates = pl.concat(candidate_frames, how="diagonal_relaxed")
        if global_order:
            all_candidates = all_candidates.sort(
                [*global_order, "__pick_event_nr__"],
                descending=[mode == "last"] * len(global_order) + [False],
                nulls_last=True,
                maintain_order=True,
            )
        else:
            all_candidates = all_candidates.sort("__pick_event_nr__", maintain_order=True)
        winners = all_candidates.group_by(by_vars, maintain_order=True).first()
        winners = winners.select(by_vars + target_list)

        # Drop pre-existing target columns from base frame before join
        drop_existing = [t for t in target_list if t in df.columns]
        if drop_existing:
            df = df.drop(drop_existing)

        result = df.join(winners, on=by_vars, how="left", nulls_equal=True)
        return self._materialise_then(result)

    @staticmethod
    def _warn_pick_ties(
        candidates: pl.DataFrame,
        event_nr: int,
        by_vars: list[str],
        order: list[str],
        mode: str,
        targets: list[str],
    ) -> None:
        """Warn when records tie with the selected one on *order* but set other values."""
        pick_one = (lambda e: e.first()) if mode == "first" else (lambda e: e.last())
        tied = candidates.filter(
            pl.all_horizontal(
                pl.col(c).eq_missing(pick_one(pl.col(c)).over(by_vars)) for c in order
            )
        )
        differ = (
            tied.group_by(by_vars, maintain_order=True)
            .agg(pl.struct(targets).n_unique().alias("__n__"))
            .filter(pl.col("__n__") > 1)
        )
        if differ.is_empty():
            return
        first = differ.row(0, named=True)
        key = ", ".join(f"{c}={first[c]!r}" for c in by_vars)
        warnings.warn(
            f"pick() event #{event_nr}: {differ.height} group(s) have records that tie on "
            f"{order} and set different values (first: {key}). mode={mode!r} takes the "
            f"{mode} input record of the tie. Add a key to 'order' to break the tie.",
            stacklevel=3,
        )

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
        Each *by* key must name one ADSL row, and a non-key column may be
        on one side only: give *keep*, or add a shared column such as
        STUDYID to *by*, as admiral ``derive_vars_merged`` asks.

        Args:
            adsl: The ADSL ``pl.DataFrame`` to merge in.
            by: Key column(s) for the join (default ``["USUBJID"]``).
            keep: Subset of ADSL columns to bring in (excluding *by*
                keys, which are always included).  When ``None``, all ADSL
                columns are merged.

        Returns:
            Self: A fresh namespace wrapping the joined frame.

        Raises:
            DerivationError: When a *keep* column is not in *adsl*, a
                non-key column is on both sides, or *adsl* has two
                different rows for one key.

        References:
            ADR-0032 (docs/adr/0032-merge-reads-as-sas-merge-and-stops-on-a-clash.md).
            ADaMIG 1.3: ADSL holds one record per subject.

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
            require_columns("merge_adsl(keep=...)", keep, adsl.columns, where="ADSL")
            adsl = adsl.select(list(dict.fromkeys(keep + join_keys)))
        df = self.to_frame()
        refuse_shared_columns(
            "merge_adsl()",
            df.columns,
            adsl.columns,
            join_keys,
            hint="Pass keep= to choose the ADSL columns, or add the shared column to by=.",
        )
        adsl = refuse_repeated_keys("merge_adsl()", adsl, join_keys, source="ADSL")
        joined = df.join(adsl, on=join_keys, how="left", nulls_equal=True)
        return self._materialise_then(joined)

    # ------------------------------------------------------------------ #
    # Subject-level event aggregations (first_date / last_date / count)    #
    # ------------------------------------------------------------------ #

    def first_date(
        self,
        target: str,
        *,
        from_dataset: pl.DataFrame,
        date_col: str,
        where: str | pl.Expr | None = None,
        by: list[str] | None = None,
        impute: str | None = None,
    ) -> Self:
        """Derive *target* as the earliest date in *date_col* from *from_dataset*.

        Materialises the current pipeline, aggregates *from_dataset* to
        subject level, then left-joins.  Useful for ASTDTM, TRTSDT, etc.
        ``--DTC`` text is compared as dates: ``*DT`` gives a date, ``*DTM``
        a date-time, ``*DTC`` the text of the earliest record.  A partial
        or unreadable value is left out with a warning, unless *impute*
        states the SAP rule (admiral ``derive_vars_dt``).

        Args:
            target: Name of the output date column.
            from_dataset: Source ``pl.DataFrame`` to aggregate.
            date_col: Date column to take the minimum of.
            where: Optional filter applied to *from_dataset* before aggregation.
            by: Join key columns (default ``["USUBJID"]``).
            impute: Impute a partial ``--DTC`` value (``"first"``, ``"mid"``,
                ``"last"``) for a ``*DT`` target, write the ``*DTF`` flag of the
                earliest record, and warn with the count.

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
            impute=impute,
        )

    def last_date(
        self,
        target: str,
        *,
        from_dataset: pl.DataFrame,
        date_col: str,
        where: str | pl.Expr | None = None,
        by: list[str] | None = None,
        impute: str | None = None,
    ) -> Self:
        """Derive *target* as the latest date in *date_col* from *from_dataset*.

        Useful for AENDTM, TRTEDT, DTHDT, etc.  Reads ``--DTC`` text as
        :meth:`first_date` does.

        Args:
            target: Name of the output date column.
            from_dataset: Source ``pl.DataFrame`` to aggregate.
            date_col: Date column to take the maximum of.
            where: Optional filter applied to *from_dataset* before aggregation.
            by: Join key columns (default ``["USUBJID"]``).
            impute: Impute a partial ``--DTC`` value for a ``*DT`` target,
                write the ``*DTF`` flag of the latest record, and warn.

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
            impute=impute,
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
        impute: str | None = None,
    ) -> Self:
        """Shared implementation for first_date/last_date.

        ``--DTC`` text is read by the shared reader and compared as dates, so
        the extreme is a date, never a text minimum.  The output type
        follows the target: ``*DT`` a date, ``*DTM`` a date-time (values with
        hours and minutes), ``*DTC`` the text of the winning record.  With no
        *impute*, a partial value is left out with a warning; with one, a
        partial value is imputed and the ``*DTF`` flag comes from the
        winning record.
        """
        from fleet.adam.utils import (
            _extract_prefix,
            _infer_output_type,
            dtf_expr,
            impute_dtc_to_date,
        )
        from fleet.core.dtc import date_part, datetime_part
        from fleet.sdtm.utils import parse_expression

        verb = "first_date" if agg_fn == "min" else "last_date"
        grps = by or ["USUBJID"]
        src = from_dataset
        if where is not None:
            where_expr = where if isinstance(where, pl.Expr) else parse_expression(str(where))
            src = src.filter(where_expr)
        output = _infer_output_type(target) or "dt"
        if src.schema[date_col] != pl.String:
            if impute is not None:
                raise DerivationError(f"{verb}('{target}'): impute= reads --DTC text only.")
            col = pl.col(date_col)
            if output == "dt" and isinstance(src.schema[date_col], pl.Datetime):
                col = col.cast(pl.Date)
            agg_df = src.group_by(grps).agg(
                (col.min() if agg_fn == "min" else col.max()).alias(target)
            )
            df = self.to_frame()
            refuse_shared_columns(f"{verb}()", df.columns, agg_df.columns, grps, hint=_CLASH_HINT)
            df = df.join(agg_df, on=grps, how="left", nulls_equal=True)
            return self._materialise_then(df)

        raw = pl.col(date_col)
        flag = None
        if impute is not None:
            if output != "dt":
                raise DerivationError(
                    f"{verb}('{target}', impute=): imputation writes a *DT target and its *DTF "
                    "flag. Impute the source with .adam.date() first for other targets."
                )
            key = impute_dtc_to_date(
                date_col, "__key__", day_imputation=impute, month_imputation=impute
            )
            flag = f"{_extract_prefix(target)}DTF"
        elif output == "dtm":
            key = datetime_part(raw)
        else:
            key = date_part(raw)

        given = raw.str.strip_chars().fill_null("") != ""
        rows = src.with_columns(key.alias("__key__"))
        left_out = rows.filter(given & pl.col("__key__").is_null())
        if left_out.height:
            values = left_out[date_col].unique(maintain_order=True).head(5).to_list()
            warnings.warn(
                f"{verb}('{target}'): {date_col} has {left_out.height} partial or unreadable "
                f"value(s), left out of the {verb}. Pass impute= to impute partial dates. "
                f"Values: {values}",
                stacklevel=3,
            )

        picks = [pl.col("__key__").alias(target) if output != "dtc" else raw.alias(target)]
        if flag is not None:
            rows = rows.with_columns(dtf_expr(date_col, "__flag__"))
            picks.append(pl.col("__flag__").alias(flag))
        winners = (
            rows.filter(pl.col("__key__").is_not_null())
            .sort(
                [*grps, "__key__", *(["__flag__"] if flag else [])],
                descending=[False] * len(grps) + [agg_fn == "max"] + ([False] if flag else []),
                nulls_last=False,
            )
            .group_by(grps, maintain_order=True)
            .first()
            .select(*grps, *picks)
        )
        if flag is not None:
            imputed = winners.filter(pl.col(flag).is_not_null()).height
            if imputed:
                warnings.warn(
                    f"{verb}('{target}'): imputed {imputed} date(s) from partial {date_col} "
                    f"values (impute='{impute}'); {flag} records it.",
                    stacklevel=3,
                )
        df = self.to_frame()
        refuse_shared_columns(f"{verb}()", df.columns, winners.columns, grps, hint=_CLASH_HINT)
        df = df.join(winners, on=grps, how="left", nulls_equal=True)
        return self._materialise_then(df)

    def count_events(
        self,
        target: str,
        *,
        from_dataset: pl.DataFrame,
        where: str | pl.Expr | None = None,
        by: list[str] | None = None,
    ) -> Self:
        """Derive *target* as the count of matching records in *from_dataset*.

        Returns 0 for subjects with no matching records (never null).  The
        count is Int64, so a later subtraction can go below zero.

        Args:
            target: Name of the output count column.
            from_dataset: Source ``pl.DataFrame`` to count.
            where: Optional filter applied before counting.
            by: Join key columns (default ``["USUBJID"]``).

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
        agg_df = src.group_by(grps).agg(pl.len().cast(pl.Int64).alias(target))
        df = self.to_frame()
        refuse_shared_columns("count_events()", df.columns, agg_df.columns, grps, hint=_CLASH_HINT)
        df = df.join(agg_df, on=grps, how="left", nulls_equal=True)
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
            min_date: Lower bound for an imputed date (column name or date
                literal).  Applies only when the bound is inside the possible
                range of the partial value; a complete date never changes.
                Date (*DT) targets only.
            max_date: Upper bound for an imputed date, with the same rule.

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
        from fleet.adam.utils import (
            _resolve_flag_names,
            _resolve_time,
            dtf_expr,
            dtm_with_time,
            impute_dtc_to_date,
            impute_dtc_to_datetime,
            refuse_dtm_bounds,
            source_text,
            tmf_expr,
            warn_unread,
        )
        from fleet.core.dtc import date_part

        if output_type == "dtm":
            refuse_dtm_bounds(target, min_date, max_date, highest=highest)
            if time is not None:
                return self._materialise_then(
                    dtm_with_time(
                        self._lazy,
                        source=source,
                        target=target,
                        time=time,
                        impute_time=impute_time,
                        flag=flag,
                    )
                )
        src = source_text(source, self._lazy.collect_schema().get(source), verb=f"date('{target}')")

        if output_type == "dt":
            exprs = impute_and_flag(
                src,
                target,
                output_type="dt",
                impute=impute,
                highest=highest,
                min_date=min_date,
                max_date=max_date,
                flag=flag,
            )
            return self._chain(*exprs, verb="date")

        # output_type == "dtm": a partial date takes the imputed date and the imputed time
        dtf_name, tmf_name = _resolve_flag_names(target, flag, output_type)
        effective_time_impute = impute_time or impute

        date_expr = impute_dtc_to_date(
            src,
            "__dtm_date_tmp__",
            day_imputation=impute,
            month_imputation=impute,
        )
        df = self._lazy.with_columns(date_expr).collect()

        dtm_expr = impute_dtc_to_datetime(
            src,
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
            pl.when(src.is_null() | (src.str.strip_chars() == ""))
            .then(pl.lit(None, dtype=pl.Datetime("us")))
            .when(date_part(src).is_not_null())
            .then(dtm_expr)
            .otherwise(partial_dtm)
        )

        exprs_list: list[pl.Expr] = [
            warn_unread(src, target, dtm_full, pl.Datetime("us")).alias(target)
        ]
        if dtf_name is not None:
            exprs_list.append(pl.when(dtm_full.is_not_null()).then(dtf_expr(src)).alias(dtf_name))
        if tmf_name is not None:
            exprs_list.append(pl.when(dtm_full.is_not_null()).then(tmf_expr(src)).alias(tmf_name))

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
