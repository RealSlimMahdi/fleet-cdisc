"""Tests for the nodup verb (SharedVerbsMixin)."""

import polars as pl
import pytest

import fleet  # noqa: F401 — triggers namespace registration


@pytest.fixture
def df_with_dups():
    """DataFrame with known duplicates."""
    return pl.from_repr("""┌─────────┬──────────┬────────────┬──────┐
│ USUBJID ┆ AEDECOD  ┆ AESTDTC    ┆ ASEQ │
│ ---     ┆ ---      ┆ ---        ┆ ---  │
│ str     ┆ str      ┆ str        ┆ i64  │
╞═════════╪══════════╪════════════╪══════╡
│ 01-001  ┆ HEADACHE ┆ 2014-01-05 ┆ 1    │
│ 01-001  ┆ HEADACHE ┆ 2014-01-05 ┆ 2    │
│ 01-001  ┆ NAUSEA   ┆ 2014-02-10 ┆ 3    │
│ 01-002  ┆ HEADACHE ┆ 2014-03-01 ┆ 1    │
│ 01-002  ┆ HEADACHE ┆ 2014-03-01 ┆ 2    │
│ 01-003  ┆ RASH     ┆ 2014-04-15 ┆ 1    │
└─────────┴──────────┴────────────┴──────┘
""")


@pytest.fixture
def df_no_dups():
    """DataFrame with no duplicates."""
    return pl.from_repr("""┌─────────┬──────────┬────────────┐
│ USUBJID ┆ AEDECOD  ┆ AESTDTC    │
│ ---     ┆ ---      ┆ ---        │
│ str     ┆ str      ┆ str        │
╞═════════╪══════════╪════════════╡
│ 01-001  ┆ HEADACHE ┆ 2014-01-05 │
│ 01-002  ┆ NAUSEA   ┆ 2014-02-10 │
│ 01-003  ┆ RASH     ┆ 2014-03-01 │
└─────────┴──────────┴────────────┘
""")


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
            order_by=["ASEQ"],
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
            order_by=["ASEQ"],
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
            order_by=["ASEQ"],
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
            order_by=["ASEQ"],
            keep="first",
        ).to_frame()
        captured = capsys.readouterr()
        assert "keeping 'first'" in captured.out
        assert "ASEQ" in captured.out


class TestNodupValidation:
    """Tests for argument validation."""

    def test_keep_without_sort_by_raises(self, df_with_dups):
        with pytest.raises(ValueError, match="order_by is required"):
            df_with_dups.sdtm.nodup(subset=["USUBJID"], keep="first").to_frame()

    def test_invalid_keep_raises(self, df_with_dups):
        with pytest.raises(ValueError, match="keep must be"):
            df_with_dups.sdtm.nodup(
                subset=["USUBJID"], order_by=["ASEQ"], keep="invalid"
            ).to_frame()


class TestNodupAdam:
    """Tests that nodup works on ADaM namespaces too."""

    def test_nodup_on_adam_occds(self, df_with_dups, capsys):
        result = df_with_dups.adam.occds.nodup(
            subset=["USUBJID", "AEDECOD"],
            order_by=["ASEQ"],
            keep="last",
        ).to_frame()
        assert len(result) == 4

    def test_nodup_on_adam_adsl(self, capsys):
        adsl_df = pl.from_repr("""┌─────────┬─────┬─────┐
│ USUBJID ┆ AGE ┆ SEX │
│ ---     ┆ --- ┆ --- │
│ str     ┆ i64 ┆ str │
╞═════════╪═════╪═════╡
│ 01-001  ┆ 45  ┆ F   │
│ 01-001  ┆ 45  ┆ F   │
│ 01-002  ┆ 62  ┆ M   │
└─────────┴─────┴─────┘
""")
        result = adsl_df.adam.adsl.nodup(subset=["USUBJID"]).to_frame()
        # Report-only — unchanged
        assert len(result) == 3
        captured = capsys.readouterr()
        assert "2 duplicate rows" in captured.out


# ------------------------------------------------------------------ #
# Phase 7 hardening: realistic duplicate patterns                      #
# ------------------------------------------------------------------ #


class TestNodupRealisticDuplicates:
    """Dedup behavior under EDC-realistic duplicate patterns."""

    def test_adjacent_duplicates_same_subject_visit(self, capsys):
        """Same subject, same event, same date — classic EDC double-entry."""
        df = pl.from_repr("""┌─────────┬──────────┬────────────┬───────┐
│ USUBJID ┆ AEDECOD  ┆ AESTDTC    ┆ AESEQ │
│ ---     ┆ ---      ┆ ---        ┆ ---   │
│ str     ┆ str      ┆ str        ┆ i64   │
╞═════════╪══════════╪════════════╪═══════╡
│ 01-001  ┆ HEADACHE ┆ 2014-01-05 ┆ 1     │
│ 01-001  ┆ HEADACHE ┆ 2014-01-05 ┆ 2     │
│ 01-001  ┆ NAUSEA   ┆ 2014-02-01 ┆ 3     │
│ 01-002  ┆ RASH     ┆ 2014-03-01 ┆ 1     │
└─────────┴──────────┴────────────┴───────┘
""")
        result = df.sdtm.nodup(
            subset=["USUBJID", "AEDECOD", "AESTDTC"],
            order_by=["AESEQ"],
            keep="first",
        ).to_frame()
        # Only the HEADACHE pair is a dup on (USUBJID, AEDECOD, AESTDTC)
        assert result.height == 3
        headaches = result.filter(
            (pl.col("USUBJID") == "01-001") & (pl.col("AEDECOD") == "HEADACHE")
        )
        assert headaches.height == 1
        assert headaches["AESEQ"][0] == 1  # kept first

    def test_mixed_scheduled_unscheduled_duplicates(self, capsys):
        """Scheduled + unscheduled visit for same test — keep scheduled."""
        df = pl.from_repr("""┌─────────┬──────────┬──────────┬────────────┬──────────┐
│ USUBJID ┆ VSTESTCD ┆ VISITNUM ┆ VSDTC      ┆ VSSTRESN │
│ ---     ┆ ---      ┆ ---      ┆ ---        ┆ ---      │
│ str     ┆ str      ┆ i64      ┆ str        ┆ f64      │
╞═════════╪══════════╪══════════╪════════════╪══════════╡
│ 01-001  ┆ SYSBP    ┆ 3        ┆ 2014-02-01 ┆ 120.0    │
│ 01-001  ┆ SYSBP    ┆ 99       ┆ 2014-02-01 ┆ 125.0    │
│ 01-001  ┆ DIABP    ┆ 3        ┆ 2014-02-01 ┆ 80.0     │
└─────────┴──────────┴──────────┴────────────┴──────────┘
""")
        result = df.sdtm.nodup(
            subset=["USUBJID", "VSTESTCD", "VSDTC"],
            order_by=["VISITNUM"],
            keep="first",
        ).to_frame()
        assert result.height == 2
        sysbp = result.filter(pl.col("VSTESTCD") == "SYSBP")
        assert sysbp["VISITNUM"][0] == 3  # scheduled kept

    def test_multi_key_ties_edc_correction(self, capsys):
        """Two records identical on all dedup keys — EDC correction pattern."""
        df = pl.from_repr("""┌─────────┬──────────┬────────────┬───────┬────────────┐
│ USUBJID ┆ AEDECOD  ┆ AESTDTC    ┆ AESEQ ┆ AEENDTC    │
│ ---     ┆ ---      ┆ ---        ┆ ---   ┆ ---        │
│ str     ┆ str      ┆ str        ┆ i64   ┆ str        │
╞═════════╪══════════╪════════════╪═══════╪════════════╡
│ 01-001  ┆ HEADACHE ┆ 2014-01-05 ┆ 1     ┆ 2014-01-10 │
│ 01-001  ┆ HEADACHE ┆ 2014-01-05 ┆ 1     ┆ 2014-01-12 │
└─────────┴──────────┴────────────┴───────┴────────────┘
""")
        result = df.sdtm.nodup(
            subset=["USUBJID", "AEDECOD", "AESTDTC", "AESEQ"],
            order_by=["AESEQ"],
            keep="last",
        ).to_frame()
        # True tie on sort key — last physical row kept
        assert result.height == 1

    def test_dedup_with_null_in_subset_key(self, capsys):
        """Null values in subset columns — two nulls should be treated as equal."""
        df = pl.from_repr("""┌─────────┬─────────┬───────┐
│ USUBJID ┆ AEDECOD ┆ AESEQ │
│ ---     ┆ ---     ┆ ---   │
│ str     ┆ str     ┆ i64   │
╞═════════╪═════════╪═══════╡
│ 01-001  ┆ null    ┆ 1     │
│ 01-001  ┆ null    ┆ 2     │
│ 01-002  ┆ RASH    ┆ 1     │
└─────────┴─────────┴───────┘
""")
        result = df.sdtm.nodup(
            subset=["USUBJID", "AEDECOD"],
            order_by=["AESEQ"],
            keep="first",
        ).to_frame()
        # Two rows with null AEDECOD for 01-001 should be treated as dups
        assert result.height == 2

    def test_ae_with_duplicate_sequences(self, capsys):
        """AE data with duplicate AESEQ — inline replacement for factory."""
        df = pl.from_repr("""┌─────────────┬───────┬──────────┬──────────┬────────────┬────────────┬──────────┬───────┐
│ USUBJID     ┆ AESEQ ┆ AETERM   ┆ AESEV    ┆ AESTDTC    ┆ AEENDTC    ┆ AEREL    ┆ AESER │
│ ---         ┆ ---   ┆ ---      ┆ ---      ┆ ---        ┆ ---        ┆ ---      ┆ ---   │
│ str         ┆ i64   ┆ str      ┆ str      ┆ str        ┆ str        ┆ str      ┆ str   │
╞═════════════╪═══════╪══════════╪══════════╪════════════╪════════════╪══════════╪═══════╡
│ 01-701-1015 ┆ 1     ┆ HEADACHE ┆ MILD     ┆ 2014-01-10 ┆ 2014-01-15 ┆ PROBABLE ┆ N     │
│ 01-701-1015 ┆ 2     ┆ NAUSEA   ┆ MODERATE ┆ 2014-02-05 ┆ 2014-02-10 ┆ POSSIBLE ┆ N     │
│ 01-701-1015 ┆ 1     ┆ DIARRHEA ┆ MILD     ┆ 2014-01-10 ┆ 2014-01-15 ┆ UNLIKELY ┆ N     │
│ 01-701-1016 ┆ 1     ┆ HEADACHE ┆ MILD     ┆ 2014-01-11 ┆ 2014-01-16 ┆ PROBABLE ┆ N     │
│ 01-701-1016 ┆ 2     ┆ NAUSEA   ┆ MODERATE ┆ 2014-02-06 ┆ 2014-02-11 ┆ POSSIBLE ┆ N     │
│ 01-701-1017 ┆ 1     ┆ HEADACHE ┆ MILD     ┆ 2014-01-12 ┆ 2014-01-17 ┆ PROBABLE ┆ N     │
│ 01-701-1017 ┆ 2     ┆ NAUSEA   ┆ SEVERE   ┆ 2014-02-07 ┆ 2014-02-12 ┆ POSSIBLE ┆ N     │
└─────────────┴───────┴──────────┴──────────┴────────────┴────────────┴──────────┴───────┘
""")
        result = df.sdtm.nodup(
            subset=["USUBJID", "AESEQ"],
            order_by=["AESEQ"],
            keep="first",
        ).to_frame()
        # Should have fewer rows than input (01-701-1015 has dup AESEQ=1)
        assert result.height < df.height
