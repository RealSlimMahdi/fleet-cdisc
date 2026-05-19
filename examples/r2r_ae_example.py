"""
Raw-to-Render (R2R) — AE domain in a single program.

Demonstrates the **R2R strategy**: one self-contained script that takes
raw adverse-event data all the way to a rendered HTML table, traversing
every CDISC layer in sequence:

    Raw AE CSV  →  SDTM AE  →  ADaM ADAE  →  Validate  →  TLG (HTML)

DM and ADSL are assumed to already exist (produced by separate governed
programs).  This script focuses on **one domain end-to-end**: AE → ADAE →
Table 14.3.1.1.  An AI agent — or a human programmer — can reason about
the complete data lineage for this domain in a single file.

Run from repo root:
    uv run python examples/r2r_ae_example.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from fleet.core.lineage import lineage_of

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl

import fleet  # noqa: F401 — registers .sdtm / .adam / .tlg namespaces
from fleet.tlg import (
    AESummarySpec,
    GroupPool,
    OverallStat,
    RenderMetadata,
    Row,
    Statistic,
    ard_to_table_model,
    render_html,
)

OUT = Path("outputs/cdiscpilot01")
OUT.mkdir(parents=True, exist_ok=True)


# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃  LAYER 0 — Load upstream artefacts + raw AE data                      ┃
# ┃                                                                       ┃
# ┃  DM and ADSL are produced by separate governed programs.              ┃
# ┃  This R2R script only owns the AE domain.                             ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
print("━━ Layer 0 · Inputs ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

# Pre-existing ADSL (subject-level reference for Big-N, treatment arms, dates)
adsl = pl.from_repr("""\
┌─────────────┬─────┬─────┬───────────────────────────┬──────────────────────┬────────────┬────────────┬───────┐
│ USUBJID     ┆ AGE ┆ SEX ┆ RACE                      ┆ TRT01P               ┆ TRTSDT     ┆ TRTEDT     ┆ SAFFL │
│ ---         ┆ --- ┆ --- ┆ ---                       ┆ ---                  ┆ ---        ┆ ---        ┆ ---   │
│ str         ┆ i64 ┆ str ┆ str                       ┆ str                  ┆ str        ┆ str        ┆ str   │
╞═════════════╪═════╪═════╪═══════════════════════════╪══════════════════════╪════════════╪════════════╪═══════╡
│ 01-701-1015 ┆ 63  ┆ F   ┆ WHITE                     ┆ Placebo              ┆ 2014-01-02 ┆ 2014-07-02 ┆ Y     │
│ 01-701-1023 ┆ 64  ┆ F   ┆ WHITE                     ┆ Xanomeline Low Dose  ┆ 2014-01-03 ┆ 2014-07-03 ┆ Y     │
│ 01-701-1028 ┆ 71  ┆ M   ┆ WHITE                     ┆ Xanomeline High Dose ┆ 2014-01-04 ┆ 2014-07-04 ┆ Y     │
│ 01-701-1034 ┆ 74  ┆ M   ┆ BLACK OR AFRICAN AMERICAN ┆ Placebo              ┆ 2014-01-05 ┆ 2014-07-05 ┆ Y     │
│ 01-701-1047 ┆ 56  ┆ F   ┆ WHITE                     ┆ Xanomeline Low Dose  ┆ 2014-01-06 ┆ 2014-07-06 ┆ Y     │
└─────────────┴─────┴─────┴───────────────────────────┴──────────────────────┴────────────┴────────────┴───────┘
""")
adsl = adsl.with_columns(pl.col("TRT01P").alias("TRTA"))
print(f"  ADSL (inline)    : {adsl.shape[0]} subjects × {adsl.shape[1]} variables")
print(f"         Arms: {sorted(adsl['TRTA'].unique().to_list())}")

# Raw AE extract — the only raw data this script owns
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
print(f"  ae_raw           : {ae_raw.shape[0]:>3} rows × {ae_raw.shape[1]} cols")


# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃  LAYER 1 — SDTM AE: standardise raw AE into submission-ready domain   ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
print("\n━━ Layer 1 · SDTM AE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

ae = (
    ae_raw.sdtm.hardcode_no_ct("STUDYID", value="CDISCPILOT01")
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
    .seq("AESEQ", order_by=["AESTDTC"])
    .to_frame()
)

# Intentional corruption: AESER "Y" → "YES" violates CDISC CT (C66742).
# The SDTM Rules Engine should flag this as a controlled-terminology error.
ae = ae.with_columns(pl.col("AESER").replace("Y", "YES").alias("AESER"))
print(f"  AE : {ae.shape[0]} records × {ae.shape[1]} variables")


# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃  LAYER 2 — ADaM ADAE: analysis-ready event-level dataset              ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
print("\n━━ Layer 2 · ADaM ADAE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

# Merge ADSL treatment dates & population flags into SDTM AE
_adsl_trt = adsl.select(["USUBJID", "TRTSDT", "TRTEDT", "TRT01P", "TRTA", "SAFFL"])
ae_with_trt = ae.join(_adsl_trt, on="USUBJID", how="left")

_adae_base_ns = (
    ae_with_trt.adam("ADAE")
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
    .date("ASTDT", source="AESTDTC")
    .date("AENDT", source="AEENDTC")
    .duration("ADY", start="TRTSDT", end="ASTDT")
)

_adae_occds_ns = (
    _adae_base_ns.to_frame()
    .adam.occds("ADAE")
    .treatment_emergent(
        "TRTEMFL",
        start_date="AESTDTC",
        trtsdt="TRTSDT",
        trtedt="TRTEDT",
    )
    .recode("AESEVN", source="AESEV", recode_map={"MILD": 1, "MODERATE": 2, "SEVERE": 3})
    .flag(
        "ANL01FL",
        criteria="max",
        value_col="AESEVN",
        groups=["USUBJID", "AETERM"],
    )
    .seq("ASEQ", groups=["USUBJID"])
)

adae = _adae_occds_ns.to_frame()

# Simulate MedDRA coding (in a real study these come from a dictionary)
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

print(f"  ADAE : {adae.shape[0]} records × {adae.shape[1]} variables")
print(f"         TE AEs  : {(adae['TRTEMFL'] == 'Y').sum()}")
print(f"         SAEs    : {(adae['AESER'] == 'Y').sum()}")

# Export SDTM AE and ADaM ADAE as Dataset-JSON (CDISC v1.1)
from fleet.io import save_dataset_json  # noqa: E402

ae_json_path = save_dataset_json(ae, OUT / "ae.json", domain="AE", label="Adverse Events")
adae_json_path = save_dataset_json(adae, OUT / "adae.json", domain="ADAE", label="ADAE Analysis")
print(f"         AE   → {ae_json_path}")
print(f"         ADAE → {adae_json_path}")

# ── Variable-Level Lineage ─────────────────────────────────────────────
print("\n━━ ADAE Variable Lineage ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
_all_lineage = lineage_of(_adae_base_ns) + lineage_of(_adae_occds_ns)
print(f"  {'Variable':<12}  {'Verb':<22}  {'Sources':<30}  CDISC Ref")
print(f"  {'─' * 12}  {'─' * 22}  {'─' * 30}  {'─' * 50}")
for node in _all_lineage:
    src = ", ".join(node.sources) if node.sources else "—"
    print(f"  {node.name:<12}  {node.verb:<22}  {src:<30}  {node.cdisc_ref}")


# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃  LAYER 3 — Validate: pre-flight checks before table generation        ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
print("\n━━ Layer 3 · Validate ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

# TLG-level pre-validation (lightweight, no engine required)
ae_spec = AESummarySpec(
    rows=[
        Row(field="AEBODSYS", label="System Organ Class"),
        Row(field="AEDECOD", label="Preferred Term"),
        Row(field="AESER", label="Serious AE", filter_value="Y"),
    ],
    columns=["TRTA"],
    statistics=[Statistic.N_SUBJECTS, Statistic.N_PCT, Statistic.N_EVENTS],
    pools=[
        GroupPool(label="All Xanomeline", arms=["Xanomeline Low Dose", "Xanomeline High Dose"]),
        GroupPool(label="Total", arms="*"),
    ],
    column_order=[
        "Placebo",
        "Xanomeline Low Dose",
        "Xanomeline High Dose",
        "All Xanomeline",
        "Total",
    ],
)

report = adae.tlg.ae.check(spec=ae_spec)
if report:
    for msg in report:
        print(f"  ⚠ {msg}")
else:
    print("  ✓ TLG pre-validation passed — data is ready for the AE summary.")

# CDISC conformance validation (requires Rules Engine — graceful skip)
try:
    from fleet.validation.service import ValidationService

    svc = ValidationService()
    sdtm_result = svc.validate_sdtm(ae, domain="AE", version="3.4")
    sdtm_result.print_report(report_type="summary")
    adam_result = svc.validate_adam(adae, dataset="ADAE", version="1.3")
    adam_result.print_report(report_type="full")
except (FileNotFoundError, ImportError) as exc:
    print(f"  ℹ CDISC conformance check skipped — {exc}")
    print("    Install with: uv run fleet install-engine")


# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃  LAYER 4 — TLG: produce the analysis results & render to HTML         ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
print("\n━━ Layer 4 · Render ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

# Compute the Analysis Results Dataset (ARD)
ard = adae.tlg.ae.t_summary(spec=ae_spec, adsl=adsl)

# Also generate via the inline builder (header rows variant)
ard_builder = (
    adae.tlg.ae.population(adsl, adsl_filter=pl.col("SAFFL") == "Y")
    .by("TRTA")
    .header_rows(
        [
            OverallStat(label="Subjects with any AE"),
            OverallStat(label="Subjects with ≥1 SAE", filter=pl.col("AESER") == "Y"),
        ]
    )
    .rows(["AEBODSYS", "AEDECOD"])
    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
    .pools([GroupPool(label="Total", arms="*")])
    .column_order(
        [
            "Placebo",
            "Xanomeline Low Dose",
            "Xanomeline High Dose",
            "Total",
        ]
    )
    .to_ard()
)

print(f"  ARD (spec)    : {ard.shape[0]} rows × {ard.shape[1]} cols")
print(f"  ARD (builder) : {ard_builder.shape[0]} rows × {ard_builder.shape[1]} cols")

# Render to HTML
meta = RenderMetadata(
    title="Table 14.3.1.1",
    subtitle="Summary of Adverse Events by System Organ Class and Preferred Term",
    footnotes=[
        "Source: ADAE",
        "Population: Safety (SAFFL=Y)",
        "Generated by Fleet Raw-to-Render (R2R) pipeline",
    ],
)
model = ard_to_table_model(ard, meta)
html = render_html(model)

html_path = OUT / "ae_r2r.html"
html_path.write_text(html, encoding="utf-8")


# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃  Summary                                                              ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
print("\n━━ R2R Complete ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print(f"  ADSL (input)     : {adsl.shape[0]} subjects (pre-built)")
print(f"  Raw  → SDTM AE   : {ae_raw.shape[0]} raw rows → {ae.shape[0]} SDTM records")
print(f"  SDTM → ADaM ADAE : {ae.shape[0]} records → {adae.shape[0]} analysis records")
print(f"  ADaM → ARD       : {adae.shape[0]} records → {ard.shape[0]} result rows")
print(f"  ARD  → HTML      : {len(html):,} characters → {html_path}")
print()
print("  One file. One domain. Raw to Render.")
