"""ADSL and OCCDS rules of package B of the alpha audit.

* ``treatment_emergent`` follows admiral ``derive_var_trtemfl`` case by case
  (Mahdi, 2026-11-02, Q1 of round 1);
* a top-level ``order`` and ``mode`` of ``pick`` act across events, as in
  admiral ``derive_vars_extreme_event`` (engineering decision on c1-124);
* ``recode`` gives the type of its map values, and a mixed map raises
  (engineering decision on c1-121).
"""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

import fleet  # noqa: F401  (registers the namespaces)
from fleet.core.exceptions import DerivationError

# ── treatment_emergent (c1-144) ───────────────────────────────────────────────

ADAE = pl.from_repr("""
┌─────────┬────────────┬────────────┬────────────┬────────────┐
│ USUBJID ┆ ASTDT      ┆ AENDT      ┆ TRTSDT     ┆ TRTEDT     │
│ ---     ┆ ---        ┆ ---        ┆ ---        ┆ ---        │
│ str     ┆ date       ┆ date       ┆ date       ┆ date       │
╞═════════╪════════════╪════════════╪════════════╪════════════╡
│ NOSTART ┆ null       ┆ null       ┆ 2024-01-10 ┆ 2024-03-10 │
│ ENDPRE  ┆ null       ┆ 2024-01-05 ┆ 2024-01-10 ┆ 2024-03-10 │
│ ENDPOST ┆ null       ┆ 2024-02-01 ┆ 2024-01-10 ┆ 2024-03-10 │
│ BEFORE  ┆ 2024-01-09 ┆ null       ┆ 2024-01-10 ┆ 2024-03-10 │
│ DAY1    ┆ 2024-01-10 ┆ null       ┆ 2024-01-10 ┆ 2024-03-10 │
│ LATE    ┆ 2024-03-15 ┆ null       ┆ 2024-01-10 ┆ 2024-03-10 │
│ NOTRT   ┆ 2024-02-01 ┆ null       ┆ null       ┆ null       │
│ OPENEND ┆ 2024-06-01 ┆ null       ┆ 2024-01-10 ┆ null       │
└─────────┴────────────┴────────────┴────────────┴────────────┘
""")


def _teae(**kwargs) -> list[str | None]:
    return (
        ADAE.adam.occds.treatment_emergent(
            "TRTEMFL", start_date="ASTDT", end_date="AENDT", trtsdt="TRTSDT", **kwargs
        )
        .to_frame()["TRTEMFL"]
        .to_list()
    )


def test_teae_without_an_end_window_follows_admiral() -> None:
    """admiral: TRTSDT missing -> no flag; end before TRTSDT -> no flag; start missing -> Y."""
    assert _teae() == ["Y", None, "Y", None, "Y", "Y", None, "Y"]


def test_teae_with_an_end_window_bounds_the_start_and_keeps_an_open_trtedt() -> None:
    zero = _teae(trtedt="TRTEDT", end_window=0)
    thirty = _teae(trtedt="TRTEDT", end_window=30)

    assert zero == ["Y", None, "Y", None, "Y", None, None, "Y"]
    assert thirty == ["Y", None, "Y", None, "Y", "Y", None, "Y"]


def test_teae_reads_timed_dtc_text_by_its_date() -> None:
    ae = pl.DataFrame(
        {
            "AESTDTC": ["2024-01-10T08:00", None],
            "AEENDTC": [None, "2024-01-05"],
            "TRTSDT": [dt.date(2024, 1, 10)] * 2,
        }
    )

    out = ae.adam.occds.treatment_emergent(
        start_date="AESTDTC", end_date="AEENDTC", trtsdt="TRTSDT"
    ).to_frame()

    assert out["TRTEMFL"].to_list() == ["Y", None]


def test_teae_end_window_needs_trtedt_and_trtedt_needs_an_end_window() -> None:
    with pytest.raises(DerivationError, match="end_window"):
        _teae(trtedt="TRTEDT")
    with pytest.raises(DerivationError, match="trtedt"):
        _teae(end_window=0)
    with pytest.raises(DerivationError, match="end_window"):
        _teae(trtedt="TRTEDT", end_window=-1)


def test_teae_needs_end_date_stated() -> None:
    with pytest.raises(TypeError, match="end_date"):
        ADAE.adam.occds.treatment_emergent("TRTEMFL", start_date="ASTDT", trtsdt="TRTSDT")


# ── pick across events (c1-124) ───────────────────────────────────────────────

DEATH = pl.DataFrame({"USUBJID": ["S5"], "DTHDT": [dt.date(2024, 1, 20)]})
AE_END = pl.DataFrame(
    {
        "USUBJID": ["S2", "S2", "S4", "S5"],
        "AENDT": [
            dt.date(2024, 2, 10),
            dt.date(2024, 4, 20),
            dt.date(2024, 1, 5),
            dt.date(2024, 1, 20),
        ],
    }
)
TRT_END = pl.DataFrame(
    {"USUBJID": ["S2", "S4", "S5"], "TRTEDT": [dt.date(2024, 3, 1), dt.date(2024, 3, 10), None]}
)
EVENTS = [
    {
        "when": pl.col("DTHDT").is_not_null(),
        "set": {"LSTALVDT": "DTHDT", "DTHFL": pl.lit("Y")},
        "source": DEATH,
    },
    {
        "when": pl.col("AENDT").is_not_null(),
        "set": {"LSTALVDT": "AENDT", "DTHFL": pl.lit("N")},
        "source": AE_END,
    },
    {
        "when": pl.col("TRTEDT").is_not_null(),
        "set": {"LSTALVDT": "TRTEDT", "DTHFL": pl.lit("N")},
        "source": TRT_END,
    },
]
SUBJECTS = pl.DataFrame({"USUBJID": ["S2", "S4", "S5"]})


def test_pick_with_a_top_level_order_takes_the_latest_over_all_events() -> None:
    """admiral LSTALVDT template: order = exprs(LSTALVDT, ...), mode = "last"."""
    out = SUBJECTS.adam.adsl.pick(
        ["LSTALVDT", "DTHFL"], events=EVENTS, order_by=["LSTALVDT"], mode="last"
    ).to_frame()

    assert out["LSTALVDT"].to_list() == [
        dt.date(2024, 4, 20),
        dt.date(2024, 3, 10),
        dt.date(2024, 1, 20),
    ]


def test_pick_tie_across_events_goes_to_the_first_listed_event() -> None:
    out = SUBJECTS.adam.adsl.pick(
        ["LSTALVDT", "DTHFL"], events=EVENTS, order_by=["LSTALVDT"], mode="last"
    ).to_frame()

    assert out.filter(pl.col("USUBJID") == "S5")["DTHFL"].to_list() == ["Y"]


def test_pick_without_a_top_level_order_keeps_the_priority_cascade() -> None:
    """admiral DTHCAUS template: the first listed event with data wins."""
    events = [
        {**EVENTS[0]},
        {**EVENTS[1], "order_by": ["AENDT"], "mode": "last"},
        {**EVENTS[2]},
    ]

    out = SUBJECTS.adam.adsl.pick(["LSTALVDT", "DTHFL"], events=events).to_frame()

    assert out["LSTALVDT"].to_list() == [
        dt.date(2024, 4, 20),
        dt.date(2024, 1, 5),
        dt.date(2024, 1, 20),
    ]


# ── recode types (c1-121) ─────────────────────────────────────────────────────

ADAE_SEV = pl.DataFrame({"AESEV": ["MILD", "SEVERE", "mild", None]})


def test_recode_to_integers_gives_an_integer_column() -> None:
    out = ADAE_SEV.adam.recode(
        "ASEVN", source="AESEV", recode_map={"MILD": 1, "MODERATE": 2, "SEVERE": 3}
    ).to_frame()

    assert out.schema["ASEVN"] == pl.Int64
    assert out["ASEVN"].to_list() == [1, 3, None, None]


def test_recode_max_on_a_numeric_scale_compares_numbers() -> None:
    adae = pl.DataFrame({"USUBJID": ["S1"] * 3, "CODE": ["A", "B", "C"]})

    out = (
        adae.adam.recode("SEVN", source="CODE", recode_map={"A": 2, "B": 9, "C": 10})
        .flag("MAXFL", criteria="max", value_col="SEVN", by=["USUBJID"])
        .to_frame()
    )

    assert out["MAXFL"].to_list() == [None, None, "Y"]


def test_recode_mixed_int_and_float_gives_float_and_ignores_none() -> None:
    floats = ADAE_SEV.adam.recode(
        "X", source="AESEV", recode_map={"MILD": 1, "SEVERE": 2.5}
    ).to_frame()
    ints = ADAE_SEV.adam.recode("Y", source="AESEV", recode_map={"MILD": 1, "UNK": None}).to_frame()

    assert floats["X"].to_list() == [1.0, 2.5, None, None]
    assert ints.schema["Y"] == pl.Int64


def test_recode_to_text_stays_text() -> None:
    out = ADAE_SEV.adam.recode("SEVC", source="AESEV", recode_map={"MILD": "1"}).to_frame()

    assert out.schema["SEVC"] == pl.String


@pytest.mark.parametrize(
    ("recode_map", "default"),
    [({"MILD": 1, "SEVERE": "3"}, None), ({"MILD": 1, "SEVERE": 3}, "UNK")],
)
def test_recode_with_mixed_types_raises(recode_map: dict, default: object) -> None:
    with pytest.raises(DerivationError, match="ASEVN"):
        ADAE_SEV.adam.recode(
            "ASEVN", source="AESEV", recode_map=recode_map, default=default
        ).to_frame()
