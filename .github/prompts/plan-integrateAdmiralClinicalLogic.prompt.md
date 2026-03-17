## Plan: Expand Fleet to Reach Parity with Admiral

**TL;DR**
Fleet already possesses a robust pipeline architecture (via `SharedADaMVerbsMixin`) and a foundational set of computations (in `src/fleet/adam/utils.py`). We will close the feature gap with Admiral by creating pure functional additions in `utils.py` for missing core formulas (like `bsa`, `map`, extreme flags), and adding high-level semantic verbs to the relevant ADaM namespaces (BDS, ADSL) that generate new records or perform specialized assignments.

**Steps**

1. **Expand Core Computations (Phase 1)**
   - Target File: `src/fleet/adam/utils.py`
   - Implement missing standard vector/expression logic from Admiral.
   - _Additions:_ `bsa` (Body Surface Area), `map` (Mean Arterial Pressure), `qtc` (Corrected QT), and imputation-aware age/duration builders.
   - Ensure all output types are purely `pl.Expr` to snap into existing patterns.

2. **Add Record-Generating Verbs to BDS (Phase 2)**
   - Target File: `src/fleet/adam/namespace.py`
   - Fleet currently generates columns (`.bmi()`, `.nrind()`), but Admiral frequently appends new _records_ (e.g., LOCF, summary derivation rows).
   - _Additions:_
     - `.derive_summary_records()` (using Polars `group_by` and concatenating)
     - `.derive_locf_records()` (forward filling within bounded patient groups)
     - `.derive_param(...)` (helper to append a new calculated record, like BMI, to BDS structure rather than a horizontal column).

3. **Enhance ADSL Demographic Logic (Phase 3)**
   - Target File: `src/fleet/adam/adsl_namespace.py`
   - _Additions:_
     - `.age_years()` (handles strings with unit permutations vs just dates)
     - `.derive_period()` (creates standard Subperiod/Phase variables)

4. **Integrate Typings and Fleet Specs (Phase 4)**
   - Ensure all newly added verbs in `namespace.py`, `adsl_namespace.py`, etc., return `Self` for flawless IDE autocomplete.
   - Update `_std_function_dispatch` in `namespace.py` if new verbs need to be accessible from `define.yaml`.

**Relevant files**

- `src/fleet/adam/utils.py` — For the low-level Polars mathematical implementations.
- `src/fleet/adam/namespace.py` — For BDS row-appending verbs (LOCF, summary) and proxying utils expressions.
- `src/fleet/adam/adsl_namespace.py` — For demographic and timeline gap-filling.
- `src/fleet/adam/occds_namespace.py` — Adding `atc_class` lookup structures or `trtemfl` flags.

**Verification**

1. Write specific unit tests targeting the new `utils.py` equations validating against standard Admiral or manual calculation logic.
2. Ensure `derive_summary_records` test strictly validates `pl.concat()` operations handle mismatched schemas gracefully statically via Polars schema alignments correctly.
3. Validate `uv run ruff check` and formatting before submission.

**Decisions / Assumptions**

- _No API Breaking Changes:_ We will strictly build _alongside_ existing patterns. Existing verbs (`chg`, `flag`, `on_treatment`) remain untouched.
- _Strict Polars Lazy Execution:_ Row appending (like parameter definitions) requires `pl.concat` on dataframes. These will be implemented using Fleet's existing `self._materialise_then()` mechanism, to jump between lazy frames safely while generating records.
