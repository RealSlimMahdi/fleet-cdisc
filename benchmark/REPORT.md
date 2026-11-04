# Fleet vs Oak + Admiral — ADAE Benchmark Report

**Date:** 2025-07-22  
**System:** macOS, Apple Silicon, 64 GB RAM  
**Data:** 11,468,544 AE rows (6,988,644 subjects) inflated from a synthetic 64-row AE extract (study STUDY001, 39 subjects, `benchmark/data`); Parquet I/O for all  
**Threads:** Polars at its default thread count  
**Timings:** from the run of this date. The ANL01FL tie rule and the ASEQ order of both scripts changed later (section 6); the timings were not run again.

---

## 1. What Was Benchmarked

All pipelines derive the same ADAE variables from raw AE + ADSL inputs:

| Step            | Variables                                                                                    |
| --------------- | -------------------------------------------------------------------------------------------- |
| SDTM mapping    | STUDYID, DOMAIN, USUBJID, AETERM, AESTDTC, AEENDTC, AESEV, AESER, AEREL, AEOUT, AEACN, AESEQ |
| ADaM derivation | ASTDT, AENDT, study day (ADY/ASTDY+AENDY), TRTEMFL, AESEVN, ANL01FL, ASEQ                    |

Both sides use CDISC-aware SDTM frameworks: Fleet's `.sdtm` namespace verbs map to oak's `assign_no_ct` / `hardcode_no_ct` / `derive_seq`. The ADaM layer maps Fleet's `.adam` / `.adam.occds` verbs to admiral's `derive_vars_*` functions.

All tools read Parquet (via Arrow for R, native for Polars) to ensure I/O parity.

---

## 2. Execution Time (seconds)

### Fleet vs Oak + Admiral (native R)

|  Rows | Fleet (Polars) | Oak + Admiral (R) | Speedup |
| ----: | -------------: | ----------------: | ------: |
|  100K |       **0.20** |               2.8 |     14× |
|  500K |       **0.36** |              15.1 |     42× |
|    1M |       **0.74** |              30.5 |     41× |
|    2M |       **1.48** |              56.5 |     38× |
|    5M |       **3.98** |             136.2 |     34× |
| 11.5M |       **9.02** |             318.1 |     35× |

### Native R vs rpy2 (same R code called from Python)

| Rows | Oak + Admiral (Rscript) | rpy2 → Oak + Admiral | rpy2 overhead |
| ---: | ----------------------: | -------------------: | ------------: |
| 100K |                     2.8 |                 10.6 |         +279% |
| 500K |                    15.1 |                 22.1 |          +46% |
|   1M |                    30.5 |                 41.6 |          +36% |
|   2M |                    56.5 |                 76.7 |          +36% |

### SDTM + ADaM breakdown (rpy2, pipeline time only)

| Rows | SDTM (oak) | ADaM (admiral) | Pipeline total | Data load overhead |
| ---: | ---------: | -------------: | -------------: | -----------------: |
| 100K |       1.2s |           2.6s |           3.8s |               6.8s |
| 500K |       5.1s |          13.5s |          18.6s |               3.5s |
|   1M |       9.5s |          28.8s |          38.3s |               3.3s |
|   2M |      18.8s |          53.4s |          72.2s |               4.5s |

### Scaling behaviour

- **Fleet:** Near-linear. Doubling rows roughly doubles time. At 2M rows the pipeline finishes in **1.5 seconds**. At full scale (11.5M rows) it completes in **9.0 seconds** (SDTM 3.2s + ADaM 5.9s).
- **Oak + Admiral:** Also near-linear from 500K rows, at about 27 to 31 seconds per million rows. Most of the time is in oak's join-per-column SDTM mapping, admiral's `derive_vars_dt()` date parsing and `derive_var_extreme_flag()` per-group operations. At 2M rows: **56.5 seconds**. At full scale (11.5M rows) it completes in **318.1 seconds** (SDTM 89.2s + ADaM 228.9s) — over 5 minutes.
- **rpy2 overhead:** At small scale (100K), rpy2's fixed cost of data loading per iteration dominates (+279%). At 1M and 2M rows the overhead is about 36% (table above).

---

## 3. Pipeline Code Comparison

Line counts: non-blank, non-comment lines between the timers of `run_pipeline` in each script (Fleet 18 + 37 = 55, Oak + Admiral 58 + 31 = 89). The excerpts below are shorter than the scripts.

### Fleet (Python / Polars)

```python
# SDTM
ae = (
    ae_raw.sdtm
    .assign("STUDYID", value="STUDY001")
    .assign("DOMAIN", value="AE")
    .assign("USUBJID", source="subject_id")
    .assign("AETERM", source="event_term")
    .assign("AESTDTC", source="start_date")
    .assign("AEENDTC", source="end_date")
    .assign("AESEV", source="severity")
    .derivation("AESER",
        expression=pl.when(pl.col("serious") == "Yes")
        .then(pl.lit("Y")).otherwise(pl.lit("N")))
    .assign("AEREL", source="relationship_to_study_drug")
    .assign("AEOUT", source="outcome")
    .assign("AEACN", source="action_taken")
    .seq("AESEQ", order_by=["AESTDTC"])
    .to_frame()
)

# ADaM
adae = (
    ae_merged.adam
    .source("USUBJID").source("AETERM")
    .source("AESTDTC").source("AEENDTC")
    .source("AESEV").source("AESER")
    .source("AEREL").source("AEOUT").source("AEACN")
    .date("ASTDT", source="AESTDTC")
    .date("AENDT", source="AEENDTC")
    .duration("ADY", start="TRTSDT", end="ASTDT")
    .to_frame()
    .adam.occds
    .treatment_emergent("TRTEMFL",
        start_date="ASTDT", end_date="AENDT", trtsdt="TRTSDT")
    .recode("AESEVN", source="AESEV",
        recode_map={"Mild": 1, "Moderate": 2, "Severe": 3})
    .flag("ANL01FL", criteria="last",
        order_by=["AESEVN", "AESEQ"], by=["USUBJID", "AETERM"])
    .seq("ASEQ", by=["USUBJID"], order_by=["AESEQ"])
    .to_frame()
)
```

### Oak + Admiral (R / pharmaverse)

```r
# SDTM using sdtm.oak
ae_oak <- ae_raw %>%
  mutate(oak_id = row_number(), raw_source = "AE_RAW",
         patient_number = as.integer(factor(subject_id)))

ae_sdtm <-
  hardcode_no_ct(raw_dat = ae_oak, raw_var = "event_term",
    tgt_var = "STUDYID", tgt_val = "STUDY001") |>
  hardcode_no_ct(tgt_dat = _, raw_dat = ae_oak, raw_var = "event_term",
    tgt_var = "DOMAIN", tgt_val = "AE") |>
  assign_no_ct(tgt_dat = _, raw_dat = ae_oak,
    raw_var = "subject_id", tgt_var = "USUBJID") |>
  assign_no_ct(tgt_dat = _, raw_dat = ae_oak,
    raw_var = "event_term", tgt_var = "AETERM") |>
  assign_no_ct(tgt_dat = _, raw_dat = ae_oak,
    raw_var = "start_date", tgt_var = "AESTDTC") |>
  assign_no_ct(tgt_dat = _, raw_dat = ae_oak,
    raw_var = "end_date", tgt_var = "AEENDTC") |>
  assign_no_ct(tgt_dat = _, raw_dat = ae_oak,
    raw_var = "severity", tgt_var = "AESEV") |>
  assign_no_ct(tgt_dat = _, raw_dat = ae_oak,
    raw_var = "relationship_to_study_drug", tgt_var = "AEREL") |>
  assign_no_ct(tgt_dat = _, raw_dat = ae_oak,
    raw_var = "outcome", tgt_var = "AEOUT") |>
  assign_no_ct(tgt_dat = _, raw_dat = ae_oak,
    raw_var = "action_taken", tgt_var = "AEACN") |>
  assign_no_ct(tgt_dat = _, raw_dat = ae_oak,
    raw_var = "serious", tgt_var = "AESER") |>
  mutate(AESER = if_else(AESER == "Yes", "Y", "N")) |>
  select(-oak_id, -raw_source, -patient_number) |>
  derive_seq(tgt_var = "AESEQ",
    rec_vars = c("STUDYID", "USUBJID", "AESTDTC"),
    sbj_vars = c("STUDYID", "USUBJID"))

# ADaM using admiral
adae <- ae_sdtm %>%
  derive_vars_merged(dataset_add = adsl_vars,
    by_vars = exprs(USUBJID),
    new_vars = exprs(TRTSDT, TRTEDT, TRT01P, SAFFL)) %>%
  derive_vars_dt(new_vars_prefix = "AST", dtc = AESTDTC) %>%
  derive_vars_dt(new_vars_prefix = "AEN", dtc = AEENDTC) %>%
  derive_vars_dy(reference_date = TRTSDT,
    source_vars = exprs(ASTDT, AENDT)) %>%
  derive_var_trtemfl(trt_start_date = TRTSDT, trt_end_date = TRTEDT,
    start_date = ASTDT, end_date = AENDT) %>%
  mutate(AESEVN = case_when(
    AESEV == "Mild" ~ 1L,
    AESEV == "Moderate" ~ 2L,
    AESEV == "Severe" ~ 3L)) %>%
  derive_var_extreme_flag(by_vars = exprs(USUBJID, AETERM),
    order = exprs(AESEVN, AESEQ), new_var = ANL01FL, mode = "last") %>%
  derive_var_obs_number(by_vars = exprs(USUBJID),
    order = exprs(AESEQ), new_var = ASEQ)
```

---

## 4. Dependency Footprint

| Metric         |            Fleet |                               Oak + Admiral |
| -------------- | ---------------: | ------------------------------------------: |
| Total packages |               23 |                                          54 |
| SDTM engine    | `.sdtm` (Polars) |                              sdtm.oak 0.2.0 |
| ADaM engine    | `.adam` (Polars) |                               admiral 1.4.1 |
| Core runtime   |    Polars (Rust) | dplyr + lubridate + tidyr + stringr (R/C++) |
| I/O library    | Built-in Parquet |                                       arrow |
| Language       |      Python 3.12 |                                     R 4.5.3 |

Oak + Admiral pulls in 54 transitive dependencies (including admiraldev, sdtm.oak, tidyr, stringr, cpp11, pkgbuild, roxygen2, etc.) vs Fleet's 23 (many of which — httpx, jsonschema, lxml — are for optional CLI features, not the derivation pipeline itself).

---

## 5. rpy2 Observations

The rpy2 benchmark runs the **exact same R code** (oak SDTM + admiral ADaM) from within a Python process via `rpy2.robjects`. Key findings:

1. **Fixed overhead at small scale.** At 100K rows, rpy2 takes 10.6s vs Rscript's 2.8s. The gap is mostly data I/O (reading Parquet into the embedded R session for each scale factor) and rpy2 marshalling.
2. **Smaller share at large scale.** At 1M and 2M rows, the overhead is about 36%. The R pipeline itself takes most of the time.
3. **Pipeline time.** The SDTM + ADaM time under rpy2 is 72.2s at 2M rows (18.8s + 53.4s), against 56.5s in total for native Rscript. The rest of the rpy2 time is data load.
4. **Practical implication.** rpy2 is viable for embedding pharmaverse pipelines within Python workflows, but adds measurable overhead. For benchmarking, native Rscript is fairer; for production, the overhead may be acceptable if it avoids language switching in a Python-centric stack.

---

## 6. Output Differences

| Aspect                | Fleet                                     | Oak + Admiral                   |
| --------------------- | ----------------------------------------- | ------------------------------- |
| Output columns        | 49 (retains raw source columns + derived) | 24 (only SDTM + ADaM variables) |
| Study day variable    | `ADY` (single)                            | `ASTDY` + `AENDY` (separate)    |
| Date imputation flags | `ASTDTF`, `AENDTF` generated              | Not generated                   |

Fleet carries forward all source columns by default (useful for traceability); Oak + Admiral pipelines explicitly select only target variables. This is a design choice.

**Row-by-row check.** `run_benchmark.py` compares the full outputs of the smallest scale on 17 variables (STUDYID, USUBJID, AETERM, AESTDTC, AEENDTC, AESEV, AESER, AEREL, AEOUT, AEACN, AESEQ, ASTDT, AENDT, TRTEMFL, AESEVN, ANL01FL, ASEQ) and exits 1 on a difference. Both sides use the same rules:

- TRTEMFL: start on or after TRTSDT, no upper limit (Fleet passes no `trtedt`; the R call sets no `end_window`).
- ANL01FL: the last record by AESEVN, then AESEQ, within USUBJID and AETERM, so one record per group on a tie.
- ASEQ: numbered by AESEQ within USUBJID.

On an 11,520-row inflated input, all 17 variables have the same value on every row.

---

## 7. Fairness Notes

To ensure objectivity:

1. **Symmetric SDTM frameworks.** Both sides use CDISC-aware verb-based SDTM mapping (Fleet's `.sdtm` namespace / oak's `assign_no_ct` + `hardcode_no_ct`). Neither uses raw `dplyr::transmute`.
2. **Same data, same I/O format.** Both read the same Parquet files (Snappy-compressed).
3. **Same derivation rules.** AESER recoding, date parsing, TRTEMFL, the severity flag and sequencing follow the rules in section 6; `run_benchmark.py` checks every row of the smallest scale.
4. **Both run as clean subprocesses** (no warm JIT caches). The rpy2 benchmark runs in a fresh Python process with an embedded R session.
5. **Memory measurement caveat.** R's `gc()` reports GC-tracked allocations only; Python's RSS includes the full process. The numbers are not directly comparable.
6. **Oak's join-per-column architecture** is inherently more expensive than Fleet's lazy Polars expressions — each `assign_no_ct()` call performs a join on `oak_id_vars`. This is a design trade-off in oak (row-level traceability and provenance), not inefficiency.
7. **Admiral's strength is not raw speed.** It is a mature, regulatory-validated, well-documented CDISC toolkit with broad industry adoption. Performance at clinical-trial scale (thousands to tens of thousands of rows) is rarely a bottleneck.
8. **Fleet's Polars engine** is a Rust-backed columnar engine designed for large-scale data — the speed advantage is expected and reflects the technology choice, not better engineering per se.

---

## 8. Summary

| Dimension             | Fleet                     | Oak + Admiral          | Winner       |
| --------------------- | ------------------------- | ---------------------- | ------------ |
| Speed (2M rows)       | 1.5s                      | 56.5s (native R)       | Fleet (~38×) |
| Speed (11.5M rows)    | 9.0s                      | 318.1s (native R)      | Fleet (~35×) |
| Speed via rpy2        | —                         | 76.7s (+36% vs native) | Native R     |
| Scaling linearity     | Near-linear               | Near-linear            | Comparable   |
| Pipeline LOC          | 55                        | 89                     | Fleet        |
| Dependency count      | 23                        | 54                     | Fleet        |
| SDTM framework        | `.sdtm` namespace         | sdtm.oak               | Comparable   |
| Regulatory maturity   | Emerging                  | Established            | Oak+Admiral  |
| Community / ecosystem | Small                     | Large (pharmaverse)    | Oak+Admiral  |
| CDISC CT integration  | Built-in codelist classes | External lookups       | Fleet        |

Fleet delivers order-of-magnitude speed gains at scale through Polars' columnar engine, with fewer lines of pipeline code and a lighter dependency tree. Oak + Admiral remains the pharmaverse standard with deeper regulatory acceptance and a broader R-based ecosystem. The rpy2 bridge is functional but adds about 36% overhead at 1M and 2M rows, making native Rscript the appropriate baseline for performance comparison.

---

## Versions

| Component | Version |
| --------- | ------- |
| Fleet     | 0.1.0   |
| Polars    | 1.39.0  |
| Python    | 3.12.13 |
| sdtm.oak  | 0.2.0   |
| Admiral   | 1.4.1   |
| R         | 4.5.3   |
| rpy2      | 3.6.7   |
| arrow (R) | latest  |
