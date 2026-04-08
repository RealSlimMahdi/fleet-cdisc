# How `define.yaml` Drives DataFrame Creation

`define.yaml` is the **single source of truth** for a Fleet study. One file simultaneously:

1. Declares all output variables (fed to Define-XML 2.1 generation)
2. Specifies how each variable is derived (executed as a pipeline)
3. Declares codelists and controlled terminology references
4. Defines structural metadata (keys, class, structure label)

---

## File Layout

```yaml
# yaml-language-server: $schema=../../../src/fleet/define_xml/schemas/define_spec_schema.json
study:
  id:             CDISCPILOT01
  standard:       ADAMIG
  standard_version: "1.1"

codelists:
  - oid: C66731
    name: Sex
    type: text
    items:
      - coded_value: "M"
        decode: MALE
      - coded_value: "F"
        decode: FEMALE

datasets:
  - name: ADSL
    label: Subject-Level Analysis Dataset
    structure: One record per subject
    keys: [STUDYID, USUBJID]
    inputs:
      - name: DM
        type: dataset
    variables:
      - name: STUDYID
        ...
```

The schema is validated by the bundled JSON Schema (`define_spec_schema.json`), which means editors with YAML language server support provide auto-complete and inline error highlighting.

---

## Derivation Algorithms

Each variable's `derivation.algorithm` maps directly to an `.adsl` (or `.adam`) verb:

| `algorithm`  | Namespace verb                                                   | What it does                    |
| ------------ | ---------------------------------------------------------------- | ------------------------------- |
| `assigned`   | `.assigned(target, value=...)`                                   | Constant literal for all rows   |
| `source`     | `.source(target, from_col=...)`                                  | Copy column from predecessor    |
| `derivation` | `.derivation(target, expression=...)`                            | Arbitrary Polars expression     |
| `first_date` | `.first_date(target, from_dataset=..., date_col=..., where=...)` | Earliest event date per subject |
| `last_date`  | `.last_date(...)`                                                | Latest event date per subject   |
| `duration`   | `.duration(target, start_date=..., end_date=...)`                | Integer day count               |
| `flag`       | `.eligibility_flag(target, criteria=...)`                        | `"Y"` / `null` flag             |
| `count`      | `.count_events(target, from_dataset=..., where=...)`             | Integer event count             |

### Example — TRTSDT (date of first dose)

In `define.yaml`:

```yaml
- name: TRTSDT
  label: Date of First Exposure to Treatment
  type: date
  origin: Derived
  derivation:
    algorithm: first_date
    from_dataset: EX
    date_col: EXSTDTC
    where: 'pl.col("EXDOSE") > 0'
```

Equivalent hand-written pipeline:

```python
adsl = (
    dm_sdtm.adsl
    ...
    .first_date("TRTSDT", from_dataset=ex_sdtm,
                date_col="EXSTDTC",
                where='pl.col("EXDOSE") > 0')
    ...
    .to_frame()
)
```

---

## End-to-End Flow

```mermaid
graph TD
    A[define.yaml] -->|parsed| B[DefineSpecGenerator]
    B -->|variable metadata| C[DefineXMLGenerator]
    B -->|derivation specs| D[StudyContext.build]
    D -->|applies verbs| E[Polars pipeline]
    E -->|calls .to_frame| F[ADSL DataFrame]
    C --> G[define_adam.xml]
    F --> H[adsl.parquet / adsl.csv]
    F --> I[DatasetChecker / ValidationService]
```

### Running the full pipeline programmatically

```python
from fleet import load_study_context

ctx = load_study_context("specs/cdiscpilot01/adam/define.yaml")

# Build every dataset declared in the spec
adsl = ctx.build("ADSL")   # returns a polars.DataFrame
advs = ctx.build("ADVS")
```

### Generating Define-XML from the same spec

```python
from fleet import DefineXMLGenerator

gen = DefineXMLGenerator("specs/cdiscpilot01/adam/define.yaml")
gen.write("outputs/cdiscpilot01/define_adam.xml")
```

---

## Codelist References

Variables can reference codelists declared in the `codelists` block:

```yaml
- name: SEX
  label: Sex
  type: text
  codelist: C66731 # references the oid in codelists[]
  derivation:
    algorithm: source
    source: SEX
```

Fleet threads CT validation through the pipeline automatically — invalid values raise a `CTError` at runtime.

---

## Schema Validation — What, When, and How

Fleet has two independent layers of schema validation for `define.yaml`. They run at different
points and catch different classes of error.

### Layer 1 — Pydantic model validation (pipeline-build time)

When you call `.from_spec()` on an SDTM or ADaM namespace, Fleet parses each variable's
`derivation` block through a Pydantic model (`SDTMVariableSpec` / `ADAMVariableSpec`). This
runs **immediately when `.from_spec()` is called**, before any data is loaded.

What it catches:

- Missing required fields for a given `algorithm` (e.g. `assign_ct` without `ct_codelist`)
- Unknown algorithm names
- Wrong field types (e.g. a list where a string is expected)

```python
# define.yaml snippet with a bug — assign_ct is missing ct_codelist:
#   - name: SEX
#     derivation:
#       algorithm: assign_ct
#       source: sex               ← ct_codelist is required but absent

dm = raw_df.sdtm.from_spec("specs/define.yaml", dataset="DM")
# Raises pydantic.ValidationError immediately at this line, before .to_frame() is ever called.
# pydantic_core._pydantic_core.ValidationError: 1 validation error for SDTMVariableSpec
#   ct_codelist
#     Field required [type=missing, ...]
```

### Layer 2 — JSON Schema + business rule validation (`DefineValidator`)

`DefineValidator` runs a deeper structural check against the bundled JSON Schema
(`src/fleet/define_xml/schemas/define_xml_2_1_schema.json`) and a set of CDISC business rules.
This layer fires **on demand**, not automatically during pipeline execution.

**Trigger it explicitly** — before generating Define-XML or before submission:

```python
from fleet.define_xml import DefineValidator
from pathlib import Path

validator = DefineValidator()
is_valid = validator.validate(Path("specs/cdiscpilot01/sdtm/define.yaml"))

for issue in validator.issues:
    print(f"[{issue.severity.upper()}] {issue.rule} @ {issue.location}: {issue.message}")

# Example output:
# [ERROR]   SCHEMA_001 @ datasets.0.variables.2: 'type' is a required property
# [ERROR]   BR03 @ datasets.0.variables.5.codelist: CodeListRef 'C99999' not found in codelists[]
# [WARNING] ALG02 @ datasets.0.variables.3: assign_ct should have ct_codelist declared
```

What it catches:

| Rule         | Checks                                                               |
| ------------ | -------------------------------------------------------------------- |
| `SCHEMA_001` | All fields conform to the JSON Schema (types, required properties)   |
| `BR01`       | Every dataset has at least one key variable                          |
| `BR02`       | All `ItemRef` references resolve to declared variables               |
| `BR03`       | All `codelist:` references resolve to codelists declared in the spec |
| `BR04`       | All `MethodDef` references resolve                                   |
| `ALG01`      | `assign_no_ct` has `source_variable`                                 |
| `ALG02`      | `assign_ct` has both `source_variable` and `ct_codelist`             |
| `ALG03`      | `hardcode_*` has `constant_value`                                    |
| `ALG05`      | `merge` has `merge_dataset` and `merge_key`                          |

`validator.issues` is a list of `DefineIssue` dataclasses with fields `severity`, `location`,
`message`, and `rule`. `validator.has_errors()` returns `True` when any `"error"` severity
issues exist. Warnings do not block Define-XML generation.

### When to run each layer

| Layer              | When it fires                             | Blocks execution?                                               |
| ------------------ | ----------------------------------------- | --------------------------------------------------------------- |
| Pydantic models    | Automatically on `.from_spec()` call      | Yes — raises `ValidationError`                                  |
| `DefineValidator`  | Manually, before Define-XML generation    | Only `has_errors()` returns `True`; you decide how to handle it |
| CDISC Rules Engine | Manually, after datasets are materialised | No — report only                                                |

### JSON Schema & Editor Support

The YAML spec is validated against the bundled schema at:

```
src/fleet/define_xml/schemas/define_spec_schema.json
```

Add this comment to the top of every spec file to activate YAML language-server auto-complete in
VS Code or any LSP-enabled editor:

```yaml
# yaml-language-server: $schema=../../../src/fleet/define_xml/schemas/define_spec_schema.json
```

---

## Tips

- The `inputs` block declares which upstream datasets the pipeline should join/merge.
- Variables with no `derivation` block are expected to flow in via the `source` dataset — they appear in Define-XML as `origin: CRF`.
- Run `DefineValidator("...").validate(Path("specs/.../define.yaml"))` to catch schema and business rule errors before generating Define-XML or running pipelines.
