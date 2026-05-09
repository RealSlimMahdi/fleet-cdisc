#!/usr/bin/env Rscript
# Quick validation of the Admiral pipeline on a small subset

suppressPackageStartupMessages({
  library(admiral)
  library(dplyr)
  library(lubridate)
  library(arrow)
})
cat("Libraries loaded\n")

DATA <- "benchmark/data"

# Read only a small slice
cat("Reading data...\n")
ae_full <- arrow::read_parquet(file.path(DATA, "ae_inflated.parquet"))
ae_raw  <- head(ae_full, 5000)
rm(ae_full); invisible(gc())

adsl_full <- arrow::read_parquet(file.path(DATA, "adsl_inflated.parquet"))
# Only keep subjects that appear in our AE subset
ae_subj <- unique(ae_raw$subject_id)
adsl <- adsl_full[adsl_full$USUBJID %in% ae_subj, ]
rm(adsl_full); invisible(gc())

cat(sprintf("AE : %d rows, cols: %s\n", nrow(ae_raw), paste(names(ae_raw), collapse=", ")))
cat(sprintf("ADSL: %d rows, cols: %s\n", nrow(adsl), paste(names(adsl), collapse=", ")))
cat(sprintf("TRTSDT class: %s\n", paste(class(adsl$TRTSDT), collapse=",")))

# SDTM
ae_sdtm <- ae_raw %>%
  transmute(
    STUDYID = "STUDY001",
    DOMAIN  = "AE",
    USUBJID = subject_id,
    AETERM  = event_term,
    AESTDTC = start_date,
    AEENDTC = end_date,
    AESEV   = severity,
    AESER   = if_else(serious == "Yes", "Y", "N"),
    AEREL   = relationship_to_study_drug,
    AEOUT   = outcome,
    AEACN   = action_taken
  ) %>%
  group_by(USUBJID) %>%
  arrange(AESTDTC, .by_group = TRUE) %>%
  mutate(AESEQ = row_number()) %>%
  ungroup()
cat(sprintf("SDTM: %d rows OK\n", nrow(ae_sdtm)))

# ADaM
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
    order   = exprs(AESEVN),
    new_var = ANL01FL,
    mode    = "last"
  ) %>%
  derive_var_obs_number(
    by_vars = exprs(USUBJID),
    new_var = ASEQ
  )

cat(sprintf("ADAE: %d rows x %d cols\n", nrow(adae), ncol(adae)))
cat(sprintf("Columns: %s\n", paste(names(adae), collapse=", ")))
print(head(adae %>% select(USUBJID, AETERM, ASTDT, ASTDY, TRTEMFL, AESEVN, ANL01FL, ASEQ), 5))
cat("\n✓ Pipeline validation OK\n")
