## Plan: TLG Architecture Fitness + ARD → HTML/PDF/Slides Export

Two streams run in sequence:

1. **Phase 0** — Close two real gaps: filter semantics (Scenario A) and the lack of an
   inline fluent API (Scenario B). Scenario C (multi-dataset) is solved by a documented
   pre-merge pattern that requires no API change.
2. **Phases 1–7** — `fleet.tlg.render` sub-module: HTML tables, PDF, HTML injection, and
   slides (format decided in Phase 6b).

---

## Phase 0: Architecture Fitness

### Scenario A — PARAMCD subset (e.g., `PARAMCD == "ALBUMIN"`)

**Decision: replace the single `filter` field with `adsl_filter` and `dataset_filter`.**

The old `filter` conflated two clinically distinct concepts:

| Field            | Applied to              | Example                          |
| ---------------- | ----------------------- | -------------------------------- |
| `adsl_filter`    | ADSL only (denominator) | `pl.col("SAFFL") == "Y"`         |
| `dataset_filter` | Primary dataset only    | `pl.col("PARAMCD") == "ALBUMIN"` |

Both default to `None`. When `None`, no filter is applied — all rows pass. There is no
need for a sentinel `True == True`; a `None` check is simply skipped.

```python
# No filter at all — full population, all records
spec = VSSummarySpec()

# Safety population denominator only — all ADVS records analysed
spec = VSSummarySpec(adsl_filter=pl.col("SAFFL") == "Y")

# Subset ADVS to one parameter — all subjects in denominator
spec = VSSummarySpec(dataset_filter=pl.col("PARAMCD") == "ALBUMIN")

# Both — safety population, ALBUMIN records only
spec = VSSummarySpec(
    adsl_filter=pl.col("SAFFL") == "Y",
    dataset_filter=pl.col("PARAMCD") == "ALBUMIN",
)
ard = advs.tlg.vs.t_summary(groupby="TRTA", adsl=adsl, spec=spec)
```

In `t_summary()`: `compute_big_n()` receives only `adsl_filter`; `dataset_filter` is
applied to `self._df` before any computation. Neither propagates to the other.

---

### Scenario B — Inline fluent builder API

**Decision: adopt Lead B2 as the inline programming alternative, generalized across all TLG
sub-namespaces. B1 (NestedRow) and B3 (FunctionStat) are dropped.**

#### Design principle: ARD schema drives verb design

The ARD schema is the output contract. Each builder verb maps directly to one or more ARD
columns — the verbs are _down products_ of the schema. This creates a traceable, one-to-one
correspondence between what you write and what the ARD contains:

| ARD column                    | Origin                 | Builder verb                                           |
| ----------------------------- | ---------------------- | ------------------------------------------------------ |
| `group1` / `group1_level`     | user-defined           | `.by(col)`                                             |
| `group2` / `group2_level`     | user-defined           | `.by2(col)` — user pre-merges column if from ADSL (C3) |
| `variable` / `variable_level` | first `.rows()` entry  | `.rows([field, ...])`                                  |
| `group2` nesting (alt)        | second `.rows()` entry | `.rows([outer, inner])` — two-level hierarchy          |
| `stat_name` / `stat_label`    | user-defined           | `.stats([Statistic.MEAN, ...])`                        |
| `fmt_fn`                      | default or override    | `.fmt({"mean": "xx.xx"})` (optional)                   |
| `stat` / `stat_fmt`           | computed               | — auto                                                 |
| `warning` / `error`           | computed               | — auto                                                 |
| `context`                     | inferred               | — auto from sub-namespace name                         |
| `variable=""` header rows     | `OverallStat` list     | `.header_rows([OverallStat(...)])`                     |

Data input verbs:

| Input                | Builder verb                                |
| -------------------- | ------------------------------------------- |
| Primary dataset      | namespace binding: `df.tlg.ae`, `df.tlg.vs` |
| ADSL for big-N       | `.population(adsl, adsl_filter=...)`        |
| Analysis subset      | `.filter(expr)` — maps to `dataset_filter`  |
| Treatment pooling    | `.pools([GroupPool(...)])`                  |
| Column display order | `.column_order([...])`                      |

#### Full inline examples

VS with two-level nesting and population filter:

```python
ard = (
    advs.tlg.vs
    .population(adsl, adsl_filter=pl.col("SAFFL") == "Y")          # ADSL + pop filter
    .filter(pl.col("PARAMCD").is_in(["SYSBP", "DIABP", "PULSE"]))  # dataset_filter
    .by("TRTA")                                                     # → group1
    .rows(["PARAMCD", "AVISIT"])                                    # → variable + group2 nesting
    .stats([Statistic.MEAN, Statistic.SD, Statistic.MEDIAN])
    .pools([GroupPool("All Active", arms=["Drug A", "Drug B"])])
    .column_order(["Placebo", "Drug A", "Drug B", "All Active"])
    .to_ard()
)
```

AE summary — same verbs, domain-specific defaults:

```python
ard = (
    adae.tlg.ae
    .population(adsl, adsl_filter=pl.col("SAFFL") == "Y")
    .by("TRTA")
    .rows(["AEBODSYS", "AEDECOD"])   # two-level: AEBODSYS → variable, AEDECOD → group2
    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
    .pools([GroupPool("Total", arms="*")])
    .to_ard()
)
```

Stratification from ADSL via pre-merge (C3 pattern + `.by2()`):

```python
adae_strat = adae.join(adsl.select(["USUBJID", "AGEGR1"]), on="USUBJID", how="left")

ard = (
    adae_strat.tlg.ae
    .population(adsl, adsl_filter=pl.col("SAFFL") == "Y")
    .by("TRTA")
    .by2("AGEGR1")                   # → group2 / group2_level
    .rows(["AEDECOD"])
    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
    .to_ard()
)
```

#### Dual-mode API: inline ↔ spec-driven (define.yaml analogy)

The two styles are parallel paths to the same ARD output — matching the inline vs.
`define.yaml` duality already present in Fleet's ADaM layer:

```
Inline (B2 builder)                   Spec-driven (define.yaml equivalent)
─────────────────────────────────     ──────────────────────────────────────
df.tlg.ae                               AESummarySpec(
  .population(adsl, ...)                adsl_filter=...,
  .filter(...)            ≡              dataset_filter=...,
  .by("TRTA")                           by=...,
  .rows([...])                          rows=[...],
  .stats([...])                         statistics=[...],
  .pools([...])                         pools=[...],)
  .to_ard()               ≡             df.tlg.ae.t_summary(adsl=adsl, spec=spec)
```

The `TLGBuilder` class (returned by the first builder verb) accumulates state that maps
1:1 to the spec Pydantic model. `.to_spec()` on the builder serialises to the equivalent
spec YAML; `TLGSpec.from_yaml()` already covers the reverse direction.

#### Generalization across domains

Every TLG sub-namespace (`.ae`, `.vs`, future `.lb`, `.cm`, …) exposes the same verb set.
Domain-specific defaults (required columns, default statistics, `context` label) are baked
into the sub-namespace rather than the builder. `TLGBuilder` is a shared base class
composed into each sub-namespace.

---

### Scenario C — Combining data from more than one dataset

**Decision: adopt C3 (pre-merge pattern) as the documented approach. No API change.**

The `group2`/`group2_level` ARD columns carry any second-dimension stratification. When
that column comes from another dataset, the user pre-merges it before calling the namespace.
The B2 `.by2()` verb then drives the ARD output. This is explicit, zero-surprise, and
totally consistent with the Polars-first philosophy of Fleet.

```python
# Pre-merge an ADSL column onto the primary dataset
adae_strat = adae.join(
    adsl.select(["USUBJID", "AGEGR1"]),
    on="USUBJID", how="left",
)

# Then use the fluent builder — no hidden joins inside the namespace
ard = (
    adae_strat.tlg.ae
    .population(adsl, adsl_filter=pl.col("SAFFL") == "Y")
    .by("TRTA")
    .by2("AGEGR1")
    .rows(["AEBODSYS", "AEDECOD"])
    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
    .to_ard()
)
```

Document this pattern in examples and the TLG guide section. No `stratify_by` spec field
or `TLGContext` object added.

---

### Scenario D — Summary header rows (any AE, SAE, deaths, grade 3–4, QTcF thresholds, …)

**Decision: `OverallStat` model + `.header_rows()` builder verb, both on the shared base.**

#### Design

`OverallStat` describes a single whole-dataset aggregate row: apply an optional filter,
count subjects (or events), emit one flat ARD row with no level hierarchy. It belongs to
`TLGSpec` — the _base class_ — so every sub-spec and every domain inherits `header_rows`
for free. The `.header_rows()` verb lives on `TLGBuilder` base for the same reason.

```python
class OverallStat(BaseModel):
    label: str                                # → variable_level in ARD
    filter: pl.Expr | None = None             # None = no filter (count all subjects)
    statistics: list[Statistic] | None = None # None = inherit from spec.statistics
```

ARD output contract for `OverallStat` rows:

- `variable = ""` — signals "header row" to the renderer (no indentation, no level label)
- `variable_level = OverallStat.label` — becomes the display stub text
- Rows appear **before** hierarchy rows in the ARD; renderer preserves this order
- `statistics` override is per-row (e.g. deaths should not carry `N_PCT` when the
  denominator is all-subjects)

#### AE example

```python
from fleet.tlg import OverallStat

# Spec-driven
spec = AESummarySpec(
    header_rows=[
        OverallStat("Subjects with any AE"),
        OverallStat("Subjects with ≥1 SAE",       filter=pl.col("AESER") == "Y"),
        OverallStat("Subjects with Grade 3–4 AE", filter=pl.col("AETOXGR").is_in(["3","4"])),
        OverallStat("Deaths",                     filter=pl.col("AESDTH") == "Y",
                                                   statistics=[Statistic.N_SUBJECTS]),
    ],
)
ard = adae.tlg.ae.t_summary(adsl=adsl, spec=spec)

# Inline builder — identical output
ard = (
    adae.tlg.ae
    .population(adsl, adsl_filter=pl.col("SAFFL") == "Y")
    .by("TRTA")
    .header_rows([
        OverallStat("Subjects with any AE"),
        OverallStat("≥1 SAE",       filter=pl.col("AESER") == "Y"),
        OverallStat("Grade 3–4 AE", filter=pl.col("AETOXGR").is_in(["3","4"])),
        OverallStat("Deaths",       filter=pl.col("AESDTH") == "Y",
                                     statistics=[Statistic.N_SUBJECTS]),
    ])
    .rows(["AEBODSYS", "AEDECOD"])
    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
    .to_ard()
)
```

#### Cross-domain examples — same API, different columns

VS abnormality flags:

```python
ard = (
    advs.tlg.vs
    .population(adsl, adsl_filter=pl.col("SAFFL") == "Y")
    .filter(pl.col("PARAMCD") == "SYSBP")
    .by("TRTA")
    .header_rows([
        OverallStat("Subjects with any measurement"),
        OverallStat("High value",     filter=pl.col("ANRHI") == "Y"),
        OverallStat("Critical value", filter=pl.col("ANRC2HI") == "Y"),
    ])
    .rows(["AVISIT"])
    .stats([Statistic.MEAN, Statistic.SD])
    .to_ard()
)
```

ECG / QTcF threshold rows:

```python
ard = (
    adeg.tlg.ecg
    .population(adsl, adsl_filter=pl.col("SAFFL") == "Y")
    .filter(pl.col("PARAMCD") == "QTcF")
    .by("TRTA")
    .header_rows([
        OverallStat("> 450 ms",         filter=pl.col("AVAL") > 450),
        OverallStat("> 480 ms",         filter=pl.col("AVAL") > 480),
        OverallStat("> 500 ms",         filter=pl.col("AVAL") > 500),
        OverallStat("Increase > 30 ms", filter=pl.col("CHG") > 30),
        OverallStat("Increase > 60 ms", filter=pl.col("CHG") > 60),
    ])
    .rows(["AVISIT"])
    .stats([Statistic.MEAN, Statistic.SD])
    .to_ard()
)
```

Lab toxicity grades (CTCAE):

```python
ard = (
    adlb.tlg.lb
    .population(adsl, adsl_filter=pl.col("SAFFL") == "Y")
    .filter(pl.col("PARAMCD") == "ALT")
    .by("TRTA")
    .header_rows([
        OverallStat("Any elevation",    filter=pl.col("ANRHI") == "Y"),
        OverallStat("Grade ≥ 3",        filter=pl.col("ATOXGRN") >= 3),
        OverallStat("> 3× ULN",         filter=pl.col("AVAL") > 3 * pl.col("A1HI")),
        OverallStat("> 5× ULN",         filter=pl.col("AVAL") > 5 * pl.col("A1HI")),
        OverallStat("> 10× ULN",        filter=pl.col("AVAL") > 10 * pl.col("A1HI")),
    ])
    .rows(["AVISIT"])
    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
    .to_ard()
)
```

#### Why this scales

- **No per-domain code**: `OverallStat` has no knowledge of AE, VS, ECG, or lab columns.
  It is just a filter + label + optional stat override. Domain specificity lives entirely
  in the `filter` expression the user writes.
- **`header_rows` on `TLGSpec` base**: all future sub-specs (`ECGSummarySpec`,
  `LBSummarySpec`, …) inherit it without any additional code.
- **`.header_rows()` on `TLGBuilder` base**: all future sub-namespaces (`.ecg`, `.lb`, …)
  get the verb automatically.
- **Renderer contract**: `variable == ""` rows are rendered as a distinct display class —
  no indentation, no level column, optional visual separator above the hierarchy section.
  Fully domain-agnostic.

---

## Where Does This Live?

**Computation** (`fleet.tlg`): stays in Fleet — ARD schema, spec models, and pool logic
are Fleet-native. The `df.tlg` Polars namespace entry point is preserved.

**Rendering** (`fleet.tlg.render`): new sub-module under Fleet. Pure output layer — ARD in,
artifact out. Extractable to a standalone `fleet-render` companion package later if
non-Fleet users need it.

```
fleet/tlg/render/
  __init__.py
  _models.py     — RenderMetadata, TableModel, ListingModel  (shared by all renderers)
  html.py        — pharma-style HTML table renderer + HTML injection support
  pdf.py         — HTML → PDF via WeasyPrint  (optional dep)
  slides.py      — table/listing → slide deck  (format decided in Phase 6b)
```

**HTML injection**: `html.py` accepts an optional `html_wrapper` string parameter. If
given, the generated `<table>` block is injected at a `{table}` placeholder, letting
users embed outputs in sponsor portals, Quarto documents, or interactive dashboards without
post-processing.

**Slides format candidates** (decided in Phase 6b):

| Format            | Library         | Notes                                                  |
| ----------------- | --------------- | ------------------------------------------------------ |
| **PPTX**          | `python-pptx`   | Standard for sponsor review decks; full layout control |
| **HTML slides**   | Native HTML+CSS | Lightweight; Marp/Quarto-compatible; no extra dep      |
| **PDF landscape** | WeasyPrint      | Reuses PDF infrastructure; no additional dep           |

---

## Full Step List (All Phases)

### Phase 0a — Filter rename: `adsl_filter` + `dataset_filter`

1. `_specs.py`: remove `filter`; add `adsl_filter: pl.Expr | None = None` and
   `dataset_filter: pl.Expr | None = None` to `TLGSpec`. Both `None` by default — when
   `None`, no filter is applied (no sentinel value required).
2. `ae_namespace.py` (and future `vs_namespace.py`): pass `spec.adsl_filter` to
   `compute_big_n()` (replaces `filter_expr`); apply `spec.dataset_filter` to `self._df`
   only, before any computation. Neither propagates to the other.
3. Update all tests and `tlg_ae_example.py` that referenced `spec.filter`.

### Phase 0b — Inline fluent builder: `TLGBuilder`

4. Add `src/fleet/tlg/_builder.py`: `TLGBuilder` base class with verbs:
   - `.population(adsl, adsl_filter=None)` — stores ADSL + population filter
   - `.filter(expr)` — stores `dataset_filter`
   - `.by(col)` — stores `group1`
   - `.by2(col)` — stores `group2`
   - `.header_rows(overallstats)` — stores `OverallStat` list (see Phase 0c)
   - `.rows(fields)` — stores variable hierarchy (1 or 2 fields)
   - `.stats(statistics)` — stores stat list
   - `.pools(pools)` — stores pool definitions
   - `.column_order(order)` — stores display order
   - `.fmt(mapping)` — overrides per-stat `fmt_fn`
   - `.to_ard()` — materialises by constructing equivalent spec and calling `t_summary()`
   - `.to_spec()` — serialises accumulated state to the equivalent spec YAML
5. Each sub-namespace (`AETLGNamespace`, `VSTLGNamespace`) returns a `TLGBuilder`
   pre-configured with domain defaults on the first builder verb call. The existing
   `t_summary(spec=...)` path remains untouched.
6. `vs_namespace.py`: new file; `VSTLGNamespace` with `VSSummarySpec` defaults;
   required columns `["USUBJID", "TRTA", "PARAMCD", "AVISIT", "AVAL"]`.
7. `namespace.py`: add `.vs` property. `__init__.py`: export `TLGBuilder` and VS symbols.
8. Tests:
   - Builder verbs on AE and VS.
   - Builder and spec paths produce identical ARD for the same inputs.
   - `.to_spec()` round-trip: builder → spec YAML → `from_yaml()` → same ARD.

### Phase 0c — `OverallStat` header rows

9. `_specs.py`:
   - Add `OverallStat(label, filter=None, statistics=None)` Pydantic model.
   - Add `header_rows: list[OverallStat] = []` to `TLGSpec` base so all sub-specs
     (`AESummarySpec`, `VSSummarySpec`, and every future domain spec) inherit it.
10. `ae_namespace.py` (and `vs_namespace.py`): in `t_summary()`, before the hierarchy
    row loop, iterate `spec.header_rows`; for each:
    - Apply `OverallStat.filter` (if any) to the dataset.
    - Resolve effective statistics: `OverallStat.statistics or spec.statistics`.
    - Count unique subjects (or events for `N_EVENTS`) per arm.
    - Emit ARD rows with `variable=""`, `variable_level=OverallStat.label`.
    - Append before hierarchy rows so ARD order matches display order.
11. `_builder.py`: add `.header_rows(overallstats)` to `TLGBuilder` base.
12. `__init__.py`: export `OverallStat`.
13. Tests:
    - Header rows appear before hierarchy rows in ARD.
    - `filter=None` counts all subjects.
    - Per-row `statistics` override respected.
    - Spec-driven and builder paths produce identical ARD.
    - Cross-domain: works identically on VS and AE namespaces.

### Phase 1 — Lock display contract from NEST AET01

- Define display contract: title/subtitle, arm headers with N, left-stub labels,
  indentation rules, right-aligned numeric cells, section divider rows, footnotes.
- Map ARD fields to display roles: `group1_level` → column headers, `stat_fmt` → cells,
  `variable`/`variable_level` → row hierarchy, `group2`/`group2_level` → sub-rows.
- Confirm behaviour: missing values, zero counts, long-label wrapping, empty arms.

### Phase 2 — ARD → table model shaping utilities

- `render/_models.py`: `RenderMetadata`, `TableModel` (wide), `ListingModel`.
- Pure `ard_to_table_model(ard, meta)` and `listing_to_model(listing, spec, meta)`.
- Both shapers are deterministic, renderer-agnostic, and independently testable.

### Phase 3 — Pharma-style HTML renderer

- `render/html.py`: `render_summary(model, meta, *, html_wrapper=None) -> str` and
  `render_listing(model, meta, *, html_wrapper=None) -> str`.
- Summary: arm headers + N, indented row hierarchy, count/pct cells, divider rows,
  compact submission-style spacing, explicit `<style>` block.
- Listing: sponsor-style borders/alignment, print-friendly spacing.
- HTML injection: when `html_wrapper` is given, the `<table>` block is placed at the
  `{table}` placeholder in the wrapper string — enables embedding in sponsor portals,
  Quarto documents, or interactive dashboards without post-processing.

### Phase 4 — Python API on namespace and builder

- `.to_html(path=None, *, metadata=None, html_wrapper=None) -> str | None` on
  `AETLGNamespace`, `VSTLGNamespace`, and `TLGBuilder`.
- `.to_pdf(path, *, metadata=None)` — delegates to `render/pdf.py`.
- `.to_slides(path, *, format="pptx", metadata=None)` — delegates to `render/slides.py`;
  raises `NotImplementedError` until Phase 6b is implemented.
- Google-style docstrings, copy-pasteable pipeline examples.

### Phase 5 — CLI entry point

- `fleet tlg export --domain ae|vs --format html|pdf|slides`
- Options: `--title`, `--subtitle`, `--footnote`, `--output`, `--adsl` (path),
  `--data` (path to primary dataset), `--wrap` (path to HTML wrapper template).
- Log output consistent with the define-xml command pattern.

### Phase 6a — PDF via WeasyPrint

- `render/pdf.py`: calls HTML renderer, passes HTML string to WeasyPrint.
- Optional dep in `pyproject.toml`: `tlg-pdf = ["weasyprint"]`.
- Graceful `ImportError` with install hint when WeasyPrint is absent.
- Page margins, font scaling, and page-break behaviour validated for clinical review.

### Phase 6b — Slides exploration and implementation

- Evaluate three candidates:
  - **PPTX** (`python-pptx`) — standard for sponsor review decks; full layout control.
  - **HTML slides** (native HTML+CSS, Marp-compatible) — lightweight; no extra dep;
    integrates with Quarto/R Markdown pipelines.
  - **PDF landscape** (WeasyPrint + landscape CSS) — reuses Phase 6a infrastructure;
    zero additional dependency.
- Decide format based on: do users need to edit post-generation? (→ PPTX); will slides
  live in web/Quarto pipelines? (→ HTML); minimise deps? (→ PDF landscape).
- `render/slides.py`: implement chosen format; optional dep added only if PPTX is chosen.
- Document the format decision in `GUIDE.md` under the TLG section.

### Phase 7 — Tests, examples, docs, release hygiene

- Unit tests: ARD → table model, listing model, HTML structure/injection, PDF smoke,
  slides smoke, CLI arg parsing.
- Extend `tlg_ae_example.py`: builder API, HTML export with and without wrapper injection.
- Add `examples/tlg_vs_example.py`: VS inline-builder end-to-end with nesting + PDF.
- Docs: new TLG API/render page under `docs/api/`, update `mkdocs.yml` nav,
  update `docs/api/index.md`.
- Regenerate `llms.txt` — new public API surface (builder verbs, render methods, CLI).

---

## Relevant Files

- `src/fleet/tlg/_specs.py` — replace `filter` with `adsl_filter` + `dataset_filter`;
  add `OverallStat` model; add `header_rows: list[OverallStat] = []` to `TLGSpec` base
- `src/fleet/tlg/_builder.py` — new: `TLGBuilder` base class with all fluent verbs
  including `.header_rows()`
- `src/fleet/tlg/_ard.py` — no schema changes; `group2` columns already present
- `src/fleet/tlg/ae_namespace.py` — filter rename, builder wiring, `to_html`, `to_pdf`, `to_slides`
- `src/fleet/tlg/vs_namespace.py` — new: mirrors AE namespace with VS defaults
- `src/fleet/tlg/namespace.py` — add `.vs` property
- `src/fleet/tlg/__init__.py` — export `TLGBuilder`, `OverallStat`, VS symbols, render entry points
- `src/fleet/tlg/render/__init__.py` — new sub-module init
- `src/fleet/tlg/render/_models.py` — `RenderMetadata`, `TableModel`, `ListingModel`
- `src/fleet/tlg/render/html.py` — HTML renderer with injection support
- `src/fleet/tlg/render/pdf.py` — WeasyPrint wrapper (optional dep)
- `src/fleet/tlg/render/slides.py` — slide deck renderer (format decided in Phase 6b)
- `src/fleet/cli.py` — `fleet tlg export` command
- `tests/unit/test_tlg_namespace.py` — extend for filter rename + builder + C3 tests
- `examples/tlg_ae_example.py` — extend with builder API, C3 pattern, HTML export
- `examples/tlg_vs_example.py` — new: VS inline-builder end-to-end
- `pyproject.toml` — `tlg-pdf` and optionally `tlg-slides` optional deps
- `mkdocs.yml` + `docs/api/index.md` — docs nav and API landing updates

---

## Verification

1. `uv run ruff check && uv run ruff format --check`
2. `uv run pytest`
3. All example scripts:
   - `uv run python examples/full_pipeline_example.py`
   - `uv run python examples/cdiscpilot01_inline.py`
   - `uv run python examples/cdiscpilot01_spec_driven.py`
   - `uv run python examples/adnca_example.py`
   - `uv run python examples/tdd_example.py`
   - `uv run python examples/tlg_ae_example.py`
   - `uv run python examples/tlg_vs_example.py` (after Phase 0b)
4. `uv run python scripts/build_llms.py && uv run python scripts/build_llms.py --check`
5. `uv run --extra docs mkdocs build --clean`

---

## Decisions

- **A**: `adsl_filter` + `dataset_filter` replace `filter`; both `None` by default.
  `None` means no condition — no sentinel required.
- **B**: B2 fluent builder is the chosen inline path; B1 (NestedRow) and B3 (FunctionStat)
  are dropped. `TLGBuilder` is a shared base composed into every sub-namespace. Verb set
  is a direct down-product of the ARD schema column list. Two-element `.rows()` list drives
  the `group2` nesting that B1 would have added via NestedRow.
- **C**: C3 pre-merge pattern is the documented approach; no `stratify_by` field or
  `TLGContext` object added.
- **D**: `OverallStat` model on `TLGSpec` base; `header_rows` field inherited by all
  domain sub-specs automatically. `.header_rows()` verb on `TLGBuilder` base. ARD contract:
  `variable=""`, `variable_level=label`, emitted before hierarchy rows. `statistics`
  override per row; defaults to spec-level statistics. No per-domain code required for
  any future domain (VS, ECG, LB, CM, …).
- **Location**: `fleet.tlg` stays in Fleet; `fleet.tlg.render` is the rendering sub-module;
  extractable to `fleet-render` if/when non-Fleet users need it.
- **Slides**: format decided in Phase 6b (PPTX, HTML slides, or PDF landscape).
- Out of scope: RTF, non-AE/VS domains at this stage, `TLGContext`, ARD schema changes.
