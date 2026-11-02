# CDISC Rules Engine: Custom Rule Writing Guide & Tracker

> **Source:** [pharmaverse sdtmchecks R package](https://github.com/pharmaverse/sdtmchecks)
> **Target:** Fleet CDISC Rules Engine custom YAML rules
> **Branch:** `feat/sdtmchecks-custom-rules`
> **Date:** 2026-05-20

---

## Part 1: Tutorial — Writing Custom CDISC Rules (Easy → Advanced)

This tutorial teaches you to write custom rules for the CDISC Rules Engine,
progressing from simple record-level checks to advanced cross-domain validations.

### Execution

Custom rules are executed using the `-lr` (local rules) flag:

```bash
fleet validate --datasets ./data --local-rules ./metadata/custom_rules/
```

Or with the engine directly:

```bash
core -s SDTMIG -v 3-4 -dp ./data -lr ./metadata/custom_rules/ -o results.json
```

---

### Level 1: Simple Record-Level Check (Single Condition)

The simplest rule checks one condition on a single variable.

```yaml
# Rule: AEDECOD must not be empty
Core:
  Id: SDTMCHK-AE-001
  Status: Draft
  Version: '1'

Rule Type: Record Data

Scope:
  Classes:
    Include: [EVENTS]
  Domains:
    Include: [AE]

Check:
  all:
    - name: AEDECOD
      operator: empty

Outcome:
  Message: "AEDECOD is missing. All AE records must have a coded preferred term."
  Output Variables: [USUBJID, AETERM, AEDECOD]

Description: "AEDECOD must be populated for every AE record."
Sensitivity: Record
Executability: Fully Executable

Authorities:
  - Organization: sdtmchecks
    Standards:
      - Name: SDTMIG
        Version: '3.4'
        References:
          - Origin: sdtmchecks R package
            Rule Identifier:
              Id: SDTMCHK-AE-001
              Version: '1'
```

**Key anatomy:**

| Section | Purpose |
|---------|---------|
| `Core` | Unique ID, status, version |
| `Rule Type` | Always `Record Data` for row-level checks |
| `Scope` | Which domains/classes the rule applies to |
| `Check` | The validation logic (conditions that flag an issue) |
| `Outcome` | Error message and variables to display |
| `Description` | Human-readable explanation |
| `Sensitivity` | `Record` (one issue per row) or `Dataset` |
| `Executability` | `Fully Executable` or `Partially Executable` |
| `Authorities` | Provenance and standard references |

---

### Level 2: Multi-Condition Check (AND logic)

Use `all:` to require ALL conditions to be true to flag a record.

```yaml
# Rule: AEDTHDTC populated but AESDTH ≠ 'Y'
Check:
  all:
    - name: AEDTHDTC
      operator: non_empty
    - name: AESDTH
      operator: not_equal_to
      value: "Y"
      value_is_literal: true
```

**Important:** `value_is_literal: true` means `"Y"` is a literal string, NOT a
column name. Without it, the engine would look for a column called `Y`.

---

### Level 3: OR Logic and Nested Conditions

Use `any:` for OR logic. You can nest `all:` inside `any:` for complex patterns.

```yaml
# Rule: CMSTDTC or CMENDTC is an incomplete date
Check:
  any:
    - all:
        - name: CMSTDTC
          operator: non_empty
        - name: CMSTDTC
          operator: is_incomplete_date
    - all:
        - name: CMENDTC
          operator: non_empty
        - name: CMENDTC
          operator: is_incomplete_date
```

---

### Level 4: Set Membership (Valid Value Lists)

Use `is_not_contained_by` to check if a value is NOT in an allowed list.

```yaml
# Rule: AEREL contains an unexpected causality value
Check:
  all:
    - name: AEREL
      operator: non_empty
    - name: AEREL
      operator: is_not_contained_by
      value:
        - "RELATED"
        - "NOT RELATED"
        - "POSSIBLY RELATED"
        - "PROBABLY RELATED"
        - "UNLIKELY RELATED"
```

---

### Level 5: Date Comparison (Within Same Domain)

Compare two date columns using `date_greater_than`, `date_less_than`, etc.
Use `date_component: auto` for partial-date-aware comparisons.

```yaml
# Rule: AEENDTC is before AESTDTC (impossible end before start)
Check:
  all:
    - name: AEENDTC
      operator: non_empty
    - name: AESTDTC
      operator: non_empty
    - name: AESTDTC
      operator: date_greater_than
      value: AEENDTC
      date_component: auto
```

**Available date operators:** `date_equal_to`, `date_not_equal_to`,
`date_greater_than`, `date_less_than`, `date_greater_than_or_equal_to`,
`date_less_than_or_equal_to`, `is_complete_date`, `is_incomplete_date`, `invalid_date`.

---

### Level 6: Uniqueness & Duplicate Detection

Use `is_not_unique_set` to detect duplicate records based on a key combination.

```yaml
# Rule: Duplicate AE records (same subject + term + dates)
Check:
  all:
    - name: AETERM
      operator: is_not_unique_set
      value:
        - USUBJID
        - AESTDTC
        - AEENDTC
        - AEDECOD
```

Use `present_on_multiple_rows_within` for group-based duplicate detection:

```yaml
# Rule: Multiple randomization records per subject
Check:
  all:
    - name: DSDECOD
      operator: equal_to
      value: "RANDOMIZED"
      value_is_literal: true
    - name: DSDECOD
      operator: present_on_multiple_rows_within
      within: USUBJID
```

---

### Level 7: Data Consistency (Value Stability Within Groups)

Use `is_inconsistent_across_dataset` to flag when a variable's value differs
within a grouping.

```yaml
# Rule: Multiple death records with different dates
Check:
  all:
    - name: DSDECOD
      operator: equal_to
      value: "DEATH"
      value_is_literal: true
    - name: DSSTDTC
      operator: non_empty
    - name: DSSTDTC
      operator: is_inconsistent_across_dataset
      value: USUBJID
```

---

### Level 8: Visit Ordering (Sequential Data)

Use `target_is_not_sorted_by` to validate chronological order within groups.

```yaml
# Rule: Visit dates not in chronological order
Check:
  all:
    - name: EGDTC
      operator: non_empty
    - name: VISITNUM
      operator: non_empty
    - name: VISITNUM
      operator: target_is_not_sorted_by
      within:
        - USUBJID
      value:
        - name: EGDTC
          sort_order: asc
```

**Parameters:**

- `within:` — grouping variable(s) (subject, test, etc.)
- `value:` — sorting criteria with `name`, `sort_order` (asc/desc), optional `null_position`
- `regex:` — optional, extract portion of value for sort comparison

---

### Level 9: Cross-Domain Checks (Operations Block)

The `Operations` block enables cross-domain logic by computing aggregations
from other datasets, then using the results in `Check`.

```yaml
# Rule: AE start date after death date from DS domain
Check:
  all:
    - name: AESTDTC
      operator: non_empty
    - name: $ds_death_date
      operator: non_empty
    - name: AESTDTC
      operator: date_greater_than
      value: $ds_death_date
      date_component: auto

Operations:
  - operator: max_date
    domain: DS
    name: DSSTDTC
    id: $ds_death_date
    group:
      - USUBJID
    filter:
      DSDECOD: DEATH
```

**How it works:**

1. `Operations` runs FIRST — queries another domain, computes a per-subject value.
2. The result is stored as `$ds_death_date` (accessible as a column/scalar in Check).
3. `Check` compares AESTDTC against the computed `$ds_death_date`.

**Available operation operators:**

| Operator | Description |
|----------|-------------|
| `distinct` | Unique list of values (use with `is_contained_by` / `is_not_contained_by`) |
| `max` | Maximum numeric value |
| `min` | Minimum numeric value |
| `max_date` | Latest date |
| `min_date` | Earliest date |
| `mean` | Average value |
| `record_count` | Number of records (with optional filter/group) |

**Operation parameters:**

- `domain:` — target domain to query
- `name:` — variable to aggregate
- `id:` — `$variable` name to reference in Check
- `group:` — grouping variables (e.g., `[USUBJID]` for per-subject)
- `filter:` — subset conditions (dictionary format: `VARNAME: VALUE`)

---

### Level 10: Cross-Domain Existence (Subject in Other Domain)

Combine `Operations: distinct` with `is_not_contained_by` to check if a subject
has records in another domain.

```yaml
# Rule: DTHFL=Y in DM but no death record in DS
Check:
  all:
    - name: DTHFL
      operator: equal_to
      value: "Y"
      value_is_literal: true
    - name: USUBJID
      operator: is_not_contained_by
      value: $ds_death_subjects

Operations:
  - operator: distinct
    domain: DS
    name: USUBJID
    id: $ds_death_subjects
    filter:
      DSDECOD: DEATH
```

**Pattern:** Get the list of subjects meeting a condition in domain B, then check
if the current record's subject is NOT in that list.

---

### Level 11: Match Datasets (Explicit Cross-Domain Joins)

For direct column-to-column comparisons across domains, use `Match Datasets`
(newer engine feature):

```yaml
# Rule: AE death date ≠ DM death date (direct join)
Check:
  all:
    - name: AEDTHDTC
      operator: non_empty
    - name: DTHDTC
      operator: non_empty
    - name: AEDTHDTC
      operator: date_not_equal_to
      value: DTHDTC
      date_component: auto

Match Datasets:
  - Name: DM
    Keys:
      - USUBJID
    Join Type: inner
```

This merges DM columns (like DTHDTC) into the AE evaluation frame using
USUBJID as the join key.

---

### Complete Operator Reference

#### Relational
`equal_to`, `not_equal_to`, `greater_than`, `less_than`, `greater_than_or_equal_to`,
`less_than_or_equal_to`, `empty`, `non_empty`

#### String
`matches_regex`, `not_matches_regex`, `starts_with`, `ends_with`, `contains`,
`does_not_contain`, `longer_than`, `shorter_than`, `is_title_case`

#### Date
`date_equal_to`, `date_not_equal_to`, `date_greater_than`, `date_less_than`,
`is_complete_date`, `is_incomplete_date`, `invalid_date`, `invalid_duration`

#### Set Membership
`is_contained_by`, `is_not_contained_by`, `is_contained_by_case_insensitive`

#### Set Operations
`contains_all`, `shares_at_least_one_element_with`, `shares_no_elements_with`,
`is_ordered_subset_of`

#### Uniqueness & Integrity
`is_unique_set`, `is_not_unique_set`, `is_unique_relationship`,
`present_on_multiple_rows_within`

#### Data Consistency
`is_inconsistent_across_dataset`, `has_same_values`

#### Sequential & Ordering
`target_is_sorted_by`, `target_is_not_sorted_by`, `is_ordered_set`,
`has_next_corresponding_record`, `empty_within_except_last_row`

#### Metadata
`exists`, `not_exists`

---

### Tips & Patterns

1. **Always include `non_empty` guards** before comparing values — otherwise null
   records may trigger false positives.

2. **Use `value_is_literal: true`** when comparing against a fixed string. Without
   it, the engine interprets the value as a column name.

3. **`date_component: auto`** is your friend for partial dates — the engine
   automatically compares at the common precision level.

4. **Operations run before Check** — you can reference multiple `$variables`
   from different domains in a single rule.

5. **Filter in Operations** uses exact match syntax: `VARNAME: VALUE`.

6. **Sensitivity: Record** means one finding per row. Use `Dataset` for
   dataset-level checks.

---

## Part 2: Translation Tracker

---

### Summary

| Status | Count |
|--------|-------|
| ✅ YAML translated | 53 |
| 🔵 Covered by CORE | 14 |
| ⚠️ Not expressible | 8 |
| 🟡 COVID/OPHTH-specific (skipped) | 15 |
| 🔄 Partially expressible (simplified) | 19 |
| **Total functions** | **109** |

---

### Legend

| Column | Description |
|--------|-------------|
| **Function** | R function name from sdtmchecks |
| **Domain(s)** | SDTM domain(s) involved |
| **Status** | ✅ Translated / 🔵 CORE covered / ⚠️ Not expressible / 🟡 Skipped / 🔄 Partial |
| **Rule ID** | Fleet custom rule ID or CORE ID |
| **Notes** | Coverage details and engine mechanism used |

---

### AE Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 1 | `check_ae_aedecod` | AE | ✅ | SDTMCHK-AE-001 | `empty` operator |
| 2 | `check_ae_aedthdtc_aesdth` | AE | ✅ | SDTMCHK-AE-002 | `non_empty` + `not_equal_to` |
| 3 | `check_ae_aesdth_aedthdtc` | AE | ✅ | SDTMCHK-AE-003 | `equal_to` + `empty` |
| 4 | `check_ae_aeout` (part 1) | AE | ✅ | SDTMCHK-AE-004 | AEDTHDTC present, AEOUT≠FATAL |
| 5 | `check_ae_aeout` (part 2) | AE | ✅ | SDTMCHK-AE-005 | AEOUT=FATAL, AEDTHDTC missing |
| 6 | `check_ae_death` | AE | ✅ | SDTMCHK-AE-006 | Grade 5 death inconsistency |
| 7 | `check_ae_fatal` | AE | ✅ | SDTMCHK-AE-007 | AEOUT=FATAL inconsistency |
| 8 | `check_ae_aeout_aeendtc_nonfatal` (part 1) | AE | ✅ | SDTMCHK-AE-008 | Resolved AE, AEENDTC missing |
| 9 | `check_ae_aeout_aeendtc_nonfatal` (part 2) | AE | ✅ | SDTMCHK-AE-009 | NOT RECOVERED, AEENDTC populated |
| 10 | `check_ae_aeout_aeendtc_aedthdtc` | AE | ✅ | SDTMCHK-AE-010 | FATAL: AEENDTC≠AEDTHDTC |
| 11 | `check_ae_aetoxgr` | AE | ✅ | SDTMCHK-AE-011 | Both AETOXGR and AESEV missing |
| 12 | `check_ae_aelat` | AE | ✅ | SDTMCHK-AE-012 | Eye AE missing laterality |
| 13 | `check_ae_aestdtc_after_aeendtc` | AE | 🔵 | CORE-000717 | AESTDTC > AEENDTC |
| 14 | `check_ae_aerel` | AE | ✅ | SDTMCHK-AE-021 | `is_not_contained_by` value list |
| 15 | `check_ae_dup` | AE | ✅ | SDTMCHK-AE-014 | `is_not_unique_set` |
| 16 | `check_ae_aeacnoth` | AE | ✅ | SDTMCHK-AE-022 | MULTIPLE but AEACNOT1 missing |
| 17 | `check_ae_aestdtc_after_dd` | AE, DS | ✅ | SDTMCHK-AE-013 | `Operations: max_date` + `date_greater_than` |
| 18 | `check_ae_aedthdtc_ds_death` | AE, DS | ✅ | SDTMCHK-AE-015 | `Operations: distinct` + `is_not_contained_by` |
| 19 | `check_ae_death_ds_discon` | AE, DS | ✅ | SDTMCHK-AE-019 | `Operations: distinct` + `is_not_contained_by` |
| 20 | `check_ae_ds_partial_death_dates` | AE | ✅ | SDTMCHK-AE-017 | `is_incomplete_date` |
| 21 | `check_ae_withdr_ds_discon` | AE, DS | ✅ | SDTMCHK-AE-018 | `Operations: distinct` + `is_not_contained_by` |
| 22 | `check_ae_aeacn_ds_disctx_covid` | AE, DS | 🟡 | — | COVID-specific |
| 23 | `check_ae_aeacnoth_ds_disctx` | AE, DS | ✅ | SDTMCHK-AE-020 | `contains_case_insensitive` + cross-domain |
| 24 | `check_ae_aeacnoth_ds_stddisc_covid` | AE, DS | 🟡 | — | COVID-specific |
| — | `check_dd_ae_aedthdtc_ds_dsstdtc` | AE, DS | ✅ | SDTMCHK-AE-016 | `Operations: max_date` + `date_not_equal_to` |
| — | `check_dd_ae_aeout_aedthdtc` | AE | 🔵 | SDTMCHK-AE-004/005 | Covered by existing rules |
| — | `check_dd_death_date` | AE, DS | 🔄 | SDTMCHK-AE-015 | Partially covered via AE-015 |

---

### CE Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 25 | `check_ce_missing_month` | CE | ✅ | SDTMCHK-CE-001 | `is_incomplete_date` |

---

### CM Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 26 | `check_cm_cmdecod` | CM | ✅ | SDTMCHK-CM-001 | `empty` operator |
| 27 | `check_cm_cmindc` | CM | 🟡 | — | OPHTH-specific |
| 28 | `check_cm_cmlat` | CM | 🟡 | — | OPHTH-specific |
| 29 | `check_cm_cmlat_prior_ocular` | CM | 🟡 | — | OPHTH-specific |
| 30 | `check_cm_missing_month` | CM | ✅ | SDTMCHK-CM-002 | `is_incomplete_date` (any: start or end) |

---

### DM Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 34 | `check_dm_actarm_arm` | DM | ✅ | SDTMCHK-DM-002 | ARM ≠ ACTARM |
| 35 | `check_dm_age_missing` | DM | ✅ | SDTMCHK-DM-001 | AGE missing |
| 36 | `check_dm_armcd` | DM | 🔵 | CORE-000119 | ARM/ARMCD missing |
| 37 | `check_dm_dthfl_dthdtc` | DM | 🔵 | CORE-000006/007 | DTHFL/DTHDTC consistency |
| 38 | `check_dm_usubjid_dup` | DM | 🔵 | CORE-000186 | Duplicate SUBJID |
| 39 | `check_dm_ae_ds_death` | DM, AE, DS | ✅ | SDTMCHK-DM-003 | `Operations: distinct` + `is_not_contained_by` |
| 40 | `check_dm_usubjid_ae_usubjid` | DM, AE, DS, EX | ⚠️ | — | Multi-domain merge + conditional logic beyond DSL |

---

### DS Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 41 | `check_ds_dsdecod_dsstdtc` | DS | ✅ | SDTMCHK-DS-001 | DEATH without date |
| 42 | `check_ds_dsterm_death_due_to` | DS | ✅ | SDTMCHK-DS-002 | Blank death cause |
| 43 | `check_ds_dsdecod_death` | DS | ✅ | SDTMCHK-DS-006 | `Operations: distinct` cross-record |
| 44 | `check_ds_dsscat` | DS | 🔵 | CORE-000213 | Multiple study discon |
| 45 | `check_ds_duplicate_randomization` | DS | ✅ | SDTMCHK-DS-003 | `present_on_multiple_rows_within` |
| 46 | `check_ds_multdeath_dsstdtc` | DS | ✅ | SDTMCHK-DS-004 | `is_inconsistent_across_dataset` |
| 47 | `check_ds_ae_discon` | DS, AE | ✅ | SDTMCHK-DS-007 | `Operations: distinct` + `is_not_contained_by` |
| 48 | `check_ds_ex_after_discon` | DS, EX | ✅ | SDTMCHK-DS-005 | `Operations: max_date` + `date_greater_than` |
| 49 | `check_ds_sc_strat` | DS, SC | ⚠️ | — | Requires SC domain with specific stratification logic |

---

### DV Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 50 | `check_dv_ae_aedecod_covid` | AE, DV | 🟡 | — | COVID-specific |
| 51 | `check_dv_covid` | DV | 🟡 | — | COVID-specific |

---

### EC Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 52 | `check_ec_sc_lat` | EC, SC | 🟡 | — | OPHTH-specific |

---

### EG Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 53 | `check_eg_egdtc_visit_ordinal_error` | EG | ✅ | SDTMCHK-EG-001 | `target_is_not_sorted_by` |

---

### EX Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 54 | `check_ex_exdose_exoccur` | EX | ✅ | SDTMCHK-EX-001 | EXDOSE missing when occurred |
| 55 | `check_ex_exdose_pos_exoccur_no` | EX | ✅ | SDTMCHK-EX-002 | EXDOSE>0 but EXOCCUR≠Y |
| 56 | `check_ex_exdosu` | EX | ✅ | SDTMCHK-EX-003 | EXDOSU missing |
| 57 | `check_ex_extrt_exoccur` | EX | ✅ | SDTMCHK-EX-004 | EXTRT missing |
| 58 | `check_ex_visit` | EX | ✅ | SDTMCHK-EX-005 | VISIT missing |
| 59 | `check_ex_exoccur_mis_exdose_nonmis` | EX | ✅ | SDTMCHK-EX-006 | EXOCCUR missing, EXDOSE present |
| 60 | `check_ex_exstdtc_after_exendtc` | EX | 🔵 | CORE-000718 | --STDTC > --ENDTC |
| 61 | `check_ex_dup` | EX | ✅ | SDTMCHK-EX-007 | `is_not_unique_set` |
| 62 | `check_ex_exoccur_exdose_exstdtc` | EX | ✅ | SDTMCHK-EX-011 | EXOCCUR=N but dose/date present |
| 63 | `check_ex_exstdtc_after_dd` | AE, DS, EX | ✅ | SDTMCHK-EX-008 | `Operations: max_date` + `date_greater_than` |
| 64 | `check_ex_exstdtc_visit_ordinal_error` | EX | ✅ | SDTMCHK-EX-009 | `target_is_not_sorted_by` |
| 65 | `check_ex_infusion_exstdtc_exendtc` | EX | ✅ | SDTMCHK-EX-010 | IV route + `date_equal_to` (same datetime) |

---

### LB Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 66 | `check_lb_lbstresn_missing` | LB | ✅ | SDTMCHK-LB-001 | LBORRES present, standardized missing |
| 67 | `check_lb_lbstresu` | LB | ✅ | SDTMCHK-LB-002 | Units missing |
| 68 | `check_lb_lbstresc_char` | LB | ✅ | SDTMCHK-LB-003 | < or > prefix in results |
| 69 | `check_lb_lbstnrlo_lbstnrhi` | LB | ✅ | SDTMCHK-LB-007 | Reference range missing for numeric |
| 70 | `check_lb_lbdtc_after_dd` | AE, DS, LB | ✅ | SDTMCHK-LB-006 | `Operations: max_date` + `date_greater_than` |
| 71 | `check_lb_lbdtc_visit_ordinal_error` | LB | ✅ | SDTMCHK-LB-004 | `target_is_not_sorted_by` |
| 72 | `check_lb_missing_month` | LB | ✅ | SDTMCHK-LB-005 | `is_incomplete_date` |

---

### MH Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 73 | `check_mh_missing_month` | MH | ✅ | SDTMCHK-MH-001 | `is_incomplete_date` |

---

### MI Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 74 | `check_mi_mispec` | MI | ✅ | SDTMCHK-MI-001 | MISPEC missing |

---

### OE Domain Checks (Ophthalmology)

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 75 | `check_oe_bcva_1m_late_early_tot` | OE | 🟡 | — | OPHTH: BCVA arithmetic scoring |
| 76 | `check_oe_bcva_4m_late_early_tot` | OE | 🟡 | — | OPHTH: BCVA arithmetic scoring |
| 77 | `check_oe_bcva_4m_vs_1m_req` | OE | 🟡 | — | OPHTH: BCVA 4m vs 1m requirement |
| 78 | `check_oe_bcva_tot_mismatch` | OE | 🟡 | — | OPHTH: BCVA total mismatch |
| 79 | `check_oe_sc_lat_count_fingers` | OE, SC | 🟡 | — | OPHTH: laterality mismatch |

---

### PR Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 80 | `check_pr_missing_month` | PR | ✅ | SDTMCHK-PR-001 | `is_incomplete_date` |
| 81 | `check_pr_prlat` | PR | 🟡 | — | OPHTH: ocular procedure laterality |

---

### QS Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 82 | `check_qs_qsstat_qsreasnd` | QS | ✅ | SDTMCHK-QS-001 | NOT DONE without reason |
| 83 | `check_qs_qsstat_qsstresc` | QS | ✅ | SDTMCHK-QS-005 | NOT DONE but responses populated |
| 84 | `check_qs_dup` | QS | ✅ | SDTMCHK-QS-004 | `is_not_unique_set` |
| 85 | `check_qs_qsdtc_after_dd` | AE, DS, QS | ✅ | SDTMCHK-QS-003 | `Operations: max_date` + `date_greater_than` |
| 86 | `check_qs_qsdtc_visit_ordinal_error` | QS | ✅ | SDTMCHK-QS-002 | `target_is_not_sorted_by` |

---

### RS Domain Checks (Oncology)

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 87 | `check_rs_rscat_rsscat` | RS | ✅ | SDTMCHK-RS-001 | RSSCAT without RSCAT |
| 88 | `check_rs_rsdtc_visit` | RS | ✅ | SDTMCHK-RS-004 | INV assessment missing date/visit |
| 89 | `check_rs_rsdtc_across_visit` | RS | ✅ | SDTMCHK-RS-003 | `is_inconsistent_across_dataset` |
| 90 | `check_rs_rsdtc_visit_ordinal_error` | RS | ✅ | SDTMCHK-RS-002 | `target_is_not_sorted_by` |

---

### SC Domain Checks (Ophthalmology)

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 91 | `check_sc_dm_eligcrit` | DM, SC | 🟡 | — | OPHTH: eye eligibility |
| 92 | `check_sc_dm_seyeselc` | DM, SC | 🟡 | — | OPHTH: study eye selection |

---

### SS Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 93 | `check_ss_ssstat_ssorres` | SS | ✅ | SDTMCHK-SS-001 | NOT DONE but SSORRES populated |
| 94 | `check_ss_ssdtc_alive_dm` | SS, DM | ✅ | SDTMCHK-SS-002 | `Operations: max_date` + `date_greater_than` |
| 95 | `check_ss_ssdtc_dead_ds` | SS, DS | ✅ | SDTMCHK-SS-004 | `Operations: distinct` + `is_not_contained_by` |
| 96 | `check_ss_ssdtc_dead_dthdtc` | SS, DM | ✅ | SDTMCHK-SS-003 | `Operations: max_date` + `date_not_equal_to` |

---

### TR Domain Checks (Oncology)

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 97 | `check_tr_trstresn_ldiam` | TR | ✅ | SDTMCHK-TR-001 | LDIAM missing TRSTRESN |
| 98 | `check_tr_dup` | TR | ✅ | SDTMCHK-TR-003 | `is_not_unique_set` |
| 99 | `check_tr_trdtc_across_visit` | TR | ✅ | SDTMCHK-TR-004 | `is_inconsistent_across_dataset` |
| 100 | `check_tr_trdtc_visit_ordinal_error` | TR | ✅ | SDTMCHK-TR-002 | `target_is_not_sorted_by` |

---

### TS Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 101 | `check_ts_aedict` | TS | ⚠️ | — | External dictionary version; requires MedDRA cache config |
| 102 | `check_ts_cmdict` | TS | ⚠️ | — | External dictionary version; requires WHODrug cache config |
| 103 | `check_ts_sstdtc_ds_consent` | TS, DS | ⚠️ | — | TS parameter extraction + date compare; complex TS structure |

---

### TU Domain Checks (Oncology)

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 104 | `check_tu_tudtc` | TU | ✅ | SDTMCHK-TU-001 | TUDTC missing |
| 105 | `check_tu_tuloc_missing` | TU | ✅ | SDTMCHK-TU-002 | TULOC missing |
| 106 | `check_tu_rs_new_lesions` | TU, RS | ⚠️ | — | Complex cross-domain: new TU lesion without PD in RS |
| 107 | `check_tu_tudtc_across_visit` | TU | ✅ | SDTMCHK-TU-004 | `is_inconsistent_across_dataset` |
| 108 | `check_tu_tudtc_visit_ordinal_error` | TU | ✅ | SDTMCHK-TU-003 | `target_is_not_sorted_by` |

---

### VS Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 109 | `check_vs_sbp_lt_dbp` | VS | ✅ | SDTMCHK-VS-001 | DBP > SBP |
| 110 | `check_vs_height` | VS, DM | ✅ | SDTMCHK-VS-003 | `Operations: distinct` + `is_not_contained_by` |
| 111 | `check_vs_vsdtc_after_dd` | AE, DS, VS | ✅ | SDTMCHK-VS-002 | `Operations: max_date` + `date_greater_than` |

---

## Part 3: Why Some Checks Remain Not Expressible

### Truly not expressible (⚠️ — 8 remaining)

| Check | Reason |
|-------|--------|
| `check_dm_usubjid_ae_usubjid` | Requires 4-domain merge + conditional row exclusion logic |
| `check_ds_sc_strat` | SC stratification factor extraction + randomization conditional |
| `check_ts_aedict` | Requires external MedDRA dictionary cache + TS parameter parsing |
| `check_ts_cmdict` | Requires external WHODrug dictionary cache + TS parameter parsing |
| `check_ts_sstdtc_ds_consent` | TS single-value extraction (TSPARMCD=SSTDTC) + DS date compare |
| `check_tu_rs_new_lesions` | Cross-domain: new TU TULINKID not matching any RS with RSSTRESC=PD |
| BCVA scoring (x4) | Arithmetic sums across multiple OE rows — beyond DSL capabilities |

### Resolution paths for remaining checks

1. **External dictionary checks (TS):** Could be implemented if MedDRA/WHODrug
   dictionaries are loaded in the engine cache. The engine supports
   `valid_external_dictionary_value` operations but requires runtime configuration.

2. **Multi-domain conditional (DM → AE/DS/EX):** Would require multiple
   Operations blocks with complex filter combinations. May be feasible with
   Match Datasets in future engine versions.

3. **TU→RS new lesion logic:** Requires conditional matching on TULINKID across
   domains with specific response criteria. Candidate for Python plugin.

4. **BCVA arithmetic:** Requires row-level summation and comparison of computed
   totals. No arithmetic operators exist in the YAML DSL.

---

## Part 4: File Listing

All 53 translated rules + this tracker in `metadata/custom_rules/`:

```
SDTMCHK-AE-001.yaml   # AEDECOD missing
SDTMCHK-AE-002.yaml   # AEDTHDTC present, AESDTH≠Y
SDTMCHK-AE-003.yaml   # AESDTH=Y, AEDTHDTC missing
SDTMCHK-AE-004.yaml   # AEDTHDTC present, AEOUT≠FATAL
SDTMCHK-AE-005.yaml   # AEOUT=FATAL, AEDTHDTC missing
SDTMCHK-AE-006.yaml   # Grade 5 death inconsistency
SDTMCHK-AE-007.yaml   # AEOUT=FATAL inconsistency
SDTMCHK-AE-008.yaml   # Resolved AE, AEENDTC missing
SDTMCHK-AE-009.yaml   # NOT RECOVERED, AEENDTC populated
SDTMCHK-AE-010.yaml   # FATAL: AEENDTC≠AEDTHDTC
SDTMCHK-AE-011.yaml   # AETOXGR and AESEV both missing
SDTMCHK-AE-012.yaml   # Eye AE laterality missing
SDTMCHK-AE-013.yaml   # AE date after death (cross-domain DS)
SDTMCHK-AE-014.yaml   # Duplicate AE records
SDTMCHK-AE-015.yaml   # DS death but no AEDTHDTC
SDTMCHK-AE-016.yaml   # AEDTHDTC ≠ DS death date
SDTMCHK-AE-017.yaml   # Partial AEDTHDTC (incomplete date)
SDTMCHK-AE-018.yaml   # DRUG WITHDRAWN without DS treatment discon
SDTMCHK-AE-019.yaml   # AEOUT=FATAL without DS death record
SDTMCHK-AE-020.yaml   # AEACNOTH mentions discontinuation, no DS
SDTMCHK-AE-021.yaml   # AEREL unexpected value
SDTMCHK-AE-022.yaml   # AEACNOTH=MULTIPLE, AEACNOT1 missing
SDTMCHK-CE-001.yaml   # Incomplete CE date
SDTMCHK-CM-001.yaml   # CMDECOD missing
SDTMCHK-CM-002.yaml   # Incomplete CM dates
SDTMCHK-DM-001.yaml   # AGE missing
SDTMCHK-DM-002.yaml   # ARM≠ACTARM
SDTMCHK-DM-003.yaml   # DTHFL=Y, no DS death record
SDTMCHK-DS-001.yaml   # Death without date in DS
SDTMCHK-DS-002.yaml   # Blank death cause
SDTMCHK-DS-003.yaml   # Duplicate randomization
SDTMCHK-DS-004.yaml   # Multiple death dates inconsistent
SDTMCHK-DS-005.yaml   # EX after treatment discontinuation
SDTMCHK-DS-006.yaml   # Death without study discon record
SDTMCHK-DS-007.yaml   # Trt discon due to AE, no matching AE
SDTMCHK-EG-001.yaml   # EG visit date ordering
SDTMCHK-EX-001.yaml   # EXDOSE missing when occurred
SDTMCHK-EX-002.yaml   # EXDOSE>0 but EXOCCUR≠Y
SDTMCHK-EX-003.yaml   # EXDOSU missing
SDTMCHK-EX-004.yaml   # EXTRT missing
SDTMCHK-EX-005.yaml   # VISIT missing
SDTMCHK-EX-006.yaml   # EXOCCUR missing, EXDOSE present
SDTMCHK-EX-007.yaml   # Duplicate EX records
SDTMCHK-EX-008.yaml   # EX date after death
SDTMCHK-EX-009.yaml   # EX visit date ordering
SDTMCHK-EX-010.yaml   # IV infusion same start/end time
SDTMCHK-EX-011.yaml   # EXOCCUR=N but dose/date present
SDTMCHK-LB-001.yaml   # LBORRES present, standardized missing
SDTMCHK-LB-002.yaml   # Lab units missing
SDTMCHK-LB-003.yaml   # < or > prefix in lab results
SDTMCHK-LB-004.yaml   # LB visit date ordering
SDTMCHK-LB-005.yaml   # Incomplete LB date
SDTMCHK-LB-006.yaml   # LB date after death
SDTMCHK-LB-007.yaml   # Reference ranges missing
SDTMCHK-MH-001.yaml   # Incomplete MH dates
SDTMCHK-MI-001.yaml   # MISPEC missing
SDTMCHK-PR-001.yaml   # Incomplete PR dates
SDTMCHK-QS-001.yaml   # NOT DONE without reason
SDTMCHK-QS-002.yaml   # QS visit date ordering
SDTMCHK-QS-003.yaml   # QS date after death
SDTMCHK-QS-004.yaml   # Duplicate QS records
SDTMCHK-QS-005.yaml   # NOT DONE but responses populated
SDTMCHK-RS-001.yaml   # RSSCAT without RSCAT
SDTMCHK-RS-002.yaml   # RS visit date ordering
SDTMCHK-RS-003.yaml   # Same RS date across visits
SDTMCHK-RS-004.yaml   # INV assessment missing date/visit
SDTMCHK-SS-001.yaml   # NOT DONE but SSORRES populated
SDTMCHK-SS-002.yaml   # ALIVE date after DM death date
SDTMCHK-SS-003.yaml   # DEAD date ≠ DM death date
SDTMCHK-SS-004.yaml   # DEAD without DS death record
SDTMCHK-TR-001.yaml   # LDIAM missing TRSTRESN
SDTMCHK-TR-002.yaml   # TR visit date ordering
SDTMCHK-TR-003.yaml   # Duplicate TR records
SDTMCHK-TR-004.yaml   # Same TR date across visits
SDTMCHK-TU-001.yaml   # TUDTC missing
SDTMCHK-TU-002.yaml   # TULOC missing
SDTMCHK-TU-003.yaml   # TU visit date ordering
SDTMCHK-TU-004.yaml   # Same TU date across visits
SDTMCHK-VS-001.yaml   # DBP > SBP
SDTMCHK-VS-002.yaml   # VS date after death
SDTMCHK-VS-003.yaml   # Height measurement missing
```

---

## Part 5: Engine Mechanism Usage Summary

| Engine Mechanism | Rules Using It | Example |
|------------------|---------------|---------|
| Simple `empty`/`non_empty` | 12 | SDTMCHK-AE-001 |
| `equal_to` + `not_equal_to` | 14 | SDTMCHK-AE-002 |
| `is_not_contained_by` (value list) | 1 | SDTMCHK-AE-021 |
| `is_incomplete_date` | 7 | SDTMCHK-CE-001 |
| `is_not_unique_set` | 5 | SDTMCHK-AE-014 |
| `present_on_multiple_rows_within` | 1 | SDTMCHK-DS-003 |
| `is_inconsistent_across_dataset` | 4 | SDTMCHK-DS-004 |
| `target_is_not_sorted_by` | 8 | SDTMCHK-EG-001 |
| `Operations: max_date` + date compare | 9 | SDTMCHK-AE-013 |
| `Operations: distinct` + existence | 8 | SDTMCHK-DM-003 |
| `date_equal_to` / `date_not_equal_to` | 3 | SDTMCHK-AE-016 |
| `contains_case_insensitive` | 1 | SDTMCHK-AE-020 |
| Mixed multi-condition (`any`/`all`) | 5 | SDTMCHK-CM-002 |
