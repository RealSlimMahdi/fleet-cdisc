"""
Admiral-inspired ADPC / ADNCA and ADPPK pipeline for CDISCPILOT01.

Reproduces the admiral "Creating a PK NCA or Population PK ADaM" programming
flow in Python / Fleet:
  https://github.com/pharmaverse/admiral/blob/main/vignettes/pk_adnca.Rmd

Fleet<>admiral verb mapping
-----------------------------
The table below shows how each admiral derivation step maps to a Fleet verb.

| admiral step / function             | Fleet verb                        |
|-------------------------------------|-----------------------------------|
| derive_vars_dtm / derive_vars_dy    | pk.actual_time()                  |
| derive_var_nfrlt                    | pk.nominal_time()                 |
| mutate(EVID = 0/1)                  | pk.evid()                         |
| derive_vars_duration (AFRLT/ARRLT)  | pk.actual_time()                  |
| MRRLT = if_else(ARRLT<0, 0, ARRLT) | pk.mrrlt()                        |
| BLQFL = case_when(PCSTRESC=="<BLQ") | pk.blq_flag()                    |
| BLQFN (numeric 0/1)                 | pk.blqfn()                        |
| AVAL = ALLOQ * .5                   | pk.blq_impute(method="half_lloq") |
| AVALCAT1 = if_else(BLQ, "<BLQ", …) | pk.avalcat()                      |
| log(DV)                             | pk.log_conc()                     |
| MDV                                 | pk.mdv()                          |
| AMT                                 | pk.amt()                          |
| CMT                                 | pk.cmt()                          |
| derive_var_obs_number (ASEQ)        | pk.seq()                          |
| derive_vars_merged (ADSL join)      | pk.merge_adsl()                   |
| dose_normalized                     | pk.dose_normalized()              |
| ANL01FL / ANL02FL                   | pk.anl_flag()                     |

Workflow
---------
PART 1 — ADPC (NCA):
  1.  Read raw PC, DM, VS data
  2.  Build minimal ADSL from DM
  3.  Build VS baselines (height)
  4.  Clean PC → cast PCSTRESN (BLQ "." → null)
  5.  Merge ADSL early variables (TRT01P, TRTSDT, DOSEP)
  6.  Derive EVID = 0 (concentration records)
  7.  Derive NFRLT / NRRLT from PCTPTNUM  (nominal relative times)
  8.  Derive AFRLT / ARRLT from datetimes  (actual relative times)
  9.  Derive MRRLT                         (clip pre-dose to 0)
  10. Derive BLQFL / BLQFN                 (BLQ flags)
  11. Derive AVAL via BLQ imputation       (half-LLOQ)
  12. Derive AVALCAT1                      (listing-ready category)
  13. Derive ATPT, ATPTREF, BASETYPE, ABLFL (analysis identifiers)
  14. Derive DOSEA (actual dose) from treatment
  15. Derive DTYPE = "HALFLLOQ" for BLQ records
  16. Derive ANL01FL / ANL02FL             (analysis flags)
  17. Derive ASEQ
  18. Merge HTBL from VS
  19. Merge remaining ADSL variables

PART 2 — ADPPK (Population PK):
  1.  Start from the cleaned PC frame
  2.  Derive EVID = 0 (concentration rows) then stack EX (EVID=1) rows
  3.  Derive DV / DVL (log-concentration)
  4.  Derive MDV, AMT, CMT
  5.  Derive AFRLT, APRLT (actual relative times from first / previous dose)
  6.  Derive NFRLT, NPRLT (nominal relative times)
  7.  Derive BLQFL / BLQFN
  8.  Derive numeric covariates (SEXN, ARMN)
  9.  Derive ASEQ

Run from repo root:
    uv run python examples/adnca_example.py
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

import fleet  # registers .sdtm / .adam namespace extensions

OUT = Path("outputs/cdiscpilot01")
OUT.mkdir(parents=True, exist_ok=True)

# ════════════════════════════════════════════════════════════════════════════
# 1. Raw Data (inline — no external CSV dependencies)
# ════════════════════════════════════════════════════════════════════════════
pc_raw = fleet.frame(
    pl.from_repr("""\
┌─────────────┬───────┬──────────┬────────┬──────────┬────────┬─────────────────────┬──────────┬──────────────────┬─────────┬──────────┬──────────┬──────────┬────────┬────────┬────────┬─────────────────────┐
│ USUBJID     ┆ PCSEQ ┆ VISITNUM ┆ VISIT  ┆ PCTESTCD ┆ PCTEST ┆ PCDTC               ┆ PCTPTNUM ┆ PCTPT            ┆ PCORRES ┆ PCSTRESC ┆ PCSTRESN ┆ PCSTRESU ┆ PCSPEC ┆ PCBLFL ┆ PCLLOQ ┆ EXSTDTC             │
│ ---         ┆ ---   ┆ ---      ┆ ---    ┆ ---      ┆ ---    ┆ ---                 ┆ ---      ┆ ---              ┆ ---     ┆ ---      ┆ ---      ┆ ---      ┆ ---    ┆ ---    ┆ ---    ┆ ---                 │
│ str         ┆ i64   ┆ i64      ┆ str    ┆ str      ┆ str    ┆ str                 ┆ f64      ┆ str              ┆ str     ┆ str      ┆ str      ┆ str      ┆ str    ┆ str    ┆ f64    ┆ str                 │
╞═════════════╪═══════╪══════════╪════════╪══════════╪════════╪═════════════════════╪══════════╪══════════════════╪═════════╪══════════╪══════════╪══════════╪════════╪════════╪════════╪═════════════════════╡
│ 01-701-1015 ┆ 1     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-01-17T08:00:00 ┆ 0.0      ┆ PRE-DOSE         ┆ BLQ     ┆ BLQ      ┆ .        ┆ ng/mL    ┆ PLASMA ┆ Y      ┆ 1.0    ┆ 2014-01-17T08:00:00 │
│ 01-701-1015 ┆ 2     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-01-17T08:30:00 ┆ 0.5      ┆ 30 MIN POST-DOSE ┆ 5.43    ┆ 5.43     ┆ 5.43     ┆ ng/mL    ┆ PLASMA ┆ null   ┆ 1.0    ┆ 2014-01-17T08:00:00 │
│ 01-701-1015 ┆ 3     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-01-17T09:00:00 ┆ 1.0      ┆ 1 HR POST-DOSE   ┆ 10.27   ┆ 10.27    ┆ 10.27    ┆ ng/mL    ┆ PLASMA ┆ null   ┆ 1.0    ┆ 2014-01-17T08:00:00 │
│ 01-701-1015 ┆ 4     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-01-17T10:00:00 ┆ 2.0      ┆ 2 HR POST-DOSE   ┆ 18.64   ┆ 18.64    ┆ 18.64    ┆ ng/mL    ┆ PLASMA ┆ null   ┆ 1.0    ┆ 2014-01-17T08:00:00 │
│ 01-701-1015 ┆ 5     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-01-17T12:00:00 ┆ 4.0      ┆ 4 HR POST-DOSE   ┆ 22.31   ┆ 22.31    ┆ 22.31    ┆ ng/mL    ┆ PLASMA ┆ null   ┆ 1.0    ┆ 2014-01-17T08:00:00 │
│ 01-701-1015 ┆ 6     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-01-17T16:00:00 ┆ 8.0      ┆ 8 HR POST-DOSE   ┆ 14.88   ┆ 14.88    ┆ 14.88    ┆ ng/mL    ┆ PLASMA ┆ null   ┆ 1.0    ┆ 2014-01-17T08:00:00 │
│ 01-701-1015 ┆ 7     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-01-17T20:00:00 ┆ 12.0     ┆ 12 HR POST-DOSE  ┆ 8.12    ┆ 8.12     ┆ 8.12     ┆ ng/mL    ┆ PLASMA ┆ null   ┆ 1.0    ┆ 2014-01-17T08:00:00 │
│ 01-701-1015 ┆ 8     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-01-18T08:00:00 ┆ 24.0     ┆ 24 HR POST-DOSE  ┆ 0.73    ┆ 0.73     ┆ 0.73     ┆ ng/mL    ┆ PLASMA ┆ null   ┆ 1.0    ┆ 2014-01-17T08:00:00 │
│ 01-701-1023 ┆ 1     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-02-10T08:00:00 ┆ 0.0      ┆ PRE-DOSE         ┆ BLQ     ┆ BLQ      ┆ .        ┆ ng/mL    ┆ PLASMA ┆ Y      ┆ 1.0    ┆ 2014-02-10T08:00:00 │
│ 01-701-1023 ┆ 2     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-02-10T08:30:00 ┆ 0.5      ┆ 30 MIN POST-DOSE ┆ 4.89    ┆ 4.89     ┆ 4.89     ┆ ng/mL    ┆ PLASMA ┆ null   ┆ 1.0    ┆ 2014-02-10T08:00:00 │
│ 01-701-1023 ┆ 3     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-02-10T09:00:00 ┆ 1.0      ┆ 1 HR POST-DOSE   ┆ 9.56    ┆ 9.56     ┆ 9.56     ┆ ng/mL    ┆ PLASMA ┆ null   ┆ 1.0    ┆ 2014-02-10T08:00:00 │
│ 01-701-1023 ┆ 4     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-02-10T10:00:00 ┆ 2.0      ┆ 2 HR POST-DOSE   ┆ 17.82   ┆ 17.82    ┆ 17.82    ┆ ng/mL    ┆ PLASMA ┆ null   ┆ 1.0    ┆ 2014-02-10T08:00:00 │
│ 01-701-1023 ┆ 5     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-02-10T12:00:00 ┆ 4.0      ┆ 4 HR POST-DOSE   ┆ 20.54   ┆ 20.54    ┆ 20.54    ┆ ng/mL    ┆ PLASMA ┆ null   ┆ 1.0    ┆ 2014-02-10T08:00:00 │
│ 01-701-1023 ┆ 6     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-02-10T16:00:00 ┆ 8.0      ┆ 8 HR POST-DOSE   ┆ 13.40   ┆ 13.40    ┆ 13.40    ┆ ng/mL    ┆ PLASMA ┆ null   ┆ 1.0    ┆ 2014-02-10T08:00:00 │
│ 01-701-1023 ┆ 7     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-02-10T20:00:00 ┆ 12.0     ┆ 12 HR POST-DOSE  ┆ 7.23    ┆ 7.23     ┆ 7.23     ┆ ng/mL    ┆ PLASMA ┆ null   ┆ 1.0    ┆ 2014-02-10T08:00:00 │
│ 01-701-1023 ┆ 8     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-02-11T08:00:00 ┆ 24.0     ┆ 24 HR POST-DOSE  ┆ BLQ     ┆ BLQ      ┆ .        ┆ ng/mL    ┆ PLASMA ┆ null   ┆ 1.0    ┆ 2014-02-10T08:00:00 │
│ 01-701-1028 ┆ 1     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-03-05T08:00:00 ┆ 0.0      ┆ PRE-DOSE         ┆ BLQ     ┆ BLQ      ┆ .        ┆ ng/mL    ┆ PLASMA ┆ Y      ┆ 1.0    ┆ 2014-03-05T08:00:00 │
│ 01-701-1028 ┆ 2     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-03-05T08:30:00 ┆ 0.5      ┆ 30 MIN POST-DOSE ┆ 6.11    ┆ 6.11     ┆ 6.11     ┆ ng/mL    ┆ PLASMA ┆ null   ┆ 1.0    ┆ 2014-03-05T08:00:00 │
│ 01-701-1028 ┆ 3     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-03-05T09:00:00 ┆ 1.0      ┆ 1 HR POST-DOSE   ┆ 11.78   ┆ 11.78    ┆ 11.78    ┆ ng/mL    ┆ PLASMA ┆ null   ┆ 1.0    ┆ 2014-03-05T08:00:00 │
│ 01-701-1028 ┆ 4     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-03-05T10:00:00 ┆ 2.0      ┆ 2 HR POST-DOSE   ┆ 19.95   ┆ 19.95    ┆ 19.95    ┆ ng/mL    ┆ PLASMA ┆ null   ┆ 1.0    ┆ 2014-03-05T08:00:00 │
│ 01-701-1028 ┆ 5     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-03-05T12:00:00 ┆ 4.0      ┆ 4 HR POST-DOSE   ┆ 24.67   ┆ 24.67    ┆ 24.67    ┆ ng/mL    ┆ PLASMA ┆ null   ┆ 1.0    ┆ 2014-03-05T08:00:00 │
│ 01-701-1028 ┆ 6     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-03-05T16:00:00 ┆ 8.0      ┆ 8 HR POST-DOSE   ┆ 16.34   ┆ 16.34    ┆ 16.34    ┆ ng/mL    ┆ PLASMA ┆ null   ┆ 1.0    ┆ 2014-03-05T08:00:00 │
│ 01-701-1028 ┆ 7     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-03-05T20:00:00 ┆ 12.0     ┆ 12 HR POST-DOSE  ┆ 9.01    ┆ 9.01     ┆ 9.01     ┆ ng/mL    ┆ PLASMA ┆ null   ┆ 1.0    ┆ 2014-03-05T08:00:00 │
│ 01-701-1028 ┆ 8     ┆ 2        ┆ Week 1 ┆ DRUG     ┆ Drug A ┆ 2014-03-06T08:00:00 ┆ 24.0     ┆ 24 HR POST-DOSE  ┆ 0.88    ┆ 0.88     ┆ 0.88     ┆ ng/mL    ┆ PLASMA ┆ null   ┆ 1.0    ┆ 2014-03-05T08:00:00 │
└─────────────┴───────┴──────────┴────────┴──────────┴────────┴─────────────────────┴──────────┴──────────────────┴─────────┴──────────┴──────────┴──────────┴────────┴────────┴────────┴─────────────────────┘
""")
)

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

print("── 1. Raw data loaded ───────────────────────────────────────────────────")
print(f"   pc_raw: {pc_raw.shape[0]:>2} rows   columns → {pc_raw.columns}")
print(f"   dm_raw: {dm_raw.shape[0]:>2} rows   columns → {dm_raw.columns}")

# ════════════════════════════════════════════════════════════════════════════
# 2. Build minimal ADSL  (admiral: derive_vars_merged with adsl)
#    TRTSDT = first_dose_date, TRT01P = arm_description, DOSEP from arm
# ════════════════════════════════════════════════════════════════════════════
adsl = (
    dm_raw.adam.adsl.assign("USUBJID", source="patient_number")
    .assign("TRT01P", source="arm_description")
    .assign("TRTSDT", source="first_dose_date")
    .assign("SEX", source="sex")
    .assign("RACE", source="race")
    .assign("AGE", source="age")
    # Planned dose from treatment arm
    .case_when(
        "DOSEP",
        when=[
            {"condition": pl.col("arm_code") == "Xan_Hi", "value": 81.0},
            {"condition": pl.col("arm_code") == "Xan_Lo", "value": 54.0},
        ],
        else_=0.0,
    )
    # Numeric sex covariate (admiral: compute_bmi / SEXN)
    .case_when(
        "SEXN",
        when=[
            {"condition": pl.col("SEX") == "M", "value": 1},
            {"condition": pl.col("SEX") == "F", "value": 2},
        ],
        else_=3,
    )
    # Numeric arm covariate (admiral: ARMN)
    .case_when(
        "ARMN",
        when=[
            {"condition": pl.col("arm_code") == "Xan_Hi", "value": 2},
            {"condition": pl.col("arm_code") == "Xan_Lo", "value": 1},
        ],
        else_=0,
    )
    .to_frame()
    .select(["USUBJID", "TRT01P", "TRTSDT", "DOSEP", "SEX", "SEXN", "RACE", "AGE", "ARMN"])
)

print("\n── 2. ADSL built ───────────────────────────────────────────────────────")
print(adsl.select(["USUBJID", "TRT01P", "DOSEP", "TRTSDT"]))

# ════════════════════════════════════════════════════════════════════════════
# 3. VS baselines — HTBL  (admiral: derive_vars_merged from VS)
# ════════════════════════════════════════════════════════════════════════════
htbl = (
    vs_raw.filter(pl.col("vstestcd") == "HEIGHT")
    .rename({"patient_number": "USUBJID", "vsorres": "HTBL", "vsorresu": "HTBLU"})
    .with_columns(pl.col("HTBL").cast(pl.Float64))
    .select(["USUBJID", "HTBL", "HTBLU"])
)

# ════════════════════════════════════════════════════════════════════════════
# 4. Clean PC — cast PCSTRESN  ("." = BLQ → null in Float64)
#    admiral: convert_blanks_to_na(pc)
# ════════════════════════════════════════════════════════════════════════════
pc = pc_raw.with_columns(
    pl.col("PCSTRESN").cast(pl.Float64, strict=False),
    pl.col("PCLLOQ").cast(pl.Float64),
    pl.col("PCTPTNUM").cast(pl.Float64),
)

# ════════════════════════════════════════════════════════════════════════════
# ┌────────────────────────────────────────────────────────────────────────┐
# │  PART 1 — ADPC (NCA)                                                  │
# └────────────────────────────────────────────────────────────────────────┘
# ════════════════════════════════════════════════════════════════════════════

print("\n════════════ PART 1: ADPC (NCA) ════════════")

adpc = (
    fleet.frame(pc)
    .adam.pk
    # ── Step 5. Merge early ADSL variables ──────────────────────────────────
    # admiral: derive_vars_merged(dataset_add = adsl, new_vars = adsl_vars,
    #           by_vars = exprs(STUDYID, USUBJID))
    .merge_adsl(adsl, keep=["TRT01P", "TRTSDT", "DOSEP", "SEX", "SEXN", "RACE", "AGE", "ARMN"])
    # ── Step 6. EVID = 0 for all concentration records ──────────────────────
    # admiral: mutate(EVID = 0)
    .evid("EVID")
    # ── Step 7. Nominal relative times from first / reference dose ──────────
    # admiral: derive_var_nfrlt(new_var = NFRLT, tpt_var = PCTPT,
    #                           visit_day = VISITDY, out_unit = "HOURS")
    # For this single-dose study PCTPTNUM already holds hours post-dose.
    .nominal_time("NFRLT", from_col="PCTPTNUM")  # Nom. Rel. Time from First Dose (h)
    .nominal_time("NRRLT", from_col="PCTPTNUM")  # Nom. Rel. Time from Ref. Dose (h)
    # (In multi-dose studies NRRLT = NFRLT - NFRLT_prev; here they are equal)
    # ── Step 8. Actual relative times from first / reference dose ───────────
    # admiral: derive_vars_duration(new_var = AFRLT, start_date = FANLDTM,
    #                               end_date = ADTM, out_unit = "HOURS", add_one = FALSE)
    # EXSTDTC is embedded in the PC domain for this single-dose dataset.
    .duration("AFRLT", start="EXSTDTC", end="PCDTC", unit="hours", add_one=False)
    .duration("ARRLT", start="EXSTDTC", end="PCDTC", unit="hours", add_one=False)
    # (In multi-dose studies ARRLT uses the most-recent prior dose datetime;
    # for the pre-dose record ARRLT is set to AXRLT = time-to-next-dose)
    # ── Step 9. Modified relative time — clip pre-dose negative values to 0 ─
    # admiral: mutate(MRRLT = if_else(ARRLT < 0, 0, ARRLT))
    .mrrlt("MRRLT", arrlt_col="ARRLT")
    # ── Step 10. BLQ flags ───────────────────────────────────────────────────
    # admiral: mutate(BLQFL = case_when(PCSTRESC == "<BLQ" ~ "Y", TRUE ~ "N"))
    # admiral: mutate(BLQFN = case_when(PCSTRESC == "<BLQ" ~ 1, TRUE ~ 0))
    # Fleet reads the BLQ text in PCSTRESC ("<...", "BLQ"; blq_text= sets the list)
    # and also counts a number below PCLLOQ (numeric_below_lloq=False turns it off).
    .blq_flag("BLQFL", conc_col="PCSTRESN", lloq_col="PCLLOQ")
    .blqfn("BLQFN", conc_col="PCSTRESN", lloq_col="PCLLOQ")
    # ── Step 11. AVAL — BLQ imputed to LLOQ / 2 ────────────────────────────
    # admiral: derive_extreme_records(..., set_values_to = exprs(AVAL = ALLOQ * .5,
    #                                                             DTYPE = "HALFLLOQ"))
    .blq_impute("AVAL", conc_col="PCSTRESN", lloq_col="PCLLOQ", method="half_lloq")
    # ── Step 12. Categorised analysis value (listing-ready) ─────────────────
    # admiral: mutate(AVALCAT1 = if_else(PCSTRESC == "<BLQ", PCSTRESC,
    #                            prettyNum(signif(AVAL, digits = 3))))
    .avalcat("AVALCAT1", conc_col="PCSTRESN", lloq_col="PCLLOQ", blq_label="BLQ")
    # ── Step 13. Analysis identifiers ────────────────────────────────────────
    # admiral: mutate(ATPT = PCTPT, ATPTREF = AVISIT_prev, BASETYPE = paste(ATPTREF, "Baseline"))
    .assign("ATPT", source="PCTPT")
    .assign("ATPTREF", source="VISIT")  # reference dosing visit
    .derivation(
        "BASETYPE",
        expression=pl.concat_str([pl.col("VISIT"), pl.lit(" Baseline")]),
    )
    # ABLFL = "Y" for pre-dose (nominal time == 0) records
    # admiral: mutate(ABLFL = case_when(ATPT == "Pre-dose" & !is.na(AVAL) ~ "Y"))
    .predose_flag("ABLFL", time_col="AFRLT", window_hrs=0.25)
    # ── Step 14. Dose variables ───────────────────────────────────────────────
    # admiral: mutate(DOSEA = EXDOSE_prev, DOSEP = case_when(TRT01P == "..." ~ 81))
    # DOSEP already merged from ADSL above.
    # DOSEA is derived as the actual dose from the reference dosing record.
    # In this single-dose dataset we use DOSEP as a proxy for DOSEA.
    .assign("DOSEA", source="DOSEP")
    .assign("DOSEU", value="mg")
    # ── Step 15. DTYPE for BLQ-imputed records ───────────────────────────────
    # admiral: set_values_to = exprs(DTYPE = "HALFLLOQ") on BLQ records
    .case_when(
        "DTYPE",
        when=[
            {"condition": pl.col("BLQFL") == "Y", "value": "HALFLLOQ"},
        ],
        else_=None,
    )
    # ── Step 16. Analysis flags ───────────────────────────────────────────────
    # admiral: mutate(ANL01FL = "Y", ANL02FL = if_else(is.na(DTYPE), "Y", NA))
    .anl_flag("ANL01FL")  # all records get "Y"
    .anl_flag("ANL02FL", exclude_dtype=True)  # non-DTYPE records only
    # ── Step 17. ASEQ — sequential record number per subject ─────────────────
    # admiral: derive_var_obs_number(new_var = ASEQ, by_vars = exprs(STUDYID, USUBJID))
    .seq("ASEQ", by=["USUBJID"])
    .to_frame()
)

# ── Step 18. Merge VS baselines (HTBL)  ──────────────────────────────────────
# admiral: derive_vars_merged(dataset_add = vs, filter_add = VSTESTCD == "HEIGHT",
#                             new_vars = exprs(HTBL = VSSTRESN))
adpc = adpc.join(htbl, on="USUBJID", how="left")

_blq_text = adpc.filter(pl.col("PCSTRESC") == "BLQ")
print(
    f"   BLQ text rows: {_blq_text.height}, flagged and imputed: "
    f"{_blq_text.filter((pl.col('BLQFL') == 'Y') & pl.col('AVAL').is_not_null()).height}"
)
assert (_blq_text["BLQFL"] == "Y").all(), "every PCSTRESC 'BLQ' record is BLQ"

# ── Step 19. ADSL variables already merged via merge_adsl() in the pipeline ──

print("\n── ADPC preview ─────────────────────────────────────────────────────────")
preview_cols = [
    "USUBJID",
    "PCTPT",
    "NFRLT",
    "AFRLT",
    "ARRLT",
    "MRRLT",
    "BLQFL",
    "BLQFN",
    "AVAL",
    "AVALCAT1",
    "DTYPE",
    "ANL01FL",
    "ANL02FL",
    "ATPTREF",
    "BASETYPE",
    "DOSEA",
    "DOSEP",
    "ASEQ",
]
print(adpc.select([c for c in preview_cols if c in adpc.columns]))

# ════════════════════════════════════════════════════════════════════════════
# ┌────────────────────────────────────────────────────────────────────────┐
# │  PART 2 — ADPPK (Population PK)                                        │
# └────────────────────────────────────────────────────────────────────────┘
# ════════════════════════════════════════════════════════════════════════════

print("\n════════════ PART 2: ADPPK (Population PK) ════════════")
print("(Stacking concentration rows [EVID=0] with synthetic dosing rows [EVID=1])")

# ── Create one dosing (EX) record per subject from EXSTDTC ──────────────────
# admiral: create_single_dose_dataset() / expand dosing records
# Here we keep the first-dose record per subject (single-dose study).
ex_records = (
    pc.group_by("USUBJID")
    .agg(
        [
            pl.col("EXSTDTC").first().alias("PCDTC"),  # reuse PCDTC for dose record
            pl.col("EXSTDTC").first().alias("EXSTDTC"),
            pl.col("PCLLOQ").first(),
            pl.col("PCSTRESU").first().alias("PCSTRESU"),
            pl.col("VISIT").first(),
            pl.col("PCTESTCD").first(),
            pl.col("PCSPEC").first(),
        ]
    )
    .with_columns(
        [
            pl.lit(None).cast(pl.Float64).alias("PCSTRESN"),  # dose record has no conc
            pl.lit(0.0).alias("PCTPTNUM"),
            pl.lit("Dose").alias("PCTPT"),
            pl.lit(1).cast(pl.Int64).alias("EVID"),
        ]
    )
)

# Stack concentration and dosing records (admiral: bind_rows(adpc, ex_exp))
pc_with_ex = pl.concat(
    [
        pc.with_columns(pl.lit(0).cast(pl.Int64).alias("EVID")),
        ex_records,
    ],
    how="diagonal_relaxed",
)

adppk = (
    fleet.frame(pc_with_ex)
    .adam.pk
    # Merge ADSL
    .merge_adsl(adsl, keep=["TRT01P", "TRTSDT", "DOSEP", "SEXN", "ARMN"])
    # ── AFRLT / APRLT — Actual Relative Time from First / Previous Dose ──────
    # admiral: derive_vars_duration(new_var = AFRLT, add_one = FALSE)
    # admiral: derive_vars_duration(new_var = APRLT, add_one = FALSE)
    # For single-dose: AFRLT = APRLT = time since the single dose
    .duration("AFRLT", start="EXSTDTC", end="PCDTC", unit="hours", add_one=False)
    .duration("APRLT", start="EXSTDTC", end="PCDTC", unit="hours", add_one=False)
    # ── NFRLT / NPRLT — Nominal Relative Times ───────────────────────────────
    # admiral: mutate(NFRLT = PCTPTNUM), NPRLT = NFRLT - NFRLT_prev
    .nominal_time("NFRLT", from_col="PCTPTNUM")
    .nominal_time("NPRLT", from_col="PCTPTNUM")  # same for single-dose
    # ── EVID ─────────────────────────────────────────────────────────────────
    # admiral: mutate(EVID = 0) for PC, EVID = 1 for EX
    .evid("EVID", from_col="EVID")  # already set; re-declares via verb
    # ── DV / DVL ─────────────────────────────────────────────────────────────
    # admiral: mutate(DV = PCSTRESN, DVL = case_when(DV != 0 ~ log(DV)))
    # DV is the measured value: a BLQ record keeps DV null and MDV 1.
    .assign("DV", source="PCSTRESN")
    .log_conc("DVL", conc_col="DV")
    # ── MDV — Missing Dependent Variable ─────────────────────────────────────
    # admiral: mutate(MDV = case_when(EVID == 1 ~ 1, is.na(DV) ~ 1, TRUE ~ 0))
    .mdv("MDV", conc_col="DV", evid_col="EVID")
    # ── AMT — Dose amount on dosing records ───────────────────────────────────
    # admiral: mutate(AMT = case_when(EVID == 1 ~ EXDOSE, TRUE ~ NA_real_))
    .amt("AMT", dose_col="DOSEP", evid_col="EVID")
    # ── CMT — Compartment number ─────────────────────────────────────────────
    # admiral: mutate(CMT = case_when(EVID == 1 ~ 1, PCSPEC == "PLASMA" ~ 2, TRUE ~ 3))
    .cmt("CMT", evid_col="EVID", dose_cmt=1, conc_cmt=2)
    # ── BLQ flags ─────────────────────────────────────────────────────────────
    # admiral: mutate(BLQFL = …, BLQFN = …)
    .blq_flag("BLQFL", conc_col="PCSTRESN", lloq_col="PCLLOQ")
    .blqfn("BLQFN", conc_col="PCSTRESN", lloq_col="PCLLOQ")
    # ── ASEQ ───────────────────────────────────────────────────────────────────
    # admiral: derive_var_obs_number(new_var = ASEQ, order = exprs(AFRLT, EVID, CMT))
    .seq("ASEQ", by=["USUBJID"])
    .to_frame()
)

# Merge height baseline
adppk = adppk.join(htbl, on="USUBJID", how="left")

print("\n── ADPPK preview ────────────────────────────────────────────────────────")
ppk_cols = [
    "USUBJID",
    "EVID",
    "NFRLT",
    "AFRLT",
    "APRLT",
    "DV",
    "DVL",
    "MDV",
    "AMT",
    "CMT",
    "BLQFL",
    "BLQFN",
    "SEXN",
    "ARMN",
    "ASEQ",
]
print(adppk.select([c for c in ppk_cols if c in adppk.columns]))

# ════════════════════════════════════════════════════════════════════════════
# Save outputs
# ════════════════════════════════════════════════════════════════════════════
adpc_out = OUT / "adpc.parquet"
adppk_out = OUT / "adppk.parquet"
adpc.write_parquet(adpc_out)
adppk.write_parquet(adppk_out)
print("\n── Outputs written ──────────────────────────────────────────────────────")
print(f"   {adpc_out}  ({adpc.shape[0]} rows, {adpc.shape[1]} cols)")
print(f"   {adppk_out} ({adppk.shape[0]} rows, {adppk.shape[1]} cols)")

# ════════════════════════════════════════════════════════════════════════════
# Fleet <> admiral feature parity summary
# ════════════════════════════════════════════════════════════════════════════
print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║  Fleet PK Feature Parity vs. admiral pk_adnca.Rmd                          ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  ADPC (NCA) features                                                        ║
║  ✓  NFRLT / NRRLT  nominal_time()         admiral: derive_var_nfrlt()      ║
║  ✓  AFRLT / ARRLT  actual_time()          admiral: derive_vars_duration()  ║
║  ✓  MRRLT          mrrlt()                admiral: if_else(ARRLT<0,0,…)    ║
║  ✓  EVID           evid()                 admiral: mutate(EVID=0/1)        ║
║  ✓  BLQFL          blq_flag()             admiral: case_when BLQ flag      ║
║  ✓  BLQFN          blqfn()               admiral: numeric BLQ flag         ║
║  ✓  AVAL (BLQ)     blq_impute()           admiral: ALLOQ * 0.5             ║
║  ✓  AVALCAT1       avalcat()              admiral: prettyNum(signif(…))    ║
║  ✓  ABLFL / PREDFL predose_flag()         admiral: ATPT == "Pre-dose"      ║
║  ✓  DTYPE          derivation()           admiral: set_values_to DTYPE     ║
║  ✓  ANL01FL        anl_flag()             admiral: mutate(ANL01FL = "Y")   ║
║  ✓  ANL02FL        anl_flag(exclude_…)    admiral: if_else(is.na(DTYPE)…) ║
║  ✓  ASEQ           seq()                  admiral: derive_var_obs_number() ║
║  ✓  ADSL merge     merge_adsl()           admiral: derive_vars_merged()    ║
║  ✓  DOSEA/DOSEP    derivation()           admiral: mutate(DOSEA=…)         ║
║                                                                             ║
║  ADPPK (Population PK) features                                             ║
║  ✓  DV / DVL       source() / log_conc()  admiral: DV=PCSTRESN, log(DV)   ║
║  ✓  MDV            mdv()                  admiral: MDV=case_when(…)        ║
║  ✓  AMT            amt()                  admiral: AMT=case_when(EVID==1)  ║
║  ✓  CMT            cmt()                  admiral: CMT=case_when(EVID==1)  ║
║  ✓  AFRLT/APRLT    actual_time()          admiral: derive_vars_duration()  ║
║  ✓  NFRLT/NPRLT    nominal_time()         admiral: NFRLT - NFRLT_prev     ║
║  ✓  SEXN/ARMN      adsl derivation        admiral: covariate mutates       ║
║  ✓  ASEQ           seq()                  admiral: derive_var_obs_number() ║
║                                                                             ║
║  Advanced admiral steps not yet covered by Fleet verbs (use plain Polars): ║
║  ~  create_single_dose_dataset()  — multi-dose expansion                   ║
║  ~  derive_vars_joined() prev/next dose temporal joins                     ║
║  ~  compute_egfr() / compute_bsa() renal function / body-surface area      ║
║  ~  COPY DTYPE duplicate records for pre-dose NCA                          ║
║  ~  BASE / CHG from baseline via ABLFL grouping                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
""")
