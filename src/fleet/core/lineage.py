"""Variable-level lineage capture for SDTM/ADaM namespace verbs.

Each verb call appends to the namespace's ``_lineage`` list a record of
*which verb produced which output column from which source columns*.
The list survives ``copy.copy()`` of the namespace so it accumulates
across the entire pipeline chain.

The capture path is intentionally lightweight: a single ``inspect.stack``
lookup per call to retrieve the verb name, plus Polars expression
metadata for column names.  No verb code needs to be modified.

Examples:
    Inspect lineage after a pipeline::

        from fleet.core.lineage import lineage_of

        result = (
            vs_df.adam
            .source("USUBJID")
            .baseline("BASE", aval="AVAL", baseline_flag="ABLFL")
        )
        for entry in lineage_of(result):
            print(entry.name, entry.verb, entry.sources, entry.method)
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

import polars as pl

if TYPE_CHECKING:
    from fleet.core.dag import VariableNode


def _expr_output_name(expr: pl.Expr) -> str | None:
    """Return the alias / output column name of *expr*, or ``None``."""
    try:
        return expr.meta.output_name()
    except Exception:
        return None


def _expr_sources(expr: pl.Expr) -> list[str]:
    """Return the deduplicated list of source columns referenced by *expr*."""
    try:
        return list(dict.fromkeys(expr.meta.root_names()))
    except Exception:
        return []


def _resolve_method_path(owner: object, verb: str) -> str:
    """Resolve ``ClassName.verb`` to its dotted import path.

    Walks the MRO so verbs defined on a mixin (e.g. ``SharedADaMVerbsMixin``)
    are reported with their *defining* module — matching how mkdocstrings
    anchors them in the rendered docs.
    """
    cls = owner.__class__
    for klass in cls.__mro__:
        if verb in klass.__dict__:
            return f"{klass.__module__}.{klass.__qualname__}.{verb}"
    return f"{cls.__module__}.{cls.__qualname__}.{verb}"


def record_lineage(owner: Any, exprs: tuple[pl.Expr, ...]) -> None:
    """Append one ``VariableNode`` per expression to ``owner._lineage``.

    Called from ``_chain()`` of SDTM/ADaM namespaces.  The verb name is
    recovered from the call stack (the function that called ``_chain``).

    Args:
        owner: The namespace instance whose lineage is being extended.
        exprs: The Polars expressions about to be applied via
            ``with_columns``.
    """
    # Lazy import to avoid circulars at module import time.
    from fleet.core.dag import VariableNode

    # stack: [0] this function, [1] _chain, [2] the verb method.
    try:
        verb = inspect.stack()[2].function
    except Exception:
        verb = "unknown"
    if verb.startswith("_"):
        # Internal helpers (e.g. _materialise_then) — not user-facing verbs.
        verb = verb.lstrip("_")

    method_path = _resolve_method_path(owner, verb)
    domain: str | None = getattr(owner, "_domain", None)
    lineage: list[VariableNode] = list(getattr(owner, "_lineage", []))
    for expr in exprs:
        name = _expr_output_name(expr)
        if not name:
            continue
        lineage.append(
            VariableNode(
                name=name,
                verb=verb,
                sources=_expr_sources(expr),
                method=method_path,
                domain=domain,
            )
        )
    owner._lineage = lineage


def lineage_of(namespace: Any) -> list[VariableNode]:
    """Return the accumulated lineage of *namespace* (empty list if none)."""
    return list(getattr(namespace, "_lineage", []))
