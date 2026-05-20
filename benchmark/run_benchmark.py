"""
Fleet vs Admiral ADAE benchmark orchestrator.

Steps:
  1. Inflate data (if not already done)
  2. Run Fleet ADAE benchmark (Python subprocess — clean process)
  3. Run Admiral ADAE benchmark (Rscript subprocess — clean process)
  4. Load metrics, compare side-by-side, print report

Using subprocesses for both ensures each tool gets a clean memory space
and neither benefits from warm caches of the other.

Usage:
    uv run python benchmark/run_benchmark.py [--target-gb 2.0] [--skip-inflate]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
DATA = ROOT / "data"
REPO = ROOT.parent


def run_cmd(cmd: list[str], label: str) -> tuple[float, str, str]:
    """Run a command, return (wall_seconds, stdout, stderr)."""
    print(f"\n{'─' * 70}")
    print(f"  {label}")
    print(f"  $ {' '.join(cmd)}")
    print(f"{'─' * 70}")
    t0 = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO))
    elapsed = time.perf_counter() - t0
    if result.returncode != 0:
        print(f"  STDERR:\n{result.stderr}")
        print(f"  STDOUT:\n{result.stdout}")
        raise RuntimeError(f"{label} failed (exit code {result.returncode})")
    print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
    return elapsed, result.stdout, result.stderr


def fmt_time(sec: float) -> str:
    if sec < 1:
        return f"{sec * 1000:.0f}ms"
    return f"{sec:.1f}s"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-gb", type=float, default=2.0)
    parser.add_argument("--skip-inflate", action="store_true")
    args = parser.parse_args()

    # ── Step 1: Inflate data ──────────────────────────────────────────
    if not args.skip_inflate and not (DATA / "ae_inflated.parquet").exists():
        print("⏳ Inflating data …")
        run_cmd(
            [sys.executable, str(ROOT / "inflate_data.py"), "--target-gb", str(args.target_gb)],
            "Inflate raw data",
        )
    else:
        if (DATA / "ae_inflated.parquet").exists():
            size_mb = (DATA / "ae_inflated.parquet").stat().st_size / 1e6
            print(f"✓ Inflated data exists ({size_mb:.0f} MB Parquet)")
        else:
            print("ERROR: Inflated data not found. Run without --skip-inflate.")
            sys.exit(1)

    # ── Step 2: Fleet benchmark ───────────────────────────────────────
    fleet_wall, _, _ = run_cmd(
        [sys.executable, str(ROOT / "fleet_adae_benchmark.py")],
        "Fleet ADAE benchmark",
    )

    # ── Step 3: Admiral benchmark ─────────────────────────────────────
    admiral_wall, _, _ = run_cmd(
        ["Rscript", str(ROOT / "admiral_adae_benchmark.R")],
        "Admiral ADAE benchmark",
    )

    # ── Step 4: Load and compare ──────────────────────────────────────
    fm = json.loads((DATA / "fleet_metrics.json").read_text())
    am = json.loads((DATA / "admiral_metrics.json").read_text())

    W = 78
    print(f"\n\n{'=' * W}")
    print("  FLEET vs ADMIRAL — ADAE BENCHMARK REPORT")
    print(f"{'=' * W}")

    # Version info
    print(f"\n  Fleet   : {fm.get('fleet_version', '?')}  (Polars {fm.get('polars_version', '?')}, Python {fm.get('python_version', '?')})")
    print(f"  Admiral : {am.get('admiral_version', '?')}  ({am.get('r_version', '?')})")

    # Table header
    C1, C2, C3 = 34, 18, 18
    hdr = f"\n  {'Metric':<{C1}}  {'Fleet':>{C2}}  {'Admiral':>{C3}}"
    sep = f"  {'─' * C1}  {'─' * C2}  {'─' * C3}"

    def row(label: str, fv: str, av: str, note: str = "") -> None:
        n = f"  {note}" if note else ""
        print(f"  {label:<{C1}}  {fv:>{C2}}  {av:>{C3}}{n}")

    def winner_str(fv: float, av: float, lower_better: bool = True) -> str:
        if fv == av:
            return ""
        if lower_better:
            w = "Fleet" if fv < av else "Admiral"
            ratio = max(fv, av) / max(min(fv, av), 0.001)
        else:
            w = "Fleet" if fv > av else "Admiral"
            ratio = max(fv, av) / max(min(fv, av), 0.001)
        return f"← {w} ({ratio:.1f}×)"

    # ── Input ─────────────────────────────────────────────────────────
    print(hdr)
    print(sep)
    row("Input AE rows", f"{fm['input_rows_ae']:,}", f"{am['input_rows_ae']:,}")
    row("Input ADSL rows", f"{fm['input_rows_adsl']:,}", f"{am['input_rows_adsl']:,}")

    # ── Output ────────────────────────────────────────────────────────
    print()
    row("Output rows", f"{fm['output_rows']:,}", f"{am['output_rows']:,}")
    row("Output columns", str(fm["output_cols"]), str(am["output_cols"]))

    # ── Timing ────────────────────────────────────────────────────────
    print(f"\n  {'Timing':<{C1}}  {'Fleet':>{C2}}  {'Admiral':>{C3}}")
    print(sep)
    for label, key in [
        ("I/O (Parquet read)", "time_io_sec"),
        ("SDTM preparation", "time_sdtm_sec"),
        ("ADaM derivation", "time_adam_sec"),
        ("Total (in-process)", "time_total_sec"),
    ]:
        fv = fm.get(key, 0)
        av = am.get(key, 0)
        row(label, fmt_time(fv), fmt_time(av), winner_str(fv, av))

    row("Total (wall, subprocess)", fmt_time(fleet_wall), fmt_time(admiral_wall),
        winner_str(fleet_wall, admiral_wall))

    # ── Memory ────────────────────────────────────────────────────────
    print(f"\n  {'Memory':<{C1}}  {'Fleet':>{C2}}  {'Admiral':>{C3}}")
    print(sep)
    f_rss = fm.get("peak_rss_mb", 0)
    a_gc = am.get("peak_memory_gc_mb", 0)
    row("Peak RSS / GC (MB)", f"{f_rss:,.0f}", f"{a_gc:,.0f}",
        winner_str(f_rss, a_gc))
    f_traced = fm.get("peak_memory_tracemalloc_mb", 0)
    row("Python tracemalloc (MB)", f"{f_traced:,.0f}", "n/a")

    # ── Code metrics ──────────────────────────────────────────────────
    print(f"\n  {'Code':<{C1}}  {'Fleet':>{C2}}  {'Admiral':>{C3}}")
    print(sep)
    row("Pipeline LOC (SDTM)", str(fm.get("pipeline_loc_sdtm", "?")), str(am.get("pipeline_loc_sdtm", "?")))
    row("Pipeline LOC (ADaM)", str(fm.get("pipeline_loc_adam", "?")), str(am.get("pipeline_loc_adam", "?")))
    row("Pipeline LOC (total)", str(fm.get("pipeline_loc_total", "?")), str(am.get("pipeline_loc_total", "?")))
    row("Recursive dependencies", str(fm["n_total_dependencies"]), str(am["n_total_dependencies"]))
    row("Language / engine", "Python + Polars (Rust)", "R + dplyr (C++)")

    # ── Equivalence check ─────────────────────────────────────────────
    print("\n  Output Equivalence Check")
    print(sep)
    try:
        import polars as pl

        f_sample = pl.read_parquet(DATA / "fleet_adae_sample.parquet")
        a_sample = pl.read_parquet(DATA / "admiral_adae_sample.parquet")
        common = sorted(set(f_sample.columns) & set(a_sample.columns))
        fleet_only = sorted(set(f_sample.columns) - set(a_sample.columns))
        admiral_only = sorted(set(a_sample.columns) - set(f_sample.columns))
        print(f"  Common columns        : {len(common)}")
        if fleet_only:
            print(f"  Fleet-only columns    : {fleet_only}")
        if admiral_only:
            print(f"  Admiral-only columns  : {admiral_only}")
        for col in common[:12]:
            try:
                fv = f_sample[col].head(3).to_list()
                av = a_sample[col].head(3).to_list()
                match = "✓" if str(fv) == str(av) else "≈"
                print(f"    {match}  {col:<14}  Fleet={fv}  Admiral={av}")
            except Exception:
                print(f"    ?  {col}")
    except Exception as e:
        print(f"  ⚠ Could not compare samples: {e}")

    # ── Notes ─────────────────────────────────────────────────────────
    print(f"\n{'=' * W}")
    print("  Notes:")
    print("  • Both pipelines ran in separate clean subprocesses")
    print("  • Same Parquet input, same derivation steps, same target variables")
    print("  • Fleet uses Polars (Rust columnar engine, lazy evaluation)")
    print("  • Admiral uses dplyr (C++ backed, eager row-major data.frame)")
    print("  • R memory via gc() can underreport; Fleet reports process RSS")
    print("  • LOC counts pipeline code only (data mapping + derivations)")
    print(f"{'=' * W}")

    # Save full report
    report = {
        "fleet": fm,
        "admiral": am,
        "fleet_wall_sec": round(fleet_wall, 3),
        "admiral_wall_sec": round(admiral_wall, 3),
    }
    rpt = DATA / "benchmark_report.json"
    rpt.write_text(json.dumps(report, indent=2, default=str))
    print(f"\n  Full report → {rpt}")


if __name__ == "__main__":
    main()
