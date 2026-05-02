"""Unit tests for enhanced flag() and criterion() verbs.

Covers all criteria modes: first/last, max/min, exists, before/after,
exists_after/exists_before, and the criterion() triple-output verb.

Test cases ported from admiral's MIT-licensed test suite.
"""

import polars as pl
import pytest

import fleet  # noqa: F401

# ====================================================================== #
# 1. Extreme Flag — First / Last                                          #
# ====================================================================== #


class TestFlagFirstLast:
    """Tests for criteria='first' and criteria='last'."""

    def test_first_observation_per_group(self):
        """Admiral Test 1: first observation per group."""
        input_df = pl.DataFrame(
            {
                "USUBJID": [1, 1, 2, 3, 3],
                "AVISITN": [1, 3, 2, 3, 3],
                "AVAL": [12, 9, 42, 14, 10],
            }
        )
        result = input_df.adam.flag(
            "firstfl",
            criteria="first",
            order_by=["AVISITN", "AVAL"],
            groups=["USUBJID"],
        ).to_frame()
        # Ascending lexicographic: (3,10) < (3,14) so AVAL=10 is "first" for USUBJID=3
        assert result["firstfl"].to_list() == ["Y", None, "Y", None, "Y"]

    def test_last_observation_per_group(self):
        """Admiral Test 2: last observation per group."""
        input_df = pl.DataFrame(
            {
                "USUBJID": [1, 1, 2, 3, 3],
                "AVISITN": [1, 3, 2, 3, 3],
                "AVAL": [12, 9, 42, 14, 10],
            }
        )
        result = input_df.adam.flag(
            "lastfl",
            criteria="last",
            order_by=["AVISITN", "AVAL"],
            groups=["USUBJID"],
        ).to_frame()
        # Descending: (3,14) > (3,10) so AVAL=14 is "last" for USUBJID=3
        assert result["lastfl"].to_list() == [None, "Y", "Y", "Y", None]

    def test_null_in_order_column(self):
        """Admiral Test 7: NA in order column → never flagged."""
        input_na = pl.DataFrame(
            {
                "USUBJID": [1, 1, 2, 3, 3],
                "AVISITN": [None, 3, 2, 3, 3],
                "AVAL": [12, 9, 42, 14, 10],
            }
        )
        result = input_na.adam.flag(
            "firstfl",
            criteria="first",
            order_by=["AVISITN", "AVAL"],
            groups=["USUBJID"],
        ).to_frame()
        # Row 0: null AVISITN → None; USUBJID=3: (3,10) < (3,14) → row 4 is first
        assert result["firstfl"].to_list() == [None, "Y", "Y", None, "Y"]

    def test_flag_all_ties(self):
        """Admiral Test 4: flag_all=True (ties)."""
        input_ties = pl.DataFrame(
            {
                "STUDYID": ["TEST01"] * 5,
                "USUBJID": ["PAT01"] * 5,
                "ADTM": [
                    "2020-02-01T12:00",
                    "2020-02-01T12:00",
                    "2020-02-01T12:01",
                    "2020-02-01T13:00",
                    "2020-02-01T13:00",
                ],
                "AVISITN": [1] * 5,
                "BASETYPE": ["ontrt"] * 5,
                "PARAM": ["test1", "test2", "test1", "test1", "test2"],
            }
        )
        result = input_ties.adam.flag(
            "FIRSTFL",
            criteria="first",
            order_by="ADTM",
            groups=["STUDYID", "USUBJID", "BASETYPE", "AVISITN"],
            flag_all=True,
        ).to_frame()
        assert result["FIRSTFL"].to_list() == ["Y", "Y", None, None, None]

    def test_custom_true_false_values(self):
        """Admiral Test 9: custom true/false values."""
        input_df = pl.DataFrame(
            {
                "USUBJID": [1, 1, 2, 3, 3],
                "AVISITN": [1, 3, 2, 3, 3],
                "AVAL": [12, 9, 42, 14, 10],
            }
        )
        result = input_df.adam.flag(
            "firstfl",
            criteria="first",
            order_by=["AVISITN", "AVAL"],
            groups=["USUBJID"],
            flag_value="Yes",
            false_value="No",
        ).to_frame()
        # (3,10) < (3,14) so row 4 is "first" for USUBJID=3
        assert result["firstfl"].to_list() == ["Yes", "No", "Yes", "No", "Yes"]

    def test_first_requires_order_by(self):
        """flag criteria='first' raises without order_by."""
        df = pl.DataFrame({"USUBJID": [1], "AVAL": [10]})
        with pytest.raises(ValueError, match="requires order_by"):
            df.adam.flag("FL", criteria="first", groups=["USUBJID"]).to_frame()


# ====================================================================== #
# 2. Extreme Flag — Max / Min                                              #
# ====================================================================== #


class TestFlagMaxMin:
    """Tests for criteria='max' and criteria='min'."""

    def test_max_flag(self):
        df = pl.DataFrame(
            {
                "USUBJID": ["A", "A", "A", "B", "B"],
                "PARAMCD": ["X"] * 5,
                "AVAL": [1.0, 5.0, 3.0, 2.0, 4.0],
            }
        )
        result = df.adam.flag(
            "AMXFL", criteria="max", value_col="AVAL", groups=["USUBJID", "PARAMCD"]
        ).to_frame()
        assert result["AMXFL"].to_list() == [None, "Y", None, None, "Y"]

    def test_min_flag(self):
        df = pl.DataFrame(
            {
                "USUBJID": ["A", "A", "B", "B"],
                "PARAMCD": ["X"] * 4,
                "AVAL": [3.0, 1.0, 5.0, 2.0],
            }
        )
        result = df.adam.flag(
            "AMNFL", criteria="min", value_col="AVAL", groups=["USUBJID", "PARAMCD"]
        ).to_frame()
        assert result["AMNFL"].to_list() == [None, "Y", None, "Y"]

    def test_max_requires_value_col(self):
        df = pl.DataFrame({"USUBJID": [1], "AVAL": [10]})
        with pytest.raises(ValueError, match="requires value_col"):
            df.adam.flag("FL", criteria="max", groups=["USUBJID"]).to_frame()


# ====================================================================== #
# 3. Exist Flag — Single Dataset                                           #
# ====================================================================== #


class TestFlagExists:
    """Tests for criteria='exists'."""

    def test_exist_flag_single_dataset(self):
        """Admiral Test 19: merge existence flag."""
        adsl = pl.DataFrame(
            {
                "USUBJID": ["ST42-1", "ST42-2", "ST42-3", "ST42-4"],
                "SEX": ["F", "M", "M", "F"],
                "STUDYID": ["ST42"] * 4,
            }
        )
        advs = pl.DataFrame(
            {
                "USUBJID": ["ST42-1", "ST42-1", "ST42-2", "ST42-3", "ST42-3"],
                "PARAMCD": ["WEIGHT"] * 5,
                "AVISIT": ["BASELINE", "Week 2", "BASELINE", "Week 2", "Week 4"],
                "AVAL": [66, 68, 88, 55, 50],
                "STUDYID": ["ST42"] * 5,
            }
        )
        result = adsl.adam.adsl.flag(
            "VSEVALFL",
            criteria="exists",
            from_dataset=advs,
            on=["USUBJID"],
            source_filter=pl.col("AVISIT") == "BASELINE",
        ).to_frame()
        assert result["VSEVALFL"].to_list() == ["Y", "Y", None, None]

    def test_exist_flag_with_source_filter(self):
        """Exist flag with condition on source dataset."""
        dm = pl.DataFrame(
            {
                "STUDYID": ["PILOT01"] * 4,
                "USUBJID": ["01-1028", "04-1127", "06-1049", "09-1088"],
                "AGE": [71, 84, 68, 69],
            }
        )
        ae = pl.DataFrame(
            {
                "STUDYID": ["PILOT01"] * 4,
                "USUBJID": ["01-1028", "01-1028", "06-1049", "06-1049"],
                "AEREL": ["POSSIBLE", "PROBABLE", "POSSIBLE", "PROBABLE"],
            }
        )
        result = dm.adam.adsl.flag(
            "AERELFL",
            criteria="exists",
            from_dataset=ae,
            on=["STUDYID", "USUBJID"],
            source_filter=pl.col("AEREL") == "PROBABLE",
        ).to_frame()
        assert result["AERELFL"].to_list() == ["Y", None, "Y", None]

    def test_exist_flag_multi_source(self):
        """Admiral Test 1: multi-source existence flag."""
        adsl = pl.DataFrame(
            {
                "USUBJID": ["1", "2", "3"],
            }
        )
        cm = pl.DataFrame(
            {
                "USUBJID": ["1", "1", "2"],
                "CMCAT": ["ANTI-CANCER", "OTHER", "ANTI-CANCER"],
            }
        )
        pr = pl.DataFrame(
            {
                "USUBJID": ["1", "3"],
                "PRDECOD": ["SURGERY", "RADIATION"],
            }
        )
        result = adsl.adam.adsl.flag(
            "CANCTRFL",
            criteria="exists",
            from_dataset=[
                cm.filter(pl.col("CMCAT") == "ANTI-CANCER"),
                pr,
            ],
            on=["USUBJID"],
        ).to_frame()
        assert result["CANCTRFL"].to_list() == ["Y", "Y", "Y"]

    def test_exist_requires_from_dataset(self):
        df = pl.DataFrame({"USUBJID": [1]})
        with pytest.raises(ValueError, match="requires from_dataset and on"):
            df.adam.flag("FL", criteria="exists", groups=["USUBJID"]).to_frame()


# ====================================================================== #
# 4. Relative Flag — Before / After                                        #
# ====================================================================== #


class TestFlagRelative:
    """Tests for criteria='before' and criteria='after'."""

    def test_before_inclusive(self):
        """Flag observations up to first PD (inclusive)."""
        response = pl.DataFrame(
            {
                "USUBJID": [
                    "1",
                    "1",
                    "1",
                    "1",
                    "1",
                    "2",
                    "2",
                    "2",
                    "3",
                    "4",
                    "4",
                    "4",
                    "4",
                    "4",
                ],
                "AVISITN": [0, 1, 2, 3, 4, 0, 1, 2, 0, 0, 1, 2, 3, 4],
                "AVALC": [
                    "PR",
                    "CR",
                    "CR",
                    "SD",
                    "NE",
                    "SD",
                    "PD",
                    "PD",
                    "SD",
                    "SD",
                    "PR",
                    "PD",
                    "SD",
                    "PR",
                ],
            }
        )
        result = response.adam.flag(
            "ANL02FL",
            criteria="before",
            condition=pl.col("AVALC") == "PD",
            order_by="AVISITN",
            groups=["USUBJID"],
            inclusive=True,
        ).to_frame()
        expected = [
            "Y",
            "Y",
            "Y",
            "Y",
            "Y",  # USUBJID=1: no PD → all flagged
            "Y",
            "Y",
            None,  # USUBJID=2: PD at visit 1
            "Y",  # USUBJID=3: no PD → all flagged
            "Y",
            "Y",
            "Y",
            None,
            None,  # USUBJID=4: PD at visit 2
        ]
        assert result["ANL02FL"].to_list() == expected

    def test_after_exclusive_no_ref_groups(self):
        """Flag AEs AFTER first COVID AE (exclusive)."""
        adae = pl.DataFrame(
            {
                "USUBJID": ["1", "1", "1", "1", "1", "1", "2", "2"],
                "ASTDY": [2, 5, 5, 17, 27, 32, 8, 11],
                "ACOVFL": [None, "Y", None, None, "Y", None, None, None],
                "AESEQ": [1, 2, 3, 4, 5, 6, 1, 2],
            }
        )
        result = adae.adam.flag(
            "PSTCOVFL",
            criteria="after",
            condition=pl.col("ACOVFL") == "Y",
            order_by=["ASTDY", "AESEQ"],
            groups=["USUBJID"],
            inclusive=False,
            flag_no_ref_groups=False,
        ).to_frame()
        expected = [
            None,
            None,
            "Y",
            "Y",
            "Y",
            "Y",  # USUBJID=1
            None,
            None,  # USUBJID=2: no COVID
        ]
        assert result["PSTCOVFL"].to_list() == expected

    def test_before_requires_condition(self):
        df = pl.DataFrame({"USUBJID": ["1"], "AVISITN": [1]})
        with pytest.raises(ValueError, match="requires condition"):
            df.adam.flag("FL", criteria="before", order_by="AVISITN", groups=["USUBJID"]).to_frame()

    def test_before_requires_order_by(self):
        df = pl.DataFrame({"USUBJID": ["1"], "AVISITN": [1]})
        with pytest.raises(ValueError, match="requires order_by"):
            df.adam.flag(
                "FL",
                criteria="before",
                condition=pl.col("AVISITN") == 1,
                groups=["USUBJID"],
            ).to_frame()


# ====================================================================== #
# 5. Joined Exist Flag — exists_after / exists_before                      #
# ====================================================================== #


class TestFlagExistsAfter:
    """Tests for criteria='exists_after' and 'exists_before'."""

    def test_exists_after_self_join(self):
        """PR followed by CR or PR."""
        data = pl.DataFrame(
            {
                "USUBJID": [
                    "1",
                    "1",
                    "1",
                    "1",
                    "1",
                    "2",
                    "2",
                    "2",
                    "3",
                    "4",
                    "4",
                    "4",
                    "4",
                    "4",
                ],
                "AVISITN": [1, 2, 3, 4, 5, 1, 2, 3, 1, 1, 2, 3, 4, 5],
                "AVALC": [
                    "PR",
                    "CR",
                    "CR",
                    "SD",
                    "NE",
                    "SD",
                    "PR",
                    "PD",
                    "SD",
                    "PR",
                    "PD",
                    "SD",
                    "SD",
                    "PR",
                ],
            }
        )
        result = data.adam.flag(
            "CONFFL",
            criteria="exists_after",
            from_dataset=data,
            on=["USUBJID"],
            condition=(pl.col("AVALC") == "PR"),
            source_filter=pl.col("AVALC").is_in(["CR", "PR"]),
            order_by="AVISITN",
        ).to_frame()
        expected = [
            "Y",
            None,
            None,
            None,
            None,  # USUBJID=1: PR@1 → CR@2
            None,
            None,
            None,  # USUBJID=2: PR@2 → PD
            None,  # USUBJID=3: no PR
            "Y",
            None,
            None,
            None,
            None,  # USUBJID=4: PR@1 → PR@5
        ]
        assert result["CONFFL"].to_list() == expected

    def test_exists_after_requires_from_dataset(self):
        df = pl.DataFrame({"USUBJID": ["1"], "AVISITN": [1], "AVALC": ["PR"]})
        with pytest.raises(ValueError, match="requires from_dataset"):
            df.adam.flag(
                "FL",
                criteria="exists_after",
                condition=pl.col("AVALC") == "PR",
                groups=["USUBJID"],
            ).to_frame()


# ====================================================================== #
# 6. Expression-based flag                                                 #
# ====================================================================== #


class TestFlagExpression:
    """Test direct pl.Expr criteria."""

    def test_direct_expression(self):
        df = pl.DataFrame(
            {
                "USUBJID": ["A", "A", "B"],
                "PARAMCD": ["X", "X", "X"],
                "AVAL": [5.0, 15.0, 10.0],
            }
        )
        result = df.adam.flag("HIGHFL", criteria=pl.col("AVAL") > 8).to_frame()
        assert result["HIGHFL"].to_list() == [None, "Y", "Y"]

    def test_unknown_criteria_raises(self):
        df = pl.DataFrame({"USUBJID": [1], "AVAL": [10]})
        with pytest.raises(ValueError):
            df.adam.flag("FL", criteria="not_a_valid_expr!!!", groups=["USUBJID"]).to_frame()


# ====================================================================== #
# 7. Flag available on all namespaces                                      #
# ====================================================================== #


class TestFlagShared:
    """Verify flag() is available on ADSL and OCCDS namespaces."""

    def test_flag_on_adsl(self):
        df = pl.DataFrame({"USUBJID": ["A", "B"], "AGE": [30, 40]})
        result = df.adam.adsl.flag(
            "AGEGT35",
            criteria=pl.col("AGE") > 35,
        ).to_frame()
        assert result["AGEGT35"].to_list() == [None, "Y"]

    def test_flag_on_occds(self):
        df = pl.DataFrame(
            {
                "USUBJID": ["A", "A"],
                "AESEV": ["MILD", "SEVERE"],
            }
        )
        result = df.adam.occds.flag(
            "SEVFL",
            criteria=pl.col("AESEV") == "SEVERE",
        ).to_frame()
        assert result["SEVFL"].to_list() == [None, "Y"]


# ====================================================================== #
# 8. Criterion — Triple Output                                             #
# ====================================================================== #


class TestCriterion:
    """Tests for criterion() verb."""

    def test_basic_criterion(self):
        """Triple-output: CRITy, CRITyFL, CRITyFN."""
        adlb = pl.DataFrame(
            {
                "USUBJID": ["1", "1", "2"],
                "PARAMCD": ["ALT", "ALT", "ALT"],
                "AVAL": [15.0, 8.0, 12.0],
            }
        )
        result = adlb.adam.criterion(
            1, condition=pl.col("AVAL") >= 10, description="AVAL >= 10"
        ).to_frame()
        assert result["CRIT1"].to_list() == ["AVAL >= 10"] * 3
        assert result["CRIT1FL"].to_list() == ["Y", "N", "Y"]
        assert result["CRIT1FN"].to_list() == [1, 0, 1]

    def test_multiple_criteria(self):
        """Multiple criteria chained."""
        adlb = pl.DataFrame(
            {
                "USUBJID": ["1", "1", "2"],
                "PARAMCD": ["ALT", "ALT", "ALT"],
                "AVAL": [15.0, 8.0, 12.0],
            }
        )
        result = (
            adlb.adam.criterion(1, condition=pl.col("AVAL") >= 10, description="AVAL >= 10")
            .criterion(2, condition=pl.col("AVAL") >= 15, description="AVAL >= 15")
            .to_frame()
        )
        assert result["CRIT1FL"].to_list() == ["Y", "N", "Y"]
        assert result["CRIT2FL"].to_list() == ["Y", "N", "N"]
        assert result["CRIT2FN"].to_list() == [1, 0, 0]

    def test_criterion_no_description(self):
        """criterion without description produces null CRITy."""
        df = pl.DataFrame({"AVAL": [5.0, 15.0]})
        result = df.adam.criterion(1, condition=pl.col("AVAL") > 10).to_frame()
        assert result["CRIT1"].to_list() == [None, None]
        assert result["CRIT1FL"].to_list() == ["N", "Y"]
        assert result["CRIT1FN"].to_list() == [0, 1]

    def test_criterion_custom_prefix(self):
        """Custom prefix works."""
        df = pl.DataFrame({"AVAL": [1.0, 20.0]})
        result = df.adam.criterion(1, condition=pl.col("AVAL") > 10, prefix="MCRIT").to_frame()
        assert "MCRIT1" in result.columns
        assert "MCRIT1FL" in result.columns
        assert "MCRIT1FN" in result.columns

    def test_criterion_on_adsl(self):
        """criterion() available on ADSL namespace."""
        df = pl.DataFrame({"USUBJID": ["A", "B"], "AGE": [30, 70]})
        result = df.adam.adsl.criterion(
            1, condition=pl.col("AGE") >= 65, description="Elderly"
        ).to_frame()
        assert result["CRIT1FL"].to_list() == ["N", "Y"]

    def test_criterion_on_occds(self):
        """criterion() available on OCCDS namespace."""
        df = pl.DataFrame({"USUBJID": ["A", "A"], "AVAL": [3.0, 8.0]})
        result = df.adam.occds.criterion(
            1, condition=pl.col("AVAL") > 5, description="AVAL > 5"
        ).to_frame()
        assert result["CRIT1FL"].to_list() == ["N", "Y"]
