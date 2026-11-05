# Namespace Pipeline Architecture

Fleet lets you write the same pipeline in two notations: **Code-driven** (chaining verbs in Python) or **Spec-driven** (declaring the same verbs in a `define.yaml` that Fleet executes for you). Verb names and argument names are identical in both, so a step can move between them.

## The Recommended Approach: Spec-First with Custom Extensions

For the majority of modern statistical programming tasks, we highly recommend a hybrid "**Spec-First**" workflow.

In this approach, you let AI or your documentation team generate the `define.yaml`. Fleet consumes this YAML to automatically manage 90% of the derivations, dependencies, traceability, and Define-XML generation. Then, for the 10% of highly complex, proprietary derivations that do not fit neatly into a YAML file, you apply a thin layer of manual Polars python code on top of the built data step.

This hybrid approach ensures high reproducibility and documentation sync, while leaving an "escape hatch" open for when code must take over.

### 1. Code-Driven (Inline Python)

Best for: Quick exploration, ad-hoc analysis, smaller studies, or initial data discovery.

You construct your pipelines entirely in Python by chaining namespace verbs on Polars DataFrames. All logic is embedded directly in your scripts.

**Example:**

```python
adsl = dm.adam.adsl.source("USUBJID").duration("ADY", start="TRTSDT", end="ADT").to_frame()
```

### 2. Spec-Driven (`define.yaml`)

Best for: Production clinical trials, regulatory submissions, repeatability across projects.

You define metadata, controlled terminology, and derivations in a central `define.yaml` file. Fleet reads the specification and automatically builds the datasets. In this model, your Python scripts simply load the study context and call `.from_spec()`.

**Example of the Hybrid Escape Hatch:**

```python
# The standard derivations live in define.yaml.
import polars as pl
import fleet  # noqa: F401

dm = pl.read_parquet("outputs/sdtm/dm.parquet")
base_adsl = dm.adam.from_spec("specs/study01/adam/define.yaml", dataset="ADSL").to_frame()

# Add custom logic for the 10% of edge-case scenarios not covered by the spec:
final_adsl = base_adsl.adam.adsl.derivation(
    "CUSTOM_FLAG", expression=pl.when(pl.col("AGE") > 80).then(pl.lit("Y")).otherwise(pl.lit("N"))
).to_frame()
```

---

## How the pipeline works underneath

Every Fleet namespace (`sdtm`, `adam`, `adsl`, `occds`) follows the same pattern:

1. **Access** the namespace on a Polars DataFrame: `df.sdtm`
2. **Chain** verb calls — each returns a new namespace object accumulating `pl.Expr` objects
3. **Materialise** with `.to_frame()` — Polars runs the lazy plan

```python
result = (
    raw_df.sdtm.assign("USUBJID", source="patient_id")  # 1. access  # 2. chain
    .assign("DOMAIN", value="DM")
    .assign("SEX", source="sex_raw", ct=SEX, ct_map={"Male": "M", "Female": "F"})
    .to_frame()  # 3. materialise
)
```

`assign` is the one canonical assignment verb (`source=` copies, `value=`
hardcodes, `ct=`/`ct_map=` add CT). Most verbs append to one lazy plan. Some
verbs read data before the chain continues: checks (`baseline`, `date` to a DTC
variable) and verbs that
build or filter records (`whereclauses`, `pick`, `derive_*`, `nodup`). The chain
does not break at these verbs.

To inspect intermediate state or the query plan during development, use the
chainable debug verbs `.inspect()` (hard checkpoint with diagnostic output)
and `.explain()` (print the Polars query plan). See
[Advanced Patterns](advanced.md#pipeline-debugging-observability) for details.

---

## Lazy evaluation

```
df.sdtm
  │
  ├─ .assign("USUBJID", source=...)  →  [Expr("patient_id".alias("USUBJID"))]
  ├─ .assign("SEX", ct=...)          →  [..., Expr(when/then.alias("SEX"))]
  └─ .to_frame()
       │
       └─ df.with_columns(*exprs)   ← one Polars plan for these verbs
```

This means you pay no cost for columns you don't chain. Expression ordering mirrors declaration order.
The verbs that read data before the chain continues are listed in the GUIDE
laziness table ("What is lazy, and what checkpoints").

---

## SDTM verbs at a glance

| Verb                                       | Purpose                                |
| ------------------------------------------ | -------------------------------------- |
| `assign(target, source=)`                  | Copy raw column                        |
| `assign(target, value=)`                   | Constant literal for all rows          |
| `assign(target, source=, ct=, ct_map=)`    | Copy + validate/recode through a codelist |
| `case_when(target, when=, else_=)`         | Multi-branch conditional               |
| `date(target, source=)`                    | Normalise to ISO 8601 date or datetime |
| `derivation(target, expression=)`          | Arbitrary `pl.Expr`                    |
| `merge(dataset, on=, keep=)`               | Join a reference dataset               |
| `to_frame()`                               | Materialise                            |

---

## ADaM verbs at a glance

| Verb                                        | Purpose                                   |
| ------------------------------------------- | ----------------------------------------- |
| `source(*targets)`                          | Variadic pass-through column(s)           |
| `derivation(target, expression=)`           | Arbitrary `pl.Expr`                       |
| `assign(target, value=)`                    | Constant literal                          |
| `date(target, source=)`                     | Parse DTC → Date/Datetime with imputation |
| `duration(target, start=, end=)`            | CDISC study day / elapsed time            |
| `flag(target, criteria=, by=)`              | Per-group boolean flag                    |
| `baseline(target, aval=, baseline_flag=, by=)` | Carry baseline AVAL within groups      |
| `chg(target, aval, base)`                   | Change from baseline                      |
| `pchg(target, aval, base)`                  | Percent change from baseline              |
| `bmi(target, weight, height)`               | Body Mass Index                           |
| `nrind(target, value, low, high)`           | Normal range indicator (LOW/NORMAL/HIGH)  |
| `on_treatment(target, adt, trtsdt, trtedt)` | On-treatment flag                         |
| `shift(target, baseline_cat, post_cat)`     | Categorical shift string                  |
| `bsa(target, weight, height, method)`       | Body Surface Area (4 methods)             |
| `map(target, systolic, diastolic)`          | Mean Arterial Pressure                    |
| `qtc(target, qt, rr, method, rr_unit)`      | Corrected QT (QT in ms, RR in ms by default) |
| `derive_summary_records(by, ...)`           | Aggregate by group, append summary rows   |
| `derive_locf_records(dataset_ref, by, order_by, ...)` | Add LOCF records for the expected visits |
| `derive_param(by_vars, ...)`                | Derive a new parameter and append as rows |
| `to_frame()`                                | Materialise                               |

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
from fleet import StudyContext, load_study_context
from fleet.core.study_context import ADAMConfig, SDTMConfig
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
