"""Fleet *DTM imputation equals admiral 1.4.1 ``derive_vars_dtm`` on a frozen grid (no R in CI).

The grid comes from ``scripts/regen_admiral_dtm_grid.R``: 15 ``--DTC`` forms
(complete, truncated, a hyphen for a missing part, blank, null), each
``highest_imputation`` level a *DTM target accepts with no bounds, and the
first and last date and time imputation.  admiral runs with its default
``preserve = FALSE``.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import polars as pl
import pytest

import fleet  # noqa: F401

GRID = Path(__file__).parents[1] / "fixtures" / "goldens" / "dates" / "admiral_dtm_grid.csv"


@pytest.fixture(scope="module")
def grid() -> pl.DataFrame:
    return pl.read_csv(GRID, null_values="NA", infer_schema=False).with_columns(
        pl.col("adtm").str.to_datetime("%Y-%m-%dT%H:%M:%S", time_unit="us")
    )


# c1-119: one *DTM path in both namespaces, with the admiral highest_imputation levels.
@pytest.mark.parametrize("namespace", ["adam", "sdtm"])
@pytest.mark.parametrize("highest", ["n", "s", "m", "h", "D", "M"])
@pytest.mark.parametrize(
    ("date_imp", "time_imp"),
    [("first", "first"), ("last", "last"), ("first", "last"), ("last", "first")],
)
def test_datetime_target_equals_admiral_derive_vars_dtm(
    grid: pl.DataFrame, namespace: str, highest: str, date_imp: str, time_imp: str
) -> None:
    rows = grid.filter(
        pl.col("highest") == highest, pl.col("date_imp") == date_imp, pl.col("time_imp") == time_imp
    )
    assert rows.height == 15

    out = (
        getattr(rows.select("dtc"), namespace)
        .date("ADTM", source="dtc", impute=date_imp, impute_time=time_imp, highest=highest)
        .to_frame()
    )

    assert out.select("ADTM", "ADTF", "ATMF").rows() == rows.select("adtm", "adtf", "atmf").rows()


def test_admiral_default_preserve_drops_a_collected_time_below_a_missing_day() -> None:
    ae = pl.from_repr("""
┌─────────────────┬────────────┬─────────┐
│ AESTDTC         ┆ AESTDAT    ┆ AESTTIM │
│ ---             ┆ ---        ┆ ---     │
│ str             ┆ str        ┆ str     │
╞═════════════════╪════════════╪═════════╡
│ 2021-03--T08:30 ┆ 2021-03    ┆ 08:30   │
│ 2021-03-15T08   ┆ 2021-03-15 ┆ 08      │
└─────────────────┴────────────┴─────────┘
""")
    for ns in ("adam", "sdtm"):
        text = getattr(ae, ns).date("ASTDTM", source="AESTDTC").to_frame()
        timed = getattr(ae, ns).date("ASTDTM", source="AESTDAT", time="AESTTIM").to_frame()
        assert text["ASTDTM"].to_list() == [datetime(2021, 3, 1), datetime(2021, 3, 15, 8)]
        assert text["ASTDTF"].to_list() == ["D", None]
        assert text["ASTTMF"].to_list() == ["H", "M"]
        assert timed.select("ASTDTM", "ASTDTF", "ASTTMF").equals(
            text.select("ASTDTM", "ASTDTF", "ASTTMF")
        )
