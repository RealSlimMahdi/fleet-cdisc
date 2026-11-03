# Quickstart

## Prerequisites

- Python 3.12 to 3.14
- Fleet installed — see [Installation](installation.md)

---

## Your first SDTM domain — zero setup

No API key, no config file, no network. Import `fleet` and chain verbs on any
Polars DataFrame:

```python
import fleet
import polars as pl

raw = pl.from_repr("""
┌────────────┬─────────┬────────────┐
│ patient_id ┆ sex_raw ┆ birth_date │
│ ---        ┆ ---     ┆ ---        │
│ str        ┆ str     ┆ str        │
╞════════════╪═════════╪════════════╡
│ 001        ┆ Male    ┆ 1970-04-15 │
│ 002        ┆ Female  ┆ 1985-11-02 │
│ 003        ┆ Male    ┆ 1960-07-30 │
└────────────┴─────────┴────────────┘
""")

dm = (
    raw.sdtm.assign("DOMAIN", value="DM")
    .assign("STUDYID", value="MYSTUDY01")
    .assign("USUBJID", source="patient_id")
    .date("BRTHDTC", source="birth_date")
    .to_frame()
)
print(dm)
```

```text
┌────────────┬─────────┬────────────┬────────┬───────────┬─────────┬────────────┐
│ patient_id ┆ sex_raw ┆ birth_date ┆ DOMAIN ┆ STUDYID   ┆ USUBJID ┆ BRTHDTC    │
│ 001        ┆ Male    ┆ 1970-04-15 ┆ DM     ┆ MYSTUDY01 ┆ 001     ┆ 1970-04-15 │
│ …          ┆         ┆            ┆        ┆           ┆         ┆            │
└────────────┴─────────┴────────────┴────────┴───────────┴─────────┴────────────┘
```

`assign` is the one assignment verb: `source=` copies a column, `value=`
hardcodes a literal. All derivations accumulate lazily and collapse into a
single optimized Polars pass at `.to_frame()`.

!!! tip "More zero-setup wins"
    The Trial Design domains work fully offline too — SDTMIG 3.4 structures
    ship with Fleet, so `fleet tdd build` and the whole
    [Trial Design walkthrough](../examples/tdd_pipeline.md) run without an
    API key.

### Add controlled terminology

CT is where the CDISC Library comes in. Put an API key in a `.env` file at
your project root:

```bash title=".env"
CDISC_API_KEY=your-key-here
```

Then bootstrap typed codelist constants for your study's domains:

```bash
fleet add-ct --domains DM,AE,VS,EX --output codelists.py
```

This queries the **SDTM Implementation Guide** to discover every codelist referenced by variables in those domains, downloads the term definitions from the CDISC Library, and generates a typed Python module with IDE auto-completion. Now the same pipeline validates and recodes against real CT:

```python
from codelists import SEX  # generated above

dm = (
    raw.sdtm.assign("DOMAIN", value="DM")
    .assign("STUDYID", value="MYSTUDY01")
    .assign("USUBJID", source="patient_id")
    .assign("SEX", source="sex_raw", ct=SEX, ct_map={"Male": "M", "Female": "F"})
    .date("BRTHDTC", source="birth_date")
    .to_frame()
)
```

`ct=` (a generated codelist class or an NCI concept ID) turns on
controlled-terminology validation — no need to look up concept IDs. `ct_map`
recodes collected values to CT submission values (here ``"Male"`` → ``"M"``);
omit it when the raw data already matches the codelist — values are then passed
through and validated as-is.

---

## Your first ADaM BDS dataset

```python
vs_sdtm = pl.from_repr("""
┌─────────┬──────────┬─────────┬───────┬────────────┬────────────┐
│ USUBJID ┆ VISITNUM ┆ PARAMCD ┆ AVAL  ┆ ADT        ┆ TRTSDT     │
│ ---     ┆ ---      ┆ ---     ┆ ---   ┆ ---        ┆ ---        │
│ str     ┆ i64      ┆ str     ┆ f64   ┆ str        ┆ str        │
╞═════════╪══════════╪═════════╪═══════╪════════════╪════════════╡
│ 001-01  ┆ 1        ┆ SYSBP   ┆ 120.0 ┆ 2024-01-10 ┆ 2024-01-10 │
│ 001-01  ┆ 2        ┆ SYSBP   ┆ 115.0 ┆ 2024-02-10 ┆ 2024-01-10 │
│ 001-01  ┆ 3        ┆ SYSBP   ┆ 118.0 ┆ 2024-03-10 ┆ 2024-01-10 │
└─────────┴──────────┴─────────┴───────┴────────────┴────────────┘
""")

advs = (
    vs_sdtm.adam.source("USUBJID", "PARAMCD", "AVAL")
    .study_day("ADY", date_col="ADT", ref_col="TRTSDT")
    .flag("ABLFL", criteria='pl.col("VISITNUM") == 1', by=["USUBJID", "PARAMCD"])
    .baseline("BASE", aval="AVAL", baseline_flag="ABLFL", by=["USUBJID", "PARAMCD"])
    .chg("CHG", aval="AVAL", base="BASE")
    .pchg("PCHG", aval="AVAL", base="BASE")
    .to_frame()
)
```

The `flag → baseline → chg` chain runs in one pipeline — no intermediate
`.to_frame()`. `study_day` uses the CDISC algorithm (`+1` when on/after the
reference date, no day 0).

---

## ADSL — one row per subject

```python
# Exposure rule of the admiral template (ad_adsl.R): a placebo dose of 0 is exposure.
# The SAP decides. Change this if placebo is not coded EXDOSE = 0 with PLACEBO in EXTRT.
treated = (
    '(pl.col("EXDOSE") > 0) | '
    '((pl.col("EXDOSE") == 0) & pl.col("EXTRT").str.to_uppercase().str.contains("PLACEBO"))'
)

adsl = (
    dm_sdtm.adam.adsl.source("USUBJID", "AGE", "SEX")
    .first_date("TRTSDT", from_dataset=ex_sdtm, date_col="EXSTDTC", where=treated)
    .last_date("TRTEDT", from_dataset=ex_sdtm, date_col="EXENDTC", where=treated)
    .duration("TRTDURD", start="TRTSDT", end="TRTEDT")
    .flag("SAFFL", criteria='pl.col("TRTSDT").is_not_null()', false_value="N")
    .count_events("NUMAE", from_dataset=ae_sdtm)
    .to_frame()
)
```

A population flag is never blank (ADaMIG 1.3), so `false_value="N"` gives N to
the subjects outside the safety population.

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
commands like `fleet add-ct`.

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
