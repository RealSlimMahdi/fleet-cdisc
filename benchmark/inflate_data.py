"""
Inflate raw AE + DM CSVs to ~2 GB for benchmarking.

Strategy:
  - Read original CSV (~64 AE rows, ~50 DM rows)
  - Replicate N times, appending a batch suffix to subject_id
    so every row is unique yet structurally realistic
  - Write as both Parquet (fast I/O) and CSV (fallback)
  - Build a minimal ADSL reference with TRTSDT / TRTEDT

Usage:
    uv run python benchmark/inflate_data.py [--target-gb 2.0]
    uv run python benchmark/inflate_data.py --dense-rows 2000000 --dense-subjects 50000

The dense mode writes ae_dense.parquet and adsl_dense.parquet: copy i of the
64 raw rows goes to subject group i modulo G, so each subject holds many
records (about rows / subjects) instead of 1 to 3.
"""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import polars as pl

OUT = Path(__file__).parent / "data"
RAW_AE = OUT / "ae_raw_20260418_214047.csv"
RAW_DM = OUT / "dm_raw_20260418_214047.csv"
RAW_EX = OUT / "ex_raw_20260418_214047.csv"


def inflate(target_gb: float = 2.0) -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    ae = pl.read_csv(RAW_AE)
    dm = pl.read_csv(RAW_DM)
    ex = pl.read_csv(RAW_EX)

    # Estimate bytes per row from CSV serialisation
    ae_csv_bytes = len(ae.write_csv().encode("utf-8"))
    bytes_per_row = ae_csv_bytes / ae.height
    target_rows = int(target_gb * 1e9 / bytes_per_row)
    n_copies = math.ceil(target_rows / ae.height)

    print(f"Original AE : {ae.height} rows, ~{bytes_per_row:.0f} bytes/row (CSV)")
    print(f"Original DM : {dm.height} rows")
    print(f"Original EX : {ex.height} rows")
    print(f"Target      : ~{target_rows:,} AE rows  ({n_copies:,} copies)")
    print()

    # ── Inflate AE ──────────────────────────────────────────────────────
    t0 = time.perf_counter()
    CHUNK = 5_000
    chunks: list[pl.DataFrame] = []

    for start in range(0, n_copies, CHUNK):
        end = min(start + CHUNK, n_copies)
        batch = pl.concat(
            [
                ae.with_columns(
                    (pl.lit(f"B{i:06d}_") + pl.col("subject_id")).alias("subject_id"),
                )
                for i in range(start, end)
            ]
        )
        chunks.append(batch)
        print(f"  AE inflating: batch {start:>8,}–{end:>8,} / {n_copies:,}", end="\r")

    ae_big = pl.concat(chunks)
    elapsed_ae = time.perf_counter() - t0
    print(f"\n  AE inflated : {ae_big.height:,} rows in {elapsed_ae:.1f}s")

    # Write Parquet
    ae_pq = OUT / "ae_inflated.parquet"
    ae_big.write_parquet(ae_pq, compression="snappy")
    print(f"  Parquet     : {ae_pq}  ({ae_pq.stat().st_size / 1e6:.0f} MB)")

    # ── Inflate DM → minimal ADSL ──────────────────────────────────────
    # Every unique subject in the inflated AE must appear in ADSL
    t1 = time.perf_counter()
    dm_frames = [
        dm.with_columns(
            (pl.lit(f"B{i:06d}_") + pl.col("subject_id")).alias("subject_id"),
        )
        for i in range(n_copies)
    ]
    dm_big = pl.concat(dm_frames).unique(subset=["subject_id"])

    # Build ADSL with treatment dates derived from EX (first/last dose)
    # First, inflate EX the same way
    ex_frames = [
        ex.with_columns(
            (pl.lit(f"B{i:06d}_") + pl.col("subject_id")).alias("subject_id"),
        )
        for i in range(n_copies)
    ]
    ex_big = pl.concat(ex_frames)

    # Derive TRTSDT / TRTEDT from EX (first and last administration_date)
    trt_dates = ex_big.group_by("subject_id").agg(
        pl.col("administration_date").min().alias("TRTSDT_str"),
        pl.col("administration_date").max().alias("TRTEDT_str"),
    )

    adsl = dm_big.join(trt_dates, on="subject_id", how="left").select(
        pl.lit("STUDY001").alias("STUDYID"),
        pl.col("subject_id").alias("USUBJID"),
        pl.col("TRTSDT_str").str.to_date("%Y-%m-%d").alias("TRTSDT"),
        pl.col("TRTEDT_str").str.to_date("%Y-%m-%d").alias("TRTEDT"),
        pl.lit("Treatment A").alias("TRT01P"),
        pl.lit("Y").alias("SAFFL"),
    )

    adsl_pq = OUT / "adsl_inflated.parquet"
    adsl.write_parquet(adsl_pq, compression="snappy")
    elapsed_dm = time.perf_counter() - t1
    print(f"  ADSL built  : {adsl.height:,} subjects in {elapsed_dm:.1f}s → {adsl_pq}")

    # Summary
    print(f"\n✓ Data ready in {OUT}/")
    print(f"  ae_inflated.parquet : {ae_big.height:,} rows")
    print(f"  adsl_inflated.parquet : {adsl.height:,} rows")


def inflate_dense(rows: int, subjects: int) -> None:
    ae = pl.read_csv(RAW_AE)
    dm = pl.read_csv(RAW_DM)
    ex = pl.read_csv(RAW_EX)
    n_copies = math.ceil(rows / ae.height)
    n_groups = math.ceil(subjects / ae["subject_id"].n_unique())

    def prefixed(df: pl.DataFrame, i: int) -> pl.DataFrame:
        return df.with_columns((pl.lit(f"B{i:06d}_") + pl.col("subject_id")).alias("subject_id"))

    ae_big = pl.concat([prefixed(ae, i % n_groups) for i in range(n_copies)]).head(rows)
    ae_big.write_parquet(OUT / "ae_dense.parquet", compression="snappy")

    ex_big = pl.concat([prefixed(ex, i) for i in range(n_groups)])
    trt_dates = ex_big.group_by("subject_id").agg(
        pl.col("administration_date").min().alias("TRTSDT_str"),
        pl.col("administration_date").max().alias("TRTEDT_str"),
    )
    adsl = (
        pl.concat([prefixed(dm, i) for i in range(n_groups)])
        .join(trt_dates, on="subject_id", how="left")
        .select(
            pl.lit("STUDY001").alias("STUDYID"),
            pl.col("subject_id").alias("USUBJID"),
            pl.col("TRTSDT_str").str.to_date("%Y-%m-%d").alias("TRTSDT"),
            pl.col("TRTEDT_str").str.to_date("%Y-%m-%d").alias("TRTEDT"),
            pl.lit("Treatment A").alias("TRT01P"),
            pl.lit("Y").alias("SAFFL"),
        )
    )
    adsl.write_parquet(OUT / "adsl_dense.parquet", compression="snappy")
    n_subj = ae_big["subject_id"].n_unique()
    print(
        f"✓ Dense data: {ae_big.height:,} AE rows, {n_subj:,} subjects "
        f"({ae_big.height / n_subj:.1f} records per subject)"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--target-gb", type=float, default=2.0)
    parser.add_argument("--dense-rows", type=int, default=None)
    parser.add_argument("--dense-subjects", type=int, default=50_000)
    args = parser.parse_args()
    if args.dense_rows:
        inflate_dense(args.dense_rows, args.dense_subjects)
    else:
        inflate(args.target_gb)
