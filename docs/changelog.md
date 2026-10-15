# Changelog

All notable changes to Fleet are documented here.

## [Unreleased]

### Changed

- **TLG summary specs are the engine contract** (ADR-0005) — one seam, `fleet.tlg.summarize_spec(df, spec, groupby=, adsl=)`, reads every engine argument from the spec; sixteen `df.tlg.<domain>.t_*` methods are now one call on it, and the seven composite tables (AE severity, grade and relationship, deaths, lab shift and abnormal, demographics) share `prepare_frame` before their own logic. Public method signatures are unchanged.
  - two template rules leave method bodies and become spec fields, visible in YAML and settable inline: `uncoded` (an `Uncoded(columns, label)` model, GDSR default `"No Coding Available"` on the AE, CM and MH tables; `null` switches it off) and `prefilter` (an expression string in the same form as `dataset_filter`, applied after it; default per template; `null` switches it off). Builder verbs `.uncoded()` and `.prefilter()` map onto them.
  - every column a prefilter names is a required column: `lb.t_chg` and `eg.t_chg` on a dataset without `ABLFL`, and `ex.t_summary` on a dataset without `PARCAT1`, now raise `SchemaError` instead of counting baseline or per-interval records silently. `check()` reports the missing column.
  - the dataset filter on `lb.t_shift` now bites before the worst-case reduction, as it already did on the AE tables.
  - the AE and VS spec classes moved from `fleet.tlg._specs` to their domain modules; `fleet.tlg.AESummarySpec` and friends are unchanged. `prepare_frame`, `summarize_ard` and `Uncoded` are new public names on `fleet.tlg`.

## [0.2.0a1] — pre-alpha

First pre-alpha on PyPI. It replaces 0.1.0, which is yanked. Install with `pip install --pre fleet-cdisc`.

### Added

- **Dataset comparison** — a `PROC COMPARE` analogue in pure Polars (no new dependency), reachable three ways over one engine:
  - `fleet.compare(base, candidate, keys=...)` pairs observations on keys and variables by name, and returns a `ComparisonReport` with the data set, variables, observation and values summaries, the long value listing, named flags (`values_differ`, `base_only_observations`, …) and `is_equal`
  - `.compare(base, keys=..., on_fail="warn")` on every namespace (`sdtm`, `adam`, `adsl`, `occds`, …) — the chain is the candidate, the report stays on `last_comparison`, and `on_fail` speaks the same vocabulary as `.validate()`
  - `fleet compare BASE CANDIDATE --keys K1,K2 [--all]` — exit `0` equal, `1` different, `2` the comparison could not run
  - machine-readable outputs: `report.to_json()` / `save_json(path)` render one JSON document whose keys mirror the report and are additive-only within a major version; `save_listing(path)` writes the complete value listing as parquet; `fleet compare --format json` prints the document and nothing else, `--out differences.parquet` writes the listing
  - tolerances and trailing whitespace: `abs_tol` / `rel_tol` widen equality on the numeric variables (a pair differs when the absolute difference exceeds `max(abs_tol, rel_tol × |base|)`, anchored on the **base** as in SAS), `ignore_trailing_whitespace` makes a legacy SAS dataset's padded character values equal Fleet's stripped ones; exact stays the default, nulls and NaN keep their rule, and the rule in effect shows on the text settings line, the HTML header and the JSON `settings` block. Same three options on every surface: `fleet.compare(...)`, `.compare(...)` and `fleet compare --abs-tol --rel-tol --ignore-trailing-whitespace`
  - HTML report for a reviewer without Python: `report.to_html()` / `save_html_report(path)` render one self-contained page — raised flags as chips, then only the mismatched observations with the base and candidate values side by side, one collapsible block per differing variable, sectioned per group once the listing's `group` column is populated; `fleet compare --report compare.html` writes it
  - duplicate-key override and BY groups: `allow_duplicates` pairs duplicate keys by their position within each key group instead of refusing to run — counting them per side, raising `duplicate_keys` and warning above every report — and `by` prepends the BY variables to the keys, labels every difference with its group, reports the observation and values summaries per group in text, JSON and HTML, and flags the groups found on one side only while the verdict stays global. On every surface: `fleet.compare(...)`, `.compare(...)` and `fleet compare --by TRT01P --allow-duplicates`
  - variable pairs and restriction: `pairs={"WEIGHT": "WT"}` compares two variables named differently on each side, on top of the automatic name matching, and names them after the base throughout the report; `variables=["WEIGHT", "AVISIT"]` narrows the comparison to the variables that matter, ignoring the rest on both sides so a work-in-progress candidate raises no missing-variable flag. On every surface: `fleet.compare(...)`, `.compare(...)` and `fleet compare --pairs WEIGHT=WT --variables WEIGHT,AVISIT`
  - a compare that checks no values keeps the two-value verdict (ADR-0004): sides that share only their keys follow the observations, two empty sides are EQUAL, and the report warns in both cases; `fleet compare` now prints the report and exits `1` for one-sided variables instead of exiting `2`, and a `variables=` list of keys only is refused
  - summary statistics: `report.statistics` gives, per differing numeric variable, the n, mean, std, min and max of the base, the candidate, their difference and its percent, over the matched observations where both sides are finite. A null, NaN or infinite value on either side is left out, so no measure is NaN and the text report, the HTML page and the JSON document show the same numbers (#112)

- **CDISC Library API integration** — native client (`CDISCClient`) for downloading Controlled Terminology directly from the authoritative CDISC Library REST API
  - `CDISCClient.get_packages()` — list available CT versions (SDTM, ADaM)
  - `CDISCClient.get_codelist()` — download a single codelist by NCI concept ID with version pinning
  - Credentials via `.env` file or `CDISC_API_KEY` environment variable
- **CT Code Generator** — `CodelistGenerator` converts CDISC Library JSON into typed Python constants with IDE auto-completion
  - `CodelistGenerator.from_sdtm_ig()` — derive codelists from the SDTM IG (source of truth), scoped to requested domains
  - `CodelistGenerator.from_concept_ids()` — download codelists from an explicit set of NCI concept IDs
  - Generated classes include `_concept_id` attribute, submission value constants, human-readable aliases (e.g. `SEX = C66731`), and `__all__` for clean imports
  - Optional `include_docs` flag to inject CDISC definitions into code comments
- **`fleet` CLI** bootstrapping pipeline and standalone commands:
  - `fleet init cfg` — create `study_config.yaml` with study metadata, IG versions, domains, and directory structure
  - `fleet init define` — generate `define.yaml` pre-populated with standard variables from the CDISC Library IG (SDTM + ADaM)
  - `fleet init ct` — generate `codelists.py` from codelist references in the `define.yaml` files
  - `fleet init-ct` — standalone bootstrap of `codelists.py` from the SDTM IG for given domains
  - `fleet add-ct` — incrementally add domains to an existing `codelists.py` (preserves existing codelists)
  - `fleet define-xml` — generate Define-XML 2.1 from a `define.yaml` specification (with optional HTML preview)
- **Custom Validation Rules** — sponsor-specific CDISC rule authoring and validation workflow:
  - `fleet add-rule` — scaffold a schema-valid rule YAML skeleton (auto-increments ID, uniqueness check across directory)
  - `fleet check-rule` — validate a rule file (YAML syntax + structure + JSON Schema); exits 1 on error for CI gates
  - `custom_rules=` parameter on `.validate()`, `ValidationService.validate_sdtm()`, and `.validate_adam()` — load a directory of rules via the engine's `-lr` flag
  - `validation.custom_rules` in `study_config.yaml` — team-wide default rules directory
  - `fleet init cfg` scaffolds the `custom_rules/` directory and field automatically
  - Header comments in generated rule files include CDISC operator reference link and rule type guide

- **CT assignment now accepts codelist classes** (today: `assign(ct=...)`) — pass a generated class (e.g. `SEX`) instead of a raw NCI string; `ct_map` is optional when raw data already matches CDISC submission values

- **Spec-driven CT checks use the study's `codelists.py`** — inside a study, `from_spec` resolves a `ct_codelist:` ID to the class of that ID in the generated `codelists.py`, so `algorithm: assign_ct` gives the same "values not in codelist" warning as `.assign(..., ct=<class>)`; before, the spec copied values unvalidated unless a CT file was loaded (#131)
  - stale detection: `codelists.py` gets a `__ct_package__` marker; a file from another package than `ct.package`, mixing packages, missing a referenced codelist, or missing warns once in `from_spec`, fails `fleet check` and shows in `fleet doctor`; `fleet add-ct --package` refuses another package

- **Admiral-parity expansion** — new core computations and record-generating verbs:
  - `utils.py`: `bsa()` (Body Surface Area, 4 methods), `mean_arterial_pressure()`, `qtc()` (Fridericia/Bazett), `age_in_years()` (unit-aware), `extreme_flag()` (min/max per group)
  - `df.adam`: `.bsa()`, `.map()`, `.qtc()` — namespace wrappers for the new computations
  - `df.adam`: `.derive_summary_records()` — aggregate by group and append summary rows (mean, sum, min, max, median, count)
  - `df.adam`: `.derive_locf_records()` — forward-fill (LOCF) within patient groups
  - `df.adam`: `.derive_param()` — pivot source parameters, compute a new AVAL, and append as new records (e.g. BMI from HEIGHT+WEIGHT)
  - `df.adam.adsl`: `.age_years()` — unit-aware age conversion (YEARS, MONTHS, WEEKS, DAYS)
  - `df.adam.adsl`: `.derive_period()` — create standard Subperiod/Phase variables (APxxSDT, APxxEDT, TRTxxP)
  - Spec-driven support: `bsa`, `map`, `qtc` are available as `algorithm` values in `define.yaml`
- `StudyContext.init()` — scaffolds a new study workspace (folder tree, `study_config.yaml`) with full IG/CT/domain configuration; raises `StudyConfigError` if already initialised
- `DefineScaffolder` — queries CDISC Library IG to generate `define.yaml` pre-populated with standard variables, types, labels, mandatory flags, and codelist references
- Evolved `StudyConfig` model with `SDTMConfig`, `ADAMConfig`, `CTConfig` sub-models for IG versions, domains, and CT package
- MkDocs documentation site with Material theme
- `mike` versioned deployment to GitHub Pages
- Pre-executed example notebook: ADSL pipeline (CDISCPILOT01)
- `llms.txt` for LLM-friendly documentation

### Changed

- **Spec parameter facts are checked against the verb signature** (ADR-0007, #179 phase 1) — the parity test now compares every `Param` of a spec algorithm with `inspect.signature()` of its verb: the spec may be stricter than the verb, never looser. The ten spec-only defaults are gone, so a define.yaml must state `aval`, `low` and `high` for `nrind`, the three dates for `on_treatment`, `term_var` for `atoxgr`, `on` for `merge` and `lookup`, and `agg` for `group_by`; `ct_codelist` is required on `assign_ct` and `hardcode_ct`, as the define.yaml concept doc already stated. A missing key is a load-time error
- **One validation HTML page**: `fleet validate --report` and `ValidationResult.save_html_report()` write the same page (`fleet.validation.models.write_html_report()`): a status row per dataset, then one row per finding. Every cell is HTML-escaped, so a `<` in a data value or a custom rule message no longer breaks the page or injects markup; `rows_affected=0` is shown (#119)

- **API simplification**: therapeutic-area namespaces (`onco`, `ophtha`, `peds`, `vaccine`, `metabolic`, `neuro`) and ADaM sub-structures (`adsl`, `occds`) are now accessed via `df.adam.<name>` instead of `df.<name>` — reduces registered namespaces from 10 to 2 (`df.sdtm` and `df.adam`)

### Fixed

- **Define-XML `FormalExpression` names the method the run records**: the verb the algorithm dispatches to, by the class that defines it on the define's own namespace, as `VariableNode.method` does (the `fleet lsp` hover names the defining class too). ADaM defines named `SDTMNamespace` and rendered calls that do not exist, such as `study_day('ADY', end=..., start=...)`; ADY now reads `fleet.core._verb_mixin.SharedVerbsMixin.duration('ADY', end='ASTDT', start='TRTSDT')` (#93)

## [0.1.0] — 2025-01-01

### Added

- `df.sdtm` namespace — 14 SDTM derivation verbs
- `df.adam` namespace — 22 ADaM BDS derivation verbs, with `df.adam.adsl` (8 patient-level verbs), `df.adam.occds` (5 occurrence verbs), and 6 TA extensions
- Define-XML 2.1 generation from `define.yaml`
- Define-XML validation against CDISC schema
- Controlled terminology loading and validation
- `StudyContext` and `PipelineDAG` for spec-driven pipelines
- CDISCPILOT01 example dataset and pipeline
- Pytest suite with fixtures
