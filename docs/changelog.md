# Changelog

All notable changes to Pymaverse are documented here.

## [Unreleased]

### Added

- `StudyContext.init()` — scaffolds a new study workspace (folder tree, `study_config.yaml`, SDTM and ADaM `define.yaml` boilerplates) in one call; raises `StudyConfigError` if already initialised
- MkDocs documentation site with Material theme
- `mike` versioned deployment to GitHub Pages
- Pre-executed example notebook: ADSL pipeline (CDISCPILOT01)
- `llms.txt` for LLM-friendly documentation

## [0.1.0] — 2025-01-01

### Added

- `df.sdtm` namespace — 14 SDTM derivation verbs
- `df.adam` namespace — 16 ADaM BDS derivation verbs
- `df.adsl` namespace — 6 patient-level derivation verbs
- `df.occds` namespace — 5 occurrence derivation verbs
- Therapeutic-area extensions: `onco`, `ophtha`, `peds`, `vaccine`, `metabolic`, `neuro`
- Define-XML 2.1 generation from `define.yaml`
- Define-XML validation against CDISC schema
- Controlled terminology loading and validation
- `StudyContext` and `PipelineDAG` for spec-driven pipelines
- CDISCPILOT01 example dataset and pipeline
- Pytest suite with fixtures
