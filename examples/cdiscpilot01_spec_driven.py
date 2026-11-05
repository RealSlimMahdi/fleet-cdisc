"""
End-to-end CDISCPILOT01 pipeline — spec-driven style.

Every ADaM column derivation is defined in examples/cdiscpilot01/adam/define.yaml
and executed via ``df.adam.from_spec()``.  OCCDS-specific verbs that the spec
cannot yet express (worst-severity flag, seq) are applied inline
immediately after the spec phase.

Shared-verb mixin architecture
-------------------------------
Fleet's shared verb mixin provides the canonical verbs — ``assign``,
``case_when``, ``merge``, ``keep``, ``derivation``, ``recode``,
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

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl

import fleet  # registers .sdtm / .adam namespace extensions
from examples.cdiscpilot01.sdtm.codelists import ETHNIC, RACE, SEX
from fleet import DatasetChecker, DefineSpecGenerator

SPECS = Path("examples/cdiscpilot01")
OUT = Path("outputs/cdiscpilot01")
OUT.mkdir(parents=True, exist_ok=True)

SDTM_SPEC = SPECS / "sdtm/define.yaml"
ADAM_SPEC = SPECS / "adam/define.yaml"

# ── 1. Raw data (inline) ─────────────────────────────────────────────────────
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

# ── 2. SDTM DM ───────────────────────────────────────────────────────────────
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
        ct_map={"WHITE": "WHITE", "BLACK OR AFRICAN AMERICAN": "BLACK OR AFRICAN AMERICAN"},
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
    .select(spec=SDTM_SPEC, dataset="DM")
    .write_parquet(OUT / "dm.parquet")
)
print(f"SDTM DM  : {dm.shape[0]} subjects  ·  {dm.shape[1]} columns")

# ── 3. Synthesise SDTM EX (one record per subject) ───────────────────────────
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

# ── 4. Synthesise SDTM AE ─────────────────────────────────────────────────────
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
    .derivation("AESEQ", expression='pl.col("ae_term").cum_count().over("patient_number")')
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
            "AESEV",
            "AESER",
            "AEOUT",
            "AEACN",
            "AEREL",
        ]
    )
)
print(f"SDTM AE  : {ae.shape[0]} records  ·  {ae.shape[1]} columns")

# ════════════════════════════════════════════════════════════════════════════
# 5. ADaM ADSL — spec-driven
#    Simple derivations (source/rename/assigned) live in the spec, and so do
#    TRTSDT/TRTEDT (first_date/last_date on the pinned EX).
#    Join-based pre-computations (AGEGR1, SAFFL, ITTFL, TRT01P/TRT01A)
#    are added to the DM frame before from_spec() runs.
# ════════════════════════════════════════════════════════════════════════════
print("\n── ADaM ADSL (spec-driven) ──────────────────────────────────────────────")

dm_enriched = (
    # Treatment variables (admiral: mutate TRT01P=ARM, TRT01A=ACTARM)
    dm.adam.adsl.assign("TRT01P", source="ARM")
    .assign("TRT01A", source="ACTARM")
    # Age grouping (admiral: derive_vars_cat)
    .case_when(
        "AGEGR1",
        when=[
            {"condition": "pl.col('AGE') < 18", "value": "<18"},
            {"condition": "pl.col('AGE') <= 64", "value": "18-64"},
            {"condition": "pl.col('AGE') > 64", "value": ">64"},
        ],
        else_="Missing",
    )
    # Population flags (admiral: derive_var_merged_exist_flag). This is the admiral
    # template condition; the SAP decides. A population flag is never blank: N.
    .flag_exists(
        "SAFFL",
        from_dataset=ex,
        on=["USUBJID"],
        source_filter=(pl.col("EXDOSE") > 0)
        | ((pl.col("EXDOSE") == 0) & pl.col("EXTRT").str.to_uppercase().str.contains("PLACEBO")),
        false_value="N",
    )
    .flag("ITTFL", criteria='pl.col("ARMCD") != "SCRNFAIL"', false_value="N")
    .to_frame()
)
assert (dm_enriched["SAFFL"] == "Y").sum() == dm_enriched.height, "every pilot subject took a dose"

# The columns below are derived inline above (or upstream in DM) with a
# *different* method than the spec documents, so they are omitted from the
# spec pass — from_spec()'s overwrite guard would (rightly) raise otherwise.
# TRTSDT and TRTEDT run from the spec on the pinned EX.
adsl = (
    dm_enriched.adam.pin("EX", ex)
    .from_spec(
        ADAM_SPEC,
        dataset="ADSL",
        omit=["TRT01P", "TRT01A"],
    )
    .select(spec=ADAM_SPEC, dataset="ADSL")
    .write_parquet(OUT / "adsl.parquet")
)
print(f"   {adsl.shape[0]} subjects × {adsl.shape[1]} variables")

# ════════════════════════════════════════════════════════════════════════════
# 6. ADaM ADVS — spec-driven
#    The variables run in spec order, so each one reads the columns above it:
#      ADT → ADY,  ABLFL → BASE,  BASE → CHG / PCHG
#    The define declares `inputs: [VS, ADSL]`: the subject-level variables it
#    lists (SUBJID … ITTFL) are merged in from the ADSL built above, exactly
#    as the define.yaml documents.
# ════════════════════════════════════════════════════════════════════════════
print("\n── ADaM ADVS (spec-driven) ──────────────────────────────────────────────")

_ADSL_CARRY = [
    "USUBJID",
    "SUBJID",
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
    "TRT01P",
    "TRT01A",
    "TRTSDT",
    "TRTEDT",
    "RFSTDTC",
    "RFENDTC",
    "RFICDTC",
    "SAFFL",
    "ITTFL",
]
vs_with_adsl = (
    vs_raw.adam.assign("USUBJID", source="patient_number")
    .merge(dataset=adsl.select(_ADSL_CARRY), on="USUBJID", how="left")
    .to_frame()
)

# The spec copies USUBJID as it is (an identity copy of the merge key).
advs = (
    vs_with_adsl.adam.from_spec(ADAM_SPEC, dataset="ADVS")
    .select(spec=ADAM_SPEC, dataset="ADVS")
    .write_parquet(OUT / "advs.parquet")
)
print(f"   {advs.shape[0]} records × {advs.shape[1]} variables")
print(f"   Parameters: {sorted(advs['PARAMCD'].unique().to_list())}")

# ════════════════════════════════════════════════════════════════════════════
# 7. ADaM ADAE — hybrid: spec for source columns and TRTEMFL, occds for the rest
#    admiral ref: https://pharmaverse.github.io/admiral/articles/adae.html
# ════════════════════════════════════════════════════════════════════════════
print("\n── ADaM ADAE (spec-driven + occds verbs) ────────────────────────────────")

_adsl_trt = adsl.select(["USUBJID", "TRTSDT", "TRTEDT", "TRT01P", "AGE", "SEX", "SAFFL"])
ae_with_trt = fleet.frame(ae).adam.merge(dataset=_adsl_trt, on="USUBJID", how="left").to_frame()
# STUDYID already exists on the SDTM AE frame — keep it, skip the spec's copy.
# The spec derives TRTEMFL with occds.treatment_emergent (end window 0 days).
adae_sourced = ae_with_trt.adam.from_spec(ADAM_SPEC, dataset="ADAE", omit=["STUDYID"]).to_frame()
adae = (
    adae_sourced.adam.occds.recode(
        "AESEVN", source="AESEV", recode_map={"MILD": 1, "MODERATE": 2, "SEVERE": 3}
    )
    .flag(
        "ANL01FL",
        criteria="max",
        value_col="AESEVN",
        by=["USUBJID", "AETERM"],
    )
    .seq("ASEQ", by=["USUBJID"])
    .to_frame()
)
adae = adae.adam.select(spec=ADAM_SPEC, dataset="ADAE").write_parquet(OUT / "adae.parquet")
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
ex_with_adsl = fleet.frame(ex).adam.merge(dataset=_adsl_ex, on="USUBJID", how="left").to_frame()
# STUDYID already exists on the SDTM EX frame — keep it, skip the spec's copy.
adex_s1 = ex_with_adsl.adam.from_spec(ADAM_SPEC, dataset="ADEX", omit=["STUDYID"]).to_frame()
adex = (
    adex_s1.adam.occds.derivation(  # admiral: derive_var_dur (inclusive end-date convention)
        "EXDURD",  # shared verb on occds via mixin
        expression="(pl.col('AENDT').cast(pl.Date) - pl.col('ASTDT').cast(pl.Date))"
        ".dt.total_days() + 1",
    )
    # admiral: derive_var_obs_number
    .seq("ASEQ", by=["USUBJID"])  # occds-specific verb
    .to_frame()
)
adex = adex.adam.select(spec=ADAM_SPEC, dataset="ADEX").write_parquet(OUT / "adex.parquet")
print(f"   {adex.shape[0]} records × {adex.shape[1]} variables")
print(f"   EXDURD range : {adex['EXDURD'].min()} – {adex['EXDURD'].max()} days")

# ── 9. Post-dataset quality checks ───────────────────────────────────────────
print("\n── Quality checks ────────────────────────────────────────────────────────")
sdtm_checker = DatasetChecker(SDTM_SPEC)
adam_checker = DatasetChecker(ADAM_SPEC)

for checker, df, ds in [
    (sdtm_checker, dm, "DM"),
    (adam_checker, adsl, "ADSL"),
    (adam_checker, advs, "ADVS"),
    (adam_checker, adae, "ADAE"),
    (adam_checker, adex, "ADEX"),
]:
    result = checker.check(df, dataset=ds)
    result.print_report()
    result.raise_on_errors()  # a failing dataset must fail the pipeline

# ── 10. Generate Define-XML 2.1 ───────────────────────────────────────────────
# One MethodDef per Derived variable, with submission-facing text rendered
# from the algorithm registry (a spec `comment:` overrides it) and the
# faithful Fleet call as FormalExpression. strict=True refuses a define with
# a gap: a Derived variable with no method text, a numeric item with no
# Length or a float with no SignificantDigits.
# XSD validation + the semantic lint run automatically on the way out.
DefineSpecGenerator(SDTM_SPEC, strict=True).generate(OUT / "define_sdtm.xml")
DefineSpecGenerator(ADAM_SPEC, strict=True).generate(OUT / "define_adam.xml")
print(f"\nDefine-XML written to {OUT}/")
print("  Serve with: python -m http.server 8080 --directory outputs/cdiscpilot01")

# ── 11. Export Dataset-JSON v1.1 ──────────────────────────────────────────────
from fleet.io import save_dataset_json  # noqa: E402

for name, df in [("DM", dm), ("ADSL", adsl), ("ADVS", advs), ("ADAE", adae), ("ADEX", adex)]:
    save_dataset_json(df, OUT / f"{name.lower()}_spec.json", domain=name)
print(f"Dataset-JSON exported to {OUT}/")
