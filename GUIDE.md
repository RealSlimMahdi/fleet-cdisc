# Fleet — Workflow & Usage Guide

> A complete walkthrough: from installation to validated SDTM/ADaM datasets, Define-XML, and XPT export — using the CDISCPILOT01 study.

---

## Prerequisites

- **Python 3.12+**
- **uv** — the only supported package manager ([install uv](https://docs.astral.sh/uv/getting-started/installation/))
- **CDISC Library API key** — required for CLI bootstrapping and codelist generation. Get one at [library.cdisc.org](https://library.cdisc.org). Set `CDISC_API_KEY` in a `.env` file at your project root.

---

## Part 1 — Installation

### From PyPI (pre-alpha)

```bash
uv add fleet-cdisc --prerelease=allow
```

### From TestPyPI (development builds)

```bash
uv pip install -i https://test.pypi.org/simple/ fleet-cdisc
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


SEX = C66731  # Human-readable alias
RACE = C74457  # ...
```

### Standalone codelist commands

If you prefer to skip the full bootstrap pipeline, `fleet add-ct` both
bootstraps a fresh `codelists.py` and extends an existing one (only missing
codelists are added):

```bash
# Bootstrap (or extend) codelists.py directly from the SDTM IG
uv run fleet add-ct --domains DM,AE,VS,EX --output examples/cdiscpilot01/sdtm/codelists.py

# Add more domains later (preserves existing codelists)
uv run fleet add-ct --domains LB,CM --output examples/cdiscpilot01/sdtm/codelists.py

# Pin to a specific IG version and CT package
uv run fleet add-ct --domains DM,AE --ig 3-4 --package sdtmct-2025-09-26 --output codelists.py
```

---

## Part 3 — Core Concepts

### 3.1 The namespace pipeline

Importing `fleet` registers chainable namespaces on **every** Polars DataFrame
— and on every `pl.LazyFrame`, so `pl.scan_parquet(...).sdtm` starts a pipeline
that never leaves the lazy world (predicate/projection pushdown intact for large
LB/PC domains):

```python
import fleet
import polars as pl
```

| Namespace           | Target                 | Description                    |
| ------------------- | ---------------------- | ------------------------------ |
| `df.sdtm`           | SDTM domains           | domain mapping, CT, dates, TDD |
| `df.adam`           | ADaM BDS (ADVS, ADLB…) | baseline, change, flags, …     |
| `df.adam.adsl`      | ADSL                   | patient-level summaries        |
| `df.adam.occds`     | OCCDS (ADAE, ADCM…)    | occurrence flags, ASEQ         |
| `df.adam.onco`      | Oncology TA            | RECIST response, BOR           |
| `df.adam.ophtha`    | Ophthalmology TA       | ETDRS/LogMAR                   |
| `df.adam.peds`      | Pediatrics TA          | Age, prematurity               |
| `df.adam.vaccine`   | Vaccine TA             | Fever, seroconversion          |
| `df.adam.metabolic` | Metabolic TA           | Waist ratios, body fat         |
| `df.adam.neuro`     | Neuroscience TA        | Centiloid, MMSE                |
| `df.adam.pk`        | Pharmacokinetics TA    | ADNCA pipeline                 |

Verb counts drift; don't trust a printed number. Every namespace answers
`.verbs()` — the always-current catalog:

```python
print(dm_raw.sdtm.verbs())  # verb + one-line summary
print(vs_raw.adam.verbs())
print(dm.adam.adsl.verbs())
```

Each verb returns a new namespace instance with its expression appended; call
`.to_frame()` to materialise.

### What is lazy, and what checkpoints

Fleet is **not** "nothing runs until `.to_frame()`". Most verbs are pure
lazy `with_columns` expressions, but a handful must materialise mid-chain
(a window needs a real column; a cross-domain join needs the pinned frame
collected). Chaining across a checkpoint still works — Fleet re-wraps the
collected frame and continues — but each checkpoint is one Polars `collect()`.

| Fully lazy (accumulate into one pass)                                                                                                  | Checkpoints (collect mid-chain)                                                                                                                                                                                                                                       |
| ------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `assign`, `case_when`, `derivation`, `recode`, `keep`, `source`, `ae_aerel`, `notsubmitted`; `duration` (numeric & ISO paths); `study_day` (in-frame `ref_col=`); `seq`; `select`; `merge`/`lookup`; SDTM `group_by`; `multiple_responses` | `date` (DTC-with-time & DTM-with-time paths), `baseline`/`baseline_flag`, `study_day` with a pinned-domain join, `join_adsl`, `merge_adsl`, `whereclauses`, `first_date`/`last_date`/`count_events`, `pick`, `derive_summary_records`/`derive_locf_records`/`derive_param`, `atoxgr`, `transform`, `nodup`, `inspect`, `validate`, frame-kind `@derivation`, multi-column `flag(criteria="exists")` |

Use `.explain()` to print the Polars logical plan without materialising, and
`.inspect()` to force one checkpoint and log schema/shape/head.

### 3.2 Loading raw data

<!-- docs:no-run -->

```python
from pathlib import Path

from fleet import load_raw_data

dm_raw = load_raw_data(Path("datasets/cdiscpilot01/raw/dm_raw.csv")).collect()
ae_raw = load_raw_data(Path("datasets/cdiscpilot01/raw/ae_raw.csv")).collect()
vs_raw = load_raw_data(Path("datasets/cdiscpilot01/raw/vs_raw.csv")).collect()
```

`load_raw_data` takes a `pathlib.Path` and returns a `pl.LazyFrame` — call
`.collect()` to materialise. It also accepts a URL or Parquet/XPT/SAS path. The
examples below reuse `dm_raw`, `ae_raw`, `vs_raw` from this step.

### Typed entry (`fleet.frame`)

Registered namespaces are invisible to type checkers (pola-rs/polars#27795):
`df.sdtm` works at runtime but a bare `pl.DataFrame` gives no autocomplete and
Pyright flags it. Wrap the IO-boundary load in `fleet.frame()` — a zero-cost
identity cast that types the frame as `fleet.DataFrame` / `fleet.LazyFrame`
with `.sdtm` / `.adam` / `.tlg` declared:

<!-- docs:no-run -->

```python
raw = fleet.frame(pl.read_csv("dm_raw.csv"))  # returns the same object, typed
dm = raw.sdtm.assign("DOMAIN", value="DM").to_frame()
dm.tlg  # to_frame() returns fleet.DataFrame — chains stay typed downstream
```

At runtime `fleet.DataFrame` *is* `pl.DataFrame` (a plain alias) and
`frame()` returns its argument unchanged — no wrapper, no copy.

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

`assign` is the one canonical assignment verb: `source=` copies a column,
`value=` hardcodes a literal, and `ct=` / `ct_map=` add controlled-terminology
validation/decoding. `case_when` is the one conditional verb. (Reusing `dm_raw`
from Part 3.2.)

```python
import fleet
import polars as pl
from examples.cdiscpilot01.sdtm.codelists import SEX, RACE, ETHNIC

dm = (
    dm_raw.sdtm.assign("STUDYID", value="CDISCPILOT01")
    .assign("DOMAIN", value="DM")
    .assign("USUBJID", source="patient_number")
    .assign("SUBJID", source="patient_number")
    .derivation("SITEID", expression="pl.col('site_id').cast(pl.String)")
    .assign("AGE", source="age")
    .assign("AGEU", value="YEARS")
    .assign("SEX", source="sex", ct=SEX, ct_map={"F": "F", "M": "M"})
    .assign(
        "RACE",
        source="race",
        ct=RACE,
        ct_map={
            "WHITE": "WHITE",
            "BLACK OR AFRICAN AMERICAN": "BLACK OR AFRICAN AMERICAN",
        },
    )
    .assign(
        "ETHNIC",
        source="ethnic",
        ct=ETHNIC,
        ct_map={
            "HISPANIC OR LATINO": "HISPANIC OR LATINO",
            "NOT HISPANIC OR LATINO": "NOT HISPANIC OR LATINO",
        },
    )
    .case_when(
        "ARMCD",
        when=[
            {"condition": pl.col("arm_code") == "Pbo", "value": "PBO"},
            {"condition": pl.col("arm_code") == "Xan_Lo", "value": "XAN_LO"},
            {"condition": pl.col("arm_code") == "Xan_Hi", "value": "XAN_HI"},
        ],
        else_="SCRNFAIL",
    )
    .assign("ARM", source="arm_description")
    .assign("ACTARMCD", source="arm_code")
    .assign("ACTARM", source="arm_description")
    .date("RFSTDTC", source="first_dose_date")
    .date("RFENDTC", source="last_dose_date")
    .date("RFICDTC", source="informed_consent_date")
    .to_frame()
)

print(dm.select("STUDYID", "DOMAIN", "USUBJID", "SEX", "RACE", "ARMCD", "RFSTDTC"))
```

> **Renamed in pre-alpha.** The old spellings (`assign_no_ct` / `assign_ct` /
> `hardcode_no_ct` / `hardcode_ct` / `dataset_level` / `if_then_else`, …) were
> removed outright — `assign` / `case_when` / `merge` with `by=` / `keep=` are
> the only spellings. Run `python -m fleet.tools.migrate <files...> --write`
> (or `fleet migrate`) to rewrite old external scripts automatically.

### 4.2 Spec-driven DM pipeline

Put the derivation logic in `define.yaml`. The spec path accepts both canonical
and legacy algorithm names (the registry maps them onto the same verbs), so an
existing define.yaml keeps working:

<!-- docs:no-run -->

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
          algorithm: date
          source: first_dose_date
```

Then execute in one line:

<!-- docs:no-run -->

```python
dm = dm_raw.sdtm.from_spec("examples/cdiscpilot01/sdtm/define.yaml", dataset="DM").to_frame()
```

`from_spec` is `strict=True` by default: an unknown `algorithm:` raises a
`SpecError` naming file → dataset → variable, with a did-you-mean suggestion.
Pass `strict=False` to warn-and-skip, `overwrite=True` to let a spec variable
replace an existing column, or `omit=["TRTSDT"]` to keep an inline derivation
for one variable. Prototyped inline first? `ns.to_spec_yaml(dataset="DM")`
emits the equivalent `derivation:` blocks so you don't retype the YAML by hand;
for an ADaM pipeline, `to_spec_yaml(dataset="ADSL", predecessor="DM")` also
pre-fills `origin: Predecessor` / `predecessor: DM.<VAR>` for carried columns.

---

## Part 5 — SDTM Derivation: AE

The CDISCPILOT01 raw adverse events file has:

```
patient_number, ae_term, ae_start_date, ae_end_date,
ae_severity, ae_serious, ae_outcome, ae_action_taken, ae_relationship
```

```python
ae = (
    ae_raw.sdtm.assign("STUDYID", value="CDISCPILOT01")
    .assign("DOMAIN", value="AE")
    .assign("USUBJID", source="patient_number")
    .assign("AETERM", source="ae_term")
    .date("AESTDTC", source="ae_start_date")
    .date("AEENDTC", source="ae_end_date")
    .assign("AESEV", source="ae_severity")
    .assign("AESER", source="ae_serious")
    .assign("AEOUT", source="ae_outcome")
    .assign("AEACN", source="ae_action_taken")
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
vs = (
    vs_raw.sdtm.assign("STUDYID", value="CDISCPILOT01")
    .assign("DOMAIN", value="VS")
    .assign("USUBJID", source="patient_number")
    .assign("VSTESTCD", source="vstestcd")
    .assign("VSTEST", source="vstest")
    .assign("VSORRES", source="vsorres")
    .assign("VSORRESU", source="vsorresu")
    .derivation("VSSTRESN", expression="pl.col('vsorres').cast(pl.Float64, strict=False)")
    .assign("VSSTRESU", source="vsorresu")
    .date("VSDTC", source="vsdtc")
    .nodup(subset=["USUBJID", "VSTESTCD", "VSDTC"])
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
    dm.sdtm.assign("USUBJID", source="USUBJID")
    .assign("EXSTDTC", source="RFSTDTC")
    .assign("EXENDTC", source="RFENDTC")
    .assign("EXDOSE", value=54.0)
    .to_frame()
)

# Synthesise DS from DM (disposition events)
ds = (
    dm.sdtm.assign("USUBJID", source="USUBJID")
    .assign("DSCAT", value="DISPOSITION EVENT")
    .assign("DSDECOD", value="COMPLETED")
    .assign("DSSTDTC", source="RFENDTC")
    .to_frame()
)

# Prepare max-dose lookup for SAFFL
_ex_max_dose = ex.sdtm.group_by(
    by=["USUBJID"], agg=[pl.col("EXDOSE").max().alias("_EXDOSE_MAX")]
).to_frame()
```

### 7.2 Derive ADSL

The shared-verb mixin (`assign`, `case_when`, `merge`, `flag`, `duration`, …)
lives on **every** ADaM sub-namespace, so the whole ADSL derivation is a single
chain — no break-and-re-enter. `source()` is variadic: carry many columns in one
call. `merge()` is the one join verb.

```python
adsl = (
    dm.adam.adsl
    # ── Demographics from DM (variadic carry-through) ──
    .source(
        "STUDYID",
        "USUBJID",
        "SUBJID",
        "SITEID",
        "AGE",
        "AGEU",
        "SEX",
        "RACE",
        "ETHNIC",
        "ARM",
        "ARMCD",
        "ACTARM",
        "ACTARMCD",
    )
    # ── Treatment variables ──
    .assign("TRT01P", source="ARM")
    .assign("TRT01A", source="ACTARM")
    # ── Study dates ──
    .source("RFSTDTC", "RFENDTC", "RFICDTC")
    # ── Treatment dates from EX ──
    .first_date("TRTSDT", from_dataset=ex, date_col="EXSTDTC")
    .last_date("TRTEDT", from_dataset=ex, date_col="EXENDTC")
    # ── Treatment duration ──
    .duration("TRTDURD", start="TRTSDT", end="TRTEDT")
    # ── Disposition ──
    .last_date(
        "EOSDT", from_dataset=ds, date_col="DSSTDTC", where='pl.col("DSCAT") == "DISPOSITION EVENT"'
    )
    .first_date(
        "RANDDT", from_dataset=ds, date_col="DSSTDTC", where='pl.col("DSDECOD") == "RANDOMIZED"'
    )
    # ── Age grouping ──
    .case_when(
        "AGEGR1",
        when=[
            {"condition": "pl.col('AGE') < 18", "value": "<18"},
            {"condition": "pl.col('AGE') <= 64", "value": "18-64"},
            {"condition": "pl.col('AGE') > 64", "value": ">64"},
        ],
        else_="Missing",
    )
    # ── Population flags ──
    .merge(_ex_max_dose, on="USUBJID")
    .flag("SAFFL", criteria='pl.col("_EXDOSE_MAX") > 0')
    .flag("ITTFL", criteria='pl.col("ARMCD") != "SCRNFAIL"')
    # ── AE counts ──
    .count_events("NUMAE", from_dataset=ae)
    .count_events("NUMSAE", from_dataset=ae, where='pl.col("AESER") == "Y"')
    .to_frame()
    .drop("_EXDOSE_MAX")
)

print(adsl.select("USUBJID", "TRT01P", "TRTSDT", "TRTDURD", "SAFFL", "NUMAE"))
```

---

## Part 8 — ADaM Derivation: ADVS

ADVS is a BDS (Basic Data Structure) dataset derived from SDTM VS.

The full baseline derivation is **one unbroken chain**. `flag` writes `ABLFL`,
`baseline` reads it to produce `BASE`, and `chg`/`pchg` read `BASE` — all in the
same pipeline. Fleet checkpoints internally where a window function needs a real
column and re-wraps the collected frame, so you never write intermediate
`.to_frame()` calls. This keeps lineage intact end-to-end.

```python
# Join treatment start date from ADSL
_trtsdt_map = adsl.select("USUBJID", "TRTSDT")

advs = (
    vs_raw.adam.assign("STUDYID", value="CDISCPILOT01")
    .assign("USUBJID", source="patient_number")
    .assign("PARAMCD", source="vstestcd")
    .assign("PARAM", source="vstest")
    .assign("AVALU", source="vsorresu")
    .derivation("AVAL", expression="pl.col('vsorres').cast(pl.Float64, strict=False)")
    .date("ADT", source="vsdtc")
    # Join TRTSDT for study day calculation
    .merge(_trtsdt_map, on="USUBJID")
    .duration("ADY", start="TRTSDT", end="ADT")
    # Baseline flag: last pre-dose visit (vsdy <= 0)
    .flag("ABLFL", criteria='pl.col("vsdy") <= 0', by=["USUBJID", "PARAMCD"])
    # BASE = AVAL where ABLFL == "Y" — reads the flag written one line up
    .baseline("BASE", aval="AVAL", baseline_flag="ABLFL", by=["USUBJID", "PARAMCD"])
    # CHG / PCHG read BASE — still the same chain
    .chg("CHG", aval="AVAL", base="BASE")
    .pchg("PCHG", aval="AVAL", base="BASE")
    .to_frame()
)

print(advs.select("USUBJID", "PARAMCD", "ADT", "AVAL", "ADY", "ABLFL", "BASE", "CHG"))
```

### Do I ever need an intermediate `.to_frame()`?

No — not for the `flag → baseline → chg` dependency shown above. That pattern is
one of Fleet's `test_docs_examples.py` guardrails, so it can never silently
regress. You only reach for `.to_frame()` when you want a plain `pl.DataFrame`
to hand to non-Fleet code (a `select`, a raw Polars join, an export writer).
`baseline`/`chg`/`pchg` still checkpoint internally (see the
[laziness table](#what-is-lazy-and-what-checkpoints)) — but that is Fleet's job,
not yours, and it does not break the chain.

---

## Part 9 — ADAE with OCCDS Verbs

Because the shared verbs and the OCCDS-specific verbs share one namespace, the
enrichment join, the standard derivations, and the occurrence flags run in a
single `df.adam.occds` chain.

```python
# Lookup columns from ADSL for enrichment
_adsl_lookup = adsl.select("USUBJID", "TRTSDT", "TRTEDT", "TRT01P", "AGE", "SEX", "SAFFL")

adae = (
    ae.adam.occds.merge(_adsl_lookup, on="USUBJID")
    .assign("STUDYID", value="CDISCPILOT01")
    .source("USUBJID", "AETERM", "AESTDTC", "AEENDTC", "AESEV", "AESER", "AEREL", "AEOUT", "AEACN")
    .date("ASTDT", source="AESTDTC")
    .date("AENDT", source="AEENDTC")
    .duration("ADY", start="TRTSDT", end="ASTDT")
    # OCCDS-specific verbs — same chain
    .treatment_emergent("TRTEMFL", start_date="AESTDTC", trtsdt="TRTSDT", trtedt="TRTEDT")
    .recode("AESEVN", source="AESEV", recode_map={"MILD": 1, "MODERATE": 2, "SEVERE": 3})
    .flag("ANL01FL", criteria="max", value_col="AESEVN", by=["USUBJID", "AETERM"])
    .seq("ASEQ", by=["USUBJID"])
    .to_frame()
)

print(adae.select("USUBJID", "AETERM", "TRTEMFL", "AESEVN", "ASEQ"))
```

---

## Part 10 — Trial Design Domains (TDD)

Fleet supports all nine CDISC Trial Design domains (TE, TA, TV, TS, TI, TD,
TM protocol-reference; SV, SE subject-level) through two complementary paths:

1. **`fleet.StudyDesign`** — define the design once, derive every domain.
2. **Row-level pipeline** — `fetch_structure() → study_header() → add_*() → to_frame()`
   with rich Pydantic collections.

SDTMIG 3.4 structures for the TDD domains **ship with Fleet**, so both paths
run offline — no CDISC Library API key required.

### 10.1 StudyDesign — define once, derive everything

Arms are declared as *element paths*; `TAETORD`, `ELEMENT`, `EPOCH`, and
`TABRANCH` (at the randomization branch point) are derived, never typed:

```python
import fleet
import polars as pl

design = fleet.StudyDesign(
    study_id="CDISCPILOT01",
    elements=[
        {"etcd": "SCRN", "element": "Screening", "tedur": "P14D",
         "epoch": "SCREENING", "testrl": "INFORMED CONSENT",
         "teenrl": "RANDOMIZATION - 1"},
        {"etcd": "PBO", "element": "Placebo Treatment", "tedur": "P84D",
         "epoch": "TREATMENT", "testrl": "RANDOMIZATION"},
        {"etcd": "XANLO", "element": "Xanomeline Low Dose", "tedur": "P84D",
         "epoch": "TREATMENT", "testrl": "RANDOMIZATION"},
        {"etcd": "FU", "element": "Follow-up", "tedur": "P28D",
         "epoch": "FOLLOW-UP", "testrl": "END OF TREATMENT + 1"},
    ],
    arms={"PBO": ["SCRN", "PBO", "FU"], "XAN_LO": ["SCRN", "XANLO", "FU"]},
    arm_names={"PBO": "Placebo", "XAN_LO": "Xanomeline Low Dose"},
    parameters=[
        {"tsparmcd": "TITLE", "tsparm": "Trial Title", "tsval": "Demo"},
        {"tsparmcd": "SSTDTC", "tsparm": "Study Start Date", "tsval": "2014-01-01"},
    ],
)

ta = design.to_ta()               # one domain
frames = design.domains()          # every populated domain: {"TE": df, ...}
assert ta.filter(pl.col("TABRANCH") != "")["ETCD"].to_list() == ["SCRN", "SCRN"]
```

The design serialises to YAML (`design.to_yaml("trial_design.yaml")` /
`fleet.StudyDesign.from_yaml(...)`) and imports from a CDISC USDM (DDF)
study definition via `fleet.StudyDesign.from_usdm(usdm_json)` — arms,
epochs, elements, study cells, encounters, and eligibility criteria map to
the corresponding design sections.

### 10.2 Conformance audit — a P21 dry-run, offline

`design.audit()` (or the standalone `fleet.sdtm.trial_design_audit(te=, ta=, ...)`)
checks the derived domains against the published P21/FDA rule IDs: SD-series
structural rules (TAETORD uniqueness, TA↔TE element consistency, reserved
ARMCDs, ARM↔ARMCD one-to-one) and the FDA Technical Conformance Guide TS
parameter profile (missing `SSTDTC` is flagged as rejection-level 1734):

```python
findings = design.audit()
errors = findings.filter(pl.col("severity") == "error")
assert "SD2214" in findings["rule_id"].to_list()  # TPHASE missing above
```

Pass `dm=` to cross-check ARMCD assignments against Demographics
(`SD1354`, undefined-arm detection).

### 10.3 Visit schedules and Mermaid round trip

Build TV from day offsets relative to an anchor event — `VISITNUM`,
`VISITDY` (no-day-zero convention), and deterministic `TVSTRL` text derive:

```python
from fleet.sdtm.tdd import TrialVisits

tv_rows = TrialVisits.from_schedule(
    [("Screening", -14), ("Baseline", 0), ("Week 4", 28), ("Week 8", 56)],
    anchor="RANDOMIZATION",
    window=3,
)
assert tv_rows.to_polars()["VISITDY"].to_list() == [-14, 1, 29, 57]
```

A design renders to a Mermaid flowchart and parses back — diagram-as-code
for protocol review decks:

```python
diagram = design.to_mermaid()
reparsed = fleet.StudyDesign.from_mermaid(diagram, study_id="CDISCPILOT01")
assert reparsed.arms == design.arms
```

### 10.4 Row-level pipeline: TE — Trial Elements

```python
import polars as pl
from fleet.sdtm.tdd import (
    Epoch,
    TrialElement,
    TrialElements,
    TrialArm,
    TrialArms,
    TrialVisit,
    TrialParameter,
    TrialParameters,
    TrialCriterion,
    TrialCriteria,
)

te_rows = TrialElements(
    elements=[
        TrialElement(
            etcd="SCRN",
            element="Screening",
            testrl="INFORMED CONSENT",
            teenrl="RANDOMIZATION - 1",
            tedur="P14D",
            epoch=Epoch.SCREENING,
        ),
        TrialElement(
            etcd="TRT",
            element="Treatment",
            testrl="RANDOMIZATION",
            teenrl="END OF TREATMENT",
            tedur="P84D",
            epoch=Epoch.TREATMENT,
        ),
        TrialElement(
            etcd="FU",
            element="Follow-up",
            testrl="END OF TREATMENT + 1",
            teenrl="END OF FOLLOW-UP",
            tedur="P28D",
            epoch=Epoch.FOLLOW_UP,
        ),
    ]
)

te = (
    pl.DataFrame()
    .sdtm.fetch_structure("TE", ig_version="3-4")
    .study_header(study_id="CDISCPILOT01", domain="TE")
    .add_elements(te_rows)
    .to_frame()
)
```

`epoch` on `TrialElement` is a **design-time attribute** — it drives the
element→epoch mapping when deriving TA and SE, but is not written to the TE
dataset (SDTMIG 3.4 has no EPOCH variable in TE). Sponsor-defined epoch
terms are accepted alongside the `Epoch` enum (C99079 is extensible):
`TrialElement(etcd="ESC", element="Escalation", epoch="DOSE ESCALATION")`.

### 10.5 TA — Trial Arms (with FK validation)

```python
ta_rows = TrialArms(
    arms=[
        TrialArm(armcd="PBO", arm="Placebo", taetord=1,
                 etcd="SCRN", element="Screening", epoch=Epoch.SCREENING),
        TrialArm(armcd="PBO", arm="Placebo", taetord=2,
                 etcd="TRT", element="Treatment", epoch=Epoch.TREATMENT),
        TrialArm(armcd="PBO", arm="Placebo", taetord=3,
                 etcd="FU", element="Follow-up", epoch=Epoch.FOLLOW_UP),
    ]
)

ta = (
    pl.DataFrame()
    .sdtm.fetch_structure("TA")
    .study_header("CDISCPILOT01", "TA")
    .add_arms(ta_rows, te=te_rows)  # FK check: ETCD ∈ TE.ETCD
    .to_frame()
)
```

`TrialArm` also carries the optional `tabranch` / `tatrans` rule fields
(SDTMIG `TABRANCH`, `TATRANS`).

### 10.6 TV — Trial Visits (with FK validation)

```python
tv_rows2 = TrialVisits(
    visits=[
        TrialVisit(visitnum=1, visit="Screening", visitdy=-14),
        TrialVisit(visitnum=2, visit="Baseline", visitdy=1, armcd="PBO"),
        TrialVisit(visitnum=3, visit="Week 4", visitdy=29),
    ]
)

tv = (
    pl.DataFrame()
    .sdtm.fetch_structure("TV")
    .study_header("CDISCPILOT01", "TV")
    .add_visits(tv_rows2, ta=ta_rows)  # FK check: ARMCD ∈ TA.ARMCD
    .to_frame()
)
```

### 10.7 TS — Trial Summary (with ClinicalTrials.gov seeding)

`TrialParameter` supports the full SDTMIG 3.4 variable set — `TSSEQ` for
repeating parameters (e.g. one `FCNTRY` row per country) plus `TSGRPID`,
`TSVCDREF`, `TSVCDVER` for dictionary-bound values:

```python
ts_rows = TrialParameters(
    parameters=[
        TrialParameter(tsparmcd="TITLE", tsparm="Trial Title", tsval="Demo study"),
        TrialParameter(tsparmcd="FCNTRY", tsparm="Planned Country of Investigational Sites",
                       tsval="USA", tsseq=1),
        TrialParameter(tsparmcd="FCNTRY", tsparm="Planned Country of Investigational Sites",
                       tsval="DEU", tsseq=2),
        TrialParameter(tsparmcd="INDIC", tsparm="Trial Disease/Condition Indication",
                       tsval="Alzheimer's disease", tsvalcd="26929004",
                       tsvcdref="SNOMED CT", tsvcdver="2014-03-01"),
    ]
)

ts = (
    pl.DataFrame()
    .sdtm.fetch_structure("TS")
    .study_header("CDISCPILOT01", "TS")
    .add_parameters(ts_rows)
    .to_frame()
)
```

Seed the registry-derivable parameters straight from ClinicalTrials.gov
(REGID, TITLE, TPHASE, STYPE, AGEMIN/AGEMAX, SEXPOP, PLANSUB, NARMS,
FCNTRY, SSTDTC, …) and extend by hand:

<!-- docs:no-run -->

```python
ts_seed = TrialParameters.from_ctgov("NCT00048217")  # network call
```

Or from the CLI — print the YAML, or merge it into `trial_design.yaml`:

```bash
uv run fleet tdd ctgov NCT00048217           # print the parameters: block
uv run fleet tdd ctgov NCT00048217 --write   # merge into trial_design.yaml
```

### 10.8 TI — Trial Inclusion/Exclusion

```python
ti_rows = TrialCriteria(
    criteria=[
        TrialCriterion(ietestcd="INCL01", ietest="Age 50-80 years at screening",
                       iecat="INCLUSION"),
        TrialCriterion(ietestcd="EXCL01", ietest="Pregnancy or lactation",
                       iecat="EXCLUSION", tivers="2.0"),
    ]
)

ti = (
    pl.DataFrame()
    .sdtm.fetch_structure("TI")
    .study_header("CDISCPILOT01", "TI")
    .add_criteria(ti_rows)
    .to_frame()
)
```

### 10.9 TD & TM — Disease Assessments and Milestones

```python
from fleet.sdtm.tdd import (
    TrialDiseaseAssessment,
    TrialDiseaseAssessments,
    TrialMilestone,
    TrialMilestones,
)

td = (
    pl.DataFrame()
    .sdtm.fetch_structure("TD")
    .study_header("CDISCPILOT01", "TD")
    .add_disease_assessments(TrialDiseaseAssessments(assessments=[
        TrialDiseaseAssessment(tdorder=1, tdancvar="TDANCH01", tdstoff="P0D",
                               tdtgtpai="P8W", tdminpai="P7W", tdmaxpai="P9W",
                               tdnumrpt=6),
    ]))
    .to_frame()
)

tm = (
    pl.DataFrame()
    .sdtm.fetch_structure("TM")
    .study_header("CDISCPILOT01", "TM")
    .add_milestones(TrialMilestones(milestones=[
        TrialMilestone(midstype="DIAGNOSIS",
                       tmdef="Initial diagnosis of disease", tmrpt="N"),
    ]))
    .to_frame()
)
```

### 10.10 Subject-level: EPOCH stamped from SE

`epoch_assign(se=...)` derives EPOCH for **any** domain from the subject's
own element intervals — the cross-domain consistency P21 checks against SE:

```python
se = pl.DataFrame({
    "USUBJID": ["001", "001"],
    "SESTDTC": ["2014-01-01", "2014-01-15"],
    "SEENDTC": ["2014-01-14", None],
    "EPOCH": ["SCREENING", "TREATMENT"],
})

ae_epoch = (
    pl.DataFrame({"USUBJID": ["001", "001"],
                  "AESTDTC": ["2014-01-05", "2014-02-01"]})
    .sdtm.epoch_assign("EPOCH", date_col="AESTDTC", se=se)
    .to_frame()
)
assert ae_epoch["EPOCH"].to_list() == ["SCREENING", "TREATMENT"]
```

Derive `SESEQ` with the standard `seq()` verb:
`.seq("SESEQ", order_by=["SESTDTC"])`.

### 10.11 CLI: build and audit from trial_design.yaml

`fleet tdd` runs in the context of the discovered `study_config.yaml`
(git-style parent walk, `--config` to override): the design spec defaults
to `<metadata_sdtm>/trial_design.yaml` and the output directory to the
config's `sdtm_data` path — so the command works from any subdirectory of
any company's folder structure. The YAML mirrors the `StudyDesign` schema:

```yaml
trial_design:
  study_id: CDISCPILOT01
  elements:
    - {etcd: SCRN, element: Screening, tedur: P14D, epoch: SCREENING,
       testrl: INFORMED CONSENT}
    - {etcd: TRT, element: Treatment, tedur: P84D, epoch: TREATMENT,
       testrl: RANDOMIZATION}
  arms:
    PBO: [SCRN, TRT]
  arm_names:
    PBO: Placebo
```

```bash
uv run fleet tdd audit                       # conformance pre-check
uv run fleet tdd build --format xpt          # audit + write to <sdtm_data>/
uv run fleet tdd ctgov NCT04280705 --write   # seed TS parameters from ClinicalTrials.gov
uv run fleet tdd build --design specs/td.yaml --out /tmp/out   # explicit overrides
```

`fleet tdd build` refuses to write when the audit reports errors
(override with `--force`).

### TDD pipeline sequence

The row-level pipeline enforces a fixed order:

```
fetch_structure() → study_header() → add_*() → to_frame()
```

Calling verbs out of order raises a `ValueError`.

---

## Part 11 — TLG: Tables, Listings, and Graphs

Fleet's `df.tlg` namespace produces **Analysis Results Datasets (ARDs)** from
ADaM data — long-format DataFrames holding all the computed statistics needed
for clinical tables, with a display-rounding step applied only at render time.

### Sub-namespaces

Nine domain sub-namespaces cover the common submission tables. The full catalog
of registry templates (id → CDISC class → namespace method → output type) is
`df.tlg.catalog()`:

| Sub-namespace | Access      | Example templates            |
| ------------- | ----------- | ---------------------------- |
| AE            | `df.tlg.ae` | `aet01` overview, `aet05` relationship, `ael01` listing |
| VS            | `df.tlg.vs` | `vst01` summary              |
| LB            | `df.tlg.lb` | `lbt01`/`lbt02` summary, shift, listing |
| EG            | `df.tlg.eg` | ECG summary, change, QTc     |
| CM            | `df.tlg.cm` | Concomitant medications      |
| EX            | `df.tlg.ex` | Exposure summary             |
| DM            | `df.tlg.dm` | Demographics summary         |
| DS            | `df.tlg.ds` | Disposition, deaths          |
| MH            | `df.tlg.mh` | Medical history              |

### Spec-driven path

Define a spec and call `t_summary()`:

```python
from fleet.tlg import AESummarySpec, GroupPool, Statistic

spec = AESummarySpec(
    adsl_filter=pl.col("SAFFL") == "Y",
    statistics=[Statistic.N_SUBJECTS, Statistic.N_PCT, Statistic.N_EVENTS],
    pools=[GroupPool(label="Total", arms="*")],
    column_order=["Placebo", "Drug A", "Drug B", "Total"],
)
ard = adae.tlg.ae.t_summary(groupby="TRTA", adsl=adsl, spec=spec)
```

### Inline fluent builder

The builder produces the same ARD without constructing a spec object:

```python
ard = (
    adae.tlg.ae.population(adsl, adsl_filter=pl.col("SAFFL") == "Y")
    .by("TRTA")
    .rows(["AEBODSYS", "AEDECOD"])
    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
    .pools([GroupPool(label="Total", arms="*")])
    .column_order(["Placebo", "Drug A", "Drug B", "Total"])
    .to_ard()
)
```

### YAML spec as a full workflow

A TLG YAML file names a registry `template:` and its fields — so a spec file
alone reproduces the table. `load_spec` resolves the template to its spec model,
and `run_spec` dispatches to the right namespace method:

```python
import fleet.tlg as tlg

spec = tlg.load_spec("examples/tlg_specs/aet01.yaml")
ard = tlg.run_spec(spec, adae, adsl=adsl)
```

`tlg.spec_schema("aet01")` returns the JSON schema for a template (editor
auto-complete), and `tlg.register_template(meta, fn)` adds a study-specific
template to the open registry. These are also the composition points for the
`fleet tlg list` / `fleet tlg run` CLI commands.

### Filters: `adsl_filter` vs `dataset_filter`

Two filter fields keep denominators separate from analysis subsets:

| Field            | Applied to      | Example                          |
| ---------------- | --------------- | -------------------------------- |
| `adsl_filter`    | ADSL only (N)   | `pl.col("SAFFL") == "Y"`         |
| `dataset_filter` | Primary dataset | `pl.col("PARAMCD") == "ALBUMIN"` |

Both default to `None` (no filter). Neither propagates to the other.

### Header rows (`OverallStat`)

Whole-dataset aggregate rows appear above the hierarchy in the ARD:

```python
from fleet.tlg import OverallStat

ard = (
    adae.tlg.ae.population(adsl, adsl_filter=pl.col("SAFFL") == "Y")
    .by("TRTA")
    .header_rows(
        [
            OverallStat(label="Subjects with any AE"),
            OverallStat(label="Subjects with ≥1 SAE", filter=pl.col("AESER") == "Y"),
        ]
    )
    .rows(["AEBODSYS", "AEDECOD"])
    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
    .to_ard()
)
```

Header rows emit `variable=""` and `variable_level=label` in the ARD.

### Pre-merge stratification (C3 pattern)

When a stratification column lives in another dataset (e.g. AGEGR1 from ADSL),
pre-merge it before calling the namespace — no hidden joins:

```python
adae_strat = adae.join(
    adsl.select(["USUBJID", "AGEGR1"]),
    on="USUBJID",
    how="left",
)
ard = (
    adae_strat.tlg.ae.population(adsl)
    .by("TRTA")
    .by2("AGEGR1")
    .rows(["AEBODSYS", "AEDECOD"])
    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
    .to_ard()
)
```

### AE listing

```python
from fleet.tlg import AEListingSpec, Column

listing = adae.tlg.ae.l_listing(
    spec=AEListingSpec(
        columns=[
            Column(field="USUBJID", label="Subject"),
            Column(field="AEDECOD", label="Preferred Term"),
            Column(field="AESEV", label="Severity"),
        ],
        sort_by=["USUBJID", "AEDECOD"],
    )
)
```

### HTML & PDF export

The `fleet.tlg.render` sub-module converts ARD DataFrames into pharma-style
HTML tables and PDF documents.

```python
from fleet.tlg import RenderMetadata, ard_to_table_model, render_html

meta = RenderMetadata(
    title="Table 14.3.1.1",
    subtitle="AE Summary — Safety Population",
    footnotes=["Source: ADAE"],
)
model = ard_to_table_model(ard, meta)
html = render_html(model)
```

Or use the builder shortcut:

```python
html = (
    adae.tlg.ae.population(adsl)
    .by("TRTA")
    .rows(["AEBODSYS", "AEDECOD"])
    .stats([Statistic.N_SUBJECTS, Statistic.N_PCT])
    .to_html(
        path="ae_summary.html",
        metadata=RenderMetadata(title="Table 14.3.1.1"),
    )
)
```

PDF export requires WeasyPrint (`uv add weasyprint` or `pip install fleet-cdisc[tlg-pdf]`):

```python
path = builder.to_pdf("ae_summary.pdf", metadata=meta)
```

PPTX slide export requires python-pptx (`uv add python-pptx` or `pip install fleet-cdisc[tlg-pptx]`).
Slides are fully editable — modify text, tables, fonts, and colours in PowerPoint or
LibreOffice Impress after export:

```python
path = builder.to_pptx("ae_summary.pptx", metadata=meta)
```

Custom themes override fonts, colours, and sizes:

```python
path = builder.to_pptx(
    "ae_summary.pptx",
    metadata=meta,
    theme={"font_name": "Arial", "header_bg": "003366"},
)
```

HTML injection embeds tables in custom templates:

```python
wrapper = '<div class="portal">{table}</div>'
html = render_html(model, html_wrapper=wrapper)
```

### CLI export

```bash
fleet tlg export --domain ae --data adae.csv --adsl adsl.csv \
    --title "Table 14.3.1.1" --footnote "Source: ADAE" --output ae.html

fleet tlg export --domain ae --format pdf --data adae.csv --adsl adsl.csv \
    --output ae.pdf

fleet tlg export --domain ae --format pptx --data adae.csv --adsl adsl.csv \
    --title "Table 14.3.1.1" --output ae.pptx
```

---

## Part 12 — CDISC Validation

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

1. **`study_config.yaml`** — `validation.engine_path` (relative or absolute); committed to VCS for team use. Inside a study it beats the environment variable.
2. **`FLEET_RULES_ENGINE` env var** — set in `.env` or shell; applies when the study config pins no engine, and outside a study.
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
- `.print_report(report_type="summary")` — formatted console output (`"summary"` = compact one-liner per issue, `"full"` = expanded with all fields including INFO)
- `.save_html_report(path)` — HTML report for archiving

### 11.4 Remove the engine

```bash
uv run fleet uninstall-engine
```

> **Note:** `pyreadstat` is also required for validation (XPT serialization). Install it with `uv sync --extra io`.

### 11.5 Cache CDISC conformance rules

```bash
# After fleet init define has created your define.yaml files:
uv run fleet init rules

# SDTM only
uv run fleet init rules --sdtm-only

# Overwrite previously cached rules
uv run fleet init rules --force
```

`fleet init rules` reads the IG version from each `define.yaml` (`study.standard_version`),
fetches **all** conformance rules for that IG from the CDISC Library API, and writes one
YAML file per domain into `metadata/sdtm/rules/` and `metadata/adam/rules/`.

Each YAML file contains the rule's CORE ID, description, check logic, scope, severity, and
citations. Commit these files to VCS — they serve as a **permanent, version-locked audit
trail** of the exact rules that were in scope for the study at the time of validation.

### 11.6 Custom validation rules

When the CDISC CORE rule set does not cover a study-specific check (e.g. a sponsor SOP
constraint, an FDA TCG requirement not yet in CORE, or a protocol-specific range check),
you can author custom rules in the same YAML format used by the engine.

#### Configuration

Add a `custom_rules` path to your `study_config.yaml` to set a team-wide default:

```yaml
validation:
  engine_path: null
  custom_rules: metadata/custom_rules  # directory containing your .yaml rule files
```

`fleet init cfg` scaffolds this by default. The engine picks up **all `.yaml` files**
in the configured directory.

#### Scaffold a new rule with the CLI

Use `fleet add-rule` to generate a schema-valid YAML skeleton — you only need to fill
in the `Check:` block with your logic:

```bash
# Basic — auto-increments the rule ID (FLEET-AE-001, FLEET-AE-002, …)
uv run fleet add-rule --domain AE --description "AESEV must be populated when AESER = Y"

# Custom prefix (e.g. your company name)
uv run fleet add-rule --domain AE --prefix ROCHE --description "AESEV required for serious AEs"

# Explicit ID (skips auto-increment)
uv run fleet add-rule --domain AE --id ROCHE-AE-042 --description "Custom check"

# Write to a specific directory (overrides study_config)
uv run fleet add-rule --domain VS --description "VSORRES range check" --output ./my_rules/
```

The generated file includes all required CDISC schema sections with a placeholder
`Check:` block containing a `# TODO` comment. The uniqueness check ensures no two rules
share the same `Core.Id` within the target directory.

#### Run validation with custom rules

**From a pipeline (inline):**

```python
ae = (
    raw_df.sdtm.assign("DOMAIN", value="AE")
    .assign("USUBJID", source="subject_id")
    .validate("AE", custom_rules="metadata/custom_rules")
    .to_frame()
)
```

**From the service (programmatic):**

```python
from fleet.validation.service import ValidationService

svc = ValidationService()
result = svc.validate_sdtm(ae, domain="AE", version="3.4", custom_rules="metadata/custom_rules")
result.print_report()
```

**Resolution order:** The `custom_rules` parameter on `.validate()` takes precedence
over the `validation.custom_rules` path in `study_config.yaml`. If neither is set,
no custom rules are loaded.

#### ID convention

Use a prefix to avoid clashing with official `CORE-XXXXXX` identifiers:

| Pattern | Example |
|---------|---------|
| `<COMPANY>-<DOMAIN>-<NNN>` | `ROCHE-AE-001` |
| `FLEET-<DOMAIN>-<NNN>` | `FLEET-DM-003` |

#### Rule YAML structure

```yaml
Core:
  Id: FLEET-AE-001
  Status: Draft
  Version: "1"

Rule Type: Record Data

Scope:
  Classes:
    Include: [EVENTS]
  Domains:
    Include: [AE]

Check:                              # ← This is what you edit
  all:
    - name: AESER
      operator: equal_to
      value: "Y"
      value_is_literal: true
    - name: AESEV
      operator: empty

Outcome:
  Message: "AESEV is empty for a record where AESER = 'Y'."
  Output Variables: [USUBJID, AETERM, AESER, AESEV]

Description: >-
  AESEV must be populated when AESER = 'Y'.
```

Available operators in the `Check:` block: `equal_to`, `not_equal_to`, `empty`,
`non_empty`, `less_than`, `greater_than`, `less_than_or_equal_to`,
`greater_than_or_equal_to`, `contains`, `does_not_contain`, `is_contained_by`,
`starts_with`, `ends_with`, `matches_regex`.

#### Validate the rule schema

The vendored JSON Schema at `src/fleet/validation/schemas/cdisc_rule_schema.json` can
be used to validate your rule before running the engine:

```python
from fleet.validation.rule_scaffolder import scaffold_rule
from test_custom_rule import validate_rule_schema

errors = validate_rule_schema(rule_dict)
```

---

## Part 13 — Generate Define-XML

### From the CLI

```bash
# SDTM Define-XML
uv run fleet define-xml \
  --spec examples/cdiscpilot01/sdtm/define.yaml \
  --output outputs/define_sdtm.xml \
  --enrich-methods

# ADaM Define-XML (without HTML preview)
uv run fleet define-xml \
  --spec examples/cdiscpilot01/adam/define.yaml \
  --output outputs/define_adam.xml \
  --enrich-methods \
  --no-preview
```

`--enrich-methods` instructs Fleet to emit a `<MethodDef>` for every derivation
in the spec, populated from the docstring of the referenced verb
(`algorithm:`) or study callable (`callable:`). Each `<ItemDef>` gets a
`MethodOID` attribute pointing at it, so reviewers see the exact computational
method beside every variable.

### From Python

```python
from fleet import DefineSpecGenerator, DatasetChecker

# Check datasets against the spec before generating
sdtm_spec = "examples/cdiscpilot01/sdtm/define.yaml"
adam_spec = "examples/cdiscpilot01/adam/define.yaml"

sdtm_checker = DatasetChecker(sdtm_spec)
adam_checker = DatasetChecker(adam_spec)

sdtm_checker.check(dm, dataset="DM").print_report()
adam_checker.check(adsl, dataset="ADSL").print_report()
adam_checker.check(advs, dataset="ADVS").print_report()

# Use strict=False during development to downgrade Req errors to warnings
sdtm_checker.check(dm, dataset="DM", strict=False).print_report()

# Generate Define-XML 2.1 (enrich_methods=True emits one <MethodDef> per Derived variable)
DefineSpecGenerator(sdtm_spec, enrich_methods=True).generate("outputs/define_sdtm.xml")
DefineSpecGenerator(adam_spec, enrich_methods=True).generate("outputs/define_adam.xml")
```

---

## Part 14 — Export Datasets

### Parquet (development)

```python
from fleet import save_parquet

save_parquet(dm, "outputs/sdtm/dm.parquet")
save_parquet(ae, "outputs/sdtm/ae.parquet")
save_parquet(vs, "outputs/sdtm/vs.parquet")
save_parquet(adsl, "outputs/adam/adsl.parquet")
save_parquet(advs, "outputs/adam/advs.parquet")
save_parquet(adae, "outputs/adam/adae.parquet")
```

### SAS XPT (regulatory submission)

```python
from fleet.io import save_xpt

save_xpt(dm, "outputs/sdtm/dm.xpt")
save_xpt(ae, "outputs/sdtm/ae.xpt")
save_xpt(vs, "outputs/sdtm/vs.xpt")
save_xpt(adsl, "outputs/adam/adsl.xpt")
save_xpt(advs, "outputs/adam/advs.xpt")
save_xpt(adae, "outputs/adam/adae.xpt")
```

> **Note:** XPT export requires `pyreadstat`. Install with `uv sync --extra io`. Column names are automatically upper-cased and truncated to 8 characters per SAS Transport format.

### CDISC Dataset-JSON v1.1 (recommended)

Dataset-JSON is the modern CDISC exchange format — no external dependencies required. It is the default format used by Fleet's validation subsystem and is accepted natively by the CDISC Rules Engine.

```python
from fleet.io import save_dataset_json

save_dataset_json(dm, "outputs/sdtm/dm.json", domain="DM")
save_dataset_json(ae, "outputs/sdtm/ae.json", domain="AE")
save_dataset_json(adsl, "outputs/adam/adsl.json", domain="ADSL")
save_dataset_json(adae, "outputs/adam/adae.json", domain="ADAE")
```

Or use the terminal verb directly on a pipeline (no `to_frame()` needed):

```python
path = (
    raw_df.sdtm.assign("DOMAIN", value="DM")
    .assign("USUBJID", source="subject_id")
    .to_dataset_json("outputs/sdtm/dm.json", domain="DM")
)
```

---

## Part 15 — Debugging Pipelines

### `.inspect()` — hard checkpoint

Materialises the pipeline at that point, prints schema + shape + first rows, and resumes from the checkpoint.

```python
dm = (
    dm_raw.sdtm.assign("DOMAIN", value="DM")
    .assign("USUBJID", source="patient_number")
    .inspect(prefix="After USUBJID")
    .date("RFSTDTC", source="first_dose_date")
    .to_frame()
)
```

### `.explain()` — query plan

Prints the Polars logical plan without materialising.

```python
dm = dm_raw.sdtm.assign("DOMAIN", value="DM").explain().to_frame()
```

Both verbs are available on `.sdtm` and all ADaM namespaces. `.trail()` prints
each derived variable's origin (verb + source columns) from the lineage graph.

---

## Part 16 — Complete End-to-End Summary

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

Verb sets grow; this cheat sheet lists the **canonical** verbs you reach for
most. For the authoritative, always-current list on any namespace — including
one-line summaries generated from the live docstrings — call `.verbs()`:

```python
import fleet  # noqa: F401
import polars as pl

df = pl.DataFrame({"x": [1]})
print(df.sdtm.verbs())  # SDTM
print(df.adam.verbs())  # ADaM BDS
print(df.adam.adsl.verbs())  # ADSL
print(df.adam.occds.verbs())  # OCCDS
print(df.tlg.catalog())  # TLG template registry
```

### SDTM verbs (`df.sdtm`) — canonical highlights

| Verb                 | Purpose                                          |
| -------------------- | ------------------------------------------------ |
| `assign`             | Copy (`source=`) or hardcode (`value=`) a variable; add `ct=`/`ct_map=` for CT |
| `case_when`          | Multi-branch conditional (`when=[…]`, `else_=`)  |
| `date`               | Date/datetime normalisation                      |
| `condition_add`      | `IF X THEN Y ELSE NULL`                          |
| `ae_aerel`           | AE relatedness mapping                           |
| `merge`              | Join a reference dataset (`on=`, `keep=`, `where=`) |
| `keep`               | Restrict frame to named columns                  |
| `nodup`              | Detect/remove duplicates with diagnostics        |
| `group_by`           | Aggregate to summary rows (`by=`)                |
| `notsubmitted`       | Set columns to null                              |
| `multiple_responses` | Expand pipe-delimited fields into rows           |
| `flag` family        | `flag` + `flag_first`/`flag_last`/`flag_extreme`/`flag_exists`/`flag_relative` |
| `pin` / `repin` / `pins` | Attach / replace / inspect reference domains |
| `study_day`          | CDISC study day (consumes pinned DM)             |
| `baseline_flag`      | Last pre-reference-date observation flag         |
| `fk_policy`          | Set FK-check severity (warn/error/off)           |

### ADaM verbs (`df.adam`) — canonical highlights

The shared-verb mixin (`assign`, `case_when`, `merge`, `source`, `derivation`,
`recode`, `whereclauses`, `date`, `duration`, `flag`, `keep`, `pin`, `study_day`,
`join_adsl`, `merge_adsl`, `nodup`, …) is available on **every** ADaM
sub-namespace, so you rarely need to switch back to the base `adam` namespace.

| Verb                     | Purpose                            |
| ------------------------ | ---------------------------------- |
| `source`                 | Variadic carry-over from SDTM      |
| `assign`                 | Copy / hardcode / rename (`source=`/`value=`) |
| `derivation`             | Arbitrary Polars expression        |
| `recode`                 | Map values to new labels           |
| `case_when`              | Multi-branch conditional           |
| `merge`                  | Join a reference dataset           |
| `whereclauses`           | Filter rows                        |
| `date`                   | Parse DTC → Date/Datetime          |
| `duration`               | ADY / elapsed time / ISO duration (`start=`, `end=`) |
| `baseline`               | BASE = AVAL at baseline (`strict=True` guards dup flags) |
| `chg` / `pchg`           | Change / percent change from BASE  |
| `flag` family            | General "Y" flag + typed wrappers  |
| `bmi` / `bsa` / `map` / `qtc` | Vital-sign / ECG calculations |
| `nrind`                  | LOW / NORMAL / HIGH                |
| `on_treatment` / `shift` | On-treatment flag / shift string   |
| `derive_summary_records` / `derive_locf_records` / `derive_param` | Multi-row generators |
| `atoxgr` / `combine_grades` | CTCAE / DAIDS toxicity grading  |
| `transform`              | Apply a `@derivation` frame function |
| `pin` / `join_adsl` / `study_day` | Cross-domain reference verbs |

### ADSL verbs (`df.adam.adsl`)

| Verb            | Purpose                                                      |
| --------------- | ------------------------------------------------------------ |
| `first_date`    | Earliest date from event dataset                             |
| `last_date`     | Latest date from event dataset                               |
| `count_events`  | Count matching records per subject                           |
| `pick`          | First/last event value(s) by ordered by-group               |
| `age_years` / `age_from_dates` | Age → years                                   |
| `derive_period` | Subperiod/Phase variables                                    |

### OCCDS verbs (`df.adam.occds`)

| Verb                 | Purpose                                     |
| -------------------- | ------------------------------------------- |
| `seq`                | Sequential record number (ASEQ, `by=`)      |
| `treatment_emergent` | TRTEMFL = "Y" on/after TRTSDT               |
| `onset_recovery`     | Event started on-treatment and resolved     |

### TLG builder verbs (`df.tlg.<domain>`)

| Verb           | Purpose                                      |
| -------------- | -------------------------------------------- |
| `population`   | Set ADSL for big-N + optional `adsl_filter`  |
| `filter`       | Dataset filter (primary dataset only)        |
| `by`           | Primary grouping column (treatment arm)      |
| `template`     | Target a registry template (`aet01`, `lbt02`…) |
| `header_rows`  | Whole-dataset aggregate rows (`OverallStat`) |
| `rows`         | Row hierarchy fields (1 or 2 levels)         |
| `stats`        | Statistics to compute                        |
| `value` / `label` / `decimals` | Continuous value col, label col, per-stat rounding |
| `pools`        | Pooled treatment group definitions           |
| `column_order` | Display column ordering                      |
| `to_ard`       | Materialise → ARD DataFrame                  |
| `to_listing`   | Materialise → listing DataFrame              |
| `to_spec`      | Serialise builder state → spec model         |
| `to_html` / `to_rtf` / `to_pdf` / `to_pptx` | Render (RTF/PDF/PPTX need optional deps) |

### Renamed in pre-alpha

The pre-alpha verb/kwarg spellings (`assign_no_ct`, `assign_ct`, `hardcode_*`,
`dataset_level`, `assigned`, `rename`, `if_then_else`, `condderivation`,
`lookup`; `groups=`/`by_vars=`/`group_cols=`/`group_by=` → `by=`;
`target_cols=`/`keep_cols=` → `keep=`) were removed outright — no deprecation
shims remain. Old external scripts migrate in one command:
`python -m fleet.tools.migrate <files...> --write` (or `fleet migrate`).
Spec-file algorithm ids (`algorithm: assign_no_ct`, …) are the stable YAML
vocabulary and are unaffected.

---

## Part 17 — Maintaining `llms.txt`

`llms.txt` is **generated — never edit by hand**. Regenerate after API changes:

```bash
uv run python scripts/build_llms.py
uv run python scripts/build_llms.py --check   # CI stale-check
```

## Part 18 — Study-Specific Derivations (`@derivation`)

### When to use `@derivation` vs inline `.derivation(expression=...)`

| Scenario                                   | Recommended form                                           |
| ------------------------------------------ | ---------------------------------------------------------- |
| One-liner row transform, no reuse needed   | `.derivation("VAR", expression=pl.col(...))`               |
| Multi-line logic, reused across datasets   | `@derivation` object in `derivations/` folder              |
| Logic needs version control / traceability | `@derivation` object — `dotted_path` ends up in Define-XML |
| Referenced from `define.yaml` `callable:`  | `@derivation` object — auto-registered on import           |

### The `derivations/` folder convention

Fleet creates this structure on `fleet init cfg`:

```
specs/<study_id>/adam/derivations/
    __init__.py    # import all derivations here for auto-registration
    AGEGR1.py
    BMI.py
```

Scaffold a new derivation with the CLI:

```bash
# Column-kind (zero-arg, returns pl.Expr):
fleet derivation add AGEGR1 --dataset ADSL --kind column

# Frame-kind (receives DataFrame, returns DataFrame):
fleet derivation add add_pop_flags --dataset ADSL --kind frame

# Param-kind (by-group reshape):
fleet derivation add BMI --dataset ADVS --kind param
```

### How `callable:` in `define.yaml` links to runtime execution

```yaml
# examples/cdiscpilot01/adam/define.yaml
- name: AGEGR1
  label: Pooled Age Group 1
  derivation:
    algorithm: callable
    callable: examples.cdiscpilot01.adam.derivations.AGEGR1
```

At runtime, `from_spec()` calls `_resolve_callable("examples.cdiscpilot01.adam.derivations.AGEGR1")`,
which either:

1. Looks up the name in the transform registry (if the derivations module was imported), or
2. Imports the dotted path at execution time.

The `Derivation` object's `kind` determines routing:

- `kind="column"` → expression added to lazy plan (no materialisation)
- `kind="frame"` / `kind="param"` → pipeline materialised, function called, result re-wrapped

### How Define-XML MethodDef text is resolved

When `fleet define-xml --enrich-methods` is run, `DefineSpecGenerator` emits
one `<MethodDef>` per **Derived** variable (`Algorithm for <VARIABLE>`),
choosing its `<Description>` in this order:

1. The variable's `comment:` in the spec — always wins.
2. For `callable:` derivations, the study callable's docstring
   (`@derivation` objects use `obj.fn.__doc__`; `obj.dotted_path` becomes
   the `<FormalExpression>`).
3. The algorithm registry's submission-facing template with the spec params
   filled in (e.g. `chg` → `Change from baseline: AVAL - BASE.`).

Fleet verb docstrings are never emitted — the same spec renders the same
text on any Fleet version. This creates a verifiable link between the
regulatory submission and the exact code that produced the data.
