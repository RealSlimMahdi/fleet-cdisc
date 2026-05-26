# End-to-End Walkthrough: Multi-Domain Pipeline

[![Open in Colab](https://img.shields.io/badge/Open_in_Colab-F9AB00?style=for-the-badge&logo=googlecolab&logoColor=white)](https://colab.research.google.com/github/RealSlimMahdi/fleet-cdisc/blob/devel/docs/examples/01_code_driven_pipeline.ipynb)

> **Interactive Playground** — Click the badge above to launch a notebook in Google Colab and experiment with Fleet live, no local setup needed.

This guide walks you through building a complete, code-driven data pipeline. We will take synthetic raw data and map it into three SDTM domains (DM, VS, AE), and then derive two ADaM datasets (ADSL, ADVS).

You can find the full script in the `examples/` directory under `full_pipeline_example.py`.

## 1. Setup and Raw Data

First, let's establish some raw Polars DataFrames that mimic EDC extracts.

```python
import polars as pl
import fleet

# Raw Demographics
raw_dm = pl.from_repr("""
┌────────────┬─────┬────────────┬─────────┐
│ subject_id ┆ sex ┆ dob        ┆ arm     │
│ ---        ┆ --- ┆ ---        ┆ ---     │
│ str        ┆ str ┆ str        ┆ str     │
╞════════════╪═════╪════════════╪═════════╡
│ S001       ┆ M   ┆ 1980-01-01 ┆ Drug A  │
│ S002       ┆ F   ┆ 1992-05-15 ┆ Placebo │
└────────────┴─────┴────────────┴─────────┘
""")

# Raw Vitals
raw_vs = pl.from_repr("""
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

# Raw Adverse Events
raw_ae = pl.from_repr("""
┌────────────┬──────────┬────────────┐
│ subject_id ┆ ae_term  ┆ start_date │
│ ---        ┆ ---      ┆ ---        │
│ str        ┆ str      ┆ str        │
╞════════════╪══════════╪════════════╡
│ S001       ┆ Headache ┆ 2023-01-05 │
│ S002       ┆ Nausea   ┆ 2023-01-04 │
└────────────┴──────────┴────────────┘
""")
```

## 2. SDTM Derivation

We map the raw datasets to SDTM variables using `df.sdtm`.

### DM (Demographics)

```python
dm = (
    raw_dm.sdtm.hardcode_no_ct("DOMAIN", value="DM")
    .assign_no_ct("USUBJID", source="subject_id")
    .assign_no_ct("ARM", source="arm")
    .assign_ct("SEX", source="sex", ct_codelist=SEX, ct_mapping={"M": "M", "F": "F"})
    .assign_dtc("BRTHDTC", source="dob")
    .to_frame()
)
```

### VS (Vital Signs)

```python
vs = (
    raw_vs.sdtm.hardcode_no_ct("DOMAIN", value="VS")
    .assign_no_ct("USUBJID", source="subject_id")
    .assign_ct(
        "VSTESTCD",
        source="test_name",
        ct_codelist=VSTESTCD,
        ct_mapping={"Weight": "WEIGHT", "Heart Rate": "HR"},
    )
    .assign_no_ct("VSSTRESN", source="result")
    .assign_dtc("VSDTC", source="date")
    .to_frame()
)
```

### AE (Adverse Events)

```python
ae = (
    raw_ae.sdtm.hardcode_no_ct("DOMAIN", value="AE")
    .assign_no_ct("USUBJID", source="subject_id")
    .assign_no_ct("AEDECOD", source="ae_term")
    .assign_dtc("AESTDTC", source="start_date")
    .to_frame()
)
```

## 3. ADaM Derivation

### ADSL (Subject-Level Analysis)

ADSL aggregates information per subject. We source core demographics from `dm`, and then fetch the date of the first adverse event using the `.first_date()` verb from the `ae` dataset.

```python
adsl = (
    dm.adam.adsl.source("USUBJID")
    .source("ARM")
    .source("SEX")
    .first_date(
        "TRTSDT", from_dataset=ae, date_col="AESTDTC"
    )  # For demonstration, using AE start date as proxy
    .to_frame()
)
```

### ADVS (Vital Signs Analysis Dataset)

ADVS provides BDS-structured derivations like Day and Baseline. We join our derived `vs` dataset with `adsl` to obtain the reference date (`TRTSDT`), and apply BDS logic.

```python
# First, pull in the required ADSL reference variables
vs_with_adsl = vs.join(adsl.select(["USUBJID", "TRTSDT"]), on="USUBJID", how="left")

advs = (
    vs_with_adsl.adam.source("USUBJID")
    .source("VSTESTCD")
    .source("VSSTRESN")
    # Identify Baseline logic (Dummy logic: first record is baseline)
    .derivation("ABLFL", expression=pl.lit("Y"))
    .baseline("BASE", aval="VSSTRESN", baseline_flag="ABLFL")
    .to_frame()
)
```

## Conclusion

In roughly 50 lines of code, we constructed an end-to-end multi-domain clinical pipeline that compiles into optimized execution plans and computes efficiently without intermediate pandas serialization!
