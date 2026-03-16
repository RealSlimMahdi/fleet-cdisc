"""Unit tests for the Neuroscience Polars namespace extension (df.adam.neuro)."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration

# ---------------------------------------------------------------------------
# All 4 pre-defined Centiloid calibration entries from the namespace module.
# slope and intercept taken directly from _CENTILOID_CALIBRATIONS.
# ---------------------------------------------------------------------------
_CENTILOID_CALIBRATIONS = [
    ("18F-Florbetapir",  "AVID FBP SUVR PIPELINE",     183.07,  -177.26),
    ("18F-Florbetaben",  "AVID FBB SUVR PIPELINE",     156.06,  -148.13),
    ("18F-Florbetapir",  "BERKELEY FBP SUVR PIPELINE",  188.22, -189.16),
    ("18F-Florbetaben",  "BERKELEY FBB SUVR PIPELINE",  157.15, -151.87),
]

# ---------------------------------------------------------------------------
# MMSE severity boundary values — test exactly AT each transition threshold
# ---------------------------------------------------------------------------
_MMSE_CATEGORY_CASES = [
    (30, "Normal"),
    (27, "Normal"),     # boundary: ≥27
    (26, "Mild"),
    (18, "Mild"),       # boundary: ≥18
    (17, "Moderate"),
    (10, "Moderate"),   # boundary: ≥10
    (9,  "Severe"),
    (0,  "Severe"),
]

# ---------------------------------------------------------------------------
# MoCA category boundary values
# ---------------------------------------------------------------------------
_MOCA_CATEGORY_CASES = [
    (30, "Normal"),
    (26, "Normal"),   # boundary: ≥26
    (25, "MCI"),
    (18, "MCI"),      # boundary: ≥18
    (17, "Impaired"),
    (0,  "Impaired"),
]


@pytest.fixture
def neuro_frame():
    """Minimal frame for shared verb tests on the neuro namespace."""
    return pl.DataFrame({
        "USUBJID": ["01-001", "01-002"],
        "MMSE":    [28, 15],
        "ARM":     ["Active", "Placebo"],
    })


class TestBaseVerbs:
    """Shared verbs inherited from SharedADaMVerbsMixin."""

    def test_source(self, neuro_frame):
        result = neuro_frame.adam.neuro.source("USUBJID").to_frame()
        assert "USUBJID" in result.columns

    def test_assigned(self, neuro_frame):
        result = neuro_frame.adam.neuro.assigned("STUDYID", value="NEU01").to_frame()
        assert result["STUDYID"].to_list() == ["NEU01"] * 2

    def test_derivation(self, neuro_frame):
        result = neuro_frame.adam.neuro.derivation(
            "MMSE2", expression='pl.col("MMSE") * 2'
        ).to_frame()
        assert result["MMSE2"].to_list() == [56, 30]

    def test_recode(self, neuro_frame):
        result = neuro_frame.adam.neuro.recode(
            "ARMCD", source="ARM",
            recode_map={"Active": "ACT", "Placebo": "PBO"}
        ).to_frame()
        assert result["ARMCD"].to_list() == ["ACT", "PBO"]

    def test_rename(self, neuro_frame):
        result = neuro_frame.adam.neuro.rename("SUBJ", source="USUBJID").to_frame()
        assert result["SUBJ"].to_list() == neuro_frame["USUBJID"].to_list()

    def test_condderivation(self, neuro_frame):
        result = neuro_frame.adam.neuro.condderivation(
            "SEVCAT",
            conditions=[{"condition": 'pl.col("MMSE") >= 27', "value": "Normal"}],
            else_value="Impaired",
        ).to_frame()
        assert result["SEVCAT"].to_list() == ["Normal", "Impaired"]

    def test_whereclauses(self, neuro_frame):
        result = neuro_frame.adam.neuro.whereclauses(
            where='pl.col("MMSE") >= 27'
        ).to_frame()
        assert result.height == 1


class TestCentiloid:
    """
    Test 1: Centiloid conversion (custom slopes and all 4 pre-defined calibrations).
    """

    def test_custom_slope_intercept(self):
        df = pl.DataFrame({"SUVR": [1.25]})
        result = df.adam.neuro.centiloid(
            "CLV", suvr_col="SUVR", slope=183.07, intercept=-177.26
        ).to_frame()
        assert result["CLV"][0] == pytest.approx(183.07 * 1.25 - 177.26, abs=0.01)

    @pytest.mark.parametrize("tracer,pipeline,slope,intercept", _CENTILOID_CALIBRATIONS)
    def test_all_predefined_calibrations(self, tracer, pipeline, slope, intercept):
        """All 4 pre-defined tracer/pipeline combinations produce the correct result."""
        suvr = 1.2
        df = pl.DataFrame({"SUVR": [suvr]})
        result = df.adam.neuro.centiloid(
            "CLV", suvr_col="SUVR", tracer=tracer, pipeline=pipeline
        ).to_frame()
        assert result["CLV"][0] == pytest.approx(slope * suvr + intercept, abs=0.01)

    def test_unknown_combination_raises(self):
        df = pl.DataFrame({"SUVR": [1.0]})
        with pytest.raises(ValueError, match="No calibration found"):
            df.adam.neuro.centiloid(
                "CLV", suvr_col="SUVR",
                tracer="MyTracer", pipeline="MyPipeline"
            ).to_frame()

    def test_no_params_raises(self):
        df = pl.DataFrame({"SUVR": [1.0]})
        with pytest.raises(ValueError, match="slope"):
            df.adam.neuro.centiloid("CLV", suvr_col="SUVR").to_frame()

    def test_non_derived_columns_preserved(self):
        df = pl.DataFrame({"USUBJID": ["01-701-1015"], "SUVR": [1.2]})
        result = df.adam.neuro.centiloid(
            "CLV", suvr_col="SUVR", slope=183.07, intercept=-177.26
        ).to_frame()
        assert "USUBJID" in result.columns


class TestMmseCategory:
    """
    Test 2: MMSE category — all 4 severity bands with boundary values.
    """

    @pytest.mark.parametrize("score,expected_category", _MMSE_CATEGORY_CASES)
    def test_mmse_boundary_values(self, score, expected_category):
        df = pl.DataFrame({"MMSE": [score]})
        result = df.adam.neuro.mmse_category("MMSECG", score_col="MMSE").to_frame()
        assert result["MMSECG"][0] == expected_category

    def test_all_categories_in_order(self):
        df = pl.DataFrame({"MMSE": [28, 22, 15, 8]})
        result = df.adam.neuro.mmse_category("MMSECG", score_col="MMSE").to_frame()
        assert result["MMSECG"].to_list() == ["Normal", "Mild", "Moderate", "Severe"]


class TestCdrsob:
    """Test 3: CDR Sum-of-Boxes = sum of 6 domain scores."""

    def test_sum_of_boxes(self):
        df = pl.DataFrame({
            "CDRMEM":  [2.0],
            "CDRORNT": [1.0],
            "CDRJDGM": [0.5],
            "CDRCOMM": [1.0],
            "CDRHOME": [0.0],
            "CDRPERS": [0.0],
        })
        result = df.adam.neuro.cdrsob_total(
            "CDRSOB",
            domain_cols=["CDRMEM", "CDRORNT", "CDRJDGM", "CDRCOMM", "CDRHOME", "CDRPERS"],
        ).to_frame()
        assert result["CDRSOB"][0] == pytest.approx(4.5)

    def test_all_zeros(self):
        df = pl.DataFrame({"A": [0.0], "B": [0.0], "C": [0.0]})
        result = df.adam.neuro.cdrsob_total("TOT", domain_cols=["A", "B", "C"]).to_frame()
        assert result["TOT"][0] == pytest.approx(0.0)

    def test_null_propagates_to_total(self):
        """Any null domain score should make the total null (strict null-safety)."""
        df = pl.DataFrame({"A": [1.0], "B": [None]})
        result = df.adam.neuro.cdrsob_total("TOT", domain_cols=["A", "B"]).to_frame()
        assert result["TOT"][0] is None


class TestMocaCategory:
    """
    Test 4: MoCA category — Normal / MCI / Impaired with boundary values.
    """

    @pytest.mark.parametrize("score,expected_category", _MOCA_CATEGORY_CASES)
    def test_moca_boundary_values(self, score, expected_category):
        df = pl.DataFrame({"MOCA": [score]})
        result = df.adam.neuro.moca_category("MOACG", score_col="MOCA").to_frame()
        assert result["MOACG"][0] == expected_category

    def test_full_vector_all_categories(self):
        df = pl.DataFrame({"MOCA": [28, 22, 10]})
        result = df.adam.neuro.moca_category("MOACG", score_col="MOCA").to_frame()
        assert result["MOACG"].to_list() == ["Normal", "MCI", "Impaired"]


class TestPanssTotal:
    """Test 5: PANSS total = positive + negative + general subscales."""

    def test_sum_subscales(self):
        df = pl.DataFrame({
            "PANSSPOS": [14.0],
            "PANSSNEG": [16.0],
            "PANSSGEN": [30.0],
        })
        result = df.adam.neuro.panss_total(
            "PANSSTOT",
            positive_col="PANSSPOS",
            negative_col="PANSSNEG",
            general_col="PANSSGEN",
        ).to_frame()
        assert result["PANSSTOT"][0] == pytest.approx(60.0)

    def test_null_subscale_propagates(self):
        """Null in any subscale should yield null total."""
        df = pl.DataFrame({
            "PANSSPOS": [14.0],
            "PANSSNEG": [None],
            "PANSSGEN": [30.0],
        })
        result = df.adam.neuro.panss_total(
            "PANSSTOT",
            positive_col="PANSSPOS",
            negative_col="PANSSNEG",
            general_col="PANSSGEN",
        ).to_frame()
        assert result["PANSSTOT"][0] is None

    def test_multi_subject(self):
        """Multiple subjects evaluated independently."""
        df = pl.DataFrame({
            "STUDYID":  ["NEUROSTUDY"] * 2,
            "USUBJID":  ["01-701-1015", "01-701-1023"],
            "PANSSPOS": [14.0, 7.0],
            "PANSSNEG": [16.0, 7.0],
            "PANSSGEN": [30.0, 16.0],
        })
        result = df.adam.neuro.panss_total(
            "PANSSTOT",
            positive_col="PANSSPOS",
            negative_col="PANSSNEG",
            general_col="PANSSGEN",
        ).to_frame()
        totals = dict(zip(result["USUBJID"].to_list(), result["PANSSTOT"].to_list()))
        assert totals["01-701-1015"] == pytest.approx(60.0)
        assert totals["01-701-1023"] == pytest.approx(30.0)
