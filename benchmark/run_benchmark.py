"""
Fleet vs Admiral ADAE benchmark orchestrator.

Steps:
  1. Inflate data (if not already done): the sparse input (1 to 3 records
     per subject) and a dense input (about 40 records per subject)
  2. Run the Fleet ADAE benchmark twice per input (Python subprocess): at the
     default Polars thread count and with POLARS_MAX_THREADS=1
  3. Run the Oak + Admiral ADAE benchmark per input (Rscript subprocess)
  4. Compare the outputs row by row at every scale and print the timing table

Using subprocesses for both ensures each tool gets a clean memory space
and neither benefits from warm caches of the other.

Usage:
    uv run python -u benchmark/run_benchmark.py [--skip-inflate] [--max-rows N] [--reps 3]

The run exits 1 when the Fleet and admiral outputs at any scale differ in
any compared variable on any row.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

import polars as pl

ROOT = Path(__file__).parent
DATA = ROOT / "data"
REPO = ROOT.parent

# The SDTM and ADaM variables that both pipelines derive.
COMPARED = [
    "STUDYID", "USUBJID", "AETERM", "AESTDTC", "AEENDTC", "AESEV", "AESER",
    "AEREL", "AEOUT", "AEACN", "AESEQ", "ASTDT", "AENDT", "TRTEMFL",
    "AESEVN", "ANL01FL", "ASEQ",
]  # fmt: skip


def compare_outputs(fleet: pl.DataFrame, admiral: pl.DataFrame) -> list[str]:
    """Compare the two ADAE outputs row by row and return one line per difference."""

    def norm(df: pl.DataFrame) -> pl.DataFrame:
        cols = [c for c in COMPARED if c in df.columns]
        return (
            df.select(cols)
            .with_columns(
                pl.col(c).cast(pl.Int64) for c in ("AESEQ", "AESEVN", "ASEQ") if c in cols
            )
            .with_columns(pl.col(c).cast(pl.Date) for c in ("ASTDT", "AENDT") if c in cols)
            .sort(["USUBJID", "ASEQ"])
        )

    f, a = norm(fleet), norm(admiral)
    problems = [f"{c}: missing in Fleet" for c in COMPARED if c not in f.columns]
    problems += [f"{c}: missing in admiral" for c in COMPARED if c not in a.columns]
    if f.height != a.height:
        return [*problems, f"row count: Fleet {f.height}, admiral {a.height}"]
    for c in (c for c in COMPARED if c in f.columns and c in a.columns):
        diff = ~f[c].eq_missing(a[c])
        n = int(diff.sum())
        if n:
            i = int(diff.arg_max())
            problems.append(
                f"{c}: {n} row(s) differ, first at USUBJID {f['USUBJID'][i]} ASEQ "
                f"{f['ASEQ'][i]}: Fleet {f[c][i]!r}, admiral {a[c][i]!r}"
            )
    return problems


def run_cmd(cmd: list[str], label: str, env: dict[str, str] | None = None) -> float:
    """Run a command in a clean subprocess, stream its output, return wall seconds."""
    print(f"\n{'─' * 70}\n  {label}\n  $ {' '.join(cmd)}\n{'─' * 70}", flush=True)
    t0 = time.perf_counter()
    result = subprocess.run(cmd, cwd=str(REPO), env={**os.environ, **(env or {})})
    if result.returncode != 0:
        raise RuntimeError(f"{label} failed (exit code {result.returncode})")
    return time.perf_counter() - t0


def machine_info() -> dict:
    """Machine, OS and core counts of the host."""

    def sysctl(key: str) -> str:
        out = subprocess.run(["sysctl", "-n", key], capture_output=True, text=True)
        return out.stdout.strip()

    info = {"os": platform.platform(), "logical_cpus": os.cpu_count()}
    if platform.system() == "Darwin":
        info |= {
            "model": sysctl("hw.model"),
            "cpu": sysctl("machdep.cpu.brand_string"),
            "performance_cores": sysctl("hw.perflevel0.physicalcpu"),
            "efficiency_cores": sysctl("hw.perflevel1.physicalcpu"),
            "memory_gb": int(sysctl("hw.memsize") or 0) // 2**30,
            "load_average": os.getloadavg(),
        }
    return info


def spread(row: dict) -> str:
    return f"{row['total_sec']:.2f} [{row['total_min_sec']:.2f}-{row['total_max_sec']:.2f}]"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-gb", type=float, default=2.0)
    parser.add_argument("--skip-inflate", action="store_true")
    parser.add_argument("--max-rows", type=int, default=None, help="cap the largest scale")
    parser.add_argument("--reps", type=int, default=3, help="runs per scale")
    parser.add_argument("--dense-rows", type=int, default=2_000_000)
    parser.add_argument("--dense-subjects", type=int, default=50_000)
    args = parser.parse_args()
    cap = [str(args.max_rows)] if args.max_rows else []
    reps = ["--reps", str(args.reps)]

    # ── Step 1: Inflate data ──────────────────────────────────────────
    if not (DATA / "ae_inflated.parquet").exists():
        if args.skip_inflate:
            sys.exit("ERROR: Inflated data not found. Run without --skip-inflate.")
        run_cmd(
            [sys.executable, str(ROOT / "inflate_data.py"), "--target-gb", str(args.target_gb)],
            "Inflate raw data",
        )
    if not (DATA / "ae_dense.parquet").exists():
        run_cmd(
            [
                sys.executable, str(ROOT / "inflate_data.py"),
                "--dense-rows", str(args.dense_rows),
                "--dense-subjects", str(args.dense_subjects),
            ],
            "Inflate dense-subject data",
        )  # fmt: skip

    info = machine_info()
    print(f"\nMachine: {json.dumps(info)}", flush=True)

    # ── Step 2: Fleet (default threads, 1 thread) and admiral, on both inputs ──
    one_thread = {"POLARS_MAX_THREADS": "1"}
    fleet = [sys.executable, "-u", str(ROOT / "fleet_adae_benchmark.py")]
    admiral = ["Rscript", str(ROOT / "admiral_adae_benchmark.R")]
    runs = {
        "": (fleet + cap + reps, None),
        "1thread": (fleet + cap + reps + ["--tag", "1thread"], one_thread),
        "dense": (fleet + reps + ["--input", "dense", "--tag", "dense"], None),
        "dense_1thread": (
            fleet + reps + ["--input", "dense", "--tag", "dense_1thread"],
            one_thread,
        ),
    }
    r_runs = {
        "": admiral + cap + [f"--reps={args.reps}"],
        "dense": admiral + [f"--reps={args.reps}", "--input=dense", "--tag=dense"],
    }
    wall = {}
    for tag, (cmd, env) in runs.items():
        wall[f"fleet_{tag}"] = run_cmd(cmd, f"Fleet ADAE benchmark {tag}".strip(), env)
    for tag, cmd in r_runs.items():
        wall[f"admiral_{tag}"] = run_cmd(cmd, f"Admiral ADAE benchmark {tag}".strip())

    def metrics(tool: str, tag: str) -> dict:
        name = f"{tool}_metrics_{tag}.json" if tag else f"{tool}_metrics.json"
        return json.loads((DATA / name).read_text())

    fm, fm1, am = metrics("fleet", ""), metrics("fleet", "1thread"), metrics("admiral", "")
    fd, fd1, ad = (
        metrics("fleet", "dense"),
        metrics("fleet", "dense_1thread"),
        metrics("admiral", "dense"),
    )

    # ── Step 3: Row-by-row check at every scale, and the timing table ──
    W = 110
    print(f"\n\n{'=' * W}\n  FLEET vs OAK + ADMIRAL — ADAE BENCHMARK\n{'=' * W}")
    print(
        f"  Fleet {fm['fleet_version']} (Polars {fm['polars_version']}, "
        f"Python {fm['python_version']}, {fm['polars_threads']} threads)"
    )
    print(f"  sdtm.oak {am['oak_version']}, admiral {am['admiral_version']} ({am['r_version']})")
    print(f"  Repetitions per scale: {args.reps}. Times: median [min-max] seconds.\n")
    print(
        f"  {'Input':<7} {'AE rows':>11} {'Subjects':>10} {'Fleet':>20} {'Fleet 1 thread':>20} "
        f"{'Oak + admiral':>24} {'Speedup':>8}  Check"
    )
    problems_all: list[str] = []
    table = []
    for label, f, f1, a, tag in (
        ("sparse", fm, fm1, am, ""),
        ("dense", fd, fd1, ad, "dense"),
    ):
        suffix = f"_{tag}" if tag else ""
        for fr, f1r, ar in zip(f["scaling"], f1["scaling"], a["scaling"], strict=True):
            n = fr["rows"]
            check_r = pl.read_parquet(DATA / f"admiral_adae_check{suffix}_{n}.parquet")
            problems = compare_outputs(
                pl.read_parquet(DATA / f"fleet_adae_check{suffix}_{n}.parquet"), check_r
            )
            problems += compare_outputs(
                pl.read_parquet(DATA / f"fleet_adae_check{suffix}_1thread_{n}.parquet"),
                check_r,
            )
            problems_all += [f"{label} {n:,} rows: {p}" for p in problems]
            check = "same" if not problems else f"{len(problems)} DIFF"
            speedup = ar["total_sec"] / fr["total_sec"]
            print(
                f"  {label:<7} {n:>11,} {fr['subjects']:>10,} {spread(fr):>20} "
                f"{spread(f1r):>20} {spread(ar):>24} {speedup:>7.0f}×  {check}",
                flush=True,
            )
            table.append(
                {
                    "input": label,
                    "rows": n,
                    "subjects": fr["subjects"],
                    "fleet": fr,
                    "fleet_1thread": f1r,
                    "admiral": ar,
                    "speedup": round(speedup, 1),
                    "check": problems or "same",
                }
            )
    for p in problems_all:
        print(f"    DIFF  {p}")
    if not problems_all:
        print(f"\n  Same values in {len(COMPARED)} variables on every row at every scale.")

    report = {
        "machine": info,
        "repetitions": args.reps,
        "fleet": fm,
        "fleet_1thread": fm1,
        "admiral": am,
        "fleet_dense": fd,
        "fleet_dense_1thread": fd1,
        "admiral_dense": ad,
        "wall_sec": {k: round(v, 1) for k, v in wall.items()},
        "table": table,
    }
    rpt = DATA / "benchmark_report.json"
    rpt.write_text(json.dumps(report, indent=2, default=str))
    print(f"\n  Full report → {rpt}")
    if problems_all:
        sys.exit(1)


if __name__ == "__main__":
    main()
