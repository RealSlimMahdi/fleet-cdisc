"""Regression tests for the date engine: imputation ceiling, column types and durations.

Expected values follow admiral 1.4.1 (``derive_vars_dt``, ``derive_var_ontrtfl``,
``derive_vars_duration``), SDTMIG 3.4 section 4.4 and ISO 8601 durations.
"""

from __future__ import annotations

import warnings
from datetime import date, datetime

import polars as pl
import pytest

import fleet  # noqa: F401
from fleet.core.exceptions import DerivationError


@pytest.fixture
def partial_ae() -> pl.DataFrame:
    return pl.from_repr("""
┌─────────┬─────────────────┐
│ USUBJID ┆ AESTDTC         │
│ ---     ┆ ---             │
│ str     ┆ str             │
╞═════════╪═════════════════╡
│ 01      ┆ 2021            │
│ 02      ┆ 2021-03         │
│ 03      ┆ 2021-03-15      │
│ 04      ┆ 2021---15       │
│ 05      ┆ 2021-03--T08:30 │
└─────────┴─────────────────┘
""")


# c1-67, c1-74: highest= has the admiral highest_imputation meaning.
@pytest.mark.parametrize(
    ("highest", "adt", "adtf"),
    [
        (
            "M",
            [
                date(2021, 1, 1),
                date(2021, 3, 1),
                date(2021, 3, 15),
                date(2021, 1, 1),
                date(2021, 3, 1),
            ],
            ["M", "D", None, "M", "D"],
        ),
        (
            "D",
            [None, date(2021, 3, 1), date(2021, 3, 15), None, date(2021, 3, 1)],
            [None, "D", None, None, "D"],
        ),
        ("n", [None, None, date(2021, 3, 15), None, None], [None] * 5),
    ],
)
def test_highest_follows_admiral_highest_imputation(partial_ae, highest, adt, adtf) -> None:
    out = partial_ae.adam.date("ASTDT", source="AESTDTC", highest=highest).to_frame()
    assert out["ASTDT"].to_list() == adt
    assert out["ASTDTF"].to_list() == adtf


@pytest.mark.parametrize("highest", ["Y", "h", "m", "s", "X"])
def test_highest_refuses_levels_a_date_target_cannot_honour(partial_ae, highest) -> None:
    with pytest.raises(DerivationError, match="highest"):
        partial_ae.adam.date("ASTDT", source="AESTDTC", highest=highest)


# c1-119: a *DTM target takes highest=, except "Y", which needs bounds a *DTM target refuses.
@pytest.mark.parametrize("namespace", ["adam", "sdtm"])
def test_highest_y_on_a_datetime_target_raises(partial_ae, namespace) -> None:
    with pytest.raises(DerivationError, match="highest='Y' is not supported"):
        getattr(partial_ae, namespace).date("ASTDTM", source="AESTDTC", highest="Y")


def test_value_date_text_on_a_datetime_target_gives_midnight() -> None:
    frame = pl.from_repr("""
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ 01      │
└─────────┘
""")
    out = frame.adam.date("ASTDTM", value="2024-01-15").to_frame()
    assert out["ASTDTM"].to_list() == [datetime(2024, 1, 15)]


# c1-69: missing-middle forms impute; the flag reads the form, not the length.
def test_missing_middle_forms_impute_and_unread_values_have_no_flag() -> None:
    ae = pl.from_repr("""
┌─────────┬─────────────────┐
│ USUBJID ┆ AESTDTC         │
│ ---     ┆ ---             │
│ str     ┆ str             │
╞═════════╪═════════════════╡
│ 01      ┆ 2021---15       │
│ 02      ┆ 2021-03--T08:30 │
│ 03      ┆ 202103          │
│ 04      ┆ foo             │
└─────────┴─────────────────┘
""")
    with pytest.warns(UserWarning, match="not ISO 8601"):
        out = ae.adam.date("ASTDT", source="AESTDTC").to_frame()
    assert out["ASTDT"].to_list() == [date(2021, 1, 1), date(2021, 3, 1), None, None]
    assert out["ASTDTF"].to_list() == ["M", "D", None, None]


# c1-119: one *DTM path: time= first, then the imputation, then highest=, in both namespaces.
@pytest.mark.parametrize(
    ("highest", "astdtm", "astdtf", "asttmf"),
    [
        (
            None,
            [datetime(2024, 3, 15, 8, 15), datetime(2024, 3, 1), datetime(2024, 1, 1)],
            [None, "D", "M"],
            [None, "H", "H"],
        ),
        (
            "D",
            [datetime(2024, 3, 15, 8, 15), datetime(2024, 3, 1), None],
            [None, "D", None],
            [None, "H", None],
        ),
        ("h", [datetime(2024, 3, 15, 8, 15), None, None], [None] * 3, [None] * 3),
    ],
)
def test_datetime_target_with_time_is_one_path_in_both_namespaces(
    highest, astdtm, astdtf, asttmf
) -> None:
    ae = pl.from_repr("""
┌────────────┬──────────┐
│ AESTDTC    ┆ AESTTIM  │
│ ---        ┆ ---      │
│ str        ┆ str      │
╞════════════╪══════════╡
│ 2024-03-15 ┆ 08:15:00 │
│ 2024-03    ┆ 08:15:00 │
│ 2024       ┆ 08:15:00 │
└────────────┴──────────┘
""")
    call = {"source": "AESTDTC", "time": "AESTTIM", "highest": highest}
    adam = ae.adam.date("ASTDTM", **call).to_frame()
    sdtm = ae.sdtm.date("ASTDTM", **call).to_frame()
    assert adam["ASTDTM"].to_list() == astdtm
    assert adam["ASTDTF"].to_list() == astdtf
    assert adam["ASTTMF"].to_list() == asttmf
    assert adam.equals(sdtm)


def test_datetime_target_warns_on_a_time_of_another_layout() -> None:
    ae = pl.from_repr("""
┌────────────┬─────────┐
│ AESTDTC    ┆ AESTTIM │
│ ---        ┆ ---     │
│ str        ┆ str     │
╞════════════╪═════════╡
│ 2024-03-15 ┆ 0815    │
└────────────┴─────────┘
""")
    with pytest.warns(UserWarning, match="not hh:mm"):
        out = ae.adam.date("ASTDTM", source="AESTDTC", time="AESTTIM").to_frame()
    assert out["ASTDTM"].to_list() == [datetime(2024, 3, 15)]
    assert out["ASTTMF"].to_list() == ["H"]


# c1-117: a Date or Datetime source converts; a number raises with the fix.
@pytest.mark.parametrize("namespace", ["adam", "sdtm"])
def test_date_and_datetime_sources_convert(namespace) -> None:
    adsl = pl.from_repr("""
┌─────────┬────────────┬─────────────────────┐
│ USUBJID ┆ TRTSDT     ┆ TRTSDTM             │
│ ---     ┆ ---        ┆ ---                 │
│ str     ┆ date       ┆ datetime[μs]        │
╞═════════╪════════════╪═════════════════════╡
│ 01-001  ┆ 2021-03-15 ┆ 2021-03-15 10:30:00 │
└─────────┴────────────┴─────────────────────┘
""")
    ns = getattr(adsl, namespace)
    out = (
        ns.date("ADT", source="TRTSDT")
        .date("BDT", source="TRTSDTM")
        .date("CDTM", source="TRTSDTM")
        .date("DDTM", source="TRTSDT")
        .to_frame()
    )
    assert out["ADT"].to_list() == [date(2021, 3, 15)]
    assert out["BDT"].to_list() == [date(2021, 3, 15)]
    assert out["CDTM"].to_list() == [datetime(2021, 3, 15, 10, 30)]
    assert out["DDTM"].to_list() == [datetime(2021, 3, 15)]
    assert out["ADTF"].to_list() == [None]
    assert out["CTMF"].to_list() == [None]
    assert out["DTMF"].to_list() == ["H"]


@pytest.mark.parametrize("namespace", ["adam", "sdtm"])
@pytest.mark.parametrize("target", ["ADT", "ADTM"])
def test_numeric_source_raises_with_the_sas_conversion(namespace, target) -> None:
    adsl = pl.from_repr("""
┌─────────┬─────────┐
│ USUBJID ┆ TRTSDT  │
│ ---     ┆ ---     │
│ str     ┆ f64     │
╞═════════╪═════════╡
│ 01-001  ┆ 22354.0 │
└─────────┴─────────┘
""")
    with pytest.raises(DerivationError, match=r"TRTSDT is a number .*pl\.date\(1960, 1, 1\)"):
        getattr(adsl, namespace).date(target, source="TRTSDT")


def test_duration_from_a_number_raises() -> None:
    adsl = pl.from_repr("""
┌────────┬────────────┐
│ TRTSDT ┆ TRTEDT     │
│ ---    ┆ ---        │
│ f64    ┆ date       │
╞════════╪════════════╡
│ 3653.0 ┆ 2024-01-01 │
└────────┴────────────┘
""")
    with pytest.raises(DerivationError, match="duration.*TRTSDT is a number"):
        adsl.adam.duration("TRTDURD", start="TRTSDT", end="TRTEDT")


# c1-141: every day-arithmetic verb refuses a numeric date column.
@pytest.mark.parametrize(
    "call",
    [
        lambda f: f.adam.adsl.age_from_dates("AAGE", birth_date="BRTHDT", reference_date="TRTSDT"),
        lambda f: f.adam.on_treatment("ONTRTFL", adt="BRTHDT", trtsdt="TRTSDT", trtedt="TRTSDT"),
        lambda f: f.adam.occds.treatment_emergent(
            "TRTEMFL", start_date="TRTSDT", end_date=None, trtsdt="BRTHDT"
        ),
        lambda f: f.adam.peds.age_days("AGEDAYS", birth_date="BRTHDT", analysis_date="TRTSDT"),
    ],
)
def test_numeric_date_column_raises_in_every_day_verb(call) -> None:
    adsl = pl.from_repr("""
┌─────────┬────────┬────────────┐
│ USUBJID ┆ BRTHDT ┆ TRTSDT     │
│ ---     ┆ ---    ┆ ---        │
│ str     ┆ f64    ┆ date       │
╞═════════╪════════╪════════════╡
│ 01      ┆ 3653.0 ┆ 2024-01-01 │
└─────────┴────────┴────────────┘
""")
    with pytest.raises(DerivationError, match="BRTHDT is a number"):
        call(adsl).to_frame()


# c1-143: --DTC text is read by its date portion; a partial value gives null.
def test_day_verbs_read_dtc_text_by_its_date_portion() -> None:
    ae = pl.from_repr("""
┌─────────┬──────────────────┬────────────┬────────────┬────────────┐
│ USUBJID ┆ AESTDTC          ┆ AEENDTC    ┆ TRTSDT     ┆ TRTEDT     │
│ ---     ┆ ---              ┆ ---        ┆ ---        ┆ ---        │
│ str     ┆ str              ┆ str        ┆ date       ┆ date       │
╞═════════╪══════════════════╪════════════╪════════════╪════════════╡
│ 01      ┆ 2024-01-05       ┆ 2024-01-09 ┆ 2024-01-02 ┆ 2024-03-01 │
│ 01      ┆ 2024-01          ┆ 2024-01-09 ┆ 2024-01-02 ┆ 2024-03-01 │
│ 01      ┆ 2024-01-05T10:00 ┆ 2024-01-09 ┆ 2024-01-02 ┆ 2024-03-01 │
└─────────┴──────────────────┴────────────┴────────────┴────────────┘
""")
    on = ae.adam.on_treatment("ONTRTFL", adt="AESTDTC", trtsdt="TRTSDT", trtedt="TRTEDT")
    assert on.to_frame()["ONTRTFL"].to_list() == ["Y", None, "Y"]
    rec = ae.adam.occds.onset_recovery(
        "RCVRYFL", start_date="AESTDTC", end_date="AEENDTC", ref_date="TRTSDT"
    )
    assert rec.to_frame()["RCVRYFL"].to_list() == ["Y", None, "Y"]
    days = ae.adam.peds.age_days("D", birth_date="TRTSDT", analysis_date="AESTDTC")
    assert days.to_frame()["D"].to_list() == [3, None, 3]
    age = ae.adam.adsl.age_from_dates("AAGE", birth_date="AESTDTC", reference_date="TRTEDT")
    assert age.to_frame()["AAGE"].null_count() == 1


# c1-78: on_treatment keeps the time of the start comparison for two date-times.
def test_on_treatment_compares_start_with_time_for_datetimes() -> None:
    adeg = pl.from_repr("""
┌─────────┬─────────────────────┬─────────────────────┬─────────────────────┐
│ USUBJID ┆ ADTM                ┆ TRTSDTM             ┆ TRTEDTM             │
│ ---     ┆ ---                 ┆ ---                 ┆ ---                 │
│ str     ┆ datetime[μs]        ┆ datetime[μs]        ┆ datetime[μs]        │
╞═════════╪═════════════════════╪═════════════════════╪═════════════════════╡
│ 01      ┆ 2024-01-10 07:00:00 ┆ 2024-01-10 09:00:00 ┆ 2024-01-20 09:00:00 │
│ 02      ┆ 2024-01-10 07:00:00 ┆ 2024-01-10 09:00:00 ┆ null                │
│ 03      ┆ 2024-01-10 09:30:00 ┆ 2024-01-10 09:00:00 ┆ 2024-01-20 09:00:00 │
│ 04      ┆ 2024-01-20 10:00:00 ┆ 2024-01-10 09:00:00 ┆ 2024-01-20 09:00:00 │
└─────────┴─────────────────────┴─────────────────────┴─────────────────────┘
""")
    out = adeg.adam.on_treatment("ONTRTFL", adt="ADTM", trtsdt="TRTSDTM", trtedt="TRTEDTM")
    assert out.to_frame()["ONTRTFL"].to_list() == [None, None, "Y", "Y"]


def test_on_treatment_with_a_date_analysis_value_stays_at_date_level() -> None:
    adeg = pl.from_repr("""
┌────────────┬─────────────────────┬─────────────────────┐
│ ADT        ┆ TRTSDTM             ┆ TRTEDTM             │
│ ---        ┆ ---                 ┆ ---                 │
│ date       ┆ datetime[μs]        ┆ datetime[μs]        │
╞════════════╪═════════════════════╪═════════════════════╡
│ 2024-01-10 ┆ 2024-01-10 09:00:00 ┆ 2024-01-20 09:00:00 │
└────────────┴─────────────────────┴─────────────────────┘
""")
    out = adeg.adam.on_treatment("ONTRTFL", adt="ADT", trtsdt="TRTSDTM", trtedt="TRTEDTM")
    assert out.to_frame()["ONTRTFL"].to_list() == ["Y"]


# c1-371: aval() reads each row from its own date or date-time columns.
def test_aval_mixes_date_and_datetime_parameters() -> None:
    adtte = pl.from_repr("""
┌─────────┬─────────┬────────────┬────────────┬─────────────────────┬─────────────────────┐
│ USUBJID ┆ PARAMCD ┆ STARTDT    ┆ ADT        ┆ STARTDTM            ┆ ADTM                │
│ ---     ┆ ---     ┆ ---        ┆ ---        ┆ ---                 ┆ ---                 │
│ str     ┆ str     ┆ date       ┆ date       ┆ datetime[μs]        ┆ datetime[μs]        │
╞═════════╪═════════╪════════════╪════════════╪═════════════════════╪═════════════════════╡
│ 01      ┆ OS      ┆ 2023-01-01 ┆ 2023-03-01 ┆ null                ┆ null                │
│ 02      ┆ OS      ┆ 2023-01-02 ┆ 2023-06-30 ┆ null                ┆ null                │
│ 01      ┆ TTAE    ┆ null       ┆ null       ┆ 2023-01-01 00:00:00 ┆ 2023-01-10 08:00:00 │
│ 02      ┆ TTAE    ┆ null       ┆ null       ┆ 2023-01-02 00:00:00 ┆ 2023-02-05 08:00:00 │
└─────────┴─────────┴────────────┴────────────┴─────────────────────┴─────────────────────┘
""")
    out = adtte.adam.tte.aval().to_frame()
    assert out["AVAL"].to_list() == [60.0, 180.0, 10.0, 35.0]


# c1-4: a pl.Expr input is read by its type, as a column name is.
def test_duration_expression_input_takes_the_date_part() -> None:
    ae = pl.from_repr("""
┌─────────────────────┬─────────────────────┐
│ ASTDTM              ┆ TRTSDTM             │
│ ---                 ┆ ---                 │
│ datetime[μs]        ┆ datetime[μs]        │
╞═════════════════════╪═════════════════════╡
│ 2021-03-16 07:00:00 ┆ 2021-03-15 08:00:00 │
│ 2021-03-14 09:00:00 ┆ 2021-03-15 08:00:00 │
│ 2021-03-13 09:00:00 ┆ 2021-03-15 08:00:00 │
│ 2021-03-17 07:59:00 ┆ 2021-03-15 08:00:00 │
└─────────────────────┴─────────────────────┘
""")
    by_expr = ae.adam.duration("ASTDY", start=pl.col("TRTSDTM"), end=pl.col("ASTDTM"))
    by_name = ae.adam.duration("ASTDY", start="TRTSDTM", end="ASTDTM")
    assert by_expr.to_frame()["ASTDY"].to_list() == [2, -1, -2, 3]
    assert by_name.to_frame()["ASTDY"].to_list() == [2, -1, -2, 3]


# c1-5: hours on a date-only text give null and one warning with the count.
def test_duration_in_hours_warns_on_values_with_no_time() -> None:
    pc = pl.from_repr("""
┌─────────────────────┬─────────────────────┐
│ EXSTDTC             ┆ PCDTC               │
│ ---                 ┆ ---                 │
│ str                 ┆ str                 │
╞═════════════════════╪═════════════════════╡
│ 2021-03-15T08:00:00 ┆ 2021-03-15T14:30:00 │
│ 2021-03-15          ┆ 2021-03-15T14:30:00 │
│ 2021-03-15T08       ┆ 2021-03-15T14:30:00 │
└─────────────────────┴─────────────────────┘
""")
    with pytest.warns(UserWarning, match=r"2 value\(s\) of EXSTDTC have no hour and minute"):
        out = pc.adam.duration(
            "AFRLT", start="EXSTDTC", end="PCDTC", unit="hours", add_one=False
        ).to_frame()
    assert out["AFRLT"].to_list() == [6.5, None, None]


def test_duration_in_hours_on_timed_text_gives_no_warning() -> None:
    pc = pl.from_repr("""
┌─────────────────────┬─────────────────────┐
│ EXSTDTC             ┆ PCDTC               │
│ ---                 ┆ ---                 │
│ str                 ┆ str                 │
╞═════════════════════╪═════════════════════╡
│ 2021-03-15T08:00:00 ┆ 2021-03-15T14:30:00 │
│ null                ┆ 2021-03-15T14:30:00 │
└─────────────────────┴─────────────────────┘
""")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        out = pc.adam.duration("AFRLT", start="EXSTDTC", end="PCDTC", unit="hours").to_frame()
    assert out["AFRLT"].to_list() == [6.5, None]


# c1-7: ISO 8601 output keeps the sign, splits the clock and adds one on request only.
@pytest.fixture
def pc_eltm() -> pl.DataFrame:
    return pl.from_repr("""
┌─────────┬──────────────────┬──────────────────┐
│ USUBJID ┆ RFDTC            ┆ PCDTC            │
│ ---     ┆ ---              ┆ ---              │
│ str     ┆ str              ┆ str              │
╞═════════╪══════════════════╪══════════════════╡
│ S1      ┆ 2021-01-01T08:00 ┆ 2021-01-01T07:45 │
│ S1      ┆ 2021-01-01T08:00 ┆ 2021-01-01T09:30 │
│ S1      ┆ 2021-01-01T08:00 ┆ 2021-01-01T10:00 │
│ S1      ┆ 2021-01-01T08:00 ┆ 2021-01-01T08:00 │
│ S1      ┆ 2021-01-01T08:00 ┆ null             │
└─────────┴──────────────────┴──────────────────┘
""")


@pytest.mark.parametrize("unit", ["hours", "minutes", "seconds"])
def test_iso8601_clock_duration_keeps_sign_and_parts(pc_eltm, unit) -> None:
    out = pc_eltm.sdtm.duration("PCELTM", start="RFDTC", end="PCDTC", unit=unit, out="iso8601")
    zero = {"hours": "PT0H", "minutes": "PT0M", "seconds": "PT0S"}[unit]
    assert out.to_frame()["PCELTM"].to_list() == ["-PT15M", "PT1H30M", "PT2H", zero, None]


def test_iso8601_day_duration_adds_one_only_on_request() -> None:
    ex = pl.from_repr("""
┌────────────┬────────────┐
│ EXSTDTC    ┆ EXENDTC    │
│ ---        ┆ ---        │
│ str        ┆ str        │
╞════════════╪════════════╡
│ 2021-01-01 ┆ 2021-01-10 │
│ 2021-01-01 ┆ 2021-01-01 │
│ 2021-01-10 ┆ 2021-01-01 │
└────────────┴────────────┘
""")
    default = ex.sdtm.duration("EXDUR", start="EXSTDTC", end="EXENDTC", out="iso8601")
    assert default.to_frame()["EXDUR"].to_list() == ["P9D", "P0D", "-P9D"]
    inclusive = ex.sdtm.duration(
        "EXDUR", start="EXSTDTC", end="EXENDTC", out="iso8601", add_one=True
    )
    assert inclusive.to_frame()["EXDUR"].to_list() == ["P10D", "P1D", "-P9D"]


def test_iso8601_weeks_need_whole_weeks() -> None:
    ex = pl.from_repr("""
┌────────────┬────────────┐
│ EXSTDTC    ┆ EXENDTC    │
│ ---        ┆ ---        │
│ str        ┆ str        │
╞════════════╪════════════╡
│ 2021-01-01 ┆ 2021-01-15 │
│ 2021-01-01 ┆ 2021-01-10 │
└────────────┴────────────┘
""")
    with pytest.warns(UserWarning, match="not whole weeks"):
        out = ex.sdtm.duration(
            "EXDUR", start="EXSTDTC", end="EXENDTC", unit="weeks", out="iso8601"
        ).to_frame()
    assert out["EXDUR"].to_list() == ["P2W", None]


@pytest.mark.parametrize("unit", ["months", "years"])
def test_iso8601_months_and_years_raise(unit) -> None:
    ex = pl.from_repr("""
┌────────────┬────────────┐
│ EXSTDTC    ┆ EXENDTC    │
│ ---        ┆ ---        │
│ str        ┆ str        │
╞════════════╪════════════╡
│ 2021-01-01 ┆ 2021-03-15 │
└────────────┴────────────┘
""")
    with pytest.raises(DerivationError, match="no fixed length"):
        ex.sdtm.duration("EXDUR", start="EXSTDTC", end="EXENDTC", unit=unit, out="iso8601")
