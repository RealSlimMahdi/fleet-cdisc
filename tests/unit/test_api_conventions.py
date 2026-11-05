"""Machine-enforced API shape (CONTRIBUTING.md § "API Shape & Conventions").

The written rule: verbs are ``.verb(target, *, keyword_args)`` — keyword-only
after the positional target(s).  This module sweeps the public method surface
of every namespace class and fails when a method accepts more positional
parameters than its allowance (default: 1, the target).

Existing multi-positional methods are grandfathered in
``_POSITIONAL_ALLOWANCE`` with a stated reason — adding a NEW verb with an
irregular shape fails here until its shape is a conscious, reviewed decision
(the same pattern as ``SPEC_UNSUPPORTED`` in the spec registry).
"""

from __future__ import annotations

import inspect

import pytest

import fleet  # noqa: F401 — registers namespaces and loads all verb classes
from fleet.adam._mixins import SharedADaMVerbsMixin
from fleet.sdtm._tdd_mixin import TrialDesignMixin
from fleet.sdtm.namespace import SDTMNamespace

#: Method name → allowed count of positional (positional-only or
#: positional-or-keyword) parameters after ``self``.  Default is 1.
#: Everything listed here is shipped public API — shapes are frozen for
#: stability; new verbs must conform to the default or be added here as a
#: reviewed decision.
_POSITIONAL_ALLOWANCE: dict[str, int] = {
    # (name, frame) pairs — the pair IS the target; both positional-only.
    "pin": 2,
    "repin": 2,
    # (path/spec, dataset-ish) legacy two-positional readers.
    "from_spec": 2,
    # Largest legacy deviation: 6 positional-or-keyword params, shipped shape.
    # Candidate for keyword-only tightening in a future deprecation cycle.
    "validate": 6,
    # (paramcd, param) — the PARAMCD/PARAM pair is the target of a TTE param.
    "param": 2,
    # TDD multi-target verbs: the target is a column pair, both positional.
    "element_boundaries": 2,  # (target_start, target_end)
    "visit_map": 2,  # (target_num, target_name)
    "study_header": 2,  # (study_id, domain) — TDD scaffolding, shipped shape.
}


def _namespace_classes() -> list[type]:
    """Every verb-bearing class: SDTM, TDD, and all ADaM (sub)namespaces."""
    classes: set[type] = {SDTMNamespace, TrialDesignMixin, SharedADaMVerbsMixin}
    stack = [SharedADaMVerbsMixin]
    while stack:
        for sub in stack.pop().__subclasses__():
            if sub not in classes:
                classes.add(sub)
                stack.append(sub)
    return sorted(classes, key=lambda c: c.__name__)


def _public_methods() -> dict[str, object]:
    """Public callables defined by Fleet, deduped by underlying function."""
    methods: dict[str, object] = {}
    for cls in _namespace_classes():
        for name in dir(cls):
            if name.startswith("_"):
                continue
            fn = inspect.getattr_static(cls, name, None)
            if isinstance(fn, (staticmethod, classmethod)):
                fn = fn.__func__
            if not inspect.isfunction(fn):
                continue  # properties, descriptors, non-Fleet attributes
            if not (fn.__module__ or "").startswith("fleet"):
                continue
            methods.setdefault(fn.__qualname__, fn)
    return methods


_METHODS = _public_methods()


def test_the_sweep_sees_the_verb_surface():
    """Guard the guard: an import/refactor must not silently empty the sweep."""
    names = {q.rsplit(".", 1)[-1] for q in _METHODS}
    assert {"assign", "merge", "pin", "date", "seq", "to_spec_yaml"} <= names
    assert len(_METHODS) > 50


@pytest.mark.parametrize("qualname", sorted(_METHODS))
def test_keyword_only_after_target(qualname):
    fn = _METHODS[qualname]
    params = list(inspect.signature(fn).parameters.values())
    if params and params[0].name in ("self", "cls"):
        params = params[1:]
    positional = [
        p
        for p in params
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    name = qualname.rsplit(".", 1)[-1]
    allowed = _POSITIONAL_ALLOWANCE.get(name, 1)
    assert len(positional) <= allowed, (
        f"{qualname} takes {len(positional)} positional parameters "
        f"({[p.name for p in positional]}); the Fleet convention is keyword-only "
        f"after the target (CONTRIBUTING.md). Make the extras keyword-only, or — "
        f"if the shape is a deliberate decision — add it to _POSITIONAL_ALLOWANCE "
        f"with a reason."
    )
