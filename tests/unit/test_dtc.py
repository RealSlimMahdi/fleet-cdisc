"""The shared ``--DTC`` reader (package A of the alpha audit).

Expected values follow SDTMIG 3.4 sections 4.4.1 to 4.4.4: study day on the
date portion, right truncation and hyphens for missing components, and no
value invented.
"""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from fleet.core.dtc import (
    date_part,
    datetime_part,
    has_time,
    is_iso8601,
    to_day,
    warn_on_collect,
)


def _apply(expr_fn, values: list[str | None]) -> list:
    frame = pl.DataFrame({"x": values}, schema={"x": pl.String})
    return frame.select(expr_fn(pl.col("x"))).to_series().to_list()


def test_date_part_reads_the_date_of_complete_values_only() -> None:
    got = _apply(
        date_part,
        ["2021-03-20T10:30", "2021-03-20", "2021-03", "2021-02-30", "15MAR2021", "", None],
    )

    assert got == [dt.date(2021, 3, 20), dt.date(2021, 3, 20), None, None, None, None, None]


def test_datetime_part_keeps_the_collected_time_and_invents_none() -> None:
    got = _apply(
        datetime_part,
        [
            "2021-03-15T10:30",
            "2021-03-15T10:30:45.123",
            "2021-03-15T10:30:45+02:00",
            "2021-03-15T10",
            "2021-03-15",
        ],
    )

    assert got == [
        dt.datetime(2021, 3, 15, 10, 30),
        dt.datetime(2021, 3, 15, 10, 30, 45, 123000),
        dt.datetime(2021, 3, 15, 10, 30, 45),
        None,
        None,
    ]


def test_has_time_needs_hours_and_minutes() -> None:
    assert _apply(has_time, ["2021-03-15T10:30", "2021-03-15T10", "2021-03-15"]) == [
        True,
        False,
        False,
    ]


@pytest.mark.parametrize(
    "value",
    [
        "2021",
        "2021-03",
        "2021-03-15",
        "2021---15",
        "--03-15",
        "-----T08:30",
        "2021-03-15T10",
        "2021-03-15T10:30",
        "2021-03-15T10:30:45.123",
        "2021-03-15T10:30:45Z",
        "2021-03-15T10:30:45+02:00",
        "2021-03-15/2021-03-20",
    ],
)
def test_iso8601_accepts_every_sdtmig_form(value: str) -> None:
    assert _apply(is_iso8601, [value]) == [True]


@pytest.mark.parametrize(
    "value",
    [
        "UNK",
        "2021-UN-UN",
        "UN-MAR-2021",
        "2021-02-30",
        "2021-13-01",
        "2021-03-15T25:00",
        "2021-03-15 10:30",
        "15MAR2021:10:30:00",
        "03/04/2021",
        "2021-03-15T8:30",
    ],
)
def test_iso8601_refuses_what_sdtmig_does_not_allow(value: str) -> None:
    assert _apply(is_iso8601, [value]) == [False]


def test_to_day_reduces_text_datetime_and_date_to_the_date() -> None:
    frame = pl.DataFrame(
        {
            "txt": ["2024-01-09T20:00"],
            "dtm": [dt.datetime(2024, 1, 9, 20, 0)],
            "dat": [dt.date(2024, 1, 9)],
        }
    )

    out = frame.select(to_day(pl.col(c), frame.schema[c]) for c in frame.columns)

    assert out.row(0) == (dt.date(2024, 1, 9),) * 3


def test_warn_on_collect_warns_once_with_count_and_sample_and_stays_lazy() -> None:
    raw = pl.LazyFrame({"x": ["2021-03-15", "UNK", "foo", "UNK", None]})
    parsed = date_part(pl.col("x"))
    expr = warn_on_collect(
        parsed,
        pl.col("x").is_not_null() & parsed.is_null(),
        lambda n, sample: f"{n} value(s) did not convert: {sample}",
        dtype=pl.Date,
        shown=pl.col("x"),
    ).alias("y")
    plan = raw.with_columns(expr)

    assert plan.collect_schema()["y"] == pl.Date
    with pytest.warns(UserWarning, match=r"3 value\(s\) did not convert: \['UNK', 'foo'\]"):
        out = plan.collect()
    assert out["y"].to_list() == [dt.date(2021, 3, 15), None, None, None, None]
