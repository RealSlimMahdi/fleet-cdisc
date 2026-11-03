"""
TLG Example — VS summary tables from CDISCPILOT01.

Demonstrates the inline fluent builder on the VS domain:
  1. Build a minimal ADVS from raw vitals
  2. Produce a VS summary ARD using the builder API
  3. Produce a VS summary with header rows and dataset filter
  4. Pre-merge stratification pattern (C3)

Run from repo root:
    uv run python examples/tlg_vs_example.py
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl

import fleet  # registers namespaces
from examples.cdiscpilot01.sdtm.codelists import ETHNIC, RACE, SEX
from fleet.tlg import (
    GroupPool,
    OverallStat,
    Statistic,
    VSSummarySpec,
)

# ════════════════════════════════════════════════════════════════════════════
# 1. Load raw data & build ADSL (reuse pattern from tlg_ae_example.py)
# ════════════════════════════════════════════════════════════════════════════
print("══ 1. Load raw data & build ADSL ═══════════════════════════════════════")
dm_raw = fleet.frame(
    pl.from_repr("""\
┌────────────────┬─────────┬─────┬─────┬───────────────────────────┬────────────────────────┬──────────┬──────────────────────┬─────────────────┬────────────────┬───────────────────────┐
│ patient_number ┆ site_id ┆ age ┆ sex ┆ race                      ┆ ethnic                 ┆ arm_code ┆ arm_description      ┆ first_dose_date ┆ last_dose_date ┆ informed_consent_date │
│ ---            ┆ ---     ┆ --- ┆ --- ┆ ---                       ┆ ---                    ┆ ---      ┆ ---                  ┆ ---             ┆ ---            ┆ ---                   │
│ str            ┆ i64     ┆ i64 ┆ str ┆ str                       ┆ str                    ┆ str      ┆ str                  ┆ str             ┆ str            ┆ str                   │
╞════════════════╪═════════╪═════╪═════╪═══════════════════════════╪════════════════════════╪══════════╪══════════════════════╪═════════════════╪════════════════╪═══════════════════════╡
│ 01-701-1015    ┆ 701     ┆ 63  ┆ F   ┆ WHITE                     ┆ NOT HISPANIC OR LATINO ┆ Pbo      ┆ Placebo              ┆ 2014-01-02      ┆ 2014-07-02     ┆ 2014-01-01            │
│ 01-701-1023    ┆ 701     ┆ 64  ┆ F   ┆ WHITE                     ┆ NOT HISPANIC OR LATINO ┆ Xan_Lo   ┆ Xanomeline Low Dose  ┆ 2014-01-03      ┆ 2014-07-04     ┆ 2014-01-02            │
│ 01-701-1028    ┆ 701     ┆ 71  ┆ M   ┆ WHITE                     ┆ NOT HISPANIC OR LATINO ┆ Xan_Hi   ┆ Xanomeline High Dose ┆ 2014-01-04      ┆ 2014-07-05     ┆ 2014-01-03            │
│ 01-701-1034    ┆ 701     ┆ 74  ┆ M   ┆ BLACK OR AFRICAN AMERICAN ┆ NOT HISPANIC OR LATINO ┆ Pbo      ┆ Placebo              ┆ 2014-01-05      ┆ 2014-07-06     ┆ 2014-01-04            │
│ 01-701-1047    ┆ 701     ┆ 56  ┆ F   ┆ WHITE                     ┆ NOT HISPANIC OR LATINO ┆ Xan_Lo   ┆ Xanomeline Low Dose  ┆ 2014-01-06      ┆ 2014-07-07     ┆ 2014-01-05            │
└────────────────┴─────────┴─────┴─────┴───────────────────────────┴────────────────────────┴──────────┴──────────────────────┴─────────────────┴────────────────┴───────────────────────┘
""")
)

dm = (
    dm_raw.sdtm.assign("STUDYID", value="CDISCPILOT01")
    .assign("DOMAIN", value="DM")
    .assign("USUBJID", source="patient_number")
    .assign("AGE", source="age")
    .assign("SEX", source="sex", ct=SEX, ct_map={"F": "F", "M": "M"})
    .assign(
        "RACE",
        source="race",
        ct=RACE,
        ct_map={
            "WHITE": "WHITE",
            "BLACK OR AFRICAN AMERICAN": "BLACK OR AFRICAN AMERICAN",
        },
    )
    .assign(
        "ETHNIC",
        source="ethnic",
        ct=ETHNIC,
        ct_map={
            "HISPANIC OR LATINO": "HISPANIC OR LATINO",
            "NOT HISPANIC OR LATINO": "NOT HISPANIC OR LATINO",
        },
    )
    .assign("ARM", source="arm_description")
    .date("RFSTDTC", source="first_dose_date")
    .date("RFENDTC", source="last_dose_date")
    .to_frame()
)

adsl = (
    dm.adam.adsl.source("STUDYID")
    .source("USUBJID")
    .source("AGE")
    .source("SEX")
    .source("RACE")
    .source("ARM")
    .assign("TRT01P", source="ARM")
    .date("TRTSDT", source="RFSTDTC")
    .date("TRTEDT", source="RFENDTC")
    .derivation(
        "SAFFL",
        expression='pl.when(pl.col("TRTSDT").is_not_null()).then(pl.lit("Y")).otherwise(pl.lit("N"))',
    )
    .to_frame()
)
adsl = adsl.with_columns(pl.col("TRT01P").alias("TRTA"))

print(f"   {adsl.shape[0]} subjects × {adsl.shape[1]} variables")
print(f"   Arms: {sorted(adsl['TRTA'].unique().to_list())}")


# ════════════════════════════════════════════════════════════════════════════
# 2. Build synthetic ADVS
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 2. Build synthetic ADVS ═════════════════════════════════════════════")

# Create a minimal ADVS from ADSL subjects with synthetic vital signs
random.seed(42)

subjects = adsl.select(["USUBJID", "TRTA", "SAFFL"]).to_dicts()
vs_records = []
for subj in subjects:
    for paramcd, param_label in [
        ("SYSBP", "Systolic BP"),
        ("DIABP", "Diastolic BP"),
        ("PULSE", "Pulse Rate"),
    ]:
        for visit in ["Baseline", "Week 2", "Week 8"]:
            base = {"SYSBP": 120, "DIABP": 80, "PULSE": 72}[paramcd]
            vs_records.append(
                {
                    "USUBJID": subj["USUBJID"],
                    "TRTA": subj["TRTA"],
                    "SAFFL": subj["SAFFL"],
                    "PARAMCD": paramcd,
                    "PARAM": param_label,
                    "AVISIT": visit,
                    "AVAL": round(base + random.gauss(0, 10), 1),
                }
            )

advs = fleet.frame(pl.DataFrame(vs_records))
print(f"   {advs.shape[0]} records × {advs.shape[1]} variables")
print(f"   Parameters: {sorted(advs['PARAMCD'].unique().to_list())}")
print(f"   Visits: {advs['AVISIT'].unique().to_list()}")


# ════════════════════════════════════════════════════════════════════════════
# 3. VS Summary — DEFAULT spec (zero-config)
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 3. VS Summary — DEFAULT spec ════════════════════════════════════════")
ard_default = advs.tlg.vs.t_summary(groupby="TRTA", adsl=adsl)
print(ard_default)
print(f"\n   ARD shape: {ard_default.shape[0]} rows × {ard_default.shape[1]} cols")


# ════════════════════════════════════════════════════════════════════════════
# 4. VS Summary — INLINE BUILDER with dataset filter + header rows
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 4. VS Summary — INLINE BUILDER ══════════════════════════════════════")

ard_builder = (
    advs.tlg.vs.population(adsl, adsl_filter=pl.col("SAFFL") == "Y")
    .filter(pl.col("PARAMCD").is_in(["SYSBP", "DIABP"]))
    .by("TRTA")
    .header_rows(
        [
            OverallStat(label="Subjects with any measurement"),
        ]
    )
    .rows(["PARAMCD", "AVISIT"])
    .stats([Statistic.MEAN, Statistic.SD, Statistic.MEDIAN])
    .to_ard()
)

print(ard_builder)
print(f"\n   ARD shape: {ard_builder.shape[0]} rows × {ard_builder.shape[1]} cols")
print(
    f"   Parameters in output: {ard_builder.filter(pl.col('variable') != '')['variable_level'].unique().to_list()}"
)


# ════════════════════════════════════════════════════════════════════════════
# 5. VS Summary — spec-driven with pools
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 5. VS Summary — SPEC with pools ═════════════════════════════════════")

spec = VSSummarySpec(
    dataset_filter=pl.col("PARAMCD") == "SYSBP",
    adsl_filter=pl.col("SAFFL") == "Y",
    pools=[GroupPool(label="Total", arms="*")],
    column_order=["Placebo", "Xanomeline Low Dose", "Xanomeline High Dose", "Total"],
)
ard_spec = advs.tlg.vs.t_summary(groupby="TRTA", adsl=adsl, spec=spec)
print(ard_spec)
print(f"\n   ARD shape: {ard_spec.shape[0]} rows × {ard_spec.shape[1]} cols")


# ════════════════════════════════════════════════════════════════════════════
# 6. Pre-merge stratification pattern (C3)
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 6. Pre-merge stratification (C3 pattern) ════════════════════════════")

# Add AGEGR1 from ADSL to ADVS via pre-merge
adsl_age = adsl.with_columns(
    pl.when(pl.col("AGE") < 65).then(pl.lit("<65")).otherwise(pl.lit(">=65")).alias("AGEGR1")
)
advs_strat = advs.join(
    adsl_age.select(["USUBJID", "AGEGR1"]),
    on="USUBJID",
    how="left",
)
print(f"   ADVS with AGEGR1: {advs_strat.shape[0]} rows × {advs_strat.shape[1]} cols")
print(f"   Age groups: {sorted(advs_strat['AGEGR1'].unique().to_list())}")

# Nested stratification: pass the merged column as a second row field —
# the engine computes per-(AGEGR1, PARAMCD) cells with group2 lineage.
# One visit only: the hierarchy has two levels, so the visit is a filter.
ard_strat = (
    fleet.frame(advs_strat)
    .tlg.vs.population(adsl_age)
    .filter(pl.col("AVISIT") == "Week 8")
    .by("TRTA")
    .rows(["AGEGR1", "PARAMCD"])
    .to_ard()
)
print(f"   Stratified ARD: {ard_strat.shape[0]} rows (AGEGR1 → PARAMCD nesting)")
print("   ✓ C3 pre-merge pattern demonstrated: AGEGR1 joined from ADSL onto ADVS.")


print("\n════════════════════════════════════════════════════════════════════════")
print("  VS TLG example complete!")
print("════════════════════════════════════════════════════════════════════════")
