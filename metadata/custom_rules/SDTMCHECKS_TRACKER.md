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
fleet validate ./data --custom-rules ./metadata/custom_rules/
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

This page keeps no typed totals: count the rows of the tables below. The
rule files are the reference (`ls metadata/custom_rules/SDTMCHK-*.yaml`).

**Fidelity** (c2-918). A rule follows the condition of its R function. When
the engine cannot express a part of it, the rule file states the difference
in `Description`. When the engine cannot express the check at all, the rule
was removed. `tests/unit/test_sdtmchecks_rules.py` runs every rule on one
frame the R function fails and one frame it passes.

---

### Legend

| Column | Description |
|--------|-------------|
| **Function** | R function name from sdtmchecks |
| **Domain(s)** | SDTM domain(s) involved |
| **Status** | ✅ Translated / 🔵 CORE covered / ⚠️ Not expressible / 🟡 Skipped / 🔄 Partial |
| **Rule ID** | Fleet custom rule ID or CORE ID |
| **Fidelity** | Same as R / Differs (the rule file states how) / Removed (the engine cannot express the R condition) |
| **Notes** | Coverage details and engine mechanism used |

---

### AE Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 1 | `check_ae_aedecod` | AE | ✅ | SDTMCHK-AE-001 | Same as R | `empty` operator |
| 2 | `check_ae_aedthdtc_aesdth` | AE | ✅ | SDTMCHK-AE-002 | Same as R | `non_empty` + `not_equal_to` |
| 3 | `check_ae_aesdth_aedthdtc` | AE | ✅ | SDTMCHK-AE-003 | Same as R | `equal_to` + `empty` |
| 4 | `check_ae_aeout` (part 1) | AE | ✅ | SDTMCHK-AE-004 | Same as R | AEDTHDTC present, AEOUT≠FATAL |
| 5 | `check_ae_aeout` (part 2) | AE | ✅ | SDTMCHK-AE-005 | Same as R | AEOUT=FATAL, AEDTHDTC missing |
| 6 | `check_ae_death` | AE | ✅ | SDTMCHK-AE-006 | Same as R | Grade 5 death inconsistency |
| 7 | `check_ae_fatal` | AE | ✅ | SDTMCHK-AE-007 | Differs (stated in the rule) | AEOUT is 'FATAL' but AEDTHDTC is missing, AESDTH is not 'Y', AETOXGR is not 5 or AESEV is not SEVERE. |
| 8 | `check_ae_aeout_aeendtc_nonfatal` (part 1) | AE | ✅ | SDTMCHK-AE-008 | Same as R | Resolved AE, AEENDTC missing |
| 9 | `check_ae_aeout_aeendtc_nonfatal` (part 2) | AE | ✅ | SDTMCHK-AE-009 | Same as R | AEOUT is UNKNOWN, NOT RECOVERED/NOT RESOLVED or RECOVERING/RESOLVING but AEENDTC is populated. |
| 10 | `check_ae_aeout_aeendtc_aedthdtc` | AE | ✅ | SDTMCHK-AE-010 | Same as R | AEOUT is 'FATAL' but AEENDTC is missing or does not equal AEDTHDTC. Query only if the team agrees (note of the R function). |
| 11 | `check_ae_aetoxgr` | AE | ✅ | SDTMCHK-AE-011 | Same as R | The severity or grade is missing: AETOXGR and AESEV are both missing, or the only one of them that the study has is missing. |
| 12 | `check_ae_aelat` | AE | ✅ | SDTMCHK-AE-012 | Same as R | AESOC is an eye disorder but AELAT is not LEFT, RIGHT or BILATERAL. |
| 13 | `check_ae_aestdtc_after_aeendtc` | AE | 🔵 | CORE-000718 | — | AESTDTC > AEENDTC |
| 14 | `check_ae_aerel` | AE | ✅ | SDTMCHK-AE-021 | Differs (stated in the rule) | AEREL is missing. |
| 15 | `check_ae_dup` | AE | ✅ | SDTMCHK-AE-014 | Differs (stated in the rule) | Duplicate AE record: USUBJID, AETERM, AEDECOD, AESTDTC, AEENDTC and AESEV are not unique. |
| 16 | `check_ae_aeacnoth` | AE | ✅ | SDTMCHK-AE-022 | Same as R | AEACNOTH is 'MULTIPLE' but AEACNOT1 or AEACNOT2 is missing. |
| 17 | `check_ae_aestdtc_after_dd` | AE, DS | ✅ | SDTMCHK-AE-013 | Differs (stated in the rule) | AESTDTC is after the death date (DM.DTHDTC). |
| 18 | `check_ae_aedthdtc_ds_death` | AE, DS | ✅ | SDTMCHK-AE-015 | Same as R | DS records a death due to an adverse event, but no AE record of the subject has AEDTHDTC. |
| 19 | `check_ae_death_ds_discon` | AE, DS | ⚠️ | — (was SDTMCHK-AE-019) | Removed | Removed (c2-918): R selects the study discontinuation record by partial DSSCAT text; an operation filter takes exact values only |
| 20 | `check_ae_ds_partial_death_dates` | AE | ✅ | SDTMCHK-AE-017 | Differs (stated in the rule) | AEDTHDTC is a partial date (fewer than 10 characters). |
| 21 | `check_ae_withdr_ds_discon` | AE, DS | ⚠️ | — (was SDTMCHK-AE-018) | Removed | Removed (c2-918): R needs a single-agent study (TS) and DS records selected by partial text; an operation filter takes exact values only |
| 22 | `check_ae_aeacn_ds_disctx_covid` | AE, DS | 🟡 | — | — | COVID-specific |
| 23 | `check_ae_aeacnoth_ds_disctx` | AE, DS | ⚠️ | — (was SDTMCHK-AE-020) | Removed | Removed (c2-918): R reads every AEACNOTx and selects DS records by partial DSSCAT text; an operation filter takes exact values only |
| 24 | `check_ae_aeacnoth_ds_stddisc_covid` | AE, DS | 🟡 | — | — | COVID-specific |
| — | `check_dd_ae_aedthdtc_ds_dsstdtc` | AE, DS | ✅ | SDTMCHK-AE-016 | Differs (stated in the rule) | AEDTHDTC equals none of the DS death dates (DSSTDTC where DSDECOD = 'DEATH'). |
| — | `check_dd_ae_aeout_aedthdtc` | AE | ✅ | SDTMCHK-AE-004/005 | Same as R | Covered by the custom rules AE-004 and AE-005, not by CORE |
| — | `check_dd_death_date` | AE, DS | 🔄 | SDTMCHK-AE-015 | Partial | DS records a death due to an adverse event, but no AE record of the subject has AEDTHDTC. |

---

### CE Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 25 | `check_ce_missing_month` | CE | ✅ | SDTMCHK-CE-001 | Same as R | A CE date (CESTDTC, CEENDTC or CEDTC) has a year and a day but no month (yyyy---dd). |

---

### CM Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 26 | `check_cm_cmdecod` | CM | ✅ | SDTMCHK-CM-001 | Same as R | `empty` operator |
| 27 | `check_cm_cmindc` | CM | 🟡 | — | — | OPHTH-specific |
| 28 | `check_cm_cmlat` | CM | 🟡 | — | — | OPHTH-specific |
| 29 | `check_cm_cmlat_prior_ocular` | CM | 🟡 | — | — | OPHTH-specific |
| 30 | `check_cm_missing_month` | CM | ✅ | SDTMCHK-CM-002 | Same as R | A CM date (CMSTDTC or CMENDTC) has a year and a day but no month (yyyy---dd). |

---

### DM Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 34 | `check_dm_actarm_arm` | DM | ✅ | SDTMCHK-DM-002 | Same as R | ARM does not equal ACTARM (a missing value counts as a value). |
| 35 | `check_dm_age_missing` | DM | ✅ | SDTMCHK-DM-001 | Same as R | AGE missing |
| 36 | `check_dm_armcd` | DM | 🔵 | CORE-000119 (partial) | — | ARM/ARMCD missing; CORE covers only part of the R check |
| 37 | `check_dm_dthfl_dthdtc` | DM | 🔵 | CORE-000007, CORE-000705 | — | DTHFL/DTHDTC consistency |
| 38 | `check_dm_usubjid_dup` | DM | 🔵 | CORE-000186, CORE-000351 | — | Duplicate SUBJID |
| 39 | `check_dm_ae_ds_death` | DM, AE, DS | ⚠️ | — (was SDTMCHK-DM-003) | Removed | Removed (c2-918): R looks for a death in four AE variables and in DS; an operation filter cannot select a non-missing AEDTHDTC |
| 40 | `check_dm_usubjid_ae_usubjid` | DM, AE, DS, EX | ⚠️ | — | — | Multi-domain merge + conditional logic beyond DSL |

---

### DS Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 41 | `check_ds_dsdecod_dsstdtc` | DS | ✅ | SDTMCHK-DS-001 | Same as R | The subject has a DEATH record in DS, and no DEATH record has DSSTDTC. |
| 42 | `check_ds_dsterm_death_due_to` | DS | ✅ | SDTMCHK-DS-002 | Same as R | Blank death cause |
| 43 | `check_ds_dsdecod_death` | DS | ⚠️ | — (was SDTMCHK-DS-006) | Removed | Removed (c2-918): R selects the study discontinuation record by partial DSSCAT text; an operation filter takes exact values only |
| 44 | `check_ds_dsscat` | DS | 🔵 | CORE-000213 (partial) | — | Multiple study discon; CORE covers only part of the R check |
| 45 | `check_ds_duplicate_randomization` | DS | ✅ | SDTMCHK-DS-003 | Differs (stated in the rule) | The subject has more than one randomization record (DSDECOD contains RANDOMIZ). |
| 46 | `check_ds_multdeath_dsstdtc` | DS | ✅ | SDTMCHK-DS-004 | Same as R | The subject has DEATH records in DS with more than one DSSTDTC. |
| 47 | `check_ds_ae_discon` | DS, AE | ✅ | SDTMCHK-DS-007 | Differs (stated in the rule) | Treatment discontinuation due to an adverse event (DSSPID contains DISCTX) but no AE record with AEACN = 'DRUG WITHDRAWN'. |
| 48 | `check_ds_ex_after_discon` | DS, EX | ⚠️ | — (was SDTMCHK-DS-005) | Removed | Removed (c2-918): R compares the study discontinuation date with the last valid dose; an operation filter cannot select those DS and EX records |
| 49 | `check_ds_sc_strat` | DS, SC | ⚠️ | — | — | Requires SC domain with specific stratification logic |

---

### DV Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 50 | `check_dv_ae_aedecod_covid` | AE, DV | 🟡 | — | — | COVID-specific |
| 51 | `check_dv_covid` | DV | 🟡 | — | — | COVID-specific |

---

### EC Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 52 | `check_ec_sc_lat` | EC, SC | 🟡 | — | — | OPHTH-specific |

---

### EG Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 53 | `check_eg_egdtc_visit_ordinal_error` | EG | ⚠️ | — (was SDTMCHK-EG-001) | Removed | Removed (c2-918): visit order: the engine sorts all records, so unscheduled and NOT DONE records cannot be left out as R does |

---

### EX Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 54 | `check_ex_exdose_exoccur` | EX | ✅ | SDTMCHK-EX-001 | Same as R | EXDOSE missing when occurred |
| 55 | `check_ex_exdose_pos_exoccur_no` | EX | ✅ | SDTMCHK-EX-002 | Same as R | EXDOSE>0 but EXOCCUR≠Y |
| 56 | `check_ex_exdosu` | EX | ✅ | SDTMCHK-EX-003 | Same as R | EXDOSU missing |
| 57 | `check_ex_extrt_exoccur` | EX | ✅ | SDTMCHK-EX-004 | Same as R | EXTRT missing |
| 58 | `check_ex_visit` | EX | ✅ | SDTMCHK-EX-005 | Same as R | VISIT missing |
| 59 | `check_ex_exoccur_mis_exdose_nonmis` | EX | ✅ | SDTMCHK-EX-006 | Same as R | EXOCCUR missing, EXDOSE present |
| 60 | `check_ex_exstdtc_after_exendtc` | EX | 🔵 | CORE-000718 | — | --STDTC > --ENDTC |
| 61 | `check_ex_dup` | EX | ✅ | SDTMCHK-EX-007 | Differs (stated in the rule) | Duplicate EX record: USUBJID, EXTRT, EXDOSE and EXSTDTC are not unique. |
| 62 | `check_ex_exoccur_exdose_exstdtc` | EX | ✅ | SDTMCHK-EX-011 | Same as R | A valid dose (EXOCCUR = 'Y' or no EXOCCUR) has no full EXSTDTC, no EXDOSE, or EXDOSE <= 0 for an active treatment. |
| 63 | `check_ex_exstdtc_after_dd` | AE, DS, EX | ✅ | SDTMCHK-EX-008 | Differs (stated in the rule) | EXSTDTC is after the death date (DM.DTHDTC). |
| 64 | `check_ex_exstdtc_visit_ordinal_error` | EX | ⚠️ | — (was SDTMCHK-EX-009) | Removed | Removed (c2-918): visit order: the engine sorts all records, so unscheduled records cannot be left out as R does |
| 65 | `check_ex_infusion_exstdtc_exendtc` | EX | ✅ | SDTMCHK-EX-010 | Same as R | IV infusion: a start or end date is missing, the start and end dates differ, or the start is after the end. |

---

### LB Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 66 | `check_lb_lbstresn_missing` | LB | ✅ | SDTMCHK-LB-001 | Same as R | LBORRES present, standardized missing |
| 67 | `check_lb_lbstresu` | LB | ✅ | SDTMCHK-LB-002 | Same as R | LBSTRESU is missing when LBORRES is populated (qualitative, NOT DONE, PH and SPGRAV results excluded). |
| 68 | `check_lb_lbstresc_char` | LB | ✅ | SDTMCHK-LB-003 | Same as R | LBSTRESC holds '<' or '>' followed by a number, and LBSTRESN is missing. |
| 69 | `check_lb_lbstnrlo_lbstnrhi` | LB | ✅ | SDTMCHK-LB-007 | Same as R | Reference range missing for numeric |
| 70 | `check_lb_lbdtc_after_dd` | AE, DS, LB | ✅ | SDTMCHK-LB-006 | Differs (stated in the rule) | LBDTC is after the death date (DM.DTHDTC) for a record with a result. |
| 71 | `check_lb_lbdtc_visit_ordinal_error` | LB | ⚠️ | — (was SDTMCHK-LB-004) | Removed | Removed (c2-918): visit order: the engine sorts all records, so unscheduled and NOT DONE records cannot be left out as R does |
| 72 | `check_lb_missing_month` | LB | ✅ | SDTMCHK-LB-005 | Same as R | LBDTC has a year and a day but no month (yyyy---dd). |

---

### MH Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 73 | `check_mh_missing_month` | MH | ✅ | SDTMCHK-MH-001 | Same as R | An MH date (MHSTDTC or MHENDTC) has a year and a day but no month (yyyy---dd). |

---

### MI Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 74 | `check_mi_mispec` | MI | ✅ | SDTMCHK-MI-001 | Same as R | MISPEC missing |

---

### OE Domain Checks (Ophthalmology)

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 75 | `check_oe_bcva_1m_late_early_tot` | OE | 🟡 | — | — | OPHTH: BCVA arithmetic scoring |
| 76 | `check_oe_bcva_4m_late_early_tot` | OE | 🟡 | — | — | OPHTH: BCVA arithmetic scoring |
| 77 | `check_oe_bcva_4m_vs_1m_req` | OE | 🟡 | — | — | OPHTH: BCVA 4m vs 1m requirement |
| 78 | `check_oe_bcva_tot_mismatch` | OE | 🟡 | — | — | OPHTH: BCVA total mismatch |
| 79 | `check_oe_sc_lat_count_fingers` | OE, SC | 🟡 | — | — | OPHTH: laterality mismatch |

---

### PR Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 80 | `check_pr_missing_month` | PR | ✅ | SDTMCHK-PR-001 | Same as R | A PR date (PRSTDTC or PRENDTC) has a year and a day but no month (yyyy---dd). |
| 81 | `check_pr_prlat` | PR | 🟡 | — | — | OPHTH: ocular procedure laterality |

---

### QS Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 82 | `check_qs_qsstat_qsreasnd` | QS | ✅ | SDTMCHK-QS-001 | Differs (stated in the rule) | QSSTAT is 'NOT DONE' (any case) but QSREASND is missing. |
| 83 | `check_qs_qsstat_qsstresc` | QS | ✅ | SDTMCHK-QS-005 | Same as R | The questionnaire is NOT DONE (QSTESTCD = 'QSALL') but QSSTRESC is populated at the same visit and date. |
| 84 | `check_qs_dup` | QS | ✅ | SDTMCHK-QS-004 | Same as R | The subject has more than one QSDTC at one visit of a questionnaire (QSCAT). |
| 85 | `check_qs_qsdtc_after_dd` | AE, DS, QS | ✅ | SDTMCHK-QS-003 | Differs (stated in the rule) | QSDTC is after the death date (DM.DTHDTC) for a record with a result. |
| 86 | `check_qs_qsdtc_visit_ordinal_error` | QS | ⚠️ | — (was SDTMCHK-QS-002) | Removed | Removed (c2-918): visit order: the engine sorts all records, so unscheduled records cannot be left out as R does |

---

### RS Domain Checks (Oncology)

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 87 | `check_rs_rscat_rsscat` | RS | ✅ | SDTMCHK-RS-001 | Same as R | RSSCAT without RSCAT |
| 88 | `check_rs_rsdtc_visit` | RS | ✅ | SDTMCHK-RS-004 | Differs (stated in the rule) | An investigator RS record with a result has no RSDTC or no VISIT. |
| 89 | `check_rs_rsdtc_across_visit` | RS | ✅ | SDTMCHK-RS-003 | Differs (stated in the rule) | The same RSDTC is at more than one visit (investigator records). |
| 90 | `check_rs_rsdtc_visit_ordinal_error` | RS | ⚠️ | — (was SDTMCHK-RS-002) | Removed | Removed (c2-918): visit order: the engine sorts all records, so unscheduled, NOT DONE and independent assessor records cannot be left out as R does |

---

### SC Domain Checks (Ophthalmology)

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 91 | `check_sc_dm_eligcrit` | DM, SC | 🟡 | — | — | OPHTH: eye eligibility |
| 92 | `check_sc_dm_seyeselc` | DM, SC | 🟡 | — | — | OPHTH: study eye selection |

---

### SS Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 93 | `check_ss_ssstat_ssorres` | SS | ✅ | SDTMCHK-SS-001 | Same as R | NOT DONE but SSORRES populated |
| 94 | `check_ss_ssdtc_alive_dm` | SS, DM | ✅ | SDTMCHK-SS-002 | Same as R | SSTESTCD is SURVSTAT and SSORRES is ALIVE, but SSDTC is after the death date (DM.DTHDTC). |
| 95 | `check_ss_ssdtc_dead_ds` | SS, DS | ✅ | SDTMCHK-SS-004 | Differs (stated in the rule) | SSSTRESC is DEAD but DS has no death disposition record (DSDECOD = 'DEATH', DSCAT = 'DISPOSITION EVENT'). |
| 96 | `check_ss_ssdtc_dead_dthdtc` | SS, DM | ✅ | SDTMCHK-SS-003 | Same as R | SSSTRESC is DEAD but SSDTC is before the death date (DM.DTHDTC). |

---

### TR Domain Checks (Oncology)

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 97 | `check_tr_trstresn_ldiam` | TR | ✅ | SDTMCHK-TR-001 | Same as R | Investigator LDIAM record with no TRSTRESN. |
| 98 | `check_tr_dup` | TR | ✅ | SDTMCHK-TR-003 | Differs (stated in the rule) | Duplicate investigator TR record: USUBJID, TRCAT, TRTESTCD, TRLINKID, TRSPID, TRDTC and TRSTRESC are not unique. |
| 99 | `check_tr_trdtc_across_visit` | TR | ✅ | SDTMCHK-TR-004 | Differs (stated in the rule) | The same TRDTC is at more than one visit (investigator LDIAM records). |
| 100 | `check_tr_trdtc_visit_ordinal_error` | TR | ⚠️ | — (was SDTMCHK-TR-002) | Removed | Removed (c2-918): visit order: the engine sorts all records, so unscheduled, NOT DONE and independent assessor records cannot be left out as R does |

---

### TS Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 101 | `check_ts_aedict` | TS | ⚠️ | — | — | External dictionary version; requires MedDRA cache config |
| 102 | `check_ts_cmdict` | TS | ⚠️ | — | — | External dictionary version; requires WHODrug cache config |
| 103 | `check_ts_sstdtc_ds_consent` | TS, DS | ⚠️ | — | — | TS parameter extraction + date compare; complex TS structure |

---

### TU Domain Checks (Oncology)

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 104 | `check_tu_tudtc` | TU | ✅ | SDTMCHK-TU-001 | Same as R | Investigator TU record with no TUDTC. |
| 105 | `check_tu_tuloc_missing` | TU | ✅ | SDTMCHK-TU-002 | Same as R | Investigator TARGET lesion (any case) with no TULOC. |
| 106 | `check_tu_rs_new_lesions` | TU, RS | ⚠️ | — | — | Complex cross-domain: new TU lesion without PD in RS |
| 107 | `check_tu_tudtc_across_visit` | TU | ✅ | SDTMCHK-TU-004 | Differs (stated in the rule) | The same TUDTC is at more than one visit (investigator records). |
| 108 | `check_tu_tudtc_visit_ordinal_error` | TU | ⚠️ | — (was SDTMCHK-TU-003) | Removed | Removed (c2-918): visit order: the engine sorts all records, so unscheduled and independent assessor records cannot be left out as R does |

---

### VS Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Fidelity | Notes |
|---|----------|-----------|--------|---------|----------|-------|
| 109 | `check_vs_sbp_lt_dbp` | VS | ⚠️ | — (was SDTMCHK-VS-001) | Removed | Removed (c2-918): R merges SYSBP and DIABP records by USUBJID, VISIT and VSSPID; the engine compares values within one record only |
| 110 | `check_vs_height` | VS, DM | ✅ | SDTMCHK-VS-003 | Differs (stated in the rule) | `Operations: distinct` + `is_not_contained_by` |
| 111 | `check_vs_vsdtc_after_dd` | AE, DS, VS | ✅ | SDTMCHK-VS-002 | Differs (stated in the rule) | VSDTC is after the death date (DM.DTHDTC) for a record with a result. |

---

## Part 3: Why Some Checks Remain Not Expressible

### Truly not expressible (⚠️)

| Check | Reason |
|-------|--------|
| `check_dm_usubjid_ae_usubjid` | Requires 4-domain merge + conditional row exclusion logic |
| `check_ds_sc_strat` | SC stratification factor extraction + randomization conditional |
| `check_ts_aedict` | Requires external MedDRA dictionary cache + TS parameter parsing |
| `check_ts_cmdict` | Requires external WHODrug dictionary cache + TS parameter parsing |
| `check_ts_sstdtc_ds_consent` | TS single-value extraction (TSPARMCD=SSTDTC) + DS date compare |
| `check_tu_rs_new_lesions` | Cross-domain: new TU TULINKID not matching any RS with RSSTRESC=PD |
| BCVA scoring (x4) | Arithmetic sums across multiple OE rows — beyond DSL capabilities |
| SDTMCHK-EG-001 (removed, c2-918) | visit order: the engine sorts all records, so unscheduled and NOT DONE records cannot be left out as R does |
| SDTMCHK-EX-009 (removed, c2-918) | visit order: the engine sorts all records, so unscheduled records cannot be left out as R does |
| SDTMCHK-LB-004 (removed, c2-918) | visit order: the engine sorts all records, so unscheduled and NOT DONE records cannot be left out as R does |
| SDTMCHK-QS-002 (removed, c2-918) | visit order: the engine sorts all records, so unscheduled records cannot be left out as R does |
| SDTMCHK-RS-002 (removed, c2-918) | visit order: the engine sorts all records, so unscheduled, NOT DONE and independent assessor records cannot be left out as R does |
| SDTMCHK-TR-002 (removed, c2-918) | visit order: the engine sorts all records, so unscheduled, NOT DONE and independent assessor records cannot be left out as R does |
| SDTMCHK-TU-003 (removed, c2-918) | visit order: the engine sorts all records, so unscheduled and independent assessor records cannot be left out as R does |
| SDTMCHK-DS-005 (removed, c2-918) | R compares the study discontinuation date with the last valid dose; an operation filter cannot select those DS and EX records |
| SDTMCHK-AE-018 (removed, c2-918) | R needs a single-agent study (TS) and DS records selected by partial text; an operation filter takes exact values only |
| SDTMCHK-AE-019 (removed, c2-918) | R selects the study discontinuation record by partial DSSCAT text; an operation filter takes exact values only |
| SDTMCHK-AE-020 (removed, c2-918) | R reads every AEACNOTx and selects DS records by partial DSSCAT text; an operation filter takes exact values only |
| SDTMCHK-DM-003 (removed, c2-918) | R looks for a death in four AE variables and in DS; an operation filter cannot select a non-missing AEDTHDTC |
| SDTMCHK-DS-006 (removed, c2-918) | R selects the study discontinuation record by partial DSSCAT text; an operation filter takes exact values only |
| SDTMCHK-VS-001 (removed, c2-918) | R merges SYSBP and DIABP records by USUBJID, VISIT and VSSPID; the engine compares values within one record only |

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

The rule files in `metadata/custom_rules/` (the 14 removed rules of c2-918 are not listed):

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
SDTMCHK-AE-021.yaml   # AEREL unexpected value
SDTMCHK-AE-022.yaml   # AEACNOTH=MULTIPLE, AEACNOT1 missing
SDTMCHK-CE-001.yaml   # Incomplete CE date
SDTMCHK-CM-001.yaml   # CMDECOD missing
SDTMCHK-CM-002.yaml   # Incomplete CM dates
SDTMCHK-DM-001.yaml   # AGE missing
SDTMCHK-DM-002.yaml   # ARM≠ACTARM
SDTMCHK-DS-001.yaml   # Death without date in DS
SDTMCHK-DS-002.yaml   # Blank death cause
SDTMCHK-DS-003.yaml   # Duplicate randomization
SDTMCHK-DS-004.yaml   # Multiple death dates inconsistent
SDTMCHK-DS-007.yaml   # Trt discon due to AE, no matching AE
SDTMCHK-EX-001.yaml   # EXDOSE missing when occurred
SDTMCHK-EX-002.yaml   # EXDOSE>0 but EXOCCUR≠Y
SDTMCHK-EX-003.yaml   # EXDOSU missing
SDTMCHK-EX-004.yaml   # EXTRT missing
SDTMCHK-EX-005.yaml   # VISIT missing
SDTMCHK-EX-006.yaml   # EXOCCUR missing, EXDOSE present
SDTMCHK-EX-007.yaml   # Duplicate EX records
SDTMCHK-EX-008.yaml   # EX date after death
SDTMCHK-EX-010.yaml   # IV infusion same start/end time
SDTMCHK-EX-011.yaml   # EXOCCUR=N but dose/date present
SDTMCHK-LB-001.yaml   # LBORRES present, standardized missing
SDTMCHK-LB-002.yaml   # Lab units missing
SDTMCHK-LB-003.yaml   # < or > prefix in lab results
SDTMCHK-LB-005.yaml   # Incomplete LB date
SDTMCHK-LB-006.yaml   # LB date after death
SDTMCHK-LB-007.yaml   # Reference ranges missing
SDTMCHK-MH-001.yaml   # Incomplete MH dates
SDTMCHK-MI-001.yaml   # MISPEC missing
SDTMCHK-PR-001.yaml   # Incomplete PR dates
SDTMCHK-QS-001.yaml   # NOT DONE without reason
SDTMCHK-QS-003.yaml   # QS date after death
SDTMCHK-QS-004.yaml   # Duplicate QS records
SDTMCHK-QS-005.yaml   # NOT DONE but responses populated
SDTMCHK-RS-001.yaml   # RSSCAT without RSCAT
SDTMCHK-RS-003.yaml   # Same RS date across visits
SDTMCHK-RS-004.yaml   # INV assessment missing date/visit
SDTMCHK-SS-001.yaml   # NOT DONE but SSORRES populated
SDTMCHK-SS-002.yaml   # ALIVE date after DM death date
SDTMCHK-SS-003.yaml   # DEAD date ≠ DM death date
SDTMCHK-SS-004.yaml   # DEAD without DS death record
SDTMCHK-TR-001.yaml   # LDIAM missing TRSTRESN
SDTMCHK-TR-003.yaml   # Duplicate TR records
SDTMCHK-TR-004.yaml   # Same TR date across visits
SDTMCHK-TU-001.yaml   # TUDTC missing
SDTMCHK-TU-002.yaml   # TULOC missing
SDTMCHK-TU-004.yaml   # Same TU date across visits
SDTMCHK-VS-002.yaml   # VS date after death
SDTMCHK-VS-003.yaml   # Height measurement missing
```

---

## Part 5: Engine Mechanisms Used

| Engine Mechanism | Example |
|------------------|---------|
| Simple `empty`/`non_empty` | SDTMCHK-AE-001 |
| `equal_to` + `not_equal_to` | SDTMCHK-AE-002 |
| `exists` / `not_exists` (a variable the study may not have) | SDTMCHK-AE-011 |
| `matches_regex` (`yyyy---dd`) | SDTMCHK-CM-002 |
| `is_not_unique_set` | SDTMCHK-AE-014 |
| `present_on_multiple_rows_within` | SDTMCHK-DS-003 |
| `is_inconsistent_across_dataset` | SDTMCHK-DS-004 |
| `Operations: max_date` on DM.DTHDTC + date compare | SDTMCHK-AE-013 |
| `Operations: max_date` grouped by a second key | SDTMCHK-DS-001 |
| `Operations: distinct` + existence | SDTMCHK-DS-007 |
| `Operations: record_count` with a filter | SDTMCHK-QS-005 |

An operation `filter` works for `distinct` and `record_count`. The engine
ignores it for `max_date` and `min_date`, so a rule cannot take the death date
from the DS records with DSDECOD = DEATH.
