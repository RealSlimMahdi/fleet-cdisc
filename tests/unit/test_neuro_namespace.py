"""Unit tests for the Neuroscience Polars namespace extension (df.neuro)."""

import polars as pl
import pytest

import pymaverse  # noqa: F401 — triggers namespace registration


class TestCentiloid:
    def test_custom_slope_intercept(self):
        # Centiloid = 183.07 * 1.25 − 177.26 = 228.8375 − 177.26 = 51.5775
        df = pl.DataFrame({"SUVR": [1.25]})
        result = df.neuro.centiloid(
            "CLV", suvr_col="SUVR", slope=183.07, intercept=-177.26
        ).to_frame()
        assert result["CLV"][0] == pytest.approx(183.07 * 1.25 - 177.26, abs=0.01)

    def test_predefined_florbetapir_avid(self):
        df = pl.DataFrame({"SUVR": [1.0]})
        result = df.neuro.centiloid(
            "CLV", suvr_col="SUVR",
            tracer="18F-Florbetapir",
            pipeline="AVID FBP SUVR PIPELINE",
        ).to_frame()
        # slope=183.07, intercept=-177.26 → 183.07*1.0 − 177.26 = 5.81
        assert result["CLV"][0] == pytest.approx(183.07 - 177.26, abs=0.01)

    def test_predefined_florbetaben_berkeley(self):
        df = pl.DataFrame({"SUVR": [1.5]})
        result = df.neuro.centiloid(
            "CLV", suvr_col="SUVR",
            tracer="18F-Florbetaben",
            pipeline="BERKELEY FBB SUVR PIPELINE",
        ).to_frame()
        # slope=157.15, intercept=-151.87
        expected = 157.15 * 1.5 - 151.87
        assert result["CLV"][0] == pytest.approx(expected, abs=0.01)

    def test_unknown_combination_raises(self):
        df = pl.DataFrame({"SUVR": [1.0]})
        with pytest.raises(ValueError, match="No calibration found"):
            df.neuro.centiloid(
                "CLV", suvr_col="SUVR",
                tracer="MyTracer", pipeline="MyPipeline"
            ).to_frame()

    def test_no_params_raises(self):
        df = pl.DataFrame({"SUVR": [1.0]})
        with pytest.raises(ValueError, match="slope"):
            df.neuro.centiloid("CLV", suvr_col="SUVR").to_frame()


class TestMmseCategory:
    def test_normal(self):
        df = pl.DataFrame({"MMSE": [30, 27]})
        result = df.neuro.mmse_category("MMSECG", score_col="MMSE").to_frame()
        assert result["MMSECG"].to_list() == ["Normal", "Normal"]

    def test_mild(self):
        df = pl.DataFrame({"MMSE": [26, 18]})
        result = df.neuro.mmse_category("MMSECG", score_col="MMSE").to_frame()
        assert result["MMSECG"].to_list() == ["Mild", "Mild"]

    def test_moderate(self):
        df = pl.DataFrame({"MMSE": [17, 10]})
        result = df.neuro.mmse_category("MMSECG", score_col="MMSE").to_frame()
        assert result["MMSECG"].to_list() == ["Moderate", "Moderate"]

    def test_severe(self):
        df = pl.DataFrame({"MMSE": [9, 0]})
        result = df.neuro.mmse_category("MMSECG", score_col="MMSE").to_frame()
        assert result["MMSECG"].to_list() == ["Severe", "Severe"]

    def test_all_categories_in_order(self):
        df = pl.DataFrame({"MMSE": [28, 22, 15, 8]})
        result = df.neuro.mmse_category("MMSECG", score_col="MMSE").to_frame()
        assert result["MMSECG"].to_list() == ["Normal", "Mild", "Moderate", "Severe"]


class TestCdrsob:
    def test_sum_of_boxes(self):
        df = pl.DataFrame({
            "CDRMEM":  [2.0],
            "CDRORNT": [1.0],
            "CDRJDGM": [0.5],
            "CDRCOMM": [1.0],
            "CDRHOME": [0.0],
            "CDRPERS": [0.0],
        })
        result = df.neuro.cdrsob_total(
            "CDRSOB",
            domain_cols=["CDRMEM", "CDRORNT", "CDRJDGM", "CDRCOMM", "CDRHOME", "CDRPERS"],
        ).to_frame()
        assert result["CDRSOB"][0] == pytest.approx(4.5)

    def test_null_propagates(self):
        df = pl.DataFrame({
            "A": [1.0],
            "B": [None],
        })
        result = df.neuro.cdrsob_total("TOT", domain_cols=["A", "B"]).to_frame()
        assert result["TOT"][0] is None


class TestMocaCategory:
    def test_normal_26_and_above(self):
        df = pl.DataFrame({"MOCA": [26, 30]})
        result = df.neuro.moca_category("MOACG", score_col="MOCA").to_frame()
        assert result["MOACG"].to_list() == ["Normal", "Normal"]

    def test_mci(self):
        df = pl.DataFrame({"MOCA": [18, 25]})
        result = df.neuro.moca_category("MOACG", score_col="MOCA").to_frame()
        assert result["MOACG"].to_list() == ["MCI", "MCI"]

    def test_impaired(self):
        df = pl.DataFrame({"MOCA": [0, 17]})
        result = df.neuro.moca_category("MOACG", score_col="MOCA").to_frame()
        assert result["MOACG"].to_list() == ["Impaired", "Impaired"]


class TestPanssTotal:
    def test_sum_subscales(self):
        df = pl.DataFrame({
            "PANSSPOS": [14.0],
            "PANSSNEG": [16.0],
            "PANSSGEN": [30.0],
        })
        result = df.neuro.panss_total(
            "PANSSTOT",
            positive_col="PANSSPOS",
            negative_col="PANSSNEG",
            general_col="PANSSGEN",
        ).to_frame()
        assert result["PANSSTOT"][0] == pytest.approx(60.0)
