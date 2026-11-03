"""Fleet grades equal admiral 1.4.1 on a frozen grid (no R needed in CI).

The grid comes from ``scripts/regen_admiral_grading_grid.R``: every entry of
the 8 admiral tables, random rows and rows on each cut-off, every BNRIND,
SEX, age band and unit spelling.  Where admiral drops a row (a population
filter that evaluates to NA), Fleet keeps it with a null grade.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

import fleet  # noqa: F401
from fleet.adam.grading import GradingSystem

GRID = Path(__file__).parents[1] / "fixtures" / "goldens" / "grading" / "admiral_grid.parquet"


@pytest.fixture(scope="module")
def grid() -> pl.DataFrame:
    return pl.read_parquet(GRID)


@pytest.mark.parametrize("system", [s.value for s in GradingSystem])
@pytest.mark.parametrize(
    ("direction", "target", "kept"), [("L", "ATOXGRL", "KEPT_L"), ("H", "ATOXGRH", "KEPT_H")]
)
def test_fleet_grades_equal_admiral(
    grid: pl.DataFrame, system: str, direction: str, target: str, kept: str
) -> None:
    rows = grid.filter(pl.col("SYSTEM") == system).drop("ATOXGRL", "ATOXGRH")
    expected = grid.filter(pl.col("SYSTEM") == system).select(
        "ROWID", pl.when(pl.col(kept)).then(pl.col(target)).alias("EXPECTED")
    )

    out = rows.adam.atoxgr(
        target, system=system, direction=direction, term_var="TERM", unit_var="AVALU"
    ).to_frame()

    assert out["ROWID"].to_list() == rows["ROWID"].to_list()
    diff = out.join(expected, on="ROWID").filter(pl.col(target).ne_missing(pl.col("EXPECTED")))
    assert diff.height == 0, diff.select(
        "ROWID",
        "TERM",
        "AVAL",
        "ANRLO",
        "ANRHI",
        "BASE",
        "BNRIND",
        "SEX",
        "BRTHDT",
        "AVALU",
        target,
        "EXPECTED",
    ).head(10)
