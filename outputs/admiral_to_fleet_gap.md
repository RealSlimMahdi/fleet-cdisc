# Admiral → Fleet Gap Analysis

> Generated 2025-05-02. Source: admiral v1.2+ reference index vs Fleet ADaM namespace layer (96 public verbs).

---

## Executive Summary

Fleet currently covers **~65%** of admiral's core derivation surface through 96 public verbs across 10 namespace classes. The remaining gaps fall into three complexity tiers. Most "Easy" items are already expressible via existing Fleet primitives (`flag`, `condderivation`, `lookup`, `derivation`) but lack a dedicated convenience verb. The truly novel work concentrates in **TTE derivations**, **query-variable frameworks**, and **multi-source date derivations**.

---

## 1. Direct Equivalents (28 functions)

| Admiral Function                              | Fleet Verb                      | Namespace                     |
| --------------------------------------------- | ------------------------------- | ----------------------------- |
| `derive_vars_dt` / `impute_dtc_dt`            | `derive_dt`                     | SharedADaMVerbsMixin          |
| `derive_vars_dtm` / `impute_dtc_dtm`          | `derive_dtm`                    | SharedADaMVerbsMixin          |
| `derive_vars_dy`                              | `study_day`                     | AdamNamespace                 |
| `derive_var_base`                             | `baseline`                      | AdamNamespace                 |
| `derive_var_chg`                              | `chg`                           | AdamNamespace                 |
| `derive_var_pchg`                             | `pchg`                          | AdamNamespace                 |
| `derive_var_obs_number`                       | `seq`                           | MultiRowMixin                 |
| `derive_var_ontrtfl`                          | `on_treatment`                  | AdamNamespace                 |
| `derive_var_shift`                            | `shift`                         | AdamNamespace                 |
| `derive_var_anrind`                           | `nrind`                         | AdamNamespace                 |
| `derive_var_extreme_flag` (first/last)        | `flag(criteria="first"/"last")` | AdamNamespace                 |
| `derive_var_extreme_flag` (max/min)           | `flag(criteria="max"/"min")`    | AdamNamespace                 |
| `derive_param_bmi` / `compute_bmi`            | `bmi` / `derive_param`          | AdamNamespace                 |
| `derive_param_bsa` / `compute_bsa`            | `bsa` / `derive_param`          | AdamNamespace                 |
| `derive_param_map` / `compute_map`            | `map` / `derive_param`          | AdamNamespace                 |
| `derive_param_qtc` / `compute_qtc`            | `qtc` / `derive_param`          | AdamNamespace                 |
| `derive_summary_records`                      | `derive_summary_records`        | AdamNamespace                 |
| `derive_locf_records`                         | `derive_locf_records`           | AdamNamespace                 |
| `derive_param_computed`                       | `derive_param`                  | AdamNamespace                 |
| `derive_vars_duration` / `compute_duration`   | `duration`                      | ADSLNamespace                 |
| `derive_var_age_years` / `compute_age_years`  | `age_years`                     | ADSLNamespace / PedsNamespace |
| `derive_vars_period`                          | `derive_period`                 | ADSLNamespace                 |
| `derive_var_trtemfl`                          | `treatment_emergent`            | OCCDSNamespace                |
| `derive_var_atoxgr` / `derive_var_atoxgr_dir` | `atoxgr` + `combine_grades`     | AdamNamespace (grading)       |
| `derive_vars_merged`                          | `lookup`                        | AdamNamespace                 |
| `derive_vars_merged_lookup`                   | `lookup`                        | AdamNamespace                 |
| `derive_var_trtdurd`                          | `duration` (via ADSL)           | ADSLNamespace                 |
| `derive_var_nfrlt`                            | `nominal_time`                  | PKNamespace                   |

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
| `derive_vars_crit_flag`       | `flag` + `derivation` for CRITyFN                                    | Needs 3 columns (CRITy, CRITyFL, CRITyFN)      |
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
| 1   | `derive_var_merged_exist_flag`      | "Y" if record exists in another dataset     | Add `exist_flag` verb: `lookup` + `is_not_null` → flag. ~20 lines in `_mixins.py`.  |
| 2   | `derive_param_exist_flag`           | Append parameter record flagging existence  | `derive_param` + existence check. Wrap as `derive_param_exist_flag`.                |
| 3   | `derive_extreme_records`            | Append first/last record per group          | `derive_summary_records`-style with `filter_extreme` logic. Reuse `flag` internals. |
| 4   | `derive_param_doseint`              | Dose intensity: `DOSE / PLANNED_DOSE × 100` | Trivial `derive_param` + expression. Add as `dose_intensity` in OCCDS/BDS.          |
| 5   | `derive_param_wbc_abs`              | `WBC × differential / 100`                  | Trivial `derive_param` + expression. Add as convenience.                            |
| 6   | `compute_scale`                     | Compute questionnaire scale scores          | `derivation` with sum/mean across items. Add `scale_score` verb.                    |
| 7   | `yn_to_numeric`                     | "Y"→1, "N"→0                                | One-liner `recode`. Not worth a dedicated verb.                                     |
| 8   | `convert_blanks_to_na`              | Blank → null                                | Polars handles natively; add note in docs.                                          |
| 9   | `derive_var_merged_ef_msrc`         | Exist flag from multiple source datasets    | Chain multiple `exist_flag` calls with `condderivation`.                            |
| 10  | `filter_exist` / `filter_not_exist` | Semi-join / anti-join filters               | Add `filter_exist(dataset, on=...)` to SharedADaMVerbsMixin. ~15 lines.             |

### 🟡 Moderate (3–5 day effort, new algorithm or join pattern)

| #   | Admiral Function               | Description                                    | Fleet Implementation Strategy                                                                            |
| --- | ------------------------------ | ---------------------------------------------- | -------------------------------------------------------------------------------------------------------- |
| 11  | `derive_var_joined_exist_flag` | Flag based on conditions spanning two datasets | Extend `flag` with `from_dataset` + join condition parameters.                                           |
| 12  | `derive_var_relative_flag`     | Flag records before/after a condition          | New `relative_flag` verb: partition → locate condition → flag before/after. Reuse `flag` infrastructure. |
| 13  | `derive_vars_query`            | Derive SMQ/CQ variables from query dataset     | New `query_vars` verb in OCCDSNamespace. Needs query dataset schema.                                     |
| 14  | `create_query_data`            | Build query dataset from MedDRA/SMQ            | CLI utility + metadata lookup. Partially overlaps `fleet init` tooling.                                  |
| 15  | `derive_extreme_event`         | Worst/best observation as new record           | Generalise `derive_summary_records` with event-object pattern.                                           |
| 16  | `derive_vars_extreme_event`    | Worst/best observation as new variables (ADSL) | `first_date`/`last_date` generalized: add `extreme_event` to ADSLNamespace.                              |
| 17  | `derive_expected_records`      | Insert expected but missing records            | New `derive_expected_records` in BDS: cross-join expected visits × parameters, anti-join actual.         |
| 18  | `derive_vars_transposed`       | Transpose + merge another dataset              | `transform` with `.pivot()` + join. Add `transpose_merge` convenience verb.                              |
| 19  | `derive_param_exposure`        | Aggregate exposure with start/end dates        | New `exposure` verb in OCCDS: group_by period, sum dose, derive dates.                                   |
| 20  | `create_single_dose_dataset`   | Expand multi-dose to single-dose records       | `transform` with date_range expansion. Moderate Polars logic.                                            |
| 21  | `derive_vars_atc`              | ATC class variables from WHO Drug              | Needs external ATC dictionary lookup. Add `atc_class` verb to OCCDSNamespace.                            |
| 22  | `compute_qual_imputation`      | Handle `<` / `>` qualifiers in lab results     | New `qual_impute` verb: parse character result, apply factor. Moderate string parsing.                   |
| 23  | `compute_egfr`                 | eGFR by CKD-EPI/MDRD/Cockcroft-Gault           | New `egfr` in AdamNamespace. Multiple formulae, ~50 lines.                                               |

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

| Proposed Verb                       | Scope                   | Mixin / Class                         |
| ----------------------------------- | ----------------------- | ------------------------------------- |
| `exist_flag`                        | All namespaces          | `SharedADaMVerbsMixin`                |
| `filter_exist` / `filter_not_exist` | All namespaces          | `SharedADaMVerbsMixin`                |
| `relative_flag`                     | BDS + OCCDS             | New `FlagMixin` or extend `flag()`    |
| `extreme_records`                   | BDS                     | `MultiRowMixin`                       |
| `expected_records`                  | BDS                     | `MultiRowMixin`                       |
| `query_vars`                        | OCCDS only              | `OCCDSNamespace` directly             |
| `exposure`                          | OCCDS only              | `OCCDSNamespace` directly             |
| `egfr`                              | BDS (clinical measures) | `AdamNamespace` alongside `bmi`/`bsa` |
| `qual_impute`                       | BDS labs                | `AdamNamespace` or new `LabMixin`     |
| TTE subsystem                       | Dedicated               | New `TTENamespace` (`.adam.tte`)      |

### 4.2 Simplification Opportunities

1. **Unified `exist_flag` pattern.** Admiral has 3 functions (`derive_var_merged_exist_flag`, `derive_var_merged_ef_msrc`, `derive_param_exist_flag`). Fleet can unify into one `exist_flag(target, *, from_dataset, where, scope="var"|"param")` verb.

2. **`flag()` already subsumes 4 admiral functions.** Fleet's single `flag` verb with `criteria` shortcuts covers `derive_var_extreme_flag` (first/last/max/min). Adding `from_dataset` and `relative` modes would absorb `derive_var_joined_exist_flag` and `derive_var_relative_flag` too.

3. **`derive_param` is Fleet's universal parameter-derivation engine.** Admiral's `derive_param_bmi`, `_bsa`, `_map`, `_qtc`, `_rr`, `_wbc_abs`, `_doseint`, `_exist_flag` are all special cases. Fleet's single `derive_param(by_vars, set_values_to, parameter_filter, analysis_value)` + domain-specific expression covers all of them.

4. **Python's `for` loop replaces `call_derivation`.** No Fleet verb needed.

5. **`whereclauses` + restore pattern replaces `restrict_derivation`.** Consider adding a `scoped(where)` context manager for ergonomics but not strictly necessary.

### 4.3 Recommended Implementation Order (ROI-ranked)

| Priority | Verb(s)                                | Rationale                                                          |
| -------- | -------------------------------------- | ------------------------------------------------------------------ |
| P1       | `exist_flag`                           | Most-requested pattern; trivial to implement; covers 3 admiral fns |
| P1       | `filter_exist` / `filter_not_exist`    | Common data-quality filter; 15 lines each                          |
| P2       | `relative_flag`                        | Unique pattern not easily expressed today                          |
| P2       | `query_vars` + `create_query_data` CLI | Required for AE/CM SMQ/CQ derivations                              |
| P2       | `egfr`                                 | High-value clinical measure; no workaround                         |
| P3       | `extreme_records` / `expected_records` | Multi-row operations for BDS completeness                          |
| P3       | `qual_impute`                          | Lab-specific; niche but important for ADLB                         |
| P4       | TTE subsystem                          | Large scope; consider phased delivery                              |
| P4       | Framingham                             | Niche cardiovascular; low frequency                                |
| P4       | Pediatric growth                       | Requires reference data bundling                                   |

---

## 5. Implementation Phase: Enhanced `flag()` + `criterion()`

### 5.1 Design Philosophy

Admiral uses **7 separate functions** to derive flag variables. Fleet replaces them with **2 verbs** by leveraging Polars' window functions and expression-based set operations:

| Admiral Function (7)                   | Fleet Verb    | `criteria` value                     |
| -------------------------------------- | ------------- | ------------------------------------ |
| `derive_var_extreme_flag` (first/last) | `flag()`      | `"first"` / `"last"`                 |
| `derive_var_extreme_flag` (max/min)    | `flag()`      | `"max"` / `"min"`                    |
| `derive_var_merged_exist_flag`         | `flag()`      | `"exists"`                           |
| `derive_var_merged_ef_msrc`            | `flag()`      | `"exists"` (list of datasets)        |
| `derive_var_relative_flag`             | `flag()`      | `"before"` / `"after"`               |
| `derive_var_joined_exist_flag`         | `flag()`      | `"exists_after"` / `"exists_before"` |
| `derive_vars_crit_flag`                | `criterion()` | (separate verb, triple-output)       |

### 5.2 Proposed `flag()` Signature

```python
def flag(
    self,
    target: str,
    *,
    criteria: str | pl.Expr,
    groups: list[str] | None = None,
    order_by: str | list[str] | None = None,
    value_col: str | None = None,
    where: str | pl.Expr | None = None,
    # ── New parameters ──
    from_dataset: pl.DataFrame | list[pl.DataFrame] | None = None,
    on: list[str] | None = None,
    source_filter: pl.Expr | None = None,
    condition: pl.Expr | None = None,
    inclusive: bool = True,
    flag_no_ref_groups: bool = True,
    flag_all: bool = False,
    flag_value: str = "Y",
    false_value: str | None = None,
) -> Self:
```

**`criteria` dispatch:**

| Value                                | Behavior                             | Required params                   |
| ------------------------------------ | ------------------------------------ | --------------------------------- |
| `pl.Expr`                            | Direct boolean → flag where True     | —                                 |
| `"first"` / `"last"`                 | Rank-based edge detection            | `order_by`                        |
| `"max"` / `"min"`                    | Value-based extreme                  | `value_col`                       |
| `"exists"`                           | Set-membership from external dataset | `from_dataset`, `on`              |
| `"before"` / `"after"`               | Relative to landmark condition       | `condition`, `order_by`           |
| `"exists_after"` / `"exists_before"` | Temporal join condition              | `from_dataset`, `on`, `condition` |

### 5.3 Proposed `criterion()` Signature

```python
def criterion(
    self,
    number: int,
    *,
    condition: pl.Expr,
    description: str | None = None,
    prefix: str = "CRIT",
) -> Self:
```

Produces three columns: `{prefix}{number}`, `{prefix}{number}FL`, `{prefix}{number}FN`.

### 5.4 Polars Compilation Strategy

| Pattern                 | Polars primitive                                     | Advantage over R/dplyr             |
| ----------------------- | ---------------------------------------------------- | ---------------------------------- |
| Extreme (first/last)    | `pl.col(order_by).rank("ordinal").over(groups) == 1` | No materialisation, pure lazy expr |
| Extreme (max/min)       | `pl.col(val) == pl.col(val).max().over(groups)`      | Single-pass window                 |
| Exist (another dataset) | `pl.col(key).is_in(other[key])`                      | Zero-join, set membership          |
| Multi-source exist      | `pl.col(key).is_in(pl.concat([ds1, ds2, ...])[key])` | Union keys, single scan            |
| Relative (before/after) | `pl.col(cond).cum_max().over(groups)`                | O(n) cumulative signal             |
| Joined exist (temporal) | `join_asof` with tolerance or window expression      | Avoids full cross-join             |
| Criterion               | `pl.when(cond).then(flag_value)` + `.cast(pl.Int8)`  | Trivial expression                 |

### 5.5 Test Cases (Ported from Admiral)

All test data below is derived from admiral's MIT-licensed test suite (`tests/testthat/`).

#### 5.5.1 Extreme Flag — First/Last

```python
import polars as pl
import fleet  # noqa: F401

# ── admiral Test 1: first observation per group ──
# Source: test-derive_var_extreme_flag.R, Test 1
input_df = pl.DataFrame({
    "USUBJID": [1, 1, 2, 3, 3],
    "AVISITN": [1, 3, 2, 3, 3],
    "AVAL":    [12, 9, 42, 14, 10],
})

result = (
    input_df.adam
    .flag("firstfl", criteria="first", order_by=["AVISITN", "AVAL"],
          groups=["USUBJID"])
    .to_frame()
)
assert result["firstfl"].to_list() == ["Y", None, "Y", "Y", None]


# ── admiral Test 2: last observation per group ──
# Source: test-derive_var_extreme_flag.R, Test 2
result = (
    input_df.adam
    .flag("lastfl", criteria="last", order_by=["AVISITN", "AVAL"],
          groups=["USUBJID"])
    .to_frame()
)
assert result["lastfl"].to_list() == [None, "Y", "Y", None, "Y"]


# ── admiral Test 7: NA in order column ──
# Source: test-derive_var_extreme_flag.R, Test 7
input_na = pl.DataFrame({
    "USUBJID": [1, 1, 2, 3, 3],
    "AVISITN": [None, 3, 2, 3, 3],
    "AVAL":    [12, 9, 42, 14, 10],
})

result = (
    input_na.adam
    .flag("firstfl", criteria="first", order_by=["AVISITN", "AVAL"],
          groups=["USUBJID"])
    .to_frame()
)
assert result["firstfl"].to_list() == [None, "Y", "Y", "Y", None]


# ── admiral Test 4: flag_all=True (ties) ──
# Source: test-derive_var_extreme_flag.R, Test 4
input_ties = pl.DataFrame({
    "STUDYID":  ["TEST01"] * 5,
    "USUBJID":  ["PAT01"] * 5,
    "ADTM":     ["2020-02-01T12:00", "2020-02-01T12:00",
                 "2020-02-01T12:01", "2020-02-01T13:00", "2020-02-01T13:00"],
    "AVISITN":  [1] * 5,
    "BASETYPE": ["ontrt"] * 5,
    "PARAM":    ["test1", "test2", "test1", "test1", "test2"],
})

result = (
    input_ties.adam
    .flag("FIRSTFL", criteria="first", order_by="ADTM",
          groups=["STUDYID", "USUBJID", "BASETYPE", "AVISITN"],
          flag_all=True)
    .to_frame()
)
assert result["FIRSTFL"].to_list() == ["Y", "Y", None, None, None]


# ── admiral Test 9: custom true/false values ──
# Source: test-derive_var_extreme_flag.R, Test 9
result = (
    input_df.adam
    .flag("firstfl", criteria="first", order_by=["AVISITN", "AVAL"],
          groups=["USUBJID"],
          flag_value="Yes", false_value="No")
    .to_frame()
)
assert result["firstfl"].to_list() == ["Yes", "No", "Yes", "Yes", "No"]
```

#### 5.5.2 Exist Flag — Single Dataset

```python
# ── admiral Test 19: merge existence flag ──
# Source: test-derive_merged.R, Test 19
adsl = pl.DataFrame({
    "USUBJID": ["ST42-1", "ST42-2", "ST42-3", "ST42-4"],
    "SEX":     ["F", "M", "M", "F"],
    "STUDYID": ["ST42"] * 4,
})

advs = pl.DataFrame({
    "USUBJID": ["ST42-1", "ST42-1", "ST42-2", "ST42-3", "ST42-3"],
    "PARAMCD": ["WEIGHT"] * 5,
    "AVISIT":  ["BASELINE", "Week 2", "BASELINE", "Week 2", "Week 4"],
    "AVAL":    [66, 68, 88, 55, 50],
    "STUDYID": ["ST42"] * 5,
})

result = (
    adsl.adam.adsl
    .flag("VSEVALFL", criteria="exists",
          from_dataset=advs,
          on=["USUBJID"],
          source_filter=pl.col("AVISIT") == "BASELINE")
    .to_frame()
)
assert result["VSEVALFL"].to_list() == ["Y", "Y", None, None]


# ── admiral: exist flag with condition on source dataset ──
# Source: test-derive_merged.R (derive_var_merged_exist_flag example)
dm = pl.DataFrame({
    "STUDYID": ["PILOT01"] * 4,
    "USUBJID": ["01-1028", "04-1127", "06-1049", "09-1088"],
    "AGE":     [71, 84, 68, 69],
})

ae = pl.DataFrame({
    "STUDYID": ["PILOT01"] * 4,
    "USUBJID": ["01-1028", "01-1028", "06-1049", "06-1049"],
    "AEREL":   ["POSSIBLE", "PROBABLE", "POSSIBLE", "PROBABLE"],
})

result = (
    dm.adam.adsl
    .flag("AERELFL", criteria="exists",
          from_dataset=ae,
          on=["STUDYID", "USUBJID"],
          source_filter=pl.col("AEREL") == "PROBABLE")
    .to_frame()
)
assert result["AERELFL"].to_list() == ["Y", None, "Y", None]
```

#### 5.5.3 Exist Flag — Multiple Sources

```python
# ── admiral Test 1: multi-source existence flag ──
# Source: test-derive_var_merged_ef_msrc.R, Test 1
adsl = pl.DataFrame({
    "USUBJID":   ["1", "2", "3"],
    "CANCTRFL":  [None, None, None],  # to be derived
})

cm = pl.DataFrame({
    "USUBJID": ["1", "1", "2"],
    "CMCAT":   ["ANTI-CANCER", "OTHER", "ANTI-CANCER"],
})

pr = pl.DataFrame({
    "USUBJID": ["1", "3"],
    "PRDECOD": ["SURGERY", "RADIATION"],
})

# Fleet: pass list of pre-filtered datasets
result = (
    adsl.select("USUBJID").adam.adsl
    .flag("CANCTRFL", criteria="exists",
          from_dataset=[
              cm.filter(pl.col("CMCAT") == "ANTI-CANCER"),
              pr,
          ],
          on=["USUBJID"])
    .to_frame()
)
assert result["CANCTRFL"].to_list() == ["Y", "Y", "Y"]
```

#### 5.5.4 Relative Flag — Before/After Landmark

```python
# ── admiral Test 1: flag observations up to first PD (inclusive) ──
# Source: test-derive_var_relative_flag.R, Test 1
response = pl.DataFrame({
    "USUBJID": ["1","1","1","1","1", "2","2","2", "3", "4","4","4","4","4"],
    "AVISITN": [0,   1,  2,  3,  4,   0,  1,  2,   0,   0,  1,  2,  3,  4],
    "AVALC":   ["PR","CR","CR","SD","NE",
                "SD","PD","PD",
                "SD",
                "SD","PR","PD","SD","PR"],
})

result = (
    response.adam
    .flag("ANL02FL", criteria="before",
          condition=pl.col("AVALC") == "PD",
          order_by="AVISITN",
          groups=["USUBJID"],
          inclusive=True)
    .to_frame()
)
expected = [
    "Y","Y","Y","Y","Y",   # USUBJID=1: no PD → all flagged
    "Y","Y", None,          # USUBJID=2: PD at visit 1 → include it, exclude after
    "Y",                     # USUBJID=3: no PD → all flagged
    "Y","Y","Y", None, None # USUBJID=4: PD at visit 2 → include it
]
assert result["ANL02FL"].to_list() == expected


# ── admiral Test 2: flag AEs AFTER first COVID AE (exclusive) ──
# Source: test-derive_var_relative_flag.R, Test 2
adae = pl.DataFrame({
    "USUBJID": ["1","1","1","1","1","1", "2","2"],
    "ASTDY":   [2,   5,  5, 17, 27, 32,   8, 11],
    "ACOVFL":  [None,"Y",None,None,"Y",None, None,None],
    "AESEQ":   [1,   2,  3,  4,  5,  6,   1,  2],
})

result = (
    adae.adam
    .flag("PSTCOVFL", criteria="after",
          condition=pl.col("ACOVFL") == "Y",
          order_by=["ASTDY", "AESEQ"],
          groups=["USUBJID"],
          inclusive=False,
          flag_no_ref_groups=False)
    .to_frame()
)
expected = [
    None, None, "Y", "Y", "Y", "Y",  # USUBJID=1: COVID at seq=2 → after
    None, None                          # USUBJID=2: no COVID → flag_no_ref=False
]
assert result["PSTCOVFL"].to_list() == expected
```

#### 5.5.5 Joined Exist Flag — Temporal/Self-Join

```python
# ── admiral Test 1: PR followed by CR or PR ──
# Source: test-derive_var_joined_exist_flag.R, Test 1
data = pl.DataFrame({
    "USUBJID": ["1","1","1","1","1", "2","2","2", "3", "4","4","4","4","4"],
    "AVISITN": [1,   2,  3,  4,  5,   1,  2,  3,   1,   1,  2,  3,  4,  5],
    "AVALC":   ["PR","CR","CR","SD","NE",
                "SD","PR","PD",
                "SD",
                "PR","PD","SD","SD","PR"],
})

result = (
    data.adam
    .flag("CONFFL", criteria="exists_after",
          from_dataset=data,
          on=["USUBJID"],
          condition=(pl.col("AVALC") == "PR"),
          source_filter=pl.col("AVALC").is_in(["CR", "PR"]))
    .to_frame()
)
expected = [
    "Y", None, None, None, None,  # USUBJID=1: PR@1 followed by CR@2
    None, None, None,              # USUBJID=2: PR@2 followed by PD — no CR/PR after
    None,                          # USUBJID=3: no PR
    "Y", None, None, None, None   # USUBJID=4: PR@1 followed by PR@5
]
assert result["CONFFL"].to_list() == expected


# ── admiral Test 4: duration > 30 AND within 7 days of COVID AE ──
# Source: test-derive_var_joined_exist_flag.R, Test 4
adae = pl.DataFrame({
    "USUBJID": ["1","1","1","1","1", "2","2","2", "3", "4","4"],
    "ADY":     [10, 21, 23, 32, 42,   2, 11, 23,  13,  14, 21],
    "ACOVFL":  ["N","N","Y","N","N", "N","Y","N", "Y", "N","N"],
    "ADURN":   [1,  50, 14, 31, 20,  33, 13,  2,  12,  32, 41],
})

result = (
    adae.adam
    .flag("ALCOVFL", criteria="exists_after",
          from_dataset=adae,
          on=["USUBJID"],
          condition=(pl.col("ADURN") > 30),
          source_filter=(pl.col("ACOVFL") == "Y"),
          window=pl.duration(days=7))
    .to_frame()
)
expected = [
    None, "Y", None, "Y", None,  # USUBJID=1
    None, None, None,              # USUBJID=2
    None,                          # USUBJID=3
    None, None                     # USUBJID=4
]
assert result["ALCOVFL"].to_list() == expected
```

#### 5.5.6 Criterion Flag

```python
# ── Triple-output pattern (CRITy, CRITyFL, CRITyFN) ──
# Source: test-derive_vars_cat.R concept
adlb = pl.DataFrame({
    "USUBJID": ["1", "1", "2"],
    "PARAMCD": ["ALT", "ALT", "ALT"],
    "AVAL":    [15.0, 8.0, 12.0],
})

result = (
    adlb.adam
    .criterion(1, condition=pl.col("AVAL") >= 10,
               description="AVAL >= 10")
    .to_frame()
)
assert result["CRIT1"].to_list() == ["AVAL >= 10"] * 3
assert result["CRIT1FL"].to_list() == ["Y", "N", "Y"]
assert result["CRIT1FN"].to_list() == [1, 0, 1]


# ── Multiple criteria ──
result = (
    adlb.adam
    .criterion(1, condition=pl.col("AVAL") >= 10,
               description="AVAL >= 10")
    .criterion(2, condition=pl.col("AVAL") >= 15,
               description="AVAL >= 15")
    .to_frame()
)
assert result["CRIT1FL"].to_list() == ["Y", "N", "Y"]
assert result["CRIT2FL"].to_list() == ["Y", "N", "N"]
assert result["CRIT2FN"].to_list() == [1, 0, 0]
```

### 5.6 Edge Cases to Handle (from Admiral Test Suite)

| Edge Case                         | Admiral Source                           | Fleet Requirement                                 |
| --------------------------------- | ---------------------------------------- | ------------------------------------------------- |
| `None` in order column            | `test-derive_var_extreme_flag.R` Test 7  | Rows with null order → never flagged (get `None`) |
| Tied extreme values               | Tests 3–6 (`flag_all`)                   | `flag_all=True` flags all tied extremes           |
| Custom true/false values          | Test 9                                   | `flag_value` + `false_value` params               |
| No reference group (relative)     | `test-derive_var_relative_flag.R` Test 2 | `flag_no_ref_groups=False` → all `None`           |
| Self-join (same dataset)          | `test-derive_var_joined_exist_flag.R`    | `from_dataset` can be the pipeline's own frame    |
| `source_filter` on external DS    | `test-derive_merged.R` Test 19           | Pre-filter before key extraction                  |
| `inclusive=True/False` (relative) | `test-derive_var_relative_flag.R`        | Include/exclude the landmark row itself           |
| Multi-source key union            | `test-derive_var_merged_ef_msrc.R`       | `from_dataset` accepts `list[pl.DataFrame]`       |

### 5.7 Implementation Placement

Both verbs go in `SharedADaMVerbsMixin` (`src/fleet/adam/_mixins.py`):

```
src/fleet/adam/_mixins.py
├── flag()          ← extend existing method with new criteria modes
└── criterion()     ← new method (~25 lines)
```

**Admiral coverage absorbed:** 7 functions → 2 Fleet verbs. Combined with existing `flag()` modes (`first`/`last`/`max`/`min`) already shipping, this closes **items #1, #9, #11, #12** from the gap list and moves `derive_vars_crit_flag` from "near-equivalent" to "direct equivalent."

---

## 6. Coverage Summary

| Category                               | Count   | % of Admiral Derivation Surface |
| -------------------------------------- | ------- | ------------------------------- |
| Direct equivalents                     | 28      | 38%                             |
| Near-equivalents (expressible today)   | 17      | 23%                             |
| Missing — Easy                         | 10      | 14%                             |
| Missing — Moderate                     | 13      | 18%                             |
| Missing — Complex                      | 7       | 9%                              |
| **Total admiral derivation functions** | **~75** | —                               |

> **Note:** Admiral utility functions (template management, quosure helpers, dataset checking) are excluded as they are R-ecosystem-specific and have no meaningful clinical-programming equivalent in a Python/Polars pipeline.

---

## 7. Extension Package Gaps (admiralonco, admiralvaccines, admiralophtha, admiralpeds)

| Extension           | Fleet Coverage                                                                            | Gap                                                                                    |
| ------------------- | ----------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| **admiralonco**     | `OncoNamespace` covers BOR, confirmed response, tumor_response_flag, filter_pd, aval_resp | Missing: `derive_param_confirmed_resp` full event_joined pattern, duration of response |
| **admiralvaccines** | `VaccineNamespace` covers fever, seroconversion, seroresponse, event_flag, aval_adis      | Missing: multi-period reactogenicity, booster-dose derivations                         |
| **admiralophtha**   | `OphthaNamespace` covers ETDRS/LogMAR, study_eye, affected_eye, bcva_criterion            | Substantially complete; minor: `derive_var_aession` (study eye from AGSUB)             |
| **admiralpeds**     | `PedsNamespace` covers age_days, age_months, corrected_age, prematurity_flag              | Missing: WHO/CDC growth chart z-scores/percentiles                                     |

---

_End of report._
