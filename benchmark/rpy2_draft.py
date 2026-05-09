"""
rpy2 draft — runs the Admiral ADAE pipeline inside Python for verification.

WARNING: rpy2 adds data serialisation overhead (Python↔R copies), so timings
here are NOT directly comparable to the vanilla Rscript run. Use this to:
  1. Verify the R code is correct before running standalone
  2. Cross-check output equivalence within a single process

Prerequisites:
    uv add rpy2
    # R must have: admiral, dplyr, lubridate installed

Usage:
    uv run python benchmark/rpy2_draft.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import polars as pl

DATA = Path(__file__).parent / "data"


def run_admiral_via_rpy2() -> dict:
    import rpy2.robjects as ro
    from rpy2.robjects import pandas2ri
    from rpy2.robjects.packages import importr

    pandas2ri.activate()

    # Import R packages
    importr("admiral")
    importr("dplyr")
    importr("lubridate")

    # Read data in Python, convert to R via pandas bridge
    t_io = time.perf_counter()
    ae_raw_pl = pl.read_parquet(DATA / "ae_inflated.parquet")
    adsl_pl = pl.read_parquet(DATA / "adsl_inflated.parquet")

    ae_raw_pd = ae_raw_pl.to_pandas()
    adsl_pd = adsl_pl.to_pandas()

    with (ro.default_converter + pandas2ri.converter).context():
        ae_raw_r = ro.conversion.get_conversion().py2rpy(ae_raw_pd)
        adsl_r = ro.conversion.get_conversion().py2rpy(adsl_pd)

    io_sec = time.perf_counter() - t_io
    print(f"  I/O + conversion: {io_sec:.1f}s")

    ro.globalenv["ae_raw"] = ae_raw_r
    ro.globalenv["adsl"] = adsl_r

    t_pipeline = time.perf_counter()

    ro.r("""
    suppressPackageStartupMessages({
      library(admiral)
      library(dplyr)
      library(lubridate)
    })

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
    """)
    pipeline_sec = time.perf_counter() - t_pipeline

    with (ro.default_converter + pandas2ri.converter).context():
        adae_pd = ro.conversion.get_conversion().rpy2py(ro.globalenv["adae"])

    adae_result = pl.from_pandas(adae_pd)

    print(f"  Pipeline time (rpy2): {pipeline_sec:.1f}s")
    print(f"  Output shape: {adae_result.shape}")
    print(f"  Columns: {adae_result.columns}")

    return {
        "tool": "Admiral via rpy2 (overhead included)",
        "time_io_conversion_sec": round(io_sec, 3),
        "time_pipeline_sec": round(pipeline_sec, 3),
        "output_rows": adae_result.height,
        "output_cols": adae_result.width,
        "note": "rpy2 adds data serialisation overhead; vanilla Rscript is the canonical R timing",
    }


if __name__ == "__main__":
    result = run_admiral_via_rpy2()
    print(json.dumps(result, indent=2))
