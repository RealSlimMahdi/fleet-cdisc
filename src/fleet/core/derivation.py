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

    A new parameter row (for example BMI from WEIGHT and HEIGHT) is not a
    derivation: use the tested ``.adam.derive_param()`` verb.

    Use in a pipeline::

        from examples.cdiscpilot01.adam.derivations import AGEGR1, add_pop_flags

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
        kind:          Dispatch strategy: ``"column"`` or ``"frame"``.
        targets:       Output column names produced by this derivation.
                       For ``kind="column"`` it is the function name, unless
                       the expression has an explicit ``.alias()``.
        sources:       Input column names consumed (populated automatically
                       for ``kind="column"``).
        dotted_path:   Fully qualified import path for Define-XML MethodDef
                       (e.g. ``"examples.cdiscpilot01.adam.derivations.AGEGR1"``).
    """

    fn: Callable
    name: str
    kind: Literal["column", "frame"]
    targets: list[str]
    sources: list[str]
    dotted_path: str

    def __call__(self, df: pl.DataFrame | None = None) -> pl.Expr | pl.DataFrame:
        """Invoke the wrapped function.

        For ``kind="column"`` the function takes no arguments and returns a
        ``pl.Expr`` named as the target.  For ``kind="frame"`` the function
        receives the upstream DataFrame and returns a ``pl.DataFrame``.

        Args:
            df: Upstream DataFrame; required for frame derivations,
                ignored for column derivations.

        Returns:
            A ``pl.Expr`` (column kind) or ``pl.DataFrame`` (frame kind).
        """
        if self.kind == "column":
            expr: pl.Expr = self.fn()
            return expr if _has_alias(expr) else expr.alias(self.targets[0])
        return self.fn(df)


def _has_alias(expr: pl.Expr) -> bool:
    """True when *expr* ends with an explicit ``.alias()`` or ``.name`` call."""
    try:
        return not expr.meta.undo_aliases().meta.eq(expr)
    except Exception:
        return False


def _infer_kind(fn: Callable) -> Literal["column", "frame"]:
    """Infer ``kind`` from the function signature.

    Priority:
    1. Return annotation is ``pl.Expr`` → ``"column"``
    2. Return annotation is ``pl.DataFrame`` → ``"frame"``
    3. No parameters on ``fn`` → ``"column"``
    4. Otherwise → ``"frame"``

    Args:
        fn: Function being decorated.

    Returns:
        Inferred kind string.
    """
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
) -> Derivation:
    """Wrap *fn* in a :class:`Derivation` and register it in the transform registry.

    Args:
        fn:            Function to wrap.
        targets:       Explicit output column list (inferred for column kind).
        sources:       Explicit input column list (inferred for column kind).

    Returns:
        The constructed :class:`Derivation` instance (also auto-registered).
    """
    # Deferred import to avoid circular dependency at module load time.
    from fleet.adam.transforms import register_transform

    kind = _infer_kind(fn)
    dotted_path = f"{fn.__module__}.{fn.__qualname__}"
    name = fn.__name__

    _targets: list[str]
    _sources: list[str]

    if kind == "column":
        # Eagerly invoke to extract expression metadata.
        try:
            expr: pl.Expr = fn()
            if targets is None:
                # The function name is the target, as the bare spec form
                # says; an explicit alias wins.
                _targets = [expr.meta.output_name() if _has_alias(expr) else name]
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
        dotted_path=dotted_path,
    )

    register_transform(name, drv)
    return drv


def derivation(
    fn: Callable | None = None,
    *,
    targets: list[str] | None = None,
    sources: list[str] | None = None,
    **removed: Any,
) -> Derivation | Callable[[Callable], Derivation]:
    """Decorator that wraps a function as a typed :class:`Derivation` object.

    Supports both **bare** and **parameterised** forms.

    Bare form (``kind`` inferred from return annotation)::

        @derivation
        def AGEGR1() -> pl.Expr:
            return pl.when(pl.col("AGE") < 65).then(pl.lit("<65 yrs")).otherwise(pl.lit(">=65 yrs"))

    A column derivation writes to the column named as the function
    (``AGEGR1`` above).  An explicit ``.alias()`` on the expression wins.

    Parameterised form::

        @derivation(targets=["SAFFL", "ITTFL"])
        def add_pop_flags(df: pl.DataFrame) -> pl.DataFrame: ...

    Kind inference rules:

    +-------------------------------------------------------+-----------+
    | Condition                                             | Kind      |
    +=======================================================+===========+
    | Return annotation is ``pl.Expr``                      | ``column``|
    +-------------------------------------------------------+-----------+
    | Return annotation is ``pl.DataFrame``                 | ``frame`` |
    +-------------------------------------------------------+-----------+
    | No parameters on the function                         | ``column``|
    +-------------------------------------------------------+-----------+
    | Otherwise                                             | ``frame`` |
    +-------------------------------------------------------+-----------+

    A new parameter row (``PARAMCD = "BMI"``) is not a derivation: use
    ``.adam.derive_param()``.

    After decoration the function name is **auto-registered** in the Fleet
    transform registry, making it referenceable by name in YAML specs.

    Args:
        fn:            The function to decorate (bare form only; ``None`` in
                       parameterised form).
        targets:       Explicit list of output column names.  Inferred
                       automatically for ``kind="column"`` derivations.
        sources:       Explicit list of input column names.  Inferred
                       automatically for ``kind="column"`` derivations.
        **removed:     ``by=`` and ``set_values_to=`` are refused.

    Returns:
        A :class:`Derivation` object (bare form) or a decorator that returns
        one (parameterised form).

    Raises:
        VerbUsageError: When ``by=`` or ``set_values_to=`` is given: they
            appended no row and overwrote AVAL.  Use ``.adam.derive_param()``.
    """
    if removed:
        from fleet.core.exceptions import VerbUsageError

        names = ", ".join(f"{k}=" for k in removed)
        if set(removed) <= {"by", "set_values_to"}:
            raise VerbUsageError(
                f"@derivation does not take {names}: it appended no parameter row and "
                "overwrote AVAL on the input records. Use .adam.derive_param(...) to add "
                "a parameter row such as PARAMCD BMI."
            )
        raise TypeError(f"derivation() got unexpected keyword argument(s): {names}")

    if fn is not None:
        # Bare form: @derivation applied directly to the function.
        return _build_derivation(fn, targets=targets, sources=sources)

    # Parameterised form: @derivation(...) — return a decorator.
    def _decorator(func: Callable) -> Derivation:
        return _build_derivation(func, targets=targets, sources=sources)

    return _decorator
