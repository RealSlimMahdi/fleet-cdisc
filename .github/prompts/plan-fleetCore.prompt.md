# Plan: fleet-core — Rust CDISC Conformance Engine

A standalone Rust workspace that reimplements the CDISC CORE Rules Engine with full SDTM/ADaM support, 40+ operations, custom rules, and multiple compilation targets (CLI, WASM, PyO3, static binary). Uses Apache Arrow for zero-copy columnar data, Rayon for parallel rule execution, and a clean trait-based design for long-term maintainability.

---

## Architecture

```
fleet-core/                 (Cargo workspace)
├── crates/
│   ├── core/               # Library — all validation logic
│   │   └── src/
│   │       ├── lib.rs
│   │       ├── rule/       # Rule model + YAML parser
│   │       ├── engine/     # Orchestrator + applicability filter
│   │       ├── operators/  # ~50 check operators (equal_to, empty, regex, date, set, uniqueness)
│   │       ├── operations/ # ~40 pre-check ops (record_count, distinct, mean, codelist, MedDRA...)
│   │       ├── dataset/    # Arrow-backed Dataset trait
│   │       ├── readers/    # XPT, Dataset-JSON, Parquet
│   │       ├── metadata/   # CDISC Library cache + CT + define-xml
│   │       ├── report/     # JSON + XLSX output
│   │       └── dsl/        # Lean DSL parser (logos + chumsky)
│   ├── cli/                # Clap CLI (matches CORE flags)
│   │   ├── src/main.rs
│   │   └── Cargo.toml
│   ├── pyo3/               # Python bindings
│   │   ├── src/lib.rs
│   │   └── Cargo.toml
│   └── wasm/               # Browser target
│       ├── src/lib.rs
│       └── Cargo.toml
├── rules/                  # Bundled CDISC YAML rules
├── cache/                  # Pre-populated library metadata
├── tests/                  # Integration tests
└── benches/                # Criterion benchmarks
```

---

## Phase 1: Foundation

### Step 1 — Project scaffold

- Initialize Cargo workspace with `crates/core`, `crates/cli`
- CI (GitHub Actions): `cargo check`, `cargo test`, `cargo clippy`, `cargo fmt --check`
- Dependencies: `serde`, `serde_yaml`, `serde_json`, `rayon`, `thiserror`, `arrow`

### Step 2 — Dataset abstraction layer

Arrow-backed columnar dataset with trait-based access:

```rust
trait Dataset: Send + Sync {
    fn column(&self, name: &str) -> Option<&Column>;
    fn column_names(&self) -> &[String];
    fn row_count(&self) -> usize;
    fn domain(&self) -> &str;
    fn filter(&self, mask: &BooleanArray) -> Self;
}
```

- `Column` enum wrapping Arrow arrays (String, Int64, Float64, Boolean, Date, DateTime)
- `ArrowDataset` backed by `arrow-rs` RecordBatch

### Step 3 — Data readers

- **Dataset-JSON v1.1** — serde_json streaming → Arrow RecordBatch
- **XPT (SAS Transport v5/v8)** — readstat-sys FFI or pure-Rust parser
- **Parquet** — parquet-rs → Arrow RecordBatch (zero-copy)
- Auto-detect format from file extension + magic bytes

### Step 4 — Rule model (CORE-compatible)

Serde structs matching the CDISC CORE YAML schema:

```rust
struct Rule {
    core_id: String,
    description: String,
    rule_type: RuleType,
    scope: Scope,
    check: Check,
    operations: Vec<Operation>,
    outcome: Outcome,
    authorities: Vec<Authority>,
    sensitivity: Sensitivity,
}

struct Scope {
    classes: Option<IncludeExclude>,
    domains: Option<IncludeExclude>,
    entities: Option<IncludeExclude>,
}

enum Check {
    All(Vec<Condition>),
    Any(Vec<Condition>),
    Not(Box<Check>),
}

struct Condition {
    name: String,
    operator: String,
    value: Option<ConditionValue>,
    value_is_literal: Option<bool>,
    prefix: Option<usize>,
    suffix: Option<usize>,
    regex: Option<String>,
}

struct Operation {
    id: String,
    operator: String,
    domain: Option<String>,
    name: Option<String>,
    group: Option<Vec<String>>,
    filter: Option<HashMap<String, String>>,
}
```

- Parser: loads YAML/JSON, normalizes to internal `Rule`
- Schema validation at parse time (fail fast)

---

## Phase 2: Operators & Operations Engine

### Step 5 — Check operators (~50 operators)

Each operator is a pure function: `fn(column, value) -> BooleanArray`

```rust
trait CheckOperator: Send + Sync {
    fn evaluate(&self, target: &Column, value: &OperatorValue, ctx: &EvalContext) -> Result<BooleanArray>;
}
```

| Group          | Operators                                                                                                                                                   |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Relational     | `equal_to`, `not_equal_to`, `greater_than`, `less_than`, `greater_than_or_equal_to`, `less_than_or_equal_to`, `empty`, `non_empty`                          |
| String         | `starts_with`, `ends_with`, `matches_regex`, `longer_than`, `shorter_than`, `has_equal_length`, `contains`, `does_not_contain`, `contains_case_insensitive` |
| Set Membership | `is_contained_by`, `is_not_contained_by`, `contains_all`, `not_contains_all`, `prefix_is_contained_by`, `suffix_is_contained_by`                            |
| Date/Time      | `date_equal_to`, `date_less_than`, `date_greater_than`, `is_complete_date`, `is_incomplete_date`, `invalid_date`, `invalid_duration`                        |
| Uniqueness     | `is_unique_set`, `is_not_unique_set`, `is_unique`, `is_not_unique`                                                                                          |
| Metadata       | `exists`, `not_exists`                                                                                                                                      |
| Consistency    | `is_inconsistent_across_dataset`, `has_same_values`, `has_different_values`, `value_has_multiple_references`                                                |

Operator registry: `HashMap<&str, Box<dyn CheckOperator>>` populated at startup.

### Step 6 — Operations engine (~40+ operations)

Operations produce computed columns/scalars that Check conditions reference via `$variable_id`.

```rust
trait Operation: Send + Sync {
    fn execute(&self, params: &OperationParams, ctx: &EngineContext) -> Result<OperationResult>;
}

enum OperationResult {
    Scalar(Value),
    Series(Column),
    DataFrame(Box<dyn Dataset>),
}
```

| Group            | Operations                                                                                                                                                                                                                |
| ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Aggregation      | `record_count`, `max`, `min`, `mean`, `max_date`, `min_date`, `variable_count`, `variable_value_count`                                                                                                                    |
| Domain/Dataset   | `dataset_names`, `study_domains`, `domain_is_custom`, `related_domain_is_custom`, `domain_label`, `standard_domains`                                                                                                      |
| Library/Metadata | `variable_names`, `required_variables`, `expected_variables`, `permissible_variables`, `get_column_order_from_library`, `get_model_filtered_variables`, `get_library_class_domains`                                       |
| Codelist/CT      | `codelist_terms`, `codelist_extensible`, `valid_codelist_dates`, `get_codelist_attributes`                                                                                                                                |
| External Dict    | `valid_meddra_code_references`, `valid_meddra_term_references`, `valid_meddra_code_term_pairs`, `valid_whodrug_references`, `whodrug_code_hierarchy`, `valid_external_dictionary_value`, `valid_external_dictionary_code` |
| Transform        | `distinct`, `map`, `dy`, `variable_exists`, `variable_is_null`, `split_by`, `extract_metadata`, `define_variable_metadata`                                                                                                |
| Dataset Build    | `get_column_order_from_dataset`, `get_dataset_filtered_variables`                                                                                                                                                         |
| Define-XML       | `valid_define_external_dictionary_version`, `define_extensible_codelists`                                                                                                                                                 |

Factory registry with `register_operation(name, impl)` for extensibility.

---

## Phase 3: Validation Orchestrator

### Step 7 — Rule applicability filter

Before executing a rule against a dataset, check:

1. `rule_applies_to_domain(rule.scope.domains, dataset.domain)`
2. `rule_applies_to_class(rule.scope.classes, dataset_class)`
3. `rule_applies_to_data_structure(rule.scope.data_structures, dataset_structure)`
4. `valid_rule_structure(rule)` — sanity check

### Step 8 — Dataset builder (per rule type)

Rule types determine how the evaluation dataset is constructed:

| Rule Type                                                 | Dataset Shape                              |
| --------------------------------------------------------- | ------------------------------------------ |
| `Record Data`                                             | Raw submission rows                        |
| `Dataset Metadata Check`                                  | One-row-per-dataset with metadata columns  |
| `Variable Metadata Check`                                 | One-row-per-variable with metadata columns |
| `Domain Presence Check`                                   | Single row, one column per domain          |
| `Value Check with Dataset Metadata`                       | Pivoted long-format + dataset metadata     |
| `Value Check against Define XML Variable`                 | Long-format + define-xml variable metadata |
| `Value Check against Define XML VLM`                      | Long-format + value-level metadata         |
| `Variables Metadata Check against Define XML and Library` | Variable + define + library metadata       |

```rust
trait DatasetBuilder: Send + Sync {
    fn build(&self, rule: &Rule, metadata: &DatasetMetadata, ctx: &EngineContext) -> Result<Box<dyn Dataset>>;
}
```

### Step 9 — Condition evaluator

- Recursively evaluate `Check` tree (all/any/not) against the built dataset
- Replace `$operation_id` references with computed values
- Apply wildcard replacement (`--` → domain prefix) in variable names
- Produce per-row boolean mask → extract failing rows → generate error objects

### Step 10 — Parallel execution via Rayon

```rust
let results: Vec<RuleValidationResult> = rules
    .par_iter()
    .map(|rule| {
        datasets.iter()
            .filter(|ds| rule_applies(rule, ds))
            .map(|ds| validate_rule_on_dataset(rule, ds, &ctx))
            .collect()
    })
    .collect();
```

---

## Phase 4: Metadata & Controlled Terminology

### Step 11 — CDISC Library cache reader

- Cache format: MessagePack files on disk (`cache/` directory)
- Structs: `StandardMetadata`, `ClassMetadata`, `DatasetDefinition`, `VariableDefinition`
- Loaded once at engine start, shared via `Arc<LibraryMetadata>`
- CLI subcommand: `fleet-core cache update --api-key <KEY>`

### Step 12 — Controlled Terminology

- Load CT packages from cache (codelist → terms mapping)
- Variable-to-codelist mapping per standard/version
- Extensible vs non-extensible codelist enforcement

### Step 13 — Define-XML reader

- Parse define.xml (v2.0/v2.1) via `quick-xml`
- Extract: dataset definitions, variable metadata, value-level metadata, codelists, methods
- Expose as `DefineXmlMetadata` for rule types that reference define columns

---

## Phase 5: Lean DSL (Rust-like Rule Expressions)

### Step 14 — Syntax design

```
rule "AE_MISSING_DECOD" {
    standard: sdtmig 3.4
    domain: AE
    sensitivity: record

    when AEDECOD.is_empty() & AETERM.is_not_empty() {
        error("AEDECOD is missing when AETERM is populated",
              output: [USUBJID, AETERM, AEDECOD])
    }
}

rule "DM_AGE_RANGE" {
    standard: sdtmig 3.4
    domain: DM
    sensitivity: record

    let avg_age = mean(DM.AGE)
    when AGE > avg_age * 3 {
        warning("AGE is more than 3x the study average")
    }
}

rule "EX_DY_CALCULATION" {
    standard: sdtmig 3.4
    domain: EX
    sensitivity: record

    let expected_dy = dy(EXSTDTC, DM.RFSTDTC)
    when EXSTDY.is_not_empty() & EXSTDTC.is_complete_date() & EXSTDY != expected_dy {
        error("EXSTDY does not match calculated study day")
    }
}
```

### Step 15 — DSL parser + compiler

- Lexer: `logos` crate
- Parser: `chumsky` crate → AST
- Compile AST to internal `Rule` struct (same execution path as CORE YAML)
- DSL is a thin syntax layer — no separate runtime

---

## Phase 6: Output & Reporting

### Step 16 — JSON report

- Match CORE's output schema: `Rules_Report`, `Issue_Summary`, `Issue_Details`, `Conformance_Details`
- Streaming JSON writer (don't buffer entire report in memory)

### Step 17 — XLSX report

- `rust_xlsxwriter` crate
- Tabs: Rules Report, Issue Summary, Issue Details, Dataset Details, Conformance Details
- Template matching CORE's Excel format

---

## Phase 7: Compilation Targets

### Step 18 — CLI binary (`crates/cli/`)

```bash
# Validate SDTM datasets
fleet-core validate -s sdtmig -v 3-4 -d /path/to/data

# With custom rules
fleet-core validate -s sdtmig -v 3-4 -d /data -lr /custom/rules

# Specific rules only
fleet-core validate -s sdtmig -v 3-4 -d /data -r CORE-000001 -r CORE-000002

# ADaM validation
fleet-core validate -s adam -v 1-1 -d /path/to/adam/data

# Cache management
fleet-core cache update --api-key <KEY> -s sdtmig -v 3-4
fleet-core cache list

# Lint a rule file
fleet-core rule check /path/to/rule.yaml
fleet-core rule check /path/to/rule.rule  # lean DSL

# Output formats
fleet-core validate -s sdtmig -v 3-4 -d /data -o json
fleet-core validate -s sdtmig -v 3-4 -d /data -o xlsx
```

### Step 19 — PyO3 bindings (`crates/pyo3/`)

```python
from fleet_core import Engine, ValidationConfig

engine = Engine(cache_path="./cache")
config = ValidationConfig(
    standard="sdtmig",
    version="3-4",
    dataset_paths=["/data/ae.xpt", "/data/dm.xpt"],
    custom_rules_path="/rules",
)
result = engine.validate(config)

# Access results as Python objects
for issue in result.issues:
    print(f"{issue.rule_id}: {issue.message} [{issue.severity}]")
    for error in issue.errors:
        print(f"  Row {error.row}: {error.values}")
```

### Step 20 — WASM target (`crates/wasm/`)

- `wasm-bindgen` interface for browser-based rule validation
- Accepts Dataset-JSON input (no filesystem access)
- Returns JSON validation report
- Useful for rule editors / interactive validation UIs

---

## Phase 8: Testing & Benchmarks

### Step 21 — Unit tests

- Every operator: property-based tests with `proptest`
- Every operation: deterministic test with known input/output
- Rule parser: roundtrip YAML → Rule → re-serialize
- DSL parser: roundtrip `.rule` → AST → `Rule` → YAML

### Step 22 — Integration tests

- Golden-file tests: run known rules against known datasets, assert exact output
- Use CORE's test fixtures from `cdisc-org/cdisc-rules-engine` as reference
- Fleet's 15 custom rules (`metadata/custom_rules/SDTMCHK-*.yaml`) against test data
- Cross-validate: same rules + same data → compare output against Python CORE

### Step 23 — Benchmarks (Criterion)

- Single-rule latency: target <1ms per rule on 10K-row dataset
- Full-study throughput: 500 rules × 20 datasets
- Memory profiling with DHAT
- Compare against CORE Python engine on identical workloads

---

## Key Dependencies

| Crate                                 | Purpose                         |
| ------------------------------------- | ------------------------------- |
| `arrow` + `parquet`                   | Columnar data + Parquet I/O     |
| `serde` + `serde_yaml` + `serde_json` | Rule parsing, cache, output     |
| `rayon`                               | Parallel rule execution         |
| `clap`                                | CLI argument parsing            |
| `quick-xml`                           | Define-XML parsing              |
| `rust_xlsxwriter`                     | Excel report generation         |
| `logos` + `chumsky`                   | DSL lexer + parser              |
| `pyo3` + `maturin`                    | Python bindings + build         |
| `wasm-bindgen`                        | WASM target                     |
| `thiserror` + `anyhow`                | Error handling                  |
| `tracing`                             | Structured logging              |
| `rmp-serde`                           | MessagePack cache serialization |
| `criterion`                           | Benchmarking                    |
| `proptest`                            | Property-based testing          |
| `regex`                               | Regex operators                 |
| `chrono`                              | Date/time handling              |

---

## Design Decisions

| Decision                        | Rationale                                                                                               |
| ------------------------------- | ------------------------------------------------------------------------------------------------------- |
| **Arrow as internal format**    | Zero-copy from Parquet, efficient columnar ops, SIMD-friendly                                           |
| **No JSONata in v1**            | Requires JS runtime; mark JSONata rules as "not executable" in report. Defer to Phase 9 (embed QuickJS) |
| **Cache-only (no network)**     | Deterministic, reproducible validation. `cache update` CLI fetches offline                              |
| **CORE YAML is primary format** | Interop with published CDISC rules. DSL compiles to same internal model                                 |
| **Standalone repo**             | Consumed via PyPI wheel (`fleet-core`), `cargo install fleet-core`, or static binary                    |
| **Trait-based extensibility**   | New operators/operations register without touching core logic                                           |
| **No global mutable state**     | `EngineContext` passed explicitly; thread-safe by construction                                          |
| **Fail fast on invalid rules**  | Schema validation at parse time, not at execution time                                                  |

---

## Future Phases (Post-v1)

| Phase    | Feature                                                                               |
| -------- | ------------------------------------------------------------------------------------- |
| Phase 9  | JSONata support via embedded QuickJS                                                  |
| Phase 10 | Incremental validation (delta mode via file hashes)                                   |
| Phase 11 | Rule versioning — manifest tying rules cache to engine version                        |
| Phase 12 | Language Server Protocol for DSL (syntax highlighting, diagnostics, go-to-definition) |
| Phase 13 | GPU-accelerated operators via `cudf` / Arrow compute kernels                          |
| Phase 14 | Distributed validation (split large studies across nodes)                             |

---

## Verification Checklist

- [ ] `cargo clippy --all-targets -- -D warnings` — zero warnings
- [ ] `cargo test` — all unit + integration tests pass
- [ ] `cargo fmt --check` — consistent formatting
- [ ] Run Fleet's 15 custom rules → identical output to CORE
- [ ] Validate cdiscpilot01 SDTM with full ruleset → compare to CORE report
- [ ] Criterion: single-rule <1ms / 10K rows
- [ ] PyO3: `pytest` calling `fleet_core.Engine().validate()` from Python
- [ ] WASM: browser test loading Dataset-JSON + 5 rules
- [ ] Binary size: CLI <20MB statically linked
- [ ] Memory: peak RSS <500MB for 500-rule × 20-dataset study
