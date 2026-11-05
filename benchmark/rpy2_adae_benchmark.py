"""
rpy2 benchmark — Run the same Oak + Admiral R pipeline from Python via rpy2.

This measures the overhead of calling R through Python's rpy2 interface
compared to running the same R code natively via Rscript.

The R code executed is identical to admiral_adae_benchmark.R.

Usage:
    uv run python benchmark/rpy2_adae_benchmark.py [max_rows]
    uv run python benchmark/rpy2_adae_benchmark.py           # default: 2M cap
    uv run python benchmark/rpy2_adae_benchmark.py 500000    # cap at 500K
"""

from __future__ import annotations

import json
import platform
import sys
import time
from pathlib import Path

# ── rpy2 setup ───────────────────────────────────────────────────────────────
import rpy2.robjects as ro
from rpy2.robjects import r as R

# Suppress R startup messages
ro.r("suppressPackageStartupMessages(library(sdtm.oak))")
ro.r("suppressPackageStartupMessages(library(admiral))")
ro.r("suppressPackageStartupMessages(library(dplyr))")
ro.r("suppressPackageStartupMessages(library(lubridate))")
ro.r("suppressPackageStartupMessages(library(arrow))")

DATA = Path(__file__).parent / "data"
SCALE_FACTORS = [100_000, 500_000, 1_000_000, 2_000_000]


def run_pipeline_rpy2(n_rows: int, ae_parquet: str, adsl_parquet: str) -> dict:
    """Run the oak+admiral pipeline at a given scale via rpy2, return metrics."""

    t_total = time.perf_counter()

    # ── Load + subset data in R ──────────────────────────────────────────
    R(f"""
    ae_full  <- arrow::read_parquet("{ae_parquet}")
    adsl_full <- arrow::read_parquet("{adsl_parquet}")

    if ({n_rows} < nrow(ae_full)) {{
      ae_raw <- head(ae_full, {n_rows})
    }} else {{
      ae_raw <- ae_full
    }}
    ae_subj  <- unique(ae_raw$subject_id)
    adsl     <- adsl_full[adsl_full$USUBJID %in% ae_subj, ]

    n_ae_rows   <- nrow(ae_raw)
    n_adsl_rows <- nrow(adsl)
    """)

    n_ae = int(R("n_ae_rows")[0])
    n_adsl = int(R("n_adsl_rows")[0])

    # ── SDTM step (oak verbs — identical to admiral_adae_benchmark.R) ────
    t_sdtm = time.perf_counter()

    R("""
    invisible(gc(reset = TRUE))

    ae_oak <- ae_raw %>%
      dplyr::mutate(
        oak_id         = dplyr::row_number(),
        raw_source     = "AE_RAW",
        patient_number = as.integer(factor(subject_id))
      )

    ae_sdtm <-
      sdtm.oak::hardcode_no_ct(
        raw_dat = ae_oak, raw_var = "event_term",
        tgt_var = "STUDYID", tgt_val = "STUDY001"
      ) |>
      sdtm.oak::hardcode_no_ct(
        tgt_dat = _, raw_dat = ae_oak, raw_var = "event_term",
        tgt_var = "DOMAIN", tgt_val = "AE"
      ) |>
      sdtm.oak::assign_no_ct(
        tgt_dat = _, raw_dat = ae_oak,
        raw_var = "subject_id", tgt_var = "USUBJID"
      ) |>
      sdtm.oak::assign_no_ct(
        tgt_dat = _, raw_dat = ae_oak,
        raw_var = "event_term", tgt_var = "AETERM"
      ) |>
      sdtm.oak::assign_no_ct(
        tgt_dat = _, raw_dat = ae_oak,
        raw_var = "start_date", tgt_var = "AESTDTC"
      ) |>
      sdtm.oak::assign_no_ct(
        tgt_dat = _, raw_dat = ae_oak,
        raw_var = "end_date", tgt_var = "AEENDTC"
      ) |>
      sdtm.oak::assign_no_ct(
        tgt_dat = _, raw_dat = ae_oak,
        raw_var = "severity", tgt_var = "AESEV"
      ) |>
      sdtm.oak::assign_no_ct(
        tgt_dat = _, raw_dat = ae_oak,
        raw_var = "relationship_to_study_drug", tgt_var = "AEREL"
      ) |>
      sdtm.oak::assign_no_ct(
        tgt_dat = _, raw_dat = ae_oak,
        raw_var = "outcome", tgt_var = "AEOUT"
      ) |>
      sdtm.oak::assign_no_ct(
        tgt_dat = _, raw_dat = ae_oak,
        raw_var = "action_taken", tgt_var = "AEACN"
      ) |>
      sdtm.oak::assign_no_ct(
        tgt_dat = _, raw_dat = ae_oak,
        raw_var = "serious", tgt_var = "AESER"
      ) |>
      dplyr::mutate(AESER = dplyr::if_else(AESER == "Yes", "Y", "N")) |>
      dplyr::select(-oak_id, -raw_source, -patient_number) |>
      sdtm.oak::derive_seq(
        tgt_var  = "AESEQ",
        rec_vars = c("STUDYID", "USUBJID", "AESTDTC"),
        sbj_vars = c("STUDYID", "USUBJID")
      )
    """)
    sdtm_sec = time.perf_counter() - t_sdtm

    # ── ADaM step (admiral verbs — identical to admiral_adae_benchmark.R) ─
    t_adam = time.perf_counter()

    R("""
    adsl_vars <- adsl %>% dplyr::select(USUBJID, TRTSDT, TRTEDT, TRT01P, SAFFL)

    adae <- ae_sdtm %>%
      admiral::derive_vars_merged(
        dataset_add = adsl_vars,
        by_vars     = admiral::exprs(USUBJID),
        new_vars    = admiral::exprs(TRTSDT, TRTEDT, TRT01P, SAFFL)
      ) %>%
      admiral::derive_vars_dt(new_vars_prefix = "AST", dtc = AESTDTC) %>%
      admiral::derive_vars_dt(new_vars_prefix = "AEN", dtc = AEENDTC) %>%
      admiral::derive_vars_dy(
        reference_date = TRTSDT,
        source_vars = admiral::exprs(ASTDT, AENDT)
      ) %>%
      admiral::derive_var_trtemfl(
        trt_start_date = TRTSDT, trt_end_date = TRTEDT,
        start_date = ASTDT, end_date = AENDT
      ) %>%
      dplyr::mutate(
        AESEVN = dplyr::case_when(
          AESEV == "Mild"     ~ 1L,
          AESEV == "Moderate" ~ 2L,
          AESEV == "Severe"   ~ 3L
        )
      ) %>%
      admiral::derive_var_extreme_flag(
        by_vars = admiral::exprs(USUBJID, AETERM),
        order   = admiral::exprs(AESEVN, AESEQ),
        new_var = ANL01FL,
        mode    = "last"
      ) %>%
      admiral::derive_var_obs_number(
        by_vars = admiral::exprs(USUBJID),
        order   = admiral::exprs(AESEQ),
        new_var = ASEQ
      )
    """)
    adam_sec = time.perf_counter() - t_adam
    total_sec = time.perf_counter() - t_total

    # Retrieve output dimensions from R
    out_rows = int(R("nrow(adae)")[0])
    out_cols = int(R("ncol(adae)")[0])
    out_columns = list(R("names(adae)"))

    # R memory info
    R("invisible(gc())")
    peak_mem = float(R("g <- gc(); sum(g[, ncol(g)])")[0])

    return {
        "n_rows": n_ae,
        "n_adsl": n_adsl,
        "out_rows": out_rows,
        "out_cols": out_cols,
        "sdtm_sec": round(sdtm_sec, 3),
        "adam_sec": round(adam_sec, 3),
        "total_sec": round(total_sec, 3),
        "peak_r_gc_mb": round(peak_mem, 1),
        "columns": out_columns,
    }


def main():
    max_rows = int(sys.argv[1]) if len(sys.argv) > 1 else 2_000_000

    ae_parquet = str(DATA / "ae_inflated.parquet")
    adsl_parquet = str(DATA / "adsl_inflated.parquet")

    factors = [s for s in SCALE_FACTORS if s <= max_rows]
    if not factors:
        factors = [max_rows]

    # Versions
    import importlib.metadata

    rpy2_ver = importlib.metadata.version("rpy2")
    oak_ver = str(R('as.character(packageVersion("sdtm.oak"))')[0])
    admiral_ver = str(R('as.character(packageVersion("admiral"))')[0])
    r_ver = str(R("R.version.string")[0])

    print(f"rpy2 {rpy2_ver} | oak {oak_ver} | admiral {admiral_ver} | {r_ver}")
    print(f"Scale factors: {factors}")

    scaling = []
    last_result = None

    for n in factors:
        print(f"\n── Scale: {n:,} rows ──────────────────────────────────")
        result = run_pipeline_rpy2(n, ae_parquet, adsl_parquet)
        print(
            f"  SDTM: {result['sdtm_sec']:.1f}s  "
            f"ADaM: {result['adam_sec']:.1f}s  "
            f"Total: {result['total_sec']:.1f}s  "
            f"Out: {result['out_rows']}×{result['out_cols']}"
        )
        scaling.append(
            {
                "rows": result["n_rows"],
                "sdtm_sec": result["sdtm_sec"],
                "adam_sec": result["adam_sec"],
                "total_sec": result["total_sec"],
            }
        )
        last_result = result

        # Clean up R memory between runs
        R("rm(ae_raw, ae_oak, ae_sdtm, adae, adsl_vars); invisible(gc())")

    # Build final metrics
    metrics = {
        "tool": "rpy2 → Oak + Admiral",
        "rpy2_version": rpy2_ver,
        "oak_version": oak_ver,
        "admiral_version": admiral_ver,
        "r_version": r_ver,
        "python_version": platform.python_version(),
        "output_rows": last_result["out_rows"],
        "output_cols": last_result["out_cols"],
        "output_columns": last_result["columns"],
        "scaling": scaling,
    }

    json_out = json.dumps(metrics, indent=2, default=str)
    print(f"\n{json_out}")
    (DATA / "rpy2_metrics.json").write_text(json_out)
    print("\n✓ rpy2 benchmark complete")


if __name__ == "__main__":
    main()
