# Plan: Deterministic `llms.txt` Generator Script

Replace hand-maintained `llms.txt` with a **script that generates it** (`scripts/build_llms.py`). Static sections (verb tables, rules) live in the script as Python strings. Dynamic sections (example scripts) are read from `examples/` at runtime. The file is never edited by hand again.

---

## Phase 1 — Create `scripts/build_llms.py`

1. Create `scripts/build_llms.py` with:
   - `_example(filename)` helper — reads from `examples/` and wraps it in a fenced `python` code block
   - One function per `llms.txt` section (e.g., `_rules_section()`, `_golden_master_section()`, `_verb_table_section()`, etc.)
   - `build() -> str` — assembles all sections in order, joined by `\n\n`
   - `main()` with `--output` (default `llms.txt`) and `--check` (exit 1 if stale) flags
   - `if __name__ == "__main__": main()`

2. Section order in generated file:
   - Header + description
   - **`## Rules for AI Agents`** ← NEW (Fleet-first verb priority rule, Polars-only rule, lazy execution rule)
   - `## Install`
   - `## Quickstart` (minimal inline snippet as-is from current `llms.txt`)
   - **`## Golden Master Examples`** ← NEW — two sub-sections reading from source:
     - `### Inline pipeline` → embeds full `examples/cdiscpilot01_inline.py`
     - `### Spec-driven pipeline` → embeds full `examples/cdiscpilot01_spec_driven.py`
   - `## Namespaces` (TA extensions prose — unchanged)
   - `## SDTM verbs` (all 14, already correct)
   - **`## Shared ADaM verbs (available on all sub-namespaces)`** ← NEW — from `SharedADaMVerbsMixin`: `source`, `derivation`, `assigned`, `recode`, `rename`, `condderivation`, `whereclauses`, `merge_adsl`
   - `## ADaM verbs` — updated to add `lookup`, `from_spec`, `assign_datetime`
   - `## ADSL verbs` — unchanged (already complete)
   - `## OCCDS verbs` — updated to add `worst_flag`, `treatment_emergent`, `onset_recovery`, `seq`
   - **`## Operation → Fleet Verb Mapping`** ← NEW — Markdown table (~30 rows)
   - `## define.yaml` (unchanged)
   - `## Controlled Terminology` (unchanged)
   - `## Documentation` (unchanged)

3. After writing the script, run it once to regenerate `llms.txt` from it as the new source of truth.

---

## Phase 2 — Update `GUIDE.md`

4. Add a `## Maintaining llms.txt` section (after the documentation build section) explaining:
   - File is **generated — never edit by hand**
   - `uv run python scripts/build_llms.py` to regenerate
   - `uv run python scripts/build_llms.py --check` for CI stale-check
   - Edit `scripts/build_llms.py` to change static content; edit `examples/*.py` for example code

---

## Phase 3 — Update `STRUCTURE.md`

5. Add `scripts/` folder entry to the repository layout tree and a brief description table entry for `build_llms.py`
6. Add a note under `llms.txt` in the layout that it is generated (do not edit by hand)

---

## Relevant files

- `scripts/build_llms.py` — new file to create (the generator)
- `llms.txt` — regenerated from the script (no manual edits after this)
- `examples/cdiscpilot01_inline.py` — embedded verbatim in Golden Master section
- `examples/cdiscpilot01_spec_driven.py` — embedded verbatim in Golden Master section
- `src/fleet/adam/_mixins.py` — source for Shared ADaM verbs list
- `src/fleet/adam/occds_namespace.py` — source for OCCDS verb completions
- `GUIDE.md` — add `## Maintaining llms.txt` section
- `STRUCTURE.md` — add `scripts/` to repo layout

---

## Verb Mapping Table Rows (for `## Operation → Fleet Verb Mapping`)

Markdown table with columns: **CDISC Operation | Fleet Verb | Namespace | Notes**

| CDISC Operation               | Fleet Verb               | Namespace              | Notes                                               |
| ----------------------------- | ------------------------ | ---------------------- | --------------------------------------------------- |
| Copy column                   | `assign_no_ct`           | `sdtm`                 | Direct 1:1 rename, no CT                            |
| Copy column                   | `source`                 | `adam` / all sub-ns    | Pass-through column                                 |
| Rename variable               | `rename`                 | `adam` / all sub-ns    | e.g. `VSDTC → ADT`                                  |
| Constant value                | `hardcode_no_ct`         | `sdtm`                 | Same literal for every row                          |
| Constant value                | `assigned`               | `adam` / all sub-ns    | Same literal for every row                          |
| CT recode                     | `assign_ct`              | `sdtm`                 | Decodes via codelist                                |
| CT recode                     | `recode`                 | `adam` / all sub-ns    | Map raw→decoded values                              |
| Multi-branch conditional      | `if_then_else`           | `sdtm`                 | List of `{condition, value}` branches               |
| Multi-branch conditional      | `condderivation`         | `adam` / all sub-ns    | Same pattern as `if_then_else`                      |
| Arbitrary expression          | `derivation`             | `sdtm` / `adam`        | Last resort — use a Fleet verb first                |
| ISO datetime parse            | `assign_datetime`        | `sdtm` / `adam`        | Normalises to `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS` |
| Study day (ADY)               | `study_day`              | `adam`                 | `ADY = ADT − RFSTDTC + 1` (signed)                  |
| Baseline flag (ABLFL)         | `flag`                   | `adam`                 | Per-group boolean flag                              |
| Baseline value (BASE)         | `baseline`               | `adam`                 | Carries AVAL at baseline row                        |
| Change from baseline (CHG)    | `chg`                    | `adam`                 | `CHG = AVAL − BASE`                                 |
| % change from baseline        | `pchg`                   | `adam`                 | `PCHG = (AVAL − BASE) / BASE × 100`                 |
| BMI                           | `bmi`                    | `adam`                 | `weight / (height/100)²`                            |
| BSA                           | `bsa`                    | `adam`                 | 4 methods: Mosteller, DuBois, Haycock, Gehan        |
| Mean arterial pressure (MAP)  | `map`                    | `adam`                 | `(SBP + 2×DBP) / 3`                                 |
| Corrected QT (QTc)            | `qtc`                    | `adam`                 | Fridericia or Bazett method                         |
| Normal range indicator        | `nrind`                  | `adam`                 | Returns `LOW / NORMAL / HIGH`                       |
| On-treatment flag             | `on_treatment`           | `adam`                 | `TRTSDT ≤ ADT ≤ TRTEDT`                             |
| Categorical shift             | `shift`                  | `adam`                 | `"BASELINE / POST-BASELINE"` string                 |
| LOCF imputation records       | `derive_locf_records`    | `adam`                 | Forward-fill within patient groups                  |
| Summary records               | `derive_summary_records` | `adam`                 | Aggregate and append summary rows                   |
| Derived parameter rows        | `derive_param`           | `adam`                 | New parameter rows from existing ones               |
| Join reference dataset        | `lookup`                 | `adam`                 | Left-join another DataFrame into lazy plan          |
| Merge ADSL columns            | `merge_adsl`             | `adam` / all sub-ns    | Join ADSL onto current dataset                      |
| Filter rows                   | `whereclauses`           | `adam` / all sub-ns    | Filter by expression (materialises first)           |
| Treatment dates (ADSL)        | `first_date`/`last_date` | `adam.adsl`            | Earliest/latest event date per subject              |
| Treatment duration (TRTDURD)  | `duration`               | `adam.adsl`            | Integer day count between two date columns          |
| Population flag (SAFFL, etc.) | `eligibility_flag`       | `adam.adsl`            | `"Y"` / null based on row condition                 |
| Event count (NUMAE, NUMSAE)   | `count_events`           | `adam.adsl`            | Integer event count per subject                     |
| Age conversion                | `age_years`              | `adam.adsl`            | Unit-aware: YEARS, MONTHS, WEEKS, DAYS              |
| Period variables              | `derive_period`          | `adam.adsl`            | APxxSDT, APxxEDT, TRTxxP                            |
| Sequence number (ASEQ)        | `seq`                    | `adam.occds`/`adam.pk` | Sequential 1-based record number per group          |
| Worst severity                | `worst_flag`             | `adam.occds`           | Worst value per group (custom ordering)             |
| Treatment-emergent flag       | `treatment_emergent`     | `adam.occds`           | TRTEMFL using TRTSDT/TRTEDT window                  |
| Onset/recovery dates          | `onset_recovery`         | `adam.occds`           | Onset and recovery date derivation                  |
| Run spec derivations          | `from_spec`              | `adam`                 | Execute all derivations defined in define.yaml      |

---

## Verification

1. `uv run python scripts/build_llms.py` runs without error
2. `diff` between script output and old `llms.txt` shows only the intended new content
3. `uv run python scripts/build_llms.py --check` exits 0 immediately after a fresh run
4. All three new sections (`Rules for AI Agents`, `Golden Master Examples`, `Operation → Fleet Verb Mapping`) appear in the generated file with correct content

---

## Decisions

- `scripts/` directory at repo root — standard Python project convention, no package registration needed
- Invocation is `uv run python scripts/build_llms.py` — no `pyproject.toml` script entry (it's a dev utility, not a user-facing CLI)
- `--check` flag enables CI enforcement without any extra tooling
- `llms.txt` stays at repo root (not moved); the script just overwrites it
- `mkdocs-llmstxt` plugin already in `docs` extras is left unchanged
- No `pyproject.toml` changes required
