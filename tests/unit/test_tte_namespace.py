"""Unit tests for the ADTTE namespace (df.adam.tte).

Ports the substance of admiral's ``test-derive_param_tte.R`` behavior
catalog (each test docstring names the admiral scenario mirrored), plus the
Fleet DX additions: declaration-time validation with did-you-mean,
retain='censor_at_start', auto SRCDOM/SRCVAR/SRCSEQ, AVALU stamping,
inspectable sources, the explain trace, and km_data().
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration
from fleet.adam.tte import (
    AE_EVENT,
    DEATH_EVENT,
    LASTALIVE_CENSOR,
    PREBUILT_SOURCES,
    CensorSource,
    EventSource,
    prebuilt_sources_frame,
    sources_frame,
)
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


def _os(ns, **kwargs):
    """OS param with the standard death/last-alive sources."""
    defaults = dict(start_date="TRTSDT", events=[DEATH_EVENT], censors=[LASTALIVE_CENSOR])
    defaults.update(kwargs)
    return ns.param("OS", "Overall Survival", **defaults)


# ------------------------------------------------------------------ #
# admiral test catalog — core selection                                #
# ------------------------------------------------------------------ #


class TestSelection:
    def test_single_event_single_censor(self, adsl):
        """admiral #1: death event wins (CNSR 0), else last-alive censor (CNSR 1)."""
        result = _os(adsl.adam.tte.pin("ADSL", adsl)).to_frame().sort("USUBJID")
        s1, s2 = result.row(0, named=True), result.row(1, named=True)
        assert s1["CNSR"] == 0 and s1["EVNTDESC"] == "DEATH"
        assert s1["ADT"] == date(2023, 3, 1) and s1["STARTDT"] == date(2023, 1, 1)
        assert s1["SRCDOM"] == "ADSL" and s1["SRCVAR"] == "DTHDT"  # auto-stamped
        assert s2["CNSR"] == 1 and s2["EVNTDESC"] == "ALIVE"
        # Subject 03 has no event and no censor date → dropped (with warning).
        assert result.height == 2

    def test_no_event_no_censor_drops_with_warning(self, adsl):
        """admiral #1/#3 corollary + Fleet DX: the drop is never silent."""
        with pytest.warns(UserWarning, match="no event and no censoring record"):
            result = _os(adsl.adam.tte.pin("ADSL", adsl)).to_frame()
        assert "03" not in result["USUBJID"].to_list()

    def test_retain_censor_at_start(self, adsl):
        """Fleet DX: retain='censor_at_start' replaces the safety-net censor."""
        result = (
            _os(adsl.adam.tte.pin("ADSL", adsl), retain="censor_at_start")
            .to_frame()
            .sort("USUBJID")
        )
        s3 = result.filter(pl.col("USUBJID") == "03").row(0, named=True)
        assert s3["CNSR"] == 1
        assert s3["ADT"] == s3["STARTDT"] == date(2023, 1, 3)
        assert s3["EVNTDESC"] == "NO EVENT OBSERVED"

    def test_multiple_sources_and_adsl_subset(self, adsl, adae):
        """admiral #3: several event+censor sources; subjects absent from the
        ADSL universe produce no output rows."""
        universe = adsl.filter(pl.col("USUBJID") != "02")
        result = (
            universe.adam.tte.pin("ADSL", universe)
            .pin("ADAE", adae)
            .param(
                "TTAE",
                "Time to First AE",
                start_date="TRTSDT",
                events=[AE_EVENT, DEATH_EVENT],
                censors=[LASTALIVE_CENSOR, CensorSource(dataset="ADSL", date="EOSDT")],
            )
            .to_frame()
        )
        assert set(result["USUBJID"].to_list()) == {"01", "03"}

    def test_earliest_event_pooled_across_sources(self, adsl, adae):
        """admiral #3: the earliest date across ALL event sources wins."""
        result = (
            adsl.adam.tte.pin("ADSL", adsl)
            .pin("ADAE", adae)
            .param(
                "X",
                "First of AE or Death",
                start_date="TRTSDT",
                events=[DEATH_EVENT, AE_EVENT],  # death listed first, AE earlier
                censors=[LASTALIVE_CENSOR],
            )
            .to_frame()
        )
        s1 = result.filter(pl.col("USUBJID") == "01").row(0, named=True)
        assert s1["ADT"] == date(2023, 1, 10)  # AE beats later death
        assert s1["EVNTDESC"] == "ADVERSE EVENT"

    def test_order_resolves_same_date_ties(self, adsl):
        """admiral #15: order= picks the lowest AESEQ on a shared date."""
        adae = pl.from_repr("""
┌─────────┬─────────┬────────────┬───────┐
│ USUBJID ┆ TRTEMFL ┆ ASTDT      ┆ AESEQ │
│ ---     ┆ ---     ┆ ---        ┆ ---   │
│ str     ┆ str     ┆ date       ┆ i64   │
╞═════════╪═════════╪════════════╪═══════╡
│ 01      ┆ Y       ┆ 2023-01-10 ┆ 2     │
│ 01      ┆ Y       ┆ 2023-01-10 ┆ 1     │
└─────────┴─────────┴────────────┴───────┘
""")
        result = (
            adsl.adam.tte.pin("ADSL", adsl)
            .pin("ADAE", adae)
            .param(
                "TTAE", "TTAE", start_date="TRTSDT", events=[AE_EVENT], censors=[LASTALIVE_CENSOR]
            )
            .to_frame()
        )
        assert result.filter(pl.col("USUBJID") == "01")["SRCSEQ"][0] == 1

    def test_input_sort_independence(self, adsl, adae):
        """admiral #16: ascending vs shuffled input rows → identical output."""
        chain = lambda ae: (  # noqa: E731
            adsl.adam.tte.pin("ADSL", adsl)
            .pin("ADAE", ae)
            .param(
                "TTAE", "TTAE", start_date="TRTSDT", events=[AE_EVENT], censors=[LASTALIVE_CENSOR]
            )
            .to_frame()
            .sort("USUBJID")
        )
        assert chain(adae).equals(chain(shuffle_rows(adae)))

    def test_same_date_dup_without_order_warns_but_deterministic(self, adsl):
        """admiral #14 (check_type='warning') improved: warn AND stay
        deterministic regardless of input order."""
        adae = pl.DataFrame(
            {
                "USUBJID": ["01", "01"],
                "TRTEMFL": ["Y", "Y"],
                "ASTDT": [date(2023, 1, 10), date(2023, 1, 10)],
                "AEDECOD": ["B", "A"],
            }
        )
        src = EventSource(
            dataset="ADAE", where='pl.col("TRTEMFL") == "Y"', date="ASTDT", set={"EVNTDESC": "AE"}
        )
        run = lambda ae: (  # noqa: E731
            adsl.adam.tte.pin("ADSL", adsl)
            .pin("ADAE", ae)
            .param("TTAE", "TTAE", start_date="TRTSDT", events=[src], censors=[LASTALIVE_CENSOR])
            .to_frame()
        )
        with pytest.warns(UserWarning, match="no order="):
            first = run(adae)
        with pytest.warns(UserWarning, match="no order="):
            second = run(shuffle_rows(adae))
        assert first.sort("USUBJID").equals(second.sort("USUBJID"))

    def test_date_floored_to_startdt(self, adsl):
        """Fleet improvement (documented admiral behavior, untested there):
        an event date before STARTDT is floored to STARTDT."""
        early = CensorSource(dataset="ADSL", date="EOSDT", set={"EVNTDESC": "EOS"})
        universe = adsl.with_columns(pl.lit(date(2023, 4, 1)).alias("TRTSDT"))
        result = (
            universe.adam.tte.pin("ADSL", universe)
            .param("X", "X", start_date="TRTSDT", events=[DEATH_EVENT], censors=[early])
            .to_frame()
            .sort("USUBJID")
        )
        assert (result["ADT"] >= result["STARTDT"]).all()

    def test_null_start_date_keeps_adt(self, adsl):
        """admiral #11: a missing start date nulls STARTDT but keeps ADT."""
        universe = adsl.with_columns(
            pl.when(pl.col("USUBJID") == "01")
            .then(None)
            .otherwise(pl.col("TRTSDT"))
            .alias("TRTSDT")
        )
        result = _os(universe.adam.tte.pin("ADSL", universe)).to_frame()
        s1 = result.filter(pl.col("USUBJID") == "01").row(0, named=True)
        assert s1["STARTDT"] is None
        assert s1["ADT"] == date(2023, 3, 1)

    def test_create_datetime(self, adsl):
        """admiral #2: datetime mode emits ADTM/STARTDTM; date-only sources
        are coerced to datetime."""
        result = _os(adsl.adam.tte.pin("ADSL", adsl), create_datetime=True).to_frame()
        assert {"ADTM", "STARTDTM"}.issubset(result.columns)
        assert result.schema["ADTM"] == pl.Datetime("us")


# ------------------------------------------------------------------ #
# admiral test catalog — end_dates / event_type (1.5.0)                #
# ------------------------------------------------------------------ #


class TestEndDates:
    def test_end_dates_truncate_and_censor(self, adsl, adae):
        """admiral #17: the earliest end date closes the window with its own
        CNSR/EVNTDESC; events after it do not count."""
        # Subject 02's AE (Feb 05) falls after their new-drug date (Jan 15).
        universe = adsl.with_columns(
            pl.when(pl.col("USUBJID") == "02")
            .then(pl.lit(date(2023, 1, 15)))
            .otherwise(None)
            .alias("NEWDRGDT")
        )
        end = CensorSource(dataset="ADSL", date="NEWDRGDT", censor=2, set={"EVNTDESC": "NEW DRUG"})
        result = (
            universe.adam.tte.pin("ADSL", universe)
            .pin("ADAE", adae)
            .param(
                "TTAE",
                "TTAE",
                start_date="TRTSDT",
                events=[AE_EVENT],
                censors=[LASTALIVE_CENSOR],
                end_dates=[end],
            )
            .to_frame()
        )
        s2 = result.filter(pl.col("USUBJID") == "02").row(0, named=True)
        assert s2["CNSR"] == 2 and s2["EVNTDESC"] == "NEW DRUG"
        assert s2["ADT"] == date(2023, 1, 15)
        # Subject 01's AE (Jan 10) precedes any end date → still an event.
        s1 = result.filter(pl.col("USUBJID") == "01").row(0, named=True)
        assert s1["CNSR"] == 0

    def test_event_type_positive_requires_end_dates(self, adsl):
        """admiral #18 precondition: 'positive' without end_dates errors."""
        with pytest.raises(Exception, match="requires end_dates"):
            _os(adsl.adam.tte.pin("ADSL", adsl), event_type="positive")

    def test_event_type_positive_censors_at_window_end(self, adsl):
        """admiral #18: no favorable event → censored at the earliest end date."""
        universe = adsl.with_columns(pl.lit(None, dtype=pl.Date).alias("RESPDT"))
        response = EventSource(dataset="ADSL", date="RESPDT", set={"EVNTDESC": "RESPONSE"})
        eos = CensorSource(dataset="ADSL", date="EOSDT", set={"EVNTDESC": "END OF STUDY"})
        result = (
            universe.adam.tte.pin("ADSL", universe)
            .param(
                "TTR",
                "Time to Response",
                start_date="TRTSDT",
                events=[response],
                end_dates=[eos],
                event_type="positive",
            )
            .to_frame()
            .sort("USUBJID")
        )
        assert result["CNSR"].to_list() == [1, 1, 1]
        assert result["EVNTDESC"].unique().to_list() == ["END OF STUDY"]


# ------------------------------------------------------------------ #
# admiral test catalog — strata (by=)                                   #
# ------------------------------------------------------------------ #


class TestByStrata:
    def test_by_strata_dynamic_paramcd(self, adsl, adae):
        """admiral #5: one parameter per AEDECOD stratum with derived PARAMCD."""
        src = EventSource(
            dataset="ADAE",
            where='pl.col("TRTEMFL") == "Y"',
            date="ASTDT",
            order=["AESEQ"],
            set={"EVNTDESC": "AE"},
        )
        universe = adsl.with_columns(pl.lit("x").alias("AEDECOD")).drop("AEDECOD")
        result = (
            adsl.adam.tte.pin("ADSL", adsl)
            .pin("ADAE", adae)
            .param(
                "TT",
                "Time to AE",
                start_date="TRTSDT",
                events=[src],
                censors=[
                    # censor source must carry the by column too (admiral #6)
                    CensorSource(dataset="ADAE", date="ASTDT", set={"EVNTDESC": "LAST"})
                ],
                by=["AEDECOD"],
                set_values_to={
                    "PARAMCD": pl.concat_str([pl.lit("TT"), pl.col("AEDECOD").str.slice(0, 6)]),
                    "PARAM": pl.concat_str([pl.lit("Time to "), pl.col("AEDECOD")]),
                },
                retain="drop",
            )
            .to_frame()
        )
        _ = universe
        assert set(result["PARAMCD"].to_list()) >= {"TTNAUSEA", "TTFATIGU"}
        nausea = result.filter(pl.col("PARAMCD") == "TTNAUSEA")
        assert set(nausea["USUBJID"].to_list()) == {"01", "02"}

    def test_static_paramcd_with_strata_raises(self, adsl, adae):
        """admiral #8: constant PARAMCD across several strata violates 1:1."""
        src = EventSource(
            dataset="ADAE", where='pl.col("TRTEMFL") == "Y"', date="ASTDT", set={"EVNTDESC": "AE"}
        )
        with pytest.raises(Exception, match="1:1"):
            (
                adsl.adam.tte.pin("ADSL", adsl)
                .pin("ADAE", adae)
                .param(
                    "TT",
                    "Time to AE",
                    start_date="TRTSDT",
                    events=[src],
                    censors=[CensorSource(dataset="ADAE", date="ASTDT")],
                    by=["AEDECOD"],
                )
            )

    def test_by_missing_in_source_raises(self, adsl, adae):
        """admiral #6/#7: a by column absent from a source frame errors cleanly."""
        with pytest.raises(Exception, match="by column 'AEDECOD'"):
            (
                adsl.adam.tte.pin("ADSL", adsl)
                .pin("ADAE", adae)
                .param(
                    "TT",
                    "T",
                    start_date="TRTSDT",
                    events=[DEATH_EVENT],  # ADSL has no AEDECOD
                    by=["AEDECOD"],
                )
            )


# ------------------------------------------------------------------ #
# admiral test catalog — validation errors                              #
# ------------------------------------------------------------------ #


class TestValidation:
    def test_string_date_column_raises(self, adsl):
        """admiral #4: character/DTC date columns are rejected with guidance."""
        universe = adsl.with_columns(pl.col("DTHDT").cast(pl.String))
        with pytest.raises(Exception, match="Parse DTC strings first"):
            _os(universe.adam.tte.pin("ADSL", universe))

    def test_unknown_column_has_did_you_mean(self, adsl):
        """Fleet DX: declaration-time validation with a did-you-mean hint."""
        typo = EventSource(dataset="ADSL", date="DTHDTT", set={"EVNTDESC": "DEATH"})
        with pytest.raises(Exception, match="Did you mean 'DTHDT'"):
            adsl.adam.tte.pin("ADSL", adsl).param("OS", "OS", start_date="TRTSDT", events=[typo])

    def test_unknown_pin_nickname_raises(self, adsl):
        """admiral #13: referencing an unattached dataset names the pins."""
        with pytest.raises(Exception, match="not pinned"):
            adsl.adam.tte.pin("ADSL", adsl).param(
                "TTAE", "TTAE", start_date="TRTSDT", events=[AE_EVENT]
            )

    def test_invalid_where_expression_raises(self, adsl):
        """admiral #9: a bad expression fails loudly at declaration."""
        bad = EventSource(dataset="ADSL", date="DTHDT", where='pl.past("DTHFL")')
        with pytest.raises(Exception):
            _os(adsl.adam.tte.pin("ADSL", adsl), events=[bad])

    def test_paramcd_collision_raises(self, adsl):
        """admiral #10: deriving an already-present PARAMCD errors."""
        ns = _os(adsl.adam.tte.pin("ADSL", adsl), retain="censor_at_start")
        with pytest.raises(Exception, match="already exists"):
            _os(ns, retain="censor_at_start")

    def test_bad_start_date_has_did_you_mean(self, adsl):
        with pytest.raises(Exception, match="Did you mean 'TRTSDT'"):
            _os(adsl.adam.tte.pin("ADSL", adsl), start_date="TRTSDTT")

    def test_unknown_source_field_rejected(self):
        """Pydantic extra='forbid': misspelled source fields fail loudly."""
        with pytest.raises(Exception, match="wher"):
            EventSource(dataset="ADSL", date="DTHDT", wher="x")


class TestAccumulation:
    def test_multi_param_single_chain(self, adsl, adae):
        """Fleet improvement: one chain accumulates several parameters."""
        result = (
            _os(adsl.adam.tte.pin("ADSL", adsl).pin("ADAE", adae), retain="censor_at_start")
            .param(
                "TTAE",
                "Time to First AE",
                start_date="TRTSDT",
                events=[AE_EVENT],
                censors=[
                    CensorSource(dataset="ADSL", date="EOSDT", set={"EVNTDESC": "END OF STUDY"})
                ],
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
        base = pl.DataFrame(
            {
                "USUBJID": ["01"],
                "PARAMCD": ["XYZ"],
                "PARAM": ["Existing"],
                "STARTDT": [date(2023, 1, 1)],
                "ADT": [date(2023, 2, 1)],
                "CNSR": [0],
            }
        )
        result = _os(base.adam.tte.pin("ADSL", adsl), retain="censor_at_start").to_frame()
        assert set(result["PARAMCD"].to_list()) == {"XYZ", "OS"}
        assert result.filter(pl.col("PARAMCD") == "XYZ").height == 1


# ------------------------------------------------------------------ #
# AVAL / AVALU / km_data                                                #
# ------------------------------------------------------------------ #


class TestAvalAndKm:
    def test_aval_days_inclusive(self, adsl):
        result = (
            _os(adsl.adam.tte.pin("ADSL", adsl), retain="censor_at_start")
            .aval(unit="days")
            .to_frame()
            .sort("USUBJID")
        )
        assert result["AVAL"].to_list() == [60.0, 180.0, 1.0]
        assert result["AVALU"].unique().to_list() == ["DAYS"]

    def test_aval_months_conversion(self, adsl):
        result = (
            _os(adsl.adam.tte.pin("ADSL", adsl), retain="censor_at_start")
            .aval(unit="months")
            .to_frame()
            .sort("USUBJID")
        )
        assert result["AVAL"][0] == pytest.approx(60 / 30.4375)
        assert result["AVALU"][0] == "MONTHS"

    def test_km_data_shape(self, adsl):
        km = _os(adsl.adam.tte.pin("ADSL", adsl), retain="censor_at_start").aval().km_data("OS")
        assert km.columns == ["USUBJID", "duration", "event"]
        assert km.sort("USUBJID")["event"].to_list() == [True, False, False]

    def test_km_data_requires_paramcd_when_ambiguous(self, adsl, adae):
        ns = (
            _os(adsl.adam.tte.pin("ADSL", adsl).pin("ADAE", adae), retain="censor_at_start")
            .param(
                "TTAE",
                "TTAE",
                start_date="TRTSDT",
                events=[AE_EVENT],
                censors=[CensorSource(dataset="ADSL", date="EOSDT")],
            )
            .aval()
        )
        with pytest.raises(Exception, match="paramcd"):
            ns.km_data()


# ------------------------------------------------------------------ #
# Inspectability (Fleet improvement over admiral)                       #
# ------------------------------------------------------------------ #


class TestInspectability:
    def test_source_to_polars(self):
        row = DEATH_EVENT.to_polars().row(0, named=True)
        assert row["kind"] == "event" and row["dataset"] == "ADSL"
        assert row["date"] == "DTHDT" and row["censor"] is None
        crow = LASTALIVE_CENSOR.to_polars().row(0, named=True)
        assert crow["kind"] == "censor" and crow["censor"] == 1

    def test_sources_frame_stacks(self):
        frame = sources_frame(DEATH_EVENT, LASTALIVE_CENSOR, AE_EVENT)
        assert frame.height == 3
        assert frame["kind"].to_list() == ["event", "censor", "event"]

    def test_prebuilt_registry(self):
        """admiral #19/#20: the ported registry lists 12 sources as a frame."""
        assert len(PREBUILT_SOURCES) == 12
        frame = prebuilt_sources_frame()
        assert frame.height == 12
        assert "DEATH_EVENT" in frame["name"].to_list()
        assert frame.filter(pl.col("name") == "AE_GR35_EVENT")["dataset"][0] == "ADAE"

    def test_explain_trace_logged(self, adsl, caplog):
        import logging

        with caplog.at_level(logging.INFO, logger="fleet"):
            _os(adsl.adam.tte.pin("ADSL", adsl), retain="censor_at_start", explain=True)
        text = caplog.text
        assert "TTE decision trace" in text
        assert "earliest event" in text
        assert "latest censor (no event)" in text

    def test_lineage_records_param(self, adsl):
        ns = _os(adsl.adam.tte.pin("ADSL", adsl), retain="censor_at_start")
        names = [node.name for node in ns._lineage]
        assert "OS" in names
