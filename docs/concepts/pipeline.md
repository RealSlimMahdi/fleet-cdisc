# Namespace Pipeline Architecture

When using Fleet, you have two primary ways to create datasets: **Code-driven** (writing Python pipelines manually) or **Spec-driven** (authoring a `define.yaml` and having Fleet write the pipelines for you).

## The Recommended Approach: Spec-First with Custom Extensions

For the majority of modern statistical programming tasks, we highly recommend a hybrid "**Spec-First**" workflow.

In this approach, you let AI or your documentation team generate the `define.yaml`. Fleet consumes this YAML to automatically manage 90% of the derivations, dependencies, traceability, and Define-XML generation. Then, for the 10% of highly complex, proprietary derivations that do not fit neatly into a YAML file, you apply a thin layer of manual Polars python code on top of the built data step.

This hybrid approach ensures high reproducibility and documentation sync, while leaving an "escape hatch" open for when code must take over.

### 1. Code-Driven (Inline Python)

Best for: Quick exploration, ad-hoc analysis, smaller studies, or initial data discovery.

You construct your pipelines entirely in Python by chaining namespace verbs on Polars DataFrames. All logic is embedded directly in your scripts.

**Example:**

```python
adsl = (
    dm.adam.adsl
    .source("USUBJID")
    .duration("ADY", start="TRTSDT", end="ADT")
    .to_frame()
)
```

### 2. Spec-Driven (`define.yaml`)

Best for: Production clinical trials, regulatory submissions, repeatability across projects.

You define metadata, controlled terminology, and derivations in a central `define.yaml` file. Fleet reads the specification and automatically builds the datasets. In this model, your Python scripts simply load the study context and call `.build()`.

**Example of the Hybrid Escape Hatch:**

```python
# The standard derivations live in define.yaml.
from fleet import load_study_context
import polars as pl

ctx = load_study_context("specs/study01/adam/define.yaml")
base_adsl = ctx.build("ADSL")

# Add custom logic for the 10% of edge-case scenarios not covered by the spec:
final_adsl = (
    base_adsl.adam.adsl
    .derivation("CUSTOM_FLAG", expression=pl.when(pl.col("AGE") > 80).then(pl.lit("Y")).otherwise(pl.lit("N")))
    .to_frame()
)
```

---

## How the pipeline works underneath

Every Fleet namespace (`sdtm`, `adam`, `adsl`, `occds`) follows the same pattern:

1. **Access** the namespace on a Polars DataFrame: `df.sdtm`
2. **Chain** verb calls — each returns a new namespace object accumulating `pl.Expr` objects
3. **Materialise** with `.to_frame()` — executes a single `df.with_columns(...)` pass

```python
result = (
    raw_df.sdtm                  # 1. access
    .assign_no_ct("USUBJID", source="patient_id")   # 2. chain
    .hardcode_no_ct("DOMAIN", value="DM")
    .assign_ct("SEX", source="sex_raw",
               ct_codelist=SEX, ct_mapping={"M": "M", "F": "F"})
    .to_frame()                  # 3. materialise
)
```

Nothing runs at step 2 — verbs only build an internal expression list.

To inspect intermediate state or the query plan during development, use the
chainable debug verbs `.inspect()` (hard checkpoint with diagnostic output)
and `.explain()` (print the Polars query plan). See
[Advanced Patterns](advanced.md#pipeline-debugging-observability) for details.

---

## Lazy evaluation

```
df.sdtm
  │
  ├─ .assign_no_ct("USUBJID", ...)  →  [Expr("patient_id".alias("USUBJID"))]
  ├─ .assign_ct("SEX", ...)         →  [..., Expr(when/then.alias("SEX"))]
  └─ .to_frame()
       │
       └─ df.with_columns(*exprs)   ← single Polars pass
```

This means you pay no cost for columns you don't chain. Expression ordering mirrors declaration order.

---

## SDTM verbs at a glance

| Verb                                                 | Purpose                                |
| ---------------------------------------------------- | -------------------------------------- |
| `assign_no_ct(target, source)`                       | Copy raw column, no CT validation      |
| `hardcode_no_ct(target, value)`                      | Constant literal for all rows          |
| `assign_ct(target, source, ct_codelist, ct_mapping)` | Recode values through a CT codelist    |
| `date(target, source)`                               | Normalise to ISO 8601 date or datetime |
| `derivation(target, expression)`                     | Arbitrary `pl.Expr`                    |
| `if_then_else(target, when, else_value)`             | Multi-branch conditional               |
| `to_frame()`                                         | Materialise                            |

---

## ADaM verbs at a glance

| Verb                                               | Purpose                                   |
| -------------------------------------------------- | ----------------------------------------- |
| `source(target)`                                   | Pass-through column                       |
| `derivation(target, expression)`                   | Arbitrary `pl.Expr`                       |
| `assigned(target, value)`                          | Constant literal                          |
| `date(target, source)`                             | Parse DTC → Date/Datetime with imputation |
| `duration(target, start, end)`                     | CDISC study day / elapsed time            |
| `flag(target, criteria, groups)`                   | Per-group boolean flag                    |
| `baseline(target, aval, baseline_flag)`            | Carry baseline AVAL within groups         |
| `chg(target, aval, base)`                          | Change from baseline                      |
| `pchg(target, aval, base)`                         | Percent change from baseline              |
| `bmi(target, weight, height)`                      | Body Mass Index                           |
| `nrind(target, value, low, high)`                  | Normal range indicator (LOW/NORMAL/HIGH)  |
| `on_treatment(target, adt, trtsdt, trtedt)`        | On-treatment flag                         |
| `shift(target, baseline_cat, post_cat)`            | Categorical shift string                  |
| `bsa(target, weight, height, method)`              | Body Surface Area (4 methods)             |
| `map(target, systolic, diastolic)`                 | Mean Arterial Pressure                    |
| `qtc(target, qt, rr, method)`                      | Corrected QT interval (Fridericia/Bazett) |
| `derive_summary_records(by_vars, ...)`             | Aggregate by group, append summary rows   |
| `derive_locf_records(by_vars, ...)`                | Forward-fill (LOCF) within patient groups |
| `derive_param(by_vars, ...)`                       | Derive a new parameter and append as rows |
| `to_frame()`                                       | Materialise                               |

---

## ADSL verbs at a glance

| Verb                                                | Purpose                                            |
| --------------------------------------------------- | -------------------------------------------------- |
| `source(target)`                                    | Pass-through column                                |
| `first_date(target, from_dataset, date_col, where)` | Earliest event date per subject                    |
| `last_date(target, from_dataset, date_col, where)`  | Latest event date per subject                      |
| `duration(target, start, end)`                      | Elapsed days / duration                            |
| `flag(target, criteria)`                            | `"Y"` flag (expression, first/last/max/min/exists) |
| `count_events(target, from_dataset, where)`         | Event count per subject                            |
| `age_years(target, age_col, age_unit_col)`          | Unit-aware age conversion to years                 |
| `derive_period(periods, start_date)`                | Subperiod/Phase variables (APxxSDT, etc.)          |
| `to_frame()`                                        | Materialise                                        |

---

## OCCDS verbs at a glance

| Verb                                        | Purpose                                                       |
| ------------------------------------------- | ------------------------------------------------------------- |
| `source(target)`                            | Pass-through column                                           |
| `first_occ(target, date_col, groups)`       | Flag first occurrence within group                            |
| `flag(target, criteria, value_col, groups)` | Generalised \"Y\" flag (max/min/first/last/exists/expression) |
| `any_flag(target, col, value, groups)`      | `"Y"` if event exists in group                                |
| `to_frame()`                                | Materialise                                                   |

---

## StudyContext — workspace initialisation

The recommended way to start a new study is the **bootstrapping pipeline** via
the Fleet CLI:

```bash
fleet init cfg --study-id STUDY01 --company "Acme Pharma" \
  --domains DM,AE,VS,EX --adam-datasets ADSL,ADVS --root ./studies/STUDY01
fleet init define --config ./studies/STUDY01/study_config.yaml  # queries CDISC Library IG → define.yaml
fleet init ct     --config ./studies/STUDY01/study_config.yaml  # reads define.yaml → codelists.py
```

!!! note
When `--root` points to a non-current directory, pass `--config <root>/study_config.yaml`
to `init define` and `init ct`, or `cd` into the root directory before running them.

See the [CLI Reference](../getting-started/cli.md) for full details.

`StudyContext.init()` can also be used programmatically — it creates the folder
tree and writes `study_config.yaml`. Define specs and codelists are produced by
the subsequent pipeline steps (`fleet init define`, `fleet init ct`).

```python
from fleet import StudyContext, SDTMConfig, ADAMConfig, load_study_context
from pathlib import Path

# ── Once, when starting a new study ──────────────────────────────────────
ctx = StudyContext.init(
    "./studies/STUDY01",
    study_id="STUDY01",
    company="Acme Pharma",
    sdtm=SDTMConfig(ig_version="3-4", domains=["DM", "AE", "VS", "EX"]),
    adam=ADAMConfig(ig_version="1-1", datasets=["ADSL", "ADVS"]),
)

# ── Every subsequent session ──────────────────────────────────────────────
ctx = load_study_context(Path("./studies/STUDY01/study_config.yaml"))
```

| Outcome                    | Behaviour                                                      |
| -------------------------- | -------------------------------------------------------------- |
| Directories already exist  | Silently skipped (`mkdir -p` semantics)                        |
| `study_config.yaml` exists | Raises `StudyConfigError` — use `load_study_context()` instead |
