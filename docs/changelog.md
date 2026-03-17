# Changelog

All notable changes to Fleet are documented here.

## [Unreleased]

### Added

- **Admiral-parity expansion** — new core computations and record-generating verbs:
  - `utils.py`: `bsa()` (Body Surface Area, 4 methods), `mean_arterial_pressure()`, `qtc()` (Fridericia/Bazett), `age_in_years()` (unit-aware), `extreme_flag()` (min/max per group)
  - `df.adam`: `.bsa()`, `.map()`, `.qtc()` — namespace wrappers for the new computations
  - `df.adam`: `.derive_summary_records()` — aggregate by group and append summary rows (mean, sum, min, max, median, count)
  - `df.adam`: `.derive_locf_records()` — forward-fill (LOCF) within patient groups
  - `df.adam`: `.derive_param()` — pivot source parameters, compute a new AVAL, and append as new records (e.g. BMI from HEIGHT+WEIGHT)
  - `df.adam.adsl`: `.age_years()` — unit-aware age conversion (YEARS, MONTHS, WEEKS, DAYS)
  - `df.adam.adsl`: `.derive_period()` — create standard Subperiod/Phase variables (APxxSDT, APxxEDT, TRTxxP)
  - Spec-driven support: `bsa`, `map`, `qtc` are available as `algorithm` values in `define.yaml`
- `StudyContext.init()` — scaffolds a new study workspace (folder tree, `study_config.yaml`, SDTM and ADaM `define.yaml` boilerplates) in one call; raises `StudyConfigError` if already initialised
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
