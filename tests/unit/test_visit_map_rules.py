"""visit_map, element_boundaries and epoch_assign(se=) rules (alpha audit, sdtm package)."""

from __future__ import annotations

import warnings

import polars as pl
import pytest

import fleet  # noqa: F401
from fleet.core.exceptions import DerivationError
from fleet.sdtm.tdd import TrialVisit, TrialVisits
from tests.helpers import shuffle_rows

TV = pl.from_repr("""
┌──────────┬───────────┬─────────┐
│ VISITNUM ┆ VISIT     ┆ VISITDY │
│ ---      ┆ ---       ┆ ---     │
│ f64      ┆ str       ┆ i64     │
╞══════════╪═══════════╪═════════╡
│ 1.0      ┆ SCREENING ┆ -3      │
│ 2.0      ┆ BASELINE  ┆ 1       │
│ 3.0      ┆ WEEK 2    ┆ 15      │
└──────────┴───────────┴─────────┘
""")


def _map(sv: pl.DataFrame, **kw) -> pl.DataFrame:
    kw.setdefault("ref_date", "RFSTDTC")
    return sv.sdtm.visit_map(
        "VISITNUM", "VISIT", date_col="SVSTDTC", planned_visits=TV, **kw
    ).to_frame()


class TestStudyDayDistance:
    """c1-222 (decision B): the distance is the difference of study-day numbers."""

    def test_day_minus_one_is_two_days_from_baseline(self):
        sv = pl.from_repr("""
┌─────────┬────────────┬────────────┐
│ USUBJID ┆ SVSTDTC    ┆ RFSTDTC    │
│ ---     ┆ ---        ┆ ---        │
│ str     ┆ str        ┆ str        │
╞═════════╪════════════╪════════════╡
│ 01      ┆ 2014-01-09 ┆ 2014-01-10 │
└─────────┴────────────┴────────────┘
""")
        # Day -1: 2 from SCREENING (-3) and 2 from BASELINE (1); the tie takes VISITNUM 1.
        assert _map(sv)["VISIT"].to_list() == ["SCREENING"]
        # With a 1-day window the record is outside every window: unscheduled after SCREENING.
        out = _map(sv, tolerance={"before": 1, "after": 1})
        assert out.row(0)[-2:] == (1.1, "UNSCHEDULED 1.1")


class TestRefDateAndColumns:
    """c1-220: ref_date from the DM pin, and named errors for missing columns."""

    SV = pl.from_repr("""
┌─────────┬────────────┐
│ USUBJID ┆ SVSTDTC    │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ 01      ┆ 2014-01-24 │
│ 01      ┆ 2014-01-09 │
└─────────┴────────────┘
""")
    DM = pl.from_repr("""
┌─────────┬────────────┐
│ USUBJID ┆ RFSTDTC    │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ 01      ┆ 2014-01-10 │
└─────────┴────────────┘
""")

    def test_ref_date_is_read_from_the_dm_pin(self):
        out = (
            self.SV.sdtm.pin("DM", self.DM)
            .visit_map(
                "VISITNUM", "VISIT", date_col="SVSTDTC", planned_visits=TV, ref_date="RFSTDTC"
            )
            .to_frame()
        )
        assert out["VISITNUM"].to_list() == [3.0, 1.0]
        assert out.columns == ["USUBJID", "SVSTDTC", "VISITNUM", "VISIT"]

    def test_ref_date_typo_names_the_column(self):
        with pytest.raises(DerivationError, match="RFSTDT"):
            _map(self.SV.sdtm.pin("DM", self.DM).to_frame(), ref_date="RFSTDT")

    def test_date_col_typo_names_the_column(self):
        sv = self.SV.join(self.DM, on="USUBJID")
        with pytest.raises(DerivationError, match="SVSTDT'"):
            sv.sdtm.visit_map(
                "VISITNUM", "VISIT", date_col="SVSTDT", planned_visits=TV, ref_date="RFSTDTC"
            )

    def test_no_ref_date_and_no_visitdy_raises(self):
        with pytest.raises(DerivationError, match="VISITDY"):
            _map(self.SV, ref_date=None)


class TestTargetIsReplaced:
    """c1-221: an existing target column is replaced, with no *_right column."""

    def test_visit_map_replaces_visitnum_and_visit(self):
        sv = pl.from_repr("""
┌─────────┬────────────┬────────────┬──────────┬───────┐
│ USUBJID ┆ SVSTDTC    ┆ RFSTDTC    ┆ VISITNUM ┆ VISIT │
│ ---     ┆ ---        ┆ ---        ┆ ---      ┆ ---   │
│ str     ┆ str        ┆ str        ┆ f64      ┆ str   │
╞═════════╪════════════╪════════════╪══════════╪═══════╡
│ 01      ┆ 2014-01-24 ┆ 2014-01-10 ┆ 77.0     ┆ OLD   │
└─────────┴────────────┴────────────┴──────────┴───────┘
""")
        out = _map(sv)
        assert out.columns == ["USUBJID", "SVSTDTC", "RFSTDTC", "VISITNUM", "VISIT"]
        assert out.row(0)[-2:] == (3.0, "WEEK 2")

    def test_epoch_assign_se_replaces_epoch(self):
        ae = pl.from_repr("""
┌─────────┬────────────┬───────┐
│ USUBJID ┆ AESTDTC    ┆ EPOCH │
│ ---     ┆ ---        ┆ ---   │
│ str     ┆ str        ┆ str   │
╞═════════╪════════════╪═══════╡
│ 01      ┆ 2014-03-01 ┆ OLD   │
└─────────┴────────────┴───────┘
""")
        se = pl.from_repr("""
┌─────────┬────────────┬────────────┬───────────┐
│ USUBJID ┆ SESTDTC    ┆ SEENDTC    ┆ EPOCH     │
│ ---     ┆ ---        ┆ ---        ┆ ---       │
│ str     ┆ str        ┆ str        ┆ str       │
╞═════════╪════════════╪════════════╪═══════════╡
│ 01      ┆ 2014-01-15 ┆ 2014-04-15 ┆ TREATMENT │
└─────────┴────────────┴────────────┴───────────┘
""")
        out = ae.sdtm.epoch_assign("EPOCH", date_col="AESTDTC", se=se).to_frame()
        assert out.columns == ["USUBJID", "AESTDTC", "EPOCH"]
        assert out["EPOCH"].to_list() == ["TREATMENT"]


class TestArmSpecificVisits:
    """c1-223: a subject only takes visits of its arm or of all arms."""

    TV_ARM = pl.from_repr("""
┌──────────┬──────────┬─────────┬───────┐
│ VISITNUM ┆ VISIT    ┆ VISITDY ┆ ARMCD │
│ ---      ┆ ---      ┆ ---     ┆ ---   │
│ f64      ┆ str      ┆ i64     ┆ str   │
╞══════════╪══════════╪═════════╪═══════╡
│ 1.0      ┆ DAY 1    ┆ 1       ┆ null  │
│ 2.0      ┆ A WEEK 2 ┆ 15      ┆ A     │
│ 3.0      ┆ B WEEK 3 ┆ 22      ┆ B     │
└──────────┴──────────┴─────────┴───────┘
""")
    SV = pl.from_repr("""
┌─────────┬───────┬────────────┬────────────┐
│ USUBJID ┆ ARMCD ┆ SVSTDTC    ┆ RFSTDTC    │
│ ---     ┆ ---   ┆ ---        ┆ ---        │
│ str     ┆ str   ┆ str        ┆ str        │
╞═════════╪═══════╪════════════╪════════════╡
│ SA      ┆ A     ┆ 2014-01-30 ┆ 2014-01-10 │
│ SB      ┆ B     ┆ 2014-01-23 ┆ 2014-01-10 │
└─────────┴───────┴────────────┴────────────┘
""")

    def test_frame_path(self):
        out = self.SV.sdtm.visit_map(
            "VISITNUM", "VISIT", date_col="SVSTDTC", planned_visits=self.TV_ARM, ref_date="RFSTDTC"
        ).to_frame()
        assert out["VISIT"].to_list() == ["A WEEK 2", "B WEEK 3"]

    def test_typed_path_blank_armcd_means_all_arms(self):
        tv = TrialVisits(
            visits=[
                TrialVisit(visitnum=1, visit="DAY 1", visitdy=1),
                TrialVisit(visitnum=2, visit="A WEEK 2", visitdy=15, armcd="A"),
                TrialVisit(visitnum=3, visit="B WEEK 3", visitdy=22, armcd="B"),
            ]
        )
        out = self.SV.sdtm.visit_map(
            "VISITNUM", "VISIT", date_col="SVSTDTC", planned_visits=tv, ref_date="RFSTDTC"
        ).to_frame()
        assert out["VISITNUM"].to_list() == [2, 3]

    def test_frame_with_no_armcd_raises(self):
        with pytest.raises(DerivationError, match="ARMCD"):
            self.SV.drop("ARMCD").sdtm.visit_map(
                "VISITNUM",
                "VISIT",
                date_col="SVSTDTC",
                planned_visits=self.TV_ARM,
                ref_date="RFSTDTC",
            )


class TestUnscheduledAndWarnings:
    """c2-950 (decision C): unscheduled decimal numbers, and warnings on nulls and SV keys."""

    def test_unscheduled_numbers_follow_the_planned_visit_before(self):
        sv = pl.from_repr("""
┌────────┬─────────┬────────────┬────────────┐
│ DOMAIN ┆ USUBJID ┆ SVSTDTC    ┆ RFSTDTC    │
│ ---    ┆ ---     ┆ ---        ┆ ---        │
│ str    ┆ str     ┆ str        ┆ str        │
╞════════╪═════════╪════════════╪════════════╡
│ SV     ┆ 01      ┆ 2014-01-31 ┆ 2014-01-10 │
│ SV     ┆ 01      ┆ 2014-01-30 ┆ 2014-01-10 │
│ SV     ┆ 01      ┆ 2014-01-10 ┆ 2014-01-10 │
│ SV     ┆ 01      ┆ 2014-01-17 ┆ 2014-01-10 │
│ SV     ┆ 02      ┆ 2014-01-17 ┆ 2014-01-10 │
│ SV     ┆ 03      ┆ 2014-01-17 ┆ null       │
└────────┴─────────┴────────────┴────────────┘
""")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            out = _map(sv, tolerance={"before": 2, "after": 2})
        assert out["VISITNUM"].to_list() == [3.2, 3.1, 2.0, 2.1, 2.1, None]
        assert out["VISIT"][0] == "UNSCHEDULED 3.2" and out["VISIT"][3] == "UNSCHEDULED 2.1"
        messages = [str(w.message) for w in caught]
        assert any(
            "1 row(s) have no study day" in m and "4 row(s) are outside every window" in m
            for m in messages
        )

    def test_repeated_sv_keys_warn(self):
        sv = pl.from_repr("""
┌────────┬─────────┬────────────┬────────────┐
│ DOMAIN ┆ USUBJID ┆ SVSTDTC    ┆ RFSTDTC    │
│ ---    ┆ ---     ┆ ---        ┆ ---        │
│ str    ┆ str     ┆ str        ┆ str        │
╞════════╪═════════╪════════════╪════════════╡
│ SV     ┆ 01      ┆ 2014-01-24 ┆ 2014-01-10 │
│ SV     ┆ 01      ┆ 2014-01-25 ┆ 2014-01-10 │
└────────┴─────────┴────────────┴────────────┘
""")
        with pytest.warns(UserWarning, match="1 USUBJID \\+ VISITNUM key\\(s\\) repeat on 2 row"):
            _map(sv)


class TestElementBoundariesOrder:
    """c1-226: the next element is the next by start date, for any row order."""

    RAW = pl.from_repr("""
┌─────────┬──────┬────────────┬────────────┬────────────┐
│ USUBJID ┆ ETCD ┆ scr        ┆ trt        ┆ fu         │
│ ---     ┆ ---  ┆ ---        ┆ ---        ┆ ---        │
│ str     ┆ str  ┆ str        ┆ str        ┆ str        │
╞═════════╪══════╪════════════╪════════════╪════════════╡
│ 01      ┆ FU   ┆ 2014-01-01 ┆ 2014-01-15 ┆ 2014-04-15 │
│ 01      ┆ SCRN ┆ 2014-01-01 ┆ 2014-01-15 ┆ 2014-04-15 │
│ 01      ┆ TRT  ┆ 2014-01-01 ┆ 2014-01-15 ┆ 2014-04-15 │
│ 02      ┆ TRT  ┆ 2014-02-01 ┆ 2014-02-15 ┆ 2014-05-15 │
│ 02      ┆ SCRN ┆ 2014-02-01 ┆ 2014-02-15 ┆ 2014-05-15 │
└─────────┴──────┴────────────┴────────────┴────────────┘
""")
    EXPECTED = {
        ("01", "SCRN"): "2014-01-15",
        ("01", "TRT"): "2014-04-15",
        ("01", "FU"): None,
        ("02", "SCRN"): "2014-02-15",
        ("02", "TRT"): None,
    }

    @pytest.mark.parametrize("seed", [0, 1, 42])
    def test_any_row_order_gives_the_same_ends(self, seed):
        raw = shuffle_rows(self.RAW, seed=seed)
        out = raw.sdtm.element_boundaries(
            "SESTDTC", "SEENDTC", milestones={"SCRN": "scr", "TRT": "trt", "FU": "fu"}
        ).to_frame()
        assert out["ETCD"].to_list() == raw["ETCD"].to_list()
        got = {(u, e): end for u, e, end in out.select("USUBJID", "ETCD", "SEENDTC").iter_rows()}
        assert got == self.EXPECTED
