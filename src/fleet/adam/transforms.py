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
        algorithm: transform
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

from typing import Callable, overload

import polars as pl


# Module-level registry: name → callable
_TRANSFORMS: dict[str, Callable[[pl.DataFrame], pl.DataFrame]] = {}


@overload
def register_transform(
    name: str,
) -> Callable[
    [Callable[[pl.DataFrame], pl.DataFrame]],
    Callable[[pl.DataFrame], pl.DataFrame],
]:
    ...


@overload
def register_transform(
    name: str,
    fn: Callable[[pl.DataFrame], pl.DataFrame],
) -> Callable[[pl.DataFrame], pl.DataFrame]:
    ...


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
            raise TypeError(f"Expected a callable, got {type(fn).__name__}")
        _TRANSFORMS[name] = fn
        return fn

    # Decorator form: @register_transform("name")
    def _decorator(
        func: Callable[[pl.DataFrame], pl.DataFrame],
    ) -> Callable[[pl.DataFrame], pl.DataFrame]:
        _TRANSFORMS[name] = func
        return func

    return _decorator


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
