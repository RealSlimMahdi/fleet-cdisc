"""Every date verb reads ``--DTC`` text one way (package A of the alpha audit).

Rules, with their sources:

* study day uses the date portion (SDTMIG 3.4 section 4.4.4); a partial
  date gives null (CG0007);
* baseline is the last record strictly before the reference; a record on
  the reference date with no time is not eligible (Mahdi, 2026-11-02, Q1 B);
* EPOCH on a transition date with no time: Findings (``--DTC``) take the
  earlier element, Events and Interventions (``--STDTC``) the later one,
  and ``same_day=`` overrides (Q2 E);
* duration adds one day only when the end is on or after the start, as
  admiral ``compute_duration`` (Q3 A);
* ``.sdtm.date()`` refuses to guess a layout (Q4 A), writes null for a value
  it cannot convert and warns (c1-90), and writes ``-----T08:30`` for a time
  with no date (Q5 A, SDTMIG 4.4.2);
* first and last dates leave a partial value out unless ``impute=`` states
  a rule (c1-118).
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import polars as pl
import pytest

import fleet  # noqa: F401  (registers the namespaces)
from fleet.core.exceptions import DerivationError

# ── Study day and duration (c1-3, c1-6) ───────────────────────────────────────


def test_study_day_uses_the_date_portion_of_timed_text() -> None:
    ae = pl.from_repr("""
┌─────────┬──────────────────┬──────────────────┐
│ USUBJID ┆ AESTDTC          ┆ RFSTDTC          │
│ ---     ┆ ---              ┆ ---              │
│ str     ┆ str              ┆ str              │
╞═════════╪══════════════════╪══════════════════╡
│ S1      ┆ 2021-03-20T10:30 ┆ 2021-03-15T08:00 │
│ S1      ┆ 2021-03-15T07:00 ┆ 2021-03-15T08:00 │
│ S1      ┆ 2021-03-14T23:59 ┆ 2021-03-15T08:00 │
│ S1      ┆ 2021-03          ┆ 2021-03-15T08:00 │
└─────────┴──────────────────┴──────────────────┘
""")

    out = ae.sdtm.study_day("AESTDY", date_col="AESTDTC", ref_col="RFSTDTC").to_frame()

    assert out["AESTDY"].to_list() == [6, 1, -1, None]


def test_study_day_from_a_pinned_dm_with_a_timed_rfstdtc() -> None:
    ae = pl.DataFrame({"USUBJID": ["S1", "S1"], "AESTDTC": ["2021-03-20", "2021-03-20T10:30"]})
    dm = pl.DataFrame({"USUBJID": ["S1"], "RFSTDTC": ["2021-03-15T08:00"]})

    out = ae.sdtm.pin("DM", dm).study_day("AESTDY", date_col="AESTDTC").to_frame()

    assert out["AESTDY"].to_list() == [6, 6]


def test_study_day_on_datetimes_uses_the_date() -> None:
    adlb = pl.DataFrame(
        {
            "USUBJID": ["S1", "S1"],
            "ADTM": [dt.datetime(2024, 1, 9, 20, 0), dt.datetime(2024, 1, 11, 6, 0)],
            "TRTSDTM": [dt.datetime(2024, 1, 10, 10, 0)] * 2,
        }
    )

    out = adlb.adam.study_day("ADY", date_col="ADTM", ref_col="TRTSDTM").to_frame()

    assert out["ADY"].to_list() == [-1, 2]


def test_duration_in_days_reads_timed_text_without_raising() -> None:
    ae = pl.DataFrame({"RFSTDTC": ["2021-03-15T08:00"], "AESTDTC": ["2021-03-20T10:30"]})

    out = ae.sdtm.duration("AESTDY", start="RFSTDTC", end="AESTDTC").to_frame()

    assert out["AESTDY"].to_list() == [6]


@pytest.mark.parametrize(
    ("unit", "expected"),
    [("days", 85), ("weeks", 85 / 7), ("months", 85 / 30.4375), ("years", 85 / 365.25)],
)
def test_duration_adds_one_day_before_dividing(unit: str, expected: float) -> None:
    """ADaMIG 1.3 TRTDURD/M/Y: each is the entire duration; admiral compute_duration."""
    adsl = pl.DataFrame({"TRTSDT": [dt.date(2021, 1, 1)], "TRTEDT": [dt.date(2021, 3, 26)]})

    out = adsl.adam.duration("TRTDUR", start="TRTSDT", end="TRTEDT", unit=unit).to_frame()

    assert out["TRTDUR"][0] == pytest.approx(expected)


def test_duration_of_a_negative_span_adds_nothing() -> None:
    adae = pl.DataFrame({"ASTDT": [dt.date(2024, 1, 11)], "AENDT": [dt.date(2024, 1, 10)]})

    out = adae.adam.duration("ADURN", start="ASTDT", end="AENDT").to_frame()

    assert out["ADURN"].to_list() == [-1]


def test_duration_in_hours_is_the_raw_difference_by_default() -> None:
    adpc = pl.DataFrame(
        {
            "DOSE": [dt.datetime(2024, 1, 10, 8, 0)] * 2,
            "SAMPLE": [dt.datetime(2024, 1, 10, 10, 0), dt.datetime(2024, 1, 10, 7, 30)],
        }
    )

    out = adpc.adam.duration("AFRLT", start="DOSE", end="SAMPLE", unit="hours").to_frame()

    assert out["AFRLT"].to_list() == [2.0, -0.5]


# ── Baseline flag (c1-3, Q1 B) ────────────────────────────────────────────────


def _vs(rows: list[tuple[str, str]], rfstdtc: str) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "USUBJID": ["S7"] * len(rows),
            "VSTESTCD": [t for t, _ in rows],
            "VSDTC": [d for _, d in rows],
            "VSORRES": ["120"] * len(rows),
            "RFSTDTC": [rfstdtc] * len(rows),
        }
    )


def test_baseline_on_the_reference_date_with_no_time_is_not_eligible() -> None:
    vs = _vs([("SYSBP", "2014-01-05"), ("SYSBP", "2014-01-10")], "2014-01-10T08:30")

    out = vs.sdtm.baseline_flag("VSBLFL", date_col="VSDTC", testcd_col="VSTESTCD").to_frame()

    assert out["VSBLFL"].to_list() == ["Y", None]


def test_baseline_on_the_reference_date_before_the_dose_time_is_eligible() -> None:
    vs = _vs(
        [("SYSBP", "2014-01-05"), ("SYSBP", "2014-01-10T07:00"), ("SYSBP", "2014-01-10T09:00")],
        "2014-01-10T08:30",
    )

    out = vs.sdtm.baseline_flag("VSBLFL", date_col="VSDTC", testcd_col="VSTESTCD").to_frame()

    assert out["VSBLFL"].to_list() == [None, "Y", None]


def test_baseline_keeps_one_record_when_the_last_date_has_two_times() -> None:
    vs = _vs([("SYSBP", "2014-01-09T08:00"), ("SYSBP", "2014-01-09T09:00")], "2014-01-10")

    out = vs.sdtm.baseline_flag("VSBLFL", date_col="VSDTC", testcd_col="VSTESTCD").to_frame()

    assert out["VSBLFL"].to_list() == [None, "Y"]


# ── EPOCH (c1-219, Q2 E) ──────────────────────────────────────────────────────

SE = pl.from_repr("""
┌─────────────┬──────────────────┬──────────────────┬───────────┐
│ USUBJID     ┆ SESTDTC          ┆ SEENDTC          ┆ EPOCH     │
│ ---         ┆ ---              ┆ ---              ┆ ---       │
│ str         ┆ str              ┆ str              ┆ str       │
╞═════════════╪══════════════════╪══════════════════╪═══════════╡
│ 01-701-1015 ┆ 2014-01-01       ┆ 2014-01-15T08:30 ┆ SCREENING │
│ 01-701-1015 ┆ 2014-01-15T08:30 ┆ 2014-04-15T10:00 ┆ TREATMENT │
│ 01-701-1015 ┆ 2014-04-15T10:00 ┆ 2014-05-15       ┆ FOLLOW-UP │
└─────────────┴──────────────────┴──────────────────┴───────────┘
""")


def _epochs(date_col: str, values: list[str], **kwargs) -> list[str | None]:
    df = pl.DataFrame({"USUBJID": ["01-701-1015"] * len(values), date_col: values})
    return (
        df.sdtm.epoch_assign("EPOCH", date_col=date_col, se=SE, **kwargs)
        .to_frame()["EPOCH"]
        .to_list()
    )


def test_epoch_reads_timed_and_date_only_values() -> None:
    got = _epochs("AESTDTC", ["2014-02-01", "2014-02-01T10:30", "2014-06-01"])

    assert got == ["TREATMENT", "TREATMENT", None]


def test_epoch_on_the_transition_date_follows_the_time_when_both_have_one() -> None:
    got = _epochs("LBDTC", ["2014-01-15T07:00", "2014-01-15T08:30", "2014-01-15T12:00"])

    assert got == ["SCREENING", "TREATMENT", "TREATMENT"]


def test_epoch_on_the_transition_date_with_no_time_follows_the_record_kind() -> None:
    with pytest.warns(UserWarning, match=r"1 row.*earlier element.*LBDTC"):
        findings = _epochs("LBDTC", ["2014-01-15"])
    with pytest.warns(UserWarning, match=r"1 row.*later element.*AESTDTC"):
        events = _epochs("AESTDTC", ["2014-01-15"])

    assert findings == ["SCREENING"]
    assert events == ["TREATMENT"]


def test_epoch_same_day_overrides_the_record_kind() -> None:
    with pytest.warns(UserWarning, match="earlier element"):
        got = _epochs("AESTDTC", ["2014-01-15"], same_day="earlier")

    assert got == ["SCREENING"]


def test_epoch_by_class_needs_a_dtc_name() -> None:
    with pytest.raises(DerivationError, match="same_day"):
        _epochs("VISITDATE", ["2014-01-15"])


def test_epoch_blank_end_is_open_and_partial_end_is_not() -> None:
    se = pl.DataFrame(
        {
            "USUBJID": ["S1", "S2"],
            "SESTDTC": ["2014-01-01", "2014-01-01"],
            "SEENDTC": ["", "2014-04"],
            "EPOCH": ["TREATMENT", "TREATMENT"],
        }
    )
    ae = pl.DataFrame({"USUBJID": ["S1", "S2"], "AESTDTC": ["2014-09-01", "2014-09-01"]})

    with pytest.warns(UserWarning, match="SEENDTC"):
        out = ae.sdtm.epoch_assign("EPOCH", date_col="AESTDTC", se=se).to_frame()

    assert out["EPOCH"].to_list() == ["TREATMENT", None]


# ── .sdtm.date() (c1-89, c1-90, c1-94) ────────────────────────────────────────


def _dtc(values: list[str | None], **kwargs) -> pl.DataFrame:
    raw = pl.DataFrame({"raw": values}, schema={"raw": pl.String})
    return raw.sdtm.date("AESTDTC", source="raw", **kwargs).to_frame()


def test_date_refuses_to_guess_the_order_of_a_slash_date() -> None:
    with pytest.raises(DerivationError, match=r"format='%m/%d/%Y'.*03/04/2021"):
        _dtc(["03/04/2021", "03/15/2021"])


def test_date_refuses_to_guess_the_century_of_a_two_digit_year() -> None:
    with pytest.raises(DerivationError, match="%y"):
        _dtc(["15-MAR-21"])


def test_date_reads_a_named_layout() -> None:
    assert _dtc(["03/04/2021"], format="%m/%d/%Y")["AESTDTC"].to_list() == ["2021-03-04"]
    assert _dtc(["15-MAR-21"], format="%d-%b-%y")["AESTDTC"].to_list() == ["2021-03-15"]


def test_date_keeps_every_valid_iso_form_and_converts_unambiguous_layouts() -> None:
    values = [
        "2021-03",
        "2021",
        "2021---15",
        "2021-03-15T10:30",
        "2021-03-15T10:30:00+01:00",
        "2021-03-15 10:30",
        "20210315",
        "15-MAR-2021",
        "15MAR2021",
        "",
        None,
    ]

    assert _dtc(values)["AESTDTC"].to_list() == [
        "2021-03",
        "2021",
        "2021---15",
        "2021-03-15T10:30",
        "2021-03-15T10:30:00+01:00",
        "2021-03-15T10:30",
        "2021-03-15",
        "2021-03-15",
        "2021-03-15",
        None,
        None,
    ]


def test_date_writes_null_for_a_value_it_cannot_convert_and_warns_once() -> None:
    with pytest.warns(UserWarning, match=r"AESTDTC.*4 value.*UNK"):
        out = _dtc(["2021-03-15", "UNK", "2021-02-30", "2021-13-01", "foo"])

    assert out["AESTDTC"].to_list() == ["2021-03-15", None, None, None, None]


@pytest.mark.parametrize(
    ("date", "time", "expected"),
    [
        ("2021-03-15", None, "2021-03-15"),
        ("2021-03-15", "", "2021-03-15"),
        ("2021-03-15", "8:30", "2021-03-15T08:30"),
        ("2021-03-15", "08:30:15.123", "2021-03-15T08:30:15.123"),
        ("2021-03", "08:30", "2021-03--T08:30"),
        ("2021", "08:30", "2021----T08:30"),
        ("2021---15", "08:30", "2021---15T08:30"),
        (None, "08:30", "-----T08:30"),
        ("2021-03", None, "2021-03"),
    ],
)
def test_date_with_time_follows_sdtmig_4_4_2(
    date: str | None, time: str | None, expected: str
) -> None:
    raw = pl.DataFrame({"d": [date], "t": [time]}, schema={"d": pl.String, "t": pl.String})

    out = raw.sdtm.date("EXSTDTC", source="d", time="t").to_frame()

    assert out["EXSTDTC"].to_list() == [expected]


def test_date_with_a_time_it_cannot_read_keeps_the_date_and_warns() -> None:
    raw = pl.DataFrame({"d": ["2021-03-15", "2021-03-16"], "t": ["0830", "UNK"]})

    with pytest.warns(UserWarning, match=r"EXSTDTC.*2 time.*0830"):
        out = raw.sdtm.date("EXSTDTC", source="d", time="t").to_frame()

    assert out["EXSTDTC"].to_list() == ["2021-03-15", "2021-03-16"]


# ── .adam.date() to a date-time (c1-65) and bounds (c1-66) ────────────────────


def test_adam_datetime_keeps_the_collected_hour_and_minute() -> None:
    ae = pl.DataFrame({"AESTDTC": ["2021-03-15T10:30", "2021-03-15T10", "2021-03-15"]})

    first = ae.adam.date("ASTDTM", source="AESTDTC").to_frame()
    last = ae.adam.date("ASTDTM", source="AESTDTC", impute="last").to_frame()
    mid = ae.adam.date("ASTDTM", source="AESTDTC", impute="mid").to_frame()

    assert first["ASTDTM"].to_list() == [
        dt.datetime(2021, 3, 15, 10, 30),
        dt.datetime(2021, 3, 15, 10, 0),
        dt.datetime(2021, 3, 15, 0, 0),
    ]
    assert first["ASTTMF"].to_list() == ["S", "M", "H"]
    assert last["ASTDTM"].to_list() == [
        dt.datetime(2021, 3, 15, 10, 30, 59),
        dt.datetime(2021, 3, 15, 10, 59, 59),
        dt.datetime(2021, 3, 15, 23, 59, 59),
    ]
    assert mid["ASTDTM"].to_list() == [
        dt.datetime(2021, 3, 15, 10, 30),
        dt.datetime(2021, 3, 15, 10, 0),
        dt.datetime(2021, 3, 15, 12, 0),
    ]


def test_adam_datetime_keeps_a_fraction_and_drops_an_offset_with_a_warning() -> None:
    ae = pl.DataFrame({"AESTDTC": ["2021-03-15T10:30:45.123", "2021-03-15T10:30:45+02:00"]})

    with pytest.warns(UserWarning, match=r"1 value.*offset"):
        out = ae.adam.date("ASTDTM", source="AESTDTC").to_frame()

    assert out["ASTDTM"].to_list() == [
        dt.datetime(2021, 3, 15, 10, 30, 45, 123000),
        dt.datetime(2021, 3, 15, 10, 30, 45),
    ]
    assert out["ASTTMF"].to_list() == [None, None]


def test_min_date_moves_only_a_partial_date_whose_range_holds_the_bound() -> None:
    """admiral derive_vars_dt: the non-missing parts of the date never change."""
    adae = pl.DataFrame(
        {
            "AESTDTC": ["2021-03", "2021-02", "2021-02-20", "2021-04", "2021", "2020"],
            "TRTSDT": [dt.date(2021, 3, 15)] * 6,
        }
    )

    out = adae.adam.date("ASTDT", source="AESTDTC", min_date="TRTSDT").to_frame()

    assert out["ASTDT"].to_list() == [
        dt.date(2021, 3, 15),
        dt.date(2021, 2, 1),
        dt.date(2021, 2, 20),
        dt.date(2021, 4, 1),
        dt.date(2021, 3, 15),
        dt.date(2020, 1, 1),
    ]
    assert out["ASTDTF"].to_list() == ["D", "D", None, "D", "M", "M"]


def test_max_date_moves_only_a_partial_date_whose_range_holds_the_bound() -> None:
    adae = pl.DataFrame({"AEENDTC": ["2021-04", "2021-04-10", "2021-03"]})

    out = adae.adam.date("AENDT", source="AEENDTC", impute="last", max_date="2021-03-25").to_frame()

    assert out["AENDT"].to_list() == [
        dt.date(2021, 4, 30),
        dt.date(2021, 4, 10),
        dt.date(2021, 3, 25),
    ]


def test_bounds_on_a_datetime_target_are_refused() -> None:
    ae = pl.DataFrame({"AESTDTC": ["2021-03"], "TRTSDT": [dt.date(2021, 3, 15)]})

    with pytest.raises(DerivationError, match="min_date"):
        ae.adam.date("ASTDTM", source="AESTDTC", min_date="TRTSDT").to_frame()


# ── First and last dates (c1-118) ─────────────────────────────────────────────

EX = pl.from_repr("""
┌─────────┬──────────────────┬──────────────────┐
│ USUBJID ┆ EXSTDTC          ┆ EXENDTC          │
│ ---     ┆ ---              ┆ ---              │
│ str     ┆ str              ┆ str              │
╞═════════╪══════════════════╪══════════════════╡
│ S1      ┆ 2021-03-15       ┆ 2021-03-25       │
│ S2      ┆ 2021-03          ┆ 2021-04          │
│ S2      ┆ 2021-03-15       ┆ 2021-03-14       │
│ S3      ┆ 2021-03-15T08:30 ┆ 2021-03-15T09:30 │
│ S4      ┆ null             ┆ 2021-03-16       │
│ S4      ┆ 2021-03-15       ┆ null             │
│ S5      ┆ 2021-03          ┆ null             │
└─────────┴──────────────────┴──────────────────┘
""")
DM = pl.DataFrame({"USUBJID": ["S1", "S2", "S3", "S4", "S5"]})


def test_first_and_last_date_are_dates_and_leave_partial_values_out() -> None:
    with pytest.warns(UserWarning, match=r"EXSTDTC.*2 partial"):
        out = (
            DM.adam.adsl.first_date("TRTSDT", from_dataset=EX, date_col="EXSTDTC")
            .last_date("TRTEDT", from_dataset=EX, date_col="EXENDTC")
            .to_frame()
        )

    assert out.schema["TRTSDT"] == pl.Date
    assert out["TRTSDT"].to_list() == [dt.date(2021, 3, 15)] * 4 + [None]
    assert out["TRTEDT"].to_list() == [
        dt.date(2021, 3, 25),
        dt.date(2021, 3, 14),
        dt.date(2021, 3, 15),
        dt.date(2021, 3, 16),
        None,
    ]


def test_first_date_with_impute_writes_the_flag_and_warns() -> None:
    with pytest.warns(UserWarning, match=r"imputed.*2"):
        out = DM.adam.adsl.first_date(
            "TRTSDT", from_dataset=EX, date_col="EXSTDTC", impute="first"
        ).to_frame()

    assert out["TRTSDT"].to_list() == [dt.date(2021, 3, 15), dt.date(2021, 3, 1)] + [
        dt.date(2021, 3, 15)
    ] * 2 + [dt.date(2021, 3, 1)]
    assert out["TRTSDTF"].to_list() == [None, "D", None, None, "D"]


def test_first_date_to_a_datetime_keeps_the_time() -> None:
    out = DM.adam.adsl.first_date("TRTSDTM", from_dataset=EX, date_col="EXSTDTC").to_frame()

    assert out["TRTSDTM"][2] == dt.datetime(2021, 3, 15, 8, 30)


# ── select(spec=) never casts --DTC (c1-1, c1-2) ──────────────────────────────

_DEFINE = """\
datasets:
  - name: AE
    variables:
      - {name: USUBJID, type: text}
      - {name: AESTDTC, type: datetime}
  - name: ADAE
    variables:
      - {name: USUBJID, type: text}
      - {name: AESTDTC, type: datetime}
      - {name: ASTDT, type: date}
      - {name: ASTDTM, type: datetime}
"""


def test_select_keeps_sdtm_dtc_text(tmp_path: Path) -> None:
    spec = tmp_path / "define.yaml"
    spec.write_text(_DEFINE, encoding="utf-8")
    ae = pl.DataFrame({"USUBJID": ["S1", "S2"], "AESTDTC": ["2021-03", "2021-03-15T10:30"]})

    out = ae.sdtm.select(spec=spec, dataset="AE").to_frame()

    assert out["AESTDTC"].to_list() == ["2021-03", "2021-03-15T10:30"]


def test_select_reads_adam_dates_from_text_without_inventing_a_time(tmp_path: Path) -> None:
    spec = tmp_path / "define.yaml"
    spec.write_text(_DEFINE, encoding="utf-8")
    adae = pl.DataFrame(
        {
            "USUBJID": ["S1", "S2"],
            "AESTDTC": ["2024-01-15T08:30", "2024-02"],
            "ASTDT": ["2024-01-15T08:30", "2024-02"],
            "ASTDTM": ["2024-01-15T10:00", "2024-01-15"],
        }
    )

    with pytest.warns(UserWarning, match=r"ASTDT.*2024-02"):
        out = adae.adam.select(spec=spec, dataset="ADAE").to_frame()

    assert out["AESTDTC"].to_list() == ["2024-01-15T08:30", "2024-02"]
    assert out["ASTDT"].to_list() == [dt.date(2024, 1, 15), None]
    assert out["ASTDTM"].to_list() == [dt.datetime(2024, 1, 15, 10, 0), None]
