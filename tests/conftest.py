"""Shared pytest fixtures for Fleet tests."""

from pathlib import Path

import polars as pl
import pytest

# ------------------------------------------------------------------ #
# Data directories                                                     #
# ------------------------------------------------------------------ #

FIXTURES = Path(__file__).parent / "fixtures"
RAW_DIR = FIXTURES / "raw"
CT_DIR = FIXTURES / "ct"
SPECS_DIR = FIXTURES / "specs"


# ------------------------------------------------------------------ #
# Raw DataFrames                                                       #
# ------------------------------------------------------------------ #


@pytest.fixture(scope="session")
def dm_raw() -> pl.DataFrame:
    """Raw Demographics data (dm_raw.csv)."""
    return pl.read_csv(RAW_DIR / "dm_raw.csv")


@pytest.fixture(scope="session")
def vs_raw() -> pl.DataFrame:
    """Raw Vital Signs data (vs_raw.csv)."""
    return pl.read_csv(RAW_DIR / "vs_raw.csv")


@pytest.fixture(scope="session")
def ae_raw() -> pl.DataFrame:
    """Raw Adverse Events data (ae_raw.csv)."""
    return pl.read_csv(RAW_DIR / "ae_raw.csv")


# ------------------------------------------------------------------ #
# Synthetic minimal frames                                             #
# ------------------------------------------------------------------ #


@pytest.fixture
def simple_raw() -> pl.DataFrame:
    """Minimal 3-row frame for quick unit tests."""
    return pl.DataFrame(
        {
            "patient_number": ["01-701-1015", "01-701-1023", "01-701-1028"],
            "site_id": ["701", "701", "701"],
            "age": [63, 64, 71],
            "sex": ["F", "F", "M"],
            "race": ["WHITE", "WHITE", "WHITE"],
            "ethnic": [
                "NOT HISPANIC OR LATINO",
                "NOT HISPANIC OR LATINO",
                "NOT HISPANIC OR LATINO",
            ],
            "arm_code": ["Pbo", "Xan_Lo", "Xan_Hi"],
            "arm_description": ["Placebo", "Xanomeline Low Dose", "Xanomeline High Dose"],
            "first_dose_date": ["2014-01-02", "2014-01-03", "2014-01-04"],
            "last_dose_date": ["2014-07-02", "2014-07-04", "2014-07-05"],
            "informed_consent_date": ["2014-01-01", "2014-01-02", "2014-01-03"],
        }
    )


@pytest.fixture
def simple_vs() -> pl.DataFrame:
    """Minimal VS-like frame for ADaM unit tests."""
    return pl.DataFrame(
        {
            "patient_number": ["01-701-1015", "01-701-1015", "01-701-1023"],
            "vstestcd": ["SYSBP", "DIABP", "SYSBP"],
            "vstest": [
                "Systolic Blood Pressure",
                "Diastolic Blood Pressure",
                "Systolic Blood Pressure",
            ],
            "VSSTRESN": [120.0, 80.0, 118.0],
            "vsorresu": ["mmHg", "mmHg", "mmHg"],
            "vsdtc": ["2014-01-02", "2014-01-02", "2014-01-03"],
            "TRTSDT": ["2014-01-02", "2014-01-02", "2014-01-03"],
        }
    )


# ------------------------------------------------------------------ #
# Paths                                                                #
# ------------------------------------------------------------------ #


@pytest.fixture
def ct_sample_path() -> Path:
    return CT_DIR / "cdisc_ct_sample.yaml"


@pytest.fixture
def sdtm_define_path() -> Path:
    """Unified SDTM define.yaml (drives both Define-XML and from_spec())."""
    return SPECS_DIR / "define_sdtm.yaml"


@pytest.fixture
def adam_define_path() -> Path:
    """Unified ADaM define.yaml (drives both Define-XML and from_spec())."""
    return SPECS_DIR / "define_adam.yaml"


# ------------------------------------------------------------------ #
# Therapeutic-area shared frames (admiral-style, multi-subject)        #
# ------------------------------------------------------------------ #


@pytest.fixture
def adrs_frame() -> pl.DataFrame:
    """
    Multi-subject overall response frame modelled on CDISC PILOT data.

    Subject layout mirrors admiralonco test conventions:
      01-701-1015  CR → PD                  BOR = CR
      01-701-1023  SD → PR → SD             BOR = PR
      01-701-1028  PD immediately           BOR = PD
      01-701-1034  NE only                  BOR = NE
      01-701-1039  no PD (PR, SD, PR)       all rows survive filter_pd
    """
    return pl.DataFrame(
        {
            "STUDYID": ["CDISCPILOT01"] * 11,
            "USUBJID": [
                "01-701-1015",
                "01-701-1015",
                "01-701-1023",
                "01-701-1023",
                "01-701-1023",
                "01-701-1028",
                "01-701-1034",
                "01-701-1039",
                "01-701-1039",
                "01-701-1039",
                "01-701-1015",  # BOR row (different PARAMCD)
            ],
            "PARAMCD": ["OVR"] * 10 + ["BOR"],
            "AVALC": [
                "CR",
                "PD",
                "SD",
                "PR",
                "SD",
                "PD",
                "NE",
                "PR",
                "SD",
                "PR",
                "CR",
            ],
            "ADT": [
                "2020-01-01",
                "2020-02-01",
                "2020-01-01",
                "2020-02-01",
                "2020-03-01",
                "2020-01-01",
                "2020-01-01",
                "2020-01-01",
                "2020-02-01",
                "2020-03-01",
                "2020-01-01",
            ],
        }
    )


@pytest.fixture
def adis_frame() -> pl.DataFrame:
    """
    Multi-subject immunogenicity frame (ADIS-like) modelled on admiralvaccine
    test conventions — covers below-LLOQ, in-range, and above-ULOQ rows.
    """
    return pl.DataFrame(
        {
            "STUDYID": ["VACCSTUDY01"] * 6,
            "USUBJID": [
                "01-001",
                "01-001",
                "01-002",
                "01-002",
                "01-003",
                "01-003",
            ],
            "PARAMCD": ["J0033VN", "J0033VN", "I0019NT", "I0019NT", "M0019LN", "M0019LN"],
            "AVISITN": [10, 30, 10, 30, 10, 30],
            "ISSTRESN": [1.0, 50.0, None, 98.2, None, None],
            "ISLLOQ": [4.0, 4.0, 4.0, 4.0, 8.0, 8.0],
            "ISULOQ": [200.0, 200.0, 200.0, 200.0, 150.0, 150.0],
            "ISORRES": [None, None, "3", None, ">150", None],
        }
    )


# ------------------------------------------------------------------ #
# Factory-based messy cohorts (Phase 1 hardening)                      #
# ------------------------------------------------------------------ #

from tests.factories import (  # noqa: E402
    build_adsl_cohort,
    build_ae_cohort,
    build_dm_cohort,
    build_merge_mismatch_pair,
    build_vs_cohort,
)


@pytest.fixture
def messy_dm() -> pl.DataFrame:
    """DM cohort with partial dates, duplicates, and terminology drift."""
    return build_dm_cohort(
        partial_dates=True,
        duplicate_keys=True,
        mixed_terminology=True,
    )


@pytest.fixture
def messy_vs() -> pl.DataFrame:
    """VS cohort with unscheduled visits, nulls, and tied timestamps."""
    return build_vs_cohort(
        unscheduled_visits=True,
        null_results=True,
        tied_timestamps=True,
    )


@pytest.fixture
def messy_ae() -> pl.DataFrame:
    """AE cohort with overlapping events, null end dates, and severity drift."""
    return build_ae_cohort(
        overlapping_events=True,
        null_end_dates=True,
        mixed_severity_terms=True,
    )


@pytest.fixture
def adsl_with_null_dates() -> pl.DataFrame:
    """ADSL cohort with missing treatment dates and same-day boundaries."""
    return build_adsl_cohort(
        null_treatment_dates=True,
        same_day_start_end=True,
    )


@pytest.fixture
def merge_mismatch_frames() -> tuple[pl.DataFrame, pl.DataFrame]:
    """Pair of frames with non-overlapping keys for join tests."""
    return build_merge_mismatch_pair()
