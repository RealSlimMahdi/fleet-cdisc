"""Test data factories for Fleet test suite hardening.

Provides builders that wrap realistic raw CSV fixtures with controlled
injection of missingness, duplicates, terminology drift, partial dates,
and merge mismatches. Keeps tests readable while surfacing messy clinical
reality.
"""

from __future__ import annotations

import polars as pl

# ------------------------------------------------------------------ #
# Cohort builders (return DataFrames with controlled messiness)        #
# ------------------------------------------------------------------ #


def build_dm_cohort(
    *,
    n_subjects: int = 5,
    partial_dates: bool = False,
    duplicate_keys: bool = False,
    mixed_terminology: bool = False,
    sparse_arms: bool = False,
    null_treatment_dates: bool = False,
) -> pl.DataFrame:
    """Build a DM-like cohort with controlled messiness.

    Args:
        n_subjects: Base number of subjects.
        partial_dates: Inject partial ISO 8601 dates (day or month missing).
        duplicate_keys: Include duplicate USUBJID rows.
        mixed_terminology: Mix casing/spelling variants in coded fields.
        sparse_arms: Include arms with only 1 subject.
        null_treatment_dates: Set TRTSDT/TRTEDT to null for some subjects.
    """
    subjects = [f"01-701-{1015 + i}" for i in range(n_subjects)]
    arms = ["Placebo", "Xanomeline Low Dose", "Xanomeline High Dose"]
    arm_codes = ["Pbo", "Xan_Lo", "Xan_Hi"]

    if sparse_arms:
        # Add a 4th arm with only 1 subject
        arms.append("Screen Failure")
        arm_codes.append("Scr_Fail")

    sex_values = ["F", "M", "F", "M", "F"][:n_subjects]
    race_values = ["WHITE"] * n_subjects

    if mixed_terminology:
        sex_values[0] = "f"  # lowercase drift
        sex_values[1] = " M"  # leading whitespace
        race_values[2] = "White"  # case drift
        race_values[3] = "WHITE "  # trailing whitespace

    first_dose = [f"2014-01-{2 + i:02d}" for i in range(n_subjects)]
    last_dose = [f"2014-07-{2 + i:02d}" for i in range(n_subjects)]

    if partial_dates:
        first_dose[1] = "2014-01"  # month-only
        first_dose[3] = "2014"  # year-only
        last_dose[2] = "2014-07"

    if null_treatment_dates:
        first_dose[0] = None  # type: ignore[assignment]
        last_dose[4] = None  # type: ignore[assignment]

    data = {
        "patient_number": subjects,
        "site_id": ["701"] * n_subjects,
        "age": [63, 64, 71, 55, 48][:n_subjects],
        "sex": sex_values,
        "race": race_values,
        "ethnic": ["NOT HISPANIC OR LATINO"] * n_subjects,
        "arm_code": [arm_codes[i % len(arm_codes)] for i in range(n_subjects)],
        "arm_description": [arms[i % len(arms)] for i in range(n_subjects)],
        "first_dose_date": first_dose,
        "last_dose_date": last_dose,
        "informed_consent_date": [f"2014-01-{1 + i:02d}" for i in range(n_subjects)],
    }

    df = pl.DataFrame(data)

    if duplicate_keys:
        # Duplicate first subject with slightly different data
        dup_row = df.filter(pl.col("patient_number") == subjects[0]).with_columns(
            pl.lit(65).cast(df["age"].dtype).alias("age")  # age changed in EDC correction
        )
        df = pl.concat([df, dup_row])

    return df


def build_vs_cohort(
    *,
    n_subjects: int = 3,
    partial_dates: bool = False,
    unscheduled_visits: bool = False,
    duplicate_records: bool = False,
    null_results: bool = False,
    tied_timestamps: bool = False,
) -> pl.DataFrame:
    """Build a VS-like cohort with controlled messiness.

    Args:
        n_subjects: Number of subjects.
        partial_dates: Inject partial DTC values.
        unscheduled_visits: Include unscheduled visit records.
        duplicate_records: Include duplicate measurement records.
        null_results: Include null VSSTRESN values.
        tied_timestamps: Same datetime for multiple records.
    """
    subjects = [f"01-701-{1015 + i}" for i in range(n_subjects)]
    rows: list[dict] = []

    for i, subj in enumerate(subjects):
        base_date = f"2014-01-{2 + i:02d}"
        # Baseline visit
        rows.append(
            {
                "USUBJID": subj,
                "VSTESTCD": "SYSBP",
                "VSTEST": "Systolic Blood Pressure",
                "VSSTRESN": 120.0 + i * 2,
                "VSSTRESU": "mmHg",
                "VSDTC": base_date,
                "VISITNUM": 1,
                "VISIT": "SCREENING 1",
                "EPOCH": "SCREENING",
            }
        )
        # Post-baseline
        rows.append(
            {
                "USUBJID": subj,
                "VSTESTCD": "SYSBP",
                "VSTEST": "Systolic Blood Pressure",
                "VSSTRESN": 115.0 + i * 3,
                "VSSTRESU": "mmHg",
                "VSDTC": f"2014-02-{2 + i:02d}",
                "VISITNUM": 3,
                "VISIT": "WEEK 2",
                "EPOCH": "TREATMENT",
            }
        )

    df = pl.DataFrame(rows)

    if partial_dates:
        df = df.with_columns(
            pl.when(pl.col("USUBJID") == subjects[0])
            .then(pl.lit("2014-01"))
            .otherwise(pl.col("VSDTC"))
            .alias("VSDTC")
        )

    if unscheduled_visits:
        unsched = pl.DataFrame(
            [
                {
                    "USUBJID": subjects[0],
                    "VSTESTCD": "SYSBP",
                    "VSTEST": "Systolic Blood Pressure",
                    "VSSTRESN": 130.0,
                    "VSSTRESU": "mmHg",
                    "VSDTC": "2014-01-15",
                    "VISITNUM": 99,
                    "VISIT": "UNSCHEDULED",
                    "EPOCH": "TREATMENT",
                }
            ]
        )
        df = pl.concat([df, unsched])

    if duplicate_records:
        dup = df.filter((pl.col("USUBJID") == subjects[0]) & (pl.col("VISITNUM") == 1))
        df = pl.concat([df, dup])

    if null_results:
        df = df.with_columns(
            pl.when((pl.col("USUBJID") == subjects[-1]) & (pl.col("VISITNUM") == 3))
            .then(pl.lit(None, dtype=pl.Float64))
            .otherwise(pl.col("VSSTRESN"))
            .alias("VSSTRESN")
        )

    if tied_timestamps:
        # Make two records have the same datetime for same subject
        df = df.with_columns(
            pl.when((pl.col("USUBJID") == subjects[0]) & (pl.col("VISITNUM") == 3))
            .then(pl.lit("2014-01-02"))
            .otherwise(pl.col("VSDTC"))
            .alias("VSDTC")
        )

    return df


def build_ae_cohort(
    *,
    n_subjects: int = 3,
    overlapping_events: bool = False,
    null_end_dates: bool = False,
    duplicate_sequences: bool = False,
    mixed_severity_terms: bool = False,
) -> pl.DataFrame:
    """Build an AE-like cohort with controlled messiness.

    Args:
        n_subjects: Number of subjects.
        overlapping_events: Include temporally overlapping AEs.
        null_end_dates: Include ongoing AEs with no end date.
        duplicate_sequences: Include duplicate AESEQ values.
        mixed_severity_terms: Mix casing variants in severity.
    """
    subjects = [f"01-701-{1015 + i}" for i in range(n_subjects)]
    rows: list[dict] = []

    severities = ["MILD", "MODERATE", "SEVERE"]
    if mixed_severity_terms:
        severities = ["Mild", "MODERATE", "severe"]

    for i, subj in enumerate(subjects):
        rows.append(
            {
                "USUBJID": subj,
                "AESEQ": 1,
                "AETERM": "HEADACHE",
                "AESEV": severities[i % 3],
                "AESTDTC": f"2014-01-{10 + i:02d}",
                "AEENDTC": f"2014-01-{15 + i:02d}",
                "AEREL": "PROBABLE",
                "AESER": "N",
            }
        )
        rows.append(
            {
                "USUBJID": subj,
                "AESEQ": 2,
                "AETERM": "NAUSEA",
                "AESEV": severities[(i + 1) % 3],
                "AESTDTC": f"2014-02-{5 + i:02d}",
                "AEENDTC": f"2014-02-{10 + i:02d}",
                "AEREL": "POSSIBLE",
                "AESER": "N",
            }
        )

    df = pl.DataFrame(rows)

    if overlapping_events:
        overlap = pl.DataFrame(
            [
                {
                    "USUBJID": subjects[0],
                    "AESEQ": 3,
                    "AETERM": "DIZZINESS",
                    "AESEV": "MILD",
                    "AESTDTC": "2014-01-12",  # overlaps with first AE
                    "AEENDTC": "2014-01-18",
                    "AEREL": "UNLIKELY",
                    "AESER": "N",
                }
            ]
        )
        df = pl.concat([df, overlap])

    if null_end_dates:
        df = df.with_columns(
            pl.when(pl.col("AESEQ") == 2)
            .then(pl.lit(None, dtype=pl.Utf8))
            .otherwise(pl.col("AEENDTC"))
            .alias("AEENDTC")
        )

    if duplicate_sequences:
        dup = df.filter((pl.col("USUBJID") == subjects[0]) & (pl.col("AESEQ") == 1)).with_columns(
            pl.lit("DIARRHEA").alias("AETERM")
        )
        df = pl.concat([df, dup])

    return df


def build_adsl_cohort(
    *,
    n_subjects: int = 5,
    null_treatment_dates: bool = False,
    same_day_start_end: bool = False,
) -> pl.DataFrame:
    """Build an ADSL-like cohort for ADaM tests.

    Args:
        n_subjects: Number of subjects.
        null_treatment_dates: Include subjects with missing TRTSDT/TRTEDT.
        same_day_start_end: Include subjects where TRTSDT == TRTEDT.
    """
    subjects = [f"01-701-{1015 + i}" for i in range(n_subjects)]
    trtsdt = [f"2014-01-{2 + i:02d}" for i in range(n_subjects)]
    trtedt = [f"2014-07-{2 + i:02d}" for i in range(n_subjects)]

    if null_treatment_dates:
        trtsdt[0] = None  # type: ignore[assignment]
        trtedt[n_subjects - 1] = None  # type: ignore[assignment]

    if same_day_start_end:
        trtedt[1] = trtsdt[1]

    return pl.DataFrame(
        {
            "STUDYID": ["CDISCPILOT01"] * n_subjects,
            "USUBJID": subjects,
            "SITEID": ["701"] * n_subjects,
            "AGE": [63, 64, 71, 55, 48][:n_subjects],
            "SEX": ["F", "M", "F", "M", "F"][:n_subjects],
            "RACE": ["WHITE"] * n_subjects,
            "ARM": ["Placebo", "Xan Lo", "Xan Hi", "Placebo", "Xan Lo"][:n_subjects],
            "ACTARM": ["Placebo", "Xan Lo", "Xan Hi", "Placebo", "Xan Lo"][:n_subjects],
            "TRTSDT": trtsdt,
            "TRTEDT": trtedt,
            "SAFFL": ["Y"] * n_subjects,
            "ITTFL": ["Y"] * n_subjects,
        }
    )


# ------------------------------------------------------------------ #
# Merge mismatch helpers                                               #
# ------------------------------------------------------------------ #


def build_merge_mismatch_pair() -> tuple[pl.DataFrame, pl.DataFrame]:
    """Return (left, right) with subjects that don't fully overlap.

    Useful for testing join cardinality: left has subjects not in right
    and vice-versa.
    """
    left = pl.DataFrame(
        {
            "USUBJID": ["SUBJ-01", "SUBJ-02", "SUBJ-03"],
            "AGE": [65, 72, 48],
        }
    )
    right = pl.DataFrame(
        {
            "USUBJID": ["SUBJ-02", "SUBJ-03", "SUBJ-04"],
            "TRTSDT": ["2014-01-01", "2014-01-02", "2014-01-03"],
        }
    )
    return left, right


# ------------------------------------------------------------------ #
# Reorder helper for order-invariance testing                          #
# ------------------------------------------------------------------ #


def shuffle_rows(df: pl.DataFrame, seed: int = 42) -> pl.DataFrame:
    """Return df with rows in a different deterministic order."""
    return df.sample(fraction=1.0, seed=seed, shuffle=True)
