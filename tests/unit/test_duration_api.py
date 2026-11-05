"""Tests for the unified .duration() verb on both SDTM and ADaM namespaces."""

from __future__ import annotations

import polars as pl
import pytest

import fleet  # noqa: F401  — register namespaces


@pytest.fixture()
def date_df() -> pl.DataFrame:
    return pl.from_repr("""\
┌─────────┬────────────┬────────────┐
│ USUBJID ┆ TRTSDT     ┆ ADT        │
│ ---     ┆ ---        ┆ ---        │
│ str     ┆ str        ┆ str        │
╞═════════╪════════════╪════════════╡
│ S01     ┆ 2024-01-01 ┆ 2024-01-10 │
│ S02     ┆ 2024-02-15 ┆ 2024-02-15 │
│ S03     ┆ 2024-03-10 ┆ 2024-03-08 │
└─────────┴────────────┴────────────┘
""").with_columns(
        pl.col("TRTSDT").str.to_date().alias("TRTSDT"),
        pl.col("ADT").str.to_date().alias("ADT"),
    )


@pytest.fixture()
def sdtm_date_df() -> pl.DataFrame:
    return pl.from_repr("""\
┌─────────┬────────────┬────────────┐
│ USUBJID ┆ SVSTDTC    ┆ RFSTDTC    │
│ ---     ┆ ---        ┆ ---        │
│ str     ┆ str        ┆ str        │
╞═════════╪════════════╪════════════╡
│ S01     ┆ 2024-01-05 ┆ 2024-01-01 │
│ S02     ┆ 2024-02-20 ┆ 2024-02-15 │
└─────────┴────────────┴────────────┘
""")


# ── ADaM .duration() ─────────────────────────────────────────────────


class TestAdamDuration:
    def test_study_day(self, date_df: pl.DataFrame) -> None:
        result = date_df.adam.duration("ADY", start="TRTSDT", end="ADT").to_frame()
        assert "ADY" in result.columns
        # Day 1 = reference date itself → 10 days diff + 1 = 10 (for S01)
        vals = result["ADY"].to_list()
        assert vals[0] == 10  # 9 days diff, +1 for >=0 → 10
        assert vals[1] == 1  # same day → 0 + 1 = 1

    def test_study_day_negative(self, date_df: pl.DataFrame) -> None:
        result = date_df.adam.duration("ADY", start="TRTSDT", end="ADT").to_frame()
        vals = result["ADY"].to_list()
        assert vals[2] == -2  # ADT before TRTSDT → negative, no +1

    def test_days_no_add_one(self, date_df: pl.DataFrame) -> None:
        result = date_df.adam.duration(
            "TRTDURD", start="TRTSDT", end="ADT", add_one=False
        ).to_frame()
        assert result["TRTDURD"].to_list() == [9, 0, -2]

    # Month and year lengths are averages: a year is 365.25 days, a month is 365.25 / 12
    # days. add_one counts both end days, so 2020-01-01 to 2021-01-01 is 367 days.
    @pytest.mark.parametrize(
        ("unit", "add_one", "expected"),
        [
            ("months", True, 367 / (365.25 / 12)),  # 12.0575
            ("months", False, 366 / (365.25 / 12)),  # 12.0246
            ("years", True, 367 / 365.25),  # 1.0048
            ("years", False, 366 / 365.25),  # 1.0021
        ],
    )
    def test_months_and_years(self, unit: str, add_one: bool, expected: float) -> None:
        df = pl.from_repr("""
        ┌────────────┬────────────┐
        │ TRTSDT     ┆ TRTEDT     │
        │ ---        ┆ ---        │
        │ date       ┆ date       │
        ╞════════════╪════════════╡
        │ 2020-01-01 ┆ 2021-01-01 │
        └────────────┴────────────┘
        """)
        result = df.adam.duration(
            "DUR", start="TRTSDT", end="TRTEDT", unit=unit, add_one=add_one
        ).to_frame()
        assert result["DUR"][0] == pytest.approx(expected, abs=1e-9)

    def test_hours(self) -> None:
        df = pl.from_repr("""\
┌─────────────────────┬─────────────────────┐
│ START               ┆ END                 │
│ ---                 ┆ ---                 │
│ str                 ┆ str                 │
╞═════════════════════╪═════════════════════╡
│ 2024-01-01T00:00:00 ┆ 2024-01-01T06:00:00 │
└─────────────────────┴─────────────────────┘
""").with_columns(
            pl.col("START").str.to_datetime(),
            pl.col("END").str.to_datetime(),
        )
        result = df.adam.duration(
            "DUR", start="START", end="END", unit="hours", add_one=False
        ).to_frame()
        assert result["DUR"][0] == pytest.approx(6.0)

    def test_invalid_unit(self, date_df: pl.DataFrame) -> None:
        with pytest.raises(ValueError, match="not supported"):
            date_df.adam.duration("X", start="TRTSDT", end="ADT", unit="fortnights")

    def test_iso8601_output(self, date_df: pl.DataFrame) -> None:
        result = date_df.adam.duration("DUR", start="TRTSDT", end="ADT", out="iso8601").to_frame()
        assert result["DUR"].to_list() == ["P9D", "P0D", "-P2D"]


# ── SDTM .duration() ─────────────────────────────────────────────────


class TestSdtmDuration:
    def test_study_day_from_strings(self, sdtm_date_df: pl.DataFrame) -> None:
        result = sdtm_date_df.sdtm.duration("SVSTDY", start="RFSTDTC", end="SVSTDTC").to_frame()
        assert "SVSTDY" in result.columns
        # DY suffix → auto add_one for >=0
        vals = result["SVSTDY"].to_list()
        assert vals[0] == 5  # 4 days + 1
        assert vals[1] == 6  # 5 days + 1

    def test_iso8601_duration(self, sdtm_date_df: pl.DataFrame) -> None:
        result = sdtm_date_df.sdtm.duration(
            "EXDUR", start="RFSTDTC", end="SVSTDTC", out="iso8601"
        ).to_frame()
        assert "EXDUR" in result.columns
        assert result["EXDUR"][0].startswith("P")
