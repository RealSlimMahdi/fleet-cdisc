"""
Fleet End-to-End Multi-Domain Example

This script demonstrates creating DM, VS, and AE SDTM datasets from raw mock data,
and subsequently deriving ADSL and ADVS ADaM datasets from those SDTMs.
"""

import polars as pl

import fleet  # noqa: F401  — register namespace extensions
from specs.cdiscpilot01.sdtm.codelists import SEX, VSTESTCD


def main():
    print("--- 1. Loading Raw Mock Data ---")
    raw_dm = pl.DataFrame(
        {
            "subject_id": ["S001", "S002"],
            "sex": ["M", "F"],
            "dob": ["1980-01-01", "1992-05-15"],
            "arm": ["Drug A", "Placebo"],
        }
    )

    raw_vs = pl.DataFrame(
        {
            "subject_id": ["S001", "S001", "S002", "S002"],
            "test_name": ["Weight", "Heart Rate", "Weight", "Heart Rate"],
            "result": [80.5, 72, 65.0, 88],
            "date": ["2023-01-01", "2023-01-01", "2023-01-02", "2023-01-02"],
        }
    )

    raw_ae = pl.DataFrame(
        {
            "subject_id": ["S001", "S002"],
            "ae_term": ["Headache", "Nausea"],
            "start_date": ["2023-01-05", "2023-01-04"],
        }
    )

    print("--- 2. Deriving SDTM ---")
    dm = (
        raw_dm.sdtm.hardcode_no_ct("DOMAIN", value="DM")  # type: ignore[attr-defined]  # runtime namespace registered by fleet
        .assign_no_ct("USUBJID", source="subject_id")
        .assign_no_ct("ARM", source="arm")
        .assign_ct("SEX", source="sex", ct_codelist=SEX, ct_mapping={"M": "M", "F": "F"})
        .date("BRTHDTC", source="dob")
        .to_frame()
    )
    print("\nDM Dataset:")
    print(dm)

    vs = (
        raw_vs.sdtm.hardcode_no_ct("DOMAIN", value="VS")  # type: ignore[attr-defined]  # runtime namespace registered by fleet
        .assign_no_ct("USUBJID", source="subject_id")
        .assign_ct(
            "VSTESTCD",
            source="test_name",
            ct_codelist=VSTESTCD,
            ct_mapping={"Weight": "WEIGHT", "Heart Rate": "HR"},
        )
        .assign_no_ct("VSSTRESN", source="result")
        .date("VSDTC", source="date")
        .to_frame()
    )
    print("\nVS Dataset:")
    print(vs)

    ae = (
        raw_ae.sdtm.hardcode_no_ct("DOMAIN", value="AE")  # type: ignore[attr-defined]  # runtime namespace registered by fleet
        .assign_no_ct("USUBJID", source="subject_id")
        .assign_no_ct("AEDECOD", source="ae_term")
        .date("AESTDTC", source="start_date")
        .to_frame()
    )
    print("\nAE Dataset:")
    print(ae)

    print("--- 3. Deriving ADaM ---")
    adsl = (
        dm.adam.adsl.source("USUBJID")  # type: ignore[attr-defined]  # runtime namespace registered by fleet
        .source("ARM")
        .source("SEX")
        .first_date("TRTSDT", from_dataset=ae, date_col="AESTDTC")
        .to_frame()
    )
    print("\nADSL Dataset:")
    print(adsl)

    vs_with_adsl = vs.join(adsl.select(["USUBJID", "TRTSDT"]), on="USUBJID", how="left")

    advs = (
        vs_with_adsl.adam.source("USUBJID")  # type: ignore[attr-defined]  # runtime namespace registered by fleet
        .source("VSTESTCD")
        .source("VSSTRESN")
        .derivation("ABLFL", expression=pl.lit("Y"))
        .baseline("BASE", aval="VSSTRESN", baseline_flag="ABLFL", groups=["USUBJID", "VSTESTCD"])
        .to_frame()
    )
    print("\nADVS Dataset:")
    print(advs)

    # ── Export to CDISC Dataset-JSON v1.1 ────────────────────────────── #
    print("\n--- 4. Exporting Dataset-JSON ---")
    from pathlib import Path

    from fleet.io import save_dataset_json

    out = Path("outputs/cdiscpilot01")
    for name, df in [("DM", dm), ("VS", vs), ("AE", ae), ("ADSL", adsl), ("ADVS", advs)]:
        p = save_dataset_json(df, out / f"{name.lower()}.json", domain=name)
        print(f"  {name:<6} → {p}")


if __name__ == "__main__":
    main()
