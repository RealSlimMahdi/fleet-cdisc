#!/usr/bin/env python3
"""ADLB toxicity grading example — CTCAE and DAIDS.

Demonstrates:
  - NCI CTCAE v5 grading for lab parameters (Anemia, ALT, Creatinine)
  - Low and high direction grading with .atoxgr()
  - Combining grades into signed ATOXGR with .combine_grades()
  - Listing available grading systems
  - Switching to DAIDS grading
"""

import polars as pl

import fleet  # registers the .adam namespace
from fleet.adam.grading import list_systems


def main() -> None:
    # ── Available grading systems ──────────────────────────────────────
    print("Available grading systems:", list_systems())
    print()

    # ── 1. Synthetic ADLB-like lab data ────────────────────────────────
    # HGB (Anemia) is graded in the LOW direction; ALT and Creatinine
    # are graded HIGH.
    #
    # CTCAE v5 thresholds (SI units):
    #   Anemia:     G3 <80 g/L · G2 <100 g/L · G1 <LLN
    #   ALT incr:   G4 >20×ULN · G3 >5×ULN · G2 >3×ULN · G1 >ULN
    #   Creat incr: G4 >6×ULN · G3 >3×ULN & >3×BASE · G2 >1.5×ULN & >1.5×BASE · G1 >ULN
    adlb = fleet.frame(pl.from_repr("""\
┌─────────┬─────────┬──────────┬────────────────────────────────────┬───────┬───────┬───────┬──────┬────────┬───────┐
│ USUBJID ┆ PARAMCD ┆ ATOXDSCL ┆ ATOXDSCH                           ┆ AVAL  ┆ ANRLO ┆ ANRHI ┆ BASE ┆ BNRIND ┆ AVALU │
│ ---     ┆ ---     ┆ ---      ┆ ---                                ┆ ---   ┆ ---   ┆ ---   ┆ ---  ┆ ---    ┆ ---   │
│ str     ┆ str     ┆ str      ┆ str                                ┆ f64   ┆ f64   ┆ f64   ┆ f64  ┆ str    ┆ str   │
╞═════════╪═════════╪══════════╪════════════════════════════════════╪═══════╪═══════╪═══════╪══════╪════════╪═══════╡
│ 01-001  ┆ HGB     ┆ Anemia   ┆ null                               ┆ 75.0  ┆ 140.0 ┆ null  ┆ null ┆ null   ┆ g/L   │
│ 01-001  ┆ HGB     ┆ Anemia   ┆ null                               ┆ 130.0 ┆ 140.0 ┆ null  ┆ null ┆ null   ┆ g/L   │
│ 01-001  ┆ ALT     ┆ null     ┆ Alanine aminotransferase increased ┆ 250.0 ┆ null  ┆ 40.0  ┆ 35.0 ┆ NORMAL ┆ null  │
│ 01-001  ┆ ALT     ┆ null     ┆ Alanine aminotransferase increased ┆ 35.0  ┆ null  ┆ 40.0  ┆ 35.0 ┆ NORMAL ┆ null  │
│ 01-001  ┆ CREAT   ┆ null     ┆ Creatinine increased               ┆ 300.0 ┆ null  ┆ 100.0 ┆ 80.0 ┆ NORMAL ┆ null  │
│ 01-002  ┆ HGB     ┆ Anemia   ┆ null                               ┆ 90.0  ┆ 140.0 ┆ null  ┆ null ┆ null   ┆ g/L   │
│ 01-002  ┆ HGB     ┆ Anemia   ┆ null                               ┆ 145.0 ┆ 140.0 ┆ null  ┆ null ┆ null   ┆ g/L   │
│ 01-002  ┆ ALT     ┆ null     ┆ Alanine aminotransferase increased ┆ 900.0 ┆ null  ┆ 40.0  ┆ 35.0 ┆ NORMAL ┆ null  │
│ 01-002  ┆ ALT     ┆ null     ┆ Alanine aminotransferase increased ┆ 42.0  ┆ null  ┆ 40.0  ┆ 35.0 ┆ NORMAL ┆ null  │
│ 01-002  ┆ CREAT   ┆ null     ┆ Creatinine increased               ┆ 50.0  ┆ null  ┆ 100.0 ┆ 80.0 ┆ NORMAL ┆ null  │
└─────────┴─────────┴──────────┴────────────────────────────────────┴───────┴───────┴───────┴──────┴────────┴───────┘
"""))

    print("── Input ADLB data ──")
    print(adlb.select("USUBJID", "PARAMCD", "AVAL", "ANRLO", "ANRHI"))
    print()

    # ── 2. CTCAE v5 grading pipeline ──────────────────────────────────
    # Step 1: Grade low-direction parameters (Anemia — needs unit match)
    # Step 2: Grade high-direction parameters (ALT, Creatinine)
    # Step 3: Combine low + high into signed ATOXGR
    result = (
        adlb.adam.atoxgr(
            "ATOXGRL",
            system="ctcae_v5",
            direction="L",
            term_var="ATOXDSCL",
            unit_var="AVALU",
        )
        .atoxgr(
            "ATOXGRH",
            system="ctcae_v5",
            direction="H",
            term_var="ATOXDSCH",
        )
        .combine_grades("ATOXGR")
        .to_frame()
    )

    print("── CTCAE v5 grading results ──")
    print(
        result.select("USUBJID", "PARAMCD", "AVAL", "ATOXGRL", "ATOXGRH", "ATOXGR").sort(
            "USUBJID", "PARAMCD"
        )
    )
    print()

    # ── 3. DAIDS grading comparison ───────────────────────────────────
    # DAIDS uses different term names and thresholds.
    #   ALT, High:        G4 ≥10×ULN · G3 ≥5×ULN · G2 ≥2.5×ULN · G1 ≥1.25×ULN
    #   Creatinine, High: G4 ≥3.5×ULN & ≥2×BASE · G3 >1.8×ULN & ≥1.5×BASE · …
    daids_df = fleet.frame(pl.from_repr("""\
┌─────────┬─────────┬──────────────────┬───────┬───────┬──────┬────────┐
│ USUBJID ┆ PARAMCD ┆ ATOXDSCH         ┆ AVAL  ┆ ANRHI ┆ BASE ┆ BNRIND │
│ ---     ┆ ---     ┆ ---              ┆ ---   ┆ ---   ┆ ---  ┆ ---    │
│ str     ┆ str     ┆ str              ┆ f64   ┆ f64   ┆ f64  ┆ str    │
╞═════════╪═════════╪══════════════════╪═══════╪═══════╪══════╪════════╡
│ 01-001  ┆ ALT     ┆ ALT, High        ┆ 250.0 ┆ 40.0  ┆ 35.0 ┆ NORMAL │
│ 01-001  ┆ CREAT   ┆ Creatinine, High ┆ 200.0 ┆ 100.0 ┆ 80.0 ┆ NORMAL │
│ 01-002  ┆ ALT     ┆ ALT, High        ┆ 50.0  ┆ 40.0  ┆ 35.0 ┆ NORMAL │
│ 01-002  ┆ CREAT   ┆ Creatinine, High ┆ 95.0  ┆ 100.0 ┆ 80.0 ┆ NORMAL │
└─────────┴─────────┴──────────────────┴───────┴───────┴──────┴────────┘
"""))

    daids_result = daids_df.adam.atoxgr(
        "ATOXGRH",
        system="daids",
        direction="H",
        term_var="ATOXDSCH",
    ).to_frame()

    print("── DAIDS grading results (high direction only) ──")
    print(daids_result.select("USUBJID", "PARAMCD", "AVAL", "ATOXGRH").sort("USUBJID", "PARAMCD"))


if __name__ == "__main__":
    main()
