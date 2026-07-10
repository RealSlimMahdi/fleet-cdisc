# Why Fleet?

Fleet is designed to bridge the gap between modern, high-performance data engineering and the specialized business logic of clinical statistical programming (SDTM and ADaM).

While traditional tools (like SAS or SQL) or general-purpose Python libraries (like Pandas or plain Polars) are capable of building clinical datasets, they often require writing hundreds of lines of boilerplate code to handle common CDISC requirements: merging controlled terminology, calculating study days, deriving baselines, and maintaining traceability.

Fleet solves this by extending [Polars](https://pola.rs/) with **chainable, domain-specific verbs**.

## The Fleet Advantage

### 1. Simplicity: Intent-Driven Syntax

With Fleet, your code reads like a specification. Instead of writing complex join logic and conditional expressions, you use verbs that exactly match CDISC concepts.

**Without Fleet (Manual Polars):**

```python
import polars as pl

# Deriving a baseline value requires multiple steps and intermediate variables
# 1. Filter to baseline records
baseline_df = adbd.filter(pl.col("ABLFL") == "Y").select(["USUBJID", "PARAMCD", "AVAL"])
baseline_df = baseline_df.rename({"AVAL": "BASE"})

# 2. Join back to the main dataset
adbd = adbd.join(baseline_df, on=["USUBJID", "PARAMCD"], how="left")

# 3. Calculate change from baseline
adbd = adbd.with_columns((pl.col("AVAL") - pl.col("BASE")).alias("CHG"))
```

**With Fleet:**

```python
import fleet

# Intent is immediately clear in a single chain
adbd = (
    adbd.adam.baseline("BASE", aval="AVAL", baseline_flag="ABLFL", by=["USUBJID", "PARAMCD"])
    .chg("CHG", aval="AVAL", base="BASE")
    .to_frame()
)
```

### 2. Power: High Performance Lazy Evaluation

Fleet doesn't just wrap Polars; it deeply integrates with its lazy evaluation engine. When you chain Fleet verbs (e.g., `.assign()`, `.study_day()`), most accumulate business logic into a single optimized set of Polars expressions rather than computing immediately.

When you call `.to_frame()`, Polars executes the pipeline in one pass, leveraging multithreading and query optimization. A few window/cross-domain verbs (`baseline`, pinned `study_day`) checkpoint internally — but they re-wrap the collected frame and keep the chain going, so `flag → baseline → chg` stays a single pipeline. The namespaces are also registered on `pl.LazyFrame`, so `pl.scan_parquet(...).sdtm` keeps the whole pipeline lazy with predicate pushdown.

- **No intermediate DataFrames:** Saves memory.
- **Blazing fast:** Processes millions of records in milliseconds.
- **Zero overhead:** Fleet verbs compile down to native Polars `pl.Expr` objects.

### 3. Clarity: Specification-Driven Development

Fleet natively understands the `define.yaml` specification. You can define your metadata, controlled terminology, and derivation rules in a single, human-readable file.

Fleet can read this YAML to automatically apply derivations, validate data, and generate CDISC-compliant `define.xml` exports, ensuring your documentation and your code are never out of sync. You can choose to be fully code-driven, fully spec-driven, or a hybrid of both.

### 4. Flexibility: Built for Extension

Fleet comes with built-in namespaces for core SDTM (`df.sdtm`), ADaM BDS (`df.adam`), ADSL (`df.adam.adsl`), OCCDS (`df.adam.occds`), and specialized therapeutic areas (Oncology, Ophthalmology, Vaccines, etc.). Fleet also includes verbs for Body Surface Area (`bsa`), Mean Arterial Pressure (`map`), corrected QT (`qtc`), LOCF imputation, summary record derivation, and parameter-level record generation.

If you have proprietary study requirements, Fleet is designed to be easily extended with custom verbs using standard Polars expressions via the `.derivation()` method, or by subclassing the namespaces to add your own company-specific logic.

### 5. AI-Native Architecture

Fleet was built with AI code generation in mind from day one. You can stop wrestling with niche SAS macros or fragmented statistical R packages that trip up modern Large Language Models (LLMs).

- **Standardised Foundation:** Built entirely on Python and Polars, two of the most widely represented tools in LLM training data.
- **Unified Package:** No need to juggle 10 different sub-packages. One import (`import fleet`) gives agents everything they need.
- **Clear Intent-Driven API:** Because derivations are simple verbs (`.study_day()`, `.baseline()`), an AI code agent naturally scripts correct, readable pipelines with fewer token hallucinations.
- **Tight AI Feedback Loops:** Fleet drastically accelerates the developer and agent feedback cycle. The `define.yaml` structure is validated through bundled JSON schemas, and CDISC core data validations output structured error arrays. This allows coding agents to course-correct immediately.
- **Readable Specs:** The declarative, YAML-based approach limits token overhead and naturally reflects clinical data specification standards, making it the perfect bridge between LLMs and regulatory outputs.
- **Built-in `llms.txt`:** Fleet natively provides structured AI context (like `llms.txt` and schemas) so your coding agents always know precisely how to write and validate Fleet pipelines.

### 6. Native CDISC Library Integration

Fleet is the first open-source clinical toolkit with **built-in CDISC Library API support**. Instead of manually downloading PDF terminology files or maintaining hand-curated codelist dictionaries, Fleet connects directly to the authoritative source.

```bash
# Full bootstrapping pipeline: config → define.yaml → codelists.py
fleet init cfg --study-id STUDY01 --domains DM,AE,VS,EX --adam-datasets ADSL,ADVS
fleet init define
fleet init ct

# Or standalone: bootstrap codelists directly from the SDTM IG
fleet add-ct --domains DM,AE,VS,EX --output codelists.py
```

- **Source of truth is the CDISC Library IG** — Fleet queries the Implementation Guide model to discover every variable and codelist for your domains. No manual curation, no guessing concept IDs.
- **IDE auto-completion for CT values** — the generated `codelists.py` gives you typed constants (`SEX.M`, `RACE.WHITE`) with full definitions as code comments. Your IDE autocompletes both the codelist name and every permitted submission value.
- **Incremental domain expansion** — start with DM and AE, then `fleet add-ct --domains LB,CM` later. Existing codelists are preserved; only new ones are added.
- **Version-pinned reproducibility** — pin your CT package version (e.g. `--package sdtmct-2025-09-26`) so every team member and CI run generates identical constants.

```python
from codelists import SEX, RACE

dm = (
    raw_df.sdtm.assign("SEX", source="sex", ct=SEX)
    .assign("RACE", source="race", ct=RACE)
    .to_frame()
)
```

No NCI codes to memorise. No CSV lookups at runtime. Just import the codelist and use it — the `_concept_id` is carried through for Define-XML generation and P21 validation automatically.
