# Plan: Add Rich Google-Style Docstrings with Few-Shot Examples

## Goal

Ensure every public user-facing verb in Fleet namespaces has a Google-style
docstring (Args / Returns / Examples sections) with copy-pasteable,
CDISC-compliant examples that AI agents can pattern-match.

## Scope (confirmed with user)

- Fill **gaps only** (TA namespaces already covered — not audited)
- **Public verbs only** (skip `_chain`, `_materialise_then`, `_extract_define_variables`, `_spec_columns`, `_std_function_dispatch`)
- `to_frame()` IS included (public terminal op used by all callers)
- **Google-style** format: Args / Returns / Examples sections

---

## Phase 1 — `src/fleet/sdtm/namespace.py`

### 1a. Add Examples to 12 verbs currently missing them

| Verb              | Current state       | CDISC example scenario                      |
| ----------------- | ------------------- | ------------------------------------------- |
| `assign_no_ct`    | 1-liner             | Copy `subject_id` → `USUBJID`               |
| `assign_ct`       | 3-line, no Examples | Map `sex` → `SEX` via C66731 sex codelist   |
| `assign_datetime` | 4-line, no Examples | Parse `ae_start_date` → `ASTDTC` (ISO 8601) |
| `hardcode_ct`     | 1-liner             | Set `STUDYID` to study identifier           |
| `hardcode_no_ct`  | 1-liner             | Hardcode `DOMAIN = "DM"`                    |
| `condition_add`   | 3-line              | Set `AEOUT` = "FATAL" where death flag      |
| `ae_aerel`        | unknown             | Default AE causality mapping                |
| `merge`           | unknown             | Merge suppdm_df on USUBJID                  |
| `remove_dup`      | unknown             | Dedup on ["USUBJID", "VISIT"]               |
| `dataset_level`   | unknown             | Hardcode `STUDYID = "CDISCPILOT01"`         |
| `notsubmitted`    | unknown             | Drop internal fields `_raw_id`              |
| `validate`        | brief               | Validate DM domain against SDTM 3.4         |

### 1b. Convert 6 existing `Example::` blocks → Google-style `Examples:`

| Verb                 | Line      |
| -------------------- | --------- |
| `derivation`         | 79        |
| `if_then_else`       | 221       |
| `group_by`           | 339       |
| `multiple_responses` | 390 / 420 |
| `from_spec`          | 420       |
| `select`             | 694       |

---

## Phase 2 — `src/fleet/adam/_mixins.py`

### 2a. Add Examples to 8 public verbs missing them

| Verb             | Class                  | CDISC example scenario                  |
| ---------------- | ---------------------- | --------------------------------------- |
| `to_frame`       | `SharedADaMVerbsMixin` | Close the pipeline and return DataFrame |
| `source`         | `SharedADaMVerbsMixin` | Copy `AEDECOD` → `ADECOD`               |
| `derivation`     | `SharedADaMVerbsMixin` | Compute `AVAL` from raw numeric col     |
| `assigned`       | `SharedADaMVerbsMixin` | Constant `PARAMCD = "SYSBP"`            |
| `recode`         | `SharedADaMVerbsMixin` | Map `SEXN` (1/2) → `SEX` (M/F)          |
| `rename`         | `SharedADaMVerbsMixin` | Rename `VSTEST` → `PARAM`               |
| `condderivation` | `SharedADaMVerbsMixin` | DTYPE: LOCF/WOCF branches               |
| `whereclauses`   | `SharedADaMVerbsMixin` | Subset to on-treatment records          |

### 2b. Convert 2 existing `Example::` blocks → Google-style `Examples:`

| Verb         | Line |
| ------------ | ---- |
| `merge_adsl` | 221  |
| `seq`        | 257  |

---

## Phase 3 — `src/fleet/adam/namespace.py`

Add Examples to 2 verbs missing them:

| Verb       | Line | CDISC example scenario                            |
| ---------- | ---- | ------------------------------------------------- |
| `lookup`   | 130  | Join paramcd lookup table (testcd → param/paramn) |
| `validate` | 1000 | Validate ADSL against ADaM 1.3 rules              |

---

## Docstring Template (Google-style)

```
"""One-sentence summary of what the verb does.

Longer description if needed (2-3 sentences max). Reference CDISC spec
where applicable (e.g., "Per CDISC ADaM 1.3, study day = ...").

Args:
    target: Name of the output column to create.
    source: Name of the input column (keyword-only).
    ...

Returns:
    Self: The namespace with *target* appended; call ``.to_frame()`` to
        materialise.

Examples:
    Copy the raw subject ID to USUBJID::

        dm = (
            raw_df.sdtm
            .assign_no_ct("USUBJID", source="subject_id")
            .to_frame()
        )
```

---

## Relevant Files

- `src/fleet/sdtm/namespace.py` — SDTMNamespace verb hub
- `src/fleet/adam/_mixins.py` — SharedADaMVerbsMixin + MultiRowMixin
- `src/fleet/adam/namespace.py` — AdamNamespace (general ADaM)

## Verification

1. `uv run pytest` — all 254 tests should still pass (docstring-only changes, no logic changes)
2. `uv run ruff check src/fleet/sdtm/namespace.py src/fleet/adam/_mixins.py src/fleet/adam/namespace.py` — no lint errors
3. Visual scan: every public verb should have `Examples:` in docstring

## Decisions

- Private helpers (`_chain`, `_materialise_then`, etc.) → excluded
- `to_frame` → included (user-facing terminal verb)
- TA-specific namespaces (adsl, occds, pk, onco, ophtha, peds, metabolic, neuro, vaccine) → NOT touched (already covered)
- utils.py standalone functions → NOT touched (not namespace verbs)
- Existing Example:: blocks → converted to Google-style as part of holistic upgrade
