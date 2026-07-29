"""Tests for the unified .date() verb on both SDTM and ADaM namespaces."""

from __future__ import annotations

import polars as pl
import pytest

import fleet  # noqa: F401  — register namespaces

# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture()
def raw_df() -> pl.DataFrame:
    return pl.from_repr("""\
┌─────────┬────────────┬────────────┐
│ subject ┆ ae_start   ┆ ae_end     │
│ ---     ┆ ---        ┆ ---        │
│ str     ┆ str        ┆ str        │
╞═════════╪════════════╪════════════╡
│ S01     ┆ 2024-01-15 ┆ 2024-02-01 │
│ S02     ┆ 2024-03-20 ┆ 2024-04    │
│ S03     ┆ 2024-06    ┆            │
└─────────┴────────────┴────────────┘
""")


@pytest.fixture()
def dtc_df() -> pl.DataFrame:
    return pl.from_repr("""\
┌─────────┬────────────┬─────────────────────┐
│ USUBJID ┆ AESTDTC    ┆ AEENDTC             │
│ ---     ┆ ---        ┆ ---                 │
│ str     ┆ str        ┆ str                 │
╞═════════╪════════════╪═════════════════════╡
│ S01     ┆ 2024-01-15 ┆ 2024-02-01T10:30:00 │
│ S02     ┆ 2024-03-20 ┆ 2024-04             │
│ S03     ┆ 2024-06    ┆                     │
└─────────┴────────────┴─────────────────────┘
""")


# ── SDTM .date() tests ───────────────────────────────────────────────


class TestSdtmDateDtc:
    """SDTM .date() with DTC target (raw parsing)."""

    def test_basic_dtc(self, raw_df: pl.DataFrame) -> None:
        result = raw_df.sdtm.date("AESTDTC", source="ae_start").to_frame()
        assert "AESTDTC" in result.columns

    def test_dtc_with_format(self) -> None:
        df = pl.from_repr("""\
┌────────────┐
│ raw        │
│ ---        │
│ str        │
╞════════════╡
│ 15/01/2024 │
│ 20/03/2024 │
└────────────┘
""")
        result = df.sdtm.date("AESTDTC", source="raw", format="%d/%m/%Y").to_frame()
        assert "AESTDTC" in result.columns

    def test_source_value_mutual_exclusion(self, raw_df: pl.DataFrame) -> None:
        with pytest.raises(ValueError, match="Cannot specify both"):
            raw_df.sdtm.date("AESTDTC", source="ae_start", value="2024-01-01")

    def test_must_specify_source_or_value(self, raw_df: pl.DataFrame) -> None:
        with pytest.raises(ValueError, match="Must specify either"):
            raw_df.sdtm.date("AESTDTC")


class TestSdtmDateDt:
    """SDTM .date() with DT target (imputation)."""

    def test_dt_output(self, raw_df: pl.DataFrame) -> None:
        result = raw_df.sdtm.date("AESTDT", source="ae_start").to_frame()
        assert "AESTDT" in result.columns

    def test_dt_explicit_output(self, raw_df: pl.DataFrame) -> None:
        result = raw_df.sdtm.date(
            "MYSTARTDATE", source="ae_start", output="dt", flag=False
        ).to_frame()
        assert "MYSTARTDATE" in result.columns


class TestSdtmDateValue:
    """SDTM .date() with value= broadcast."""

    def test_value_broadcast(self, raw_df: pl.DataFrame) -> None:
        result = raw_df.sdtm.date("AESTDTC", value="2024-01-01").to_frame()
        assert "AESTDTC" in result.columns
        assert result["AESTDTC"].to_list() == ["2024-01-01"] * 3


# ── ADaM .date() tests ───────────────────────────────────────────────


class TestAdamDateDt:
    """ADaM .date() with DT target."""

    def test_basic_dt(self, dtc_df: pl.DataFrame) -> None:
        result = dtc_df.adam.date("ADT", source="AESTDTC").to_frame()
        assert "ADT" in result.columns
        assert result["ADT"].dtype == pl.Date

    def test_dt_with_flag(self, dtc_df: pl.DataFrame) -> None:
        result = dtc_df.adam.date("ADT", source="AESTDTC", flag=True).to_frame()
        assert "ADT" in result.columns

    def test_dt_flag_disabled(self, dtc_df: pl.DataFrame) -> None:
        result = dtc_df.adam.date("ADT", source="AESTDTC", flag=False).to_frame()
        assert "ADT" in result.columns


class TestAdamDateDtm:
    """ADaM .date() with DTM target."""

    def test_basic_dtm(self, dtc_df: pl.DataFrame) -> None:
        result = dtc_df.adam.date("ADTM", source="AESTDTC").to_frame()
        assert "ADTM" in result.columns

    def test_dtm_time_invalid_for_dt(self, dtc_df: pl.DataFrame) -> None:
        with pytest.raises(ValueError, match="time= parameter is only valid"):
            dtc_df.adam.date("ADT", source="AESTDTC", time="00:00:00")


class TestAdamDateValue:
    """ADaM .date() with value= broadcast."""

    def test_value_broadcast_dt(self, dtc_df: pl.DataFrame) -> None:
        result = dtc_df.adam.date("ADT", value="2024-01-01").to_frame()
        assert "ADT" in result.columns


# ── SDTM .date() DTM + time= parameter tests ─────────────────────────
#
# Simulates raw EX domain collection where date and time are captured in
# separate eCRF fields — the typical source of the bug.


class TestSdtmDateDtmTime:
    """SDTM .date() — DTM and DTC targets with the time= parameter.

    Covers the original bug: time= was silently ignored for DTM output.
    """

    @pytest.fixture()
    def raw_ex(self) -> pl.DataFrame:
        """Raw EX-like data with separate date/time columns (complete)."""
        return pl.from_repr("""\
┌────────────┬───────────────┬───────────────┬─────────────┬─────────────┐
│ subject_id ┆ ex_start_date ┆ ex_start_time ┆ ex_end_date ┆ ex_end_time │
│ ---        ┆ ---           ┆ ---           ┆ ---         ┆ ---         │
│ str        ┆ str           ┆ str           ┆ str         ┆ str         │
╞════════════╪═══════════════╪═══════════════╪═════════════╪═════════════╡
│ 101-001    ┆ 2024-02-15    ┆ 08:59         ┆ 2024-02-15  ┆ 09:30       │
│ 101-002    ┆ 2024-03-01    ┆ 14:30         ┆ 2024-03-01  ┆ 15:00       │
│ 101-003    ┆ 2024-04-10    ┆ 09:07         ┆ 2024-04-10  ┆ 09:45       │
│ 101-004    ┆ 2024-05-22    ┆ 11:40         ┆ 2024-05-22  ┆ 12:10       │
└────────────┴───────────────┴───────────────┴─────────────┴─────────────┘
""")

    @pytest.fixture()
    def raw_ex_partial_time(self) -> pl.DataFrame:
        """Raw EX data with missing time for some records."""
        return pl.from_repr("""\
┌────────────┬───────────────┬───────────────┐
│ subject_id ┆ ex_start_date ┆ ex_start_time │
│ ---        ┆ ---           ┆ ---           │
│ str        ┆ str           ┆ str           │
╞════════════╪═══════════════╪═══════════════╡
│ 101-001    ┆ 2024-02-15    ┆ 08:59         │
│ 101-002    ┆ 2024-03-01    ┆ null          │
│ 101-003    ┆ 2024-04-10    ┆ 09:07         │
│ 101-004    ┆ 2024-05-22    ┆ null          │
└────────────┴───────────────┴───────────────┘
""")

    @pytest.fixture()
    def raw_ex_no_time_col(self) -> pl.DataFrame:
        """Raw EX data without a time column at all."""
        return pl.from_repr("""\
┌────────────┬───────────────┐
│ subject_id ┆ ex_start_date │
│ ---        ┆ ---           │
│ str        ┆ str           │
╞════════════╪═══════════════╡
│ 101-001    ┆ 2024-02-15    │
│ 101-002    ┆ 2024-03-01    │
└────────────┴───────────────┘
""")

    # ── DTM with time= column (the original bug scenario) ────────────

    def test_dtm_time_column_combines_date_and_time(self, raw_ex: pl.DataFrame) -> None:
        """Core bug fix: time= column values appear in the DTM result."""
        from datetime import datetime

        result = raw_ex.sdtm.date(
            "EXSTDTM", source="ex_start_date", time="ex_start_time", output="dtm"
        ).to_frame()
        assert result["EXSTDTM"].dtype == pl.Datetime
        assert result["EXSTDTM"].to_list() == [
            datetime(2024, 2, 15, 8, 59),
            datetime(2024, 3, 1, 14, 30),
            datetime(2024, 4, 10, 9, 7),
            datetime(2024, 5, 22, 11, 40),
        ]

    def test_dtm_time_column_end_date(self, raw_ex: pl.DataFrame) -> None:
        """End-date DTM works identically to start-date."""
        from datetime import datetime

        result = raw_ex.sdtm.date(
            "EXENDTM", source="ex_end_date", time="ex_end_time", output="dtm"
        ).to_frame()
        assert result["EXENDTM"].to_list() == [
            datetime(2024, 2, 15, 9, 30),
            datetime(2024, 3, 1, 15, 0),
            datetime(2024, 4, 10, 9, 45),
            datetime(2024, 5, 22, 12, 10),
        ]

    # ── DTM with time= literal (e.g. protocol-fixed infusion start) ──

    def test_dtm_time_literal_hhmm(self, raw_ex: pl.DataFrame) -> None:
        """Literal time '08:59' broadcasts to all rows."""
        from datetime import datetime

        result = raw_ex.sdtm.date(
            "EXSTDTM", source="ex_start_date", time="08:59", output="dtm"
        ).to_frame()
        assert result["EXSTDTM"].to_list() == [
            datetime(2024, 2, 15, 8, 59),
            datetime(2024, 3, 1, 8, 59),
            datetime(2024, 4, 10, 8, 59),
            datetime(2024, 5, 22, 8, 59),
        ]

    def test_dtm_time_literal_hhmmss(self, raw_ex: pl.DataFrame) -> None:
        """Literal time '08:59:30' with seconds is preserved."""
        from datetime import datetime

        result = raw_ex.sdtm.date(
            "EXSTDTM", source="ex_start_date", time="08:59:30", output="dtm"
        ).to_frame()
        assert result["EXSTDTM"].to_list() == [
            datetime(2024, 2, 15, 8, 59, 30),
            datetime(2024, 3, 1, 8, 59, 30),
            datetime(2024, 4, 10, 8, 59, 30),
            datetime(2024, 5, 22, 8, 59, 30),
        ]

    # ── DTM without time= (no time column available) ─────────────────

    def test_dtm_no_time_param_defaults_to_imputation(self, raw_ex: pl.DataFrame) -> None:
        """Without time=, DTM uses impute_time strategy (default='first' → 00:00)."""
        from datetime import datetime

        result = raw_ex.sdtm.date("EXSTDTM", source="ex_start_date", output="dtm").to_frame()
        assert result["EXSTDTM"].to_list() == [
            datetime(2024, 2, 15, 0, 0),
            datetime(2024, 3, 1, 0, 0),
            datetime(2024, 4, 10, 0, 0),
            datetime(2024, 5, 22, 0, 0),
        ]

    def test_dtm_no_time_param_impute_last(self, raw_ex: pl.DataFrame) -> None:
        """Without time=, impute_time='last' yields 23:59:59."""
        from datetime import datetime

        result = raw_ex.sdtm.date(
            "EXENDTM", source="ex_end_date", output="dtm", impute_time="last"
        ).to_frame()
        assert result["EXENDTM"].to_list() == [
            datetime(2024, 2, 15, 23, 59, 59),
            datetime(2024, 3, 1, 23, 59, 59),
            datetime(2024, 4, 10, 23, 59, 59),
            datetime(2024, 5, 22, 23, 59, 59),
        ]

    # ── DTM with partial/null time values ─────────────────────────────

    def test_dtm_time_column_null_fallback_first(self, raw_ex_partial_time: pl.DataFrame) -> None:
        """Null time rows fall back to impute_time='first' (00:00:00)."""
        from datetime import datetime

        result = raw_ex_partial_time.sdtm.date(
            "EXSTDTM",
            source="ex_start_date",
            time="ex_start_time",
            impute_time="first",
            output="dtm",
        ).to_frame()
        assert result["EXSTDTM"].to_list() == [
            datetime(2024, 2, 15, 8, 59),
            datetime(2024, 3, 1, 0, 0),  # null time → 00:00:00
            datetime(2024, 4, 10, 9, 7),
            datetime(2024, 5, 22, 0, 0),  # null time → 00:00:00
        ]

    def test_dtm_time_column_null_fallback_last(self, raw_ex_partial_time: pl.DataFrame) -> None:
        """Null time rows fall back to impute_time='last' (23:59:59)."""
        from datetime import datetime

        result = raw_ex_partial_time.sdtm.date(
            "EXSTDTM",
            source="ex_start_date",
            time="ex_start_time",
            impute_time="last",
            output="dtm",
        ).to_frame()
        assert result["EXSTDTM"].to_list() == [
            datetime(2024, 2, 15, 8, 59),
            datetime(2024, 3, 1, 23, 59, 59),  # null time → 23:59:59
            datetime(2024, 4, 10, 9, 7),
            datetime(2024, 5, 22, 23, 59, 59),  # null time → 23:59:59
        ]

    # ── DTC with time= (existing working path — regression guard) ─────

    def test_dtc_with_time_column(self, raw_ex: pl.DataFrame) -> None:
        """DTC path: time= column correctly appends T + time to ISO string."""
        result = raw_ex.sdtm.date(
            "EXSTDTC", source="ex_start_date", time="ex_start_time"
        ).to_frame()
        assert result["EXSTDTC"].to_list() == [
            "2024-02-15T08:59",
            "2024-03-01T14:30",
            "2024-04-10T09:07",
            "2024-05-22T11:40",
        ]

    def test_dtc_with_time_literal(self, raw_ex: pl.DataFrame) -> None:
        """DTC path: literal time broadcasts across all rows."""
        result = raw_ex.sdtm.date("EXSTDTC", source="ex_start_date", time="08:59").to_frame()
        assert result["EXSTDTC"].to_list() == [
            "2024-02-15T08:59",
            "2024-03-01T08:59",
            "2024-04-10T08:59",
            "2024-05-22T08:59",
        ]

    def test_dtc_without_time(self, raw_ex: pl.DataFrame) -> None:
        """DTC path: without time= only the date portion is produced."""
        result = raw_ex.sdtm.date("EXSTDTC", source="ex_start_date").to_frame()
        assert result["EXSTDTC"].to_list() == [
            "2024-02-15",
            "2024-03-01",
            "2024-04-10",
            "2024-05-22",
        ]

    # ── Error handling ────────────────────────────────────────────────

    def test_dtm_time_column_not_found_raises(self, raw_ex_no_time_col: pl.DataFrame) -> None:
        """time= referencing a non-existent column raises ValueError."""
        with pytest.raises(ValueError, match="column not found"):
            raw_ex_no_time_col.sdtm.date(
                "EXSTDTM", source="ex_start_date", time="ex_start_time", output="dtm"
            ).to_frame()

    def test_dtm_time_invalid_for_dt_target(self, raw_ex: pl.DataFrame) -> None:
        """time= raises ValueError when target resolves to DT (not DTM)."""
        with pytest.raises(ValueError, match="time= parameter is only valid"):
            raw_ex.sdtm.date("EXSTDT", source="ex_start_date", time="ex_start_time")

    # ── Flags ─────────────────────────────────────────────────────────

    def test_dtm_time_column_tmf_is_null(self, raw_ex: pl.DataFrame) -> None:
        """TMF is null when time was observed (not imputed)."""
        result = raw_ex.sdtm.date(
            "EXSTDTM",
            source="ex_start_date",
            time="ex_start_time",
            output="dtm",
            flag=True,
        ).to_frame()
        assert "EXSTTMF" in result.columns
        assert result["EXSTTMF"].null_count() == len(result)

    def test_dtm_time_column_dtf_still_derived(self, raw_ex: pl.DataFrame) -> None:
        """DTF is still derived from date source precision."""
        result = raw_ex.sdtm.date(
            "EXSTDTM",
            source="ex_start_date",
            time="ex_start_time",
            output="dtm",
            flag=True,
        ).to_frame()
        assert "EXSTDTF" in result.columns

    def test_dtm_no_time_flag_disabled(self, raw_ex: pl.DataFrame) -> None:
        """flag=False suppresses both DTF and TMF."""
        result = raw_ex.sdtm.date(
            "EXSTDTM", source="ex_start_date", output="dtm", flag=False
        ).to_frame()
        assert "EXSTDTF" not in result.columns
        assert "EXSTTMF" not in result.columns
