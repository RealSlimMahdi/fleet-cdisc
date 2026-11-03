"""Alpha audit package C: baseline_flag results and ties, flag last with where, qtc units."""

from __future__ import annotations

import polars as pl
import pytest

import fleet  # noqa: F401
from fleet.adam.utils import qtc
from fleet.core.exceptions import DerivationError

# ── baseline_flag: only a record with a result (c1-99) ────────────────────────


def test_baseline_skips_a_not_done_record_on_the_last_date() -> None:
    vs = pl.from_repr("""\
┌─────────┬──────────┬────────────┬─────────┬──────────┬────────────┐
│ USUBJID ┆ VSTESTCD ┆ VSDTC      ┆ VSORRES ┆ VSSTAT   ┆ RFSTDTC    │
│ ---     ┆ ---      ┆ ---        ┆ ---     ┆ ---      ┆ ---        │
│ str     ┆ str      ┆ str        ┆ str     ┆ str      ┆ str        │
╞═════════╪══════════╪════════════╪═════════╪══════════╪════════════╡
│ S4      ┆ SYSBP    ┆ 2014-01-05 ┆ 150     ┆ null     ┆ 2014-01-10 │
│ S4      ┆ SYSBP    ┆ 2014-01-09 ┆ null    ┆ NOT DONE ┆ 2014-01-10 │
└─────────┴──────────┴────────────┴─────────┴──────────┴────────────┘
""")

    out = vs.sdtm.baseline_flag("VSBLFL", date_col="VSDTC", testcd_col="VSTESTCD").to_frame()

    assert out["VSBLFL"].to_list() == ["Y", None]


def test_baseline_is_null_when_every_record_is_not_done() -> None:
    vs = pl.from_repr("""\
┌─────────┬──────────┬────────────┬─────────┬──────────┬────────────┐
│ USUBJID ┆ VSTESTCD ┆ VSDTC      ┆ VSORRES ┆ VSSTAT   ┆ RFSTDTC    │
│ ---     ┆ ---      ┆ ---        ┆ ---     ┆ ---      ┆ ---        │
│ str     ┆ str      ┆ str        ┆ str     ┆ str      ┆ str        │
╞═════════╪══════════╪════════════╪═════════╪══════════╪════════════╡
│ S4      ┆ SYSBP    ┆ 2014-01-05 ┆ null    ┆ NOT DONE ┆ 2014-01-10 │
│ S4      ┆ SYSBP    ┆ 2014-01-09 ┆ null    ┆ NOT DONE ┆ 2014-01-10 │
└─────────┴──────────┴────────────┴─────────┴──────────┴────────────┘
""")

    out = vs.sdtm.baseline_flag("VSBLFL", date_col="VSDTC", testcd_col="VSTESTCD").to_frame()

    assert out["VSBLFL"].to_list() == [None, None]


def test_baseline_skips_a_blank_result() -> None:
    vs = pl.from_repr("""\
┌─────────┬──────────┬────────────┬─────────┬────────────┐
│ USUBJID ┆ VSTESTCD ┆ VSDTC      ┆ VSORRES ┆ RFSTDTC    │
│ ---     ┆ ---      ┆ ---        ┆ ---     ┆ ---        │
│ str     ┆ str      ┆ str        ┆ str     ┆ str        │
╞═════════╪══════════╪════════════╪═════════╪════════════╡
│ S4      ┆ SYSBP    ┆ 2014-01-05 ┆ 150     ┆ 2014-01-10 │
│ S4      ┆ SYSBP    ┆ 2014-01-09 ┆         ┆ 2014-01-10 │
└─────────┴──────────┴────────────┴─────────┴────────────┘
""")

    out = vs.sdtm.baseline_flag("VSBLFL", date_col="VSDTC", testcd_col="VSTESTCD").to_frame()

    assert out["VSBLFL"].to_list() == ["Y", None]


def test_baseline_takes_the_result_when_a_not_done_record_has_the_same_date() -> None:
    vs = pl.from_repr("""\
┌─────────┬──────────┬────────────┬─────────┬──────────┬───────┬────────────┐
│ USUBJID ┆ VSTESTCD ┆ VSDTC      ┆ VSORRES ┆ VSSTAT   ┆ VSSEQ ┆ RFSTDTC    │
│ ---     ┆ ---      ┆ ---        ┆ ---     ┆ ---      ┆ ---   ┆ ---        │
│ str     ┆ str      ┆ str        ┆ str     ┆ str      ┆ i64   ┆ str        │
╞═════════╪══════════╪════════════╪═════════╪══════════╪═══════╪════════════╡
│ S8      ┆ SYSBP    ┆ 2014-01-09 ┆ 140     ┆ null     ┆ 1     ┆ 2014-01-10 │
│ S8      ┆ SYSBP    ┆ 2014-01-09 ┆ null    ┆ NOT DONE ┆ 2     ┆ 2014-01-10 │
└─────────┴──────────┴────────────┴─────────┴──────────┴───────┴────────────┘
""")

    out = vs.sdtm.baseline_flag("VSBLFL", date_col="VSDTC", testcd_col="VSTESTCD").to_frame()

    assert out["VSBLFL"].to_list() == ["Y", None]


def test_baseline_reads_stresc_before_orres() -> None:
    lb = pl.from_repr("""\
┌─────────┬──────────┬────────────┬─────────┬──────────┬────────────┐
│ USUBJID ┆ LBTESTCD ┆ LBDTC      ┆ LBORRES ┆ LBSTRESC ┆ RFSTDTC    │
│ ---     ┆ ---      ┆ ---        ┆ ---     ┆ ---      ┆ ---        │
│ str     ┆ str      ┆ str        ┆ str     ┆ str      ┆ str        │
╞═════════╪══════════╪════════════╪═════════╪══════════╪════════════╡
│ S5      ┆ ALT      ┆ 2014-01-05 ┆ 30      ┆ 30       ┆ 2014-01-10 │
│ S5      ┆ ALT      ┆ 2014-01-09 ┆ 31      ┆ null     ┆ 2014-01-10 │
└─────────┴──────────┴────────────┴─────────┴──────────┴────────────┘
""")

    out = lb.sdtm.baseline_flag("LBBLFL", date_col="LBDTC", testcd_col="LBTESTCD").to_frame()

    assert out["LBBLFL"].to_list() == ["Y", None]


def test_baseline_keeps_a_derived_record_with_no_orres() -> None:
    eg = pl.from_repr("""\
┌─────────┬──────────┬────────────┬─────────┬──────────┬─────────┬────────────┐
│ USUBJID ┆ EGTESTCD ┆ EGDTC      ┆ EGORRES ┆ EGSTRESC ┆ EGDRVFL ┆ RFSTDTC    │
│ ---     ┆ ---      ┆ ---        ┆ ---     ┆ ---      ┆ ---     ┆ ---        │
│ str     ┆ str      ┆ str        ┆ str     ┆ str      ┆ str     ┆ str        │
╞═════════╪══════════╪════════════╪═════════╪══════════╪═════════╪════════════╡
│ S6      ┆ QTCF     ┆ 2014-01-05 ┆ 410     ┆ 410      ┆ null    ┆ 2014-01-10 │
│ S6      ┆ QTCF     ┆ 2014-01-09 ┆ null    ┆ 415      ┆ Y       ┆ 2014-01-10 │
│ S6      ┆ QTCF     ┆ 2014-01-08 ┆ null    ┆ 412      ┆ null    ┆ 2014-01-10 │
└─────────┴──────────┴────────────┴─────────┴──────────┴─────────┴────────────┘
""")

    out = eg.sdtm.baseline_flag("EGBLFL", date_col="EGDTC", testcd_col="EGTESTCD").to_frame()

    assert out["EGBLFL"].to_list() == [None, "Y", None]


def test_baseline_reads_a_numeric_result_column() -> None:
    vs = pl.from_repr("""\
┌─────────┬──────────┬────────────┬──────────┬────────────┐
│ USUBJID ┆ VSTESTCD ┆ VSDTC      ┆ VSSTRESN ┆ RFSTDTC    │
│ ---     ┆ ---      ┆ ---        ┆ ---      ┆ ---        │
│ str     ┆ str      ┆ str        ┆ f64      ┆ str        │
╞═════════╪══════════╪════════════╪══════════╪════════════╡
│ S4      ┆ SYSBP    ┆ 2014-01-05 ┆ 150.0    ┆ 2014-01-10 │
│ S4      ┆ SYSBP    ┆ 2014-01-09 ┆ null     ┆ 2014-01-10 │
└─────────┴──────────┴────────────┴──────────┴────────────┘
""")

    out = vs.sdtm.baseline_flag(
        "VSBLFL", date_col="VSDTC", testcd_col="VSTESTCD", result_col="VSSTRESN"
    ).to_frame()

    assert out["VSBLFL"].to_list() == ["Y", None]


def test_baseline_with_no_result_column_raises() -> None:
    vs = pl.from_repr("""\
┌─────────┬──────────┬────────────┬────────────┐
│ USUBJID ┆ VSTESTCD ┆ VSDTC      ┆ RFSTDTC    │
│ ---     ┆ ---      ┆ ---        ┆ ---        │
│ str     ┆ str      ┆ str        ┆ str        │
╞═════════╪══════════╪════════════╪════════════╡
│ S4      ┆ SYSBP    ┆ 2014-01-05 ┆ 2014-01-10 │
└─────────┴──────────┴────────────┴────────────┘
""")

    with pytest.raises(DerivationError, match="result_col="):
        vs.sdtm.baseline_flag("VSBLFL", date_col="VSDTC", testcd_col="VSTESTCD")


# ── baseline_flag: one record on a tie (c1-99, Q1 A) ──────────────────────────


def test_baseline_tie_takes_the_last_seq_with_a_warning() -> None:
    eg = pl.from_repr("""\
┌──────────────┬──────────┬────────────┬──────────┬───────┬────────────┐
│ USUBJID      ┆ EGTESTCD ┆ EGDTC      ┆ EGSTRESC ┆ EGSEQ ┆ RFSTDTC    │
│ ---          ┆ ---      ┆ ---        ┆ ---      ┆ ---   ┆ ---        │
│ str          ┆ str      ┆ str        ┆ str      ┆ i64   ┆ str        │
╞══════════════╪══════════╪════════════╪══════════╪═══════╪════════════╡
│ 01-701-1015  ┆ QTCF     ┆ 2014-01-01 ┆ 420      ┆ 4     ┆ 2014-01-02 │
│ 01-701-1015  ┆ QTCF     ┆ 2014-01-01 ┆ 418      ┆ 3     ┆ 2014-01-02 │
└──────────────┴──────────┴────────────┴──────────┴───────┴────────────┘
""")

    with pytest.warns(UserWarning, match="EGSEQ"):
        out = eg.sdtm.baseline_flag("EGBLFL", date_col="EGDTC", testcd_col="EGTESTCD").to_frame()

    assert out["EGBLFL"].to_list() == ["Y", None]


def test_baseline_tie_follows_order_by() -> None:
    eg = pl.from_repr("""\
┌─────────┬──────────┬────────────┬──────────┬───────┬──────────┬────────────┐
│ USUBJID ┆ EGTESTCD ┆ EGDTC      ┆ EGSTRESC ┆ EGSEQ ┆ EGREPNUM ┆ RFSTDTC    │
│ ---     ┆ ---      ┆ ---        ┆ ---      ┆ ---   ┆ ---      ┆ ---        │
│ str     ┆ str      ┆ str        ┆ str      ┆ i64   ┆ i64      ┆ str        │
╞═════════╪══════════╪════════════╪══════════╪═══════╪══════════╪════════════╡
│ S1      ┆ QTCF     ┆ 2014-01-01 ┆ 420      ┆ 1     ┆ 3        ┆ 2014-01-02 │
│ S1      ┆ QTCF     ┆ 2014-01-01 ┆ 418      ┆ 2     ┆ 1        ┆ 2014-01-02 │
└─────────┴──────────┴────────────┴──────────┴───────┴──────────┴────────────┘
""")

    out = eg.sdtm.baseline_flag(
        "EGBLFL", date_col="EGDTC", testcd_col="EGTESTCD", order_by="EGREPNUM"
    ).to_frame()

    assert out["EGBLFL"].to_list() == ["Y", None]


def test_baseline_tie_with_no_seq_takes_the_last_input_record() -> None:
    eg = pl.from_repr("""\
┌─────────┬──────────┬────────────┬──────────┬────────────┐
│ USUBJID ┆ EGTESTCD ┆ EGDTC      ┆ EGSTRESC ┆ RFSTDTC    │
│ ---     ┆ ---      ┆ ---        ┆ ---      ┆ ---        │
│ str     ┆ str      ┆ str        ┆ str      ┆ str        │
╞═════════╪══════════╪════════════╪══════════╪════════════╡
│ S1      ┆ QTCF     ┆ 2014-01-01 ┆ 420      ┆ 2014-01-02 │
│ S1      ┆ QTCF     ┆ 2014-01-01 ┆ 418      ┆ 2014-01-02 │
└─────────┴──────────┴────────────┴──────────┴────────────┘
""")

    with pytest.warns(UserWarning, match="order_by="):
        out = eg.sdtm.baseline_flag("EGBLFL", date_col="EGDTC", testcd_col="EGTESTCD").to_frame()

    assert out["EGBLFL"].to_list() == [None, "Y"]


# ── flag last with where on a tie (c2-937) ────────────────────────────────────


def test_flag_last_ignores_a_tied_record_that_fails_where() -> None:
    adeg = pl.from_repr("""\
┌─────────┬─────────┬────────────┬─────────┬───────┐
│ USUBJID ┆ PARAMCD ┆ ADT        ┆ DTYPE   ┆ AVAL  │
│ ---     ┆ ---     ┆ ---        ┆ ---     ┆ ---   │
│ str     ┆ str     ┆ date       ┆ str     ┆ f64   │
╞═════════╪═════════╪════════════╪═════════╪═══════╡
│ S1      ┆ QTCF    ┆ 2014-01-01 ┆ null    ┆ 410.0 │
│ S1      ┆ QTCF    ┆ 2014-01-01 ┆ null    ┆ 412.0 │
│ S1      ┆ QTCF    ┆ 2014-01-01 ┆ null    ┆ 414.0 │
│ S1      ┆ QTCF    ┆ 2014-01-01 ┆ AVERAGE ┆ 412.0 │
└─────────┴─────────┴────────────┴─────────┴───────┘
""")

    out = adeg.adam.flag(
        "ABLFL",
        criteria="last",
        order_by="ADT",
        by=["USUBJID", "PARAMCD"],
        where=pl.col("DTYPE") == "AVERAGE",
    ).to_frame()

    assert out["ABLFL"].to_list() == [None, None, None, "Y"]


def test_flag_last_with_where_keeps_base_and_chg() -> None:
    advs = pl.from_repr("""\
┌─────────┬─────────┬────────────┬─────────┬───────┐
│ USUBJID ┆ PARAMCD ┆ ADT        ┆ ATPT    ┆ AVAL  │
│ ---     ┆ ---     ┆ ---        ┆ ---     ┆ ---   │
│ str     ┆ str     ┆ date       ┆ str     ┆ f64   │
╞═════════╪═════════╪════════════╪═════════╪═══════╡
│ S1      ┆ SYSBP   ┆ 2014-01-02 ┆ PREDOSE ┆ 130.0 │
│ S1      ┆ SYSBP   ┆ 2014-01-02 ┆ POST1H  ┆ 125.0 │
│ S2      ┆ SYSBP   ┆ 2014-01-03 ┆ PREDOSE ┆ 150.0 │
│ S2      ┆ SYSBP   ┆ 2014-01-03 ┆ POST1H  ┆ 135.0 │
└─────────┴─────────┴────────────┴─────────┴───────┘
""")

    out = (
        advs.adam.flag(
            "ABLFL",
            criteria="last",
            order_by="ADT",
            by=["USUBJID", "PARAMCD"],
            where=pl.col("ATPT") == "PREDOSE",
        )
        .baseline("BASE", aval="AVAL", baseline_flag="ABLFL")
        .chg("CHG", aval="AVAL", base="BASE")
        .to_frame()
    )

    assert out["ABLFL"].to_list() == ["Y", None, "Y", None]
    assert out["BASE"].to_list() == [130.0, 130.0, 150.0, 150.0]
    assert out["CHG"].to_list() == [0.0, -5.0, 0.0, -15.0]


@pytest.mark.parametrize(("criteria", "expected"), [("last", [None, "Y"]), ("first", ["Y", None])])
def test_flag_tie_with_no_where_follows_input_order(criteria: str, expected: list) -> None:
    advs = pl.from_repr("""\
┌─────────┬────────────┬───────┐
│ USUBJID ┆ ADT        ┆ AVAL  │
│ ---     ┆ ---        ┆ ---   │
│ str     ┆ date       ┆ f64   │
╞═════════╪════════════╪═══════╡
│ S1      ┆ 2014-01-01 ┆ 120.0 │
│ S1      ┆ 2014-01-01 ┆ 125.0 │
└─────────┴────────────┴───────┘
""")

    out = advs.adam.flag("ANL01FL", criteria=criteria, order_by="ADT").to_frame()

    assert out["ANL01FL"].to_list() == expected


def test_flag_mask_grid_gives_one_flag_on_the_right_record() -> None:
    """Every eligibility mask over 2 dates x 2 records: SAS LAST./FIRST. after a WHERE."""
    dates = ["2014-01-01", "2014-01-01", "2014-01-02", "2014-01-02"]
    for mask in range(1, 16):
        keep = [bool(mask >> i & 1) for i in range(4)]
        frame = pl.DataFrame({"USUBJID": ["S1"] * 4, "ADT": dates, "KEEP": keep}).with_columns(
            pl.col("ADT").str.to_date()
        )
        eligible = [i for i in range(4) if keep[i]]
        for criteria, want in (("last", eligible[-1]), ("first", eligible[0])):
            out = frame.adam.flag(
                "FL", criteria=criteria, order_by="ADT", where=pl.col("KEEP")
            ).to_frame()
            flags = out["FL"].to_list()
            assert flags == ["Y" if i == want else None for i in range(4)], (mask, criteria)


def test_flag_all_ignores_a_later_record_that_fails_where() -> None:
    advs = pl.from_repr("""\
┌─────────┬────────────┬─────────┐
│ USUBJID ┆ ADT        ┆ ATPT    │
│ ---     ┆ ---        ┆ ---     │
│ str     ┆ date       ┆ str     │
╞═════════╪════════════╪═════════╡
│ S1      ┆ 2014-01-01 ┆ PREDOSE │
│ S1      ┆ 2014-01-01 ┆ PREDOSE │
│ S1      ┆ 2014-01-02 ┆ POST1H  │
└─────────┴────────────┴─────────┘
""")

    out = advs.adam.flag(
        "ABLFL",
        criteria="last",
        order_by="ADT",
        where=pl.col("ATPT") == "PREDOSE",
        flag_all=True,
    ).to_frame()

    assert out["ABLFL"].to_list() == ["Y", "Y", None]


# ── qtc: RR unit (c1-75, Q2 A) ────────────────────────────────────────────────

ECG = """\
┌─────────┬───────┬───────┐
│ USUBJID ┆ QT    ┆ RR    │
│ ---     ┆ ---   ┆ ---   │
│ str     ┆ f64   ┆ f64   │
╞═════════╪═══════╪═══════╡
│ S001    ┆ 400.0 ┆ 800.0 │
│ S002    ┆ 350.0 ┆ 857.0 │
└─────────┴───────┴───────┘
"""


@pytest.mark.parametrize(
    ("method", "expected"), [("Fridericia", [430.89, 368.47]), ("Bazett", [447.21, 378.07])]
)
def test_qtc_reads_rr_in_ms_by_default(method: str, expected: list[float]) -> None:
    out = pl.from_repr(ECG).adam.qtc("QTC", qt="QT", rr="RR", method=method).to_frame()

    assert out["QTC"].to_list() == expected


@pytest.mark.parametrize("unit", ["s", "sec", "S"])
def test_qtc_reads_rr_in_seconds_when_stated(unit: str) -> None:
    ecg = pl.from_repr(ECG).with_columns(pl.col("RR") / 1000)

    out = ecg.adam.qtc("QTCF", qt="QT", rr="RR", rr_unit=unit).to_frame()

    assert out["QTCF"].to_list() == [430.89, 368.47]


def test_qtc_accepts_msec() -> None:
    out = pl.from_repr(ECG).adam.qtc("QTCF", rr_unit="msec").to_frame()

    assert out["QTCF"].to_list() == [430.89, 368.47]


def test_qtc_stops_on_seconds_data_with_the_default_unit() -> None:
    ecg = pl.from_repr(ECG).with_columns(pl.col("RR") / 1000)

    with pytest.raises(DerivationError, match="rr_unit"):
        ecg.adam.qtc("QTCF", qt="QT", rr="RR")


def test_qtc_stops_on_mixed_units() -> None:
    ecg = pl.from_repr(ECG).with_columns(
        pl.when(pl.col("USUBJID") == "S002").then(0.857).otherwise(pl.col("RR")).alias("RR")
    )

    with pytest.raises(DerivationError, match="rr_unit"):
        ecg.adam.qtc("QTCF", qt="QT", rr="RR")


def test_qtc_stops_on_qt_in_seconds() -> None:
    ecg = pl.from_repr(ECG).with_columns(pl.col("QT") / 1000)

    with pytest.raises(DerivationError, match="QT"):
        ecg.adam.qtc("QTCF", qt="QT", rr="RR")


def test_qtc_null_rr_gives_null_without_a_stop() -> None:
    ecg = pl.from_repr(ECG).with_columns(
        pl.when(pl.col("USUBJID") == "S002").then(None).otherwise(pl.col("RR")).alias("RR")
    )

    out = ecg.adam.qtc("QTCF", qt="QT", rr="RR").to_frame()

    assert out["QTCF"].to_list() == [430.89, None]


def test_qtc_unknown_unit_raises() -> None:
    with pytest.raises(DerivationError, match="rr_unit"):
        pl.from_repr(ECG).select(qtc("QT", "RR", rr_unit="min"))
