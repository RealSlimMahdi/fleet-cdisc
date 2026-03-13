# -*- coding: utf-8 -*-
"""
End-to-end CDISCPILOT01 pipeline — method chaining style.

raw eCRF CSVs  →  SDTM DM  →  ADaM ADSL + ADVS  →  Quality checks + Define-XML

Run from the repo root:
    uv run python examples/pipeline_cdiscpilot01.py
"""
from pathlib import Path

import polars as pl
import pymaverse  # noqa: F401 — registers .sdtm / .adam namespace extensions
from pymaverse import DatasetChecker, DefineSpecGenerator

RAW   = Path("datasets/cdiscpilot01/raw")
SPECS = Path("specs/cdiscpilot01")
OUT   = Path("outputs/cdiscpilot01")

# ── 1. Load raw data ─────────────────────────────────────────────────────────
dm_raw = pl.read_csv(RAW / "dm_raw.csv")
vs_raw = pl.read_csv(RAW / "vs_raw.csv")

# ── 2. SDTM DM ───────────────────────────────────────────────────────────────
dm = (
    dm_raw.sdtm
    .hardcode_no_ct("STUDYID",  value="CDISCPILOT01")
    .hardcode_no_ct("DOMAIN",   value="DM")
    .assign_no_ct(  "USUBJID",  source="patient_number")
    .assign_no_ct(  "SUBJID",   source="patient_number")
    .derivation(    "SITEID",   expression="pl.col('site_id').cast(pl.String)")
    .assign_no_ct(  "AGE",      source="age")
    .hardcode_no_ct("AGEU",     value="YEARS")
    .assign_ct(     "SEX",      source="sex",    ct_codelist="C66731",
                    ct_mapping={"F": "F", "M": "M"})
    .assign_ct(     "RACE",     source="race",   ct_codelist="C74457",
                    ct_mapping={"WHITE": "WHITE", "BLACK OR AFRICAN AMERICAN": "BLACK OR AFRICAN AMERICAN"})
    .assign_ct(     "ETHNIC",   source="ethnic", ct_codelist="C66790",
                    ct_mapping={"HISPANIC OR LATINO": "HISPANIC OR LATINO",
                                "NOT HISPANIC OR LATINO": "NOT HISPANIC OR LATINO"})
    .if_then_else(  "ARMCD",
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
    .select(spec=SPECS / "sdtm/define.yaml", dataset="DM")
    .write_parquet(OUT / "dm.parquet")
)
print(f"SDTM DM  : {dm.shape[0]} subjects  ·  {dm.shape[1]} columns")

# ── 3. ADaM ADSL ─────────────────────────────────────────────────────────────
adsl = (
    dm.adam
    .assigned("STUDYID",  value="CDISCPILOT01")
    .source(  "USUBJID")
    .source(  "SUBJID")
    .source(  "SITEID")
    .source(  "AGE")
    .source(  "AGEU")
    .source(  "SEX")
    .source(  "RACE")
    .source(  "ETHNIC")
    .source(  "ARMCD")
    .source(  "ARM")
    .source(  "ACTARMCD")
    .source(  "ACTARM")
    .rename(  "TRT01P",   source="ARM")
    .rename(  "TRT01A",   source="ACTARM")
    .rename(  "TRTSDT",   source="RFSTDTC")
    .rename(  "TRTEDT",   source="RFENDTC")
    .source(  "RFSTDTC")
    .source(  "RFENDTC")
    .source(  "RFICDTC")
    .select(spec=SPECS / "adam/define.yaml", dataset="ADSL")
    .write_parquet(OUT / "adsl.parquet")
)
print(f"ADaM ADSL: {adsl.shape[0]} subjects  ·  {adsl.shape[1]} columns")

# ── 4. ADaM ADVS ─────────────────────────────────────────────────────────────
# Join TRTSDT from ADSL so study day can be calculated
trtsdt_map = adsl.select(["USUBJID", "TRTSDT"])

advs = (
    vs_raw.adam
    .assigned("STUDYID", value="CDISCPILOT01")
    .rename(  "USUBJID",  source="patient_number")
    .rename(  "PARAMCD",  source="vstestcd")
    .rename(  "PARAM",    source="vstest")
    .rename(  "AVALU",    source="vsorresu")
    .derivation("AVAL",   expression="pl.col('vsorres').cast(pl.Float64, strict=False)")
    .assign_datetime("ADT", source="vsdtc",   mode="date")
    .lookup(  dataset=trtsdt_map, on="USUBJID", how="left")
    .study_day("ADY",     analysis_date="ADT", reference_date="TRTSDT")
    .flag(    "ABLFL",    criteria='pl.col("vsdy") <= 0',
              groups=["USUBJID", "PARAMCD"])
    .to_frame()  # materialize: ABLFL must exist before baseline() can reference it
    .adam
    .baseline("BASE",     aval="AVAL", baseline_flag="ABLFL",
              groups=["USUBJID", "PARAMCD"])
    .to_frame()  # materialize: BASE must exist before chg() / pchg() can reference it
    .adam
    .chg(     "CHG",      aval="AVAL", base="BASE")
    .pchg(    "PCHG",     aval="AVAL", base="BASE")
    .select(spec=SPECS / "adam/define.yaml", dataset="ADVS")
    .write_parquet(OUT / "advs.parquet")
)
print(f"ADaM ADVS: {advs.shape[0]} records  ·  {advs.shape[1]} columns")
print(f"  Parameters: {sorted(advs['PARAMCD'].unique().to_list())}")

# ── 5. Post-dataset quality checks ──────────────────────────────────────────
sdtm_checker = DatasetChecker(SPECS / "sdtm/define.yaml")
adam_checker  = DatasetChecker(SPECS / "adam/define.yaml")

for checker, df, dataset in [
    (sdtm_checker, dm,   "DM"),
    (adam_checker,  adsl, "ADSL"),
    (adam_checker,  advs, "ADVS"),
]:
    checker.check(df, dataset=dataset).print_report()

# ── 6. Generate Define-XML 2.1 ───────────────────────────────────────────────
DefineSpecGenerator(SPECS / "sdtm/define.yaml").generate(OUT / "define_sdtm.xml")
DefineSpecGenerator(SPECS / "adam/define.yaml").generate(OUT / "define_adam.xml")
print(f"Define-XML written to {OUT}/")
print("View in browser: http://localhost:8080/define_adam.xml"
      "  (serve with: python -m http.server 8080 --directory outputs/cdiscpilot01)")

