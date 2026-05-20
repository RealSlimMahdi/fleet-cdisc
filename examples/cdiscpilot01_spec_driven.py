"""
End-to-end CDISCPILOT01 pipeline — spec-driven style.

Every ADaM column derivation is defined in examples/cdiscpilot01/adam/define.yaml
and executed via ``df.adam.from_spec()``.  OCCDS-specific verbs that the spec
cannot yet express (treatment_emergent, seq) are applied inline
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

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl

import fleet  # noqa: F401 — registers .sdtm / .adam namespace extensions
from examples.cdiscpilot01.sdtm.codelists import ETHNIC, RACE, SEX
from fleet import DatasetChecker, DefineSpecGenerator

SPECS = Path("examples/cdiscpilot01")
OUT = Path("outputs/cdiscpilot01")
OUT.mkdir(parents=True, exist_ok=True)

SDTM_SPEC = SPECS / "sdtm/define.yaml"
ADAM_SPEC = SPECS / "adam/define.yaml"

# ── 1. Raw data (inline) ─────────────────────────────────────────────────────
dm_raw = pl.from_repr("""\
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

ae_raw = pl.from_repr("""\
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

vs_raw = pl.from_repr("""\
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

# ── 2. SDTM DM ───────────────────────────────────────────────────────────────
dm = (
    dm_raw.sdtm.hardcode_no_ct("STUDYID", value="CDISCPILOT01")  # type: ignore[attr-defined]  # runtime namespace registered by fleet
    .hardcode_no_ct("DOMAIN", value="DM")
    .assign_no_ct("USUBJID", source="patient_number")
    .assign_no_ct("SUBJID", source="patient_number")
    .derivation("SITEID", expression="pl.col('site_id').cast(pl.String)")
    .assign_no_ct("AGE", source="age")
    .hardcode_no_ct("AGEU", value="YEARS")
    .assign_ct("SEX", source="sex", ct_codelist=SEX, ct_mapping={"F": "F", "M": "M"})
    .assign_ct(
        "RACE",
        source="race",
        ct_codelist=RACE,
        ct_mapping={"WHITE": "WHITE", "BLACK OR AFRICAN AMERICAN": "BLACK OR AFRICAN AMERICAN"},
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
    .if_then_else(
        "ARMCD",
        when=[
            {"condition": pl.col("arm_code") == "Pbo", "value": "PBO"},
            {"condition": pl.col("arm_code") == "Xan_Lo", "value": "XAN_LO"},
            {"condition": pl.col("arm_code") == "Xan_Hi", "value": "XAN_HI"},
        ],
        else_value="SCRNFAIL",
    )
    .assign_no_ct("ARM", source="arm_description")
    .assign_no_ct("ACTARMCD", source="arm_code")
    .assign_no_ct("ACTARM", source="arm_description")
    .date("RFSTDTC", source="first_dose_date")
    .date("RFENDTC", source="last_dose_date")
    .date("RFICDTC", source="informed_consent_date")
    .select(spec=SDTM_SPEC, dataset="DM")
    .write_parquet(OUT / "dm.parquet")
)
print(f"SDTM DM  : {dm.shape[0]} subjects  ·  {dm.shape[1]} columns")

# ── 3. Synthesise SDTM EX (one record per subject) ───────────────────────────
ex = (
    dm_raw.sdtm.hardcode_no_ct("STUDYID", value="CDISCPILOT01")  # type: ignore[attr-defined]  # runtime namespace registered by fleet
    .hardcode_no_ct("DOMAIN", value="EX")
    .assign_no_ct("USUBJID", source="patient_number")
    .assign_no_ct("EXTRT", source="arm_description")
    .if_then_else(
        "EXDOSE",
        when=[
            {"condition": pl.col("arm_code") == "Pbo", "value": 0.0},
            {"condition": pl.col("arm_code") == "Xan_Lo", "value": 54.0},
            {"condition": pl.col("arm_code") == "Xan_Hi", "value": 81.0},
        ],
    )
    .hardcode_no_ct("EXDOSU", value="mg")
    .assign_no_ct("EXSTDTC", source="first_dose_date")
    .assign_no_ct("EXENDTC", source="last_dose_date")
    .hardcode_no_ct("EXSEQ", value=1)
    .to_frame()
    .select(
        ["STUDYID", "DOMAIN", "USUBJID", "EXSEQ", "EXTRT", "EXDOSE", "EXDOSU", "EXSTDTC", "EXENDTC"]
    )
)

# ── 4. Synthesise SDTM AE ─────────────────────────────────────────────────────
ae = (
    ae_raw.sdtm.hardcode_no_ct("STUDYID", value="CDISCPILOT01")  # type: ignore[attr-defined]  # runtime namespace registered by fleet
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
#    Simple derivations (source/rename/assigned) live in the spec.
#    Join-based pre-computations (TRTSDT from EX, AGEGR1, SAFFL, ITTFL,
#    TRT01P/TRT01A) are added to the DM frame before from_spec() runs.
# ════════════════════════════════════════════════════════════════════════════
print("\n── ADaM ADSL (spec-driven) ──────────────────────────────────────────────")

_ex_max_dose = ex.group_by("USUBJID").agg(pl.col("EXDOSE").max().alias("_EXDOSE_MAX"))

dm_enriched = (
    dm.adam.lookup(dataset=_ex_max_dose, on="USUBJID", how="left")  # type: ignore[attr-defined]  # runtime namespace registered by fleet
    .to_frame()
    .adam.adsl  # type: ignore[attr-defined]  # runtime namespace registered by fleet
    # Treatment dates from EX (admiral: derive_vars_merged)
    .first_date("TRTSDT", from_dataset=ex, date_col="EXSTDTC")
    .last_date("TRTEDT", from_dataset=ex, date_col="EXENDTC")
    # Treatment variables (admiral: mutate TRT01P=ARM, TRT01A=ACTARM)
    .rename("TRT01P", source="ARM")
    .rename("TRT01A", source="ACTARM")
    # Age grouping (admiral: derive_vars_cat)
    .condderivation(
        "AGEGR1",
        conditions=[
            {"condition": "pl.col('AGE') < 18", "value": "<18"},
            {"condition": "pl.col('AGE') <= 64", "value": "18-64"},
            {"condition": "pl.col('AGE') > 64", "value": ">64"},
        ],
        else_value="Missing",
    )
    # Population flags (admiral: derive_var_merged_exist_flag)
    .flag("SAFFL", criteria='pl.col("_EXDOSE_MAX") > 0')
    .flag("ITTFL", criteria='pl.col("ARMCD") != "SCRNFAIL"')
    .to_frame()
    .drop("_EXDOSE_MAX")
)

adsl = (
    dm_enriched.adam.from_spec(ADAM_SPEC, dataset="ADSL")  # type: ignore[attr-defined]  # runtime namespace registered by fleet
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
    vs_raw.adam.rename("USUBJID", source="patient_number")  # type: ignore[attr-defined]  # runtime namespace registered by fleet
    .lookup(dataset=_trtsdt_map, on="USUBJID", how="left")
    .to_frame()
)

advs = (
    vs_with_trtsdt.adam.from_spec(ADAM_SPEC, dataset="ADVS")  # type: ignore[attr-defined]  # runtime namespace registered by fleet
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
ae_with_trt = ae.adam.lookup(dataset=_adsl_trt, on="USUBJID", how="left").to_frame()  # type: ignore[attr-defined]  # runtime namespace registered by fleet

adae_sourced = ae_with_trt.adam.from_spec(ADAM_SPEC, dataset="ADAE").to_frame()  # type: ignore[attr-defined]  # runtime namespace registered by fleet

adae = (
    adae_sourced.adam.occds.treatment_emergent(  # type: ignore[attr-defined]  # runtime namespace registered by fleet
        "TRTEMFL", start_date="AESTDTC", trtsdt="TRTSDT", trtedt="TRTEDT"
    )
    .recode("AESEVN", source="AESEV", recode_map={"MILD": 1, "MODERATE": 2, "SEVERE": 3})
    .flag(
        "ANL01FL",
        criteria="max",
        value_col="AESEVN",
        groups=["USUBJID", "AETERM"],
    )
    .seq("ASEQ", groups=["USUBJID"])
    .to_frame()
    .with_columns(
        pl.col("TRTSDT"),
        pl.col("TRTEDT"),
        pl.col("TRT01P"),
        pl.col("AGE"),
        pl.col("SEX"),
        pl.col("SAFFL"),
    )
)
adae = adae.adam.select(spec=ADAM_SPEC, dataset="ADAE").write_parquet(OUT / "adae.parquet")  # type: ignore[attr-defined]  # runtime namespace registered by fleet

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
ex_with_adsl = ex.adam.lookup(dataset=_adsl_ex, on="USUBJID", how="left").to_frame()  # type: ignore[attr-defined]  # runtime namespace registered by fleet

adex_s1 = ex_with_adsl.adam.from_spec(ADAM_SPEC, dataset="ADEX").to_frame()  # type: ignore[attr-defined]  # runtime namespace registered by fleet

adex = (
    adex_s1.adam.occds  # type: ignore[attr-defined]  # runtime namespace registered by fleet
    # admiral: derive_var_dur (inclusive end-date convention)
    .derivation(
        "EXDURD",  # shared verb on occds via mixin
        expression="(pl.col('AENDT').cast(pl.Date) - pl.col('ASTDT').cast(pl.Date))"
        ".dt.total_days() + 1",
    )
    # admiral: derive_var_obs_number
    .seq("ASEQ", groups=["USUBJID"])  # occds-specific verb
    .to_frame()
    .with_columns(
        pl.col("TRTSDT"),
        pl.col("TRTEDT"),
        pl.col("TRT01P"),
        pl.col("AGE"),
        pl.col("SAFFL"),
    )
)
adex = adex.adam.select(spec=ADAM_SPEC, dataset="ADEX").write_parquet(OUT / "adex.parquet")  # type: ignore[attr-defined]  # runtime namespace registered by fleet

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
    checker.check(df, dataset=ds).print_report()

# ── 10. Generate Define-XML 2.1 ───────────────────────────────────────────────
# enrich_methods=True embeds Fleet verb docstrings into the Origin/MethodDef
# elements so reviewers see the exact computational method (single source of
# truth: docstring -> Define-XML).
DefineSpecGenerator(SDTM_SPEC, enrich_methods=True).generate(OUT / "define_sdtm.xml")
DefineSpecGenerator(ADAM_SPEC, enrich_methods=True).generate(OUT / "define_adam.xml")
print(f"\nDefine-XML written to {OUT}/")
print("  Serve with: python -m http.server 8080 --directory outputs/cdiscpilot01")

# ── 11. Export Dataset-JSON v1.1 ──────────────────────────────────────────────
from fleet.io import save_dataset_json  # noqa: E402

for name, df in [("DM", dm), ("ADSL", adsl), ("ADVS", advs), ("ADAE", adae), ("ADEX", adex)]:
    save_dataset_json(df, OUT / f"{name.lower()}_spec.json", domain=name)
print(f"Dataset-JSON exported to {OUT}/")
