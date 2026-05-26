"""Shared callable resolver for spec-driven pipelines."""

from __future__ import annotations

from typing import Any


def resolve_callable(ref: str) -> Any:
    """Resolve a callable reference by name or dotted import path.

    Discovery order:

    1. Look up *ref* in the Fleet transform registry.
    2. If *ref* contains a dot, treat it as a dotted import path.
    3. Raise ``ValueError`` if neither lookup succeeds.

    Args:
        ref: Registry name or dotted import path.

    Returns:
        The callable or Derivation object.

    Raises:
        ValueError: If *ref* cannot be resolved.
    """
    from fleet.adam.transforms import get_transform

    try:
        return get_transform(ref)
    except KeyError:
        pass

    if "." in ref:
        import importlib

        module_path, _, attr = ref.rpartition(".")
        mod = importlib.import_module(module_path)
        return getattr(mod, attr)

    raise ValueError(
        f"Callable '{ref}' is not registered and is not a dotted import path. "
        "Register it with @derivation or import the derivations module before from_spec()."
    )
