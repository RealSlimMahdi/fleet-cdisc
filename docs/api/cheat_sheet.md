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
| `.assign_datetime(target, source, mode)`              | Normalise dates to ISO 8601 strings.                                        | `.assign_datetime("RFSTDTC", "first_dose_dt", mode="datetime")` |
| `.if_then_else(target, when, else_value)`             | Derive a value conditionally.                                               | `.if_then_else("AGEGR1", pl.col("AGE") < 18, "ADULT")`          |

## ADaM BDS Namespace (`df.adam`)

| Verb                                                | Description                                                          | Example                                               |
| --------------------------------------------------- | -------------------------------------------------------------------- | ----------------------------------------------------- |
| `.study_day(target, analysis_date, reference_date)` | Calculate CDISC study day algorithm.                                 | `.study_day("ADY", "ADT", "TRTSDT")`                  |
| `.baseline(target, aval, baseline_flag)`            | Find the baseline record per USUBJID/PARAMCD, broadcast to `target`. | `.baseline("BASE", "AVAL", "ABLFL")`                  |
| `.chg(target, aval, base)`                          | Change (`AVAL - BASE`)                                               | `.chg("CHG", "AVAL", "BASE")`                         |
| `.pchg(target, aval, base)`                         | Percent change `(CHG / BASE) * 100`                                  | `.pchg("PCHG", "AVAL", "BASE")`                       |
| `.flag(target, criteria, groups)`                   | Assign boolean `"Y"` based on Polars criteria.                       | `.flag("CRIT1FL", pl.col("AVAL") > 10)`               |
| `.imputation(target, method, groups)`               | LOCF or WOCF imputations.                                            | `.imputation("AVAL", "LOCF", ["USUBJID", "PARAMCD"])` |

## ADSL Namespace (`df.adam.adsl`)

| Verb                                                 | Description                                                              | Example                                                         |
| ---------------------------------------------------- | ------------------------------------------------------------------------ | --------------------------------------------------------------- |
| `.first_date(target, from_dataset, date_col, where)` | Find earliest date per subject in a second dataset, e.g. TRTSDT from EX. | `.first_date("TRTSDT", ex_df, "EXSTDTC")`                       |
| `.last_date(target, from_dataset, date_col, where)`  | Find latest date per subject.                                            | `.last_date("TRTEDT", ex_df, "EXENDTC")`                        |
| `.duration(target, start_date, end_date)`            | Number of elapsed days (start to end + 1).                               | `.duration("TRTDUR", "TRTSDT", "TRTEDT")`                       |
| `.eligibility_flag(target, criteria)`                | Single-row evaluation into a `"Y"` flag.                                 | `.eligibility_flag("ITTFL", pl.col("ARM") != "Screen Failure")` |
| `.count_events(target, from_dataset, where)`         | Tally events for a subject.                                              | `.count_events("AECNT", ae_df)`                                 |

## OCCDS Namespace (`df.adam.occds`)

| Verb                                                   | Description                                              | Example                                                             |
| ------------------------------------------------------ | -------------------------------------------------------- | ------------------------------------------------------------------- |
| `.first_occ(target, date_col, groups)`                 | Flags the first chronological record per group.          | `.first_occ("AOCCFL", "ASTDT", ["USUBJID", "AEDECOD"])`             |
| `.worst_severity(target, severity_col, order, groups)` | Flags worst event when multiple occur.                   | `.worst_severity("AOCCSFL", "AESEV", ["MILD","MODERATE","SEVERE"])` |
| `.any_flag(target, col, value, groups)`                | Emits `"Y"` if _any_ record in the group meets criteria. | `.any_flag("ANYSEVERE", "AESEV", "SEVERE", ["USUBJID"])`            |
