"""Flag / criterion verbs shared by SDTM and ADaM namespaces.

``FlagCriterionMixin`` provides ``flag()`` (with its discoverable
``flag_first`` / ``flag_last`` / ``flag_extreme`` / ``flag_exists`` /
``flag_relative`` wrappers) and ``criterion()`` to any namespace that
exposes ``_chain()`` / ``_materialise_then()`` / ``_with_lazy()``.

Both the SDTM namespace (``df.sdtm``) and all ADaM namespaces inherit
from this mixin.  The keyword criteria modes are implemented as pure
Polars window/join expressions, so they stay lazy and vectorised.
"""

from __future__ import annotations

import difflib
import re
from typing import Literal, Self

import polars as pl

from fleet.core.exceptions import DerivationError, VerbUsageError

#: Built-in shortcut keywords accepted by ``flag(criteria=...)``.
_FLAG_CRITERIA_KEYWORDS: frozenset[str] = frozenset(
    {
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
)

#: Which flag() parameters are consumed by each criteria mode.  A
#: parameter passed with a non-default value outside its modes raises
#: ``VerbUsageError`` instead of being silently ignored.
_FLAG_MODE_PARAMS: dict[str, frozenset[str]] = {
    "order_by": frozenset({"first", "last", "before", "after", "exists_after", "exists_before"}),
    "value_col": frozenset({"max", "min"}),
    "where": frozenset({"first", "last", "max", "min", "expression"}),
    "from_dataset": frozenset({"exists", "exists_after", "exists_before"}),
    "on": frozenset({"exists", "exists_after", "exists_before"}),
    "source_filter": frozenset({"exists", "exists_after", "exists_before"}),
    "condition": frozenset({"before", "after", "exists_after", "exists_before"}),
    "inclusive": frozenset({"before", "after"}),
    "flag_no_ref_groups": frozenset({"before", "after"}),
    "flag_all": frozenset({"first", "last"}),
    "false_value": frozenset(
        {"first", "last", "max", "min", "exists", "before", "after", "expression"}
    ),
}

#: Defaults used to detect explicitly-passed parameters (identity check).
_FLAG_PARAM_DEFAULTS: dict[str, object] = {
    "order_by": None,
    "value_col": None,
    "where": None,
    "from_dataset": None,
    "on": None,
    "source_filter": None,
    "condition": None,
    "inclusive": True,
    "flag_no_ref_groups": True,
    "flag_all": False,
    "false_value": None,
}


class FlagCriterionMixin:
    """Mixin providing ``flag()``, its wrappers, and ``criterion()``.

    Both SDTM (``df.sdtm``) and all ADaM namespaces inherit from this
    mixin.  The methods rely on ``_chain()``, ``_with_lazy()`` and
    ``_materialise_then()`` which every concrete namespace class must
    provide.
    """

    _lazy: pl.LazyFrame

    # Subclasses must provide these — declared here for type-checker only.
    def _chain(self, *exprs: pl.Expr, verb: str | None = None) -> Self: ...  # noqa: E704
    def _materialise_then(self, df: pl.DataFrame) -> Self: ...  # noqa: E704
    def _with_lazy(self, lf: pl.LazyFrame) -> Self: ...  # noqa: E704

    # ------------------------------------------------------------------ #
    # Flag — generalised "Y" / null flagging                               #
    # ------------------------------------------------------------------ #

    def flag(
        self,
        target: str,
        *,
        criteria: str | pl.Expr,
        by: list[str] | None = None,
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

        Parameters that are irrelevant to the selected criteria mode
        raise :class:`~fleet.core.exceptions.VerbUsageError` instead of
        being silently ignored.  The ``flag_first`` / ``flag_last`` /
        ``flag_extreme`` / ``flag_exists`` / ``flag_relative`` wrappers
        expose each mode with only its own parameters.

        Args:
            target: Name of the output flag column.
            criteria: A Polars expression, or one of ``"first"``,
                ``"last"``, ``"max"``, ``"min"``, ``"exists"``,
                ``"before"``, ``"after"``, ``"exists_after"``,
                ``"exists_before"``.
            by: Partition columns (default ``["USUBJID"]``).
            order_by: Sort column(s) required for ``"first"``/``"last"``
                and ``"before"``/``"after"``.  On a tie among candidates,
                ``"last"`` takes the last input record and ``"first"`` the
                first (SAS ``LAST.``/``FIRST.``); add a sequence variable
                to remove the dependence on input order.  For
                ``"first"``/``"last"`` a missing value sorts last in each
                key, as admiral (ADR-0020): ``"last"`` takes a record with a
                missing key, and ``"first"`` takes one only when every
                candidate misses it.  SAS sorts a missing value first, so a
                QC program with PROC SORT differs on such a group.
                ``"exists_after"``/``"exists_before"`` take one column
                only; build one ordered key (ADTM) for date and time.
            value_col: Value column required for ``"max"``/``"min"``.
            where: Optional pre-filter — only matching rows are candidates;
                rows that fail it take no part, even on a tie.
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

        Raises:
            VerbUsageError: When a parameter irrelevant to the selected
                criteria mode is passed.
            DerivationError: When a mode-required parameter is missing,
                or a bare-identifier *criteria* matches neither a
                keyword nor a column.

        References:
            admiral ``derive_var_extreme_flag`` (pharmaverse): the order of
            ``"first"``/``"last"``, a missing value last in each key (ADR-0020).

        Examples:
            First observation per group::

                advs = (
                    vs_raw.adam
                    .flag("ABLFL", criteria="first", order_by="AVISITN",
                          by=["USUBJID", "PARAMCD"])
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
                          order_by="AVISITN", by=["USUBJID"],
                          inclusive=True)
                    .to_frame()
                )

            Population flag from the treatment start date (a population
            flag is never blank, so non-members get ``"N"``)::

                adsl = (
                    adsl.adam.adsl
                    .flag("SAFFL", criteria=pl.col("TRTSDT").is_not_null(),
                          false_value="N")
                    .to_frame()
                )
        """
        from fleet.sdtm.utils import parse_expression

        grps = by or ["USUBJID"]
        order_cols: list[str] | None = None
        if order_by is not None:
            order_cols = [order_by] if isinstance(order_by, str) else list(order_by)

        criteria_lower = criteria.lower() if isinstance(criteria, str) else None
        mode = criteria_lower if criteria_lower in _FLAG_CRITERIA_KEYWORDS else "expression"
        if mode == "expression":
            # Keyword typos ("frist") must surface as a did-you-mean error
            # before any parameter validation blames the wrong thing.
            self._check_flag_criteria_typo(target, criteria)
        self._validate_flag_params(
            target,
            criteria,
            mode,
            {
                "order_by": order_by,
                "value_col": value_col,
                "where": where,
                "from_dataset": from_dataset,
                "on": on,
                "source_filter": source_filter,
                "condition": condition,
                "inclusive": inclusive,
                "flag_no_ref_groups": flag_no_ref_groups,
                "flag_all": flag_all,
                "false_value": false_value,
            },
        )

        where_expr: pl.Expr | None = None
        if where is not None:
            where_expr = where if isinstance(where, pl.Expr) else parse_expression(str(where))

        false_lit = pl.lit(false_value) if false_value is not None else pl.lit(None)

        if mode in ("first", "last"):
            return self._flag_ranked(
                target,
                criteria_lower=mode,
                grps=grps,
                order_cols=order_cols,
                where_expr=where_expr,
                flag_all=flag_all,
                flag_value=flag_value,
                false_lit=false_lit,
            )
        elif mode in ("max", "min"):
            return self._flag_extreme(
                target,
                criteria_lower=mode,
                grps=grps,
                value_col=value_col,
                where_expr=where_expr,
                flag_value=flag_value,
                false_lit=false_lit,
            )
        elif mode == "exists":
            return self._flag_exists(
                target,
                grps=grps,
                from_dataset=from_dataset,
                on=on,
                source_filter=source_filter,
                flag_value=flag_value,
                false_lit=false_lit,
            )
        elif mode in ("before", "after"):
            return self._flag_relative(
                target,
                criteria_lower=mode,
                grps=grps,
                order_cols=order_cols,
                condition=condition,
                inclusive=inclusive,
                flag_no_ref_groups=flag_no_ref_groups,
                flag_value=flag_value,
                false_value=false_value,
            )
        elif mode in ("exists_after", "exists_before"):
            return self._flag_temporal_exists(
                target,
                criteria_lower=mode,
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

    # ------------------------------------------------------------------ #
    # Discoverable per-mode wrappers                                       #
    # ------------------------------------------------------------------ #

    def flag_first(
        self,
        target: str,
        *,
        order_by: str | list[str],
        by: list[str] | None = None,
        where: str | pl.Expr | None = None,
        flag_all: bool = False,
        flag_value: str = "Y",
        false_value: str | None = None,
    ) -> Self:
        """Flag the first record per group (``flag(criteria="first")``).

        Args:
            target: Name of the output flag column.
            order_by: Sort column(s) defining "first" within each group.
                A tie goes to the first input record.  A missing value sorts
                last, as admiral: it is first only when every candidate
                misses it.
            by: Partition columns (default ``["USUBJID"]``).
            where: Optional pre-filter — only matching rows are candidates.
            flag_all: Flag every tied extreme record instead of one.
            flag_value: Value assigned to flagged records (default ``"Y"``).
            false_value: Value assigned otherwise (default null).

        Returns:
            Self: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Baseline flag on the first visit per subject/parameter::

                advs = (
                    vs_raw.adam
                    .flag_first("ABLFL", order_by="AVISITN",
                                by=["USUBJID", "PARAMCD"])
                    .to_frame()
                )
        """
        return self.flag(
            target,
            criteria="first",
            order_by=order_by,
            by=by,
            where=where,
            flag_all=flag_all,
            flag_value=flag_value,
            false_value=false_value,
        )

    def flag_last(
        self,
        target: str,
        *,
        order_by: str | list[str],
        by: list[str] | None = None,
        where: str | pl.Expr | None = None,
        flag_all: bool = False,
        flag_value: str = "Y",
        false_value: str | None = None,
    ) -> Self:
        """Flag the last record per group (``flag(criteria="last")``).

        Args:
            target: Name of the output flag column.
            order_by: Sort column(s) defining "last" within each group.
                A tie goes to the last input record.  A missing value sorts
                last, as admiral, so a record with a missing key is last.
            by: Partition columns (default ``["USUBJID"]``).
            where: Optional pre-filter — only matching rows are candidates.
            flag_all: Flag every tied extreme record instead of one.
            flag_value: Value assigned to flagged records (default ``"Y"``).
            false_value: Value assigned otherwise (default null).

        Returns:
            Self: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Last analysis-eligible record per subject/parameter::

                advs = (
                    vs_raw.adam
                    .flag_last("ANL01FL", order_by="ADT",
                               by=["USUBJID", "PARAMCD"])
                    .to_frame()
                )
        """
        return self.flag(
            target,
            criteria="last",
            order_by=order_by,
            by=by,
            where=where,
            flag_all=flag_all,
            flag_value=flag_value,
            false_value=false_value,
        )

    def flag_extreme(
        self,
        target: str,
        *,
        value_col: str,
        mode: Literal["max", "min"] = "max",
        by: list[str] | None = None,
        where: str | pl.Expr | None = None,
        flag_value: str = "Y",
        false_value: str | None = None,
    ) -> Self:
        """Flag the extreme-valued record(s) per group (``criteria="max"/"min"``).

        Args:
            target: Name of the output flag column.
            value_col: Column whose extreme value is flagged.
            mode: ``"max"`` (default) or ``"min"``.
            by: Partition columns (default ``["USUBJID"]``).
            where: Optional pre-filter — only matching rows are candidates.
            flag_value: Value assigned to flagged records (default ``"Y"``).
            false_value: Value assigned otherwise (default null).

        Returns:
            Self: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Worst-severity record per subject and term::

                adae = (
                    ae_df.adam.occds
                    .flag_extreme("ANL01FL", value_col="AESEVN",
                                  by=["USUBJID", "AETERM"])
                    .to_frame()
                )
        """
        return self.flag(
            target,
            criteria=mode,
            value_col=value_col,
            by=by,
            where=where,
            flag_value=flag_value,
            false_value=false_value,
        )

    def flag_exists(
        self,
        target: str,
        *,
        from_dataset: pl.DataFrame | list[pl.DataFrame],
        on: list[str],
        source_filter: pl.Expr | None = None,
        flag_value: str = "Y",
        false_value: str | None = None,
    ) -> Self:
        """Flag records with a match in external dataset(s) (``criteria="exists"``).

        Args:
            target: Name of the output flag column.
            from_dataset: External dataset(s) to look up keys in.
            on: Join key columns.
            source_filter: Filter applied to *from_dataset* before key
                extraction.
            flag_value: Value assigned when a match exists (default ``"Y"``).
            false_value: Value assigned otherwise (default null).

        Returns:
            Self: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Subjects with a baseline vital-signs record::

                adsl = (
                    dm.adam.adsl
                    .flag_exists("VSEVALFL", from_dataset=advs,
                                 on=["USUBJID"],
                                 source_filter=pl.col("AVISIT") == "BASELINE")
                    .to_frame()
                )
        """
        return self.flag(
            target,
            criteria="exists",
            from_dataset=from_dataset,
            on=on,
            source_filter=source_filter,
            flag_value=flag_value,
            false_value=false_value,
        )

    def flag_relative(
        self,
        target: str,
        *,
        when: Literal["before", "after"],
        condition: pl.Expr,
        order_by: str | list[str],
        by: list[str] | None = None,
        inclusive: bool = True,
        flag_no_ref_groups: bool = True,
        flag_value: str = "Y",
        false_value: str | None = None,
    ) -> Self:
        """Flag records before/after a landmark (``criteria="before"/"after"``).

        Args:
            target: Name of the output flag column.
            when: ``"before"`` or ``"after"`` the first landmark record.
            condition: Boolean expression identifying landmark rows.
            order_by: Sort column(s) defining record order within groups.
            by: Partition columns (default ``["USUBJID"]``).
            inclusive: Whether the landmark row itself is flagged.
            flag_no_ref_groups: If ``True`` (default), every record of a
                group with no landmark gets *flag_value*, in both
                directions, as admiral ``derive_var_relative_flag``.  Pass
                ``False`` for a post-event flag, so that such a group gets
                *false_value*.
            flag_value: Value assigned to flagged records (default ``"Y"``).
            false_value: Value assigned otherwise (default null).

        Returns:
            Self: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Analysis flag for records up to first disease progression::

                adrs = (
                    rs_df.adam
                    .flag_relative("ANL02FL", when="before",
                                   condition=pl.col("AVALC") == "PD",
                                   order_by="AVISITN", by=["USUBJID"])
                    .to_frame()
                )
        """
        return self.flag(
            target,
            criteria=when,
            condition=condition,
            order_by=order_by,
            by=by,
            inclusive=inclusive,
            flag_no_ref_groups=flag_no_ref_groups,
            flag_value=flag_value,
            false_value=false_value,
        )

    # ------------------------------------------------------------------ #
    # Internal validation / dispatch helpers                               #
    # ------------------------------------------------------------------ #

    def _validate_flag_params(
        self,
        target: str,
        criteria: str | pl.Expr,
        mode: str,
        passed: dict[str, object],
    ) -> None:
        """Reject parameters that the selected criteria mode does not use."""
        irrelevant = [
            name
            for name, value in passed.items()
            if value is not _FLAG_PARAM_DEFAULTS[name] and mode not in _FLAG_MODE_PARAMS[name]
        ]
        if not irrelevant:
            return
        crit_repr = repr(criteria) if isinstance(criteria, str) else "<expression>"
        raise VerbUsageError(
            f"flag('{target}', criteria={crit_repr}): parameter(s) "
            f"{', '.join(sorted(irrelevant))} are not used by criteria mode "
            f"'{mode}' and would be silently ignored. Remove them, or pick the "
            "matching mode (see flag_first/flag_last/flag_extreme/flag_exists/"
            "flag_relative for per-mode signatures)."
        )

    def _check_flag_criteria_typo(self, target: str, criteria: str | pl.Expr) -> None:
        """Reject bare-identifier criteria that match neither keyword nor column.

        A string like ``"frist"`` would otherwise fall through to
        expression parsing and blame a nonexistent *column* when the user
        typo'd a *keyword*.  Reports both interpretations.
        """
        if not isinstance(criteria, str):
            return
        bare = criteria.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", bare):
            return
        schema_names = self._lazy.collect_schema().names()
        if bare in schema_names:
            return
        parts = [
            f"flag('{target}', criteria={criteria!r}): {bare!r} is neither a "
            "criteria keyword nor a column in the frame."
        ]
        kw_hit = difflib.get_close_matches(bare.lower(), sorted(_FLAG_CRITERIA_KEYWORDS), n=1)
        if kw_hit:
            parts.append(f"Did you mean criteria='{kw_hit[0]}'?")
        col_hit = difflib.get_close_matches(bare, schema_names, n=1)
        if col_hit:
            parts.append(f"Or the column '{col_hit[0]}'?")
        parts.append(f"Valid keywords: {sorted(_FLAG_CRITERIA_KEYWORDS)}.")
        raise DerivationError(" ".join(parts))

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
        false_lit,
    ) -> Self:
        """Handle first/last rank-based flag criteria.

        The order is admiral's (``dplyr::arrange``): ascending on each key,
        a missing value last, then input order.  ``"first"`` takes the first
        record of that order and ``"last"`` the last one, so a record with a
        missing key is the last record, and it is first only when every
        candidate of the group misses that key.
        """
        if not order_cols:
            raise DerivationError(f"flag criteria='{criteria_lower}' requires order_by.")
        last = criteria_lower == "last"
        eligible = pl.lit(True) if where_expr is None else where_expr.fill_null(False)
        # is_null() before each key puts a missing value last: Polars 1.x ignores
        # nulls_last when a window order_by has more than one key.
        null_keys = [
            k
            for i, c in enumerate(order_cols)
            for k in (pl.col(c).is_null().alias(f"__null_{i}"), pl.col(c))
        ]

        if flag_all:
            # "last" reads admiral's order backwards: descending, so missing values come first.
            def ordered(expr: pl.Expr) -> pl.Expr:
                return expr.over(
                    grps,
                    order_by=[*null_keys, pl.int_range(pl.len()).alias("__tie")],
                    descending=last,
                )

            # Every candidate whose keys equal the winner's, a missing value equal to a missing one.
            row_cond = eligible & pl.all_horizontal(
                pl.col(c).eq_missing(ordered(pl.col(c).filter(eligible).first()))
                for c in order_cols
            )
        else:
            # One global sort instead of an ordered window: a window is slow with many
            # small groups (issue #207). Candidates go to the end of their group for
            # "last", to the front for "first"; a tie keeps input order.
            position = pl.int_range(pl.len())
            sort_keys = [*grps, eligible if last else ~eligible, *null_keys, position]
            group = pl.struct(grps).sort_by(sort_keys)
            edge = group.is_last_distinct() if last else group.is_first_distinct()
            row_cond = edge.sort_by(position.sort_by(sort_keys)) & eligible
        expr = pl.when(row_cond).then(pl.lit(flag_value)).otherwise(false_lit).alias(target)
        return self._chain(expr, verb="flag")

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
            raise DerivationError(f"flag criteria='{criteria_lower}' requires value_col.")
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
        return self._chain(expr, verb="flag")

    def _flag_exists(
        self,
        target,
        *,
        grps,
        from_dataset,
        on,
        source_filter,
        flag_value,
        false_lit,
    ) -> Self:
        """Handle exists set-membership flag criteria."""
        if from_dataset is None or on is None:
            raise DerivationError("flag criteria='exists' requires from_dataset and on.")
        datasets = from_dataset if isinstance(from_dataset, list) else [from_dataset]
        key_frames: list[pl.DataFrame] = []
        for ds in datasets:
            filtered = ds
            if source_filter is not None:
                filtered = ds.filter(source_filter)
            key_frames.append(filtered.select(on).unique())
        all_keys = pl.concat(key_frames).unique()

        if len(on) == 1:
            is_member = pl.col(on[0]).is_in(all_keys[on[0]].implode(), nulls_equal=True)
        else:
            is_member = pl.struct(on).is_in(
                all_keys.select(pl.struct(on)).to_series().implode(), nulls_equal=True
            )
        expr = pl.when(is_member).then(pl.lit(flag_value)).otherwise(false_lit).alias(target)
        return self._chain(expr, verb="flag")

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
        """Handle before/after relative-to-landmark flag criteria (window exprs)."""
        if condition is None:
            raise DerivationError(f"flag criteria='{criteria_lower}' requires condition.")
        if not order_cols:
            raise DerivationError(f"flag criteria='{criteria_lower}' requires order_by.")

        pos = pl.int_range(pl.len()).over(grps, order_by=[pl.col(c) for c in order_cols])
        cond_bool = condition.cast(pl.Boolean)
        landmark = pl.when(cond_bool).then(pos).otherwise(None).min().over(grps)

        norm_false = pl.lit(false_value) if false_value else pl.lit(None)
        no_ref = pl.lit(flag_value) if flag_no_ref_groups else norm_false
        if criteria_lower == "before":
            flagged = (pos <= landmark) if inclusive else (pos < landmark)
        else:
            flagged = (pos >= landmark) if inclusive else (pos > landmark)

        expr = (
            pl.when(landmark.is_null())
            .then(no_ref)
            .when(flagged)
            .then(pl.lit(flag_value))
            .otherwise(norm_false)
            .alias(target)
        )
        return self._chain(expr, verb="flag")

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
        """Handle exists_after/exists_before via one aggregate join.

        "Any source record strictly after t" is equivalent to
        "max(source times) > t" (and symmetrically with min for
        exists_before), so a per-key aggregate left join replaces the
        former per-row scan.
        """
        if from_dataset is None or condition is None:
            raise DerivationError(
                f"flag criteria='{criteria_lower}' requires from_dataset and condition."
            )
        if on is None:
            raise DerivationError(f"flag criteria='{criteria_lower}' requires on.")

        src = from_dataset if isinstance(from_dataset, pl.DataFrame) else pl.concat(from_dataset)
        if source_filter is not None:
            src = src.filter(source_filter)

        if len(order_cols) > 1:
            raise VerbUsageError(
                f"flag criteria='{criteria_lower}' takes one order_by column, got "
                f"{order_cols}. Build one ordered key column first, for example "
                "pl.concat_str([pl.col('ADT').cast(pl.String), pl.col('ATM')]) or ADTM, "
                "and pass it as order_by."
            )
        if order_cols:
            time_col = order_cols[0]
        else:
            schema_names = self._lazy.collect_schema().names()
            common_time = [
                c
                for c in ["AVISITN", "ADY", "ADT", "ADTM"]
                if c in schema_names and c in src.columns
            ]
            if not common_time:
                raise DerivationError(
                    f"flag criteria='{criteria_lower}' requires order_by or a "
                    "common temporal column (AVISITN, ADY, ADT, ADTM)."
                )
            time_col = common_time[0]

        tmp = "__flag_src_time__"
        if criteria_lower == "exists_after":
            src_agg = src.group_by(on).agg(pl.col(time_col).max().alias(tmp))
            cmp = pl.col(tmp) > pl.col(time_col)
        else:
            src_agg = src.group_by(on).agg(pl.col(time_col).min().alias(tmp))
            cmp = pl.col(tmp) < pl.col(time_col)

        flag_expr = (
            pl.when(condition & cmp).then(pl.lit(flag_value)).otherwise(pl.lit(None)).alias(target)
        )
        lf = (
            self._lazy.join(
                src_agg.lazy(), on=on, how="left", maintain_order="left", nulls_equal=True
            )
            .with_columns(flag_expr)
            .drop(tmp)
        )
        return self._with_lazy(lf)

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
            row_cond = parse_expression(str(criteria), self._lazy.collect_schema())
        final_cond = (where_expr & row_cond) if where_expr is not None else row_cond
        expr = pl.when(final_cond).then(pl.lit(flag_value)).otherwise(false_lit).alias(target)
        return self._chain(expr, verb="flag")

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
        - ``{prefix}{number}FL`` — ``"Y"`` if condition is met, ``"N"`` if not.
        - ``{prefix}{number}FN`` — ``1`` if met, ``0`` if not.

        When the condition is null (for example AVAL is missing), FL and FN are
        null, as admiral ``derive_vars_crit_flag()``. For a SAP rule "missing is
        not met", pass ``condition=(...).fill_null(False)``.

        References:
            admiral ``derive_vars_crit_flag(values_yn = TRUE,
            create_numeric_flag = TRUE)``; ADR-0033.

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
        fl_expr = (
            pl.when(condition).then(pl.lit("Y")).when(~condition).then(pl.lit("N")).alias(col_fl)
        )
        fn_expr = pl.when(condition).then(pl.lit(1)).when(~condition).then(pl.lit(0)).alias(col_fn)

        return self._chain(desc_expr, fl_expr, fn_expr, verb="criterion")
