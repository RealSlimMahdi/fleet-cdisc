# Quickstart

## Prerequisites

- Python 3.12+
- Fleet installed — see [Installation](installation.md)

---

## Your first SDTM domain

### Step 1: Bootstrap Controlled Terminology

Before writing SDTM pipelines, generate your study's controlled terminology constants from the CDISC Library. This requires a CDISC API key in a `.env` file at your project root:

```bash title=".env"
CDISC_API_KEY=your-key-here
```

Then bootstrap the codelists for your study's domains:

```bash
fleet init-ct --domains DM,AE,VS,EX --output codelists.py
```

This queries the **SDTM Implementation Guide** to discover every codelist referenced by variables in those domains, downloads the term definitions from the CDISC Library, and generates a typed Python module with IDE auto-completion.

### Step 2: Write your pipeline

```python
import fleet
import polars as pl
from codelists import SEX  # generated in Step 1

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
    .assign_ct("SEX", source="sex_raw", ct_codelist=SEX)
    .assign_dtc("BRTHDTC", source="birth_date")
    .to_frame()
)
print(dm)
```

`assign_ct` accepts the generated codelist class directly — no need to look up NCI concept IDs. When `ct_mapping` is omitted (as above), raw values are passed through and validated against the codelist. Add `ct_mapping={"1": "M", "2": "F"}` if your raw data needs recoding.

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
    dm_sdtm.adam.adsl
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

Fleet also provides Admiral-parity verbs for advanced BDS derivations — `bsa()`, `map()`, `qtc()`, `derive_summary_records()`, `derive_locf_records()`, and `derive_param()` — as well as ADSL helpers `age_years()` and `derive_period()`. See the [Cheat Sheet](../api/cheat_sheet.md) for the full list.

---

## Initialising a new study workspace

The **bootstrapping pipeline** is the recommended way to set up a new study.
It creates the folder tree, queries the CDISC Library IG to generate
`define.yaml` specs, and downloads the referenced codelists:

```bash
# Step 1 — create study_config.yaml + directory structure
fleet init cfg --study-id MYSTUDY01 --company "Acme Pharma" \
  --domains DM,AE,VS,EX --adam-datasets ADSL,ADVS --root ./studies/MYSTUDY01

# Step 2 — generate define.yaml from the CDISC Library IG
fleet init define

# Step 3 — generate codelists.py from define.yaml codelist references
fleet init ct
```

See the [CLI Reference](cli.md) for full argument details and standalone
commands like `fleet init-ct` and `fleet add-ct`.

The same first step can be done programmatically with `StudyContext.init()`:

```python
from fleet import StudyContext, SDTMConfig, ADAMConfig

ctx = StudyContext.init(
    "./studies/MYSTUDY01",
    study_id="MYSTUDY01",
    company="Acme Pharma",
    sdtm=SDTMConfig(ig_version="3-4", domains=["DM", "AE", "VS", "EX"]),
    adam=ADAMConfig(ig_version="1-1", datasets=["ADSL", "ADVS"]),
)
```

This creates:

```
studies/MYSTUDY01/
  study_config.yaml        ← load later with load_study_context()
  data/
    raw/
    sdtm/
    adam/
  metadata/
    sdtm/                  ← define.yaml created by `fleet init define`
    adam/                   ← define.yaml created by `fleet init define`
  outputs/
```

If `study_config.yaml` already exists, `StudyContext.init()` raises a `StudyConfigError` without touching anything — protecting in-progress work.

To reload an existing workspace in subsequent sessions:

```python
from pathlib import Path
from fleet import load_study_context

ctx = load_study_context(Path("./studies/MYSTUDY01/study_config.yaml"))
```

---

## Full pipeline example

See the [ADSL Pipeline notebook](../examples/02_spec_driven_pipeline.ipynb) for a complete, pre-executed walkthrough using the CDISCPILOT01 dataset — covering all 10 admiral-equivalent steps from raw data to final ADSL.

---

## Next steps

- [CLI Reference](cli.md) — bootstrapping pipeline and standalone CT commands
- [How define.yaml drives DataFrame creation](../concepts/define-yaml.md)
- [Namespace pipeline architecture](../concepts/pipeline.md)
- [API reference](../api/index.md)
