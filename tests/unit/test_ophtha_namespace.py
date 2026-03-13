"""Unit tests for the Ophthalmology Polars namespace extension (df.ophtha)."""

import polars as pl
import pytest

import pymaverse  # noqa: F401 — triggers namespace registration


class TestEtdrsToLogmar:
    def test_etdrs_50_gives_07(self):
        df = pl.DataFrame({"ETDRS": [50.0]})
        result = df.ophtha.etdrs_to_logmar("LOGMAR", source="ETDRS").to_frame()
        assert result["LOGMAR"][0] == pytest.approx(0.7, abs=1e-4)

    def test_etdrs_85_gives_0(self):
        df = pl.DataFrame({"ETDRS": [85.0]})
        result = df.ophtha.etdrs_to_logmar("LOGMAR", source="ETDRS").to_frame()
        assert result["LOGMAR"][0] == pytest.approx(0.0, abs=1e-4)

    def test_etdrs_0_gives_17(self):
        df = pl.DataFrame({"ETDRS": [0.0]})
        result = df.ophtha.etdrs_to_logmar("LOGMAR", source="ETDRS").to_frame()
        assert result["LOGMAR"][0] == pytest.approx(1.7, abs=1e-4)


class TestLogmarToEtdrs:
    def test_logmar_07_gives_50(self):
        df = pl.DataFrame({"LOGMAR": [0.7]})
        result = df.ophtha.logmar_to_etdrs("ETDRS", source="LOGMAR").to_frame()
        assert result["ETDRS"][0] == pytest.approx(50.0, abs=0.1)

    def test_logmar_0_gives_85(self):
        df = pl.DataFrame({"LOGMAR": [0.0]})
        result = df.ophtha.logmar_to_etdrs("ETDRS", source="LOGMAR").to_frame()
        assert result["ETDRS"][0] == pytest.approx(85.0, abs=0.1)

    def test_roundtrip(self):
        df = pl.DataFrame({"ETDRS": [55.0, 70.0, 20.0]})
        # Materialise after the first conversion so "LOGMAR" exists for the next step.
        logmar_df = df.ophtha.etdrs_to_logmar("LOGMAR", source="ETDRS").to_frame()
        result = logmar_df.ophtha.logmar_to_etdrs("ETDRS_RT", source="LOGMAR").to_frame()
        for orig, rt in zip(df["ETDRS"].to_list(), result["ETDRS_RT"].to_list()):
            assert rt == pytest.approx(orig, abs=0.2)


class TestStudyEye:
    def test_os_maps_left(self):
        df = pl.DataFrame({"SCSTRESC": ["OS"]})
        result = df.ophtha.study_eye("STUDYEYE", source="SCSTRESC").to_frame()
        assert result["STUDYEYE"][0] == "LEFT"

    def test_od_maps_right(self):
        df = pl.DataFrame({"SCSTRESC": ["OD"]})
        result = df.ophtha.study_eye("STUDYEYE", source="SCSTRESC").to_frame()
        assert result["STUDYEYE"][0] == "RIGHT"

    def test_ou_maps_bilateral(self):
        df = pl.DataFrame({"SCSTRESC": ["OU"]})
        result = df.ophtha.study_eye("STUDYEYE", source="SCSTRESC").to_frame()
        assert result["STUDYEYE"][0] == "BILATERAL"

    def test_unknown_maps_null(self):
        df = pl.DataFrame({"SCSTRESC": ["UNKNOWN"]})
        result = df.ophtha.study_eye("STUDYEYE", source="SCSTRESC").to_frame()
        assert result["STUDYEYE"][0] is None

    def test_case_insensitive(self):
        df = pl.DataFrame({"SCSTRESC": ["os", "Od", "oU"]})
        result = df.ophtha.study_eye("STUDYEYE", source="SCSTRESC").to_frame()
        assert result["STUDYEYE"].to_list() == ["LEFT", "RIGHT", "BILATERAL"]


class TestAffectedEye:
    def test_bilateral_lat_gives_both_eyes(self):
        df = pl.DataFrame({
            "STUDYEYE": ["RIGHT"],
            "AELOC":    ["EYE"],
            "AELAT":    ["BILATERAL"],
        })
        result = df.ophtha.affected_eye(
            "AFEYE", loc_col="AELOC", lat_col="AELAT"
        ).to_frame()
        assert result["AFEYE"][0] == "Both Eyes"

    def test_matching_lat_gives_study_eye(self):
        df = pl.DataFrame({
            "STUDYEYE": ["RIGHT"],
            "AELOC":    ["EYE"],
            "AELAT":    ["RIGHT"],
        })
        result = df.ophtha.affected_eye(
            "AFEYE", loc_col="AELOC", lat_col="AELAT"
        ).to_frame()
        assert result["AFEYE"][0] == "Study Eye"

    def test_opposite_lat_gives_fellow_eye(self):
        df = pl.DataFrame({
            "STUDYEYE": ["RIGHT"],
            "AELOC":    ["EYE"],
            "AELAT":    ["LEFT"],
        })
        result = df.ophtha.affected_eye(
            "AFEYE", loc_col="AELOC", lat_col="AELAT"
        ).to_frame()
        assert result["AFEYE"][0] == "Fellow Eye"

    def test_invalid_loc_gives_null(self):
        df = pl.DataFrame({
            "STUDYEYE": ["RIGHT"],
            "AELOC":    ["NOSE"],
            "AELAT":    ["RIGHT"],
        })
        result = df.ophtha.affected_eye(
            "AFEYE", loc_col="AELOC", lat_col="AELAT"
        ).to_frame()
        assert result["AFEYE"][0] is None


class TestBcvaCriterion:
    def test_ge_threshold(self):
        df = pl.DataFrame({"ETDRS": [50.0, 70.0, 69.0]})
        result = df.ophtha.bcva_criterion(
            "BCVACR1FL", value_col="ETDRS", threshold=70.0, direction="ge"
        ).to_frame()
        assert result["BCVACR1FL"].to_list() == [None, "Y", None]

    def test_lt_threshold(self):
        df = pl.DataFrame({"ETDRS": [30.0, 35.0, 40.0]})
        result = df.ophtha.bcva_criterion(
            "LOWFL", value_col="ETDRS", threshold=35.0, direction="lt"
        ).to_frame()
        assert result["LOWFL"].to_list() == ["Y", None, None]

    def test_invalid_direction_raises(self):
        df = pl.DataFrame({"ETDRS": [50.0]})
        with pytest.raises(ValueError, match="direction"):
            df.ophtha.bcva_criterion("X", value_col="ETDRS", threshold=50, direction="eq").to_frame()
