"""
Fleet / Polars ADAE benchmark — Multi-scale.

Reproduces core ADAE derivations (matching the Admiral benchmark exactly):
  SDTM: STUDYID, DOMAIN, USUBJID, AETERM, AESTDTC, AEENDTC, AESEV, AESER,
        AEREL, AEOUT, AEACN, AESEQ
  ADaM: ASTDT, AENDT, ADY, TRTEMFL, AESEVN, ANL01FL, ASEQ

Runs the pipeline at multiple scale factors for a scaling curve.

Usage:
    uv run python benchmark/fleet_adae_benchmark.py [max_rows]
    uv run python benchmark/fleet_adae_benchmark.py            # all rows
    uv run python benchmark/fleet_adae_benchmark.py 500000     # cap at 500K
"""

from __future__ import annotations

import json
import platform
import resource
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
            start_date="AESTDTC",
            trtsdt="TRTSDT",
            trtedt="TRTEDT",
        )
        .recode(
            "AESEVN",
            source="AESEV",
            recode_map={"Mild": 1, "Moderate": 2, "Severe": 3},
        )
        .flag(
            "ANL01FL",
            criteria="max",
            value_col="AESEVN",
            by=["USUBJID", "AETERM"],
        )
        .seq("ASEQ", by=["USUBJID"])
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


def run() -> dict:
    # ── Read full data ────────────────────────────────────────────────
    ae_full = pl.read_parquet(DATA / "ae_inflated.parquet")
    adsl_full = pl.read_parquet(DATA / "adsl_inflated.parquet")

    full_n = ae_full.height
    print(f"  Full AE  : {full_n:,} rows")
    print(f"  Full ADSL: {adsl_full.height:,} rows")

    max_rows = int(sys.argv[1]) if len(sys.argv) > 1 else None
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
        adsl_sub = adsl_full.filter(pl.col("USUBJID").is_in(subj))

        result = run_pipeline(ae_sub, adsl_sub)
        print(
            f"  SDTM: {result['sdtm_sec']:.1f}s  "
            f"ADaM: {result['adam_sec']:.1f}s  "
            f"Total: {result['total_sec']:.1f}s  "
            f"RSS: {result['peak_rss_mb']:.0f} MB  "
            f"Out: {result['out_rows']}×{result['out_cols']}"
        )
        scaling.append(
            {
                "rows": result["n_rows"],
                "sdtm_sec": result["sdtm_sec"],
                "adam_sec": result["adam_sec"],
                "total_sec": result["total_sec"],
                "peak_rss_mb": result["peak_rss_mb"],
            }
        )
        last_result = result

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
        "input_rows_ae": last_result["n_rows"],
        "input_rows_adsl": last_result["n_adsl"],
        "output_rows": last_result["out_rows"],
        "output_cols": last_result["out_cols"],
        "time_sdtm_sec": last_result["sdtm_sec"],
        "time_adam_sec": last_result["adam_sec"],
        "time_total_sec": last_result["total_sec"],
        "peak_memory_tracemalloc_mb": last_result["peak_traced_mb"],
        "peak_rss_mb": last_result["peak_rss_mb"],
        "pipeline_loc_sdtm": 15,
        "pipeline_loc_adam": 22,
        "pipeline_loc_total": 37,
        "n_total_dependencies": len(all_deps),
        "dependency_names": sorted(all_deps),
        "output_columns": last_result["columns"],
        "scaling": scaling,
    }

    # Save sample for equivalence check
    last_result["adae"].head(100).write_parquet(DATA / "fleet_adae_sample.parquet")

    return metrics


if __name__ == "__main__":
    metrics = run()
    print(json.dumps(metrics, indent=2, default=str))
    (DATA / "fleet_metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
