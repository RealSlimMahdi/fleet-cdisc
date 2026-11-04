"""Regression tests for the BDS record verbs (c1-317, c1-318, c1-323, c1-324)."""

import polars as pl
import pytest

from fleet.core.exceptions import DerivationError

ADQS = """\
┌─────────┬─────────┬──────────┬─────────┬────────────┬──────┐
│ USUBJID ┆ PARAMCD ┆ AVISIT   ┆ AVISITN ┆ ADT        ┆ AVAL │
│ ---     ┆ ---     ┆ ---      ┆ ---     ┆ ---        ┆ ---  │
│ str     ┆ str     ┆ str      ┆ i64     ┆ date       ┆ f64  │
╞═════════╪═════════╪══════════╪═════════╪════════════╪══════╡
│ S01     ┆ ACTOT   ┆ BASELINE ┆ 0       ┆ 2024-01-01 ┆ 20.0 │
│ S01     ┆ ACTOT   ┆ WEEK 8   ┆ 8       ┆ 2024-02-26 ┆ null │
│ S01     ┆ ACTOT   ┆ WEEK 16  ┆ 16      ┆ 2024-04-22 ┆ 24.0 │
│ S02     ┆ ACTOT   ┆ WEEK 8   ┆ 8       ┆ 2024-02-20 ┆ 18.0 │
└─────────┴─────────┴──────────┴─────────┴────────────┴──────┘
"""

VISITS = pl.from_repr("""\
┌──────────┬─────────┐
│ AVISIT   ┆ AVISITN │
│ ---      ┆ ---     │
│ str      ┆ i64     │
╞══════════╪═════════╡
│ BASELINE ┆ 0       │
│ WEEK 8   ┆ 8       │
│ WEEK 16  ┆ 16      │
│ WEEK 24  ┆ 24      │
└──────────┴─────────┘
""")

# admiral 1.4.1 derive_locf_records(order = exprs(AVISITN)) on ADQS and VISITS,
# rows as (USUBJID, AVISITN, AVAL, DTYPE), sorted.
ADMIRAL_ADD = [
    ("S01", 0, 20.0, None),
    ("S01", 8, 20.0, "LOCF"),
    ("S01", 8, None, None),
    ("S01", 16, 24.0, None),
    ("S01", 24, 24.0, "LOCF"),
    ("S02", 0, None, "LOCF"),
    ("S02", 8, 18.0, None),
    ("S02", 16, 18.0, "LOCF"),
    ("S02", 24, 18.0, "LOCF"),
]
ADMIRAL_UPDATE = [r for r in ADMIRAL_ADD if r != ("S01", 8, None, None)]


def _locf(df: pl.DataFrame, **kwargs) -> pl.DataFrame:
    return df.adam.derive_locf_records(
        dataset_ref=VISITS, by=["USUBJID", "PARAMCD"], order_by=["AVISITN"], **kwargs
    ).to_frame()


def _rows(out: pl.DataFrame) -> list[tuple]:
    return sorted(
        out.select("USUBJID", "AVISITN", "AVAL", "DTYPE").rows(),
        key=lambda r: (r[0], r[1], r[2] is None, r[3] is None),
    )


@pytest.mark.parametrize(
    ("imputation", "expected"),
    [("add", ADMIRAL_ADD), ("update", ADMIRAL_UPDATE), ("update_add", ADMIRAL_ADD)],
)
def test_locf_matches_admiral(imputation: str, expected: list[tuple]) -> None:
    out = _locf(pl.from_repr(ADQS), imputation=imputation)
    assert _rows(out) == expected


def test_locf_add_is_the_default_and_keeps_input_rows() -> None:
    adqs = pl.from_repr(ADQS)
    out = _locf(adqs)
    assert out.height == 9
    kept = out.filter(pl.col("DTYPE").is_null()).drop("DTYPE")
    assert kept.sort("USUBJID", "AVISITN").equals(adqs.sort("USUBJID", "AVISITN"))
    new = out.filter(pl.col("DTYPE") == "LOCF")
    assert new["ADT"].null_count() == new.height


def test_update_add_keeps_the_collected_date_on_the_updated_row() -> None:
    out = _locf(pl.from_repr(ADQS), imputation="update_add")
    week8 = out.filter((pl.col("USUBJID") == "S01") & (pl.col("AVISITN") == 8))
    assert week8.height == 2
    assert week8["ADT"].cast(pl.String).to_list() == ["2024-02-26", "2024-02-26"]


def test_locf_keeps_an_existing_dtype() -> None:
    adqs = pl.from_repr(ADQS).with_columns(
        pl.when(pl.col("AVISITN") == 16).then(pl.lit("AVERAGE")).alias("DTYPE")
    )
    out = _locf(adqs)
    s01 = out.filter((pl.col("USUBJID") == "S01") & (pl.col("AVISITN") == 16))
    assert s01["DTYPE"].to_list() == ["AVERAGE"]
    assert out.filter(pl.col("DTYPE") == "LOCF").height == 5


def test_locf_first_order_column_must_be_in_dataset_ref() -> None:
    with pytest.raises(DerivationError, match="not in dataset_ref"):
        pl.from_repr(ADQS).adam.derive_locf_records(
            dataset_ref=VISITS, by=["USUBJID", "PARAMCD"], order_by="ADT"
        )


def test_locf_null_order_value_raises() -> None:
    adqs = pl.from_repr(ADQS).with_columns(
        pl.when(pl.col("AVISITN") == 16).then(None).otherwise(pl.col("AVISITN")).alias("AVISITN")
    )
    with pytest.raises(DerivationError, match="null value in order_by"):
        _locf(adqs)


def test_locf_order_by_is_required() -> None:
    with pytest.raises(TypeError):
        pl.from_repr(ADQS).adam.derive_locf_records(  # type: ignore[call-arg]
            dataset_ref=VISITS, by=["USUBJID", "PARAMCD"]
        )


def test_locf_unknown_imputation_raises() -> None:
    with pytest.raises(DerivationError, match="imputation"):
        _locf(pl.from_repr(ADQS), imputation="replace")


def test_locf_undated_missed_visits_follow_visit_order() -> None:
    adqs = pl.from_repr("""\
┌─────────┬─────────┬──────────┬─────────┬────────────┬──────┐
│ USUBJID ┆ PARAMCD ┆ AVISIT   ┆ AVISITN ┆ ADT        ┆ AVAL │
│ ---     ┆ ---     ┆ ---      ┆ ---     ┆ ---        ┆ ---  │
│ str     ┆ str     ┆ str      ┆ i64     ┆ date       ┆ f64  │
╞═════════╪═════════╪══════════╪═════════╪════════════╪══════╡
│ S01     ┆ ACTOT   ┆ BASELINE ┆ 0       ┆ 2024-01-01 ┆ 20.0 │
│ S01     ┆ ACTOT   ┆ WEEK 8   ┆ 8       ┆ null       ┆ null │
│ S01     ┆ ACTOT   ┆ WEEK 16  ┆ 16      ┆ 2024-04-22 ┆ 24.0 │
│ S01     ┆ ACTOT   ┆ WEEK 24  ┆ 24      ┆ null       ┆ null │
└─────────┴─────────┴──────────┴─────────┴────────────┴──────┘
""")
    out = _locf(adqs, imputation="update").sort("AVISITN")
    assert out["AVAL"].to_list() == [20.0, 20.0, 24.0, 24.0]


def test_locf_keep_vars_are_carried() -> None:
    adqs = pl.from_repr(ADQS).with_columns(pl.lit("ADAS-Cog total").alias("PARAM"))
    out = _locf(adqs, keep_vars=["PARAM"])
    s01_w24 = out.filter((pl.col("USUBJID") == "S01") & (pl.col("AVISITN") == 24))
    assert s01_w24["PARAM"].to_list() == ["ADAS-Cog total"]


# ── derive_summary_records ────────────────────────────────────────────────

ADEG = """\
┌─────────┬─────────┬────────┬───────┬───────┐
│ USUBJID ┆ PARAMCD ┆ AVISIT ┆ ATPTN ┆ AVAL  │
│ ---     ┆ ---     ┆ ---    ┆ ---   ┆ ---   │
│ str     ┆ str     ┆ str    ┆ i64   ┆ f64   │
╞═════════╪═════════╪════════╪═══════╪═══════╡
│ S01     ┆ QTCF    ┆ WEEK 2 ┆ 1     ┆ 400.1 │
│ S01     ┆ QTCF    ┆ WEEK 2 ┆ 2     ┆ 410.2 │
└─────────┴─────────┴────────┴───────┴───────┘
"""
BY = ["USUBJID", "PARAMCD", "AVISIT"]


def test_summary_where_excludes_derived_rows() -> None:
    out = (
        pl.from_repr(ADEG)
        .adam.derive_summary_records(by=BY, set_values_to={"DTYPE": "MAX"}, stat="max")
        .derive_summary_records(
            by=BY,
            set_values_to={"DTYPE": "AVERAGE"},
            stat="mean",
            where=pl.col("DTYPE").is_null(),
        )
        .to_frame()
    )
    avg = out.filter(pl.col("DTYPE") == "AVERAGE")["AVAL"].to_list()
    assert avg == [pytest.approx(405.15)]
    assert out.height == 4


def test_summary_where_accepts_a_string() -> None:
    out = (
        pl.from_repr(ADEG)
        .adam.derive_summary_records(
            by=BY, set_values_to={"DTYPE": "MAX"}, stat="max", where='pl.col("ATPTN") == 1'
        )
        .to_frame()
    )
    assert out.filter(pl.col("DTYPE") == "MAX")["AVAL"].to_list() == [400.1]


def test_summary_warns_on_derived_rows_without_where() -> None:
    first = pl.from_repr(ADEG).adam.derive_summary_records(
        by=BY, set_values_to={"DTYPE": "MAX"}, stat="max"
    )
    with pytest.warns(UserWarning, match="non-null DTYPE"):
        first.derive_summary_records(by=BY, set_values_to={"DTYPE": "AVERAGE"}, stat="mean")


def test_summary_sum_of_all_null_group_is_null() -> None:
    adqs = pl.from_repr("""\
┌─────────┬─────────┬────────┬──────┐
│ USUBJID ┆ PARAMCD ┆ AVISIT ┆ AVAL │
│ ---     ┆ ---     ┆ ---    ┆ ---  │
│ str     ┆ str     ┆ str    ┆ f64  │
╞═════════╪═════════╪════════╪══════╡
│ S01     ┆ ITEM    ┆ WEEK 2 ┆ 3.0  │
│ S01     ┆ ITEM    ┆ WEEK 2 ┆ 4.0  │
│ S02     ┆ ITEM    ┆ WEEK 2 ┆ null │
│ S02     ┆ ITEM    ┆ WEEK 2 ┆ null │
└─────────┴─────────┴────────┴──────┘
""")
    out = adqs.adam.derive_summary_records(
        by=["USUBJID", "PARAMCD", "AVISIT"], set_values_to={"DTYPE": "SUM"}, stat="sum"
    ).to_frame()
    sums = dict(out.filter(pl.col("DTYPE") == "SUM").select("USUBJID", "AVAL").rows())
    assert sums == {"S01": 7.0, "S02": None}
    counts = adqs.adam.derive_summary_records(
        by=["USUBJID", "PARAMCD", "AVISIT"], set_values_to={"DTYPE": "N"}, stat="count"
    ).to_frame()
    assert dict(counts.filter(pl.col("DTYPE") == "N").select("USUBJID", "AVAL").rows()) == {
        "S01": 2.0,
        "S02": 0.0,
    }
