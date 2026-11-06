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
    with pytest.raises(DerivationError, match="key 'USUBJID' is String in the pipeline and Int64"):
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
# c1-20: nodup with keep= always sorts by subset + order_by              #
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
            df.sdtm.nodup(subset=["USUBJID", "AETERM"], order_by=["AESEQ"], keep="first")
            .seq("SEQ", by=["USUBJID"])
            .to_frame()
        )
        return list(zip(out["USUBJID"], out["SEQ"], strict=True))

    plain = run(_AE_NODUP)
    with_dup = run(pl.concat([_AE_NODUP, _AE_NODUP.head(1)]))
    assert plain == with_dup == [("S1", 1), ("S2", 1), ("S2", 2), ("S3", 1)]


def test_c1_20_descending_does_not_reverse_the_key():
    out = _AE_NODUP.sdtm.nodup(
        subset=["USUBJID", "AETERM"], order_by=["AESEQ"], keep="first", descending=True
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


# --------------------------------------------------------------------- #
# c1-8 / c1-11: study_day reference resolution and its lineage           #
# --------------------------------------------------------------------- #


def test_c1_8_study_day_takes_the_pinned_reference_before_the_frame_column():
    ae = pl.from_repr("""\
┌─────────┬────────────┬────────────┐
│ USUBJID ┆ AESTDTC    ┆ RFSTDTC    │
│ ---     ┆ ---        ┆ ---        │
│ str     ┆ str        ┆ str        │
╞═════════╪════════════╪════════════╡
│ 01-701  ┆ 2021-03-20 ┆ 2021-03-10 │
└─────────┴────────────┴────────────┘
""")
    dm = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ RFSTDTC    │
│ ---     ┆ ---        │
│ str     ┆ str        │
╞═════════╪════════════╡
│ 01-701  ┆ 2021-03-01 │
└─────────┴────────────┘
""")
    out = ae.sdtm.pin("DM", dm).study_day("AESTDY", date_col="AESTDTC", ref_pin="DM").to_frame()
    assert out["AESTDY"].to_list() == [20]
    assert out.columns == ["USUBJID", "AESTDTC", "RFSTDTC", "AESTDY"]


_ADAE_ADT = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ ADT        │
│ ---     ┆ ---        │
│ str     ┆ date       │
╞═════════╪════════════╡
│ 01-701  ┆ 2021-03-20 │
└─────────┴────────────┘
""")

_REF_XDT = pl.from_repr("""\
┌─────────┬────────────┐
│ USUBJID ┆ XDT        │
│ ---     ┆ ---        │
│ str     ┆ date       │
╞═════════╪════════════╡
│ 01-701  ┆ 2021-03-01 │
└─────────┴────────────┘
""")


@pytest.mark.parametrize(
    ("namespace", "kwargs", "expected"),
    [
        ("adam", {"ref_df": _REF_XDT}, []),
        ("sdtm", {"ref_df": _REF_XDT}, []),
        ("adam", {"adsl": _REF_XDT}, [("ADSL", ["XDT"])]),
        ("adam", {"dm": _REF_XDT}, [("DM", ["XDT"])]),
        ("sdtm", {"dm": _REF_XDT}, [("DM", ["XDT"])]),
        ("sdtm", {"adsl": _REF_XDT}, [("ADSL", ["XDT"])]),
        ("adam", {"ref_df": _REF_XDT, "ref_pin": "QS"}, [("QS", ["XDT"])]),
    ],
)
def test_c1_11_study_day_records_only_a_named_reference(namespace, kwargs, expected):
    from fleet.core.lineage import pin_lineage_of

    ns = getattr(_ADAE_ADT, namespace).study_day("ADY", date_col="ADT", ref_col="XDT", **kwargs)
    assert ns.to_frame()["ADY"].to_list() == [20]
    assert [(d.source_domain, d.source_cols) for d in pin_lineage_of(ns)] == expected


# --------------------------------------------------------------------- #
# c1-203: trail reads the node pin sources                               #
# --------------------------------------------------------------------- #


def _trail_text(ns, caplog) -> str:
    import logging

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="fleet"):
        ns.trail()
    return "\n".join(r.getMessage() for r in caplog.records)


def test_c1_203_a_literal_after_a_pin_shows_literal(caplog):
    ns = (
        _AE_DAYS.sdtm.pin("DM", _DM_DAYS)
        .study_day("AESTDY", date_col="AESTDTC")
        .assign("AESTDY", value=1)
    )
    rows = _trail_text(ns, caplog).splitlines()
    assert any("study_day" in r and "DM.RFSTDTC" in r for r in rows)
    assert any("assign" in r and "(literal)" in r for r in rows)
    assert not any("assign" in r and "DM.RFSTDTC" in r for r in rows)


def test_c1_203_join_adsl_shows_in_trail(caplog):
    ns = _AE_DAYS.adam.occds.pin("ADSL", _ADSL_DAYS).join_adsl("AGE")
    text = _trail_text(ns, caplog)
    assert "AGE" in text and "ADSL.AGE" in text and "(empty" not in text


def test_c1_203_baseline_flag_records_its_params():
    from fleet.core.lineage import lineage_of

    vs = pl.from_repr("""\
┌─────────┬──────────┬────────────┬─────────┐
│ USUBJID ┆ VSTESTCD ┆ VSDTC      ┆ VSORRES │
│ ---     ┆ ---      ┆ ---        ┆ ---     │
│ str     ┆ str      ┆ str        ┆ str     │
╞═════════╪══════════╪════════════╪═════════╡
│ S1      ┆ SYSBP    ┆ 2021-02-20 ┆ 120     │
└─────────┴──────────┴────────────┴─────────┘
""")
    ns = vs.sdtm.pin("DM", _DM_DAYS).baseline_flag(
        "VSBLFL", date_col="VSDTC", testcd_col="VSTESTCD", ref_col="RFSTDTC"
    )
    node = lineage_of(ns)[-1]
    assert node.params == {
        "target": "VSBLFL",
        "date_col": "VSDTC",
        "testcd_col": "VSTESTCD",
        "ref_col": "RFSTDTC",
        "ref_pin": "DM",
    }


# --------------------------------------------------------------------- #
# c1-199 / c1-200 / c1-201: lineage capture                              #
# --------------------------------------------------------------------- #

_FLAGS = pl.from_repr("""\
┌─────────┬─────────┬───────┬──────┬────────┐
│ USUBJID ┆ AVISITN ┆ ANLFL ┆ AVAL ┆ AVALC  │
│ ---     ┆ ---     ┆ ---   ┆ ---  ┆ ---    │
│ str     ┆ i64     ┆ str   ┆ f64  ┆ str    │
╞═════════╪═════════╪═══════╪══════╪════════╡
│ S1      ┆ 1       ┆ Y     ┆ 1.0  ┆ SD     │
│ S1      ┆ 2       ┆ Y     ┆ 2.0  ┆ PD     │
└─────────┴─────────┴───────┴──────┴────────┘
""")


def _lineage_warnings(record) -> list[str]:
    return [str(w.message) for w in record if w.filename.endswith("lineage.py")]


def test_c1_199_no_lineage_warning_on_an_expression_argument():
    ex = pl.from_repr("""\
┌─────────┬────────┐
│ USUBJID ┆ EXDOSE │
│ ---     ┆ ---    │
│ str     ┆ f64    │
╞═════════╪════════╡
│ S1      ┆ 54.0   │
└─────────┴────────┘
""")
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        _FLAGS.adam.flag_first("F", order_by="AVISITN", where=pl.col("ANLFL") == "Y")
        _FLAGS.adam.flag_exists(
            "SAFFL", from_dataset=ex, on="USUBJID", source_filter=pl.col("EXDOSE") > 0
        )
        _FLAGS.adam.flag_relative(
            "R",
            when="before",
            order_by="AVISITN",
            condition=pl.col("AVALC") == "PD",
            by=["USUBJID"],
        )
    assert _lineage_warnings(record) == []


def test_c1_200_the_ct_warning_names_the_user_line():
    dm = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ sex │
│ ---     ┆ --- │
│ str     ┆ str │
╞═════════╪═════╡
│ S1      ┆ X   │
└─────────┴─────┘
""")

    class SEX:
        _concept_id = "C66731"
        M = "M"
        F = "F"

    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        dm.sdtm.assign("SEX", source="sex", ct=SEX)
    found = [w for w in record if "not in codelist" in str(w.message)]
    assert found and found[0].filename == __file__


def test_c1_201_a_pin_on_a_branch_does_not_reach_the_parent():
    from fleet.core.lineage import lineage_of

    base = _AE_DAYS.adam.occds.pin("ADSL", _ADSL_DAYS).assign("TRTSDT", value="x")
    branch = base.join_adsl("AGE").study_day("ASTDY", date_col="AESTDTC")
    assert all(not n.pin_sources for n in lineage_of(base))
    assert any(n.pin_sources for n in lineage_of(branch))


# --------------------------------------------------------------------- #
# c1-214: flag() refuses by= where no mode uses it                        #
# --------------------------------------------------------------------- #

_EX = pl.from_repr("""\
┌─────────┬────────┐
│ USUBJID ┆ EXDOSE │
│ ---     ┆ ---    │
│ str     ┆ f64    │
╞═════════╪════════╡
│ S1      ┆ 0.0    │
│ S1      ┆ 54.0   │
└─────────┴────────┘
""")


def test_c1_214_expression_flag_with_by_raises():
    from fleet.core.exceptions import VerbUsageError

    with pytest.raises(VerbUsageError, match="by"):
        _EX.sdtm.flag("SAFFL", criteria=pl.col("EXDOSE") > 0, by=["USUBJID"])


def test_c1_214_exists_flag_with_by_raises():
    from fleet.core.exceptions import VerbUsageError

    with pytest.raises(VerbUsageError, match="by"):
        _EX.adam.flag("F", criteria="exists", from_dataset=_EX, on=["USUBJID"], by=["PARAMCD"])


def test_c1_214_expression_flag_without_by_is_a_row_flag():
    out = _EX.sdtm.flag("SAFFL", criteria=pl.col("EXDOSE") > 0).to_frame()
    assert out["SAFFL"].to_list() == [None, "Y"]


# --------------------------------------------------------------------- #
# c1-208 / c1-217: flag_relative and the untested flag paths              #
# --------------------------------------------------------------------- #

_RS = pl.from_repr("""\
┌─────────┬─────────┬───────┬───────┬───────┐
│ USUBJID ┆ AVISITN ┆ AVALC ┆ AVAL  ┆ ANLFL │
│ ---     ┆ ---     ┆ ---   ┆ ---   ┆ ---   │
│ str     ┆ i64     ┆ str   ┆ f64   ┆ str   │
╞═════════╪═════════╪═══════╪═══════╪═══════╡
│ S1      ┆ 3       ┆ SD    ┆ 10.0  ┆ N     │
│ S1      ┆ 1       ┆ SD    ┆ 5.0   ┆ Y     │
│ S1      ┆ 2       ┆ PD    ┆ 3.0   ┆ Y     │
│ S1      ┆ 4       ┆ PD    ┆ 1.0   ┆ Y     │
│ S2      ┆ 1       ┆ SD    ┆ 2.0   ┆ Y     │
│ S2      ┆ 2       ┆ SD    ┆ 4.0   ┆ Y     │
└─────────┴─────────┴───────┴───────┴───────┘
""")


@pytest.mark.parametrize(
    ("when", "inclusive", "no_ref", "expected"),
    [
        ("before", True, True, [None, "Y", "Y", None, "Y", "Y"]),
        ("before", False, True, [None, "Y", None, None, "Y", "Y"]),
        ("after", True, True, ["Y", None, "Y", "Y", "Y", "Y"]),
        ("after", False, False, ["Y", None, None, "Y", None, None]),
    ],
)
def test_c1_208_c1_217_flag_relative_by_hand(when, inclusive, no_ref, expected):
    out = _RS.adam.flag_relative(
        "F",
        when=when,
        condition=pl.col("AVALC") == "PD",
        order_by="AVISITN",
        by=["USUBJID"],
        inclusive=inclusive,
        flag_no_ref_groups=no_ref,
    ).to_frame()
    assert out["F"].to_list() == expected
    assert out.columns == [*_RS.columns, "F"]


def test_c1_208_a_condition_with_its_own_window():
    out = _RS.adam.flag_relative(
        "F",
        when="before",
        condition=pl.col("AVAL") == pl.col("AVAL").max().over("USUBJID"),
        order_by="AVISITN",
        by=["USUBJID"],
    ).to_frame()
    # S1 max AVAL is at visit 3; S2 max AVAL is at visit 2.
    assert out["F"].to_list() == ["Y", "Y", "Y", None, "Y", "Y"]


def test_c1_208_lineage_names_the_condition_columns():
    from fleet.core.lineage import lineage_of

    ns = _RS.adam.flag_relative(
        "F", when="before", condition=pl.col("AVALC") == "PD", order_by="AVISITN"
    )
    node = lineage_of(ns)[-1]
    assert "AVALC" in node.sources
    assert not any(s.startswith("__") for s in node.sources)


def test_c1_217_flag_extreme_with_where_skips_the_global_max():
    out = _RS.adam.flag_extreme(
        "F", value_col="AVAL", by=["USUBJID"], where=pl.col("ANLFL") == "Y"
    ).to_frame()
    assert out["F"].to_list() == [None, "Y", None, None, None, "Y"]


def test_c1_217_flag_expression_with_where():
    out = _RS.adam.flag("F", criteria=pl.col("AVAL") > 2, where=pl.col("ANLFL") == "Y").to_frame()
    assert out["F"].to_list() == [None, "Y", "Y", None, None, "Y"]


def test_c1_217_flag_exists_before_one_key_no_by():
    adae = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ ADY │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ S1      ┆ 5   │
│ S1      ┆ 1   │
│ S2      ┆ 5   │
└─────────┴─────┘
""")
    cm = pl.from_repr("""\
┌─────────┬─────┐
│ USUBJID ┆ ADY │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ S1      ┆ 3   │
└─────────┴─────┘
""")
    out = adae.adam.flag(
        "F",
        criteria="exists_before",
        from_dataset=cm,
        on=["USUBJID"],
        order_by="ADY",
        condition=pl.lit(True),
    ).to_frame()
    assert out["F"].to_list() == ["Y", None, None]


def test_c1_217_join_adsl_keeps_a_subject_not_in_adsl():
    ae = pl.DataFrame({"USUBJID": ["S1", "S9"]})
    out = ae.adam.occds.pin("ADSL", _ADSL_DAYS).join_adsl("AGE").to_frame()
    assert out["USUBJID"].to_list() == ["S1", "S9"]
    assert out["AGE"].to_list() == [50, None]


# --------------------------------------------------------------------- #
# c1-215: a string key or condition is accepted                           #
# --------------------------------------------------------------------- #


def test_c1_215_merge_adsl_by_string():
    ae = pl.DataFrame({"USUBJID": ["S1", "S2"]})
    out = ae.adam.merge_adsl(_ADSL_DAYS, by="USUBJID", keep=["AGE"]).to_frame()
    assert out["AGE"].to_list() == [50, 60]


def test_c1_215_pick_by_string():
    out = _RS.adam.pick(
        "X",
        events=[{"when": pl.col("AVALC") == "PD", "set": {"X": "AVISITN"}}],
        by="USUBJID",
        order_by="AVISITN",
    ).to_frame()
    assert out["X"].to_list() == [2, 2, 2, 2, None, None]


def test_c1_215_string_condition_and_source_filter():
    by_expr = _RS.adam.flag_relative(
        "F", when="before", condition=pl.col("AVALC") == "PD", order_by="AVISITN"
    ).to_frame()
    by_text = _RS.adam.flag_relative(
        "F", when="before", condition='pl.col("AVALC") == "PD"', order_by="AVISITN"
    ).to_frame()
    assert by_text.equals(by_expr)
    out = _RS.adam.flag_exists(
        "F", from_dataset=_RS, on=["USUBJID"], source_filter="pl.col('AVAL') > 5"
    ).to_frame()
    assert out["F"].to_list() == ["Y"] * 4 + [None] * 2
    crit = _RS.adam.criterion(1, condition="pl.col('AVAL') > 5", description="AVAL > 5")
    assert crit.to_frame()["CRIT1FL"].to_list() == ["Y", "N", "N", "N", "N", "N"]


# --------------------------------------------------------------------- #
# Spec registry and from_spec                                           #
# --------------------------------------------------------------------- #


def _write_define(tmp_path, variables, *, dataset="DM", ds_extra=None, **top) -> str:
    import yaml

    spec = {"datasets": [{"name": dataset, **(ds_extra or {}), "variables": variables}], **top}
    path = tmp_path / "define.yaml"
    path.write_text(yaml.safe_dump(spec, sort_keys=False))
    return str(path)


def test_c1_171_case_when_method_text_reads_as_prose():
    from fleet.core.spec_registry import render_method_text

    text = render_method_text(
        "adam",
        "case_when",
        {"when": [{"condition": "pl.col('AGE') < 65", "value": "<65"}], "else": "UNK"},
    )
    assert "if pl.col('AGE') < 65 then <65" in text
    assert "{" not in text


def test_c1_171_an_expression_method_text_warns_in_define_xml(tmp_path):
    from fleet.define_xml.spec_generator import DefineSpecGenerator

    spec = _write_define(
        tmp_path,
        [
            {
                "name": "X",
                "label": "X",
                "type": "text",
                "length": 1,
                "origin": "Derived",
                "derivation": {"algorithm": "derivation", "expression": "pl.col('A') + 1"},
            }
        ],
        study={
            "id": "S01",
            "name": "S01",
            "description": "ml-core-a test study",
            "protocol_name": "S01",
            "originator": "Fleet Tests",
            "standard": "SDTMIG",
            "standard_version": "3.4",
        },
        ds_extra={"label": "Demographics", "structure": "One record per subject", "keys": ["X"]},
    )
    with pytest.warns(UserWarning, match=r"DM\.X: the method text holds a Polars expression"):
        DefineSpecGenerator(spec, enrich_methods=True).to_xml_string()


def test_c1_172_grading_method_texts():
    from fleet.core.spec_registry import render_method_text

    atox = render_method_text(
        "adam", "atoxgr", {"direction": "L", "term_var": "ATOXDSCL", "unit_var": "AVALU"}
    )
    assert atox == "Toxicity grade from ATOXDSCL using the criteria ctcae_v5, direction L."
    assert "takes precedence" in render_method_text("adam", "combine_grades", {})


def test_c1_173_a_record_step_as_a_variable_warns(tmp_path):
    spec = _write_define(
        tmp_path,
        [{"name": "FILTER", "derivation": {"algorithm": "whereclauses", "where": "AGE > 1"}}],
        dataset="ADSL",
    )
    with pytest.warns(UserWarning, match="row_steps"):
        _AGES.adam.from_spec(spec, dataset="ADSL").to_frame()


def test_c1_174_a_sub_namespace_verb_names_the_limit(tmp_path):
    from fleet.core.exceptions import SpecError

    spec = _write_define(
        tmp_path,
        [{"name": "AVALC", "derivation": {"algorithm": "onco.best_overall_response"}}],
        dataset="ADRS",
    )
    with pytest.raises(SpecError, match="inline only in this release"):
        _AGES.adam.from_spec(spec, dataset="ADRS")


def test_c1_175_dotted_paths_keep_the_sub_namespace():
    from fleet.adam.namespace import AdamNamespace
    from fleet.core.lineage import defining_method_path
    from fleet.lsp_server import _ALGORITHM_RE

    assert (
        defining_method_path(AdamNamespace, "onco.best_overall_response")
        == "fleet.adam.onco_namespace.OncoNamespace.best_overall_response"
    )
    assert _ALGORITHM_RE.match("algorithm: occds.treatment_emergent").group(1) == (
        "occds.treatment_emergent"
    )


def test_c1_175_a_dotted_verb_round_trips_through_to_spec_yaml(tmp_path):
    import yaml

    adae = pl.from_repr("""\
┌─────────┬────────────┬────────────┬────────────┐
│ USUBJID ┆ ASTDT      ┆ AENDT      ┆ TRTSDT     │
│ ---     ┆ ---        ┆ ---        ┆ ---        │
│ str     ┆ date       ┆ date       ┆ date       │
╞═════════╪════════════╪════════════╪════════════╡
│ S1      ┆ 2021-03-05 ┆ 2021-03-06 ┆ 2021-03-01 │
│ S2      ┆ 2021-02-05 ┆ 2021-02-06 ┆ 2021-03-01 │
└─────────┴────────────┴────────────┴────────────┘
""")
    ns = adae.adam.occds.treatment_emergent(
        "TRTEMFL", start_date="ASTDT", end_date="AENDT", trtsdt="TRTSDT"
    )
    text = ns.to_spec_yaml(dataset="ADAE")
    blocks = {
        v["name"]: v.get("derivation") for v in yaml.safe_load(text)["datasets"][0]["variables"]
    }
    assert blocks["TRTEMFL"]["algorithm"] == "occds.treatment_emergent"
    path = tmp_path / "define.yaml"
    path.write_text(text)
    again = adae.adam.from_spec(str(path), dataset="ADAE").to_frame()
    assert again["TRTEMFL"].to_list() == ns.to_frame()["TRTEMFL"].to_list()


@pytest.mark.parametrize(
    ("block", "message"),
    [
        ({"algorithm": "nsv", "source": "saf"}, "missing label"),
        ({"algorithm": "nsv", "source": "saf", "value": "Y"}, "exclude each other"),
        ({"algorithm": "assign", "value": None}, "null is not a value"),
    ],
)
def test_c1_176_the_spec_is_never_looser_than_the_verb(tmp_path, block, message):
    from fleet.core.exceptions import SpecError

    dm = pl.from_repr("""\
┌─────────┬─────┬─────┐
│ USUBJID ┆ saf ┆ SEX │
│ ---     ┆ --- ┆ --- │
│ str     ┆ str ┆ str │
╞═════════╪═════╪═════╡
│ A       ┆ N   ┆ M   │
└─────────┴─────┴─────┘
""")
    spec = _write_define(tmp_path, [{"name": "SEX", "derivation": block}])
    with pytest.raises(SpecError, match=message):
        dm.sdtm.from_spec(spec, dataset="DM", overwrite=True).to_frame()


def test_c1_177_formal_expression_names_the_public_namespace():
    from fleet.core.lineage import lineage_of
    from fleet.core.spec_registry import render_formal_expression

    expr = render_formal_expression("adam", "assign", {"source": "AEENDTC"}, target="AENDT")
    assert expr == "fleet.adam.namespace.AdamNamespace.assign('AENDT', source='AEENDTC')"
    ns = pl.DataFrame({"AEENDTC": ["2021"]}).adam.assign("AENDT", source="AEENDTC")
    assert lineage_of(ns)[-1].method == expr.split("(")[0]


def test_c1_54_migrate_spec_drops_depends_on():
    from fleet.tools.migrate_spec import migrate_spec_text

    text = (
        "datasets:\n"
        "  - name: ADVS\n"
        "    variables:\n"
        "      - name: ADY\n"
        "        derivation:\n"
        "          algorithm: duration\n"
        "          start: TRTSDT\n"
        "          end: ADT\n"
        "          depends_on: [ADT]\n"
    )
    new, changes = migrate_spec_text(text, set_version=False)
    assert "depends_on" not in new
    assert any("depends_on" in c for c in changes)


def test_c1_56_a_spec_ct_file_does_not_change_the_global_validator(tmp_path):
    import yaml

    from fleet.ct.validator import get_validator

    ct_file = tmp_path / "ct.yaml"
    ct_file.write_text(yaml.safe_dump({"C99999": {"A": "Alpha"}}))
    before = get_validator().has_codelist("C99999")
    dm = pl.DataFrame({"USUBJID": ["S1"], "raw": ["B"]})
    spec = _write_define(
        tmp_path,
        [{"name": "X", "derivation": {"algorithm": "assign", "source": "raw", "ct": "C99999"}}],
        ct={"validate": True, "file": str(ct_file)},
    )
    with pytest.warns(UserWarning, match="not in codelist 'C99999'"):
        dm.sdtm.from_spec(spec, dataset="DM").to_frame()
    assert get_validator().has_codelist("C99999") == before


def test_c1_37_a_ct_file_without_validate_is_loaded(tmp_path):
    import yaml

    from fleet.core.exceptions import SpecError

    ct_file = tmp_path / "ct.yaml"
    ct_file.write_text(yaml.safe_dump({"C99998": {"A": "Alpha"}}))
    dm = pl.DataFrame({"USUBJID": ["S1"], "raw": ["B"]})
    variables = [
        {"name": "X", "derivation": {"algorithm": "assign", "source": "raw", "ct": "C99998"}}
    ]
    spec = _write_define(tmp_path, variables, ct={"file": str(ct_file)})
    with pytest.warns(UserWarning, match="not in codelist 'C99998'"):
        dm.sdtm.from_spec(spec, dataset="DM").to_frame()
    missing = _write_define(tmp_path, variables, ct={"file": "does_not_exist.yaml"})
    with pytest.raises(SpecError, match="could not be loaded"):
        dm.sdtm.from_spec(missing, dataset="DM")


def test_c1_37_ct_and_codelist_two_c_codes_are_reported(tmp_path):
    from pathlib import Path

    from fleet.ct.study_codelists import ct_codelist_conflicts

    spec = _write_define(
        tmp_path,
        [
            {
                "name": "SEX",
                "codelist": "C66731",
                "derivation": {"algorithm": "assign", "source": "sex", "ct": "C74457"},
            },
            {
                "name": "VSTESTCD",
                "codelist": "CL.VSTEST",
                "derivation": {"algorithm": "assign", "source": "t", "ct": "C66741"},
            },
        ],
    )
    assert ct_codelist_conflicts(Path(spec)) == [
        "DM.SEX: ct C74457 differs from codelist C66731; the values are checked against C74457."
    ]


def test_c1_60_importing_study_code_prints_a_notice(tmp_path, capsys, monkeypatch):
    from fleet.core import _verb_mixin

    (tmp_path / "ml_core_a_study_mod.py").write_text("X = 1\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(_verb_mixin, "_ANNOUNCED_MODULES", set())
    spec = _write_define(
        tmp_path,
        [{"name": "DOMAIN", "derivation": {"algorithm": "assign", "value": "DM"}}],
        derivations_module="ml_core_a_study_mod",
    )
    pl.DataFrame({"USUBJID": ["S1"]}).sdtm.from_spec(spec, dataset="DM")
    assert "importing study code derivations_module 'ml_core_a_study_mod'" in (
        capsys.readouterr().err
    )


# --------------------------------------------------------------------- #
# c1-547: the CDISC Library path takes 3.4 and 3-4                       #
# --------------------------------------------------------------------- #


class _RecordingClient:
    def __init__(self) -> None:
        self.paths: list[str] = []

    def get(self, path: str) -> dict:
        self.paths.append(path)
        return {}


@pytest.mark.parametrize("version", ["3.4", "3-4"])
def test_c1_547_library_paths_use_the_dashed_version(version):
    from fleet.core.scaffolder import DefineScaffolder
    from fleet.ct.generator import extract_ig_concept_ids

    client = _RecordingClient()
    scaffolder = DefineScaffolder(client)
    scaffolder._fetch_sdtm_datasets(version, [])
    scaffolder._fetch_adam_datasets(version.replace("3", "1"), [])
    extract_ig_concept_ids(client, version, ["DM"])
    assert client.paths == [
        "/mdr/sdtmig/3-4/datasets",
        "/mdr/adam/adamig-1-4",
        "/mdr/sdtmig/3-4/datasets",
    ]


# --------------------------------------------------------------------- #
# c1-43: a frame step notes a row change; lineage names real columns     #
# --------------------------------------------------------------------- #


@pytest.fixture
def _clean_transforms():
    from fleet.adam.transforms import clear_transforms

    yield
    clear_transforms()


def _log_text(caplog) -> str:
    return "\n".join(r.getMessage() for r in caplog.records)


@pytest.mark.usefixtures("_clean_transforms")
def test_c1_43_a_frame_derivation_that_drops_rows_is_noted(caplog):
    import logging

    from fleet.core.derivation import derivation

    @derivation(targets=["FLG"])
    def ml_core_a_drop_rows(df: pl.DataFrame) -> pl.DataFrame:
        return df.filter(pl.col("AGE") > 60).with_columns(pl.lit("Y").alias("FLG"))

    with caplog.at_level(logging.INFO, logger="fleet"):
        out = _AGES.adam.derivation(ml_core_a_drop_rows).to_frame()
    assert out.height == 1
    assert "NOTE: derivation ml_core_a_drop_rows: 2 -> 1 rows" in _log_text(caplog)


@pytest.mark.usefixtures("_clean_transforms")
def test_c1_43_lineage_names_only_columns_in_the_frame():
    from fleet.core.derivation import derivation
    from fleet.core.lineage import lineage_of

    @derivation(targets=["DECLARED"])
    def ml_core_a_wrong_target(df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(pl.lit(1).alias("UNDECLARED"))

    with pytest.warns(UserWarning, match=r"declared target\(s\) \['DECLARED'\]"):
        ns = _AGES.adam.derivation(ml_core_a_wrong_target)
    assert [n.name for n in lineage_of(ns)] == []

    @derivation
    def ml_core_a_no_targets(df: pl.DataFrame) -> pl.DataFrame:
        return df.with_columns(pl.lit(1).alias("UNDECLARED"))

    ns = _AGES.adam.derivation(ml_core_a_no_targets)
    assert [n.name for n in lineage_of(ns)] == ["UNDECLARED"]


def test_c1_43_a_transform_that_drops_rows_is_noted(caplog):
    import logging

    with caplog.at_level(logging.INFO, logger="fleet"):
        _AGES.adam.transform(lambda d: d.filter(pl.col("AGE") > 60)).to_frame()
    assert "2 -> 1 rows" in _log_text(caplog)


# --------------------------------------------------------------------- #
# c1-755: one vocabulary; the TTE namespace keeps its dataset name        #
# --------------------------------------------------------------------- #


def test_c1_755_source_from_col_is_removed():
    with pytest.raises(TypeError, match="from_col"):
        pl.DataFrame({"a": [1]}).adam.source("b", from_col="a")
    out = pl.DataFrame({"a": [1]}).adam.assign("b", source="a").to_frame()
    assert out.columns == ["a", "b"]


def test_c1_755_tte_namespace_keeps_adtte():
    ns = pl.DataFrame({"USUBJID": ["S1"]}).lazy().adam.tte
    assert ns._domain == "ADTTE"
    text = ns.assign("STUDYID", value="S").to_spec_yaml()
    assert "name: ADTTE" in text


# --------------------------------------------------------------------- #
# c1-202 / c1-737: to_spec_yaml never writes a block that changes values #
# --------------------------------------------------------------------- #


def _blocks(text: str) -> dict:
    import yaml

    return {
        v["name"]: v.get("derivation") for v in yaml.safe_load(text)["datasets"][0]["variables"]
    }


def test_c1_202_a_target_changed_after_a_read_is_a_stub():
    df = pl.DataFrame({"USUBJID": ["S1", "S2"]})
    ns = (
        df.adam.assign("FLG", value="A")
        .derivation("COPY", expression="pl.col('FLG')")
        .assign("FLG", value="B")
    )
    with pytest.warns(UserWarning, match="FLG is changed after COPY read it"):
        text = ns.to_spec_yaml(dataset="ADX")
    assert _blocks(text)["FLG"] == {"algorithm": "derivation", "callable": "TODO_FLG"}


def test_c1_737_a_target_derived_from_itself_is_a_stub():
    adlb = pl.from_repr("""\
┌─────────┬──────────┐
│ USUBJID ┆ LBSTRESN │
│ ---     ┆ ---      │
│ str     ┆ f64      │
╞═════════╪══════════╡
│ A       ┆ 1.234    │
└─────────┴──────────┘
""")
    ns = adlb.adam.assign("AVAL", source="LBSTRESN").derivation("AVAL", expression="AVAL.round(2)")
    with pytest.warns(UserWarning, match="the last step of AVAL reads AVAL"):
        text = ns.to_spec_yaml(dataset="ADLB")
    assert _blocks(text)["AVAL"]["callable"] == "TODO_AVAL"


def test_c1_737_a_plain_overwrite_still_writes_its_block():
    df = pl.DataFrame({"USUBJID": ["S1"], "a": ["x"], "b": ["y"]})
    ns = df.sdtm.assign("COL", source="a").assign("COL", source="b")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        text = ns.to_spec_yaml(dataset="DM")
    assert _blocks(text)["COL"] == {"algorithm": "assign", "source": "b"}


# --------------------------------------------------------------------- #
# c1-35: one term lookup across the CT stores                            #
# --------------------------------------------------------------------- #


class _SEX:
    _concept_id = "C66731"
    M = "M"
    F = "F"


def test_c1_35_terms_for_asks_the_stores_in_order():
    from fleet.ct.terms import terms_for
    from fleet.ct.validator import CTValidator

    empty = CTValidator()
    assert terms_for(_SEX, validator=empty) == {"M", "F"}
    assert terms_for("C66731", validator=empty, study_classes={"C66731": _SEX}) == {"M", "F"}
    assert terms_for("C1", define_items={"C1": ["A", "B"]}) == {"A", "B"}
    assert terms_for("C2", validator=empty) is None


def test_c1_35_mcp_ct_terms_reads_the_study_classes(monkeypatch):
    pytest.importorskip("mcp", reason="mcp extra (mcp SDK) not installed")
    from fleet import mcp_server
    from fleet.ct import terms

    monkeypatch.setattr(terms, "study_codelist_classes", lambda: {"C99997": _SEX})
    assert mcp_server.fleet_ct_terms("C99997") == ["F", "M"]
