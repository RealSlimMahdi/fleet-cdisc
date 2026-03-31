# Fleet — Project Structure

> A CDISC SDTM/ADaM derivation toolkit built on Polars namespace extensions.

---

## Repository Layout

```
Fleet/
├── src/fleet/          # Main package
│   ├── __init__.py         # Public API surface + namespace registration
│   ├── _version.py         # Package version ("0.1.0")
│   ├── core/               # Shared foundation
│   ├── ct/                 # Controlled terminology
│   ├── io/                 # Data loading / saving
│   ├── sdtm/               # SDTM namespace (14 derivation verbs)
│   ├── adam/               # ADaM namespace (9 derivation verbs)
│   ├── define_xml/         # Define-XML validation + generation
│   └── validation/         # CDISC rules-engine integration
│
├── datasets/               # Example raw data (CDISCPILOT01)
├── specs/                  # YAML derivation specs per study/domain
├── tests/                  # Pytest test suite
│   ├── conftest.py         # Shared fixtures
│   ├── fixtures/           # CT files, spec YAMLs, raw CSVs for tests
│   └── unit/               # Unit tests per module
│
├── examples/               # End-to-end reference pipelines (cdiscpilot01_inline.py, …)
├── scripts/                # Developer utility scripts
│   └── build_llms.py       # llms.txt generator (run: uv run python scripts/build_llms.py)
├── llms.txt                # LLM context file — GENERATED, do not edit by hand
├── pyproject.toml          # Build config, dependencies, tool settings
└── uv.lock                 # Locked dependency tree
```

---

## `src/fleet/` — Module by Module

### `__init__.py` — Package Entry Point

Importing `fleet` does two things automatically:

1. **Registers namespace extensions** on all Polars DataFrames (`df.sdtm`, `df.adam`, `df.adsl`, `df.occds`)
2. **Re-exports the full public API** so everything is reachable from one import

```python
import fleet  # registers df.sdtm, df.adam, df.adsl, df.occds everywhere
```

---

### `core/` — Shared Foundation

| File               | Purpose                                                                                                                                                                               |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `exceptions.py`    | All custom exception classes — `FleetError`, `SDTMError`, `ADAMError`, `CTError`, `FleetIOError`, `SpecError`, `ValidationError`                                                      |
| `study_context.py` | `StudyContext` — wraps a study root directory and resolves configured paths (raw data, SDTM, ADaM, metadata, outputs). Loaded via `load_study_context(config_path)` from a YAML file. |

**`StudyContext`** is useful when your study files live in a standard directory layout and you want paths resolved automatically rather than hard-coded.

---

### `ct/` — Controlled Terminology

| File           | Purpose                                                                                                                                                                                |
| -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `loader.py`    | `load_controlled_terminology(ct_path, codelist_name=None)` — reads a YAML or CSV CT file (or downloads from a URL) and returns a nested dict: `{codelist_code: {term: decoded_value}}` |
| `validator.py` | `CTValidator` — a **thread-safe process-wide singleton** that caches loaded CT files and provides validation helpers                                                                   |

**`CTValidator` key methods:**

| Method                                  | What it does                                                                                         |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `CTValidator.get_instance()`            | Returns the singleton                                                                                |
| `.load_ct_file(path, aliases={})`       | Reads a CT file into the cache; aliases map human names to codelist codes (e.g. `{"SEX": "C66731"}`) |
| `.validate_value(codelist, value)`      | Returns `(bool, message)`                                                                            |
| `.get_valid_values(codelist)`           | Returns the set of valid terms                                                                       |
| `.apply_ct_mapping(df, col, codelist)`  | Applies CT decode to a Polars column                                                                 |
| `.register_alias(alias, codelist_code)` | Adds a name → code mapping at runtime                                                                |
| `.get_cache_info()`                     | Returns `{"codelists_loaded": n, ...}`                                                               |

The `assign_ct` SDTM verb and `recode` ADaM verb use the singleton automatically when no explicit mapping is provided.

---

### `io/` — Data Loading and Saving

| File         | Purpose                                              |
| ------------ | ---------------------------------------------------- |
| `loaders.py` | Functions for loading raw data and optionally saving |

**Key functions:**

| Function            | Signature                      | What it does                                                |
| ------------------- | ------------------------------ | ----------------------------------------------------------- |
| `load_raw_data`     | `(file_path, file_type=None)`  | Returns a `pl.LazyFrame` — auto-detects CSV, Excel, Parquet |
| `load_datasets`     | `(directory, pattern="*.csv")` | Loads all matching files in a directory                     |
| `download_raw_data` | `(url, destination)`           | Downloads a file from a URL                                 |
| `save_parquet`      | `(df, path)`                   | Writes a Polars DataFrame to Parquet                        |
| `save_xpt`          | `(df, path)`                   | Writes to SAS XPT (requires `pyreadstat`)                   |

---

### `sdtm/` — SDTM Derivation Namespace

The core of Fleet for SDTM work. Registers `df.sdtm` on every Polars DataFrame.

| File           | Purpose                                                                                                                         |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `models.py`    | `SDTMAlgorithm` enum (the 14 verb names), `SDTMVariableSpec` (Pydantic model for one variable in a YAML spec), `SDTMDomainSpec` |
| `utils.py`     | Internal helpers — `to_iso8601_date`, `to_iso8601_datetime`, `parse_expression(str) → pl.Expr` (with AST whitelist)             |
| `namespace.py` | `SDTMNamespace` — the actual namespace class with all 14 verbs                                                                  |

**The 14 SDTM derivation verbs:**

| Verb                 | Signature                                             | Purpose                                                      |
| -------------------- | ----------------------------------------------------- | ------------------------------------------------------------ |
| `assign_no_ct`       | `(target, *, source)`                                 | Direct 1:1 column copy/rename, no CT lookup                  |
| `assign_ct`          | `(target, *, source, ct_codelist, ct_mapping=None)`   | Copy column and decode values via CT codelist                |
| `assign_dtc`         | `(target, *, source, mode="date", input_format=None)` | Parse date string → ISO 8601; preserves partial dates        |
| `hardcode_ct`        | `(target, *, value, ct_codelist=None)`                | Set every row to a literal constant (CT-validated)           |
| `hardcode_no_ct`     | `(target, *, value)`                                  | Set every row to a literal constant, no CT                   |
| `condition_add`      | `(target, *, condition, then_value)`                  | `IF condition THEN value ELSE NULL`                          |
| `if_then_else`       | `(target, *, when, else_value=None)`                  | Multi-branch conditional (list of `{condition, value}`)      |
| `ae_aerel`           | `(target="AEREL", *, source, aerel_map=None)`         | Standard adverse-event relatedness mapping                   |
| `merge`              | `(target_cols=None, *, dataset, on, how="left")`      | Join another DataFrame into the pipeline                     |
| `remove_dup`         | `(*, subset=None, keep="first")`                      | Deduplicate rows by subset of columns                        |
| `group_by`           | `(*, group_cols, agg)`                                | Group-and-aggregate to produce a summary row                 |
| `dataset_level`      | `(target, *, value)`                                  | Alias for `hardcode_no_ct` — marks dataset-level constants   |
| `notsubmitted`       | `(*targets)`                                          | Set one or more columns to null (not for submission)         |
| `multiple_responses` | `(target, *, source, delimiter="\|", id_cols=None)`   | Expand pipe-delimited multi-answer fields into separate rows |

**Special methods:**

| Method                      | Purpose                                                                  |
| --------------------------- | ------------------------------------------------------------------------ |
| `from_spec(spec_path)`      | Load a YAML spec file and replay all its variable mappings automatically |
| `validate(domain, version)` | Run CDISC rules-engine validation on the result                          |
| `inspect(prefix)`           | Materialise pipeline, log schema/shape/head, return checkpoint           |
| `explain()`                 | Print the Polars query plan without materialising                        |
| `to_frame()`                | **Materialise** — execute the whole pipeline and return a `pl.DataFrame` |

**How the pipeline works:**  
Every verb returns a _new_ `SDTMNamespace` instance (via `copy.copy(self)`) with the expression appended to an internal lazy plan. Nothing executes until `to_frame()` is called, which collects the lazy frame. Both `_chain` and `_materialise_then` use `copy.copy` to preserve all instance state across chaining calls.

---

### `adam/` — ADaM Derivation Namespace

Registers `df.adam` on every Polars DataFrame.

| File           | Purpose                                                                                                                                                                                             |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `models.py`    | `ADAMAlgorithm` enum (11 verb names), `ADAMVariableSpec`, `ADAMDatasetSpec`                                                                                                                          |
| `utils.py`     | Standard ADaM calculation functions — all return `pl.Expr`: `study_day`, `baseline`, `chg`, `pchg`, `bmi`, `bsa`, `mean_arterial_pressure`, `qtc`, `age_in_years`, `nrind`, `on_treatment`, `shift` |
| `namespace.py` | `AdamNamespace` — the BDS namespace class with 24 verbs including record-generating verbs (`derive_summary_records`, `derive_locf_records`, `derive_param`) and toxicity grading (`atoxgr`, `combine_grades`) |
| `grading/`     | CTCAE / DAIDS toxicity-grading sub-package (see below)                                                                                                                                               |

**The 9 ADaM derivation verbs:**

| Verb             | Signature                                                    | Purpose                                                       |
| ---------------- | ------------------------------------------------------------ | ------------------------------------------------------------- |
| `source`         | `(target, *, from_col=None)`                                 | Copy a column from the predecessor SDTM dataset               |
| `derivation`     | `(target, *, expression)`                                    | Polars expression string or `pl.Expr` — arbitrary calculation |
| `assigned`       | `(target, *, value)`                                         | Global constant for all records                               |
| `recode`         | `(target, *, source, recode_map, default=None)`              | Map raw values to new values (like a lookup table)            |
| `rename`         | `(target, *, source)`                                        | Rename a column (e.g. `VSDTC → ADT`)                          |
| `condderivation` | `(target, *, conditions, else_value=None)`                   | Multi-branch conditional derivation                           |
| `lookup`         | `(target_cols=None, *, dataset, on, how="left", where=None)` | Join a reference dataset                                      |
| `std_function`   | `(target, *, func, ...)`                                     | Named standard ADaM functions (see below)                     |
| `whereclauses`   | `(*, where)`                                                 | Filter rows by an expression                                  |

**`std_function` — standard ADaM functions:**

| `func=`           | Extra params                      | Calculates                                   |
| ----------------- | --------------------------------- | -------------------------------------------- |
| `"study_day"`     | `analysis_date`, `reference_date` | `ADY = ADT - RFSTDTC + 1` (signed)           |
| `"baseline"`      | `aval`, `baseline_flag`           | `BASE = AVAL` at the baseline record         |
| `"chg"`           | `aval`, `base`                    | `CHG = AVAL - BASE`                          |
| `"pchg"`          | `aval`, `base`                    | `PCHG = (AVAL - BASE) / BASE * 100`          |
| `"flag_baseline"` | `baseline_criteria`               | Sets `ABLFL = "Y"` where condition is true   |
| `"bmi"`           | `height`, `weight`                | `BMI = weight / (height/100)²`               |
| `"bsa"`           | `height`, `weight`, `method`      | Body Surface Area (4 methods)                |
| `"map"`           | `systolic`, `diastolic`           | Mean Arterial Pressure                       |
| `"qtc"`           | `qt`, `rr`, `method`              | Corrected QT interval (Fridericia or Bazett) |

**Special methods** (same as SDTM):

| Method                       | Purpose                                            |
| ---------------------------- | -------------------------------------------------- |
| `from_spec(spec_path)`       | YAML-driven derivation                             |
| `validate(dataset, version)` | CDISC rules-engine validation                      |
| `inspect(prefix)`            | Materialise pipeline, log state, return checkpoint |
| `explain()`                  | Print query plan without materialising             |
| `to_frame()`                 | Materialise and return `pl.DataFrame`              |

**Toxicity grading verbs (CTCAE / DAIDS):**

| Verb             | Signature                                                                         | Purpose                                              |
| ---------------- | --------------------------------------------------------------------------------- | ---------------------------------------------------- |
| `atoxgr`         | `(target, *, system, direction, term_var, unit_var=None, ...)`                    | Derive toxicity grades 0–4 using CTCAE or DAIDS      |
| `combine_grades` | `(target="ATOXGR", *, low_var="ATOXGRL", high_var="ATOXGRH", ...)`               | Combine low (negative) and high (positive) grades     |

**`grading/` sub-package:**

| File             | Purpose                                                                                |
| ---------------- | -------------------------------------------------------------------------------------- |
| `_models.py`     | Pydantic models for the criteria DSL: `CriteriaFile`, `TermCriteria`, `GradeRule`, etc. |
| `_compiler.py`   | Translates JSON criteria into Polars `when/then/otherwise` expression chains            |
| `_registry.py`   | `GradingSystem` enum (8 systems) and `load_criteria()` with caching                    |
| `criteria/*.json` | Bundled grading criteria (CTCAE v4/v5/v6 + DAIDS, each with SI and USCV units)         |

---

### `define_xml/` — Define-XML Support

| File                                 | Purpose                                                                                                |
| ------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| `schemas/define_xml_2_1_schema.json` | JSON Schema for Define-XML 2.1 YAML representation                                                     |
| `validator.py`                       | `DefineValidator` — validates a YAML Define-XML spec against the schema; reports `DefineIssue` objects |
| `generator.py`                       | `DefineXMLGenerator` — converts a YAML spec into a Define-XML 2.1 ODM XML string                       |

The YAML key `fleet_algorithm` in a variable spec is used to record the derivation verb for traceability in the generated XML.

---

### `validation/` — CDISC Rules Engine Integration

| File           | Purpose                                                                                                                                              |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| `engine.py`    | Engine installer and discovery — `install_engine()`, `uninstall_engine()`, `discover_engine()`, `doctor()`; manages `~/.fleet/cdisc-rules-engine/`   |
| `models.py`    | `Severity` enum (`ERROR/WARNING/INFO`), `ValidationIssue` dataclass, `ValidationResult` (with `.is_valid`, `.print_report()`, `.save_html_report()`) |
| `official.py`  | `OfficialCDISCValidator` — wraps the CDISC Rules Engine binary (or legacy `core.py`) via subprocess                                                  |
| `providers.py` | `ValidationProvider` ABC, `OfficialRulesEngineProvider`, `ValidationProviderRegistry` (plugin registry)                                              |
| `service.py`   | `ValidationService` — high-level `.validate_sdtm()` and `.validate_adam()` methods                                                                   |

---

## `specs/` — Study Derivation Specifications

YAML files that describe the study metadata, derivation logic, and Define-XML output. Consumed by both `from_spec()` and the Define-XML generator.

```
specs/
└── cdiscpilot01/
    ├── sdtm/
    │   └── define.yaml   # SDTM Define-XML spec + DM derivations
    └── adam/
        └── define.yaml   # ADaM Define-XML spec + ADSL/ADVS derivations
```

**Define YAML format (single source of truth):**

```yaml
datasets:
  - name: DM
    variables:
      - name: STUDYID
        derivation:
          algorithm: hardcode_no_ct
          value: "CDISCPILOT01"
      - name: SEX
        derivation:
          algorithm: assign_ct
          source: sex
          ct_codelist: C66731
          ct_mapping:
            "F": "F"
            "M": "M"
```

---

## `datasets/` — Example Study Data

```
datasets/
└── cdiscpilot01/
    └── raw/
        ├── dm_raw.csv    # Demographics raw eCRF data
        ├── vs_raw.csv    # Vital Signs raw data
        └── ae_raw.csv    # Adverse Events raw data
```

Source: CDISC CDISCPILOT01 public example study.

---

## `tests/` — Test Suite

```
tests/
├── conftest.py                          # Shared pytest fixtures
├── fixtures/
│   ├── raw/                             # CSV copies of datasets for tests
│   ├── ct/cdisc_ct_sample.yaml          # Sample CT for CT validator tests
│   └── specs/                           # define_sdtm.yaml, define_adam.yaml
└── unit/
    ├── test_sdtm_namespace.py           # 20 tests — all 14 SDTM verbs
    ├── test_adam_namespace.py           # 24 tests — all 16 BDS ADaM verbs
    ├── test_adsl_namespace.py           # 14 tests — ADSL namespace
    ├── test_occds_namespace.py          # 12 tests — OCCDS namespace
    ├── test_ct_validation.py            #  9 tests — CT loader + validator
    └── test_define_xml.py               #  6 tests — validator + generator
```

Run the suite:

```bash
uv run pytest tests/ -v
```

---

## `scripts/` — Developer Utilities

| File            | Purpose                                                                                                                                                               |
| --------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `build_llms.py` | Generates `llms.txt` from static Python strings and live `examples/*.py` files. Run with `uv run python scripts/build_llms.py`. Use `--check` for CI stale detection. |

`llms.txt` is the only output of this script and must never be edited by hand.

---

## Dependency Summary

| Package                    | Role                                            |
| -------------------------- | ----------------------------------------------- |
| `polars ≥ 1.0.0`           | Core DataFrame engine; namespace extension host |
| `pydantic ≥ 2.0.0`         | YAML spec validation and data modelling         |
| `pyyaml ≥ 6.0`             | YAML spec / CT file parsing                     |
| `httpx ≥ 0.27.0`           | HTTP downloads (CT files, raw data)             |
| `jsonschema ≥ 4.26.0`      | Define-XML YAML schema validation               |
| `pyreadstat ≥ 1.2.0`       | SAS XPT I/O (optional, `uv sync --extra io`)    |
| `pytest, pytest-cov, ruff` | Dev tooling (`uv sync --extra dev`)             |
