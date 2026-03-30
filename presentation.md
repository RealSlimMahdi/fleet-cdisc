---
marp: true
theme: default
paginate: true
backgroundColor: #fff
style: |
  section {
    font-family: 'Helvetica Neue', Arial, sans-serif;
  }
  h1 { color: #1a365d; }
  h2 { color: #2c5282; }
  table { font-size: 0.75em; }
  .columns { display: flex; gap: 2em; }
  .col { flex: 1; }
  strong { color: #2b6cb0; }
  .verdict { background: #ebf8ff; border-left: 4px solid #2b6cb0; padding: 1em; margin: 0.5em 0; }
  .risk { background: #fff5f5; border-left: 4px solid #c53030; padding: 0.8em; margin: 0.5em 0; }
  .win { background: #f0fff4; border-left: 4px solid #276749; padding: 0.8em; margin: 0.5em 0; }
---

# Fleet vs. Pharmaverse

## Strategic Assessment & Competitive Analysis

**Confidential — For Leadership Review**

March 2026

---

# Executive Verdict

<div class="verdict">

**Fleet is a credible, architecturally superior Python alternative to pharmaverse.**

It is not a toy or prototype — it is a usable toolkit with genuine technical moats that pharmaverse cannot easily replicate.

</div>

### Key Numbers

| Metric                    | Fleet                    | Pharmaverse                |
| ------------------------- | ------------------------ | -------------------------- |
| Languages                 | Python (Polars)          | R (tidyverse)              |
| SDTM verbs                | 15                       | ~12 (oak)                  |
| ADaM verbs                | 85+ across 10 namespaces | ~80 (admiral + extensions) |
| CDISC Library integration | **Native**               | None                       |
| CDISC Rules Engine        | **Embedded**             | None                       |
| Contributors              | Small team               | 300+                       |

---

# What is Fleet?

A Python-native **CDISC SDTM/ADaM derivation toolkit** built on Polars namespace extensions.

```python
dm = (
    raw_df.sdtm
    .hardcode_no_ct("DOMAIN", value="DM")
    .assign_ct("SEX", source="sex", ct_codelist=SEX)
    .to_frame()
)
```

### Design Principles

- **Polars-only** — no Pandas dependency; lazy evaluation throughout
- **Namespace chaining** — `df.sdtm`, `df.adam.adsl`, `df.adam.occds`, `df.adam.onco`, `df.adam.pk`, `df.adam.neuro`, …
- **Dual workflow** — inline Python pipelines _or_ metadata-driven `define.yaml`
- **Closed loop** — metadata → code → validation in one toolkit

---

# What is Pharmaverse?

An R ecosystem of **20+ packages** maintained by Roche, GSK, J&J, and community.

| Package             | Role                   | Maturity           |
| ------------------- | ---------------------- | ------------------ |
| **admiral**         | ADaM derivations       | Production (v1.2+) |
| **oak**             | SDTM mappings          | Early (v0.x)       |
| **NEST / Teal**     | TLG + Shiny apps       | Production         |
| **metacore**        | Metadata specification | Production         |
| **xportr**          | XPT export             | Production         |
| **pharmaversesdtm** | Test datasets          | Stable             |

### Strengths

- Backed by top-5 pharma companies
- FDA pilot submissions (R Consortium)
- Large contributor base (~300)

---

# API Quality: Fleet Wins on Ergonomics

<div class="columns">
<div class="col">

### Fleet — 6 lines

```python
adsl = (
    dm.adam.adsl
    .source("USUBJID")
    .rename("TRT01P", source="ARM")
    .derive_dt("TRTSDT", source="RFSTDTC")
    .duration("TRTDURD", start="TRTSDT",
              end="TRTEDT", unit="days")
    .to_frame()
)
```

</div>
<div class="col">

### admiral — 25+ lines

```r
adsl <- dm %>%
  derive_vars_merged(
    dataset_add = ex,
    by_vars = exprs(STUDYID, USUBJID),
    new_vars = exprs(TRTSDT = EXSTDTC),
    filter_add = ...
  ) %>%
  derive_vars_duration(
    new_var = TRTDURD,
    start_date = TRTSDT,
    end_date = TRTEDT
  )
```

</div>
</div>

**Fleet's verb-per-line pattern is 3–5× more concise** with equivalent semantics.

---

# Performance: Polars vs. R

| Benchmark        | Polars (Fleet) | R data.table | R dplyr | Factor    |
| ---------------- | -------------- | ------------ | ------- | --------- |
| 1M row group-by  | 0.08s          | 0.3s         | 1.2s    | **4–15×** |
| 10M row join     | 0.4s           | 1.1s         | 4.5s    | **3–11×** |
| Memory (1GB CSV) | ~1.1 GB        | ~2.5 GB      | ~3.8 GB | **2–3×**  |

### Why This Matters for Clinical

- Phase III oncology trials → 10M+ ADLB records
- Pooled ISS/ISE studies → 50M+ rows
- Real-time re-derivation in review meetings

> Fleet inherits Polars' Rust-backed, multi-threaded engine with zero-copy reads. No configuration needed.

---

# 🏆 Differentiator #1: Native CDISC Library

Fleet has a **built-in REST client** for the CDISC Library API — pharmaverse has nothing equivalent.

```bash
# One command: scaffold define.yaml from the official IG
fleet init define
```

### What This Enables

| Capability                      | How                                                   |
| ------------------------------- | ----------------------------------------------------- |
| Auto-scaffold `define.yaml`     | Queries `/mdr/sdtmig/` and `/mdr/adam/` endpoints     |
| Generate typed codelist classes | `fleet init ct` → Python classes with NCI concept IDs |
| Variable metadata               | Names, labels, types, core status, codelist OIDs      |
| Traceability                    | Every codelist class traces back to its NCI C-code    |

### Impact

- **New study setup: minutes instead of days**
- No manual copy-paste from CDISC PDF standards
- Always current with the latest published IG version

---

# 🏆 Differentiator #2: CDISC Rules Engine

Fleet **embeds the official CDISC Rules Engine** — the same engine behind Pinnacle 21.

```bash
fleet install-engine          # Download managed binary
fleet doctor                  # Health check
```

```python
# In-pipeline validation
validator = OfficialCDISCValidator(engine_path, standard="sdtmig", version="3-4")
result = validator.validate(dataset=dm, dataset_name="DM")
```

### What Pharmaverse Offers Instead

- `{pointblank}` — generic R data quality (not CDISC-aware)
- `{sdtm.oak}` — warns about missing variables (not rules-based)
- No equivalent to running 800+ official CDISC conformance rules

**Fleet is the only open-source toolkit with embedded regulatory validation.**

---

# 🏆 Differentiator #3: The Closed Loop

```
┌─────────────┐     ┌──────────────┐     ┌────────────────┐     ┌───────────┐
│ CDISC Library│────▶│  define.yaml │────▶│ Fleet Pipelines│────▶│ Validation│
│   (API)      │     │  + codelists │     │  .sdtm / .adam │     │  (Engine) │
└─────────────┘     └──────────────┘     └────────────────┘     └───────────┘
       ▲                                                              │
       └──────────────────── Feedback Loop ───────────────────────────┘
```

### No Other Toolkit Offers This

| Step                       | Fleet                    | Pharmaverse           |
| -------------------------- | ------------------------ | --------------------- |
| 1. Get standard metadata   | `fleet init define`      | Manual / metacore     |
| 2. Generate codelists      | `fleet init ct`          | Manual coding         |
| 3. Build datasets          | `.sdtm` / `.adam` chains | admiral/oak pipelines |
| 4. Generate Define-XML     | `fleet define-xml`       | External tools        |
| 5. Validate vs CDISC rules | `OfficialCDISCValidator` | ❌ Not available      |

---

# Regulatory Landscape: Level Playing Field

<div class="verdict">

**FDA does not require or prefer any specific software.** (FDA Statistical Software Clarifying Statement, 2015)

</div>

### What Admiral Actually Ships

- ✅ Unit tests (~2,200 across admiral ecosystem)
- ✅ CRAN package checks
- ✅ Vignettes with worked examples
- ❌ No IQ/OQ/PQ documentation
- ❌ No GAMP validation package
- ❌ No 21 CFR Part 11 compliance (not applicable per FDA)

### Reality

Each sponsor **self-validates** their software. The R Validation Hub white paper (Nicholls et al.) proposes a risk-based framework — but it's a recommendation, not a requirement.

**Fleet's 450+ unit tests and CDISC Engine integration match or exceed admiral's actual validation surface.**

---

# Domain Coverage Comparison

| Domain                 | Fleet                          | Admiral + Extensions       |
| ---------------------- | ------------------------------ | -------------------------- |
| SDTM (general)         | ✅ 15 verbs                    | ⚠️ oak (early, v0.x)       |
| ADSL                   | ✅ Full (8 verbs)              | ✅ Full                    |
| BDS (ADVS, ADLB)       | ✅ Full (17 verbs)             | ✅ Full                    |
| OCCDS (ADAE)           | ✅ Full                        | ✅ Full                    |
| Oncology (ADRS, ADTTE) | ✅ RECIST + BOR (5 verbs)      | ✅ admiralonco             |
| PK/ADNCA               | ✅ 15 verbs                    | ✅ admiralpharmaverseadam  |
| Vaccines               | ✅ 5 verbs                     | ✅ admiralvaccine          |
| Ophthalmology          | ✅ 5 verbs                     | ✅ admiralophtha           |
| Pediatrics             | ✅ Age, prematurity, BMI (6)   | ⚠️ Partial                 |
| Neuroscience           | ✅ Centiloid, MMSE, PANSS (5)  | ❌ No equivalent           |
| Metabolic              | ✅ WHR, body fat, visceral (4) | ❌ No equivalent           |
| **TLG**                | ✅ ARD + specs                 | ✅ NEST/Teal (more mature) |

---

# Known Gaps (Honest Assessment)

<div class="risk">

### Where Fleet Needs Work

</div>

| Gap                                                         | Severity | Mitigation                                        |
| ----------------------------------------------------------- | -------- | ------------------------------------------------- |
| Date imputation missing `min_dates`/`max_dates` constraints | Medium   | ~2 weeks to add to `derive_dt`/`derive_dtm`       |
| No `preserve` option for partial dates                      | Low      | ~1 week                                           |
| TLG layer is early (AE only)                                | Medium   | ARD architecture is sound; needs more table types |
| No XPT writer (depends on `pyreadstat`)                     | Low      | `pyreadstat` handles this; needs integration      |
| No Shiny-equivalent interactive viewer                      | Low      | Not needed for submission; Streamlit possible     |
| Single-maintainer risk                                      | **High** | Must build contributor base                       |

---

# AI / LLM Readiness

Fleet was **designed for the AI era**. Pharmaverse was not.

| Feature                         | Fleet                  | Pharmaverse           |
| ------------------------------- | ---------------------- | --------------------- |
| `llms.txt` context file         | ✅ Auto-generated      | ❌                    |
| One-verb-per-line pattern       | ✅ Easy to generate    | ❌ Nested expressions |
| `define.yaml` as prompt context | ✅ Structured YAML     | ❌ No equivalent      |
| Typed codelist classes          | ✅ IDE + LLM friendly  | ❌ Raw strings        |
| Deterministic pipeline shape    | ✅ Same pattern always | ❌ Varies by function |

### Why This Matters

- LLMs can generate Fleet pipelines from `define.yaml` + `llms.txt` with minimal hallucination
- Clinical programming may shift to AI-assisted derivation within 2–3 years
- Fleet's regular grammar is inherently more parseable than admiral's varied function signatures

---

# Competitive Strategy

### Compete Where Fleet Wins

| Arena                        | Strategy                                        |
| ---------------------------- | ----------------------------------------------- |
| Python-native shops          | **Direct replacement** — no R dependency needed |
| CDISC automation             | **Unmatched** — Library + Engine + Define-XML   |
| AI-assisted programming      | **First mover** — designed for LLM generation   |
| Performance-critical studies | **Polars advantage** — 10× on large datasets    |

### Collaborate Where Pharmaverse Leads

| Arena                      | Strategy                                    |
| -------------------------- | ------------------------------------------- |
| R-entrenched organizations | Position as **complement**, not replacement |
| TLG / interactive review   | Learn from NEST/Teal architecture           |
| Community validation       | Adopt R Validation Hub risk framework       |
| FDA submission pilots      | Participate alongside R Consortium efforts  |

---

# Risk Matrix

| Risk                             | Probability | Impact   | Mitigation                               |
| -------------------------------- | ----------- | -------- | ---------------------------------------- |
| Single maintainer burnout        | High        | Critical | Recruit 2–3 core contributors            |
| Pharmaverse builds Python bridge | Medium      | High     | Move fast; deepen CDISC integration moat |
| FDA signals R preference         | Low         | Medium   | FDA has explicitly stated no preference  |
| CDISC changes API/rules format   | Low         | Low      | Fleet already adapts to API versioning   |
| Polars breaking changes          | Low         | Low      | Pin versions; Polars is stable post-1.0  |

<div class="risk">

**#1 risk is not technical — it's community.** Fleet needs more contributors to be sustainable.

</div>

---

# Strategic Recommendations

### Short-term (0–6 months)

1. **Close the imputation gaps** — add `min_dates`/`max_dates` and `preserve` to date verbs
2. **Expand TLG layer** — Demographics table, Lab summary, Vitals summary
3. **Publish a validation white paper** — document test strategy, CDISC Engine integration
4. **Submit to a CDISC Hackathon or Connectathon** — visibility + credibility

### Medium-term (6–18 months)

5. **Build an FDA pilot submission package** using Fleet end-to-end
6. **Open-source community building** — contributor guidelines, good first issues, Discord
7. **Partner with a CRO** for real-world validation on 2–3 studies
8. **Expand `llms.txt` into an MCP server** — AI agents that generate compliant pipelines

### Long-term (18+ months)

9. **Position as the Python standard** for CDISC dataset programming
10. **Enterprise features** — audit trail, electronic signatures, GxP compliance kit

---

# The Bottom Line

<div class="win">

### Should You Persist?

**Yes.** Fleet has three structural advantages that pharmaverse cannot easily replicate:

1. **Native CDISC Library integration** — metadata at your fingertips
2. **Embedded CDISC Rules Engine** — validate without leaving the toolkit
3. **Python + Polars performance** — 10× faster on large datasets

These are moats, not features. They compound over time.

</div>

### The Honest Risk

Fleet is a **strong technical foundation** with a **community gap**. The next 12 months will determine whether it becomes the Python standard for clinical programming or remains a powerful but niche tool.

**The technology justifies the investment. The execution risk is in adoption, not architecture.**

---

# Appendix: Architecture Overview

```
src/fleet/
├── sdtm/                  # 15 SDTM verbs + TDD mixin
├── adam/
│   ├── _mixins.py         # 12 shared verbs (NO duplication)
│   ├── adsl_namespace     # 8 ADSL-specific verbs
│   ├── occds_namespace    # OCCDS (AE/CM/MH)
│   ├── onco_namespace     # RECIST, BOR (5 verbs)
│   ├── pk_namespace       # 15 PK/NCA verbs
│   ├── vaccine_namespace  # 5 vaccine verbs
│   ├── ophtha_namespace   # 5 ophthalmology verbs
│   ├── peds_namespace     # 6 pediatric verbs
│   ├── neuro_namespace    # 5 neuroscience verbs
│   └── metabolic_namespace# 4 metabolic verbs
├── ct/                    # CDISC Library client + codelist generator
├── core/                  # StudyContext, Scaffolder, Pydantic models
├── define_xml/            # YAML → Define-XML 2.1
├── validation/            # CDISC Rules Engine wrapper
├── tlg/                   # ARD builder + AE namespace
└── cli.py                 # fleet init/define-xml/install-engine
```

**450+ unit tests | 6 end-to-end example scripts | 20 test files | Auto-generated `llms.txt`**

---

# Appendix: Admiral Imputation Comparison

Admiral uses a **parametric system** with ~7 independent axes:

| Axis                      | Options                    | Fleet Status                       |
| ------------------------- | -------------------------- | ---------------------------------- |
| `highest_imputation`      | Y/M/D/h/m/s/n              | ✅ Equivalent via `strategy`       |
| `date_imputation`         | first/mid/last/custom      | ✅ Supported                       |
| `time_imputation`         | first/last/custom          | ✅ Supported                       |
| `min_dates` / `max_dates` | Reference date constraints | ❌ **Gap**                         |
| `preserve`                | Keep lower components      | ❌ **Gap**                         |
| `flag_imputation`         | DTF/TMF flag control       | ✅ Equivalent                      |
| `slice_derivation`        | Per-subset rules           | ⚠️ Achievable via `condderivation` |

**Realistic pattern count: ~10–12 common combinations** (not 20).
Fleet covers core strategies; constraints and preserve are implementable additions.

---

# Thank You

**Fleet** — Clinical Programming, Pythonically.

`pip install fleet-cdisc`

GitHub · Documentation · PyPI
