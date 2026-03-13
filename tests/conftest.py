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
