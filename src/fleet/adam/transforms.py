"""
Transform registry for custom ADaM derivations.

Statistical programmers register named transforms so that:

1. **Inline pipelines** can reference them by name or pass them directly.
2. **YAML specs** can invoke them via ``algorithm: transform`` / ``callable: "<name>"``.

Usage
-----
Register with the decorator::

    from fleet.adam.transforms import register_transform

    @register_transform("derive_agegr1")
    def derive_agegr1(df: pl.DataFrame) -> pl.DataFrame:
        \"\"\"Classify AGE into age group bands.\"\"\"
        return df.with_columns(
            pl.when(pl.col("AGE") < 65).then(pl.lit("<65"))
              .otherwise(pl.lit(">=65"))
              .alias("AGEGR1")
        )

Or register imperatively::

    register_transform("derive_agegr1", derive_agegr1)

Then use in a pipeline::

    adsl = (
        dm.adam
        .transform("derive_agegr1")      # by registered name
        .transform(my_other_fn)           # or pass a callable directly
        .to_frame()
    )

Or in a YAML spec::

    - name: AGEGR1
      label: Pooled Age Group 1
      derivation:
        algorithm: derivation
        callable: derive_agegr1

Contract
--------
Every transform function must satisfy:

- **Signature**: ``(pl.DataFrame) -> pl.DataFrame``
- **Pure**: no hidden side-effects; the returned frame *is* the result.
- **Additive**: add or modify columns, but do not drop existing ones
  unless that is the documented intent.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from typing import Any, overload

import polars as pl

from fleet.core.exceptions import VerbUsageError

# Module-level registry: name → callable or Derivation object.
# Values may be plain callables (df → df) or ``Derivation`` instances created
# by the ``@derivation`` decorator.  Both are callable, so existing call-sites
# that do ``fn(df)`` continue to work for frame/param kinds; the ADaM namespace
# detects ``Derivation`` objects via ``hasattr(obj, "kind")`` and dispatches
# appropriately for column-kind derivations (which take no df argument).
_TRANSFORMS: dict[str, Callable | Any] = {}


@overload
def register_transform(
    name: str,
) -> Callable[
    [Callable[[pl.DataFrame], pl.DataFrame]],
    Callable[[pl.DataFrame], pl.DataFrame],
]: ...


@overload
def register_transform(
    name: str,
    fn: Callable[[pl.DataFrame], pl.DataFrame],
) -> Callable[[pl.DataFrame], pl.DataFrame]: ...


def register_transform(name, fn=None):
    """
    Register a named transform function.

    Can be used as a **decorator** or called **imperatively**::

        # Decorator form
        @register_transform("derive_agegr1")
        def derive_agegr1(df):
            ...

        # Imperative form
        register_transform("derive_agegr1", derive_agegr1)

    Parameters
    ----------
    name : str
        Registry key.  Referenced in YAML specs via ``callable: "<name>"``.
    fn : callable, optional
        The transform function.  Omit when using as a decorator.

    Returns
    -------
    The original function (unmodified), so it remains usable outside the
    registry.
    """
    if fn is not None:
        # Imperative form: register_transform("name", fn)
        if not callable(fn):
            raise VerbUsageError(f"Expected a callable, got {type(fn).__name__}")
        _warn_on_duplicate(name, fn)
        _TRANSFORMS[name] = fn
        return fn

    # Decorator form: @register_transform("name")
    def _decorator(
        func: Callable[[pl.DataFrame], pl.DataFrame],
    ) -> Callable[[pl.DataFrame], pl.DataFrame]:
        _warn_on_duplicate(name, func)
        _TRANSFORMS[name] = func
        return func

    return _decorator


def _warn_on_duplicate(name: str, fn: Callable | Any) -> None:
    """Warn when *name* is already registered with a different callable.

    Silent overwrites let two studies' derivations (e.g. two ``AGEGR1``
    implementations) shadow each other depending on import order — the
    warning makes the collision visible without breaking re-imports of
    the same function.
    """
    existing = _TRANSFORMS.get(name)
    if existing is not None and existing is not fn:
        warnings.warn(
            f"Transform '{name}' is already registered "
            f"({getattr(existing, '__module__', '?')}.{getattr(existing, '__qualname__', '?')}); "
            f"overwriting with {getattr(fn, '__module__', '?')}.{getattr(fn, '__qualname__', '?')}.",
            stacklevel=3,
        )


def get_transform(name: str) -> Callable[[pl.DataFrame], pl.DataFrame]:
    """
    Retrieve a registered transform by name.

    Raises
    ------
    KeyError
        If *name* has not been registered.
    """
    try:
        return _TRANSFORMS[name]
    except KeyError:
        available = ", ".join(sorted(_TRANSFORMS)) or "(none)"
        raise KeyError(
            f"Transform '{name}' is not registered. "
            f"Available: {available}. "
            f"Register it with @register_transform('{name}')."
        ) from None


def list_transforms() -> list[str]:
    """Return the names of all registered transforms (sorted)."""
    return sorted(_TRANSFORMS)


def clear_transforms() -> None:
    """Remove all registered transforms. Useful in test teardown."""
    _TRANSFORMS.clear()
