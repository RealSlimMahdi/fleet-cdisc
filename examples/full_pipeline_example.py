"""
Fleet End-to-End Multi-Domain Example

This script demonstrates creating DM, VS, and AE SDTM datasets from raw mock data,
and subsequently deriving ADSL and ADVS ADaM datasets from those SDTMs.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl

import fleet  # registers namespace extensions
from examples.cdiscpilot01.sdtm.codelists import SEX, VSTESTCD


def main():
    print("--- 1. Loading Raw Mock Data ---")
    raw_dm = fleet.frame(
        pl.from_repr("""\
┌────────────┬─────┬────────────┬─────────┐
│ subject_id ┆ sex ┆ dob        ┆ arm     │
│ ---        ┆ --- ┆ ---        ┆ ---     │
│ str        ┆ str ┆ str        ┆ str     │
╞════════════╪═════╪════════════╪═════════╡
│ S001       ┆ M   ┆ 1980-01-01 ┆ Drug A  │
│ S002       ┆ F   ┆ 1992-05-15 ┆ Placebo │
└────────────┴─────┴────────────┴─────────┘
""")
    )

    raw_vs = fleet.frame(
        pl.from_repr("""\
┌────────────┬────────────┬────────┬────────────┐
│ subject_id ┆ test_name  ┆ result ┆ date       │
│ ---        ┆ ---        ┆ ---    ┆ ---        │
│ str        ┆ str        ┆ f64    ┆ str        │
╞════════════╪════════════╪════════╪════════════╡
│ S001       ┆ Weight     ┆ 80.5   ┆ 2023-01-01 │
│ S001       ┆ Heart Rate ┆ 72.0   ┆ 2023-01-01 │
│ S002       ┆ Weight     ┆ 65.0   ┆ 2023-01-02 │
│ S002       ┆ Heart Rate ┆ 88.0   ┆ 2023-01-02 │
└────────────┴────────────┴────────┴────────────┘
""")
    )

    raw_ae = fleet.frame(
        pl.from_repr("""\
┌────────────┬──────────┬────────────┐
│ subject_id ┆ ae_term  ┆ start_date │
│ ---        ┆ ---      ┆ ---        │
│ str        ┆ str      ┆ str        │
╞════════════╪══════════╪════════════╡
│ S001       ┆ Headache ┆ 2023-01-05 │
│ S002       ┆ Nausea   ┆ 2023-01-04 │
└────────────┴──────────┴────────────┘
""")
    )

    print("--- 2. Deriving SDTM ---")
    dm = (
        raw_dm.sdtm.assign("DOMAIN", value="DM")
        .assign("USUBJID", source="subject_id")
        .assign("ARM", source="arm")
        .assign("SEX", source="sex", ct=SEX, ct_map={"M": "M", "F": "F"})
        .date("BRTHDTC", source="dob")
        .to_frame()
    )
    print("\nDM Dataset:")
    print(dm)

    vs = (
        raw_vs.sdtm.assign("DOMAIN", value="VS")
        .assign("USUBJID", source="subject_id")
        .assign(
            "VSTESTCD",
            source="test_name",
            ct=VSTESTCD,
            ct_map={"Weight": "WEIGHT", "Heart Rate": "HR"},
        )
        .assign("VSSTRESN", source="result")
        .date("VSDTC", source="date")
        .to_frame()
    )
    print("\nVS Dataset:")
    print(vs)

    ae = (
        raw_ae.sdtm.assign("DOMAIN", value="AE")
        .assign("USUBJID", source="subject_id")
        .assign("AEDECOD", source="ae_term")
        .date("AESTDTC", source="start_date")
        .to_frame()
    )
    print("\nAE Dataset:")
    print(ae)

    print("--- 3. Deriving ADaM ---")
    adsl = (
        dm.adam.adsl.source("USUBJID")
        .source("ARM")
        .source("SEX")
        .first_date("TRTSDT", from_dataset=ae, date_col="AESTDTC")
        .to_frame()
    )
    print("\nADSL Dataset:")
    print(adsl)

    vs_with_adsl = fleet.frame(
        vs.join(adsl.select(["USUBJID", "TRTSDT"]), on="USUBJID", how="left")
    )

    advs = (
        vs_with_adsl.adam.source("USUBJID")
        .source("VSTESTCD")
        .source("VSSTRESN")
        .derivation("ABLFL", expression=pl.lit("Y"))
        .baseline("BASE", aval="VSSTRESN", baseline_flag="ABLFL", by=["USUBJID", "VSTESTCD"])
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
