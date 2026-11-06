"""
Fleet / Polars ADAE benchmark — Multi-scale.

Reproduces core ADAE derivations (matching the Admiral benchmark exactly):
  SDTM: STUDYID, DOMAIN, USUBJID, AETERM, AESTDTC, AEENDTC, AESEV, AESER,
        AEREL, AEOUT, AEACN, AESEQ
  ADaM: ASTDT, AENDT, ADY, TRTEMFL, AESEVN, ANL01FL, ASEQ

Runs the pipeline at multiple scale factors for a scaling curve.

Usage:
    uv run python benchmark/fleet_adae_benchmark.py [max_rows] [--reps N] [--input NAME] [--tag TAG]
    uv run python benchmark/fleet_adae_benchmark.py            # all rows
    uv run python benchmark/fleet_adae_benchmark.py 500000     # cap at 500K
    POLARS_MAX_THREADS=1 uv run python benchmark/fleet_adae_benchmark.py --tag 1thread

--input NAME reads ae_NAME.parquet and adsl_NAME.parquet (default: inflated).
Each scale runs --reps times (default 3); the output of the last run at each
scale goes to fleet_adae_check[_TAG]_<rows>.parquet for run_benchmark.py.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl

import fleet  # noqa: F401 — registers namespace extensions

DATA = Path(__file__).parent / "data"

SCALE_FACTORS = [100_000, 500_000, 1_000_000, 2_000_000, 5_000_000]


def run_pipeline(ae_raw: pl.DataFrame, adsl: pl.DataFrame) -> dict:
    """Run the full SDTM + ADaM pipeline on the given data, return metrics."""
    tracemalloc.start()
    t_total = time.perf_counter()

    n_ae = ae_raw.height
    n_adsl = adsl.height

    # ── SDTM AE ───────────────────────────────────────────────────────
    t_sdtm = time.perf_counter()
    ae = (
        ae_raw.sdtm.assign("STUDYID", value="STUDY001")
        .assign("DOMAIN", value="AE")
        .assign("USUBJID", source="subject_id")
        .assign("AETERM", source="event_term")
        .assign("AESTDTC", source="start_date")
        .assign("AEENDTC", source="end_date")
        .assign("AESEV", source="severity")
        .derivation(
            "AESER",
            expression=pl.when(pl.col("serious") == "Yes").then(pl.lit("Y")).otherwise(pl.lit("N")),
        )
        .assign("AEREL", source="relationship_to_study_drug")
        .assign("AEOUT", source="outcome")
        .assign("AEACN", source="action_taken")
        .seq("AESEQ", order_by=["AESTDTC"])
        .to_frame()
    )
    sdtm_sec = time.perf_counter() - t_sdtm

    # ── ADaM ADAE ─────────────────────────────────────────────────────
    t_adam = time.perf_counter()
    _adsl_cols = adsl.select(["USUBJID", "TRTSDT", "TRTEDT", "TRT01P", "SAFFL"])
    ae_merged = ae.join(_adsl_cols, on="USUBJID", how="left")

    adae = (
        ae_merged.adam.assign("STUDYID", value="STUDY001")
        .source("USUBJID")
        .source("AETERM")
        .source("AESTDTC")
        .source("AEENDTC")
        .source("AESEV")
        .source("AESER")
        .source("AEREL")
        .source("AEOUT")
        .source("AEACN")
        .date("ASTDT", source="AESTDTC")
        .date("AENDT", source="AEENDTC")
        .duration("ADY", start="TRTSDT", end="ASTDT")
        .to_frame()
        .adam.occds.treatment_emergent(
            "TRTEMFL",
            start_date="ASTDT",
            end_date="AENDT",
            trtsdt="TRTSDT",
        )
        .recode(
            "AESEVN",
            source="AESEV",
            recode_map={"Mild": 1, "Moderate": 2, "Severe": 3},
        )
        .flag(
            "ANL01FL",
            criteria="last",
            order_by=["AESEVN", "AESEQ"],
            by=["USUBJID", "AETERM"],
        )
        .seq("ASEQ", by=["USUBJID"], order_by=["AESEQ"])
        .to_frame()
    )
    adam_sec = time.perf_counter() - t_adam
    total_sec = time.perf_counter() - t_total

    _, peak_traced = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    rusage = resource.getrusage(resource.RUSAGE_SELF)
    peak_rss = rusage.ru_maxrss
    if platform.system() == "Darwin":
        peak_rss_mb = peak_rss / 1e6
    else:
        peak_rss_mb = peak_rss / 1e3

    return {
        "n_rows": n_ae,
        "n_adsl": n_adsl,
        "out_rows": adae.height,
        "out_cols": adae.width,
        "sdtm_sec": round(sdtm_sec, 3),
        "adam_sec": round(adam_sec, 3),
        "total_sec": round(total_sec, 3),
        "peak_traced_mb": round(peak_traced / 1e6, 1),
        "peak_rss_mb": round(peak_rss_mb, 1),
        "columns": adae.columns,
        "adae": adae,
    }


CHECK_COLS = [
    "STUDYID", "USUBJID", "AETERM", "AESTDTC", "AEENDTC", "AESEV", "AESER",
    "AEREL", "AEOUT", "AEACN", "AESEQ", "ASTDT", "AENDT", "TRTEMFL",
    "AESEVN", "ANL01FL", "ASEQ",
]  # fmt: skip


def run(args: argparse.Namespace) -> dict:
    # ── Read full data ────────────────────────────────────────────────
    ae_full = pl.read_parquet(DATA / f"ae_{args.input}.parquet")
    adsl_full = pl.read_parquet(DATA / f"adsl_{args.input}.parquet")
    suffix = f"_{args.tag}" if args.tag else ""

    full_n = ae_full.height
    print(f"  Full AE  : {full_n:,} rows")
    print(f"  Full ADSL: {adsl_full.height:,} rows")
    print(f"  Polars threads: {pl.thread_pool_size()}  Repetitions: {args.reps}")

    max_rows = args.max_rows
    factors = [s for s in SCALE_FACTORS if s < full_n]
    factors.append(full_n)
    if max_rows:
        factors = [s for s in factors if s <= max_rows]

    # ── Run at each scale factor ──────────────────────────────────────
    scaling = []
    last_result = None
    for n in factors:
        print(f"\n── Scale: {n:,} rows ──────────────────────────────────")
        ae_sub = ae_full.head(n) if n < full_n else ae_full
        subj = ae_sub["subject_id"].unique()
        adsl_sub = adsl_full.filter(pl.col("USUBJID").is_in(subj.implode()))

        runs = []
        for _ in range(args.reps):
            result = run_pipeline(ae_sub, adsl_sub)
            runs.append(result)
            print(
                f"  SDTM: {result['sdtm_sec']:.2f}s  "
                f"ADaM: {result['adam_sec']:.2f}s  "
                f"Total: {result['total_sec']:.2f}s  "
                f"RSS: {result['peak_rss_mb']:.0f} MB  "
                f"Out: {result['out_rows']}×{result['out_cols']}"
            )
        totals = [r["total_sec"] for r in runs]
        scaling.append(
            {
                "rows": result["n_rows"],
                "subjects": result["n_adsl"],
                "sdtm_sec": statistics.median(r["sdtm_sec"] for r in runs),
                "adam_sec": statistics.median(r["adam_sec"] for r in runs),
                "total_sec": statistics.median(totals),
                "total_min_sec": min(totals),
                "total_max_sec": max(totals),
                "total_runs_sec": totals,
                "peak_rss_mb": result["peak_rss_mb"],
            }
        )
        last_result = result
        # Output of the last run at each scale, for the row-by-row check in run_benchmark.py
        result["adae"].select(CHECK_COLS).write_parquet(
            DATA / f"fleet_adae_check{suffix}_{n}.parquet"
        )

    # ── Dependency count ──────────────────────────────────────────────
    import importlib.metadata

    def count_deps(pkg: str) -> set[str]:
        seen: set[str] = set()
        stack = [pkg]
        while stack:
            p = stack.pop()
            if p.lower() in {s.lower() for s in seen}:
                continue
            seen.add(p)
            try:
                reqs = importlib.metadata.requires(p) or []
            except importlib.metadata.PackageNotFoundError:
                continue
            for r in reqs:
                if "extra ==" in r:
                    continue
                name = (
                    r.split()[0]
                    .split(";")[0]
                    .split("[")[0]
                    .split("<")[0]
                    .split(">")[0]
                    .split("=")[0]
                    .split("!")[0]
                    .strip()
                )
                stack.append(name)
        return seen

    all_deps = count_deps("fleet-cdisc") | count_deps("polars")

    metrics = {
        "tool": "Fleet (Python / Polars)",
        "polars_version": pl.__version__,
        "fleet_version": importlib.metadata.version("fleet-cdisc"),
        "python_version": platform.python_version(),
        "polars_threads": pl.thread_pool_size(),
        "polars_max_threads_env": os.environ.get("POLARS_MAX_THREADS"),
        "repetitions": args.reps,
        "input": args.input,
        "input_rows_ae": last_result["n_rows"],
        "input_rows_adsl": last_result["n_adsl"],
        "output_rows": last_result["out_rows"],
        "output_cols": last_result["out_cols"],
        "time_sdtm_sec": scaling[-1]["sdtm_sec"],
        "time_adam_sec": scaling[-1]["adam_sec"],
        "time_total_sec": scaling[-1]["total_sec"],
        "peak_memory_tracemalloc_mb": last_result["peak_traced_mb"],
        "peak_rss_mb": last_result["peak_rss_mb"],
        # Non-blank, non-comment lines between the timers of run_pipeline
        "pipeline_loc_sdtm": 18,
        "pipeline_loc_adam": 37,
        "pipeline_loc_total": 55,
        "n_total_dependencies": len(all_deps),
        "dependency_names": sorted(all_deps),
        "output_columns": last_result["columns"],
        "scaling": scaling,
    }

    return metrics


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("max_rows", type=int, nargs="?", default=None)
    parser.add_argument("--reps", type=int, default=3)
    parser.add_argument("--input", default="inflated")
    parser.add_argument("--tag", default="")
    args = parser.parse_args()
    metrics = run(args)
    print(json.dumps(metrics, indent=2, default=str))
    out = DATA / (f"fleet_metrics_{args.tag}.json" if args.tag else "fleet_metrics.json")
    out.write_text(json.dumps(metrics, indent=2, default=str))
