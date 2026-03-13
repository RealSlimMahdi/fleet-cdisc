"""Unit tests for the Vaccine Polars namespace extension (df.vaccine)."""

import polars as pl
import pytest

import pymaverse  # noqa: F401 — triggers namespace registration


class TestFeverFlag:
    def test_above_threshold_flagged(self):
        df = pl.DataFrame({"TEMP": [37.0, 38.1, 39.0, 38.0]})
        result = df.vaccine.fever_flag("FEVFL", temp_col="TEMP").to_frame()
        # > 38.0, not >=
        assert result["FEVFL"].to_list() == [None, "Y", "Y", None]

    def test_custom_threshold(self):
        df = pl.DataFrame({"TEMP": [39.0, 39.5, 40.0]})
        result = df.vaccine.fever_flag(
            "HIGHFL", temp_col="TEMP", threshold=39.0
        ).to_frame()
        assert result["HIGHFL"].to_list() == [None, "Y", "Y"]


class TestSeroconversionFlag:
    def test_fourfold_rise_flagged(self):
        # 400/100 = 4.0 >= 4.0 → "Y"; 1600/100 = 16.0 >= 4.0 → "Y"; 300/100 = 3.0 < 4.0 → null
        df = pl.DataFrame({
            "AVAL": [400.0, 1600.0, 300.0],
            "BASE": [100.0, 100.0,  100.0],
        })
        result = df.vaccine.seroconversion_flag(
            "SRCONVFL", aval_col="AVAL", base_col="BASE"
        ).to_frame()
        assert result["SRCONVFL"].to_list() == ["Y", "Y", None]

    def test_zero_base_gives_null(self):
        df = pl.DataFrame({"AVAL": [100.0], "BASE": [0.0]})
        result = df.vaccine.seroconversion_flag(
            "SRCONVFL", aval_col="AVAL", base_col="BASE"
        ).to_frame()
        assert result["SRCONVFL"][0] is None

    def test_custom_fold_rise(self):
        df = pl.DataFrame({
            "AVAL": [200.0, 300.0],
            "BASE": [100.0, 100.0],
        })
        result = df.vaccine.seroconversion_flag(
            "SRCONV2FL", aval_col="AVAL", base_col="BASE", fold_rise=2.0
        ).to_frame()
        assert result["SRCONV2FL"].to_list() == ["Y", "Y"]


class TestSeroresponseFlag:
    def test_above_threshold(self):
        df = pl.DataFrame({"AVAL": [30.0, 40.0, 50.0]})
        result = df.vaccine.seroresponse_flag(
            "SRSFL", aval_col="AVAL", threshold=40.0
        ).to_frame()
        assert result["SRSFL"].to_list() == [None, "Y", "Y"]


class TestAvalAdis:
    def test_below_lloq_gives_half(self):
        df = pl.DataFrame({
            "ISSTRESN": [1.0],
            "ISLLOQ":   [4.0],
            "ISULOQ":   [200.0],
            "ISORRES":  ["1"],
        })
        result = df.vaccine.aval_adis(
            "AVAL",
            stresn_col="ISSTRESN", lloq_col="ISLLOQ",
            uloq_col="ISULOQ", orres_col="ISORRES"
        ).to_frame()
        assert result["AVAL"][0] == pytest.approx(2.0)   # 4/2

    def test_in_range_gives_stresn(self):
        df = pl.DataFrame({
            "ISSTRESN": [50.0],
            "ISLLOQ":   [4.0],
            "ISULOQ":   [200.0],
            "ISORRES":  ["50"],
        })
        result = df.vaccine.aval_adis(
            "AVAL",
            stresn_col="ISSTRESN", lloq_col="ISLLOQ",
            uloq_col="ISULOQ", orres_col="ISORRES"
        ).to_frame()
        assert result["AVAL"][0] == pytest.approx(50.0)

    def test_above_uloq_gives_uloq(self):
        df = pl.DataFrame({
            "ISSTRESN": [250.0],
            "ISLLOQ":   [4.0],
            "ISULOQ":   [200.0],
            "ISORRES":  ["250"],
        })
        result = df.vaccine.aval_adis(
            "AVAL",
            stresn_col="ISSTRESN", lloq_col="ISLLOQ",
            uloq_col="ISULOQ", orres_col="ISORRES"
        ).to_frame()
        assert result["AVAL"][0] == pytest.approx(200.0)

    def test_missing_stresn_gt_orres(self):
        df = pl.DataFrame({
            "ISSTRESN": [None],
            "ISLLOQ":   [4.0],
            "ISULOQ":   [200.0],
            "ISORRES":  [">200"],
        })
        result = df.vaccine.aval_adis(
            "AVAL",
            stresn_col="ISSTRESN", lloq_col="ISLLOQ",
            uloq_col="ISULOQ", orres_col="ISORRES"
        ).to_frame()
        assert result["AVAL"][0] == pytest.approx(200.0)

    def test_missing_stresn_null_orres_gives_null(self):
        df = pl.DataFrame({
            "ISSTRESN": [None],
            "ISLLOQ":   [4.0],
            "ISULOQ":   [200.0],
            "ISORRES":  [None],
        })
        result = df.vaccine.aval_adis(
            "AVAL",
            stresn_col="ISSTRESN", lloq_col="ISLLOQ",
            uloq_col="ISULOQ", orres_col="ISORRES"
        ).to_frame()
        assert result["AVAL"][0] is None


class TestEventFlag:
    def test_group_event_flag(self):
        df = pl.DataFrame({
            "USUBJID": ["S01", "S01", "S01"],
            "FAOBJ":   ["REDNESS", "REDNESS", "REDNESS"],
            "ATPTREF": ["VAC1", "VAC1", "VAC1"],
            "AVAL":    [3.5, 1.0, 4.5],
            "AVALC":   ["3.5", "1.0", "4.5"],
        })
        result = df.vaccine.event_flag(
            "EVENTFL", aval_col="AVAL", cutoff=2.5,
            groups=["USUBJID", "FAOBJ", "ATPTREF"]
        ).to_frame()
        # Event occurred (> 2.5) at least once → all rows flagged "Y"
        assert all(f == "Y" for f in result["EVENTFL"].to_list())

    def test_no_event_gives_N(self):
        df = pl.DataFrame({
            "USUBJID": ["S02", "S02"],
            "FAOBJ":   ["PAIN", "PAIN"],
            "ATPTREF": ["VAC1", "VAC1"],
            "AVAL":    [1.0, 2.0],
            "AVALC":   ["1.0", "2.0"],
        })
        result = df.vaccine.event_flag(
            "EVENTFL", aval_col="AVAL", cutoff=2.5,
            groups=["USUBJID", "FAOBJ", "ATPTREF"]
        ).to_frame()
        assert all(f == "N" for f in result["EVENTFL"].to_list())
