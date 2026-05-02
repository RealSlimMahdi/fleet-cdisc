---
marp: true
theme: default
paginate: true
backgroundColor: #F5F5F2
header: ""
footer: "Fleet — Statistical Reporting for the Python & AI Era | PHUSE 2026"
style: |
  section {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    font-size: 24px;
  }
  h1 { color: #1a365d; font-size: 1.6em; }
  h2 { color: #2c5282; font-size: 1.3em; }
  h3 { color: #2b6cb0; }
  table { font-size: 0.72em; }
  code { font-size: 0.85em; }
  pre { font-size: 0.78em; }
  strong { color: #2b6cb0; }
  footer { font-size: 0.55em; color: #718096; }
  .highlight { background: #ebf8ff; border-left: 4px solid #2b6cb0; padding: 0.8em 1em; margin: 0.5em 0; font-size: 0.9em; }
  .win { background: #f0fff4; border-left: 4px solid #276749; padding: 0.8em 1em; margin: 0.5em 0; font-size: 0.9em; }
  .warn { background: #fffaf0; border-left: 4px solid #c05621; padding: 0.8em 1em; margin: 0.5em 0; font-size: 0.9em; }
  .columns { display: flex; gap: 2em; }
  .col { flex: 1; }
  section.lead h1 { font-size: 2.2em; }
  section.lead { text-align: center; }
---

<!-- _class: lead -->
<!-- _paginate: false -->
<!-- _footer: '' -->
<!-- <style>
/* Target all slides and force override the theme */
section {
  background-color: #f4f4f4 !important;

  /* Layer 1: Roche Logo */
  /* Layer 2: Base64 Encoded SVG for the blue chevron lines */
  background-image:
    url('https://upload.wikimedia.org/wikipedia/commons/f/f5/Hoffmann-La_Roche_logo.svg'),
    url('data:image/svg+xml;base64,PHN2ZyB3aWR0aD0nMTI4MCcgaGVpZ2h0PSc3MjAnIHhtbG5zPSdodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2Zyc+PHBvbHlsaW5lIHBvaW50cz0nNjQwLDAgMTI4MCwzNjAgNjQwLDcyMCcgZmlsbD0nbm9uZScgc3Ryb2tlPScjMDA1NWJhJyBzdHJva2Utd2lkdGg9JzMnLz48L3N2Zz4=') !important;

  background-position:
    top 50px right 50px,
    center center !important;

  background-repeat: no-repeat !important;
  background-size: 130px, cover !important;
}


</style> -->
<style>
    /* 1. Register the local font file */
@font-face {
  font-family: 'Roche';
  /* The path is relative to your Markdown file */
  src: url('./assets/Roche Sans/RocheSans-Regular.otf') format('truetype');
  font-weight: normal;
  font-style: normal;
}
/* 1. GLOBAL: Logo and Background */
section {
  background-color: #f4f4f4 !important;
  background-image: url('https://upload.wikimedia.org/wikipedia/commons/f/f5/Hoffmann-La_Roche_logo.svg') !important;
  background-position: top 40px right 40px !important;
  background-repeat: no-repeat !important;
  background-size: 130px !important;
  overflow: hidden !important; 
}

/* 2. THE BLUE LINES */
/* Notice the comma: this applies the lines to BOTH classes */
section.with-lines::before,
section.chapter::before {
  content: "";
  position: absolute;
  width: 510px;
  height: 510px;
  border-top: 3px solid #0055ba;
  border-right: 3px solid #0055ba;
  transform: rotate(45deg);
  top: 50%;
  margin-top: -255px; 
  right: 106px; 
  pointer-events: none;
}

/* 3. CHAPTER DIVIDER TEXT LAYOUT */
section.chapter {
  display: flex;
  flex-direction: column;
  justify-content: center; /* The magic property that vertically centers text */
  padding-left: 100px;     /* Pushes text away from the left edge */
}

/* Make the title big, bold, and remove default margins so it centers perfectly */
section.chapter h1 {
  margin: 0;
  text-align: left;
  font-size: 3.0em; 
  font-family: 'Roche', sans-serif;
  color: #000;
}
</style>

# Fleet

### A Python-Native CDISC SDTM/ADaM Toolkit

### Built for the AI Era

<br>

**PHUSE 2026**

`pip install fleet-cdisc`

---

<!-- _class: chapter -->

# Test

---

# Agenda

1. **The Problem** — Why clinical programming needs a rethink
2. **What is Fleet?** — Philosophy & architecture
3. **Inline vs. Spec-Driven** — Two workflows, one toolkit
4. **Native CDISC Library Integration** — Metadata at your fingertips
5. **One Package, All Domains** — SDTM + ADaM + 8 TA extensions + TLG
6. **Schema & CT Validation** — Catch errors before they reach the reviewer
7. **CDISC Rules Engine** — Regulatory-grade conformance, embedded
8. **AI-First Design** — Purpose-built for LLM-assisted programming
9. **Raw-to-Render (R2R)** — From CSV to clinical table in one file
10. **Validation Strategy** — Risk-based qualification for regulated use
11. **Demo & Q&A**

---

# The Problem

### Clinical programming in 2026 still looks like 1996

- **Fragmented tooling** — SDTM in one package, ADaM in another, TLG in a third, validation elsewhere
- **Boilerplate everywhere** — 25+ lines of R/SAS for a baseline derivation
- **No metadata connection** — standards live in xlsx; code lives in scripts; they drift apart
- **AI-hostile APIs** — nested function signatures, inconsistent patterns, scattered across 20+ packages
- **Performance ceilings** — single-threaded execution on 10M+ row oncology datasets

<div class="highlight">

**What if one toolkit could handle the full lifecycle — from CDISC Library metadata to validated, rendered clinical tables — in a language AI agents already speak fluently?**

</div>

---

# What is Fleet?

A **lazy expression accumulator** with an immutable builder API that creates CDISC-compliant datasets using Polars namespace extensions.

```python
import fleet
import polars as pl
from codelists import SEX

dm = (
    raw_df.sdtm
    .hardcode_no_ct("DOMAIN",  value="DM")
    .assign_no_ct("USUBJID",   source="patient_id")
    .assign_ct("SEX", source="sex_raw", ct_codelist=SEX,
               ct_mapping={"M": "M", "F": "F"})
    .assign_dtc("RFSTDTC", source="first_dose_date")
    .to_frame()
)
```

**Nothing runs until `.to_frame()`.** All verbs accumulate into a single optimised Polars `with_columns` pass.

---

# Design Principles

| Principle                | What it means                                             |
| ------------------------ | --------------------------------------------------------- |
| **Intent-driven syntax** | Your code reads like the CDISC spec itself                |
| **Lazy evaluation**      | Zero intermediate DataFrames; one-pass execution          |
| **Polars-only**          | Rust-backed, multi-threaded engine; no Pandas             |
| **Dual workflow**        | Inline Python chaining _or_ metadata-driven `define.yaml` |
| **AI-first**             | Regular grammar, structured API, built-in `llms.txt`      |
| **Closed loop**          | Metadata → Code → Validation → Define-XML in one toolkit  |
| **Minimal footprint**    | 7 dependencies. That's it.                                |

<div class="win">

**Fleet's verb-per-line pattern is 3–5× more concise than equivalent admiral/SAS code with identical semantics.**

</div>

---

# Why Not Just Use Admiral & Oak?

Admiral and the pharmaverse are excellent — Fleet was inspired by them.

**But there Fleet is just a different paradigm in a different language: Python**

| Challenge             | Pharmaverse                            | Fleet                        |
| --------------------- | -------------------------------------- | ---------------------------- |
| Language              | R focus                                | Python (Polars)              |
| Package count         | 20-50 packages to install & coordinate | 1 import: `import fleet`     |
| CDISC Library         | No native integration                  | Built-in REST client         |
| CDISC Rules Engine    | Not available or wrapper               | Embedded                     |
| Define-XML generation | P21                                    | `fleet define-xml`           |
| AI/LLM friendliness   | Various API.                           | Regular, predictable grammar |
| Spec ↔ Code sync      | Manual                                 | `define.yaml` drives both    |
| TLG in same toolkit   | Separate ecosystem (NEST/Teal)         | `df.tlg` namespace           |

---

# Architecture at a Glance

```
┌─────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  CDISC Library  │───▶│   define.yaml     │──▶│  Fleet Pipelines │
│  (REST API)     │     │   + codelists.py │     │  .sdtm / .adam   │
└─────────────────┘     └──────────────────┘     └────────┬─────────┘
                                                          │
                    ┌─────────────────────────────────────┤
                    ▼                    ▼                 ▼
            ┌──────────────┐   ┌──────────────┐   ┌─────────────────┐
            │  Define-XML  │   │  Validation  │   │  TLG (ARD →     │
            │  2.1 Export  │   │  (CDISC CORE)│   │  HTML/PDF/PPTX) │
            └──────────────┘   └──────────────┘   └─────────────────┘
```

A **closed loop** from authoritative metadata to validated, rendered outputs — in one package.

---

# Namespace Extensions

Importing `fleet` registers chainable namespaces on **every** Polars DataFrame:

| Namespace                 | Target                 | Verb count                        |
| ------------------------- | ---------------------- | --------------------------------- |
| `df.sdtm`                 | SDTM domains           | 14 + 4 TDD                        |
| `df.adam`                 | ADaM BDS (ADVS, ADLB…) | 28 (17 specific + 11 shared)      |
| `df.adam.adsl`            | ADSL                   | 20 (9 specific + 11 shared)       |
| `df.adam.occds`           | OCCDS (ADAE, ADCM…)    | 15 (3 specific + 11 shared + seq) |
| `df.adam.onco`            | Oncology               | 16 (RECIST, BOR)                  |
| `df.adam.pk`              | Pharmacokinetics       | 27 (ADNCA pipeline)               |
| `df.adam.ophtha`          | Ophthalmology          | 16 (ETDRS/LogMAR)                 |
| `df.adam.vaccine`         | Vaccine                | 16 (seroconversion)               |
| `df.adam.peds`            | Pediatrics             | 17 (age, prematurity)             |
| `df.adam.neuro`           | Neuroscience           | 16 (Centiloid, MMSE)              |
| `df.adam.metabolic`       | Metabolic              | 15 (waist ratios, body fat)       |
| `df.tlg.ae` / `df.tlg.vs` | TLG                    | ARD + render                      |

---

# How the Pipeline Works

Every verb accumulates `pl.Expr` objects. Nothing executes until `.to_frame()`:

```
df.sdtm
  │
  ├─ .assign_no_ct("USUBJID", ...)  →  [Expr("patient_id".alias("USUBJID"))]
  ├─ .assign_ct("SEX", ...)         →  [..., Expr(when/then.alias("SEX"))]
  ├─ .assign_dtc("RFSTDTC", ...)    →  [..., Expr(strptime.alias("RFSTDTC"))]
  └─ .to_frame()
       └─ df.with_columns(*exprs)   ← single Polars pass, multi-threaded
```

- **No intermediate DataFrames** — saves memory
- **Polars query optimisation** — predicate pushdown, projection pruning
- **Expression ordering mirrors declaration** — what you write is what you get

---

# Workflow 1: Inline (Code-Driven)

Best for: exploration, ad-hoc analysis, smaller studies, rapid prototyping.

```python
from specs.cdiscpilot01.sdtm.codelists import SEX, RACE, ETHNIC

dm = (
    dm_raw.sdtm
    .hardcode_no_ct("STUDYID", value="CDISCPILOT01")
    .hardcode_no_ct("DOMAIN",  value="DM")
    .assign_no_ct("USUBJID",   source="patient_number")
    .assign_ct("SEX",  source="sex",  ct_codelist=SEX,
               ct_mapping={"F": "F", "M": "M"})
    .assign_ct("RACE", source="race", ct_codelist=RACE)
    .assign_dtc("RFSTDTC", source="first_dose_date")
    .to_frame()
)
```

Every derivation is explicit, visible, and traceable in the script.

---

# Workflow 2: Spec-Driven (`define.yaml`)

Best for: production trials, regulatory submissions, team collaboration.

```yaml
datasets:
  - name: DM
    variables:
      - name: STUDYID
        derivation: { algorithm: hardcode_no_ct, value: "CDISCPILOT01" }
      - name: SEX
        derivation:
          algorithm: assign_ct
          source: sex
          ct_codelist: C66731
          ct_mapping: { "F": "F", "M": "M" }
      - name: RFSTDTC
        derivation: { algorithm: assign_dtc, source: first_dose_date }
```

Execute in one line:

```python
dm = dm_raw.sdtm.from_spec("define.yaml", dataset="DM").to_frame()
```

**One file drives both the pipeline code _and_ Define-XML generation.**

---

# The Hybrid Escape Hatch

For the 90% that fits a spec, let `define.yaml` handle it. For the 10% of complex logic, drop to native Polars and resume:

```python
# Standard derivations from the spec
base_adsl = ctx.build("ADSL")

# Custom edge-case logic in pure Polars
complex_flag = (
    base_adsl.select(["USUBJID", "TRTSDT"])
    .join(ae_df.filter(pl.col("AESEV") == "SEVERE"), on="USUBJID")
    .group_by("USUBJID")
    .agg(pl.lit("Y").alias("CUSTFL"))
)
merged = base_adsl.join(complex_flag, on="USUBJID", how="left")

# Resume Fleet for finalisation
final = (
    merged.adam.adsl
    .derivation("CUSTFL", expression=pl.col("CUSTFL").fill_null("N"))
    .to_frame()
)
```

**You are never bottlenecked by the API.** If you can write it in Polars, you can use it in Fleet.

---

# Native CDISC Library Integration

Fleet is the **first open-source toolkit** with a built-in CDISC Library REST client.

### Three-command study bootstrap

```bash
# 1. Scaffold study structure + study_config.yaml
fleet init cfg --study-id CDISCPILOT01 --domains DM,AE,VS,EX

# 2. Generate define.yaml from the official CDISC IG model
fleet init define

# 3. Generate typed Python codelist classes from NCI concept IDs
fleet init ct
```

### What this produces

- `study_config.yaml` — study metadata and path configuration
- `define.yaml` — variable names, labels, types, core status, codelist OIDs
- `codelists.py` — typed Python classes with IDE auto-completion

**New study setup: minutes instead of days. No manual copy-paste from CDISC PDFs.**

---

# Generated Codelist Classes

```python
# codelists.py — auto-generated from the CDISC Library
class C66731:
    """SEX (C66731) — Sex or gender of the subject."""
    _concept_id = "C66731"
    F = "F"
    M = "M"
    U = "U"

SEX = C66731     # Human-readable alias
RACE = C74457    # ...
```

### Why this matters

- **IDE auto-completion** — `SEX.` shows all valid submission values
- **No raw NCI codes** — `ct_codelist=SEX` instead of `ct_codelist="C66731"`
- **Traceability** — `_concept_id` flows into Define-XML and validation
- **Version-pinned** — `--package sdtmct-2025-09-26` for reproducible builds
- **Incremental** — `fleet add-ct --domains LB,CM` preserves existing codelists

---

# Schema & CT Validation

Fleet validates at **two layers** — catching errors before data ever reaches a reviewer.

### Layer 1: Pydantic model validation (build-time)

```python
dm = raw_df.sdtm.from_spec("define.yaml", dataset="DM")
# ↑ Raises pydantic.ValidationError IMMEDIATELY if:
#   - assign_ct is missing ct_codelist
#   - Unknown algorithm name
#   - Wrong field types
```

### Layer 2: JSON Schema + business rules (on-demand)

```python
from fleet.define_xml import DefineValidator

validator = DefineValidator()
validator.validate(Path("define.yaml"))
for issue in validator.issues:
    print(f"[{issue.severity}] {issue.rule} @ {issue.location}: {issue.message}")
# [ERROR] SCHEMA_001 @ datasets.0.variables.2: 'type' is a required property
```

**Editors with YAML Language Server get inline error highlighting for free.**

---

# Embedded CDISC Rules Engine

Fleet wraps the **official CDISC CORE Rules Engine** — the same engine behind Pinnacle 21.

```bash
fleet install-engine    # Download the managed binary
fleet doctor            # Health check: engine, pyreadstat, env vars
```

```python
from fleet import ValidationService

svc = ValidationService()
result = svc.validate_sdtm(dm, domain="DM", version="3.4")
result.print_report()                          # Console output
result.save_html_report("dm_validation.html")  # Archivable HTML
assert result.is_valid
```

### Engine discovery chain (first match wins)

1. `FLEET_RULES_ENGINE` environment variable
2. `validation.engine_path` in `study_config.yaml` (shared across team)
3. Managed install from `fleet install-engine`
4. Legacy development fallback

---

# Define-XML 2.1 Generation

Generate regulatory-ready Define-XML directly from the same `define.yaml` that drives your pipelines:

```bash
fleet define-xml --spec specs/sdtm/define.yaml --output define_sdtm.xml
```

```python
from fleet import DefineXMLGenerator

gen = DefineXMLGenerator("specs/adam/define.yaml")
gen.write("outputs/define_adam.xml")
```

### Key point

Your `define.yaml` is the **single source of truth** for:

- Pipeline derivation logic (what `.from_spec()` executes)
- Define-XML structural metadata (what the reviewer sees)
- Controlled terminology references (what validation checks)

**Spec, code, and documentation are never out of sync.**

---

# AI-First Architecture

Fleet was **designed for the AI era from day one**.

| Feature                          | Why it matters for LLMs                                    |
| -------------------------------- | ---------------------------------------------------------- |
| **One import**                   | `import fleet` — no 20-package dependency tree to discover |
| **One verb per line**            | Predictable, regular grammar → fewer hallucinations        |
| **`define.yaml` as context**     | Structured YAML → perfect prompt input                     |
| **Typed codelist classes**       | IDE + LLM-friendly; no memorising NCI codes                |
| **Built-in `llms.txt`**          | Full API surface in one context file                       |
| **Deterministic pipeline shape** | Same pattern every time → consistent generation            |
| **Token efficiency**             | Fleet is concise → resulting in less context bloat.        |

<div class="highlight">

**An LLM can generate a complete Fleet pipeline from `define.yaml` + `llms.txt` with minimal hallucination — because the API was designed for exactly this use case.**

</div>

---

# AI Feedback Loop

The real power is the **tight feedback cycle** between agent and toolkit:

```
┌────────────────┐     ┌──────────────────┐     ┌───────────────────┐
│  LLM / Agent   │────▶│  Fleet Pipeline  │──▶│  Validation       │
│  generates code│     │  from define.yaml │    │  (Schema + CORE)  │
└────────────────┘     └──────────────────┘     └───────┬───────────┘
       ▲                                                │
       └──── Structured error arrays ───────────────────┘
```

1. Agent reads `define.yaml` + `llms.txt` → generates pipeline
2. Pydantic catches spec errors **immediately** (no data needed)
3. CDISC CORE catches data conformance issues → **structured JSON errors**
4. Agent reads errors → fixes → re-runs

**Errors are machine-parseable, not buried in SAS logs or R warnings.**

---

# One Package for All Statistical Programming 1/2

### SDTM — 14 verbs + Trial Design Domains

`assign_no_ct` · `assign_ct` · `assign_dtc` · `hardcode_ct` · `hardcode_no_ct` · `condition_add` · `if_then_else` · `ae_aerel` · `merge` · `remove_dup` · `group_by` · `dataset_level` · `notsubmitted` · `multiple_responses`

### ADaM — 11 shared verbs inherited by ALL sub-namespaces

`source` · `derivation` · `assigned` · `recode` · `rename` · `condderivation` · `whereclauses` · `merge_adsl` · `derive_dt` · `derive_dtm` · `format_iso`

---

# One Package for All Statistical Programming 2/2

### Therapeutic Area Extensions (mirror admiral TA packages)

| TA            | Verbs                                                                       | Examples   |
| ------------- | --------------------------------------------------------------------------- | ---------- |
| Oncology      | `aval_resp` · `best_overall_response` · `confirmed_response_flag`           | RECIST BOR |
| PK            | `blq_flag` · `blq_impute` · `nominal_time` · `dose_normalized` · `log_conc` | ADNCA      |
| Vaccine       | `fever_flag` · `seroconversion_flag` · `aval_adis`                          | ADIS       |
| Ophthalmology | `etdrs_to_logmar` · `study_eye` · `bcva_criterion`                          | ADBCVA     |
| Neuroscience  | `centiloid` · `mmse_category` · `cdrsob_total` · `panss_total`              | ADQS       |

---

# Trial Design Domains (TDD)

First-class support for all **7 CDISC TDD domains** with rich Pydantic models:

```python
from fleet.sdtm.tdd import TrialElement, TrialElements, Epoch

te_rows = TrialElements(elements=[
    TrialElement(etcd="SCRN", element="Screening",
                 tedur="P14D", epoch=Epoch.SCREENING),
    TrialElement(etcd="TRT",  element="Treatment",
                 tedur="P84D", epoch=Epoch.TREATMENT),
])

te = (
    pl.DataFrame().sdtm
    .fetch_structure("TE", ig_version="3-4")
    .study_header(study_id="CDISCPILOT01", domain="TE")
    .add_elements(te_rows)
    .to_frame()
)
```

- **Collection-level validators** — duplicate ETCD? `ValueError` at construction time
- **Foreign-key validation** — `.add_arms(ta_rows, te=te_rows)` checks TA.ETCD ∈ TE.ETCD
- **Mermaid parser** — parse a flowchart directly into TE/TA collections

---

# TLG: Analysis Results Datasets (ARD)

Fleet's `df.tlg` namespace produces **ARDs** — long-format DataFrames aligned to CDISC ARS / pharmaverse {cards}.

<div class="columns">
<div class="col">

### Inline builder

```python
ard = (
    adae.tlg.ae
    .population(adsl,
        adsl_filter=pl.col("SAFFL") == "Y")
    .by("TRTA")
    .header_rows([
        OverallStat(label="Any AE"),
        OverallStat(label="SAEs",
            filter=pl.col("AESER") == "Y"),
    ])
    .rows(["AEBODSYS", "AEDECOD"])
    .stats([Statistic.N_SUBJECTS,
            Statistic.N_PCT])
    .pools([GroupPool(label="Total",
                      arms="*")])
    .to_ard()
)
```

</div>
<div class="col">

### Spec-driven

```python
spec = AESummarySpec(
    adsl_filter=pl.col("SAFFL") == "Y",
    header_rows=[
        OverallStat(label="Any AE"),
        OverallStat(label="SAEs",
            filter=pl.col("AESER") == "Y"),
    ],
    pools=[GroupPool(label="Total",
                     arms="*")],
)
ard = adae.tlg.ae.t_summary(
    groupby="TRTA",
    adsl=adsl,
    spec=spec,
)
```

</div>
</div>

Both paths produce the **same ARD** — render to HTML, PDF, or PPTX.

---

# TLG Rendering: HTML, PDF, PPTX

```python
from fleet.tlg import RenderMetadata, ard_to_table_model, render_html

meta = RenderMetadata(
    title="Table 14.3.1.1",
    subtitle="AE Summary — Safety Population",
    footnotes=["Source: ADAE", "Population: Safety"],
)
html = render_html(ard_to_table_model(ard, meta))
```

### CLI export

```bash
# HTML
fleet tlg export --domain ae --data adae.csv --adsl adsl.csv --output ae.html

# PDF (requires weasyprint)
fleet tlg export --domain ae --format pdf --data adae.csv --adsl adsl.csv --output ae.pdf

# Editable PowerPoint slides (requires python-pptx)
fleet tlg export --domain ae --format pptx --data adae.csv --adsl adsl.csv --output ae.pptx
```

**HTML injection** into sponsor portal templates: `--wrap portal_template.html`

---

# Raw-to-Render (R2R) Strategy

**One file. One domain. Raw to rendered table.**

```
ADSL (pre-built) ──────────────────────┐
                                        ▼
Raw AE CSV → SDTM AE → ADaM ADAE → Validate → TLG (HTML)
```

### The traditional model: 4 separate programs

| Program      | Input → Output         | Owner           |
| ------------ | ---------------------- | --------------- |
| `ae.sas`     | Raw AE → SDTM AE       | SDTM programmer |
| `adae.sas`   | SDTM AE + ADSL → ADAE  | ADaM programmer |
| `v_adae.sas` | ADAE → Validation log  | QC programmer   |
| `t_ae.sas`   | ADAE + ADSL → AE table | TLG programmer  |

### The R2R model: 1 script

```bash
uv run python r2r_ae.py
# → SDTM AE → ADAE → Validate → ae_summary.html
```

When cell (3,2) in the table looks wrong, scroll up — the derivation is in the same file.

---

# R2R: Purpose-Built for AI Agents

| Property                     | Why it helps                                            |
| ---------------------------- | ------------------------------------------------------- |
| **Single-context reasoning** | Entire derivation fits in one prompt                    |
| **End-to-end generation**    | Agent generates complete R2R script in one pass         |
| **Instant feedback**         | Script produces visible HTML output → inspect & iterate |
| **Self-documenting**         | Layered structure doubles as executable documentation   |
| **Deterministic**            | One command reproduces the full artefact                |

### Agent prompt pattern

> _"Using Fleet's R2R pattern, write a single Python script that takes `ae_raw.csv` and a pre-built ADSL and produces an HTML AE summary table (Table 14.3.1.1). Include SDTM AE, ADAE with treatment-emergent flags, pre-validation, and rendered HTML output."_

The agent returns a **complete, runnable script**. No follow-up questions needed.

---

# Performance: Polars Advantage

| Benchmark        | Polars (Fleet) | R data.table | R dplyr | Factor    |
| ---------------- | -------------- | ------------ | ------- | --------- |
| 1M row group-by  | 0.08s          | 0.3s         | 1.2s    | **4–15×** |
| 10M row join     | 0.4s           | 1.1s         | 4.5s    | **3–11×** |
| Memory (1GB CSV) | ~1.1 GB        | ~2.5 GB      | ~3.8 GB | **2–3×**  |

### Why this matters for clinical programming

- **Phase III oncology** → 10M+ ADLB records
- **Pooled ISS/ISE** → 50M+ rows
- **Real-time re-derivation** in review meetings
- **CI/CD pipelines** where speed = developer productivity

Fleet inherits Polars' Rust-backed, multi-threaded engine with zero-copy reads. No configuration needed.

---

# Validation Strategy

Fleet's qualification follows the **R Validation Hub risk-based framework** — built on four pillars:

### Pillar 1: CDISC Library Traceability

`CDISC Library API → define.yaml → codelists.py → pipeline code → output dataset`
Every link is a versioned, reviewable artefact.

### Pillar 2: Admiral Parity Testing

400+ tests benchmark Fleet against documented `{admiral}` algorithm specs.
BSA, MAP, QTc, age conversion, ANL01FL, LOCF, summary records — numerically identical results.

### Pillar 3: CDISC Rules Engine (CORE)

800+ official conformance rules. Same engine as Pinnacle 21.

### Pillar 4: Automated Test Suite

540+ unit tests · Ruff static analysis · 7 end-to-end example scripts.

<div class="highlight">

**FDA does not require or prefer any specific software.** Sponsors self-validate; Fleet provides the tools to do so rigorously.

</div>

---

# Conciseness Comparison

<div class="columns">
<div class="col">

### Fleet — 7 lines

```python
adsl = (
    dm.adam.adsl
    .source("USUBJID")
    .rename("TRT01P", source="ARM")
    .first_date("TRTSDT",
        from_dataset=ex, date_col="EXSTDTC")
    .last_date("TRTEDT",
        from_dataset=ex, date_col="EXENDTC")
    .duration("TRTDURD",
        start_date="TRTSDT", end_date="TRTEDT")
    .to_frame()
)
```

</div>
<div class="col">

### admiral — ~30 lines

```r
adsl <- dm %>%
  derive_vars_merged(
    dataset_add = ex,
    by_vars = exprs(STUDYID, USUBJID),
    new_vars = exprs(TRTSDT = EXSTDTC),
    filter_add = ...
  ) %>%
  derive_vars_merged(
    dataset_add = ex,
    by_vars = exprs(STUDYID, USUBJID),
    new_vars = exprs(TRTEDT = EXENDTC),
    ...
  ) %>%
  derive_vars_duration(
    new_var = TRTDURD,
    start_date = TRTSDT,
    end_date = TRTEDT
  )
```

</div>
</div>

**Same semantics. 3–5× fewer lines. One verb per derivation.**

---

# Full ADAE Pipeline — From SDTM to Flagged

```python
# SDTM AE → ADaM ADAE in one continuous chain
adae = (
    ae_with_trt.adam
    .source("STUDYID").source("USUBJID").source("AETERM").source("TRTA")
    .derive_dt("ASTDT", source="AESTDTC")
    .study_day("ADY", analysis_date="ASTDT", reference_date="TRTSDT")
    .to_frame()
    .adam.occds
    .treatment_emergent("TRTEMFL",
        start_date="AESTDTC", trtsdt="TRTSDT", trtedt="TRTEDT")
    .recode("AESEVN", source="AESEV",
        recode_map={"MILD": 1, "MODERATE": 2, "SEVERE": 3})
    .flag("ANL01FL", criteria="max",
        value_col="AESEVN",
        groups=["USUBJID", "AETERM"])
    .seq("ASEQ", groups=["USUBJID"])
    .to_frame()
)
```

Treatment-emergent flag, worst-severity flag, and sequence number — all in Fleet's OCCDS namespace.

---

# Pipeline Debugging: `.inspect()` and `.explain()`

Both SDTM and ADaM namespaces expose chainable debug verbs:

```python
adsl = (
    dm.adam.adsl
    .source("USUBJID")
    .rename("TRT01P", source="ARM")
    .inspect("After demographics")   # ← prints schema + shape + head
    .first_date("TRTSDT", from_dataset=ex, date_col="EXSTDTC")
    .explain()                       # ← prints Polars query plan
    .duration("TRTDURD", start_date="TRTSDT", end_date="TRTEDT")
    .to_frame()
)
```

- **`.inspect()`** — materialises at that point; prints diagnostic output; returns fresh namespace
- **`.explain()`** — prints query plan without executing; returns `self` unchanged

Isolate exactly which derivation step introduced bad data — without leaving the chain.

---

# Extensibility

### Custom derivations — use native Polars expressions

```python
adsl = (
    dm.adam.adsl
    .derivation("AGEGR1", expression=(
        pl.when(pl.col("AGE") < 18).then(pl.lit("<18"))
          .when(pl.col("AGE") <= 65).then(pl.lit("18-65"))
          .otherwise(pl.lit(">65"))
    ))
    .to_frame()
)
```

### Subclass namespaces for company-specific verbs

```python
from fleet.adam.adam_namespace import AdamNamespace

class CompanyAdamNamespace(AdamNamespace):
    def proprietary_flag(self, target: str, condition: str) -> Self:
        expr = pl.when(pl.col(condition) == "Y").then(pl.lit("Y"))
        return self._chain(expr.alias(target))
```

**Fleet is designed for extension**, not forking.

---

# Mixin Architecture: No Code Duplication

Shared verbs live **once** in `_mixins.py`. All namespaces inherit them:

```python
# _mixins.py — single source of truth
class SharedADaMVerbsMixin:
    def study_day(self, target, *, analysis_date, reference_date) -> Self: ...
    def derive_dt(self, target, *, source) -> Self: ...
    # ... 11 shared verbs

# Every namespace gets them automatically
class ADSLNamespace(SharedADaMVerbsMixin, DateDerivationMixin): ...
class OCCDSNamespace(SharedADaMVerbsMixin): ...
class OncoNamespace(SharedADaMVerbsMixin): ...
# ... 8 more
```

### The rule

> If a verb makes sense for 2+ namespaces, it **MUST** live in a mixin. Never copy implementations across namespace classes.

This keeps the codebase maintainable as TA coverage expands.

---

# Coverage Summary

| Capability                                        | Status                           |
| ------------------------------------------------- | -------------------------------- |
| SDTM general domains                              | 14 verbs                         |
| Trial Design Domains (TE, TA, TV, TS, TI, SV, SE) | 7/7 domains                      |
| ADaM ADSL                                         | 20 verbs                         |
| ADaM BDS (ADVS, ADLB)                             | 28 verbs                         |
| ADaM OCCDS (ADAE, ADCM)                           | 15 verbs                         |
| Oncology (RECIST, BOR)                            | 16 verbs                         |
| PK / ADNCA                                        | 27 verbs                         |
| Vaccines, Ophthalmology, Peds, Neuro, Metabolic   | 15–17 verbs each                 |
| TLG — AE & VS summary tables                      | ARD + HTML/PDF/PPTX              |
| Define-XML 2.1 generation                         | From `define.yaml`               |
| CDISC Library integration                         | REST client + codelist generator |
| CDISC Rules Engine                                | Embedded, managed install        |
| Schema validation                                 | Pydantic + JSON Schema           |
| Admiral parity tests                              | 400+ tests                       |

---

# The Closed Loop — Putting It All Together

```bash
# 1. Bootstrap from CDISC Library
fleet init cfg --study-id STUDY01 --domains DM,AE,VS,EX
fleet init define
fleet init ct

# 2. Build datasets (inline or spec-driven)
dm = dm_raw.sdtm.from_spec("define.yaml", dataset="DM").to_frame()
adsl = dm.adam.adsl. ... .to_frame()

# 3. Validate
svc = ValidationService()
svc.validate_sdtm(dm, domain="DM").print_report()

# 4. Generate Define-XML
fleet define-xml --spec define.yaml --output define_sdtm.xml

# 5. Render clinical tables
fleet tlg export --domain ae --data adae.csv --adsl adsl.csv --output ae.html
```

**Metadata → Code → Validation → Define-XML → TLG. One toolkit. One workflow.**

---

# Getting Started

### Install

```bash
pip install fleet-cdisc
```

### Verify

```python
import fleet
print(fleet.__version__)
```

### Resources

- **Documentation**: [realslimmahdi.github.io/fleet-cdisc](https://realslimmahdi.github.io/fleet-cdisc/)
- **GitHub**: [github.com/RealSlimMahdi/fleet-cdisc](https://github.com/RealSlimMahdi/fleet-cdisc)
- **PyPI**: [pypi.org/project/fleet-cdisc](https://pypi.org/project/fleet-cdisc/)
- **License**: MIT — fully open source
- **Python**: 3.12+

We welcome contributions, feedback, and real-world validation stories.

---

<!-- _class: lead -->

# Thank You

### Fleet — Clinical Programming, Pythonically.

<br>

`pip install fleet-cdisc`

<br>

**Questions?**
