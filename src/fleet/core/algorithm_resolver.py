"""Resolve Fleet algorithm names and dotted callable paths to docstrings.

Used by :class:`fleet.define_xml.spec_generator.DefineSpecGenerator` to
auto-populate Define-XML ``Description`` and ``MethodDef`` content from
the same Python docstrings developers write for verbs and study-specific
custom functions.

The resolver is intentionally read-only and has no side effects beyond
importing modules referenced by ``callable:`` paths.

Examples:
    Resolve a built-in SDTM verb::

        from fleet.core.algorithm_resolver import resolve_algorithm_docstring

        summary, dotted = resolve_algorithm_docstring("assign_ct")
        # spec algorithm ids resolve through the registry to their verb:
        # summary -> first sentence of SharedVerbsMixin.assign.__doc__
        # dotted  -> "fleet.core._verb_mixin.SharedVerbsMixin.assign"

    Resolve a study-specific callable::

        from fleet.core.algorithm_resolver import resolve_callable_docstring

        summary, dotted = resolve_callable_docstring(
            "mycompany.grading.ctcae_grade"
        )
"""

from __future__ import annotations

import importlib
import inspect
from typing import Any


def first_sentence(doc: str | None) -> str:
    """Return the first sentence of a docstring, stripped and dedented.

    Args:
        doc: A raw ``__doc__`` string (or ``None``).

    Returns:
        str: The first sentence, or ``""`` when the docstring is empty.

    Examples:
        Summarise a verb for a catalogue listing::

            from fleet.core.algorithm_resolver import first_sentence

            summary = first_sentence(SDTMNamespace.assign.__doc__)
    """
    if not doc:
        return ""
    text = inspect.cleandoc(doc).strip()
    if not text:
        return ""
    # Take everything up to the first blank line, then split on first period.
    head = text.split("\n\n", 1)[0].strip().replace("\n", " ")
    if "." in head:
        head = head.split(".", 1)[0].strip() + "."
    return head


#: Backward-compatible internal alias.
_first_sentence = first_sentence


def _candidate_namespaces() -> list[type]:
    """Return the verb-bearing namespace classes, in lookup priority order.

    Imports are local so that this module stays cheap to import and so that
    optional namespaces (PK, oncology) do not break resolution if removed.
    """
    classes: list[type] = []

    def _try(module: str, attr: str) -> None:
        try:
            mod = importlib.import_module(module)
        except Exception:
            return
        cls = getattr(mod, attr, None)
        if cls is not None:
            classes.append(cls)

    _try("fleet.sdtm.namespace", "SDTMNamespace")
    _try("fleet.adam.namespace", "AdamNamespace")
    _try("fleet.adam._mixins", "SharedADaMVerbsMixin")
    _try("fleet.adam.adsl_namespace", "ADSLNamespace")
    _try("fleet.adam.occds_namespace", "OCCDSNamespace")
    _try("fleet.adam.pk_namespace", "PKNamespace")
    _try("fleet.sdtm._tdd_mixin", "TrialDesignMixin")
    return classes


def resolve_algorithm_docstring(
    algorithm: str,
) -> tuple[str, str] | tuple[None, None]:
    """Resolve a Fleet algorithm name to its docstring summary and dotted path.

    Searches the known SDTM/ADaM verb namespace classes for a method whose
    name equals *algorithm*.  The first match wins (SDTM is searched
    before ADaM mixins).

    Args:
        algorithm: Algorithm string from a ``define.yaml`` derivation
            block (e.g. ``"assign_ct"`` or ``"baseline"``).

    Returns:
        Tuple of ``(summary, dotted_path)`` if a match is found, or
        ``(None, None)`` otherwise.  ``summary`` is the first sentence of
        the verb docstring; ``dotted_path`` is the fully-qualified
        ``module.Class.method`` path suitable for use as a Define-XML
        ``MethodDef`` reference.
    """
    if not algorithm:
        return (None, None)

    # Resolve through the spec registry first: algorithm names are not
    # always method names (e.g. study_day executes via duration()).
    method_names = [algorithm]
    try:
        from fleet.core.spec_registry import get_algorithm

        for standard in ("sdtm", "adam"):
            algo = get_algorithm(standard, algorithm)
            if algo is not None and algo.verb not in method_names:
                method_names.append(algo.verb)
    except Exception:  # pragma: no cover — resolver must never break generation
        pass

    for name in method_names:
        for cls in _candidate_namespaces():
            method = getattr(cls, name, None)
            if method is None or not callable(method):
                continue
            summary = _first_sentence(method.__doc__)
            dotted = f"{cls.__module__}.{cls.__qualname__}.{name}"
            return (summary, dotted)
    return (None, None)


def resolve_callable_docstring(
    dotted: str,
) -> tuple[str, str] | tuple[None, None]:
    """Resolve a dotted Python path to its docstring summary.

    Used for study-specific custom functions referenced from
    ``define.yaml`` via the optional ``callable:`` field.

    Args:
        dotted: Fully-qualified Python path
            (e.g. ``"mycompany.grading.ctcae_grade"``).

    Returns:
        Tuple of ``(summary, dotted)`` if the import succeeds, or
        ``(None, None)`` otherwise.  Failures are silent so that
        Define-XML generation never breaks because a sponsor extension
        package is missing from the build environment.
    """
    if not dotted or "." not in dotted:
        return (None, None)
    module_path, _, attr = dotted.rpartition(".")
    try:
        mod = importlib.import_module(module_path)
    except Exception:
        return (None, None)
    obj: Any = getattr(mod, attr, None)
    if obj is None:
        return (None, None)
    
    doc_owner: Any = obj

    # @derivation-decorated objects expose the original function at .fn.
    fn = getattr(obj, "fn", None)
    if callable(fn):
        doc_owner = fn

    summary = _first_sentence(getattr(doc_owner, "__doc__", None))
    return (summary, dotted)
