"""CSV files hold no variable type: what Fleet decides, and when it warns (c1-237)."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from fleet.io import load_raw_data


def _csv(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_a_column_with_a_leading_zero_reads_as_text_and_warns(tmp_path: Path) -> None:
    path = _csv(tmp_path / "dm.csv", "SUBJID,SITEID,AGE\n0012,701,45\n0013,702,60\n")

    with pytest.warns(UserWarning, match="SUBJID"):
        dm = load_raw_data(path).collect()

    assert dm["SUBJID"].to_list() == ["0012", "0013"]
    assert dm.schema["AGE"] == pl.Int64


def test_a_text_value_late_in_the_file_does_not_stop_the_read(tmp_path: Path) -> None:
    rows = "".join(f"S{i},{i}\n" for i in range(200))
    path = _csv(tmp_path / "lb.csv", f"USUBJID,LBORRES\n{rows}S999,ABC\n")

    lb = load_raw_data(path).collect()

    assert lb.schema["LBORRES"] == pl.String
    assert lb["LBORRES"].to_list()[-1] == "ABC"


def test_the_callers_schema_overrides_win(tmp_path: Path) -> None:
    path = _csv(tmp_path / "dm.csv", "SUBJID,AGE\n0012,45\n")

    dm = load_raw_data(path, schema_overrides={"SUBJID": pl.Int64, "AGE": pl.String}).collect()

    assert dm.row(0) == (12, "45")


def test_a_latin1_csv_reads_with_the_encoding_named(tmp_path: Path) -> None:
    path = tmp_path / "ae.csv"
    path.write_bytes("USUBJID,AETERM\nS1,CAF\xe9\n".encode("latin-1"))

    ae = load_raw_data(path, encoding="iso-8859-1").collect()

    assert ae["AETERM"].to_list() == ["CAFé"]


def test_a_nan_cell_reads_as_null_so_a_threshold_flag_is_null(tmp_path: Path) -> None:
    """c1-423: SAS has no NaN; a missing value is never above a threshold."""
    path = tmp_path / "face.csv"
    path.write_text("USUBJID,AVAL\nA,NaN\nB,\nC,37.0\nD,38.5\n")

    face = load_raw_data(path).collect()
    out = face.adam.vaccine.fever_flag("FEVFL", temp_col="AVAL").to_frame()

    assert face["AVAL"].to_list() == [None, None, 37.0, 38.5]
    assert out["FEVFL"].to_list() == [None, None, None, "Y"]
