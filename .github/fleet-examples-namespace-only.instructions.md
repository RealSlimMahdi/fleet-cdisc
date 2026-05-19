---
name: "Fleet Examples Namespace-Only"
description: "Use when editing or generating Python examples in Fleet; enforce namespace-only transformations."
applyTo: "examples/*.py"
---

# Namespace-only policy for Fleet examples

- Use Fleet namespace chaining for all dataset transformations.
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
  - **TLG:** `.tlg.ae`, `.tlg.vs`
- End every transformation chain with `.to_frame()`.
- Do not use direct DataFrame transformation methods in examples (for example: .with_columns, .rename, .select, .filter, .join, .group_by, pl.concat) when the step is a derivation or merge that belongs in namespace verbs.
- If a required derivation is not covered by an existing namespace verb, stop and implement or request a namespace verb first; do not inline plain Polars transformation logic in the example.
- Keep mapping arguments explicit and keyword-based (source=, value=, ct_mapping=, etc.).
- Preserve lazy/chained style and avoid mixed patterns where part of the pipeline is namespace-based and part is ad hoc DataFrame logic.
- Only use non-namespace operations for basic IO boundaries (read/write files, constants, simple printing), not for derivation logic.
- For shared ADaM logic needed in multiple namespaces, implement in mixins instead of per-namespace duplication.

# Available verbs by namespace

## SDTM (`.sdtm`)

`assign_no_ct`, `assign_ct`, `date`, `hardcode_ct`, `hardcode_no_ct`, `nsv`, `study_day`, `baseline_flag`, `condition_add`, `if_then_else`, `ae_aerel`, `seq`, `merge`, `group_by`, `dataset_level`, `notsubmitted`, `multiple_responses`, `from_spec`, `export_supp`, `derivation`, `duration`, `validate`, `select`, `nodup`, `flag`, `criterion`, `pin`, `repin`, `inspect`, `explain`, `to_frame`, `to_dataset_json`, `write_parquet`

**Trial Design (`.sdtm` with `fetch_structure`):** `fetch_structure`, `study_header`, `add_elements`, `add_arms`, `add_visits`, `add_parameters`, `add_criteria`, `visit_map`, `element_boundaries`, `epoch_assign`

## ADaM BDS (`.adam`)

`source`, `assigned`, `recode`, `rename`, `condderivation`, `whereclauses`, `merge_adsl`, `join_adsl`, `date`, `study_day`, `lookup`, `baseline`, `chg`, `pchg`, `bmi`, `nrind`, `on_treatment`, `shift`, `bsa`, `map`, `qtc`, `derive_summary_records`, `derive_locf_records`, `derive_param`, `atoxgr`, `combine_grades`, `transform`, `from_spec`, `derivation`, `duration`, `seq`, `validate`, `select`, `nodup`, `flag`, `criterion`, `pin`, `repin`, `inspect`, `explain`, `to_frame`, `to_dataset_json`, `write_parquet`

## ADaM ADSL (`.adam.adsl`)

Inherits all BDS verbs plus: `first_date`, `last_date`, `count_events`, `age_years`, `age_from_dates`, `derive_period`

## ADaM OCCDS (`.adam.occds`)

Inherits all BDS verbs plus: `treatment_emergent`, `onset_recovery`

## ADaM PK (`.adam.pk`)

Inherits all BDS verbs plus: `blq_flag`, `blq_impute`, `nominal_time`, `predose_flag`, `dose_normalized`, `evid`, `mrrlt`, `blqfn`, `log_conc`, `mdv`, `amt`, `cmt`, `avalcat`, `anl_flag`

## ADaM Oncology (`.adam.onco`)

Inherits all BDS verbs plus: `aval_resp`, `tumor_response_flag`, `best_overall_response`, `confirmed_response_flag`, `filter_pd`

## ADaM Ophthalmology (`.adam.ophtha`)

Inherits all BDS verbs plus: `etdrs_to_logmar`, `logmar_to_etdrs`, `study_eye`, `affected_eye`, `bcva_criterion`

## ADaM Pediatrics (`.adam.peds`)

Inherits all BDS verbs plus: `age_days`, `age_months`, `age_years`, `corrected_age`, `prematurity_flag`, `bmi_category`

## ADaM Vaccine (`.adam.vaccine`)

Inherits all BDS verbs plus: `fever_flag`, `seroconversion_flag`, `seroresponse_flag`, `aval_adis`, `event_flag`

## ADaM Metabolic (`.adam.metabolic`)

Inherits all BDS verbs plus: `waist_hip_ratio`, `waist_height_ratio`, `body_fat_pct`, `visceral_fat_flag`

## ADaM Neurology (`.adam.neuro`)

Inherits all BDS verbs plus: `centiloid`, `mmse_category`, `cdrsob_total`, `moca_category`, `panss_total`

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
- If a new example script is added, it must also be added to the validation list in `.github/copilot-instructions.md` §3 and §9.
