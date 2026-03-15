# -*- coding: utf-8 -*-
"""
Admiral-inspired ADSL pipeline for CDISCPILOT01.

Reproduces the admiral "Creating ADSL" programming flow in Python/Fleet:
  https://pharmaverse.github.io/admiral/articles/adsl.html

Admiral programming-flow steps reproduced
------------------------------------------
1.  Read in Data            DM, AE (raw CSVs); EX and DS synthesised from dm_raw
2.  Build SDTM domains      DM, EX, AE, DS
3.  Treatment variables     TRT01P = ARM,  TRT01A = ACTARM   (admiral: mutate)
4.  Treatment dates         TRTSDT, TRTEDT from EX            (admiral: derive_vars_merged)
5.  Treatment duration      TRTDURD                           (admiral: derive_var_trtdurd)
6.  Disposition             EOSDT, EOSSTT, DCSREAS, RANDDT    (admiral: derive_vars_merged)
7.  Age grouping            AGEGR1                            (admiral: derive_vars_cat)
8.  Safety population flag  SAFFL                             (admiral: derive_var_merged_exist_flag)
9.  Last date known alive   LSTALVDT from AE / TRTEDT         (admiral: derive_vars_extreme_event)
10. AE counts               NUMAE, NUMSAE                     (admiral: count_vals / custom)

Run from repo root:
    uv run python examples/admiral_adsl_cdiscpilot01.py
"""
from __future__ import annotations

from pathlib import Path

import polars as pl
import fleet  # noqa: F401 — registers .sdtm / .adam / .adsl namespace extensions

RAW = Path("datasets/cdiscpilot01/raw")
OUT = Path("outputs/cdiscpilot01")

# ════════════════════════════════════════════════════════════════════════════
# 1. Read in Data
# ════════════════════════════════════════════════════════════════════════════
dm_raw = pl.read_csv(RAW / "dm_raw.csv")
ae_raw = pl.read_csv(RAW / "ae_raw.csv")

print("── 1. Raw data loaded ───────────────────────────────────────────────────")
print(f"   dm_raw : {dm_raw.shape[0]:>3} rows   columns → {dm_raw.columns}")
print(f"   ae_raw : {ae_raw.shape[0]:>3} rows   columns → {ae_raw.columns}")

# ════════════════════════════════════════════════════════════════════════════
# 2a. Build SDTM DM
#     Admiral uses DM as the starting point for ADSL:
#       adsl <- dm %>% select(-DOMAIN) %>% mutate(TRT01P = ARM, ...)
# ════════════════════════════════════════════════════════════════════════════
dm = (
    dm_raw.sdtm
    .hardcode_no_ct("STUDYID",  value="CDISCPILOT01")
    .hardcode_no_ct("DOMAIN",   value="DM")
    .assign_no_ct(  "USUBJID",  source="patient_number")
    .assign_no_ct(  "SUBJID",   source="patient_number")
    .derivation(    "SITEID",   expression="pl.col('site_id').cast(pl.String)")
    .assign_no_ct(  "AGE",      source="age")
    .hardcode_no_ct("AGEU",     value="YEARS")
    .assign_ct("SEX",   source="sex",    ct_codelist="C66731",
               ct_mapping={"F": "F", "M": "M"})
    .assign_ct("RACE",  source="race",   ct_codelist="C74457",
               ct_mapping={
                   "WHITE":                       "WHITE",
                   "BLACK OR AFRICAN AMERICAN":   "BLACK OR AFRICAN AMERICAN",
               })
    .assign_ct("ETHNIC", source="ethnic", ct_codelist="C66790",
               ct_mapping={
                   "HISPANIC OR LATINO":     "HISPANIC OR LATINO",
                   "NOT HISPANIC OR LATINO": "NOT HISPANIC OR LATINO",
               })
    .if_then_else("ARMCD",
                  when=[
                      {"condition": pl.col("arm_code") == "Pbo",    "value": "PBO"},
                      {"condition": pl.col("arm_code") == "Xan_Lo", "value": "XAN_LO"},
                      {"condition": pl.col("arm_code") == "Xan_Hi", "value": "XAN_HI"},
                  ],
                  else_value="SCRNFAIL")
    .assign_no_ct(  "ARM",      source="arm_description")
    .assign_no_ct(  "ACTARMCD", source="arm_code")
    .assign_no_ct(  "ACTARM",   source="arm_description")
    .assign_datetime("RFSTDTC", source="first_dose_date",       mode="date")
    .assign_datetime("RFENDTC", source="last_dose_date",        mode="date")
    .assign_datetime("RFICDTC", source="informed_consent_date", mode="date")
    .to_frame()
)
print(f"\n── 2a. SDTM DM : {dm.shape[0]} subjects × {dm.shape[1]} variables")

# ════════════════════════════════════════════════════════════════════════════
# 2b. Synthesise SDTM EX (Exposure)
#     In admiral the CDISC Pilot EX dataset comes from {pharmaversesdtm}.
#     Here we reconstruct it from dm_raw's first_dose_date / last_dose_date.
#     One record per subject; EXDOSE derived from arm assignment:
#       Placebo → 0 mg   |   Xanomeline Low → 54 mg   |   High → 81 mg
#
#     Admiral condition to identify treated subjects:
#       EXDOSE > 0  OR  (EXDOSE == 0 AND EXTRT contains "PLACEBO")
# ════════════════════════════════════════════════════════════════════════════
ex = (
    dm_raw.with_columns(
        pl.lit("CDISCPILOT01").alias("STUDYID"),
        pl.lit("EX").alias("DOMAIN"),
        pl.col("patient_number").alias("USUBJID"),
        pl.col("arm_description").alias("EXTRT"),
        pl.when(pl.col("arm_code") == "Pbo")
          .then(pl.lit(0.0))
          .when(pl.col("arm_code") == "Xan_Lo")
          .then(pl.lit(54.0))
          .when(pl.col("arm_code") == "Xan_Hi")
          .then(pl.lit(81.0))
          .otherwise(None)
          .alias("EXDOSE"),
        pl.lit("mg").alias("EXDOSU"),
        pl.col("first_dose_date").alias("EXSTDTC"),
        pl.col("last_dose_date").alias("EXENDTC"),
        pl.lit(1).alias("EXSEQ"),
    )
    .select(["STUDYID", "DOMAIN", "USUBJID", "EXSEQ",
             "EXTRT", "EXDOSE", "EXDOSU", "EXSTDTC", "EXENDTC"])
)
print(f"── 2b. SDTM EX : {ex.shape[0]} records  × {ex.shape[1]} variables "
      f"(synthesised from dm_raw)")

# ════════════════════════════════════════════════════════════════════════════
# 2c. Synthesise SDTM DS (Disposition)
#     Admiral uses DS for EOSDT, EOSSTT, DCSREAS, and RANDDT.
#     Record types created:
#       DSCAT = "PROTOCOL MILESTONE"  / DSDECOD = "RANDOMIZED"  (at first dose)
#       DSCAT = "DISPOSITION EVENT"   / DSDECOD = "COMPLETED"   (at last dose)
# ════════════════════════════════════════════════════════════════════════════
_ds_cols = ["STUDYID", "DOMAIN", "USUBJID", "DSSEQ", "DSCAT", "DSTERM", "DSDECOD", "DSSTDTC"]

ds_completed = (
    dm_raw.with_columns(
        pl.lit("CDISCPILOT01").alias("STUDYID"),
        pl.lit("DS").alias("DOMAIN"),
        pl.col("patient_number").alias("USUBJID"),
        pl.lit(1).alias("DSSEQ"),
        pl.lit("DISPOSITION EVENT").alias("DSCAT"),
        pl.lit("PROTOCOL COMPLETED").alias("DSTERM"),
        pl.lit("COMPLETED").alias("DSDECOD"),
        pl.col("last_dose_date").alias("DSSTDTC"),
    )
    .select(_ds_cols)
)

ds_randomized = (
    dm_raw.with_columns(
        pl.lit("CDISCPILOT01").alias("STUDYID"),
        pl.lit("DS").alias("DOMAIN"),
        pl.col("patient_number").alias("USUBJID"),
        pl.lit(2).alias("DSSEQ"),
        pl.lit("PROTOCOL MILESTONE").alias("DSCAT"),
        pl.lit("RANDOMIZED").alias("DSTERM"),
        pl.lit("RANDOMIZED").alias("DSDECOD"),
        pl.col("first_dose_date").alias("DSSTDTC"),
    )
    .select(_ds_cols)
)

ds = pl.concat([ds_completed, ds_randomized]).sort(["USUBJID", "DSSEQ"])
print(f"── 2c. SDTM DS : {ds.shape[0]} records  × {ds.shape[1]} variables "
      f"(synthesised from dm_raw)")

# ════════════════════════════════════════════════════════════════════════════
# 2d. Build SDTM AE (Adverse Events) from ae_raw
# ════════════════════════════════════════════════════════════════════════════
ae = (
    ae_raw.with_columns(
        pl.lit("CDISCPILOT01").alias("STUDYID"),
        pl.lit("AE").alias("DOMAIN"),
        pl.col("patient_number").alias("USUBJID"),
        pl.col("ae_term").alias("AETERM"),
        pl.col("ae_start_date").alias("AESTDTC"),
        pl.col("ae_end_date").alias("AEENDTC"),
        pl.col("ae_severity").alias("AESEV"),
        pl.col("ae_serious").alias("AESER"),
        pl.col("ae_outcome").alias("AEOUT"),
        pl.col("ae_action_taken").alias("AEACN"),
        pl.col("ae_relationship").alias("AEREL"),
        # AESEQ: running count within each subject
        pl.col("ae_term").cum_count().over("patient_number").alias("AESEQ"),
    )
    .select(["STUDYID", "DOMAIN", "USUBJID", "AESEQ",
             "AETERM", "AESTDTC", "AEENDTC", "AESEV", "AESER", "AEOUT", "AEACN", "AEREL"])
)
print(f"── 2d. SDTM AE : {ae.shape[0]} records  × {ae.shape[1]} variables")

# ════════════════════════════════════════════════════════════════════════════
# 3–5. Build ADSL base + Treatment Variables + Treatment Dates/Duration
#      Admiral step 2 → TRT01P = ARM, TRT01A = ACTARM
#      Admiral step 3 → TRTSDT, TRTEDT from EX (derive_vars_merged, mode=first/last)
#      Admiral step 4 → TRTDURD (derive_var_trtdurd)
# ════════════════════════════════════════════════════════════════════════════
print("\n── 3–5. ADSL base + treatment dates ────────────────────────────────────")

adsl = (
    dm.adsl
    # ── demographics from DM ──────────────────────────────────────────────
    .source("STUDYID")
    .source("USUBJID")
    .source("SUBJID")
    .source("SITEID")
    .source("AGE")
    .source("AGEU")
    .source("SEX")
    .source("RACE")
    .source("ETHNIC")
    .source("ARM")
    .source("ARMCD")
    .source("ACTARM")
    .source("ACTARMCD")
    # ── treatment variables (admiral: adsl <- dm %>% mutate(TRT01P=ARM, TRT01A=ACTARM)) ──
    .rename("TRT01P", source="ARM")
    .rename("TRT01A", source="ACTARM")
    # ── study dates from DM ───────────────────────────────────────────────
    .source("RFSTDTC")
    .source("RFENDTC")
    .source("RFICDTC")
    .to_frame()
    # ── treatment start date from EX (admiral: derive_vars_merged, mode="first") ──
    .adsl
    .first_date("TRTSDT", from_dataset=ex, date_col="EXSTDTC")
    # ── treatment end date from EX (admiral: derive_vars_merged, mode="last") ──
    .last_date( "TRTEDT", from_dataset=ex, date_col="EXENDTC")
    # ── treatment duration (admiral: derive_var_trtdurd → TRTEDT - TRTSDT + 1) ──
    .duration(  "TRTDURD", start_date="TRTSDT", end_date="TRTEDT")
    .to_frame()
)

print(f"   {adsl.shape[0]} subjects × {adsl.shape[1]} variables")
print(f"   Sample: TRTSDT={adsl['TRTSDT'][0]!r}  TRTEDT={adsl['TRTEDT'][0]!r}  TRTDURD={adsl['TRTDURD'][0]}")

# ════════════════════════════════════════════════════════════════════════════
# 6. Disposition variables from DS
#    Admiral: derive_vars_merged(ds_ext) for each variable
#      EOSDT   — date of DISPOSITION EVENT
#      EOSSTT  — COMPLETED | DISCONTINUED | ONGOING (missing)
#      DCSREAS — discontinuation reason (DSDECOD when not COMPLETED/SCREEN FAILURE)
#      RANDDT  — date of RANDOMIZED milestone
# ════════════════════════════════════════════════════════════════════════════
print("\n── 6. Disposition variables ─────────────────────────────────────────────")

# EOSDT: latest date of DISPOSITION EVENT per subject
ds_eosdt = (
    ds.filter(pl.col("DSCAT") == "DISPOSITION EVENT")
      .group_by("USUBJID")
      .agg(pl.col("DSSTDTC").max().alias("EOSDT"))
)

# EOSSTT: status mapped from DSDECOD (admiral: format_eosstt)
ds_eosstt = (
    ds.filter(pl.col("DSCAT") == "DISPOSITION EVENT")
      .with_columns(
          pl.when(pl.col("DSDECOD") == "COMPLETED")
            .then(pl.lit("COMPLETED"))
            .when(pl.col("DSDECOD") == "SCREEN FAILURE")
            .then(pl.lit(None))
            .otherwise(pl.lit("DISCONTINUED"))
            .alias("EOSSTT")
      )
      .select(["USUBJID", "EOSSTT"])
)

# DCSREAS / DCSREASP: reason for discontinuation (null for completed subjects)
ds_dcsreas = (
    ds.filter(
        (pl.col("DSCAT") == "DISPOSITION EVENT")
        & pl.col("DSDECOD").is_not_null()
        & (~pl.col("DSDECOD").is_in(["COMPLETED", "SCREEN FAILURE"]))
    )
    .select(pl.col("USUBJID"),
            pl.col("DSDECOD").alias("DCSREAS"),
            pl.col("DSTERM").alias("DCSREASP"))
)

# RANDDT: date of RANDOMIZED protocol milestone
ds_randdt = (
    ds.filter(pl.col("DSDECOD") == "RANDOMIZED")
      .select(pl.col("USUBJID"), pl.col("DSSTDTC").alias("RANDDT"))
)

adsl = (
    adsl
    .join(ds_eosdt,   on="USUBJID", how="left")
    .join(ds_eosstt,  on="USUBJID", how="left")
    .join(ds_dcsreas, on="USUBJID", how="left")
    .join(ds_randdt,  on="USUBJID", how="left")
)

print(f"   {adsl.shape[0]} subjects × {adsl.shape[1]} variables")
print(f"   EOSSTT counts: {adsl['EOSSTT'].value_counts().to_dicts()}")

# ════════════════════════════════════════════════════════════════════════════
# 7. Age Grouping (AGEGR1)
#    Admiral: derive_vars_cat(agegr1_lookup)
#      AGE <18  → "<18"    |   18–64 → "18-64"   |   >64 → ">64"
# ════════════════════════════════════════════════════════════════════════════
print("\n── 7. Age grouping (AGEGR1) ─────────────────────────────────────────────")

adsl = (
    adsl.adsl
    .condderivation("AGEGR1",
                    conditions=[
                        {"condition": "pl.col('AGE') < 18",  "value": "<18"},
                        {"condition": "pl.col('AGE') <= 64", "value": "18-64"},
                        {"condition": "pl.col('AGE') > 64",  "value": ">64"},
                    ],
                    else_value="Missing")
    .to_frame()
)

_agegr = adsl.group_by("AGEGR1").agg(pl.len().alias("n")).sort("AGEGR1")
print(f"   AGEGR1 distribution: {_agegr.to_dicts()}")

# ════════════════════════════════════════════════════════════════════════════
# 8. Safety Population Flag (SAFFL)
#    Admiral: derive_var_merged_exist_flag(ex, condition = EXDOSE > 0 | PLACEBO)
#    Subjects with at least one exposure record (all randomised subjects here).
#    We also derive ITTFL (intent-to-treat) = same population in this study.
# ════════════════════════════════════════════════════════════════════════════
print("\n── 8. Population flags ──────────────────────────────────────────────────")

# Subjects with ≥1 EX record → treated (used for SAFFL)
subjects_exposed = ex.select("USUBJID").unique()

adsl = (
    adsl
    .with_columns(
        pl.col("USUBJID")
          .is_in(subjects_exposed["USUBJID"].to_list())
          .map_elements(lambda v: "Y" if v else None, return_dtype=pl.String)
          .alias("SAFFL")
    )
    # ITTFL: all randomised subjects (ARMCD not SCRNFAIL)
    .adsl
    .eligibility_flag("ITTFL",
                      criteria='pl.col("ARMCD") != "SCRNFAIL"')
    .to_frame()
)

print(f"   SAFFL : {adsl['SAFFL'].value_counts().to_dicts()}")
print(f"   ITTFL : {adsl['ITTFL'].value_counts().to_dicts()}")

# ════════════════════════════════════════════════════════════════════════════
# 9. Last Date Known Alive (LSTALVDT)
#    Admiral: derive_vars_extreme_event(ae, lb, adsl; order=last)
#    Sources (in priority order, latest date wins):
#      a) AE end dates   (AEENDTC)
#      b) AE start dates (AESTDTC)
#      c) Treatment end  (TRTEDT)  ← fallback if no AE records
# ════════════════════════════════════════════════════════════════════════════
print("\n── 9. Last date known alive (LSTALVDT) ──────────────────────────────────")

ae_last_end = (
    ae.filter(pl.col("AEENDTC").is_not_null())
      .group_by("USUBJID")
      .agg(pl.col("AEENDTC").max().alias("_ae_end"))
)

ae_last_start = (
    ae.filter(pl.col("AESTDTC").is_not_null())
      .group_by("USUBJID")
      .agg(pl.col("AESTDTC").max().alias("_ae_start"))
)

adsl = (
    adsl
    .join(ae_last_end,   on="USUBJID", how="left")
    .join(ae_last_start, on="USUBJID", how="left")
    .with_columns(
        # ISO 8601 strings are lexicographically comparable; max_horizontal ignores nulls
        pl.max_horizontal(
            pl.col("_ae_end"),
            pl.col("_ae_start"),
            pl.col("TRTEDT"),
        ).alias("LSTALVDT")
    )
    .drop(["_ae_end", "_ae_start"])
)

print(f"   {adsl.shape[0]} subjects × {adsl.shape[1]} variables")
print(f"   LSTALVDT range: {adsl['LSTALVDT'].min()} → {adsl['LSTALVDT'].max()}")

# ════════════════════════════════════════════════════════════════════════════
# 10. AE Summary Counts (NUMAE, NUMSAE)
#     Admiral: derive_vars_merged_summary / custom aggregation
#       NUMAE  — total number of AE records per subject
#       NUMSAE — number of serious AEs (AESER == "Y")
# ════════════════════════════════════════════════════════════════════════════
print("\n── 10. AE counts ────────────────────────────────────────────────────────")

adsl = (
    adsl.adsl
    .count_events("NUMAE",  from_dataset=ae)
    .count_events("NUMSAE", from_dataset=ae,
                  where='pl.col("AESER") == "Y"')
    .to_frame()
)

print(f"   Subjects with ≥1 AE  : {(adsl['NUMAE']  > 0).sum()}")
print(f"   Subjects with ≥1 SAE : {(adsl['NUMSAE'] > 0).sum()}")

# ════════════════════════════════════════════════════════════════════════════
# 11. Final column selection and output
#     Mirrors the admiral ADSL variable set from the vignette.
# ════════════════════════════════════════════════════════════════════════════
FINAL_COLS = [
    # Identifiers
    "STUDYID", "USUBJID", "SUBJID", "SITEID",
    # Demographics
    "AGE", "AGEU", "AGEGR1", "SEX", "RACE", "ETHNIC",
    # Treatment assignment
    "ARM", "ARMCD", "ACTARM", "ACTARMCD",
    # Planned / actual treatment labels (admiral: TRT01P, TRT01A)
    "TRT01P", "TRT01A",
    # Study-level dates from DM
    "RFSTDTC", "RFENDTC", "RFICDTC",
    # Randomisation date (admiral: RANDDT from DS)
    "RANDDT",
    # Treatment dates & duration (admiral: TRTSDT, TRTEDT, TRTDURD from EX)
    "TRTSDT", "TRTEDT", "TRTDURD",
    # Disposition (admiral: EOSDT, EOSSTT, DCSREAS, DCSREASP from DS)
    "EOSDT", "EOSSTT", "DCSREAS", "DCSREASP",
    # Survival
    "LSTALVDT",
    # Population flags (admiral: SAFFL, ITTFL)
    "SAFFL", "ITTFL",
    # AE summary counts
    "NUMAE", "NUMSAE",
]

adsl_final = adsl.select(FINAL_COLS)

print("\n── 11. Final ADSL ───────────────────────────────────────────────────────")
print(f"   Shape   : {adsl_final.shape[0]} subjects × {adsl_final.shape[1]} variables")
print(f"\n   First 5 rows (key columns):")
print(adsl_final.select(
    ["USUBJID", "AGE", "AGEGR1", "SEX", "TRT01P",
     "TRTSDT", "TRTEDT", "TRTDURD", "EOSSTT", "SAFFL", "NUMAE"]
).head(5))

# Persist outputs
OUT.mkdir(parents=True, exist_ok=True)
adsl_final.write_parquet(OUT / "adsl_admiral.parquet")
adsl_final.write_csv(OUT / "adsl_admiral.csv")

print(f"\n   Written: {OUT}/adsl_admiral.parquet")
print(f"   Written: {OUT}/adsl_admiral.csv")

# ════════════════════════════════════════════════════════════════════════════
# 12. Quick validation summary (mirrors admiral's dataset previews)
# ════════════════════════════════════════════════════════════════════════════
print("\n── 12. Validation summary ───────────────────────────────────────────────")
print(f"   Total subjects                   : {adsl_final.shape[0]}")
print(f"   Treatment arms                   : {sorted(adsl_final['TRT01P'].unique().to_list())}")
print(f"   Age range                        : {adsl_final['AGE'].min()} – {adsl_final['AGE'].max()} years")
print(f"   AGEGR1 distribution              : {adsl_final['AGEGR1'].value_counts().sort('AGEGR1').to_dicts()}")
print(f"   EOSSTT distribution              : {adsl_final['EOSSTT'].value_counts().sort('EOSSTT').to_dicts()}")
print(f"   SAFFL = Y                        : {(adsl_final['SAFFL'] == 'Y').sum()} / {adsl_final.shape[0]}")
print(f"   ITTFL = Y                        : {(adsl_final['ITTFL'] == 'Y').sum()} / {adsl_final.shape[0]}")
print(f"   TRTDURD range                    : {adsl_final['TRTDURD'].min()} – {adsl_final['TRTDURD'].max()} days")
print(f"   Subjects with ≥1 AE              : {(adsl_final['NUMAE'] > 0).sum()}")
print(f"   Subjects with ≥1 serious AE      : {(adsl_final['NUMSAE'] > 0).sum()}")
print(f"   LSTALVDT range                   : {adsl_final['LSTALVDT'].min()} → {adsl_final['LSTALVDT'].max()}")

# ════════════════════════════════════════════════════════════════════════════
# 13. ADaM ADVS — inline method-chaining  (admiral: create_advs)
#     https://pharmaverse.github.io/admiralvaccine/articles/advs.html
#
#     Steps reproduced from admiral vignette
#     a) Join ADSL → TRTSDT for study-day derivation
#     b) Rename par/result columns     → PARAMCD, PARAM, AVAL, AVALU, ADT
#     c) Study day                     → ADY    (derive_vars_dt)
#     d) Baseline flag                 → ABLFL  (flag_variables)
#     e) Baseline value                → BASE   (derive_var_base)
#     f) Change / % change             → CHG, PCHG (derive_var_chg)
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 13. ADaM ADVS (inline) ═══════════════════════════════════════════════")

vs_raw = pl.read_csv(RAW / "vs_raw.csv")

_trtsdt_map = adsl_final.select(["USUBJID", "TRTSDT"])

advs = (
    vs_raw.adam
    .assigned("STUDYID", value="CDISCPILOT01")
    .rename(  "USUBJID",  source="patient_number")
    .rename(  "PARAMCD",  source="vstestcd")
    .rename(  "PARAM",    source="vstest")
    .rename(  "AVALU",    source="vsorresu")
    .derivation("AVAL",   expression="pl.col('vsorres').cast(pl.Float64, strict=False)")
    .assign_datetime("ADT", source="vsdtc", mode="date")
    .lookup(dataset=_trtsdt_map, on="USUBJID", how="left")
    .study_day("ADY", analysis_date="ADT", reference_date="TRTSDT")
    # admiral: flag_variables — last pre-dose visit (vsdy ≤ 0)
    .flag("ABLFL", criteria='pl.col("vsdy") <= 0', groups=["USUBJID", "PARAMCD"])
    .to_frame()   # materialise — ABLFL must exist before baseline() window fn
    .adam
    # admiral: derive_var_base
    .baseline("BASE", aval="AVAL", baseline_flag="ABLFL", groups=["USUBJID", "PARAMCD"])
    .to_frame()   # materialise — BASE must exist before chg()/pchg()
    .adam
    # admiral: derive_var_chg
    .chg( "CHG",  aval="AVAL", base="BASE")
    .pchg("PCHG", aval="AVAL", base="BASE")
    .to_frame()
)

ADVS_COLS = ["STUDYID", "USUBJID", "PARAMCD", "PARAM",
             "AVAL", "AVALU", "ADT", "ADY", "ABLFL", "BASE", "CHG", "PCHG", "TRTSDT"]
advs_final = advs.select([c for c in ADVS_COLS if c in advs.columns])
advs_final.write_parquet(OUT / "advs_admiral.parquet")

print(f"   Shape      : {advs_final.shape[0]} records × {advs_final.shape[1]} variables")
print(f"   Parameters : {sorted(advs_final['PARAMCD'].unique().to_list())}")
print(f"   ABLFL = Y  : {(advs_final['ABLFL'] == 'Y').sum()} records")
print(f"   CHG range  : {advs_final['CHG'].drop_nulls().min():.2f} – {advs_final['CHG'].drop_nulls().max():.2f}")

# ════════════════════════════════════════════════════════════════════════════
# 14. ADaM ADAE — inline method-chaining  (admiral: create_adae)
#     https://pharmaverse.github.io/admiral/articles/adae.html
#
#     Steps reproduced from admiral vignette
#     a) Join ADSL treatment dates
#     b) Analysis dates               → ASTDT, AENDT (derive_vars_dt)
#     c) Study day                    → ADY           (derive_vars_dt)
#     d) Treatment-emergent flag      → TRTEMFL       (derive_var_trtemfl)
#     e) Worst severity flag per term → ANL01FL       (slice_derivation)
#     f) Sequence number              → ASEQ          (derive_var_obs_number)
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 14. ADaM ADAE (inline) ═══════════════════════════════════════════════")

_adsl_trt = adsl_final.select(["USUBJID", "TRTSDT", "TRTEDT", "TRT01P", "SAFFL"])
ae_with_trt = ae.join(_adsl_trt, on="USUBJID", how="left")

adae = (
    ae_with_trt.adam
    .assigned("STUDYID", value="CDISCPILOT01")
    .source(  "USUBJID")
    .source(  "AETERM")
    .source(  "AESTDTC")
    .source(  "AEENDTC")
    .source(  "AESEV")
    .source(  "AESER")
    .source(  "AEREL")
    .source(  "AEOUT")
    .source(  "AEACN")
    # admiral: derive_vars_dt
    .rename("ASTDT", source="AESTDTC")
    .rename("AENDT", source="AEENDTC")
    .to_frame()   # materialise — ASTDT must exist before study_day references it
    .adam
    .study_day("ADY", analysis_date="ASTDT", reference_date="TRTSDT")
    .to_frame()
    .occds
    # admiral: derive_var_trtemfl
    .treatment_emergent("TRTEMFL", start_date="AESTDTC",
                        trtsdt="TRTSDT", trtedt="TRTEDT")
    # admiral: slice_derivation (worst severity per subject × AE term)
    .worst_flag("ANL01FL", severity_col="AESEV",
                severity_order=["MILD", "MODERATE", "SEVERE"],
                groups=["USUBJID", "AETERM"])
    # admiral: derive_var_obs_number
    .seq("ASEQ", groups=["USUBJID"])
    .to_frame()
)

ADAE_COLS = ["STUDYID", "USUBJID", "ASEQ", "AETERM",
             "AESTDTC", "AEENDTC", "AESEV", "AESER", "AEREL", "AEOUT", "AEACN",
             "ASTDT", "AENDT", "ADY", "TRTEMFL", "ANL01FL",
             "TRTSDT", "TRTEDT", "TRT01P", "SAFFL"]
adae_final = adae.select([c for c in ADAE_COLS if c in adae.columns])
adae_final.write_parquet(OUT / "adae_admiral.parquet")

_te = (adae_final["TRTEMFL"] == "Y").sum()
print(f"   Shape                  : {adae_final.shape[0]} records × {adae_final.shape[1]} variables")
print(f"   Treatment-emergent AEs : {_te} / {adae_final.shape[0]}")
print(f"   Serious AEs (AESER=Y)  : {(adae_final['AESER'] == 'Y').sum()}")
print(f"   ANL01FL = Y (worst)    : {(adae_final['ANL01FL'] == 'Y').sum()} records")

# ════════════════════════════════════════════════════════════════════════════
# 15. ADaM ADEX — inline method-chaining  (admiral: create_adex)
#     https://pharmaverse.github.io/admiral/articles/adex.html
#
#     Steps reproduced from admiral vignette
#     a) Join ADSL
#     b) Analysis start/end dates → ASTDT, AENDT (derive_vars_dt)
#     c) Exposure duration        → EXDURD (derive_var_dur, inclusive)
#     d) Sequence number          → ASEQ   (derive_var_obs_number)
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 15. ADaM ADEX (inline) ═══════════════════════════════════════════════")

_adsl_ex = adsl_final.select(["USUBJID", "TRTSDT", "TRTEDT", "TRT01P", "SAFFL"])

adex = (
    ex.join(_adsl_ex, on="USUBJID", how="left")
    .adam
    .assigned("STUDYID", value="CDISCPILOT01")
    .source(  "USUBJID")
    .source(  "EXTRT")
    .source(  "EXDOSE")
    .source(  "EXDOSU")
    # admiral: derive_vars_dt
    .rename("ASTDT", source="EXSTDTC")
    .rename("AENDT", source="EXENDTC")
    .to_frame()   # materialise — ASTDT/AENDT must exist before EXDURD references them
    .adam
    # admiral: derive_var_dur (inclusive end-date convention)
    .derivation("EXDURD",
                expression="(pl.col('AENDT').cast(pl.Date) - pl.col('ASTDT').cast(pl.Date))"
                           ".dt.total_days() + 1")
    .to_frame()
    # admiral: derive_var_obs_number
    .occds
    .seq("ASEQ", groups=["USUBJID"])
    .to_frame()
)

ADEX_COLS = ["STUDYID", "USUBJID", "ASEQ", "EXTRT", "EXDOSE", "EXDOSU",
             "ASTDT", "AENDT", "EXDURD", "TRTSDT", "TRTEDT", "TRT01P", "SAFFL"]
adex_final = adex.select([c for c in ADEX_COLS if c in adex.columns])
adex_final.write_parquet(OUT / "adex_admiral.parquet")

print(f"   Shape        : {adex_final.shape[0]} records × {adex_final.shape[1]} variables")
print(f"   Treatments   : {adex_final['EXTRT'].unique().to_list()}")
print(f"   EXDURD range : {adex_final['EXDURD'].min()} – {adex_final['EXDURD'].max()} days")

# ════════════════════════════════════════════════════════════════════════════
# 16. Cross-dataset summary
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 16. Cross-dataset summary ════════════════════════════════════════════")
print(f"   ADSL : {adsl_final.shape[0]} subjects × {adsl_final.shape[1]} variables  → adsl_admiral.parquet")
print(f"   ADVS : {advs_final.shape[0]} records  × {advs_final.shape[1]} variables  → advs_admiral.parquet")
print(f"   ADAE : {adae_final.shape[0]} records  × {adae_final.shape[1]} variables  → adae_admiral.parquet")
print(f"   ADEX : {adex_final.shape[0]} records  × {adex_final.shape[1]} variables  → adex_admiral.parquet")
print(f"\n   All outputs in {OUT}/")
