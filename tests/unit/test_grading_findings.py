"""Alpha audit package D: hand-checked grades from the findings (admiral 1.4.1 values)."""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

import fleet  # noqa: F401
from fleet.core.exceptions import DerivationError

ADT = date(2020, 6, 15)
ADULT, CHILD_3Y, NEONATE_2D, NEONATE_5D = (
    date(1980, 1, 1),
    date(2017, 3, 1),
    date(2020, 6, 13),
    date(2020, 6, 10),
)
SCHEMA = {
    "TERM": pl.String,
    "AVAL": pl.Float64,
    "ANRLO": pl.Float64,
    "ANRHI": pl.Float64,
    "BASE": pl.Float64,
    "PCHG": pl.Float64,
    "BNRIND": pl.String,
    "SEX": pl.String,
    "BRTHDT": pl.Date,
    "ADT": pl.Date,
    "AVALU": pl.String,
}


def _grade(system: str, direction: str, unit_var: str | None = "AVALU", **row) -> str | None:
    frame = pl.DataFrame([{**dict.fromkeys(SCHEMA), "ADT": ADT, **row}], schema=SCHEMA)
    out = frame.adam.atoxgr(
        "GR", system=system, direction=direction, term_var="TERM", unit_var=unit_var
    ).to_frame()
    return out["GR"][0]


CASES = [
    # c1-380: a null BNRIND takes the ULN branch, as admiral !(BNRIND %in% high_indicator).
    ("ctcae_v5", "H", "Alanine aminotransferase increased", {"AVAL": 900, "ANRHI": 40}, "4"),
    ("ctcae_v6", "H", "Creatinine increased", {"AVAL": 288, "ANRHI": 90}, "3"),
    # c1-381: the unit matches without case; another unit gives null.
    ("ctcae_v5", "H", "Hyperkalemia", {"AVAL": 7.5, "ANRHI": 5.0, "AVALU": "mmol/L"}, "4"),
    ("ctcae_v5", "H", "Hyperkalemia", {"AVAL": 7.5, "ANRHI": 5.0, "AVALU": "MMOL/L"}, "4"),
    ("ctcae_v5", "H", "Hyperkalemia", {"AVAL": 7.5, "ANRHI": 5.0, "AVALU": "Mmol/l"}, "4"),
    ("ctcae_v5", "H", "Hyperkalemia", {"AVAL": 7.5, "ANRHI": 5.0, "AVALU": "mEq/L"}, None),
    ("ctcae_v5", "L", "Anemia", {"AVAL": 75, "ANRLO": 120, "AVALU": "G/L"}, "3"),
    # c1-382: each row takes the entry of its own subgroup and unit.
    (
        "daids",
        "L",
        "Hemoglobin, Low",
        {"AVAL": 60, "SEX": "M", "BRTHDT": ADULT, "AVALU": "g/L"},
        "4",
    ),
    (
        "daids",
        "L",
        "Hemoglobin, Low",
        {"AVAL": 60, "SEX": "F", "BRTHDT": ADULT, "AVALU": "g/L"},
        "4",
    ),
    (
        "daids",
        "L",
        "Hemoglobin, Low",
        {"AVAL": 60, "SEX": "M", "BRTHDT": NEONATE_2D, "AVALU": "g/L"},
        "4",
    ),
    (
        "ctcae_v5_uscv",
        "L",
        "Platelet count decreased",
        {"AVAL": 10, "ANRLO": 150, "AVALU": "10^3/uL"},
        "4",
    ),
    (
        "ctcae_v5_uscv",
        "L",
        "Platelet count decreased",
        {"AVAL": 300, "ANRLO": 150, "AVALU": "10^3/uL"},
        "0",
    ),
    (
        "daids",
        "L",
        "Absolute CD4+ Count, Low",
        {"AVAL": 0.05, "BRTHDT": ADULT, "AVALU": "10^9/L"},
        "4",
    ),
    (
        "daids",
        "L",
        "Absolute CD4+ Count, Low",
        {"AVAL": 0.05, "BRTHDT": CHILD_3Y, "AVALU": "10^9/L"},
        None,
    ),
    ("daids", "H", "Total Bilirubin, High", {"AVAL": 50, "ANRHI": 20, "BRTHDT": ADULT}, "2"),
    ("daids", "H", "Total Bilirubin, High", {"AVAL": 50, "ANRHI": 20, "BRTHDT": CHILD_3Y}, "2"),
    ("daids", "H", "Total Bilirubin, High", {"AVAL": 50, "ANRHI": 20, "BRTHDT": NEONATE_5D}, None),
    # c1-392: INR takes the worse of the absolute and the baseline cut-offs (Q1 A).
    ("ctcae_v5", "H", "INR increased", {"AVAL": 3.0, "BASE": 2.0}, "3"),
    ("ctcae_v5", "H", "INR increased", {"AVAL": 3.0}, "3"),
    ("ctcae_v5", "H", "INR increased", {"AVAL": 1.15, "BASE": 1.0}, "1"),
    ("ctcae_v6", "L", "Creatinine clearance decreased", {"AVAL": 5, "AVALU": "mL/min"}, None),
    ("ctcae_v4", "H", "Creatinine increased", {"AVAL": 110, "ANRHI": 100}, "1"),
    (
        "ctcae_v4",
        "H",
        "Hemoglobin increased",
        {"AVAL": 200, "ANRHI": 160, "BASE": 150, "AVALU": "g/L"},
        "2",
    ),
]


@pytest.mark.parametrize(("system", "direction", "term", "row", "expected"), CASES)
def test_grade_equals_admiral(system: str, direction: str, term: str, row: dict, expected) -> None:
    assert _grade(system, direction, TERM=term, **row) == expected


def test_null_bnrind_grades_as_normal_on_every_branch_term() -> None:
    for system in ("ctcae_v5", "ctcae_v6"):
        for aval in (45.0, 130.0, 210.0, 900.0):
            row = {"TERM": "Alanine aminotransferase increased", "AVAL": aval, "ANRHI": 40.0}
            normal = _grade(system, "H", BNRIND="NORMAL", BASE=30.0, **row)
            assert _grade(system, "H", BASE=30.0, **row) == normal
            assert _grade(system, "H", BNRIND="", BASE=30.0, **row) == normal


def test_a_term_with_several_units_needs_unit_var() -> None:
    with pytest.raises(DerivationError, match="unit_var="):
        _grade(
            "ctcae_v5_uscv",
            "L",
            unit_var=None,
            TERM="Platelet count decreased",
            AVAL=250,
            ANRLO=150,
        )


def test_a_missing_column_is_named() -> None:
    frame = pl.DataFrame({"TERM": ["Anemia"], "AVAL": [75.0]})
    with pytest.raises(DerivationError, match="ANRLO"):
        frame.adam.atoxgr("GR", system="ctcae_v5", direction="L", term_var="TERM")


def test_rows_keep_their_order_and_count() -> None:
    frame = pl.from_repr("""\
┌───────────────┬───────┬───────┬───────┐
│ TERM          ┆ AVAL  ┆ ANRLO ┆ AVALU │
│ ---           ┆ ---   ┆ ---   ┆ ---   │
│ str           ┆ f64   ┆ f64   ┆ str   │
╞═══════════════╪═══════╪═══════╪═══════╡
│ Anemia        ┆ 130.0 ┆ 120.0 ┆ g/L   │
│ Unknown term  ┆ 1.0   ┆ 1.0   ┆ g/L   │
│ null          ┆ 1.0   ┆ 1.0   ┆ g/L   │
│ Anemia        ┆ 75.0  ┆ 120.0 ┆ g/L   │
└───────────────┴───────┴───────┴───────┘
""")

    out = frame.adam.atoxgr(
        "GR", system="ctcae_v5", direction="L", term_var="TERM", unit_var="AVALU"
    ).to_frame()

    assert out["AVAL"].to_list() == [130.0, 1.0, 1.0, 75.0]
    assert out["GR"].to_list() == ["0", None, None, "3"]
