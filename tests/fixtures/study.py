"""Frozen synthetic study for TLG golden and registry-driven tests.

Deliberate properties (mirroring the NEST testthat setup):

- Three arms; **Drug B has zero records in every analysis dataset**, so
  the zero-event-arm guarantee (N row + zero cells) is exercised by
  every template.
- ``TRT01P`` duplicates ``TRTA`` on every frame so each template also
  runs with a custom ``by``.
- Big-N differs from subjects-in-data everywhere (each analysis dataset
  covers a subset of ADSL).
- S01 carries multi-severity / multi-grade AEs (worst-case dedup),
  ADAE has a non-treatment-emergent record, ADCM an uncoded medication,
  ADLB a baseline-abnormal subject, ADEX interval dose records.

Never edit values casually: the golden CSVs under
``tests/fixtures/goldens/tlg/`` pin the ARDs computed from this study.
"""

from __future__ import annotations

import polars as pl


def _with_trt01p(df: pl.DataFrame) -> pl.DataFrame:
    return df.with_columns(pl.col("TRTA").alias("TRT01P"))


ADSL = _with_trt01p(
    pl.DataFrame(
        {
            "USUBJID": [f"S{i:02d}" for i in range(1, 11)],
            "TRTA": ["Placebo"] * 4 + ["Drug A"] * 4 + ["Drug B"] * 2,
            "SAFFL": ["Y", "Y", "Y", "N", "Y", "Y", "Y", "Y", "Y", "Y"],
            "AGE": [60, 70, 65, 80, 55, 75, 62, 68, 71, 59],
            "SEX": ["M", "F", "F", "M", "M", "F", "M", "F", "F", "M"],
            "AGEGR1": ["<65", ">=65", ">=65", ">=65", "<65", ">=65", "<65", ">=65", ">=65", "<65"],
            "RACE": [
                "WHITE",
                "WHITE",
                "ASIAN",
                "WHITE",
                "BLACK",
                "WHITE",
                "ASIAN",
                "WHITE",
                "WHITE",
                "BLACK",
            ],
            "ETHNIC": ["NOT HISPANIC"] * 10,
            "SITEID": ["701", "701", "702", "702", "701", "702", "701", "702", "701", "702"],
            "EOSSTT": [
                "COMPLETED",
                "DISCONTINUED",
                "COMPLETED",
                "COMPLETED",
                "COMPLETED",
                "DISCONTINUED",
                "COMPLETED",
                "COMPLETED",
                "COMPLETED",
                "COMPLETED",
            ],
            "DCSREAS": [
                None,
                "ADVERSE EVENT",
                None,
                None,
                None,
                "WITHDRAWAL BY SUBJECT",
                None,
                None,
                None,
                None,
            ],
            "DTHFL": ["N", "Y", "N", "N", "N", "Y", "N", "N", "N", "N"],
            "DTHCAT": [None, "ADVERSE EVENT", None, None, None, None, None, None, None, None],
        }
    )
)

ADAE = _with_trt01p(
    pl.DataFrame(
        {
            "USUBJID": ["S01", "S01", "S02", "S05", "S05", "S06"],
            "TRTA": ["Placebo", "Placebo", "Placebo", "Drug A", "Drug A", "Drug A"],
            "AEBODSYS": ["NERVOUS", "NERVOUS", "GASTRO", "NERVOUS", "GASTRO", "NERVOUS"],
            "AEDECOD": ["HEADACHE", "MIGRAINE", "NAUSEA", "HEADACHE", "NAUSEA", "DIZZINESS"],
            "AESEV": ["MILD", "SEVERE", "MODERATE", "MODERATE", "MILD", "MILD"],
            "AETOXGR": ["1", "3", "2", "2", "1", "1"],
            "AEREL": ["N", "Y", "N", "N", "Y", "N"],
            "AESER": ["N", "Y", "N", "N", "N", "N"],
            "TRTEMFL": ["Y", "Y", "Y", "Y", "Y", "N"],
        }
    )
)

ADCM = _with_trt01p(
    pl.DataFrame(
        {
            "USUBJID": ["S01", "S02", "S05"],
            "TRTA": ["Placebo", "Placebo", "Drug A"],
            "CMCLAS": ["NSAID", None, "NSAID"],
            "CMDECOD": ["ASPIRIN", None, "IBUPROFEN"],
        }
    )
)

ADMH = _with_trt01p(
    pl.DataFrame(
        {
            "USUBJID": ["S01", "S06"],
            "TRTA": ["Placebo", "Drug A"],
            "MHBODSYS": ["CARDIAC", "CARDIAC"],
            "MHDECOD": ["ANGINA", "ANGINA"],
        }
    )
)

ADLB = _with_trt01p(
    pl.DataFrame(
        {
            "USUBJID": ["S01", "S01", "S02", "S02", "S05", "S05"],
            "TRTA": ["Placebo", "Placebo", "Placebo", "Placebo", "Drug A", "Drug A"],
            "PARAMCD": ["ALT"] * 6,
            "AVISIT": ["BASELINE", "WEEK 1"] * 3,
            "ABLFL": ["Y", None, "Y", None, "Y", None],
            "AVAL": [10.0, 16.0, 40.0, 44.0, 20.0, 18.0],
            "CHG": [None, 6.0, None, 4.0, None, -2.0],
            "BNRIND": ["NORMAL", "NORMAL", "HIGH", "HIGH", "NORMAL", "NORMAL"],
            "ANRIND": ["NORMAL", "HIGH", "HIGH", "HIGH", "NORMAL", "NORMAL"],
        }
    )
)

ADEG = _with_trt01p(
    pl.DataFrame(
        {
            "USUBJID": ["S01", "S01", "S05", "S05"],
            "TRTA": ["Placebo", "Placebo", "Drug A", "Drug A"],
            "PARAMCD": ["QTCF"] * 4,
            "AVISIT": ["BASELINE", "WEEK 1", "BASELINE", "WEEK 1"],
            "ABLFL": ["Y", None, "Y", None],
            "AVAL": [400.0, 432.0, 410.0, 415.0],
            "CHG": [None, 32.0, None, 5.0],
            "AVALCAT1": ["<=450 msec", "<=450 msec", "<=450 msec", "<=450 msec"],
        }
    )
)

ADEX = _with_trt01p(
    pl.DataFrame(
        {
            "USUBJID": ["S01", "S01", "S05"],
            "TRTA": ["Placebo", "Placebo", "Drug A"],
            "PARAMCD": ["TDOSE"] * 3,
            "PARCAT1": ["OVERALL", "WEEK", "OVERALL"],
            "AVAL": [540.0, 54.0, 810.0],
        }
    )
)

ADDV = _with_trt01p(
    pl.DataFrame(
        {
            "USUBJID": ["S01", "S05"],
            "TRTA": ["Placebo", "Drug A"],
            "DVDECOD": ["VISIT OUT OF WINDOW", "EXCLUDED CONCOMITANT MEDICATION"],
        }
    )
)

#: Analysis dataset per ADaM name — the registry's ``domains`` metadata
#: resolves each template's primary frame from here.
FRAMES: dict[str, pl.DataFrame] = {
    "ADSL": ADSL,
    "ADAE": ADAE,
    "ADCM": ADCM,
    "ADMH": ADMH,
    "ADLB": ADLB,
    "ADEG": ADEG,
    "ADEX": ADEX,
    "ADDV": ADDV,
    "ADVS": ADLB.rename({}),  # VS shares the findings shape; reuse ADLB values
}
