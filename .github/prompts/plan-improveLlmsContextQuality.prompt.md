# Plan: Improve llms.txt LLM Context Quality

## TL;DR
Add the missing PK namespace, expand TA namespace verb listings to full signatures, surface `inspect()`/`explain()` debug verbs, add a namespace switching pattern section, add disambiguation notes for same-named verbs, register `df.adam.pk` in the namespaces registry, and include `adnca_example.py` as a fourth golden master. All changes go in `scripts/build_llms.py`; `llms.txt` is regenerated.

---

## Phase 1 — Missing namespace & golden master (highest signal)

**Step 1.** Add `def _pk_verbs_section() -> str` to `build_llms.py`.  
Content: full signature list for all 16 PK-specific verbs (blq_flag, blq_impute, nominal_time, actual_time, predose_flag, dose_normalized, evid, mrrlt, blqfn, log_conc, mdv, amt, cmt, avalcat, anl_flag) plus note that SharedADaMVerbsMixin verbs are also available.  
Pattern: mirror the existing `_occds_verbs_section()` style.

**Step 2.** Add `df.adam.pk` entry to `_namespaces_section()` in the TA extensions bullet list.  
Add: `- df.adam.pk — Pharmacokinetics: BLQ flags/imputation, nominal/actual time, EVID, MDV, AMT, CMT, dose normalisation, log concentration, analysis flags`

**Step 3.** Embed `adnca_example.py` as the fourth golden master in `_golden_master_section()`.  
Add `pk = _example("adnca_example.py")` and a `### PK/NCA pipeline` subsection. Depends on Steps 1+2 (conceptual, not code dependency).

**Step 4.** Add `_pk_verbs_section()` and update `_namespaces_section()` call in `build()`.

---

## Phase 2 — Expand all TA namespace verb listings (medium signal)

**Step 5.** Replace the one-liner bullet entries for each TA namespace in `_namespaces_section()` with dedicated sections (following the pattern of `_adsl_verbs_section()`):

- Add `def _onco_verbs_section() -> str`: `aval_resp`, `tumor_response_flag`, `best_overall_response`, `confirmed_response_flag`, `filter_pd`
- Add `def _ophtha_verbs_section() -> str`: `etdrs_to_logmar`, `logmar_to_etdrs`, `study_eye`, `affected_eye`, `bcva_criterion`
- Add `def _peds_verbs_section() -> str`: `age_days`, `age_months`, `age_years`, `corrected_age`, `prematurity_flag`, `bmi_category`
- Add `def _vaccine_verbs_section() -> str`: `fever_flag`, `seroconversion_flag`, `seroresponse_flag`, `aval_adis`, `event_flag`
- Add `def _metabolic_verbs_section() -> str`: `waist_hip_ratio`, `waist_height_ratio`, `body_fat_pct`, `visceral_fat_flag`
- Add `def _neuro_verbs_section() -> str`: `centiloid`, `mmse_category`, `cdrsob_total`, `moca_category`, `panss_total`

Each section: verb name + key parameter names + one-line description. Signatures from the Explore agent findings.

**Step 6.** Keep the TA one-liners in `_namespaces_section()` as a quick index (don't remove), but update them to be accurate tallies (e.g. "5 verbs" vs "3 verbs").

**Step 7.** Wire all new `_*_verbs_section()` functions into `build()` assembly.

---

## Phase 3 — Debug verbs + namespace-switching section (quality)

**Step 8.** Add `inspect()` and `explain()` to `_shared_adam_verbs_section()`.  
Lines to add:
- `inspect(prefix="DEBUG")` — materialise, print schema + shape + head rows, return fresh namespace (hard checkpoint). Use to isolate which step introduced bad data.
- `explain()` — print Polars query plan without materialising; returns self unchanged.

**Step 9.** Add a new `def _namespace_switching_section() -> str` section.  
Content: short explanation of why `.to_frame()` is needed to switch sub-namespaces, with a 10-line pattern example showing `df → .adam.adsl → .to_frame() → .adam → .to_frame() → .adam.adsl`. Also show the `inspect()` checkpoint pattern inline.

**Step 10.** Wire `_namespace_switching_section()` into `build()`, placed after `_quickstart_section()` and before `_golden_master_section()`.

---

## Phase 4 — Disambiguation of same-named verbs (polish)

**Step 11.** Add disambiguation notes to `_verb_mapping_table()` rows for:
- `study_day` — noted as existing in both `sdtm` (TDD subject-level) and `adam` BDS. Different signatures.
- `seq` — exists in `adam.occds`, `adam.pk`, and `SharedADaMVerbsMixin`. All identical behaviour.
- `age_years` — exists in both `adam.adsl` (unit-aware, from AGEU column) and `adam.peds` (computed from birth/analysis dates). Different inputs.

**Step 12.** Add a "Same-name disambiguation" note block to the verb mapping table header.

---

## Phase 5 — Regenerate and verify

**Step 13.** Run `uv run python scripts/build_llms.py` to regenerate `llms.txt`.

**Step 14.** Run `uv run python scripts/build_llms.py --check` to confirm no diff.

**Step 15.** Run `uv run ruff check && uv run ruff format --check` on `build_llms.py`.

---

## Relevant files
- `scripts/build_llms.py` — all changes go here (section functions + `build()` assembly)
- `llms.txt` — regenerated output; never edit by hand
- `examples/adnca_example.py` — embedded as golden master (read-only)
- `src/fleet/adam/pk_namespace.py` — source of truth for PK verb signatures
- `src/fleet/adam/{onco,ophtha,peds,vaccine,metabolic,neuro}_namespace.py` — TA verb signatures
- `src/fleet/adam/_mixins.py` — inspect/explain signatures

## Verification
1. `uv run python scripts/build_llms.py --check` exits 0
2. `uv run ruff check scripts/build_llms.py` — clean
3. Manually scan `llms.txt` for `df.adam.pk` namespace entry
4. Manually scan `llms.txt` for `blq_flag`, `nominal_time`, `actual_time`, `evid`
5. Manually scan `llms.txt` for `inspect()` in shared mixin section
6. Manually scan `llms.txt` for disambiguation note in verb mapping table

## Decisions
- Common mistakes section: intentionally left empty (per user request)
- `pip install` line: left as-is (acceptable for end-user consumption context)
- Full `adnca_example.py` is embedded (same pattern as other 3 golden masters)
- TA namespace one-liners in `_namespaces_section()` are kept as a quick-reference index but updated for accuracy
