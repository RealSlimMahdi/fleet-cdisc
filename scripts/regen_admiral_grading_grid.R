# Freeze admiral toxicity grades on a seeded grid, as the oracle for Fleet's tests.
#
# Usage (from the repository root, with R, admiral and arrow installed):
#   Rscript scripts/regen_admiral_grading_grid.R
#
# For every entry of the 8 admiral tables, the grid holds random rows and rows
# on each cut-off of its GRADE_CRITERIA_CODE (the literal, and the literal as a
# multiple of ANRHI, ANRLO and BASE), with every BNRIND, SEX, age band and unit
# spelling. admiral::derive_var_atoxgr_dir grades it in both directions. CI
# reads the parquet with no R: tests/unit/test_grading_admiral_grid.py.

suppressMessages({
  library(admiral)
  library(arrow)
  library(dplyr)
})

OUT <- file.path("tests", "fixtures", "goldens", "grading", "admiral_grid.parquet")
SYSTEMS <- c(
  ctcae_v4 = "atoxgr_criteria_ctcv4",
  ctcae_v4_uscv = "atoxgr_criteria_ctcv4_uscv",
  ctcae_v5 = "atoxgr_criteria_ctcv5",
  ctcae_v5_uscv = "atoxgr_criteria_ctcv5_uscv",
  ctcae_v6 = "atoxgr_criteria_ctcv6",
  ctcae_v6_uscv = "atoxgr_criteria_ctcv6_uscv",
  daids = "atoxgr_criteria_daids",
  daids_uscv = "atoxgr_criteria_daids_uscv"
)
ADT <- as.Date("2020-06-15")
AGE_DAYS <- c(0, 3, 7, 8, 15, 21, 22, 30, 35, 36, 45, 56, 57, 90, 200, 364, 400, 730,
              1825, 4380, 4744, 4749, 5110, 6575, 6580, 14600)
REF <- c(ANRHI = 40, ANRLO = 10, BASE = 30)

literals <- function(e) {
  if (is.numeric(e)) return(abs(e))
  if (is.call(e)) return(unlist(lapply(as.list(e)[-1], literals)))
  numeric()
}

entry_rows <- function(row, n_random = 50) {
  k <- unique(literals(parse(text = row$GRADE_CRITERIA_CODE)[[1]]))
  k <- k[k > 0]
  if (!length(k)) k <- 1
  lo <- min(k) / 20
  hi <- max(k) * 30
  anrhi <- exp(runif(n_random, log(lo * 2), log(max(hi / 10, lo * 4))))
  rel <- runif(n_random) < 0.5
  aval <- ifelse(
    rel,
    anrhi * exp(runif(n_random, log(0.05), log(40))),
    exp(runif(n_random, log(lo), log(hi)))
  )
  random <- tibble(
    AVAL = aval, ANRHI = anrhi, ANRLO = anrhi * runif(n_random, 0.2, 0.7),
    BASE = anrhi * exp(runif(n_random, log(0.2), log(5)))
  )
  steps <- c(0.999, 1, 1.001)
  edges <- c(k %o% steps, (k * REF[["ANRHI"]]) %o% steps, (k * REF[["ANRLO"]]) %o% steps,
             (k * REF[["BASE"]]) %o% steps)
  boundary <- tibble(
    AVAL = as.vector(edges), ANRHI = REF[["ANRHI"]], ANRLO = REF[["ANRLO"]], BASE = REF[["BASE"]]
  )
  rows <- bind_rows(random, boundary)
  n <- nrow(rows)
  unit <- row$UNIT_CHECK
  units <- if (is.na(unit)) c("g/L", NA) else c(unit, toupper(unit), tolower(unit), "XYZ", NA)
  unit_prob <- if (is.na(unit)) c(0.9, 0.1) else c(0.55, 0.15, 0.15, 0.1, 0.05)
  age <- sample(AGE_DAYS, n, replace = TRUE)
  rows %>% mutate(
    TERM = ifelse(runif(n) < 0.05, tolower(row$TERM), row$TERM),
    BASE = ifelse(runif(n) < 0.2, NA_real_, BASE),
    ANRHI = ifelse(runif(n) < 0.05, NA_real_, ANRHI),
    ANRLO = ifelse(runif(n) < 0.05, NA_real_, ANRLO),
    PCHG = (AVAL - BASE) / BASE * 100,
    BNRIND = sample(c("NORMAL", "HIGH", "LOW", "H", "L", NA), n, replace = TRUE),
    SEX = sample(c("M", "F", NA), n, replace = TRUE, prob = c(0.45, 0.45, 0.1)),
    ADT = ADT,
    BRTHDT = as.Date(ifelse(runif(n) < 0.05, NA, ADT - age), origin = "1970-01-01"),
    AVALU = sample(units, n, replace = TRUE, prob = unit_prob)
  )
}

grade <- function(grid, meta, direction, new_var) {
  out <- derive_var_atoxgr_dir(
    grid,
    new_var = !!sym(new_var),
    tox_description_var = TERM,
    meta_criteria = meta,
    criteria_direction = direction,
    high_indicator = c("HIGH", "H"),
    low_indicator = c("LOW", "L"),
    get_unit_expr = AVALU
  )
  out %>% select(ROWID, all_of(new_var))
}

set.seed(20261103)
parts <- list()
for (system in names(SYSTEMS)) {
  meta <- getExportedValue("admiral", SYSTEMS[[system]])
  grid <- bind_rows(lapply(seq_len(nrow(meta)), function(i) entry_rows(meta[i, ]))) %>%
    mutate(SYSTEM = system, ROWID = row_number())
  low <- suppressWarnings(grade(grid, meta, "L", "ATOXGRL"))
  high <- suppressWarnings(grade(grid, meta, "H", "ATOXGRH"))
  grid <- grid %>%
    mutate(KEPT_L = ROWID %in% low$ROWID, KEPT_H = ROWID %in% high$ROWID) %>%
    left_join(low, by = "ROWID") %>%
    left_join(high, by = "ROWID")
  cat(sprintf("%-14s %6d rows, admiral dropped L %d H %d\n", system, nrow(grid),
              sum(!grid$KEPT_L), sum(!grid$KEPT_H)))
  parts[[system]] <- grid
}
out <- bind_rows(parts) %>%
  select(SYSTEM, ROWID, TERM, AVAL, ANRLO, ANRHI, BASE, PCHG, BNRIND, SEX, BRTHDT, ADT, AVALU,
         ATOXGRL, ATOXGRH, KEPT_L, KEPT_H)
dir.create(dirname(OUT), recursive = TRUE, showWarnings = FALSE)
write_parquet(out, OUT, compression = "zstd")
cat("wrote", nrow(out), "rows to", OUT, "\n")
