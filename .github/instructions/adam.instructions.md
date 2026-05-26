---
description: "Use when writing or modifying ADaM namespace code, mixins, ADSL/OCCDS/Onco verbs, or any file under src/fleet/adam/"
applyTo: "src/fleet/adam/**"
---

# ADaM Namespace Mixin Discipline

**Duplicating verb implementations across namespace classes is strictly forbidden.**

## Decision Tree

| Scope                        | Action                                                     |
| ---------------------------- | ---------------------------------------------------------- |
| Verb in **1** namespace only | Implement directly in that class                           |
| Verb in **2+** namespaces    | Extract into mixin in `_mixins.py`; all namespaces inherit |
| Verb in **all** namespaces   | Add to `SharedADaMVerbsMixin`                              |
| Verb in a **subset**         | Create focused mixin, inherit selectively                  |

## Adding a Shared Verb

1. Add method to appropriate mixin in `src/fleet/adam/_mixins.py`.
2. Return type MUST be `Self` (from `typing`).
3. Use `self._chain(*exprs)` for lazy expressions, `self._materialise_then(df)` for materialisation.

```python
# src/fleet/adam/_mixins.py
class SharedADaMVerbsMixin:
    def my_new_verb(self, target: str, *, param: str) -> Self:
        ...
        return self._chain(some_expr.alias(target))
```

## Selective Exposure

```python
class DateDerivationMixin:
    def impute_date(self, target: str, *, source: str) -> Self: ...

class ADSLNamespace(SharedADaMVerbsMixin, DateDerivationMixin): ...
class OncoNamespace(SharedADaMVerbsMixin): ...  # no date verbs
```

## Extending a Shared Verb

Override and call `super()`:

```python
class ADSLNamespace(SharedADaMVerbsMixin):
    def derivation(self, target: str, *, expression: str | pl.Expr) -> Self:
        # ADSL-specific validation
        return super().derivation(target, expression=expression)
```

## Canonical Reference

`src/fleet/adam/_mixins.py` is the single source of truth. Read its module docstring before modifying shared verbs.
