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


def record_pin_lineage(
    owner: Any,
    target_col: str,
    verb: str,
    source_domain: str,
    source_cols: list[str],
    join_key: list[str],
    relationship: str = "derivation",
) -> None:
    """Append a ``PinDependency`` to ``owner._pin_lineage``.

    Called from cross-domain verbs (e.g. ``study_day``, ``join_adsl``)
    after consuming a pinned domain, so every pin access is automatically
    traced.

    Args:
        owner: The namespace instance.
        target_col: Output column being derived.
        verb: Name of the consuming verb.
        source_domain: Pinned domain that was consulted.
        source_cols: Columns read from the pinned frame.
        join_key: Join key(s) used to align frames.
        relationship: Semantic tag — ``"derivation"``, ``"fk_check"``,
            or ``"carry_forward"``.
    """
    from fleet.core.dag import PinDependency

    pin_lineage: list[PinDependency] = list(getattr(owner, "_pin_lineage", []))
    pin_lineage.append(
        PinDependency(
            target_col=target_col,
            target_domain=getattr(owner, "_domain", None),
            verb=verb,
            source_domain=source_domain,
            source_cols=source_cols,
            join_key=join_key,
            relationship=relationship,
        )
    )
    owner._pin_lineage = pin_lineage


def pin_lineage_of(namespace: Any) -> list:
    """Return the accumulated pin lineage of *namespace* (empty list if none)."""
    return list(getattr(namespace, "_pin_lineage", []))


def _append_lineage_nodes(ns: Any, drv: Any) -> Any:
    """Inject ``VariableNode`` entries for frame-level / param-level ``Derivation`` s.

    Called from ``_apply_derivation()`` after ``_materialise_then()``, because
    those code paths bypass ``_chain()`` and therefore miss ``record_lineage()``.

    Args:
        ns:  The namespace instance (already materialised).
        drv: The :class:`~fleet.core.derivation.Derivation` whose ``targets``
             and ``sources`` are to be recorded.

    Returns:
        The same namespace instance with ``_lineage`` extended in place.
    """
    from fleet.core.dag import VariableNode

    lineage: list[VariableNode] = list(getattr(ns, "_lineage", []))
    domain: str | None = getattr(ns, "_domain", None)
    for t in drv.targets:
        lineage.append(
            VariableNode(
                name=t,
                verb="derivation",
                sources=drv.sources,
                method=drv.dotted_path,
                domain=domain,
            )
        )
    ns._lineage = lineage
    return ns
