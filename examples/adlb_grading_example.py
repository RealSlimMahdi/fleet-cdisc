#!/usr/bin/env python3
"""ADLB toxicity grading example — CTCAE and DAIDS.

Demonstrates:
  - NCI CTCAE v5 grading for lab parameters (Anemia, ALT, Creatinine)
  - Low and high direction grading with .atoxgr()
  - Combining grades into signed ATOXGR with .combine_grades()
  - Listing available grading systems
  - Switching to DAIDS grading
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl

import fleet  # noqa: F401  — registers the .adam namespace
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
    adlb = pl.DataFrame(
        {
            "USUBJID": ["01-001"] * 5 + ["01-002"] * 5,
            "PARAMCD": ["HGB", "HGB", "ALT", "ALT", "CREAT"] * 2,
            "ATOXDSCL": ["Anemia", "Anemia", None, None, None] * 2,
            "ATOXDSCH": [
                None,
                None,
                "Alanine aminotransferase increased",
                "Alanine aminotransferase increased",
                "Creatinine increased",
            ]
            * 2,
            "AVAL": [
                75.0,  # 01-001 HGB: <80 → Anemia G3
                130.0,  # 01-001 HGB: <LLN(140) → Anemia G1
                250.0,  # 01-001 ALT: >5×ULN(200) → ALT G3
                35.0,  # 01-001 ALT: ≤ULN(40) → G0
                300.0,  # 01-001 CREAT: >3×BASE(240) → G3
                90.0,  # 01-002 HGB: <100 → Anemia G2
                145.0,  # 01-002 HGB: ≥LLN(140) → G0
                900.0,  # 01-002 ALT: >20×ULN(800) → ALT G4
                42.0,  # 01-002 ALT: >ULN(40) → ALT G1
                50.0,  # 01-002 CREAT: ≤ULN(100) → G0
            ],
            "ANRLO": [140.0, 140.0, None, None, None] * 2,
            "ANRHI": [None, None, 40.0, 40.0, 100.0] * 2,
            "BASE": [None, None, 35.0, 35.0, 80.0] * 2,
            "BNRIND": [None, None, "NORMAL", "NORMAL", "NORMAL"] * 2,
            "AVALU": ["g/L", "g/L", None, None, None] * 2,
        }
    )

    print("── Input ADLB data ──")
    print(adlb.select("USUBJID", "PARAMCD", "AVAL", "ANRLO", "ANRHI"))
    print()

    # ── 2. CTCAE v5 grading pipeline ──────────────────────────────────
    # Step 1: Grade low-direction parameters (Anemia — needs unit match)
    # Step 2: Grade high-direction parameters (ALT, Creatinine)
    # Step 3: Combine low + high into signed ATOXGR
    result = (
        adlb.adam.atoxgr(  # type: ignore[attr-defined]
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
    daids_df = pl.DataFrame(
        {
            "USUBJID": ["01-001", "01-001", "01-002", "01-002"],
            "PARAMCD": ["ALT", "CREAT", "ALT", "CREAT"],
            "ATOXDSCH": [
                "ALT, High",
                "Creatinine, High",
                "ALT, High",
                "Creatinine, High",
            ],
            "AVAL": [250.0, 200.0, 50.0, 95.0],
            "ANRHI": [40.0, 100.0, 40.0, 100.0],
            "BASE": [35.0, 80.0, 35.0, 80.0],
            "BNRIND": ["NORMAL", "NORMAL", "NORMAL", "NORMAL"],
        }
    )

    daids_result = daids_df.adam.atoxgr(  # type: ignore[attr-defined]
        "ATOXGRH",
        system="daids",
        direction="H",
        term_var="ATOXDSCH",
    ).to_frame()

    print("── DAIDS grading results (high direction only) ──")
    print(daids_result.select("USUBJID", "PARAMCD", "AVAL", "ATOXGRH").sort("USUBJID", "PARAMCD"))


if __name__ == "__main__":
    main()
