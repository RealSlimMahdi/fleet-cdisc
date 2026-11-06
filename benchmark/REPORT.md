# Fleet vs Oak + Admiral — ADAE Benchmark Report

**Date:** 2026-11-05 (one rerun on branch `wip/high2-bench`)  
**Machine:** Apple M4 Max (Mac16,6), 16 cores (12 performance, 4 efficiency), 64 GB RAM, macOS 26.7.1. The machine was shared with other jobs: load average 12.4 when the Fleet runs started, 3 to 6 during the R runs.  
**Data:** synthetic raw AE, inflated from a synthetic 64-row AE extract (study STUDY001, 39 subjects, `benchmark/data`) copied 179,196 times. Two inputs:

- **Sparse:** each copy gets new subject IDs, so a subject holds 1 to 3 AE records (1.64 on average). The full input has 11,468,544 AE rows and 6,988,644 subjects.
- **Dense:** copy *i* goes to subject group *i* modulo 1,283, so the 2,000,000 rows belong to 50,037 subjects (40 records per subject at 2M rows; the smaller sizes take the first rows, so 2, 10 and 20 records per subject).

**I/O:** Parquet for all tools; the timers exclude the read.  
**Threads:** Fleet at the Polars default (16 threads) and with `POLARS_MAX_THREADS=1`. R (dplyr, admiral, sdtm.oak) runs on one thread.  
**Repetitions:** each size runs 3 times in one process per tool. The tables give the median and, in brackets, the minimum and maximum.  
**Command:** `uv run python -u benchmark/run_benchmark.py --reps 3` (section 2 names the exceptions of this rerun).

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

Pipeline time only (SDTM + ADaM, no file read). Median [min-max] of 3 runs. Speedup is the R median divided by the Fleet median. "Check" is the row-by-row comparison of section 6 at that size, for Fleet at both thread counts against oak + admiral.

### Sparse input (1 to 3 records per subject)

|      Rows |  Subjects | Fleet (16 threads) |    Fleet (1 thread) |       Oak + Admiral (R) | Speedup (16 / 1 thread) | Check   |
| --------: | --------: | -----------------: | ------------------: | ----------------------: | ----------------------: | ------- |
|      100K |    60,940 | 0.23 [0.22-0.23]   | 0.47 [0.47-0.48]    | 2.81 [2.79-3.04]        |               12× / 6× | same    |
|      500K |   304,690 | 1.05 [1.04-1.06]   | 2.64 [2.40-2.92]    | 15.23 [15.13-16.44]     |               15× / 6× | same    |
|        1M |   609,375 | 2.12 [2.11-2.14]   | 5.20 [5.11-5.28]    | 31.64 [30.50-31.70]     |               15× / 6× | same    |
|        2M | 1,218,750 | 4.24 [4.22-4.28]   | 10.10 [9.93-11.44]  | 54.56 [53.48-59.27]     |               13× / 5× | same    |
|        5M | 3,046,875 | 11.57 [10.80-12.17] | 26.00 [25.34-26.66] | 133.74 [131.07-139.85] |               12× / 5× | same    |
| 11,468,544 | 6,988,644 | 26.61 [25.53-29.64] | 58.46 [57.79-58.81] | 322.20 (1 run, see below) |             12× / 6× | not run |

### Dense input (50,037 subjects)

| Rows | Records per subject | Fleet (16 threads) | Fleet (1 thread) | Oak + Admiral (R)   | Speedup (16 / 1 thread) | Check |
| ---: | ------------------: | -----------------: | ---------------: | ------------------: | ----------------------: | ----- |
| 100K |                   2 | 0.19 [0.19-0.19]   | 0.40 [0.40-0.41] | 2.08 [2.06-2.30]    |                11× / 5× | same  |
| 500K |                  10 | 0.34 [0.33-0.35]   | 0.88 [0.88-0.88] | 4.99 [4.83-5.08]    |                15× / 6× | same  |
|   1M |                  20 | 0.54 [0.54-0.55]   | 1.60 [1.59-1.60] | 8.10 [7.95-8.10]    |                15× / 5× | same  |
|   2M |                  40 | 0.97 [0.96-0.98]   | 2.91 [2.90-2.95] | 14.62 [14.34-15.99] |                15× / 5× | same  |

### Exceptions in this rerun

- **R at 11,468,544 rows.** The first run took 322.20 s (SDTM 87.19 s, ADaM 235.01 s). In the second run the R process went into swap (gc "max used" 75.6 GB on a 64 GB machine), because the script kept the output of the previous run in memory; it took 466.39 s. The run was stopped during the third repetition, so this size has one clean R run and no row-by-row check. The script now frees the previous output before each repetition; this fix was not run at this size. The largest size with the full protocol (3 runs and the check) is 5M rows.
- **Order of the runs.** The rerun stopped at that point, so `run_benchmark.py` did not finish. The R dense runs were then started alone (`admiral_adae_benchmark.R --reps=3 --input=dense --tag=dense`), and the check of section 6 ran on the saved outputs with `compare_outputs` of `run_benchmark.py`.
- **Earlier report.** From 500K rows on, the Fleet times on the sparse input are about 2.9 times those of the 2025-07-22 report (2.12 s against 0.74 s at 1M rows, 26.61 s against 9.02 s at 11.5M rows). A recheck at 1M rows at load average 3.3 gave 2.11 to 2.13 s. The R times are close to the earlier ones (31.64 s against 30.5 s at 1M rows).
- **Cause of the slowdown (issue #207).** Not Polars: with Polars 1.39.0 the code of this rerun takes the same time (2.05 s at 1M rows). Not the new call-time checks: the Python part of the pipeline takes less than 0.02 s. The cause is the change of the Fleet pipeline in this rerun, to give the same ANL01FL and ASEQ as admiral: `flag(criteria="last", order_by=["AESEVN", "AESEQ"])` in place of `flag(criteria="max", value_col="AESEVN")`, and `seq(order_by=["AESEQ"])`. The ordered window of `flag` took 1.24 of the 2.1 s, because the sparse input has about one record per USUBJID and AETERM. The July 2025 code with its pipeline takes 0.68 s on this machine. The fix of #207 sorts the frame once in `flag`: the pipeline then takes 0.90 s at 1M rows and 1.87 s at 2M rows, with the same output. The tables above are from before this fix and are not rerun.

### Native R vs rpy2 (same R code called from Python)

One run per size. The rpy2 total includes reading the full 11.5M-row Parquet file into R and taking the subset at each size; the pipeline column is SDTM + ADaM only. The Rscript column is the median of section 2.

| Rows | Oak + Admiral (Rscript) | rpy2 pipeline | rpy2 total | Pipeline overhead | Total overhead |
| ---: | ----------------------: | ------------: | ---------: | ----------------: | -------------: |
| 100K |                    2.81 |          3.43 |       9.56 |              +22% |          +240% |
| 500K |                   15.23 |         16.35 |      19.48 |               +7% |           +28% |
|   1M |                   31.64 |         35.10 |      38.02 |              +11% |           +20% |
|   2M |                   54.56 |         63.33 |      67.08 |              +16% |           +23% |

### Scaling behaviour

- **Both scale near-linearly on the sparse input.** From 100K to 11.5M rows (115 times the rows), Fleet time grows 117 times and R time 115 times.
- **Fleet:** at 2M rows the pipeline takes 4.24 s; at 11.5M rows 26.61 s (SDTM 3.73 s, ADaM 22.88 s). On one thread it takes 2.1 to 2.5 times as long on the sparse input (58.46 s at 11.5M rows) and 2.1 to 3.0 times as long on the dense input. Fleet time depends on the number of subjects: at 2M rows it takes 0.97 s with 50,037 subjects and 4.24 s with 1,218,750 subjects.
- **Oak + Admiral:** about 27 to 32 s per million rows on the sparse input. Most of the time is in the ADaM step: 235.01 of 322.20 s at 11.5M rows.
- **Speedup:** 11 to 15 times with 16 threads and 5 to 6 times with one thread, at every size and on both inputs.

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
| Total packages |               23 |                                          56 |
| SDTM engine    | `.sdtm` (Polars) |                              sdtm.oak 0.2.0 |
| ADaM engine    | `.adam` (Polars) |                               admiral 1.4.1 |
| Core runtime   |    Polars (Rust) | dplyr + lubridate + tidyr + stringr (R/C++) |
| I/O library    | Built-in Parquet |                                       arrow |
| Language       |      Python 3.12 |                                     R 4.5.3 |

Oak + Admiral pulls in 56 recursive dependencies (including admiraldev, sdtm.oak, tidyr, stringr, cpp11, pkgbuild, roxygen2, etc.) vs Fleet's 23 (many of which, such as httpx, jsonschema and lxml, are for optional CLI features, not the derivation pipeline itself). Both counts come from the metrics files of this rerun.

---

## 5. rpy2 Observations

The rpy2 benchmark runs the same R code as `admiral_adae_benchmark.R` (oak SDTM + admiral ADaM, same ANL01FL tie order and ASEQ order) from within a Python process via `rpy2.robjects`. rpy2 is not a Fleet dependency; the run used `uv run --with rpy2`. One run per size. Key findings:

1. **Fixed cost at small scale.** At 100K rows, rpy2 takes 9.56 s in total against 2.81 s for Rscript. Most of the gap (6.13 s) is the data load: the script reads the full 11.5M-row Parquet file into the embedded R session at each size.
2. **Smaller share at large scale.** From 500K to 2M rows, the total overhead is 20% to 28%, and the pipeline-only overhead (SDTM + ADaM) is 7% to 16%.
3. **Pipeline time.** At 2M rows the SDTM + ADaM time under rpy2 is 63.33 s (16.62 s + 46.71 s), against a median of 54.56 s for native Rscript.
4. **Practical implication.** rpy2 can embed pharmaverse pipelines in a Python workflow, with a measurable overhead. Native Rscript is the fairer baseline for a speed comparison.

---

## 6. Output Differences

| Aspect                | Fleet                                     | Oak + Admiral                   |
| --------------------- | ----------------------------------------- | ------------------------------- |
| Output columns        | 49 (retains raw source columns + derived) | 24 (only SDTM + ADaM variables) |
| Study day variable    | `ADY` (single)                            | `ASTDY` + `AENDY` (separate)    |
| Date imputation flags | `ASTDTF`, `AENDTF` generated              | Not generated                   |

Fleet carries forward all source columns by default (useful for traceability); Oak + Admiral pipelines explicitly select only target variables. This is a design choice.

**Row-by-row check.** At every size, `run_benchmark.py` compares the full outputs on 17 variables (STUDYID, USUBJID, AETERM, AESTDTC, AEENDTC, AESEV, AESER, AEREL, AEOUT, AEACN, AESEQ, ASTDT, AENDT, TRTEMFL, AESEVN, ANL01FL, ASEQ), for Fleet at both thread counts against oak + admiral, and exits 1 on a difference. Both sides use the same rules:

- TRTEMFL: start on or after TRTSDT, no upper limit (Fleet passes no `trtedt`; the R call sets no `end_window`).
- ANL01FL: the last record by AESEVN, then AESEQ, within USUBJID and AETERM, so one record per group on a tie.
- ASEQ: numbered by AESEQ within USUBJID.

Result of this rerun: all 17 variables have the same value on every row at every checked size: sparse 100K to 5M rows, dense 100K to 2M rows (on the dense input a USUBJID and AETERM group holds several copies of the same record, so the tie rule decides ANL01FL). The check did not run at 11,468,544 rows (section 2). A changed value in one row (ANL01FL, TRTEMFL or ASEQ) of a saved Fleet output makes the check report a difference.

---

## 7. Fairness Notes

To ensure objectivity:

1. **Symmetric SDTM frameworks.** Both sides use CDISC-aware verb-based SDTM mapping (Fleet's `.sdtm` namespace / oak's `assign_no_ct` + `hardcode_no_ct`). Neither uses raw `dplyr::transmute`.
2. **Same data, same I/O format.** Both read the same Parquet files (Snappy-compressed).
3. **Same derivation rules.** AESER recoding, date parsing, TRTEMFL, the severity flag and sequencing follow the rules in section 6; `run_benchmark.py` checks every row at every size.
4. **Both run as clean subprocesses** (no warm JIT caches). The 3 repetitions of a size run in the same process. The rpy2 benchmark runs in a fresh Python process with an embedded R session.
5. **Memory measurement caveat.** R's `gc()` reports GC-tracked allocations only; Python's RSS includes the full process. The numbers are not directly comparable, so this report does not compare them.
6. **Shared machine.** Other jobs ran on the machine during the rerun (section 2). The min-max ranges show the spread between repetitions.
7. **Oak's join-per-column architecture** is inherently more expensive than Fleet's lazy Polars expressions — each `assign_no_ct()` call performs a join on `oak_id_vars`. This is a design trade-off in oak (row-level traceability and provenance), not inefficiency.
8. **Admiral's strength is not raw speed.** It is a mature, regulatory-validated, well-documented CDISC toolkit with broad industry adoption. Performance at clinical-trial scale (thousands to tens of thousands of rows) is rarely a bottleneck.
9. **Fleet's Polars engine** is a Rust-backed columnar engine designed for large-scale data — the speed advantage is expected and reflects the technology choice, not better engineering per se.

---

## 8. Summary

| Dimension             | Fleet                     | Oak + Admiral          | Winner       |
| --------------------- | ------------------------- | ---------------------- | ------------ |
| Speed (2M rows, sparse) | 4.24 s (16 threads), 10.10 s (1 thread) | 54.56 s (native R) | Fleet (13× / 5×) |
| Speed (2M rows, dense)  | 0.97 s (16 threads), 2.91 s (1 thread)  | 14.62 s (native R) | Fleet (15× / 5×) |
| Speed (11.5M rows, sparse) | 26.61 s (16 threads), 58.46 s (1 thread) | 322.20 s (1 run) | Fleet (12× / 6×) |
| Speed via rpy2 (2M rows) | —                      | 67.08 s (+23% vs native) | Native R   |
| Scaling linearity     | Near-linear               | Near-linear            | Comparable   |
| Same 17 ADAE variables | Every row, every checked size | Every row, every checked size | Comparable |
| Pipeline LOC          | 55                        | 89                     | Fleet        |
| Dependency count      | 23                        | 56                     | Fleet        |
| SDTM framework        | `.sdtm` namespace         | sdtm.oak               | Comparable   |
| Regulatory maturity   | Emerging                  | Established            | Oak+Admiral  |
| Community / ecosystem | Small                     | Large (pharmaverse)    | Oak+Admiral  |
| CDISC CT integration  | Built-in codelist classes | External lookups       | Fleet        |

On this workload Fleet is 11 to 15 times faster than oak + admiral with 16 threads and 5 to 6 times faster on one thread, with fewer lines of pipeline code and a lighter dependency tree. Oak + Admiral remains the pharmaverse standard with deeper regulatory acceptance and a broader R-based ecosystem. The rpy2 bridge works and adds 20% to 28% to the total time from 500K to 2M rows, so native Rscript is the baseline for the speed comparison.

---

## Versions

| Component | Version                       |
| --------- | ----------------------------- |
| Fleet     | 0.1.dev371 (`wip/high2-bench`) |
| Polars    | 1.44.2                        |
| Python    | 3.12.16                       |
| sdtm.oak  | 0.2.0                         |
| Admiral   | 1.4.1                         |
| dplyr     | 1.2.1                         |
| arrow (R) | 24.0.0                        |
| R         | 4.5.3                         |
| rpy2      | 3.6.7                         |
