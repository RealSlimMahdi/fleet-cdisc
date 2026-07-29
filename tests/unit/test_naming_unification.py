"""Tests for the §2.1/§2.4 naming unification and discoverability work.

Covers the canonical verbs (``assign`` / ``case_when`` / ``merge`` /
``keep``), the removal of the pre-alpha spellings (old verbs and kwargs
are gone, not shimmed), variadic ``source``, the ``flag`` family + mode
validation, SDTM ``flag`` availability, lazy entry points, and
``verbs()``.
"""

from __future__ import annotations

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration
from fleet.core.exceptions import DerivationError, VerbUsageError

# ------------------------------------------------------------------ #
# Canonical assign()                                                   #
# ------------------------------------------------------------------ #


class TestAssign:
    def test_assign_source(self):
        df = pl.from_repr("""\
┌─────┐
│ sid │
│ --- │
│ str │
╞═════╡
│ A   │
│ B   │
└─────┘
""")
        out = df.sdtm.assign("USUBJID", source="sid").to_frame()
        assert out["USUBJID"].to_list() == ["A", "B"]

    def test_assign_value_sets_domain(self):
        df = pl.from_repr("""\
┌─────┐
│ a   │
│ --- │
│ i64 │
╞═════╡
│ 1   │
└─────┘
""")
        ns = df.sdtm.assign("DOMAIN", value="DM")
        assert ns._domain == "DM"
        assert ns.to_frame()["DOMAIN"].to_list() == ["DM"]

    def test_assign_ct_map(self):
        df = pl.from_repr("""\
┌─────┐
│ sex │
│ --- │
│ str │
╞═════╡
│ 1   │
│ 2   │
└─────┘
""")
        out = df.sdtm.assign("SEX", source="sex", ct_map={"1": "M", "2": "F"}).to_frame()
        assert out["SEX"].to_list() == ["M", "F"]

    def test_assign_requires_exactly_one_of_source_value(self):
        df = pl.from_repr("""\
┌─────┐
│ a   │
│ --- │
│ i64 │
╞═════╡
│ 1   │
└─────┘
""")
        with pytest.raises(DerivationError, match="exactly one"):
            df.sdtm.assign("X")
        with pytest.raises(DerivationError, match="exactly one"):
            df.sdtm.assign("X", source="a", value=1)

    def test_assign_value_with_ct_map_rejected(self):
        df = pl.from_repr("""\
┌─────┐
│ a   │
│ --- │
│ i64 │
╞═════╡
│ 1   │
└─────┘
""")
        with pytest.raises(VerbUsageError, match="ct_map"):
            df.sdtm.assign("X", value="M", ct_map={"M": "M"})

    def test_adam_assign_value(self):
        df = pl.from_repr("""\
┌─────┐
│ a   │
│ --- │
│ i64 │
╞═════╡
│ 1   │
│ 2   │
└─────┘
""")
        out = df.adam.assign("STUDYID", value="S01").to_frame()
        assert out["STUDYID"].to_list() == ["S01", "S01"]


# ------------------------------------------------------------------ #
# case_when                                                            #
# ------------------------------------------------------------------ #


class TestCaseWhen:
    def test_case_when_branches(self):
        df = pl.from_repr("""\
┌─────┐
│ AGE │
│ --- │
│ i64 │
╞═════╡
│ 70  │
│ 50  │
└─────┘
""")
        out = df.adam.case_when(
            "AGEGR1",
            when=[{"condition": 'pl.col("AGE") >= 65', "value": ">=65"}],
            else_="<65",
        ).to_frame()
        assert out["AGEGR1"].to_list() == [">=65", "<65"]

    def test_empty_when_uses_else(self):
        df = pl.from_repr("""\
┌─────┐
│ a   │
│ --- │
│ i64 │
╞═════╡
│ 1   │
└─────┘
""")
        out = df.sdtm.case_when("X", when=[], else_="z").to_frame()
        assert out["X"].to_list() == ["z"]


# ------------------------------------------------------------------ #
# merge / keep                                                         #
# ------------------------------------------------------------------ #


class TestMergeKeep:
    def test_merge_positional_dataset_and_keep(self):
        base = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ S1      │
│ S2      │
└─────────┘
""")
        ref = pl.from_repr("""\
┌─────────┬────────┬─────┐
│ USUBJID ┆ TRTSDT ┆ X   │
│ ---     ┆ ---    ┆ --- │
│ str     ┆ str    ┆ str │
╞═════════╪════════╪═════╡
│ S1      ┆ a      ┆ p   │
│ S2      ┆ b      ┆ q   │
└─────────┴────────┴─────┘
""")
        out = base.sdtm.merge(ref, on="USUBJID", keep=["TRTSDT"]).to_frame()
        assert out.columns == ["USUBJID", "TRTSDT"]

    def test_merge_where_filters_right(self):
        base = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ S1      │
│ S2      │
└─────────┘
""")
        ref = pl.from_repr("""\
┌─────────┬─────┬─────┐
│ USUBJID ┆ FL  ┆ V   │
│ ---     ┆ --- ┆ --- │
│ str     ┆ str ┆ i64 │
╞═════════╪═════╪═════╡
│ S1      ┆ Y   ┆ 1   │
│ S2      ┆ N   ┆ 2   │
└─────────┴─────┴─────┘
""")
        out = base.adam.merge(ref, on="USUBJID", where='pl.col("FL") == "Y"', keep=["V"]).to_frame()
        assert out.sort("USUBJID")["V"].to_list() == [1, None]

    def test_merge_stays_lazy(self):
        base = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ S1      │
└─────────┘
""")
        ref = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ V   │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ S1      ┆ 1   │
└─────────┴─────┘
""")
        ns = base.sdtm.merge(ref, on="USUBJID")
        assert isinstance(ns._lazy, pl.LazyFrame)

    def test_keep_variadic(self):
        df = pl.from_repr("""\
┌─────┬─────┬──────────┐
│ A   ┆ B   ┆ _scratch │
│ --- ┆ --- ┆ ---      │
│ i64 ┆ i64 ┆ i64      │
╞═════╪═════╪══════════╡
│ 1   ┆ 2   ┆ 3        │
└─────┴─────┴──────────┘
""")
        out = df.sdtm.keep("A", "B").to_frame()
        assert out.columns == ["A", "B"]

    def test_keep_list(self):
        df = pl.from_repr("""\
┌─────┬─────┐
│ A   ┆ B   │
│ --- ┆ --- │
│ i64 ┆ i64 │
╞═════╪═════╡
│ 1   ┆ 2   │
└─────┴─────┘
""")
        out = df.sdtm.keep(["B", "A"]).to_frame()
        assert out.columns == ["B", "A"]

    def test_keep_unknown_column_suggests(self):
        df = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ i64     │
╞═════════╡
│ 1       │
└─────────┘
""")
        with pytest.raises(DerivationError, match="USUBJID"):
            df.sdtm.keep("USUBJIX")


# ------------------------------------------------------------------ #
# Old spellings are gone (removed outright, not shimmed)               #
# ------------------------------------------------------------------ #


class TestOldSpellingsRemoved:
    @pytest.mark.parametrize(
        "verb",
        [
            "assign_no_ct",
            "assign_ct",
            "hardcode_no_ct",
            "hardcode_ct",
            "if_then_else",
            "dataset_level",
        ],
    )
    def test_sdtm_old_verbs_gone(self, verb):
        df = pl.from_repr("""\
┌─────┐
│ a   │
│ --- │
│ i64 │
╞═════╡
│ 1   │
└─────┘
""")
        with pytest.raises(AttributeError):
            getattr(df.sdtm, verb)

    @pytest.mark.parametrize("verb", ["assigned", "rename", "condderivation", "lookup"])
    def test_adam_old_verbs_gone(self, verb):
        df = pl.from_repr("""\
┌─────┐
│ a   │
│ --- │
│ i64 │
╞═════╡
│ 1   │
└─────┘
""")
        with pytest.raises(AttributeError):
            getattr(df.adam, verb)

    def test_old_kwarg_groups_gone(self):
        df = pl.from_repr("""\
┌─────────┬──────┐
│ USUBJID ┆ AVAL │
│ ---     ┆ ---  │
│ str     ┆ f64  │
╞═════════╪══════╡
│ A       ┆ 1.0  │
└─────────┴──────┘
""")
        with pytest.raises(TypeError):
            df.adam.flag("MXFL", criteria="max", value_col="AVAL", groups=["USUBJID"])

    def test_old_kwarg_by_vars_gone(self):
        df = pl.from_repr("""\
┌─────────┬─────────┬──────┐
│ USUBJID ┆ PARAMCD ┆ AVAL │
│ ---     ┆ ---     ┆ ---  │
│ str     ┆ str     ┆ f64  │
╞═════════╪═════════╪══════╡
│ A       ┆ X       ┆ 1.0  │
└─────────┴─────────┴──────┘
""")
        with pytest.raises(TypeError):
            df.adam.derive_summary_records(by_vars=["USUBJID"], set_values_to={"DTYPE": "AVERAGE"})

    def test_merge_positional_column_list_gone(self):
        base = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ S1      │
└─────────┘
""")
        with pytest.raises(VerbUsageError, match="DataFrame"):
            base.sdtm.merge(["V"], on="USUBJID")


# ------------------------------------------------------------------ #
# Variadic source                                                     #
# ------------------------------------------------------------------ #


class TestVariadicSource:
    def test_multi_column_carry_through(self):
        df = pl.from_repr("""\
┌─────────┬─────────┬────────┐
│ STUDYID ┆ USUBJID ┆ AETERM │
│ ---     ┆ ---     ┆ ---    │
│ str     ┆ str     ┆ str    │
╞═════════╪═════════╪════════╡
│ S       ┆ 1       ┆ H      │
└─────────┴─────────┴────────┘
""")
        out = df.adam.source("STUDYID", "USUBJID", "AETERM").to_frame()
        assert out.columns == ["STUDYID", "USUBJID", "AETERM"]

    def test_single_from_col_still_works(self):
        df = pl.from_repr("""\
┌─────┐
│ vst │
│ --- │
│ str │
╞═════╡
│ BP  │
└─────┘
""")
        out = df.adam.source("PARAM", from_col="vst").to_frame()
        assert out["PARAM"].to_list() == ["BP"]

    def test_from_col_with_many_targets_rejected(self):
        df = pl.from_repr("""\
┌─────┬─────┐
│ a   ┆ b   │
│ --- ┆ --- │
│ i64 ┆ i64 │
╞═════╪═════╡
│ 1   ┆ 2   │
└─────┴─────┘
""")
        with pytest.raises(DerivationError, match="single target"):
            df.adam.source("a", "b", from_col="a")


# ------------------------------------------------------------------ #
# flag family + mode validation + SDTM flag                            #
# ------------------------------------------------------------------ #


class TestFlagFamily:
    @pytest.fixture
    def advs(self) -> pl.DataFrame:
        return pl.from_repr("""\
┌─────────┬─────────┬─────────┬──────┐
│ USUBJID ┆ PARAMCD ┆ AVISITN ┆ AVAL │
│ ---     ┆ ---     ┆ ---     ┆ ---  │
│ str     ┆ str     ┆ i64     ┆ f64  │
╞═════════╪═════════╪═════════╪══════╡
│ A       ┆ X       ┆ 1       ┆ 5.0  │
│ A       ┆ X       ┆ 2       ┆ 15.0 │
│ B       ┆ X       ┆ 1       ┆ 10.0 │
└─────────┴─────────┴─────────┴──────┘
""")

    def test_flag_first(self, advs):
        out = advs.adam.flag_first("F", order_by="AVISITN", by=["USUBJID", "PARAMCD"]).to_frame()
        assert out["F"].to_list() == ["Y", None, "Y"]

    def test_flag_last(self, advs):
        out = advs.adam.flag_last("F", order_by="AVISITN", by=["USUBJID", "PARAMCD"]).to_frame()
        assert out["F"].to_list() == [None, "Y", "Y"]

    def test_flag_extreme_min(self, advs):
        out = advs.adam.flag_extreme("F", value_col="AVAL", mode="min", by=["USUBJID"]).to_frame()
        assert out["F"].to_list() == ["Y", None, "Y"]

    def test_flag_exists(self):
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
        ae = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ 1       │
│ 3       │
└─────────┘
""")
        out = adsl.adam.adsl.flag_exists("AEFL", from_dataset=ae, on=["USUBJID"]).to_frame()
        assert out["AEFL"].to_list() == ["Y", None, "Y"]

    def test_flag_relative(self):
        rs = pl.from_repr("""\
┌─────────┬─────────┬───────┐
│ USUBJID ┆ AVISITN ┆ AVALC │
│ ---     ┆ ---     ┆ ---   │
│ str     ┆ i64     ┆ str   │
╞═════════╪═════════╪═══════╡
│ 1       ┆ 1       ┆ CR    │
│ 1       ┆ 2       ┆ PD    │
│ 1       ┆ 3       ┆ SD    │
└─────────┴─────────┴───────┘
""")
        out = rs.adam.flag_relative(
            "ANL02FL",
            when="before",
            condition=pl.col("AVALC") == "PD",
            order_by="AVISITN",
            by=["USUBJID"],
        ).to_frame()
        assert out["ANL02FL"].to_list() == ["Y", "Y", None]

    def test_irrelevant_param_raises(self, advs):
        with pytest.raises(VerbUsageError, match="value_col"):
            advs.adam.flag("F", criteria="first", order_by="AVISITN", value_col="AVAL")

    def test_irrelevant_order_by_for_max_raises(self, advs):
        with pytest.raises(VerbUsageError, match="order_by"):
            advs.adam.flag("F", criteria="max", value_col="AVAL", order_by="AVISITN")

    def test_expression_criteria_allows_where(self, advs):
        out = advs.adam.flag(
            "F", criteria=pl.col("AVAL") > 8, where='pl.col("PARAMCD") == "X"'
        ).to_frame()
        assert out["F"].to_list() == [None, "Y", "Y"]

    def test_sdtm_has_flag(self):
        dm = pl.from_repr("""\
┌─────────┬────────┐
│ USUBJID ┆ EXDOSE │
│ ---     ┆ ---    │
│ str     ┆ i64    │
╞═════════╪════════╡
│ A       ┆ 1      │
│ B       ┆ 0      │
└─────────┴────────┘
""")
        out = dm.sdtm.flag("SAFFL", criteria='pl.col("EXDOSE") > 0').to_frame()
        assert out["SAFFL"].to_list() == ["Y", None]

    def test_sdtm_flag_family_present(self):
        dm = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ A       │
└─────────┘
""")
        assert hasattr(dm.sdtm, "flag_first")
        assert hasattr(dm.sdtm, "criterion")


# ------------------------------------------------------------------ #
# Lazy entry points                                                   #
# ------------------------------------------------------------------ #


class TestLazyEntry:
    def test_lazyframe_sdtm_namespace(self):
        lf = pl.LazyFrame({"sid": ["A", "B"]})
        ns = lf.sdtm.assign("USUBJID", source="sid")
        assert isinstance(ns._lazy, pl.LazyFrame)
        assert ns.to_frame()["USUBJID"].to_list() == ["A", "B"]

    def test_lazyframe_adam_and_subns(self):
        lf = pl.LazyFrame({"USUBJID": ["A"]})
        assert lf.adam.source("USUBJID").to_frame()["USUBJID"].to_list() == ["A"]
        assert lf.adsl.source("USUBJID").to_frame()["USUBJID"].to_list() == ["A"]
        assert lf.occds.source("USUBJID").to_frame()["USUBJID"].to_list() == ["A"]

    def test_scan_parquet_end_to_end(self, tmp_path):
        p = tmp_path / "raw.parquet"
        pl.from_repr("""\
┌─────┬─────┐
│ sid ┆ sex │
│ --- ┆ --- │
│ str ┆ str │
╞═════╪═════╡
│ A   ┆ M   │
│ B   ┆ F   │
└─────┴─────┘
""").write_parquet(p)
        out = pl.scan_parquet(p).sdtm.assign("USUBJID", source="sid").to_frame()
        assert out["USUBJID"].to_list() == ["A", "B"]


# ------------------------------------------------------------------ #
# verbs() listing                                                     #
# ------------------------------------------------------------------ #


class TestVerbsListing:
    def test_sdtm_verbs_frame_shape(self):
        df = pl.from_repr("""\
┌─────┐
│ a   │
│ --- │
│ i64 │
╞═════╡
│ 1   │
└─────┘
""")
        v = df.sdtm.verbs()
        assert v.columns == ["verb", "summary"]
        assert v.height > 0

    def test_canonical_verbs_present(self):
        df = pl.from_repr("""\
┌─────┐
│ a   │
│ --- │
│ i64 │
╞═════╡
│ 1   │
└─────┘
""")
        names = set(df.sdtm.verbs()["verb"].to_list())
        assert {"assign", "case_when", "merge", "keep", "flag"} <= names

    def test_removed_spellings_not_listed(self):
        df = pl.from_repr("""\
┌─────┐
│ a   │
│ --- │
│ i64 │
╞═════╡
│ 1   │
└─────┘
""")
        names = set(df.sdtm.verbs()["verb"].to_list())
        assert "assign_no_ct" not in names
        assert "hardcode_no_ct" not in names
        assert "if_then_else" not in names

    def test_adam_verbs_exclude_removed_spellings(self):
        df = pl.from_repr("""\
┌─────┐
│ a   │
│ --- │
│ i64 │
╞═════╡
│ 1   │
└─────┘
""")
        names = set(df.adam.verbs()["verb"].to_list())
        assert "assign" in names
        assert "assigned" not in names
        assert "rename" not in names
        assert "lookup" not in names

    def test_verbs_summary_is_first_sentence(self):
        df = pl.from_repr("""\
┌─────┐
│ a   │
│ --- │
│ i64 │
╞═════╡
│ 1   │
└─────┘
""")
        v = df.sdtm.verbs().filter(pl.col("verb") == "assign")
        assert v["summary"][0].startswith("Assign")


# ------------------------------------------------------------------ #
# study_day aliases                                                   #
# ------------------------------------------------------------------ #


class TestStudyDayAliases:
    def test_dm_alias(self):
        ae = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ AESTDTC    │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ S1      ┆ 2014-01-05 │
└─────────┴────────────┘
""")
        dm = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ RFSTDTC    │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ S1      ┆ 2014-01-02 │
└─────────┴────────────┘
""")
        out = ae.sdtm.study_day("AESTDY", date_col="AESTDTC", dm=dm).to_frame()
        assert out["AESTDY"].to_list() == [4]

    def test_adsl_alias(self):
        ae = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ ASTDT      │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ S1      ┆ 2014-01-05 │
└─────────┴────────────┘
""")
        adsl = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ TRTSDT     │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ S1      ┆ 2014-01-02 │
└─────────┴────────────┘
""")
        out = ae.adam.study_day("ASTDY", date_col="ASTDT", adsl=adsl).to_frame()
        assert out["ASTDY"].to_list() == [4]

    def test_multiple_ref_aliases_rejected(self):
        ae = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ ASTDT      │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ S1      ┆ 2014-01-05 │
└─────────┴────────────┘
""")
        adsl = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ TRTSDT     │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ S1      ┆ 2014-01-02 │
└─────────┴────────────┘
""")
        with pytest.raises(VerbUsageError):
            ae.adam.study_day("ASTDY", date_col="ASTDT", adsl=adsl, ref_df=adsl)
