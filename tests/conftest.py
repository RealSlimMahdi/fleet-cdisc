"""Shared pytest fixtures for Pymaverse tests."""

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
    return pl.DataFrame({
        "patient_number": ["01-701-1015", "01-701-1023", "01-701-1028"],
        "site_id": ["701", "701", "701"],
        "age": [63, 64, 71],
        "sex": ["F", "F", "M"],
        "race": ["WHITE", "WHITE", "WHITE"],
        "ethnic": ["NOT HISPANIC OR LATINO", "NOT HISPANIC OR LATINO", "NOT HISPANIC OR LATINO"],
        "arm_code": ["Pbo", "Xan_Lo", "Xan_Hi"],
        "arm_description": ["Placebo", "Xanomeline Low Dose", "Xanomeline High Dose"],
        "first_dose_date": ["2014-01-02", "2014-01-03", "2014-01-04"],
        "last_dose_date": ["2014-07-02", "2014-07-04", "2014-07-05"],
        "informed_consent_date": ["2014-01-01", "2014-01-02", "2014-01-03"],
    })


@pytest.fixture
def simple_vs() -> pl.DataFrame:
    """Minimal VS-like frame for ADaM unit tests."""
    return pl.DataFrame({
        "patient_number": ["01-701-1015", "01-701-1015", "01-701-1023"],
        "vstestcd": ["SYSBP", "DIABP", "SYSBP"],
        "vstest": ["Systolic Blood Pressure", "Diastolic Blood Pressure", "Systolic Blood Pressure"],
        "VSSTRESN": [120.0, 80.0, 118.0],
        "vsorresu": ["mmHg", "mmHg", "mmHg"],
        "vsdtc": ["2014-01-02", "2014-01-02", "2014-01-03"],
        "TRTSDT": ["2014-01-02", "2014-01-02", "2014-01-03"],
    })


# ------------------------------------------------------------------ #
# Paths                                                                #
# ------------------------------------------------------------------ #

@pytest.fixture
def ct_sample_path() -> Path:
    return CT_DIR / "cdisc_ct_sample.yaml"


@pytest.fixture
def dm_spec_path() -> Path:
    return SPECS_DIR / "dm_spec.yaml"


@pytest.fixture
def advs_spec_path() -> Path:
    return SPECS_DIR / "advs_spec.yaml"


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
    return pl.DataFrame({
        "STUDYID": ["CDISCPILOT01"] * 11,
        "USUBJID": [
            "01-701-1015", "01-701-1015",
            "01-701-1023", "01-701-1023", "01-701-1023",
            "01-701-1028",
            "01-701-1034",
            "01-701-1039", "01-701-1039", "01-701-1039",
            "01-701-1015",   # BOR row (different PARAMCD)
        ],
        "PARAMCD": ["OVR"] * 10 + ["BOR"],
        "AVALC": [
            "CR", "PD",
            "SD", "PR", "SD",
            "PD",
            "NE",
            "PR", "SD", "PR",
            "CR",
        ],
        "ADT": [
            "2020-01-01", "2020-02-01",
            "2020-01-01", "2020-02-01", "2020-03-01",
            "2020-01-01",
            "2020-01-01",
            "2020-01-01", "2020-02-01", "2020-03-01",
            "2020-01-01",
        ],
    })


@pytest.fixture
def adis_frame() -> pl.DataFrame:
    """
    Multi-subject immunogenicity frame (ADIS-like) modelled on admiralvaccine
    test conventions — covers below-LLOQ, in-range, and above-ULOQ rows.
    """
    return pl.DataFrame({
        "STUDYID": ["VACCSTUDY01"] * 6,
        "USUBJID": [
            "01-001", "01-001",
            "01-002", "01-002",
            "01-003", "01-003",
        ],
        "PARAMCD": ["J0033VN", "J0033VN", "I0019NT", "I0019NT", "M0019LN", "M0019LN"],
        "AVISITN": [10, 30, 10, 30, 10, 30],
        "ISSTRESN": [1.0, 50.0, None, 98.2, None, None],
        "ISLLOQ":   [4.0,  4.0,   4.0,  4.0,  8.0,  8.0],
        "ISULOQ":   [200.0, 200.0, 200.0, 200.0, 150.0, 150.0],
        "ISORRES":  [None, None, "3", None, ">150", None],
    })
