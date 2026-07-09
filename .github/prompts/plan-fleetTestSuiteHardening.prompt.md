> **Status (2026-07): implemented; the factory/CSV-fixture approach herein was later superseded by inline `pl.from_repr` — see `.github/instructions/tests.instructions.md`.**

## Plan: Harden Fleet Test Suite

Raise defect detection by making the suite resemble messy clinical reality instead of idealized toy data. Start with shared fixtures and assertion discipline, then harden each test cluster against CDISC-relevant edge cases: partial dates, duplicate keys, denominator drift, sparse strata, terminology drift, null propagation, join cardinality, and audit-trail fidelity. Keep production code out of scope unless stronger tests expose a real defect.

**Steps**

0. Phase 0: create a new branch for this work, do not commit or push any code.
1. Phase 1: Establish realistic shared test data foundations in /Users/aboutm/Code/Python/Fleet/tests/conftest.py and new helper fixtures under /Users/aboutm/Code/Python/Fleet/tests/fixtures/ or a new test factory module. Add reusable cohorts for partial dates, unscheduled visits, duplicate keys, mixed terminology, sparse treatment arms, merge mismatches, and tied ordering scenarios. This step blocks most later steps.
2. Phase 2: Refactor assertion style in cross-cutting tests to reduce false confidence. Replace brittle exact-row-order assertions with semantic checks on grouping, flags, counts, null propagation, determinism, and cardinality. This can begin after Phase 1 fixtures exist and then proceed in parallel with Phases 3 to 6.
3. Phase 3: Harden SDTM, CT, and spec-driven tests in /Users/aboutm/Code/Python/Fleet/tests/unit/test_sdtm_namespace.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_ct_validation.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_tdd_workflow.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_define_xml.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_from_spec_callable.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_nsv.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_derivation_protocol.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_hardening.py, and /Users/aboutm/Code/Python/Fleet/tests/unit/test_flag_criterion.py. Add cases for CT casing and whitespace drift, codelist mismatch behavior, malformed codelist classes, missing CT files, partial and malformed DTC values, stage-order violations, NSV multi-domain behavior, incomplete spec metadata, and tie or null behavior in flagging.
4. Phase 4: Harden core ADaM derivation tests in /Users/aboutm/Code/Python/Fleet/tests/unit/test_adam_namespace.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_adsl_namespace.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_occds_namespace.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_pk_namespace.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_shared_verbs_mixin.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_date_api.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_date_derivation.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_duration_api.py, and /Users/aboutm/Code/Python/Fleet/tests/unit/test_derivation_polymorphic.py. Focus on baseline ties, null baseline with flagged records, negative and same-day study day boundaries, partial date interaction with ADaM logic, TRTSDT or TRTEDT missingness, duration sign preservation, join cardinality explosions, sequence determinism under ties, and row-order invariance.
5. Phase 5: Harden therapeutic-area and parity tests in /Users/aboutm/Code/Python/Fleet/tests/unit/test_onco_namespace.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_neuro_namespace.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_ophtha_namespace.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_peds_namespace.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_vaccine_namespace.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_metabolic_namespace.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_grading.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_transform.py, and /Users/aboutm/Code/Python/Fleet/tests/unit/test_admiral_parity.py. Add domain-realistic cases for oncology progression timing ambiguity, neurology composite-score missing-item rules, ophthalmology laterality and extreme acuity values, pediatric leap-year and gestational-age boundaries, vaccine LLOQ or ULOQ parsing and zero-baseline handling, metabolic sex-coding and unit assumptions, grading threshold precision, and derivation-kind misuse in transform registration.
6. Phase 6: Harden TLG, lineage, metadata, and validator coverage in /Users/aboutm/Code/Python/Fleet/tests/unit/test_tlg_namespace.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_tlg_render.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_dataset_json.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_crf_pages.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_pin_lineage.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_pin_adam.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_pin_sdtm.py, /Users/aboutm/Code/Python/Fleet/tests/unit/test_pin_mixin.py, and /Users/aboutm/Code/Python/Fleet/test_custom_rule.py. Add sparse-arm and zero-count strata cases, denominator consistency checks under safety or efficacy population filters, deterministic render ordering, dataset-json type round-trip checks, CRF page deduplication, lineage loss through manual joins or filters, and custom-rule negative cases beyond the single pass or fail engine smoke test.
7. Phase 7: Add targeted coverage for duplicate and dedup behavior in /Users/aboutm/Code/Python/Fleet/tests/unit/test_nodup.py using realistic duplicate patterns: adjacent duplicates, same subject same visit duplicate records, mixed scheduled and unscheduled duplicates, and multi-key ties that mirror real EDC correction flows. This can run in parallel with Phases 4 to 6 once shared fixtures are ready.
8. Phase 8: Add a thin layer of higher-order robustness checks after the explicit examples are in place. Prefer small parameterized order-invariance tests and a limited set of generated-data tests for durations, sorting, and group flags. Keep this last so the suite does not become harder to debug before core examples are improved.
9. Phase 9: Run verification iteratively by cluster while developing, then run the full suite and record uncovered production defects separately from the test-improvement work. If stronger tests fail because implementation is wrong, open a follow-on implementation batch rather than diluting the test-hardening task.

**Relevant files**

- /Users/aboutm/Code/Python/Fleet/tests/conftest.py — central fixture entry point; best place to replace toy fixtures with richer reusable cohorts.
- /Users/aboutm/Code/Python/Fleet/tests/fixtures/raw/dm_raw.csv — realistic raw DM source already available for broader reuse.
- /Users/aboutm/Code/Python/Fleet/tests/fixtures/raw/vs_raw.csv — realistic VS source for partial-date, visit-window, and unit tests.
- /Users/aboutm/Code/Python/Fleet/tests/fixtures/raw/ae_raw.csv — realistic AE source for treatment-emergent, sequencing, and duplicate tests.
- /Users/aboutm/Code/Python/Fleet/tests/fixtures/specs/define_sdtm.yaml — spec-driven SDTM metadata fixture; useful for missing or malformed spec scenarios.
- /Users/aboutm/Code/Python/Fleet/tests/fixtures/specs/define_adam.yaml — spec-driven ADaM metadata fixture; useful for algorithm and metadata drift cases.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_sdtm_namespace.py — currently too narrow around assign_ct and date happy paths.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_ct_validation.py — needs stronger CT drift, casing, whitespace, missing-file, and malformed-codelist coverage.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_date_derivation.py — already strong for imputation; should become the reusable partial-date reference for other clusters.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_adam_namespace.py — primary location for baseline, change, treatment window, and null-propagation edge cases.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_adsl_namespace.py — best place for subject-level cardinality, first or last date, and duration boundary realism.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_occds_namespace.py — needs treatment-emergent and sequencing ambiguity tests.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_pk_namespace.py — join cardinality and BLQ edge cases.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_onco_namespace.py — needs progression ambiguity and post-PD behavior coverage.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_neuro_namespace.py — needs composite-score missing-item-rule coverage.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_ophtha_namespace.py — laterality, bilateral, mixed-case, and extreme acuity cases.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_peds_namespace.py — leap-year and gestational-age thresholds.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_vaccine_namespace.py — LLOQ or ULOQ parsing, whitespace, and zero-baseline behavior.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_metabolic_namespace.py — sex-coding and unit-assumption realism.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_grading.py — significant-figure and threshold-boundary behavior.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_transform.py — derivation-kind misuse and registry robustness.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_admiral_parity.py — extreme-value parity cases for BSA, QTc, and similar functions.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_tlg_namespace.py — denominator integrity and sparse-arm behavior.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_tlg_render.py — deterministic ordering and sparse display formatting.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_dataset_json.py — type, label, length, and date round-trip fidelity.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_crf_pages.py — duplicate and overlapping page reference coverage.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_pin_lineage.py — audit-trail gaps after manual joins or filters.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_pin_adam.py — pinned reference-domain integrity in ADaM workflows.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_pin_sdtm.py — pinned FK and study-day behavior under messy source data.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_pin_mixin.py — duplicate pin, repin, and lifecycle assertions.
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_nodup.py — realistic duplicate-key scenarios are still underrepresented.
- /Users/aboutm/Code/Python/Fleet/test_custom_rule.py — current validation is mostly a smoke path; needs stronger failure-mode expectations.

**Verification**

1. For each phase, run only the touched test cluster first so failures stay attributable to the new scenarios.
2. After each cluster is stable, run the full Fleet test suite with uv run pytest.
3. If only test files and fixtures changed, stop at the suite unless the new tests expose a product defect; if product code must then change, follow the repository verification order for those fixes: uv run ruff check, uv run pytest, then the documented example scripts.
4. Specifically verify that new tests are order-invariant where intended by running the same assertions against reordered inputs in the relevant files.
5. Track any newly exposed implementation defects separately from the test-hardening tasks so the plan remains focused on robustness and fidelity rather than broad code changes.

**Decisions**

- Included scope: stronger fixtures, more realistic synthetic data, tighter assertions, broader edge-case coverage, and clearer separation between test hardening and product bug fixes.
- Excluded scope: changing Fleet production semantics up front, adding very large end-to-end datasets, or introducing wide property-based testing before core explicit cases are in place.
- Recommended sequencing: fixture foundation first, then domain clusters in parallel, then higher-order generated-data checks last.
- Recommended default mindset for new tests: prefer clinically plausible messy inputs over mathematically convenient toy frames, and assert on subject-level or group-level behavior rather than row position when order is not the behavior under test.

**Further Considerations**

1. Shared factory module versus expanding conftest.py: prefer a small dedicated test factory module once fixture count starts to obscure conftest.py; keep only broadly reused top-level fixtures in conftest.py.
2. Hypothesis or other generated-data testing: defer until the explicit clinical edge cases are encoded, then add a narrow layer only for invariants such as order invariance, sign symmetry, and one-flag-per-group behavior.
3. Real raw fixture reuse versus synthetic builders: prefer the existing raw CSV fixtures for realism, but wrap them in builders that can inject controlled missingness, duplicates, and terminology drift so tests stay readable and reproducible.
