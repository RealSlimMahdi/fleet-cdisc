"""Tests for the TLG namespace — specs, validation, ARD, AE summary & listing."""

from __future__ import annotations

import polars as pl
import pytest

from fleet.core.exceptions import SchemaError
from fleet.tlg import (
    AEListingSpec,
    AESummarySpec,
    Column,
    GroupPool,
    OverallStat,
    Row,
    Statistic,
    TLGSpec,
    VSSummarySpec,
)
from fleet.tlg._ard import (
    ARD_SCHEMA,
    apply_fmt_fn,
    compute_big_n,
    default_fmt_fn,
    expand_pools,
    validate_ard,
)

# ------------------------------------------------------------------ #
# Fixtures                                                             #
# ------------------------------------------------------------------ #


@pytest.fixture()
def adsl() -> pl.DataFrame:
    """Minimal ADSL with 6 subjects across 3 arms."""
    return pl.DataFrame(
        {
            "USUBJID": [
                "SUBJ-01",
                "SUBJ-02",
                "SUBJ-03",
                "SUBJ-04",
                "SUBJ-05",
                "SUBJ-06",
            ],
            "TRTA": [
                "Placebo",
                "Placebo",
                "Drug A",
                "Drug A",
                "Drug B",
                "Drug B",
            ],
            "SAFFL": ["Y", "Y", "Y", "Y", "Y", "N"],
        }
    )


@pytest.fixture()
def adae() -> pl.DataFrame:
    """Minimal ADAE-like DataFrame for AE summary tests."""
    return pl.DataFrame(
        {
            "USUBJID": [
                "SUBJ-01",
                "SUBJ-01",
                "SUBJ-02",
                "SUBJ-03",
                "SUBJ-03",
                "SUBJ-03",
                "SUBJ-04",
                "SUBJ-05",
            ],
            "TRTA": [
                "Placebo",
                "Placebo",
                "Placebo",
                "Drug A",
                "Drug A",
                "Drug A",
                "Drug A",
                "Drug B",
            ],
            "AEBODSYS": [
                "NERVOUS",
                "GASTRO",
                "NERVOUS",
                "NERVOUS",
                "NERVOUS",
                "GASTRO",
                "GASTRO",
                "NERVOUS",
            ],
            "AEDECOD": [
                "HEADACHE",
                "NAUSEA",
                "HEADACHE",
                "HEADACHE",
                "DIZZINESS",
                "NAUSEA",
                "NAUSEA",
                "HEADACHE",
            ],
            "AESEV": [
                "MILD",
                "MODERATE",
                "MILD",
                "MILD",
                "MILD",
                "MODERATE",
                "MILD",
                "MILD",
            ],
            "AESER": ["N", "N", "N", "N", "N", "Y", "N", "N"],
            "SAFFL": ["Y", "Y", "Y", "Y", "Y", "Y", "Y", "Y"],
        }
    )


# ================================================================== #
# Tier 1 — Structural Validation                                      #
# ================================================================== #


class TestStructuralValidation:
    """Missing columns → SchemaError."""

    def test_missing_required_columns_raises(self) -> None:
        df = pl.DataFrame({"USUBJID": ["A"], "TRTA": ["Placebo"]})
        with pytest.raises(SchemaError, match="missing.*AEDECOD"):
            df.tlg.ae.t_summary(groupby="TRTA")

    def test_all_columns_present_passes(self, adae: pl.DataFrame) -> None:
        # No adsl → allowed only without percentage statistics
        spec = AESummarySpec(statistics=[Statistic.N_SUBJECTS])
        ard = adae.tlg.ae.t_summary(groupby="TRTA", spec=spec)
        assert len(ard) > 0

    def test_pct_without_adsl_raises(self, adae: pl.DataFrame) -> None:
        # Default spec requests n_pct → a missing population must be loud
        with pytest.raises(SchemaError, match="adsl"):
            adae.tlg.ae.t_summary(groupby="TRTA")

    def test_listing_missing_columns_raises(self) -> None:
        df = pl.DataFrame({"USUBJID": ["A"]})
        with pytest.raises(SchemaError, match="missing.*TRTA"):
            df.tlg.ae.l_listing()


# ================================================================== #
# Tier 2 — Content Validation                                         #
# ================================================================== #


class TestContentValidation:
    """Required flag/PARAMCD values must exist in data."""

    def test_missing_flag_value_raises(self) -> None:
        spec = TLGSpec(
            required_columns=["FLAG"],
            required_flags={"FLAG": ["Y"]},
        )
        df = pl.DataFrame({"FLAG": ["N", "N"]})
        with pytest.raises(SchemaError, match="missing.*Y"):
            spec.validate_dataframe(df)

    def test_present_flag_value_passes(self) -> None:
        spec = TLGSpec(
            required_columns=["FLAG"],
            required_flags={"FLAG": ["Y"]},
        )
        df = pl.DataFrame({"FLAG": ["Y", "N"]})
        spec.validate_dataframe(df)  # Should not raise

    def test_missing_flag_column_raises(self) -> None:
        spec = TLGSpec(
            required_columns=[],
            required_flags={"MISSING_COL": ["Y"]},
        )
        df = pl.DataFrame({"OTHER": [1]})
        with pytest.raises(SchemaError, match="MISSING_COL"):
            spec.validate_dataframe(df)


# ================================================================== #
# Tier 3 — Pool Arm Validation                                        #
# ================================================================== #


class TestPoolArmValidation:
    """Referenced pool arms must exist in data."""

    def test_bad_arm_reference_raises(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        spec = AESummarySpec(
            pools=[GroupPool(label="Bad Pool", arms=["Drug A", "NONEXISTENT"])],
        )
        with pytest.raises(SchemaError, match="NONEXISTENT"):
            adae.tlg.ae.t_summary(spec=spec, groupby="TRTA", adsl=adsl)

    def test_wildcard_pool_passes(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        spec = AESummarySpec(
            pools=[GroupPool(label="Total", arms="*")],
        )
        ard = adae.tlg.ae.t_summary(spec=spec, groupby="TRTA", adsl=adsl)
        assert "Total" in ard["group1_level"].to_list()

    def test_valid_pool_passes(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        spec = AESummarySpec(
            pools=[GroupPool(label="All Active", arms=["Drug A", "Drug B"])],
        )
        ard = adae.tlg.ae.t_summary(spec=spec, groupby="TRTA", adsl=adsl)
        assert "All Active" in ard["group1_level"].to_list()


# ================================================================== #
# Pool Stacking Correctness                                            #
# ================================================================== #


class TestPoolStacking:
    """Expand_pools produces correct deduplication and event counts."""

    def test_expand_pools_adds_rows(self, adae: pl.DataFrame) -> None:
        pool = GroupPool(label="All Active", arms=["Drug A", "Drug B"])
        expanded = expand_pools(adae, [pool], "TRTA")
        assert len(expanded) > len(adae)

    def test_wildcard_pool_duplicates_all(self, adae: pl.DataFrame) -> None:
        pool = GroupPool(label="Total", arms="*")
        expanded = expand_pools(adae, [pool], "TRTA")
        # Original rows + all rows relabeled as "Total"
        assert len(expanded) == 2 * len(adae)

    def test_n_unique_dedup_in_pool(self) -> None:
        """Subject in 2 arms counted once in a pool encompassing both."""
        df = pl.DataFrame(
            {
                "USUBJID": ["S1", "S1", "S2"],
                "TRTA": ["Arm A", "Arm B", "Arm A"],
                "AEDECOD": ["AE1", "AE2", "AE1"],
                "AEBODSYS": ["SOC1", "SOC1", "SOC1"],
            }
        )
        pool = GroupPool(label="Both", arms=["Arm A", "Arm B"])
        expanded = expand_pools(df, [pool], "TRTA")
        both_df = expanded.filter(pl.col("TRTA") == "Both")
        # S1 appears from both Arm A and Arm B rows → 2 rows
        # But n_unique should still be 2 (S1, S2)
        assert both_df["USUBJID"].n_unique() == 2

    def test_event_counts_sum_across_pool(self) -> None:
        """Event counts in pool = sum of events from constituent arms."""
        df = pl.DataFrame(
            {
                "USUBJID": ["S1", "S1", "S2", "S3"],
                "TRTA": ["A", "A", "B", "B"],
                "AEDECOD": ["AE1", "AE2", "AE1", "AE1"],
                "AEBODSYS": ["SOC", "SOC", "SOC", "SOC"],
            }
        )
        pool = GroupPool(label="All", arms=["A", "B"])
        expanded = expand_pools(df, [pool], "TRTA")
        all_df = expanded.filter(pl.col("TRTA") == "All")
        assert len(all_df) == 4  # All events from A and B

    def test_big_n_includes_pools(self, adsl: pl.DataFrame) -> None:
        pool = GroupPool(label="All Active", arms=["Drug A", "Drug B"])
        big_n = compute_big_n(adsl, "TRTA", [pool])
        assert big_n["Placebo"] == 2
        assert big_n["Drug A"] == 2
        assert big_n["Drug B"] == 2
        assert big_n["All Active"] == 4  # Subjects from Drug A + Drug B

    def test_big_n_with_filter(self, adsl: pl.DataFrame) -> None:
        big_n = compute_big_n(adsl, "TRTA", [], filter_expr=pl.col("SAFFL") == "Y")
        # SUBJ-06 has SAFFL=N, so Drug B has 1 not 2
        assert big_n["Drug B"] == 1


# ================================================================== #
# ARD Output Structure                                                 #
# ================================================================== #


class TestARDStructure:
    """ARD DataFrame has the correct columns and types."""

    EXPECTED_COLUMNS = {
        "group1",
        "group1_level",
        "group2",
        "group2_level",
        "variable",
        "variable_level",
        "variable_label",
        "stat_name",
        "stat_label",
        "stat",
        "fmt_fn",
        "stat_fmt",
        "warning",
        "error",
        "context",
    }

    def test_ard_columns(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)
        assert set(ard.columns) == self.EXPECTED_COLUMNS

    def test_ard_context_is_t_ae_summary(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)
        assert (ard["context"] == "t_ae_summary").all()

    def test_ard_stat_type_is_float(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)
        assert ard["stat"].dtype == pl.Float64

    def test_ard_has_fmt_fn_column(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)
        assert "fmt_fn" in ard.columns
        assert ard["fmt_fn"].dtype == pl.Utf8
        # All rows should have a non-null format specifier
        assert ard["fmt_fn"].null_count() == 0

    def test_ard_has_stat_fmt_column(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)
        assert "stat_fmt" in ard.columns
        assert ard["stat_fmt"].dtype == pl.Utf8

    def test_ard_warning_error_nullable(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)
        # Clean computation → all null
        assert ard["warning"].null_count() == len(ard)
        assert ard["error"].null_count() == len(ard)

    def test_ard_group2_columns_present(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)
        assert "group2" in ard.columns
        assert "group2_level" in ard.columns

    def test_empty_ard_has_correct_schema(self) -> None:
        # DataFrame with columns but no matching data
        df = pl.DataFrame(
            {
                "USUBJID": ["S1"],
                "TRTA": ["Arm A"],
                "AEBODSYS": ["SOC"],
                "AEDECOD": ["PT"],
            }
        )
        ard = df.tlg.ae.t_summary(groupby="TRTA", adsl=df)
        assert set(ard.columns) == self.EXPECTED_COLUMNS


# ================================================================== #
# ARD Schema Validation                                                #
# ================================================================== #


class TestARDValidation:
    """validate_ard() catches schema violations."""

    def test_valid_ard_passes(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)
        issues = validate_ard(ard)
        assert issues == []

    def test_missing_column_detected(self) -> None:
        bad = pl.DataFrame({"group1": ["TRTA"], "stat": [1.0]})
        issues = validate_ard(bad)
        assert any("Missing required ARD columns" in i for i in issues)

    def test_extra_column_detected(self) -> None:
        good = pl.DataFrame(
            {
                "group1": ["TRTA"],
                "group1_level": ["A"],
                "group2": [""],
                "group2_level": [""],
                "variable": ["X"],
                "variable_level": ["Y"],
                "stat_name": ["n"],
                "stat_label": ["n"],
                "stat": [1.0],
                "fmt_fn": ["xx"],
                "stat_fmt": ["1"],
                "warning": [None],
                "error": [None],
                "context": ["test"],
                "EXTRA": ["bad"],
            }
        )
        issues = validate_ard(good)
        assert any("Unexpected columns" in i for i in issues)

    def test_wrong_dtype_detected(self) -> None:
        bad = pl.DataFrame(
            {
                "variable": ["X"],
                "stat_name": ["n"],
                "stat_label": ["n"],
                "stat": ["not_a_float"],  # wrong type
                "fmt_fn": ["xx"],
                "warning": [None],
                "error": [None],
            }
        )
        issues = validate_ard(bad)
        assert any("stat" in i and "Float64" in i for i in issues)

    def test_empty_ard_flagged(self) -> None:
        empty = pl.DataFrame(schema=ARD_SCHEMA)
        issues = validate_ard(empty)
        assert any("empty" in i.lower() for i in issues)

    def test_t_summary_auto_validates(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        """t_summary() output always passes ARD validation."""
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)
        assert validate_ard(ard) == []


# ================================================================== #
# Known-Data AE Summary Stats                                         #
# ================================================================== #


class TestAESummaryStats:
    """AE summary stats match expected values on known data."""

    def test_big_n_values(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)
        big_n_rows = ard.filter(pl.col("stat_name") == "N")
        big_n_map = dict(
            zip(
                big_n_rows["group1_level"].to_list(),
                big_n_rows["stat"].to_list(),
            )
        )
        assert big_n_map["Placebo"] == 2.0
        assert big_n_map["Drug A"] == 2.0
        assert big_n_map["Drug B"] == 2.0

    def test_n_subjects_headache_placebo(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)
        row = ard.filter(
            (pl.col("variable") == "AEDECOD")
            & (pl.col("variable_level") == "HEADACHE")
            & (pl.col("group1_level") == "Placebo")
            & (pl.col("stat_name") == "n")
        )
        # SUBJ-01 and SUBJ-02 both have HEADACHE under Placebo
        assert row["stat"][0] == 2.0

    def test_n_pct_headache_placebo(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)
        row = ard.filter(
            (pl.col("variable") == "AEDECOD")
            & (pl.col("variable_level") == "HEADACHE")
            & (pl.col("group1_level") == "Placebo")
            & (pl.col("stat_name") == "pct")
        )
        # 2 out of 2 Placebo subjects = 100.0%
        assert row["stat"][0] == 100.0

    def test_event_count_stat(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        spec = AESummarySpec(
            statistics=[Statistic.N_SUBJECTS, Statistic.N_EVENTS],
        )
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl, spec=spec)
        events_row = ard.filter(
            (pl.col("variable") == "AEDECOD")
            & (pl.col("variable_level") == "HEADACHE")
            & (pl.col("group1_level") == "Drug A")
            & (pl.col("stat_name") == "n_events")
        )
        # SUBJ-03 has 1 HEADACHE event under Drug A
        assert events_row["stat"][0] == 1.0

    def test_summary_with_pools_and_column_order(
        self, adae: pl.DataFrame, adsl: pl.DataFrame
    ) -> None:
        spec = AESummarySpec(
            pools=[
                GroupPool(label="All Active", arms=["Drug A", "Drug B"]),
                GroupPool(label="Total", arms="*"),
            ],
            column_order=["Placebo", "Drug A", "Drug B", "All Active", "Total"],
        )
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl, spec=spec)
        levels = ard["group1_level"].unique().to_list()
        assert "All Active" in levels
        assert "Total" in levels


# ================================================================== #
# AE Listing                                                           #
# ================================================================== #


class TestAEListing:
    """AE listing returns correct rows, columns, sort order."""

    def test_default_listing(self, adae: pl.DataFrame) -> None:
        listing = adae.tlg.ae.l_listing()
        # Default columns: USUBJID, TRTA, AEBODSYS, AEDECOD, AESEV, AESER
        assert "Subject" in listing.columns  # renamed from USUBJID
        assert "Treatment" in listing.columns
        assert len(listing) == len(adae)

    def test_custom_listing_columns(self, adae: pl.DataFrame) -> None:
        spec = AEListingSpec(
            columns=[
                Column(field="USUBJID", label="Subject ID"),
                Column(field="AEDECOD", label="PT"),
            ],
            sort_by=["USUBJID"],
            required_columns=["USUBJID", "AEDECOD"],
        )
        listing = adae.tlg.ae.l_listing(spec=spec)
        assert list(listing.columns) == ["Subject ID", "PT"]

    def test_listing_sort_order(self, adae: pl.DataFrame) -> None:
        spec = AEListingSpec(
            columns=[
                Column(field="USUBJID", label="Subject"),
                Column(field="AEDECOD", label="PT"),
            ],
            sort_by=["USUBJID", "AEDECOD"],
            required_columns=["USUBJID", "AEDECOD"],
        )
        listing = adae.tlg.ae.l_listing(spec=spec)
        subjects = listing["Subject"].to_list()
        assert subjects == sorted(subjects)

    def test_listing_with_filter(self, adae: pl.DataFrame) -> None:
        spec = AEListingSpec(
            dataset_filter=pl.col("AESER") == "Y",
        )
        listing = adae.tlg.ae.l_listing(spec=spec)
        assert len(listing) == 1  # Only SUBJ-03's serious AE


# ================================================================== #
# Pre-validation (.check())                                            #
# ================================================================== #


class TestCheck:
    """Pre-validation diagnostics without computing."""

    def test_check_returns_warnings_for_missing_cols(self) -> None:
        df = pl.DataFrame({"USUBJID": ["A"], "TRTA": ["Placebo"]})
        report = df.tlg.ae.check()
        assert any("AEDECOD" in msg for msg in report)
        assert any("AEBODSYS" in msg for msg in report)

    def test_check_returns_empty_for_good_data(self, adae: pl.DataFrame) -> None:
        report = adae.tlg.ae.check()
        assert report == []

    def test_check_with_custom_spec(self, adae: pl.DataFrame) -> None:
        spec = AESummarySpec(
            rows=[
                Row(field="AEBODSYS", label="SOC"),
                Row(field="NONEXISTENT_COL", label="Missing"),
            ],
        )
        report = adae.tlg.ae.check(spec=spec)
        assert any("NONEXISTENT_COL" in msg for msg in report)


# ================================================================== #
# Spec YAML Round-Trip                                                 #
# ================================================================== #


class TestSpecYAMLRoundTrip:
    """to_yaml() → from_yaml() produces identical spec."""

    def test_ae_summary_spec_roundtrip(self) -> None:
        spec = AESummarySpec(
            rows=[
                Row(field="AEBODSYS", label="SOC"),
                Row(field="AEDECOD", label="PT"),
            ],
            statistics=[Statistic.N_SUBJECTS, Statistic.N_PCT],
            pools=[GroupPool(label="Total", arms="*")],
            column_order=["Placebo", "Drug A", "Total"],
        )
        yaml_str = spec.to_yaml()
        restored = AESummarySpec.from_yaml(yaml_str)
        assert restored.rows == spec.rows
        assert restored.statistics == spec.statistics
        assert restored.pools == spec.pools
        assert restored.column_order == spec.column_order

    def test_ae_listing_spec_roundtrip(self) -> None:
        spec = AEListingSpec(
            columns=[
                Column(field="USUBJID", label="Subject"),
                Column(field="AEDECOD", label="PT"),
            ],
            sort_by=["USUBJID"],
        )
        yaml_str = spec.to_yaml()
        restored = AEListingSpec.from_yaml(yaml_str)
        assert restored.columns == spec.columns
        assert restored.sort_by == spec.sort_by

    def test_vs_summary_spec_roundtrip(self) -> None:
        spec = VSSummarySpec()
        yaml_str = spec.to_yaml()
        restored = VSSummarySpec.from_yaml(yaml_str)
        assert restored.required_columns == spec.required_columns

    def test_base_spec_roundtrip(self) -> None:
        spec = TLGSpec(
            required_columns=["A", "B"],
            required_flags={"FLAG": ["Y"]},
        )
        yaml_str = spec.to_yaml()
        restored = TLGSpec.from_yaml(yaml_str)
        assert restored.required_columns == spec.required_columns
        assert restored.required_flags == spec.required_flags


# ================================================================== #
# {cards} Formatting Functions                                         #
# ================================================================== #


class TestFormatting:
    """{cards}-compatible formatting: default_fmt_fn, apply_fmt_fn, format_ard."""

    def test_default_fmt_fn_integer_stats(self) -> None:
        assert default_fmt_fn("N") == "xx"
        assert default_fmt_fn("n") == "xx"
        assert default_fmt_fn("n_events") == "xx"

    def test_default_fmt_fn_pct(self) -> None:
        assert default_fmt_fn("pct") == "xx.x"

    def test_default_fmt_fn_continuous(self) -> None:
        assert default_fmt_fn("mean") == "xx.x"
        assert default_fmt_fn("sd") == "xx.xx"
        assert default_fmt_fn("median") == "xx.x"

    def test_default_fmt_fn_unknown_stat(self) -> None:
        assert default_fmt_fn("custom_stat") == "xx.x"

    def test_apply_fmt_fn_integer(self) -> None:
        assert apply_fmt_fn(86.0, "xx") == "86"

    def test_apply_fmt_fn_one_decimal(self) -> None:
        assert apply_fmt_fn(75.23, "xx.x") == "75.2"

    def test_apply_fmt_fn_two_decimals(self) -> None:
        assert apply_fmt_fn(8.5, "xx.xx") == "8.50"

    def test_apply_fmt_fn_pct_suffix(self) -> None:
        assert apply_fmt_fn(75.2, "xx.x%") == "75.2%"

    def test_apply_fmt_fn_none(self) -> None:
        assert apply_fmt_fn(None, "xx.x") == ""

    def test_apply_fmt_fn_nan(self) -> None:
        assert apply_fmt_fn(float("nan"), "xx.x") == ""

    def test_format_ard_populates_stat_fmt(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)
        # stat_fmt should already be populated by t_summary
        assert "stat_fmt" in ard.columns
        # Big-N rows (fmt_fn="xx") should produce integer-formatted strings
        big_n = ard.filter(pl.col("stat_name") == "N")
        for val, fmt_str in zip(big_n["stat"].to_list(), big_n["stat_fmt"].to_list()):
            if val is not None:
                assert "." not in fmt_str  # Integer format, no decimal

    def test_stat_fmt_matches_fmt_fn(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)
        pct_rows = ard.filter(pl.col("stat_name") == "pct")
        for val, fmt_fn_val, fmt_str in zip(
            pct_rows["stat"].to_list(),
            pct_rows["fmt_fn"].to_list(),
            pct_rows["stat_fmt"].to_list(),
        ):
            if val is not None:
                assert fmt_fn_val == "xx.x"
                # Should have exactly one decimal place
                assert "." in fmt_str


# ================================================================== #
# Filter rename: adsl_filter + dataset_filter                          #
# ================================================================== #


class TestFilterRename:
    """adsl_filter and dataset_filter replace the old filter field."""

    def test_adsl_filter_affects_big_n(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        spec = AESummarySpec(adsl_filter=pl.col("SAFFL") == "Y")
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl, spec=spec)
        big_n = ard.filter(pl.col("stat_name") == "N")
        big_n_map = dict(zip(big_n["group1_level"].to_list(), big_n["stat"].to_list()))
        # SUBJ-06 has SAFFL=N in Drug B, so Drug B big-N = 1
        assert big_n_map["Drug B"] == 1.0

    def test_dataset_filter_subsets_data(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        spec = AESummarySpec(dataset_filter=pl.col("AESER") == "Y")
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl, spec=spec)
        # Only serious AEs should appear (SUBJ-03, Drug A, NAUSEA)
        non_big_n = ard.filter(pl.col("stat_name") != "N")
        levels = non_big_n["variable_level"].unique().to_list()
        # Only GASTRO/NAUSEA should appear (the one serious AE)
        assert "HEADACHE" not in levels

    def test_both_filters_independent(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        spec = AESummarySpec(
            adsl_filter=pl.col("SAFFL") == "Y",
            dataset_filter=pl.col("AESER") == "Y",
        )
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl, spec=spec)
        big_n = ard.filter(pl.col("stat_name") == "N")
        big_n_map = dict(zip(big_n["group1_level"].to_list(), big_n["stat"].to_list()))
        # adsl_filter shrinks Drug A big-N but only arms with data appear
        # Only Drug A has serious AEs in our fixture data
        assert big_n_map["Drug A"] == 2.0
        # dataset_filter limits to serious AEs only
        non_big_n = ard.filter(pl.col("stat_name") != "N")
        assert "HEADACHE" not in non_big_n["variable_level"].unique().to_list()


# ================================================================== #
# Builder API                                                          #
# ================================================================== #


class TestBuilderAPI:
    """TLGBuilder fluent API produces correct ARDs."""

    def test_builder_basic_ae(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        ard = (
            adae.tlg.ae.population(adsl)
            .by("TRTA")
            .rows(["AEBODSYS", "AEDECOD"])
            .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
            .to_ard()
        )
        assert len(ard) > 0
        assert set(ard.columns) == TestARDStructure.EXPECTED_COLUMNS

    def test_builder_matches_spec(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        """Builder and spec paths produce identical ARD for the same inputs."""
        spec = AESummarySpec(
            statistics=[Statistic.N_SUBJECTS, Statistic.N_PCT],
        )
        ard_spec = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl, spec=spec)
        ard_builder = (
            adae.tlg.ae.population(adsl)
            .by("TRTA")
            .rows(["AEBODSYS", "AEDECOD"])
            .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
            .to_ard()
        )
        assert ard_spec.shape == ard_builder.shape
        # Same stat values for Big-N
        big_n_spec = dict(
            zip(
                ard_spec.filter(pl.col("stat_name") == "N")["group1_level"].to_list(),
                ard_spec.filter(pl.col("stat_name") == "N")["stat"].to_list(),
            )
        )
        big_n_builder = dict(
            zip(
                ard_builder.filter(pl.col("stat_name") == "N")["group1_level"].to_list(),
                ard_builder.filter(pl.col("stat_name") == "N")["stat"].to_list(),
            )
        )
        assert big_n_spec == big_n_builder

    def test_builder_with_pools(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        ard = (
            adae.tlg.ae.population(adsl)
            .by("TRTA")
            .rows(["AEBODSYS", "AEDECOD"])
            .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
            .pools([GroupPool(label="Total", arms="*")])
            .to_ard()
        )
        assert "Total" in ard["group1_level"].to_list()

    def test_builder_with_filter(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        ard = (
            adae.tlg.ae.population(adsl, adsl_filter=pl.col("SAFFL") == "Y")
            .filter(pl.col("AESER") == "Y")
            .by("TRTA")
            .rows(["AEBODSYS", "AEDECOD"])
            .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
            .to_ard()
        )
        non_big_n = ard.filter(pl.col("stat_name") != "N")
        assert "HEADACHE" not in non_big_n["variable_level"].unique().to_list()

    def test_builder_to_spec_roundtrip(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        builder = (
            adae.tlg.ae.population(adsl)
            .by("TRTA")
            .rows(["AEBODSYS", "AEDECOD"])
            .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
            .pools([GroupPool(label="Total", arms="*")])
            .column_order(["Placebo", "Drug A", "Drug B", "Total"])
        )
        spec = builder.to_spec()
        assert isinstance(spec, AESummarySpec)
        assert len(spec.rows) == 2
        assert spec.statistics == [Statistic.N_SUBJECTS, Statistic.N_PCT]
        assert len(spec.pools) == 1
        assert spec.column_order == ["Placebo", "Drug A", "Drug B", "Total"]


# ================================================================== #
# VS Namespace                                                         #
# ================================================================== #


@pytest.fixture()
def advs() -> pl.DataFrame:
    """Minimal ADVS-like DataFrame for VS summary tests."""
    return pl.DataFrame(
        {
            "USUBJID": [
                "SUBJ-01",
                "SUBJ-01",
                "SUBJ-02",
                "SUBJ-02",
                "SUBJ-03",
                "SUBJ-03",
                "SUBJ-04",
                "SUBJ-04",
            ],
            "TRTA": [
                "Placebo",
                "Placebo",
                "Placebo",
                "Placebo",
                "Drug A",
                "Drug A",
                "Drug A",
                "Drug A",
            ],
            "PARAMCD": [
                "SYSBP",
                "DIABP",
                "SYSBP",
                "DIABP",
                "SYSBP",
                "DIABP",
                "SYSBP",
                "DIABP",
            ],
            "AVAL": [
                120.0,
                80.0,
                130.0,
                85.0,
                115.0,
                75.0,
                125.0,
                78.0,
            ],
        }
    )


class TestVSNamespace:
    """VS summary namespace produces correct ARDs."""

    def test_vs_basic_summary(self, advs: pl.DataFrame, adsl: pl.DataFrame) -> None:
        ard = advs.tlg.vs.t_summary(groupby="TRTA", adsl=adsl)
        assert len(ard) > 0
        assert (ard["context"] == "t_vs_summary").all()

    def test_vs_builder(self, advs: pl.DataFrame, adsl: pl.DataFrame) -> None:
        ard = (
            advs.tlg.vs.population(adsl)
            .by("TRTA")
            .rows(["PARAMCD"])
            .stats([Statistic.MEAN, Statistic.SD])
            .to_ard()
        )
        assert len(ard) > 0
        stat_names = ard.filter(pl.col("stat_name") != "N")["stat_name"].unique().to_list()
        assert "mean" in stat_names
        assert "sd" in stat_names

    def test_vs_with_dataset_filter(self, advs: pl.DataFrame, adsl: pl.DataFrame) -> None:
        spec = VSSummarySpec(dataset_filter=pl.col("PARAMCD") == "SYSBP")
        ard = advs.tlg.vs.t_summary(groupby="TRTA", adsl=adsl, spec=spec)
        non_big_n = ard.filter(pl.col("stat_name") != "N")
        levels = non_big_n["variable_level"].unique().to_list()
        assert "SYSBP" in levels
        assert "DIABP" not in levels


# ================================================================== #
# OverallStat header rows                                              #
# ================================================================== #


class TestOverallStatHeaderRows:
    """OverallStat header rows appear before hierarchy rows."""

    def test_header_rows_before_hierarchy(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        spec = AESummarySpec(
            header_rows=[
                OverallStat(label="Subjects with any AE"),
            ],
        )
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl, spec=spec)
        # Header rows have variable=""
        header = ard.filter((pl.col("variable") == "") & (pl.col("stat_name") != "N"))
        assert len(header) > 0
        assert "Subjects with any AE" in header["variable_level"].to_list()

    def test_header_row_with_filter(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        spec = AESummarySpec(
            header_rows=[
                OverallStat(label="Serious AEs", filter=pl.col("AESER") == "Y"),
            ],
        )
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl, spec=spec)
        hdr = ard.filter((pl.col("variable") == "") & (pl.col("variable_level") == "Serious AEs"))
        # Drug A arm: SUBJ-03 has 1 serious AE
        drug_a_n = hdr.filter((pl.col("group1_level") == "Drug A") & (pl.col("stat_name") == "n"))
        assert drug_a_n["stat"][0] == 1.0

    def test_header_row_no_filter_counts_all(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        spec = AESummarySpec(
            header_rows=[OverallStat(label="Any AE")],
        )
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl, spec=spec)
        hdr = ard.filter(
            (pl.col("variable") == "")
            & (pl.col("variable_level") == "Any AE")
            & (pl.col("stat_name") == "n")
        )
        # Placebo has 2 unique subjects with AEs (SUBJ-01, SUBJ-02)
        placebo = hdr.filter(pl.col("group1_level") == "Placebo")
        assert placebo["stat"][0] == 2.0

    def test_header_row_stat_override(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        spec = AESummarySpec(
            header_rows=[
                OverallStat(
                    label="Deaths",
                    filter=pl.col("AESER") == "Y",
                    statistics=[Statistic.N_SUBJECTS],
                ),
            ],
        )
        ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl, spec=spec)
        hdr = ard.filter((pl.col("variable") == "") & (pl.col("variable_level") == "Deaths"))
        # Only N_SUBJECTS stat, not N_PCT (the spec default)
        assert set(hdr["stat_name"].to_list()) == {"n"}

    def test_header_rows_via_builder(self, adae: pl.DataFrame, adsl: pl.DataFrame) -> None:
        ard = (
            adae.tlg.ae.population(adsl)
            .by("TRTA")
            .header_rows(
                [
                    OverallStat(label="Any AE"),
                    OverallStat(label="Serious AEs", filter=pl.col("AESER") == "Y"),
                ]
            )
            .rows(["AEBODSYS", "AEDECOD"])
            .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
            .to_ard()
        )
        header = ard.filter((pl.col("variable") == "") & (pl.col("stat_name") != "N"))
        labels = header["variable_level"].unique().to_list()
        assert "Any AE" in labels
        assert "Serious AEs" in labels

    def test_header_rows_on_vs(self, advs: pl.DataFrame, adsl: pl.DataFrame) -> None:
        spec = VSSummarySpec(
            header_rows=[OverallStat(label="Subjects with any measurement")],
        )
        ard = advs.tlg.vs.t_summary(groupby="TRTA", adsl=adsl, spec=spec)
        hdr = ard.filter(
            (pl.col("variable") == "")
            & (pl.col("variable_level") == "Subjects with any measurement")
        )
        assert len(hdr) > 0
