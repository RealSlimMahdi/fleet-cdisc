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
``FlagCriterionMixin`` provides ``flag()`` and ``criterion()`` to both
ADaM namespaces (via ``SharedADaMVerbsMixin`` inheritance) **and** the
SDTM namespace (which inherits from this mixin directly).  Any namespace
that exposes ``_chain()`` and ``_materialise_then()`` can inherit it.

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
from pathlib import Path
from typing import Any, Self

import polars as pl

from fleet.core._pin_mixin import PinMixin


class FlagCriterionMixin:
    """Mixin providing ``flag()`` and ``criterion()`` to any namespace.

    Both SDTM (``df.sdtm``) and all ADaM namespaces inherit from this
    mixin.  The methods rely on ``_chain()`` and ``_materialise_then()``
    which every concrete namespace class must provide.
    """

    _lazy: pl.LazyFrame

    # Subclasses must provide these — declared here for type-checker only.
    def _chain(self, *exprs: pl.Expr) -> Self: ...  # noqa: E704
    def _materialise_then(self, df: pl.DataFrame) -> Self: ...  # noqa: E704

    # ------------------------------------------------------------------ #
    # Flag — generalised "Y" / null flagging                               #
    # ------------------------------------------------------------------ #

    def flag(
        self,
        target: str,
        *,
        criteria: str | pl.Expr,
        groups: list[str] | None = None,
        order_by: str | list[str] | None = None,
        value_col: str | None = None,
        where: str | pl.Expr | None = None,
        from_dataset: pl.DataFrame | list[pl.DataFrame] | None = None,
        on: list[str] | None = None,
        source_filter: pl.Expr | None = None,
        condition: pl.Expr | None = None,
        inclusive: bool = True,
        flag_no_ref_groups: bool = True,
        flag_all: bool = False,
        flag_value: str = "Y",
        false_value: str | None = None,
    ) -> Self:
        """Set *target* to *flag_value* for records matching *criteria*.

        Supports row-level boolean expressions and built-in shortcuts:

        - ``"first"`` / ``"last"`` — rank-based edge detection within groups.
        - ``"max"`` / ``"min"`` — value-based extreme within groups.
        - ``"exists"`` — set-membership from external dataset(s).
        - ``"before"`` / ``"after"`` — relative to a landmark condition.
        - ``"exists_after"`` / ``"exists_before"`` — temporal/self-join flag.

        Args:
            target: Name of the output flag column.
            criteria: A Polars expression, or one of ``"first"``,
                ``"last"``, ``"max"``, ``"min"``, ``"exists"``,
                ``"before"``, ``"after"``, ``"exists_after"``,
                ``"exists_before"``.
            groups: Partition columns (default ``["USUBJID"]``).
            order_by: Sort column(s) required for ``"first"``/``"last"``
                and ``"before"``/``"after"``.
            value_col: Value column required for ``"max"``/``"min"``.
            where: Optional pre-filter — only matching rows are candidates.
            from_dataset: External dataset(s) for ``"exists"`` and
                ``"exists_after"``/``"exists_before"`` criteria.
            on: Join key columns for ``"exists"`` criteria.
            source_filter: Filter applied to *from_dataset* before key
                extraction or join.
            condition: Boolean expression identifying landmark rows for
                ``"before"``/``"after"`` or the current-row condition for
                ``"exists_after"``/``"exists_before"``.
            inclusive: Whether the landmark row itself is included in the
                flag (for ``"before"``/``"after"``). Default ``True``.
            flag_no_ref_groups: If ``False``, groups without a landmark
                condition match get ``None`` instead of being flagged
                (for ``"before"``/``"after"``). Default ``True``.
            flag_all: If ``True``, all tied extreme values receive the
                flag (for ``"first"``/``"last"``). Default ``False``.
            flag_value: Value to assign when condition is met (default
                ``"Y"``).
            false_value: Value to assign when condition is not met.
                Default ``None`` (null).

        Returns:
            Self: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            First observation per group::

                advs = (
                    vs_raw.adam
                    .flag("ABLFL", criteria="first", order_by="AVISITN",
                          groups=["USUBJID", "PARAMCD"])
                    .to_frame()
                )

            Existence flag from external dataset::

                adsl = (
                    dm.adam.adsl
                    .flag("VSEVALFL", criteria="exists",
                          from_dataset=advs, on=["USUBJID"],
                          source_filter=pl.col("AVISIT") == "BASELINE")
                    .to_frame()
                )

            Relative flag — before first PD::

                result = (
                    response.adam
                    .flag("ANL02FL", criteria="before",
                          condition=pl.col("AVALC") == "PD",
                          order_by="AVISITN", groups=["USUBJID"],
                          inclusive=True)
                    .to_frame()
                )

            Population flag on SDTM::

                dm = (
                    raw_df.sdtm
                    .flag("SAFFL", criteria=pl.col("EXDOSE") > 0,
                          groups=["USUBJID"])
                    .to_frame()
                )
        """
        from fleet.sdtm.utils import parse_expression

        grps = groups or ["USUBJID"]

        # Normalise order_by to list
        order_cols: list[str] | None = None
        if order_by is not None:
            order_cols = [order_by] if isinstance(order_by, str) else list(order_by)

        # Parse where clause
        where_expr: pl.Expr | None = None
        if where is not None:
            where_expr = where if isinstance(where, pl.Expr) else parse_expression(str(where))

        # Determine false literal
        false_lit = pl.lit(false_value) if false_value is not None else pl.lit(None)

        # ── Criteria dispatch ──
        if isinstance(criteria, str):
            criteria_lower = criteria.lower()
        else:
            criteria_lower = None

        # ── first / last ──
        if criteria_lower in ("first", "last"):
            if not order_cols:
                raise ValueError(f"flag criteria='{criteria}' requires order_by.")
            descending = criteria_lower == "last"

            # Materialise to sort properly — handles nulls and multi-column
            df = self._lazy.collect()
            df = df.with_row_index("__flag_orig_idx__")

            # Null check: rows with null in any order col are never flagged
            null_mask = pl.all_horizontal([pl.col(c).is_not_null() for c in order_cols])

            if flag_all:
                # flag_all: all rows sharing the extreme value get flagged
                # Build struct for comparison
                if len(order_cols) == 1:
                    val_expr = pl.col(order_cols[0])
                else:
                    val_expr = pl.struct(order_cols)
                if descending:
                    extreme = val_expr.max().over(grps)
                else:
                    extreme = val_expr.min().over(grps)
                row_cond = null_mask & (val_expr == extreme)
                if where_expr is not None:
                    row_cond = where_expr & row_cond
                expr = pl.when(row_cond).then(pl.lit(flag_value)).otherwise(false_lit).alias(target)
                result_df = (
                    df.with_columns(expr).sort("__flag_orig_idx__").drop("__flag_orig_idx__")
                )
                return self._materialise_then(result_df)

            # Standard: ordinal rank within each group
            # Sort and pick first per group
            sort_descending = [descending] * len(order_cols)
            null_last = [True] * len(order_cols)

            eligible = df.filter(null_mask)
            if where_expr is not None:
                eligible = eligible.filter(where_expr)

            # Sort eligible rows by order_cols, then take first per group
            eligible_sorted = eligible.sort(
                order_cols, descending=sort_descending, nulls_last=null_last
            )
            first_per_group = eligible_sorted.group_by(grps, maintain_order=True).first()
            flagged_indices = set(first_per_group["__flag_orig_idx__"].to_list())

            # Build result
            flags = [
                flag_value if idx in flagged_indices else (false_value if false_value else None)
                for idx in df["__flag_orig_idx__"].to_list()
            ]
            result_df = (
                df.with_columns(pl.Series(target, flags))
                .sort("__flag_orig_idx__")
                .drop("__flag_orig_idx__")
            )
            return self._materialise_then(result_df)

        # ── max / min ──
        elif criteria_lower in ("max", "min"):
            if not value_col:
                raise ValueError(f"flag criteria='{criteria}' requires value_col.")
            if where_expr is not None:
                masked_val = pl.when(where_expr).then(pl.col(value_col)).otherwise(pl.lit(None))
                agg_val = (
                    masked_val.max().over(grps)
                    if criteria_lower == "max"
                    else masked_val.min().over(grps)
                )
                row_cond = where_expr & (pl.col(value_col) == agg_val)
            else:
                agg_val = (
                    pl.col(value_col).max().over(grps)
                    if criteria_lower == "max"
                    else pl.col(value_col).min().over(grps)
                )
                row_cond = pl.col(value_col) == agg_val
            final_cond = row_cond

        # ── exists ──
        elif criteria_lower == "exists":
            if from_dataset is None or on is None:
                raise ValueError("flag criteria='exists' requires from_dataset and on.")
            # Collect unique keys from source dataset(s)
            datasets = from_dataset if isinstance(from_dataset, list) else [from_dataset]
            key_frames: list[pl.DataFrame] = []
            for ds in datasets:
                filtered = ds
                if source_filter is not None:
                    filtered = ds.filter(source_filter)
                key_frames.append(filtered.select(on).unique())
            all_keys = pl.concat(key_frames).unique()

            # Materialise current frame to perform semi-join logic
            df = self._lazy.collect()

            # Build struct key for multi-column join
            if len(on) == 1:
                is_member = pl.col(on[0]).is_in(all_keys[on[0]].to_list())
            else:
                # For multi-column: join approach
                df = df.with_columns(pl.lit(None).cast(pl.String).alias(target))
                member_df = df.join(all_keys, on=on, how="semi").with_columns(
                    pl.lit(flag_value).alias(target)
                )
                non_member_df = df.join(all_keys, on=on, how="anti").with_columns(
                    false_lit.cast(pl.String).alias(target)
                )
                result = pl.concat([member_df, non_member_df], how="diagonal").sort(df.columns[0])

                # Preserve original row order
                df_with_idx = df.with_row_index("__flag_idx__")
                result = (
                    df_with_idx.drop(target)
                    .join(
                        df_with_idx.select(on + ["__flag_idx__"])
                        .unique()
                        .join(all_keys, on=on, how="semi")
                        .with_columns(pl.lit(flag_value).alias(target)),
                        on="__flag_idx__",
                        how="left",
                    )
                    .with_columns(
                        pl.col(target).fill_null(
                            pl.lit(false_value) if false_value else pl.lit(None)
                        )
                    )
                    .drop("__flag_idx__")
                )
                return self._materialise_then(result)

            # Single-key path
            final_cond = is_member
            expr = pl.when(final_cond).then(pl.lit(flag_value)).otherwise(false_lit).alias(target)
            return self._chain(expr)

        # ── before / after ──
        elif criteria_lower in ("before", "after"):
            if condition is None:
                raise ValueError(f"flag criteria='{criteria}' requires condition.")
            if not order_cols:
                raise ValueError(f"flag criteria='{criteria}' requires order_by.")
            # Materialise for ordered window operations
            df = self._lazy.collect()

            # Sort within groups
            df = df.with_row_index("__orig_idx__")
            df_sorted = df.sort(order_cols)

            # Evaluate condition to boolean
            cond_col = "__flag_cond__"
            df_sorted = df_sorted.with_columns(condition.cast(pl.Boolean).alias(cond_col))

            # For each group, find the position of the first condition match
            # "before" = flag rows up to (and optionally including) landmark
            # "after" = flag rows after (and optionally including) landmark
            result_parts: list[pl.DataFrame] = []
            for _, grp_df in df_sorted.group_by(grps, maintain_order=True):
                cond_mask = grp_df[cond_col].to_list()

                # Find first True in condition
                first_cond_idx: int | None = None
                for i, v in enumerate(cond_mask):
                    if v is True:
                        first_cond_idx = i
                        break

                n = len(grp_df)
                if first_cond_idx is None:
                    # No landmark found
                    if flag_no_ref_groups:
                        if criteria_lower == "before":
                            # All rows flagged (nothing to be "after")
                            flags = [flag_value] * n
                        else:
                            # "after" with no ref → nothing flagged
                            flags = [false_value] * n
                    else:
                        flags = [false_value if false_value else None] * n
                else:
                    flags = []
                    for i in range(n):
                        if criteria_lower == "before":
                            if inclusive:
                                flagged = i <= first_cond_idx
                            else:
                                flagged = i < first_cond_idx
                        else:  # "after"
                            if inclusive:
                                flagged = i >= first_cond_idx
                            else:
                                flagged = i > first_cond_idx
                        flags.append(
                            flag_value if flagged else (false_value if false_value else None)
                        )

                result_parts.append(grp_df.with_columns(pl.Series(target, flags)))

            result_df = pl.concat(result_parts)
            result_df = result_df.sort("__orig_idx__").drop(["__orig_idx__", cond_col])
            return self._materialise_then(result_df)

        # ── exists_after / exists_before ──
        elif criteria_lower in ("exists_after", "exists_before"):
            if from_dataset is None or condition is None:
                raise ValueError(f"flag criteria='{criteria}' requires from_dataset and condition.")
            if on is None:
                raise ValueError(f"flag criteria='{criteria}' requires on.")
            # Materialise
            df = self._lazy.collect()

            # Filter source dataset
            src = (
                from_dataset if isinstance(from_dataset, pl.DataFrame) else pl.concat(from_dataset)
            )
            if source_filter is not None:
                src = src.filter(source_filter)

            # Determine order column for temporal comparison
            # Use the first order_by column or infer from frame
            if order_cols:
                time_col = order_cols[0]
            else:
                # Try to find a common time-like column
                common_time = [
                    c
                    for c in ["AVISITN", "ADY", "ADT", "ADTM"]
                    if c in df.columns and c in src.columns
                ]
                if not common_time:
                    raise ValueError(
                        f"flag criteria='{criteria}' requires order_by or a "
                        "common temporal column (AVISITN, ADY, ADT, ADTM)."
                    )
                time_col = common_time[0]

            # For each row meeting `condition` in df, check if there exists
            # a row in src (joined on `on`) that comes after/before it
            df = df.with_row_index("__flag_idx__")

            # Get candidate rows from current df that satisfy condition
            cond_df = df.filter(condition)

            flags = [None] * len(df)

            for row in cond_df.iter_rows(named=True):
                # Find matching source rows
                src_filtered = src
                for key in on:
                    src_filtered = src_filtered.filter(pl.col(key) == row[key])

                if len(src_filtered) == 0:
                    continue

                # Check temporal condition
                row_time = row[time_col]
                if criteria_lower == "exists_after":
                    matches = src_filtered.filter(pl.col(time_col) > row_time)
                else:
                    matches = src_filtered.filter(pl.col(time_col) < row_time)

                if len(matches) > 0:
                    idx = row["__flag_idx__"]
                    flags[idx] = flag_value

            result_df = df.drop("__flag_idx__").with_columns(pl.Series(target, flags))
            return self._materialise_then(result_df)

        # ── Direct expression criteria ──
        else:
            _known = {
                "first",
                "last",
                "max",
                "min",
                "exists",
                "before",
                "after",
                "exists_after",
                "exists_before",
            }
            if criteria_lower is not None and criteria_lower in _known:
                # Should not reach here — handled above
                raise ValueError(
                    f"Unknown flag criteria: '{criteria}'. Supported: "
                    "'first', 'last', 'max', 'min', 'exists', 'before', "
                    "'after', 'exists_after', 'exists_before'."
                )
            # criteria is a pl.Expr or a parseable string expression
            if isinstance(criteria, pl.Expr):
                row_cond = criteria
            else:
                row_cond = parse_expression(str(criteria))
            final_cond = (where_expr & row_cond) if where_expr is not None else row_cond

        # Standard expression-based path
        expr = pl.when(final_cond).then(pl.lit(flag_value)).otherwise(false_lit).alias(target)
        return self._chain(expr)

    # ------------------------------------------------------------------ #
    # Criterion — CRITy / CRITyFL / CRITyFN triple-output                 #
    # ------------------------------------------------------------------ #

    def criterion(
        self,
        number: int,
        *,
        condition: pl.Expr,
        description: str | None = None,
        prefix: str = "CRIT",
    ) -> Self:
        """Derive criterion flag triple: CRITy, CRITyFL, CRITyFN.

        Produces three columns following CDISC ADaM conventions:

        - ``{prefix}{number}`` — the criterion description (constant string).
        - ``{prefix}{number}FL`` — ``"Y"`` if condition is met, ``"N"`` otherwise.
        - ``{prefix}{number}FN`` — ``1`` if met, ``0`` otherwise.

        Args:
            number: Criterion number (e.g. 1 → CRIT1, CRIT1FL, CRIT1FN).
            condition: Boolean Polars expression defining the criterion.
            description: Human-readable description stored in CRITy column.
                If ``None``, the column is still created with null values.
            prefix: Column name prefix (default ``"CRIT"``).

        Returns:
            Self: The namespace with three new columns appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Flag records where AVAL >= 10::

                adlb = (
                    lb_df.adam
                    .criterion(1, condition=pl.col("AVAL") >= 10,
                               description="AVAL >= 10")
                    .to_frame()
                )
        """
        col_crit = f"{prefix}{number}"
        col_fl = f"{prefix}{number}FL"
        col_fn = f"{prefix}{number}FN"

        desc_expr = (
            pl.lit(description).alias(col_crit)
            if description is not None
            else pl.lit(None).cast(pl.String).alias(col_crit)
        )
        fl_expr = pl.when(condition).then(pl.lit("Y")).otherwise(pl.lit("N")).alias(col_fl)
        fn_expr = pl.when(condition).then(pl.lit(1)).otherwise(pl.lit(0)).alias(col_fn)

        return self._chain(desc_expr, fl_expr, fn_expr)


class SharedADaMVerbsMixin(PinMixin, FlagCriterionMixin):
    """Base mixin providing the shared verbs and chaining infrastructure.

    Concrete namespace classes inherit from this mixin.  The ``_chain``
    and ``_materialise_then`` helpers use ``self.__class__`` so the returned
    instance stays the correct sub-type for continued method chaining.

    Required instance attribute
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~
    ``_lazy: pl.LazyFrame``  — set by ``__init__``.
    """

    _lazy: pl.LazyFrame

    _FK_RULES: dict[str, dict[str, str]] = {
        "USUBJID": {"pin": "ADSL", "ref_col": "USUBJID"},
    }

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def __init__(self, df: pl.DataFrame) -> None:
        self._lazy = df.lazy()
        self._domain: str | None = None
        self._pinned: dict[str, tuple[pl.DataFrame, list[str]]] = {}
        self._pin_lineage: list = []

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
    # Chaining infrastructure                                              #
    # ------------------------------------------------------------------ #

    def _chain(self, *exprs: pl.Expr) -> Self:
        """Append expressions to the lazy plan; return a *new* namespace."""
        from fleet.core.lineage import record_lineage

        new = copy.copy(self)
        new._lazy = self._lazy.with_columns(list(exprs))
        record_lineage(new, exprs)
        return new

    def _materialise_then(self, df: pl.DataFrame) -> Self:
        """Return a fresh namespace wrapping *df* as a new lazy plan."""
        new = copy.copy(self)
        new._lazy = df.lazy()
        return new

    def to_frame(self) -> pl.DataFrame:
        """Materialise the accumulated pipeline into a Polars DataFrame.

        Returns:
            pl.DataFrame: The fully materialised result of all chained
                ADaM verbs.

        Examples:
            Collect the pipeline result::

                advs = (
                    vs_df.adam
                    .source("USUBJID")
                    .derivation("AVAL", expression="VSSTRESN")
                    .to_frame()
                )
        """
        return self._lazy.collect()

    def to_dataset_json(
        self,
        path: str | Path,
        *,
        domain: str,
        label: str | None = None,
    ) -> Path:
        """Materialise the pipeline and write a CDISC Dataset-JSON v1.1 file.

        This is a terminal verb — it collects the lazy plan and writes the
        result.  No further chaining is possible after this call.

        Args:
            path: Destination file path (should end in ``.json``).
            domain: Dataset / domain name (e.g. ``"ADSL"``, ``"ADAE"``).
            label: Optional human-readable dataset label.

        Returns:
            Path: Path to the written file.

        Examples:
            Export an ADaM ADSL dataset to Dataset-JSON::

                path = (
                    dm.adam.adsl
                    .source("USUBJID")
                    .first_date("TRTSDT", from_dataset=ex, date_col="EXSTDTC")
                    .to_dataset_json("outputs/adsl.json", domain="ADSL")
                )
        """
        from fleet.io.dataset_json import save_dataset_json

        return save_dataset_json(self._lazy.collect(), path, domain=domain, label=label)

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

    def study_day(
        self,
        target: str,
        *,
        date_col: str,
        ref_col: str = "TRTSDT",
        ref_pin: str = "ADSL",
        adsl: pl.DataFrame | None = None,
    ) -> Self:
        """Derive a CDISC study day variable for ADaM datasets.

        Uses the CDISC algorithm: ``date - ref_date + 1`` when
        ``date >= ref_date``, else ``date - ref_date`` (no day 0).

        The reference date is resolved in this order:

        1. Explicit ``adsl=`` parameter (highest priority).
        2. Pinned domain (via ``.pin("ADSL", adsl_df)``).
        3. ``ref_col`` already present in the current frame.
        4. Actionable ``LookupError``.

        Args:
            target: Name of the output study day variable
                (e.g. ``"ASTDY"``).
            date_col: Column containing the analysis date
                (e.g. ``"ASTDT"``).
            ref_col: Reference date column in the pinned domain
                (default ``"TRTSDT"``).
            ref_pin: Pinned domain name (default ``"ADSL"``).
            adsl: Optional explicit DataFrame override.

        Returns:
            Self: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Derive AE analysis study day from pinned ADSL::

                adae = (
                    ae_df.adam.occds("ADAE")
                    .pin("ADSL", adsl_df)
                    .source("USUBJID")
                    .join_adsl("TRTSDT")
                    .derivation("ASTDT", expression="pl.col('AESTDTC').str.to_date(format='%Y-%m-%d', strict=False)")
                    .study_day("ASTDY", date_col="ASTDT")
                    .to_frame()
                )
        """
        from fleet.core.lineage import record_pin_lineage

        df = self._lazy.collect()

        # Resolve reference date
        if adsl is not None:
            ref_df = adsl
            join_key = ["USUBJID"]
        elif ref_col in df.columns:
            # Already in frame — compute directly
            date_expr = pl.col(date_col)
            ref_expr = pl.col(ref_col)
            # Handle both Date and String types
            if df.schema.get(date_col) == pl.String:
                date_expr = date_expr.str.to_date(format="%Y-%m-%d", strict=False)
            if df.schema.get(ref_col) == pl.String:
                ref_expr = ref_expr.str.to_date(format="%Y-%m-%d", strict=False)
            diff = (date_expr - ref_expr).dt.total_days()
            study_day_expr = pl.when(diff >= 0).then(diff + 1).otherwise(diff).alias(target)
            return self._materialise_then(df.with_columns(study_day_expr))
        else:
            ref_df = self._require_pin(ref_pin.upper(), "study_day", columns=[ref_col])
            join_key = self._pin_join_key(ref_pin.upper())

        # Join, compute, drop temp
        ref_slim = ref_df.select(
            [c for c in dict.fromkeys(join_key + [ref_col]) if c in ref_df.columns]
        ).unique(subset=join_key)

        _ref_tmp = f"__pin_{ref_col}__"
        ref_slim = ref_slim.rename({ref_col: _ref_tmp})
        df = df.join(ref_slim, on=join_key, how="left")

        date_expr = pl.col(date_col)
        ref_expr = pl.col(_ref_tmp)
        if df.schema.get(date_col) == pl.String:
            date_expr = date_expr.str.to_date(format="%Y-%m-%d", strict=False)
        if df.schema.get(_ref_tmp) == pl.String:
            ref_expr = ref_expr.str.to_date(format="%Y-%m-%d", strict=False)

        diff = (date_expr - ref_expr).dt.total_days()
        study_day_expr = pl.when(diff >= 0).then(diff + 1).otherwise(diff).alias(target)
        df = df.with_columns(study_day_expr).drop(_ref_tmp)

        new = self._materialise_then(df)

        # Record variable lineage (since _materialise_then bypasses _chain)
        from fleet.core.dag import VariableNode as _VN

        var_lineage: list = list(getattr(new, "_lineage", []))
        var_lineage.append(
            _VN(
                name=target,
                verb="study_day",
                sources=[date_col, ref_col],
                method=f"{self.__class__.__module__}.{self.__class__.__qualname__}.study_day",
                domain=getattr(new, "_domain", None),
            )
        )
        new._lineage = var_lineage

        record_pin_lineage(
            new,
            target_col=target,
            verb="study_day",
            source_domain=ref_pin.upper(),
            source_cols=[ref_col],
            join_key=join_key,
            relationship="derivation",
        )
        return new

    # ------------------------------------------------------------------ #
    # Debugging & observability                                            #
    # ------------------------------------------------------------------ #

    def inspect(self, prefix: str = "DEBUG") -> Self:
        """Materialise the pipeline at this point and log its state.

        Creates a hard checkpoint: the pipeline resumes from the
        materialised frame, making it easy to isolate exactly where a
        derivation goes wrong.

        Args:
            prefix: Label printed alongside the diagnostic output.

        Returns:
            Self: A fresh namespace wrapping the materialised frame; call
                further verbs or ``.to_frame()`` to continue.

        Examples:
            Inspect the pipeline after baseline derivation::

                advs = (
                    vs_df.adam
                    .source("USUBJID")
                    .baseline("BASE", aval="AVAL", baseline_flag="ABLFL")
                    .inspect(prefix="After BASE")
                    .chg("CHG", aval="AVAL", base="BASE")
                    .to_frame()
                )
        """
        df = self._lazy.collect()
        print(f"[{prefix}] Schema: {df.schema}")
        print(f"[{prefix}] Shape:  {df.shape}")
        print(df.head(5))
        return self._materialise_then(df)

    def explain(self) -> Self:
        """Print the current Polars query plan without materialising.

        Useful for understanding how Polars will optimise the accumulated
        derivation pipeline.

        Returns:
            Self: The same namespace instance (unchanged); call further
                verbs or ``.to_frame()`` to continue.

        Examples:
            Print the query plan before collecting::

                advs = (
                    vs_df.adam
                    .source("USUBJID")
                    .derivation("AVAL", expression="VSSTRESN")
                    .explain()
                    .to_frame()
                )
        """
        print(self._lazy.explain())
        return self

    # ------------------------------------------------------------------ #
    # Shared verbs                                                         #
    # ------------------------------------------------------------------ #

    def source(self, target: str, *, from_col: str | None = None) -> Self:
        """Copy a source column into the ADaM dataset.

        When *from_col* is ``None``, the column named *target* is carried
        through as-is (identity copy).

        Args:
            target: Name of the output ADaM variable.
            from_col: Name of the input column to copy from.  Defaults to
                *target* when omitted.

        Returns:
            Self: The namespace with *target* appended; call ``.to_frame()``
                to materialise.

        Examples:
            Copy ``AEDECOD`` from the source data::

                adae = (
                    ae_df.adam
                    .source("AEDECOD", from_col="AEDECOD")
                    .to_frame()
                )
        """
        src = from_col if from_col is not None else target
        return self._chain(pl.col(src).alias(target))

    def derivation(self, target: str, *, expression: str | pl.Expr) -> Self:
        """Derive *target* using an arbitrary Polars expression.

        Args:
            target: Name of the output ADaM variable.
            expression: A Polars expression object or a string that evaluates
                to one.

        Returns:
            Self: The namespace with *target* appended; call ``.to_frame()``
                to materialise.

        Examples:
            Compute ``AVAL`` from a raw numeric column::

                advs = (
                    vs_df.adam
                    .derivation("AVAL", expression="pl.col('VSSTRESN').cast(pl.Float64)")
                    .to_frame()
                )
        """
        from fleet.sdtm.utils import parse_expression

        expr = expression if isinstance(expression, pl.Expr) else parse_expression(str(expression))
        return self._chain(expr.alias(target))

    def assigned(self, target: str, *, value: Any) -> Self:
        """Set *target* to a constant *value* for every record.

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
                    .assigned("PARAMCD", value="SYSBP")
                    .to_frame()
                )
        """
        return self._chain(pl.lit(value).alias(target))

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
        return self._chain(expr)

    def rename(self, target: str, *, source: str) -> Self:
        """Create *target* as a copy of *source* (variable renaming).

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
                    .rename("PARAM", source="VSTEST")
                    .to_frame()
                )
        """
        return self._chain(pl.col(source).alias(target))

    def condderivation(
        self,
        target: str,
        *,
        conditions: list[dict[str, Any]],
        else_value: Any = None,
    ) -> Self:
        """Multi-branch conditional derivation (when/then/otherwise chain).

        Branches are evaluated in order; the first matching condition wins.

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
                    .condderivation("DTYPE", conditions=[
                        {"condition": 'pl.col("LOCF_FLAG") == "Y"', "value": "LOCF"},
                        {"condition": 'pl.col("WOCF_FLAG") == "Y"', "value": "WOCF"},
                    ], else_value=None)
                    .to_frame()
                )
        """
        from fleet.sdtm.utils import parse_expression

        if not conditions:
            return self._chain(pl.lit(else_value).alias(target))
        first = conditions[0]
        c0 = (
            first["condition"]
            if isinstance(first["condition"], pl.Expr)
            else parse_expression(str(first["condition"]))
        )
        chain = pl.when(c0).then(pl.lit(first["value"]))
        for branch in conditions[1:]:
            c = (
                branch["condition"]
                if isinstance(branch["condition"], pl.Expr)
                else parse_expression(str(branch["condition"]))
            )
            chain = chain.when(c).then(pl.lit(branch["value"]))
        return self._chain(chain.otherwise(pl.lit(else_value)).alias(target))

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
        keep_cols: list[str] | None = None,
    ) -> Self:
        """Left-join ADSL columns onto the current dataset.

        Materialises the pipeline, left-joins *adsl* (optionally restricted to
        *keep_cols* plus the *by* key columns), and returns a fresh namespace.

        Args:
            adsl: The ADSL ``pl.DataFrame`` to merge in.
            by: Key column(s) for the join (default ``["USUBJID"]``).
            keep_cols: Subset of ADSL columns to bring in (excluding *by*
                keys, which are always included).  When ``None``, all ADSL
                columns are merged.

        Returns:
            Self: A fresh namespace wrapping the joined frame.

        Examples:
            Merge treatment date columns from ADSL::

                advs = (
                    vs_df.adam
                    .merge_adsl(adsl_df, keep_cols=["TRTSDT", "TRTEDT", "TRT01P"])
                    .to_frame()
                )
        """
        join_keys = by if by is not None else ["USUBJID"]
        if keep_cols is not None:
            extra = [c for c in join_keys if c not in keep_cols]
            adsl = adsl.select(keep_cols + extra)
        df = self.to_frame()
        joined = df.join(adsl, on=join_keys, how="left")
        return self._materialise_then(joined)

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
            raise ValueError("Cannot specify both source= and value=. Choose one.")
        if source is None and value is None:
            raise ValueError("Must specify either source= or value=.")

        output_type = _resolve_output_type(target, output)

        # DTC targets belong in SDTM, not ADaM
        if output_type == "dtc":
            raise ValueError(
                f"DTC output type is not supported on ADaM namespaces. "
                f"Use the SDTM .date() verb for target '{target}'."
            )

        # time= only valid for DTM
        if time is not None and output_type != "dtm":
            raise ValueError(
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
            return self._chain(*exprs)

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
            return self._chain(*exprs)

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

    def duration(
        self,
        target: str,
        *,
        start: str | pl.Expr,
        end: str | pl.Expr,
        unit: str = "days",
        add_one: bool | None = None,
        out: str = "numeric",
    ) -> Self:
        """Compute the duration between two date/datetime columns.

        Supports column references (``str``) and Polars expressions
        (e.g. ``pl.lit(date(2024, 1, 1))``) for *start* and *end*.

        The ``add_one`` parameter controls inclusive counting:
        - ``None`` (default): auto-resolves from the target suffix.
          ``*DY`` targets use CDISC study-day convention (no day 0);
          all others add 1 for inclusive counting.
        - ``True``: always add 1 (inclusive).
        - ``False``: raw difference (e.g. PK elapsed time).

        Args:
            target: Name of the output column.
            start: Start date column name or expression.
            end: End date column name or expression.
            unit: Duration unit — ``"seconds"``, ``"minutes"``, ``"hours"``,
                ``"days"`` (default), ``"weeks"``, ``"months"``, ``"years"``.
            add_one: Override for inclusive counting.  ``None`` auto-resolves
                from the target suffix.
            out: Output format — ``"numeric"`` (default) or ``"iso8601"``.

        Returns:
            Self: The namespace with *target* appended; call ``.to_frame()``
                to materialise.

        Examples:
            Study day (auto-detected from DY suffix)::

                adae = (
                    ae_df.adam
                    .duration("ASTDY", start="TRTSDT", end="ASTDT")
                    .to_frame()
                )

            Treatment duration in days::

                adsl = (
                    dm_df.adam.adsl
                    .duration("TRTDURD", start="TRTSDT", end="TRTEDT")
                    .to_frame()
                )

            PK elapsed time in hours::

                adpc = (
                    pc_df.adam.pk
                    .duration("APTS", start="EXSTDTM", end="PCDTM",
                              unit="hours", add_one=False)
                    .to_frame()
                )
        """
        # Normalise start/end to expressions
        start_expr = pl.col(start) if isinstance(start, str) else start
        end_expr = pl.col(end) if isinstance(end, str) else end

        # Auto-cast string columns to date/datetime
        start_expr = (
            start_expr.str.to_date(strict=False)
            .cast(pl.Date)
            .fill_null(start_expr.str.to_datetime("%Y-%m-%dT%H:%M:%S", strict=False))
            if isinstance(start, str)
            else start_expr
        )
        end_expr = (
            end_expr.str.to_date(strict=False)
            .cast(pl.Date)
            .fill_null(end_expr.str.to_datetime("%Y-%m-%dT%H:%M:%S", strict=False))
            if isinstance(start, str)
            else end_expr
        )

        # For string columns, we need a safer approach: try to cast
        # but the column may already be Date/Datetime. Use a materialise
        # approach to inspect dtypes.
        df = self._lazy.collect()

        def _to_date_expr(col_or_expr: str | pl.Expr) -> pl.Expr:
            """Resolve a column reference or expression to a temporal expr."""
            if isinstance(col_or_expr, str):
                col_name = col_or_expr
                if col_name in df.columns:
                    dtype = df[col_name].dtype
                    if dtype == pl.Date:
                        return pl.col(col_name)
                    if dtype.is_(pl.Datetime) or str(dtype).startswith("Datetime"):
                        # For time-based units, keep Datetime precision
                        if unit in ("seconds", "minutes", "hours"):
                            return pl.col(col_name)
                        return pl.col(col_name).cast(pl.Date)
                    # String → try to parse
                    if unit in ("seconds", "minutes", "hours"):
                        return pl.col(col_name).str.to_datetime(strict=False)
                    return pl.col(col_name).str.to_date(strict=False)
                return pl.col(col_name)
            # pl.Expr — use as-is
            return col_or_expr

        s_expr = _to_date_expr(start)
        e_expr = _to_date_expr(end)

        # Compute difference
        valid_units = {
            "seconds",
            "minutes",
            "hours",
            "days",
            "weeks",
            "months",
            "years",
        }
        if unit not in valid_units:
            raise ValueError(
                f"duration unit={unit!r} is not supported. Choose one of: {sorted(valid_units)}"
            )

        if unit in ("seconds", "minutes", "hours"):
            # Need datetime precision — ensure both sides are Datetime
            s_dtm = s_expr.cast(pl.Datetime("us"))
            e_dtm = e_expr.cast(pl.Datetime("us"))
            diff_s = (e_dtm - s_dtm).dt.total_seconds().cast(pl.Float64)
            if unit == "seconds":
                diff = diff_s.cast(pl.Int64)
            elif unit == "minutes":
                diff = diff_s / 60.0
            else:  # hours
                diff = diff_s / 3600.0
        else:
            diff_days = (e_expr - s_expr).dt.total_days()
            if unit == "days":
                diff = diff_days
            elif unit == "weeks":
                diff = diff_days.cast(pl.Float64) / 7.0
            elif unit == "months":
                diff = diff_days.cast(pl.Float64) / 30.4375
            else:  # years
                diff = diff_days.cast(pl.Float64) / 365.25

        # Resolve add_one
        if add_one is None:
            if target.endswith("DY"):
                # CDISC study day: +1 if >= 0, no day 0
                result_expr = (
                    (pl.when(diff >= 0).then(diff + 1).otherwise(diff)).cast(pl.Int64).alias(target)
                )
                return self._materialise_then(df.with_columns(result_expr))
            else:
                add_one = True

        if add_one:
            result_expr = (diff + 1).alias(target)
        else:
            result_expr = diff.alias(target)

        if out == "iso8601":
            # ISO 8601 duration formatting
            # For simplicity, output P{n}D for days, PT{n}H for hours, etc.
            abs_val = diff.abs()
            if unit == "days":
                iso_expr = (
                    pl.lit("P") + abs_val.cast(pl.Int64).cast(pl.String) + pl.lit("D")
                ).alias(target)
            elif unit == "hours":
                iso_expr = (
                    pl.lit("PT") + abs_val.cast(pl.Int64).cast(pl.String) + pl.lit("H")
                ).alias(target)
            elif unit == "weeks":
                iso_expr = (
                    pl.lit("P") + abs_val.cast(pl.Int64).cast(pl.String) + pl.lit("W")
                ).alias(target)
            elif unit == "years":
                iso_expr = (
                    pl.lit("P") + abs_val.cast(pl.Int64).cast(pl.String) + pl.lit("Y")
                ).alias(target)
            elif unit == "months":
                iso_expr = (
                    pl.lit("P") + abs_val.cast(pl.Int64).cast(pl.String) + pl.lit("M")
                ).alias(target)
            elif unit == "minutes":
                iso_expr = (
                    pl.lit("PT") + abs_val.cast(pl.Int64).cast(pl.String) + pl.lit("M")
                ).alias(target)
            else:  # seconds
                iso_expr = (
                    pl.lit("PT") + abs_val.cast(pl.Int64).cast(pl.String) + pl.lit("S")
                ).alias(target)
            return self._materialise_then(df.with_columns(iso_expr))

        return self._materialise_then(df.with_columns(result_expr))


class MultiRowMixin:
    """
    Mixin for ADaM datasets with multiple rows per subject (OCCDS, PK, etc.).

    Provides ``seq()`` — a sequential 1-based record-number verb.  Any
    namespace class that needs this verb should inherit from this mixin in
    *addition* to ``SharedADaMVerbsMixin``::

        class OCCDSNamespace(SharedADaMVerbsMixin, MultiRowMixin): ...
        class PKNamespace(SharedADaMVerbsMixin, MultiRowMixin): ...
    """

    def seq(
        self,
        target: str = "ASEQ",
        *,
        order_by: list[str] | None = None,
        groups: list[str] | None = None,
        check_uniqueness: bool = False,
    ) -> Self:
        """Derive a 1-based observation sequence number within each group.

        Mirrors admiral's ``derive_var_obs_number()``.  When *order_by* is
        provided the data is sorted within each *groups* partition before
        numbering, ensuring deterministic and reproducible sequence values.

        Args:
            target: Name of the output sequence column (default ``"ASEQ"``).
            order_by: Columns that define the sort order within each group.
                When ``None``, the current row order is preserved.
            groups: Partition columns (default ``["USUBJID"]``).
            check_uniqueness: If ``True``, emit a warning when the
                combination of *groups* + *order_by* does not uniquely
                identify each row (analogous to admiral's
                ``check_type = "warning"``).

        Returns:
            Self: A fresh namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Add a per-subject sequence number ordered by analysis date::

                adae = (
                    ae_df.adam.occds
                    .seq("ASEQ", order_by=["ASTDT"], groups=["USUBJID"])
                    .to_frame()
                )
        """
        from fleet.core.seq import derive_seq

        grps = groups or ["USUBJID"]
        df = derive_seq(
            self.to_frame(),
            target,
            order_by=order_by,
            groups=grps,
            check_uniqueness=check_uniqueness,
        )
        return self._materialise_then(df)
