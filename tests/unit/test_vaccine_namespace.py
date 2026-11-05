"""Unit tests for the Vaccine Polars namespace extension (df.adam.vaccine)."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration
from fleet.core.exceptions import DerivationError

# ---------------------------------------------------------------------------
# LOQ boundary scenarios for aval_adis: follow the rule of admiralvaccine
# test-derive_var_aval_adis.R (below/at/in-range/at-uloq/above); values hand-written
# ---------------------------------------------------------------------------
_LLOQ_ULOQ_CASES = [
    # (stresn, lloq, uloq, orres,  expected_aval, description)
    (1.0, 4.0, 200.0, "1", 2.0, "below LLOQ → lloq/2"),
    (4.0, 4.0, 200.0, "4", 4.0, "exactly at LLOQ → stresn (not below)"),
    (50.0, 4.0, 200.0, "50", 50.0, "in range → stresn"),
    (200.0, 4.0, 200.0, "200", 200.0, "exactly at ULOQ → uloq"),
    (250.0, 4.0, 200.0, "250", 200.0, "above ULOQ → uloq"),
]


@pytest.fixture
def vaccine_frame():
    """Minimal frame for shared verb tests on the vaccine namespace."""
    return pl.from_repr("""\
┌─────────┬──────┬─────┐
│ USUBJID ┆ TEMP ┆ SEX │
│ ---     ┆ ---  ┆ --- │
│ str     ┆ f64  ┆ str │
╞═════════╪══════╪═════╡
│ 01-001  ┆ 37.0 ┆ F   │
│ 01-002  ┆ 38.5 ┆ M   │
│ 01-003  ┆ 39.0 ┆ F   │
└─────────┴──────┴─────┘
""")


class TestBaseVerbs:
    """Shared verbs inherited from SharedADaMVerbsMixin."""

    def test_source(self, vaccine_frame):
        result = vaccine_frame.adam.vaccine.source("USUBJID").to_frame()
        assert "USUBJID" in result.columns

    def test_assigned(self, vaccine_frame):
        result = vaccine_frame.adam.vaccine.assign("STUDYID", value="VAC01").to_frame()
        assert result["STUDYID"].to_list() == ["VAC01"] * 3

    def test_derivation(self, vaccine_frame):
        result = vaccine_frame.adam.vaccine.derivation(
            "TEMP_F", expression='pl.col("TEMP") * 9 / 5 + 32'
        ).to_frame()
        assert result["TEMP_F"][0] == pytest.approx(98.6)

    def test_recode(self, vaccine_frame):
        result = vaccine_frame.adam.vaccine.recode(
            "SEXN", source="SEX", recode_map={"F": "Female", "M": "Male"}
        ).to_frame()
        assert result["SEXN"].to_list() == ["Female", "Male", "Female"]

    def test_rename(self, vaccine_frame):
        result = vaccine_frame.adam.vaccine.assign("SUBJ", source="USUBJID").to_frame()
        assert result["SUBJ"].to_list() == vaccine_frame["USUBJID"].to_list()

    def test_condderivation(self, vaccine_frame):
        result = vaccine_frame.adam.vaccine.case_when(
            "FEVCAT",
            when=[{"condition": 'pl.col("TEMP") >= 38.0', "value": "FEVER"}],
            else_="NORMAL",
        ).to_frame()
        assert result["FEVCAT"].to_list() == ["NORMAL", "FEVER", "FEVER"]

    def test_whereclauses(self, vaccine_frame):
        result = vaccine_frame.adam.vaccine.whereclauses(where='pl.col("TEMP") >= 38.0').to_frame()
        assert result.height == 2


class TestFeverFlag:
    """Test 1: Temperature fever flag — >= threshold by default (FDA 2007, Brighton)."""

    def test_above_threshold_flagged(self):
        df = pl.from_repr("""\
┌──────┐
│ TEMP │
│ ---  │
│ f64  │
╞══════╡
│ 37.0 │
│ 38.1 │
│ 39.0 │
│ 38.0 │
└──────┘
""")
        result = df.adam.vaccine.fever_flag("FEVFL", temp_col="TEMP").to_frame()
        assert result["FEVFL"].to_list() == [None, "Y", "Y", "Y"]

    def test_at_exact_threshold_flagged(self):
        """Exactly AT the threshold flags: grade 1 fever starts at 38.0 C."""
        df = pl.from_repr("""\
┌──────┐
│ TEMP │
│ ---  │
│ f64  │
╞══════╡
│ 38.0 │
└──────┘
""")
        result = df.adam.vaccine.fever_flag("FEVFL", temp_col="TEMP").to_frame()
        assert result["FEVFL"][0] == "Y"

    def test_custom_threshold(self):
        df = pl.from_repr("""\
┌──────┐
│ TEMP │
│ ---  │
│ f64  │
╞══════╡
│ 38.9 │
│ 39.0 │
│ 40.0 │
└──────┘
""")
        result = df.adam.vaccine.fever_flag("HIGHFL", temp_col="TEMP", threshold=39.0).to_frame()
        assert result["HIGHFL"].to_list() == [None, "Y", "Y"]

    def test_inclusive_false_flags_strictly_above(self):
        """FDA 2007 grade 4 is > 40.0 C: 40.0 gets no flag with inclusive=False."""
        df = pl.from_repr("""\
┌──────┐
│ TEMP │
│ ---  │
│ f64  │
╞══════╡
│ 40.0 │
│ 40.1 │
└──────┘
""")
        result = df.adam.vaccine.fever_flag(
            "G4FL", temp_col="TEMP", threshold=40.0, inclusive=False
        ).to_frame()
        assert result["G4FL"].to_list() == [None, "Y"]

    def test_custom_flag_value(self):
        df = pl.from_repr("""\
┌──────┐
│ TEMP │
│ ---  │
│ f64  │
╞══════╡
│ 39.0 │
└──────┘
""")
        result = df.adam.vaccine.fever_flag("FEVFL", temp_col="TEMP", flag_value="1").to_frame()
        assert result["FEVFL"][0] == "1"

    def test_non_derived_columns_preserved(self):
        df = pl.from_repr("""\
┌─────────────┬─────────┬──────┐
│ STUDYID     ┆ USUBJID ┆ TEMP │
│ ---         ┆ ---     ┆ ---  │
│ str         ┆ str     ┆ f64  │
╞═════════════╪═════════╪══════╡
│ VACCSTUDY01 ┆ 01-001  ┆ 39.5 │
└─────────────┴─────────┴──────┘
""")
        result = df.adam.vaccine.fever_flag("FEVFL", temp_col="TEMP").to_frame()
        assert "STUDYID" in result.columns
        assert "USUBJID" in result.columns


class TestSeroconversionFlag:
    """Test 2: ≥N-fold rise from baseline."""

    def test_fourfold_rise_flagged(self):
        df = pl.from_repr("""\
┌────────┬───────┐
│ AVAL   ┆ BASE  │
│ ---    ┆ ---   │
│ f64    ┆ f64   │
╞════════╪═══════╡
│ 400.0  ┆ 100.0 │
│ 1600.0 ┆ 100.0 │
│ 300.0  ┆ 100.0 │
└────────┴───────┘
""")
        result = df.adam.vaccine.seroconversion_flag(
            "SRCONVFL", aval_col="AVAL", base_col="BASE", lloq_col=None
        ).to_frame()
        assert result["SRCONVFL"].to_list() == ["Y", "Y", None]

    def test_exactly_four_fold_flagged(self):
        """Exactly 4.0-fold rise must be flagged (≥ is inclusive)."""
        df = pl.from_repr("""\
┌───────┬───────┐
│ AVAL  ┆ BASE  │
│ ---   ┆ ---   │
│ f64   ┆ f64   │
╞═══════╪═══════╡
│ 400.0 ┆ 100.0 │
└───────┴───────┘
""")
        result = df.adam.vaccine.seroconversion_flag(
            "SRCONVFL", aval_col="AVAL", base_col="BASE", lloq_col=None
        ).to_frame()
        assert result["SRCONVFL"][0] == "Y"

    def test_zero_base_gives_null(self):
        """Zero denominator must produce null, not an error or infinity."""
        df = pl.from_repr("""\
┌───────┬──────┐
│ AVAL  ┆ BASE │
│ ---   ┆ ---  │
│ f64   ┆ f64  │
╞═══════╪══════╡
│ 100.0 ┆ 0.0  │
└───────┴──────┘
""")
        result = df.adam.vaccine.seroconversion_flag(
            "SRCONVFL", aval_col="AVAL", base_col="BASE", lloq_col=None
        ).to_frame()
        assert result["SRCONVFL"][0] is None

    def test_null_base_gives_null(self):
        df = pl.from_repr("""\
┌───────┬──────┐
│ AVAL  ┆ BASE │
│ ---   ┆ ---  │
│ f64   ┆ null │
╞═══════╪══════╡
│ 100.0 ┆ null │
└───────┴──────┘
""")
        result = df.adam.vaccine.seroconversion_flag(
            "SRCONVFL", aval_col="AVAL", base_col="BASE", lloq_col=None
        ).to_frame()
        assert result["SRCONVFL"][0] is None

    def test_custom_fold_rise(self):
        df = pl.from_repr("""\
┌───────┬───────┐
│ AVAL  ┆ BASE  │
│ ---   ┆ ---   │
│ f64   ┆ f64   │
╞═══════╪═══════╡
│ 200.0 ┆ 100.0 │
│ 300.0 ┆ 100.0 │
└───────┴───────┘
""")
        result = df.adam.vaccine.seroconversion_flag(
            "SRCONV2FL", aval_col="AVAL", base_col="BASE", lloq_col=None, fold_rise=2.0
        ).to_frame()
        assert result["SRCONV2FL"].to_list() == ["Y", "Y"]

    def test_lloq_rule_needs_four_times_lloq_below_lloq(self):
        """FDA CBER 2007 HI: pre < 1:10 needs post >= 1:40 (LLOQ 10, BASE LLOQ/2)."""
        df = pl.from_repr("""\
┌─────────┬────────┬────────┬──────┐
│ USUBJID ┆ ISLLOQ ┆ BASE   ┆ AVAL │
│ ---     ┆ ---    ┆ ---    ┆ ---  │
│ str     ┆ f64    ┆ f64    ┆ f64  │
╞═════════╪════════╪════════╪══════╡
│ S01     ┆ 10.0   ┆ 5.0    ┆ 20.0 │
│ S02     ┆ 10.0   ┆ 5.0    ┆ 39.0 │
│ S03     ┆ 10.0   ┆ 5.0    ┆ 40.0 │
│ S12     ┆ 10.0   ┆ 8.0    ┆ 32.0 │
│ S20     ┆ 10.0   ┆ 10.0   ┆ 40.0 │
│ S21     ┆ 10.0   ┆ 20.0   ┆ 79.0 │
│ S30     ┆ null   ┆ 5.0    ┆ 80.0 │
└─────────┴────────┴────────┴──────┘
""")
        lloq = df.adam.vaccine.seroconversion_flag(
            "SRCONVFL", aval_col="AVAL", base_col="BASE", lloq_col="ISLLOQ"
        ).to_frame()
        ratio = df.adam.vaccine.seroconversion_flag(
            "SRCONVFL", aval_col="AVAL", base_col="BASE", lloq_col=None
        ).to_frame()

        assert lloq["SRCONVFL"].to_list() == [None, None, "Y", None, "Y", None, None]
        assert ratio["SRCONVFL"].to_list() == ["Y", "Y", "Y", "Y", "Y", None, "Y"]

    def test_seronegative_fold_sets_the_arm_below_lloq(self):
        df = pl.from_repr("""\
┌────────┬──────┬──────┐
│ ISLLOQ ┆ BASE ┆ AVAL │
│ ---    ┆ ---  ┆ ---  │
│ f64    ┆ f64  ┆ f64  │
╞════════╪══════╪══════╡
│ 8.0    ┆ 4.0  ┆ 8.0  │
│ 8.0    ┆ 4.0  ┆ 7.0  │
└────────┴──────┴──────┘
""")
        result = df.adam.vaccine.seroconversion_flag(
            "SRCONVFL", aval_col="AVAL", base_col="BASE", lloq_col="ISLLOQ", seronegative_fold=1.0
        ).to_frame()
        assert result["SRCONVFL"].to_list() == ["Y", None]

    def test_lloq_col_has_no_default(self):
        df = pl.from_repr("""\
┌──────┬──────┐
│ BASE ┆ AVAL │
│ ---  ┆ ---  │
│ f64  ┆ f64  │
╞══════╪══════╡
│ 5.0  ┆ 20.0 │
└──────┴──────┘
""")
        with pytest.raises(TypeError, match="lloq_col"):
            df.adam.vaccine.seroconversion_flag("SRCONVFL", aval_col="AVAL", base_col="BASE")


class TestSeroresponseFlag:
    """Test 3: Seroresponse — value at or above threshold."""

    def test_above_threshold(self):
        df = pl.from_repr("""\
┌──────┐
│ AVAL │
│ ---  │
│ f64  │
╞══════╡
│ 30.0 │
│ 40.0 │
│ 50.0 │
└──────┘
""")
        result = df.adam.vaccine.seroresponse_flag(
            "SRSFL", aval_col="AVAL", threshold=40.0
        ).to_frame()
        assert result["SRSFL"].to_list() == [None, "Y", "Y"]

    def test_exactly_at_threshold_flagged(self):
        """Exactly AT the threshold must flag (≥ is inclusive)."""
        df = pl.from_repr("""\
┌──────┐
│ AVAL │
│ ---  │
│ f64  │
╞══════╡
│ 40.0 │
└──────┘
""")
        result = df.adam.vaccine.seroresponse_flag(
            "SRSFL", aval_col="AVAL", threshold=40.0
        ).to_frame()
        assert result["SRSFL"][0] == "Y"


class TestAvalAdis:
    """
    Test 4: AVAL derivation with LOQ handling.

    Follows the rule of admiralvaccine derive_var_aval_adis (hand-written values):
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
        df = pl.DataFrame(
            {
                "ISSTRESN": [stresn],
                "ISLLOQ": [lloq],
                "ISULOQ": [uloq],
                "ISORRES": [orres],
            }
        )
        result = df.adam.vaccine.aval_adis(
            "AVAL", stresn_col="ISSTRESN", lloq_col="ISLLOQ", uloq_col="ISULOQ", orres_col="ISORRES"
        ).to_frame()
        assert result["AVAL"][0] == pytest.approx(expected), _desc

    def test_without_a_uloq_column_high_values_stay(self):
        df = pl.from_repr("""
        ┌──────────┬────────┬─────────┐
        │ ISSTRESN ┆ ISLLOQ ┆ ISORRES │
        │ ---      ┆ ---    ┆ ---     │
        │ f64      ┆ f64    ┆ str     │
        ╞══════════╪════════╪═════════╡
        │ 1.0      ┆ 4.0    ┆ 1       │
        │ 50.0     ┆ 4.0    ┆ 50      │
        │ 250.0    ┆ 4.0    ┆ 250     │
        │ null     ┆ 4.0    ┆ <4      │
        │ null     ┆ 4.0    ┆ >200    │
        └──────────┴────────┴─────────┘
        """)
        result = df.adam.vaccine.aval_adis(
            "AVAL", stresn_col="ISSTRESN", lloq_col="ISLLOQ", uloq_col=None, orres_col="ISORRES"
        ).to_frame()
        # No ULOQ: 250 is kept and ">200" with no number gives null; LLOQ / 2 still applies.
        assert result["AVAL"].to_list() == [2.0, 50.0, 250.0, 2.0, None]

    def test_round_digits_rounds_every_branch(self):
        df = pl.from_repr("""
        ┌───────────┬────────┬────────┬───────────┐
        │ ISSTRESN  ┆ ISLLOQ ┆ ISULOQ ┆ ISORRES   │
        │ ---       ┆ ---    ┆ ---    ┆ ---       │
        │ f64       ┆ f64    ┆ f64    ┆ str       │
        ╞═══════════╪════════╪════════╪═══════════╡
        │ 50.123456 ┆ 4.0    ┆ 200.0  ┆ 50.123456 │
        │ 1.0       ┆ 3.0    ┆ 200.0  ┆ 1         │
        │ null      ┆ 4.5    ┆ 200.0  ┆ <4.5      │
        └───────────┴────────┴────────┴───────────┘
        """)
        result = df.adam.vaccine.aval_adis(
            "AVAL",
            stresn_col="ISSTRESN",
            lloq_col="ISLLOQ",
            uloq_col="ISULOQ",
            orres_col="ISORRES",
            round_digits=1,
        ).to_frame()
        # 50.123456 -> 50.1; 3.0 / 2 = 1.5; 4.5 / 2 = 2.25 -> 2.2 (round half to even).
        assert result["AVAL"].to_list() == [50.1, 1.5, 2.2]

    def test_lloq_rule_lloq(self):
        """lloq_rule='lloq' → value below LLOQ returns full LLOQ (not half)."""
        df = pl.from_repr("""\
┌──────────┬────────┬────────┬─────────┐
│ ISSTRESN ┆ ISLLOQ ┆ ISULOQ ┆ ISORRES │
│ ---      ┆ ---    ┆ ---    ┆ ---     │
│ f64      ┆ f64    ┆ f64    ┆ str     │
╞══════════╪════════╪════════╪═════════╡
│ 1.0      ┆ 4.0    ┆ 200.0  ┆ 1       │
└──────────┴────────┴────────┴─────────┘
""")
        result = df.adam.vaccine.aval_adis(
            "AVAL",
            stresn_col="ISSTRESN",
            lloq_col="ISLLOQ",
            uloq_col="ISULOQ",
            orres_col="ISORRES",
            lloq_rule="lloq",
        ).to_frame()
        assert result["AVAL"][0] == pytest.approx(4.0)  # full LLOQ, not 2.0

    def test_missing_stresn_gt_orres(self):
        """Missing STRESN but ISORRES starts with '>' → capped at ULOQ."""
        df = pl.from_repr("""\
┌──────────┬────────┬────────┬─────────┐
│ ISSTRESN ┆ ISLLOQ ┆ ISULOQ ┆ ISORRES │
│ ---      ┆ ---    ┆ ---    ┆ ---     │
│ null     ┆ f64    ┆ f64    ┆ str     │
╞══════════╪════════╪════════╪═════════╡
│ null     ┆ 4.0    ┆ 200.0  ┆ >200    │
└──────────┴────────┴────────┴─────────┘
""")
        result = df.adam.vaccine.aval_adis(
            "AVAL", stresn_col="ISSTRESN", lloq_col="ISLLOQ", uloq_col="ISULOQ", orres_col="ISORRES"
        ).to_frame()
        assert result["AVAL"][0] == pytest.approx(200.0)

    def test_missing_stresn_null_orres_gives_null(self):
        df = pl.from_repr("""\
┌──────────┬────────┬────────┬─────────┐
│ ISSTRESN ┆ ISLLOQ ┆ ISULOQ ┆ ISORRES │
│ ---      ┆ ---    ┆ ---    ┆ ---     │
│ null     ┆ f64    ┆ f64    ┆ null    │
╞══════════╪════════╪════════╪═════════╡
│ null     ┆ 4.0    ┆ 200.0  ┆ null    │
└──────────┴────────┴────────┴─────────┘
""")
        result = df.adam.vaccine.aval_adis(
            "AVAL", stresn_col="ISSTRESN", lloq_col="ISLLOQ", uloq_col="ISULOQ", orres_col="ISORRES"
        ).to_frame()
        assert result["AVAL"][0] is None

    def test_multi_subject_adis_frame(self, adis_frame):
        """
        Full ADIS fixture test — verifies correct LOQ handling across 3 subjects
        and 2 visits each, in the shape of admiral's multi-parameter test 1.
        """
        result = adis_frame.adam.vaccine.aval_adis(
            "AVAL", stresn_col="ISSTRESN", lloq_col="ISLLOQ", uloq_col="ISULOQ", orres_col="ISORRES"
        ).to_frame()
        assert result.height == adis_frame.height
        # Row 0: ISSTRESN=1.0 < ISLLOQ=4.0 → 2.0
        assert result["AVAL"][0] == pytest.approx(2.0)
        # Row 1: ISSTRESN=50.0, in range → 50.0
        assert result["AVAL"][1] == pytest.approx(50.0)


class TestEventFlag:
    """Test 5: Group-level reactogenicity event flag."""

    def test_group_event_flag(self):
        df = pl.from_repr("""\
┌─────────┬─────────┬─────────┬──────┬───────┐
│ USUBJID ┆ FAOBJ   ┆ ATPTREF ┆ AVAL ┆ AVALC │
│ ---     ┆ ---     ┆ ---     ┆ ---  ┆ ---   │
│ str     ┆ str     ┆ str     ┆ f64  ┆ str   │
╞═════════╪═════════╪═════════╪══════╪═══════╡
│ S01     ┆ REDNESS ┆ VAC1    ┆ 3.5  ┆ 3.5   │
│ S01     ┆ REDNESS ┆ VAC1    ┆ 1.0  ┆ 1.0   │
│ S01     ┆ REDNESS ┆ VAC1    ┆ 4.5  ┆ 4.5   │
└─────────┴─────────┴─────────┴──────┴───────┘
""")
        result = df.adam.vaccine.event_flag(
            "EVENTFL", aval_col="AVAL", cutoff=2.5, by=["USUBJID", "FAOBJ", "ATPTREF"]
        ).to_frame()
        # Event occurred (> 2.5) at least once → all rows flagged "Y"
        assert all(f == "Y" for f in result["EVENTFL"].to_list())

    def test_no_event_gives_N_for_all(self):
        """No row exceeds cutoff → all rows in the group should return "N"."""
        df = pl.from_repr("""\
┌─────────┬───────┬─────────┬──────┬───────┐
│ USUBJID ┆ FAOBJ ┆ ATPTREF ┆ AVAL ┆ AVALC │
│ ---     ┆ ---   ┆ ---     ┆ ---  ┆ ---   │
│ str     ┆ str   ┆ str     ┆ f64  ┆ str   │
╞═════════╪═══════╪═════════╪══════╪═══════╡
│ S02     ┆ PAIN  ┆ VAC1    ┆ 1.0  ┆ 1.0   │
│ S02     ┆ PAIN  ┆ VAC1    ┆ 1.5  ┆ 1.5   │
│ S02     ┆ PAIN  ┆ VAC1    ┆ 2.0  ┆ 2.0   │
└─────────┴───────┴─────────┴──────┴───────┘
""")
        result = df.adam.vaccine.event_flag(
            "EVENTFL",
            aval_col="AVAL",
            cutoff=2.5,
            by=["USUBJID", "FAOBJ", "ATPTREF"],
            no_event_value="N",
        ).to_frame()
        assert all(f == "N" for f in result["EVENTFL"].to_list())

    def test_multi_subject_independent_flags(self):
        """Subjects must be evaluated independently."""
        df = pl.from_repr("""\
┌─────────┬───────┬─────────┬──────┬───────┐
│ USUBJID ┆ FAOBJ ┆ ATPTREF ┆ AVAL ┆ AVALC │
│ ---     ┆ ---   ┆ ---     ┆ ---  ┆ ---   │
│ str     ┆ str   ┆ str     ┆ f64  ┆ str   │
╞═════════╪═══════╪═════════╪══════╪═══════╡
│ S01     ┆ REDNS ┆ VAC1    ┆ 3.5  ┆ 3.5   │
│ S01     ┆ REDNS ┆ VAC1    ┆ 1.0  ┆ 1.0   │
│ S02     ┆ REDNS ┆ VAC1    ┆ 1.0  ┆ 1.0   │
│ S02     ┆ REDNS ┆ VAC1    ┆ 2.0  ┆ 2.0   │
└─────────┴───────┴─────────┴──────┴───────┘
""")
        result = df.adam.vaccine.event_flag(
            "EVENTFL",
            aval_col="AVAL",
            cutoff=2.5,
            by=["USUBJID", "FAOBJ", "ATPTREF"],
            no_event_value="N",
        ).to_frame()
        s01_flags = result.filter(pl.col("USUBJID") == "S01")["EVENTFL"].to_list()
        s02_flags = result.filter(pl.col("USUBJID") == "S02")["EVENTFL"].to_list()
        assert all(f == "Y" for f in s01_flags)  # S01 had event
        assert all(f == "N" for f in s02_flags)  # S02 had no event

    def test_no_event_gives_N(self):
        df = pl.from_repr("""\
┌─────────┬───────┬─────────┬──────┬───────┐
│ USUBJID ┆ FAOBJ ┆ ATPTREF ┆ AVAL ┆ AVALC │
│ ---     ┆ ---   ┆ ---     ┆ ---  ┆ ---   │
│ str     ┆ str   ┆ str     ┆ f64  ┆ str   │
╞═════════╪═══════╪═════════╪══════╪═══════╡
│ S02     ┆ PAIN  ┆ VAC1    ┆ 1.0  ┆ 1.0   │
│ S02     ┆ PAIN  ┆ VAC1    ┆ 2.0  ┆ 2.0   │
└─────────┴───────┴─────────┴──────┴───────┘
""")
        result = df.adam.vaccine.event_flag(
            "EVENTFL", aval_col="AVAL", cutoff=2.5, by=["USUBJID", "FAOBJ", "ATPTREF"]
        ).to_frame()
        assert all(f == "N" for f in result["EVENTFL"].to_list())

    def test_avalc_y_counts_and_missing_diary_gives_null(self):
        """admiralvaccine derive_vars_event_flag: AVALC Y is an event; no data gives NA."""
        df = pl.from_repr("""\
┌─────────┬──────────┬─────────┬──────┬──────────┐
│ USUBJID ┆ FAOBJ    ┆ ATPTREF ┆ AVAL ┆ AVALC    │
│ ---     ┆ ---      ┆ ---     ┆ ---  ┆ ---      │
│ str     ┆ str      ┆ str     ┆ f64  ┆ str      │
╞═════════╪══════════╪═════════╪══════╪══════════╡
│ 1       ┆ FATIGUE  ┆ VAC1    ┆ 1.0  ┆ MILD     │
│ 1       ┆ FATIGUE  ┆ VAC1    ┆ 2.0  ┆ MODERATE │
│ 1       ┆ NAUSEA   ┆ VAC1    ┆ null ┆ Y        │
│ 1       ┆ NAUSEA   ┆ VAC1    ┆ null ┆ N        │
│ 1       ┆ PAIN     ┆ VAC1    ┆ null ┆ null     │
│ 1       ┆ PAIN     ┆ VAC1    ┆ null ┆ null     │
│ 1       ┆ VOMITING ┆ VAC1    ┆ null ┆ N        │
│ 1       ┆ REDNESS  ┆ VAC1    ┆ 3.0  ┆ 3.0      │
│ 1       ┆ SWELLING ┆ VAC1    ┆ 1.0  ┆ 1.0      │
└─────────┴──────────┴─────────┴──────┴──────────┘
""")
        result = df.adam.vaccine.event_flag(
            "EVENTFL", aval_col="AVAL", cutoff=2.5, by=["USUBJID", "FAOBJ", "ATPTREF"]
        ).to_frame()
        assert result["EVENTFL"].to_list() == ["Y", "Y", "Y", "Y", None, None, "N", "Y", "N"]

    def test_severity_col_none_and_empty_values(self):
        df = pl.from_repr("""\
┌─────────┬─────────┬─────────┬──────┬───────┐
│ USUBJID ┆ FAOBJ   ┆ ATPTREF ┆ AVAL ┆ AVALC │
│ ---     ┆ ---     ┆ ---     ┆ ---  ┆ ---   │
│ str     ┆ str     ┆ str     ┆ f64  ┆ str   │
╞═════════╪═════════╪═════════╪══════╪═══════╡
│ 1       ┆ FATIGUE ┆ VAC1    ┆ 1.0  ┆ MILD  │
└─────────┴─────────┴─────────┴──────┴───────┘
""")
        by = ["USUBJID", "FAOBJ", "ATPTREF"]
        no_sev = df.adam.vaccine.event_flag(
            "EVENTFL", aval_col="AVAL", cutoff=2.5, by=by, severity_col=None
        ).to_frame()
        empty = df.adam.vaccine.event_flag(
            "EVENTFL", aval_col="AVAL", cutoff=2.5, by=by, severity_values=[]
        ).to_frame()
        assert no_sev["EVENTFL"].to_list() == ["N"]
        assert empty["EVENTFL"].to_list() == ["N"]

    def test_by_is_required(self):
        df = pl.from_repr("""\
┌─────────┬──────┬───────┐
│ USUBJID ┆ AVAL ┆ AVALC │
│ ---     ┆ ---  ┆ ---   │
│ str     ┆ f64  ┆ str   │
╞═════════╪══════╪═══════╡
│ 1       ┆ 3.0  ┆ 3.0   │
└─────────┴──────┴───────┘
""")
        with pytest.raises(TypeError, match="by"):
            df.adam.vaccine.event_flag("EVENTFL", aval_col="AVAL", cutoff=2.5)


@pytest.mark.parametrize("rule", ["HALF", "Half", "half ", "half_lloq", "zero"])
def test_aval_adis_refuses_an_unknown_lloq_rule(rule: str) -> None:
    df = pl.from_repr("""\
┌──────────┬────────┬────────┬─────────┐
│ ISSTRESN ┆ ISLLOQ ┆ ISULOQ ┆ ISORRES │
│ ---      ┆ ---    ┆ ---    ┆ ---     │
│ f64      ┆ f64    ┆ f64    ┆ str     │
╞══════════╪════════╪════════╪═════════╡
│ 1.0      ┆ 4.0    ┆ 200.0  ┆ 1       │
└──────────┴────────┴────────┴─────────┘
""")
    with pytest.raises(DerivationError, match="'half' or 'lloq'"):
        df.adam.vaccine.aval_adis("AVAL", lloq_rule=rule)
