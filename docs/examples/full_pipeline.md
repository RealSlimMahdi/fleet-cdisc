# End-to-End Walkthrough: Multi-Domain Pipeline

[![Open in Colab](https://img.shields.io/badge/Open_in_Colab-F9AB00?style=for-the-badge&logo=googlecolab&logoColor=white)](https://colab.research.google.com/github/RealSlimMahdi/fleet-cdisc/blob/devel/docs/examples/01_code_driven_pipeline.ipynb)

> **Interactive Playground** — Click the badge above to launch a notebook in Google Colab and experiment with Fleet live, no local setup needed.

This guide walks the **whole** journey, in the order a study actually runs:
scaffold the workspace, generate metadata and codelists, derive SDTM and ADaM,
prove traceability with `.trail()`, validate against the CDISC Rules Engine,
and generate the Define-XML with an annotated CRF. The code-only core of this
flow lives in `examples/full_pipeline_example.py`.

## 1. Scaffold the study workspace

One command creates the folder tree, `study_config.yaml`, the IG-derived
`define.yaml` skeletons, and the typed `codelists.py` (requires a
[CDISC Library API key](https://library.cdisc.org) in `.env`):

```bash
uv run fleet new STUDY01 --domains DM,VS,AE --adam-datasets ADSL,ADVS
cd STUDY01
```

or step by step:

```bash
uv run fleet init cfg --study-id STUDY01 --company "Acme Pharma" \
  --domains DM,VS,AE --adam-datasets ADSL,ADVS --root ./STUDY01
cd STUDY01
uv run fleet init define   # CDISC Library IG → metadata/*/define.yaml
uv run fleet init ct       # define.yaml codelists → metadata/sdtm/codelists.py
uv run fleet init rules    # conformance rules cache (optional)
```

Every Fleet command from here on discovers `study_config.yaml` by walking up
from wherever you run it — paths below (`data/sdtm`, `metadata/...`) come
from that config, not from hard-coding.

## 2. Raw data

Synthetic EDC extracts — note the collected values (`Male`, `Weight`) that
will need controlled-terminology remapping:

```python
import polars as pl
import fleet
from fleet.ct import import_codelists

import_codelists()  # metadata/sdtm/codelists.py, made by: fleet init ct
from codelists import SEX, VSTESTCD

raw_dm = pl.from_repr("""
┌────────────┬────────┬────────────┬─────────┬────────────┐
│ subject_id ┆ sex    ┆ dob        ┆ arm     ┆ first_dose │
│ ---        ┆ ---    ┆ ---        ┆ ---     ┆ ---        │
│ str        ┆ str    ┆ str        ┆ str     ┆ str        │
╞════════════╪════════╪════════════╪═════════╪════════════╡
│ S001       ┆ Male   ┆ 1980-01-01 ┆ Drug A  ┆ 2023-01-01 │
│ S002       ┆ Female ┆ 1992-05-15 ┆ Placebo ┆ 2023-01-02 │
└────────────┴────────┴────────────┴─────────┴────────────┘
""")

raw_vs = pl.from_repr("""
┌────────────┬────────────┬────────┬────────────┬───────┬───────┐
│ subject_id ┆ test_name  ┆ result ┆ date       ┆ low   ┆ high  │
│ ---        ┆ ---        ┆ ---    ┆ ---        ┆ ---   ┆ ---   │
│ str        ┆ str        ┆ f64    ┆ str        ┆ f64   ┆ f64   │
╞════════════╪════════════╪════════╪════════════╪═══════╪═══════╡
│ S001       ┆ Weight     ┆ 80.5   ┆ 2023-01-01 ┆ null  ┆ null  │
│ S001       ┆ Heart Rate ┆ 72.0   ┆ 2023-01-01 ┆ 60.0  ┆ 100.0 │
│ S002       ┆ Weight     ┆ 65.0   ┆ 2023-01-02 ┆ null  ┆ null  │
│ S002       ┆ Heart Rate ┆ 108.0  ┆ 2023-01-02 ┆ 60.0  ┆ 100.0 │
└────────────┴────────────┴────────┴────────────┴───────┴───────┘
""")

raw_ex = pl.from_repr("""
┌────────────┬────────────┬────────────┐
│ subject_id ┆ start      ┆ end        │
│ ---        ┆ ---        ┆ ---        │
│ str        ┆ str        ┆ str        │
╞════════════╪════════════╪════════════╡
│ S001       ┆ 2023-01-01 ┆ 2023-03-01 │
│ S002       ┆ 2023-01    ┆ 2023-03-02 │
└────────────┴────────────┴────────────┘
""")

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

## 3. SDTM derivation

### DM (Demographics)

```python
dm = (
    raw_dm.sdtm.assign("STUDYID", value="STUDY01")
    .assign("DOMAIN", value="DM")
    .assign("USUBJID", source="subject_id")
    .assign("ARM", source="arm")
    .assign("SEX", source="sex", ct=SEX, ct_map={"Male": "M", "Female": "F"})
    .date("BRTHDTC", source="dob")
    .date("RFSTDTC", source="first_dose")
    .to_frame()
)
```

A `--DTC` column is text (`pl.String`) in ISO 8601. `.date()` keeps a
partial value partial (`2023-01`) and never guesses the day (SDTMIG 3.4
section 4.4). A `*DT` target (`TRTSDT`) is a `pl.Date`.

### EX (Exposure) and the reference dates

```python
ex = (
    raw_ex.sdtm.assign("STUDYID", value="STUDY01")
    .assign("DOMAIN", value="EX")
    .assign("USUBJID", source="subject_id")
    .date("EXSTDTC", source="start")
    .date("EXENDTC", source="end")
    .to_frame()
)
```

`RFXSTDTC` and `RFXENDTC` are the first and last exposure dates in EX. The
subject-level verbs `first_date` and `last_date` take them from EX. On a
`*DTC` target they keep the text of the earliest (or latest) record. A
partial value is left out with a warning, so S002 gets no `RFXSTDTC`:

```python
dm = (
    dm.adam.adsl.first_date("RFXSTDTC", from_dataset=ex, date_col="EXSTDTC")
    .last_date("RFXENDTC", from_dataset=ex, date_col="EXENDTC")
    .to_frame()
)
```

### VS (Vital Signs) — with a cross-domain pin

`study_day()` needs DM's `RFSTDTC`; instead of merging DM in, **pin** it —
the reference stays beside the frame and the output stays clean:

```python
vs = (
    raw_vs.sdtm.assign("STUDYID", value="STUDY01")
    .assign("DOMAIN", value="VS")
    .assign("USUBJID", source="subject_id")
    .assign(
        "VSTESTCD",
        source="test_name",
        ct=VSTESTCD,
        ct_map={"Weight": "WEIGHT", "Heart Rate": "HR"},
    )
    .assign("VSSTRESN", source="result")
    .assign("VSSTNRLO", source="low")
    .assign("VSSTNRHI", source="high")
    .date("VSDTC", source="date")
    .pin("DM", dm)
    .study_day("VSDY", date_col="VSDTC")  # resolves DM.RFSTDTC via the pin
    .to_frame()
)
```

### AE (Adverse Events)

```python
ae = (
    raw_ae.sdtm.assign("STUDYID", value="STUDY01")
    .assign("DOMAIN", value="AE")
    .assign("USUBJID", source="subject_id")
    .assign("AEDECOD", source="ae_term")
    .date("AESTDTC", source="start_date")
    .pin("DM", dm)
    .study_day("AESTDY", date_col="AESTDTC")
    .to_frame()
)
```

## 4. ADaM derivation

### ADSL (Subject-Level Analysis)

`TRTSDT` is the date of first exposure, so it comes from EX, not from
another domain (ADaMIG 1.3, ADSL). The EX start of S002 is partial. With
`impute="first"` (the rule of the SAP) `first_date` imputes the day and
writes `TRTSDTF`; with no `impute=` the partial value is left out:

```python
adsl = (
    dm.adam.adsl.source("STUDYID", "USUBJID", "ARM", "SEX")
    .assign("TRT01P", source="ARM")
    .first_date("TRTSDT", from_dataset=ex, date_col="EXSTDTC", impute="first")
    .last_date("TRTEDT", from_dataset=ex, date_col="EXENDTC")
    .to_frame()
)
```

### ADVS (BDS) — pin ADSL, carry columns, derive baseline

`BNRIND` is the `ANRIND` of the baseline record. `baseline()` carries any
column, text included:

```python
advs = (
    vs.adam.pin("ADSL", adsl)
    .source("STUDYID", "USUBJID", "VSTESTCD")
    .assign("PARAMCD", source="VSTESTCD")
    .assign("AVAL", source="VSSTRESN")
    .assign("ANRLO", source="VSSTNRLO")
    .assign("ANRHI", source="VSSTNRHI")
    .nrind("ANRIND", value="AVAL", low="ANRLO", high="ANRHI")
    .join_adsl("TRT01P", "TRTSDT")  # carry forward on the ADSL pin's key
    # the last pre-dose record per subject and parameter
    .flag(
        "ABLFL",
        criteria="last",
        order_by="VSDTC",
        where='pl.col("VSDY") <= 1',
        by=["USUBJID", "PARAMCD"],
    )
    .baseline("BASE", aval="AVAL", baseline_flag="ABLFL", by=["USUBJID", "PARAMCD"])
    .baseline("BNRIND", aval="ANRIND", baseline_flag="ABLFL", by=["USUBJID", "PARAMCD"])
    .chg("CHG", aval="AVAL", base="BASE")
    .to_frame()
)
```

## 5. Prove traceability — `.trail()`

Drop `.trail()` anywhere in a chain (typically just before `.to_frame()`)
and Fleet prints the origin of every derived variable — including
cross-domain pin reads, attributed as `DOMAIN.COLUMN`:

```python
advs_ns = (
    vs.adam.pin("ADSL", adsl)
    .source("STUDYID", "USUBJID", "VSTESTCD")
    .assign("AVAL", source="VSSTRESN")
    .join_adsl("TRTSDT")
    .trail()  # ← prints the table below; the pipeline continues
)
```

```text
Variable trail (4 derivation(s)):
┌───┬──────────┬────────┬──────────┐
│ # ┆ Variable ┆ Verb   ┆ Origin   │
╞═══╪══════════╪════════╪══════════╡
│ 1 ┆ STUDYID  ┆ source ┆ STUDYID  │
│ 2 ┆ USUBJID  ┆ source ┆ USUBJID  │
│ 3 ┆ VSTESTCD ┆ source ┆ VSTESTCD │
│ 4 ┆ AVAL     ┆ assign ┆ VSSTRESN │
└───┴──────────┴────────┴──────────┘
```

`join_adsl` does not record a trail row yet: the pin itself is recorded,
and `TRTSDT` does not show in this table.

This is the machine-checkable answer to "where did this number come from" —
the same lineage feeds `to_spec_yaml()` (pipeline → define.yaml round-trip)
and the Define-XML method descriptions.

## 6. Validate — are we CDISC compliant?

Validation is a **verb** — chain `.validate()` right where the dataset is
born and the CDISC Rules Engine report prints without breaking the pipeline
(`fleet install-engine` once, first). Revisiting the AE chain from step 3:

<!-- docs:no-run: needs the raw AE data of a study -->

```python
ae = (
    raw_ae.sdtm.assign("STUDYID", value="STUDY01")
    .assign("DOMAIN", value="AE")
    .assign("USUBJID", source="subject_id")
    .assign("AEDECOD", source="ae_term")
    .date("AESTDTC", source="start_date")
    .pin("DM", dm)
    .study_day("AESTDY", date_col="AESTDTC")
    .validate("AE")  # ← CORE report prints here; the chain continues
    .to_frame()
)
```

```text
======================================================================
CDISC Validation Report: AE
======================================================================
Standard:     SDTMIG (namespace)
IG version:   3.4 (default)
...
Dataset Type: sdtmig v3.4
Status: FAIL
Rules (engine run, official): 75 executed, 340 skipped, 15 could not run
Total Issues: 19
  Errors: 17, Warnings (accepted): 0, Info: 2
----------------------------------------------------------------------

ERRORS (9 unique, 17 total):

1. [CORE-000182] (official) Variable name length is greater than 8.
   Variable: variable_name
...
3. [CORE-000355] (official) At least one required variable is missing from dataset
   Variable: AESEQ, AETERM
...
```

This is a real run (CORE 0.15.0). The toy AE has no `AESEQ` and no
`AETERM`, and it keeps the raw columns (`subject_id` is longer than 8
characters), so CORE reports them. The report is a warning: the chain
continues.

For a CI pipeline, make compliance a hard gate — `on_fail="raise"` turns
a finding that `validation.accepted` does not list into a `ValidationError`
instead of a warning:

<!-- docs:no-run: needs the DM of a study -->

```python
adsl = (
    dm.adam.adsl.source("STUDYID", "USUBJID", "ARM", "SEX")
    .assign("TRT01P", source="ARM")
    .date("TRTSDT", source="RFSTDTC")
    .validate("ADSL", on_fail="raise")  # ← a finding not accepted stops the build
    .to_frame()
)
```

The full `ValidationResult` stays retrievable via the namespace's
`last_validation` property when you need programmatic access to findings.
To sweep every written dataset at once (e.g. a nightly job), the batch
equivalent is `uv run fleet validate --report outputs/validation.html`.
(Note: official executable ADaMIG rules are not yet published by CDISC —
ADaM datasets run your custom rules; see
[Validation with CORE](../concepts/validation-core.md).)

## 7. Define-XML with an annotated CRF

Declare the aCRF once (it edits `metadata/sdtm/define.yaml` in place —
point `--href` at your real annotated CRF; `blankcrf.pdf` is the
conventional placeholder name in a submission package):

```bash
uv run fleet add-acrf --href blankcrf.pdf --standard both
```

Tag CRF-collected variables with their page numbers in the define.yaml
(`origin: Collected` + `crf_pages: "8"` — see
[CRF Page References](../concepts/define-yaml.md#crf-page-references)),
then generate:

```bash
uv run fleet define-xml --standard sdtm
uv run fleet define-xml --standard adam
```

Each Derived variable gets a `<MethodDef>` with its method text: a verifiable
link between the submission metadata and the exact code above. Add
`--strict` to refuse a define with a gap (a Derived variable with no method
text, or a numeric variable with no `length:`).

## 8. Bonus: read the dependency graph

The same define.yaml files describe the dependency graph. Fleet gives it as
data that an orchestrator can read. Fleet does not write a Snakefile or an
Airflow DAG file: each step of a study run is `fleet run --dataset ...`.

<!-- docs:no-run: needs the study define.yaml files -->

```python
from fleet import build_dag

dag = build_dag("metadata/sdtm/define.yaml", "metadata/adam/define.yaml")
dag.execution_order()  # → ["dm_raw", "DM", ..., "ADSL", ...]
dag.to_airflow()  # → {"ADSL": ["DM", ...], ...}: upstream datasets per dataset
dag.generate("dag.json")  # → the graph as JSON
```

## Conclusion

One workspace bootstrap, ~60 lines of pipeline code, and four CLI commands
took us from raw EDC extracts to validated SDTM/ADaM datasets with
variable-level traceability and a Define-XML — with every
path resolved from `study_config.yaml`, so the same flow runs unchanged in
any company folder structure.
