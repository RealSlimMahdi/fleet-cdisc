---
description: "Use when writing new code, refactoring, or reviewing code quality patterns in Fleet"
applyTo: "src/**"
---

# Code Hygiene — Avoiding Common Debt Patterns

## No private attribute access across modules

Never access `obj._private_attr` from outside the owning class. Expose a public method instead.

```python
# WRONG
decode_map = {coded: info.get("preferred_term", coded) for coded, info in ct_validator._ct_cache.items()}

# CORRECT
decode_map = ct_validator.get_decode_map(ct_codelist)
```

## Prefer dispatch dicts over if/elif chains

```python
# WRONG
if domain == "ae":
    ard = data_df.tlg.ae.t_summary(...)
elif domain == "vs":
    ard = data_df.tlg.vs.t_summary(...)

# CORRECT
_domain_dispatch = {
    "ae": lambda df: df.tlg.ae.t_summary(...),
    "vs": lambda df: df.tlg.vs.t_summary(...),
}
ard = _domain_dispatch[domain](data_df)
```

## No dead constants or unused maps

Remove constants that are defined but never referenced. Don't leave "aspirational" data structures.

## Large methods: extract when branches are independent

If >5 top-level if/elif branches with >10 lines each, extract into private helpers.

## No duplicated logic across namespace subclasses

Same method body in 2+ namespace classes → extract into:

- Mixin in `_mixins.py` (ADaM namespaces)
- `SharedVerbsMixin` in `src/fleet/core/_verb_mixin.py` (cross-namespace)
- Shared module function (stateless utilities)

## CLI: argparse `choices` replaces validation

When argparse constrains via `choices=`, don't re-validate in the handler. Use dispatch dict + let argparse handle errors.
