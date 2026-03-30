## Plan: Declarative TLG Namespace with Spec-Driven Customization

Add a `.tlg` Polars DataFrame namespace to Fleet with a **Vega-Lite-inspired declarative spec system**. Each TLG output (AE summary, AE listing, VS summary, etc.) is defined by a `TLGSpec` Pydantic model that declares field→role mappings, statistics, and data requirements. The spec carries both **structural validation** (column presence/types) and **content validation** (required PARAM/PARAMCD values, flag values, pool arm existence). Methods like `.t_summary()` accept an optional spec override for full customization. Default specs provide zero-config convenience; custom specs let users add columns, change grouping, or adjust statistics declaratively — without writing compute code.

---

### Architecture: 3 Concepts (Vega-Lite Analogy)

| Vega-Lite | Fleet TLG | Example |
|-----------|-----------|---------|
| `mark` | `output_type` | `"summary"`, `"listing"`, `"shift"`, `"forest_plot"` |
| `encoding` | `rows` / `columns` / `statistics` | `Row(field="AEDECOD")`, `Statistic.N_PCT` |
| `transform.filter` | `filter` | `pl.col("SAFFL") == "Y"` |
| `data` | implicit | The DataFrame `.tlg` is called on |
| `config` | `format` | Decimal places, labels, sort order, column ordering |

A spec is a Pydantic model. It declares *what* the output should contain — not *how* to compute it. The engine resolves the spec into Polars expressions. This mirrors Vega-Lite where you say `encoding: {x: {field: "date"}}` and the library figures out scales, axes, and rendering.

---

### Three Validation Tiers

**Tier 1 — Structural**: required columns exist, correct dtypes

```python
bad_df.tlg.ae.t_summary()
# → SchemaError: "AESummarySpec requires columns [USUBJID, TRTA, AEDECOD, AEBODSYS]
#    but DataFrame is missing [AEBODSYS]. Available: [USUBJID, TRTA, AEDECOD, SEX, AGE]"
```

**Tier 2 — Content** (PARAM/codelist scanning): required data values exist

```python
advs_without_pulse.tlg.vs.t_summary()
# → SchemaError: "VSSummarySpec requires PARAMCD values ['SYSBP','DIABP','PULSE']
#    but data is missing ['PULSE']. Available: ['SYSBP','DIABP','HEIGHT','WEIGHT']"
```

**Tier 3 — Pool arm validation**: composite group arms exist in data

```python
spec = AESummarySpec(pools=[GroupPool(label="All Active", arms=["Drug A", "Drug B"])])
adae.tlg.ae.t_summary(spec=spec)
# → SchemaError: "Pool 'All Active' references arm 'Drug B' but TRTA contains
#    only ['Placebo', 'Drug A']"
```

All three tiers fire at method entry — before any computation.

---

### Customization Model

**Zero-config** (sensible defaults baked into each spec type):
```python
ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)
# Uses AESummarySpec defaults: rows=SOC→PT, stats=[n, pct],
# filters=[SAFFL=="Y", TRTEMFL=="Y"]
```

**Override via spec** (declarative — describe the table, don't code it):
```python
from fleet.tlg import AESummarySpec, Row, Statistic, GroupPool

spec = AESummarySpec(
    rows=[
        Row(field="AEBODSYS", label="System Organ Class"),
        Row(field="AEDECOD", label="Preferred Term"),
        Row(field="AESER", label="Serious", filter_value="Y"),  # add sub-analysis
    ],
    columns=["TRTA"],
    statistics=[Statistic.N_SUBJECTS, Statistic.N_PCT, Statistic.N_EVENTS],
    pools=[
        GroupPool(label="All Xanomeline",
                  arms=["Xanomeline Low Dose", "Xanomeline High Dose"]),
        GroupPool(label="Total", arms="*"),
    ],
    column_order=["Placebo", "Xanomeline Low Dose", "Xanomeline High Dose",
                  "All Xanomeline", "Total"],
    filter=pl.col("SAFFL") == "Y",
    denominator="TRTA",
)
ard = adae.tlg.ae.t_summary(spec=spec, adsl=adsl)
```

**Custom listing** (add/remove columns):
```python
from fleet.tlg import AEListingSpec, Column

spec = AEListingSpec(
    columns=[
        Column(field="USUBJID", label="Subject"),
        Column(field="TRTA",    label="Treatment"),
        Column(field="AEBODSYS",label="SOC"),
        Column(field="AEDECOD", label="Preferred Term"),
        Column(field="AESEV",   label="Severity"),
        Column(field="AESER",   label="Serious"),
        Column(field="ASTDT",   label="Start Date", format="date"),
        Column(field="AENDT",   label="End Date", format="date"),
        Column(field="AEACN",   label="Action Taken"),  # ← user adds this
    ],
    sort_by=["USUBJID", "ASTDT"],
    filter=pl.col("SAFFL") == "Y",
)
listing = adae.tlg.ae.l_listing(spec=spec)
```

**YAML-serializable** (for CI pipelines, spec-driven workflows):
```yaml
# tlg_spec.yaml — can live alongside define.yaml
- output: t_ae_summary
  rows:
    - {field: AEBODSYS, label: System Organ Class}
    - {field: AEDECOD, label: Preferred Term}
  columns: [TRTA]
  statistics: [n_subjects, n_pct]
  pools:
    - label: "All Xanomeline"
      arms: ["Xanomeline Low Dose", "Xanomeline High Dose"]
    - label: "Total"
      arms: "*"
  column_order: [Placebo, Xanomeline Low Dose, Xanomeline High Dose,
                 All Xanomeline, Total]
  data_requirements:
    required_columns: [USUBJID, TRTA, AEDECOD, AEBODSYS]
    required_flags: {SAFFL: ["Y"]}
```

**Pre-check without computing** (IDE/notebook diagnostic):
```python
report = adae.tlg.ae.check()
# ["WARNING: Column AESER not present — serious AE sub-analysis will be skipped"]
```

---

### Composite Treatment Groups (Pooled Arms)

CSR tables show real arms alongside synthetic aggregate columns:

| Stat | Placebo | Xan Low | Xan High | **All Xanomeline** | **Total** |
|------|---------|---------|----------|---------------------|-----------|
| N | 86 | 84 | 84 | **168** | **254** |
| Any AE n (%) | 57 (66.3) | 73 (86.9) | 74 (88.1) | **130 (77.4)** | **187 (73.6)** |

**Mechanism — pre-computation stacking** (3 steps, transparent to user):

1. **Validate**: check that referenced arm labels exist in `df[group_col].unique()`
2. **Stack**: for each `GroupPool`, filter df to constituent arms → overwrite group column with pool label → `pl.concat` onto original df
3. **Compute**: run normal groupby statistics on expanded df

**Why stacking is reliable**:
- `n_unique(USUBJID)` within each group naturally deduplicates subjects appearing in multiple constituent arms (the "counted once" problem solved for free)
- Event counts (`len()`) correctly sum all events across pooled arms
- Same groupby code path handles real and synthetic groups — zero special-case logic
- Polars handles efficiently via lazy evaluation (no data copy until `collect`)
- Applied to **both** the analysis df **and** the ADSL df — big-N denominators correct for pools too

**`GroupPool` model**: `label: str`, `arms: list[str] | Literal["*"]`

---

### ARD Output Format

Standardized columns aligned with CDISC ARS / pharmaverse {cards}:

| Column | Type | Example |
|--------|------|---------|
| `group1` | str | `"TRTA"` |
| `group1_level` | str | `"Xanomeline Low Dose"` |
| `variable` | str | `"AEDECOD"` |
| `variable_level` | str | `"HEADACHE"` |
| `stat_name` | str | `"n"`, `"pct"`, `"N"` |
| `stat_label` | str | `"n (%)"`, `"N"` |
| `stat` | float/str | `73`, `86.9` |
| `context` | str | `"t_ae_summary"` |

ARD is the **computation** layer. Rendering (HTML, RTF, LaTeX) is a separate future concern that consumes ARD. Listings return a plain `pl.DataFrame` (they're data extracts, not statistics).

---

### Steps

**Phase 1 — Foundation** (`src/fleet/tlg/`)

| Step | File | What |
|------|------|------|
| 1 | `src/fleet/tlg/__init__.py` | Register `@pl.api.register_dataframe_namespace("tlg")`, export public API |
| 2 | `src/fleet/tlg/_specs.py` | Pydantic spec hierarchy: `TLGSpec` base, `Row`, `Column`, `Statistic`, `GroupPool` building blocks, `AESummarySpec`, `AEListingSpec`, `VSSummarySpec` with defaults, `validate_dataframe(df)` method |
| 3 | `src/fleet/tlg/_ard.py` | ARD builder utility (standardized columns), `_expand_pools(df, pools, group_col)` stacking helper |
| 4 | `src/fleet/tlg/namespace.py` | `TLGNamespace` with `.ae` / `.vs` sub-namespace properties |
| 5 | `src/fleet/tlg/ae_namespace.py` | `AETLGNamespace` with `.t_summary()`, `.l_listing()`, `.check()` |
| 6 | `src/fleet/core/exceptions.py` | Add `TLGError`, `SchemaError` |
| 7 | `src/fleet/__init__.py` | Wire `from . import tlg` |

**Phase 2 — Validation Engine** (*depends on Phase 1*)

| Step | What |
|------|------|
| 8 | Two-tier validation in `TLGSpec.validate_dataframe(df)`: structural (columns/types) + content (PARAMCD values, flag values) |
| 9 | Pool arm validation: referenced arms must exist in data |
| 10 | Auto-validation: every `.t_summary()` / `.l_listing()` runs `spec.validate_dataframe(df)` at entry |
| 11 | `.check(spec=...)` pre-validation: returns diagnostic list without computing |

**Phase 3 — AE Summary + AE Listing** (*depends on Phase 2*)

| Step | What |
|------|------|
| 12 | `_expand_pools()`: filter + relabel + concat for each pool, applied to both analysis df and ADSL |
| 13 | `t_summary()`: N from ADSL (per arm, incl. pools), n/% any AE, by SOC, by PT, optional serious/related/severity sub-analyses. Pure Polars groupby → ARD output |
| 14 | `l_listing()`: schema validation → select + sort + filter → plain `pl.DataFrame` output |

**Phase 4 — Spec Serialization** (*parallel with Phase 3*)

| Step | What |
|------|------|
| 15 | `spec.to_yaml()` / `TLGSpec.from_yaml(path)` — round-trip YAML serialization |
| 16 | Optional `tlg:` section in `define.yaml` for spec-driven TLG pipelines |

**Phase 5 — Tests & Integration**

| Step | What |
|------|------|
| 17 | Unit tests: structural validation (missing cols → `SchemaError`) |
| 18 | Unit tests: content validation (missing PARAMCD → `SchemaError`) |
| 19 | Unit tests: pool arm validation (bad arm ref → `SchemaError`) |
| 20 | Unit tests: pool stacking correctness (n_unique dedup, event sums) |
| 21 | Unit tests: ARD output structure (correct columns, types) |
| 22 | Unit tests: known-data AE summary stats match expected values |
| 23 | Unit tests: AE listing output (correct rows, columns, sort) |
| 24 | Unit tests: spec YAML round-trip (`to_yaml` → `from_yaml` → identical spec) |

---

### Relevant Files (implementation reference)

- `src/fleet/adam/_mixins.py` — Namespace `__init__`, `_chain`, `Self` typing, `_materialise_then` pattern
- `src/fleet/adam/namespace.py` — Sub-namespace property pattern (`.adsl`, `.occds`), `from_spec()` YAML-driven pipeline
- `src/fleet/sdtm/models.py` — Pydantic model patterns (`SDTMVariableSpec`, `SDTMDomainSpec`)
- `src/fleet/sdtm/tdd.py` — `@model_validator` for complex Pydantic validation
- `src/fleet/core/exceptions.py` — Exception hierarchy to extend
- `src/fleet/__init__.py` — Where to register `.tlg` namespace
- `specs/cdiscpilot01/adam/define.yaml` — Reference for spec-driven approach
- `docs/concepts/advanced.md` — Custom namespace registration pattern reference

---

### Verification

1. `uv run ruff check` + `uv run ruff format --check`
2. `uv run pytest` — new + existing tests pass
3. All 5 example scripts run without error
4. Schema validation tests: missing columns → `SchemaError`, correct columns → pass
5. Content validation tests: missing PARAMCD → `SchemaError`, present → pass
6. Pool validation tests: bad arm reference → `SchemaError`, correct pools → pass
7. Pool stacking tests: subject dedup correct, event counts correct
8. ARD output structure matches expected columns and types
9. Spec round-trip: `to_yaml()` → `from_yaml()` produces identical spec

---

### Decisions

| Decision | Rationale |
|----------|-----------|
| **Separate `.tlg` namespace** (not on `.adam`) | TLGs consume ADaM data, different concern. Terminal output (returns DataFrame), not chainable (returns Self). |
| **Sub-namespaces** (`.tlg.ae`, `.tlg.vs`) | Mirrors domain structure, prevents name collisions, IDE narrows autocomplete. Proven pattern in Fleet. |
| **Pydantic for specs** | Already used throughout Fleet. IDE autocomplete, validation, YAML serde for free. |
| **Spec is optional** | Zero-config defaults for every method. Spec for customization only. |
| **Content validation scans data** | Not just columns — checks PARAMCD values, flag values, pool arm existence. |
| **Pre-computation stacking for pools** | `n_unique` dedup is correct by construction. No special-case code paths. |
| **ARD for tables, plain DataFrame for listings** | Different output types for different purposes. |
| **`adsl` as explicit argument** | Big-N denominators require ADSL. Explicit > implicit. |
| **Extend + replace for spec customization** | `extra_rows` for additive, `rows` for full override. Both supported. |

---

### Further Considerations

1. **Rendering layer**: ARD is computation-only. A `.to_html()` / `.to_rtf()` renderer consuming ARD would be Phase 6. Deliberately out of scope for initial implementation — keeps first iteration minimal.

2. **Graph specs**: The Vega-Lite analogy extends naturally to figures (forest plots, Kaplan-Meier curves). `TLGSpec(output_type="forest_plot")` with appropriate row/column encodings is future work.

3. **Spec inheritance**: Default `AESummarySpec` has `rows=[SOC, PT]`. Adding e.g. serious AE sub-analysis uses `extra_rows=[Row(field="AESER", ...)]` (additive). Full replacement uses `rows=[...]` directly. Both paths supported via Pydantic model defaults.
