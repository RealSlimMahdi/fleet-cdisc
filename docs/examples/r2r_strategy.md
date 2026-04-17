# Raw-to-Render (R2R) Strategy

## One file. One domain. Raw to Render.

The **Raw-to-Render** (R2R) strategy collapses the traditional multi-program pharma
workflow into a single, self-contained script that takes raw source data all the
way to a rendered clinical table:

```
ADSL (pre-built)  ─────────────────┐
                                    ▼
Raw AE CSV  →  SDTM AE  →  ADaM ADAE  →  Validate  →  TLG (HTML)
```

DM and ADSL are assumed to already exist — they are **governed, shared artefacts**
produced by separate programs. The R2R script focuses on **one domain end-to-end**:
raw AE data through SDTM, ADaM, validation, and table rendering.

Instead of maintaining separate programs for each layer — with hand-offs, naming
conventions to remember, and scattered data lineage — an R2R script keeps the
**complete derivation chain for a single domain visible in one place**.

---

## Why R2R?

### The traditional model

In conventional clinical programming, the AE deliverable involves at least
**four separate programs**, often written by different people:

| Program       | Input          | Output           | Owner      |
| ------------- | -------------- | ---------------- | ---------- |
| `ae.sas`      | Raw AE extract | SDTM AE          | SDTM prog. |
| `adae.sas`    | SDTM AE + ADSL | ADaM ADAE        | ADaM prog. |
| `adae_qc.sas` | ADAE           | Validation log   | QC prog.   |
| `t_ae.sas`    | ADAE + ADSL    | AE summary table | TLG prog.  |

Each program runs independently. Context about _why_ a particular derivation
exists often lives only in the developer's head or in a Word document. When the
table looks wrong, you debug backwards across four files, hoping the variable
names haven't drifted.

### The R2R model

```
r2r_ae.py   ADSL (input) + Raw AE → SDTM AE → ADAE → validate → AE summary → HTML
```

One script. One review. When cell `(3, 2)` in the table looks wrong, scroll up —
the derivation that produced it is in the same file.

DM and ADSL remain separate, governed programs — they are shared by many domains.
The R2R script consumes ADSL as a pre-built input and owns everything else.

### Advantages

- **Full lineage visibility** — every transformation from raw value to table cell
  is traceable in a single scroll.
- **Faster debugging** — no need to run four programs and cross-reference
  intermediate datasets; breakpoints anywhere in the chain.
- **Atomic reviews** — a reviewer sees the complete picture; intent and
  implementation live together.
- **Agent-native** — an AI coding agent can reason about the entire pipeline
  in one context window, generate it end-to-end, and fix issues without
  switching files.
- **Reproducible** — one command (`uv run python r2r_ae.py`) regenerates
  everything from source.

### When to use R2R

R2R shines when:

- You need to **prototype fast** — get a table on screen from raw data in minutes.
- The domain is **self-contained** — AE, VS, LB, CM — where the analysis dataset
  depends only on its own SDTM domain plus ADSL.
- You're working with an **AI agent** that benefits from seeing the full pipeline
  in one prompt.
- You want a **living specification** — the code _is_ the documentation of how
  raw data becomes a regulatory table.

### When NOT to use R2R

- **Shared derivations** — ADSL is consumed by many domains; it deserves its own
  program with governed outputs. The R2R script **loads** ADSL as an input — it
  does not derive it.
- **Large teams** — when SDTM and ADaM are programmed by different people on
  different timelines, separation makes sense.
- **Validated production** — regulatory submissions may require individual
  program-level sign-off; R2R is ideal for exploratory and rapid development
  before refactoring into governed programs.

---

## The Layers

An R2R script is organised into clearly labelled layers. Each layer uses a
different Fleet namespace:

### Layer 0 — Inputs

Load the pre-built ADSL and the raw AE extract:

```python
import polars as pl
import fleet  # registers .sdtm / .adam / .tlg namespaces

# ADSL is produced by a separate governed program
adsl = pl.read_csv("outputs/cdiscpilot01/adsl_admiral.csv", try_parse_dates=True)
adsl = adsl.with_columns(pl.col("TRT01P").alias("TRTA"))

# Raw AE — the only raw data this script owns
ae_raw = pl.read_csv("datasets/cdiscpilot01/raw/ae_raw.csv")
```

### Layer 1 — SDTM (`.sdtm` namespace)

Standardise raw columns into CDISC-compliant SDTM variables:

```python
ae = (
    ae_raw.sdtm
    .hardcode_no_ct("STUDYID", value="CDISCPILOT01")
    .hardcode_no_ct("DOMAIN",  value="AE")
    .assign_no_ct("USUBJID",  source="patient_number")
    .assign_no_ct("AETERM",   source="ae_term")
    .assign_no_ct("AESTDTC",  source="ae_start_date")
    .assign_no_ct("AEENDTC",  source="ae_end_date")
    .assign_no_ct("AESEV",    source="ae_severity")
    .assign_no_ct("AESER",    source="ae_serious")
    .to_frame()
)
```

### Layer 2 — ADaM ADAE (`.adam` / `.adam.occds` namespaces)

Merge ADSL treatment dates into SDTM AE, then derive analysis dates,
treatment-emergent flags, and worst-severity flags:

```python
# Merge ADSL treatment dates & population flags into SDTM AE
_adsl_trt = adsl.select(["USUBJID", "TRTSDT", "TRTEDT", "TRT01P", "TRTA", "SAFFL"])
ae_with_trt = ae.join(_adsl_trt, on="USUBJID", how="left")

adae = (
    ae_with_trt.adam
    .source("STUDYID")
    .source("USUBJID")
    .source("AETERM")
    .source("TRTA")
    .source("SAFFL")
    .derive_dt("ASTDT", source="AESTDTC")
    .study_day("ADY", analysis_date="ASTDT", reference_date="TRTSDT")
    .to_frame()
    .adam.occds
    .treatment_emergent(
        "TRTEMFL", start_date="AESTDTC",
        trtsdt="TRTSDT", trtedt="TRTEDT",
    )
    .worst_flag(
        "ANL01FL", severity_col="AESEV",
        severity_order=["MILD", "MODERATE", "SEVERE"],
        groups=["USUBJID", "AETERM"],
    )
    .seq("ASEQ", groups=["USUBJID"])
    .to_frame()
)
```

### Layer 3 — Validate

Call `.validate()` directly in the pipeline chain — it prints the conformance
report and returns the namespace unchanged so derivations can continue:

```python
ae = (
    ae_raw.sdtm
    .hardcode_no_ct("STUDYID", value="CDISCPILOT01")
    .hardcode_no_ct("DOMAIN",  value="AE")
    .assign_no_ct("USUBJID",  source="patient_number")
    .assign_no_ct("AETERM",   source="ae_term")
    .assign_no_ct("AESTDTC",  source="ae_start_date")
    .assign_no_ct("AEENDTC",  source="ae_end_date")
    .assign_no_ct("AESEV",    source="ae_severity")
    .assign_no_ct("AESER",    source="ae_serious")
    .validate("AE")          # ← prints report, chain continues
    .to_frame()
)

adae = (
    ae_with_trt.adam
    .source("STUDYID")
    .source("USUBJID")
    .source("AETERM")
    .source("TRTA")
    .source("SAFFL")
    .derive_dt("ASTDT", source="AESTDTC")
    .study_day("ADY", analysis_date="ASTDT", reference_date="TRTSDT")
    .to_frame()
    .adam.occds
    .treatment_emergent(
        "TRTEMFL", start_date="AESTDTC",
        trtsdt="TRTSDT", trtedt="TRTEDT",
    )
    .worst_flag(
        "ANL01FL", severity_col="AESEV",
        severity_order=["MILD", "MODERATE", "SEVERE"],
        groups=["USUBJID", "AETERM"],
    )
    .seq("ASEQ", groups=["USUBJID"])
    .validate("ADAE")        # ← prints report, chain continues
    .to_frame()
)
```

The report printed to stdout makes conformance issues immediately visible:

```
======================================================================
CDISC Validation Report: AE
======================================================================
Dataset Type: SDTM 3.4
Status: FAIL
Total Issues: 2
----------------------------------------------------------------------

ERRORS (2):

1. [Error] SDTM.AE.R0001: AESEQ is required but missing
   Variable: AESEQ

2. [Error] SDTM.AE.R0014: AEBODSYS must be populated when AEDECOD is present
   Variable: AEBODSYS
   Rows: 43
   Producing verb: assign_no_ct (AETERM)
   Suggested fix: Map AEBODSYS from MedDRA lookup or hardcode domain SOC

======================================================================

======================================================================
CDISC Validation Report: ADAE
======================================================================
Dataset Type: ADaM 1.3
Status: PASS
Total Issues: 0
----------------------------------------------------------------------

======================================================================
```

The `Producing verb` field traces an error directly back to the Fleet verb that
created the offending column — no manual variable hunting required.

### Layer 4 — Render (`.tlg.ae` namespace)

Compute the Analysis Results Dataset and render to HTML:

```python
from fleet.tlg import (
    AESummarySpec, Row, Statistic,
    RenderMetadata, ard_to_table_model, render_html,
)

spec = AESummarySpec(
    rows=[
        Row(field="AEBODSYS", label="System Organ Class"),
        Row(field="AEDECOD",  label="Preferred Term"),
    ],
    statistics=[Statistic.N_SUBJECTS, Statistic.N_PCT],
)

ard = adae.tlg.ae.t_summary(spec=spec, adsl=adsl)

meta = RenderMetadata(
    title="Table 14.3.1.1",
    subtitle="AE Summary by SOC and PT",
    footnotes=["Source: ADAE", "Population: Safety"],
)
html = render_html(ard_to_table_model(ard, meta))
Path("outputs/ae_r2r.html").write_text(html)
```

---

## R2R and Agentic Coding

The R2R strategy is **purpose-built for AI agents**. Here's why:

1. **Single-context reasoning** — The entire derivation fits in one file (and one
   prompt). An agent doesn't need to discover dependencies across a file tree.

2. **End-to-end generation** — Given a raw dataset schema and a target table shell,
   an agent can generate a complete R2R script in one pass — no multi-turn
   orchestration.

3. **Instant feedback** — The script produces a visible output (HTML table). The
   agent (or user) can inspect the result and iterate without leaving the file.

4. **Self-documenting** — The layered structure doubles as executable documentation.
   An agent reading the file can explain every derivation decision from raw to
   table.

5. **Deterministic re-execution** — One `uv run python r2r_ae.py` reproduces the
   full artefact. No DAG scheduler, no Makefile, no external state.

### Agent prompt pattern

> "Using Fleet's R2R pattern, write a single Python script that takes
> `ae_raw.csv` and a pre-built ADSL (`adsl_admiral.csv`) and produces an
> HTML AE summary table (Table 14.3.1.1). Include SDTM AE, ADAE with
> treatment-emergent flags, pre-validation, and a rendered HTML output."

The agent returns a complete, runnable script — no follow-up questions needed.

---

## Running the Example

The full working example is at [`examples/r2r_ae_example.py`](https://github.com/RealSlimMahdi/fleet-cdisc/blob/main/examples/r2r_ae_example.py):

```bash
uv run python examples/r2r_ae_example.py
```

Output:

```
━━ Layer 0 · Inputs ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ADSL (pre-built) : 5 subjects × 33 variables
  ae_raw           :   5 rows × 9 cols

━━ Layer 1 · SDTM AE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  AE : 5 records × 21 variables

━━ Layer 2 · ADaM ADAE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ADAE : 5 records × 34 variables

━━ Layer 3 · Validate ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ✓ TLG pre-validation passed

━━ Layer 4 · Render ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ARD: 155 rows × 14 cols → ae_r2r.html

━━ R2R Complete ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  One file. One domain. Raw to Render.
```
