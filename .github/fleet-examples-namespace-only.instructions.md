---
name: "Fleet Examples Namespace-Only"
description: "Use when editing or generating Python examples in Fleet; enforce namespace-only transformations."
applyTo: "examples/*.py"
---

# Namespace-only policy for Fleet examples

- Use Fleet namespace chaining for all dataset transformations.
- Enter pipelines through `fleet.frame(...)` at IO boundaries — the sanctioned zero-cost typed entry (`fleet.DataFrame` / `fleet.LazyFrame`); never `# type: ignore` on namespace access.
- Start transformations from a namespace entrypoint:
  - **SDTM:** `.sdtm`
  - **ADaM BDS:** `.adam`
  - **ADaM ADSL:** `.adam.adsl`
  - **ADaM OCCDS:** `.adam.occds`
  - **ADaM PK/NCA:** `.adam.pk`
  - **ADaM Oncology:** `.adam.onco`
  - **ADaM Ophthalmology:** `.adam.ophtha`
  - **ADaM Pediatrics:** `.adam.peds`
  - **ADaM Vaccine:** `.adam.vaccine`
  - **ADaM Metabolic:** `.adam.metabolic`
  - **ADaM Neurology:** `.adam.neuro`
  - **TLG:** `.tlg.ae`, `.tlg.cm`, `.tlg.dm`, `.tlg.ds`, `.tlg.eg`, `.tlg.ex`, `.tlg.lb`, `.tlg.mh`, `.tlg.vs` (spec-driven: `fleet.tlg.load_spec` / `run_spec`)
- End every SDTM/ADaM transformation chain with `.to_frame()`.
- Do not use direct DataFrame transformation methods in examples (for example: .with_columns, .rename, .select, .filter, .join, .group_by, pl.concat) when the step is a derivation or merge that belongs in namespace verbs.
- If a required derivation is not covered by an existing namespace verb, stop and implement or request a namespace verb first; do not inline plain Polars transformation logic in the example.
- Keep mapping arguments explicit and keyword-based (`source=`, `value=`, `ct=`, `ct_map=`, `by=`, `keep=`, etc.). Pre-alpha spellings (`ct_codelist=`, `ct_mapping=`, `by_vars=`, `target_cols=`, …) are removed at runtime.
- Preserve lazy/chained style and avoid mixed patterns where part of the pipeline is namespace-based and part is ad hoc DataFrame logic.
- Only use non-namespace operations for basic IO boundaries (read/write files, constants, simple printing), not for derivation logic.
- For shared ADaM logic needed in multiple namespaces, implement in mixins instead of per-namespace duplication.

# Available verbs by namespace

Regenerated 2026-07 from the live package. To re-check, run `df.<namespace>.verbs()` (returns a `verb`/`summary` table).

## SDTM (`.sdtm`) — 49 verbs

`ae_aerel`, `assign`, `baseline_flag`, `case_when`, `condition_add`, `criterion`, `date`, `derivation`, `duration`, `explain`, `export_supp`, `fk_policy`, `flag`, `flag_exists`, `flag_extreme`, `flag_first`, `flag_last`, `flag_relative`, `from_spec`, `group_by`, `inspect`, `keep`, `merge`, `multiple_responses`, `nodup`, `notsubmitted`, `nsv`, `pin`, `pins`, `repin`, `select`, `seq`, `study_day`, `to_dataset_json`, `to_frame`, `to_spec_yaml`, `trail`, `validate`, `write_parquet`

**Trial Design (also on `.sdtm`, via `fetch_structure`):** `fetch_structure`, `study_header`, `add_elements`, `add_arms`, `add_visits`, `add_parameters`, `add_criteria`, `visit_map`, `element_boundaries`, `epoch_assign`

## Shared ADaM core (all `.adam*` namespaces) — 40 verbs

`assign`, `case_when`, `count_events`, `criterion`, `date`, `derivation`, `duration`, `explain`, `first_date`, `fk_policy`, `flag`, `flag_exists`, `flag_extreme`, `flag_first`, `flag_last`, `flag_relative`, `from_spec`, `inspect`, `join_adsl`, `keep`, `last_date`, `merge`, `merge_adsl`, `nodup`, `pick`, `pin`, `pins`, `recode`, `repin`, `select`, `seq`, `source`, `study_day`, `to_dataset_json`, `to_frame`, `to_spec_yaml`, `trail`, `validate`, `whereclauses`, `write_parquet`

Sub-namespaces do NOT inherit BDS-specific verbs — each adds only its own on top of the core:

## ADaM BDS (`.adam`) — core + 16

`atoxgr`, `baseline`, `bmi`, `bsa`, `chg`, `combine_grades`, `derive_locf_records`, `derive_param`, `derive_summary_records`, `map`, `nrind`, `on_treatment`, `pchg`, `qtc`, `shift`, `transform`

## ADaM ADSL (`.adam.adsl`) — core + 3

`age_from_dates`, `age_years`, `derive_period`

## ADaM OCCDS (`.adam.occds`) — core + 2

`onset_recovery`, `treatment_emergent`

## ADaM PK (`.adam.pk`) — core + 14

`amt`, `anl_flag`, `avalcat`, `blq_flag`, `blq_impute`, `blqfn`, `cmt`, `dose_normalized`, `evid`, `log_conc`, `mdv`, `mrrlt`, `nominal_time`, `predose_flag`

## ADaM Oncology (`.adam.onco`) — core + 5

`aval_resp`, `best_overall_response`, `confirmed_response_flag`, `filter_pd`, `tumor_response_flag`

## ADaM Ophthalmology (`.adam.ophtha`) — core + 5

`affected_eye`, `bcva_criterion`, `etdrs_to_logmar`, `logmar_to_etdrs`, `study_eye`

## ADaM Pediatrics (`.adam.peds`) — core + 6

`age_days`, `age_months`, `age_years`, `bmi_category`, `corrected_age`, `prematurity_flag`

## ADaM Vaccine (`.adam.vaccine`) — core + 5

`aval_adis`, `event_flag`, `fever_flag`, `seroconversion_flag`, `seroresponse_flag`

## ADaM Metabolic (`.adam.metabolic`) — core + 4

`body_fat_pct`, `visceral_fat_flag`, `waist_height_ratio`, `waist_hip_ratio`

## ADaM Neurology (`.adam.neuro`) — core + 5

`cdrsob_total`, `centiloid`, `mmse_category`, `moca_category`, `panss_total`

# Validation requirement

- After any change to example scripts, **ALL** `.py` files in `examples/` must be re-run and pass without error. This includes:
  ```
  uv run python examples/full_pipeline_example.py
  uv run python examples/cdiscpilot01_inline.py
  uv run python examples/cdiscpilot01_spec_driven.py
  uv run python examples/adnca_example.py
  uv run python examples/tdd_example.py
  uv run python examples/adlb_grading_example.py
  uv run python examples/r2r_ae_example.py
  uv run python examples/tlg_ae_example.py
  uv run python examples/tlg_vs_example.py
  ```
- If a new example script is added, it must also be added to the validation list above.
