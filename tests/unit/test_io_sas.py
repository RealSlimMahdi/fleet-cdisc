"""SAS transport and SAS7BDAT files through ``fleet.io`` (package F of the alpha audit).

Every fixture is written by pyreadstat from a Polars frame, so no test needs
pandas or pyarrow.  Values read back from a written file are checked with
``disable_datetime_conversion=True``: the number SAS stores, not what a
reader makes of it.
"""

from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import polars as pl
import pytest

from fleet.core.exceptions import IOError as FleetIOError
from fleet.io import load_raw_data, save_xpt

pyreadstat = pytest.importorskip("pyreadstat")


@pytest.fixture
def no_pandas(monkeypatch: pytest.MonkeyPatch) -> None:
    """A clean ``io`` install: pyreadstat is there, pandas and pyarrow are not."""
    monkeypatch.setitem(sys.modules, "pandas", None)
    monkeypatch.setitem(sys.modules, "pyarrow", None)


def _write_fixture(df: pl.DataFrame, path: Path, **kwargs) -> Path:
    pyreadstat.write_xport(
        df, str(path), file_format_version=5, table_name=path.stem.upper(), **kwargs
    )
    return path


def _stored(path: Path) -> tuple[pl.DataFrame, object]:
    """The values and metadata as stored in the file, with no date conversion."""
    return pyreadstat.read_xport(
        str(path), output_format="polars", disable_datetime_conversion=True
    )


# ── Read ──────────────────────────────────────────────────────────────────────


def test_xpt_reads_on_an_io_only_install(tmp_path: Path, no_pandas: None) -> None:
    ae = pl.from_repr("""
┌─────────┬──────────┐
│ USUBJID ┆ AETERM   │
│ ---     ┆ ---      │
│ str     ┆ str      │
╞═════════╪══════════╡
│ S1      ┆ HEADACHE │
└─────────┴──────────┘
""")
    path = _write_fixture(ae, tmp_path / "ae.xpt")

    assert load_raw_data(path).collect().to_dicts() == [{"USUBJID": "S1", "AETERM": "HEADACHE"}]


def test_a_sas_blank_reads_as_null(tmp_path: Path) -> None:
    """SAS has one character missing value, the blank (admiral: convert blanks first)."""
    ae = pl.from_repr("""
┌─────────┬────────────┐
│ USUBJID ┆ AEENDTC    │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ S1      ┆ 2024-01-02 │
│ S2      ┆            │
│ S3      ┆ null       │
└─────────┴────────────┘
""")
    path = _write_fixture(ae, tmp_path / "ae.xpt")

    out = load_raw_data(path).collect()

    assert out["AEENDTC"].to_list() == ["2024-01-02", None, None]
    assert out.filter(pl.col("AEENDTC").is_not_null()).height == 1


def test_an_all_missing_variable_keeps_its_sas_type(tmp_path: Path) -> None:
    df = pl.DataFrame(
        {
            "USUBJID": ["S1", "S2"],
            "AVAL": pl.Series([None, None], dtype=pl.Float64),
            "AVALC": pl.Series([None, None], dtype=pl.String),
        }
    )
    path = _write_fixture(df, tmp_path / "adlb.xpt")

    schema = load_raw_data(path).collect_schema()

    assert schema["AVAL"] == pl.Float64
    assert schema["AVALC"] == pl.String


def test_sas_date_and_time_formats_read_as_polars_temporals(tmp_path: Path) -> None:
    df = pl.DataFrame(
        {
            "TRTSDT": [dt.date(2014, 1, 2)],
            "TRTSDTM": [dt.datetime(2014, 1, 2, 8, 30)],
            "TRTSTM": [dt.time(8, 30)],
        }
    )
    path = _write_fixture(
        df,
        tmp_path / "adsl.xpt",
        variable_format={"TRTSDT": "DATE9", "TRTSDTM": "DATETIME20", "TRTSTM": "TIME8"},
    )

    out = load_raw_data(path).collect()

    assert out.row(0) == (dt.date(2014, 1, 2), dt.datetime(2014, 1, 2, 8, 30), dt.time(8, 30))


def _latin1_xpt(tmp_path: Path) -> Path:
    """An XPT from a WLATIN1 SAS session: AETERM holds the byte 0xE9."""
    ae = pl.DataFrame({"USUBJID": ["S1"], "AETERM": ["CAFX"]})
    path = _write_fixture(ae, tmp_path / "ae.xpt")
    path.write_bytes(path.read_bytes().replace(b"CAFX", b"CAF\xe9"))
    return path


def test_a_latin1_xpt_reads_with_the_encoding_named(tmp_path: Path) -> None:
    path = _latin1_xpt(tmp_path)

    out = load_raw_data(path, encoding="iso-8859-1").collect()

    assert out["AETERM"].to_list() == ["CAFé"]


def test_a_latin1_xpt_read_as_utf8_names_the_encoding_argument(tmp_path: Path) -> None:
    path = _latin1_xpt(tmp_path)

    with pytest.raises(FleetIOError, match="encoding="):
        load_raw_data(path)


def test_an_unknown_keyword_for_a_sas_file_raises(tmp_path: Path) -> None:
    path = _write_fixture(pl.DataFrame({"USUBJID": ["S1"]}), tmp_path / "dm.xpt")

    with pytest.raises(FleetIOError, match="not_an_option"):
        load_raw_data(path, not_an_option=1)


def test_a_transport_file_with_two_members_names_them_and_stops(tmp_path: Path) -> None:
    """c1-242: PROC COPY of DM and AE into one file must not read as one table."""
    dm = pl.from_repr("""
┌─────────┬──────┐
│ USUBJID ┆ AGE  │
│ ---     ┆ ---  │
│ str     ┆ f64  │
╞═════════╪══════╡
│ 01-001  ┆ 63.0 │
└─────────┴──────┘
""")
    ae = pl.from_repr("""
┌─────────┬──────────┐
│ USUBJID ┆ AETERM   │
│ ---     ┆ ---      │
│ str     ┆ str      │
╞═════════╪══════════╡
│ 01-001  ┆ HEADACHE │
└─────────┴──────────┘
""")
    first = _write_fixture(dm, tmp_path / "dm.xpt").read_bytes()
    second = _write_fixture(ae, tmp_path / "ae.xpt").read_bytes()
    library_header = 3 * 80
    both = tmp_path / "all.xpt"
    both.write_bytes(first + second[library_header:])

    with pytest.raises(FleetIOError, match=r"all\.xpt holds 2 members \(DM, AE\)"):
        load_raw_data(both)


# ── Write ─────────────────────────────────────────────────────────────────────


def _adsl() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "STUDYID": ["CDISCPILOT01"] * 3,
            "USUBJID": ["01-701-1015", "01-701-1023", "01-701-1028"],
            "TRTSDT": [dt.date(2024, 1, 15), dt.date(1959, 12, 31), None],
            "TRTSDTM": [dt.datetime(2024, 1, 15, 8, 30), None, None],
            "TRTSTM": [dt.time(8, 30), None, None],
        }
    )


def test_save_xpt_writes_v5_with_the_file_name_as_member(tmp_path: Path, no_pandas: None) -> None:
    """FDA TCG 3.1.1: XPORT V5, and the dataset is named the same as the file."""
    path = save_xpt(_adsl(), tmp_path / "adsl.xpt")

    assert path.read_bytes()[:80].startswith(b"HEADER RECORD*******LIBRARY HEADER RECORD")
    _, meta = _stored(path)
    assert meta.table_name == "ADSL"


def test_save_xpt_stores_a_date_as_sas_days_with_date9(tmp_path: Path) -> None:
    """2024-01-15 is 23390 days after 01JAN1960, and 1959-12-31 is day -1."""
    path = save_xpt(_adsl(), tmp_path / "adsl.xpt")

    stored, meta = _stored(path)

    assert stored["TRTSDT"].to_list() == [23390.0, -1.0, None]
    assert stored["TRTSDTM"].to_list()[0] == 23390 * 86400 + 8 * 3600 + 30 * 60
    assert stored["TRTSTM"].to_list()[0] == 8 * 3600 + 30 * 60
    assert meta.original_variable_types["TRTSDT"] == "DATE9"
    assert meta.original_variable_types["TRTSDTM"] == "DATETIME20"
    assert meta.original_variable_types["TRTSTM"] == "TIME8"


def test_save_xpt_round_trip_keeps_dates_and_times(tmp_path: Path) -> None:
    path = save_xpt(_adsl(), tmp_path / "adsl.xpt")

    assert load_raw_data(path).collect().equals(_adsl())


def test_save_xpt_writes_nan_as_sas_missing(tmp_path: Path) -> None:
    """0/0 in a derivation gives NaN; SAS has no NaN, so it is missing."""
    advs = pl.DataFrame({"USUBJID": ["S1", "S2"], "PCHG": [float("nan"), 12.5]})

    stored, _ = _stored(save_xpt(advs, tmp_path / "advs.xpt"))

    assert stored["PCHG"].to_list() == [None, 12.5]


def test_save_xpt_writes_infinity_as_missing_and_warns(tmp_path: Path) -> None:
    advs = pl.DataFrame({"USUBJID": ["S1", "S2"], "PCHG": [float("inf"), 12.5]})

    with pytest.warns(UserWarning, match="PCHG"):
        stored, _ = _stored(save_xpt(advs, tmp_path / "advs.xpt"))

    assert stored["PCHG"].to_list() == [None, 12.5]


def test_save_xpt_upper_cases_names(tmp_path: Path) -> None:
    stored, _ = _stored(save_xpt(pl.DataFrame({"usubjid": ["S1"]}), tmp_path / "dm.xpt"))

    assert stored.columns == ["USUBJID"]


def test_save_xpt_refuses_a_name_over_eight_characters(tmp_path: Path) -> None:
    df = pl.DataFrame({"USUBJID": ["S1"], "LONGVARNAME": ["x"]})

    with pytest.raises(FleetIOError, match="LONGVARNAME"):
        save_xpt(df, tmp_path / "dm.xpt")
    assert not (tmp_path / "dm.xpt").exists()


def test_save_xpt_refuses_a_file_name_that_cannot_be_a_member(tmp_path: Path) -> None:
    with pytest.raises(FleetIOError, match="ADVERSE_EVENTS"):
        save_xpt(pl.DataFrame({"USUBJID": ["S1"]}), tmp_path / "adverse_events.xpt")


def test_save_xpt_refuses_a_value_over_200_bytes(tmp_path: Path) -> None:
    ae = pl.DataFrame({"USUBJID": ["S1"], "AETERM": ["A" * 201]})

    with pytest.raises(FleetIOError, match="AETERM"):
        save_xpt(ae, tmp_path / "ae.xpt")


def test_save_xpt_writes_labels(tmp_path: Path) -> None:
    path = save_xpt(
        _adsl().select("STUDYID", "USUBJID"),
        tmp_path / "adsl.xpt",
        label="Subject-Level Analysis Dataset",
        column_labels={"USUBJID": "Unique Subject Identifier"},
    )

    _, meta = _stored(path)

    assert meta.file_label == "Subject-Level Analysis Dataset"
    assert meta.column_names_to_labels["USUBJID"] == "Unique Subject Identifier"


def test_save_xpt_refuses_a_label_over_40_characters(tmp_path: Path) -> None:
    with pytest.raises(FleetIOError, match="40"):
        save_xpt(
            pl.DataFrame({"USUBJID": ["S1"]}),
            tmp_path / "dm.xpt",
            column_labels={"USUBJID": "U" * 41},
        )


def test_save_xpt_writes_a_non_ascii_value_and_warns(tmp_path: Path) -> None:
    """TCG 3.1.5 allows UTF-8 and advises against it: write the bytes, warn once."""
    ae = pl.DataFrame({"USUBJID": ["01-701-01"], "AETERM": ["Céphalée"]})

    with pytest.warns(UserWarning, match="AETERM"):
        path = save_xpt(ae, tmp_path / "ae.xpt")

    assert "Céphalée".encode() in path.read_bytes()
