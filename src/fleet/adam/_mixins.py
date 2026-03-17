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

Return types & IDE support
~~~~~~~~~~~~~~~~~~~~~~~~~~~
All shared methods use ``typing.Self`` as their return type.  IDEs resolve
``Self`` to the concrete class at each call-site — so
``df.adam.adsl.source(...)`` auto-completes to ``ADSLNamespace`` methods,
and ``df.adam.onco.source(...)`` auto-completes to ``OncoNamespace``
methods.  No ``if TYPE_CHECKING`` stubs or protocol tricks are needed.
"""

from __future__ import annotations

from typing import Any, Self

import polars as pl


class SharedADaMVerbsMixin:
    """Base mixin providing the shared verbs and chaining infrastructure.

    Concrete namespace classes inherit from this mixin.  The ``_chain``
    and ``_materialise_then`` helpers use ``self.__class__`` so the returned
    instance stays the correct sub-type for continued method chaining.

    Required instance attribute
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~
    ``_lazy: pl.LazyFrame``  — set by ``__init__``.
    """

    _lazy: pl.LazyFrame

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def __init__(self, df: pl.DataFrame) -> None:
        self._lazy = df.lazy()

    # ------------------------------------------------------------------ #
    # Chaining infrastructure                                              #
    # ------------------------------------------------------------------ #

    def _chain(self, *exprs: pl.Expr) -> Self:
        """Append expressions to the lazy plan; return a *new* namespace."""
        new = object.__new__(self.__class__)
        new._lazy = self._lazy.with_columns(list(exprs))
        return new

    def _materialise_then(self, df: pl.DataFrame) -> Self:
        """Return a fresh namespace wrapping *df* as a new lazy plan."""
        new = object.__new__(self.__class__)
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
        from ..sdtm.utils import parse_expression

        expr = (
            expression
            if isinstance(expression, pl.Expr)
            else parse_expression(str(expression))
        )
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
            expr = pl.col(source).replace_strict(
                recode_map, default=default_expr, return_dtype=pl.String
            ).alias(target)
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
        from ..sdtm.utils import parse_expression

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
        from ..sdtm.utils import parse_expression

        df = self.to_frame()
        filter_expr = (
            where if isinstance(where, pl.Expr) else parse_expression(str(where))
        )
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
        groups: list[str] | None = None,
    ) -> Self:
        """Sequential 1-based record number within each group.

        Preserves row order.  Materialises the current pipeline before
        assigning sequence numbers.

        Args:
            target: Name of the output sequence column (default ``"ASEQ"``).
            groups: Partition columns (default ``["USUBJID"]``).

        Returns:
            Self: A fresh namespace with the sequence column added.

        Examples:
            Add a per-subject sequence number::

                adae = (
                    ae_df.adam.occds
                    .seq("ASEQ", groups=["USUBJID"])
                    .to_frame()
                )
        """
        grps = groups or ["USUBJID"]
        df = self.to_frame()
        df = df.with_columns(
            (pl.int_range(pl.len()).over(grps) + 1).cast(pl.Int64).alias(target)
        )
        return self._materialise_then(df)
