# -*- coding: utf-8 -*-
"""
End-to-end CDISCPILOT01 pipeline — spec-driven style.

Every ADaM column derivation is defined in specs/cdiscpilot01/adam/define.yaml
and executed via ``df.adam.from_spec()``.  OCCDS-specific verbs that the spec
cannot yet express (treatment_emergent, worst_flag, seq) are applied inline
immediately after the spec phase.

Shared-verb mixin architecture
-------------------------------
Fleet's ``SharedADaMVerbsMixin`` provides seven verbs — ``source``,
``assigned``, ``derivation``, ``recode``, ``rename``, ``condderivation``,
``whereclauses`` — to **every** ADaM sub-namespace.

For post-spec OCCDS derivations (steps 7–8 below) this means ``derivation``
is available directly on the ``occds`` namespace, so inline calculations
(e.g. EXDURD) and event-level sequence numbers can be chained without
intermediate materialisation or namespace switching.

Datasets produced
-----------------
  SDTM  DM   — demographics (inline; input for ADaM)
  ADaM  ADSL — subject level          (from_spec driven)
  ADaM  ADVS — vital signs BDS        (from_spec, 3-phase staged for ABLFL→BASE→CHG)
  ADaM  ADAE — adverse events OCCDS   (from_spec for source cols; occds for TRTEMFL/ASEQ)
  ADaM  ADEX — exposure BDS           (from_spec driven)

Run from the repo root:
    uv run python examples/cdiscpilot01_spec_driven.py
"""
from pathlib import Path

import polars as pl
import fleet  # noqa: F401 — registers .sdtm / .adam namespace extensions
from fleet import DatasetChecker, DefineSpecGenerator
from specs.cdiscpilot01.sdtm.codelists import SEX, RACE, ETHNIC

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
    dm_raw.sdtm  # type: ignore[attr-defined]  # runtime namespace registered by fleet
    .hardcode_no_ct("STUDYID",  value="CDISCPILOT01")
    .hardcode_no_ct("DOMAIN",   value="DM")
    .assign_no_ct(  "USUBJID",  source="patient_number")
    .assign_no_ct(  "SUBJID",   source="patient_number")
    .derivation(    "SITEID",   expression="pl.col('site_id').cast(pl.String)")
    .assign_no_ct(  "AGE",      source="age")
    .hardcode_no_ct("AGEU",     value="YEARS")
    .assign_ct(     "SEX",      source="sex",    ct_codelist=SEX,
                    ct_mapping={"F": "F", "M": "M"})
    .assign_ct(     "RACE",     source="race",   ct_codelist=RACE,
                    ct_mapping={"WHITE": "WHITE", "BLACK OR AFRICAN AMERICAN": "BLACK OR AFRICAN AMERICAN"})
    .assign_ct(     "ETHNIC",   source="ethnic", ct_codelist=ETHNIC,
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
    .assign_dtc("RFSTDTC", source="first_dose_date",       mode="date")
    .assign_dtc("RFENDTC", source="last_dose_date",        mode="date")
    .assign_dtc("RFICDTC", source="informed_consent_date", mode="date")
    .select(spec=SDTM_SPEC, dataset="DM")
    .write_parquet(OUT / "dm.parquet")
)
print(f"SDTM DM  : {dm.shape[0]} subjects  ·  {dm.shape[1]} columns")

# ── 3. Synthesise SDTM EX (one record per subject) ───────────────────────────
ex = (
    dm_raw.sdtm  # type: ignore[attr-defined]  # runtime namespace registered by fleet
    .hardcode_no_ct("STUDYID",  value="CDISCPILOT01")
    .hardcode_no_ct("DOMAIN",   value="EX")
    .assign_no_ct(  "USUBJID",  source="patient_number")
    .assign_no_ct(  "EXTRT",    source="arm_description")
    .if_then_else(  "EXDOSE",
                    when=[
                        {"condition": pl.col("arm_code") == "Pbo",    "value": 0.0},
                        {"condition": pl.col("arm_code") == "Xan_Lo", "value": 54.0},
                        {"condition": pl.col("arm_code") == "Xan_Hi", "value": 81.0},
                    ])
    .hardcode_no_ct("EXDOSU",   value="mg")
    .assign_no_ct(  "EXSTDTC",  source="first_dose_date")
    .assign_no_ct(  "EXENDTC",  source="last_dose_date")
    .hardcode_no_ct("EXSEQ",    value=1)
    .to_frame()
    .select(["STUDYID", "DOMAIN", "USUBJID", "EXSEQ",
             "EXTRT", "EXDOSE", "EXDOSU", "EXSTDTC", "EXENDTC"])
)

# ── 4. Synthesise SDTM AE ─────────────────────────────────────────────────────
ae = (
    ae_raw.sdtm  # type: ignore[attr-defined]  # runtime namespace registered by fleet
    .hardcode_no_ct("STUDYID",  value="CDISCPILOT01")
    .hardcode_no_ct("DOMAIN",   value="AE")
    .assign_no_ct(  "USUBJID",  source="patient_number")
    .assign_no_ct(  "AETERM",   source="ae_term")
    .assign_no_ct(  "AESTDTC",  source="ae_start_date")
    .assign_no_ct(  "AEENDTC",  source="ae_end_date")
    .assign_no_ct(  "AESEV",    source="ae_severity")
    .assign_no_ct(  "AESER",    source="ae_serious")
    .assign_no_ct(  "AEOUT",    source="ae_outcome")
    .assign_no_ct(  "AEACN",    source="ae_action_taken")
    .assign_no_ct(  "AEREL",    source="ae_relationship")
    .derivation(    "AESEQ",    expression='pl.col("ae_term").cum_count().over("patient_number")')
    .to_frame()
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

_ex_max_dose = (
    ex.group_by("USUBJID")
      .agg(pl.col("EXDOSE").max().alias("_EXDOSE_MAX"))
)

dm_enriched = (
    dm.adam  # type: ignore[attr-defined]  # runtime namespace registered by fleet
    .lookup(dataset=_ex_max_dose, on="USUBJID", how="left")
    .to_frame()
    .adam.adsl  # type: ignore[attr-defined]  # runtime namespace registered by fleet
    # Treatment dates from EX (admiral: derive_vars_merged)
    .first_date("TRTSDT", from_dataset=ex, date_col="EXSTDTC")
    .last_date( "TRTEDT", from_dataset=ex, date_col="EXENDTC")
    # Treatment variables (admiral: mutate TRT01P=ARM, TRT01A=ACTARM)
    .rename("TRT01P", source="ARM")
    .rename("TRT01A", source="ACTARM")
    # Age grouping (admiral: derive_vars_cat)
    .condderivation("AGEGR1",
                    conditions=[
                        {"condition": "pl.col('AGE') < 18",  "value": "<18"},
                        {"condition": "pl.col('AGE') <= 64", "value": "18-64"},
                        {"condition": "pl.col('AGE') > 64",  "value": ">64"},
                    ],
                    else_value="Missing")
    # Population flags (admiral: derive_var_merged_exist_flag)
    .eligibility_flag("SAFFL", criteria='pl.col("_EXDOSE_MAX") > 0')
    .eligibility_flag("ITTFL", criteria='pl.col("ARMCD") != "SCRNFAIL"')
    .to_frame()
    .drop("_EXDOSE_MAX")
)

adsl = (
    dm_enriched.adam  # type: ignore[attr-defined]  # runtime namespace registered by fleet
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
    vs_raw.adam  # type: ignore[attr-defined]  # runtime namespace registered by fleet
    .rename("USUBJID", source="patient_number")
    .lookup(dataset=_trtsdt_map, on="USUBJID", how="left")
    .to_frame()
)

advs = (
    vs_with_trtsdt.adam  # type: ignore[attr-defined]  # runtime namespace registered by fleet
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
ae_with_trt = (
    ae.adam  # type: ignore[attr-defined]  # runtime namespace registered by fleet
    .lookup(dataset=_adsl_trt, on="USUBJID", how="left")
    .to_frame()
)

adae_sourced = (
    ae_with_trt.adam  # type: ignore[attr-defined]  # runtime namespace registered by fleet
    .from_spec(ADAM_SPEC, dataset="ADAE")
    .to_frame()
)

adae = (
    adae_sourced.adam.occds  # type: ignore[attr-defined]  # runtime namespace registered by fleet
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
adae = (
    adae.adam  # type: ignore[attr-defined]  # runtime namespace registered by fleet
    .select(spec=ADAM_SPEC, dataset="ADAE")
    .write_parquet(OUT / "adae.parquet")
)

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
ex_with_adsl = (
    ex.adam  # type: ignore[attr-defined]  # runtime namespace registered by fleet
    .lookup(dataset=_adsl_ex, on="USUBJID", how="left")
    .to_frame()
)

adex_s1 = (
    ex_with_adsl.adam  # type: ignore[attr-defined]  # runtime namespace registered by fleet
    .from_spec(ADAM_SPEC, dataset="ADEX")
    .to_frame()
)

adex = (
    adex_s1.adam.occds      # type: ignore[attr-defined]  # runtime namespace registered by fleet
    # admiral: derive_var_dur (inclusive end-date convention)
    .derivation("EXDURD",              # shared verb on occds via mixin
                expression="(pl.col('AENDT').cast(pl.Date) - pl.col('ASTDT').cast(pl.Date))"
                           ".dt.total_days() + 1")
    # admiral: derive_var_obs_number
    .seq("ASEQ", groups=["USUBJID"])   # occds-specific verb
    .to_frame()
    .with_columns(
        pl.col("TRTSDT"), pl.col("TRTEDT"),
        pl.col("TRT01P"), pl.col("AGE"), pl.col("SAFFL"),
    )
)
adex = (
    adex.adam  # type: ignore[attr-defined]  # runtime namespace registered by fleet
    .select(spec=ADAM_SPEC, dataset="ADEX")
    .write_parquet(OUT / "adex.parquet")
)

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
# enrich_methods=True embeds Fleet verb docstrings into the Origin/MethodDef
# elements so reviewers see the exact computational method (single source of
# truth: docstring -> Define-XML).
DefineSpecGenerator(SDTM_SPEC, enrich_methods=True).generate(OUT / "define_sdtm.xml")
DefineSpecGenerator(ADAM_SPEC, enrich_methods=True).generate(OUT / "define_adam.xml")
print(f"\nDefine-XML written to {OUT}/")
print("  Serve with: python -m http.server 8080 --directory outputs/cdiscpilot01")

