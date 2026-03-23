# Fleet — Workflow & Usage Guide

> A complete walkthrough: from installation to validated SDTM/ADaM datasets, Define-XML, and XPT export — using the CDISCPILOT01 study.

---

## Prerequisites

- **Python 3.12+**
- **uv** — the only supported package manager ([install uv](https://docs.astral.sh/uv/getting-started/installation/))
- **CDISC Library API key** — required for CLI bootstrapping and codelist generation. Get one at [library.cdisc.org](https://library.cdisc.org). Set `CDISC_API_KEY` in a `.env` file at your project root.

---

## Part 1 — Installation

### From TestPyPI (pre-release)

```bash
uv pip install -i https://test.pypi.org/simple/ fleet-cdisc
```

### From PyPI (stable release)

```bash
uv pip install fleet-cdisc
```

### For development (source checkout)

```bash
git clone https://github.com/RealSlimMahdi/fleet-cdisc.git
cd fleet-cdisc
uv sync --extra docs --extra all --extra dev
```

### Verify installation

```bash
python -c "import fleet; print(fleet.__version__)"
```

---

## Part 2 — Bootstrap a New Study with the CLI

Fleet provides a three-step CLI pipeline to scaffold a complete study workspace from the CDISC Library.

### 2.1 Create the study configuration

```bash
uv run fleet init cfg \
  --study-id CDISCPILOT01 \
  --company "CDISC" \
  --domains DM,AE,VS,EX,DS \
  --adam-datasets ADSL,ADVS,ADAE \
  --root ./cdiscpilot01
```

This creates:

- `cdiscpilot01/study_config.yaml` — study metadata and path configuration
- Directory structure: `data/raw`, `data/sdtm`, `data/adam`, `metadata/sdtm`, `metadata/adam`, `outputs`

The generated `study_config.yaml` looks like:

```yaml
study_id: CDISCPILOT01
company: CDISC
protocol_name: CDISCPILOT01
paths:
  raw_data: data/raw
  sdtm_data: data/sdtm
  adam_data: data/adam
  metadata_sdtm: metadata/sdtm
  metadata_adam: metadata/adam
sdtm:
  ig_version: "3-4"
  domains: [DM, AE, VS, EX, DS]
adam:
  ig_version: "1-1"
  datasets: [ADSL, ADVS, ADAE]
ct:
  package: "sdtmct-2023-12-15"
```

### 2.2 Generate define.yaml from the CDISC Library IG

```bash
uv run fleet init define --config cdiscpilot01/study_config.yaml
```

This queries the CDISC Library REST API for SDTM IG 3.4 and ADaM IG 1.1, and pre-populates `metadata/sdtm/define.yaml` and `metadata/adam/define.yaml` with standard variable metadata, labels, types, and codelist references.

### 2.3 Generate codelists.py

```bash
uv run fleet init ct --config cdiscpilot01/study_config.yaml
```

This reads all codelist concept IDs referenced in the define.yaml files, fetches their terms from the CDISC Library, and generates typed Python classes:

```python
# Generated codelists.py — example excerpt
class C66731:
    """SEX (C66731)."""
    _concept_id = "C66731"
    F = "F"
    M = "M"
    U = "U"

SEX = C66731    # Human-readable alias
RACE = C74457   # ...
```

### Standalone codelist commands

If you prefer to skip the full bootstrap pipeline:

```bash
# Generate codelists.py directly from the SDTM IG
uv run fleet init-ct --domains DM,AE,VS,EX --output specs/cdiscpilot01/sdtm/codelists.py

# Add more domains incrementally (preserves existing codelists)
uv run fleet add-ct --domains LB,CM --output specs/cdiscpilot01/sdtm/codelists.py

# Pin to a specific IG version and CT package
uv run fleet init-ct --domains DM,AE --ig 3-4 --package sdtmct-2025-09-26 --output codelists.py
```

---

## Part 3 — Core Concepts

### 3.1 The namespace pipeline

Importing `fleet` registers chainable namespaces on **every** Polars DataFrame:

```python
import fleet
import polars as pl
```

| Namespace           | Target                 | Description            |
| ------------------- | ---------------------- | ---------------------- |
| `df.sdtm`           | SDTM domains           | 14 derivation verbs    |
| `df.adam`           | ADaM BDS (ADVS, ADLB…) | 22 derivation verbs    |
| `df.adam.adsl`      | ADSL                   | 8 patient-level verbs  |
| `df.adam.occds`     | OCCDS (ADAE, ADCM…)    | 5 occurrence verbs     |
| `df.adam.onco`      | Oncology TA            | RECIST response, BOR   |
| `df.adam.ophtha`    | Ophthalmology TA       | ETDRS/LogMAR           |
| `df.adam.peds`      | Pediatrics TA          | Age, prematurity       |
| `df.adam.vaccine`   | Vaccine TA             | Fever, seroconversion  |
| `df.adam.metabolic` | Metabolic TA           | Waist ratios, body fat |
| `df.adam.neuro`     | Neuroscience TA        | Centiloid, MMSE        |
| `df.adam.pk`        | Pharmacokinetics TA    | ADNCA pipeline         |

Every verb returns a new namespace instance with the expression appended. **Nothing executes until `.to_frame()`**, which runs the entire pipeline in one Polars `with_columns` pass.

### 3.2 Loading raw data

```python
from fleet import load_raw_data

dm_raw = load_raw_data("datasets/cdiscpilot01/raw/dm_raw.csv").collect()
ae_raw = load_raw_data("datasets/cdiscpilot01/raw/ae_raw.csv").collect()
vs_raw = load_raw_data("datasets/cdiscpilot01/raw/vs_raw.csv").collect()
```

`load_raw_data` returns a `pl.LazyFrame` — call `.collect()` to materialise.

### 3.3 StudyContext (path management)

For larger projects, `StudyContext` resolves configured paths automatically:

```python
from fleet import load_study_context, load_raw_data

ctx = load_study_context("cdiscpilot01/study_config.yaml")

dm_raw = load_raw_data(ctx.raw_data_dir / "dm_raw.csv").collect()
vs_raw = load_raw_data(ctx.raw_data_dir / "vs_raw.csv").collect()
```

---

## Part 4 — SDTM Derivation: DM

The CDISCPILOT01 raw demographics file has these columns:

```
patient_number, site_id, age, sex, race, ethnic,
arm_code, arm_description, first_dose_date, last_dose_date, informed_consent_date
```

### 4.1 Code-driven DM pipeline

```python
import fleet
import polars as pl
from fleet import load_raw_data
from specs.cdiscpilot01.sdtm.codelists import SEX, RACE, ETHNIC

dm_raw = load_raw_data("datasets/cdiscpilot01/raw/dm_raw.csv").collect()

dm = (
    dm_raw.sdtm
    .hardcode_no_ct("STUDYID",  value="CDISCPILOT01")
    .hardcode_no_ct("DOMAIN",   value="DM")
    .assign_no_ct(  "USUBJID",  source="patient_number")
    .assign_no_ct(  "SUBJID",   source="patient_number")
    .derivation(    "SITEID",   expression="pl.col('site_id').cast(pl.String)")
    .assign_no_ct(  "AGE",      source="age")
    .hardcode_no_ct("AGEU",     value="YEARS")
    .assign_ct("SEX",   source="sex",    ct_codelist=SEX,
               ct_mapping={"F": "F", "M": "M"})
    .assign_ct("RACE",  source="race",   ct_codelist=RACE,
               ct_mapping={
                   "WHITE":                     "WHITE",
                   "BLACK OR AFRICAN AMERICAN": "BLACK OR AFRICAN AMERICAN",
               })
    .assign_ct("ETHNIC", source="ethnic", ct_codelist=ETHNIC,
               ct_mapping={
                   "HISPANIC OR LATINO":     "HISPANIC OR LATINO",
                   "NOT HISPANIC OR LATINO": "NOT HISPANIC OR LATINO",
               })
    .if_then_else("ARMCD",
                  when=[
                      {"condition": pl.col("arm_code") == "Pbo",    "value": "PBO"},
                      {"condition": pl.col("arm_code") == "Xan_Lo", "value": "XAN_LO"},
                      {"condition": pl.col("arm_code") == "Xan_Hi", "value": "XAN_HI"},
                  ],
                  else_value="SCRNFAIL")
    .assign_no_ct(  "ARM",      source="arm_description")
    .assign_no_ct(  "ACTARMCD", source="arm_code")
    .assign_no_ct(  "ACTARM",   source="arm_description")
    .assign_dtc("RFSTDTC", source="first_dose_date")
    .assign_dtc("RFENDTC", source="last_dose_date")
    .assign_dtc("RFICDTC", source="informed_consent_date")
    .to_frame()
)

print(dm.select("STUDYID", "DOMAIN", "USUBJID", "SEX", "RACE", "ARMCD", "RFSTDTC"))
```

### 4.2 Spec-driven DM pipeline

Put the derivation logic in `define.yaml`:

```yaml
datasets:
  - name: DM
    variables:
      - name: STUDYID
        derivation:
          algorithm: hardcode_no_ct
          value: "CDISCPILOT01"
      - name: DOMAIN
        derivation:
          algorithm: hardcode_no_ct
          value: "DM"
      - name: USUBJID
        derivation:
          algorithm: assign_no_ct
          source: patient_number
      - name: SEX
        derivation:
          algorithm: assign_ct
          source: sex
          ct_codelist: C66731
          ct_mapping:
            "F": "F"
            "M": "M"
      - name: RFSTDTC
        derivation:
          algorithm: assign_dtc
          source: first_dose_date
```

Then execute in one line:

```python
dm = dm_raw.sdtm.from_spec("specs/cdiscpilot01/sdtm/define.yaml", dataset="DM").to_frame()
```

---

## Part 5 — SDTM Derivation: AE

The CDISCPILOT01 raw adverse events file has:

```
patient_number, ae_term, ae_start_date, ae_end_date,
ae_severity, ae_serious, ae_outcome, ae_action_taken, ae_relationship
```

```python
ae_raw = load_raw_data("datasets/cdiscpilot01/raw/ae_raw.csv").collect()

ae = (
    ae_raw.sdtm
    .hardcode_no_ct("STUDYID", value="CDISCPILOT01")
    .hardcode_no_ct("DOMAIN",  value="AE")
    .assign_no_ct(  "USUBJID", source="patient_number")
    .assign_no_ct(  "AETERM",  source="ae_term")
    .assign_dtc("AESTDTC", source="ae_start_date")
    .assign_dtc("AEENDTC", source="ae_end_date")
    .assign_no_ct(  "AESEV",   source="ae_severity")
    .assign_no_ct(  "AESER",   source="ae_serious")
    .assign_no_ct(  "AEOUT",   source="ae_outcome")
    .assign_no_ct(  "AEACN",   source="ae_action_taken")
    .ae_aerel("AEREL", source="ae_relationship")
    .to_frame()
)
```

---

## Part 6 — SDTM Derivation: VS

The CDISCPILOT01 raw vital signs file has:

```
patient_number, site_number, vstestcd, vstest, vsorres, vsorresu, vsdtc, vsdy
```

```python
vs_raw = load_raw_data("datasets/cdiscpilot01/raw/vs_raw.csv").collect()

vs = (
    vs_raw.sdtm
    .hardcode_no_ct("STUDYID", value="CDISCPILOT01")
    .hardcode_no_ct("DOMAIN",  value="VS")
    .assign_no_ct(  "USUBJID", source="patient_number")
    .assign_no_ct(  "VSTESTCD", source="vstestcd")
    .assign_no_ct(  "VSTEST",  source="vstest")
    .assign_no_ct(  "VSORRES", source="vsorres")
    .assign_no_ct(  "VSORRESU", source="vsorresu")
    .derivation(    "VSSTRESN", expression="pl.col('vsorres').cast(pl.Float64, strict=False)")
    .assign_no_ct(  "VSSTRESU", source="vsorresu")
    .assign_dtc("VSDTC",  source="vsdtc")
    .remove_dup(subset=["USUBJID", "VSTESTCD", "VSDTC"])
    .to_frame()
)
```

---

## Part 7 — ADaM Derivation: ADSL

ADSL is built from the SDTM DM domain, enriched with treatment dates from EX and event counts from AE.

### 7.1 Prepare upstream datasets

```python
# Synthesise EX from DM dates (in production, derive EX from raw exposure data)
ex = (
    dm.sdtm
    .assign_no_ct("USUBJID",  source="USUBJID")
    .assign_no_ct("EXSTDTC",  source="RFSTDTC")
    .assign_no_ct("EXENDTC",  source="RFENDTC")
    .hardcode_no_ct("EXDOSE", value=54.0)
    .to_frame()
)

# Synthesise DS from DM (disposition events)
ds = (
    dm.sdtm
    .assign_no_ct("USUBJID",   source="USUBJID")
    .hardcode_no_ct("DSCAT",   value="DISPOSITION EVENT")
    .hardcode_no_ct("DSDECOD", value="COMPLETED")
    .assign_no_ct("DSSTDTC",  source="RFENDTC")
    .to_frame()
)

# Prepare max-dose lookup for SAFFL
_ex_max_dose = (
    ex.sdtm
    .group_by(group_cols=["USUBJID"],
              agg=[pl.col("EXDOSE").max().alias("_EXDOSE_MAX")])
    .to_frame()
)
```

### 7.2 Derive ADSL

```python
adsl = (
    dm.adam.adsl
    # ── Demographics from DM ──
    .source("STUDYID")
    .source("USUBJID")
    .source("SUBJID")
    .source("SITEID")
    .source("AGE")
    .source("AGEU")
    .source("SEX")
    .source("RACE")
    .source("ETHNIC")
    .source("ARM")
    .source("ARMCD")
    .source("ACTARM")
    .source("ACTARMCD")
    # ── Treatment variables ──
    .rename("TRT01P", source="ARM")
    .rename("TRT01A", source="ACTARM")
    # ── Study dates ──
    .source("RFSTDTC")
    .source("RFENDTC")
    .source("RFICDTC")
    # ── Treatment dates from EX ──
    .first_date("TRTSDT", from_dataset=ex, date_col="EXSTDTC")
    .last_date( "TRTEDT", from_dataset=ex, date_col="EXENDTC")
    # ── Treatment duration ──
    .duration("TRTDURD", start_date="TRTSDT", end_date="TRTEDT")
    .to_frame()
)

# ── Disposition ──
adsl = (
    adsl.adam.adsl
    .last_date("EOSDT", from_dataset=ds, date_col="DSSTDTC",
               where='pl.col("DSCAT") == "DISPOSITION EVENT"')
    .first_date("RANDDT", from_dataset=ds, date_col="DSSTDTC",
                where='pl.col("DSDECOD") == "RANDOMIZED"')
    .to_frame()
)

# ── Age grouping ──
adsl = (
    adsl.adam.adsl
    .condderivation("AGEGR1",
                    conditions=[
                        {"condition": "pl.col('AGE') < 18",  "value": "<18"},
                        {"condition": "pl.col('AGE') <= 64", "value": "18-64"},
                        {"condition": "pl.col('AGE') > 64",  "value": ">64"},
                    ],
                    else_value="Missing")
    .to_frame()
)

# ── Population flags ──
adsl = (
    adsl.adam
    .lookup(dataset=_ex_max_dose, on="USUBJID", how="left")
    .to_frame()
    .adam.adsl
    .eligibility_flag("SAFFL", criteria='pl.col("_EXDOSE_MAX") > 0')
    .eligibility_flag("ITTFL", criteria='pl.col("ARMCD") != "SCRNFAIL"')
    .to_frame()
    .drop("_EXDOSE_MAX")
)

# ── AE counts ──
adsl = (
    adsl.adam.adsl
    .count_events("NUMAE",  from_dataset=ae)
    .count_events("NUMSAE", from_dataset=ae,
                  where='pl.col("AESER") == "Y"')
    .to_frame()
)

print(adsl.select("USUBJID", "TRT01P", "TRTSDT", "TRTDURD", "SAFFL", "NUMAE"))
```

---

## Part 8 — ADaM Derivation: ADVS

ADVS is a BDS (Basic Data Structure) dataset derived from SDTM VS.

```python
# Join treatment start date from ADSL
_trtsdt_map = adsl.select("USUBJID", "TRTSDT")

advs = (
    vs_raw.adam
    .assigned("STUDYID", value="CDISCPILOT01")
    .rename(  "USUBJID",  source="patient_number")
    .rename(  "PARAMCD",  source="vstestcd")
    .rename(  "PARAM",    source="vstest")
    .rename(  "AVALU",    source="vsorresu")
    .derivation("AVAL",   expression="pl.col('vsorres').cast(pl.Float64, strict=False)")
    .derive_dt("ADT", source="vsdtc")
    # Join TRTSDT for study day calculation
    .lookup(dataset=_trtsdt_map, on="USUBJID", how="left")
    .study_day("ADY", analysis_date="ADT", reference_date="TRTSDT")
    # Baseline flag: last pre-dose visit (vsdy ≤ 0)
    .flag("ABLFL", criteria='pl.col("vsdy") <= 0',
          groups=["USUBJID", "PARAMCD"])
    .to_frame()
    # Materialise — ABLFL must exist before baseline() window function
    .adam
    .baseline("BASE", aval="AVAL", baseline_flag="ABLFL",
              groups=["USUBJID", "PARAMCD"])
    .to_frame()
    # Materialise — BASE must exist before chg()/pchg()
    .adam
    .chg( "CHG",  aval="AVAL", base="BASE")
    .pchg("PCHG", aval="AVAL", base="BASE")
    .to_frame()
)

print(advs.select("USUBJID", "PARAMCD", "ADT", "AVAL", "ADY", "ABLFL", "BASE", "CHG"))
```

### Why the intermediate `.to_frame()` calls?

Some ADaM derivations require materialisation before the next step:

- `baseline()` needs `ABLFL` to exist as a real column (it's a window function).
- `chg()` / `pchg()` need `BASE` to exist as a real column.

This is a Polars constraint, not a Fleet limitation. Each segment still runs as a single `with_columns` pass.

---

## Part 9 — ADAE with OCCDS Verbs

```python
# Lookup columns from ADSL for enrichment
_adsl_lookup = adsl.select("USUBJID", "TRTSDT", "TRTEDT", "TRT01P", "AGE", "SEX", "SAFFL")

adae = (
    ae.adam
    .lookup(dataset=_adsl_lookup, on="USUBJID", how="left")
    .assigned("STUDYID", value="CDISCPILOT01")
    .source("USUBJID")
    .source("AETERM")
    .source("AESTDTC")
    .source("AEENDTC")
    .source("AESEV")
    .source("AESER")
    .source("AEREL")
    .source("AEOUT")
    .source("AEACN")
    .rename("ASTDT", source="AESTDTC")
    .rename("AENDT", source="AEENDTC")
    .study_day("ADY", analysis_date="ASTDT", reference_date="TRTSDT")
    .to_frame()
    # OCCDS-specific verbs
    .adam.occds
    .treatment_emergent("TRTEMFL", start_date="AESTDTC",
                        trtsdt="TRTSDT", trtedt="TRTEDT")
    .worst_flag("ANL01FL", severity_col="AESEV",
                severity_order=["MILD", "MODERATE", "SEVERE"],
                groups=["USUBJID", "AETERM"])
    .seq("ASEQ", groups=["USUBJID"])
    .to_frame()
)
```

---

## Part 10 — Trial Design Domains (TDD)

Fleet supports all seven CDISC Trial Design domains through rich Pydantic models and a fixed-sequence pipeline.

### 10.1 TE — Trial Elements

```python
import polars as pl
from fleet.sdtm.tdd import (
    Epoch, TrialElement, TrialElements,
    TrialArm, TrialArms,
    TrialVisit, TrialVisits,
    TrialParameter, TrialParameters,
    TrialCriterion, TrialCriteria,
)

te_rows = TrialElements(elements=[
    TrialElement(etcd="SCRN", element="Screening",
                 testrl="INFORMED CONSENT", teenrl="RANDOMIZATION - 1",
                 tedur="P14D", epoch=Epoch.SCREENING),
    TrialElement(etcd="TRT",  element="Treatment",
                 testrl="RANDOMIZATION", teenrl="END OF TREATMENT",
                 tedur="P84D", epoch=Epoch.TREATMENT),
    TrialElement(etcd="FU",   element="Follow-up",
                 testrl="END OF TREATMENT + 1", teenrl="END OF FOLLOW-UP",
                 tedur="P28D", epoch=Epoch.FOLLOW_UP),
])

te = (
    pl.DataFrame().sdtm
    .fetch_structure("TE", ig_version="3-4")
    .study_header(study_id="CDISCPILOT01", domain="TE")
    .add_elements(te_rows)
    .to_frame()
)
```

### 10.2 TA — Trial Arms (with FK validation)

```python
ta_rows = TrialArms(arms=[
    TrialArm(armcd="PBO",    arm="Placebo",               taetord=1,
             etcd="SCRN", element="Screening", epoch=Epoch.SCREENING),
    TrialArm(armcd="PBO",    arm="Placebo",               taetord=2,
             etcd="TRT",  element="Treatment", epoch=Epoch.TREATMENT),
    TrialArm(armcd="PBO",    arm="Placebo",               taetord=3,
             etcd="FU",   element="Follow-up", epoch=Epoch.FOLLOW_UP),
    TrialArm(armcd="XAN_LO", arm="Xanomeline Low Dose",   taetord=1,
             etcd="SCRN", element="Screening", epoch=Epoch.SCREENING),
    TrialArm(armcd="XAN_LO", arm="Xanomeline Low Dose",   taetord=2,
             etcd="TRT",  element="Treatment", epoch=Epoch.TREATMENT),
    TrialArm(armcd="XAN_LO", arm="Xanomeline Low Dose",   taetord=3,
             etcd="FU",   element="Follow-up", epoch=Epoch.FOLLOW_UP),
])

ta = (
    pl.DataFrame().sdtm
    .fetch_structure("TA")
    .study_header("CDISCPILOT01", "TA")
    .add_arms(ta_rows, te=te_rows)  # FK check: ETCD ∈ TE.ETCD
    .to_frame()
)
```

### 10.3 TV — Trial Visits

```python
tv_rows = TrialVisits(visits=[
    TrialVisit(visitnum=1, visit="Screening",        visitdy=1),
    TrialVisit(visitnum=2, visit="Baseline",         visitdy=14),
    TrialVisit(visitnum=3, visit="Week 4",           visitdy=42),
    TrialVisit(visitnum=4, visit="Week 8",           visitdy=70),
    TrialVisit(visitnum=5, visit="Week 12",          visitdy=98),
    TrialVisit(visitnum=6, visit="End of Treatment", visitdy=112),
    TrialVisit(visitnum=7, visit="Follow-up",        visitdy=140),
])

tv = (
    pl.DataFrame().sdtm
    .fetch_structure("TV")
    .study_header("CDISCPILOT01", "TV")
    .add_visits(tv_rows, ta=ta_rows)  # FK check: ARM ∈ TA.ARM
    .to_frame()
)
```

### 10.4 TS — Trial Summary

```python
ts_rows = TrialParameters(parameters=[
    TrialParameter(tsparmcd="ADDON",   tsparm="Added on to Existing Treatments", tsval="N"),
    TrialParameter(tsparmcd="AGEMAX",  tsparm="Planned Maximum Age of Subjects", tsval="80"),
    TrialParameter(tsparmcd="AGEMIN",  tsparm="Planned Minimum Age of Subjects", tsval="50"),
    TrialParameter(tsparmcd="LENGTH",  tsparm="Trial Length",                    tsval="26"),
])

ts = (
    pl.DataFrame().sdtm
    .fetch_structure("TS")
    .study_header("CDISCPILOT01", "TS")
    .add_parameters(ts_rows)
    .to_frame()
)
```

### 10.5 TI — Trial Inclusion/Exclusion

```python
ti_rows = TrialCriteria(criteria=[
    TrialCriterion(ietestcd="INCL01", ietest="Age 50-80 years at screening",
                   iecat="INCLUSION"),
    TrialCriterion(ietestcd="INCL02", ietest="Diagnosis of Alzheimer's Disease",
                   iecat="INCLUSION"),
    TrialCriterion(ietestcd="EXCL01", ietest="Pregnancy or lactation",
                   iecat="EXCLUSION"),
    TrialCriterion(ietestcd="EXCL02", ietest="Known hypersensitivity to study drug",
                   iecat="EXCLUSION"),
])

ti = (
    pl.DataFrame().sdtm
    .fetch_structure("TI")
    .study_header("CDISCPILOT01", "TI")
    .add_criteria(ti_rows)
    .to_frame()
)
```

### TDD pipeline sequence

The pipeline enforces a fixed order:

```
fetch_structure() → study_header() → add_*() → to_frame()
```

Calling verbs out of order raises a `ValueError`.

---

## Part 11 — CDISC Validation

Fleet integrates with the official CDISC Rules Engine for regulatory-grade validation.

### 11.1 Install the CDISC Rules Engine

Before running validation, install the engine binary:

```bash
# Download the latest CDISC Rules Engine for your platform
uv run fleet install-engine

# Verify installation
uv run fleet doctor
```

Expected output:

```
Fleet Doctor
========================================
  engine.............. /Users/you/.fleet/cdisc-rules-engine/core/core
  type................ binary
  status.............. OK — validate command available
  pyreadstat.......... installed
```

The engine is stored at:

- **macOS / Linux:** `~/.fleet/cdisc-rules-engine/core/core`
- **Windows:** `%LOCALAPPDATA%\fleet\cdisc-rules-engine\core\core.exe`

You can also pin a specific version or force a re-download:

```bash
uv run fleet install-engine --version v0.15
uv run fleet install-engine --force
```

### 11.2 Engine discovery

Fleet finds the engine automatically using a 4-tier discovery chain (first match wins):

1. **`FLEET_RULES_ENGINE` env var** — set in `.env` or shell; highest priority.
2. **`study_config.yaml`** — `validation.engine_path` (relative or absolute); committed to VCS for team use.
3. **Managed install** — `~/.fleet/cdisc-rules-engine/` from `fleet install-engine`.
4. **Legacy** — `../cdisc-rules-engine/core.py` (development fallback).

For team projects, set the engine path in `study_config.yaml`:

```yaml
validation:
  engine_path: tools/cdisc-core # relative to study root
```

### 11.3 Run validation

```python
from fleet import ValidationService

svc = ValidationService()

# Validate SDTM domains
dm_result = svc.validate_sdtm(dm, domain="DM", version="3.4")
dm_result.print_report()

ae_result = svc.validate_sdtm(ae, domain="AE", version="3.4")
ae_result.print_report()

# Validate ADaM datasets
adsl_result = svc.validate_adam(adsl, dataset="ADSL", version="1.3")
adsl_result.print_report()

advs_result = svc.validate_adam(advs, dataset="ADVS", version="1.3")
advs_result.print_report()
```

`ValidationResult` provides:

- `.is_valid` — boolean
- `.print_report()` — formatted console output
- `.save_html_report(path)` — HTML report for archiving

### 11.4 Remove the engine

```bash
uv run fleet uninstall-engine
```

> **Note:** `pyreadstat` is also required for validation (XPT serialization). Install it with `uv sync --extra io`.

---

## Part 12 — Generate Define-XML

### From the CLI

```bash
# SDTM Define-XML
uv run fleet define-xml \
  --spec specs/cdiscpilot01/sdtm/define.yaml \
  --output outputs/define_sdtm.xml

# ADaM Define-XML (without HTML preview)
uv run fleet define-xml \
  --spec specs/cdiscpilot01/adam/define.yaml \
  --output outputs/define_adam.xml \
  --no-preview
```

### From Python

```python
from fleet import DefineSpecGenerator, DatasetChecker

# Check datasets against the spec before generating
sdtm_spec = "specs/cdiscpilot01/sdtm/define.yaml"
adam_spec  = "specs/cdiscpilot01/adam/define.yaml"

sdtm_checker = DatasetChecker(sdtm_spec)
adam_checker  = DatasetChecker(adam_spec)

sdtm_checker.check(dm, dataset="DM").print_report()
adam_checker.check(adsl, dataset="ADSL").print_report()
adam_checker.check(advs, dataset="ADVS").print_report()

# Generate Define-XML 2.1
DefineSpecGenerator(sdtm_spec).generate("outputs/define_sdtm.xml")
DefineSpecGenerator(adam_spec).generate("outputs/define_adam.xml")
```

---

## Part 13 — Export Datasets

### Parquet (development)

```python
from fleet import save_parquet

save_parquet(dm,   "outputs/sdtm/dm.parquet")
save_parquet(ae,   "outputs/sdtm/ae.parquet")
save_parquet(vs,   "outputs/sdtm/vs.parquet")
save_parquet(adsl, "outputs/adam/adsl.parquet")
save_parquet(advs, "outputs/adam/advs.parquet")
save_parquet(adae, "outputs/adam/adae.parquet")
```

### SAS XPT (regulatory submission)

```python
from fleet.io import save_xpt

save_xpt(dm,   "outputs/sdtm/dm.xpt")
save_xpt(ae,   "outputs/sdtm/ae.xpt")
save_xpt(vs,   "outputs/sdtm/vs.xpt")
save_xpt(adsl, "outputs/adam/adsl.xpt")
save_xpt(advs, "outputs/adam/advs.xpt")
save_xpt(adae, "outputs/adam/adae.xpt")
```

> **Note:** XPT export requires `pyreadstat`. Install with `uv sync --extra io`. Column names are automatically upper-cased and truncated to 8 characters per SAS Transport format.

---

## Part 14 — Debugging Pipelines

### `.inspect()` — hard checkpoint

Materialises the pipeline at that point, prints schema + shape + first rows, and resumes from the checkpoint.

```python
dm = (
    dm_raw.sdtm
    .hardcode_no_ct("DOMAIN", value="DM")
    .assign_no_ct("USUBJID", source="patient_number")
    .inspect(prefix="After USUBJID")
    .assign_dtc("RFSTDTC", source="first_dose_date")
    .to_frame()
)
```

### `.explain()` — query plan

Prints the Polars logical plan without materialising.

```python
dm = (
    dm_raw.sdtm
    .hardcode_no_ct("DOMAIN", value="DM")
    .explain()
    .to_frame()
)
```

Both verbs are available on `.sdtm` and all ADaM namespaces.

---

## Part 15 — Complete End-to-End Summary

Here is the full sequence for CDISCPILOT01:

```bash
# 1. Bootstrap project structure
uv run fleet init cfg --study-id CDISCPILOT01 --company CDISC \
  --domains DM,AE,VS,EX,DS --adam-datasets ADSL,ADVS,ADAE

# 2. Generate define.yaml from CDISC Library
uv run fleet init define

# 3. Generate codelists.py
uv run fleet init ct

# 4. Install the CDISC Rules Engine (one-time setup)
uv run fleet install-engine

# 5. Write derivation pipelines (Parts 4–10 above)

# 6. Generate Define-XML
uv run fleet define-xml --spec metadata/sdtm/define.yaml --output outputs/define_sdtm.xml
uv run fleet define-xml --spec metadata/adam/define.yaml  --output outputs/define_adam.xml

# 7. Export XPT files for regulatory submission (from Python — see Part 13)
```

---

## Quick Reference — Verb Cheat Sheet

### SDTM verbs (`df.sdtm`)

| Verb                 | Purpose                                     |
| -------------------- | ------------------------------------------- |
| `assign_no_ct`       | Raw column → SDTM variable, no decoding     |
| `assign_ct`          | Raw column → SDTM variable with CT decoding |
| `assign_dtc`         | Date string → ISO 8601                      |
| `hardcode_no_ct`     | Constant value (DOMAIN, STUDYID, AGEU…)     |
| `hardcode_ct`        | Constant value, CT-validated                |
| `condition_add`      | `IF X THEN Y ELSE NULL`                     |
| `if_then_else`       | Multi-branch conditional                    |
| `ae_aerel`           | AE relatedness mapping                      |
| `merge`              | Join a reference dataset                    |
| `remove_dup`         | Deduplicate rows                            |
| `group_by`           | Aggregate to summary rows                   |
| `dataset_level`      | Alias for `hardcode_no_ct`                  |
| `notsubmitted`       | Set columns to null                         |
| `multiple_responses` | Expand pipe-delimited fields into rows      |

### ADaM verbs (`df.adam`)

| Verb                     | Purpose                           |
| ------------------------ | --------------------------------- |
| `source`                 | Carry over from SDTM              |
| `derivation`             | Arbitrary Polars expression       |
| `assigned`               | Global constant                   |
| `recode`                 | Map values to new labels          |
| `rename`                 | Rename column (VSDTC → ADT)       |
| `condderivation`         | Multi-branch conditional          |
| `lookup`                 | Join a reference dataset          |
| `whereclauses`           | Filter rows                       |
| `study_day`              | ADY = (ADT − TRTSDT) + 1          |
| `baseline`               | BASE = AVAL at baseline           |
| `chg`                    | CHG = AVAL − BASE                 |
| `pchg`                   | PCHG = (AVAL − BASE) / BASE × 100 |
| `flag`                   | General "Y" flag                  |
| `bmi`                    | BMI from weight and height        |
| `nrind`                  | LOW / NORMAL / HIGH               |
| `on_treatment`           | ONTRTFL = "Y" on-treatment        |
| `shift`                  | Baseline-to-post shift string     |
| `bsa`                    | Body Surface Area (4 methods)     |
| `map`                    | Mean Arterial Pressure            |
| `qtc`                    | Corrected QT interval             |
| `derive_summary_records` | Append aggregate rows             |
| `derive_locf_records`    | LOCF imputation                   |
| `derive_param`           | Derive new parameter rows         |

### ADSL verbs (`df.adam.adsl`)

| Verb               | Purpose                             |
| ------------------ | ----------------------------------- |
| `first_date`       | Earliest date from event dataset    |
| `last_date`        | Latest date from event dataset      |
| `duration`         | Days between two dates              |
| `count_events`     | Count matching records per subject  |
| `eligibility_flag` | "Y" population flag (SAFFL, ITTFL…) |
| `age_years`        | Unit-aware age → years              |
| `derive_period`    | Subperiod/Phase variables           |

### OCCDS verbs (`df.adam.occds`)

| Verb                 | Purpose                                 |
| -------------------- | --------------------------------------- |
| `seq`                | Sequential record number (ASEQ)         |
| `worst_flag`         | Worst severity flag per group           |
| `treatment_emergent` | TRTEMFL = "Y" on/after TRTSDT           |
| `onset_recovery`     | Event started on-treatment and resolved |

---

## Part 16 — Maintaining `llms.txt`

`llms.txt` is **generated — never edit by hand**. Regenerate after API changes:

```bash
uv run python scripts/build_llms.py
uv run python scripts/build_llms.py --check   # CI stale-check
```
