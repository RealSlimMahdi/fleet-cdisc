# Fleet — Project Structure

> A CDISC SDTM/ADaM derivation toolkit built on Polars namespace extensions.

---

## Repository Layout

```
Fleet/
├── src/fleet/          # Main package
│   ├── __init__.py         # Public API surface + namespace registration
│   ├── _version.py         # Package version (from git tags)
│   ├── core/               # Shared foundation (verb mixin, spec registry, pins, log)
│   ├── ct/                 # Controlled terminology
│   ├── io/                 # Data loading / saving
│   ├── sdtm/               # SDTM namespace (verbs + TDD) — call `.verbs()` for the live list
│   ├── adam/               # ADaM namespace + TA extensions
│   ├── tlg/                # TLG namespace — tables, listings, template registry, render
│   ├── tools/              # migrate codemod (old → canonical spellings)
│   ├── define_xml/         # Define-XML validation + generation + schema_builder
│   ├── validation/         # CDISC rules-engine integration
│   └── comparison/         # fleet.compare — PROC COMPARE analogue in pure Polars
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
│   ├── build_llms.py       # llms.txt generator (run: uv run python scripts/build_llms.py)
│   └── gen_cli_docs.py     # docs/getting-started/cli.md generator (GENERATED — do not hand-edit)
├── llms.txt                # LLM context file — GENERATED, do not edit by hand
├── pyproject.toml          # Build config, dependencies, tool settings
└── uv.lock                 # Locked dependency tree
```

---

## `src/fleet/` — Module by Module

### `__init__.py` — Package Entry Point

Importing `fleet` does two things automatically:

1. **Registers namespace extensions** on all Polars DataFrames **and LazyFrames** (`df.sdtm`, `df.adam` with sub-namespaces `df.adam.adsl` / `df.adam.occds` / …, `df.tlg`)
2. **Re-exports the full public API** so everything is reachable from one import

```python
import fleet  # registers df.sdtm, df.adam (+ .adsl/.occds/…), df.tlg everywhere
```

---

### `core/` — Shared Foundation

| File                    | Purpose                                                                                                                                                                                                                        |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `_verb_mixin.py`        | `SharedVerbsMixin` — the canonical cross-namespace verbs (`assign`, `case_when`, `merge`, `keep`, `source`, `derivation`, `duration`, `study_day`, `seq`, `select`, `nodup`, `validate`, `verbs`), plus `to_frame`/`from_spec`/`to_spec_yaml`, `_chain()`, and column-typo did-you-mean errors |
| `_flag_mixin.py`        | `FlagCriterionMixin` — the `flag` family (`flag`, `flag_first`, `flag_last`, `flag_extreme`, `flag_exists`, `flag_relative`) shared across SDTM and ADaM; validates params per criteria mode                                    |
| `spec_registry.py`      | **Single source of truth for spec-executable algorithms** — `@spec_algorithm` declarations drive the `from_spec` executor, discriminated-union Pydantic models (`extra=forbid`), the JSON schema, and the `coverage_matrix()` / `SPEC_UNSUPPORTED` allowlist |
| `define_spec.py`        | **Single ingest boundary for spec files** — `load_define_spec()` + the `DefineSpec`/`DatasetEntry`/`VariableEntry` envelope models (`extra=forbid` at the top and dataset level). Used by `from_spec`, `build_dag`, and NSV metadata resolution so a typo'd key fails at load instead of silently deriving nothing |
| `log.py`                | `logging.getLogger("fleet")` setup — replaces the old `print()` calls in `inspect`/`trail`/`nodup`/`validate` so batch runs can route/suppress output                                                                          |
| `exceptions.py`         | Custom exceptions — `FleetError` base, `DerivationError`/`VerbUsageError`/`PinError`/`SpecError`/`SchemaError` (dual-inherit builtins so both `except FleetError` and `except ValueError` styles catch)                          |
| `study_context.py`      | `StudyContext` — wraps a study root directory and resolves configured paths (raw data, SDTM, ADaM, metadata, outputs). Loaded via `load_study_context(config_path)` from a YAML file.                                          |
| `dag.py`                | `PipelineDAG`, `PipelineNode`, `VariableNode`, `PinDependency` — pipeline + variable-level lineage graph; recursive `.trace()`, input reconciliation, `output_format:` handling                                                |
| `algorithm_resolver.py` | Resolves a Fleet verb name (`algorithm:`) or dotted callable (`callable:`) to its docstring + qualified path; powers Define-XML method enrichment                                                                              |
| `derivation.py`         | `Derivation` protocol dataclass and `@derivation` decorator — wraps study-specific Python functions as typed, auto-registered derivation objects with `kind`, `targets`, `sources`, and `dotted_path`                          |
| `lineage.py`            | `record_lineage(owner, exprs)` / `lineage_of(namespace)` / `record_pin_lineage()` / `pin_lineage_of()` / `_append_lineage_nodes()` — invoked by `_chain()` and pin-powered verbs to track intra-frame and cross-domain lineage |
| `_pin_mixin.py`         | `PinMixin` — attaches reference-domain DataFrames to pipeline instances; provides `.pin()`, `.repin()`, FK validation (batched at `to_frame()`), and `.pins()` introspection; pins/lineage survive sub-namespace switches       |
| `rules_scaffolder.py`   | `RulesScaffolder` — fetches CDISC conformance rules from the Library API and writes per-domain YAML files into `metadata/sdtm/rules/` and `metadata/adam/rules/`                                                               |
| `scaffolder.py`         | `DefineScaffolder` — generates `define.yaml` from the CDISC Library IG for SDTM and ADaM domains                                                                                                                               |

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

The `assign` SDTM verb (with `ct=`) and the `recode` ADaM verb use the singleton automatically when no explicit mapping is provided.

---

### `io/` — Data Loading and Saving

| File              | Purpose                                                        |
| ----------------- | -------------------------------------------------------------- |
| `loaders.py`      | Functions for loading raw data and optionally saving           |
| `dataset_json.py` | CDISC Dataset-JSON v1.1 writer & reader (pure Polars, no deps) |

**Key functions:**

| Function            | Signature                          | What it does                                                |
| ------------------- | ---------------------------------- | ----------------------------------------------------------- |
| `load_raw_data`     | `(file_path, file_type=None)`      | Returns a `pl.LazyFrame` — auto-detects CSV, Excel, Parquet |
| `load_datasets`     | `(directory, pattern="*.csv")`     | Loads all matching files in a directory                     |
| `download_raw_data` | `(url, destination)`               | Downloads a file from a URL                                 |
| `save_parquet`      | `(df, path)`                       | Writes a Polars DataFrame to Parquet                        |
| `save_xpt`          | `(df, path)`                       | Writes to SAS XPT (requires `pyreadstat`)                   |
| `save_dataset_json` | `(df, path, *, domain, label=...)` | Writes CDISC Dataset-JSON v1.1 (no external deps)           |
| `read_dataset_json` | `(path)`                           | Reads a Dataset-JSON v1.1 file back into a Polars DataFrame |

---

### `sdtm/` — SDTM Derivation Namespace

The core of Fleet for SDTM work. Registers `df.sdtm` on every Polars DataFrame.

| File           | Purpose                                                                                                                         |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `models.py`    | `SDTMAlgorithm` enum (verb names, kept in sync with `spec_registry`), `SDTMVariableSpec`, `SDTMDomainSpec`                       |
| `utils.py`     | Internal helpers — `to_iso8601_date`, `to_iso8601_datetime`, `parse_expression(str) → pl.Expr` (AST whitelist; bare names in arithmetic resolve to `pl.col`) |
| `namespace.py` | `SDTMNamespace` — the SDTM namespace class + `_tdd_mixin` for Trial Design domains                                              |
| `tdd.py`       | Trial Design row/collection Pydantic models (TE/TA/TV/TS/TI/TD/TM), `TrialVisits.from_schedule`, `TrialParameters.from_ctgov`, Mermaid parser |
| `design.py`    | `StudyDesign` — define-once aggregate deriving every TDD domain; YAML/Mermaid/USDM interchange                                   |
| `tdd_audit.py` | P21-style conformance pre-check (SD-series structural rules + FDA TS parameter profile)                                          |
| `_tdd_structures.yaml` | Packaged SDTMIG 3.4 structures for the nine TDD domains (offline `fetch_structure()`)                                    |

**Canonical SDTM verbs** (call `df.sdtm.verbs()` for the always-current list — hardcoded counts rot):

| Verb                 | Signature                                                | Purpose                                                 |
| -------------------- | -------------------------------------------------------- | ------------------------------------------------------- |
| `assign`             | `(target, *, source=None, value=None, ct=None, ct_map=None)` | The one assignment verb — copy / hardcode / CT decode |
| `case_when`          | `(target, *, when, else_=None)`                          | The one conditional — ordered `{condition, value}` branches |
| `date`               | `(target, *, source=None, value=None, output=None, ...)` | Parse date/datetime → ISO 8601; preserves partial dates |
| `condition_add`      | `(target, *, condition, then_value)`                     | `IF condition THEN value ELSE NULL`                     |
| `ae_aerel`           | `(target="AEREL", *, source, aerel_map=None)`            | Standard adverse-event relatedness mapping              |
| `merge`              | `(dataset, *, on, how="left", keep=None, where=None)`    | The one join verb (subsumes `lookup`)                   |
| `keep`               | `(*columns)`                                             | Restrict frame to named columns                         |
| `group_by`           | `(*, by, agg)`                                           | Group-and-aggregate to produce summary rows             |
| `notsubmitted`       | `(*targets)`                                             | Set one or more columns to null (not for submission)    |
| `multiple_responses` | `(target, *, source, delimiter="\|", id_cols=None)`      | Expand pipe-delimited fields into separate rows         |
| `flag` family        | `flag`, `flag_first`, `flag_last`, `flag_extreme`, `flag_exists`, `flag_relative` | Criteria-driven `"Y"` flags |
| `nodup`              | `(*, subset, sort_by=None, keep=None)`                   | Report or deduplicate rows by subset keys               |

Renamed in pre-alpha (removed outright, `fleet migrate` rewrites old scripts): `assign_no_ct`/`assign_ct`/`hardcode_no_ct`/`hardcode_ct`/`dataset_level` → `assign`; `if_then_else` → `case_when`; the `groups=`/`group_cols=`/`group_by=` kwargs → `by=`.

**Special methods:**

| Method                      | Purpose                                                                  |
| --------------------------- | ------------------------------------------------------------------------ |
| `from_spec(spec_path)`      | Load a YAML spec file and replay all its variable mappings automatically |
| `validate(domain, version, *, custom_rules=None)` | Run CDISC rules-engine validation on the result (optionally with custom rules dir) |
| `inspect(prefix)`           | Materialise pipeline, log schema/shape/head, return checkpoint           |
| `explain()`                 | Print the Polars query plan without materialising                        |
| `trail()`                   | Print a table of each derived variable's origin (verb + source columns)  |
| `to_frame()`                | **Materialise** — execute the whole pipeline and return a `pl.DataFrame` |

**How the pipeline works:**  
Every verb returns a _new_ namespace instance (via `copy.copy(self)`) with its expression appended to an internal lazy plan. Most verbs are pure lazy `with_columns` and only run at `to_frame()`; a few (window functions like `baseline`, cross-domain joins, `date`-with-time) checkpoint internally via `_materialise_then` and re-wrap the collected frame so the **chain is never broken** — `flag → baseline → chg` is a single pipeline. The namespaces are registered on both `pl.DataFrame` and `pl.LazyFrame`, so `pl.scan_parquet(...).sdtm` stays lazy. Both `_chain` and `_materialise_then` use `copy.copy` to preserve all instance state (lineage, pins, domain) across chaining calls and sub-namespace switches.

---

### `adam/` — ADaM Derivation Namespace

Registers `df.adam` on every Polars DataFrame.

| File           | Purpose                                                                                                                                                                                                       |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `models.py`    | `ADAMAlgorithm` enum (verb names, kept in sync with `spec_registry`), `ADAMVariableSpec`, `ADAMDatasetSpec`                                                                                                   |
| `_mixins.py`   | `SharedADaMVerbsMixin` — the shared verbs available on **every** ADaM sub-namespace (`assign`, `case_when`, `merge`, `source`, `derivation`, `recode`, `whereclauses`, `merge_adsl`, `date`, `duration`, `pick`, `first_date`, `last_date`, `count_events`, `join_adsl`, …); `MultiRowMixin` for `seq` |
| `utils.py`     | Standard ADaM calculation functions — all return `pl.Expr`: `study_day`, `baseline`, `chg`, `pchg`, `bmi`, `bsa`, `mean_arterial_pressure`, `qtc`, `age_in_years`, `nrind`, `on_treatment`, `shift`           |
| `namespace.py` | `AdamNamespace` — the BDS namespace; BDS-specific verbs (`baseline`, `chg`, `pchg`, `bmi`, `bsa`, `map`, `qtc`, `nrind`, `on_treatment`, `shift`), record-generating verbs (`derive_summary_records`, `derive_locf_records`, `derive_param`), toxicity grading (`atoxgr`, `combine_grades`), `transform`, and the sub-namespace properties (`adsl`, `occds`, `onco`, …) |
| `grading/`     | CTCAE / DAIDS toxicity-grading sub-package (see below)                                                                                                                                                        |

**Canonical ADaM verbs** (call `df.adam.verbs()` for the live list). The shared mixin (`assign`, `case_when`, `merge`, `source`, `derivation`, `recode`, `whereclauses`, `date`, `duration`, `flag`, `keep`, `pick`, …) is inherited by every sub-namespace, so a whole ADaM derivation can stay in one chain:

| Verb             | Signature                                                    | Purpose                                                       |
| ---------------- | ------------------------------------------------------------ | ------------------------------------------------------------- |
| `source`         | `(*targets, from_col=None)`                                  | Variadic copy of column(s) from the predecessor dataset       |
| `assign`         | `(target, *, source=None, value=None, ct=None, ct_map=None)` | Copy / hardcode / rename / CT decode                          |
| `case_when`      | `(target, *, when, else_=None)`                              | Multi-branch conditional derivation                           |
| `derivation`     | `(target, *, expression)`                                    | Polars expression string, `pl.Expr`, lambda, or `@derivation` |
| `recode`         | `(target, *, source, recode_map, default=None)`              | Map raw values to new values                                  |
| `merge`          | `(dataset, *, on, how="left", keep=None, where=None)`        | Join a reference dataset (subsumes `lookup`)                  |
| `baseline` / `chg` / `pchg` | `(target, *, aval=..., baseline_flag=..., by=...)`| Baseline value / change / percent change (window verbs)       |
| `duration`       | `(target, *, start, end, unit="days", out="numeric")`        | Elapsed time / study day between two date columns             |
| `whereclauses`   | `(*, where)`                                                 | Filter rows by an expression                                  |

Renamed in pre-alpha (removed outright, `fleet migrate` rewrites old scripts): `assigned`/`rename` → `assign`; `condderivation` → `case_when`; `lookup` → `merge`; kwargs `groups=`/`by_vars=` → `by=`, `keep_cols=`/`target_cols=` → `keep=`. There is no `std_function` verb — the calculations are individual verbs.

**Special methods** (shared across SDTM and ADaM via `SharedVerbsMixin`):

| Method                       | Purpose                                            |
| ---------------------------- | -------------------------------------------------- |
| `from_spec(spec_path, *, dataset=None, strict=True, overwrite=False, only=, omit=)` | Table-driven spec executor (shared with SDTM via `SharedVerbsMixin`); registry-validated |
| `to_spec_yaml(dataset=None, path=None)` | Reverse: emit a define.yaml from the pipeline's lineage (registry verbs → real blocks, others → `callable` stubs) |
| `verbs()`                    | List the namespace's public verbs (+ summaries)    |
| `validate(dataset, version, *, custom_rules=None, on_fail="warn")` | CDISC rules-engine validation; `.last_validation` holds the result |
| `inspect(prefix)`            | Materialise pipeline, log state, return checkpoint |
| `explain()`                  | Print query plan without materialising             |
| `trail()`                    | Print each derived variable's origin (verb + sources) |
| `to_frame()`                 | Materialise and return `pl.DataFrame`              |

**Toxicity grading verbs (CTCAE / DAIDS):**

| Verb             | Signature                                                          | Purpose                                           |
| ---------------- | ------------------------------------------------------------------ | ------------------------------------------------- |
| `atoxgr`         | `(target, *, system, direction, term_var, unit_var=None, ...)`     | Derive toxicity grades 0–4 using CTCAE or DAIDS   |
| `combine_grades` | `(target="ATOXGR", *, low_var="ATOXGRL", high_var="ATOXGRH", ...)` | Combine low (negative) and high (positive) grades |

**`grading/` sub-package:**

| File              | Purpose                                                                                 |
| ----------------- | --------------------------------------------------------------------------------------- |
| `_models.py`      | Pydantic models for the criteria DSL: `CriteriaFile`, `TermCriteria`, `GradeRule`, etc. |
| `_compiler.py`    | Translates JSON criteria into Polars `when/then/otherwise` expression chains            |
| `_registry.py`    | `GradingSystem` enum (8 systems) and `load_criteria()` with caching                     |
| `criteria/*.json` | Bundled grading criteria (CTCAE v4/v5/v6 + DAIDS, each with SI and USCV units)          |

---

### `tlg/` — Tables, Listings, and Graphs

Registers `df.tlg` on every Polars DataFrame. Produces Analysis Results Datasets (ARDs) — long-format statistic frames with a display-rounding step at render time.

| File                 | Purpose                                                                                                                          |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `namespace.py`       | `TLGNamespace` — root namespace with 9 sub-namespace properties (`ae`, `vs`, `lb`, `eg`, `cm`, `ex`, `dm`, `ds`, `mh`) + `catalog()` |
| `<domain>_namespace.py` | One module per domain (`ae_namespace.py`, `vs_namespace.py`, `lb_namespace.py`, …) — summary/listing methods + spec models   |
| `_registry.py`       | Open **template registry** — `TemplateMeta`, `TEMPLATES`, `catalog()`, `register_template()`, `unregister_template()`            |
| `_runner.py`         | YAML-as-workflow: `load_spec(path)`, `run_spec(spec, df, adsl=...)`, `spec_schema(template_id)`, `NAMESPACE_CLASSES` dispatch    |
| `_builder.py`        | `TLGBuilder` — shared fluent builder (`by`, `template`, `rows`, `stats`, `value`, `label`, `decimals`, `to_ard`, `to_listing`, `to_html`/`to_rtf`/`to_pdf`/`to_pptx`) |
| `_specs.py`          | Pydantic spec models: `TLGSpec`, `AESummarySpec`, `AEListingSpec`, `VSSummarySpec`, `OverallStat`, `Row`, `Column`, `Statistic` (+ `template`/`schema_version`/`value_col`/`label_col`/`decimals` fields) |
| `_ard.py`            | ARD schema, per-statistic formatting (unrounded stats + display `fmt_fn`), validation, pool expansion, big-N computation         |
| `render/`            | **Render sub-module** — ARD in, artifact out (HTML, RTF, PDF, PPTX) + pagination                                                 |

#### `tlg/render/` — Rendering layer

| File         | Purpose                                                                                                   |
| ------------ | --------------------------------------------------------------------------------------------------------- |
| `_models.py` | Display contract models (`RenderMetadata`, `TableModel`, `ListingModel`) + shaping (`ard_to_table_model`) + `paginate`/`paginate_listing` |
| `html.py`    | Pharma-style HTML table/listing renderer with CSS; supports `{table}` injection via wrapper               |
| `rtf.py`     | ARD/model → RTF (built-in, no optional dep) with pagination                                               |
| `pdf.py`     | HTML → PDF via WeasyPrint (optional dep: `fleet-cdisc[tlg-pdf]`)                                          |
| `slides.py`  | TableModel/ListingModel → editable PPTX slides via python-pptx (optional dep: `fleet-cdisc[tlg-pptx]`)    |

**Key concepts:**

- **Template registry**: every table/listing is a registered template (id → CDISC class → namespace method → output type); `df.tlg.catalog()` lists them. The registry is open — `register_template()` adds study-specific ones.
- **Triple-mode API**: build ARDs via the inline fluent builder, a spec object (`t_summary(spec=...)`), or a YAML spec file (`load_spec` + `run_spec`). Listings use the same dual API (`to_listing` / `l_listing`).
- **`OverallStat` header rows**: whole-dataset aggregate rows emitted before hierarchy rows in the ARD.
- **`adsl_filter` / `dataset_filter`**: separate filter fields — `adsl_filter` affects denominators only; `dataset_filter` subsets the primary dataset.
- **Pool expansion**: `GroupPool` definitions duplicate rows under pooled arm labels (e.g. "Total", "All Active").
- **No CDISC ARS module**: the earlier `_ars`/`_shells` modules were removed; do not cite ARS.

---

### `define_xml/` — Define-XML Support

| File                                 | Purpose                                                                                                                                         |
| ------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `schemas/define_xml_2_1_schema.json` | JSON Schema for Define-XML 2.1 YAML representation                                                                                              |
| `schemas/define_spec_schema.json`    | JSON Schema for the higher-level `define.yaml` spec — **generated** from the algorithm registry by `schema_builder.py` (CI sync test enforces it)  |
| `schema_builder.py`                  | Builds `define_spec_schema.json` from `spec_registry` (algorithm enum, per-algorithm required fields, `fleet_spec_version`/`derivations_module`/`value_level` properties) |
| `validator.py`                       | `DefineValidator` — validates a YAML spec against the schema + business rules; `.issues` / `.has_errors()` / `.print_report()`                    |
| `generator.py`                       | `DefineXMLGenerator(path)` — converts a YAML spec into Define-XML 2.1 ODM XML; `.generate(out_path)`                                              |
| `spec_generator.py`                  | `DefineSpecGenerator(spec, enrich_methods=)` — generates Define-XML from `define.yaml`; honours `output_format:` / `value_level:` / `fleet_spec_version:`; `enrich_methods=True` emits `<MethodDef>` from verb / callable docstrings |
| `checker.py`                         | `DatasetChecker(spec, check_ct=True)` — runtime conformance check of a built dataset against its spec (columns, types, CT via inline codelists)  |

Use `algorithm:` (Fleet verb) or `callable:` (study-specific dotted path) inside `derivation:` to drive execution and `enrich_methods` enrichment.

---

### `comparison/` — Dataset Comparison (`fleet.compare`)

PROC COMPARE analogue in pure Polars (ADR 0002): pairs a **candidate** against a **base** on **keys**, matches variables by name, and returns a **comparison report** (vocabulary in `CONTEXT.md`). One join, one collect; differences never raise.

| File        | Purpose                                                                                                                                                                                                                                                      |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `engine.py` | `compare(base, candidate, *, keys, max_print=50, base_name=None, candidate_name=None)` — keyed matching, kind classification (numeric / string / temporal / boolean / other), dtype supertypes, the null-equals-null / NaN-equals-NaN rule, the long value listing |
| `report.py` | `ComparisonReport` frozen dataclass — `datasets`, `variables`, `observations`, `values`, `listing`, `flags` (named, see `FLAGS`), `settings`, `version`; `.is_equal`, `.summary`, `.to_text()`, `.print_report()`                                              |
| `text.py`   | Plain-text renderer in PROC COMPARE section order, listing grouped per observation, `max_print` limits (50 per variable, 500 overall by default)                                                                                                             |

---

### `validation/` — CDISC Rules Engine Integration

| File                | Purpose                                                                                                                                                                                                                                                  |
| ------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `engine.py`         | Engine installer and discovery — `install_engine()`, `uninstall_engine()`, `discover_engine()`, `doctor()`; manages `~/.fleet/cdisc-rules-engine/`                                                                                                       |
| `models.py`         | `Severity` enum (`ERROR/WARNING/INFO`), `ValidationIssue` dataclass, `ValidationResult` (with `.is_valid`, `.print_report(report_type="summary"/"full")`, `.save_html_report()`)                                                                         |
| `official.py`       | `OfficialCDISCValidator` — wraps the CDISC Rules Engine binary (or legacy `core.py`) via subprocess; filters cross-domain engine noise to INFO; supports `custom_rules` via `-lr`                                                                        |
| `providers.py`      | `ValidationProvider` ABC, `OfficialRulesEngineProvider` (engine wrapper)                                                                                                                                                  |
| `service.py`        | `ValidationService` — high-level `.validate_sdtm()` and `.validate_adam()` methods with optional `custom_rules` parameter                                                                                                                                |
| `rule_scaffolder.py`| `scaffold_rule()` — generates schema-valid custom rule YAML skeletons; `_scan_existing_ids()` / `_next_sequence()` for ID uniqueness and auto-increment                                                                                                  |
| `lineage_join.py`   | `enrich_with_lineage(result, lineage, *, spec_ref=None)` — joins `ValidationIssue.variable` with the pipeline `VariableNode` lineage so each issue carries `producing_verb`, `verb_method`, and `spec_ref` (cross-link from rule failure to source verb). Applied automatically by the `validate()` verb |
| `schemas/`          | Vendored CDISC rule JSON Schema (`cdisc_rule_schema.json`) for validating custom rule YAML before engine execution                                                                                                                                       |

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
    ├── test_sdtm_namespace.py           # SDTM verbs
    ├── test_adam_namespace.py           # BDS ADaM verbs (+ unbroken flag→baseline→chg chain)
    ├── test_naming_unification.py       # canonical verbs + old spellings removed
    ├── test_spec_parity.py              # registry ↔ enum ↔ JSON-schema sync
    ├── test_to_spec_yaml.py             # code → spec round-trip
    ├── test_tlg_registry.py             # TLG template registry + catalog
    ├── test_docs_examples.py            # executes docs/GUIDE code blocks (guardrail)
    └── test_define_xml.py               # validator + generator
```

Test counts drift — the file names above are indicative, not exhaustive. Run the suite for the authoritative count.

Run the suite:

```bash
uv run pytest tests/ -v
```

---

## `scripts/` — Developer Utilities

| File               | Purpose                                                                                                                                                               |
| ------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `build_llms.py`    | Generates `llms.txt` (and the README namespace block) from static strings + live `examples/*.py`. Run with `uv run python scripts/build_llms.py`; `--check` for CI.  |
| `gen_cli_docs.py`  | Generates `docs/getting-started/cli.md` from the live argparse tree. `--check` for CI. **Do not hand-edit `cli.md`.**                                                 |
| `regen_tlg_goldens.py` | Regenerates the Parquet golden ARDs used by the TLG parity tests.                                                                                                 |

`llms.txt`, the README namespace block, and `cli.md` are generated — never edit them by hand.

---

## Dependency Summary

**Core (6 dependencies):**

| Package                    | Role                                            |
| -------------------------- | ----------------------------------------------- |
| `polars ≥ 1.41.0`          | Core DataFrame engine; namespace extension host |
| `pydantic ≥ 2.0.0`         | YAML spec validation and data modelling         |
| `pyyaml ≥ 6.0`             | YAML spec / CT file parsing                     |
| `httpx ≥ 0.27.0`           | HTTP downloads (CT files, raw data)             |
| `jsonschema ≥ 4.26.0`      | Define-XML / spec schema validation             |
| `lxml ≥ 5.0.0`             | Define-XML ODM XML generation                   |

**Optional extras** (`uv sync --extra <name>`):

| Extra       | Adds                | For                                    |
| ----------- | ------------------- | -------------------------------------- |
| `io`        | `pyreadstat`        | SAS XPT read/write                     |
| `tlg-pdf`   | `weasyprint`        | TLG PDF export                         |
| `tlg-pptx`  | `python-pptx`       | TLG PPTX slide export                  |
| `migrate`   | `libcst`            | `fleet migrate` old→canonical codemod  |
| `watch`     | `watchfiles`        | `--watch` dev loop                     |
| `all`       | all of the above    | everything                             |
| `dev`       | `pytest`, `pytest-cov`, `ruff`, `blacken-docs`, `dsjson` | Dev tooling  |
