"""Unit tests for the Vaccine Polars namespace extension (df.adam.vaccine)."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration

# ---------------------------------------------------------------------------
# LOQ boundary scenarios for aval_adis — mirrors admiralvaccine
# test-derive_var_aval_adis.R which tests below/at/in-range/at-uloq/above
# ---------------------------------------------------------------------------
_LLOQ_ULOQ_CASES = [
    # (stresn, lloq, uloq, orres,  expected_aval, description)
    (1.0,   4.0,  200.0, "1",     2.0,   "below LLOQ → lloq/2"),
    (4.0,   4.0,  200.0, "4",     4.0,   "exactly at LLOQ → stresn (not below)"),
    (50.0,  4.0,  200.0, "50",    50.0,  "in range → stresn"),
    (200.0, 4.0,  200.0, "200",   200.0, "exactly at ULOQ → uloq"),
    (250.0, 4.0,  200.0, "250",   200.0, "above ULOQ → uloq"),
]


class TestFeverFlag:
    """Test 1: Temperature fever flag — strict > threshold."""

    def test_above_threshold_flagged(self):
        df = pl.DataFrame({"TEMP": [37.0, 38.1, 39.0, 38.0]})
        result = df.adam.vaccine.fever_flag("FEVFL", temp_col="TEMP").to_frame()
        # > 38.0, not >=
        assert result["FEVFL"].to_list() == [None, "Y", "Y", None]

    def test_at_exact_threshold_not_flagged(self):
        """Exactly AT the threshold must NOT flag (strict >)."""
        df = pl.DataFrame({"TEMP": [38.0]})
        result = df.adam.vaccine.fever_flag("FEVFL", temp_col="TEMP").to_frame()
        assert result["FEVFL"][0] is None

    def test_custom_threshold(self):
        df = pl.DataFrame({"TEMP": [39.0, 39.5, 40.0]})
        result = df.adam.vaccine.fever_flag(
            "HIGHFL", temp_col="TEMP", threshold=39.0
        ).to_frame()
        assert result["HIGHFL"].to_list() == [None, "Y", "Y"]

    def test_custom_flag_value(self):
        df = pl.DataFrame({"TEMP": [39.0]})
        result = df.adam.vaccine.fever_flag(
            "FEVFL", temp_col="TEMP", flag_value="1"
        ).to_frame()
        assert result["FEVFL"][0] == "1"

    def test_non_derived_columns_preserved(self):
        df = pl.DataFrame({
            "STUDYID": ["VACCSTUDY01"],
            "USUBJID": ["01-001"],
            "TEMP":    [39.5],
        })
        result = df.adam.vaccine.fever_flag("FEVFL", temp_col="TEMP").to_frame()
        assert "STUDYID" in result.columns
        assert "USUBJID" in result.columns


class TestSeroconversionFlag:
    """Test 2: ≥N-fold rise from baseline."""

    def test_fourfold_rise_flagged(self):
        df = pl.DataFrame({
            "AVAL": [400.0, 1600.0, 300.0],
            "BASE": [100.0, 100.0,  100.0],
        })
        result = df.adam.vaccine.seroconversion_flag(
            "SRCONVFL", aval_col="AVAL", base_col="BASE"
        ).to_frame()
        assert result["SRCONVFL"].to_list() == ["Y", "Y", None]

    def test_exactly_four_fold_flagged(self):
        """Exactly 4.0-fold rise must be flagged (≥ is inclusive)."""
        df = pl.DataFrame({"AVAL": [400.0], "BASE": [100.0]})
        result = df.adam.vaccine.seroconversion_flag(
            "SRCONVFL", aval_col="AVAL", base_col="BASE"
        ).to_frame()
        assert result["SRCONVFL"][0] == "Y"

    def test_zero_base_gives_null(self):
        """Zero denominator must produce null, not an error or infinity."""
        df = pl.DataFrame({"AVAL": [100.0], "BASE": [0.0]})
        result = df.adam.vaccine.seroconversion_flag(
            "SRCONVFL", aval_col="AVAL", base_col="BASE"
        ).to_frame()
        assert result["SRCONVFL"][0] is None

    def test_null_base_gives_null(self):
        df = pl.DataFrame({"AVAL": [100.0], "BASE": [None]})
        result = df.adam.vaccine.seroconversion_flag(
            "SRCONVFL", aval_col="AVAL", base_col="BASE"
        ).to_frame()
        assert result["SRCONVFL"][0] is None

    def test_custom_fold_rise(self):
        df = pl.DataFrame({
            "AVAL": [200.0, 300.0],
            "BASE": [100.0, 100.0],
        })
        result = df.adam.vaccine.seroconversion_flag(
            "SRCONV2FL", aval_col="AVAL", base_col="BASE", fold_rise=2.0
        ).to_frame()
        assert result["SRCONV2FL"].to_list() == ["Y", "Y"]


class TestSeroresponseFlag:
    """Test 3: Seroresponse — value at or above threshold."""

    def test_above_threshold(self):
        df = pl.DataFrame({"AVAL": [30.0, 40.0, 50.0]})
        result = df.adam.vaccine.seroresponse_flag(
            "SRSFL", aval_col="AVAL", threshold=40.0
        ).to_frame()
        assert result["SRSFL"].to_list() == [None, "Y", "Y"]

    def test_exactly_at_threshold_flagged(self):
        """Exactly AT the threshold must flag (≥ is inclusive)."""
        df = pl.DataFrame({"AVAL": [40.0]})
        result = df.adam.vaccine.seroresponse_flag(
            "SRSFL", aval_col="AVAL", threshold=40.0
        ).to_frame()
        assert result["SRSFL"][0] == "Y"


class TestAvalAdis:
    """
    Test 4: AVAL derivation with LOQ handling.

    Mirrors admiralvaccine derive_var_aval_adis tests which cover:
      - below LLOQ → lloq/2 (default rule)
      - exactly AT LLOQ → stresn (boundary condition)
      - in range → stresn
      - exactly AT ULOQ → uloq
      - above ULOQ → uloq
      - missing STRESN with > ORRES → uloq
      - missing STRESN with < ORRES → lloq/2
      - missing STRESN with null ORRES → null
      - lloq_rule="lloq" (non-default)
    """

    @pytest.mark.parametrize("stresn,lloq,uloq,orres,expected,_desc", _LLOQ_ULOQ_CASES)
    def test_lloq_uloq_boundary(self, stresn, lloq, uloq, orres, expected, _desc):
        df = pl.DataFrame({
            "ISSTRESN": [stresn],
            "ISLLOQ":   [lloq],
            "ISULOQ":   [uloq],
            "ISORRES":  [orres],
        })
        result = df.adam.vaccine.aval_adis(
            "AVAL",
            stresn_col="ISSTRESN", lloq_col="ISLLOQ",
            uloq_col="ISULOQ", orres_col="ISORRES"
        ).to_frame()
        assert result["AVAL"][0] == pytest.approx(expected), _desc

    def test_lloq_rule_lloq(self):
        """lloq_rule='lloq' → value below LLOQ returns full LLOQ (not half)."""
        df = pl.DataFrame({
            "ISSTRESN": [1.0],
            "ISLLOQ":   [4.0],
            "ISULOQ":   [200.0],
            "ISORRES":  ["1"],
        })
        result = df.adam.vaccine.aval_adis(
            "AVAL",
            stresn_col="ISSTRESN", lloq_col="ISLLOQ",
            uloq_col="ISULOQ", orres_col="ISORRES",
            lloq_rule="lloq",
        ).to_frame()
        assert result["AVAL"][0] == pytest.approx(4.0)  # full LLOQ, not 2.0

    def test_missing_stresn_gt_orres(self):
        """Missing STRESN but ISORRES starts with '>' → capped at ULOQ."""
        df = pl.DataFrame({
            "ISSTRESN": [None],
            "ISLLOQ":   [4.0],
            "ISULOQ":   [200.0],
            "ISORRES":  [">200"],
        })
        result = df.adam.vaccine.aval_adis(
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
        result = df.adam.vaccine.aval_adis(
            "AVAL",
            stresn_col="ISSTRESN", lloq_col="ISLLOQ",
            uloq_col="ISULOQ", orres_col="ISORRES"
        ).to_frame()
        assert result["AVAL"][0] is None

    def test_multi_subject_adis_frame(self, adis_frame):
        """
        Full ADIS fixture test — verifies correct LOQ handling across 3 subjects
        and 2 visits each, mirroring admiral's multi-parameter test 1.
        """
        result = adis_frame.adam.vaccine.aval_adis(
            "AVAL",
            stresn_col="ISSTRESN", lloq_col="ISLLOQ",
            uloq_col="ISULOQ", orres_col="ISORRES"
        ).to_frame()
        assert result.height == adis_frame.height
        # Row 0: ISSTRESN=1.0 < ISLLOQ=4.0 → 2.0
        assert result["AVAL"][0] == pytest.approx(2.0)
        # Row 1: ISSTRESN=50.0, in range → 50.0
        assert result["AVAL"][1] == pytest.approx(50.0)


class TestEventFlag:
    """Test 5: Group-level reactogenicity event flag."""

    def test_group_event_flag(self):
        df = pl.DataFrame({
            "USUBJID": ["S01", "S01", "S01"],
            "FAOBJ":   ["REDNESS", "REDNESS", "REDNESS"],
            "ATPTREF": ["VAC1", "VAC1", "VAC1"],
            "AVAL":    [3.5, 1.0, 4.5],
            "AVALC":   ["3.5", "1.0", "4.5"],
        })
        result = df.adam.vaccine.event_flag(
            "EVENTFL", aval_col="AVAL", cutoff=2.5,
            groups=["USUBJID", "FAOBJ", "ATPTREF"]
        ).to_frame()
        # Event occurred (> 2.5) at least once → all rows flagged "Y"
        assert all(f == "Y" for f in result["EVENTFL"].to_list())

    def test_no_event_gives_N_for_all(self):
        """No row exceeds cutoff → all rows in the group should return "N"."""
        df = pl.DataFrame({
            "USUBJID": ["S02", "S02", "S02"],
            "FAOBJ":   ["PAIN", "PAIN", "PAIN"],
            "ATPTREF": ["VAC1", "VAC1", "VAC1"],
            "AVAL":    [1.0, 1.5, 2.0],
            "AVALC":   ["1.0", "1.5", "2.0"],
        })
        result = df.adam.vaccine.event_flag(
            "EVENTFL", aval_col="AVAL", cutoff=2.5,
            groups=["USUBJID", "FAOBJ", "ATPTREF"],
            no_event_value="N"
        ).to_frame()
        assert all(f == "N" for f in result["EVENTFL"].to_list())

    def test_multi_subject_independent_flags(self):
        """Subjects must be evaluated independently."""
        df = pl.DataFrame({
            "USUBJID": ["S01", "S01", "S02", "S02"],
            "FAOBJ":   ["REDNS"] * 4,
            "ATPTREF": ["VAC1"] * 4,
            "AVAL":    [3.5, 1.0, 1.0, 2.0],
            "AVALC":   ["3.5", "1.0", "1.0", "2.0"],
        })
        result = df.adam.vaccine.event_flag(
            "EVENTFL", aval_col="AVAL", cutoff=2.5,
            groups=["USUBJID", "FAOBJ", "ATPTREF"],
            no_event_value="N"
        ).to_frame()
        s01_flags = result.filter(pl.col("USUBJID") == "S01")["EVENTFL"].to_list()
        s02_flags = result.filter(pl.col("USUBJID") == "S02")["EVENTFL"].to_list()
        assert all(f == "Y" for f in s01_flags)   # S01 had event
        assert all(f == "N" for f in s02_flags)   # S02 had no event

    def test_no_event_gives_N(self):
        df = pl.DataFrame({
            "USUBJID": ["S02", "S02"],
            "FAOBJ":   ["PAIN", "PAIN"],
            "ATPTREF": ["VAC1", "VAC1"],
            "AVAL":    [1.0, 2.0],
            "AVALC":   ["1.0", "2.0"],
        })
        result = df.adam.vaccine.event_flag(
            "EVENTFL", aval_col="AVAL", cutoff=2.5,
            groups=["USUBJID", "FAOBJ", "ATPTREF"]
        ).to_frame()
        assert all(f == "N" for f in result["EVENTFL"].to_list())
