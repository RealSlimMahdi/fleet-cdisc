"""Unit tests for the ADTTE namespace (df.adam.tte).

Covers the scenarios of admiral's ``test-derive_param_tte.R`` with hand-written
rows that follow the same rules; each test docstring names the admiral test.
TestByStrata.test_adsl_censor_applies_to_every_stratum holds the literal rows of
admiral Test 5. Plus the
Fleet additions: retain='censor_at_start', AVALU stamping, the explain
trace, and km_data(). Sources are plain frames with USUBJID and ADT.
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration
from fleet.core.exceptions import DerivationError
from tests.helpers import shuffle_rows

# ------------------------------------------------------------------ #
# Fixtures                                                             #
# ------------------------------------------------------------------ #


@pytest.fixture
def adsl() -> pl.DataFrame:
    return pl.from_repr("""
┌─────────┬────────────┬───────┬────────────┬────────────┬────────────┐
│ USUBJID ┆ TRTSDT     ┆ DTHFL ┆ DTHDT      ┆ LSTALVDT   ┆ EOSDT      │
│ ---     ┆ ---        ┆ ---   ┆ ---        ┆ ---        ┆ ---        │
│ str     ┆ date       ┆ str   ┆ date       ┆ date       ┆ date       │
╞═════════╪════════════╪═══════╪════════════╪════════════╪════════════╡
│ 01      ┆ 2023-01-01 ┆ Y     ┆ 2023-03-01 ┆ 2023-03-01 ┆ 2023-03-01 │
│ 02      ┆ 2023-01-02 ┆ null  ┆ null       ┆ 2023-06-30 ┆ 2023-06-30 │
│ 03      ┆ 2023-01-03 ┆ null  ┆ null       ┆ null       ┆ 2023-02-01 │
└─────────┴────────────┴───────┴────────────┴────────────┴────────────┘
""")


@pytest.fixture
def adae() -> pl.DataFrame:
    return pl.from_repr("""
┌─────────┬─────────┬────────────┬───────┬─────────┐
│ USUBJID ┆ TRTEMFL ┆ ASTDT      ┆ AESEQ ┆ AEDECOD │
│ ---     ┆ ---     ┆ ---        ┆ ---   ┆ ---     │
│ str     ┆ str     ┆ date       ┆ i64   ┆ str     │
╞═════════╪═════════╪════════════╪═══════╪═════════╡
│ 01      ┆ Y       ┆ 2023-01-20 ┆ 2     ┆ NAUSEA  │
│ 01      ┆ Y       ┆ 2023-01-10 ┆ 1     ┆ FATIGUE │
│ 02      ┆ Y       ┆ 2023-02-05 ┆ 1     ┆ NAUSEA  │
└─────────┴─────────┴────────────┴───────┴─────────┘
""")


def _death(adsl: pl.DataFrame) -> pl.DataFrame:
    return adsl.filter(pl.col("DTHFL") == "Y").select(
        "USUBJID", ADT="DTHDT", SRCDOM=pl.lit("ADSL"), SRCVAR=pl.lit("DTHDT")
    )


def _alive(adsl: pl.DataFrame) -> pl.DataFrame:
    return adsl.select("USUBJID", ADT="LSTALVDT", EVNTDESC=pl.lit("ALIVE"))


def _ae(adae: pl.DataFrame) -> pl.DataFrame:
    return adae.filter(pl.col("TRTEMFL") == "Y").select(
        "USUBJID", "AEDECOD", ADT="ASTDT", SRCDOM=pl.lit("ADAE"), SRCSEQ="AESEQ"
    )


def _os(ns, adsl, **kwargs):
    """OS param with the death event and the last-alive censor."""
    defaults = dict(start="TRTSDT", events={"DEATH": _death(adsl)}, censors={1: _alive(adsl)})
    defaults.update(kwargs)
    return ns.param("OS", "Overall Survival", **defaults)


# ------------------------------------------------------------------ #
# admiral test catalog — core selection                                #
# ------------------------------------------------------------------ #


class TestSelection:
    def test_single_event_single_censor(self, adsl):
        """admiral #1: death event wins (CNSR 0), else last-alive censor (CNSR 1)."""
        with pytest.warns(UserWarning, match="dropped"):
            result = _os(adsl.adam.tte, adsl).to_frame().sort("USUBJID")
        s1, s2 = result.row(0, named=True), result.row(1, named=True)
        assert s1["CNSR"] == 0 and s1["EVNTDESC"] == "DEATH"
        assert s1["ADT"] == date(2023, 3, 1) and s1["STARTDT"] == date(2023, 1, 1)
        assert s1["SRCDOM"] == "ADSL" and s1["SRCVAR"] == "DTHDT"
        assert s2["CNSR"] == 1 and s2["EVNTDESC"] == "ALIVE"
        # Subject 03 has no event and no censor date: dropped.
        assert result.height == 2

    def test_no_event_no_censor_drops_with_warning(self, adsl):
        """admiral #1/#3 corollary: the drop is never silent and names the subject."""
        with pytest.warns(UserWarning, match=r"1 subject\(s\) .* dropped: \['03'\]"):
            result = _os(adsl.adam.tte.pin("ADSL", adsl), adsl).to_frame()
        assert "03" not in result["USUBJID"].to_list()

    def test_retain_censor_at_start(self, adsl):
        """Fleet: retain='censor_at_start' keeps the subject, censored at STARTDT."""
        result = _os(adsl.adam.tte, adsl, retain="censor_at_start").to_frame()
        s3 = result.filter(pl.col("USUBJID") == "03").row(0, named=True)
        assert s3["CNSR"] == 1
        assert s3["ADT"] == s3["STARTDT"] == date(2023, 1, 3)
        assert s3["EVNTDESC"] == "NO EVENT OBSERVED"

    def test_subjects_outside_adsl_give_no_rows(self, adsl, adae):
        """admiral #3: only subjects of the ADSL universe get rows."""
        universe = adsl.filter(pl.col("USUBJID") != "02")
        result = universe.adam.tte.param(
            "TTAE",
            "Time to First AE",
            start="TRTSDT",
            events={"ADVERSE EVENT": _ae(adae), "DEATH": _death(adsl)},
            censors={1: adsl.select("USUBJID", ADT="EOSDT")},
        ).to_frame()
        assert set(result["USUBJID"].to_list()) == {"01", "03"}

    def test_earliest_event_pooled_across_sources(self, adsl, adae):
        """admiral #3: the earliest date across ALL event frames wins."""
        result = adsl.adam.tte.param(
            "X",
            "First of AE or Death",
            start="TRTSDT",
            events={"DEATH": _death(adsl), "ADVERSE EVENT": _ae(adae)},
            censors={1: adsl.select("USUBJID", ADT="EOSDT")},
        ).to_frame()
        s1 = result.filter(pl.col("USUBJID") == "01").row(0, named=True)
        assert s1["ADT"] == date(2023, 1, 10)
        assert s1["EVNTDESC"] == "ADVERSE EVENT"

    def test_srcseq_resolves_same_date_ties(self, adsl):
        """admiral #15: SRCSEQ picks the lowest sequence on a shared date."""
        adae = pl.from_repr("""
┌─────────┬────────────┬───────┐
│ USUBJID ┆ ASTDT      ┆ AESEQ │
│ ---     ┆ ---        ┆ ---   │
│ str     ┆ date       ┆ i64   │
╞═════════╪════════════╪═══════╡
│ 01      ┆ 2023-01-10 ┆ 2     │
│ 01      ┆ 2023-01-10 ┆ 1     │
└─────────┴────────────┴───────┘
""")
        result = adsl.adam.tte.param(
            "TTAE",
            "Time to First AE",
            start="TRTSDT",
            events={"AE": adae.select("USUBJID", ADT="ASTDT", SRCSEQ="AESEQ")},
            censors={1: adsl.select("USUBJID", ADT="EOSDT")},
        ).to_frame()
        assert result.filter(pl.col("USUBJID") == "01")["SRCSEQ"][0] == 1

    def test_input_sort_independence(self, adsl, adae):
        """admiral #16: ascending vs shuffled input rows give the same output."""

        def chain(ae: pl.DataFrame) -> pl.DataFrame:
            return (
                adsl.adam.tte.param(
                    "TTAE",
                    "Time to First AE",
                    start="TRTSDT",
                    events={"AE": _ae(ae)},
                    censors={1: adsl.select("USUBJID", ADT="EOSDT")},
                )
                .to_frame()
                .sort("USUBJID")
            )

        assert chain(adae).equals(chain(shuffle_rows(adae)))

    def test_same_date_dup_without_srcseq_warns_but_deterministic(self, adsl):
        """admiral #14 (check_type='warning'): warn AND stay deterministic."""
        adae = pl.from_repr("""
┌─────────┬────────────┬─────────┐
│ USUBJID ┆ ASTDT      ┆ AEDECOD │
│ ---     ┆ ---        ┆ ---     │
│ str     ┆ date       ┆ str     │
╞═════════╪════════════╪═════════╡
│ 01      ┆ 2023-01-10 ┆ B       │
│ 01      ┆ 2023-01-10 ┆ A       │
└─────────┴────────────┴─────────┘
""")

        def run(ae: pl.DataFrame) -> pl.DataFrame:
            return adsl.adam.tte.param(
                "TTAE",
                "Time to First AE",
                start="TRTSDT",
                events={"AE": ae.select("USUBJID", "AEDECOD", ADT="ASTDT")},
                censors={1: adsl.select("USUBJID", ADT="EOSDT")},
            ).to_frame()

        with pytest.warns(UserWarning, match="no SRCSEQ"):
            first = run(adae)
        with pytest.warns(UserWarning, match="no SRCSEQ"):
            second = run(shuffle_rows(adae))
        assert first.sort("USUBJID").equals(second.sort("USUBJID"))

    def test_date_floored_to_startdt(self, adsl):
        """admiral: ADT = max(ADT, STARTDT)."""
        universe = adsl.with_columns(pl.lit(date(2023, 4, 1)).alias("TRTSDT"))
        result = universe.adam.tte.param(
            "X",
            "Time to Death",
            start="TRTSDT",
            events={"DEATH": _death(adsl)},
            censors={1: adsl.select("USUBJID", ADT="EOSDT")},
        ).to_frame()
        assert (result["ADT"] >= result["STARTDT"]).all()

    def test_null_start_date_keeps_adt(self, adsl):
        """admiral #11: a missing start date nulls STARTDT but keeps ADT."""
        universe = adsl.with_columns(
            pl.when(pl.col("USUBJID") == "01")
            .then(None)
            .otherwise(pl.col("TRTSDT"))
            .alias("TRTSDT")
        )
        result = _os(universe.adam.tte, adsl, retain="censor_at_start").to_frame()
        s1 = result.filter(pl.col("USUBJID") == "01").row(0, named=True)
        assert s1["STARTDT"] is None
        assert s1["ADT"] == date(2023, 3, 1)

    def test_create_datetime(self, adsl):
        """admiral #2: datetime mode gives ADTM/STARTDTM; date frames are coerced."""
        result = _os(adsl.adam.tte, adsl, create_datetime=True, retain="censor_at_start")
        frame = result.to_frame()
        assert {"ADTM", "STARTDTM"}.issubset(frame.columns)
        assert frame.schema["ADTM"] == pl.Datetime("us")


# ------------------------------------------------------------------ #
# c1-355: stop_at (admiral 1.5 end_dates, event_type "negative")       #
# ------------------------------------------------------------------ #

STOP_ADSL = """
┌─────────┬────────────┬────────────┬────────────┐
│ USUBJID ┆ TRTSDT     ┆ EOSDT      ┆ NACTDT     │
│ ---     ┆ ---        ┆ ---        ┆ ---        │
│ str     ┆ date       ┆ date       ┆ date       │
╞═════════╪════════════╪════════════╪════════════╡
│ A       ┆ 2024-01-01 ┆ 2024-06-30 ┆ 2024-04-01 │
│ B       ┆ 2024-01-01 ┆ 2024-06-30 ┆ null       │
│ C       ┆ 2024-01-01 ┆ 2024-06-30 ┆ 2024-02-15 │
│ D       ┆ 2024-01-01 ┆ 2024-06-30 ┆ 2024-02-01 │
│ E       ┆ 2024-01-01 ┆ 2024-03-01 ┆ null       │
└─────────┴────────────┴────────────┴────────────┘
"""

STOP_ADRS = """
┌─────────┬────────────┬───────┐
│ USUBJID ┆ ADT        ┆ AVALC │
│ ---     ┆ ---        ┆ ---   │
│ str     ┆ date       ┆ str   │
╞═════════╪════════════╪═══════╡
│ A       ┆ 2024-02-01 ┆ SD    │
│ A       ┆ 2024-03-01 ┆ SD    │
│ B       ┆ 2024-02-01 ┆ SD    │
│ B       ┆ 2024-03-10 ┆ PD    │
│ C       ┆ 2024-02-01 ┆ SD    │
│ C       ┆ 2024-03-10 ┆ PD    │
│ D       ┆ 2024-03-01 ┆ SD    │
│ E       ┆ 2024-02-01 ┆ SD    │
│ E       ┆ 2024-03-01 ┆ PD    │
└─────────┴────────────┴───────┘
"""


STOPS = {"EOSDT": (4, "END OF STUDY"), "NACTDT": (2, "NEW ANTICANCER THERAPY")}


def _pfs(censors: dict[int, pl.DataFrame] | None = None, **kwargs) -> pl.DataFrame:
    adsl = pl.from_repr(STOP_ADSL)
    adrs = pl.from_repr(STOP_ADRS)
    last_assessment = adrs.select("USUBJID", "ADT", CNSDTDSC=pl.lit("LAST ASSESSMENT"))
    if censors is None:
        censors = {1: last_assessment, 3: adsl.select("USUBJID", ADT="TRTSDT")}
        kwargs.setdefault("keep_reason", [3])
    return (
        adsl.adam.tte.param(
            "PFS",
            "Progression-Free Survival",
            start="TRTSDT",
            events={"PD": adrs.filter(pl.col("AVALC") == "PD")},
            censors=censors,
            stop_at=kwargs.pop("stop_at", STOPS),
            **kwargs,
        )
        .aval()
        .to_frame()
        .sort("USUBJID")
    )


def _row(result: pl.DataFrame, subject: str) -> dict:
    return result.filter(pl.col("USUBJID") == subject).row(0, named=True)


class TestStopAt:
    def test_no_event_censors_at_last_assessment_before_stop(self):
        """c1-355 subject A: last assessment 2024-03-01 before NACTDT 2024-04-01."""
        a = _row(_pfs(), "A")
        assert (a["ADT"], a["CNSR"], a["AVAL"]) == (date(2024, 3, 1), 2, 61.0)
        assert a["CNSDTDSC"] == "LAST ASSESSMENT"

    def test_event_before_stop_wins(self):
        b = _row(_pfs(), "B")
        assert (b["ADT"], b["CNSR"], b["EVNTDESC"], b["AVAL"]) == (date(2024, 3, 10), 0, "PD", 70.0)

    def test_event_after_stop_is_dropped(self):
        """admiral: records after the first end date are excluded, events too."""
        c = _row(_pfs(), "C")
        assert (c["ADT"], c["CNSR"]) == (date(2024, 2, 1), 2)

    def test_event_on_stop_date_counts(self):
        e = _row(_pfs(), "E")
        assert (e["ADT"], e["CNSR"]) == (date(2024, 3, 1), 0)

    def test_no_censor_record_in_window_drops_with_warning(self):
        """D's only assessment is after NACTDT: no record is left."""
        adrs = pl.from_repr(STOP_ADRS)
        with pytest.warns(UserWarning, match=r"1 subject\(s\).*stop_at date.*\['D'\]"):
            result = _pfs({1: adrs.select("USUBJID", "ADT")})
        assert "D" not in result["USUBJID"].to_list()

    def test_start_censor_keeps_subject_without_record(self):
        d = _row(_pfs(), "D")
        assert (d["ADT"], d["CNSR"], d["AVAL"]) == (date(2024, 1, 1), 3, 1.0)

    def test_censor_tie_takes_the_frame_given_last(self):
        """admiral: on one censor date, the last censor source in the list wins."""
        adsl = pl.from_repr(STOP_ADSL)
        on_start = adsl.select("USUBJID", ADT="TRTSDT")
        result = _pfs({1: on_start, 3: on_start}, keep_reason=[1, 3])
        assert set(result.filter(pl.col("CNSR") != 0)["CNSR"]) == {3}

    def test_positive_event_censors_at_the_stop_date(self):
        """admiral #18 (event_type 'positive'): censor at the first stop date."""
        adsl = pl.from_repr(STOP_ADSL)
        stop = adsl.select("USUBJID", ADT=pl.min_horizontal("EOSDT", "NACTDT"))
        a = _row(_pfs({1: stop}), "A")
        assert (a["ADT"], a["CNSR"], a["EVNTDESC"]) == (
            date(2024, 4, 1),
            2,
            "NEW ANTICANCER THERAPY",
        )

    def test_admiral_end_dates_example(self):
        """admiral 1.5 derive_param_tte example "End of the observation period".

        admiral gives CNSR 1 to both end dates (the censor_source default).
        Fleet asks a distinct CNSR per stop, so 01 and 02 get 2 and 4.
        """
        adsl = pl.from_repr("""
┌─────────┬────────────┬────────────┬────────────┐
│ USUBJID ┆ TRTSDT     ┆ EOSDT      ┆ NEWDRGDT   │
│ ---     ┆ ---        ┆ ---        ┆ ---        │
│ str     ┆ date       ┆ date       ┆ date       │
╞═════════╪════════════╪════════════╪════════════╡
│ 01      ┆ 2020-12-06 ┆ 2021-03-06 ┆ null       │
│ 02      ┆ 2021-01-16 ┆ 2021-04-03 ┆ 2021-03-21 │
│ 03      ┆ 2021-02-01 ┆ null       ┆ null       │
│ 04      ┆ 2021-03-10 ┆ null       ┆ null       │
└─────────┴────────────┴────────────┴────────────┘
""")
        adqs = pl.from_repr("""
┌─────────┬────────────┬──────┐
│ USUBJID ┆ ADT        ┆ CHG  │
│ ---     ┆ ---        ┆ ---  │
│ str     ┆ date       ┆ i64  │
╞═════════╪════════════╪══════╡
│ 01      ┆ 2021-01-03 ┆ 5    │
│ 01      ┆ 2021-02-03 ┆ -2   │
│ 01      ┆ 2021-03-01 ┆ null │
│ 01      ┆ 2021-03-07 ┆ 10   │
│ 02      ┆ 2021-01-03 ┆ 4    │
│ 02      ┆ 2021-02-03 ┆ -1   │
│ 02      ┆ 2021-04-01 ┆ -12  │
│ 03      ┆ 2021-02-15 ┆ 3    │
│ 03      ┆ 2021-03-15 ┆ -15  │
└─────────┴────────────┴──────┘
""")
        result = (
            adsl.adam.tte.param(
                "TTWORSE",
                "Time to Worsening",
                start="TRTSDT",
                events={"WORSENING": adqs.filter(pl.col("CHG") <= -10)},
                censors={
                    1: adqs.filter(pl.col("CHG").is_not_null()),
                    3: adsl.select("USUBJID", ADT="TRTSDT"),
                },
                stop_at={"EOSDT": (2, "END OF STUDY"), "NEWDRGDT": (4, "NEW DRUG")},
            )
            .aval()
            .to_frame()
            .sort("USUBJID")
        )
        assert result["ADT"].to_list() == [
            date(2021, 2, 3),
            date(2021, 2, 3),
            date(2021, 3, 15),
            date(2021, 3, 10),
        ]
        assert result["CNSR"].to_list() == [2, 4, 0, 3]
        assert result["AVAL"].to_list() == [60.0, 19.0, 43.0, 1.0]


# ------------------------------------------------------------------ #
# c1-355 follow-up: the stop gives CNSR and EVNTDESC (ADR-0043)        #
# ------------------------------------------------------------------ #

REASON_ADSL = """
┌─────────┬────────────┬────────────┬────────────┬────────────┐
│ USUBJID ┆ TRTSDT     ┆ EOSDT      ┆ NACTDT     ┆ DCUTDT     │
│ ---     ┆ ---        ┆ ---        ┆ ---        ┆ ---        │
│ str     ┆ date       ┆ date       ┆ date       ┆ date       │
╞═════════╪════════════╪════════════╪════════════╪════════════╡
│ A       ┆ 2024-01-01 ┆ 2024-06-30 ┆ 2024-04-01 ┆ 2024-12-31 │
│ B       ┆ 2024-01-01 ┆ 2024-05-31 ┆ null       ┆ 2024-12-31 │
│ C       ┆ 2024-01-01 ┆ null       ┆ null       ┆ null       │
│ D       ┆ 2024-01-01 ┆ 2024-06-30 ┆ 2024-02-01 ┆ 2024-12-31 │
│ E       ┆ 2024-01-01 ┆ 2024-06-30 ┆ null       ┆ 2024-12-31 │
│ F       ┆ 2024-01-01 ┆ 2024-03-31 ┆ null       ┆ 2024-03-31 │
└─────────┴────────────┴────────────┴────────────┴────────────┘
"""

REASON_ADRS = """
┌─────────┬────────────┬───────┐
│ USUBJID ┆ ADT        ┆ AVALC │
│ ---     ┆ ---        ┆ ---   │
│ str     ┆ date       ┆ str   │
╞═════════╪════════════╪═══════╡
│ A       ┆ 2024-03-01 ┆ SD    │
│ B       ┆ 2024-05-15 ┆ SD    │
│ C       ┆ 2024-02-10 ┆ SD    │
│ E       ┆ 2024-02-20 ┆ PD    │
│ F       ┆ 2024-03-10 ┆ SD    │
└─────────┴────────────┴───────┘
"""

REASON_STOPS = {
    "EOSDT": (4, "END OF STUDY"),
    "NACTDT": (2, "NEW ANTICANCER THERAPY"),
    "DCUTDT": (5, "DATA CUT-OFF"),
}


def _reason_frames() -> dict:
    adsl = pl.from_repr(REASON_ADSL)
    adrs = pl.from_repr(REASON_ADRS)
    last_assessment = adrs.select(
        "USUBJID",
        "ADT",
        EVNTDESC=pl.lit("NO PROGRESSION"),
        CNSDTDSC=pl.lit("LAST ADEQUATE TUMOR ASSESSMENT"),
    )
    no_baseline = adsl.filter(pl.col("USUBJID") == "D").select(
        "USUBJID", ADT="TRTSDT", EVNTDESC=pl.lit("NO BASELINE ASSESSMENT")
    )
    return dict(
        start="TRTSDT",
        events={"PROGRESSIVE DISEASE": adrs.filter(pl.col("AVALC") == "PD")},
        censors={1: last_assessment, 3: no_baseline},
    )


def _reason_pfs(**kwargs) -> pl.DataFrame:
    args = _reason_frames() | {"stop_at": REASON_STOPS, "keep_reason": [3]} | kwargs
    adsl = pl.from_repr(REASON_ADSL)
    return (
        adsl.adam.tte.param("PFS", "Progression-Free Survival", **args)
        .aval()
        .to_frame()
        .sort("USUBJID")
    )


class TestStopReason:
    def test_the_stop_gives_cnsr_and_evntdesc_the_frame_gives_the_date(self):
        """Subject A: censored at the last assessment, reason new anticancer therapy."""
        a = _row(_reason_pfs(), "A")
        assert (a["ADT"], a["AVAL"], a["CNSR"], a["EVNTDESC"], a["CNSDTDSC"]) == (
            date(2024, 3, 1),
            61.0,
            2,
            "NEW ANTICANCER THERAPY",
            "LAST ADEQUATE TUMOR ASSESSMENT",
        )

    def test_end_of_study_when_it_is_the_first_stop(self):
        b = _row(_reason_pfs(), "B")
        assert (b["ADT"], b["AVAL"], b["CNSR"], b["EVNTDESC"]) == (
            date(2024, 5, 15),
            136.0,
            4,
            "END OF STUDY",
        )

    def test_no_stop_date_keeps_the_censor_key(self):
        c = _row(_reason_pfs(), "C")
        assert (c["ADT"], c["CNSR"], c["EVNTDESC"]) == (date(2024, 2, 10), 1, "NO PROGRESSION")

    def test_keep_reason_keeps_the_frame_cnsr_before_a_stop(self):
        d = _row(_reason_pfs(), "D")
        assert (d["ADT"], d["CNSR"], d["EVNTDESC"]) == (
            date(2024, 1, 1),
            3,
            "NO BASELINE ASSESSMENT",
        )

    def test_without_keep_reason_the_stop_gives_the_reason(self):
        d = _row(_reason_pfs(keep_reason=None), "D")
        assert (d["ADT"], d["CNSR"], d["EVNTDESC"]) == (
            date(2024, 1, 1),
            2,
            "NEW ANTICANCER THERAPY",
        )

    def test_an_event_keeps_cnsr_0_and_its_evntdesc(self):
        e = _row(_reason_pfs(), "E")
        assert (e["ADT"], e["CNSR"], e["EVNTDESC"]) == (
            date(2024, 2, 20),
            0,
            "PROGRESSIVE DISEASE",
        )

    def test_two_stops_on_one_date_take_the_first_in_dict_order(self):
        f = _row(_reason_pfs(), "F")
        assert (f["ADT"], f["CNSR"], f["EVNTDESC"]) == (date(2024, 3, 10), 4, "END OF STUDY")
        reverse = dict(reversed(REASON_STOPS.items()))
        f = _row(_reason_pfs(stop_at=reverse), "F")
        assert (f["CNSR"], f["EVNTDESC"]) == (5, "DATA CUT-OFF")

    def test_the_trace_names_the_rule_of_the_cnsr(self):
        from fleet.adam.tte import select_tte

        args = _reason_frames()
        _, trace = select_tte(
            universe=pl.from_repr(REASON_ADSL),
            subject_keys=["USUBJID"],
            stop_at=REASON_STOPS,
            keep_reason=[3],
            **args,
        )
        selected = trace.filter(pl.col("selected")).sort("USUBJID")
        assert selected.select("USUBJID", "cnsr_from").rows() == [
            ("A", "stop_at NACTDT"),
            ("B", "stop_at EOSDT"),
            ("C", "censors key"),
            ("D", "keep_reason"),
            ("E", "event"),
            ("F", "stop_at EOSDT"),
        ]

    def test_a_list_stop_at_raises_and_shows_the_dict_form(self):
        with pytest.raises(DerivationError, match=r"stop_at= is a dict.*\"EOSDT\": \(4,"):
            _reason_pfs(stop_at=["EOSDT", "NACTDT"])

    @pytest.mark.parametrize(
        "stop_at",
        [
            {"EOSDT": 4},
            {"EOSDT": (0, "END OF STUDY")},
            {"EOSDT": (True, "END OF STUDY")},
            {"EOSDT": (4, "")},
            {"EOSDT": ("4", "END OF STUDY")},
        ],
    )
    def test_a_bad_stop_value_raises(self, stop_at):
        with pytest.raises(DerivationError, match=r"each value is \(CNSR, EVNTDESC\)"):
            _reason_pfs(stop_at=stop_at)

    def test_a_cnsr_shared_by_two_stops_raises(self):
        with pytest.raises(DerivationError, match=r"CNSR \[4\] is given to two stop columns"):
            _reason_pfs(stop_at={"EOSDT": (4, "END OF STUDY"), "DCUTDT": (4, "DATA CUT-OFF")})

    def test_a_cnsr_shared_by_a_stop_and_a_censor_raises(self):
        with pytest.raises(DerivationError, match=r"CNSR \[1\] is both a stop_at code"):
            _reason_pfs(stop_at={"EOSDT": (1, "END OF STUDY")})

    def test_keep_reason_must_name_a_censor_key(self):
        with pytest.raises(DerivationError, match=r"keep_reason=\[7\]: \[7\] are not keys"):
            _reason_pfs(keep_reason=[7])


# ------------------------------------------------------------------ #
# admiral test catalog — strata (by=)                                   #
# ------------------------------------------------------------------ #


class TestByStrata:
    def test_by_strata_dynamic_paramcd(self, adsl, adae):
        """admiral #5: one parameter per AEDECOD stratum with derived PARAMCD."""
        result = adsl.adam.tte.param(
            "TT",
            start="TRTSDT",
            events={"AE": _ae(adae)},
            # a censor frame with the by column censors within its stratum
            censors={1: _ae(adae).with_columns(EVNTDESC=pl.lit("LAST"))},
            by=["AEDECOD"],
            set_values_to={
                "PARAMCD": pl.concat_str([pl.lit("TT"), pl.col("AEDECOD").str.slice(0, 6)]),
                "PARAM": pl.concat_str([pl.lit("Time to "), pl.col("AEDECOD")]),
            },
        ).to_frame()
        assert set(result["PARAMCD"].to_list()) >= {"TTNAUSEA", "TTFATIGU"}
        nausea = result.filter(pl.col("PARAMCD") == "TTNAUSEA")
        assert set(nausea["USUBJID"].to_list()) == {"01", "02"}

    def test_static_paramcd_with_strata_raises(self, adsl, adae):
        """admiral #8: constant PARAMCD across several strata violates 1:1."""
        with pytest.raises(Exception, match="1:1"):
            adsl.adam.tte.param(
                "TT",
                "Time to AE",
                start="TRTSDT",
                events={"AE": _ae(adae)},
                censors={1: _ae(adae)},
                by=["AEDECOD"],
            )

    def test_by_missing_in_source_raises(self, adsl):
        """A by column absent from an EVENT frame errors cleanly (a Fleet rule)."""
        with pytest.raises(Exception, match="column 'AEDECOD' not found"):
            adsl.adam.tte.param(
                "TT",
                "Time to Death",
                start="TRTSDT",
                events={"DEATH": _death(adsl)},
                by=["AEDECOD"],
            )

    def test_adsl_censor_applies_to_every_stratum(self):
        """admiral 1.5.0 Test 5: by_vars with an ADSL censor (literal rows)."""
        adsl = pl.from_repr("""
        ┌─────────┬────────────┬────────────┐
        │ USUBJID ┆ TRTSDT     ┆ EOSDT      │
        │ ---     ┆ ---        ┆ ---        │
        │ str     ┆ date       ┆ date       │
        ╞═════════╪════════════╪════════════╡
        │ 01      ┆ 2020-01-01 ┆ 2020-06-01 │
        │ 02      ┆ 2020-01-01 ┆ 2020-06-01 │
        └─────────┴────────────┴────────────┘
        """)
        adae = pl.from_repr("""
        ┌─────────┬──────────┬────────────┐
        │ USUBJID ┆ AEDECOD  ┆ ADT        │
        │ ---     ┆ ---      ┆ ---        │
        │ str     ┆ str      ┆ date       │
        ╞═════════╪══════════╪════════════╡
        │ 01      ┆ NAUSEA   ┆ 2020-02-01 │
        │ 02      ┆ HEADACHE ┆ 2020-03-01 │
        └─────────┴──────────┴────────────┘
        """)

        result = adsl.adam.tte.param(
            "TT",
            start="TRTSDT",
            events={"AE": adae},
            censors={1: adsl.select("USUBJID", ADT="EOSDT", EVNTDESC=pl.lit("END OF STUDY"))},
            by=["AEDECOD"],
            set_values_to={
                "PARAMCD": pl.concat_str([pl.lit("TT"), pl.col("AEDECOD").str.slice(0, 6)]),
                "PARAM": pl.concat_str([pl.lit("Time to "), pl.col("AEDECOD")]),
            },
        ).to_frame()

        assert result.select("PARAMCD", "USUBJID", "ADT", "CNSR").sort(
            "PARAMCD", "USUBJID"
        ).rows() == [
            ("TTHEADAC", "01", date(2020, 6, 1), 1),
            ("TTHEADAC", "02", date(2020, 3, 1), 0),
            ("TTNAUSEA", "01", date(2020, 2, 1), 0),
            ("TTNAUSEA", "02", date(2020, 6, 1), 1),
        ]


# ------------------------------------------------------------------ #
# admiral test catalog — validation errors                              #
# ------------------------------------------------------------------ #


class TestValidation:
    def test_string_date_column_raises(self, adsl):
        """admiral #4: character/DTC date columns are rejected with guidance."""
        death = _death(adsl).with_columns(pl.col("ADT").cast(pl.String))
        with pytest.raises(Exception, match="Parse DTC strings first"):
            _os(adsl.adam.tte, adsl, events={"DEATH": death})

    def test_frame_without_adt_names_the_fix(self, adsl):
        with pytest.raises(Exception, match=r"column 'ADT' not found.*ADT=\"ASTDT\""):
            _os(adsl.adam.tte, adsl, events={"DEATH": adsl.select("USUBJID", "DTHDT")})

    def test_censor_key_must_be_a_positive_integer(self, adsl):
        with pytest.raises(Exception, match="integers >= 1"):
            _os(adsl.adam.tte, adsl, censors={0: _alive(adsl)})

    def test_stop_at_column_has_did_you_mean(self, adsl):
        with pytest.raises(Exception, match="Did you mean 'EOSDT'"):
            _os(adsl.adam.tte, adsl, stop_at={"EOSDTT": (2, "END OF STUDY")})

    def test_paramcd_collision_raises(self, adsl):
        """admiral #10: deriving an already-present PARAMCD errors."""
        ns = _os(adsl.adam.tte, adsl, retain="censor_at_start")
        with pytest.raises(Exception, match="already exists"):
            _os(ns, adsl, retain="censor_at_start")

    def test_bad_start_has_did_you_mean(self, adsl):
        with pytest.raises(Exception, match="Did you mean 'TRTSDT'"):
            _os(adsl.adam.tte, adsl, start="TRTSDTT")


class TestAccumulation:
    def test_multi_param_single_chain(self, adsl, adae):
        """Fleet: one chain accumulates several parameters."""
        result = (
            _os(adsl.adam.tte.pin("ADSL", adsl), adsl, retain="censor_at_start")
            .param(
                "TTAE",
                "Time to First AE",
                start="TRTSDT",
                events={"ADVERSE EVENT": _ae(adae)},
                censors={1: adsl.select("USUBJID", ADT="EOSDT", EVNTDESC=pl.lit("END OF STUDY"))},
            )
            .aval(unit="days")
            .seq("ASEQ", order_by=["PARAMCD"])
            .to_frame()
        )
        assert set(result["PARAMCD"].to_list()) == {"OS", "TTAE"}
        assert result.filter(pl.col("PARAMCD") == "OS").height == 3
        assert "ASEQ" in result.columns

    def test_preexisting_rows_preserved(self, adsl):
        """admiral #12: rows already in the input dataset are kept."""
        base = pl.from_repr("""
┌─────────┬─────────┬──────────┬────────────┬────────────┬──────┐
│ USUBJID ┆ PARAMCD ┆ PARAM    ┆ STARTDT    ┆ ADT        ┆ CNSR │
│ ---     ┆ ---     ┆ ---      ┆ ---        ┆ ---        ┆ ---  │
│ str     ┆ str     ┆ str      ┆ date       ┆ date       ┆ i64  │
╞═════════╪═════════╪══════════╪════════════╪════════════╪══════╡
│ 01      ┆ XYZ     ┆ Existing ┆ 2023-01-01 ┆ 2023-02-01 ┆ 0    │
└─────────┴─────────┴──────────┴────────────┴────────────┴──────┘
""")
        result = _os(base.adam.tte.pin("ADSL", adsl), adsl, retain="censor_at_start").to_frame()
        assert set(result["PARAMCD"].to_list()) == {"XYZ", "OS"}
        assert result.filter(pl.col("PARAMCD") == "XYZ").height == 1


# ------------------------------------------------------------------ #
# AVAL / AVALU / km_data                                                #
# ------------------------------------------------------------------ #


class TestAvalAndKm:
    def test_aval_days_inclusive(self, adsl):
        result = (
            _os(adsl.adam.tte, adsl, retain="censor_at_start")
            .aval(unit="days")
            .to_frame()
            .sort("USUBJID")
        )
        assert result["AVAL"].to_list() == [60.0, 180.0, 1.0]
        assert result["AVALU"].unique().to_list() == ["DAYS"]

    def test_aval_months_conversion(self, adsl):
        result = (
            _os(adsl.adam.tte, adsl, retain="censor_at_start")
            .aval(unit="months")
            .to_frame()
            .sort("USUBJID")
        )
        assert result["AVAL"][0] == pytest.approx(60 / 30.4375)
        assert result["AVALU"][0] == "MONTHS"

    def test_km_data_shape(self, adsl):
        km = _os(adsl.adam.tte, adsl, retain="censor_at_start").aval().km_data("OS")
        assert km.columns == ["USUBJID", "duration", "event"]
        assert km.sort("USUBJID")["event"].to_list() == [True, False, False]

    def test_km_data_requires_paramcd_when_ambiguous(self, adsl, adae):
        ns = (
            _os(adsl.adam.tte, adsl, retain="censor_at_start")
            .param(
                "TTAE",
                "Time to First AE",
                start="TRTSDT",
                events={"AE": _ae(adae)},
                censors={1: adsl.select("USUBJID", ADT="EOSDT")},
            )
            .aval()
        )
        with pytest.raises(Exception, match="paramcd"):
            ns.km_data()


class TestInspectability:
    def test_explain_trace_logged(self, adsl, caplog, monkeypatch):
        import logging

        from fleet.core import log as fleet_log

        # Keep the console handler off, so no later capsys test loses its output.
        monkeypatch.setattr(fleet_log, "_auto_checked", True)
        with caplog.at_level(logging.INFO, logger="fleet"):
            _os(adsl.adam.tte, adsl, retain="censor_at_start", explain=True)
        text = caplog.text
        assert "TTE decision trace" in text
        assert "earliest event" in text
        assert "last censor (no event)" in text

    def test_lineage_records_param(self, adsl):
        ns = _os(adsl.adam.tte, adsl, retain="censor_at_start")
        nodes = {node.name: node for node in ns._lineage if node.verb == "param"}
        assert "OS" not in nodes
        assert {"STARTDT", "ADT", "CNSR", "EVNTDESC", "PARAMCD", "PARAM"} <= set(nodes)
        assert nodes["ADT"].sources == ["TRTSDT"]


class TestKmDataGrouping:
    def test_km_data_pulls_group_columns_from_pinned_adsl(self, adsl):
        """by= columns absent from the ADTTE rows resolve from the ADSL pin."""
        universe = adsl.with_columns(pl.Series("TRT01P", ["Drug A", "Placebo", "Drug A"]))
        km = (
            _os(universe.adam.tte.pin("ADSL", universe), adsl, retain="censor_at_start")
            .aval()
            .km_data("OS", by=["TRT01P"])
            .sort("USUBJID")
        )
        assert km.columns == ["USUBJID", "duration", "event", "TRT01P"]
        assert km["TRT01P"].to_list() == ["Drug A", "Placebo", "Drug A"]

    def test_km_data_unknown_group_column_raises(self, adsl):
        ns = _os(adsl.adam.tte.pin("ADSL", adsl), adsl, retain="censor_at_start").aval()
        with pytest.raises(Exception, match="nor in the pinned ADSL"):
            ns.km_data("OS", by=["NOPE"])


# ------------------------------------------------------------------ #
# c1-355 follow-up: start floor, censor EVNTDESC, PARAM from CT        #
# ------------------------------------------------------------------ #

TTE_ADSL = """
┌─────────┬────────────┬────────────┬────────────┐
│ USUBJID ┆ TRTSDT     ┆ DTHDT      ┆ LSTALVDT   │
│ ---     ┆ ---        ┆ ---        ┆ ---        │
│ str     ┆ date       ┆ date       ┆ date       │
╞═════════╪════════════╪════════════╪════════════╡
│ 01      ┆ 2024-02-01 ┆ 2024-01-20 ┆ 2024-01-20 │
│ 02      ┆ 2024-02-01 ┆ null       ┆ 2024-05-01 │
└─────────┴────────────┴────────────┴────────────┘
"""

STUDY_DEFINE = """\
codelists:
  - oid: CL.PARAMCD.ADTTE
    name: ADTTE Parameter Code
    type: text
    items:
      - coded_value: OS
        decode: Overall Survival
datasets:
  - name: ADTTE
    variables:
      - name: PARAMCD
        codelist: CL.PARAMCD.ADTTE
"""


def _os_frames(adsl: pl.DataFrame, **censor_cols) -> dict:
    return dict(
        start="TRTSDT",
        events={"DEATH": adsl.filter(pl.col("DTHDT").is_not_null()).select("USUBJID", ADT="DTHDT")},
        censors={1: adsl.select("USUBJID", ADT="LSTALVDT", **censor_cols)},
    )


@pytest.fixture
def study(tmp_path, monkeypatch):
    (tmp_path / "study_config.yaml").write_text("study_id: S1\n", encoding="utf-8")
    (tmp_path / "metadata" / "adam").mkdir(parents=True)
    (tmp_path / "metadata" / "adam" / "define.yaml").write_text(STUDY_DEFINE, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestStartFloorAndCensorText:
    def test_event_before_start_is_set_to_start_and_stays_an_event(self):
        """admiral ADT = max(ADT, STARTDT): death 2024-01-20 before TRTSDT 2024-02-01."""
        adsl = pl.from_repr(TTE_ADSL)
        row = _row(
            adsl.adam.tte.param("OS", "Overall Survival", **_os_frames(adsl, EVNTDESC=pl.lit("A")))
            .aval()
            .to_frame(),
            "01",
        )
        assert (row["ADT"], row["CNSR"], row["EVNTDESC"], row["AVAL"]) == (
            date(2024, 2, 1),
            0,
            "DEATH",
            1.0,
        )

    def test_censor_without_evntdesc_is_null_and_warns(self):
        """BDS-TTE: EVNTDESC is study text, so Fleet leaves it null and says so."""
        adsl = pl.from_repr(TTE_ADSL)
        with pytest.warns(UserWarning, match=r"CNSR 1 have no EVNTDESC column"):
            result = adsl.adam.tte.param("OS", "Overall Survival", **_os_frames(adsl)).to_frame()
        assert _row(result, "02")["EVNTDESC"] is None

    def test_censor_with_evntdesc_gives_no_warning(self, recwarn):
        adsl = pl.from_repr(TTE_ADSL)
        adsl.adam.tte.param("OS", "Overall Survival", **_os_frames(adsl, EVNTDESC=pl.lit("ALIVE")))
        assert not [w for w in recwarn if "EVNTDESC" in str(w.message)]


class TestParamFromCT:
    def test_param_is_the_decode_of_the_study_paramcd_codelist(self, study):
        adsl = pl.from_repr(TTE_ADSL)
        result = adsl.adam.tte.param("OS", **_os_frames(adsl, EVNTDESC=pl.lit("ALIVE"))).to_frame()
        assert result["PARAM"].unique().to_list() == ["Overall Survival"]

    def test_unknown_paramcd_names_the_places_searched(self, study):
        adsl = pl.from_repr(TTE_ADSL)
        with pytest.raises(Exception, match=r"'PFS'.*PARAMCD codelists of .*define.yaml.*param="):
            adsl.adam.tte.param("PFS", **_os_frames(adsl, EVNTDESC=pl.lit("ALIVE")))

    def test_no_study_raises_and_asks_for_param(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        adsl = pl.from_repr(TTE_ADSL)
        with pytest.raises(Exception, match=r"no study_config.yaml.*CDISC ADaM CT.*param="):
            adsl.adam.tte.param("OS", **_os_frames(adsl, EVNTDESC=pl.lit("ALIVE")))

    def test_paramcd_from_set_values_to_needs_param_there(self, study):
        adsl = pl.from_repr(TTE_ADSL)
        with pytest.raises(Exception, match="give PARAM there too"):
            adsl.adam.tte.param(
                "OS",
                **_os_frames(adsl, EVNTDESC=pl.lit("ALIVE")),
                set_values_to={"PARAMCD": pl.lit("OS2")},
            )
