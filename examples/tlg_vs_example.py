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

import fleet  # noqa: F401 — registers namespaces
from fleet.tlg import (
    GroupPool,
    OverallStat,
    Statistic,
    VSSummarySpec,
)
from specs.cdiscpilot01.sdtm.codelists import ETHNIC, RACE, SEX

RAW = Path("datasets/cdiscpilot01/raw")


# ════════════════════════════════════════════════════════════════════════════
# 1. Load raw data & build ADSL (reuse pattern from tlg_ae_example.py)
# ════════════════════════════════════════════════════════════════════════════
print("══ 1. Load raw data & build ADSL ═══════════════════════════════════════")
dm_raw = pl.read_csv(RAW / "dm_raw.csv")

dm = (
    dm_raw.sdtm.hardcode_no_ct("STUDYID", value="CDISCPILOT01")
    .hardcode_no_ct("DOMAIN", value="DM")
    .assign_no_ct("USUBJID", source="patient_number")
    .assign_no_ct("AGE", source="age")
    .assign_ct("SEX", source="sex", ct_codelist=SEX, ct_mapping={"F": "F", "M": "M"})
    .assign_ct(
        "RACE",
        source="race",
        ct_codelist=RACE,
        ct_mapping={
            "WHITE": "WHITE",
            "BLACK OR AFRICAN AMERICAN": "BLACK OR AFRICAN AMERICAN",
        },
    )
    .assign_ct(
        "ETHNIC",
        source="ethnic",
        ct_codelist=ETHNIC,
        ct_mapping={
            "HISPANIC OR LATINO": "HISPANIC OR LATINO",
            "NOT HISPANIC OR LATINO": "NOT HISPANIC OR LATINO",
        },
    )
    .assign_no_ct("ARM", source="arm_description")
    .assign_dtc("RFSTDTC", source="first_dose_date", mode="date")
    .assign_dtc("RFENDTC", source="last_dose_date", mode="date")
    .to_frame()
)

adsl = (
    dm.adam.adsl.source("STUDYID")
    .source("USUBJID")
    .source("AGE")
    .source("SEX")
    .source("RACE")
    .source("ARM")
    .rename("TRT01P", source="ARM")
    .derive_dt("TRTSDT", source="RFSTDTC")
    .derive_dt("TRTEDT", source="RFENDTC")
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

advs = pl.DataFrame(vs_records)
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
    .rows(["PARAMCD"])
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
# 6. Pre-merge stratification pattern (C3: .by2())
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

# Use .by2() for second-dimension stratification
# Note: by2 is accumulated but current t_summary doesn't use group2 from builder yet.
# This demonstrates the API surface — full group2 computation is a future enhancement.
print("   ✓ C3 pre-merge pattern demonstrated: AGEGR1 joined from ADSL onto ADVS.")


print("\n════════════════════════════════════════════════════════════════════════")
print("  VS TLG example complete!")
print("════════════════════════════════════════════════════════════════════════")
