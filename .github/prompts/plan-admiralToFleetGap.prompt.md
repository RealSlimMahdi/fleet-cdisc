## Plan: Admiral-to-Fleet Gap Mapping

**Goal**

- Produce a ranked list of admiral Variable Listing functions with no Fleet equivalent.
- Classify each item by implementation complexity.
- Capture Fleet simplification opportunities around shared ADaM primitives and namespace patterns.
- The report is a Markdown document with a clear matrix of admiral functions vs Fleet capabilities, complexity buckets, and recommended next steps for Fleet development.

### Admiral function classification

- Direct Fleet equivalents
  - `derive_vars_dt` / `derive_vars_dtm` → `derive_dt` / `derive_dtm`
  - `derive_vars_dy` → `study_day`
  - `derive_var_base` → `baseline`
  - `derive_var_chg` → `chg`
  - `derive_var_pchg` → `pchg`
  - `derive_var_obs_number` → `seq`
  - `derive_var_ontrtfl` → `on_treatment`
  - `derive_param_bsa` → `bsa`
  - `derive_param_map` → `map`
  - `derive_param_bmi` → `bmi`
  - `derive_param_qtc` → `qtc`
  - `derive_summary_records` → `derive_summary_records`
  - `derive_locf_records` → `derive_locf_records`
  - `derive_var_shift` → `shift`

- Near-equivalent Fleet concepts
  - `derive_vars_merged`, `derive_vars_joined`, `derive_vars_merged_lookup` → `lookup` + `condderivation`/`whereclauses`
  - `derive_vars_duration` → ADSL `duration`
  - DTM/date conversions and imputation helpers → `derive_dt`, `derive_dtm`, `format_iso`

- Missing Fleet capabilities
  - `restrict_derivation`
  - `derive_var_merged_exist_flag`
  - `derive_var_extreme_flag`
  - `derive_var_relative_flag`
  - `derive_vars_query`
  - `derive_vars_max_flag`
  - `derive_vars_event_flag`
  - pediatric growth percentiles / z-scores (`derive_params_growth_age`, `derive_params_growth_height`)
  - TTE derivations / `derive_param_tte`
  - broader `create_period_dataset` behavior beyond ADSL
  - package-specific vaccine/oncology progression and summary flags

### Steps

1. Extract the authoritative `inst/admiral-lookup-book.csv` function list.
2. Map Fleet capability from current ADaM namespaces and shared verbs.
3. Build the equivalence matrix: direct verb, conceptual equivalent, or no equivalent.
4. Assign complexity buckets: `Easy`, `Moderate`, `Complex`.
5. Sort missing items from easiest to hardest with one-line rationale.
6. Recommend Fleet simplifications anchored in shared verb/mixin design.
7. Deliver the final report with the ranked gap list and architecture notes.

### Relevant files

- `src/fleet/adam/_mixins.py`
- `src/fleet/adam/namespace.py`
- `src/fleet/adam/adsl_namespace.py`
- `src/fleet/adam/occds_namespace.py`
- `src/fleet/adam/onco_namespace.py`
- `src/fleet/adam/vaccine_namespace.py`
- `src/fleet/adam/peds_namespace.py`
- `src/fleet/adam/ophtha_namespace.py`
- `src/fleet/adam/metabolic_namespace.py`
- `src/fleet/adam/pk_namespace.py`

### Verification

- Confirm every missing-item claim against Fleet source.
- Validate complexity ranking by reuse of existing primitives vs new algorithm/data needs.
- Keep any extraction uncertainty explicit.
