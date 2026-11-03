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
- ADAE carries AESER / AEACN / AESDTH aligned with ADSL's disposition
  (S02 discontinued for an AE and died) so the AET01 overview's header
  rows each count a distinct population.

Never edit values casually: the golden Parquet files under
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
    pl.from_repr("""\
┌─────────┬─────────┬──────────┬───────────┬──────────┬─────────┬───────┬───────┬──────────────────┬────────┬─────────┐
│ USUBJID ┆ TRTA    ┆ AEBODSYS ┆ AEDECOD   ┆ AESEV    ┆ AETOXGR ┆ AEREL ┆ AESER ┆ AEACN            ┆ AESDTH ┆ TRTEMFL │
│ ---     ┆ ---     ┆ ---      ┆ ---       ┆ ---      ┆ ---     ┆ ---   ┆ ---   ┆ ---              ┆ ---    ┆ ---     │
│ str     ┆ str     ┆ str      ┆ str       ┆ str      ┆ str     ┆ str   ┆ str   ┆ str              ┆ str    ┆ str     │
╞═════════╪═════════╪══════════╪═══════════╪══════════╪═════════╪═══════╪═══════╪══════════════════╪════════╪═════════╡
│ S01     ┆ Placebo ┆ NERVOUS  ┆ HEADACHE  ┆ MILD     ┆ 1       ┆ N     ┆ N     ┆ DOSE NOT CHANGED ┆ N      ┆ Y       │
│ S01     ┆ Placebo ┆ NERVOUS  ┆ MIGRAINE  ┆ SEVERE   ┆ 3       ┆ Y     ┆ Y     ┆ DOSE NOT CHANGED ┆ N      ┆ Y       │
│ S02     ┆ Placebo ┆ GASTRO   ┆ NAUSEA    ┆ MODERATE ┆ 2       ┆ N     ┆ N     ┆ DRUG WITHDRAWN   ┆ Y      ┆ Y       │
│ S05     ┆ Drug A  ┆ NERVOUS  ┆ HEADACHE  ┆ MODERATE ┆ 2       ┆ N     ┆ N     ┆ DOSE NOT CHANGED ┆ N      ┆ Y       │
│ S05     ┆ Drug A  ┆ GASTRO   ┆ NAUSEA    ┆ MILD     ┆ 1       ┆ Y     ┆ N     ┆ DOSE NOT CHANGED ┆ N      ┆ Y       │
│ S06     ┆ Drug A  ┆ NERVOUS  ┆ DIZZINESS ┆ MILD     ┆ 1       ┆ N     ┆ N     ┆ DOSE NOT CHANGED ┆ N      ┆ N       │
└─────────┴─────────┴──────────┴───────────┴──────────┴─────────┴───────┴───────┴──────────────────┴────────┴─────────┘
""")
)

ADCM = _with_trt01p(
    pl.from_repr("""\
┌─────────┬─────────┬────────┬───────────┐
│ USUBJID ┆ TRTA    ┆ CMCLAS ┆ CMDECOD   │
│ ---     ┆ ---     ┆ ---    ┆ ---       │
│ str     ┆ str     ┆ str    ┆ str       │
╞═════════╪═════════╪════════╪═══════════╡
│ S01     ┆ Placebo ┆ NSAID  ┆ ASPIRIN   │
│ S02     ┆ Placebo ┆ null   ┆ null      │
│ S05     ┆ Drug A  ┆ NSAID  ┆ IBUPROFEN │
└─────────┴─────────┴────────┴───────────┘
""")
)

ADMH = _with_trt01p(
    pl.from_repr("""\
┌─────────┬─────────┬──────────┬─────────┐
│ USUBJID ┆ TRTA    ┆ MHBODSYS ┆ MHDECOD │
│ ---     ┆ ---     ┆ ---      ┆ ---     │
│ str     ┆ str     ┆ str      ┆ str     │
╞═════════╪═════════╪══════════╪═════════╡
│ S01     ┆ Placebo ┆ CARDIAC  ┆ ANGINA  │
│ S06     ┆ Drug A  ┆ CARDIAC  ┆ ANGINA  │
└─────────┴─────────┴──────────┴─────────┘
""")
)

ADLB = _with_trt01p(
    pl.from_repr("""\
┌─────────┬─────────┬─────────┬──────────┬───────┬─────────┬──────┬──────┬────────┬────────┐
│ USUBJID ┆ TRTA    ┆ PARAMCD ┆ AVISIT   ┆ ABLFL ┆ ONTRTFL ┆ AVAL ┆ CHG  ┆ BNRIND ┆ ANRIND │
│ ---     ┆ ---     ┆ ---     ┆ ---      ┆ ---   ┆ ---     ┆ ---  ┆ ---  ┆ ---    ┆ ---    │
│ str     ┆ str     ┆ str     ┆ str      ┆ str   ┆ str     ┆ f64  ┆ f64  ┆ str    ┆ str    │
╞═════════╪═════════╪═════════╪══════════╪═══════╪═════════╪══════╪══════╪════════╪════════╡
│ S01     ┆ Placebo ┆ ALT     ┆ BASELINE ┆ Y     ┆ null    ┆ 10   ┆ null ┆ NORMAL ┆ NORMAL │
│ S01     ┆ Placebo ┆ ALT     ┆ WEEK 1   ┆ null  ┆ Y       ┆ 16   ┆ 6    ┆ NORMAL ┆ HIGH   │
│ S02     ┆ Placebo ┆ ALT     ┆ BASELINE ┆ Y     ┆ null    ┆ 40   ┆ null ┆ HIGH   ┆ HIGH   │
│ S02     ┆ Placebo ┆ ALT     ┆ WEEK 1   ┆ null  ┆ Y       ┆ 44   ┆ 4    ┆ HIGH   ┆ HIGH   │
│ S05     ┆ Drug A  ┆ ALT     ┆ BASELINE ┆ Y     ┆ null    ┆ 20   ┆ null ┆ NORMAL ┆ NORMAL │
│ S05     ┆ Drug A  ┆ ALT     ┆ WEEK 1   ┆ null  ┆ Y       ┆ 18   ┆ -2   ┆ NORMAL ┆ NORMAL │
└─────────┴─────────┴─────────┴──────────┴───────┴─────────┴──────┴──────┴────────┴────────┘
""")
)

ADEG = _with_trt01p(
    pl.from_repr("""\
┌─────────┬─────────┬─────────┬──────────┬───────┬──────┬──────┬────────────┐
│ USUBJID ┆ TRTA    ┆ PARAMCD ┆ AVISIT   ┆ ABLFL ┆ AVAL ┆ CHG  ┆ AVALCAT1   │
│ ---     ┆ ---     ┆ ---     ┆ ---      ┆ ---   ┆ ---  ┆ ---  ┆ ---        │
│ str     ┆ str     ┆ str     ┆ str      ┆ str   ┆ f64  ┆ f64  ┆ str        │
╞═════════╪═════════╪═════════╪══════════╪═══════╪══════╪══════╪════════════╡
│ S01     ┆ Placebo ┆ QTCF    ┆ BASELINE ┆ Y     ┆ 400  ┆ null ┆ <=450 msec │
│ S01     ┆ Placebo ┆ QTCF    ┆ WEEK 1   ┆ null  ┆ 432  ┆ 32   ┆ <=450 msec │
│ S05     ┆ Drug A  ┆ QTCF    ┆ BASELINE ┆ Y     ┆ 410  ┆ null ┆ <=450 msec │
│ S05     ┆ Drug A  ┆ QTCF    ┆ WEEK 1   ┆ null  ┆ 415  ┆ 5    ┆ <=450 msec │
└─────────┴─────────┴─────────┴──────────┴───────┴──────┴──────┴────────────┘
""")
)

ADEX = _with_trt01p(
    pl.from_repr("""\
┌─────────┬─────────┬─────────┬─────────┬──────┐
│ USUBJID ┆ TRTA    ┆ PARAMCD ┆ PARCAT1 ┆ AVAL │
│ ---     ┆ ---     ┆ ---     ┆ ---     ┆ ---  │
│ str     ┆ str     ┆ str     ┆ str     ┆ f64  │
╞═════════╪═════════╪═════════╪═════════╪══════╡
│ S01     ┆ Placebo ┆ TDOSE   ┆ OVERALL ┆ 540  │
│ S01     ┆ Placebo ┆ TDOSE   ┆ WEEK    ┆ 54   │
│ S05     ┆ Drug A  ┆ TDOSE   ┆ OVERALL ┆ 810  │
└─────────┴─────────┴─────────┴─────────┴──────┘
""")
)

ADDV = _with_trt01p(
    pl.from_repr("""\
┌─────────┬─────────┬─────────────────────────────────┐
│ USUBJID ┆ TRTA    ┆ DVDECOD                         │
│ ---     ┆ ---     ┆ ---                             │
│ str     ┆ str     ┆ str                             │
╞═════════╪═════════╪═════════════════════════════════╡
│ S01     ┆ Placebo ┆ VISIT OUT OF WINDOW             │
│ S05     ┆ Drug A  ┆ EXCLUDED CONCOMITANT MEDICATION │
└─────────┴─────────┴─────────────────────────────────┘
""")
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
