# Quickstart

## Prerequisites

- Python 3.12+
- Pymaverse installed — see [Installation](installation.md)

---

## Your first SDTM domain

```python
import pymaverse
import polars as pl

raw = pl.DataFrame({
    "patient_id": ["001", "002", "003"],
    "sex_raw":    ["M", "F", "M"],
    "birth_date": ["1970-04-15", "1985-11-02", "1960-07-30"],
})

dm = (
    raw.sdtm
    .hardcode_no_ct("DOMAIN",  value="DM")
    .hardcode_no_ct("STUDYID", value="MYSTUDY01")
    .assign_no_ct("USUBJID",   source="patient_id")
    .assign_ct("SEX", source="sex_raw",
               ct_codelist="C66731", ct_mapping={"M": "M", "F": "F"})
    .assign_datetime("BRTHDTC", source="birth_date", mode="date")
    .to_frame()
)
print(dm)
```

Nothing runs until `.to_frame()`. All preceding verbs accumulate into a single Polars `with_columns` pass.

---

## Your first ADaM BDS dataset

```python
vs_sdtm = pl.DataFrame({
    "USUBJID":  ["001-01", "001-01", "001-01"],
    "VISITNUM": [1,         2,         3       ],
    "PARAMCD":  ["SYSBP",  "SYSBP",  "SYSBP" ],
    "AVAL":     [120.0,    115.0,    118.0   ],
    "ADT":      ["2024-01-10", "2024-02-10", "2024-03-10"],
    "TRTSDT":   ["2024-01-10", "2024-01-10", "2024-01-10"],
})

advs = (
    vs_sdtm.adam
    .source("USUBJID")
    .source("PARAMCD")
    .source("AVAL")
    .study_day("ADY", analysis_date="ADT", reference_date="TRTSDT")
    .flag("ABLFL", criteria='pl.col("VISITNUM") == 1',
          groups=["USUBJID", "PARAMCD"])
    .baseline("BASE", aval="AVAL", baseline_flag="ABLFL")
    .chg("CHG",  aval="AVAL", base="BASE")
    .pchg("PCHG", aval="AVAL", base="BASE")
    .to_frame()
)
```

---

## ADSL — one row per subject

```python
adsl = (
    dm_sdtm.adsl
    .source("USUBJID")
    .source("AGE")
    .source("SEX")
    .first_date("TRTSDT", from_dataset=ex_sdtm, date_col="EXSTDTC",
                where='pl.col("EXDOSE") > 0')
    .last_date("TRTEDT",  from_dataset=ex_sdtm, date_col="EXENDTC",
               where='pl.col("EXDOSE") > 0')
    .duration("TRTDURD", start_date="TRTSDT", end_date="TRTEDT")
    .eligibility_flag("SAFFL", criteria='pl.col("TRTSDT").is_not_null()')
    .count_events("NUMAE", from_dataset=ae_sdtm)
    .to_frame()
)
```

---

## Full pipeline example

See the [ADSL Pipeline notebook](../examples/adsl_pipeline.ipynb) for a complete, pre-executed walkthrough using the CDISCPILOT01 dataset — covering all 10 admiral-equivalent steps from raw data to final ADSL.

---

## Next steps

- [How define.yaml drives DataFrame creation](../concepts/define-yaml.md)
- [Namespace pipeline architecture](../concepts/pipeline.md)
- [API reference](../api/index.md)
