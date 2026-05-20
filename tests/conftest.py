"""Shared pytest fixtures for Fleet tests."""

from pathlib import Path

import polars as pl
import pytest

# ------------------------------------------------------------------ #
# Data directories                                                     #
# ------------------------------------------------------------------ #

FIXTURES = Path(__file__).parent / "fixtures"
CT_DIR = FIXTURES / "ct"
SPECS_DIR = FIXTURES / "specs"


# ------------------------------------------------------------------ #
# Raw DataFrames (inline — no external CSV files)                      #
# ------------------------------------------------------------------ #


@pytest.fixture(scope="session")
def dm_raw() -> pl.DataFrame:
    """Raw Demographics data (5 subjects, mirrors CDISC Pilot)."""
    return pl.from_repr("""\
┌────────────────┬─────────┬─────┬─────┬───────────────────────────┬────────────────────────┬──────────┬──────────────────────┬─────────────────┬────────────────┬───────────────────────┐
│ patient_number ┆ site_id ┆ age ┆ sex ┆ race                      ┆ ethnic                 ┆ arm_code ┆ arm_description      ┆ first_dose_date ┆ last_dose_date ┆ informed_consent_date │
│ ---            ┆ ---     ┆ --- ┆ --- ┆ ---                       ┆ ---                    ┆ ---      ┆ ---                  ┆ ---             ┆ ---            ┆ ---                   │
│ str            ┆ str     ┆ i64 ┆ str ┆ str                       ┆ str                    ┆ str      ┆ str                  ┆ str             ┆ str            ┆ str                   │
╞════════════════╪═════════╪═════╪═════╪═══════════════════════════╪════════════════════════╪══════════╪══════════════════════╪═════════════════╪════════════════╪═══════════════════════╡
│ 01-701-1015    ┆ 701     ┆ 63  ┆ F   ┆ WHITE                     ┆ NOT HISPANIC OR LATINO ┆ Pbo      ┆ Placebo              ┆ 2014-01-02      ┆ 2014-07-02     ┆ 2014-01-01            │
│ 01-701-1023    ┆ 701     ┆ 64  ┆ F   ┆ WHITE                     ┆ NOT HISPANIC OR LATINO ┆ Xan_Lo   ┆ Xanomeline Low Dose  ┆ 2014-01-03      ┆ 2014-07-04     ┆ 2014-01-02            │
│ 01-701-1028    ┆ 701     ┆ 71  ┆ M   ┆ WHITE                     ┆ NOT HISPANIC OR LATINO ┆ Xan_Hi   ┆ Xanomeline High Dose ┆ 2014-01-04      ┆ 2014-07-05     ┆ 2014-01-03            │
│ 01-701-1034    ┆ 701     ┆ 74  ┆ M   ┆ BLACK OR AFRICAN AMERICAN ┆ NOT HISPANIC OR LATINO ┆ Pbo      ┆ Placebo              ┆ 2014-01-05      ┆ 2014-07-06     ┆ 2014-01-04            │
│ 01-701-1047    ┆ 701     ┆ 56  ┆ F   ┆ WHITE                     ┆ NOT HISPANIC OR LATINO ┆ Xan_Lo   ┆ Xanomeline Low Dose  ┆ 2014-01-06      ┆ 2014-07-07     ┆ 2014-01-05            │
└────────────────┴─────────┴─────┴─────┴───────────────────────────┴────────────────────────┴──────────┴──────────────────────┴─────────────────┴────────────────┴───────────────────────┘
""")


# ------------------------------------------------------------------ #
# Synthetic minimal frames                                             #
# ------------------------------------------------------------------ #


@pytest.fixture
def simple_raw() -> pl.DataFrame:
    """Minimal 3-row frame for quick unit tests."""
    return pl.from_repr("""\
┌────────────────┬─────────┬─────┬─────┬───────┬────────────────────────┬──────────┬──────────────────────┬─────────────────┬────────────────┬───────────────────────┐
│ patient_number ┆ site_id ┆ age ┆ sex ┆ race  ┆ ethnic                 ┆ arm_code ┆ arm_description      ┆ first_dose_date ┆ last_dose_date ┆ informed_consent_date │
│ ---            ┆ ---     ┆ --- ┆ --- ┆ ---   ┆ ---                    ┆ ---      ┆ ---                  ┆ ---             ┆ ---            ┆ ---                   │
│ str            ┆ str     ┆ i64 ┆ str ┆ str   ┆ str                    ┆ str      ┆ str                  ┆ str             ┆ str            ┆ str                   │
╞════════════════╪═════════╪═════╪═════╪═══════╪════════════════════════╪══════════╪══════════════════════╪═════════════════╪════════════════╪═══════════════════════╡
│ 01-701-1015    ┆ 701     ┆ 63  ┆ F   ┆ WHITE ┆ NOT HISPANIC OR LATINO ┆ Pbo      ┆ Placebo              ┆ 2014-01-02      ┆ 2014-07-02     ┆ 2014-01-01            │
│ 01-701-1023    ┆ 701     ┆ 64  ┆ F   ┆ WHITE ┆ NOT HISPANIC OR LATINO ┆ Xan_Lo   ┆ Xanomeline Low Dose  ┆ 2014-01-03      ┆ 2014-07-04     ┆ 2014-01-02            │
│ 01-701-1028    ┆ 701     ┆ 71  ┆ M   ┆ WHITE ┆ NOT HISPANIC OR LATINO ┆ Xan_Hi   ┆ Xanomeline High Dose ┆ 2014-01-04      ┆ 2014-07-05     ┆ 2014-01-03            │
└────────────────┴─────────┴─────┴─────┴───────┴────────────────────────┴──────────┴──────────────────────┴─────────────────┴────────────────┴───────────────────────┘
""")


@pytest.fixture
def simple_vs() -> pl.DataFrame:
    """Minimal VS-like frame for ADaM unit tests."""
    return pl.from_repr("""\
┌────────────────┬──────────┬──────────────────────────┬──────────┬──────────┬────────────┬────────────┐
│ patient_number ┆ vstestcd ┆ vstest                   ┆ VSSTRESN ┆ vsorresu ┆ vsdtc      ┆ TRTSDT     │
│ ---            ┆ ---      ┆ ---                      ┆ ---      ┆ ---      ┆ ---        ┆ ---        │
│ str            ┆ str      ┆ str                      ┆ f64      ┆ str      ┆ str        ┆ str        │
╞════════════════╪══════════╪══════════════════════════╪══════════╪══════════╪════════════╪════════════╡
│ 01-701-1015    ┆ SYSBP    ┆ Systolic Blood Pressure  ┆ 120.0    ┆ mmHg     ┆ 2014-01-02 ┆ 2014-01-02 │
│ 01-701-1015    ┆ DIABP    ┆ Diastolic Blood Pressure ┆ 80.0     ┆ mmHg     ┆ 2014-01-02 ┆ 2014-01-02 │
│ 01-701-1023    ┆ SYSBP    ┆ Systolic Blood Pressure  ┆ 118.0    ┆ mmHg     ┆ 2014-01-03 ┆ 2014-01-03 │
└────────────────┴──────────┴──────────────────────────┴──────────┴──────────┴────────────┴────────────┘
""")


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
    return pl.from_repr("""\
┌──────────────┬──────────────┬─────────┬───────┬────────────┐
│ STUDYID      ┆ USUBJID      ┆ PARAMCD ┆ AVALC ┆ ADT        │
│ ---          ┆ ---          ┆ ---     ┆ ---   ┆ ---        │
│ str          ┆ str          ┆ str     ┆ str   ┆ str        │
╞══════════════╪══════════════╪═════════╪═══════╪════════════╡
│ CDISCPILOT01 ┆ 01-701-1015  ┆ OVR     ┆ CR    ┆ 2020-01-01 │
│ CDISCPILOT01 ┆ 01-701-1015  ┆ OVR     ┆ PD    ┆ 2020-02-01 │
│ CDISCPILOT01 ┆ 01-701-1023  ┆ OVR     ┆ SD    ┆ 2020-01-01 │
│ CDISCPILOT01 ┆ 01-701-1023  ┆ OVR     ┆ PR    ┆ 2020-02-01 │
│ CDISCPILOT01 ┆ 01-701-1023  ┆ OVR     ┆ SD    ┆ 2020-03-01 │
│ CDISCPILOT01 ┆ 01-701-1028  ┆ OVR     ┆ PD    ┆ 2020-01-01 │
│ CDISCPILOT01 ┆ 01-701-1034  ┆ OVR     ┆ NE    ┆ 2020-01-01 │
│ CDISCPILOT01 ┆ 01-701-1039  ┆ OVR     ┆ PR    ┆ 2020-01-01 │
│ CDISCPILOT01 ┆ 01-701-1039  ┆ OVR     ┆ SD    ┆ 2020-02-01 │
│ CDISCPILOT01 ┆ 01-701-1039  ┆ OVR     ┆ PR    ┆ 2020-03-01 │
│ CDISCPILOT01 ┆ 01-701-1015  ┆ BOR     ┆ CR    ┆ 2020-01-01 │
└──────────────┴──────────────┴─────────┴───────┴────────────┘
""")


@pytest.fixture
def adis_frame() -> pl.DataFrame:
    """
    Multi-subject immunogenicity frame (ADIS-like) modelled on admiralvaccine
    test conventions — covers below-LLOQ, in-range, and above-ULOQ rows.
    """
    return pl.from_repr("""\
┌─────────────┬─────────┬─────────┬─────────┬──────────┬────────┬────────┬─────────┐
│ STUDYID     ┆ USUBJID ┆ PARAMCD ┆ AVISITN ┆ ISSTRESN ┆ ISLLOQ ┆ ISULOQ ┆ ISORRES │
│ ---         ┆ ---     ┆ ---     ┆ ---     ┆ ---      ┆ ---    ┆ ---    ┆ ---     │
│ str         ┆ str     ┆ str     ┆ i64     ┆ f64      ┆ f64    ┆ f64    ┆ str     │
╞═════════════╪═════════╪═════════╪═════════╪══════════╪════════╪════════╪═════════╡
│ VACCSTUDY01 ┆ 01-001  ┆ J0033VN ┆ 10      ┆ 1.0      ┆ 4.0    ┆ 200.0  ┆ null    │
│ VACCSTUDY01 ┆ 01-001  ┆ J0033VN ┆ 30      ┆ 50.0     ┆ 4.0    ┆ 200.0  ┆ null    │
│ VACCSTUDY01 ┆ 01-002  ┆ I0019NT ┆ 10      ┆ null     ┆ 4.0    ┆ 200.0  ┆ 3       │
│ VACCSTUDY01 ┆ 01-002  ┆ I0019NT ┆ 30      ┆ 98.2     ┆ 4.0    ┆ 200.0  ┆ null    │
│ VACCSTUDY01 ┆ 01-003  ┆ M0019LN ┆ 10      ┆ null     ┆ 8.0    ┆ 150.0  ┆ >150    │
│ VACCSTUDY01 ┆ 01-003  ┆ M0019LN ┆ 30      ┆ null     ┆ 8.0    ┆ 150.0  ┆ null    │
└─────────────┴─────────┴─────────┴─────────┴──────────┴────────┴────────┴─────────┘
""")
