"""Engine-seam tests for ``fleet.compare`` (ticket #100, spec #99).

Every test builds two small frames in memory, calls the engine and asserts on
the comparison report: its flags, its verdict, the rows of its summary frames
and the rows of its listing.  Nothing here knows how the engine joins or what
its internal columns are called.
"""

from __future__ import annotations

import dataclasses
import json
import math
import re
from datetime import date
from pathlib import Path

import polars as pl
import pytest

import fleet
from fleet.comparison import (
    FLAGS,
    JSON_KEYS,
    LISTING_COLUMNS,
    STATISTICS_COLUMNS,
    ComparisonError,
    ComparisonReport,
    ComparisonSettings,
    compare,
)
from fleet.core.exceptions import FleetError, VerbUsageError
from tests.helpers import shuffle_rows

NAN = float("nan")

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _adsl() -> pl.DataFrame:
    return pl.from_repr("""\
┌─────────┬─────┬─────┬───────┐
│ USUBJID ┆ AGE ┆ SEX ┆ WT    │
│ ---     ┆ --- ┆ --- ┆ ---   │
│ str     ┆ i64 ┆ str ┆ f64   │
╞═════════╪═════╪═════╪═══════╡
│ 01      ┆ 34  ┆ M   ┆ 70.1  │
│ 02      ┆ 45  ┆ F   ┆ 55.2  │
│ 03      ┆ 52  ┆ F   ┆ 60.3  │
│ 04      ┆ 61  ┆ M   ┆ 80.0  │
└─────────┴─────┴─────┴───────┘
""")


@pytest.fixture
def base() -> pl.DataFrame:
    return _adsl()


@pytest.fixture
def candidate() -> pl.DataFrame:
    """Same subjects as the base, except: 02 AGE 45→46, 03 SEX F→M, 03 WT 60.3→60.5,
    subject 04 replaced by 05, and an extra RACE column."""
    return pl.from_repr("""\
┌─────────┬─────┬─────┬───────┬──────┐
│ USUBJID ┆ AGE ┆ SEX ┆ WT    ┆ RACE │
│ ---     ┆ --- ┆ --- ┆ ---   ┆ ---  │
│ str     ┆ i64 ┆ str ┆ f64   ┆ str  │
╞═════════╪═════╪═════╪═══════╪══════╡
│ 01      ┆ 34  ┆ M   ┆ 70.1  ┆ W    │
│ 02      ┆ 46  ┆ F   ┆ 55.2  ┆ B    │
│ 03      ┆ 52  ┆ M   ┆ 60.5  ┆ W    │
│ 05      ┆ 70  ┆ F   ┆ 75.0  ┆ A    │
└─────────┴─────┴─────┴───────┴──────┘
""")


def _listing_rows(report: ComparisonReport) -> list[dict]:
    return report.listing.to_dicts()


# ── Verdict, flags and the public entry point ─────────────────────────────────


class TestEntryPoint:
    def test_compare_is_exported_from_the_package_root(self):
        assert fleet.compare is compare
        assert "compare" in fleet.__all__

    def test_equal_frames_produce_an_equal_report(self, base):
        report = compare(base, base.clone(), keys=["USUBJID"])
        assert isinstance(report, ComparisonReport)
        assert report.is_equal is True
        assert report.flags == frozenset()
        assert report.listing.height == 0

    @pytest.mark.parametrize(
        "base_kind, candidate_kind",
        [("eager", "eager"), ("lazy", "lazy"), ("eager", "lazy"), ("lazy", "eager")],
    )
    def test_accepts_dataframe_or_lazyframe_on_either_side(
        self, base, candidate, base_kind, candidate_kind
    ):
        b = base.lazy() if base_kind == "lazy" else base
        c = candidate.lazy() if candidate_kind == "lazy" else candidate
        report = compare(b, c, keys=["USUBJID"])
        assert report.is_equal is False
        assert report.values.total_differences == 3

    def test_inputs_are_collected_exactly_once(self, base, candidate):
        calls = {"base": 0, "candidate": 0}

        def counter(side):
            def tick(df: pl.DataFrame) -> pl.DataFrame:
                calls[side] += 1
                return df

            return tick

        b = base.lazy().map_batches(counter("base"), schema=base.schema)
        c = candidate.lazy().map_batches(counter("candidate"), schema=candidate.schema)
        compare(b, c, keys=["USUBJID"])
        assert calls == {"base": 1, "candidate": 1}

    def test_rejects_non_frame_inputs(self, base):
        with pytest.raises(VerbUsageError):
            compare(base.to_dicts(), base, keys=["USUBJID"])  # type: ignore[arg-type]
        with pytest.raises(VerbUsageError):
            compare(base, "candidate.parquet", keys=["USUBJID"])  # type: ignore[arg-type]

    def test_keys_accepts_a_single_name(self, base):
        report = compare(base, base, keys="USUBJID")
        assert report.settings.keys == ("USUBJID",)

    def test_keys_must_not_be_empty(self, base):
        with pytest.raises(ComparisonError, match="keys"):
            compare(base, base, keys=[])

    def test_comparison_error_is_a_fleet_error_and_a_value_error(self):
        assert issubclass(ComparisonError, FleetError)
        assert issubclass(ComparisonError, ValueError)

    def test_flags_are_exactly_the_documented_names(self):
        assert set(FLAGS) == {
            "base_only_variables",
            "candidate_only_variables",
            "type_conflicts",
            "base_only_observations",
            "candidate_only_observations",
            "values_differ",
            "duplicate_keys",
            "base_only_groups",
            "candidate_only_groups",
        }

    def test_every_raised_flag_is_a_documented_name(self, base, candidate):
        report = compare(base, candidate, keys=["USUBJID"])
        assert report.flags <= frozenset(FLAGS)
        assert report.flags == {
            "candidate_only_variables",
            "base_only_observations",
            "candidate_only_observations",
            "values_differ",
        }
        assert report.is_equal is False

    def test_settings_and_version_are_recorded(self, base):
        report = compare(base, base, keys=["USUBJID"], base_name="prod", candidate_name="qc")
        assert report.settings.keys == ("USUBJID",)
        assert report.settings.max_print == 50
        assert report.settings.base_name == "prod"
        assert report.settings.candidate_name == "qc"
        assert report.version == fleet.__version__


# ── Dataset and variables summary ─────────────────────────────────────────────


class TestDatasetsAndVariables:
    def test_dataset_summary_counts_rows_and_variables_per_side(self, base, candidate):
        report = compare(base, candidate, keys=["USUBJID"], base_name="prod", candidate_name="qc")
        assert report.datasets.base.name == "prod"
        assert report.datasets.base.rows == 4
        assert report.datasets.base.variables == 4
        assert report.datasets.candidate.name == "qc"
        assert report.datasets.candidate.rows == 4
        assert report.datasets.candidate.variables == 5

    def test_dataset_names_default_to_none(self, base):
        report = compare(base, base, keys=["USUBJID"])
        assert report.datasets.base.name is None
        assert report.datasets.candidate.name is None

    def test_variables_summary_lists_common_and_one_sided_variables(self, base, candidate):
        report = compare(base, candidate.drop("WT"), keys=["USUBJID"])
        v = report.variables
        assert v.common == ("AGE", "SEX")
        assert v.base_only == ("WT",)
        assert v.candidate_only == ("RACE",)
        assert v.compared == ("AGE", "SEX")
        assert {"base_only_variables", "candidate_only_variables"} <= report.flags

    def test_keys_are_not_counted_among_common_variables(self, base):
        report = compare(base, base, keys=["USUBJID"])
        assert "USUBJID" not in report.variables.common

    def test_type_conflict_is_listed_and_not_compared(self, base):
        cand = base.with_columns(pl.col("AGE").cast(pl.String))
        report = compare(base, cand, keys=["USUBJID"])
        conflicts = report.variables.type_conflicts
        assert [c.variable for c in conflicts] == ["AGE"]
        assert conflicts[0].base_dtype == pl.Int64
        assert conflicts[0].candidate_dtype == pl.String
        assert "AGE" not in report.variables.compared
        assert "AGE" in report.variables.common
        assert report.flags == {"type_conflicts"}
        assert report.is_equal is False
        assert "AGE" not in report.values.per_variable["variable"].to_list()

    @pytest.mark.parametrize(
        "base_dtype, candidate_dtype",
        [
            (pl.Int64, pl.Float64),
            (pl.Int32, pl.Int64),
            (pl.UInt8, pl.Int64),
            (pl.Float32, pl.Float64),
        ],
    )
    def test_numeric_dtype_difference_compares_by_value_and_raises_no_flag(
        self, base, base_dtype, candidate_dtype
    ):
        b = base.with_columns(pl.col("AGE").cast(base_dtype))
        c = base.with_columns(pl.col("AGE").cast(candidate_dtype))
        report = compare(b, c, keys=["USUBJID"])
        assert report.is_equal is True
        assert [d.variable for d in report.variables.dtype_differences] == ["AGE"]
        assert report.variables.dtype_differences[0].base_dtype == base_dtype
        assert report.variables.dtype_differences[0].candidate_dtype == candidate_dtype
        assert "AGE" in report.variables.compared

    def test_numeric_dtype_difference_still_detects_real_differences(self, base):
        c = base.with_columns(pl.col("AGE").cast(pl.Float64) + 0.5)
        report = compare(base, c, keys=["USUBJID"])
        assert report.flags == {"values_differ"}
        assert report.values.per_variable.filter(pl.col("variable") == "AGE")["differences"][0] == 4

    def test_string_and_categorical_are_the_same_kind(self, base):
        c = base.with_columns(pl.col("SEX").cast(pl.Categorical))
        report = compare(base, c, keys=["USUBJID"])
        assert report.is_equal is True
        assert [d.variable for d in report.variables.dtype_differences] == ["SEX"]

    def test_date_and_datetime_are_the_same_kind(self):
        b = pl.from_repr("""\
┌─────┬────────────┐
│ ID  ┆ DT         │
│ --- ┆ ---        │
│ i64 ┆ date       │
╞═════╪════════════╡
│ 1   ┆ 2024-01-01 │
│ 2   ┆ 2024-01-02 │
└─────┴────────────┘
""")
        c = pl.from_repr("""\
┌─────┬─────────────────────┐
│ ID  ┆ DT                  │
│ --- ┆ ---                 │
│ i64 ┆ datetime[μs]        │
╞═════╪═════════════════════╡
│ 1   ┆ 2024-01-01 00:00:00 │
│ 2   ┆ 2024-01-02 12:00:00 │
└─────┴─────────────────────┘
""")
        report = compare(b, c, keys=["ID"])
        assert [d.variable for d in report.variables.dtype_differences] == ["DT"]
        assert report.flags == {"values_differ"}
        rows = _listing_rows(report)
        assert [r["ID"] for r in rows] == [2]

    def test_temporal_against_numeric_is_a_type_conflict(self):
        b = pl.from_repr("""\
┌─────┬────────────┐
│ ID  ┆ DT         │
│ --- ┆ ---        │
│ i64 ┆ date       │
╞═════╪════════════╡
│ 1   ┆ 2024-01-01 │
└─────┴────────────┘
""")
        c = pl.from_repr("""\
┌─────┬──────────┐
│ ID  ┆ DT       │
│ --- ┆ ---      │
│ i64 ┆ i64      │
╞═════╪══════════╡
│ 1   ┆ 20240101 │
└─────┴──────────┘
""")
        report = compare(b, c, keys=["ID"])
        assert [t.variable for t in report.variables.type_conflicts] == ["DT"]

    def test_boolean_against_integer_is_a_type_conflict(self):
        b = pl.from_repr("""\
┌─────┬──────┐
│ ID  ┆ FL   │
│ --- ┆ ---  │
│ i64 ┆ bool │
╞═════╪══════╡
│ 1   ┆ true │
└─────┴──────┘
""")
        c = pl.from_repr("""\
┌─────┬─────┐
│ ID  ┆ FL  │
│ --- ┆ --- │
│ i64 ┆ i64 │
╞═════╪═════╡
│ 1   ┆ 1   │
└─────┴─────┘
""")
        report = compare(b, c, keys=["ID"])
        assert [t.variable for t in report.variables.type_conflicts] == ["FL"]

    def test_list_variables_compare_when_dtypes_are_identical(self):
        b = pl.DataFrame({"ID": [1, 2], "L": [[1, 2], [3]]})
        c = pl.DataFrame({"ID": [1, 2], "L": [[1, 2], [4]]})
        report = compare(b, c, keys=["ID"])
        assert report.flags == {"values_differ"}
        row = _listing_rows(report)[0]
        assert row["variable"] == "L"
        assert row["base"] == "[3]"
        assert row["candidate"] == "[4]"
        assert row["difference"] is None


# ── Observation summary ───────────────────────────────────────────────────────


class TestObservations:
    def test_counts_and_key_values_of_unmatched_observations(self, base, candidate):
        report = compare(base, candidate, keys=["USUBJID"])
        o = report.observations
        assert o.matched == 3
        assert o.base_only == 1
        assert o.candidate_only == 1
        assert o.base_only_keys.to_dicts() == [{"USUBJID": "04"}]
        assert o.candidate_only_keys.to_dicts() == [{"USUBJID": "05"}]
        assert {"base_only_observations", "candidate_only_observations"} <= report.flags

    def test_composite_keys_pair_observations(self):
        b = pl.from_repr("""\
┌─────────┬───────┬────────┐
│ USUBJID ┆ AESEQ ┆ AETERM │
│ ---     ┆ ---   ┆ ---    │
│ str     ┆ i64   ┆ str    │
╞═════════╪═══════╪════════╡
│ 01      ┆ 1     ┆ a      │
│ 01      ┆ 2     ┆ b      │
│ 02      ┆ 1     ┆ c      │
└─────────┴───────┴────────┘
""")
        c = pl.from_repr("""\
┌─────────┬───────┬────────┐
│ USUBJID ┆ AESEQ ┆ AETERM │
│ ---     ┆ ---   ┆ ---    │
│ str     ┆ i64   ┆ str    │
╞═════════╪═══════╪════════╡
│ 01      ┆ 1     ┆ a      │
│ 02      ┆ 1     ┆ x      │
│ 02      ┆ 2     ┆ d      │
└─────────┴───────┴────────┘
""")
        report = compare(b, c, keys=["USUBJID", "AESEQ"])
        o = report.observations
        assert o.matched == 2
        assert o.base_only_keys.to_dicts() == [{"USUBJID": "01", "AESEQ": 2}]
        assert o.candidate_only_keys.to_dicts() == [{"USUBJID": "02", "AESEQ": 2}]
        assert _listing_rows(report) == [
            {
                "USUBJID": "02",
                "AESEQ": 1,
                "group": None,
                "variable": "AETERM",
                "base": "c",
                "candidate": "x",
                "difference": None,
                "percent_difference": None,
            }
        ]

    def test_unmatched_key_lists_are_sorted_by_keys(self):
        b = pl.from_repr("""\
┌─────┬─────┐
│ ID  ┆ V   │
│ --- ┆ --- │
│ i64 ┆ i64 │
╞═════╪═════╡
│ 3   ┆ 0   │
│ 1   ┆ 0   │
│ 2   ┆ 0   │
└─────┴─────┘
""")
        c = pl.from_repr("""\
┌─────┬─────┐
│ ID  ┆ V   │
│ --- ┆ --- │
│ i64 ┆ i64 │
╞═════╪═════╡
│ 9   ┆ 0   │
│ 7   ┆ 0   │
│ 8   ┆ 0   │
└─────┴─────┘
""")
        report = compare(b, c, keys=["ID"])
        assert report.observations.base_only_keys["ID"].to_list() == [1, 2, 3]
        assert report.observations.candidate_only_keys["ID"].to_list() == [7, 8, 9]
        assert report.observations.matched == 0

    def test_null_keys_pair_with_null_keys(self):
        b = pl.from_repr("""\
┌──────┬─────┐
│ ID   ┆ V   │
│ ---  ┆ --- │
│ str  ┆ i64 │
╞══════╪═════╡
│ a    ┆ 1   │
│ null ┆ 2   │
└──────┴─────┘
""")
        c = pl.from_repr("""\
┌──────┬─────┐
│ ID   ┆ V   │
│ ---  ┆ --- │
│ str  ┆ i64 │
╞══════╪═════╡
│ a    ┆ 1   │
│ null ┆ 3   │
└──────┴─────┘
""")
        report = compare(b, c, keys=["ID"])
        assert report.observations.matched == 2
        assert report.observations.base_only == 0
        assert report.observations.candidate_only == 0
        assert [r["ID"] for r in _listing_rows(report)] == [None]

    def test_missing_keys_raise_and_name_the_side(self, base):
        with pytest.raises(ComparisonError, match=r"candidate.*STUDYID") as exc:
            compare(base, base.rename({"USUBJID": "SUBJID"}), keys=["USUBJID", "STUDYID"])
        assert "USUBJID" in str(exc.value)
        with pytest.raises(ComparisonError, match=r"base.*USUBJID"):
            compare(base.rename({"USUBJID": "SUBJID"}), base, keys=["USUBJID"])

    def test_duplicate_keys_raise_and_name_side_and_values(self, base):
        dup_base = pl.concat([base, base.head(1)])
        with pytest.raises(ComparisonError, match=r"base") as exc:
            compare(dup_base, base, keys=["USUBJID"])
        assert "USUBJID=01" in str(exc.value)
        assert "candidate" not in str(exc.value).split("base", 1)[0]

        dup_cand = pl.concat([base, base.filter(pl.col("USUBJID") == "03")])
        with pytest.raises(ComparisonError, match=r"candidate.*USUBJID=03"):
            compare(base, dup_cand, keys=["USUBJID"])

    def test_duplicate_keys_on_both_sides_are_both_reported(self, base):
        dup = pl.concat([base, base.head(2)])
        with pytest.raises(ComparisonError) as exc:
            compare(dup, dup, keys=["USUBJID"])
        message = str(exc.value)
        assert "base" in message and "candidate" in message
        assert "USUBJID=01" in message and "USUBJID=02" in message

    def test_key_type_conflict_raises(self, base):
        with pytest.raises(ComparisonError, match="USUBJID"):
            compare(base, base.with_columns(pl.col("USUBJID").cast(pl.Int64)), keys=["USUBJID"])

    def test_keys_of_the_same_kind_but_different_dtype_pair(self):
        b = pl.from_repr("""\
┌─────┬─────┐
│ ID  ┆ V   │
│ --- ┆ --- │
│ i32 ┆ i64 │
╞═════╪═════╡
│ 1   ┆ 1   │
│ 2   ┆ 2   │
└─────┴─────┘
""")
        c = pl.from_repr("""\
┌─────┬─────┐
│ ID  ┆ V   │
│ --- ┆ --- │
│ i64 ┆ i64 │
╞═════╪═════╡
│ 1   ┆ 1   │
│ 2   ┆ 2   │
└─────┴─────┘
""")
        assert compare(b, c, keys=["ID"]).is_equal is True


# ── Values and the listing ────────────────────────────────────────────────────


class TestValues:
    def test_values_summary_counts_differences_per_compared_variable(self, base, candidate):
        report = compare(base, candidate, keys=["USUBJID"])
        per_variable = report.values.per_variable
        assert per_variable.columns == ["variable", "differences"]
        assert dict(per_variable.iter_rows()) == {"AGE": 1, "SEX": 1, "WT": 1}
        assert report.values.variables_with_differences == 3
        assert report.values.observations_with_differences == 2
        assert report.values.total_differences == 3

    def test_listing_has_the_documented_columns_and_is_sorted_by_keys(self, base, candidate):
        report = compare(base, candidate, keys=["USUBJID"])
        listing = report.listing
        assert listing.columns == [
            "USUBJID",
            "group",
            "variable",
            "base",
            "candidate",
            "difference",
            "percent_difference",
        ]
        assert listing["USUBJID"].to_list() == ["02", "03", "03"]
        assert listing["variable"].to_list() == ["AGE", "SEX", "WT"]
        assert listing["group"].dtype == pl.String
        assert listing["group"].is_null().all()
        assert listing["base"].dtype == pl.String
        assert listing["candidate"].dtype == pl.String
        assert listing["difference"].dtype == pl.Float64
        assert listing["percent_difference"].dtype == pl.Float64

    def test_numeric_rows_carry_difference_and_percent(self, base, candidate):
        rows = {r["variable"]: r for r in _listing_rows(compare(base, candidate, keys="USUBJID"))}
        assert rows["AGE"]["base"] == "45"
        assert rows["AGE"]["candidate"] == "46"
        assert rows["AGE"]["difference"] == 1.0
        assert rows["AGE"]["percent_difference"] == pytest.approx(100 / 45)
        assert rows["WT"]["difference"] == pytest.approx(0.2)
        assert rows["WT"]["percent_difference"] == pytest.approx(0.2 / 60.3 * 100)
        assert rows["SEX"] == {
            "USUBJID": "03",
            "group": None,
            "variable": "SEX",
            "base": "F",
            "candidate": "M",
            "difference": None,
            "percent_difference": None,
        }

    def test_percent_is_null_when_the_base_is_zero_or_null(self):
        b = pl.from_repr("""\
┌─────┬──────┐
│ ID  ┆ X    │
│ --- ┆ ---  │
│ i64 ┆ f64  │
╞═════╪══════╡
│ 1   ┆ 0.0  │
│ 2   ┆ null │
│ 3   ┆ 2.0  │
└─────┴──────┘
""")
        c = pl.from_repr("""\
┌─────┬─────┐
│ ID  ┆ X   │
│ --- ┆ --- │
│ i64 ┆ f64 │
╞═════╪═════╡
│ 1   ┆ 1.0 │
│ 2   ┆ 1.0 │
│ 3   ┆ 3.0 │
└─────┴─────┘
""")
        rows = {r["ID"]: r for r in _listing_rows(compare(b, c, keys="ID"))}
        assert rows[1]["difference"] == 1.0 and rows[1]["percent_difference"] is None
        assert rows[2]["base"] is None
        assert rows[2]["difference"] is None and rows[2]["percent_difference"] is None
        assert rows[3]["difference"] == 1.0 and rows[3]["percent_difference"] == 50.0

    def test_empty_listing_keeps_the_documented_schema(self, base):
        listing = compare(base, base, keys=["USUBJID"]).listing
        assert listing.height == 0
        assert listing.schema == pl.Schema(
            {
                "USUBJID": pl.String,
                "group": pl.String,
                "variable": pl.String,
                "base": pl.String,
                "candidate": pl.String,
                "difference": pl.Float64,
                "percent_difference": pl.Float64,
            }
        )

    @pytest.mark.parametrize(
        "base_value, candidate_value, differs",
        [
            (None, None, False),
            (NAN, NAN, False),
            (None, NAN, True),
            (NAN, None, True),
            (1.0, None, True),
            (None, 1.0, True),
            (1.0, NAN, True),
            (NAN, 1.0, True),
            (1.0, 1.0, False),
            (1.0, 2.0, True),
        ],
        ids=lambda v: "nan" if isinstance(v, float) and math.isnan(v) else repr(v),
    )
    def test_null_and_nan_rule(self, base_value, candidate_value, differs):
        b = pl.DataFrame({"ID": [1], "X": pl.Series([base_value], dtype=pl.Float64)})
        c = pl.DataFrame({"ID": [1], "X": pl.Series([candidate_value], dtype=pl.Float64)})
        report = compare(b, c, keys=["ID"])
        assert report.is_equal is (not differs)
        assert report.listing.height == (1 if differs else 0)

    def test_null_strings_and_dates_follow_the_null_rule(self):
        b = pl.from_repr("""\
┌─────┬──────┬────────────┐
│ ID  ┆ S    ┆ D          │
│ --- ┆ ---  ┆ ---        │
│ i64 ┆ str  ┆ date       │
╞═════╪══════╪════════════╡
│ 1   ┆ null ┆ null       │
│ 2   ┆ a    ┆ 2024-01-01 │
└─────┴──────┴────────────┘
""")
        # The candidate's S is all null, so Polars types it Null; it adopts the base dtype.
        c = pl.from_repr("""\
┌─────┬──────┬────────────┐
│ ID  ┆ S    ┆ D          │
│ --- ┆ ---  ┆ ---        │
│ i64 ┆ null ┆ date       │
╞═════╪══════╪════════════╡
│ 1   ┆ null ┆ null       │
│ 2   ┆ null ┆ 2024-01-01 │
└─────┴──────┴────────────┘
""")
        report = compare(b, c, keys=["ID"])
        assert [d.variable for d in report.variables.dtype_differences] == ["S"]
        assert report.variables.type_conflicts == ()
        assert _listing_rows(report) == [
            {
                "ID": 2,
                "group": None,
                "variable": "S",
                "base": "a",
                "candidate": None,
                "difference": None,
                "percent_difference": None,
            }
        ]

    def test_all_null_column_adopts_the_other_side_dtype(self):
        b = pl.from_repr("""\
┌─────┬──────┐
│ ID  ┆ X    │
│ --- ┆ ---  │
│ i64 ┆ null │
╞═════╪══════╡
│ 1   ┆ null │
│ 2   ┆ null │
└─────┴──────┘
""")
        c = pl.from_repr("""\
┌─────┬──────┐
│ ID  ┆ X    │
│ --- ┆ ---  │
│ i64 ┆ f64  │
╞═════╪══════╡
│ 1   ┆ null │
│ 2   ┆ 2.5  │
└─────┴──────┘
""")
        report = compare(b, c, keys=["ID"])
        assert report.variables.type_conflicts == ()
        assert report.flags == {"values_differ"}
        row = _listing_rows(report)[0]
        assert row["ID"] == 2 and row["base"] is None and row["candidate"] == "2.5"
        assert row["difference"] is None  # no base value to subtract from

    def test_row_and_column_order_are_ignored(self, base):
        shuffled = shuffle_rows(base, seed=7).select("WT", "SEX", "USUBJID", "AGE")
        report = compare(base, shuffled, keys=["USUBJID"])
        assert report.is_equal is True
        assert report.observations.matched == 4

    def test_listing_groups_variables_of_one_observation_together(self):
        b = pl.from_repr("""\
┌─────┬─────┬─────┐
│ ID  ┆ A   ┆ B   │
│ --- ┆ --- ┆ --- │
│ i64 ┆ i64 ┆ str │
╞═════╪═════╪═════╡
│ 2   ┆ 1   ┆ x   │
│ 1   ┆ 1   ┆ x   │
└─────┴─────┴─────┘
""")
        c = pl.from_repr("""\
┌─────┬─────┬─────┐
│ ID  ┆ A   ┆ B   │
│ --- ┆ --- ┆ --- │
│ i64 ┆ i64 ┆ str │
╞═════╪═════╪═════╡
│ 1   ┆ 9   ┆ y   │
│ 2   ┆ 9   ┆ y   │
└─────┴─────┴─────┘
""")
        rows = _listing_rows(compare(b, c, keys=["ID"]))
        assert [(r["ID"], r["variable"]) for r in rows] == [
            (1, "A"),
            (1, "B"),
            (2, "A"),
            (2, "B"),
        ]

    def test_no_comparable_variables_still_reports_observations(self, base):
        b = base.select("USUBJID", "AGE")
        c = base.select("USUBJID", "SEX")
        report = compare(b, c, keys=["USUBJID"])
        assert report.variables.common == ()
        assert report.observations.matched == 4
        assert report.values.per_variable.height == 0
        assert report.flags == {"base_only_variables", "candidate_only_variables"}
        assert "No variables were compared besides the keys." in report.warnings

    def test_key_only_sides_with_the_same_keys_are_equal_and_warn(self, base):
        report = compare(base.select("USUBJID"), base.select("USUBJID"), keys=["USUBJID"])
        assert report.is_equal is True
        assert report.warnings == ("No variables were compared besides the keys.",)
        assert report.warnings[0] in report.to_text()

    def test_key_only_sides_with_different_keys_are_not_equal(self, base):
        report = compare(base.select("USUBJID"), base.select("USUBJID").head(3), keys="USUBJID")
        assert report.is_equal is False
        assert report.flags == {"base_only_observations"}
        assert "No variables were compared besides the keys." in report.warnings

    def test_empty_frames_compare_equal(self, base):
        report = compare(base.clear(), base.clear(), keys=["USUBJID"])
        assert report.is_equal is True
        assert report.observations.matched == 0
        assert report.datasets.base.rows == 0
        assert report.warnings == ("Both datasets have no observations.",)

    def test_a_key_may_not_reuse_a_listing_column_name(self):
        b = pl.from_repr("""\
┌──────────┬─────┐
│ variable ┆ X   │
│ ---      ┆ --- │
│ i64      ┆ i64 │
╞══════════╪═════╡
│ 1        ┆ 1   │
└──────────┴─────┘
""")
        with pytest.raises(ComparisonError, match="variable"):
            compare(b, b, keys=["variable"])


# ── Summary statistics ────────────────────────────────────────────────────────

#: The columns of the statistics frame, in order, as documented on the concepts page.
_STATISTICS_COLUMNS = [
    "variable",
    "differences",
    "base_n",
    "base_mean",
    "base_std",
    "base_min",
    "base_max",
    "candidate_n",
    "candidate_mean",
    "candidate_std",
    "candidate_min",
    "candidate_max",
    "difference_n",
    "difference_mean",
    "difference_std",
    "difference_min",
    "difference_max",
    "percent_difference_n",
    "percent_difference_mean",
    "percent_difference_std",
    "percent_difference_min",
    "percent_difference_max",
]

#: Everything after the count of differences: what only a numeric variable carries.
_MEASURES = _STATISTICS_COLUMNS[2:]


class TestStatistics:
    """A reviewer tells a systematic offset from random noise (ticket #107)."""

    def test_frame_has_the_documented_columns_and_one_row_per_differing_variable(
        self, base, candidate
    ):
        statistics = compare(base, candidate, keys="USUBJID").statistics
        assert statistics.columns == _STATISTICS_COLUMNS
        assert list(STATISTICS_COLUMNS) == _STATISTICS_COLUMNS
        assert statistics["variable"].to_list() == ["AGE", "SEX", "WT"]
        assert statistics["differences"].to_list() == [1, 1, 1]
        assert statistics.schema["differences"] == pl.Int64
        assert statistics.schema["base_n"] == pl.Int64
        assert all(statistics.schema[m] == pl.Float64 for m in _MEASURES if not m.endswith("_n"))

    def test_values_match_hand_computed_expectations(self, base, candidate):
        """AGE over the matched observations 01, 02 and 03: 34, 45, 52 against 34, 46, 52."""
        statistics = compare(base, candidate, keys="USUBJID").statistics
        age = statistics.filter(pl.col("variable") == "AGE").row(0, named=True)
        assert (age["base_n"], age["base_mean"]) == (3, pytest.approx(131 / 3))
        assert age["base_std"] == pytest.approx(math.sqrt(741 / 9))
        assert (age["base_min"], age["base_max"]) == (34.0, 52.0)
        assert (age["candidate_n"], age["candidate_mean"]) == (3, 44.0)
        assert age["candidate_std"] == pytest.approx(math.sqrt(84))
        assert (age["candidate_min"], age["candidate_max"]) == (34.0, 52.0)
        assert (age["difference_n"], age["difference_mean"]) == (3, pytest.approx(1 / 3))
        assert age["difference_std"] == pytest.approx(math.sqrt(1 / 3))
        assert (age["difference_min"], age["difference_max"]) == (0.0, 1.0)
        assert age["percent_difference_n"] == 3
        assert age["percent_difference_mean"] == pytest.approx(100 / 45 / 3)
        assert age["percent_difference_std"] == pytest.approx(math.sqrt(1 / 3) * 100 / 45)
        assert age["percent_difference_min"] == 0.0
        assert age["percent_difference_max"] == pytest.approx(100 / 45)

    def test_statistics_span_the_matched_observations_where_both_sides_are_non_null(self):
        b = pl.from_repr("""\
┌─────┬──────┐
│ ID  ┆ X    │
│ --- ┆ ---  │
│ i64 ┆ f64  │
╞═════╪══════╡
│ 1   ┆ 10.0 │
│ 2   ┆ null │
│ 3   ┆ 20.0 │
│ 4   ┆ 30.0 │
└─────┴──────┘
""")
        c = pl.from_repr("""\
┌─────┬──────┐
│ ID  ┆ X    │
│ --- ┆ ---  │
│ i64 ┆ f64  │
╞═════╪══════╡
│ 1   ┆ 12.0 │
│ 2   ┆ 5.0  │
│ 3   ┆ null │
│ 4   ┆ 30.0 │
└─────┴──────┘
""")
        row = compare(b, c, keys="ID").statistics.row(0, named=True)
        # three observations differ, but only 1 and 4 have a value on both sides
        assert row["differences"] == 3
        assert (row["base_n"], row["base_mean"]) == (2, 20.0)
        assert (row["base_min"], row["base_max"]) == (10.0, 30.0)
        assert (row["candidate_n"], row["candidate_mean"]) == (2, 21.0)
        assert (row["difference_min"], row["difference_max"]) == (0.0, 2.0)
        assert (row["percent_difference_n"], row["percent_difference_mean"]) == (2, 10.0)

    def test_percent_difference_skips_a_zero_base(self):
        b = pl.from_repr("""\
┌─────┬─────┐
│ ID  ┆ X   │
│ --- ┆ --- │
│ i64 ┆ f64 │
╞═════╪═════╡
│ 1   ┆ 0.0 │
│ 2   ┆ 4.0 │
└─────┴─────┘
""")
        c = pl.from_repr("""\
┌─────┬─────┐
│ ID  ┆ X   │
│ --- ┆ --- │
│ i64 ┆ f64 │
╞═════╪═════╡
│ 1   ┆ 1.0 │
│ 2   ┆ 5.0 │
└─────┴─────┘
""")
        row = compare(b, c, keys="ID").statistics.row(0, named=True)
        assert (row["differences"], row["base_n"], row["difference_n"]) == (2, 2, 2)
        assert (row["percent_difference_n"], row["percent_difference_mean"]) == (1, 25.0)

    def test_a_non_numeric_variable_contributes_only_a_count(self):
        b = pl.from_repr("""\
┌─────┬─────┬────────────┐
│ ID  ┆ S   ┆ D          │
│ --- ┆ --- ┆ ---        │
│ i64 ┆ str ┆ date       │
╞═════╪═════╪════════════╡
│ 1   ┆ F   ┆ 2024-01-01 │
└─────┴─────┴────────────┘
""")
        c = pl.from_repr("""\
┌─────┬─────┬────────────┐
│ ID  ┆ S   ┆ D          │
│ --- ┆ --- ┆ ---        │
│ i64 ┆ str ┆ date       │
╞═════╪═════╪════════════╡
│ 1   ┆ M   ┆ 2024-01-02 │
└─────┴─────┴────────────┘
""")
        statistics = compare(b, c, keys="ID").statistics
        assert statistics["variable"].to_list() == ["S", "D"]
        assert statistics["differences"].to_list() == [1, 1]
        for row in statistics.iter_rows(named=True):
            assert all(row[m] is None for m in _MEASURES)

    def test_only_differing_variables_get_a_row(self, base):
        c = base.with_columns(pl.col("AGE") + 1)
        assert compare(base, c, keys="USUBJID").statistics["variable"].to_list() == ["AGE"]

    def test_an_equal_comparison_keeps_the_schema(self, base):
        statistics = compare(base, base, keys="USUBJID").statistics
        assert statistics.height == 0
        assert statistics.columns == _STATISTICS_COLUMNS


# ── Tolerances and trailing whitespace ────────────────────────────────────────


def _numeric(base_value: float, candidate_value: float) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Two one-row frames whose only compared variable is ``X``."""
    b = pl.DataFrame({"ID": [1], "X": pl.Series([base_value], dtype=pl.Float64)})
    c = pl.DataFrame({"ID": [1], "X": pl.Series([candidate_value], dtype=pl.Float64)})
    return b, c


class TestTolerances:
    """``abs_tol`` and ``rel_tol`` on the numeric kinds; the rule is base-anchored."""

    def test_exact_is_the_default(self, base):
        c = base.with_columns(pl.col("WT") + 1e-9)
        report = compare(base, c, keys="USUBJID")
        assert report.settings.abs_tol == 0.0
        assert report.settings.rel_tol == 0.0
        assert report.is_equal is False
        assert report.values.total_differences == 4

    def test_absolute_tolerance_absorbs_a_difference_at_or_below_it(self):
        b, c = _numeric(10.0, 10.5)
        assert compare(b, c, keys="ID", abs_tol=0.5).is_equal is True
        assert compare(b, c, keys="ID", abs_tol=0.25).is_equal is False

    def test_relative_tolerance_is_a_fraction_of_the_base(self):
        b, c = _numeric(200.0, 202.0)  # 1% out
        assert compare(b, c, keys="ID", rel_tol=0.01).is_equal is True
        assert compare(b, c, keys="ID", rel_tol=0.009).is_equal is False

    def test_the_wider_of_the_two_tolerances_wins(self):
        b, c = _numeric(1000.0, 1001.0)
        assert compare(b, c, keys="ID", abs_tol=2.0, rel_tol=0.0001).is_equal is True
        assert compare(b, c, keys="ID", abs_tol=0.0001, rel_tol=0.002).is_equal is True
        assert compare(b, c, keys="ID", abs_tol=0.5, rel_tol=0.0005).is_equal is False

    def test_relative_tolerance_anchors_on_the_base_not_the_candidate(self):
        """100 → 110 at 9.5%: 9.5 of the base is too tight, 10.45 of the candidate would not be."""
        b, c = _numeric(100.0, 110.0)
        assert compare(b, c, keys="ID", rel_tol=0.095).is_equal is False
        # The mirror run proves the anchor: with the sides swapped the same
        # tolerance now measures 9.5% of 110 and the difference passes.
        assert compare(c, b, keys="ID", rel_tol=0.095).is_equal is True

    def test_relative_tolerance_uses_the_magnitude_of_a_negative_base(self):
        b, c = _numeric(-200.0, -202.0)
        assert compare(b, c, keys="ID", rel_tol=0.01).is_equal is True
        assert compare(b, c, keys="ID", rel_tol=0.009).is_equal is False

    def test_a_zero_base_leaves_only_the_absolute_tolerance(self):
        b, c = _numeric(0.0, 0.5)
        assert compare(b, c, keys="ID", rel_tol=0.99).is_equal is False
        assert compare(b, c, keys="ID", rel_tol=0.99, abs_tol=0.5).is_equal is True

    def test_tolerances_apply_to_integer_and_decimal_variables(self):
        b = pl.DataFrame({"ID": [1], "N": pl.Series([100], dtype=pl.Int64)})
        c = pl.DataFrame({"ID": [1], "N": pl.Series([101], dtype=pl.Int64)})
        assert compare(b, c, keys="ID", abs_tol=1.0).is_equal is True
        assert compare(b, c, keys="ID", abs_tol=0.5).is_equal is False

    def test_tolerances_survive_a_numeric_dtype_difference(self, base):
        c = base.with_columns((pl.col("AGE").cast(pl.Float64) + 0.4).alias("AGE"))
        report = compare(base, c, keys="USUBJID", abs_tol=0.5)
        assert report.is_equal is True
        assert [t.variable for t in report.variables.dtype_differences] == ["AGE"]

    def test_tolerances_leave_the_string_kinds_alone(self, base):
        c = base.with_columns(pl.lit("X").alias("SEX"))
        report = compare(base, c, keys="USUBJID", abs_tol=1e9, rel_tol=1e9)
        assert report.is_equal is False
        assert report.values.per_variable.filter(pl.col("variable") == "SEX")["differences"][0] == 4

    def test_tolerances_leave_the_temporal_kinds_alone(self):
        b = pl.DataFrame({"ID": [1], "D": [date(2026, 1, 1)]})
        c = pl.DataFrame({"ID": [1], "D": [date(2026, 1, 2)]})
        assert compare(b, c, keys="ID", abs_tol=1e9, rel_tol=1e9).is_equal is False

    @pytest.mark.parametrize(
        "base_value, candidate_value, differs",
        [
            (None, None, False),
            (NAN, NAN, False),
            (None, NAN, True),
            (NAN, None, True),
            (1.0, None, True),
            (None, 1.0, True),
            (1.0, NAN, True),
            (NAN, 1.0, True),
            (1.0, 1.0, False),
        ],
        ids=lambda v: "nan" if isinstance(v, float) and math.isnan(v) else repr(v),
    )
    def test_nulls_and_nan_keep_their_rule_under_tolerance(
        self, base_value, candidate_value, differs
    ):
        b, c = _numeric(base_value, candidate_value)
        report = compare(b, c, keys="ID", abs_tol=1e9, rel_tol=1e9)
        assert report.is_equal is (not differs)
        assert report.listing.height == (1 if differs else 0)

    def test_the_listing_reports_the_values_that_survived_the_tolerance(self):
        b, c = _numeric(10.0, 12.0)
        row = compare(b, c, keys="ID", abs_tol=1.0).listing.to_dicts()[0]
        assert (row["base"], row["candidate"]) == ("10.0", "12.0")
        assert row["difference"] == pytest.approx(2.0)
        assert row["percent_difference"] == pytest.approx(20.0)

    @pytest.mark.parametrize("option", ["abs_tol", "rel_tol"])
    def test_negative_tolerances_are_refused(self, base, option):
        with pytest.raises(ComparisonError, match=option):
            compare(base, base, keys="USUBJID", **{option: -1.0})

    @pytest.mark.parametrize("value", ["0.1", NAN, float("inf"), True])
    def test_tolerances_must_be_finite_numbers(self, base, value):
        with pytest.raises((VerbUsageError, ComparisonError), match="abs_tol"):
            compare(base, base, keys="USUBJID", abs_tol=value)


class TestTrailingWhitespace:
    """``ignore_trailing_whitespace`` on the string kinds; the left side still counts."""

    @staticmethod
    def _strings(base_value: str, candidate_value: str) -> tuple[pl.DataFrame, pl.DataFrame]:
        b = pl.DataFrame({"ID": [1], "S": [base_value]})
        c = pl.DataFrame({"ID": [1], "S": [candidate_value]})
        return b, c

    def test_trailing_whitespace_differs_by_default(self):
        b, c = self._strings("M", "M   ")
        report = compare(b, c, keys="ID")
        assert report.settings.ignore_trailing_whitespace is False
        assert report.is_equal is False

    @pytest.mark.parametrize("padded", ["M ", "M   ", "M\t", "M\n"])
    def test_trailing_whitespace_is_ignored_when_requested(self, padded):
        b, c = self._strings("M", padded)
        assert compare(b, c, keys="ID", ignore_trailing_whitespace=True).is_equal is True

    def test_padding_on_the_base_side_is_stripped_too(self):
        b, c = self._strings("M   ", "M")
        assert compare(b, c, keys="ID", ignore_trailing_whitespace=True).is_equal is True

    def test_leading_whitespace_still_differs(self):
        b, c = self._strings("M", " M")
        assert compare(b, c, keys="ID", ignore_trailing_whitespace=True).is_equal is False

    def test_a_real_difference_still_differs(self):
        b, c = self._strings("M  ", "F  ")
        assert compare(b, c, keys="ID", ignore_trailing_whitespace=True).is_equal is False

    @pytest.mark.parametrize(
        "dtype",
        [pl.Categorical, pl.Enum(["M", "M  "]), pl.String],
        ids=["categorical", "enum", "string"],
    )
    def test_every_string_kind_is_stripped(self, dtype):
        b = pl.DataFrame({"ID": [1], "S": pl.Series(["M"], dtype=dtype)})
        c = pl.DataFrame({"ID": [1], "S": pl.Series(["M  "], dtype=dtype)})
        assert compare(b, c, keys="ID").is_equal is False
        assert compare(b, c, keys="ID", ignore_trailing_whitespace=True).is_equal is True

    def test_nulls_keep_their_rule_under_stripping(self):
        b = pl.DataFrame({"ID": [1, 2], "S": ["M  ", None]})
        c = pl.DataFrame({"ID": [1, 2], "S": ["M", "  "]})
        report = compare(b, c, keys="ID", ignore_trailing_whitespace=True)
        assert report.listing["ID"].to_list() == [2]  # null against "  " still differs

    def test_stripping_leaves_the_other_kinds_alone(self, base):
        c = base.with_columns(pl.col("AGE") + 1)
        report = compare(base, c, keys="USUBJID", ignore_trailing_whitespace=True)
        assert report.values.per_variable.filter(pl.col("variable") == "AGE")["differences"][0] == 4

    def test_the_listing_shows_the_unstripped_values(self):
        b, c = self._strings("M  ", "F")
        row = compare(b, c, keys="ID", ignore_trailing_whitespace=True).listing.to_dicts()[0]
        assert (row["base"], row["candidate"]) == ("M  ", "F")

    def test_the_option_must_be_a_boolean(self, base):
        with pytest.raises(VerbUsageError, match="ignore_trailing_whitespace"):
            compare(base, base, keys="USUBJID", ignore_trailing_whitespace="yes")


# ── Duplicate keys under the override ─────────────────────────────────────────


def _duplicated() -> pl.DataFrame:
    """Subject ``01`` has two observations; ``AVAL`` tells them apart."""
    return pl.from_repr("""\
┌─────────┬──────┐
│ USUBJID ┆ AVAL │
│ ---     ┆ ---  │
│ str     ┆ i64  │
╞═════════╪══════╡
│ 01      ┆ 1    │
│ 01      ┆ 2    │
│ 02      ┆ 3    │
└─────────┴──────┘
""")


class TestAllowDuplicates:
    """Without the override duplicates refuse; with it they pair by position."""

    def test_duplicates_still_refuse_and_the_message_names_the_override(self, base):
        with pytest.raises(ComparisonError, match="allow_duplicates") as exc:
            compare(pl.concat([base, base.head(1)]), base, keys="USUBJID")
        assert "USUBJID=01" in str(exc.value)

    def test_duplicates_pair_by_position_within_each_key_group(self):
        candidate = _duplicated().with_columns(
            pl.when(pl.col("AVAL") == 2).then(9).otherwise(pl.col("AVAL")).alias("AVAL")
        )
        report = compare(_duplicated(), candidate, keys="USUBJID", allow_duplicates=True)
        assert report.observations.matched == 3
        assert _listing_rows(report) == [
            {
                "USUBJID": "01",
                "group": None,
                "variable": "AVAL",
                "base": "2",
                "candidate": "9",
                "difference": 7.0,
                "percent_difference": 350.0,
            }
        ]

    def test_the_order_within_a_key_group_decides_which_observations_pair(self):
        reversed_group = _duplicated()[[1, 0, 2]]
        report = compare(_duplicated(), reversed_group, keys="USUBJID", allow_duplicates=True)
        assert report.values.total_differences == 2  # 1 against 2, then 2 against 1

    def test_the_observation_summary_counts_the_duplicates_per_side(self):
        base = pl.concat([_duplicated(), _duplicated().head(1)])  # 01 three times
        report = compare(base, _duplicated(), keys="USUBJID", allow_duplicates=True)
        assert report.observations.base_duplicates == 2
        assert report.observations.candidate_duplicates == 1

    def test_an_unpaired_duplicate_is_an_observation_on_one_side_only(self):
        base = pl.concat([_duplicated(), _duplicated().head(1)])  # 01 three times
        report = compare(base, _duplicated(), keys="USUBJID", allow_duplicates=True)
        assert report.observations.matched == 3
        assert report.observations.base_only == 1
        assert report.observations.base_only_keys["USUBJID"].to_list() == ["01"]

    def test_the_flag_is_raised_only_under_the_override_and_only_when_duplicated(self, base):
        assert "duplicate_keys" not in compare(base, base, keys="USUBJID").flags
        assert (
            "duplicate_keys" not in compare(base, base, keys="USUBJID", allow_duplicates=True).flags
        )
        report = compare(_duplicated(), _duplicated(), keys="USUBJID", allow_duplicates=True)
        assert report.flags == {"duplicate_keys"}
        assert report.is_equal is False  # a raised flag is never equal

    def test_the_override_is_recorded_in_the_settings(self, base):
        assert compare(base, base, keys="USUBJID").settings.allow_duplicates is False
        settings = compare(base, base, keys="USUBJID", allow_duplicates=True).settings
        assert settings.allow_duplicates is True

    def test_the_option_must_be_a_boolean(self, base):
        with pytest.raises(VerbUsageError, match="allow_duplicates"):
            compare(base, base, keys="USUBJID", allow_duplicates="yes")

    def test_every_renderer_warns_at_the_top(self):
        report = compare(_duplicated(), _duplicated(), keys="USUBJID", allow_duplicates=True)
        assert len(report.warnings) == 1
        warning = report.warnings[0]
        assert "1 duplicate observation in the base" in warning
        assert "1 in the candidate" in warning

        text = report.to_text()
        assert warning in text
        assert text.index(warning) < text.index("Data set summary")

        page = report.to_html()
        assert warning in page
        assert page.index(warning) < page.index("<h2>Summary</h2>")

        assert json.loads(report.to_json())["warnings"] == [warning]

    def test_an_ordinary_report_warns_about_nothing(self, base, candidate):
        report = compare(base, candidate, keys="USUBJID")
        assert report.warnings == ()
        assert "WARNING" not in report.to_text()
        assert json.loads(report.to_json())["warnings"] == []


# ── BY groups ─────────────────────────────────────────────────────────────────


def _by_base() -> pl.DataFrame:
    return pl.from_repr("""\
┌─────────┬────────┬─────┬──────┐
│ USUBJID ┆ TRT01P ┆ AGE ┆ WT   │
│ ---     ┆ ---    ┆ --- ┆ ---  │
│ str     ┆ str    ┆ i64 ┆ f64  │
╞═════════╪════════╪═════╪══════╡
│ 01      ┆ A      ┆ 34  ┆ 70.1 │
│ 02      ┆ A      ┆ 45  ┆ 55.2 │
│ 03      ┆ B      ┆ 52  ┆ 60.3 │
│ 04      ┆ C      ┆ 61  ┆ 80.0 │
└─────────┴────────┴─────┴──────┘
""")


def _by_candidate() -> pl.DataFrame:
    """Subject 02's AGE and subject 03's WT differ; arm C is gone and arm D is new."""
    return pl.from_repr("""\
┌─────────┬────────┬─────┬──────┐
│ USUBJID ┆ TRT01P ┆ AGE ┆ WT   │
│ ---     ┆ ---    ┆ --- ┆ ---  │
│ str     ┆ str    ┆ i64 ┆ f64  │
╞═════════╪════════╪═════╪══════╡
│ 01      ┆ A      ┆ 34  ┆ 70.1 │
│ 02      ┆ A      ┆ 46  ┆ 55.2 │
│ 03      ┆ B      ┆ 52  ┆ 61.0 │
│ 05      ┆ D      ┆ 70  ┆ 75.0 │
└─────────┴────────┴─────┴──────┘
""")


@pytest.fixture
def grouped() -> ComparisonReport:
    return compare(_by_base(), _by_candidate(), keys="USUBJID", by="TRT01P")


class TestByGroups:
    def test_by_variables_are_prepended_to_the_keys_and_need_not_be_repeated(self, grouped):
        assert grouped.settings.by == ("TRT01P",)
        assert grouped.settings.keys == ("TRT01P", "USUBJID")

    def test_repeating_a_by_variable_among_the_keys_is_harmless(self):
        report = compare(_by_base(), _by_base(), keys=["USUBJID", "TRT01P"], by=["TRT01P"])
        assert report.settings.keys == ("TRT01P", "USUBJID")
        assert report.is_equal is True

    def test_a_by_variable_is_not_a_compared_variable(self, grouped):
        assert "TRT01P" not in grouped.variables.common

    def test_the_listing_carries_the_group_label_and_is_sorted_by_group_first(self, grouped):
        assert [(r["group"], r["variable"]) for r in _listing_rows(grouped)] == [
            ("TRT01P=A", "AGE"),
            ("TRT01P=B", "WT"),
        ]

    def test_the_observation_summary_is_reported_per_group(self, grouped):
        per_group = grouped.observations.per_group
        assert per_group.columns == ["group", "matched", "base_only", "candidate_only"]
        assert per_group.rows() == [
            ("TRT01P=A", 2, 0, 0),
            ("TRT01P=B", 1, 0, 0),
            ("TRT01P=C", 0, 1, 0),
            ("TRT01P=D", 0, 0, 1),
        ]

    def test_the_values_summary_is_reported_per_group(self, grouped):
        per_group = grouped.values.per_group
        assert per_group.columns == [
            "group",
            "variables_with_differences",
            "observations_with_differences",
            "differences",
        ]
        assert per_group.rows() == [("TRT01P=A", 1, 1, 1), ("TRT01P=B", 1, 1, 1)]

    def test_a_group_on_one_side_only_raises_its_flag_and_is_listed(self, grouped):
        assert {"base_only_groups", "candidate_only_groups"} <= grouped.flags
        assert grouped.observations.base_only_groups == ("TRT01P=C",)
        assert grouped.observations.candidate_only_groups == ("TRT01P=D",)

    def test_the_verdict_stays_global(self):
        assert compare(_by_base(), _by_base(), keys="USUBJID", by="TRT01P").is_equal is True
        one_arm_differs = _by_base().with_columns(
            pl.when(pl.col("TRT01P") == "B").then(0).otherwise(pl.col("AGE")).alias("AGE")
        )
        report = compare(_by_base(), one_arm_differs, keys="USUBJID", by="TRT01P")
        assert report.is_equal is False
        assert report.values.per_group.rows() == [
            ("TRT01P=A", 0, 0, 0),
            ("TRT01P=B", 1, 1, 1),
            ("TRT01P=C", 0, 0, 0),
        ]

    def test_without_by_the_per_group_frames_are_empty_and_the_group_column_null(self, base):
        report = compare(base, base, keys="USUBJID")
        assert report.settings.by == ()
        assert report.observations.per_group.height == 0
        assert report.values.per_group.height == 0
        assert report.observations.base_only_groups == ()
        assert report.listing["group"].is_null().all()

    def test_several_by_variables_label_the_group_with_each(self):
        b = pl.from_repr("""\
┌─────┬────────┬───────┬─────┐
│ ID  ┆ TRT01P ┆ AVISIT┆ X   │
│ --- ┆ ---    ┆ ---   ┆ --- │
│ i64 ┆ str    ┆ i64   ┆ i64 │
╞═════╪════════╪═══════╪═════╡
│ 1   ┆ A      ┆ 1     ┆ 10  │
│ 2   ┆ A      ┆ 2     ┆ 20  │
└─────┴────────┴───────┴─────┘
""")
        c = b.with_columns(pl.col("X") + 1)
        report = compare(b, c, keys="ID", by=["TRT01P", "AVISIT"])
        assert report.settings.keys == ("TRT01P", "AVISIT", "ID")
        assert report.listing["group"].to_list() == [
            "TRT01P=A, AVISIT=1",
            "TRT01P=A, AVISIT=2",
        ]

    def test_a_null_group_value_reads_as_null(self):
        b = pl.DataFrame({"ID": [1], "G": [None], "X": [1]})
        c = pl.DataFrame({"ID": [1], "G": [None], "X": [2]})
        report = compare(b, c, keys="ID", by="G")
        assert report.listing["group"].to_list() == ["G=null"]

    def test_groups_are_still_counted_when_nothing_is_comparable(self):
        b = _by_base().select("USUBJID", "TRT01P", "AGE")
        c = _by_base().select("USUBJID", "TRT01P", "WT")
        report = compare(b, c, keys="USUBJID", by="TRT01P")
        assert report.variables.compared == ()
        assert report.observations.per_group["matched"].to_list() == [2, 1, 1]
        assert report.values.per_group.rows() == [
            ("TRT01P=A", 0, 0, 0),
            ("TRT01P=B", 0, 0, 0),
            ("TRT01P=C", 0, 0, 0),
        ]

    def test_a_missing_by_variable_stops_the_compare(self, base):
        with pytest.raises(ComparisonError, match="TRT01P"):
            compare(base, base, keys="USUBJID", by="TRT01P")

    def test_by_may_not_reuse_a_listing_column_name(self):
        b = pl.DataFrame({"ID": [1], "group": ["A"], "X": [1]})
        with pytest.raises(ComparisonError, match="group"):
            compare(b, b, keys="ID", by="group")

    def test_by_must_be_a_name_or_a_sequence_of_names(self, base):
        with pytest.raises(VerbUsageError, match="by"):
            compare(base, base, keys="USUBJID", by=1)

    def test_by_may_not_repeat_a_variable(self, base):
        with pytest.raises(ComparisonError, match="SEX"):
            compare(base, base, keys="USUBJID", by=["SEX", "SEX"])


class TestGroupedRenderers:
    """Per-group counts reach the text, JSON and HTML renderers."""

    def test_the_text_report_sections_the_listing_per_group(self, grouped):
        listing = grouped.to_text().split("Value listing")[1]
        assert "Group TRT01P=A" in listing and "Group TRT01P=B" in listing
        arm_a = listing[listing.index("Group TRT01P=A") : listing.index("Group TRT01P=B")]
        assert "USUBJID=02" in arm_a and "AGE" in arm_a and "WT" not in arm_a
        assert "TRT01P=A, USUBJID=02" not in arm_a  # the group heading carries the BY value

    def test_the_text_report_shows_per_group_counts_in_both_summaries(self, grouped):
        text = grouped.to_text()
        observations = text.split("Observation summary")[1].split("Values summary")[0]
        assert "Groups in base only:" in observations and "TRT01P=C" in observations
        assert "Groups in candidate only:" in observations and "TRT01P=D" in observations
        assert "TRT01P=A" in observations

        values = text.split("Values summary")[1].split("Value listing")[0]
        assert "Group" in values and "TRT01P=A" in values and "TRT01P=B" in values

    def test_an_ungrouped_text_report_has_no_group_sections(self, base, candidate):
        text = compare(base, candidate, keys="USUBJID").to_text()
        assert "Group" not in text

    def test_the_json_document_carries_the_per_group_counts_and_the_one_sided_groups(self, grouped):
        document = json.loads(grouped.to_json())
        observations = document["observations"]
        assert observations["base_only_groups"] == ["TRT01P=C"]
        assert observations["candidate_only_groups"] == ["TRT01P=D"]
        assert observations["base_duplicates"] == 0
        assert observations["candidate_duplicates"] == 0
        assert observations["per_group"][0] == {
            "group": "TRT01P=A",
            "matched": 2,
            "base_only": 0,
            "candidate_only": 0,
        }
        assert document["values"]["per_group"] == [
            {
                "group": "TRT01P=A",
                "variables_with_differences": 1,
                "observations_with_differences": 1,
                "differences": 1,
            },
            {
                "group": "TRT01P=B",
                "variables_with_differences": 1,
                "observations_with_differences": 1,
                "differences": 1,
            },
        ]
        assert document["settings"]["by"] == ["TRT01P"]
        assert document["settings"]["allow_duplicates"] is False

    def test_the_html_report_shows_the_group_sections_and_counts(self, grouped):
        page = grouped.to_html()
        chips = page[page.index("NOT EQUAL") : page.index("<h2>Summary</h2>")]
        assert "Groups in base only" in chips and "TRT01P=C" in chips
        assert "Groups in candidate only" in chips and "TRT01P=D" in chips

        groups = page[page.index("<h2>Groups</h2>") : page.index("<h2>Unequal values</h2>")]
        assert "TRT01P=A" in groups and "TRT01P=D" in groups

        listing = page[page.index("<h2>Unequal values</h2>") :]
        assert "Group TRT01P=A" in listing and "Group TRT01P=B" in listing

    def test_an_ungrouped_html_report_has_no_groups_section(self, base, candidate):
        assert "<h2>Groups</h2>" not in compare(base, candidate, keys="USUBJID").to_html()


class TestSettingsOnEverySurface:
    """The three options reach the report and every renderer shows what was in effect."""

    def test_settings_record_the_three_options(self, base):
        report = compare(
            base, base, keys="USUBJID", abs_tol=0.5, rel_tol=0.01, ignore_trailing_whitespace=True
        )
        assert report.settings.abs_tol == 0.5
        assert report.settings.rel_tol == 0.01
        assert report.settings.ignore_trailing_whitespace is True

    def test_the_default_equality_phrase_is_exact(self, base):
        assert compare(base, base, keys="USUBJID").settings.equality == "exact"

    def test_the_equality_phrase_names_both_tolerances_and_the_whitespace_rule(self, base):
        settings = compare(
            base, base, keys="USUBJID", abs_tol=0.001, rel_tol=0.01, ignore_trailing_whitespace=True
        ).settings
        assert settings.equality == "abs_tol=0.001, rel_tol=0.01, ignoring trailing whitespace"

    def test_the_text_report_carries_a_settings_line(self, base):
        text = compare(base, base, keys="USUBJID", abs_tol=0.001).to_text()
        settings_line = next(line for line in text.splitlines() if "Settings:" in line)
        assert "abs_tol=0.001" in settings_line and "rel_tol=0" in settings_line
        assert "Settings:  exact" in compare(base, base, keys="USUBJID").to_text()

    def test_the_json_settings_block_carries_the_three_options(self, base):
        settings = json.loads(
            compare(
                base,
                base,
                keys="USUBJID",
                abs_tol=0.5,
                rel_tol=0.01,
                ignore_trailing_whitespace=True,
            ).to_json()
        )["settings"]
        assert settings["abs_tol"] == 0.5
        assert settings["rel_tol"] == 0.01
        assert settings["ignore_trailing_whitespace"] is True
        assert list(settings) == [f.name for f in dataclasses.fields(ComparisonSettings)]

    def test_the_html_header_shows_the_settings(self, base, candidate):
        html = compare(base, candidate, keys="USUBJID", abs_tol=0.25, rel_tol=0.1).to_html()
        header = html[: html.index("<h2>Observations")]
        assert "abs_tol=0.25, rel_tol=0.1" in header
        assert "exact" in compare(base, candidate, keys="USUBJID").to_html()


# ── Variable pairs and restriction ────────────────────────────────────────────


class TestVariablePairs:
    """``pairs`` compares two variables under different names, on top of name matching."""

    def test_a_renamed_variable_is_missing_on_both_sides_until_it_is_paired(self, base):
        renamed = base.rename({"WT": "WEIGHT"})
        unpaired = compare(base, renamed, keys="USUBJID")
        assert unpaired.variables.base_only == ("WT",)
        assert unpaired.variables.candidate_only == ("WEIGHT",)
        assert unpaired.raised_flags == ("base_only_variables", "candidate_only_variables")

        paired = compare(base, renamed, keys="USUBJID", pairs={"WT": "WEIGHT"})
        assert paired.is_equal is True
        assert paired.variables.base_only == () and paired.variables.candidate_only == ()
        assert paired.variables.compared == ("AGE", "SEX", "WT")

    def test_a_paired_variable_is_listed_under_its_base_name(self, base):
        candidate = base.rename({"WT": "WEIGHT"}).with_columns(pl.lit(99.0).alias("WEIGHT"))
        report = compare(base, candidate, keys="USUBJID", pairs={"WT": "WEIGHT"})
        assert report.flags == {"values_differ"}
        assert report.listing["variable"].to_list() == ["WT"] * 4
        assert report.listing["base"].to_list() == ["70.1", "55.2", "60.3", "80.0"]
        assert report.listing["candidate"].to_list() == ["99.0"] * 4
        assert dict(report.values.per_variable.iter_rows())["WT"] == 4

    def test_name_matching_still_applies_to_the_unpaired_variables(self, base):
        candidate = base.rename({"WT": "WEIGHT"}).with_columns(pl.lit(99).alias("AGE"))
        report = compare(base, candidate, keys="USUBJID", pairs={"WT": "WEIGHT"})
        assert report.variables.compared == ("AGE", "SEX", "WT")
        assert report.listing["variable"].unique().to_list() == ["AGE"]

    def test_a_pair_target_absent_from_the_candidate_is_reported_as_missing(self, base):
        report = compare(base, base.drop("WT"), keys="USUBJID", pairs={"WT": "WEIGHT"})
        assert report.variables.base_only == ("WT",)
        assert "WT" not in report.variables.compared
        assert "base_only_variables" in report.flags

    def test_a_paired_variable_of_another_dtype_is_compared_after_casting(self, base):
        candidate = base.rename({"AGE": "AGEN"}).with_columns(pl.col("AGEN").cast(pl.Float64))
        report = compare(base, candidate, keys="USUBJID", pairs={"AGE": "AGEN"})
        assert report.is_equal is True
        assert [
            (d.variable, str(d.base_dtype), str(d.candidate_dtype))
            for d in report.variables.dtype_differences
        ] == [("AGE", "Int64", "Float64")]

    def test_a_paired_variable_of_another_kind_is_a_type_conflict(self, base):
        candidate = base.rename({"AGE": "AGEC"}).with_columns(pl.col("AGEC").cast(pl.String))
        report = compare(base, candidate, keys="USUBJID", pairs={"AGE": "AGEC"})
        assert [c.variable for c in report.variables.type_conflicts] == ["AGE"]
        assert "AGE" not in report.variables.compared
        assert "type_conflicts" in report.flags

    @pytest.mark.parametrize(
        "pairs, message",
        [
            pytest.param({"FOO": "WEIGHT"}, "absent from the base", id="unknown-base-variable"),
            pytest.param({"USUBJID": "SUBJID"}, "may not rename a key", id="key"),
            pytest.param({"AGE": "X", "WT": "X"}, "more than one", id="two-pairs-one-target"),
        ],
    )
    def test_a_pair_that_cannot_be_honoured_is_refused(self, base, pairs, message):
        with pytest.raises(ComparisonError, match=message):
            compare(base, base, keys="USUBJID", pairs=pairs)

    @pytest.mark.parametrize("pairs", [["WT", "WEIGHT"], {"WT": 1}, "WT=WEIGHT"])
    def test_pairs_must_be_a_mapping_of_names(self, base, pairs):
        with pytest.raises(VerbUsageError, match="pairs"):
            compare(base, base, keys="USUBJID", pairs=pairs)


class TestVariableRestriction:
    """``variables`` narrows the universe; what is outside it neither compares nor flags."""

    def test_the_restriction_narrows_what_is_compared(self, base, candidate):
        report = compare(base, candidate, keys="USUBJID", variables=["AGE"])
        assert report.variables.common == ("AGE",)
        assert report.variables.compared == ("AGE",)
        assert report.listing["variable"].unique().to_list() == ["AGE"]

    def test_a_candidate_column_outside_the_restriction_raises_no_flag(self, base, candidate):
        report = compare(base, candidate, keys="USUBJID", variables=["AGE", "SEX"])
        assert report.variables.candidate_only == ()  # RACE is ignored entirely
        assert "candidate_only_variables" not in report.flags

    def test_a_base_column_outside_the_restriction_raises_no_flag(self, base):
        candidate = base.drop("WT")
        assert compare(base, candidate, keys="USUBJID").flags == {"base_only_variables"}
        assert compare(base, candidate, keys="USUBJID", variables=["AGE", "SEX"]).is_equal is True

    def test_a_restricted_variable_absent_from_the_candidate_is_still_reported(self, base):
        report = compare(base, base.drop("WT"), keys="USUBJID", variables=["WT"])
        assert report.variables.base_only == ("WT",)
        assert "base_only_variables" in report.flags

    def test_a_restricted_variable_absent_from_the_base_is_still_reported(self, base, candidate):
        report = compare(base, candidate, keys="USUBJID", variables=["RACE"])
        assert report.variables.candidate_only == ("RACE",)
        assert "candidate_only_variables" in report.flags

    def test_the_restriction_accepts_one_name(self, base, candidate):
        report = compare(base, candidate, keys="USUBJID", variables="AGE")
        assert report.settings.variables == ("AGE",)
        assert report.variables.compared == ("AGE",)

    def test_a_restriction_composes_with_a_pair(self, base):
        candidate = base.rename({"WT": "WEIGHT"}).with_columns(pl.lit(99).alias("AGE"))
        report = compare(base, candidate, keys="USUBJID", pairs={"WT": "WEIGHT"}, variables=["WT"])
        assert report.is_equal is True  # AGE differs, but it is outside the restriction
        assert report.variables.compared == ("WT",)

    def test_an_empty_restriction_is_refused(self, base):
        with pytest.raises(ComparisonError, match="variables"):
            compare(base, base, keys="USUBJID", variables=[])

    def test_a_restriction_naming_a_variable_on_neither_side_is_refused(self, base, candidate):
        with pytest.raises(ComparisonError, match="FOO"):
            compare(base, candidate, keys="USUBJID", variables=["AGE", "FOO"])

    def test_a_restriction_naming_only_keys_is_refused(self, base):
        with pytest.raises(ComparisonError, match="only key variables"):
            compare(base, base, keys="USUBJID", variables=["USUBJID"])

    def test_the_restriction_must_be_a_name_or_a_sequence_of_names(self, base):
        with pytest.raises(VerbUsageError, match="variables"):
            compare(base, base, keys="USUBJID", variables=42)


class TestMatchingSettingsOnEverySurface:
    """Both matching options reach the report and every renderer says they were in effect."""

    @pytest.fixture
    def report(self, base) -> ComparisonReport:
        candidate = base.rename({"WT": "WEIGHT"})
        return compare(
            base, candidate, keys="USUBJID", pairs={"WT": "WEIGHT"}, variables=["AGE", "WT"]
        )

    def test_the_settings_record_both_options(self, report):
        assert report.settings.pairs == {"WT": "WEIGHT"}
        assert report.settings.variables == ("AGE", "WT")

    def test_the_text_report_names_the_pairs_and_the_restriction(self, report):
        text = report.to_text()
        assert "Pairs:     WT = WEIGHT" in text
        assert "Variables: AGE, WT" in text

    def test_an_ordinary_comparison_says_nothing_about_either(self, base):
        text = compare(base, base, keys="USUBJID").to_text()
        assert "Pairs:" not in text and "Variables: " not in text

    def test_the_json_settings_block_carries_both_options(self, report):
        settings = json.loads(report.to_json())["settings"]
        assert settings["pairs"] == {"WT": "WEIGHT"}
        assert settings["variables"] == ["AGE", "WT"]
        assert list(settings) == [f.name for f in dataclasses.fields(ComparisonSettings)]

    def test_the_json_settings_are_empty_without_them(self, base):
        settings = json.loads(compare(base, base, keys="USUBJID").to_json())["settings"]
        assert settings["pairs"] == {}
        assert settings["variables"] is None

    def test_the_html_report_names_the_pairs_and_the_restriction(self, report):
        page = report.to_html()
        assert "Pairs: WT = WEIGHT" in page
        assert "Restricted to: AGE, WT" in page


# ── Text report ───────────────────────────────────────────────────────────────


_SECTIONS = [
    "Data set summary",
    "Variables summary",
    "Observation summary",
    "Values summary",
    "Summary statistics",
    "Value listing",
    "Verdict",
]


def _positions(text: str, needles: list[str]) -> list[int]:
    positions = [text.find(n) for n in needles]
    assert all(p >= 0 for p in positions), [n for n, p in zip(needles, positions) if p < 0]
    return positions


class TestTextReport:
    def test_sections_render_in_proc_compare_order(self, base, candidate):
        text = compare(
            base, candidate, keys="USUBJID", base_name="prod", candidate_name="qc"
        ).to_text()
        positions = _positions(text, _SECTIONS)
        assert positions == sorted(positions)
        assert "prod" in text and "qc" in text
        assert "RACE" in text  # candidate-only variable
        assert "USUBJID=04" in text  # base-only observation
        assert "USUBJID=05" in text  # candidate-only observation
        assert "NOT EQUAL" in text
        for flag in ("candidate_only_variables", "values_differ"):
            assert flag in text

    def test_equal_report_says_so(self, base):
        text = compare(base, base, keys="USUBJID").to_text()
        assert "EQUAL" in text
        assert "NOT EQUAL" not in text
        positions = _positions(text, _SECTIONS)
        assert positions == sorted(positions)

    def test_listing_is_grouped_per_observation(self, base, candidate):
        text = compare(base, candidate, keys="USUBJID").to_text()
        listing = text[text.index("Value listing") :]
        assert listing.count("USUBJID=03") == 1
        after_03 = listing[listing.index("USUBJID=03") :]
        assert after_03.index("SEX") < after_03.index("WT")
        assert re.search(r"AGE\s+45\s+46\s+1\b", listing)

    def test_type_conflicts_and_dtype_differences_are_shown(self, base):
        c = base.with_columns(pl.col("AGE").cast(pl.Float64), pl.col("SEX").cast(pl.Categorical))
        c = c.with_columns(pl.col("WT").cast(pl.String))
        text = compare(base, c, keys="USUBJID").to_text()
        assert "WT" in text and "Int64" not in text.split("Observation summary")[1]
        variables = text.split("Variables summary")[1].split("Observation summary")[0]
        assert "WT" in variables and "String" in variables
        assert "AGE" in variables and "Float64" in variables

    def test_statistics_render_between_the_values_summary_and_the_listing(self, base, candidate):
        text = compare(base, candidate, keys="USUBJID").to_text()
        statistics = text[text.index("Summary statistics") : text.index("Value listing")]
        assert "AGE" in statistics
        assert "43.6667" in statistics and "9.07377" in statistics  # base mean and std
        for label in ("Base", "Candidate", "Difference", "% difference"):
            assert label in statistics
        assert "SEX" in statistics  # a string contributes only its count

    def test_an_equal_comparison_shows_an_empty_statistics_section(self, base):
        text = compare(base, base, keys="USUBJID").to_text()
        statistics = text[text.index("Summary statistics") : text.index("Value listing")]
        assert "No unequal values" in statistics

    def test_default_limits_are_50_per_variable_and_500_overall(self):
        n = 120
        b = pl.DataFrame({"ID": range(n), "A": [0] * n, "B": [0] * n})
        c = pl.DataFrame({"ID": range(n), "A": [1] * n, "B": [1] * n})
        report = compare(b, c, keys="ID")
        assert report.listing.height == 2 * n  # the listing itself is never truncated
        text = report.to_text()
        listing = text[text.index("Value listing") :]
        assert len(re.findall(r"\bA\b", listing)) == 50
        assert len(re.findall(r"\bB\b", listing)) == 50
        assert "100 of 240" in listing

    def test_overall_limit_of_500(self):
        n = 30
        columns = {f"V{i}": [0] * n for i in range(20)}
        b = pl.DataFrame({"ID": range(n), **columns})
        c = pl.DataFrame({"ID": range(n), **{k: [1] * n for k in columns}})
        report = compare(b, c, keys="ID")
        assert report.values.total_differences == 600
        listing = report.to_text()[report.to_text().index("Value listing") :]
        assert len(re.findall(r"\bV\d+\b", listing)) == 500
        assert "500 of 600" in listing

    def test_max_print_none_prints_everything(self):
        n = 120
        b = pl.DataFrame({"ID": range(n), "A": [0] * n})
        c = pl.DataFrame({"ID": range(n), "A": [1] * n})
        report = compare(b, c, keys="ID", max_print=None)
        text = report.to_text()
        listing = text[text.index("Value listing") :]
        assert len(re.findall(r"\bA\b", listing)) == n
        assert f"showing all {n} unequal values" in listing.splitlines()[2]
        # the renderer accepts an override too
        capped = report.to_text(max_print=10)
        assert len(re.findall(r"\bA\b", capped[capped.index("Value listing") :])) == 10
        assert compare(b, c, keys="ID").to_text(max_print=None).count(" A ") >= n

    def test_max_print_pair_sets_both_limits(self):
        n = 40
        b = pl.DataFrame({"ID": range(n), "A": [0] * n, "B": [0] * n})
        c = pl.DataFrame({"ID": range(n), "A": [1] * n, "B": [1] * n})
        text = compare(b, c, keys="ID", max_print=(30, 45)).to_text()
        listing = text[text.index("Value listing") :]
        assert len(re.findall(r"\b[AB]\b", listing)) == 45

    def test_max_print_rejects_bad_values(self, base):
        with pytest.raises(VerbUsageError):
            compare(base, base, keys="USUBJID", max_print="all")  # type: ignore[arg-type]

    def test_print_report_emits_through_the_fleet_logger(self, base, candidate, capsys):
        report = compare(base, candidate, keys="USUBJID")
        report.print_report()
        out = capsys.readouterr().out
        assert "Value listing" in out
        assert "NOT EQUAL" in out

    def test_str_is_the_text_report(self, base):
        report = compare(base, base, keys="USUBJID")
        assert str(report) == report.to_text()

    def test_summary_is_a_one_liner(self, base, candidate):
        summary = compare(base, candidate, keys="USUBJID").summary
        assert "\n" not in summary
        assert "NOT EQUAL" in summary
        assert "EQUAL" in compare(base, base, keys="USUBJID").summary


# ── JSON and parquet ──────────────────────────────────────────────────────────

#: The top-level keys of the JSON document, in order, as documented on the
#: concepts page.  Additive-only within a major version.
_JSON_KEYS = [
    "is_equal",
    "summary",
    "flags",
    "warnings",
    "datasets",
    "variables",
    "observations",
    "values",
    "statistics",
    "listing",
    "settings",
    "version",
]


class TestJsonReport:
    def test_json_round_trips_with_every_documented_top_level_key(self, base, candidate):
        document = json.loads(compare(base, candidate, keys="USUBJID").to_json())
        assert list(document) == _JSON_KEYS
        assert list(JSON_KEYS) == _JSON_KEYS

    def test_document_mirrors_the_report(self, base, candidate):
        report = compare(base, candidate, keys="USUBJID", base_name="prod", candidate_name="qc")
        document = json.loads(report.to_json())
        assert document["is_equal"] is False
        assert document["summary"] == report.summary
        assert document["flags"] == [
            "candidate_only_variables",
            "base_only_observations",
            "candidate_only_observations",
            "values_differ",
        ]
        assert document["datasets"] == {
            "base": {"name": "prod", "rows": 4, "variables": 4},
            "candidate": {"name": "qc", "rows": 4, "variables": 5},
        }
        assert document["variables"] == {
            "common": ["AGE", "SEX", "WT"],
            "compared": ["AGE", "SEX", "WT"],
            "base_only": [],
            "candidate_only": ["RACE"],
            "type_conflicts": [],
            "dtype_differences": [],
        }
        assert document["observations"] == {
            "matched": 3,
            "base_only": 1,
            "candidate_only": 1,
            "base_only_keys": [{"USUBJID": "04"}],
            "candidate_only_keys": [{"USUBJID": "05"}],
            "base_duplicates": 0,
            "candidate_duplicates": 0,
            "per_group": [],
            "base_only_groups": [],
            "candidate_only_groups": [],
            "truncated": False,
        }
        assert document["values"] == {
            "per_variable": [
                {"variable": "AGE", "differences": 1},
                {"variable": "SEX", "differences": 1},
                {"variable": "WT", "differences": 1},
            ],
            "variables_with_differences": 3,
            "observations_with_differences": 2,
            "total_differences": 3,
            "per_group": [],
        }
        assert [r["variable"] for r in document["statistics"]] == ["AGE", "SEX", "WT"]
        assert document["settings"] == {
            "keys": ["USUBJID"],
            "by": [],
            "pairs": {},
            "variables": None,
            "abs_tol": 0.0,
            "rel_tol": 0.0,
            "ignore_trailing_whitespace": False,
            "allow_duplicates": False,
            "max_print": 50,
            "base_name": "prod",
            "candidate_name": "qc",
        }
        assert document["version"] == fleet.__version__

    def test_listing_rows_carry_the_listing_columns(self, base, candidate):
        listing = json.loads(compare(base, candidate, keys="USUBJID").to_json())["listing"]
        assert listing["columns"] == ["USUBJID", *LISTING_COLUMNS]
        assert (listing["shown"], listing["total"], listing["truncated"]) == (3, 3, False)
        first = listing["rows"][0]
        assert first["percent_difference"] == pytest.approx(2.2222, abs=1e-3)
        del first["percent_difference"]
        assert first == {
            "USUBJID": "02",
            "group": None,
            "variable": "AGE",
            "base": "45",
            "candidate": "46",
            "difference": 1.0,
        }
        assert [(r["USUBJID"], r["variable"]) for r in listing["rows"]] == [
            ("02", "AGE"),
            ("03", "SEX"),
            ("03", "WT"),
        ]

    def test_statistics_carry_one_record_per_differing_variable(self, base, candidate):
        report = compare(base, candidate, keys="USUBJID")
        statistics = json.loads(report.to_json())["statistics"]
        assert [list(r) for r in statistics] == [_STATISTICS_COLUMNS] * 3
        age = statistics[0]
        assert (age["variable"], age["differences"], age["base_n"]) == ("AGE", 1, 3)
        assert age["base_mean"] == pytest.approx(131 / 3)
        assert statistics[1]["variable"] == "SEX"
        assert all(statistics[1][m] is None for m in _MEASURES)  # a string, only a count
        assert json.loads(compare(base, base, keys="USUBJID").to_json())["statistics"] == []

    def test_type_conflicts_and_dtype_differences_name_dtypes_as_text(self, base):
        c = base.with_columns(pl.col("AGE").cast(pl.Float64), pl.col("WT").cast(pl.String))
        variables = json.loads(compare(base, c, keys="USUBJID").to_json())["variables"]
        assert variables["type_conflicts"] == [
            {"variable": "WT", "base_dtype": "Float64", "candidate_dtype": "String"}
        ]
        assert variables["dtype_differences"] == [
            {"variable": "AGE", "base_dtype": "Int64", "candidate_dtype": "Float64"}
        ]
        assert variables["compared"] == ["AGE", "SEX"]

    def test_listing_is_truncated_to_the_print_limits_with_a_marker(self):
        n = 120
        b = pl.DataFrame({"ID": range(n), "A": [0] * n, "B": [0] * n})
        c = pl.DataFrame({"ID": range(n), "A": [1] * n, "B": [1] * n})
        report = compare(b, c, keys="ID")

        listing = json.loads(report.to_json())["listing"]
        assert (listing["shown"], listing["total"], listing["truncated"]) == (100, 240, True)
        assert len(listing["rows"]) == 100
        assert sum(r["variable"] == "A" for r in listing["rows"]) == 50

        everything = json.loads(report.to_json(max_print=None))["listing"]
        assert (everything["shown"], everything["total"], everything["truncated"]) == (
            240,
            240,
            False,
        )
        assert len(everything["rows"]) == 240

        settings = json.loads(compare(b, c, keys="ID", max_print=None).to_json())
        assert settings["listing"]["truncated"] is False
        assert settings["settings"]["max_print"] is None

    def test_one_sided_key_lists_are_capped_like_the_text(self):
        b = pl.DataFrame({"ID": range(60), "A": [0] * 60})
        observations = json.loads(compare(b, b.head(0), keys="ID", max_print=10).to_json())[
            "observations"
        ]
        assert observations["base_only"] == 60
        assert observations["base_only_keys"] == [{"ID": i} for i in range(10)]
        assert observations["truncated"] is True

    def test_settings_record_every_option(self, base):
        settings = json.loads(compare(base, base, keys="USUBJID", max_print=(30, 45)).to_json())[
            "settings"
        ]
        assert settings["max_print"] == [30, 45]
        assert list(settings) == [f.name for f in dataclasses.fields(ComparisonSettings)]

    def test_strict_json_for_temporal_keys_and_non_finite_differences(self):
        b = pl.DataFrame({"DT": [date(2026, 1, 1), date(2026, 1, 2)], "X": [1.0, 2.0]})
        c = pl.DataFrame({"DT": [date(2026, 1, 1), date(2026, 1, 2)], "X": [NAN, 3.0]})
        text = compare(b, c, keys="DT").to_json()

        def reject(constant: str) -> None:
            raise AssertionError(f"non-standard JSON constant {constant}")

        rows = json.loads(text, parse_constant=reject)["listing"]["rows"]
        assert rows[0] == {
            "DT": "2026-01-01",
            "group": None,
            "variable": "X",
            "base": "1.0",
            "candidate": "NaN",
            "difference": None,
            "percent_difference": None,
        }
        assert rows[1]["difference"] == 1.0

    def test_indent_none_renders_one_line(self, base):
        text = compare(base, base, keys="USUBJID").to_json(indent=None)
        assert "\n" not in text
        assert json.loads(text)["is_equal"] is True


class TestSavedOutputs:
    def test_save_json_writes_the_same_document(self, base, candidate, tmp_path):
        report = compare(base, candidate, keys="USUBJID")
        path = tmp_path / "compare.json"
        report.save_json(path)
        assert json.loads(path.read_text(encoding="utf-8")) == json.loads(report.to_json())

    def test_save_json_honours_max_print_and_accepts_a_string_path(self, tmp_path):
        n = 120
        b = pl.DataFrame({"ID": range(n), "A": [0] * n})
        c = pl.DataFrame({"ID": range(n), "A": [1] * n})
        path = tmp_path / "compare.json"
        compare(b, c, keys="ID").save_json(str(path), max_print=None)
        listing = json.loads(path.read_text(encoding="utf-8"))["listing"]
        assert (listing["shown"], listing["truncated"]) == (n, False)

    def test_save_listing_writes_the_complete_listing_as_parquet(self, tmp_path):
        n = 120
        b = pl.DataFrame({"ID": range(n), "A": [0] * n, "B": [0] * n})
        c = pl.DataFrame({"ID": range(n), "A": [1] * n, "B": [1] * n})
        report = compare(b, c, keys="ID")
        path = tmp_path / "differences.parquet"
        report.save_listing(path)

        reloaded = pl.read_parquet(path)
        assert reloaded.schema == pl.Schema(
            {
                "ID": pl.Int64,
                "group": pl.String,
                "variable": pl.String,
                "base": pl.String,
                "candidate": pl.String,
                "difference": pl.Float64,
                "percent_difference": pl.Float64,
            }
        )
        assert reloaded.height == 240  # complete, while the JSON listing is truncated
        assert json.loads(report.to_json())["listing"]["truncated"] is True
        assert reloaded.equals(report.listing)

    def test_save_listing_of_an_equal_report_keeps_the_schema(self, base, tmp_path):
        path = tmp_path / "none.parquet"
        compare(base, base, keys="USUBJID").save_listing(str(path))
        reloaded = pl.read_parquet(path)
        assert reloaded.height == 0
        assert reloaded.columns == ["USUBJID", *LISTING_COLUMNS]
        assert reloaded.schema["USUBJID"] == pl.String


class TestHtmlReport:
    """The self-contained page a reviewer without Python opens (ticket #103)."""

    def test_every_mismatched_value_is_on_the_page_and_equal_observations_are_not(
        self, base, candidate
    ):
        report = compare(base, candidate, keys="USUBJID")
        page = report.to_html()
        for row in _listing_rows(report):
            assert row["base"] in page and row["candidate"] in page, row
            assert row["USUBJID"] in page
        assert "<td>01</td>" not in page  # subject 01 is equal on both sides and is not listed
        assert "2.22222" in page  # AGE 45 -> 46: percent difference, as in the text report

    def test_page_is_self_contained_and_escapes_values(self, base, candidate):
        c = candidate.with_columns(pl.col("SEX").str.replace("M", "<M&F>"))
        page = compare(base, c, keys="USUBJID", base_name="a<b").to_html()
        assert not re.search(r"https?://|<link|<script|@import|url\(", page)
        assert "&lt;M&amp;F&gt;" in page and "<M&F>" not in page
        assert "a&lt;b" in page and "a<b" not in page

    def test_equal_comparison_renders_a_clear_equal_page(self, base):
        page = compare(base, base, keys="USUBJID", base_name="prod", candidate_name="qc").to_html()
        assert "EQUAL" in page and "NOT EQUAL" not in page
        assert "No unequal values" in page
        assert "prod" in page and "qc" in page
        for flag in FLAGS:
            assert flag not in page

    def test_chips_reflect_the_flags(self, base, candidate):
        c = candidate.with_columns(pl.col("WT").cast(pl.String))
        page = compare(base, c, keys="USUBJID").to_html()
        chips = page[page.index("NOT EQUAL") : page.index("Summary")]
        assert "Variables in candidate only" in chips and "RACE" in chips
        assert "Type conflicts" in chips and "WT" in chips
        assert "Float64" in chips and "String" in chips
        assert "Observations in base only" in chips and "USUBJID=04" in chips
        assert "Observations in candidate only" in chips and "USUBJID=05" in chips
        assert "Values differ" in chips
        assert "Variables in base only" not in chips
        assert "Duplicate keys" not in chips

    def test_every_flag_has_a_chip(self, base, candidate):
        report = compare(base, candidate, keys="USUBJID")
        page = dataclasses.replace(report, flags=frozenset(FLAGS)).to_html()
        chips = page[page.index("NOT EQUAL") : page.index("Summary")]
        for label in (
            "Variables in base only",
            "Variables in candidate only",
            "Type conflicts",
            "Observations in base only",
            "Observations in candidate only",
            "Values differ",
            "Duplicate keys",
            "Groups in base only",
            "Groups in candidate only",
        ):
            assert label in chips

    def test_one_sided_observation_chips_name_the_first_few_and_the_page_lists_all(self):
        b = pl.DataFrame({"ID": range(20), "A": [0] * 20})
        page = compare(b, b.head(0), keys="ID").to_html()
        chips = page[page.index("NOT EQUAL") : page.index("Summary")]
        assert "20 observations" in chips and "ID=4" in chips and "ID=5" not in chips
        assert "and 15 more" in chips
        listed = page[page.index("Observations in base only (20)") :]
        assert all(f"<td>{i}</td>" in listed for i in range(20))

    def test_dtype_differences_are_information_not_findings(self, base):
        c = base.with_columns(pl.col("AGE").cast(pl.Float64))
        page = compare(base, c, keys="USUBJID").to_html()
        assert "EQUAL" in page and "NOT EQUAL" not in page
        assert "Dtype differences" in page and "AGE" in page
        assert "Int64" in page and "Float64" in page

    def test_one_collapsible_block_per_differing_variable(self, base, candidate):
        page = compare(base, candidate, keys="USUBJID").to_html()
        assert page.count("<details") == 3  # AGE, SEX and WT differ; nothing else gets a block
        listing = page[page.index("Unequal values") :]
        positions = _positions(listing, ["AGE", "SEX", "WT"])
        assert positions == sorted(positions)
        assert compare(base, base, keys="USUBJID").to_html().count("<details") == 0

    def test_blocks_follow_the_listing_even_for_a_variable_the_summary_does_not_know(
        self, base, candidate
    ):
        report = compare(base, candidate, keys="USUBJID")
        renamed = report.listing.with_columns(pl.col("variable").str.replace("WT", "WTKG"))
        page = dataclasses.replace(report, listing=renamed).to_html()
        assert page.count("<details") == 3 and "WTKG" in page and "60.5" in page

    def test_renders_one_section_per_group_when_the_group_column_is_populated(
        self, base, candidate
    ):
        report = compare(base, candidate, keys="USUBJID")
        grouped = report.listing.with_columns(
            pl.when(pl.col("USUBJID") == "02")
            .then(pl.lit("ARM A"))
            .otherwise(pl.lit("ARM B"))
            .alias("group")
        )
        page = dataclasses.replace(report, listing=grouped).to_html()

        listing = page[page.index("Unequal values") :]
        arm_a = listing[listing.index("ARM A") : listing.index("ARM B")]
        arm_b = listing[listing.index("ARM B") :]
        assert "AGE" in arm_a and "SEX" not in arm_a and "WT" not in arm_a
        assert "SEX" in arm_b and "WT" in arm_b and "AGE" not in arm_b
        assert "1 unequal value in 1 observation" in arm_a
        assert "2 unequal values in 1 observation" in arm_b
        assert page.count("<details") == 3
        assert "ARM A" not in report.to_html()  # the ungrouped report has no group sections

    def test_statistics_appear_inside_each_variable_block(self, base, candidate):
        page = compare(base, candidate, keys="USUBJID").to_html()
        age = page[page.index("<summary>AGE") : page.index("<summary>SEX")]
        assert "Summary statistics" in age
        assert "43.6667" in age and "9.07377" in age  # base mean and std
        for label in ("Base", "Candidate", "Difference", "% difference"):
            assert label in age
        sex = page[page.index("<summary>SEX") : page.index("<summary>WT")]
        assert "Summary statistics" not in sex  # a string contributes only its count

    def test_save_html_report_writes_the_page(self, base, candidate, tmp_path):
        c = candidate.with_columns(pl.col("SEX").str.replace("M", "Mâle"))
        report = compare(base, c, keys="USUBJID")
        path = tmp_path / "compare.html"
        report.save_html_report(str(path))
        assert path.read_text(encoding="utf-8") == report.to_html()
        assert "Mâle" in path.read_text(encoding="utf-8")


# ── Purity ────────────────────────────────────────────────────────────────────


def test_no_numpy_or_pandas_import_on_the_compare_path():
    package = Path(fleet.comparison.__file__).parent
    offenders = [
        path.name
        for path in package.rglob("*.py")
        if re.search(r"^\s*(import|from)\s+(numpy|pandas)\b", path.read_text(), re.M)
    ]
    assert offenders == []
