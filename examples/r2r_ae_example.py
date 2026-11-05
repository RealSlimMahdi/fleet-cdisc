"""
Raw-to-Render (R2R) — AE domain in a single program.

Demonstrates the **R2R strategy**: one self-contained script that takes
raw adverse-event data all the way to a rendered HTML table, traversing
every CDISC layer in sequence:

    Raw AE CSV  →  SDTM AE  →  ADaM ADAE  →  QC  →  Validate  →  TLG (HTML)

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

import fleet  # registers .sdtm / .adam / .tlg namespaces
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
adsl = fleet.frame(
    pl.from_repr("""\
┌─────────────┬─────┬─────┬───────────────────────────┬──────────────────────┬────────────┬────────────┬───────┐
│ USUBJID     ┆ AGE ┆ SEX ┆ RACE                      ┆ TRT01A               ┆ TRTSDT     ┆ TRTEDT     ┆ SAFFL │
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
)
print(f"  ADSL (inline)    : {adsl.shape[0]} subjects × {adsl.shape[1]} variables")
print(f"         Arms: {sorted(adsl['TRT01A'].unique().to_list())}")

# Raw AE extract — the only raw data this script owns
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
print(f"  ae_raw           : {ae_raw.shape[0]:>3} rows × {ae_raw.shape[1]} cols")


# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃  LAYER 1 — SDTM AE: standardise raw AE into an SDTM-shaped domain     ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
print("\n━━ Layer 1 · SDTM AE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

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
    .seq("AESEQ", order_by=["AESTDTC"])
    # Only AE variables, in SDTMIG order: the raw columns are not written to ae.json.
    .keep(
        "STUDYID",
        "DOMAIN",
        "USUBJID",
        "AESEQ",
        "AETERM",
        "AESEV",
        "AESER",
        "AEACN",
        "AEREL",
        "AEOUT",
        "AESTDTC",
        "AEENDTC",
    )
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
_adsl_trt = adsl.select(["USUBJID", "TRTSDT", "TRTEDT", "TRT01A", "SAFFL"])
ae_with_trt = fleet.frame(ae.join(_adsl_trt, on="USUBJID", how="left"))

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
    # Parallel design: the actual arm of the record is the ADSL actual arm.
    .assign("TRTA", source="TRT01A")
    .source("SAFFL")
    # admiral ad_adae.R: partial start to the first day but not before TRTSDT,
    # partial end to the last day. The SAP decides the rule.
    .date("ASTDT", source="AESTDTC", min_date="TRTSDT")
    .date("AENDT", source="AEENDTC", impute="last")
    .study_day("ADY", date_col="ASTDT", ref_col="TRTSDT")
)

_adae_occds_ns = (
    _adae_base_ns.to_frame()
    .adam.occds("ADAE")
    .treatment_emergent(
        "TRTEMFL",
        start_date="ASTDT",
        end_date="AENDT",
        trtsdt="TRTSDT",
        trtedt="TRTEDT",
        end_window=0,  # the SAP decides the window after the last dose
    )
    .recode("AESEVN", source="AESEV", recode_map={"MILD": 1, "MODERATE": 2, "SEVERE": 3})
    .flag(
        "ANL01FL",
        criteria="max",
        value_col="AESEVN",
        by=["USUBJID", "AETERM"],
    )
    .seq("ASEQ", by=["USUBJID"])
)

adae = _adae_occds_ns.to_frame()

# Simulate MedDRA coding (in a real study these come from a dictionary)
adae = fleet.frame(
    adae.with_columns(
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
# ┃  LAYER 3 — QC: independent re-derivation, then compare                ┃
# ┃                                                                       ┃
# ┃  This is `adae_qc.sas`.  A second programmer starts from the same     ┃
# ┃  SDTM AE + ADSL inputs, writes the analysis variables from scratch    ┃
# ┃  in plain Polars, and ends the chain in `.compare()` — Fleet's        ┃
# ┃  PROC COMPARE.  Nothing is read from the production chain above.      ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
print("\n━━ Layer 3 · QC ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

# The QC codes terms against a MedDRA extract instead of title-casing them.
QC_MEDDRA = {
    "HEADACHE": ("Headache", "NERVOUS SYSTEM DISORDERS"),
    "NAUSEA": ("Nausea", "GASTROINTESTINAL DISORDERS"),
    "DIZZINESS": ("Dizziness", "NERVOUS SYSTEM DISORDERS"),
    "FATIGUE": ("Fatigue", "GENERAL DISORDERS"),
    "APPLICATION SITE ERYTHEMA": ("Application Site Erythema", "OTHER"),
}

_qc_start = pl.col("AESTDTC").str.to_date(strict=False)
_qc_trtsdt = pl.col("TRTSDT").str.to_date(strict=False)
_qc_offset = (_qc_start - _qc_trtsdt).dt.total_days()
# Severity ranked inline, so ANL01FL never depends on production's AESEVN.
_qc_sevn = pl.col("AESEV").replace_strict(
    {"MILD": 1, "MODERATE": 2, "SEVERE": 3}, default=None, return_dtype=pl.Int64
)

adae_qc_ns = (
    ae_with_trt.adam.occds("ADAE")
    .derivation("ASTDT", expression=_qc_start)
    .derivation("AENDT", expression=pl.col("AEENDTC").str.to_date(strict=False))
    .derivation(
        "ADY",
        expression=pl.when(_qc_offset >= 0)  # CDISC study day has no day 0
        .then(_qc_offset + 1)
        .otherwise(_qc_offset)
        .cast(pl.Int64),
    )
    .derivation(
        "TRTEMFL",
        expression=pl.when(
            _qc_start.is_between(_qc_trtsdt, pl.col("TRTEDT").str.to_date(strict=False))
        ).then(pl.lit("Y")),
    )
    .derivation(
        "ANL01FL",
        expression=pl.when(_qc_sevn == _qc_sevn.max().over(["USUBJID", "AETERM"])).then(
            pl.lit("Y")
        ),
    )
    .derivation("ASEQ", expression=pl.col("ASTDT").rank("ordinal").over("USUBJID").cast(pl.Int64))
    .recode("AEDECOD", source="AETERM", recode_map={k: v[0] for k, v in QC_MEDDRA.items()})
    .recode("AEBODSYS", source="AETERM", recode_map={k: v[1] for k, v in QC_MEDDRA.items()})
    .compare(
        adae,
        keys=["USUBJID", "AESEQ"],
        # The QC scope: every analysis variable it re-derived.  Production's
        # imputation flags and its AESEVN intermediate are out of scope.
        variables=["ASTDT", "AENDT", "ADY", "TRTEMFL", "ANL01FL", "ASEQ", "AEDECOD", "AEBODSYS"],
        base_name="ADAE (production)",
        candidate_name="ADAE (QC)",
        on_fail="raise",  # the QC gate: a difference stops the script
    )
)

adae_qc = adae_qc_ns.to_frame()
_qc_report = adae_qc_ns.last_comparison
assert _qc_report is not None
print(f"  ADAE (QC) : {adae_qc.shape[0]} records × {adae_qc.shape[1]} variables")


# ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
# ┃  LAYER 4 — Validate: pre-flight checks before table generation        ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
print("\n━━ Layer 4 · Validate ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

# TLG-level pre-validation (lightweight, no engine required)
ae_spec = AESummarySpec(
    rows=[
        Row(field="AEBODSYS", label="System Organ Class"),
        Row(field="AEDECOD", label="Preferred Term"),
    ],
    header_rows=[
        OverallStat(label="Subjects with at least one serious AE", filter='pl.col("AESER") == "Y"'),
    ],
    columns=["TRTA"],
    # ADAE holds the arm as TRTA, ADSL as TRT01A: the big N reads TRT01A.
    adsl_group_col="TRT01A",
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
# ┃  LAYER 5 — TLG: produce the analysis results & render to HTML         ┃
# ┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
print("\n━━ Layer 5 · Render ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

# Compute the Analysis Results Dataset (ARD)
ard = adae.tlg.ae.t_summary(spec=ae_spec, adsl=adsl)

# Also generate via the inline builder (header rows variant)
ard_builder = (
    adae.tlg.ae.population(adsl, adsl_filter=pl.col("SAFFL") == "Y", group_col="TRT01A")
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
print(
    f"  ADaM → QC        : {len(_qc_report.variables.compared)} variables compared → "
    f"{'EQUAL' if _qc_report.is_equal else 'NOT EQUAL'}"
)
print(f"  ADaM → ARD       : {adae.shape[0]} records → {ard.shape[0]} result rows")
print(f"  ARD  → HTML      : {len(html):,} characters → {html_path}")
print()
print("  One file. One domain. Raw to Render.")
