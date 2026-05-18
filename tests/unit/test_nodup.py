"""Tests for the nodup verb (SharedVerbsMixin)."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration


@pytest.fixture
def df_with_dups():
    """DataFrame with known duplicates."""
    return pl.DataFrame(
        {
            "USUBJID": ["01-001", "01-001", "01-001", "01-002", "01-002", "01-003"],
            "AEDECOD": ["HEADACHE", "HEADACHE", "NAUSEA", "HEADACHE", "HEADACHE", "RASH"],
            "AESTDTC": [
                "2014-01-05",
                "2014-01-05",
                "2014-02-10",
                "2014-03-01",
                "2014-03-01",
                "2014-04-15",
            ],
            "ASEQ": [1, 2, 3, 1, 2, 1],
        }
    )


@pytest.fixture
def df_no_dups():
    """DataFrame with no duplicates."""
    return pl.DataFrame(
        {
            "USUBJID": ["01-001", "01-002", "01-003"],
            "AEDECOD": ["HEADACHE", "NAUSEA", "RASH"],
            "AESTDTC": ["2014-01-05", "2014-02-10", "2014-03-01"],
        }
    )


class TestNodupReportOnly:
    """Tests for nodup in report-only mode (keep=None)."""

    def test_no_duplicates_found(self, df_no_dups, capsys):
        result = df_no_dups.sdtm.nodup(subset=["USUBJID", "AEDECOD"]).to_frame()
        assert result.shape == df_no_dups.shape
        captured = capsys.readouterr()
        assert "No duplicates found" in captured.out

    def test_duplicates_reported_frame_unchanged(self, df_with_dups, capsys):
        result = df_with_dups.sdtm.nodup(subset=["USUBJID", "AEDECOD"]).to_frame()
        # Frame unchanged in report-only mode
        assert result.shape == df_with_dups.shape
        assert result.equals(df_with_dups)
        captured = capsys.readouterr()
        assert "duplicate rows" in captured.out
        assert "report only" in captured.out

    def test_report_shows_top_offenders(self, df_with_dups, capsys):
        df_with_dups.sdtm.nodup(subset=["USUBJID", "AEDECOD"]).to_frame()
        captured = capsys.readouterr()
        assert "Top offenders:" in captured.out
        assert "HEADACHE" in captured.out


class TestNodupDedup:
    """Tests for nodup with deduplication (keep='first'/'last')."""

    def test_keep_first(self, df_with_dups, capsys):
        result = df_with_dups.sdtm.nodup(
            subset=["USUBJID", "AEDECOD"],
            sort_by=["ASEQ"],
            keep="first",
        ).to_frame()
        # Should keep first occurrence per key group
        assert len(result) == 4  # 4 unique (USUBJID, AEDECOD) combos
        # First ASEQ per group
        row_01_headache = result.filter(
            (pl.col("USUBJID") == "01-001") & (pl.col("AEDECOD") == "HEADACHE")
        )
        assert row_01_headache["ASEQ"].to_list() == [1]

    def test_keep_last(self, df_with_dups, capsys):
        result = df_with_dups.sdtm.nodup(
            subset=["USUBJID", "AEDECOD"],
            sort_by=["ASEQ"],
            keep="last",
        ).to_frame()
        assert len(result) == 4
        row_01_headache = result.filter(
            (pl.col("USUBJID") == "01-001") & (pl.col("AEDECOD") == "HEADACHE")
        )
        assert row_01_headache["ASEQ"].to_list() == [2]

    def test_keep_last_descending(self, df_with_dups, capsys):
        result = df_with_dups.sdtm.nodup(
            subset=["USUBJID", "AEDECOD"],
            sort_by=["ASEQ"],
            keep="first",
            descending=True,
        ).to_frame()
        # Descending sort + keep first = keep the highest ASEQ
        assert len(result) == 4
        row_01_headache = result.filter(
            (pl.col("USUBJID") == "01-001") & (pl.col("AEDECOD") == "HEADACHE")
        )
        assert row_01_headache["ASEQ"].to_list() == [2]

    def test_output_message_shows_action(self, df_with_dups, capsys):
        df_with_dups.sdtm.nodup(
            subset=["USUBJID", "AEDECOD"],
            sort_by=["ASEQ"],
            keep="first",
        ).to_frame()
        captured = capsys.readouterr()
        assert "keeping 'first'" in captured.out
        assert "ASEQ" in captured.out


class TestNodupValidation:
    """Tests for argument validation."""

    def test_keep_without_sort_by_raises(self, df_with_dups):
        with pytest.raises(ValueError, match="sort_by is required"):
            df_with_dups.sdtm.nodup(subset=["USUBJID"], keep="first").to_frame()

    def test_invalid_keep_raises(self, df_with_dups):
        with pytest.raises(ValueError, match="keep must be"):
            df_with_dups.sdtm.nodup(subset=["USUBJID"], sort_by=["ASEQ"], keep="invalid").to_frame()


class TestNodupAdam:
    """Tests that nodup works on ADaM namespaces too."""

    def test_nodup_on_adam_occds(self, df_with_dups, capsys):
        result = df_with_dups.adam.occds.nodup(
            subset=["USUBJID", "AEDECOD"],
            sort_by=["ASEQ"],
            keep="last",
        ).to_frame()
        assert len(result) == 4

    def test_nodup_on_adam_adsl(self, capsys):
        adsl_df = pl.DataFrame(
            {
                "USUBJID": ["01-001", "01-001", "01-002"],
                "AGE": [45, 45, 62],
                "SEX": ["F", "F", "M"],
            }
        )
        result = adsl_df.adam.adsl.nodup(subset=["USUBJID"]).to_frame()
        # Report-only — unchanged
        assert len(result) == 3
        captured = capsys.readouterr()
        assert "2 duplicate rows" in captured.out
