# -*- coding: utf-8 -*-
"""
End-to-end CDISCPILOT01 pipeline — spec-driven style.

Every ADaM column derivation is defined in specs/cdiscpilot01/adam/define.yaml
and executed via ``df.adam.from_spec()``.  OCCDS-specific verbs that the spec
cannot yet express (treatment_emergent, worst_flag, seq) are applied inline
immediately after the spec phase.

Datasets produced
-----------------
  SDTM  DM   — demographics (inline; input for ADaM)
  ADaM  ADSL — subject level          (from_spec driven)
  ADaM  ADVS — vital signs BDS        (from_spec, 3-phase staged for ABLFL→BASE→CHG)
  ADaM  ADAE — adverse events OCCDS   (from_spec for source cols; occds for TRTEMFL/ASEQ)
  ADaM  ADEX — exposure BDS           (from_spec driven)

Run from the repo root:
    uv run python examples/pipeline_cdiscpilot01.py
"""
from pathlib import Path

import polars as pl
import fleet  # noqa: F401 — registers .sdtm / .adam namespace extensions
from fleet import DatasetChecker, DefineSpecGenerator

RAW       = Path("datasets/cdiscpilot01/raw")
SPECS     = Path("specs/cdiscpilot01")
OUT       = Path("outputs/cdiscpilot01")
OUT.mkdir(parents=True, exist_ok=True)

SDTM_SPEC = SPECS / "sdtm/define.yaml"
ADAM_SPEC = SPECS / "adam/define.yaml"

# ── 1. Load raw data ─────────────────────────────────────────────────────────
dm_raw = pl.read_csv(RAW / "dm_raw.csv")
ae_raw = pl.read_csv(RAW / "ae_raw.csv")
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
    .select(spec=SDTM_SPEC, dataset="DM")
    .write_parquet(OUT / "dm.parquet")
)
print(f"SDTM DM  : {dm.shape[0]} subjects  ·  {dm.shape[1]} columns")

# ── 3. Synthesise SDTM EX (one record per subject) ───────────────────────────
ex = (
    dm_raw.with_columns(
        pl.lit("CDISCPILOT01").alias("STUDYID"),
        pl.lit("EX").alias("DOMAIN"),
        pl.col("patient_number").alias("USUBJID"),
        pl.col("arm_description").alias("EXTRT"),
        pl.when(pl.col("arm_code") == "Pbo")   .then(pl.lit(0.0))
          .when(pl.col("arm_code") == "Xan_Lo").then(pl.lit(54.0))
          .when(pl.col("arm_code") == "Xan_Hi").then(pl.lit(81.0))
          .otherwise(None).alias("EXDOSE"),
        pl.lit("mg").alias("EXDOSU"),
        pl.col("first_dose_date").alias("EXSTDTC"),
        pl.col("last_dose_date").alias("EXENDTC"),
        pl.lit(1).alias("EXSEQ"),
    )
    .select(["STUDYID", "DOMAIN", "USUBJID", "EXSEQ",
             "EXTRT", "EXDOSE", "EXDOSU", "EXSTDTC", "EXENDTC"])
)

# ── 4. Synthesise SDTM AE ─────────────────────────────────────────────────────
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
        pl.col("ae_term").cum_count().over("patient_number").alias("AESEQ"),
    )
    .select(["STUDYID", "DOMAIN", "USUBJID", "AESEQ",
             "AETERM", "AESTDTC", "AEENDTC", "AESEV", "AESER",
             "AEOUT", "AEACN", "AEREL"])
)
print(f"SDTM AE  : {ae.shape[0]} records  ·  {ae.shape[1]} columns")

# ════════════════════════════════════════════════════════════════════════════
# 5. ADaM ADSL — spec-driven
#    Simple derivations (source/rename/assigned) live in the spec.
#    Join-based pre-computations (TRTSDT from EX, AGEGR1, SAFFL, ITTFL,
#    TRT01P/TRT01A) are added to the DM frame before from_spec() runs.
# ════════════════════════════════════════════════════════════════════════════
print("\n── ADaM ADSL (spec-driven) ──────────────────────────────────────────────")

_ex_dates = (
    ex.group_by("USUBJID")
      .agg(pl.col("EXSTDTC").min().alias("TRTSDT"),
           pl.col("EXENDTC").max().alias("TRTEDT"))
)
_subjects_exposed = ex.select("USUBJID").unique()

dm_enriched = (
    dm
    .join(_ex_dates, on="USUBJID", how="left")
    .with_columns(
        pl.col("ARM").alias("TRT01P"),
        pl.col("ACTARM").alias("TRT01A"),
        pl.when(pl.col("AGE") < 18) .then(pl.lit("<18"))
          .when(pl.col("AGE") <= 64).then(pl.lit("18-64"))
          .otherwise(pl.lit(">64")).alias("AGEGR1"),
        pl.col("USUBJID")
          .is_in(_subjects_exposed["USUBJID"].to_list())
          .map_elements(lambda v: "Y" if v else None, return_dtype=pl.String)
          .alias("SAFFL"),
        pl.when(pl.col("ARMCD") != "SCRNFAIL")
          .then(pl.lit("Y")).otherwise(pl.lit(None)).alias("ITTFL"),
    )
)

adsl = (
    dm_enriched.adam
    .from_spec(ADAM_SPEC, dataset="ADSL")
    .select(spec=ADAM_SPEC, dataset="ADSL")
    .write_parquet(OUT / "adsl.parquet")
)
print(f"   {adsl.shape[0]} subjects × {adsl.shape[1]} variables")

# ════════════════════════════════════════════════════════════════════════════
# 6. ADaM ADVS — spec-driven
#    depends_on: in the spec triggers auto-flush between dependent batches:
#      ADT → ADY,  ABLFL → BASE,  BASE → CHG / PCHG
# ════════════════════════════════════════════════════════════════════════════
print("\n── ADaM ADVS (spec-driven) ──────────────────────────────────────────────")

_trtsdt_map = adsl.select(["USUBJID", "TRTSDT"])
vs_with_trtsdt = (
    vs_raw
    .with_columns(pl.col("patient_number").alias("USUBJID"))
    .join(_trtsdt_map, on="USUBJID", how="left")
)

advs = (
    vs_with_trtsdt.adam
    .from_spec(ADAM_SPEC, dataset="ADVS")
    .select(spec=ADAM_SPEC, dataset="ADVS")
    .write_parquet(OUT / "advs.parquet")
)
print(f"   {advs.shape[0]} records × {advs.shape[1]} variables")
print(f"   Parameters: {sorted(advs['PARAMCD'].unique().to_list())}")

# ════════════════════════════════════════════════════════════════════════════
# 7. ADaM ADAE — hybrid: spec for source columns, occds for OCCDS-specific verbs
#    admiral ref: https://pharmaverse.github.io/admiral/articles/adae.html
# ════════════════════════════════════════════════════════════════════════════
print("\n── ADaM ADAE (spec-driven + occds verbs) ────────────────────────────────")

_adsl_trt = adsl.select(["USUBJID", "TRTSDT", "TRTEDT", "TRT01P", "AGE", "SEX", "SAFFL"])
ae_with_trt = ae.join(_adsl_trt, on="USUBJID", how="left")

adae_sourced = (
    ae_with_trt.adam
    .from_spec(ADAM_SPEC, dataset="ADAE")
    .to_frame()
)

adae = (
    adae_sourced.adam.occds
    .treatment_emergent("TRTEMFL", start_date="AESTDTC",
                        trtsdt="TRTSDT", trtedt="TRTEDT")
    .worst_flag("ANL01FL", severity_col="AESEV",
                severity_order=["MILD", "MODERATE", "SEVERE"],
                groups=["USUBJID", "AETERM"])
    .seq("ASEQ", groups=["USUBJID"])
    .to_frame()
    .with_columns(
        pl.col("TRTSDT"), pl.col("TRTEDT"),
        pl.col("TRT01P"), pl.col("AGE"), pl.col("SEX"), pl.col("SAFFL"),
    )
)
_adae_cols = ["STUDYID", "USUBJID", "AETERM", "AESTDTC", "AEENDTC", "AESEV",
              "AESER", "AEREL", "AEOUT", "AEACN", "ASTDT", "AENDT", "ADY",
              "TRTEMFL", "ANL01FL", "ASEQ",
              "TRTSDT", "TRTEDT", "TRT01P", "AGE", "SEX", "SAFFL"]
adae = adae.select([c for c in _adae_cols if c in adae.columns])
adae.write_parquet(OUT / "adae.parquet")

_te = (adae["TRTEMFL"] == "Y").sum()
print(f"   {adae.shape[0]} records × {adae.shape[1]} variables")
print(f"   Treatment-emergent AEs : {_te} / {adae.shape[0]}")
print(f"   Serious AEs (AESER=Y)  : {(adae['AESER'] == 'Y').sum()}")

# ════════════════════════════════════════════════════════════════════════════
# 8. ADaM ADEX — spec-driven
#    admiral ref: https://pharmaverse.github.io/admiral/articles/adex.html
#    ASEQ and EXDURD derived inline (not yet expressible in from_spec).
# ════════════════════════════════════════════════════════════════════════════
print("\n── ADaM ADEX (spec-driven) ──────────────────────────────────────────────")

_adsl_ex = adsl.select(["USUBJID", "TRTSDT", "TRTEDT", "TRT01P", "AGE", "SAFFL"])
ex_with_adsl = ex.join(_adsl_ex, on="USUBJID", how="left")

adex_s1 = (
    ex_with_adsl.adam
    .from_spec(ADAM_SPEC, dataset="ADEX")
    .to_frame()
)

adex = (
    adex_s1
    .with_columns(
        ((pl.col("AENDT").cast(pl.Date) - pl.col("ASTDT").cast(pl.Date))
         .dt.total_days() + 1).alias("EXDURD"),
        (pl.int_range(pl.len()).over("USUBJID") + 1).cast(pl.Int64).alias("ASEQ"),
        pl.col("TRTSDT"), pl.col("TRTEDT"),
        pl.col("TRT01P"), pl.col("AGE"), pl.col("SAFFL"),
    )
)
_adex_cols = ["STUDYID", "USUBJID", "EXTRT", "EXDOSE", "EXDOSU",
              "ASTDT", "AENDT", "ASEQ", "EXDURD",
              "TRTSDT", "TRTEDT", "TRT01P", "AGE", "SAFFL"]
adex = adex.select([c for c in _adex_cols if c in adex.columns])
adex.write_parquet(OUT / "adex.parquet")

print(f"   {adex.shape[0]} records × {adex.shape[1]} variables")
print(f"   EXDURD range : {adex['EXDURD'].min()} – {adex['EXDURD'].max()} days")

# ── 9. Post-dataset quality checks ───────────────────────────────────────────
print("\n── Quality checks ────────────────────────────────────────────────────────")
sdtm_checker = DatasetChecker(SDTM_SPEC)
adam_checker  = DatasetChecker(ADAM_SPEC)

for checker, df, ds in [
    (sdtm_checker, dm,   "DM"),
    (adam_checker,  adsl, "ADSL"),
    (adam_checker,  advs, "ADVS"),
    (adam_checker,  adae, "ADAE"),
    (adam_checker,  adex, "ADEX"),
]:
    checker.check(df, dataset=ds).print_report()

# ── 10. Generate Define-XML 2.1 ───────────────────────────────────────────────
DefineSpecGenerator(SDTM_SPEC).generate(OUT / "define_sdtm.xml")
DefineSpecGenerator(ADAM_SPEC).generate(OUT / "define_adam.xml")
print(f"\nDefine-XML written to {OUT}/")
print("  Serve with: python -m http.server 8080 --directory outputs/cdiscpilot01")

