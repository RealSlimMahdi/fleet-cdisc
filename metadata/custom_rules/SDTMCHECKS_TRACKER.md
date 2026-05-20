# sdtmchecks → Fleet Custom Rules: Translation Tracker

> **Source:** [Roche sdtmchecks R package](https://github.com/pharmaverse/sdtmchecks)
> **Target:** Fleet CDISC Rules Engine custom YAML rules
> **Branch:** `feat/sdtmchecks-custom-rules`
> **Date:** 2026-05-20

---

## Summary

| Status | Count |
|--------|-------|
| ✅ YAML translated | 28 |
| 🔵 Covered by CORE | 14 |
| ⚠️ Not expressible (cross-domain/cross-record) | 52 |
| 🟡 COVID/OPHTH-specific (skipped) | 15 |
| **Total functions** | **109** |

---

## Legend

| Column | Description |
|--------|-------------|
| **Function** | R function name from sdtmchecks |
| **Domain(s)** | SDTM domain(s) involved |
| **Status** | ✅ Translated / 🔵 CORE covered / ⚠️ Not expressible / 🟡 Skipped |
| **Rule ID** | Fleet custom rule ID (if translated) or CORE ID (if covered) |
| **Notes** | Coverage details, limitations, or reason for skipping |

---

## AE Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 1 | `check_ae_aedecod` | AE | ✅ | SDTMCHK-AE-001 | AEDECOD missing |
| 2 | `check_ae_aedthdtc_aesdth` | AE | ✅ | SDTMCHK-AE-002 | AEDTHDTC present but AESDTH≠Y |
| 3 | `check_ae_aesdth_aedthdtc` | AE | ✅ | SDTMCHK-AE-003 | AESDTH=Y but AEDTHDTC missing |
| 4 | `check_ae_aeout` (part 1) | AE | ✅ | SDTMCHK-AE-004 | AEDTHDTC present but AEOUT≠FATAL |
| 5 | `check_ae_aeout` (part 2) | AE | ✅ | SDTMCHK-AE-005 | AEOUT=FATAL but AEDTHDTC missing |
| 6 | `check_ae_death` | AE | ✅ | SDTMCHK-AE-006 | Grade 5 inconsistent death vars |
| 7 | `check_ae_fatal` | AE | ✅ | SDTMCHK-AE-007 | AEOUT=FATAL inconsistent with AESDTH/AEDTHDTC |
| 8 | `check_ae_aeout_aeendtc_nonfatal` (part 1) | AE | ✅ | SDTMCHK-AE-008 | Resolved AE but AEENDTC missing |
| 9 | `check_ae_aeout_aeendtc_nonfatal` (part 2) | AE | ✅ | SDTMCHK-AE-009 | NOT RECOVERED but AEENDTC populated |
| 10 | `check_ae_aeout_aeendtc_aedthdtc` | AE | ✅ | SDTMCHK-AE-010 | FATAL: AEENDTC≠AEDTHDTC |
| 11 | `check_ae_aetoxgr` | AE | ✅ | SDTMCHK-AE-011 | Both AETOXGR and AESEV missing |
| 12 | `check_ae_aelat` | AE | ✅ | SDTMCHK-AE-012 | Eye AE missing laterality |
| 13 | `check_ae_aestdtc_after_aeendtc` | AE | 🔵 | CORE-000717 | AESTDTC > AEENDTC |
| 14 | `check_ae_aerel` | AE | ⚠️ | — | Complex: checks AEREL1-N array + unexpected values; not single-condition |
| 15 | `check_ae_dup` | AE | ⚠️ | — | Duplicate detection (group-by n()>1); not expressible in record-level DSL |
| 16 | `check_ae_aeacnoth` | AE | ⚠️ | — | AEACNOTH=MULTIPLE but AEACNOT1/2 missing; multi-field complex |
| 17 | `check_ae_aestdtc_after_dd` | AE, DS | ⚠️ | — | Cross-domain: AE date > death date from DS |
| 18 | `check_ae_aedthdtc_ds_death` | AE, DS | ⚠️ | — | Cross-domain: DS death but no AEDTHDTC |
| 19 | `check_ae_death_ds_discon` | AE, DS | ⚠️ | — | Cross-domain: death in AE without DS discon |
| 20 | `check_ae_ds_partial_death_dates` | AE, DS | ⚠️ | — | Partial date detection (len<10); cross-domain |
| 21 | `check_ae_withdr_ds_discon` | AE, DS, TS | ⚠️ | — | Cross-domain: DRUG WITHDRAWN without DS record |
| 22 | `check_ae_aeacn_ds_disctx_covid` | AE, DS | 🟡 | — | COVID-specific |
| 23 | `check_ae_aeacnoth_ds_disctx` | AE, DS | ⚠️ | — | Cross-domain: study discon without DS record |
| 24 | `check_ae_aeacnoth_ds_stddisc_covid` | AE, DS | 🟡 | — | COVID-specific |

---

## CE Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 25 | `check_ce_missing_month` | CE | ⚠️ | — | Partial date pattern (yyyy---dd); regex possible but niche |

---

## CM Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 26 | `check_cm_cmdecod` | CM | ✅ | SDTMCHK-CM-001 | CMDECOD missing for concomitant meds |
| 27 | `check_cm_cmindc` | CM | 🟡 | — | OPHTH-specific (PROPHYL check) |
| 28 | `check_cm_cmlat` | CM | 🟡 | — | OPHTH-specific (ocular laterality) |
| 29 | `check_cm_cmlat_prior_ocular` | CM | 🟡 | — | OPHTH-specific |
| 30 | `check_cm_missing_month` | CM | ⚠️ | — | Partial date pattern; same as CE |

---

## Death Date Cross-Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 31 | `check_dd_ae_aedthdtc_ds_dsstdtc` | AE, DS | ⚠️ | — | Cross-domain: AEDTHDTC ≠ DS death date |
| 32 | `check_dd_ae_aeout_aedthdtc` | AE | 🔵 | SDTMCHK-AE-004/005 | Covered by our AE-004 and AE-005 rules |
| 33 | `check_dd_death_date` | AE, DS | ⚠️ | — | Cross-domain: AEDTHDTC without DS death record |

---

## DM Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 34 | `check_dm_actarm_arm` | DM | ✅ | SDTMCHK-DM-002 | ARM ≠ ACTARM |
| 35 | `check_dm_age_missing` | DM | ✅ | SDTMCHK-DM-001 | AGE missing/suspicious |
| 36 | `check_dm_armcd` | DM | 🔵 | CORE-000119 | ARM/ARMCD missing |
| 37 | `check_dm_dthfl_dthdtc` | DM | 🔵 | CORE-000006/007 | DTHFL/DTHDTC consistency |
| 38 | `check_dm_usubjid_dup` | DM | 🔵 | CORE-000186 | Duplicate SUBJID |
| 39 | `check_dm_ae_ds_death` | DM, AE, DS | ⚠️ | — | Cross-domain: DM death without AE/DS |
| 40 | `check_dm_usubjid_ae_usubjid` | DM, AE, DS, EX | ⚠️ | — | Cross-domain: DM patients without AE records |

---

## DS Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 41 | `check_ds_dsdecod_dsstdtc` | DS | ✅ | SDTMCHK-DS-001 | DEATH without death date |
| 42 | `check_ds_dsterm_death_due_to` | DS | ✅ | SDTMCHK-DS-002 | Blank cause of death |
| 43 | `check_ds_dsdecod_death` | DS | ⚠️ | — | Cross-record: death without study discon record |
| 44 | `check_ds_dsscat` | DS | 🔵 | CORE-000213 | Multiple study discon records |
| 45 | `check_ds_duplicate_randomization` | DS | ⚠️ | — | Cross-record: duplicate RANDOMIZ records |
| 46 | `check_ds_multdeath_dsstdtc` | DS | ⚠️ | — | Cross-record: multiple death dates mismatch |
| 47 | `check_ds_ae_discon` | DS, AE | ⚠️ | — | Cross-domain: trt discon due to AE without AE match |
| 48 | `check_ds_ex_after_discon` | DS, EX | ⚠️ | — | Cross-domain: EX after discon date |
| 49 | `check_ds_sc_strat` | DS, SC | ⚠️ | — | Cross-domain: randomized without SC strat |

---

## DV Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 50 | `check_dv_ae_aedecod_covid` | AE, DV | 🟡 | — | COVID-specific |
| 51 | `check_dv_covid` | DV | 🟡 | — | COVID-specific |

---

## EC Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 52 | `check_ec_sc_lat` | EC, SC | 🟡 | — | OPHTH-specific (eye laterality) |

---

## EG Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 53 | `check_eg_egdtc_visit_ordinal_error` | EG | ⚠️ | — | Cross-record: visit date ordering |

---

## EX Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 54 | `check_ex_exdose_exoccur` | EX | ✅ | SDTMCHK-EX-001 | EXDOSE missing when occurred |
| 55 | `check_ex_exdose_pos_exoccur_no` | EX | ✅ | SDTMCHK-EX-002 | EXDOSE>0 but EXOCCUR≠Y |
| 56 | `check_ex_exdosu` | EX | ✅ | SDTMCHK-EX-003 | EXDOSU missing |
| 57 | `check_ex_extrt_exoccur` | EX | ✅ | SDTMCHK-EX-004 | EXTRT missing |
| 58 | `check_ex_visit` | EX | ✅ | SDTMCHK-EX-005 | VISIT missing |
| 59 | `check_ex_exoccur_mis_exdose_nonmis` | EX | ✅ | SDTMCHK-EX-006 | EXOCCUR missing but EXDOSE present |
| 60 | `check_ex_exstdtc_after_exendtc` | EX | 🔵 | CORE-000718 | --STDTC > --ENDTC (generic rule) |
| 61 | `check_ex_dup` | EX | ⚠️ | — | Duplicate detection (cross-record) |
| 62 | `check_ex_exoccur_exdose_exstdtc` | EX | ⚠️ | — | Multi-condition: dose ≤ 0 AND/OR missing start |
| 63 | `check_ex_exstdtc_after_dd` | AE, DS, EX | ⚠️ | — | Cross-domain: EX date after death |
| 64 | `check_ex_exstdtc_visit_ordinal_error` | EX | ⚠️ | — | Cross-record: visit date ordering |
| 65 | `check_ex_infusion_exstdtc_exendtc` | EX | ⚠️ | — | Complex: IV route + date/time comparison |

---

## LB Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 66 | `check_lb_lbstresn_missing` | LB | ✅ | SDTMCHK-LB-001 | LBORRES present but LBSTRESN/LBSTRESC missing |
| 67 | `check_lb_lbstresu` | LB | ✅ | SDTMCHK-LB-002 | Units missing for quantitative results |
| 68 | `check_lb_lbstresc_char` | LB | ✅ | SDTMCHK-LB-003 | < or > prefix causing missing LBSTRESN |
| 69 | `check_lb_lbstnrlo_lbstnrhi` | LB, DM | ⚠️ | — | Reference range missing (may need DM join) |
| 70 | `check_lb_lbdtc_after_dd` | AE, DS, LB | ⚠️ | — | Cross-domain: LB date after death |
| 71 | `check_lb_lbdtc_visit_ordinal_error` | LB | ⚠️ | — | Cross-record: visit date ordering |
| 72 | `check_lb_missing_month` | LB | ⚠️ | — | Partial date pattern |

---

## MH Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 73 | `check_mh_missing_month` | MH | ⚠️ | — | Partial date pattern |

---

## MI Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 74 | `check_mi_mispec` | MI | ✅ | SDTMCHK-MI-001 | MISPEC missing |

---

## OE Domain Checks (Ophthalmology)

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 75 | `check_oe_bcva_1m_late_early_tot` | OE | 🟡 | — | OPHTH: BCVA scoring logic |
| 76 | `check_oe_bcva_4m_late_early_tot` | OE | 🟡 | — | OPHTH: BCVA scoring logic |
| 77 | `check_oe_bcva_4m_vs_1m_req` | OE | 🟡 | — | OPHTH: BCVA 4m vs 1m requirement |
| 78 | `check_oe_bcva_tot_mismatch` | OE | 🟡 | — | OPHTH: BCVA total mismatch |
| 79 | `check_oe_sc_lat_count_fingers` | OE, SC | 🟡 | — | OPHTH: laterality mismatch |

---

## PR Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 80 | `check_pr_missing_month` | PR | ⚠️ | — | Partial date pattern |
| 81 | `check_pr_prlat` | PR | 🟡 | — | OPHTH: ocular procedure laterality |

---

## QS Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 82 | `check_qs_qsstat_qsreasnd` | QS | ✅ | SDTMCHK-QS-001 | NOT DONE without reason |
| 83 | `check_qs_qsstat_qsstresc` | QS | ⚠️ | — | Cross-record: NOT DONE but responses populated |
| 84 | `check_qs_dup` | QS | ⚠️ | — | Cross-record: multiple dates at same visit |
| 85 | `check_qs_qsdtc_after_dd` | AE, DS, QS | ⚠️ | — | Cross-domain: QS date after death |
| 86 | `check_qs_qsdtc_visit_ordinal_error` | QS | ⚠️ | — | Cross-record: visit date ordering |

---

## RS Domain Checks (Oncology)

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 87 | `check_rs_rscat_rsscat` | RS | ✅ | SDTMCHK-RS-001 | RSSCAT without RSCAT |
| 88 | `check_rs_rsdtc_visit` | RS | ⚠️ | — | Missing RSDTC or VISIT for INV assessments |
| 89 | `check_rs_rsdtc_across_visit` | RS | ⚠️ | — | Cross-record: same date across visits |
| 90 | `check_rs_rsdtc_visit_ordinal_error` | RS | ⚠️ | — | Cross-record: visit date ordering |

---

## SC Domain Checks (Ophthalmology)

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 91 | `check_sc_dm_eligcrit` | DM, SC | 🟡 | — | OPHTH: eye eligibility criteria |
| 92 | `check_sc_dm_seyeselc` | DM, SC | 🟡 | — | OPHTH: study eye selection |

---

## SS Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 93 | `check_ss_ssstat_ssorres` | SS | ✅ | SDTMCHK-SS-001 | NOT DONE but SSORRES populated |
| 94 | `check_ss_ssdtc_alive_dm` | SS, DM | ⚠️ | — | Cross-domain: ALIVE date > DM death date |
| 95 | `check_ss_ssdtc_dead_ds` | SS, DS | ⚠️ | — | Cross-domain: DEAD without DS match |
| 96 | `check_ss_ssdtc_dead_dthdtc` | SS, DM | ⚠️ | — | Cross-domain: DEAD date < DM death date |

---

## TR Domain Checks (Oncology)

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 97 | `check_tr_trstresn_ldiam` | TR | ✅ | SDTMCHK-TR-001 | LDIAM missing TRSTRESN |
| 98 | `check_tr_dup` | TR | ⚠️ | — | Duplicate detection (cross-record) |
| 99 | `check_tr_trdtc_across_visit` | TR | ⚠️ | — | Cross-record: same date across visits |
| 100 | `check_tr_trdtc_visit_ordinal_error` | TR | ⚠️ | — | Cross-record: visit date ordering |

---

## TS Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 101 | `check_ts_aedict` | TS | ⚠️ | — | Dictionary version check (requires external ref) |
| 102 | `check_ts_cmdict` | TS | ⚠️ | — | Dictionary version check (requires external ref) |
| 103 | `check_ts_sstdtc_ds_consent` | TS, DS | ⚠️ | — | Cross-domain: study start date vs consent |

---

## TU Domain Checks (Oncology)

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 104 | `check_tu_tudtc` | TU | ✅ | SDTMCHK-TU-001 | TUDTC missing |
| 105 | `check_tu_tuloc_missing` | TU | ✅ | SDTMCHK-TU-002 | TULOC missing for targets |
| 106 | `check_tu_rs_new_lesions` | TU, RS | ⚠️ | — | Cross-domain: new lesion without PD response |
| 107 | `check_tu_tudtc_across_visit` | TU | ⚠️ | — | Cross-record: same date across visits |
| 108 | `check_tu_tudtc_visit_ordinal_error` | TU | ⚠️ | — | Cross-record: visit date ordering |

---

## VS Domain Checks

| # | Function | Domain(s) | Status | Rule ID | Notes |
|---|----------|-----------|--------|---------|-------|
| 109 | `check_vs_sbp_lt_dbp` | VS | ✅ | SDTMCHK-VS-001 | DBP > SBP (partially expressible) |
| 110 | `check_vs_height` | VS, DM | ⚠️ | — | Cross-domain/record: missing height |
| 111 | `check_vs_vsdtc_after_dd` | AE, DS, VS | ⚠️ | — | Cross-domain: VS date after death |

---

## Notes on Expressibility Limitations

### Why some checks cannot be translated to YAML

1. **Cross-domain checks** (⚠️): The CDISC Rules Engine Record Data rule type operates on a single dataset. Checks that require joining AE+DS, DM+AE, EX+DS etc. need the `Dataset Data` rule type which requires specifying join conditions — these are more complex and require manual engine configuration.

2. **Cross-record checks** (⚠️): Duplicate detection, visit-ordering checks, and date comparisons across records within the same domain require `Record Data [VP]` (value-pair) rule types or aggregation logic not available in simple YAML conditions.

3. **COVID-specific** (🟡): These are pandemic-era checks tied to specific AEDECOD terms and may not be relevant for current studies. Skipped to avoid noise.

4. **Ophthalmology-specific** (🟡): Highly specialized checks for BCVA scoring, ocular laterality. These require study-specific setup and are only relevant for ophthalmic trials.

### Potential future work

- Implement cross-domain checks using `Dataset Data` rule type once Fleet engine wrapper supports dataset joins
- Add visit-ordinal checks as a Fleet validation plugin (Python-based)
- Template partial-date pattern checks as a reusable regex rule

---

## File Listing

All translated rules are in `metadata/custom_rules/`:

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
SDTMCHK-CM-001.yaml   # CMDECOD missing
SDTMCHK-DM-001.yaml   # AGE missing/suspicious
SDTMCHK-DM-002.yaml   # ARM≠ACTARM
SDTMCHK-DS-001.yaml   # Death without date in DS
SDTMCHK-DS-002.yaml   # Blank death cause in DSTERM
SDTMCHK-EX-001.yaml   # EXDOSE missing when occurred
SDTMCHK-EX-002.yaml   # EXDOSE>0 but EXOCCUR≠Y
SDTMCHK-EX-003.yaml   # EXDOSU missing
SDTMCHK-EX-004.yaml   # EXTRT missing
SDTMCHK-EX-005.yaml   # VISIT missing
SDTMCHK-EX-006.yaml   # EXOCCUR missing, EXDOSE present
SDTMCHK-LB-001.yaml   # LBORRES present, standardized missing
SDTMCHK-LB-002.yaml   # Lab units missing
SDTMCHK-LB-003.yaml   # < or > prefix in lab results
SDTMCHK-MI-001.yaml   # MISPEC missing
SDTMCHK-QS-001.yaml   # NOT DONE without reason
SDTMCHK-RS-001.yaml   # RSSCAT without RSCAT
SDTMCHK-SS-001.yaml   # NOT DONE but SSORRES populated
SDTMCHK-TR-001.yaml   # LDIAM missing TRSTRESN
SDTMCHK-TU-001.yaml   # TUDTC missing
SDTMCHK-TU-002.yaml   # TULOC missing for targets
SDTMCHK-VS-001.yaml   # DBP > SBP (partially expressible)
```
