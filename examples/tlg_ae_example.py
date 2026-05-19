"""
TLG Example — AE summary tables from CDISCPILOT01.

Demonstrates three approaches:
  1. **Default spec** — zero-config AE summary using standard column names
  2. **Custom spec**  — declarative spec override with pooled treatment arms,
     additional statistics, custom row hierarchy, and column ordering
  3. **Inline builder** — fluent API alternative to spec-driven approach

The script:
  a) Loads raw CDISCPILOT01 data and builds SDTM AE + DM
  b) Derives a minimal ADSL and ADAE (reusing the Fleet pipeline patterns)
  c) Produces an AE summary ARD (default)
  d) Produces an AE summary ARD (custom spec with pools)
  e) Produces an AE summary ARD (inline builder with header rows)
  f) Produces an AE listing (custom spec)

Run from repo root:
    uv run python examples/tlg_ae_example.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl

# Show full ARD tables in the terminal
pl.Config.set_tbl_cols(20)
pl.Config.set_tbl_rows(200)
pl.Config.set_tbl_width_chars(220)

import fleet  # noqa: E402, F401 — registers .sdtm / .adam / .tlg namespaces
from fleet.tlg import (  # noqa: E402
    AEListingSpec,
    AESummarySpec,
    Column,
    GroupPool,
    OverallStat,
    RenderMetadata,
    Row,
    Statistic,
    ard_to_table_model,
    render_html,
)
from specs.cdiscpilot01.sdtm.codelists import ETHNIC, RACE, SEX  # noqa: E402

# ════════════════════════════════════════════════════════════════════════════
# 1. Raw data (inline)
# ════════════════════════════════════════════════════════════════════════════
print("══ 1. Load raw data ═════════════════════════════════════════════════════")
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

print(f"   dm_raw : {dm_raw.shape[0]:>3} rows  ×  {dm_raw.shape[1]} cols")
print(f"   ae_raw : {ae_raw.shape[0]:>3} rows  ×  {ae_raw.shape[1]} cols")


# ════════════════════════════════════════════════════════════════════════════
# 2. Build SDTM DM
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 2. SDTM DM ══════════════════════════════════════════════════════════")
dm = (
    dm_raw.sdtm.hardcode_no_ct("STUDYID", value="CDISCPILOT01")
    .hardcode_no_ct("DOMAIN", value="DM")
    .assign_no_ct("USUBJID", source="patient_number")
    .assign_no_ct("AGE", source="age")
    .assign_ct("SEX", source="sex", ct_codelist=SEX, ct_mapping={"F": "F", "M": "M"})
    .assign_ct(
        "RACE",
        source="race",
        ct_codelist=RACE,
        ct_mapping={
            "WHITE": "WHITE",
            "BLACK OR AFRICAN AMERICAN": "BLACK OR AFRICAN AMERICAN",
        },
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
    .assign_no_ct("ARM", source="arm_description")
    .date("RFSTDTC", source="first_dose_date")
    .date("RFENDTC", source="last_dose_date")
    .to_frame()
)
print(f"   {dm.shape[0]} subjects × {dm.shape[1]} variables")


# ════════════════════════════════════════════════════════════════════════════
# 3. Build SDTM AE
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 3. SDTM AE ══════════════════════════════════════════════════════════")
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
    .to_frame()
)
print(f"   {ae.shape[0]} records × {ae.shape[1]} variables")


# ════════════════════════════════════════════════════════════════════════════
# 4. Derive minimal ADSL (for Big-N denominators)
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 4. ADSL (minimal) ═══════════════════════════════════════════════════")
adsl = (
    dm.adam.adsl.source("STUDYID")
    .source("USUBJID")
    .source("AGE")
    .source("SEX")
    .source("RACE")
    .source("ARM")
    .rename("TRT01P", source="ARM")
    .date("TRTSDT", source="RFSTDTC")
    .date("TRTEDT", source="RFENDTC")
    .derivation(
        "SAFFL",
        expression='pl.when(pl.col("TRTSDT").is_not_null()).then(pl.lit("Y")).otherwise(pl.lit("N"))',
    )
    .to_frame()
)
# Use TRT01P as TRTA for summary tables
adsl = adsl.with_columns(pl.col("TRT01P").alias("TRTA"))

print(f"   {adsl.shape[0]} subjects × {adsl.shape[1]} variables")
print(f"   Arms: {sorted(adsl['TRTA'].unique().to_list())}")
print(f"   SAFFL=Y: {(adsl['SAFFL'] == 'Y').sum()} / {adsl.shape[0]}")


# ════════════════════════════════════════════════════════════════════════════
# 5. Derive ADAE (from SDTM AE + ADSL treatment info)
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 5. ADAE ═════════════════════════════════════════════════════════════")
_adsl_trt = adsl.select(["USUBJID", "TRTSDT", "TRTEDT", "TRT01P", "TRTA", "SAFFL"])
ae_with_trt = ae.join(_adsl_trt, on="USUBJID", how="left")

adae = (
    ae_with_trt.adam.source("STUDYID")
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
    .to_frame()
    .adam.occds.treatment_emergent(
        "TRTEMFL", start_date="AESTDTC", trtsdt="TRTSDT", trtedt="TRTEDT"
    )
    .seq("ASEQ", groups=["USUBJID"])
    .to_frame()
)

# Derive AEDECOD and AEBODSYS for TLG consumption.
# In a real study these come from MedDRA coding; here we simulate them.
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

print(f"   {adae.shape[0]} records × {adae.shape[1]} variables")
print(f"   Columns: {adae.columns}")
print(f"   AE terms: {sorted(adae['AEDECOD'].unique().to_list())}")
print(f"   Body systems: {sorted(adae['AEBODSYS'].unique().to_list())}")


# ════════════════════════════════════════════════════════════════════════════
# 6. AE Summary — DEFAULT spec (zero-config)
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 6. AE Summary — DEFAULT (zero-config) ═══════════════════════════════")
print("   adae.tlg.ae.t_summary(groupby='TRTA', adsl=adsl)")
print()

ard_default = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl)

print(ard_default)
print(f"\n   ARD shape: {ard_default.shape[0]} rows × {ard_default.shape[1]} cols")
print(f"   Arms in output: {sorted(ard_default['group1_level'].unique().to_list())}")


# ════════════════════════════════════════════════════════════════════════════
# 7. AE Summary — CUSTOM spec (declarative override)
#    Adds:
#      • Pooled "All Xanomeline" and "Total" treatment groups
#      • Event count statistic alongside n and %
#      • Serious AE sub-analysis row
#      • Explicit column ordering
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 7. AE Summary — CUSTOM spec (with pools & extra stats) ══════════════")

custom_spec = AESummarySpec(
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

print("   Spec:")
print(f"     rows       = {[r.field for r in custom_spec.rows]}")
print(f"     statistics = {[s.value for s in custom_spec.statistics]}")
print(f"     pools      = {[p.label for p in custom_spec.pools]}")
print()

ard_custom = adae.tlg.ae.t_summary(spec=custom_spec, adsl=adsl)

print(ard_custom)
print(f"\n   ARD shape: {ard_custom.shape[0]} rows × {ard_custom.shape[1]} cols")
print(f"   Arms in output: {sorted(ard_custom['group1_level'].unique().to_list())}")

# Show Big-N row for each arm
big_n_rows = ard_custom.filter(pl.col("stat_name") == "N")
print("\n   Big-N denominators:")
for row in big_n_rows.iter_rows(named=True):
    print(f"     {row['group1_level']:>25s}  N = {int(row['stat'])}")


# ════════════════════════════════════════════════════════════════════════════
# 7b. AE Summary — INLINE BUILDER with header rows
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 7b. AE Summary — INLINE BUILDER (with header rows) ═════════════════")

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
    .pools(
        [
            GroupPool(label="All Xanomeline", arms=["Xanomeline Low Dose", "Xanomeline High Dose"]),
            GroupPool(label="Total", arms="*"),
        ]
    )
    .column_order(
        [
            "Placebo",
            "Xanomeline Low Dose",
            "Xanomeline High Dose",
            "All Xanomeline",
            "Total",
        ]
    )
    .to_ard()
)

print(ard_builder)
print(f"\n   ARD shape: {ard_builder.shape[0]} rows × {ard_builder.shape[1]} cols")

# Show header rows
hdr = ard_builder.filter((pl.col("variable") == "") & (pl.col("stat_name") != "N"))
print(f"   Header rows: {hdr['variable_level'].unique().to_list()}")


# ════════════════════════════════════════════════════════════════════════════
# 8. AE Listing — CUSTOM spec
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 8. AE Listing — CUSTOM spec ═════════════════════════════════════════")

listing_spec = AEListingSpec(
    columns=[
        Column(field="USUBJID", label="Subject"),
        Column(field="TRTA", label="Treatment"),
        Column(field="AEBODSYS", label="Body System"),
        Column(field="AEDECOD", label="Preferred Term"),
        Column(field="AESEV", label="Severity"),
        Column(field="AESER", label="Serious"),
        Column(field="ASTDT", label="Start Date"),
        Column(field="AEACN", label="Action Taken"),
    ],
    sort_by=["USUBJID", "ASTDT"],
    dataset_filter=pl.col("SAFFL") == "Y",
)

listing = adae.tlg.ae.l_listing(spec=listing_spec)

print(listing)
print(f"\n   Listing shape: {listing.shape[0]} rows × {listing.shape[1]} cols")


# ════════════════════════════════════════════════════════════════════════════
# 9. Pre-validation check
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 9. Pre-validation check ═════════════════════════════════════════════")
report = adae.tlg.ae.check(spec=custom_spec)
if report:
    for msg in report:
        print(f"   ⚠ {msg}")
else:
    print("   ✓ All checks passed — data is ready for the custom AE summary.")


# ════════════════════════════════════════════════════════════════════════════
# 10. Spec YAML round-trip
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 10. Spec YAML round-trip ════════════════════════════════════════════")
yaml_str = custom_spec.to_yaml()
print(yaml_str)

restored = AESummarySpec.from_yaml(yaml_str)
assert restored.rows == custom_spec.rows
assert restored.statistics == custom_spec.statistics
assert restored.pools == custom_spec.pools
print("   ✓ Round-trip: to_yaml() → from_yaml() produces identical spec.")


# ════════════════════════════════════════════════════════════════════════════
# 11. HTML export — standalone render pipeline
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 11. HTML export ═════════════════════════════════════════════════════")

meta = RenderMetadata(
    title="Table 14.3.1.1",
    subtitle="Summary of Adverse Events by System Organ Class and Preferred Term",
    footnotes=["Source: ADAE", "Population: Safety (SAFFL=Y)"],
)
model = ard_to_table_model(ard_custom, meta)
html = render_html(model)
html_path = Path("outputs/cdiscpilot01/ae_summary.html")
html_path.write_text(html, encoding="utf-8")
print(f"   Written {len(html):,} chars → {html_path}")
print(f"   Model: {len(model.columns)} columns, {len(model.rows)} display rows")


# ════════════════════════════════════════════════════════════════════════════
# 12. HTML export — builder .to_html() shortcut
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 12. Builder .to_html() shortcut ═════════════════════════════════════")

builder_html = (
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
    .pools(
        [
            GroupPool(label="Total", arms="*"),
        ]
    )
    .column_order(["Placebo", "Xanomeline Low Dose", "Xanomeline High Dose", "Total"])
    .to_html(
        path="outputs/cdiscpilot01/ae_summary_builder.html",
        metadata=RenderMetadata(
            title="Table 14.3.1.1 (Builder)",
            subtitle="AE Summary — Safety Population",
        ),
    )
)
print(f"   Written {len(builder_html):,} chars → outputs/cdiscpilot01/ae_summary_builder.html")


# ════════════════════════════════════════════════════════════════════════════
# 13. HTML injection — wrapper template
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 13. HTML injection — wrapper template ═══════════════════════════════")

wrapper = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Sponsor Portal</title></head>
<body>
<h1>Clinical Report</h1>
{table}
<footer>Confidential</footer>
</body></html>"""

injected = render_html(model, html_wrapper=wrapper)
injected_path = Path("outputs/cdiscpilot01/ae_summary_injected.html")
injected_path.write_text(injected, encoding="utf-8")
print(f"   Written {len(injected):,} chars → {injected_path}")
print("   HTML was injected at {{table}} placeholder in wrapper template.")


# ════════════════════════════════════════════════════════════════════════════
# 14. PPTX export — editable slide deck
# ════════════════════════════════════════════════════════════════════════════
print("\n══ 14. PPTX export — editable slide deck ═══════════════════════════════")

try:
    pptx_path = (
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
        .column_order(["Placebo", "Xanomeline Low Dose", "Xanomeline High Dose", "Total"])
        .to_pptx(
            "outputs/cdiscpilot01/ae_summary.pptx",
            metadata=RenderMetadata(
                title="Table 14.3.1.1",
                subtitle="AE Summary — Safety Population",
                footnotes=["Source: ADAE", "Population: Safety (SAFFL=Y)"],
            ),
        )
    )
    print(f"   Written → {pptx_path}")
except ImportError as e:
    print(f"   Skipped (optional dependency missing): {e}")


print("\n════════════════════════════════════════════════════════════════════════")
print("  TLG example complete!")
print("════════════════════════════════════════════════════════════════════════")
