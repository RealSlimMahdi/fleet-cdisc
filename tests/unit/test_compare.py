"""Engine-seam tests for ``fleet.compare`` (ticket #100, spec #99).

Every test builds two small frames in memory, calls the engine and asserts on
the comparison report: its flags, its verdict, the rows of its summary frames
and the rows of its listing.  Nothing here knows how the engine joins or what
its internal columns are called.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import polars as pl
import pytest

import fleet
from fleet.comparison import FLAGS, ComparisonError, ComparisonReport, compare
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

    def test_empty_frames_compare_equal(self, base):
        report = compare(base.clear(), base.clear(), keys=["USUBJID"])
        assert report.is_equal is True
        assert report.observations.matched == 0
        assert report.datasets.base.rows == 0

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


# ── Text report ───────────────────────────────────────────────────────────────


_SECTIONS = [
    "Data set summary",
    "Variables summary",
    "Observation summary",
    "Values summary",
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


# ── Purity ────────────────────────────────────────────────────────────────────


def test_no_numpy_or_pandas_import_on_the_compare_path():
    package = Path(fleet.comparison.__file__).parent
    offenders = [
        path.name
        for path in package.rglob("*.py")
        if re.search(r"^\s*(import|from)\s+(numpy|pandas)\b", path.read_text(), re.M)
    ]
    assert offenders == []
