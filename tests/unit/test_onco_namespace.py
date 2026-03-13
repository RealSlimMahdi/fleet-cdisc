"""Unit tests for the Oncology Polars namespace extension (df.onco)."""

import polars as pl
import pytest

import pymaverse  # noqa: F401 — triggers namespace registration


class TestAvalResp:
    def test_cr_maps_to_1(self):
        df = pl.DataFrame({"OVRLRESP": ["CR"]})
        assert df.onco.aval_resp("AVAL", source="OVRLRESP").to_frame()["AVAL"][0] == pytest.approx(1.0)

    def test_full_recist_mapping(self):
        df = pl.DataFrame({
            "OVRLRESP": ["CR", "PR", "SD", "NON-CR/NON-PD", "PD", "NE", "MISSING", "UNKNOWN"],
        })
        result = df.onco.aval_resp("AVAL", source="OVRLRESP").to_frame()
        expected = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, None]
        vals = result["AVAL"].to_list()
        for got, exp in zip(vals, expected):
            if exp is None:
                assert got is None
            else:
                assert got == pytest.approx(exp)

    def test_null_maps_to_null(self):
        df = pl.DataFrame({"R": [None]}, schema={"R": pl.Utf8})
        result = df.onco.aval_resp("N", source="R").to_frame()
        assert result["N"][0] is None


class TestTumorResponseFlag:
    def test_cr_pr_flagged_by_default(self):
        df = pl.DataFrame({"RESP": ["CR", "PR", "SD", "PD"]})
        result = df.onco.tumor_response_flag("RSPFL", source="RESP").to_frame()
        assert result["RSPFL"].to_list() == ["Y", "Y", None, None]

    def test_custom_responses(self):
        df = pl.DataFrame({"RESP": ["CR", "PR", "SD", "PD"]})
        result = df.onco.tumor_response_flag(
            "CBFL", source="RESP", responses=["CR", "PR", "SD"]
        ).to_frame()
        assert result["CBFL"].to_list() == ["Y", "Y", "Y", None]


class TestBestOverallResponse:
    def test_best_response_is_pr(self):
        df = pl.DataFrame({
            "USUBJID": ["S01", "S01", "S01"],
            "OVRLRESP": ["SD", "PR", "PD"],
        })
        result = df.onco.best_overall_response(
            "BOR", source="OVRLRESP", groups=["USUBJID"]
        ).to_frame()
        # PR is rank 2, SD=3, PD=5 → best is PR
        assert all(r == "PR" for r in result["BOR"].to_list())

    def test_no_response_gives_ne(self):
        df = pl.DataFrame({
            "USUBJID": ["S02", "S02"],
            "OVRLRESP": ["NE", "NE"],
        })
        result = df.onco.best_overall_response(
            "BOR", source="OVRLRESP", groups=["USUBJID"]
        ).to_frame()
        assert all(r == "NE" for r in result["BOR"].to_list())

    def test_multi_subject(self):
        df = pl.DataFrame({
            "USUBJID": ["S01", "S01", "S02", "S02"],
            "OVRLRESP": ["SD", "CR", "PD", "PR"],
        })
        result = df.onco.best_overall_response(
            "BOR", source="OVRLRESP", groups=["USUBJID"]
        ).to_frame()
        bor_map = dict(zip(result["USUBJID"].to_list(), result["BOR"].to_list()))
        assert bor_map["S01"] == "CR"
        assert bor_map["S02"] == "PR"


class TestFilterPD:
    def test_records_after_pd_dropped(self):
        df = pl.DataFrame({
            "USUBJID": ["S01", "S01", "S01", "S01"],
            "ADT":     ["2024-01-01", "2024-02-01", "2024-03-01", "2024-04-01"],
            "OVRLRESP": ["SD", "PD", "PD", "NE"],
        })
        result = df.onco.filter_pd(
            response_col="OVRLRESP", date_col="ADT", groups=["USUBJID"]
        ).to_frame()
        # Only rows up to and including first PD (2024-02-01)
        assert result.height == 2
        assert result["ADT"].to_list() == ["2024-01-01", "2024-02-01"]

    def test_no_pd_retains_all(self):
        df = pl.DataFrame({
            "USUBJID": ["S02", "S02"],
            "ADT":     ["2024-01-01", "2024-02-01"],
            "OVRLRESP": ["SD", "PR"],
        })
        result = df.onco.filter_pd(
            response_col="OVRLRESP", date_col="ADT", groups=["USUBJID"]
        ).to_frame()
        assert result.height == 2


class TestChaining:
    def test_full_onco_chain(self):
        df = pl.DataFrame({
            "USUBJID": ["S01", "S01", "S02"],
            "OVRLRESP": ["CR", "PD", "PR"],
        })
        result = (
            df.onco
            .aval_resp("AVAL", source="OVRLRESP")
            .tumor_response_flag("RSPFL", source="OVRLRESP")
            .best_overall_response("BOR", source="OVRLRESP", groups=["USUBJID"])
            .to_frame()
        )
        assert "AVAL" in result.columns
        assert "RSPFL" in result.columns
        assert "BOR" in result.columns
