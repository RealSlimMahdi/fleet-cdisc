"""Derivation protocol — dataclass and ``@derivation`` decorator.

Study-specific derivation logic lives in::

    specs/<study>/adam/derivations/
        __init__.py
        AGEGR1.py
        BMI.py

Each file defines one (or more) ``@derivation``-decorated functions.  On
import the decorator wraps the function in a :class:`Derivation` dataclass
and auto-registers it in the transform registry so it can be referenced by
name from ``from_spec()`` YAML files.

Examples:
    Column-kind derivation (zero-arg, returns ``pl.Expr``)::

        from fleet.core.derivation import derivation
        import polars as pl

        @derivation
        def AGEGR1() -> pl.Expr:
            \"\"\"Classify AGE into two pooled age groups.\"\"\"
            return (
                pl.when(pl.col("AGE") < 65)
                .then(pl.lit("<65 yrs"))
                .otherwise(pl.lit(">=65 yrs"))
                .alias("AGEGR1")
            )

    Frame-kind derivation (receives upstream DataFrame)::

        @derivation(targets=["SAFFL", "ITTFL"])
        def add_pop_flags(df: pl.DataFrame) -> pl.DataFrame:
            \"\"\"Add SAFFL and ITTFL population flags.\"\"\"
            return df.with_columns(
                pl.lit("Y").alias("SAFFL"),
                pl.lit("Y").alias("ITTFL"),
            )

    Param-kind derivation (by-group reshape)::

        @derivation(
            by=["USUBJID", "ADT"],
            set_values_to={"PARAMCD": "BMI", "PARAM": "Body Mass Index"},
        )
        def BMI(df: pl.DataFrame) -> pl.DataFrame:
            \"\"\"Compute BMI per subject visit.\"\"\"
            return df.with_columns(
                (pl.col("WEIGHT") / (pl.col("HEIGHT") / 100) ** 2).alias("AVAL")
            )

    Use in a pipeline::

        from specs.cdiscpilot01.adam.derivations import AGEGR1, add_pop_flags

        adsl = (
            dm.adam.adsl
            .derivation(AGEGR1)
            .derivation(add_pop_flags)
            .to_frame()
        )
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import polars as pl


@dataclass
class Derivation:
    """A registered custom derivation: callable + rich lineage metadata.

    Created by the :func:`derivation` decorator.  Instances are callable —
    invoking them dispatches to the underlying function according to ``kind``.

    Attributes:
        fn:            The wrapped callable.
        name:          Function name (used as registry key).
        kind:          Dispatch strategy: ``"column"``, ``"frame"``, or
                       ``"param"``.
        targets:       Output column names produced by this derivation.
        sources:       Input column names consumed (populated automatically
                       for ``kind="column"``).
        by_vars:       By-group variables for ``kind="param"`` derivations.
        set_values_to: Constant column assignments for ``kind="param"``
                       (e.g. ``{"PARAMCD": "BMI"}``).
        dotted_path:   Fully qualified import path for Define-XML MethodDef
                       (e.g. ``"specs.cdiscpilot01.adam.derivations.AGEGR1"``).
    """

    fn: Callable
    name: str
    kind: Literal["column", "frame", "param"]
    targets: list[str]
    sources: list[str]
    by_vars: list[str] | None
    set_values_to: dict[str, Any] | None
    dotted_path: str

    def __call__(self, df: pl.DataFrame | None = None) -> pl.Expr | pl.DataFrame:
        """Invoke the wrapped function.

        For ``kind="column"`` the function takes no arguments and returns a
        ``pl.Expr``.  For ``kind="frame"`` and ``kind="param"`` the function
        receives the upstream DataFrame and returns a ``pl.DataFrame``.

        Args:
            df: Upstream DataFrame; required for frame/param derivations,
                ignored for column derivations.

        Returns:
            A ``pl.Expr`` (column kind) or ``pl.DataFrame`` (frame/param
            kind).
        """
        if self.kind == "column":
            return self.fn()
        return self.fn(df)


def _infer_kind(
    fn: Callable,
    *,
    by: list[str] | None,
    set_values_to: dict[str, Any] | None,
) -> Literal["column", "frame", "param"]:
    """Infer ``kind`` from function signature and decorator keyword args.

    Priority:
    1. ``by`` or ``set_values_to`` present → ``"param"``
    2. Return annotation is ``pl.Expr`` → ``"column"``
    3. Return annotation is ``pl.DataFrame`` → ``"frame"``
    4. No parameters on ``fn`` → ``"column"``
    5. Otherwise → ``"frame"``

    Args:
        fn:            Function being decorated.
        by:            ``by=`` argument from decorator.
        set_values_to: ``set_values_to=`` argument from decorator.

    Returns:
        Inferred kind string.
    """
    if by is not None or set_values_to is not None:
        return "param"

    try:
        hints = typing.get_type_hints(fn)
        ret = hints.get("return")
        if ret is pl.Expr:
            return "column"
        if ret is pl.DataFrame:
            return "frame"
    except Exception:
        pass

    sig = inspect.signature(fn)
    if not sig.parameters:
        return "column"
    return "frame"


def _build_derivation(
    fn: Callable,
    *,
    targets: list[str] | None = None,
    sources: list[str] | None = None,
    by: list[str] | None = None,
    set_values_to: dict[str, Any] | None = None,
) -> Derivation:
    """Wrap *fn* in a :class:`Derivation` and register it in the transform registry.

    Args:
        fn:            Function to wrap.
        targets:       Explicit output column list (inferred for column kind).
        sources:       Explicit input column list (inferred for column kind).
        by:            By-group variables for param kind.
        set_values_to: Constant assignments for param kind.

    Returns:
        The constructed :class:`Derivation` instance (also auto-registered).
    """
    # Deferred import to avoid circular dependency at module load time.
    from fleet.adam.transforms import register_transform

    kind = _infer_kind(fn, by=by, set_values_to=set_values_to)
    dotted_path = f"{fn.__module__}.{fn.__qualname__}"
    name = fn.__name__

    _targets: list[str]
    _sources: list[str]

    if kind == "column":
        # Eagerly invoke to extract expression metadata.
        try:
            expr: pl.Expr = fn()
            if targets is None:
                try:
                    _targets = [expr.meta.output_name()]
                except Exception:
                    _targets = [name]
            else:
                _targets = list(targets)
            if sources is None:
                try:
                    _sources = list(dict.fromkeys(expr.meta.root_names()))
                except Exception:
                    _sources = []
            else:
                _sources = list(sources)
        except Exception:
            _targets = list(targets) if targets is not None else [name]
            _sources = list(sources) if sources is not None else []
    else:
        _targets = list(targets) if targets is not None else []
        _sources = list(sources) if sources is not None else []

    drv = Derivation(
        fn=fn,
        name=name,
        kind=kind,
        targets=_targets,
        sources=_sources,
        by_vars=by,
        set_values_to=set_values_to,
        dotted_path=dotted_path,
    )

    register_transform(name, drv)
    return drv


def derivation(
    fn: Callable | None = None,
    *,
    targets: list[str] | None = None,
    sources: list[str] | None = None,
    by: list[str] | None = None,
    set_values_to: dict[str, Any] | None = None,
) -> Derivation | Callable[[Callable], Derivation]:
    """Decorator that wraps a function as a typed :class:`Derivation` object.

    Supports both **bare** and **parameterised** forms.

    Bare form (``kind`` inferred from return annotation)::

        @derivation
        def AGEGR1() -> pl.Expr:
            return pl.when(pl.col("AGE") < 65).then(pl.lit("<65 yrs")).otherwise(pl.lit(">=65 yrs")).alias("AGEGR1")

    Parameterised form::

        @derivation(targets=["SAFFL", "ITTFL"])
        def add_pop_flags(df: pl.DataFrame) -> pl.DataFrame: ...

        @derivation(by=["USUBJID"], set_values_to={"PARAMCD": "BMI"})
        def BMI(df: pl.DataFrame) -> pl.DataFrame: ...

    Kind inference rules:

    +-------------------------------------------------------+-----------+
    | Condition                                             | Kind      |
    +=======================================================+===========+
    | ``by=`` or ``set_values_to=`` supplied                | ``param`` |
    +-------------------------------------------------------+-----------+
    | Return annotation is ``pl.Expr``                      | ``column``|
    +-------------------------------------------------------+-----------+
    | Return annotation is ``pl.DataFrame``                 | ``frame`` |
    +-------------------------------------------------------+-----------+
    | No parameters on the function                         | ``column``|
    +-------------------------------------------------------+-----------+
    | Otherwise                                             | ``frame`` |
    +-------------------------------------------------------+-----------+

    After decoration the function name is **auto-registered** in the Fleet
    transform registry, making it referenceable by name in YAML specs.

    Args:
        fn:            The function to decorate (bare form only; ``None`` in
                       parameterised form).
        targets:       Explicit list of output column names.  Inferred
                       automatically for ``kind="column"`` derivations.
        sources:       Explicit list of input column names.  Inferred
                       automatically for ``kind="column"`` derivations.
        by:            By-group variable list; forces ``kind="param"``.
        set_values_to: Constant column assignments; forces ``kind="param"``.

    Returns:
        A :class:`Derivation` object (bare form) or a decorator that returns
        one (parameterised form).
    """
    if fn is not None:
        # Bare form: @derivation applied directly to the function.
        return _build_derivation(
            fn,
            targets=targets,
            sources=sources,
            by=by,
            set_values_to=set_values_to,
        )

    # Parameterised form: @derivation(...) — return a decorator.
    def _decorator(func: Callable) -> Derivation:
        return _build_derivation(
            func,
            targets=targets,
            sources=sources,
            by=by,
            set_values_to=set_values_to,
        )

    return _decorator
