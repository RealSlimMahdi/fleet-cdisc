"""Compare Fleet with admiral on a small grid of real ADAE shapes (alpha audit 5.3, gate 2).

The grid holds the shapes that broke Fleet in the alpha audit: a missing
start date, an event that ended before the first dose, an event after the
last dose, a tie on the severity order, a missing severity.  Each derivation
runs in admiral (``Rscript``) and in Fleet on the same CSV, and every cell
is compared.  A difference exits 1 and prints the rows.

Usage::

    uv run python scripts/admiral_oracle.py            # needs Rscript with admiral
    uv run python scripts/admiral_oracle.py --keep tmp  # keep the CSV files

The CI job ``.github/workflows/admiral-oracle.yml`` runs it weekly.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import fleet  # noqa: E402

GRID = pl.from_repr("""\
┌─────────┬───────┬───────────┬────────────┬────────────┬────────────┬────────────┬──────────┬────────┐
│ USUBJID ┆ AESEQ ┆ AETERM    ┆ ASTDT      ┆ AENDT      ┆ TRTSDT     ┆ TRTEDT     ┆ AESEV    ┆ AESEVN │
│ ---     ┆ ---   ┆ ---       ┆ ---        ┆ ---        ┆ ---        ┆ ---        ┆ ---      ┆ ---    │
│ str     ┆ i64   ┆ str       ┆ str        ┆ str        ┆ str        ┆ str        ┆ str      ┆ i64    │
╞═════════╪═══════╪═══════════╪════════════╪════════════╪════════════╪════════════╪══════════╪════════╡
│ S01     ┆ 1     ┆ HEADACHE  ┆ 2024-01-05 ┆ 2024-01-07 ┆ 2024-01-10 ┆ 2024-03-10 ┆ MILD     ┆ 1      │
│ S01     ┆ 2     ┆ HEADACHE  ┆ 2024-01-12 ┆ 2024-01-14 ┆ 2024-01-10 ┆ 2024-03-10 ┆ SEVERE   ┆ 3      │
│ S01     ┆ 3     ┆ HEADACHE  ┆ 2024-02-01 ┆ 2024-02-03 ┆ 2024-01-10 ┆ 2024-03-10 ┆ SEVERE   ┆ 3      │
│ S01     ┆ 4     ┆ NAUSEA    ┆ null       ┆ null       ┆ 2024-01-10 ┆ 2024-03-10 ┆ MILD     ┆ 1      │
│ S01     ┆ 5     ┆ NAUSEA    ┆ null       ┆ 2024-01-02 ┆ 2024-01-10 ┆ 2024-03-10 ┆ MILD     ┆ 1      │
│ S02     ┆ 1     ┆ RASH      ┆ 2024-01-10 ┆ 2024-01-20 ┆ 2024-01-10 ┆ 2024-03-10 ┆ MILD     ┆ 1      │
│ S02     ┆ 2     ┆ RASH      ┆ 2024-04-01 ┆ 2024-04-02 ┆ 2024-01-10 ┆ 2024-03-10 ┆ MILD     ┆ 1      │
│ S02     ┆ 3     ┆ RASH      ┆ 2024-04-15 ┆ 2024-04-16 ┆ 2024-01-10 ┆ 2024-03-10 ┆ MILD     ┆ 1      │
│ S02     ┆ 4     ┆ FATIGUE   ┆ 2024-01-09 ┆ 2024-01-11 ┆ 2024-01-10 ┆ 2024-03-10 ┆ null     ┆ null   │
│ S03     ┆ 1     ┆ DIZZINESS ┆ 2024-02-02 ┆ 2024-02-03 ┆ null       ┆ null       ┆ MILD     ┆ 1      │
│ S04     ┆ 1     ┆ COUGH     ┆ 2024-01-15 ┆ null       ┆ 2024-01-10 ┆ null       ┆ MODERATE ┆ 2      │
└─────────┴───────┴───────────┴────────────┴────────────┴────────────┴────────────┴──────────┴────────┘
""").with_columns(pl.col("ASTDT", "AENDT", "TRTSDT", "TRTEDT").str.to_date())

#: Differences with an open decision, by (USUBJID, AESEQ, variable).  The job
#: fails on any other difference, and when one of these disappears.  Empty:
#: the null-order-key cells of ANL01FL were decided in ADR-0020 (PR #205).
KNOWN: dict[tuple[str, int, str], str] = {}

#: The admiral program: one derivation per output column, as the Fleet chain below.
ADMIRAL = r"""
suppressMessages({library(admiral); library(dplyr)})
args <- commandArgs(trailingOnly = TRUE)
d <- read.csv(args[1], na.strings = "", stringsAsFactors = FALSE) %>%
  mutate(across(c(ASTDT, AENDT, TRTSDT, TRTEDT), as.Date))
o <- d %>%
  derive_vars_dy(reference_date = TRTSDT, source_vars = exprs(ASTDT, AENDT)) %>%
  derive_vars_duration(new_var = ADURN, start_date = ASTDT, end_date = AENDT) %>%
  derive_var_trtemfl(
    new_var = TRTEMFL, start_date = ASTDT, end_date = AENDT,
    trt_start_date = TRTSDT, trt_end_date = TRTEDT, end_window = 30
  ) %>%
  derive_var_extreme_flag(
    by_vars = exprs(USUBJID, AETERM), order = exprs(AESEVN, ASTDT),
    new_var = ANL01FL, mode = "last"
  ) %>%
  select(USUBJID, AESEQ, ASTDY, AENDY, ADURN, TRTEMFL, ANL01FL)
write.csv(o, args[2], row.names = FALSE, na = "")
"""


def fleet_result(grid: pl.DataFrame) -> pl.DataFrame:
    """The same derivations with Fleet verbs."""
    return (
        fleet.frame(grid)
        .adam.occds("ADAE")
        .study_day("ASTDY", date_col="ASTDT", ref_col="TRTSDT")
        .study_day("AENDY", date_col="AENDT", ref_col="TRTSDT")
        .duration("ADURN", start="ASTDT", end="AENDT")
        .treatment_emergent(
            "TRTEMFL",
            start_date="ASTDT",
            end_date="AENDT",
            trtsdt="TRTSDT",
            trtedt="TRTEDT",
            end_window=30,
        )
        .flag("ANL01FL", criteria="last", order_by=["AESEVN", "ASTDT"], by=["USUBJID", "AETERM"])
        .to_frame()
        .select("USUBJID", "AESEQ", "ASTDY", "AENDY", "ADURN", "TRTEMFL", "ANL01FL")
    )


def admiral_result(grid: pl.DataFrame, folder: Path) -> pl.DataFrame:
    """The derivations run by admiral in ``Rscript``."""
    source, result, program = folder / "grid.csv", folder / "admiral.csv", folder / "oracle.R"
    grid.write_csv(source)
    program.write_text(ADMIRAL, encoding="utf-8")
    run = subprocess.run(
        ["Rscript", str(program), str(source), str(result)], capture_output=True, text=True
    )
    if run.returncode != 0:
        raise SystemExit(f"admiral run failed (exit {run.returncode}):\n{run.stderr}")
    return pl.read_csv(
        result,
        schema_overrides={"ASTDY": pl.Int64, "AENDY": pl.Int64, "ADURN": pl.Float64},
    )


def compare(
    fleet_out: pl.DataFrame, admiral_out: pl.DataFrame
) -> list[tuple[str, int, str, str, str]]:
    """Each cell that differs: key, variable, Fleet value, admiral value; null equals null."""
    keys = ["USUBJID", "AESEQ"]
    joined = fleet_out.with_columns(pl.col("ADURN").cast(pl.Float64)).join(
        admiral_out, on=keys, how="full", suffix="_ADMIRAL", coalesce=True
    )
    cells = []
    for column in (c for c in fleet_out.columns if c not in keys):
        differ = joined.filter(
            pl.col(column).cast(pl.String).ne_missing(pl.col(f"{column}_ADMIRAL").cast(pl.String))
        )
        for row in differ.iter_rows(named=True):
            cells.append(
                (row["USUBJID"], row["AESEQ"], column, row[column], row[f"{column}_ADMIRAL"])
            )
    return sorted(cells, key=lambda cell: (cell[0], cell[1], cell[2]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--keep", type=Path, help="Keep the CSV files and the R program here.")
    args = parser.parse_args()
    if shutil.which("Rscript") is None:
        raise SystemExit("Rscript not found: install R and the admiral package.")

    folder = args.keep or Path(tempfile.mkdtemp(prefix="admiral-oracle-"))
    folder.mkdir(parents=True, exist_ok=True)
    fleet_out = fleet_result(GRID)
    admiral_out = admiral_result(GRID, folder)
    cells = compare(fleet_out, admiral_out)

    print(f"{GRID.height} records, {fleet_out.width - 2} derived variables compared with admiral.")
    failed = False
    for usubjid, seq, column, ours, theirs in cells:
        reason = KNOWN.get((usubjid, seq, column))
        label = f"known ({reason})" if reason else "NEW DIFFERENCE"
        failed |= reason is None
        print(f"  {usubjid} AESEQ {seq} {column}: Fleet {ours!r}, admiral {theirs!r} - {label}")
    gone = set(KNOWN) - {(u, s, c) for u, s, c, _, _ in cells}
    for usubjid, seq, column in sorted(gone):
        failed = True
        print(f"  {usubjid} AESEQ {seq} {column}: now equals admiral; remove it from KNOWN")
    if failed:
        raise SystemExit(1)
    print("Every other cell equals admiral.")


if __name__ == "__main__":
    main()
