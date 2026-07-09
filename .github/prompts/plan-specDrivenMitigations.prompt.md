---
mode: agent
description: "Harden the spec-driven workflow (define.yaml → from_spec()) against silent failures, improve DX, and enforce IG-canonical ordering."
tools:
  [
    "read_file",
    "replace_string_in_file",
    "multi_replace_string_in_file",
    "grep_search",
    "file_search",
    "semantic_search",
    "run_in_terminal",
    "get_errors",
  ]
---

> **Status (2026-07): implemented — `from_spec(..., strict=True)`, single registry in `core/spec_registry.py`, generated JSON schema. Algorithm ids herein are still current spec language.**

# Spec-Driven Workflow — Mitigation Plan

Harden Fleet's `define.yaml` → `from_spec()` pipeline against silent failures, late errors, and user experience gaps while respecting Fleet philosophy: **minimalistic, simple, powerful**.

## Implementation order

M1 → M2 → M4 → M5 → M3

Complete each item fully (code + tests + verification) before moving to the next.

---

## M1. Forbid unknown derivation keys (P0)

**Goal:** A typo in a derivation parameter name must raise immediately, not produce a silent wrong result.

**Change:** Set `model_config = {"extra": "forbid"}` on `SDTMVariableSpec` and `ADAMVariableSpec`.

**Files:**

- `src/fleet/sdtm/models.py` — `SDTMVariableSpec`
- `src/fleet/adam/models.py` — `ADAMVariableSpec`

**Pre-work (critical):** Before flipping the config, audit ALL `getattr(var, "field", ...)` calls in both `from_spec()` dispatchers (`src/fleet/sdtm/namespace.py`, `src/fleet/adam/namespace.py`). Any field accessed via `getattr` that is not declared on the model must be promoted to an explicit field on the Pydantic model first. Otherwise existing specs will break.

**Example — before (silent):**

```yaml
derivation:
  algorithm: source
  sourc: VSSTRESN # typo → silently ignored
```

**Example — after (caught):**

```
ValidationError: sourc — Extra inputs are not permitted
```

**Test:** Add a test that constructs a spec dict with a typo key and asserts `ValidationError` is raised.

---

## M2. Warn on unhandled algorithms in `from_spec()` (P0)

**Goal:** If a valid algorithm enum value has no handler in the `from_spec()` dispatch, the user must be told — not silently skipped.

**Change:** Add a terminal `else` clause to the if-elif dispatch chain in both `from_spec()` methods.

**Files:**

- `src/fleet/sdtm/namespace.py` — SDTM `from_spec()` method
- `src/fleet/adam/namespace.py` — ADaM `from_spec()` method

**Use `warnings.warn()`, NOT an exception.** Algorithms like `merge`, `lookup`, `multiple_responses` are intentionally unsupported in spec mode — users derive them inline with `omit=`. A warning makes the skip visible without crashing a working pipeline.

```python
else:
    import warnings
    warnings.warn(
        f"Variable '{target}': algorithm '{alg}' is not supported "
        f"in from_spec() and was skipped. Derive it inline instead.",
        stacklevel=2,
    )
```

**Test:** Add a test that uses an algorithm known to be skipped (e.g., `merge` for SDTM, `lookup` for ADaM) and asserts a `UserWarning` is emitted.

---

## M4. Early expression validation inside `from_spec()` (P1)

**Goal:** Invalid Polars expressions in the spec must fail at `from_spec()` call time with the variable name in the error — not at `.to_frame()` time with a cryptic Polars error.

**Change:** After extracting variables but BEFORE the dispatch loop, parse all expression strings in one pass. Collect all errors. Raise a single `SpecError` with the complete list.

**Files:**

- `src/fleet/adam/namespace.py` — ADaM `from_spec()`
- `src/fleet/sdtm/namespace.py` — SDTM `from_spec()` (for `condition` expressions)

**No separate `validate_spec()` method.** Validation is embedded directly in `from_spec()`. Zero extra API surface.

**Validate:**

- `expression` field when `algorithm == "derivation"` (ADaM)
- `when` strings in `conditions` list when `algorithm == "condderivation"` (ADaM)
- `condition` field when `algorithm == "condition_add"` (SDTM)
- `when[].condition` strings when `algorithm == "if_then_else"` (SDTM)

```python
errors = []
for var in variables:
    if var.algorithm.value == "derivation" and var.expression:
        try:
            parse_expression(var.expression)
        except Exception as exc:
            errors.append(f"Variable '{var.target}': invalid expression: {exc}")
    # ... same pattern for condderivation, condition_add, if_then_else

if errors:
    msg = "\n".join(f"  - {e}" for e in errors)
    raise SpecError(f"Spec validation failed for {dataset}:\n{msg}")
```

**Test:** Add a test with an intentionally broken expression in the spec and assert `SpecError` is raised with the variable name in the message.

---

## M5. IG-canonical variable ordering (P2)

**Goal:** Variables in the spec must be processed in CDISC IG order regardless of how the user ordered them in the YAML. This ensures derived columns exist before downstream derivations reference them.

**Change:** Before the dispatch loop in ADaM `from_spec()`, sort the extracted variables to IG-canonical order.

**File:** `src/fleet/adam/namespace.py`

**Approach — NOT a DAG.** The CDISC IG already defines the canonical variable order within each dataset. That order is itself a natural topological sort (`AVAL` before `ABLFL` before `BASE` before `CHG`). Use a simple lookup:

```python
def _sort_by_ig_order(variables, ig_order):
    """Re-sort variables to IG-canonical order. Custom vars go last."""
    rank = {name: i for i, name in enumerate(ig_order)}
    sentinel = len(ig_order)
    return sorted(variables, key=lambda v: rank.get(v.target, sentinel))
```

- Standard IG variables: sorted to their IG position
- Custom variables (NSVs, study-specific): sorted to end — they typically depend on standard variables
- `depends_on` stays as an optional manual escape hatch for custom-to-custom dependencies only

**Source for IG order:** The IG metadata is already available from `fleet init define` / CDISC Library cache. Determine the best way to access it at runtime (embedded constant, loaded from define.yaml dataset key order, or queried from the IG cache).

**Test:** Add a test where variables are deliberately out of IG order in the spec (e.g., `CHG` before `BASE`) and assert the pipeline still produces correct results.

---

## M3. Per-algorithm JSON Schema validation (P1)

**Goal:** VS Code YAML autocomplete should show only relevant parameters per algorithm, not all 30+ flat fields.

**Change:** Add `if/then` blocks to the JSON schema for per-algorithm required and allowed properties.

**File:** `src/fleet/define_xml/schemas/define_spec_schema.json`

**Approach:** Start with the 10 most-used algorithms:

1. `assign_no_ct` → requires `source`
2. `assign_ct` → requires `source`, `ct_codelist`; optional `ct_mapping`
3. `hardcode_no_ct` → requires `value`
4. `hardcode_ct` → requires `value`, `ct_codelist`
5. `source` → requires `source`
6. `assigned` → requires `value`
7. `derivation` → requires `expression`
8. `study_day` → requires `analysis_date`, `reference_date`
9. `baseline` → requires `baseline_flag`
10. `chg` / `pchg` → requires `aval`, `base`

Leave `additionalProperties: true` as fallback for remaining algorithms. Incremental.

**Verify:** Run `uv run mkdocs build --clean` to ensure no schema-related build errors.

---

## M6. Future leads (NOT implemented in this plan)

These are documented for future reference. Do NOT implement them as part of this plan.

| Pattern                         | Pragmatic answer today                                                   | Future direction                                       |
| ------------------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------ |
| Cross-dataset lookups           | `omit=` + inline                                                         | `SpecContext` dataset registry passed to `from_spec()` |
| LOCF / WOCF                     | Inline Polars                                                            | `locf`/`wocf` as mixin verbs + spec algorithms         |
| Partial-date imputation         | `impute`/`impute_time` kwargs (already partially wired in ADaM dispatch) | Document & expand strategies                           |
| Population flags (SAFFL, ITTFL) | Derive inline, use `omit=`                                               | Keep inline — naturally multi-dataset                  |

---

## Verification after EACH item

```bash
uv run ruff check && uv run ruff format --check
uv run pytest
uv run python examples/cdiscpilot01_spec_driven.py
uv run python examples/full_pipeline_example.py
uv run python examples/cdiscpilot01_inline.py
uv run python examples/adnca_example.py
uv run python examples/tdd_example.py
```

All must pass before moving to the next item.
