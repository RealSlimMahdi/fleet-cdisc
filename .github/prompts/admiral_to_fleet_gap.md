# Admiral → Fleet Gap Analysis

> Generated 2025-05-02. Source: admiral v1.2+ reference index vs Fleet ADaM namespace layer (96 public verbs).

---

## Executive Summary

Fleet currently covers **~65%** of admiral's core derivation surface through 96+ public verbs across 10 namespace classes. The enhanced `flag()` verb now absorbs 7 admiral functions into 2 Fleet verbs (`flag()` + `criterion()`), supporting `exists`, `before`/`after`, and `exists_after`/`exists_before` criteria modes. The remaining gaps fall into three complexity tiers. Most "Easy" items are already expressible via existing Fleet primitives (`flag`, `condderivation`, `lookup`, `derivation`) but lack a dedicated convenience verb. The truly novel work concentrates in **TTE derivations**, **query-variable frameworks**, and **multi-source date derivations**.

---

## 1. Direct Equivalents (28 functions)

| Admiral Function                              | Fleet Verb                                      | Namespace                     |
| --------------------------------------------- | ----------------------------------------------- | ----------------------------- |
| `derive_vars_dt` / `impute_dtc_dt`            | `derive_dt`                                     | SharedADaMVerbsMixin          |
| `derive_vars_dtm` / `impute_dtc_dtm`          | `derive_dtm`                                    | SharedADaMVerbsMixin          |
| `derive_vars_dy`                              | `study_day`                                     | AdamNamespace                 |
| `derive_var_base`                             | `baseline`                                      | AdamNamespace                 |
| `derive_var_chg`                              | `chg`                                           | AdamNamespace                 |
| `derive_var_pchg`                             | `pchg`                                          | AdamNamespace                 |
| `derive_var_obs_number`                       | `seq`                                           | MultiRowMixin                 |
| `derive_var_ontrtfl`                          | `on_treatment`                                  | AdamNamespace                 |
| `derive_var_shift`                            | `shift`                                         | AdamNamespace                 |
| `derive_var_anrind`                           | `nrind`                                         | AdamNamespace                 |
| `derive_var_extreme_flag` (first/last)        | `flag(criteria="first"/"last")`                 | AdamNamespace                 |
| `derive_var_extreme_flag` (max/min)           | `flag(criteria="max"/"min")`                    | AdamNamespace                 |
| `derive_param_bmi` / `compute_bmi`            | `bmi` / `derive_param`                          | AdamNamespace                 |
| `derive_param_bsa` / `compute_bsa`            | `bsa` / `derive_param`                          | AdamNamespace                 |
| `derive_param_map` / `compute_map`            | `map` / `derive_param`                          | AdamNamespace                 |
| `derive_param_qtc` / `compute_qtc`            | `qtc` / `derive_param`                          | AdamNamespace                 |
| `derive_summary_records`                      | `derive_summary_records`                        | AdamNamespace                 |
| `derive_locf_records`                         | `derive_locf_records`                           | AdamNamespace                 |
| `derive_param_computed`                       | `derive_param`                                  | AdamNamespace                 |
| `derive_vars_duration` / `compute_duration`   | `duration`                                      | ADSLNamespace                 |
| `derive_var_age_years` / `compute_age_years`  | `age_years`                                     | ADSLNamespace / PedsNamespace |
| `derive_vars_period`                          | `derive_period`                                 | ADSLNamespace                 |
| `derive_var_trtemfl`                          | `treatment_emergent`                            | OCCDSNamespace                |
| `derive_var_atoxgr` / `derive_var_atoxgr_dir` | `atoxgr` + `combine_grades`                     | AdamNamespace (grading)       |
| `derive_vars_merged`                          | `lookup`                                        | AdamNamespace                 |
| `derive_vars_merged_lookup`                   | `lookup`                                        | AdamNamespace                 |
| `derive_var_trtdurd`                          | `duration` (via ADSL)                           | ADSLNamespace                 |
| `derive_var_nfrlt`                            | `nominal_time`                                  | PKNamespace                   |
| `derive_var_merged_exist_flag`                | `flag(criteria="exists")`                       | SharedADaMVerbsMixin          |
| `derive_var_merged_ef_msrc`                   | `flag(criteria="exists", from_dataset=[...])`   | SharedADaMVerbsMixin          |
| `derive_var_relative_flag`                    | `flag(criteria="before"/"after")`               | SharedADaMVerbsMixin          |
| `derive_var_joined_exist_flag`                | `flag(criteria="exists_after"/"exists_before")` | SharedADaMVerbsMixin          |
| `derive_vars_crit_flag`                       | `criterion()`                                   | SharedADaMVerbsMixin          |

---

## 2. Near-Equivalents (Expressible via existing primitives)

| Admiral Function              | Fleet Approach                                                       | Notes                                          |
| ----------------------------- | -------------------------------------------------------------------- | ---------------------------------------------- |
| `derive_vars_merged_summary`  | `lookup` + Polars `group_by().agg()` via `transform`                 | No single verb, but one-liner with `transform` |
| `derive_vars_joined`          | `lookup(how="left", on=..., where=...)`                              | Fleet's `lookup` supports conditional joins    |
| `derive_vars_joined_summary`  | `lookup` + `derive_summary_records`                                  | Combine two verbs                              |
| `derive_var_analysis_ratio`   | `derivation(target, expression=pl.col("AVAL") / pl.col("BASE"))`     | Trivial expression                             |
| `restrict_derivation`         | `whereclauses` → verb → union back                                   | Manual pattern, no built-in wrapper            |
| `slice_derivation`            | Multiple `condderivation` or `whereclauses` chains                   | Manual pattern                                 |
| `call_derivation`             | Python loop over verb calls                                          | Inherent in Python's expressiveness            |
| `derive_vars_cat`             | `condderivation` + `recode`                                          | Pattern-based, not single-verb                 |
| `derive_basetype_records`     | `transform` + concat                                                 | Manual duplicate-and-tag pattern               |
| `compute_rr`                  | `derivation(target, expression=60000 / pl.col("HR"))`                | Trivial expression                             |
| `derive_param_rr`             | `derive_param` + RR expression                                       | Trivial combo                                  |
| `derive_vars_dtm_to_dt`       | `derivation` with `.dt.date()` cast                                  | One-liner Polars expression                    |
| `derive_vars_dtm_to_tm`       | `derivation` with `.dt.time()` cast                                  | One-liner Polars expression                    |
| `compute_dtf` / `compute_tmf` | Built into `derive_dt` / `derive_dtm` (auto-generates `*DTF`/`*TMF`) | Already handled internally                     |
| `filter_extreme`              | `whereclauses` with rank/sort expression                             | No single verb                                 |
| `filter_joined`               | `whereclauses` + `lookup`                                            | Combine two verbs                              |

---

## 3. Missing Capabilities — Ranked by Implementation Complexity

### 🟢 Easy (1–2 day effort, reuses existing primitives)

| #   | Admiral Function                    | Description                                 | Fleet Simplification Opportunity                                                    |
| --- | ----------------------------------- | ------------------------------------------- | ----------------------------------------------------------------------------------- |
| 1   | `derive_param_exist_flag`           | Append parameter record flagging existence  | `derive_param` + existence check. Wrap as `derive_param_exist_flag`.                |
| 2   | `derive_extreme_records`            | Append first/last record per group          | `derive_summary_records`-style with `filter_extreme` logic. Reuse `flag` internals. |
| 3   | `derive_param_doseint`              | Dose intensity: `DOSE / PLANNED_DOSE × 100` | Trivial `derive_param` + expression. Add as `dose_intensity` in OCCDS/BDS.          |
| 4   | `derive_param_wbc_abs`              | `WBC × differential / 100`                  | Trivial `derive_param` + expression. Add as convenience.                            |
| 5   | `compute_scale`                     | Compute questionnaire scale scores          | `derivation` with sum/mean across items. Add `scale_score` verb.                    |
| 6   | `yn_to_numeric`                     | "Y"→1, "N"→0                                | One-liner `recode`. Not worth a dedicated verb.                                     |
| 7   | `convert_blanks_to_na`              | Blank → null                                | Polars handles natively; add note in docs.                                          |
| 8   | `filter_exist` / `filter_not_exist` | Semi-join / anti-join filters               | Add `filter_exist(dataset, on=...)` to SharedADaMVerbsMixin. ~15 lines.             |

### 🟡 Moderate (3–5 day effort, new algorithm or join pattern)

| #   | Admiral Function             | Description                                    | Fleet Implementation Strategy                                                                    |
| --- | ---------------------------- | ---------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| 9   | `derive_vars_query`          | Derive SMQ/CQ variables from query dataset     | New `query_vars` verb in OCCDSNamespace. Needs query dataset schema.                             |
| 10  | `create_query_data`          | Build query dataset from MedDRA/SMQ            | CLI utility + metadata lookup. Partially overlaps `fleet init` tooling.                          |
| 11  | `derive_extreme_event`       | Worst/best observation as new record           | Generalise `derive_summary_records` with event-object pattern.                                   |
| 12  | `derive_vars_extreme_event`  | Worst/best observation as new variables (ADSL) | `first_date`/`last_date` generalized: add `extreme_event` to ADSLNamespace.                      |
| 13  | `derive_expected_records`    | Insert expected but missing records            | New `derive_expected_records` in BDS: cross-join expected visits × parameters, anti-join actual. |
| 14  | `derive_vars_transposed`     | Transpose + merge another dataset              | `transform` with `.pivot()` + join. Add `transpose_merge` convenience verb.                      |
| 15  | `derive_param_exposure`      | Aggregate exposure with start/end dates        | New `exposure` verb in OCCDS: group_by period, sum dose, derive dates.                           |
| 16  | `create_single_dose_dataset` | Expand multi-dose to single-dose records       | `transform` with date_range expansion. Moderate Polars logic.                                    |
| 17  | `derive_vars_atc`            | ATC class variables from WHO Drug              | Needs external ATC dictionary lookup. Add `atc_class` verb to OCCDSNamespace.                    |
| 18  | `compute_qual_imputation`    | Handle `<` / `>` qualifiers in lab results     | New `qual_impute` verb: parse character result, apply factor. Moderate string parsing.           |
| 19  | `compute_egfr`               | eGFR by CKD-EPI/MDRD/Cockcroft-Gault           | New `egfr` in AdamNamespace. Multiple formulae, ~50 lines.                                       |

### 🔴 Complex (1–2 week effort, new subsystem or external data)

| #   | Admiral Function                                 | Description                                                       | Fleet Implementation Strategy                                                                                                                          |
| --- | ------------------------------------------------ | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 24  | `derive_param_tte`                               | Time-to-event parameter with censoring                            | **New TTE subsystem.** Needs `event_source`, `censor_source` objects, multi-dataset scanning, CNSR/AVAL derivation. Recommend new `tte` sub-namespace. |
| 25  | `derive_param_framingham` / `compute_framingham` | Framingham 10-year CVD risk                                       | Complex multi-variable formula with sex-stratified coefficients. ~80 lines of validated logic.                                                         |
| 26  | `create_period_dataset` (full)                   | Reference dataset for periods/subperiods                          | Fleet has `derive_period` for ADSL variables, but lacks the auxiliary dataset generator that other domains consume.                                    |
| 27  | `derive_vars_computed` (multi-param)             | Derive variable from values of multiple parameters simultaneously | Requires pivot → compute → unpivot pattern. Extends `derive_param` semantics.                                                                          |
| 28  | Pediatric growth charts                          | WHO/CDC z-scores, percentiles by age/sex                          | Needs bundled reference tables (LMS parameters). New module in PedsNamespace.                                                                          |
| 29  | Oncology progression (admiralonco)               | RECIST confirmation windows, duration of response                 | Partially covered by `OncoNamespace`, but confirmation logic is simpler than admiral's full `event_joined` pattern.                                    |
| 30  | Vaccine reactogenicity (admiralvaccines)         | Multi-dose, multi-period reactogenicity summaries                 | Fleet's `VaccineNamespace` covers basics; full multi-period severity-over-time logic needs `create_period_dataset` integration.                        |

---

## 4. Architecture Recommendations

### 4.1 Mixin Strategy for New Verbs

| Proposed Verb                       | Scope                   | Mixin / Class                         | Status         |
| ----------------------------------- | ----------------------- | ------------------------------------- | -------------- |
| `flag(criteria="exists")`           | All namespaces          | `SharedADaMVerbsMixin`                | ✅ Implemented |
| `flag(criteria="before"/"after")`   | All namespaces          | `SharedADaMVerbsMixin`                | ✅ Implemented |
| `flag(criteria="exists_after")`     | All namespaces          | `SharedADaMVerbsMixin`                | ✅ Implemented |
| `criterion()`                       | All namespaces          | `SharedADaMVerbsMixin`                | ✅ Implemented |
| `filter_exist` / `filter_not_exist` | All namespaces          | `SharedADaMVerbsMixin`                | Not started    |
| `extreme_records`                   | BDS                     | `MultiRowMixin`                       | Not started    |
| `expected_records`                  | BDS                     | `MultiRowMixin`                       | Not started    |
| `query_vars`                        | OCCDS only              | `OCCDSNamespace` directly             | Not started    |
| `exposure`                          | OCCDS only              | `OCCDSNamespace` directly             | Not started    |
| `egfr`                              | BDS (clinical measures) | `AdamNamespace` alongside `bmi`/`bsa` | Not started    |
| `qual_impute`                       | BDS labs                | `AdamNamespace` or new `LabMixin`     | Not started    |
| TTE subsystem                       | Dedicated               | New `TTENamespace` (`.adam.tte`)      | Not started    |

### 4.2 Simplification Opportunities

1. **Unified `exist_flag` pattern — DONE.** Admiral has 3 functions (`derive_var_merged_exist_flag`, `derive_var_merged_ef_msrc`, `derive_param_exist_flag`). Fleet's `flag(criteria="exists")` now unifies the first two; `from_dataset` accepts a single DataFrame or a list. The third (`derive_param_exist_flag`) can be composed via `derive_param` + `flag`.

2. **`flag()` now subsumes 7 admiral functions — DONE.** Fleet's single `flag` verb with `criteria` shortcuts covers `derive_var_extreme_flag` (first/last/max/min), `derive_var_merged_exist_flag`, `derive_var_merged_ef_msrc`, `derive_var_relative_flag`, and `derive_var_joined_exist_flag`. The `criterion()` verb covers `derive_vars_crit_flag`.

3. **`derive_param` is Fleet's universal parameter-derivation engine.** Admiral's `derive_param_bmi`, `_bsa`, `_map`, `_qtc`, `_rr`, `_wbc_abs`, `_doseint`, `_exist_flag` are all special cases. Fleet's single `derive_param(by_vars, set_values_to, parameter_filter, analysis_value)` + domain-specific expression covers all of them.

4. **Python's `for` loop replaces `call_derivation`.** No Fleet verb needed.

5. **`whereclauses` + restore pattern replaces `restrict_derivation`.** Consider adding a `scoped(where)` context manager for ergonomics but not strictly necessary.

### 4.3 Recommended Implementation Order (ROI-ranked)

| Priority | Verb(s)                                | Rationale                                    | Status         |
| -------- | -------------------------------------- | -------------------------------------------- | -------------- |
| P1       | `flag(criteria="exists")`              | Most-requested pattern; covers 3 admiral fns | ✅ Implemented |
| P1       | `flag(criteria="before"/"after")`      | Relative flagging pattern                    | ✅ Implemented |
| P1       | `flag(criteria="exists_after")`        | Temporal join condition                      | ✅ Implemented |
| P1       | `criterion()`                          | Triple-output CRITy/CRITyFL/CRITyFN          | ✅ Implemented |
| P1       | `filter_exist` / `filter_not_exist`    | Common data-quality filter; 15 lines each    | Not started    |
| P2       | `query_vars` + `create_query_data` CLI | Required for AE/CM SMQ/CQ derivations        | Not started    |
| P2       | `egfr`                                 | High-value clinical measure; no workaround   | Not started    |
| P3       | `extreme_records` / `expected_records` | Multi-row operations for BDS completeness    | Not started    |
| P3       | `qual_impute`                          | Lab-specific; niche but important for ADLB   | Not started    |
| P4       | TTE subsystem                          | Large scope; consider phased delivery        | Not started    |
| P4       | Framingham                             | Niche cardiovascular; low frequency          | Not started    |
| P4       | Pediatric growth                       | Requires reference data bundling             | Not started    |

---

## 5. Coverage Summary

| Category                               | Count   | % of Admiral Derivation Surface |
| -------------------------------------- | ------- | ------------------------------- |
| Direct equivalents                     | 33      | 44%                             |
| Near-equivalents (expressible today)   | 16      | 21%                             |
| Missing — Easy                         | 8       | 11%                             |
| Missing — Moderate                     | 11      | 15%                             |
| Missing — Complex                      | 7       | 9%                              |
| **Total admiral derivation functions** | **~75** | —                               |

> **Note:** Admiral utility functions (template management, quosure helpers, dataset checking) are excluded as they are R-ecosystem-specific and have no meaningful clinical-programming equivalent in a Python/Polars pipeline.

---

## 6. Extension Package Gaps (admiralonco, admiralvaccines, admiralophtha, admiralpeds)

| Extension           | Fleet Coverage                                                                            | Gap                                                                                    |
| ------------------- | ----------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| **admiralonco**     | `OncoNamespace` covers BOR, confirmed response, tumor_response_flag, filter_pd, aval_resp | Missing: `derive_param_confirmed_resp` full event_joined pattern, duration of response |
| **admiralvaccines** | `VaccineNamespace` covers fever, seroconversion, seroresponse, event_flag, aval_adis      | Missing: multi-period reactogenicity, booster-dose derivations                         |
| **admiralophtha**   | `OphthaNamespace` covers ETDRS/LogMAR, study_eye, affected_eye, bcva_criterion            | Substantially complete; minor: `derive_var_aession` (study eye from AGSUB)             |
| **admiralpeds**     | `PedsNamespace` covers age_days, age_months, corrected_age, prematurity_flag              | Missing: WHO/CDC growth chart z-scores/percentiles                                     |

---

_End of report._
