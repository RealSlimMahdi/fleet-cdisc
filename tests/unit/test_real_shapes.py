"""Real SDTM shapes through the date and flag verbs (alpha audit 5.3, gate 1).

Clean test data has no time part, no partial date, no SAS blank and no tie,
so the alpha audit found defects that every other test passed.  Each test
here feeds one of those shapes and states the expected value of the rule
(SDTMIG 3.4 section 4.4.4, admiral, SAS ``LAST.``), written before the run.
"""

from __future__ import annotations

import polars as pl
import pytest

import fleet

_DTC = pl.from_repr("""
    ┌─────────┬──────────────────┐
    │ USUBJID ┆ raw              │
    │ ---     ┆ ---              │
    │ str     ┆ str              │
    ╞═════════╪══════════════════╡
    │ S01     ┆ 2021-03-20 10:30 │
    │ S02     ┆ 2021-03          │
    │ S03     ┆ 2021             │
    │ S04     ┆                  │
    │ S05     ┆ null             │
    └─────────┴──────────────────┘
    """)


def test_sdtm_date_keeps_the_time_and_the_partial_and_blanks_are_missing() -> None:
    out = fleet.frame(_DTC).sdtm.date("AESTDTC", source="raw").to_frame()

    assert out["AESTDTC"].to_list() == ["2021-03-20T10:30", "2021-03", "2021", None, None]


def test_adam_date_takes_the_date_of_a_timed_value_and_flags_imputation() -> None:
    dtc = _DTC.with_columns(
        pl.Series("AESTDTC", ["2021-03-20T10:30", "2021-03", "2021", None, None])
    )

    out = fleet.frame(dtc).adam.date("ASTDT", source="AESTDTC").to_frame()

    assert out["ASTDT"].cast(pl.String).to_list() == [
        "2021-03-20",
        "2021-03-01",
        "2021-01-01",
        None,
        None,
    ]
    assert out["ASTDTF"].to_list() == [None, "D", "M", None, None]


_DAYS = pl.from_repr("""
    ┌─────────┬──────────────────┬──────────────────┐
    │ USUBJID ┆ AESTDTC          ┆ RFSTDTC          │
    │ ---     ┆ ---              ┆ ---              │
    │ str     ┆ str              ┆ str              │
    ╞═════════╪══════════════════╪══════════════════╡
    │ S01     ┆ 2021-03-20T10:30 ┆ 2021-03-15T08:00 │
    │ S02     ┆ 2021-03-15T07:00 ┆ 2021-03-15T08:00 │
    │ S03     ┆ 2021-03-14       ┆ 2021-03-15T08:00 │
    │ S04     ┆ 2021-03          ┆ 2021-03-15T08:00 │
    └─────────┴──────────────────┴──────────────────┘
    """)


def test_study_day_uses_the_date_part_and_has_no_day_zero() -> None:
    out = fleet.frame(_DAYS).sdtm.study_day("AESTDY", date_col="AESTDTC", ref_col="RFSTDTC")

    # Day 1 is the reference date, whatever the time; the day before is -1.
    # A partial date has no study day.
    assert out.to_frame()["AESTDY"].to_list() == [6, 1, -1, None]


def test_duration_in_days_counts_both_ends_and_keeps_a_negative_span() -> None:
    spans = pl.from_repr("""
        ┌─────────┬──────────────────┬──────────────────┐
        │ USUBJID ┆ START            ┆ END              │
        │ ---     ┆ ---              ┆ ---              │
        │ str     ┆ str              ┆ str              │
        ╞═════════╪══════════════════╪══════════════════╡
        │ S01     ┆ 2021-03-15T08:00 ┆ 2021-03-20T10:30 │
        │ S02     ┆ 2021-03-20       ┆ 2021-03-19       │
        │ S03     ┆ 2021-03-20       ┆ null             │
        └─────────┴──────────────────┴──────────────────┘
        """)

    out = fleet.frame(spans).adam.duration("ADURN", start="START", end="END").to_frame()

    # admiral compute_duration: +1 day for a forward span, nothing for a negative one.
    assert out["ADURN"].to_list() == [6, -1, None]


def test_first_date_leaves_a_partial_value_out_and_says_so() -> None:
    dm = pl.from_repr("""
        ┌─────────────┐
        │ USUBJID     │
        │ ---         │
        │ str         │
        ╞═════════════╡
        │ 01-701-1015 │
        │ 01-701-1023 │
        └─────────────┘
        """)
    ex = pl.from_repr("""
        ┌─────────────┬────────────┐
        │ USUBJID     ┆ EXSTDTC    │
        │ ---         ┆ ---        │
        │ str         ┆ str        │
        ╞═════════════╪════════════╡
        │ 01-701-1015 ┆ 2014-01    │
        │ 01-701-1015 ┆ 2014-01-15 │
        │ 01-701-1023 ┆ 2014-01    │
        └─────────────┴────────────┘
        """)

    with pytest.warns(UserWarning, match="partial"):
        out = (
            fleet.frame(dm)
            .adam.adsl.first_date("TRTSDT", from_dataset=ex, date_col="EXSTDTC")
            .to_frame()
        )

    assert out["TRTSDT"].cast(pl.String).to_list() == ["2014-01-15", None]


def test_treatment_emergent_reads_the_date_of_a_timed_start() -> None:
    ae = pl.from_repr("""
        ┌─────────┬──────────────────┬────────────┬────────────┐
        │ USUBJID ┆ AESTDTC          ┆ AEENDTC    ┆ TRTSDT     │
        │ ---     ┆ ---              ┆ ---        ┆ ---        │
        │ str     ┆ str              ┆ str        ┆ date       │
        ╞═════════╪══════════════════╪════════════╪════════════╡
        │ S01     ┆ 2021-03-15T07:00 ┆ 2021-03-16 ┆ 2021-03-15 │
        │ S02     ┆ 2021-03-14T23:59 ┆ 2021-03-16 ┆ 2021-03-15 │
        │ S03     ┆ null             ┆ null       ┆ 2021-03-15 │
        │ S04     ┆ null             ┆ 2021-03-01 ┆ 2021-03-15 │
        └─────────┴──────────────────┴────────────┴────────────┘
        """)

    out = (
        fleet.frame(ae)
        .adam.occds("ADAE")
        .treatment_emergent("TRTEMFL", start_date="AESTDTC", end_date="AEENDTC", trtsdt="TRTSDT")
        .to_frame()
    )

    # admiral derive_var_trtemfl: a missing start is flagged unless the event
    # ended before the first dose.
    assert out["TRTEMFL"].to_list() == ["Y", None, "Y", None]


def test_flag_last_takes_one_record_on_a_tie_as_sas_last() -> None:
    adae = pl.from_repr("""
        ┌─────────┬───────┬──────────┬────────┐
        │ USUBJID ┆ AESEQ ┆ AETERM   ┆ AESEVN │
        │ ---     ┆ ---   ┆ ---      ┆ ---    │
        │ str     ┆ i64   ┆ str      ┆ i64    │
        ╞═════════╪═══════╪══════════╪════════╡
        │ S01     ┆ 1     ┆ HEADACHE ┆ 3      │
        │ S01     ┆ 2     ┆ HEADACHE ┆ 3      │
        │ S01     ┆ 3     ┆ HEADACHE ┆ 1      │
        │ S02     ┆ 1     ┆ RASH     ┆ 2      │
        └─────────┴───────┴──────────┴────────┘
        """)

    out = (
        fleet.frame(adae)
        .adam.flag("ANL01FL", criteria="last", order_by=["AESEVN"], by=["USUBJID", "AETERM"])
        .to_frame()
    )

    # PROC SORT BY USUBJID AETERM AESEVN; IF LAST.AETERM: the second tied record.
    assert out["ANL01FL"].to_list() == [None, "Y", None, "Y"]


def test_a_missing_key_matches_a_missing_key_as_sas_merge() -> None:
    advs = pl.from_repr("""
        ┌─────────┬─────────┬──────┬───────┐
        │ USUBJID ┆ PARAMCD ┆ ATPT ┆ AVAL  │
        │ ---     ┆ ---     ┆ ---  ┆ ---   │
        │ str     ┆ str     ┆ str  ┆ f64   │
        ╞═════════╪═════════╪══════╪═══════╡
        │ S01     ┆ SYSBP   ┆ null ┆ 120.0 │
        │ S01     ┆ SYSBP   ┆ 1H   ┆ 118.0 │
        └─────────┴─────────┴──────┴───────┘
        """)
    base = pl.from_repr("""
        ┌─────────┬─────────┬──────┬───────┐
        │ USUBJID ┆ PARAMCD ┆ ATPT ┆ BASE  │
        │ ---     ┆ ---     ┆ ---  ┆ ---   │
        │ str     ┆ str     ┆ str  ┆ f64   │
        ╞═════════╪═════════╪══════╪═══════╡
        │ S01     ┆ SYSBP   ┆ null ┆ 121.0 │
        │ S01     ┆ SYSBP   ┆ 1H   ┆ 119.0 │
        └─────────┴─────────┴──────┴───────┘
        """)

    out = fleet.frame(advs).adam.merge(base, on=["USUBJID", "PARAMCD", "ATPT"]).to_frame()

    # MERGE BY USUBJID PARAMCD ATPT: a missing ATPT matches a missing ATPT.
    assert out["BASE"].to_list() == [121.0, 119.0]


# ── Pilot TV and SE shapes: a decimal VISITNUM and an unplanned element (c2-974) ──


@pytest.mark.xfail(
    strict=True,
    reason="c2-974: TrialVisit types VISITNUM as an integer and refuses 3.5; TV cluster open",
)
def test_pilot_tv_rows_load_with_a_decimal_visitnum():
    from fleet.sdtm.tdd import TrialVisit, TrialVisits

    # CDISCPILOT01 TV: an unscheduled visit between visits 3 and 4 is 3.5.
    rows = [(1.0, "SCREENING 1"), (3.5, "UNSCHEDULED 3.1"), (13.0, "WEEK 26")]
    rows += [(101.0, "RETRIEVAL"), (201.0, "AMBUL ECG REMOVAL"), (501.0, "RETRIEVAL")]

    tv = TrialVisits(visits=[TrialVisit(visitnum=n, visit=v) for n, v in rows]).to_polars()

    assert tv["VISITNUM"].to_list() == [n for n, _ in rows]


def test_a_date_in_an_unplanned_element_gets_no_epoch():
    # SDTMIG 3.4 SE: an unplanned element (ETCD UNPLAN) has a null EPOCH.
    se = pl.from_repr("""
        ┌─────────┬────────┬────────────┬────────────┬───────────┐
        │ USUBJID ┆ ETCD   ┆ SESTDTC    ┆ SEENDTC    ┆ EPOCH     │
        │ ---     ┆ ---    ┆ ---        ┆ ---        ┆ ---       │
        │ str     ┆ str    ┆ str        ┆ str        ┆ str       │
        ╞═════════╪════════╪════════════╪════════════╪═══════════╡
        │ 001     ┆ SCRN   ┆ 2014-01-01 ┆ 2014-01-14 ┆ SCREENING │
        │ 001     ┆ PBO    ┆ 2014-01-14 ┆ 2014-03-01 ┆ TREATMENT │
        │ 001     ┆ UNPLAN ┆ 2014-03-01 ┆ 2014-03-10 ┆ null      │
        │ 001     ┆ FU     ┆ 2014-03-10 ┆ 2014-04-10 ┆ FOLLOW-UP │
        └─────────┴────────┴────────────┴────────────┴───────────┘
        """)
    ae = pl.DataFrame(
        {"USUBJID": ["001"] * 3, "AESTDTC": ["2014-02-01", "2014-03-05", "2014-03-20"]}
    )

    result = ae.sdtm.epoch_assign("EPOCH", date_col="AESTDTC", se=se).to_frame()

    assert result["EPOCH"].to_list() == ["TREATMENT", None, "FOLLOW-UP"]
