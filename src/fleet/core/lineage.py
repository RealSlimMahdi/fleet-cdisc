"""Variable-level lineage capture for SDTM/ADaM namespace verbs.

Each verb call appends to the namespace's ``_lineage`` list a record of
*which verb produced which output column from which source columns*.
The list survives ``copy.copy()`` of the namespace so it accumulates
across the entire pipeline chain.

The capture path is intentionally lightweight: a single frame walk per
call to retrieve the verb name and its keyword arguments, plus Polars
expression metadata for column names.  No verb code needs to be
modified.

Re-derivation policy (documented contract): ``_lineage`` keeps the
**full history** — a target derived twice has two entries in pipeline
order (``trail()`` shows both).  Consumers that need the current state
of the frame (``to_spec_yaml()``, ``PipelineDAG.inject_lineage``) apply
last-write-wins via :func:`latest_lineage_of`.

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
import sys
from typing import TYPE_CHECKING, Any

import polars as pl

if TYPE_CHECKING:
    from fleet.core.dag import VariableNode


class _Unserialisable:
    """Sentinel marking a captured verb kwarg that cannot go into YAML."""

    def __repr__(self) -> str:  # pragma: no cover — debugging aid
        return "<unserialisable>"


#: Placeholder stored in ``VariableNode.params`` for non-YAML-safe values
#: (Polars expressions, DataFrames, callables).  Its presence tells
#: ``to_spec_yaml()`` the derivation cannot be reproduced from the spec.
UNSERIALISABLE = _Unserialisable()

#: Maximum frames walked above ``_chain`` when locating the verb frame.
_MAX_FRAME_WALK = 6


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


def defining_method_path(cls: type, verb: str) -> str:
    """Return ``module.Class.verb`` of the class in the MRO of *cls* that defines *verb*.

    Lineage records this path in ``VariableNode.method``, and the Define-XML
    ``FormalExpression`` names the same one.

    Args:
        cls: The namespace class the verb runs on.
        verb: The method name.

    Returns:
        str: The dotted path of the defining class, or of *cls* when no
            class in the MRO defines *verb*.

    Examples:
        Name the method an ADaM pipeline runs for ``.duration()``::

            from fleet.adam.namespace import AdamNamespace
            from fleet.core.lineage import defining_method_path

            defining_method_path(AdamNamespace, "duration")
            # "fleet.core._verb_mixin.SharedVerbsMixin.duration"
    """
    for klass in cls.__mro__:
        if verb in klass.__dict__:
            return f"{klass.__module__}.{klass.__qualname__}.{verb}"
    return f"{cls.__module__}.{cls.__qualname__}.{verb}"


def _is_yaml_safe(value: Any) -> bool:
    """True when *value* survives a ``yaml.safe_dump`` round-trip losslessly."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, (list, tuple)):
        return all(_is_yaml_safe(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, (str, int, float, bool)) for k in value) and all(
            _is_yaml_safe(v) for v in value.values()
        )
    return False


def sanitise_params(params: dict[str, Any]) -> dict[str, Any]:
    """Normalise a captured kwargs dict for lineage storage.

    Drops ``None`` values (the verb default applies) and replaces
    non-YAML-safe values with the :data:`UNSERIALISABLE` sentinel so
    downstream consumers know the call cannot be reproduced from a spec.

    Args:
        params: Raw ``{kwarg: value}`` mapping from a verb call.

    Returns:
        dict: The sanitised copy.
    """
    out: dict[str, Any] = {}
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, tuple):
            value = list(value)
        out[key] = value if _is_yaml_safe(value) else UNSERIALISABLE
    return out


def _capture_verb_params(owner: Any, verb: str) -> dict[str, Any] | None:
    """Best-effort capture of the calling verb's keyword arguments.

    Walks up the stack from ``record_lineage``'s caller looking for a
    frame whose function name equals *verb* (verbs call ``_chain``
    either directly or through private helpers).  When found, the
    frame's locals are filtered to the verb's *signature* parameters
    whose current value differs from the declared default, then
    sanitised via :func:`sanitise_params`.

    This mirrors the existing stack-based verb-name fallback: it keeps
    every namespace verb untouched while still giving ``to_spec_yaml()``
    the kwargs it needs.  Verbs owned by the shared mixin pass
    ``params=`` explicitly and never reach this path.

    Returns:
        dict | None: Sanitised params, or ``None`` when the verb frame
            or its signature could not be resolved.
    """
    fn = getattr(type(owner), verb, None)
    if fn is None or not callable(fn):
        return None
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return None

    frame = None
    try:
        frame = sys._getframe(2)  # skip record_lineage → _chain
        for _ in range(_MAX_FRAME_WALK):
            if frame is None:
                return None
            if frame.f_code.co_name == verb:
                break
            frame = frame.f_back
        else:
            return None

        captured: dict[str, Any] = {}
        for name, param in signature.parameters.items():
            if name == "self" or param.kind in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            ):
                continue
            if name not in frame.f_locals:
                continue
            value = frame.f_locals[name]
            if param.default is not inspect.Parameter.empty:
                try:
                    if bool(value == param.default):
                        continue
                except Exception:
                    pass  # rich objects (pl.Expr, frames) — keep and sanitise
            captured[name] = value
        return sanitise_params(captured)
    except Exception:
        return None
    finally:
        del frame  # break the traceback reference cycle


def record_lineage(
    owner: Any,
    exprs: tuple[pl.Expr, ...],
    verb: str | None = None,
    params: dict[str, Any] | None = None,
) -> None:
    """Append one ``VariableNode`` per expression to ``owner._lineage``.

    Called from ``_chain()`` of SDTM/ADaM namespaces.  The verb name is
    passed explicitly by ``_chain()``; when omitted it is recovered from
    the call stack (the function that called ``_chain``).

    Args:
        owner: The namespace instance whose lineage is being extended.
        exprs: The Polars expressions about to be applied via
            ``with_columns``.
        verb: Explicit user-facing verb name.  Preferred over the stack
            fallback — it survives wrapping and misattribution.
        params: Verb keyword arguments to record (already keyed by the
            verb's kwarg names).  When omitted, a best-effort stack
            capture of the verb frame's non-default kwargs is attempted.
    """
    # Lazy import to avoid circulars at module import time.
    from fleet.core.dag import VariableNode

    if verb is None:
        # stack: [0] this function, [1] _chain, [2] the verb method.
        try:
            verb = inspect.stack()[2].function
        except Exception:
            verb = "unknown"
    if verb.startswith("_"):
        # Internal helpers (e.g. _materialise_then) — not user-facing verbs.
        verb = verb.lstrip("_")

    if params is None:
        params = _capture_verb_params(owner, verb)
    else:
        params = sanitise_params(params)

    method_path = defining_method_path(type(owner), verb)
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
                params=params,
            )
        )
    owner._lineage = lineage


def lineage_of(namespace: Any) -> list[VariableNode]:
    """Return the accumulated lineage of *namespace* (empty list if none).

    The full history is returned: a target derived more than once has
    one entry per derivation, in pipeline order.  Use
    :func:`latest_lineage_of` for the deduplicated current-state view.
    """
    return list(getattr(namespace, "_lineage", []))


def latest_lineage_of(namespace: Any) -> list[VariableNode]:
    """Return lineage deduplicated per target — last write wins.

    Order follows each target's *first* derivation (pipeline order);
    content comes from its *last* derivation, matching what the
    materialised frame actually contains.

    Args:
        namespace: A namespace instance carrying ``_lineage``.

    Returns:
        list[VariableNode]: One node per derived variable.
    """
    latest: dict[str, VariableNode] = {}
    for node in lineage_of(namespace):
        latest[node.name] = node  # dict preserves first-seen key order
    return list(latest.values())


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

    pin_dep = PinDependency(
        target_col=target_col,
        target_domain=getattr(owner, "_domain", None),
        verb=verb,
        source_domain=source_domain,
        source_cols=source_cols,
        join_key=join_key,
        relationship=relationship,
    )

    # Append to the separate pin lineage list
    pin_lineage: list[PinDependency] = list(getattr(owner, "_pin_lineage", []))
    pin_lineage.append(pin_dep)
    owner._pin_lineage = pin_lineage

    # Also populate pin_sources on the matching VariableNode in _lineage
    # so it's available immediately without needing inject_lineage()
    existing_lineage: list = list(getattr(owner, "_lineage", []))
    for vnode in reversed(existing_lineage):  # last-write-wins
        if vnode.name == target_col:
            vnode.pin_sources.append(pin_dep)
            break


def pin_lineage_of(namespace: Any) -> list:
    """Return the accumulated pin lineage of *namespace* (empty list if none)."""
    return list(getattr(namespace, "_pin_lineage", []))


def _append_lineage_nodes(ns: Any, drv: Any) -> Any:
    """Inject ``VariableNode`` entries for frame-level / param-level ``Derivation`` s.

    Called from ``_apply_derivation()`` after ``_materialise_then()``, because
    those code paths bypass ``_chain()`` and therefore miss ``record_lineage()``.
    The node's ``spec`` is set to an ``algorithm: derivation`` block whose
    ``callable:`` is the derivation's dotted path, so ``to_spec_yaml()`` round-trips it.

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
    spec_block = {"algorithm": "derivation", "callable": drv.dotted_path}
    for t in drv.targets:
        lineage.append(
            VariableNode(
                name=t,
                verb="derivation",
                sources=drv.sources,
                method=drv.dotted_path,
                domain=domain,
                spec=dict(spec_block),
            )
        )
    ns._lineage = lineage
    return ns


def append_verb_node(
    ns: Any, name: str, verb: str, sources: list[str], params: dict[str, Any]
) -> Any:
    """Record one ``VariableNode`` for a verb that bypasses ``_chain()``.

    Verbs that sort, join or materialise (``seq``, ``first_date``,
    ``count_events``) call this so that ``to_spec_yaml()`` sees their
    target: a spec-expressible call writes its block, any other call (an
    inline ``from_dataset=`` frame) writes a TODO stub with a warning.

    Args:
        ns: The namespace the verb returns.
        name: The target column.
        verb: The user-facing verb name.
        sources: Input column names.
        params: The verb keyword arguments, ``target`` included.

    Returns:
        The same namespace with ``_lineage`` extended in place.
    """
    from fleet.core.dag import VariableNode

    lineage: list[VariableNode] = list(getattr(ns, "_lineage", []))
    lineage.append(
        VariableNode(
            name=name,
            verb=verb,
            sources=list(dict.fromkeys(sources)),
            method=defining_method_path(type(ns), verb),
            domain=getattr(ns, "_domain", None),
            params=sanitise_params(params),
        )
    )
    ns._lineage = lineage
    return ns


#: Row verbs whose call a define.yaml ``row_steps:`` entry can hold (ADR-0034).
ROW_STEP_ALGORITHMS: frozenset[str] = frozenset({"whereclauses", "nodup"})


def record_row_step(ns: Any, verb: str, params: dict[str, Any]) -> Any:
    """Record a verb that adds or removes rows, for ``to_spec_yaml()``.

    The step is anchored ``after`` the variable last derived in the chain,
    so ``from_spec`` runs it at the same place (ADR-0034).  A call a
    define.yaml cannot hold (a ``pl.Expr`` filter, ``derive_param``) is
    recorded as ``algorithm: TODO`` so the frozen file fails until it is
    edited.

    Args:
        ns: The namespace the verb returns.
        verb: The user-facing verb name.
        params: The verb keyword arguments.

    Returns:
        The same namespace with ``_row_steps`` extended in place.
    """
    lineage = getattr(ns, "_lineage", [])
    clean = sanitise_params(params)
    if verb in ROW_STEP_ALGORITHMS and UNSERIALISABLE not in clean.values():
        step: dict[str, Any] = {"algorithm": verb, **clean}
    else:
        step = {"algorithm": "TODO", "verb": verb}
    step["after"] = lineage[-1].name if lineage else None
    ns._row_steps = [*getattr(ns, "_row_steps", []), step]
    return ns
