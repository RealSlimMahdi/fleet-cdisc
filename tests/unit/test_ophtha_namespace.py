"""Unit tests for the Ophthalmology Polars namespace extension (df.ophtha)."""

import polars as pl
import polars.testing as plt
import pytest

import pymaverse  # noqa: F401 — triggers namespace registration

# ---------------------------------------------------------------------------
# Reference values from admiralophtha test-convert_etdrs_to_logmar.R
# Formula: logmar = -0.02 * etdrs + 1.7
# ---------------------------------------------------------------------------
_ETDRS_LOGMAR_PAIRS = [
    (5,  1.6),
    (10, 1.5),
    (15, 1.4),
    (20, 1.3),
    (25, 1.2),
    (30, 1.1),
    (85, 0.0),
    (90, -0.1),
]

# ---------------------------------------------------------------------------
# Eye code → study eye text (admiralophtha derive_var_studyeye reference)
# ---------------------------------------------------------------------------
_EYE_CODE_MAPPING = [
    ("OS", "LEFT"),
    ("OD", "RIGHT"),
    ("OU", "BILATERAL"),
    ("OP", None),      # unknown code → null
]


class TestEtdrsToLogmar:
    """
    Test 1: ETDRS → LogMAR conversion.

    Mirrors admiralophtha test-convert_etdrs_to_logmar.R using the same
    reference values (5, 10, 15, 20, 25, 30, 90 → 1.6, 1.5, ..., -0.1).
    """

    @pytest.mark.parametrize("etdrs,expected_logmar", _ETDRS_LOGMAR_PAIRS)
    def test_reference_values(self, etdrs, expected_logmar):
        """Single-row parametrized check matching admiral's reference vector."""
        df = pl.DataFrame({"ETDRS": [float(etdrs)]})
        result = df.ophtha.etdrs_to_logmar("LOGMAR", source="ETDRS").to_frame()
        assert result["LOGMAR"][0] == pytest.approx(expected_logmar, abs=1e-4)

    def test_full_vector_at_once(self):
        """All reference ETDRS values in a single DataFrame call."""
        etdrs_vals = [float(e) for e, _ in _ETDRS_LOGMAR_PAIRS]
        expected = [lm for _, lm in _ETDRS_LOGMAR_PAIRS]
        df = pl.DataFrame({"ETDRS": etdrs_vals})
        result = df.ophtha.etdrs_to_logmar("LOGMAR", source="ETDRS").to_frame()
        for got, exp in zip(result["LOGMAR"].to_list(), expected):
            assert got == pytest.approx(exp, abs=1e-4)

    def test_non_derived_columns_preserved(self):
        df = pl.DataFrame({"USUBJID": ["01-701-1015"], "ETDRS": [50.0]})
        result = df.ophtha.etdrs_to_logmar("LOGMAR", source="ETDRS").to_frame()
        assert "USUBJID" in result.columns


class TestLogmarToEtdrs:
    """Test 2: LogMAR → ETDRS conversion and roundtrip."""

    def test_logmar_07_gives_50(self):
        df = pl.DataFrame({"LOGMAR": [0.7]})
        result = df.ophtha.logmar_to_etdrs("ETDRS", source="LOGMAR").to_frame()
        assert result["ETDRS"][0] == pytest.approx(50.0, abs=0.1)

    def test_logmar_0_gives_85(self):
        df = pl.DataFrame({"LOGMAR": [0.0]})
        result = df.ophtha.logmar_to_etdrs("ETDRS", source="LOGMAR").to_frame()
        assert result["ETDRS"][0] == pytest.approx(85.0, abs=0.1)

    def test_roundtrip(self):
        """ETDRS → LogMAR → ETDRS must recover original values within rounding."""
        df = pl.DataFrame({"ETDRS": [55.0, 70.0, 20.0]})
        logmar_df = df.ophtha.etdrs_to_logmar("LOGMAR", source="ETDRS").to_frame()
        result = logmar_df.ophtha.logmar_to_etdrs("ETDRS_RT", source="LOGMAR").to_frame()
        for orig, rt in zip(df["ETDRS"].to_list(), result["ETDRS_RT"].to_list()):
            assert rt == pytest.approx(orig, abs=0.2)


class TestStudyEye:
    """
    Test 3: Eye code → study eye text derivation.

    Mirrors admiralophtha test-derive_var_studyeye.R which checks all 4 valid
    codes (OS, OD, OU, OP/unknown) plus case-insensitivity.
    """

    @pytest.mark.parametrize("code,expected_eye", _EYE_CODE_MAPPING)
    def test_eye_code_mapping(self, code, expected_eye):
        df = pl.DataFrame({"SCSTRESC": [code]})
        result = df.ophtha.study_eye("STUDYEYE", source="SCSTRESC").to_frame()
        assert result["STUDYEYE"][0] == expected_eye

    def test_case_insensitive_full_vector(self):
        """admiral tests case-insensitive parsing — lower/mixed case must work."""
        df = pl.DataFrame({"SCSTRESC": ["os", "Od", "oU", "op"]})
        result = df.ophtha.study_eye("STUDYEYE", source="SCSTRESC").to_frame()
        assert result["STUDYEYE"].to_list() == ["LEFT", "RIGHT", "BILATERAL", None]

    def test_multi_subject_realistic(self):
        """Multi-subject frame matching admiral's test-derive_var_studyeye.R layout."""
        df = pl.DataFrame({
            "STUDYID": ["XXX001"] * 4,
            "USUBJID": ["P01", "P02", "P04", "P05"],
            "SCSTRESC": ["OS", "OD", "OU", "OD"],
        })
        result = df.ophtha.study_eye("STUDYEYE", source="SCSTRESC").to_frame()
        eyes = dict(zip(result["USUBJID"].to_list(), result["STUDYEYE"].to_list()))
        assert eyes["P01"] == "LEFT"
        assert eyes["P02"] == "RIGHT"
        assert eyes["P04"] == "BILATERAL"
        assert eyes["P05"] == "RIGHT"


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
    """
    Test 5: BCVA criterion flag — boundary conditions for all 4 directions.

    Admiral explicitly tests all 4 directions separately.
    """

    @pytest.mark.parametrize("direction,values,threshold,expected", [
        ("ge", [50.0, 70.0, 69.0], 70.0, [None, "Y", None]),   # ≥ threshold
        ("gt", [50.0, 70.0, 71.0], 70.0, [None, None, "Y"]),   # > threshold (exact = no flag)
        ("le", [70.0, 35.0, 36.0], 35.0, [None, "Y", None]),   # ≤ threshold
        ("lt", [30.0, 35.0, 34.0], 35.0, ["Y", None, "Y"]),    # < threshold
    ])
    def test_direction_variants(self, direction, values, threshold, expected):
        df = pl.DataFrame({"ETDRS": values})
        result = df.ophtha.bcva_criterion(
            "FL", value_col="ETDRS", threshold=threshold, direction=direction
        ).to_frame()
        assert result["FL"].to_list() == expected

    def test_at_exact_ge_threshold_flagged(self):
        """At exactly the ge threshold → must flag (inclusive)."""
        df = pl.DataFrame({"ETDRS": [70.0]})
        result = df.ophtha.bcva_criterion(
            "FL", value_col="ETDRS", threshold=70.0, direction="ge"
        ).to_frame()
        assert result["FL"][0] == "Y"

    def test_at_exact_gt_threshold_not_flagged(self):
        """At exactly the gt threshold → must NOT flag (exclusive)."""
        df = pl.DataFrame({"ETDRS": [70.0]})
        result = df.ophtha.bcva_criterion(
            "FL", value_col="ETDRS", threshold=70.0, direction="gt"
        ).to_frame()
        assert result["FL"][0] is None

    def test_invalid_direction_raises(self):
        df = pl.DataFrame({"ETDRS": [50.0]})
        with pytest.raises(ValueError, match="direction"):
            df.ophtha.bcva_criterion(
                "X", value_col="ETDRS", threshold=50, direction="eq"
            ).to_frame()
