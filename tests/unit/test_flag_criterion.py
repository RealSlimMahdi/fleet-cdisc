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
        input_df = pl.from_repr("""\
┌─────────┬─────────┬──────┐
│ USUBJID ┆ AVISITN ┆ AVAL │
│ ---     ┆ ---     ┆ ---  │
│ i64     ┆ i64     ┆ i64  │
╞═════════╪═════════╪══════╡
│ 1       ┆ 1       ┆ 12   │
│ 1       ┆ 3       ┆ 9    │
│ 2       ┆ 2       ┆ 42   │
│ 3       ┆ 3       ┆ 14   │
│ 3       ┆ 3       ┆ 10   │
└─────────┴─────────┴──────┘
""")
        result = input_df.adam.flag(
            "firstfl",
            criteria="first",
            order_by=["AVISITN", "AVAL"],
            by=["USUBJID"],
        ).to_frame()
        # Ascending lexicographic: (3,10) < (3,14) so AVAL=10 is "first" for USUBJID=3
        assert result["firstfl"].to_list() == ["Y", None, "Y", None, "Y"]

    def test_last_observation_per_group(self):
        """Admiral Test 2: last observation per group."""
        input_df = pl.from_repr("""\
┌─────────┬─────────┬──────┐
│ USUBJID ┆ AVISITN ┆ AVAL │
│ ---     ┆ ---     ┆ ---  │
│ i64     ┆ i64     ┆ i64  │
╞═════════╪═════════╪══════╡
│ 1       ┆ 1       ┆ 12   │
│ 1       ┆ 3       ┆ 9    │
│ 2       ┆ 2       ┆ 42   │
│ 3       ┆ 3       ┆ 14   │
│ 3       ┆ 3       ┆ 10   │
└─────────┴─────────┴──────┘
""")
        result = input_df.adam.flag(
            "lastfl",
            criteria="last",
            order_by=["AVISITN", "AVAL"],
            by=["USUBJID"],
        ).to_frame()
        # Descending: (3,14) > (3,10) so AVAL=14 is "last" for USUBJID=3
        assert result["lastfl"].to_list() == [None, "Y", "Y", "Y", None]

    def test_null_in_order_column(self):
        """Admiral Test 7: NA in order column → never flagged."""
        input_na = pl.from_repr("""\
┌─────────┬─────────┬──────┐
│ USUBJID ┆ AVISITN ┆ AVAL │
│ ---     ┆ ---     ┆ ---  │
│ i64     ┆ i64     ┆ i64  │
╞═════════╪═════════╪══════╡
│ 1       ┆ null    ┆ 12   │
│ 1       ┆ 3       ┆ 9    │
│ 2       ┆ 2       ┆ 42   │
│ 3       ┆ 3       ┆ 14   │
│ 3       ┆ 3       ┆ 10   │
└─────────┴─────────┴──────┘
""")
        result = input_na.adam.flag(
            "firstfl",
            criteria="first",
            order_by=["AVISITN", "AVAL"],
            by=["USUBJID"],
        ).to_frame()
        # Row 0: null AVISITN → None; USUBJID=3: (3,10) < (3,14) → row 4 is first
        assert result["firstfl"].to_list() == [None, "Y", "Y", None, "Y"]

    @pytest.mark.parametrize(
        ("mode", "flag_all", "expected"),
        [
            ("first", False, ["Y", None, "Y", "Y", None, "Y", None]),
            ("last", False, [None, "Y", "Y", None, "Y", None, "Y"]),
            ("first", True, ["Y", None, "Y", "Y", "Y", "Y", "Y"]),
            ("last", True, [None, "Y", "Y", "Y", "Y", "Y", "Y"]),
        ],
    )
    def test_a_missing_order_value_sorts_last_as_admiral(self, mode, flag_all, expected):
        """admiral 1.4.1 derive_var_extreme_flag, run on these rows (ADR-0020).

        dplyr::arrange puts a missing value last in each key: "last" takes the
        missing record (USUBJID 1), and "first" takes one only when every
        record misses the key (USUBJID 4, then AVAL decides).
        """
        input_na = pl.from_repr("""\
┌─────────┬─────────┬──────┐
│ USUBJID ┆ AVISITN ┆ AVAL │
│ ---     ┆ ---     ┆ ---  │
│ i64     ┆ i64     ┆ i64  │
╞═════════╪═════════╪══════╡
│ 1       ┆ 3       ┆ 9    │
│ 1       ┆ null    ┆ 12   │
│ 2       ┆ 2       ┆ 42   │
│ 3       ┆ 3       ┆ 10   │
│ 3       ┆ 3       ┆ 14   │
│ 4       ┆ null    ┆ 5    │
│ 4       ┆ null    ┆ 6    │
└─────────┴─────────┴──────┘
""")
        order_by = ["AVISITN"] if flag_all else ["AVISITN", "AVAL"]

        result = input_na.adam.flag(
            "FL", criteria=mode, order_by=order_by, by=["USUBJID"], flag_all=flag_all
        ).to_frame()

        assert result["FL"].to_list() == expected

    def test_flag_all_ties(self):
        """Admiral Test 4: flag_all=True (ties)."""
        input_ties = pl.from_repr("""\
┌─────────┬─────────┬──────────────────┬─────────┬──────────┬───────┐
│ STUDYID ┆ USUBJID ┆ ADTM             ┆ AVISITN ┆ BASETYPE ┆ PARAM │
│ ---     ┆ ---     ┆ ---              ┆ ---     ┆ ---      ┆ ---   │
│ str     ┆ str     ┆ str              ┆ i64     ┆ str      ┆ str   │
╞═════════╪═════════╪══════════════════╪═════════╪══════════╪═══════╡
│ TEST01  ┆ PAT01   ┆ 2020-02-01T12:00 ┆ 1       ┆ ontrt    ┆ test1 │
│ TEST01  ┆ PAT01   ┆ 2020-02-01T12:00 ┆ 1       ┆ ontrt    ┆ test2 │
│ TEST01  ┆ PAT01   ┆ 2020-02-01T12:01 ┆ 1       ┆ ontrt    ┆ test1 │
│ TEST01  ┆ PAT01   ┆ 2020-02-01T13:00 ┆ 1       ┆ ontrt    ┆ test1 │
│ TEST01  ┆ PAT01   ┆ 2020-02-01T13:00 ┆ 1       ┆ ontrt    ┆ test2 │
└─────────┴─────────┴──────────────────┴─────────┴──────────┴───────┘
""")
        result = input_ties.adam.flag(
            "FIRSTFL",
            criteria="first",
            order_by="ADTM",
            by=["STUDYID", "USUBJID", "BASETYPE", "AVISITN"],
            flag_all=True,
        ).to_frame()
        assert result["FIRSTFL"].to_list() == ["Y", "Y", None, None, None]

    def test_custom_true_false_values(self):
        """Admiral Test 9: custom true/false values."""
        input_df = pl.from_repr("""\
┌─────────┬─────────┬──────┐
│ USUBJID ┆ AVISITN ┆ AVAL │
│ ---     ┆ ---     ┆ ---  │
│ i64     ┆ i64     ┆ i64  │
╞═════════╪═════════╪══════╡
│ 1       ┆ 1       ┆ 12   │
│ 1       ┆ 3       ┆ 9    │
│ 2       ┆ 2       ┆ 42   │
│ 3       ┆ 3       ┆ 14   │
│ 3       ┆ 3       ┆ 10   │
└─────────┴─────────┴──────┘
""")
        result = input_df.adam.flag(
            "firstfl",
            criteria="first",
            order_by=["AVISITN", "AVAL"],
            by=["USUBJID"],
            flag_value="Yes",
            false_value="No",
        ).to_frame()
        # (3,10) < (3,14) so row 4 is "first" for USUBJID=3
        assert result["firstfl"].to_list() == ["Yes", "No", "Yes", "No", "Yes"]

    def test_first_requires_order_by(self):
        """flag criteria='first' raises without order_by."""
        df = pl.from_repr("""\
┌─────────┬──────┐
│ USUBJID ┆ AVAL │
│ ---     ┆ ---  │
│ i64     ┆ i64  │
╞═════════╪══════╡
│ 1       ┆ 10   │
└─────────┴──────┘
""")
        with pytest.raises(ValueError, match="requires order_by"):
            df.adam.flag("FL", criteria="first", by=["USUBJID"]).to_frame()


# ====================================================================== #
# 2. Extreme Flag — Max / Min                                              #
# ====================================================================== #


class TestFlagMaxMin:
    """Tests for criteria='max' and criteria='min'."""

    def test_max_flag(self):
        df = pl.from_repr("""\
┌─────────┬─────────┬──────┐
│ USUBJID ┆ PARAMCD ┆ AVAL │
│ ---     ┆ ---     ┆ ---  │
│ str     ┆ str     ┆ f64  │
╞═════════╪═════════╪══════╡
│ A       ┆ X       ┆ 1.0  │
│ A       ┆ X       ┆ 5.0  │
│ A       ┆ X       ┆ 3.0  │
│ B       ┆ X       ┆ 2.0  │
│ B       ┆ X       ┆ 4.0  │
└─────────┴─────────┴──────┘
""")
        result = df.adam.flag(
            "AMXFL", criteria="max", value_col="AVAL", by=["USUBJID", "PARAMCD"]
        ).to_frame()
        assert result["AMXFL"].to_list() == [None, "Y", None, None, "Y"]

    def test_min_flag(self):
        df = pl.from_repr("""\
┌─────────┬─────────┬──────┐
│ USUBJID ┆ PARAMCD ┆ AVAL │
│ ---     ┆ ---     ┆ ---  │
│ str     ┆ str     ┆ f64  │
╞═════════╪═════════╪══════╡
│ A       ┆ X       ┆ 3.0  │
│ A       ┆ X       ┆ 1.0  │
│ B       ┆ X       ┆ 5.0  │
│ B       ┆ X       ┆ 2.0  │
└─────────┴─────────┴──────┘
""")
        result = df.adam.flag(
            "AMNFL", criteria="min", value_col="AVAL", by=["USUBJID", "PARAMCD"]
        ).to_frame()
        assert result["AMNFL"].to_list() == [None, "Y", None, "Y"]

    def test_max_requires_value_col(self):
        df = pl.from_repr("""\
┌─────────┬──────┐
│ USUBJID ┆ AVAL │
│ ---     ┆ ---  │
│ i64     ┆ i64  │
╞═════════╪══════╡
│ 1       ┆ 10   │
└─────────┴──────┘
""")
        with pytest.raises(ValueError, match="requires value_col"):
            df.adam.flag("FL", criteria="max", by=["USUBJID"]).to_frame()


# ====================================================================== #
# 3. Exist Flag — Single Dataset                                           #
# ====================================================================== #


class TestFlagExists:
    """Tests for criteria='exists'."""

    def test_exist_flag_single_dataset(self):
        """Admiral Test 19: merge existence flag."""
        adsl = pl.from_repr("""\
┌─────────┬─────┬─────────┐
│ USUBJID ┆ SEX ┆ STUDYID │
│ ---     ┆ --- ┆ ---     │
│ str     ┆ str ┆ str     │
╞═════════╪═════╪═════════╡
│ ST42-1  ┆ F   ┆ ST42    │
│ ST42-2  ┆ M   ┆ ST42    │
│ ST42-3  ┆ M   ┆ ST42    │
│ ST42-4  ┆ F   ┆ ST42    │
└─────────┴─────┴─────────┘
""")
        advs = pl.from_repr("""\
┌─────────┬─────────┬──────────┬──────┬─────────┐
│ USUBJID ┆ PARAMCD ┆ AVISIT   ┆ AVAL ┆ STUDYID │
│ ---     ┆ ---     ┆ ---      ┆ ---  ┆ ---     │
│ str     ┆ str     ┆ str      ┆ i64  ┆ str     │
╞═════════╪═════════╪══════════╪══════╪═════════╡
│ ST42-1  ┆ WEIGHT  ┆ BASELINE ┆ 66   ┆ ST42    │
│ ST42-1  ┆ WEIGHT  ┆ Week 2   ┆ 68   ┆ ST42    │
│ ST42-2  ┆ WEIGHT  ┆ BASELINE ┆ 88   ┆ ST42    │
│ ST42-3  ┆ WEIGHT  ┆ Week 2   ┆ 55   ┆ ST42    │
│ ST42-3  ┆ WEIGHT  ┆ Week 4   ┆ 50   ┆ ST42    │
└─────────┴─────────┴──────────┴──────┴─────────┘
""")
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
        dm = pl.from_repr("""\
┌─────────┬─────────┬─────┐
│ STUDYID ┆ USUBJID ┆ AGE │
│ ---     ┆ ---     ┆ --- │
│ str     ┆ str     ┆ i64 │
╞═════════╪═════════╪═════╡
│ PILOT01 ┆ 01-1028 ┆ 71  │
│ PILOT01 ┆ 04-1127 ┆ 84  │
│ PILOT01 ┆ 06-1049 ┆ 68  │
│ PILOT01 ┆ 09-1088 ┆ 69  │
└─────────┴─────────┴─────┘
""")
        ae = pl.from_repr("""\
┌─────────┬─────────┬──────────┐
│ STUDYID ┆ USUBJID ┆ AEREL    │
│ ---     ┆ ---     ┆ ---      │
│ str     ┆ str     ┆ str      │
╞═════════╪═════════╪══════════╡
│ PILOT01 ┆ 01-1028 ┆ POSSIBLE │
│ PILOT01 ┆ 01-1028 ┆ PROBABLE │
│ PILOT01 ┆ 06-1049 ┆ POSSIBLE │
│ PILOT01 ┆ 06-1049 ┆ PROBABLE │
└─────────┴─────────┴──────────┘
""")
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
        adsl = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ 1       │
│ 2       │
│ 3       │
└─────────┘
""")
        cm = pl.from_repr("""\
┌─────────┬─────────────┐
│ USUBJID ┆ CMCAT       │
│ ---     ┆ ---         │
│ str     ┆ str         │
╞═════════╪═════════════╡
│ 1       ┆ ANTI-CANCER │
│ 1       ┆ OTHER       │
│ 2       ┆ ANTI-CANCER │
└─────────┴─────────────┘
""")
        pr = pl.from_repr("""\
┌─────────┬───────────┐
│ USUBJID ┆ PRDECOD   │
│ ---     ┆ ---       │
│ str     ┆ str       │
╞═════════╪═══════════╡
│ 1       ┆ SURGERY   │
│ 3       ┆ RADIATION │
└─────────┴───────────┘
""")
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
        df = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ i64     │
╞═════════╡
│ 1       │
└─────────┘
""")
        with pytest.raises(ValueError, match="requires from_dataset and on"):
            df.adam.flag("FL", criteria="exists", by=["USUBJID"]).to_frame()


# ====================================================================== #
# 4. Relative Flag — Before / After                                        #
# ====================================================================== #


class TestFlagRelative:
    """Tests for criteria='before' and criteria='after'."""

    def test_before_inclusive(self):
        """Flag observations up to first PD (inclusive)."""
        response = pl.from_repr("""\
┌─────────┬─────────┬───────┐
│ USUBJID ┆ AVISITN ┆ AVALC │
│ ---     ┆ ---     ┆ ---   │
│ str     ┆ i64     ┆ str   │
╞═════════╪═════════╪═══════╡
│ 1       ┆ 0       ┆ PR    │
│ 1       ┆ 1       ┆ CR    │
│ 1       ┆ 2       ┆ CR    │
│ 1       ┆ 3       ┆ SD    │
│ 1       ┆ 4       ┆ NE    │
│ 2       ┆ 0       ┆ SD    │
│ 2       ┆ 1       ┆ PD    │
│ 2       ┆ 2       ┆ PD    │
│ 3       ┆ 0       ┆ SD    │
│ 4       ┆ 0       ┆ SD    │
│ 4       ┆ 1       ┆ PR    │
│ 4       ┆ 2       ┆ PD    │
│ 4       ┆ 3       ┆ SD    │
│ 4       ┆ 4       ┆ PR    │
└─────────┴─────────┴───────┘
""")
        result = response.adam.flag(
            "ANL02FL",
            criteria="before",
            condition=pl.col("AVALC") == "PD",
            order_by="AVISITN",
            by=["USUBJID"],
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
        adae = pl.from_repr("""\
┌─────────┬───────┬────────┬───────┐
│ USUBJID ┆ ASTDY ┆ ACOVFL ┆ AESEQ │
│ ---     ┆ ---   ┆ ---    ┆ ---   │
│ str     ┆ i64   ┆ str    ┆ i64   │
╞═════════╪═══════╪════════╪═══════╡
│ 1       ┆ 2     ┆ null   ┆ 1     │
│ 1       ┆ 5     ┆ Y      ┆ 2     │
│ 1       ┆ 5     ┆ null   ┆ 3     │
│ 1       ┆ 17    ┆ null   ┆ 4     │
│ 1       ┆ 27    ┆ Y      ┆ 5     │
│ 1       ┆ 32    ┆ null   ┆ 6     │
│ 2       ┆ 8     ┆ null   ┆ 1     │
│ 2       ┆ 11    ┆ null   ┆ 2     │
└─────────┴───────┴────────┴───────┘
""")
        result = adae.adam.flag(
            "PSTCOVFL",
            criteria="after",
            condition=pl.col("ACOVFL") == "Y",
            order_by=["ASTDY", "AESEQ"],
            by=["USUBJID"],
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
        df = pl.from_repr("""\
┌─────────┬─────────┐
│ USUBJID ┆ AVISITN │
│ ---     ┆ ---     │
│ str     ┆ i64     │
╞═════════╪═════════╡
│ 1       ┆ 1       │
└─────────┴─────────┘
""")
        with pytest.raises(ValueError, match="requires condition"):
            df.adam.flag("FL", criteria="before", order_by="AVISITN", by=["USUBJID"]).to_frame()

    def test_before_requires_order_by(self):
        df = pl.from_repr("""\
┌─────────┬─────────┐
│ USUBJID ┆ AVISITN │
│ ---     ┆ ---     │
│ str     ┆ i64     │
╞═════════╪═════════╡
│ 1       ┆ 1       │
└─────────┴─────────┘
""")
        with pytest.raises(ValueError, match="requires order_by"):
            df.adam.flag(
                "FL",
                criteria="before",
                condition=pl.col("AVISITN") == 1,
                by=["USUBJID"],
            ).to_frame()


# ====================================================================== #
# 5. Joined Exist Flag — exists_after / exists_before                      #
# ====================================================================== #


class TestFlagExistsAfter:
    """Tests for criteria='exists_after' and 'exists_before'."""

    def test_exists_after_self_join(self):
        """PR followed by CR or PR."""
        data = pl.from_repr("""\
┌─────────┬─────────┬───────┐
│ USUBJID ┆ AVISITN ┆ AVALC │
│ ---     ┆ ---     ┆ ---   │
│ str     ┆ i64     ┆ str   │
╞═════════╪═════════╪═══════╡
│ 1       ┆ 1       ┆ PR    │
│ 1       ┆ 2       ┆ CR    │
│ 1       ┆ 3       ┆ CR    │
│ 1       ┆ 4       ┆ SD    │
│ 1       ┆ 5       ┆ NE    │
│ 2       ┆ 1       ┆ SD    │
│ 2       ┆ 2       ┆ PR    │
│ 2       ┆ 3       ┆ PD    │
│ 3       ┆ 1       ┆ SD    │
│ 4       ┆ 1       ┆ PR    │
│ 4       ┆ 2       ┆ PD    │
│ 4       ┆ 3       ┆ SD    │
│ 4       ┆ 4       ┆ SD    │
│ 4       ┆ 5       ┆ PR    │
└─────────┴─────────┴───────┘
""")
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
        df = pl.from_repr("""\
┌─────────┬─────────┬───────┐
│ USUBJID ┆ AVISITN ┆ AVALC │
│ ---     ┆ ---     ┆ ---   │
│ str     ┆ i64     ┆ str   │
╞═════════╪═════════╪═══════╡
│ 1       ┆ 1       ┆ PR    │
└─────────┴─────────┴───────┘
""")
        with pytest.raises(ValueError, match="requires from_dataset"):
            df.adam.flag(
                "FL",
                criteria="exists_after",
                condition=pl.col("AVALC") == "PR",
                by=["USUBJID"],
            ).to_frame()


# ====================================================================== #
# 6. Expression-based flag                                                 #
# ====================================================================== #


class TestFlagExpression:
    """Test direct pl.Expr criteria."""

    def test_direct_expression(self):
        df = pl.from_repr("""\
┌─────────┬─────────┬──────┐
│ USUBJID ┆ PARAMCD ┆ AVAL │
│ ---     ┆ ---     ┆ ---  │
│ str     ┆ str     ┆ f64  │
╞═════════╪═════════╪══════╡
│ A       ┆ X       ┆ 5.0  │
│ A       ┆ X       ┆ 15.0 │
│ B       ┆ X       ┆ 10.0 │
└─────────┴─────────┴──────┘
""")
        result = df.adam.flag("HIGHFL", criteria=pl.col("AVAL") > 8).to_frame()
        assert result["HIGHFL"].to_list() == [None, "Y", "Y"]

    def test_unknown_criteria_raises(self):
        df = pl.from_repr("""\
┌─────────┬──────┐
│ USUBJID ┆ AVAL │
│ ---     ┆ ---  │
│ i64     ┆ i64  │
╞═════════╪══════╡
│ 1       ┆ 10   │
└─────────┴──────┘
""")
        with pytest.raises(ValueError):
            df.adam.flag("FL", criteria="not_a_valid_expr!!!", by=["USUBJID"]).to_frame()


# ====================================================================== #
# 7. Flag available on all namespaces                                      #
# ====================================================================== #


class TestFlagShared:
    """Verify flag() is available on ADSL and OCCDS namespaces."""

    def test_flag_on_adsl(self):
        df = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ AGE │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ A       ┆ 30  │
│ B       ┆ 40  │
└─────────┴─────┘
""")
        result = df.adam.adsl.flag(
            "AGEGT35",
            criteria=pl.col("AGE") > 35,
        ).to_frame()
        assert result["AGEGT35"].to_list() == [None, "Y"]

    def test_flag_on_occds(self):
        df = pl.from_repr("""\
┌─────────┬────────┐
│ USUBJID ┆ AESEV  │
│ ---     ┆ ---    │
│ str     ┆ str    │
╞═════════╪════════╡
│ A       ┆ MILD   │
│ A       ┆ SEVERE │
└─────────┴────────┘
""")
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
        adlb = pl.from_repr("""\
┌─────────┬─────────┬──────┐
│ USUBJID ┆ PARAMCD ┆ AVAL │
│ ---     ┆ ---     ┆ ---  │
│ str     ┆ str     ┆ f64  │
╞═════════╪═════════╪══════╡
│ 1       ┆ ALT     ┆ 15.0 │
│ 1       ┆ ALT     ┆ 8.0  │
│ 2       ┆ ALT     ┆ 12.0 │
└─────────┴─────────┴──────┘
""")
        result = adlb.adam.criterion(
            1, condition=pl.col("AVAL") >= 10, description="AVAL >= 10"
        ).to_frame()
        assert result["CRIT1"].to_list() == ["AVAL >= 10"] * 3
        assert result["CRIT1FL"].to_list() == ["Y", "N", "Y"]
        assert result["CRIT1FN"].to_list() == [1, 0, 1]

    def test_multiple_criteria(self):
        """Multiple criteria chained."""
        adlb = pl.from_repr("""\
┌─────────┬─────────┬──────┐
│ USUBJID ┆ PARAMCD ┆ AVAL │
│ ---     ┆ ---     ┆ ---  │
│ str     ┆ str     ┆ f64  │
╞═════════╪═════════╪══════╡
│ 1       ┆ ALT     ┆ 15.0 │
│ 1       ┆ ALT     ┆ 8.0  │
│ 2       ┆ ALT     ┆ 12.0 │
└─────────┴─────────┴──────┘
""")
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
        df = pl.from_repr("""\
┌──────┐
│ AVAL │
│ ---  │
│ f64  │
╞══════╡
│ 5.0  │
│ 15.0 │
└──────┘
""")
        result = df.adam.criterion(1, condition=pl.col("AVAL") > 10).to_frame()
        assert result["CRIT1"].to_list() == [None, None]
        assert result["CRIT1FL"].to_list() == ["N", "Y"]
        assert result["CRIT1FN"].to_list() == [0, 1]

    def test_null_condition_gives_null_flags_as_admiral(self):
        """c1-204: a missing AVAL is not 'criterion not met' (admiral derive_vars_crit_flag)."""
        adlb = pl.from_repr("""\
┌─────────┬──────┐
│ USUBJID ┆ AVAL │
│ ---     ┆ ---  │
│ str     ┆ f64  │
╞═════════╪══════╡
│ S1      ┆ 12.0 │
│ S2      ┆ null │
│ S3      ┆ 5.0  │
└─────────┴──────┘
""")
        result = adlb.adam.criterion(
            1, condition=pl.col("AVAL") >= 10, description="AVAL >= 10"
        ).to_frame()
        assert result["CRIT1"].to_list() == ["AVAL >= 10"] * 3
        assert result["CRIT1FL"].to_list() == ["Y", None, "N"]
        assert result["CRIT1FN"].to_list() == [1, None, 0]

        not_met = adlb.adam.criterion(
            1, condition=(pl.col("AVAL") >= 10).fill_null(False)
        ).to_frame()
        assert not_met["CRIT1FL"].to_list() == ["Y", "N", "N"]
        assert not_met["CRIT1FN"].to_list() == [1, 0, 0]

    def test_criterion_custom_prefix(self):
        """Custom prefix works."""
        df = pl.from_repr("""\
┌──────┐
│ AVAL │
│ ---  │
│ f64  │
╞══════╡
│ 1.0  │
│ 20.0 │
└──────┘
""")
        result = df.adam.criterion(1, condition=pl.col("AVAL") > 10, prefix="MCRIT").to_frame()
        assert "MCRIT1" in result.columns
        assert "MCRIT1FL" in result.columns
        assert "MCRIT1FN" in result.columns

    def test_criterion_on_adsl(self):
        """criterion() available on ADSL namespace."""
        df = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ AGE │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ A       ┆ 30  │
│ B       ┆ 70  │
└─────────┴─────┘
""")
        result = df.adam.adsl.criterion(
            1, condition=pl.col("AGE") >= 65, description="Elderly"
        ).to_frame()
        assert result["CRIT1FL"].to_list() == ["N", "Y"]

    def test_criterion_on_occds(self):
        """criterion() available on OCCDS namespace."""
        df = pl.from_repr("""\
┌─────────┬──────┐
│ USUBJID ┆ AVAL │
│ ---     ┆ ---  │
│ str     ┆ f64  │
╞═════════╪══════╡
│ A       ┆ 3.0  │
│ A       ┆ 8.0  │
└─────────┴──────┘
""")
        result = df.adam.occds.criterion(
            1, condition=pl.col("AVAL") > 5, description="AVAL > 5"
        ).to_frame()
        assert result["CRIT1FL"].to_list() == ["N", "Y"]
