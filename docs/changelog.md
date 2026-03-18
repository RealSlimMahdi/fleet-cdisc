# Changelog

All notable changes to Fleet are documented here.

## [Unreleased]

### Added

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
- **`assign_ct` now accepts codelist classes** — pass a generated class (e.g. `SEX`) instead of a raw NCI string; `ct_mapping` is optional when raw data already matches CDISC submission values

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

- **API simplification**: therapeutic-area namespaces (`onco`, `ophtha`, `peds`, `vaccine`, `metabolic`, `neuro`) and ADaM sub-structures (`adsl`, `occds`) are now accessed via `df.adam.<name>` instead of `df.<name>` — reduces registered namespaces from 10 to 2 (`df.sdtm` and `df.adam`)

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
