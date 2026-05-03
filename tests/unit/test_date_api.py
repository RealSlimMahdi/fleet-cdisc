"""Tests for the unified .date() verb on both SDTM and ADaM namespaces."""

from __future__ import annotations

import polars as pl
import pytest

import fleet  # noqa: F401  — register namespaces

# ── Fixtures ──────────────────────────────────────────────────────────

@pytest.fixture()
def raw_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "subject": ["S01", "S02", "S03"],
            "ae_start": ["2024-01-15", "2024-03-20", "2024-06"],
            "ae_end": ["2024-02-01", "2024-04", ""],
        }
    )


@pytest.fixture()
def dtc_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "USUBJID": ["S01", "S02", "S03"],
            "AESTDTC": ["2024-01-15", "2024-03-20", "2024-06"],
            "AEENDTC": ["2024-02-01T10:30:00", "2024-04", ""],
        }
    )


# ── SDTM .date() tests ───────────────────────────────────────────────

class TestSdtmDateDtc:
    """SDTM .date() with DTC target (raw parsing)."""

    def test_basic_dtc(self, raw_df: pl.DataFrame) -> None:
        result = raw_df.sdtm.date("AESTDTC", source="ae_start").to_frame()
        assert "AESTDTC" in result.columns

    def test_dtc_with_format(self) -> None:
        df = pl.DataFrame({"raw": ["15/01/2024", "20/03/2024"]})
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
        result = raw_df.sdtm.date("MYSTARTDATE", source="ae_start", output="dt", flag=False).to_frame()
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
