"""Files that another tool wrote, read through ``fleet.io`` (c2-972).

Every other IO test reads a file that Fleet or pyreadstat wrote from a
Polars frame. These read the CDISCPILOT01 trial design XPT files that SAS
wrote and the CDISC Dataset-JSON example ADSL. Sources and licences:
``tests/fixtures/real/SOURCES.txt``. The expected values are the header row
counts and cells read in the files.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from fleet.core.exceptions import IOError as FleetIOError
from fleet.io import load_raw_data

REAL = Path(__file__).parents[1] / "fixtures" / "real"

pytest.importorskip("pyreadstat")


def _load(name: str, **kwargs):
    frame = load_raw_data(REAL / name, **kwargs)
    return frame.collect() if hasattr(frame, "collect") else frame


def test_a_windows_1252_xpt_names_the_encoding_argument():
    # TSVAL holds a typographic apostrophe, byte 0x92 in Windows-1252.
    with pytest.raises(FleetIOError, match="encoding="):
        _load("ts.xpt")


def test_ts_xpt_reads_with_its_encoding():
    ts = _load("ts.xpt", encoding="windows-1252")

    assert ts.shape == (33, 6)
    assert ts.columns == ["STUDYID", "DOMAIN", "TSSEQ", "TSPARMCD", "TSPARM", "TSVAL"]
    assert ts.row(2) == (
        "CDISCPILOT01",
        "TS",
        1.0,
        "AGEMIN",
        "Planned Minimum Age of Subjects",
        "50 years",
    )
    assert "Mild to Moderate Alzheimer\u2019s Disease" in ts["TSVAL"].to_list()


def test_te_xpt_reads_text_and_missing_values():
    te = _load("te.xpt")

    assert te.shape == (7, 7)
    assert te["ETCD"].to_list()[:4] == ["FOLO", "HIE", "HIM", "HIS"]
    assert te.row(1)[-2:] == (None, "P2W")


def test_tv_xpt_keeps_decimal_visit_numbers_and_missing_days():
    tv = _load("tv.xpt")

    assert tv.shape == (21, 9)
    assert tv["VISITNUM"].to_list()[:6] == [1.0, 2.0, 3.0, 3.5, 4.0, 5.0]
    assert tv.filter(tv["VISITNUM"] == 101.0)["VISITDY"].to_list() == [None]
    assert tv.filter(tv["VISITNUM"] == 8.1)["VISIT"].to_list() == ["WEEK 10 (T)"]


def test_the_cdisc_dataset_json_adsl_reads():
    adsl = _load("adsl.json")

    assert adsl.shape == (254, 49)
    assert adsl.select("USUBJID", "AGE", "TRT01A", "TRTSDT", "SAFFL").row(0) == (
        "01-701-1015",
        63,
        "Placebo",
        dt.date(2014, 1, 2),
        "Y",
    )
    assert adsl["TRT01A"].value_counts().sort("TRT01A").rows() == [
        ("Placebo", 86),
        ("Xanomeline High Dose", 84),
        ("Xanomeline Low Dose", 84),
    ]
