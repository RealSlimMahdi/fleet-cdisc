"""Tests for the pick() verb — event selection across sources.

Tests use deliberately dirty / edge-case data to stress the implementation:
- Subjects with NO matching events at all
- Subjects matching MULTIPLE events (top-level order, else list position, wins)
- Null values scattered across source columns
- Duplicate records per subject within a single event
- Mixed types (dates vs strings vs numerics as targets)
- Empty source DataFrames
- Single-target vs multi-target derivations
- Per-event mode/order overrides
- String conditions (YAML path) vs pl.Expr conditions
"""

from __future__ import annotations

from datetime import date

import polars as pl
import pytest

import fleet  # noqa: F401 — registers namespaces

# ═══════════════════════════════════════════════════════════════════════════
# Fixtures: deliberately messy data
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def adsl_base() -> pl.DataFrame:
    """ADSL-like frame with some subjects having death dates, some not."""
    return pl.from_repr("""\
┌─────────┬────────────┬────────────┐
│ USUBJID ┆ DTHDT      ┆ TRTEDT     │
│ ---     ┆ ---        ┆ ---        │
│ str     ┆ date       ┆ date       │
╞═════════╪════════════╪════════════╡
│ SUBJ-01 ┆ 2024-06-15 ┆ 2024-05-01 │
│ SUBJ-02 ┆ null       ┆ 2024-04-20 │
│ SUBJ-03 ┆ null       ┆ null       │
│ SUBJ-04 ┆ null       ┆ 2024-03-10 │
│ SUBJ-05 ┆ 2024-07-01 ┆ 2024-06-30 │
└─────────┴────────────┴────────────┘
""")


@pytest.fixture
def ae_dirty() -> pl.DataFrame:
    """AE source with nulls, duplicates, and subjects not in ADSL."""
    return pl.from_repr("""\
┌─────────┬────────────┬────────────┬──────────────────────┐
│ USUBJID ┆ AESTDTC    ┆ AEENDTC    ┆ AEDECOD              │
│ ---     ┆ ---        ┆ ---        ┆ ---                  │
│ str     ┆ date       ┆ date       ┆ str                  │
╞═════════╪════════════╪════════════╪══════════════════════╡
│ SUBJ-01 ┆ 2024-03-01 ┆ 2024-03-15 ┆ HEADACHE             │
│ SUBJ-01 ┆ 2024-04-10 ┆ null       ┆ NAUSEA               │
│ SUBJ-02 ┆ 2024-02-01 ┆ 2024-02-10 ┆ DIZZINESS            │
│ SUBJ-02 ┆ 2024-04-15 ┆ 2024-04-18 ┆ FATIGUE              │
│ SUBJ-02 ┆ 2024-04-15 ┆ 2024-04-19 ┆ RASH                 │
│ SUBJ-04 ┆ 2024-01-01 ┆ 2024-01-05 ┆ COUGH                │
│ SUBJ-06 ┆ 2024-05-01 ┆ 2024-05-05 ┆ PHANTOM_SUBJECT      │
│ SUBJ-03 ┆ null       ┆ null       ┆ INCOMPLETE_RECORD    │
└─────────┴────────────┴────────────┴──────────────────────┘
""")


@pytest.fixture
def lb_dirty() -> pl.DataFrame:
    """Lab source with varying dates per subject."""
    return pl.from_repr("""\
┌─────────┬────────────┬────────┐
│ USUBJID ┆ ADT        ┆ LBTESTCD │
│ ---     ┆ ---        ┆ ---    │
│ str     ┆ date       ┆ str    │
╞═════════╪════════════╪════════╡
│ SUBJ-01 ┆ 2024-05-20 ┆ ALT    │
│ SUBJ-01 ┆ 2024-06-10 ┆ AST    │
│ SUBJ-02 ┆ 2024-04-25 ┆ ALT    │
│ SUBJ-03 ┆ 2024-02-01 ┆ HGB    │
│ SUBJ-04 ┆ 2024-03-15 ┆ ALT    │
└─────────┴────────────┴────────┘
""")


@pytest.fixture
def ds_dirty() -> pl.DataFrame:
    """DS disposition with death causes and duplicates."""
    return pl.from_repr("""\
┌─────────┬────────────────────────────────────┬──────────┬────────────┐
│ USUBJID ┆ DSTERM                             ┆ DSDECOD  ┆ DSSTDTC    │
│ ---     ┆ ---                                ┆ ---      ┆ ---        │
│ str     ┆ str                                ┆ str      ┆ date       │
╞═════════╪════════════════════════════════════╪══════════╪════════════╡
│ SUBJ-01 ┆ DEATH DUE TO CARDIAC ARREST       ┆ DEATH    ┆ 2024-06-15 │
│ SUBJ-02 ┆ DEATH DUE TO DISEASE PROGRESSION  ┆ DEATH    ┆ 2024-05-01 │
│ SUBJ-02 ┆ COMPLETED                          ┆ COMPLETED┆ 2024-04-20 │
│ SUBJ-04 ┆ LOST TO FOLLOW UP                  ┆ LOST     ┆ 2024-03-20 │
└─────────┴────────────────────────────────────┴──────────┴────────────┘
""")


# ═══════════════════════════════════════════════════════════════════════════
# Tests: LSTALVDT — multi-source, multi-target, latest date over all events
# ═══════════════════════════════════════════════════════════════════════════


class TestPickLSTALVDT:
    """Last Date Known Alive: death > AE end > lab date > treatment end."""

    def test_top_level_order_takes_the_latest_date_over_all_sources(
        self, adsl_base, ae_dirty, lb_dirty
    ):
        """admiral LSTALVDT: order=[LSTALVDT], mode last acts across events."""
        result = (
            adsl_base.adam.adsl.pick(  # type: ignore[attr-defined]
                ["LSTALVDT", "DTHFL"],
                events=[
                    # Priority 1: Death date (highest)
                    {
                        "when": pl.col("DTHDT").is_not_null(),
                        "set": {"LSTALVDT": "DTHDT", "DTHFL": pl.lit("Y")},
                        "source": adsl_base,
                    },
                    # Priority 2: Latest AE end date
                    {
                        "when": pl.col("AEENDTC").is_not_null(),
                        "set": {"LSTALVDT": "AEENDTC", "DTHFL": pl.lit("N")},
                        "source": ae_dirty,
                        "mode": "last",
                        "order": ["AEENDTC"],
                    },
                    # Priority 3: Latest lab date
                    {
                        "when": pl.col("ADT").is_not_null(),
                        "set": {"LSTALVDT": "ADT", "DTHFL": pl.lit("N")},
                        "source": lb_dirty,
                        "mode": "last",
                        "order": ["ADT"],
                    },
                    # Priority 4: Treatment end (from base frame)
                    {
                        "when": pl.col("TRTEDT").is_not_null(),
                        "set": {"LSTALVDT": "TRTEDT", "DTHFL": pl.lit("N")},
                        "source": adsl_base,
                    },
                ],
                by=["USUBJID"],
                order=["LSTALVDT"],
                mode="last",
            )
            .to_frame()
            .sort("USUBJID")
        )

        # SUBJ-01: death date 2024-06-15 is the latest (lab 2024-06-10)
        row1 = result.filter(pl.col("USUBJID") == "SUBJ-01")
        assert row1["DTHFL"][0] == "Y"
        assert row1["LSTALVDT"][0] == date(2024, 6, 15)

        # SUBJ-02: no death; AE end 2024-04-19, lab 2024-04-25, TRTEDT 2024-04-20
        # The latest date wins over list position → lab
        row2 = result.filter(pl.col("USUBJID") == "SUBJ-02")
        assert row2["DTHFL"][0] == "N"
        assert row2["LSTALVDT"][0] == date(2024, 4, 25)

        # SUBJ-03: no death, no AE end (all null), lab=2024-02-01, no TRTEDT
        # Only the lab event has a record
        row3 = result.filter(pl.col("USUBJID") == "SUBJ-03")
        assert row3["DTHFL"][0] == "N"
        assert row3["LSTALVDT"][0] == date(2024, 2, 1)

        # SUBJ-04: no death, AE end=2024-01-05, lab=2024-03-15, TRTEDT=2024-03-10
        # The latest date (lab) wins
        row4 = result.filter(pl.col("USUBJID") == "SUBJ-04")
        assert row4["DTHFL"][0] == "N"
        assert row4["LSTALVDT"][0] == date(2024, 3, 15)

        # SUBJ-05: death date 2024-07-01 → wins
        row5 = result.filter(pl.col("USUBJID") == "SUBJ-05")
        assert row5["DTHFL"][0] == "Y"
        assert row5["LSTALVDT"][0] == date(2024, 7, 1)

    def test_subject_with_no_events_gets_null(self, adsl_base):
        """A subject that matches NO events should get null targets."""
        # SUBJ-03 has null DTHDT and null TRTEDT
        result = (
            adsl_base.adam.adsl.pick(  # type: ignore[attr-defined]
                ["LSTALVDT", "DTHFL"],
                events=[
                    {
                        "when": pl.col("DTHDT").is_not_null(),
                        "set": {"LSTALVDT": "DTHDT", "DTHFL": pl.lit("Y")},
                        "source": adsl_base,
                    },
                    {
                        "when": pl.col("TRTEDT").is_not_null(),
                        "set": {"LSTALVDT": "TRTEDT", "DTHFL": pl.lit("N")},
                        "source": adsl_base,
                    },
                ],
                by=["USUBJID"],
            )
            .to_frame()
            .sort("USUBJID")
        )
        row3 = result.filter(pl.col("USUBJID") == "SUBJ-03")
        assert row3["LSTALVDT"][0] is None
        assert row3["DTHFL"][0] is None


# ═══════════════════════════════════════════════════════════════════════════
# Tests: DTHCAUS — single target, multi-source, string conditions
# ═══════════════════════════════════════════════════════════════════════════


class TestPickDTHCAUS:
    """Death cause from AE (fatal) then DS (DEATH decode)."""

    def test_dthcaus_ae_over_ds(self, adsl_base, ae_dirty, ds_dirty):
        """AE with fatal outcome takes priority over DS death record."""
        # Add AEOUT column to ae_dirty for fatal condition
        ae_with_fatal = ae_dirty.with_columns(
            pl.when(pl.col("USUBJID") == "SUBJ-01")
            .then(pl.lit("FATAL"))
            .otherwise(pl.lit("RECOVERED"))
            .alias("AEOUT")
        )

        result = (
            adsl_base.adam.adsl.pick(  # type: ignore[attr-defined]
                "DTHCAUS",
                events=[
                    # Priority 1: Fatal AE
                    {
                        "when": 'pl.col("AEOUT") == "FATAL"',
                        "set": {"DTHCAUS": "AEDECOD"},
                        "source": ae_with_fatal,
                        "mode": "last",
                        "order": ["AEENDTC"],
                    },
                    # Priority 2: DS death record
                    {
                        "when": 'pl.col("DSDECOD") == "DEATH"',
                        "set": {"DTHCAUS": "DSTERM"},
                        "source": ds_dirty,
                    },
                ],
                by=["USUBJID"],
            )
            .to_frame()
            .sort("USUBJID")
        )

        # SUBJ-01: has fatal AE → AEDECOD from latest (NAUSEA, null end date filtered)
        row1 = result.filter(pl.col("USUBJID") == "SUBJ-01")
        # SUBJ-01 fatal AEs: HEADACHE (end 2024-03-15) and NAUSEA (end null)
        # mode=last, order=AEENDTC → HEADACHE wins (NAUSEA has null end)
        assert row1["DTHCAUS"][0] == "HEADACHE"

        # SUBJ-02: no fatal AE, but DS has DEATH record
        row2 = result.filter(pl.col("USUBJID") == "SUBJ-02")
        assert row2["DTHCAUS"][0] == "DEATH DUE TO DISEASE PROGRESSION"

        # SUBJ-03: no fatal AE, no DS death → null
        row3 = result.filter(pl.col("USUBJID") == "SUBJ-03")
        assert row3["DTHCAUS"][0] is None

    def test_string_conditions_yaml_compat(self, adsl_base, ds_dirty):
        """String conditions (YAML path) work identically to pl.Expr."""
        result = (
            adsl_base.adam.adsl.pick(  # type: ignore[attr-defined]
                "DTHCAUS",
                events=[
                    {
                        "when": 'pl.col("DSDECOD") == "DEATH"',
                        "set": {"DTHCAUS": "DSTERM"},
                        "source": ds_dirty,
                    },
                ],
                by=["USUBJID"],
            )
            .to_frame()
            .sort("USUBJID")
        )
        # SUBJ-01 has DS DEATH record
        assert result.filter(pl.col("USUBJID") == "SUBJ-01")["DTHCAUS"][0] is not None


# ═══════════════════════════════════════════════════════════════════════════
# Tests: Edge Cases
# ═══════════════════════════════════════════════════════════════════════════


class TestPickEdgeCases:
    """Stress tests: empty sources, duplicates, type coercion."""

    def test_invalid_mode_raises(self, adsl_base):
        with pytest.raises(Exception, match="mode='lastt'"):
            adsl_base.adam.adsl.pick(
                "MYVAR",
                events=[{"when": pl.col("TRTEDT").is_not_null(), "set": {"MYVAR": "TRTEDT"}}],
                mode="lastt",
            )

    def test_invalid_per_event_mode_raises(self, adsl_base):
        with pytest.raises(Exception, match="event #0 mode='frist'"):
            adsl_base.adam.adsl.pick(
                "MYVAR",
                events=[
                    {
                        "when": pl.col("TRTEDT").is_not_null(),
                        "set": {"MYVAR": "TRTEDT"},
                        "mode": "frist",
                    }
                ],
            ).to_frame()

    def test_global_order_on_non_target_column_does_not_crash(self, adsl_base):
        """order= may name a source column that is not a target — it selects
        the record within the event and also ranks the events."""
        ae = pl.from_repr("""\
┌─────────┬────────────┬──────┐
│ USUBJID ┆ AEENDTC    ┆ ASEQ │
│ ---     ┆ ---        ┆ ---  │
│ str     ┆ date       ┆ i64  │
╞═════════╪════════════╪══════╡
│ SUBJ-01 ┆ 2024-01-05 ┆ 1    │
│ SUBJ-01 ┆ 2024-02-01 ┆ 2    │
└─────────┴────────────┴──────┘
""")
        result = adsl_base.adam.adsl.pick(  # type: ignore[attr-defined]
            "LSTALVDT",
            events=[
                {
                    "when": pl.col("AEENDTC").is_not_null(),
                    "set": {"LSTALVDT": "AEENDTC"},
                    "source": ae,
                }
            ],
            by=["USUBJID"],
            order=["ASEQ"],  # not a target — used within the event only
            mode="last",
        ).to_frame()
        row = result.filter(pl.col("USUBJID") == "SUBJ-01")
        assert row["LSTALVDT"][0] == date(2024, 2, 1)  # last by ASEQ

    def test_empty_source_skipped(self, adsl_base):
        """An event whose source produces zero matches is silently skipped."""
        empty = pl.DataFrame(
            {"USUBJID": pl.Series([], dtype=pl.String), "VAL": pl.Series([], dtype=pl.Date)}
        )
        result = (
            adsl_base.adam.adsl.pick(  # type: ignore[attr-defined]
                "MYVAR",
                events=[
                    {
                        "when": pl.col("VAL").is_not_null(),
                        "set": {"MYVAR": "VAL"},
                        "source": empty,
                    },
                    {
                        "when": pl.col("TRTEDT").is_not_null(),
                        "set": {"MYVAR": "TRTEDT"},
                        "source": adsl_base,
                    },
                ],
                by=["USUBJID"],
            )
            .to_frame()
            .sort("USUBJID")
        )
        # SUBJ-02 has TRTEDT → should fall through to event 2
        row2 = result.filter(pl.col("USUBJID") == "SUBJ-02")
        assert row2["MYVAR"][0] == date(2024, 4, 20)

    def test_all_events_empty_gives_null(self, adsl_base):
        """When every event filters to zero rows, targets become null."""
        result = adsl_base.adam.adsl.pick(  # type: ignore[attr-defined]
            "MYVAR",
            events=[
                {
                    "when": pl.lit(False),
                    "set": {"MYVAR": pl.lit("IMPOSSIBLE")},
                    "source": adsl_base,
                },
            ],
            by=["USUBJID"],
        ).to_frame()
        assert result["MYVAR"].null_count() == len(result)

    def test_duplicate_records_within_event(self, adsl_base, ae_dirty):
        """Multiple records per subject in one event — mode/order selects one."""
        # SUBJ-02 has 3 AE records, two on same date with different end dates
        result = (
            adsl_base.adam.adsl.pick(  # type: ignore[attr-defined]
                "LATEST_AE_END",
                events=[
                    {
                        "when": pl.col("AEENDTC").is_not_null(),
                        "set": {"LATEST_AE_END": "AEENDTC"},
                        "source": ae_dirty,
                        "mode": "last",
                        "order": ["AEENDTC"],
                    },
                ],
                by=["USUBJID"],
            )
            .to_frame()
            .sort("USUBJID")
        )
        # SUBJ-02 AE ends: 2024-02-10, 2024-04-18, 2024-04-19 → last=2024-04-19
        row2 = result.filter(pl.col("USUBJID") == "SUBJ-02")
        assert row2["LATEST_AE_END"][0] == date(2024, 4, 19)

    def test_literal_values_in_set(self, adsl_base):
        """Literal values (via pl.lit) work in the set dict."""
        result = (
            adsl_base.adam.adsl.pick(  # type: ignore[attr-defined]
                ["STATUS", "CODE"],
                events=[
                    {
                        "when": pl.col("DTHDT").is_not_null(),
                        "set": {"STATUS": pl.lit("DEAD"), "CODE": pl.lit(1)},
                        "source": adsl_base,
                    },
                    {
                        "when": pl.col("TRTEDT").is_not_null(),
                        "set": {"STATUS": pl.lit("ALIVE"), "CODE": pl.lit(0)},
                        "source": adsl_base,
                    },
                ],
                by=["USUBJID"],
            )
            .to_frame()
            .sort("USUBJID")
        )
        # SUBJ-01: has death → DEAD/1
        row1 = result.filter(pl.col("USUBJID") == "SUBJ-01")
        assert row1["STATUS"][0] == "DEAD"
        assert row1["CODE"][0] == 1

        # SUBJ-02: no death, has TRTEDT → ALIVE/0
        row2 = result.filter(pl.col("USUBJID") == "SUBJ-02")
        assert row2["STATUS"][0] == "ALIVE"
        assert row2["CODE"][0] == 0

        # SUBJ-03: no death, no TRTEDT → null
        row3 = result.filter(pl.col("USUBJID") == "SUBJ-03")
        assert row3["STATUS"][0] is None
        assert row3["CODE"][0] is None

    def test_single_target_string_convenience(self, adsl_base):
        """Single target passed as a bare string (not list) works."""
        result = (
            adsl_base.adam.adsl.pick(  # type: ignore[attr-defined]
                "LSTDT",
                events=[
                    {
                        "when": pl.col("DTHDT").is_not_null(),
                        "set": {"LSTDT": "DTHDT"},
                        "source": adsl_base,
                    },
                ],
                by=["USUBJID"],
            )
            .to_frame()
            .sort("USUBJID")
        )
        assert "LSTDT" in result.columns
        assert result.filter(pl.col("USUBJID") == "SUBJ-01")["LSTDT"][0] == date(2024, 6, 15)

    def test_no_by_var_in_source_raises_cleanly(self, adsl_base):
        """Source missing the by-var column should raise during execution."""
        bad_source = pl.from_repr("""\
┌───────────┬─────┐
│ WRONG_COL ┆ VAL │
│ ---       ┆ --- │
│ str       ┆ i64 │
╞═══════════╪═════╡
│ A         ┆ 1   │
└───────────┴─────┘
""")
        with pytest.raises(Exception):
            (
                adsl_base.adam.adsl.pick(  # type: ignore[attr-defined]
                    "X",
                    events=[
                        {
                            "when": pl.col("VAL") > 0,
                            "set": {"X": "VAL"},
                            "source": bad_source,
                        },
                    ],
                    by=["USUBJID"],
                ).to_frame()
            )

    def test_empty_events_raises_valueerror(self, adsl_base):
        """Empty events list raises ValueError immediately."""
        with pytest.raises(ValueError, match="at least one event"):
            adsl_base.adam.adsl.pick("X", events=[])  # type: ignore[attr-defined]

    def test_missing_when_key_raises(self, adsl_base):
        """Event without 'when' key raises ValueError."""
        with pytest.raises(ValueError, match="'when' and 'set'"):
            (
                adsl_base.adam.adsl.pick("X", events=[{"set": {"X": pl.lit(1)}}]).to_frame()  # type: ignore[attr-defined]
            )

    def test_missing_set_key_raises(self, adsl_base):
        """Event without 'set' key raises ValueError."""
        with pytest.raises(ValueError, match="'when' and 'set'"):
            (
                adsl_base.adam.adsl.pick("X", events=[{"when": pl.lit(True)}]).to_frame()  # type: ignore[attr-defined]
            )

    def test_uses_current_frame_when_no_source(self, adsl_base):
        """When 'source' is omitted, pick() uses the current pipeline frame."""
        result = (
            adsl_base.adam.adsl.pick(  # type: ignore[attr-defined]
                "HAS_DEATH",
                events=[
                    {
                        "when": pl.col("DTHDT").is_not_null(),
                        "set": {"HAS_DEATH": pl.lit("Y")},
                    },
                ],
                by=["USUBJID"],
            )
            .to_frame()
            .sort("USUBJID")
        )
        assert result.filter(pl.col("USUBJID") == "SUBJ-01")["HAS_DEATH"][0] == "Y"
        assert result.filter(pl.col("USUBJID") == "SUBJ-02")["HAS_DEATH"][0] is None

    def test_per_event_order_override(self, adsl_base, ae_dirty):
        """Per-event order overrides the global order."""
        result = (
            adsl_base.adam.adsl.pick(  # type: ignore[attr-defined]
                "FIRST_AE_END",
                events=[
                    {
                        "when": pl.col("AEENDTC").is_not_null(),
                        "set": {"FIRST_AE_END": "AEENDTC"},
                        "source": ae_dirty,
                        "mode": "first",  # override: take earliest
                        "order": ["AEENDTC"],
                    },
                ],
                by=["USUBJID"],
                mode="last",  # global says last, but event overrides to first
            )
            .to_frame()
            .sort("USUBJID")
        )
        # SUBJ-02 AE ends: 2024-02-10, 2024-04-18, 2024-04-19 → first=2024-02-10
        row2 = result.filter(pl.col("USUBJID") == "SUBJ-02")
        assert row2["FIRST_AE_END"][0] == date(2024, 2, 10)

    def test_chaining_after_pick(self, adsl_base):
        """pick() returns Self — further verbs can be chained."""
        result = (
            adsl_base.adam.adsl.pick(  # type: ignore[attr-defined]
                "LSTALVDT",
                events=[
                    {
                        "when": pl.col("DTHDT").is_not_null(),
                        "set": {"LSTALVDT": "DTHDT"},
                        "source": adsl_base,
                    },
                    {
                        "when": pl.col("TRTEDT").is_not_null(),
                        "set": {"LSTALVDT": "TRTEDT"},
                        "source": adsl_base,
                    },
                ],
                by=["USUBJID"],
            )
            .source("USUBJID")  # chain another verb after pick
            .to_frame()
        )
        assert "LSTALVDT" in result.columns
        assert "USUBJID" in result.columns

    def test_target_not_in_all_events_gets_null(self, adsl_base):
        """If an event's 'set' omits a target, that target is null for that event."""
        result = (
            adsl_base.adam.adsl.pick(  # type: ignore[attr-defined]
                ["A", "B"],
                events=[
                    {
                        "when": pl.col("DTHDT").is_not_null(),
                        "set": {"A": "DTHDT"},  # B not set → null
                        "source": adsl_base,
                    },
                    {
                        "when": pl.col("TRTEDT").is_not_null(),
                        "set": {"A": "TRTEDT", "B": pl.lit("from_trt")},
                        "source": adsl_base,
                    },
                ],
                by=["USUBJID"],
            )
            .to_frame()
            .sort("USUBJID")
        )
        # SUBJ-01 matches event 1 (death) → A=DTHDT, B=null
        row1 = result.filter(pl.col("USUBJID") == "SUBJ-01")
        assert row1["A"][0] == date(2024, 6, 15)
        assert row1["B"][0] is None

        # SUBJ-02 matches event 2 (TRTEDT) → A=TRTEDT, B="from_trt"
        row2 = result.filter(pl.col("USUBJID") == "SUBJ-02")
        assert row2["A"][0] == date(2024, 4, 20)
        assert row2["B"][0] == "from_trt"


# ═══════════════════════════════════════════════════════════════════════════
# Tests: Verb ↔ Spec equivalence + non-date (string) targets
# ═══════════════════════════════════════════════════════════════════════════


class TestPickVerbSpecEquivalence:
    """Verify that verb (inline) and spec (from_spec dispatch) produce identical results."""

    @pytest.fixture()
    def base_df(self):
        """Minimal ADSL-like frame with USUBJID + dates."""
        return pl.from_repr("""\
┌─────────┬────────────┬────────────┐
│ USUBJID ┆ DTHDT      ┆ TRTEDT     │
│ ---     ┆ ---        ┆ ---        │
│ str     ┆ date       ┆ date       │
╞═════════╪════════════╪════════════╡
│ S01     ┆ 2024-05-01 ┆ 2024-04-15 │
│ S02     ┆ null       ┆ 2024-06-10 │
│ S03     ┆ null       ┆ null       │
└─────────┴────────────┴────────────┘
""")

    @pytest.fixture()
    def ae_source(self):
        """AE-like source with fatal outcome and string term."""
        return pl.from_repr("""\
┌─────────┬───────────┬────────────────┬────────────┐
│ USUBJID ┆ AEOUT     ┆ AEDECOD        ┆ AEENDTC    │
│ ---     ┆ ---       ┆ ---            ┆ ---        │
│ str     ┆ str       ┆ str            ┆ date       │
╞═════════╪═══════════╪════════════════╪════════════╡
│ S01     ┆ FATAL     ┆ CARDIAC ARREST ┆ 2024-04-28 │
│ S01     ┆ RECOVERED ┆ HEADACHE       ┆ 2024-03-01 │
│ S02     ┆ RECOVERED ┆ RASH           ┆ 2024-05-20 │
│ S02     ┆ RECOVERED ┆ NAUSEA         ┆ 2024-06-01 │
└─────────┴───────────┴────────────────┴────────────┘
""")

    @pytest.fixture()
    def ds_source(self):
        """DS-like source with death decode."""
        return pl.from_repr("""\
┌─────────┬───────────┬────────────────────┐
│ USUBJID ┆ DSDECOD   ┆ DSTERM             │
│ ---     ┆ ---       ┆ ---                │
│ str     ┆ str       ┆ str                │
╞═════════╪═══════════╪════════════════════╡
│ S01     ┆ DEATH     ┆ CARDIAC FAILURE    │
│ S02     ┆ COMPLETED ┆ PROTOCOL COMPLETED │
└─────────┴───────────┴────────────────────┘
""")

    def test_string_dthcaus_verb_vs_spec(self, base_df, ae_source, ds_source):
        """DTHCAUS (string target) produces same results via verb and from_spec."""
        # -- Verb path (inline Python) --
        verb_result = (
            base_df.adam.adsl.pick(  # type: ignore[attr-defined]
                ["DTHCAUS", "DTHDOM"],
                events=[
                    {
                        "when": pl.col("AEOUT") == "FATAL",
                        "set": {"DTHCAUS": "AEDECOD", "DTHDOM": pl.lit("AE")},
                        "source": ae_source,
                        "mode": "last",
                        "order": ["AEENDTC"],
                    },
                    {
                        "when": pl.col("DSDECOD") == "DEATH",
                        "set": {"DTHCAUS": "DSTERM", "DTHDOM": pl.lit("DS")},
                        "source": ds_source,
                    },
                ],
                by=["USUBJID"],
            )
            .to_frame()
            .sort("USUBJID")
        )

        # -- Spec-equivalent path (string conditions + string literals) --
        spec_result = (
            base_df.adam.adsl.pick(  # type: ignore[attr-defined]
                ["DTHCAUS", "DTHDOM"],
                events=[
                    {
                        "when": 'pl.col("AEOUT") == "FATAL"',
                        "set": {"DTHCAUS": "AEDECOD", "DTHDOM": 'pl.lit("AE")'},
                        "source": ae_source,
                        "mode": "last",
                        "order": ["AEENDTC"],
                    },
                    {
                        "when": 'pl.col("DSDECOD") == "DEATH"',
                        "set": {"DTHCAUS": "DSTERM", "DTHDOM": 'pl.lit("DS")'},
                        "source": ds_source,
                    },
                ],
                by=["USUBJID"],
            )
            .to_frame()
            .sort("USUBJID")
        )

        # Both must produce identical DataFrames
        assert verb_result.equals(spec_result), (
            f"Verb and spec paths diverge:\nVerb:\n{verb_result}\n\nSpec:\n{spec_result}"
        )

        # Verify actual values (non-date string targets)
        # S01: has fatal AE → AEDECOD="CARDIAC ARREST", DTHDOM="AE"
        row1 = verb_result.filter(pl.col("USUBJID") == "S01")
        assert row1["DTHCAUS"][0] == "CARDIAC ARREST"
        assert row1["DTHDOM"][0] == "AE"

        # S02: no fatal AE, DS has COMPLETED (not DEATH) → null
        row2 = verb_result.filter(pl.col("USUBJID") == "S02")
        assert row2["DTHCAUS"][0] is None
        assert row2["DTHDOM"][0] is None

        # S03: no data in either source → null
        row3 = verb_result.filter(pl.col("USUBJID") == "S03")
        assert row3["DTHCAUS"][0] is None
        assert row3["DTHDOM"][0] is None

    def test_literal_string_in_set_from_yaml(self, base_df):
        """pl.lit('value') strings in set are parsed, not treated as column refs."""
        result = (
            base_df.adam.adsl.pick(  # type: ignore[attr-defined]
                ["DTHFL", "LSTALVDT"],
                events=[
                    {
                        "when": 'pl.col("DTHDT").is_not_null()',
                        "set": {"DTHFL": 'pl.lit("Y")', "LSTALVDT": "DTHDT"},
                    },
                    {
                        "when": 'pl.col("TRTEDT").is_not_null()',
                        "set": {"DTHFL": 'pl.lit("N")', "LSTALVDT": "TRTEDT"},
                    },
                ],
                by=["USUBJID"],
                order=["LSTALVDT"],
                mode="last",
            )
            .to_frame()
            .sort("USUBJID")
        )
        # S01: has DTHDT → DTHFL="Y" (from pl.lit parsed string)
        row1 = result.filter(pl.col("USUBJID") == "S01")
        assert row1["DTHFL"][0] == "Y"
        assert row1["LSTALVDT"][0] == date(2024, 5, 1)

        # S02: no DTHDT, has TRTEDT → DTHFL="N"
        row2 = result.filter(pl.col("USUBJID") == "S02")
        assert row2["DTHFL"][0] == "N"
        assert row2["LSTALVDT"][0] == date(2024, 6, 10)

        # S03: neither → null
        row3 = result.filter(pl.col("USUBJID") == "S03")
        assert row3["DTHFL"][0] is None

    def test_non_date_categorical_target(self, base_df, ae_source):
        """Non-date categorical target (severity grouping) works correctly."""
        ae_with_sev = ae_source.with_columns(
            pl.when(pl.col("AEDECOD") == "CARDIAC ARREST")
            .then(pl.lit("SEVERE"))
            .otherwise(pl.lit("MILD"))
            .alias("AESEV")
        )

        result = (
            base_df.adam.adsl.pick(  # type: ignore[attr-defined]
                "DTHSEV",
                events=[
                    {
                        "when": pl.col("AEOUT") == "FATAL",
                        "set": {"DTHSEV": "AESEV"},
                        "source": ae_with_sev,
                    },
                ],
                by=["USUBJID"],
            )
            .to_frame()
            .sort("USUBJID")
        )
        # S01 has fatal AE (CARDIAC ARREST → SEVERE)
        assert result.filter(pl.col("USUBJID") == "S01")["DTHSEV"][0] == "SEVERE"
        # S02 has no fatal AE → null
        assert result.filter(pl.col("USUBJID") == "S02")["DTHSEV"][0] is None
