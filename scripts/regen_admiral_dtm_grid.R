# Freeze admiral derive_vars_dtm results on a grid, as the oracle for Fleet's *DTM tests.
#
# Usage (from the repository root, with R and admiral installed):
#   Rscript scripts/regen_admiral_dtm_grid.R
#
# Every --DTC form of the grid (complete, truncated, a hyphen for a missing
# part, blank, null) goes through derive_vars_dtm for each highest_imputation
# level that a *DTM target accepts with no bounds, and for the first and last
# date and time imputation. preserve is FALSE (the admiral default): a part
# below a missing part is not used. CI reads the CSV with no R:
# tests/unit/test_date_dtm_admiral_grid.py.

suppressMessages({
  library(admiral)
  library(dplyr)
})

OUT <- file.path("tests", "fixtures", "goldens", "dates", "admiral_dtm_grid.csv")
DTC <- c(
  "2021-03-15T08:30:45", "2021-03-15T08:30", "2021-03-15T08", "2021-03-15",
  "2021-03--T08:30", "2021-03", "2024-02", "2021---15", "2021---15T08:30", "2021",
  "2021-03-15T-:30", "2021-03-15T08:-:45", "-----T08:30", "", NA
)
grid <- expand.grid(
  highest = c("n", "s", "m", "h", "D", "M"),
  date_imp = c("first", "last"),
  time_imp = c("first", "last"),
  stringsAsFactors = FALSE
)
rows <- lapply(seq_len(nrow(grid)), function(i) {
  g <- grid[i, ]
  r <- derive_vars_dtm(
    tibble(DTC = DTC),
    new_vars_prefix = "A", dtc = DTC,
    highest_imputation = g$highest, date_imputation = g$date_imp,
    time_imputation = g$time_imp, flag_imputation = "both",
    ignore_seconds_flag = FALSE
  )
  tibble(
    highest = g$highest, date_imp = g$date_imp, time_imp = g$time_imp,
    dtc = DTC, adtm = format(r$ADTM, "%Y-%m-%dT%H:%M:%S"),
    adtf = r$ADTF, atmf = r$ATMF
  )
})
dir.create(dirname(OUT), recursive = TRUE, showWarnings = FALSE)
write.csv(bind_rows(rows), OUT, row.names = FALSE, na = "NA")
cat("admiral", as.character(packageVersion("admiral")), "wrote", OUT, "\n")
