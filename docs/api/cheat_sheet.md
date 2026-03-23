# Verb Cheat Sheet

This cheat sheet summarises the most common verbs across Fleet namespaces. For full parameter signatures, see the respective API references.

## Core Verbs (Available everywhere)

| Verb                              | Description                                                                   | Example                                                |
| --------------------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------------ |
| `.to_frame()`                     | Materialises the pipeline into a Polars DataFrame. Must be called at the end. | `.to_frame()`                                          |
| `.derivation(target, expression)` | Injects an arbitrary Polars expression.                                       | `.derivation("AGE", pl.col("AGE_RAW").cast(pl.Int64))` |
| `.source(target, from_col)`       | Passes a column through (renaming if `from_col` is provided).                 | `.source("USUBJID")`                                   |
| `.assigned(target, value)`        | Hardcodes a constant literal for all rows.                                    | `.assigned("DOMAIN", "DM")`                            |

## SDTM Namespace (`df.sdtm`)

| Verb                                                  | Description                                                                 | Example                                                         |
| ----------------------------------------------------- | --------------------------------------------------------------------------- | --------------------------------------------------------------- |
| `.assign_no_ct(target, source)`                       | Map a column entirely without Controlled Terminology.                       | `.assign_no_ct("USUBJID", source="patient_id")`                 |
| `.hardcode_no_ct(target, value)`                      | Assign a constant literal.                                                  | `.hardcode_no_ct("DOMAIN", "DM")`                               |
| `.assign_ct(target, source, ct_codelist, ct_mapping)` | Map values explicitly through a dictionary and validate against a codelist. | `.assign_ct("SEX", "sex_raw", "C66731", {"M":"M", "F":"F"})`    |
| `.assign_dtc(target, source)`                        | Normalise dates to ISO 8601 strings.                                        | `.assign_dtc("RFSTDTC", source="first_dose_dt")`                  |
| `.if_then_else(target, when, else_value)`             | Derive a value conditionally.                                               | `.if_then_else("AGEGR1", pl.col("AGE") < 18, "ADULT")`          |

## ADaM BDS Namespace (`df.adam`)

| Verb                                                | Description                                                                | Example                                                                 |
| --------------------------------------------------- | -------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| `.study_day(target, analysis_date, reference_date)` | Calculate CDISC study day algorithm.                                       | `.study_day("ADY", "ADT", "TRTSDT")`                                    |
| `.baseline(target, aval, baseline_flag)`            | Find the baseline record per USUBJID/PARAMCD, broadcast to `target`.       | `.baseline("BASE", "AVAL", "ABLFL")`                                    |
| `.chg(target, aval, base)`                          | Change (`AVAL - BASE`)                                                     | `.chg("CHG", "AVAL", "BASE")`                                           |
| `.pchg(target, aval, base)`                         | Percent change `(CHG / BASE) * 100`                                        | `.pchg("PCHG", "AVAL", "BASE")`                                         |
| `.flag(target, criteria, groups)`                   | Assign boolean `"Y"` based on Polars criteria.                             | `.flag("CRIT1FL", pl.col("AVAL") > 10)`                                 |
| `.bmi(target, weight, height)`                      | BMI = weight / (height / 100)²                                             | `.bmi("BMI", weight="WEIGHT", height="HEIGHT")`                         |
| `.nrind(target, value, low, high)`                  | Normal range indicator: LOW / NORMAL / HIGH.                               | `.nrind("ANRIND", value="AVAL", low="LO", high="HI")`                   |
| `.on_treatment(target, adt, trtsdt, trtedt)`        | On-treatment flag within [TRTSDT, TRTEDT].                                 | `.on_treatment("ONTRTFL", adt="ADT", trtsdt="TRTSDT", trtedt="TRTEDT")` |
| `.shift(target, baseline_cat, post_cat)`            | Categorical shift string: "NORMAL to HIGH".                                | `.shift("SHIFT1", baseline_cat="BNRIND", post_cat="ANRIND")`            |
| `.bsa(target, weight, height, method)`              | Body Surface Area (m²). Methods: Mosteller, DuBois, Haycock, Gehan-George. | `.bsa("BSA", weight="WEIGHT", height="HEIGHT")`                         |
| `.map(target, systolic, diastolic)`                 | Mean Arterial Pressure: DBP + (SBP - DBP) / 3.                             | `.map("MAP", systolic="SYSBP", diastolic="DIABP")`                      |
| `.qtc(target, qt, rr, method)`                      | Corrected QT interval (Fridericia or Bazett).                              | `.qtc("QTCF", qt="QT", rr="RR")`                                        |
| `.derive_summary_records(by_vars, ...)`             | Aggregate by group and append summary rows.                                | `.derive_summary_records(by_vars=["USUBJID"], ...)`                     |
| `.derive_locf_records(by_vars, ...)`                | Forward-fill (LOCF) within patient groups.                                 | `.derive_locf_records(by_vars=["USUBJID", "PARAMCD"])`                  |
| `.derive_param(by_vars, ...)`                       | Derive a new parameter from existing records and append rows.              | `.derive_param(by_vars=["USUBJID"], ...)`                               |

## ADSL Namespace (`df.adam.adsl`)

| Verb                                                 | Description                                                              | Example                                                         |
| ---------------------------------------------------- | ------------------------------------------------------------------------ | --------------------------------------------------------------- |
| `.first_date(target, from_dataset, date_col, where)` | Find earliest date per subject in a second dataset, e.g. TRTSDT from EX. | `.first_date("TRTSDT", ex_df, "EXSTDTC")`                       |
| `.last_date(target, from_dataset, date_col, where)`  | Find latest date per subject.                                            | `.last_date("TRTEDT", ex_df, "EXENDTC")`                        |
| `.duration(target, start_date, end_date)`            | Number of elapsed days (start to end + 1).                               | `.duration("TRTDUR", "TRTSDT", "TRTEDT")`                       |
| `.eligibility_flag(target, criteria)`                | Single-row evaluation into a `"Y"` flag.                                 | `.eligibility_flag("ITTFL", pl.col("ARM") != "Screen Failure")` |
| `.count_events(target, from_dataset, where)`         | Tally events for a subject.                                              | `.count_events("AECNT", ae_df)`                                 |
| `.age_years(target, age_col, age_unit_col)`          | Unit-aware age conversion (YEARS, MONTHS, WEEKS, DAYS).                  | `.age_years("AAGE", age_col="AGE", age_unit_col="AGEU")`        |
| `.derive_period(periods, start_date)`                | Create APxxSDT, APxxEDT, TRTxxP Subperiod/Phase variables.               | `.derive_period(periods=[{"number": 1, ...}])`                  |

## OCCDS Namespace (`df.adam.occds`)

| Verb                                                   | Description                                              | Example                                                             |
| ------------------------------------------------------ | -------------------------------------------------------- | ------------------------------------------------------------------- |
| `.first_occ(target, date_col, groups)`                 | Flags the first chronological record per group.          | `.first_occ("AOCCFL", "ASTDT", ["USUBJID", "AEDECOD"])`             |
| `.worst_severity(target, severity_col, order, groups)` | Flags worst event when multiple occur.                   | `.worst_severity("AOCCSFL", "AESEV", ["MILD","MODERATE","SEVERE"])` |
| `.any_flag(target, col, value, groups)`                | Emits `"Y"` if _any_ record in the group meets criteria. | `.any_flag("ANYSEVERE", "AESEV", "SEVERE", ["USUBJID"])`            |

## PK Namespace (`df.adam.pk`)

| Verb                                                          | Description                                                                  | Example                                                         |
| ------------------------------------------------------------- | ---------------------------------------------------------------------------- | --------------------------------------------------------------- |
| `.blq_flag(target, *, conc_col, lloq_col)`                    | Flag BLQ records: `"Y"` when `conc < LLOQ`, else null.                       | `.blq_flag("BLQFL", conc_col="PCSTRESN", lloq_col="PCLLOQ")`    |
| `.blq_impute(target, *, conc_col, lloq_col, method)`          | Impute BLQ concentrations (`half_lloq`, `zero`, `lloq`, or `missing`).       | `.blq_impute("AVAL", conc_col="PCSTRESN", lloq_col="PCLLOQ")`   |
| `.blqfn(target, *, conc_col, lloq_col)`                       | Numeric BLQ flag: `1` when BLQ, `0` otherwise.                               | `.blqfn("BLQFN", conc_col="PCSTRESN", lloq_col="PCLLOQ")`       |
| `.nominal_time(target, *, from_col, input_unit, output_unit)` | Derive nominal elapsed time with unit conversion.                            | `.nominal_time("NTIME", from_col="PCTPTNUM")`                   |
| `.actual_time(target, *, sample_dtm, dose_dtm, unit)`         | Derive actual elapsed time between two datetime columns.                     | `.actual_time("ATIME", sample_dtm="PCDTC", dose_dtm="EXSTDTC")` |
| `.predose_flag(target, *, time_col, window_hrs)`              | Flag pre-dose samples within a window before dosing.                         | `.predose_flag("PREDFL", time_col="ATIME")`                     |
| `.dose_normalized(target, *, conc_col, dose_col)`             | Dose-normalise concentration: `conc / dose`.                                 | `.dose_normalized("AVALDNM", conc_col="AVAL", dose_col="DOSE")` |
| `.evid(target, *, from_col, dose_indicator, conc_indicator)`  | Derive `EVID` (event ID) for NONMEM-style datasets.                          | `.evid("EVID")`                                                 |
| `.mrrlt(target, *, arrlt_col)`                                | Clip negative ARRLT to 0 for MRRLT (modified relative time).                 | `.mrrlt("MRRLT", arrlt_col="ARRLT")`                            |
| `.log_conc(target, *, conc_col, base)`                        | Log-transform concentration (`"e"`, `"2"`, or `"10"`).                       | `.log_conc("DVL", conc_col="DV")`                               |
| `.mdv(target, *, conc_col, evid_col)`                         | Derive `MDV` (Missing Dependent Variable) for PopPK datasets.                | `.mdv("MDV", conc_col="DV", evid_col="EVID")`                   |
| `.amt(target, *, dose_col, evid_col)`                         | Derive `AMT`: dose amount on dosing records, null on observations.           | `.amt("AMT", dose_col="EXDOSE", evid_col="EVID")`               |
| `.cmt(target, *, evid_col, dose_cmt, conc_cmt)`               | Derive `CMT` compartment number following NONMEM convention.                 | `.cmt("CMT", evid_col="EVID", dose_cmt=1, conc_cmt=2)`          |
| `.avalcat(target, *, conc_col, lloq_col, blq_label, digits)`  | Listing-ready categorised analysis value (`AVALCAT1`).                       | `.avalcat("AVALCAT1", conc_col="PCSTRESC", lloq_col="PCLLOQ")`  |
| `.anl_flag(target, *, exclude_dtype, dtype_col)`              | Derive analysis flag (`ANL01FL` for all records, `ANL02FL` excluding DTYPE). | `.anl_flag("ANL01FL")`                                          |
