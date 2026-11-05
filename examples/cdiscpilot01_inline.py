"""
Admiral-inspired ADSL pipeline for CDISCPILOT01.

Reproduces the admiral "Creating ADSL" programming flow in Python/Fleet:
  https://pharmaverse.github.io/admiral/articles/adsl.html

Shared-verb mixin architecture
-------------------------------
Fleet's ``SharedADaMVerbsMixin`` provides the shared verbs — ``source``,
``assign``, ``derivation``, ``recode``, ``case_when``, ``whereclauses``,
``pick`` — to **every** ADaM sub-namespace (``adsl``, ``occds``, ``onco``,
``ophtha``, ``peds``, ``vaccine``, ``metabolic``, ``neuro``).

This means the pipeline can stay in a single sub-namespace without
break-and-re-enter chains whenever a shared verb is needed.
For example, ``derivation()`` can now be called directly on ``adsl``
without switching to the base ``adam`` namespace, and ``source()`` /
``assign()`` can be called on ``occds`` so that event-level pipelines
don't need intermediate materialisations.

For OCCDS datasets (ADAE, ADEX) this means the entire derivation +
sequence number chain can run in one ``adam.occds`` pipeline.

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
9.  Last date known alive   LSTALVDT from AE / TRTEDT         (admiral: derive_vars_extreme_event → Fleet: pick())
10. AE counts               NUMAE, NUMSAE                     (admiral: count_vals / custom)

Run from repo root:
    uv run python examples/cdiscpilot01_inline.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl

import fleet  # registers .sdtm / .adam namespace extensions
from examples.cdiscpilot01.sdtm.codelists import ETHNIC, RACE, SEX

OUT = Path("outputs/cdiscpilot01")

# ════════════════════════════════════════════════════════════════════════════
# 1. Raw Data (inline — no external CSV dependencies)
# ════════════════════════════════════════════════════════════════════════════
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

ae_raw = fleet.frame(
    pl.from_repr("""\
┌────────────────┬───────────────────────────┬───────────────┬─────────────┬─────────────┬────────────┬────────────────────────────┬──────────────────┬──────────────────┐
│ patient_number ┆ ae_term                   ┆ ae_start_date ┆ ae_end_date ┆ ae_severity ┆ ae_serious ┆ ae_outcome                 ┆ ae_action_taken  ┆ ae_relationship  │
│ ---            ┆ ---                       ┆ ---           ┆ ---         ┆ ---         ┆ ---        ┆ ---                        ┆ ---              ┆ ---              │
│ str            ┆ str                       ┆ str           ┆ str         ┆ str         ┆ str        ┆ str                        ┆ str              ┆ str              │
╞════════════════╪═══════════════════════════╪═══════════════╪═════════════╪═════════════╪════════════╪════════════════════════════╪══════════════════╪══════════════════╡
│ 01-701-1015    ┆ HEADACHE                  ┆ 2014-01-10    ┆ 2014-01-12  ┆ MILD        ┆ N          ┆ RECOVERED/RESOLVED         ┆ DOSE NOT CHANGED ┆ POSSIBLY RELATED │
│ 01-701-1015    ┆ NAUSEA                    ┆ 2014-02-05    ┆ 2014-02-06  ┆ MODERATE    ┆ N          ┆ RECOVERED/RESOLVED         ┆ DOSE NOT CHANGED ┆ NOT RELATED      │
│ 01-701-1023    ┆ DIZZINESS                 ┆ 2014-01-15    ┆ 2014-01-16  ┆ MILD        ┆ N          ┆ RECOVERED/RESOLVED         ┆ DOSE NOT CHANGED ┆ POSSIBLY RELATED │
│ 01-701-1028    ┆ FATIGUE                   ┆ 2014-02-20    ┆ null        ┆ MODERATE    ┆ N          ┆ NOT RECOVERED/NOT RESOLVED ┆ DOSE NOT CHANGED ┆ PROBABLY RELATED │
│ 01-701-1034    ┆ APPLICATION SITE ERYTHEMA ┆ 2014-01-20    ┆ 2014-01-25  ┆ SEVERE      ┆ Y          ┆ RECOVERED/RESOLVED         ┆ DRUG WITHDRAWN   ┆ RELATED          │
└────────────────┴───────────────────────────┴───────────────┴─────────────┴─────────────┴────────────┴────────────────────────────┴──────────────────┴──────────────────┘
""")
)

print("── 1. Raw data loaded ───────────────────────────────────────────────────")
print(f"   dm_raw : {dm_raw.shape[0]:>3} rows   columns → {dm_raw.columns}")
print(f"   ae_raw : {ae_raw.shape[0]:>3} rows   columns → {ae_raw.columns}")

# ════════════════════════════════════════════════════════════════════════════
# 2a. Build SDTM DM
#     Admiral uses DM as the starting point for ADSL:
#       adsl <- dm %>% select(-DOMAIN) %>% mutate(TRT01P = ARM, ...)
# ════════════════════════════════════════════════════════════════════════════
dm = (
    dm_raw.sdtm.assign("STUDYID", value="CDISCPILOT01")
    .assign("DOMAIN", value="DM")
    .assign("USUBJID", source="patient_number")
    .assign("SUBJID", source="patient_number")
    .derivation("SITEID", expression="pl.col('site_id').cast(pl.String)")
    .assign("AGE", source="age")
    .assign("AGEU", value="YEARS")
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
    .case_when(
        "ARMCD",
        when=[
            {"condition": pl.col("arm_code") == "Pbo", "value": "PBO"},
            {"condition": pl.col("arm_code") == "Xan_Lo", "value": "XAN_LO"},
            {"condition": pl.col("arm_code") == "Xan_Hi", "value": "XAN_HI"},
        ],
        else_="SCRNFAIL",
    )
    .assign("ARM", source="arm_description")
    .assign("ACTARMCD", source="arm_code")
    .assign("ACTARM", source="arm_description")
    .date("RFSTDTC", source="first_dose_date")
    .date("RFENDTC", source="last_dose_date")
    .date("RFICDTC", source="informed_consent_date")
    # Only DM variables, in SDTMIG order: the raw columns are not written to dm.json.
    .keep(
        "STUDYID",
        "DOMAIN",
        "USUBJID",
        "SUBJID",
        "RFSTDTC",
        "RFENDTC",
        "RFICDTC",
        "SITEID",
        "AGE",
        "AGEU",
        "SEX",
        "RACE",
        "ETHNIC",
        "ARMCD",
        "ARM",
        "ACTARMCD",
        "ACTARM",
    )
    .to_frame()
)
print(f"\n── 2a. SDTM DM : {dm.shape[0]} subjects × {dm.shape[1]} variables")

# ── 2a-bis. SUPPDM: Non-Standard Variables (SUPPQUAL for IG ≤3.4) ──────
# nsv() declares qualifier columns with inline metadata. For IG 3.5+ the
# columns stay in DM unchanged. For IG ≤3.4, export_supp() unpivots them
# to the vertical SUPPQUAL structure.
dm_ns = (
    dm_raw.sdtm.assign("STUDYID", value="CDISCPILOT01")
    .assign("DOMAIN", value="DM")
    .assign("USUBJID", source="patient_number")
    .nsv("SAFETY", value="Y", label="Safety Population Flag")
    .nsv("ITT", value="Y", label="Intent to Treat Population Flag")
)
suppdm = dm_ns.export_supp()
print(f"        → SUPPDM: {suppdm.shape[0]} qualifier rows × {suppdm.shape[1]} variables")

# Post-hoc pattern: export_supp with explicit qualifiers dict on existing frame
suppdm_alt = (
    dm.sdtm.export_supp(
        qualifiers={"ARM": {"label": "Description of Planned Arm", "origin": "PROTOCOL"}},
    )
    if "ARM" in dm.columns
    else None
)
if suppdm_alt is not None:
    print(f"        → SUPPDM (post-hoc): {suppdm_alt.shape[0]} rows")

# Export DM as CDISC Dataset-JSON v1.1
from fleet.io import save_dataset_json  # noqa: E402

dm_json = save_dataset_json(dm, OUT / "dm.json", domain="DM", label="Demographics")
print(f"        → Dataset-JSON: {dm_json}")

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
    dm_raw.sdtm.assign("STUDYID", value="CDISCPILOT01")
    .assign("DOMAIN", value="EX")
    .assign("USUBJID", source="patient_number")
    .assign("EXTRT", source="arm_description")
    .case_when(
        "EXDOSE",
        when=[
            {"condition": pl.col("arm_code") == "Pbo", "value": 0.0},
            {"condition": pl.col("arm_code") == "Xan_Lo", "value": 54.0},
            {"condition": pl.col("arm_code") == "Xan_Hi", "value": 81.0},
        ],
    )
    .assign("EXDOSU", value="mg")
    .assign("EXSTDTC", source="first_dose_date")
    .assign("EXENDTC", source="last_dose_date")
    .assign("EXSEQ", value=1)
    .to_frame()
    .select(
        ["STUDYID", "DOMAIN", "USUBJID", "EXSEQ", "EXTRT", "EXDOSE", "EXDOSU", "EXSTDTC", "EXENDTC"]
    )
)
print(
    f"── 2b. SDTM EX : {ex.shape[0]} records  × {ex.shape[1]} variables (synthesised from dm_raw)"
)

# ════════════════════════════════════════════════════════════════════════════
# 2c. Synthesise SDTM DS (Disposition)
#     Admiral uses DS for EOSDT, EOSSTT, DCSREAS, and RANDDT.
#     Record types created:
#       DSCAT = "PROTOCOL MILESTONE"  / DSDECOD = "RANDOMIZED"  (at first dose)
#       DSCAT = "DISPOSITION EVENT"   / DSDECOD = "COMPLETED"   (at last dose)
# ════════════════════════════════════════════════════════════════════════════
_ds_cols = ["STUDYID", "DOMAIN", "USUBJID", "DSSEQ", "DSCAT", "DSTERM", "DSDECOD", "DSSTDTC"]

ds_completed = (
    dm_raw.sdtm.assign("STUDYID", value="CDISCPILOT01")
    .assign("DOMAIN", value="DS")
    .assign("USUBJID", source="patient_number")
    .assign("DSSEQ", value=1)
    .assign("DSCAT", value="DISPOSITION EVENT")
    .assign("DSTERM", value="PROTOCOL COMPLETED")
    .assign("DSDECOD", value="COMPLETED")
    .assign("DSSTDTC", source="last_dose_date")
    .to_frame()
    .select(_ds_cols)
)

ds_randomized = (
    dm_raw.sdtm.assign("STUDYID", value="CDISCPILOT01")
    .assign("DOMAIN", value="DS")
    .assign("USUBJID", source="patient_number")
    .assign("DSSEQ", value=2)
    .assign("DSCAT", value="PROTOCOL MILESTONE")
    .assign("DSTERM", value="RANDOMIZED")
    .assign("DSDECOD", value="RANDOMIZED")
    .assign("DSSTDTC", source="first_dose_date")
    .to_frame()
    .select(_ds_cols)
)

ds = pl.concat([ds_completed, ds_randomized]).sort(["USUBJID", "DSSEQ"])
print(
    f"── 2c. SDTM DS : {ds.shape[0]} records  × {ds.shape[1]} variables (synthesised from dm_raw)"
)

# ════════════════════════════════════════════════════════════════════════════
# 2d. Build SDTM AE (Adverse Events) from ae_raw
# ════════════════════════════════════════════════════════════════════════════
ae = (
    ae_raw.sdtm.assign("STUDYID", value="CDISCPILOT01")
    .assign("DOMAIN", value="AE")
    .assign("USUBJID", source="patient_number")
    .assign("AETERM", source="ae_term")
    .assign("AESTDTC", source="ae_start_date")
    .assign("AEENDTC", source="ae_end_date")
    .assign("AESEV", source="ae_severity")
    .assign("AESER", source="ae_serious")
    .assign("AEOUT", source="ae_outcome")
    .assign("AEACN", source="ae_action_taken")
    .assign("AEREL", source="ae_relationship")
    # AESEQ: running count within each subject
    .derivation("AESEQ", expression='pl.col("ae_term").cum_count().over("patient_number")')
    # Pin DM for cross-domain study day derivation
    .pin("DM", dm)
    .study_day("AESTDY", date_col="AESTDTC")
    .trail()  # print the origin of every derived variable before materialising
    .to_frame()
    .select(
        [
            "STUDYID",
            "DOMAIN",
            "USUBJID",
            "AESEQ",
            "AETERM",
            "AESTDTC",
            "AEENDTC",
            "AESTDY",
            "AESEV",
            "AESER",
            "AEOUT",
            "AEACN",
            "AEREL",
        ]
    )
)
print(f"── 2d. SDTM AE : {ae.shape[0]} records  × {ae.shape[1]} variables (with AESTDY via .pin())")

# ════════════════════════════════════════════════════════════════════════════
# 3–5. Build ADSL base + Treatment Variables + Treatment Dates/Duration
#      Admiral step 2 → TRT01P = ARM, TRT01A = ACTARM
#      Admiral step 3 → TRTSDT, TRTEDT from EX (derive_vars_merged, mode=first/last)
#      Admiral step 4 → TRTDURD (derive_var_trtdurd)
# ════════════════════════════════════════════════════════════════════════════
print("\n── 3–5. ADSL base + treatment dates ────────────────────────────────────")

adsl = (
    dm.adam.adsl.source(  # ── demographics from DM ──────────────────────────────────────────────
        "STUDYID"
    )
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
    .assign("TRT01P", source="ARM")
    .assign("TRT01A", source="ACTARM")
    # ── study dates from DM ───────────────────────────────────────────────
    .source("RFSTDTC")
    .source("RFENDTC")
    .source("RFICDTC")
    # ── treatment start date from EX (admiral: derive_vars_merged, mode="first") ──
    # first_date / last_date materialise internally — no chain break needed
    .first_date("TRTSDT", from_dataset=ex, date_col="EXSTDTC")
    # ── treatment end date from EX (admiral: derive_vars_merged, mode="last") ──
    .last_date("TRTEDT", from_dataset=ex, date_col="EXENDTC")
    # ── treatment duration (admiral: derive_var_trtdurd → TRTEDT - TRTSDT + 1) ──
    .duration("TRTDURD", start="TRTSDT", end="TRTEDT")
    .to_frame()
)

print(f"   {adsl.shape[0]} subjects × {adsl.shape[1]} variables")
print(
    f"   Sample: TRTSDT={adsl['TRTSDT'][0]!r}  TRTEDT={adsl['TRTEDT'][0]!r}  TRTDURD={adsl['TRTDURD'][0]}"
)

# ════════════════════════════════════════════════════════════════════════════
# 6. Disposition variables from DS
#    Admiral: derive_vars_merged(ds_ext) for each variable
#      EOSDT   — date of DISPOSITION EVENT
#      EOSSTT  — COMPLETED | DISCONTINUED | ONGOING (missing)
#      DCSREAS — discontinuation reason (DSDECOD when not COMPLETED/SCREEN FAILURE)
#      RANDDT  — date of RANDOMIZED milestone
# ════════════════════════════════════════════════════════════════════════════
print("\n── 6. Disposition variables ─────────────────────────────────────────────")

# Pre-filter DS for disposition status/reason derivations
_ds_disp = ds.filter(pl.col("DSCAT") == "DISPOSITION EVENT").select(
    ["USUBJID", "DSDECOD", "DSTERM"]
)

adsl = (
    adsl.adam.adsl.last_date(  # EOSDT: latest date of DISPOSITION EVENT (admiral: derive_vars_merged)
        "EOSDT", from_dataset=ds, date_col="DSSTDTC", where='pl.col("DSCAT") == "DISPOSITION EVENT"'
    )
    # RANDDT: date of RANDOMIZED protocol milestone (admiral: derive_vars_merged)
    .first_date(
        "RANDDT", from_dataset=ds, date_col="DSSTDTC", where='pl.col("DSDECOD") == "RANDOMIZED"'
    )
    .to_frame()
    # Bring in DSDECOD/DSTERM from DS for status/reason derivations
    .adam.merge(
        dataset=_ds_disp, on="USUBJID", how="left"
    )  # EOSSTT: map disposition decode to study status (admiral: format_eosstt)
    .case_when(
        "EOSSTT",
        when=[
            {"condition": 'pl.col("DSDECOD").is_null()', "value": None},
            {"condition": 'pl.col("DSDECOD") == "COMPLETED"', "value": "COMPLETED"},
            {"condition": 'pl.col("DSDECOD") == "SCREEN FAILURE"', "value": None},
        ],
        else_="DISCONTINUED",
    )
    # DCSREAS: discontinuation reason (admiral: derive_vars_merged)
    .derivation(
        "DCSREAS",
        expression='pl.when(~pl.col("DSDECOD").is_in(["COMPLETED", "SCREEN FAILURE"]) '
        '& pl.col("DSDECOD").is_not_null())'
        '.then(pl.col("DSDECOD")).otherwise(None)',
    )
    # DCSREASP: detailed reason term
    .derivation(
        "DCSREASP",
        expression='pl.when(~pl.col("DSDECOD").is_in(["COMPLETED", "SCREEN FAILURE"]) '
        '& pl.col("DSDECOD").is_not_null())'
        '.then(pl.col("DSTERM")).otherwise(None)',
    )
    .to_frame()
    .drop(["DSDECOD", "DSTERM"])
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
    fleet.frame(adsl)
    .adam.adsl.case_when(
        "AGEGR1",
        when=[
            {"condition": "pl.col('AGE') < 18", "value": "<18"},
            {"condition": "pl.col('AGE') <= 64", "value": "18-64"},
            {"condition": "pl.col('AGE') > 64", "value": ">64"},
        ],
        else_="Missing",
    )
    .to_frame()
)

_agegr = adsl.group_by("AGEGR1").agg(pl.len().alias("n")).sort("AGEGR1")
print(f"   AGEGR1 distribution: {_agegr.to_dicts()}")

# ════════════════════════════════════════════════════════════════════════════
# 8. Safety Population Flag (SAFFL)
#    Admiral: derive_var_merged_exist_flag(ex, condition = EXDOSE > 0 | PLACEBO)
#    This is the admiral template condition; the SAP decides the population.
#    A population flag is never blank (ADaMIG 1.3): non-members get "N".
#    We also derive ITTFL (intent-to-treat) = same population in this study.
# ════════════════════════════════════════════════════════════════════════════
print("\n── 8. Population flags ──────────────────────────────────────────────────")

_treated = (pl.col("EXDOSE") > 0) | (
    (pl.col("EXDOSE") == 0) & pl.col("EXTRT").str.to_uppercase().str.contains("PLACEBO")
)

adsl = (
    adsl.adam.adsl.flag_exists(  # admiral: derive_var_merged_exist_flag
        "SAFFL", from_dataset=ex, on=["USUBJID"], source_filter=_treated, false_value="N"
    )
    # ITTFL: all randomised subjects (ARMCD not SCRNFAIL)
    .flag("ITTFL", criteria='pl.col("ARMCD") != "SCRNFAIL"', false_value="N")
    .to_frame()
)

print(f"   SAFFL : {adsl['SAFFL'].value_counts().to_dicts()}")
print(f"   ITTFL : {adsl['ITTFL'].value_counts().to_dicts()}")
assert (adsl["SAFFL"] == "Y").sum() == adsl.height, "every pilot subject took a dose"

# ════════════════════════════════════════════════════════════════════════════
# 9. Last Date Known Alive (LSTALVDT)
#    Admiral: derive_vars_extreme_event(ae, lb, adsl; order=last)
#    Fleet: pick() — the latest date over all sources.  Within each event
#    the latest record is kept; then the top-level order=["LSTALVDT"],
#    mode="last" makes the events compete on the date, as admiral does.
#    A tie on the date goes to the first listed event.
#
#    Sources:
#      a) AE end dates   (AEENDTC)  — most clinically recent contact
#      b) AE start dates (AESTDTC)  — if AE end is missing
#      c) Treatment end  (TRTEDT)   — fallback from ADSL itself
# ════════════════════════════════════════════════════════════════════════════
print("\n── 9. Last date known alive (LSTALVDT) — via pick() ─────────────────────")

adsl = (
    fleet.frame(adsl)
    .adam.adsl.pick(
        "LSTALVDT",
        events=[
            {
                "when": pl.col("AEENDTC").is_not_null(),
                "set": {"LSTALVDT": "AEENDTC"},
                "source": ae,
                "label": "AE end date (latest contact)",
            },
            {
                "when": pl.col("AESTDTC").is_not_null(),
                "set": {"LSTALVDT": "AESTDTC"},
                "source": ae,
                "label": "AE start date (fallback)",
            },
            {
                "when": pl.col("TRTEDT").is_not_null(),
                "set": {"LSTALVDT": "TRTEDT"},
                "label": "Treatment end (last resort)",
            },
        ],
        by=["USUBJID"],
        order=["LSTALVDT"],
        mode="last",
    )
    .to_frame()
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
    adsl.adam.adsl.count_events("NUMAE", from_dataset=ae)
    .count_events("NUMSAE", from_dataset=ae, where='pl.col("AESER") == "Y"')
    .to_frame()
)

print(f"   Subjects with ≥1 AE  : {(adsl['NUMAE'] > 0).sum()}")
print(f"   Subjects with ≥1 SAE : {(adsl['NUMSAE'] > 0).sum()}")

# ════════════════════════════════════════════════════════════════════════════
# 11. Final column selection and output
#     Mirrors the admiral ADSL variable set from the vignette.
# ════════════════════════════════════════════════════════════════════════════
FINAL_COLS = [
    # Identifiers
    "STUDYID",
    "USUBJID",
    "SUBJID",
    "SITEID",
    # Demographics
    "AGE",
    "AGEU",
    "AGEGR1",
    "SEX",
    "RACE",
    "ETHNIC",
    # Treatment assignment
    "ARM",
    "ARMCD",
    "ACTARM",
    "ACTARMCD",
    # Planned / actual treatment labels (admiral: TRT01P, TRT01A)
    "TRT01P",
    "TRT01A",
    # Study-level dates from DM
    "RFSTDTC",
    "RFENDTC",
    "RFICDTC",
    # Randomisation date (admiral: RANDDT from DS)
    "RANDDT",
    # Treatment dates & duration (admiral: TRTSDT, TRTEDT, TRTDURD from EX)
    "TRTSDT",
    "TRTEDT",
    "TRTDURD",
    # Disposition (admiral: EOSDT, EOSSTT, DCSREAS, DCSREASP from DS)
    "EOSDT",
    "EOSSTT",
    "DCSREAS",
    "DCSREASP",
    # Survival
    "LSTALVDT",
    # Population flags (admiral: SAFFL, ITTFL)
    "SAFFL",
    "ITTFL",
    # AE summary counts
    "NUMAE",
    "NUMSAE",
]

adsl_final = adsl.select(FINAL_COLS)

print("\n── 11. Final ADSL ───────────────────────────────────────────────────────")
print(f"   Shape   : {adsl_final.shape[0]} subjects × {adsl_final.shape[1]} variables")
print("\n   First 5 rows (key columns):")
print(
    adsl_final.select(
        [
            "USUBJID",
            "AGE",
            "AGEGR1",
            "SEX",
            "TRT01P",
            "TRTSDT",
            "TRTEDT",
            "TRTDURD",
            "EOSSTT",
            "SAFFL",
            "NUMAE",
        ]
    ).head(5)
)

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
print(
    f"   Age range                        : {adsl_final['AGE'].min()} – {adsl_final['AGE'].max()} years"
)
print(
    f"   AGEGR1 distribution              : {adsl_final['AGEGR1'].value_counts().sort('AGEGR1').to_dicts()}"
)
print(
    f"   EOSSTT distribution              : {adsl_final['EOSSTT'].value_counts().sort('EOSSTT').to_dicts()}"
)
print(
    f"   SAFFL = Y                        : {(adsl_final['SAFFL'] == 'Y').sum()} / {adsl_final.shape[0]}"
)
print(
    f"   ITTFL = Y                        : {(adsl_final['ITTFL'] == 'Y').sum()} / {adsl_final.shape[0]}"
)
print(
    f"   TRTDURD range                    : {adsl_final['TRTDURD'].min()} – {adsl_final['TRTDURD'].max()} days"
)
print(f"   Subjects with ≥1 AE              : {(adsl_final['NUMAE'] > 0).sum()}")
print(f"   Subjects with ≥1 serious AE      : {(adsl_final['NUMSAE'] > 0).sum()}")
print(
    f"   LSTALVDT range                   : {adsl_final['LSTALVDT'].min()} → {adsl_final['LSTALVDT'].max()}"
)

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

vs_raw = fleet.frame(
    pl.from_repr("""\
┌────────────────┬─────────────┬──────────┬────────┬─────────┬──────────┬────────────┬──────┐
│ patient_number ┆ site_number ┆ vstestcd ┆ vstest ┆ vsorres ┆ vsorresu ┆ vsdtc      ┆ vsdy │
│ ---            ┆ ---         ┆ ---      ┆ ---    ┆ ---     ┆ ---      ┆ ---        ┆ ---  │
│ str            ┆ i64         ┆ str      ┆ str    ┆ f64     ┆ str      ┆ str        ┆ i64  │
╞════════════════╪═════════════╪══════════╪════════╪═════════╪══════════╪════════════╪══════╡
│ 01-701-1015    ┆ 701         ┆ HEIGHT   ┆ Height ┆ 155.5   ┆ cm       ┆ 2014-01-01 ┆ -1   │
│ 01-701-1023    ┆ 701         ┆ HEIGHT   ┆ Height ┆ 168.1   ┆ cm       ┆ 2014-01-01 ┆ -1   │
│ 01-701-1028    ┆ 701         ┆ HEIGHT   ┆ Height ┆ 178.0   ┆ cm       ┆ 2014-01-01 ┆ -1   │
│ 01-701-1034    ┆ 701         ┆ HEIGHT   ┆ Height ┆ 170.2   ┆ cm       ┆ 2014-01-01 ┆ -1   │
│ 01-701-1047    ┆ 701         ┆ HEIGHT   ┆ Height ┆ 166.2   ┆ cm       ┆ 2014-01-01 ┆ -1   │
└────────────────┴─────────────┴──────────┴────────┴─────────┴──────────┴────────────┴──────┘
""")
)

_trtsdt_map = adsl_final.select(["USUBJID", "TRTSDT"])

advs = (
    vs_raw.adam.assign("STUDYID", value="CDISCPILOT01")
    .assign("USUBJID", source="patient_number")
    .assign("PARAMCD", source="vstestcd")
    .assign("PARAM", source="vstest")
    .assign("AVALU", source="vsorresu")
    .derivation("AVAL", expression="pl.col('vsorres').cast(pl.Float64, strict=False)")
    .date("ADT", source="vsdtc")
    .merge(dataset=_trtsdt_map, on="USUBJID", how="left")
    .duration("ADY", start="TRTSDT", end="ADT")
    # admiral: flag_variables — last pre-dose visit (vsdy ≤ 0)
    .flag("ABLFL", criteria='pl.col("vsdy") <= 0')
    .to_frame()  # materialise — ABLFL must exist before baseline() window fn
    .adam.baseline(  # admiral: derive_var_base
        "BASE", aval="AVAL", baseline_flag="ABLFL", by=["USUBJID", "PARAMCD"]
    )
    .to_frame()  # materialise — BASE must exist before chg()/pchg()
    .adam.chg("CHG", aval="AVAL", base="BASE")  # admiral: derive_var_chg
    .pchg("PCHG", aval="AVAL", base="BASE")
    # admiral: restrict_derivation + derive_var_extreme_flag
    # ANL01FL — last valid assessment per subject/parameter (non-null AVAL)
    .flag(
        "ANL01FL",
        criteria="last",
        order_by="ADT",
        by=["USUBJID", "PARAMCD"],
        where='~pl.col("AVAL").is_null()',
    )
    .to_frame()
)

ADVS_COLS = [
    "STUDYID",
    "USUBJID",
    "PARAMCD",
    "PARAM",
    "AVAL",
    "AVALU",
    "ADT",
    "ADY",
    "ABLFL",
    "BASE",
    "CHG",
    "PCHG",
    "ANL01FL",
    "TRTSDT",
]
advs_final = advs.select([c for c in ADVS_COLS if c in advs.columns])
advs_final.write_parquet(OUT / "advs_admiral.parquet")

print(f"   Shape      : {advs_final.shape[0]} records × {advs_final.shape[1]} variables")
print(f"   Parameters : {sorted(advs_final['PARAMCD'].unique().to_list())}")
print(f"   ABLFL = Y  : {(advs_final['ABLFL'] == 'Y').sum()} records")
print(f"   ANL01FL = Y: {(advs_final['ANL01FL'] == 'Y').sum()} records")
print(
    f"   CHG range  : {advs_final['CHG'].drop_nulls().min():.2f} – {advs_final['CHG'].drop_nulls().max():.2f}"
)

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
ae_with_trt = fleet.frame(ae.join(_adsl_trt, on="USUBJID", how="left"))

adae = (
    ae_with_trt.adam.assign("STUDYID", value="CDISCPILOT01")
    .source("USUBJID")
    .source("AETERM")
    .source("AESTDTC")
    .source("AEENDTC")
    .source("AESEV")
    .source("AESER")
    .source("AEREL")
    .source("AEOUT")
    .source("AEACN")
    # admiral: derive_vars_dt (ad_adae.R: partial start to the first day but not
    # before TRTSDT, partial end to the last day; the SAP decides the rule)
    .date("ASTDT", source="AESTDTC", min_date="TRTSDT")
    .date("AENDT", source="AEENDTC", impute="last")
    .duration("ADY", start="TRTSDT", end="ASTDT")
    .to_frame()
    .adam.occds.treatment_emergent(  # admiral: derive_var_trtemfl
        "TRTEMFL",
        start_date="ASTDT",
        end_date="AENDT",
        trtsdt="TRTSDT",
        trtedt="TRTEDT",
        end_window=0,  # the SAP decides the window after the last dose
    )
    # admiral: slice_derivation (worst severity per subject × AE term)
    .recode("AESEVN", source="AESEV", recode_map={"MILD": 1, "MODERATE": 2, "SEVERE": 3})
    .flag(
        "ANL01FL",
        criteria="max",
        value_col="AESEVN",
        by=["USUBJID", "AETERM"],
    )
    # admiral: derive_var_obs_number
    .seq("ASEQ", by=["USUBJID"])
    .to_frame()
)

ADAE_COLS = [
    "STUDYID",
    "USUBJID",
    "ASEQ",
    "AETERM",
    "AESTDTC",
    "AEENDTC",
    "AESEV",
    "AESER",
    "AEREL",
    "AEOUT",
    "AEACN",
    "ASTDT",
    "AENDT",
    "ADY",
    "TRTEMFL",
    "ANL01FL",
    "TRTSDT",
    "TRTEDT",
    "TRT01P",
    "SAFFL",
]
adae_final = adae.select([c for c in ADAE_COLS if c in adae.columns])
adae_final.write_parquet(OUT / "adae_admiral.parquet")

_te = (adae_final["TRTEMFL"] == "Y").sum()
print(
    f"   Shape                  : {adae_final.shape[0]} records × {adae_final.shape[1]} variables"
)
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
    fleet.frame(ex.join(_adsl_ex, on="USUBJID", how="left"))
    .adam.occds.assign("STUDYID", value="CDISCPILOT01")  # shared verb (mixin)
    .source("USUBJID")  # shared verb (mixin)
    .source("EXTRT")  # shared verb (mixin)
    .source("EXDOSE")  # shared verb (mixin)
    .source("EXDOSU")  # shared verb (mixin)
    # admiral: derive_vars_dt
    .date("ASTDT", source="EXSTDTC")
    .date("AENDT", source="EXENDTC")
    # admiral: derive_var_dur (inclusive end-date convention)
    .derivation(
        "EXDURD",  # shared verb (mixin)
        expression="(pl.col('AENDT') - pl.col('ASTDT')).dt.total_days() + 1",
    )
    # admiral: derive_var_obs_number
    .seq("ASEQ", by=["USUBJID"])  # occds-specific verb
    .to_frame()
)

ADEX_COLS = [
    "STUDYID",
    "USUBJID",
    "ASEQ",
    "EXTRT",
    "EXDOSE",
    "EXDOSU",
    "ASTDT",
    "AENDT",
    "EXDURD",
    "TRTSDT",
    "TRTEDT",
    "TRT01P",
    "SAFFL",
]
adex_final = adex.select([c for c in ADEX_COLS if c in adex.columns])
adex_final.write_parquet(OUT / "adex_admiral.parquet")

print(f"   Shape        : {adex_final.shape[0]} records × {adex_final.shape[1]} variables")
print(f"   Treatments   : {adex_final['EXTRT'].unique().to_list()}")
print(f"   EXDURD range : {adex_final['EXDURD'].min()} – {adex_final['EXDURD'].max()} days")

# ════════════════════════════════════════════════════════════════════════════
# 16. Cross-dataset summary
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 16. Cross-dataset summary ════════════════════════════════════════════")
print(
    f"   ADSL : {adsl_final.shape[0]} subjects × {adsl_final.shape[1]} variables  → adsl_admiral.parquet"
)
print(
    f"   ADVS : {advs_final.shape[0]} records  × {advs_final.shape[1]} variables  → advs_admiral.parquet"
)
print(
    f"   ADAE : {adae_final.shape[0]} records  × {adae_final.shape[1]} variables  → adae_admiral.parquet"
)
print(
    f"   ADEX : {adex_final.shape[0]} records  × {adex_final.shape[1]} variables  → adex_admiral.parquet"
)
print(f"\n   All outputs in {OUT}/")
