---
description: "Use when writing or modifying tests under tests/"
applyTo: "tests/**"
---

# Test Data Convention — inline `pl.from_repr`

Literal test frames MUST be inline `pl.from_repr(...)` tables, not factories, CSV fixtures, or dict constructors. Each test owns its visible data — no chasing external files or factory parameters.

```python
df = pl.from_repr("""
┌─────────┬──────────┬───────┐
│ USUBJID ┆ VSTESTCD ┆ AVAL  │
│ ---     ┆ ---      ┆ ---   │
│ str     ┆ str      ┆ f64   │
╞═════════╪══════════╪═══════╡
│ 001     ┆ SYSBP    ┆ 120.0 │
│ 002     ┆ SYSBP    ┆ 135.0 │
└─────────┴──────────┴───────┘
""")
```

## Allowed exceptions

- **Programmatic frames** — data generated in a loop or parametrized (ranges, cartesian products).
- **Dtype edge cases** `from_repr` can't express (e.g. nested types, exotic temporal units) — construct directly.
- **Single-column throwaways** — a one-column frame incidental to the assertion may use `pl.DataFrame({...})`.

## Helpers

- `tests/helpers.py` provides `shuffle_rows(df, seed=42)` for order-independence tests — use it instead of hand-rolled shuffles.
- No new factory modules or CSV fixtures under `tests/fixtures/` for tabular data (`ct/`, `specs/`, `goldens/` YAML/artifacts are fine).
