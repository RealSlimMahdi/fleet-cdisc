# Event-Priority Derivation with `pick()`

Many ADaM variables require scanning multiple data sources in a defined priority order and selecting the first (or last) qualifying value.  Admiral calls this pattern `derive_vars_extreme_event` / `event()`.  Fleet provides `pick()` — a single verb that replaces multi-step joins, coalesces, and manual priority logic.

## The Problem

Consider **LSTALVDT** (Last Date Known Alive).  The derivation spec typically reads:

> Set LSTALVDT to the latest date from:
>
> 1. Death date (DTHDT) — if the subject died
> 2. Last AE end date (AEENDTC)
> 3. Last AE start date (AESTDTC)
> 4. Treatment end date (TRTEDT) — fallback

Each "event" has its own source dataset, filter condition, and column to extract.  The first event that matches (in priority order) wins for each subject.

Without `pick()`, you'd need:

```python
# Manual approach — 4 last_date lookups + coalesce
adsl = (
    adsl.adam.adsl.last_date("_dth", from_dataset=adsl_df, date_col="DTHDT")
    .last_date("_ae_end", from_dataset=ae, date_col="AEENDTC")
    .last_date("_ae_start", from_dataset=ae, date_col="AESTDTC")
    .derivation("LSTALVDT", expression='pl.coalesce("_dth", "_ae_end", "_ae_start", "TRTEDT")')
    .to_frame()
    .drop(["_dth", "_ae_end", "_ae_start"])
)
```

This is verbose, error-prone (column ordering = priority), and loses traceability.

## The Solution: `pick()`

```python
adsl = adsl.adam.adsl.pick(
    "LSTALVDT",
    events=[
        {
            "when": pl.col("DTHDT").is_not_null(),
            "set": {"LSTALVDT": "DTHDT"},
            "source": adsl_df,
            "label": "Death date",
        },
        {
            "when": pl.col("AEENDTC").is_not_null(),
            "set": {"LSTALVDT": "AEENDTC"},
            "source": ae,
            "label": "AE end date",
        },
        {
            "when": pl.col("AESTDTC").is_not_null(),
            "set": {"LSTALVDT": "AESTDTC"},
            "source": ae,
            "label": "AE start date",
        },
        {
            "when": pl.col("TRTEDT").is_not_null(),
            "set": {"LSTALVDT": "TRTEDT"},
            "label": "Treatment end (self)",
        },
    ],
    by=["USUBJID"],
    order=["LSTALVDT"],
    mode="last",
).to_frame()
```

Priority is explicit in list order.  Each event's `"label"` documents intent.  No temporary columns needed.

## How It Works

```mermaid
flowchart TD
    A[Events list<br/>ordered by priority] --> PE

    subgraph PE["For each event · in priority order"]
        direction TB
        C[Filter source by 'when' condition]
        D[Apply 'set' mappings to targets]
        E[Group by 'by' vars]
        F[Select record per mode / order]
        G[Tag with event priority number]
        C --> D --> E --> F --> G
    end

    PE --> H[Stack all candidate records]
    H --> I[Sort by priority, then order]
    I --> J[Keep first per group = winner]
    J --> K[Left-join targets back to base frame]
```

**Key properties:**

1. **Priority = list position.**  Event at index 0 beats index 1, regardless of dates.
2. **Within-event selection** uses `mode` ("first" or "last") + `order` (sort columns).
3. **Cross-event winner** is the highest-priority event that has qualifying records.
4. **Subjects with no matching events** get `null` for all targets.

## Event Dict Reference

Each event is a Python `dict` with these keys:

| Key | Required | Type | Description |
|-----|----------|------|-------------|
| `"when"` | Yes | `str \| pl.Expr` | Boolean filter — which records qualify |
| `"set"` | Yes | `dict[str, str \| pl.Expr \| Any]` | Maps each target to a source column name, expression, or literal |
| `"source"` | No | `pl.DataFrame` | External dataset to scan. Omit to use the current pipeline frame |
| `"mode"` | No | `str` | Override top-level mode for this event (`"first"` / `"last"`) |
| `"order"` | No | `str \| list[str]` | Override top-level sort for this event |
| `"label"` | No | `str` | Documentation-only description (ignored at runtime) |

## Multiple Targets

`pick()` can derive several columns simultaneously from the same event cascade:

```python
adsl = adsl.adam.adsl.pick(
    ["LSTALVDT", "DTHFL"],
    events=[
        {
            "when": pl.col("DTHDT").is_not_null(),
            "set": {"LSTALVDT": "DTHDT", "DTHFL": pl.lit("Y")},
            "source": adsl_df,
        },
        {
            "when": pl.col("AEENDTC").is_not_null(),
            "set": {"LSTALVDT": "AEENDTC", "DTHFL": pl.lit("N")},
            "source": ae,
        },
    ],
    by=["USUBJID"],
    order=["LSTALVDT"],
    mode="last",
).to_frame()
```

When an event only sets some targets, the others remain `null` for that event's candidates.

## String Conditions (YAML-Compatible)

For spec-driven pipelines, conditions can be strings that get evaluated safely:

```python
events = [
    {"when": 'pl.col("DTHDT").is_not_null()', "set": {"LSTALVDT": "DTHDT"}},
]
```

This is equivalent to passing a `pl.Expr` directly and enables full round-tripping through `define.yaml`.

## Admiral Comparison

| Admiral | Fleet |
|---------|-------|
| `event(dataset, condition, set_values_to, order, mode)` | Event dict in `events` list |
| `derive_vars_extreme_event(events, source_datasets, by_vars, order, mode, check_type)` | `.pick(targets, events=..., by=..., order=..., mode=...)` |
| Priority = position in `event()` list | Priority = position in `events` list |
| Requires pre-built event objects + explicit dataset references | Inline dicts with optional `"source"` — current frame used by default |

Fleet's `pick()` is semantically equivalent but:

- Eliminates the need for a separate `event()` constructor
- Supports per-event mode/order overrides
- Accepts literals (`pl.lit("Y")`) directly in `"set"` alongside column references
- Chains naturally into the ADaM pipeline without materialisation breaks

## When to Use `pick()` vs `@derivation`

| Scenario | Use |
|----------|-----|
| Multi-source priority cascade (LSTALVDT, DTHCAUS, LDDTHELD) | `pick()` |
| Simple conditional (AGEGR1, EOSSTT) | `case_when()` |
| Complex cross-record logic within one source (CBOR confirmation rules) | `@derivation(kind="frame")` |
| Aggregation that needs custom grouping (derived parameters) | `derive_param()` |

**Rule of thumb:** If your logic is "try source A, then B, then C" — use `pick()`.  If it requires comparing multiple records within the same subject to determine a single result (e.g., sustained response confirmation), use a `@derivation`.

## Spec-Driven Usage

In a `define.yaml`, the pick algorithm maps directly:

```yaml
variables:
  - name: LSTALVDT
    label: Last Date Known Alive
    algorithm: pick
    targets: [LSTALVDT]
    events:
      - when: 'pl.col("DTHDT").is_not_null()'
        set: {LSTALVDT: DTHDT}
        source: ADSL
      - when: 'pl.col("AEENDTC").is_not_null()'
        set: {LSTALVDT: AEENDTC}
        source: AE
    by: [USUBJID]
    order: [LSTALVDT]
    mode: last
```

Fleet's `from_spec()` dispatches to `.pick()` automatically when `algorithm: pick` is detected.
