# -*- coding: utf-8 -*-
"""
TLG Example — AE summary tables from CDISCPILOT01.

Demonstrates two approaches:
  1. **Default spec** — zero-config AE summary using standard column names
  2. **Custom spec**  — declarative spec override with pooled treatment arms,
     additional statistics, custom row hierarchy, and column ordering

The script:
  a) Loads raw CDISCPILOT01 data and builds SDTM AE + DM
  b) Derives a minimal ADSL and ADAE (reusing the Fleet pipeline patterns)
  c) Produces an AE summary ARD (default)
  d) Produces an AE summary ARD (custom spec with pools)
  e) Produces an AE listing (custom spec)

Run from repo root:
    uv run python examples/tlg_ae_example.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl

import fleet  # noqa: F401 — registers .sdtm / .adam / .tlg namespaces
from fleet.tlg import (
    AEListingSpec,
    AESummarySpec,
    Column,
    GroupPool,
    Row,
    Statistic,
)
from specs.cdiscpilot01.sdtm.codelists import ETHNIC, RACE, SEX

RAW = Path("datasets/cdiscpilot01/raw")


# ════════════════════════════════════════════════════════════════════════════
# 1. Load raw data
# ════════════════════════════════════════════════════════════════════════════
print("══ 1. Load raw data ═════════════════════════════════════════════════════")
dm_raw = pl.read_csv(RAW / "dm_raw.csv")
ae_raw = pl.read_csv(RAW / "ae_raw.csv")
print(f"   dm_raw : {dm_raw.shape[0]:>3} rows  ×  {dm_raw.shape[1]} cols")
print(f"   ae_raw : {ae_raw.shape[0]:>3} rows  ×  {ae_raw.shape[1]} cols")


# ════════════════════════════════════════════════════════════════════════════
# 2. Build SDTM DM
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 2. SDTM DM ══════════════════════════════════════════════════════════")
dm = (
    dm_raw.sdtm
    .hardcode_no_ct("STUDYID", value="CDISCPILOT01")
    .hardcode_no_ct("DOMAIN", value="DM")
    .assign_no_ct("USUBJID", source="patient_number")
    .assign_no_ct("AGE", source="age")
    .assign_ct("SEX", source="sex", ct_codelist=SEX,
               ct_mapping={"F": "F", "M": "M"})
    .assign_ct("RACE", source="race", ct_codelist=RACE,
               ct_mapping={
                   "WHITE": "WHITE",
                   "BLACK OR AFRICAN AMERICAN": "BLACK OR AFRICAN AMERICAN",
               })
    .assign_ct("ETHNIC", source="ethnic", ct_codelist=ETHNIC,
               ct_mapping={
                   "HISPANIC OR LATINO": "HISPANIC OR LATINO",
                   "NOT HISPANIC OR LATINO": "NOT HISPANIC OR LATINO",
               })
    .assign_no_ct("ARM", source="arm_description")
    .assign_dtc("RFSTDTC", source="first_dose_date", mode="date")
    .assign_dtc("RFENDTC", source="last_dose_date", mode="date")
    .to_frame()
)
print(f"   {dm.shape[0]} subjects × {dm.shape[1]} variables")


# ════════════════════════════════════════════════════════════════════════════
# 3. Build SDTM AE
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 3. SDTM AE ══════════════════════════════════════════════════════════")
ae = (
    ae_raw.sdtm
    .hardcode_no_ct("STUDYID", value="CDISCPILOT01")
    .hardcode_no_ct("DOMAIN", value="AE")
    .assign_no_ct("USUBJID", source="patient_number")
    .assign_no_ct("AETERM", source="ae_term")
    .assign_no_ct("AESTDTC", source="ae_start_date")
    .assign_no_ct("AEENDTC", source="ae_end_date")
    .assign_no_ct("AESEV", source="ae_severity")
    .assign_no_ct("AESER", source="ae_serious")
    .assign_no_ct("AEOUT", source="ae_outcome")
    .assign_no_ct("AEACN", source="ae_action_taken")
    .assign_no_ct("AEREL", source="ae_relationship")
    .to_frame()
)
print(f"   {ae.shape[0]} records × {ae.shape[1]} variables")


# ════════════════════════════════════════════════════════════════════════════
# 4. Derive minimal ADSL (for Big-N denominators)
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 4. ADSL (minimal) ═══════════════════════════════════════════════════")
adsl = (
    dm.adam.adsl
    .source("STUDYID")
    .source("USUBJID")
    .source("AGE")
    .source("SEX")
    .source("RACE")
    .source("ARM")
    .rename("TRT01P", source="ARM")
    .derive_dt("TRTSDT", source="RFSTDTC")
    .derive_dt("TRTEDT", source="RFENDTC")
    .derivation("SAFFL",
                expression='pl.when(pl.col("TRTSDT").is_not_null()).then(pl.lit("Y")).otherwise(pl.lit("N"))')
    .to_frame()
)
# Use TRT01P as TRTA for summary tables
adsl = adsl.with_columns(pl.col("TRT01P").alias("TRTA"))

print(f"   {adsl.shape[0]} subjects × {adsl.shape[1]} variables")
print(f"   Arms: {sorted(adsl['TRTA'].unique().to_list())}")
print(f"   SAFFL=Y: {(adsl['SAFFL'] == 'Y').sum()} / {adsl.shape[0]}")


# ════════════════════════════════════════════════════════════════════════════
# 5. Derive ADAE (from SDTM AE + ADSL treatment info)
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 5. ADAE ═════════════════════════════════════════════════════════════")
_adsl_trt = adsl.select(["USUBJID", "TRTSDT", "TRTEDT", "TRT01P", "TRTA", "SAFFL"])
ae_with_trt = ae.join(_adsl_trt, on="USUBJID", how="left")

adae = (
    ae_with_trt.adam
    .source("STUDYID")
    .source("USUBJID")
    .source("AETERM")
    .source("AESTDTC")
    .source("AEENDTC")
    .source("AESEV")
    .source("AESER")
    .source("AEREL")
    .source("AEOUT")
    .source("AEACN")
    .source("TRTA")
    .source("SAFFL")
    .derive_dt("ASTDT", source="AESTDTC")
    .derive_dt("AENDT", source="AEENDTC")
    .study_day("ADY", analysis_date="ASTDT", reference_date="TRTSDT")
    .to_frame()
    .adam.occds
    .treatment_emergent("TRTEMFL", start_date="AESTDTC",
                        trtsdt="TRTSDT", trtedt="TRTEDT")
    .seq("ASEQ", groups=["USUBJID"])
    .to_frame()
)

# Derive AEDECOD and AEBODSYS for TLG consumption.
# In a real study these come from MedDRA coding; here we simulate them.
adae = adae.with_columns(
    pl.col("AETERM").str.to_titlecase().alias("AEDECOD"),
    pl.when(pl.col("AETERM").is_in(["HEADACHE", "DIZZINESS"]))
    .then(pl.lit("NERVOUS SYSTEM DISORDERS"))
    .when(pl.col("AETERM").is_in(["NAUSEA"]))
    .then(pl.lit("GASTROINTESTINAL DISORDERS"))
    .when(pl.col("AETERM").is_in(["FATIGUE"]))
    .then(pl.lit("GENERAL DISORDERS"))
    .otherwise(pl.lit("OTHER"))
    .alias("AEBODSYS"),
)

print(f"   {adae.shape[0]} records × {adae.shape[1]} variables")
print(f"   Columns: {adae.columns}")
print(f"   AE terms: {sorted(adae['AEDECOD'].unique().to_list())}")
print(f"   Body systems: {sorted(adae['AEBODSYS'].unique().to_list())}")


# ════════════════════════════════════════════════════════════════════════════
# 6. AE Summary — DEFAULT spec (zero-config)
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 6. AE Summary — DEFAULT (zero-config) ═══════════════════════════════")
print("   adae.tlg.ae.t_summary(groupby='TRTA', adsl=adsl)")
print()

ard_default = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)

print(ard_default)
print(f"\n   ARD shape: {ard_default.shape[0]} rows × {ard_default.shape[1]} cols")
print(f"   Arms in output: {sorted(ard_default['group1_level'].unique().to_list())}")


# ════════════════════════════════════════════════════════════════════════════
# 7. AE Summary — CUSTOM spec (declarative override)
#    Adds:
#      • Pooled "All Xanomeline" and "Total" treatment groups
#      • Event count statistic alongside n and %
#      • Serious AE sub-analysis row
#      • Explicit column ordering
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 7. AE Summary — CUSTOM spec (with pools & extra stats) ══════════════")

custom_spec = AESummarySpec(
    rows=[
        Row(field="AEBODSYS", label="System Organ Class"),
        Row(field="AEDECOD", label="Preferred Term"),
        Row(field="AESER", label="Serious AE", filter_value="Y"),
    ],
    columns=["TRTA"],
    statistics=[Statistic.N_SUBJECTS, Statistic.N_PCT, Statistic.N_EVENTS],
    pools=[
        GroupPool(label="All Xanomeline",
                  arms=["Xanomeline Low Dose", "Xanomeline High Dose"]),
        GroupPool(label="Total", arms="*"),
    ],
    column_order=[
        "Placebo", "Xanomeline Low Dose", "Xanomeline High Dose",
        "All Xanomeline", "Total",
    ],
)

print("   Spec:")
print(f"     rows       = {[r.field for r in custom_spec.rows]}")
print(f"     statistics = {[s.value for s in custom_spec.statistics]}")
print(f"     pools      = {[p.label for p in custom_spec.pools]}")
print()

ard_custom = adae.tlg.ae.t_summary(spec=custom_spec, adsl=adsl)

print(ard_custom)
print(f"\n   ARD shape: {ard_custom.shape[0]} rows × {ard_custom.shape[1]} cols")
print(f"   Arms in output: {sorted(ard_custom['group1_level'].unique().to_list())}")

# Show Big-N row for each arm
big_n_rows = ard_custom.filter(pl.col("stat_name") == "N")
print("\n   Big-N denominators:")
for row in big_n_rows.iter_rows(named=True):
    print(f"     {row['group1_level']:>25s}  N = {int(row['stat'])}")


# ════════════════════════════════════════════════════════════════════════════
# 8. AE Listing — CUSTOM spec
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 8. AE Listing — CUSTOM spec ═════════════════════════════════════════")

listing_spec = AEListingSpec(
    columns=[
        Column(field="USUBJID", label="Subject"),
        Column(field="TRTA", label="Treatment"),
        Column(field="AEBODSYS", label="Body System"),
        Column(field="AEDECOD", label="Preferred Term"),
        Column(field="AESEV", label="Severity"),
        Column(field="AESER", label="Serious"),
        Column(field="ASTDT", label="Start Date"),
        Column(field="AEACN", label="Action Taken"),
    ],
    sort_by=["USUBJID", "ASTDT"],
    filter=pl.col("SAFFL") == "Y",
)

listing = adae.tlg.ae.l_listing(spec=listing_spec)

print(listing)
print(f"\n   Listing shape: {listing.shape[0]} rows × {listing.shape[1]} cols")


# ════════════════════════════════════════════════════════════════════════════
# 9. Pre-validation check
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 9. Pre-validation check ═════════════════════════════════════════════")
report = adae.tlg.ae.check(spec=custom_spec)
if report:
    for msg in report:
        print(f"   ⚠ {msg}")
else:
    print("   ✓ All checks passed — data is ready for the custom AE summary.")


# ════════════════════════════════════════════════════════════════════════════
# 10. Spec YAML round-trip
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 10. Spec YAML round-trip ════════════════════════════════════════════")
yaml_str = custom_spec.to_yaml()
print(yaml_str)

restored = AESummarySpec.from_yaml(yaml_str)
assert restored.rows == custom_spec.rows
assert restored.statistics == custom_spec.statistics
assert restored.pools == custom_spec.pools
print("   ✓ Round-trip: to_yaml() → from_yaml() produces identical spec.")


print("\n════════════════════════════════════════════════════════════════════════")
print("  TLG example complete!")
print("════════════════════════════════════════════════════════════════════════")
