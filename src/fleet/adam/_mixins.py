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
from typing import TYPE_CHECKING, Any, Self

import polars as pl

from fleet.core._pin_mixin import PinMixin
from fleet.core._verb_mixin import SharedVerbsMixin

if TYPE_CHECKING:
    pass


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
        order_cols: list[str] | None = None
        if order_by is not None:
            order_cols = [order_by] if isinstance(order_by, str) else list(order_by)

        where_expr: pl.Expr | None = None
        if where is not None:
            where_expr = where if isinstance(where, pl.Expr) else parse_expression(str(where))

        false_lit = pl.lit(false_value) if false_value is not None else pl.lit(None)

        criteria_lower = criteria.lower() if isinstance(criteria, str) else None

        if criteria_lower in ("first", "last"):
            return self._flag_ranked(
                target,
                criteria_lower=criteria_lower,
                grps=grps,
                order_cols=order_cols,
                where_expr=where_expr,
                flag_all=flag_all,
                flag_value=flag_value,
                false_value=false_value,
                false_lit=false_lit,
            )
        elif criteria_lower in ("max", "min"):
            return self._flag_extreme(
                target,
                criteria_lower=criteria_lower,
                grps=grps,
                value_col=value_col,
                where_expr=where_expr,
                flag_value=flag_value,
                false_lit=false_lit,
            )
        elif criteria_lower == "exists":
            return self._flag_exists(
                target,
                grps=grps,
                from_dataset=from_dataset,
                on=on,
                source_filter=source_filter,
                flag_value=flag_value,
                false_value=false_value,
                false_lit=false_lit,
            )
        elif criteria_lower in ("before", "after"):
            return self._flag_relative(
                target,
                criteria_lower=criteria_lower,
                grps=grps,
                order_cols=order_cols,
                condition=condition,
                inclusive=inclusive,
                flag_no_ref_groups=flag_no_ref_groups,
                flag_value=flag_value,
                false_value=false_value,
            )
        elif criteria_lower in ("exists_after", "exists_before"):
            return self._flag_temporal_exists(
                target,
                criteria_lower=criteria_lower,
                from_dataset=from_dataset,
                on=on,
                order_cols=order_cols,
                condition=condition,
                source_filter=source_filter,
                flag_value=flag_value,
            )
        else:
            return self._flag_expression(
                target,
                criteria=criteria,
                where_expr=where_expr,
                flag_value=flag_value,
                false_lit=false_lit,
            )

    def _flag_ranked(
        self,
        target,
        *,
        criteria_lower,
        grps,
        order_cols,
        where_expr,
        flag_all,
        flag_value,
        false_value,
        false_lit,
    ) -> Self:
        """Handle first/last rank-based flag criteria."""
        if not order_cols:
            raise ValueError(f"flag criteria='{criteria_lower}' requires order_by.")
        descending = criteria_lower == "last"

        df = self._lazy.collect()
        df = df.with_row_index("__flag_orig_idx__")
        null_mask = pl.all_horizontal([pl.col(c).is_not_null() for c in order_cols])

        if flag_all:
            if len(order_cols) == 1:
                val_expr = pl.col(order_cols[0])
            else:
                val_expr = pl.struct(order_cols)
            extreme = val_expr.max().over(grps) if descending else val_expr.min().over(grps)
            row_cond = null_mask & (val_expr == extreme)
            if where_expr is not None:
                row_cond = where_expr & row_cond
            expr = pl.when(row_cond).then(pl.lit(flag_value)).otherwise(false_lit).alias(target)
            result_df = df.with_columns(expr).sort("__flag_orig_idx__").drop("__flag_orig_idx__")
            return self._materialise_then(result_df)

        sort_descending = [descending] * len(order_cols)
        null_last = [True] * len(order_cols)

        eligible = df.filter(null_mask)
        if where_expr is not None:
            eligible = eligible.filter(where_expr)

        eligible_sorted = eligible.sort(
            order_cols, descending=sort_descending, nulls_last=null_last
        )
        first_per_group = eligible_sorted.group_by(grps, maintain_order=True).first()
        flagged_indices = set(first_per_group["__flag_orig_idx__"].to_list())

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

    def _flag_extreme(
        self,
        target,
        *,
        criteria_lower,
        grps,
        value_col,
        where_expr,
        flag_value,
        false_lit,
    ) -> Self:
        """Handle max/min value-based extreme flag criteria."""
        if not value_col:
            raise ValueError(f"flag criteria='{criteria_lower}' requires value_col.")
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
        expr = pl.when(row_cond).then(pl.lit(flag_value)).otherwise(false_lit).alias(target)
        return self._chain(expr)

    def _flag_exists(
        self,
        target,
        *,
        grps,
        from_dataset,
        on,
        source_filter,
        flag_value,
        false_value,
        false_lit,
    ) -> Self:
        """Handle exists set-membership flag criteria."""
        if from_dataset is None or on is None:
            raise ValueError("flag criteria='exists' requires from_dataset and on.")
        datasets = from_dataset if isinstance(from_dataset, list) else [from_dataset]
        key_frames: list[pl.DataFrame] = []
        for ds in datasets:
            filtered = ds
            if source_filter is not None:
                filtered = ds.filter(source_filter)
            key_frames.append(filtered.select(on).unique())
        all_keys = pl.concat(key_frames).unique()

        df = self._lazy.collect()

        if len(on) == 1:
            is_member = pl.col(on[0]).is_in(all_keys[on[0]].to_list())
            expr = pl.when(is_member).then(pl.lit(flag_value)).otherwise(false_lit).alias(target)
            return self._chain(expr)

        # Multi-column join path
        df_with_idx = df.with_row_index("__flag_idx__")
        result = (
            (df_with_idx.drop(target) if target in df_with_idx.columns else df_with_idx)
            .join(
                df_with_idx.select(on + ["__flag_idx__"])
                .unique()
                .join(all_keys, on=on, how="semi")
                .with_columns(pl.lit(flag_value).alias(target)),
                on="__flag_idx__",
                how="left",
            )
            .with_columns(
                pl.col(target).fill_null(pl.lit(false_value) if false_value else pl.lit(None))
            )
            .drop("__flag_idx__")
        )
        return self._materialise_then(result)

    def _flag_relative(
        self,
        target,
        *,
        criteria_lower,
        grps,
        order_cols,
        condition,
        inclusive,
        flag_no_ref_groups,
        flag_value,
        false_value,
    ) -> Self:
        """Handle before/after relative-to-landmark flag criteria."""
        if condition is None:
            raise ValueError(f"flag criteria='{criteria_lower}' requires condition.")
        if not order_cols:
            raise ValueError(f"flag criteria='{criteria_lower}' requires order_by.")

        df = self._lazy.collect()
        df = df.with_row_index("__orig_idx__")
        df_sorted = df.sort(order_cols)

        cond_col = "__flag_cond__"
        df_sorted = df_sorted.with_columns(condition.cast(pl.Boolean).alias(cond_col))

        result_parts: list[pl.DataFrame] = []
        for _, grp_df in df_sorted.group_by(grps, maintain_order=True):
            cond_mask = grp_df[cond_col].to_list()
            first_cond_idx: int | None = None
            for i, v in enumerate(cond_mask):
                if v is True:
                    first_cond_idx = i
                    break

            n = len(grp_df)
            if first_cond_idx is None:
                if flag_no_ref_groups:
                    if criteria_lower == "before":
                        flags = [flag_value] * n
                    else:
                        flags = [false_value] * n
                else:
                    flags = [false_value if false_value else None] * n
            else:
                flags = []
                for i in range(n):
                    if criteria_lower == "before":
                        flagged = i <= first_cond_idx if inclusive else i < first_cond_idx
                    else:
                        flagged = i >= first_cond_idx if inclusive else i > first_cond_idx
                    flags.append(flag_value if flagged else (false_value if false_value else None))
            result_parts.append(grp_df.with_columns(pl.Series(target, flags)))

        result_df = pl.concat(result_parts)
        result_df = result_df.sort("__orig_idx__").drop(["__orig_idx__", cond_col])
        return self._materialise_then(result_df)

    def _flag_temporal_exists(
        self,
        target,
        *,
        criteria_lower,
        from_dataset,
        on,
        order_cols,
        condition,
        source_filter,
        flag_value,
    ) -> Self:
        """Handle exists_after/exists_before temporal join flag criteria."""
        if from_dataset is None or condition is None:
            raise ValueError(
                f"flag criteria='{criteria_lower}' requires from_dataset and condition."
            )
        if on is None:
            raise ValueError(f"flag criteria='{criteria_lower}' requires on.")

        df = self._lazy.collect()
        src = from_dataset if isinstance(from_dataset, pl.DataFrame) else pl.concat(from_dataset)
        if source_filter is not None:
            src = src.filter(source_filter)

        if order_cols:
            time_col = order_cols[0]
        else:
            common_time = [
                c for c in ["AVISITN", "ADY", "ADT", "ADTM"] if c in df.columns and c in src.columns
            ]
            if not common_time:
                raise ValueError(
                    f"flag criteria='{criteria_lower}' requires order_by or a "
                    "common temporal column (AVISITN, ADY, ADT, ADTM)."
                )
            time_col = common_time[0]

        df = df.with_row_index("__flag_idx__")
        cond_df = df.filter(condition)

        flags = [None] * len(df)
        for row in cond_df.iter_rows(named=True):
            src_filtered = src
            for key in on:
                src_filtered = src_filtered.filter(pl.col(key) == row[key])
            if len(src_filtered) == 0:
                continue
            row_time = row[time_col]
            if criteria_lower == "exists_after":
                matches = src_filtered.filter(pl.col(time_col) > row_time)
            else:
                matches = src_filtered.filter(pl.col(time_col) < row_time)
            if len(matches) > 0:
                flags[row["__flag_idx__"]] = flag_value

        result_df = df.drop("__flag_idx__").with_columns(pl.Series(target, flags))
        return self._materialise_then(result_df)

    def _flag_expression(
        self,
        target,
        *,
        criteria,
        where_expr,
        flag_value,
        false_lit,
    ) -> Self:
        """Handle direct expression-based flag criteria."""
        from fleet.sdtm.utils import parse_expression

        if isinstance(criteria, pl.Expr):
            row_cond = criteria
        else:
            row_cond = parse_expression(str(criteria))
        final_cond = (where_expr & row_cond) if where_expr is not None else row_cond
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
        return super().study_day(
            target, date_col=date_col, ref_col=ref_col, ref_pin=ref_pin, ref_df=adsl
        )

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


class MultiRowMixin:
    """
    Mixin for ADaM datasets with multiple rows per subject (OCCDS, PK, etc.).

    Previously provided ``seq()`` which has been moved to
    ``SharedVerbsMixin``.  Retained as a marker interface for multi-row
    namespace classes (OCCDS, PK, etc.).
    """

    pass
