"""Regression tests for the ml-core-a audit findings (shared verbs, lineage, spec path)."""

from __future__ import annotations

import warnings

import polars as pl
import pytest

import fleet  # noqa: F401 — registers the namespaces
from fleet.core.exceptions import ComparisonError, ComparisonFailed, DerivationError

# --------------------------------------------------------------------- #
# c1-26: a type error at to_frame is a DerivationError                    #
# --------------------------------------------------------------------- #

_TEXT_AVAL = pl.from_repr("""\
┌─────────┬──────┐
│ USUBJID ┆ AVAL │
│ ---     ┆ ---  │
│ str     ┆ str  │
╞═════════╪══════╡
│ S1      ┆ 1    │
└─────────┴──────┘
""")


def test_c1_26_arithmetic_on_text_is_a_derivation_error():
    ns = _TEXT_AVAL.adam.derivation("X", expression=pl.col("AVAL") - 1)
    with pytest.raises(DerivationError, match="arithmetic on dtypes str.*derivation"):
        ns.to_frame()


def test_c1_26_comparison_on_text_is_a_derivation_error():
    ns = _TEXT_AVAL.adam.case_when("X", when=[{"condition": pl.col("AVAL") > 1, "value": "Y"}])
    with pytest.raises(DerivationError, match="case_when"):
        ns.to_frame()


def test_c1_26_join_key_type_clash_is_a_derivation_error():
    right = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ AGE │
│ ---     ┆ --- │
│ i64     ┆ i64 │
╞═════════╪═════╡
│ 1       ┆ 50  │
└─────────┴─────┘
""")
    with pytest.raises(DerivationError, match="Pipeline collection failed"):
        _TEXT_AVAL.adam.merge(right, on="USUBJID").to_frame()


# --------------------------------------------------------------------- #
# c1-27 / c1-28: case_when                                               #
# --------------------------------------------------------------------- #


def test_c1_27_a_null_age_takes_else_with_closed_bands():
    adsl = pl.from_repr("""\
┌──────┐
│ AGE  │
│ ---  │
│ i64  │
╞══════╡
│ 30   │
│ 70   │
│ 80   │
│ null │
└──────┘
""")
    out = adsl.adam.case_when(
        "AGEGR1",
        when=[
            {"condition": 'pl.col("AGE") < 65', "value": "<65"},
            {"condition": 'pl.col("AGE").is_between(65, 74)', "value": "65-74"},
            {"condition": 'pl.col("AGE") >= 75', "value": ">=75"},
        ],
        else_="Missing",
    ).to_frame()
    assert out["AGEGR1"].to_list() == ["<65", "65-74", ">=75", "Missing"]


_AGES = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ AGE │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ S1      ┆ 50  │
│ S2      ┆ 70  │
└─────────┴─────┘
""")


def test_c1_28_a_column_value_is_accepted_inline():
    out = _AGES.adam.case_when(
        "X", when=[{"condition": pl.col("AGE") > 60, "value": pl.col("USUBJID")}]
    ).to_frame()
    assert out["X"].to_list() == [None, "S2"]


@pytest.mark.parametrize(
    ("branch", "message"),
    [
        ({"condition": pl.col("AGE") < 65, "value": "<65", "else": ">=65"}, "else_ is a top-level"),
        ({"cond": pl.col("AGE") < 65, "value": "<65"}, "Did you mean 'condition'"),
        ({"condition": pl.col("AGE") < 65, "then": "<65"}, "unknown key 'then'"),
        ({"condition": pl.col("AGE") < 65}, "missing key 'value'"),
    ],
)
def test_c1_28_a_bad_branch_key_is_refused(branch, message):
    with pytest.raises(DerivationError, match=f"case_when\\('X'\\) branch 1: .*{message}"):
        _AGES.adam.case_when("X", when=[branch])


def test_c1_28_the_spec_refuses_an_extra_branch_key():
    from pydantic import ValidationError

    from fleet.core import spec_registry

    with pytest.raises(ValidationError):
        spec_registry.parse_variable_spec(
            "adam",
            {
                "target": "X",
                "algorithm": "case_when",
                "when": [{"condition": "pl.col('AGE') < 65", "value": "a", "else": "b"}],
            },
        )


# --------------------------------------------------------------------- #
# c1-34: assign value=None                                               #
# --------------------------------------------------------------------- #


def test_c1_34_value_none_points_to_a_typed_null_column():
    dm = pl.from_repr("""\
┌─────────┐
│ USUBJID │
│ ---     │
│ str     │
╞═════════╡
│ A       │
└─────────┘
""")
    with pytest.raises(DerivationError, match=r"pl\.lit\(None\)\.cast\(pl\.String\)"):
        dm.sdtm.assign("X", value=None)


# --------------------------------------------------------------------- #
# c1-16: merge keeps the left row order                                  #
# --------------------------------------------------------------------- #


def test_c1_16_inner_merge_keeps_the_left_order_for_any_right_size():
    ae = pl.from_repr("""\
┌─────────┬────────┐
│ USUBJID ┆ AETERM │
│ ---     ┆ ---    │
│ str     ┆ str    │
╞═════════╪════════╡
│ S2      ┆ A      │
│ S1      ┆ B      │
│ S1      ┆ C      │
│ S3      ┆ X      │
└─────────┴────────┘
""")
    for n in (3, 7, 50):
        adsl = pl.DataFrame({"USUBJID": [f"S{i}" for i in range(1, n + 1)], "AGE": range(n)})
        out = ae.adam.merge(adsl, on="USUBJID", how="inner").to_frame()
        assert out["USUBJID"].to_list() == ["S2", "S1", "S1", "S3"]


# --------------------------------------------------------------------- #
# c1-20: nodup with keep= always sorts by subset + sort_by               #
# --------------------------------------------------------------------- #

_AE_NODUP = pl.from_repr("""\
┌─────────┬────────┬───────┐
│ USUBJID ┆ AETERM ┆ AESEQ │
│ ---     ┆ ---    ┆ ---   │
│ str     ┆ str    ┆ i64   │
╞═════════╪════════╪═══════╡
│ S2      ┆ a      ┆ 1     │
│ S2      ┆ b      ┆ 2     │
│ S1      ┆ c      ┆ 1     │
│ S3      ┆ d      ┆ 1     │
└─────────┴────────┴───────┘
""")


def test_c1_20_nodup_order_does_not_depend_on_a_duplicate():
    def run(df: pl.DataFrame) -> list[tuple[str, int]]:
        out = (
            df.sdtm.nodup(subset=["USUBJID", "AETERM"], sort_by=["AESEQ"], keep="first")
            .seq("SEQ", by=["USUBJID"])
            .to_frame()
        )
        return list(zip(out["USUBJID"], out["SEQ"], strict=True))

    plain = run(_AE_NODUP)
    with_dup = run(pl.concat([_AE_NODUP, _AE_NODUP.head(1)]))
    assert plain == with_dup == [("S1", 1), ("S2", 1), ("S2", 2), ("S3", 1)]


def test_c1_20_descending_does_not_reverse_the_key():
    out = _AE_NODUP.sdtm.nodup(
        subset=["USUBJID", "AETERM"], sort_by=["AESEQ"], keep="first", descending=True
    ).to_frame()
    assert out["USUBJID"].to_list() == ["S1", "S2", "S2", "S3"]


# --------------------------------------------------------------------- #
# c1-22: seq sorts by the groups, then order_by                          #
# --------------------------------------------------------------------- #


@pytest.mark.parametrize("namespace", ["sdtm", "adam"])
def test_c1_22_seq_rows_come_back_by_subject(namespace):
    ae = pl.from_repr("""\
┌─────────┬─────────┬────────────┐
│ STUDYID ┆ USUBJID ┆ AESTDTC    │
│ ---     ┆ ---     ┆ ---        │
│ str     ┆ str     ┆ str        │
╞═════════╪═════════╪════════════╡
│ S       ┆ A       ┆ 2024-01-03 │
│ S       ┆ B       ┆ 2024-01-01 │
│ S       ┆ A       ┆ 2024-01-01 │
│ S       ┆ B       ┆ 2024-01-02 │
│ S       ┆ A       ┆ 2024-01-02 │
└─────────┴─────────┴────────────┘
""")
    ns = getattr(ae, namespace)
    if namespace == "adam":
        ns = ns.occds
    out = ns.seq("AESEQ", order_by=["AESTDTC"], by=["STUDYID", "USUBJID"]).to_frame()
    assert out["USUBJID"].to_list() == ["A", "A", "A", "B", "B"]
    assert out["AESEQ"].to_list() == [1, 2, 3, 1, 2]


# --------------------------------------------------------------------- #
# c1-50: ComparisonFailed is the QC finding only                         #
# --------------------------------------------------------------------- #


def test_c1_50_a_difference_raises_comparison_failed():
    base = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ AGE │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ S1      ┆ 50  │
└─────────┴─────┘
""")
    candidate = base.with_columns(pl.lit(51).alias("AGE"))
    with pytest.raises(ComparisonFailed):
        candidate.adam.compare(base, keys="USUBJID", on_fail="raise")


def test_c1_50_a_broken_call_is_not_comparison_failed():
    with pytest.raises(ComparisonError) as info:
        _AGES.adam.compare(_AGES, keys="NOPE", on_fail="raise")
    assert not isinstance(info.value, ComparisonFailed)


# --------------------------------------------------------------------- #
# c1-194: a LazyFrame pin is collected at pin time                        #
# --------------------------------------------------------------------- #

_AE_DAYS = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ AESTDTC    │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ S1      ┆ 2021-03-20 │
│ S2      ┆ 2021-03-02 │
└─────────┴────────────┘
""")

_DM_DAYS = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ RFSTDTC    │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ S1      ┆ 2021-03-01 │
│ S2      ┆ 2021-03-01 │
└─────────┴────────────┘
""")

_ADSL_DAYS = pl.from_repr("""\
┌─────────┬────────────┬─────┐
│ USUBJID ┆ TRTSDT     ┆ AGE │
│ ---     ┆ ---        ┆ --- │
│ str     ┆ date       ┆ i64 │
╞═════════╪════════════╪═════╡
│ S1      ┆ 2021-03-01 ┆ 50  │
│ S2      ┆ 2021-03-01 ┆ 60  │
└─────────┴────────────┴─────┘
""")


@pytest.mark.parametrize("lazy", [False, True])
def test_c1_194_lazy_pin_gives_the_same_study_day(lazy):
    dm = _DM_DAYS.lazy() if lazy else _DM_DAYS
    out = _AE_DAYS.sdtm.pin("DM", dm).study_day("AESTDY", date_col="AESTDTC").to_frame()
    assert out["AESTDY"].to_list() == [20, 2]


@pytest.mark.parametrize("lazy", [False, True])
def test_c1_194_lazy_pin_gives_the_same_join_adsl(lazy):
    adsl = _ADSL_DAYS.lazy() if lazy else _ADSL_DAYS
    out = _AE_DAYS.adam.occds.pin("ADSL", adsl).join_adsl("AGE").to_frame()
    assert out["AGE"].to_list() == [50, 60]


def test_c1_194_repin_refuses_a_value_that_is_not_a_frame():
    with pytest.raises(DerivationError, match="expected a DataFrame or LazyFrame, got str"):
        _AE_DAYS.adam.tte.repin("ADSL", "not a frame")


def test_c1_194_repin_collects_a_lazy_frame():
    ns = _AE_DAYS.adam.repin("ADSL", _ADSL_DAYS.lazy())
    assert isinstance(ns.pins()["ADSL"]["df"], pl.DataFrame)


# --------------------------------------------------------------------- #
# c1-197: the FK check reads the final frame with the last policy         #
# --------------------------------------------------------------------- #

_AE_ORPHAN = pl.from_repr("""\
┌──────┐
│ subj │
│ ---  │
│ str  │
╞══════╡
│ S1   │
│ ORPH │
└──────┘
""")


@pytest.mark.parametrize(
    "build",
    [
        lambda df, dm: df.sdtm.pin("DM", dm).fk_policy("error").assign("USUBJID", source="subj"),
        lambda df, dm: df.sdtm.fk_policy("error").assign("USUBJID", source="subj").pin("DM", dm),
        lambda df, dm: df.sdtm.pin("DM", dm).assign("USUBJID", source="subj").fk_policy("error"),
        lambda df, dm: df.sdtm.assign("USUBJID", source="subj").pin("DM", dm).fk_policy("error"),
        lambda df, dm: df.rename({"subj": "USUBJID"}).sdtm.pin("DM", dm).fk_policy("error"),
    ],
)
def test_c1_197_fk_error_in_any_order(build):
    with pytest.raises(DerivationError, match=r"FK check: 1 value\(s\) in 'USUBJID'.*ORPH"):
        build(_AE_ORPHAN, _DM_DAYS).to_frame()


def test_c1_197_fk_off_set_last_silences_the_check():
    ns = _AE_ORPHAN.sdtm.pin("DM", _DM_DAYS).assign("USUBJID", source="subj").fk_policy("off")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        ns.to_frame()


def test_c1_197_adam_derivation_of_usubjid_is_checked():
    ns = (
        _AE_ORPHAN.adam.pin("ADSL", _ADSL_DAYS)
        .fk_policy("error")
        .derivation("USUBJID", expression=pl.col("subj"))
    )
    with pytest.raises(DerivationError, match="FK check"):
        ns.to_frame()


def test_c1_197_unscheduled_visitnum_is_not_an_fk_finding():
    sv = pl.from_repr("""\
┌─────────┬──────────┐
│ USUBJID ┆ VISITNUM │
│ ---     ┆ ---      │
│ str     ┆ f64      │
╞═════════╪══════════╡
│ S1      ┆ 1.0      │
│ S1      ┆ 1.1      │
└─────────┴──────────┘
""")
    tv = pl.DataFrame({"VISITNUM": [1.0]})
    ns = sv.sdtm.pin("DM", _DM_DAYS).pin("TV", tv, join_on="VISITNUM").fk_policy("error")
    assert ns.to_frame().height == 2


def test_c1_197_an_internal_collect_does_not_check():
    """A filter after merge_adsl drops the orphan before the final frame."""
    ns = (
        _AE_ORPHAN.rename({"subj": "USUBJID"})
        .adam.pin("ADSL", _ADSL_DAYS)
        .fk_policy("error")
        .merge_adsl(_ADSL_DAYS, keep=["AGE"])
        .whereclauses(where=pl.col("USUBJID") != "ORPH")
    )
    assert ns.to_frame()["USUBJID"].to_list() == ["S1"]
