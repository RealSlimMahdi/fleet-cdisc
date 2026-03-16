"""
Fleet End-to-End Multi-Domain Example

This script demonstrates creating DM, VS, and AE SDTM datasets from raw mock data, 
and subsequently deriving ADSL and ADVS ADaM datasets from those SDTMs.
"""

import polars as pl
import fleet

def main():
    print("--- 1. Loading Raw Mock Data ---")
    raw_dm = pl.DataFrame({
        "subject_id": ["S001", "S002"],
        "sex": ["M", "F"],
        "dob": ["1980-01-01", "1992-05-15"],
        "arm": ["Drug A", "Placebo"]
    })

    raw_vs = pl.DataFrame({
        "subject_id": ["S001", "S001", "S002", "S002"],
        "test_name": ["Weight", "Heart Rate", "Weight", "Heart Rate"],
        "result": [80.5, 72, 65.0, 88],
        "date": ["2023-01-01", "2023-01-01", "2023-01-02", "2023-01-02"]
    })

    raw_ae = pl.DataFrame({
        "subject_id": ["S001", "S002"],
        "ae_term": ["Headache", "Nausea"],
        "start_date": ["2023-01-05", "2023-01-04"]
    })

    print("--- 2. Deriving SDTM ---")
    dm = (
        raw_dm.sdtm  # type: ignore[attr-defined]  # runtime namespace registered by fleet
        .hardcode_no_ct("DOMAIN", value="DM")
        .assign_no_ct("USUBJID", source="subject_id")
        .assign_no_ct("ARM", source="arm")
        .assign_ct("SEX", source="sex", ct_codelist="C66731", ct_mapping={"M": "M", "F": "F"})
        .assign_datetime("BRTHDTC", source="dob", mode="date")
        .to_frame()
    )
    print("\nDM Dataset:")
    print(dm)

    vs = (
        raw_vs.sdtm  # type: ignore[attr-defined]  # runtime namespace registered by fleet
        .hardcode_no_ct("DOMAIN", value="VS")
        .assign_no_ct("USUBJID", source="subject_id")
        .assign_ct(
            "VSTESTCD", source="test_name",
            ct_codelist="C66741", 
            ct_mapping={"Weight": "WEIGHT", "Heart Rate": "HR"}
        )
        .assign_no_ct("VSSTRESN", source="result")
        .assign_datetime("VSDTC", source="date", mode="date")
        .to_frame()
    )
    print("\nVS Dataset:")
    print(vs)

    ae = (
        raw_ae.sdtm  # type: ignore[attr-defined]  # runtime namespace registered by fleet
        .hardcode_no_ct("DOMAIN", value="AE")
        .assign_no_ct("USUBJID", source="subject_id")
        .assign_no_ct("AEDECOD", source="ae_term")
        .assign_datetime("AESTDTC", source="start_date", mode="date")
        .to_frame()
    )
    print("\nAE Dataset:")
    print(ae)

    print("--- 3. Deriving ADaM ---")
    adsl = (
        dm.adam.adsl  # type: ignore[attr-defined]  # runtime namespace registered by fleet
        .source("USUBJID")
        .source("ARM")
        .source("SEX")
        .first_date("TRTSDT", from_dataset=ae, date_col="AESTDTC")
        .to_frame()
    )
    print("\nADSL Dataset:")
    print(adsl)

    vs_with_adsl = vs.join(adsl.select(["USUBJID", "TRTSDT"]), on="USUBJID", how="left")

    advs = (
        vs_with_adsl.adam  # type: ignore[attr-defined]  # runtime namespace registered by fleet
        .source("USUBJID")
        .source("VSTESTCD")
        .source("VSSTRESN")
        .derivation("ABLFL", expression=pl.lit("Y"))
        .baseline("BASE", aval="VSSTRESN", baseline_flag="ABLFL")
        .to_frame()
    )
    print("\nADVS Dataset:")
    print(advs)

if __name__ == "__main__":
    main()
