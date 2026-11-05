#!/usr/bin/env Rscript
# ─────────────────────────────────────────────────────────────────────────────
# Oak + Admiral (R) ADAE benchmark — Multi-scale
#
# Uses the full pharmaverse stack:
#   SDTM: sdtm.oak (assign_no_ct, hardcode_no_ct, condition_add, derive_seq)
#   ADaM: admiral  (derive_vars_dt, derive_vars_dy, derive_var_trtemfl, etc.)
#
# Reproduces the same core ADAE derivations as the Fleet benchmark:
#   SDTM: STUDYID, DOMAIN, USUBJID, AETERM, AESTDTC, AEENDTC, AESEV, AESER,
#         AEREL, AEOUT, AEACN, AESEQ
#   ADaM: ASTDT, AENDT, ADY, TRTEMFL, AESEVN, ANL01FL, ASEQ
#
# Runs the pipeline at multiple scale factors for a scaling curve.
#
# Prerequisites:
#   install.packages(c("sdtm.oak", "admiral", "dplyr", "lubridate",
#                      "arrow", "jsonlite"))
#
# Usage:
#   Rscript benchmark/admiral_adae_benchmark.R [max_rows] [--reps=N] [--input=NAME] [--tag=TAG]
#   Rscript benchmark/admiral_adae_benchmark.R           # default: all rows
#   Rscript benchmark/admiral_adae_benchmark.R 500000    # cap at 500K rows
#
# --input=NAME reads ae_NAME.parquet and adsl_NAME.parquet (default: inflated).
# Each scale runs --reps times (default 3); the output of the last run at each
# scale goes to admiral_adae_check[_TAG]_<rows>.parquet for run_benchmark.py.
# ─────────────────────────────────────────────────────────────────────────────

suppressPackageStartupMessages({
  library(sdtm.oak)
  library(admiral)
  library(dplyr)
  library(lubridate)
  library(arrow)
  library(jsonlite)
})

# Prevent scientific notation in output (e.g. 1e+05 → 100000)
options(scipen = 999)

# ── Parse CLI args ───────────────────────────────────────────────────────────
args <- commandArgs(trailingOnly = TRUE)
opt <- function(name, default) {
  hit <- grep(paste0("^--", name, "="), args, value = TRUE)
  if (length(hit)) sub(paste0("^--", name, "="), "", hit[1]) else default
}
positional <- grep("^--", args, value = TRUE, invert = TRUE)
max_rows <- if (length(positional) >= 1) as.integer(positional[1]) else NULL
reps <- as.integer(opt("reps", "3"))
input <- opt("input", "inflated")
tag <- opt("tag", "")
suffix <- if (nzchar(tag)) paste0("_", tag) else ""

# ── Resolve data directory ───────────────────────────────────────────────────
script_dir <- tryCatch(
  dirname(sys.frame(1)$ofile),
  error = function(e) "benchmark"
)
DATA <- file.path(script_dir, "data")
if (!dir.exists(DATA)) DATA <- "benchmark/data"

# ── Read full data once ──────────────────────────────────────────────────────
cat("Reading data...\n")
ae_full  <- arrow::read_parquet(file.path(DATA, paste0("ae_", input, ".parquet")))
adsl_full <- arrow::read_parquet(file.path(DATA, paste0("adsl_", input, ".parquet")))
cat(sprintf("  Full AE  : %s rows\n", format(nrow(ae_full), big.mark = ",")))
cat(sprintf("  Full ADSL: %s rows\n", format(nrow(adsl_full), big.mark = ",")))

# ── Scale factors ────────────────────────────────────────────────────────────
full_n <- nrow(ae_full)
scale_factors <- c(100000, 500000, 1000000, 2000000, 5000000)
scale_factors <- c(scale_factors[scale_factors < full_n], full_n)
if (!is.null(max_rows)) {
  scale_factors <- scale_factors[scale_factors <= max_rows]
  if (length(scale_factors) == 0) scale_factors <- max_rows
}

# ── Pipeline function ────────────────────────────────────────────────────────
run_pipeline <- function(ae_raw, adsl, n_label) {
  invisible(gc(reset = TRUE))
  t_total <- proc.time()

  n_ae_rows   <- nrow(ae_raw)
  n_adsl_rows <- nrow(adsl)

  # ── SDTM (using sdtm.oak verbs) ──────────────────────────────────────────
  t_sdtm <- proc.time()

  # Oak requires oak_id_vars in the raw data
  ae_oak <- ae_raw %>%
    mutate(
      oak_id         = row_number(),
      raw_source     = "AE_RAW",
      patient_number = as.integer(factor(subject_id))
    )

  # Build AE SDTM domain using oak verbs (mirrors Fleet's .sdtm namespace)
  ae_sdtm <-
    # hardcode_no_ct: same verb name as Fleet's .hardcode_no_ct()
    hardcode_no_ct(
      raw_dat = ae_oak, raw_var = "event_term",
      tgt_var = "STUDYID", tgt_val = "STUDY001"
    ) |>
    hardcode_no_ct(
      tgt_dat = _, raw_dat = ae_oak, raw_var = "event_term",
      tgt_var = "DOMAIN", tgt_val = "AE"
    ) |>
    # assign_no_ct: same verb name as Fleet's .assign_no_ct()
    assign_no_ct(
      tgt_dat = _, raw_dat = ae_oak,
      raw_var = "subject_id", tgt_var = "USUBJID"
    ) |>
    assign_no_ct(
      tgt_dat = _, raw_dat = ae_oak,
      raw_var = "event_term", tgt_var = "AETERM"
    ) |>
    assign_no_ct(
      tgt_dat = _, raw_dat = ae_oak,
      raw_var = "start_date", tgt_var = "AESTDTC"
    ) |>
    assign_no_ct(
      tgt_dat = _, raw_dat = ae_oak,
      raw_var = "end_date", tgt_var = "AEENDTC"
    ) |>
    assign_no_ct(
      tgt_dat = _, raw_dat = ae_oak,
      raw_var = "severity", tgt_var = "AESEV"
    ) |>
    assign_no_ct(
      tgt_dat = _, raw_dat = ae_oak,
      raw_var = "relationship_to_study_drug", tgt_var = "AEREL"
    ) |>
    assign_no_ct(
      tgt_dat = _, raw_dat = ae_oak,
      raw_var = "outcome", tgt_var = "AEOUT"
    ) |>
    assign_no_ct(
      tgt_dat = _, raw_dat = ae_oak,
      raw_var = "action_taken", tgt_var = "AEACN"
    ) |>
    # AESER recode (condition_add + hardcode is canonical oak, but
    # if_else is standard practice when oak lacks a direct recode verb)
    assign_no_ct(
      tgt_dat = _, raw_dat = ae_oak,
      raw_var = "serious", tgt_var = "AESER"
    ) |>
    mutate(AESER = if_else(AESER == "Yes", "Y", "N")) |>
    # Drop oak ID columns before derive_seq
    select(-oak_id, -raw_source, -patient_number) |>
    # derive_seq: same verb name as Fleet's .seq()
    derive_seq(
      tgt_var  = "AESEQ",
      rec_vars = c("STUDYID", "USUBJID", "AESTDTC"),
      sbj_vars = c("STUDYID", "USUBJID")
    )
  sdtm_sec <- (proc.time() - t_sdtm)["elapsed"]

  # ── ADaM ────────────────────────────────────────────────────────────────
  t_adam <- proc.time()
  adsl_vars <- adsl %>% select(USUBJID, TRTSDT, TRTEDT, TRT01P, SAFFL)

  adae <- ae_sdtm %>%
    derive_vars_merged(
      dataset_add = adsl_vars,
      by_vars     = exprs(USUBJID),
      new_vars    = exprs(TRTSDT, TRTEDT, TRT01P, SAFFL)
    ) %>%
    derive_vars_dt(new_vars_prefix = "AST", dtc = AESTDTC) %>%
    derive_vars_dt(new_vars_prefix = "AEN", dtc = AEENDTC) %>%
    derive_vars_dy(reference_date = TRTSDT, source_vars = exprs(ASTDT, AENDT)) %>%
    derive_var_trtemfl(
      trt_start_date = TRTSDT, trt_end_date = TRTEDT,
      start_date = ASTDT, end_date = AENDT
    ) %>%
    mutate(
      AESEVN = case_when(
        AESEV == "Mild"     ~ 1L,
        AESEV == "Moderate" ~ 2L,
        AESEV == "Severe"   ~ 3L
      )
    ) %>%
    derive_var_extreme_flag(
      by_vars = exprs(USUBJID, AETERM),
      order   = exprs(AESEVN, AESEQ),
      new_var = ANL01FL,
      mode    = "last"
    ) %>%
    derive_var_obs_number(
      by_vars = exprs(USUBJID), order = exprs(AESEQ),
      new_var = ASEQ
    )
  adam_sec <- (proc.time() - t_adam)["elapsed"]
  total_sec <- (proc.time() - t_total)["elapsed"]

  invisible(gc())
  gc_info <- gc()
  peak_mem_mb <- sum(gc_info[, ncol(gc_info)])  # "max used (Mb)"

  list(
    n_rows    = n_ae_rows,
    n_adsl    = n_adsl_rows,
    out_rows  = nrow(adae),
    out_cols  = ncol(adae),
    sdtm_sec  = round(as.numeric(sdtm_sec), 3),
    adam_sec   = round(as.numeric(adam_sec), 3),
    total_sec  = round(as.numeric(total_sec), 3),
    peak_mb   = round(peak_mem_mb, 1),
    columns   = names(adae),
    adae      = adae
  )
}

# ── Run at each scale factor ─────────────────────────────────────────────────
results <- list()
for (n in scale_factors) {
  cat(sprintf("\n── Scale: %s rows ──────────────────────────────────────────\n",
              format(n, big.mark = ",")))

  if (n >= nrow(ae_full)) {
    ae_sub <- ae_full
  } else {
    ae_sub <- head(ae_full, n)
  }

  # Subset ADSL to only matching subjects
  ae_subj <- unique(ae_sub$subject_id)
  adsl_sub <- adsl_full[adsl_full$USUBJID %in% ae_subj, ]

  runs <- list()
  for (i in seq_len(reps)) {
    res <- run_pipeline(ae_sub, adsl_sub, n)
    cat(sprintf("  SDTM: %.2fs  ADaM: %.2fs  Total: %.2fs  Mem: %.0f MB  Out: %d×%d\n",
                res$sdtm_sec, res$adam_sec, res$total_sec, res$peak_mb, res$out_rows, res$out_cols))
    runs[[i]] <- res[setdiff(names(res), "adae")]
  }
  # Output of the last run at each scale, for the row-by-row check in run_benchmark.py
  check_cols <- c("STUDYID", "USUBJID", "AETERM", "AESTDTC", "AEENDTC", "AESEV",
                  "AESER", "AEREL", "AEOUT", "AEACN", "AESEQ", "ASTDT", "AENDT",
                  "TRTEMFL", "AESEVN", "ANL01FL", "ASEQ")
  arrow::write_parquet(
    res$adae[, check_cols],
    file.path(DATA, sprintf("admiral_adae_check%s_%d.parquet", suffix, as.integer(n)))
  )
  totals <- vapply(runs, function(r) r$total_sec, numeric(1))
  results[[as.character(n)]] <- list(
    n_rows    = res$n_rows,
    n_adsl    = res$n_adsl,
    out_rows  = res$out_rows,
    out_cols  = res$out_cols,
    peak_mb   = res$peak_mb,
    columns   = res$columns,
    sdtm_sec  = median(vapply(runs, function(r) r$sdtm_sec, numeric(1))),
    adam_sec  = median(vapply(runs, function(r) r$adam_sec, numeric(1))),
    total_sec = median(totals),
    total_min_sec = min(totals),
    total_max_sec = max(totals),
    total_runs_sec = totals
  )

  # Clean up
  rm(ae_sub, adsl_sub, res, runs); invisible(gc())
}

# ── Save the last (largest) run as the canonical result ──────────────────────
last <- results[[length(results)]]

# Recursive dependency count
core_pkgs <- c("sdtm.oak", "admiral", "dplyr", "lubridate", "arrow", "jsonlite")
all_deps  <- unique(c(
  core_pkgs,
  unlist(tools::package_dependencies(core_pkgs, recursive = TRUE))
))

# Build scaling table
scaling <- lapply(names(results), function(k) {
  r <- results[[k]]
  list(rows = r$n_rows, subjects = r$n_adsl, sdtm_sec = r$sdtm_sec,
       adam_sec = r$adam_sec, total_sec = r$total_sec,
       total_min_sec = r$total_min_sec, total_max_sec = r$total_max_sec,
       total_runs_sec = r$total_runs_sec, peak_mb = r$peak_mb)
})

metrics <- list(
  tool                  = "Oak + Admiral (R / pharmaverse)",
  oak_version           = as.character(packageVersion("sdtm.oak")),
  admiral_version       = as.character(packageVersion("admiral")),
  r_version             = R.version.string,
  repetitions           = reps,
  input                 = input,
  input_rows_ae         = last$n_rows,
  input_rows_adsl       = last$n_adsl,
  output_rows           = last$out_rows,
  output_cols           = last$out_cols,
  time_sdtm_sec         = last$sdtm_sec,
  time_adam_sec          = last$adam_sec,
  time_total_sec        = last$total_sec,
  peak_memory_gc_mb     = last$peak_mb,
  # Non-blank, non-comment lines between the timers of run_pipeline
  pipeline_loc_sdtm     = 58,
  pipeline_loc_adam      = 31,
  pipeline_loc_total    = 89,
  n_total_dependencies  = length(all_deps),
  dependency_names      = sort(all_deps),
  output_columns        = last$columns,
  scaling               = scaling
)

json_out <- toJSON(metrics, auto_unbox = TRUE, pretty = TRUE)
cat("\n", json_out, "\n")

write(json_out, file.path(DATA, paste0("admiral_metrics", suffix, ".json")))

cat("\n✓ Admiral benchmark complete\n")
