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
        """Materialise the accumulated pipeline into a Polars DataFrame."""
        return self._lazy.collect()

    # ------------------------------------------------------------------ #
    # Shared verbs                                                         #
    # ------------------------------------------------------------------ #

    def source(self, target: str, *, from_col: str | None = None) -> Self:
        """Copy *from_col* (or *target* itself) to *target*."""
        src = from_col if from_col is not None else target
        return self._chain(pl.col(src).alias(target))

    def derivation(self, target: str, *, expression: str | pl.Expr) -> Self:
        """Arbitrary Polars expression derivation."""
        from ..sdtm.utils import parse_expression

        expr = (
            expression
            if isinstance(expression, pl.Expr)
            else parse_expression(str(expression))
        )
        return self._chain(expr.alias(target))

    def assigned(self, target: str, *, value: Any) -> Self:
        """Set *target* to a constant *value* for every record."""
        return self._chain(pl.lit(value).alias(target))

    def recode(
        self,
        target: str,
        *,
        source: str,
        recode_map: dict[Any, Any],
        default: Any = None,
    ) -> Self:
        """Map values in *source* to recoded values; unmapped → *default*."""
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
        """Create *target* as a copy of *source* (variable renaming)."""
        return self._chain(pl.col(source).alias(target))

    def condderivation(
        self,
        target: str,
        *,
        conditions: list[dict[str, Any]],
        else_value: Any = None,
    ) -> Self:
        """Multi-branch conditional derivation (when/then/otherwise chain)."""
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
        """Filter records by *where* expression (materialises first)."""
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
        """
        Left-join ADSL columns onto the current dataset.

        Materialises the pipeline, left-joins *adsl* (optionally restricted to
        *keep_cols* + *by* key columns), and returns a fresh namespace.

        Parameters
        ----------
        adsl:
            The ADSL ``pl.DataFrame`` to merge in.
        by:
            Key column(s) for the join (default ``["USUBJID"]``).
        keep_cols:
            Subset of ADSL columns to bring in (excluding *by* keys, which are
            always included).  When ``None``, all ADSL columns are merged.

        Example::

            .merge_adsl(adsl_df, keep_cols=["TRTSDT", "TRTEDT", "TRT01P"])
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
        """
        Sequential 1-based record number within each group, preserving row order.

        Materialises the current pipeline before assigning sequence numbers.

        Example::

            .seq("ASEQ", groups=["USUBJID"])
            .seq("PCSEQ", groups=["USUBJID"])
        """
        grps = groups or ["USUBJID"]
        df = self.to_frame()
        df = df.with_columns(
            (pl.int_range(pl.len()).over(grps) + 1).cast(pl.Int64).alias(target)
        )
        return self._materialise_then(df)
