# Trial Design Domains

Fleet provides first-class support for all nine CDISC Trial Design Model (TDD)
domains through two complementary paths:

1. **`fleet.StudyDesign`** — a typed aggregate: define the design once,
   derive every domain, audit it, round-trip it through YAML, import it from
   USDM, and draw it as a Mermaid review diagram.
2. **Row-level pipeline** — a fixed-sequence verb chain with rich Pydantic
   models and collection-level validators, for full row control.

SDTMIG 3.4 structures for the TDD domains **ship with Fleet**, so everything
on this page runs offline — no CDISC Library API key required.

## Overview

| Domain | Full Name                 | Structure             | Type               |
| ------ | ------------------------- | --------------------- | ------------------ |
| **TE** | Trial Elements            | 1 rec/element         | Protocol-reference |
| **TA** | Trial Arms                | 1 rec/element/arm     | Protocol-reference |
| **TV** | Trial Visits              | 1 rec/visit/arm       | Protocol-reference |
| **TS** | Trial Summary             | 1 rec/parameter/seq   | Protocol-reference |
| **TI** | Trial Inclusion/Exclusion | 1 rec/criterion       | Protocol-reference |
| **TD** | Trial Disease Assessments | 1 rec/assessment plan | Protocol-reference |
| **TM** | Trial Disease Milestones  | 1 rec/milestone type  | Protocol-reference |
| **SV** | Subject Visits            | 1 rec/subject/visit   | Subject-level      |
| **SE** | Subject Elements          | 1 rec/subject/element | Subject-level      |

## StudyDesign — define once, derive everything

`fleet.StudyDesign` is the single source of truth for a study's structure.
Arms are declared as **element paths**; `TAETORD`, `ELEMENT`, `EPOCH`, and
`TABRANCH` (at the randomization branch point) are derived mechanically:

```python
import fleet

design = fleet.StudyDesign(
    study_id="CDISCPILOT01",
    elements=[
        {
            "etcd": "SCRN",
            "element": "Screening",
            "tedur": "P14D",
            "epoch": "SCREENING",
            "testrl": "INFORMED CONSENT",
            "teenrl": "RANDOMIZATION - 1",
        },
        {
            "etcd": "PBO",
            "element": "Placebo Treatment",
            "tedur": "P84D",
            "epoch": "TREATMENT",
            "testrl": "RANDOMIZATION",
        },
        {
            "etcd": "XANLO",
            "element": "Xanomeline Low Dose",
            "tedur": "P84D",
            "epoch": "TREATMENT",
            "testrl": "RANDOMIZATION",
        },
        {
            "etcd": "FU",
            "element": "Follow-up",
            "tedur": "P28D",
            "epoch": "FOLLOW-UP",
            "testrl": "END OF TREATMENT + 1",
        },
    ],
    arms={"PBO": ["SCRN", "PBO", "FU"], "XAN_LO": ["SCRN", "XANLO", "FU"]},
    arm_names={"PBO": "Placebo", "XAN_LO": "Xanomeline Low Dose"},
)

te = design.to_te()  # one domain at a time
frames = design.domains()  # or every populated domain: {"TE": df, "TA": df, ...}
```

Referential integrity is validated at construction: arm paths must reference
defined elements, visit `armcd` values must reference defined arms, and
element codes must be unique. Each arm needs its protocol name in
`arm_names` (TA.ARM). A key that the model does not read raises, in
Python and in `trial_design.yaml`, and so does a repeated YAML key.

### Arm paths: steps, branches and epochs

A path entry is an ETCD, or a step that gives the TA values of one position
([ADR 0036](../adr/0036-an-arm-path-entry-is-an-element-or-a-step.md)):

```python
design = fleet.StudyDesign(
    study_id="S1",
    elements=[...],
    arms={
        "AB": ["SCRN", "A", "WO", "B"],
        "BA": [
            "SCRN",
            {"etcd": "B", "epoch": "TREATMENT 1"},  # crossover: epoch by position
            "WO",
            {"etcd": "A", "epoch": "TREATMENT 2"},
        ],
    },
    arm_names={"AB": "Drug A then Drug B", "BA": "Drug B then Drug A"},
    randomized_at="SCRN",  # TABRANCH "Randomized to <arm>" on SCRN
)
```

TABRANCH defaults to `Randomized to <arm>` on the last element that every
arm shares, or on the `randomized_at` element. When the branch is not a
randomization (a responder extension, a cohort assignment), give the real
rule on the step: `{"etcd": "CORE", "tabranch": "Responder at end of Core"}`.
`tatrans` gives TATRANS the same way. `design.audit()` warns when two arms
have the same path (FLEETTD04) and when an element repeats in an arm with no
per-position epoch (FLEETTD05).

### Interchange formats

| Method | Direction | Use case |
| ------ | --------- | -------- |
| `StudyDesign.from_yaml(path)` / `design.to_yaml(path)` | YAML ⇄ | `trial_design.yaml` spec, versioned next to `define.yaml` |
| `StudyDesign.from_mermaid(text, study_id=...)` / `design.to_mermaid()` | Mermaid ⇄ | Review diagram: arm paths, ETCD, ELEMENT, TEDUR, epochs. Not ARM, rules, TABRANCH or a crossover; YAML is the lossless path |
| `StudyDesign.from_usdm(json_dict)` | USDM → | Import a CDISC USDM / DDF export (e.g. from OpenStudyBuilder): arms, epochs, elements, study cells, encounters, eligibility criteria |
| `TrialParameters.from_ctgov("NCT...")` | ctgov → | Seed TS from the ClinicalTrials.gov v2 API |

## Conformance audit — a P21 dry-run, offline

One CLI command (config-context — the design spec resolves from
`study_config.yaml`; exit code 1 on errors, so it drops straight into CI):

```bash
uv run fleet tdd audit
```

The same audit from Python — `design.audit()`, or the standalone
`fleet.sdtm.trial_design_audit(te=..., ta=..., tv=..., ts=..., ti=..., dm=..., td=..., tm=...)` —
checks the domains against published P21/FDA rule IDs and returns a findings
DataFrame (`rule_id`, `severity`, `domain`, `message`):

```python
findings = design.audit(dm=dm)
errors = findings.filter(pl.col("severity") == "error")
```

Encoded checks include:

| Area | Rules |
| ---- | ----- |
| All  | A Req variable of the SDTMIG 3.4 structure that is absent, null or blank (FLEETTD08), for TE, TA, TV, TI, TD and TM |
| TE   | ETCD length (SD1009), TEENRL/TEDUR presence (SD0089), duplicates (SD1271) |
| TA   | TAETORD unique per arm (SD1052), ARM↔ARMCD one-to-one (SD1033/SD1034), reserved ARMCDs (SD1053), ARMCD length (SD1004) |
| TA↔TE | ETCD not in TE, and ELEMENT consistency when both have ELEMENT, UNPLAN-aware (SD0067); unused elements (SD1378) |
| TV   | VISITNUM unique per ARMCD, no VISITNUM with both a blank-ARMCD row and an arm row (FLEETTD06), ARMCD FK vs TA |
| TI   | IETESTCD format (SD0018), uniqueness within TIVERS (SD1286) |
| DM↔TA | Undefined arms, arms without subjects (SD1354), a DM (ARMCD, ARM) pair that TA does not hold (FLEETTD07, warning) |
| TS   | The FDA Technical Conformance Guide required-parameter profile (SD22xx — a missing `SSTDTC` is flagged as **rejection-level** TRC 1734) and conditional rules (e.g. INTMODEL/INTTYPE/PCLAS when STYPE=INTERVENTIONAL — SD1310/11/12) |
| Design | `design.audit()` only: an empty elements or arms section (error) or visits or criteria section (warning) (FLEETTD09) |

TS coded values are **not** checked: a TSVAL outside its codelist (for
example SEXPOP `ALL`, which C66732 does not hold) and a TSPARM that does not
match its TSPARMCD give no finding. Check them against the CT package by hand.

The audit is a curated high-signal subset; run `fleet validate` (CDISC Rules
Engine) for exhaustive coverage.

## Visit schedules

Build TV from day offsets relative to an anchor event. `VISITNUM`,
`VISITDY` (CDISC no-day-zero convention), and deterministic `TVSTRL` rule
text are derived:

```python
from fleet.sdtm.tdd import TrialVisits

tv_rows = TrialVisits.from_schedule(
    [("Screening", -14), ("Baseline", 0), ("Week 4", 28), ("Week 8", 56)],
    anchor="RANDOMIZATION",
    window=3,  # or (before, after)
)
```

## CLI: `fleet tdd`

Like every Fleet command, `fleet tdd` runs in the context of the discovered
`study_config.yaml` (git-style parent walk, `--config` to override): the
design spec defaults to `<metadata_sdtm>/trial_design.yaml` and the output
directory to the config's `sdtm_data` path — so the command works from any
subdirectory of any company's folder structure. The YAML mirrors the
`StudyDesign` schema; a top-level `trial_design:` wrapper key is accepted.

```bash
uv run fleet tdd audit                       # conformance pre-check
uv run fleet tdd build --format xpt          # audit + write to <sdtm_data>/
uv run fleet tdd ctgov NCT04280705           # print TS parameters from ClinicalTrials.gov
uv run fleet tdd ctgov NCT04280705 --write   # ...or merge them into trial_design.yaml
uv run fleet tdd build --design specs/td.yaml --out /tmp/out   # explicit overrides
```

`build` writes every populated domain (parquet, xpt, or dataset-json) and
refuses to write when the audit reports errors (`--force` overrides).

## Row-level pipeline

### Protocol-Reference Domains

Protocol-reference domains (TE, TA, TV, TS, TI, TD, TM) follow a **fixed
sequence**:

```
fetch_structure() → study_header() → add_*() → to_frame()
```

Each step validates that the previous step was completed. Calling verbs out
of order raises a `ValueError` with a descriptive message.

```python
import polars as pl
from fleet.sdtm.tdd import TrialElement, TrialElements, Epoch

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

`fetch_structure()` resolves the domain structure in priority order:
`define_path=` → `save_to=` cache → **packaged SDTMIG 3.4 metadata** →
online CDISC Library. Discrepancies between the IG and Fleet's models are
reported as `UserWarning` (schema reconciliation).

### Subject-Level Domains

Subject-level domains (SV, SE) use derivation verbs that **freely mix** with
existing SDTM verbs:

```python
sv = (
    raw_visits.sdtm.assign("DOMAIN", value="SV")
    .assign("USUBJID", source="subject_id")
    .date("SVSTDTC", source="visit_date")
    .pin("DM", dm)  # RFSTDTC comes from DM
    .visit_map(
        "VISITNUM",
        "VISIT",
        date_col="SVSTDTC",
        planned_visits=tv_rows,
        ref_date="RFSTDTC",
        tolerance={"before": 3, "after": 3},
    )
    .study_day("SVSTDY", date_col="SVSTDTC")
    .to_frame()
)
```

`visit_map()` is a nearest-day window. Use it only when the CRF does not
collect the visit, and never to replace a collected VISITNUM. Its rules:

- The distance is the difference of study-day numbers, as
  `abs(SVSTDY - VISITDY)`: across the missing Day 0, Day -1 is 2 days from
  VISITDY 1. `TrialVisits.from_schedule()` writes its TVSTRL window in the
  same study days.
- When TV has ARMCD values, a subject takes only the visits of its arm and
  the visits with a blank ARMCD.
- A dated record outside every window is an unscheduled visit: it gets the
  VISITNUM of the last planned visit before it plus .1, .2, ... and the
  VISIT `UNSCHEDULED 5.1`. This numbering is a sponsor convention: check it
  against the SDRG ([ADR 0035](../adr/0035-visit-map-numbers-an-unscheduled-visit.md)).
- A record with no study day keeps a null VISITNUM. One warning gives the
  counts, and a second warning gives the USUBJID + VISITNUM keys that repeat
  in SV.

For SE, derive boundaries with `element_boundaries()` and the sequence
number with the standard `seq()` verb:

```python
se = (
    disposition_df.sdtm.assign("DOMAIN", value="SE")
    .assign("USUBJID", source="subject_id")
    .element_boundaries(
        "SESTDTC", "SEENDTC", milestones={"SCRN": "screening_date", "TRT": "first_dose_date"}
    )
    .seq("SESEQ", order_by=["SESTDTC"])
    .to_frame()
)
```

### EPOCH stamped from SE

`epoch_assign(se=...)` derives EPOCH for **any** domain from the subject's
own element intervals — the cross-domain consistency that P21 checks
against SE. (The study-level `epoch_ranges=` form remains available.)

```python
ae = (
    ae_raw.sdtm.assign("USUBJID", source="subject_id")
    .date("AESTDTC", source="ae_start_date")
    .epoch_assign("EPOCH", date_col="AESTDTC", se=se)
    .to_frame()
)
```

## Collection Models

Every `add_*()` verb requires a **collection model** (not a bare list).
Collections enforce integrity at construction time:

| Collection                | Checks                                        |
| ------------------------- | --------------------------------------------- |
| `TrialElements`           | Unique ETCD                                   |
| `TrialArms`               | Unique TAETORD per arm, FK to TE (opt.)       |
| `TrialVisits`             | Unique VISITNUM per arm, FK to TA (opt.)      |
| `TrialParameters`         | Unique (TSPARMCD, TSSEQ)                      |
| `TrialCriteria`           | Unique IETESTCD per TIVERS                    |
| `TrialDiseaseAssessments` | Unique TDORDER                                |
| `TrialMilestones`         | Unique MIDSTYPE                               |

### Cross-domain FK validation

```python
ta = (
    pl.DataFrame()
    .sdtm.fetch_structure("TA")
    .study_header("CDISCPILOT01", "TA")
    .add_arms(ta_rows, te=te_rows)  # TA.ETCD ∈ TE.ETCD
    .to_frame()
)

tv = (
    pl.DataFrame()
    .sdtm.fetch_structure("TV")
    .study_header("CDISCPILOT01", "TV")
    .add_visits(tv_rows, ta=ta_rows)  # TV.ARMCD ∈ TA.ARMCD
    .to_frame()
)
```

Omit `te=` / `ta=` to skip the FK check during iterative development.

## TS: TSSEQ and dictionary-bound values

`TrialParameter` covers the full SDTMIG 3.4 variable set: `TSSEQ` for
repeating parameters (one row per country for `FCNTRY`, per primary outcome
for `OUTMSPRI`, ...) plus `TSGRPID`, `TSVCDREF`, `TSVCDVER` for
dictionary-bound values (SNOMED, UNII, MED-RT):

```python
TrialParameter(
    tsparmcd="INDIC",
    tsparm="Trial Disease/Condition Indication",
    tsval="Alzheimer's disease",
    tsvalcd="26929004",
    tsvcdref="SNOMED CT",
    tsvcdver="2014-03-01",
)
```

A TSVAL over 200 characters is split at a word boundary into TSVAL,
TSVAL1, ..., TSVALn (SDTMIG 3.4 TS assumption 8). TSPARM holds 40
characters at most.

`TrialParameters.from_ctgov("NCT00048217")` seeds the registry-derivable
parameters (REGID, TITLE, TPHASE, STYPE, INTMODEL, RANDOM, TBLIND, NARMS,
PLANSUB (estimated enrollment) or ACTSUB (actual enrollment), AGEMIN/AGEMAX,
SEXPOP, HLTSUBJI, SSTDTC/SENDTC, SPONSOR, OUTMSPRI,
FCNTRY) from the ClinicalTrials.gov v2 API. It is a starting point —
dictionary-bound parameters are deliberately not guessed.

The same flow from the CLI — print the `parameters:` YAML block, or merge
it directly into the study's `trial_design.yaml` (new TSPARMCD/TSSEQ rows
only, existing entries untouched), then rebuild:

```bash
uv run fleet tdd ctgov NCT04280705           # print the parameters: YAML
uv run fleet tdd ctgov NCT04280705 --write   # merge into trial_design.yaml
uv run fleet tdd build                       # → ts.parquet in <sdtm_data>/
```

## Epoch values

The `Epoch` enum is bound to NCI C99079 with the 13 terms of the default CT package.
C99079 is **extensible**: sponsor-defined terms are accepted as plain
upper-case strings anywhere an epoch is expected:

```python
from fleet.sdtm.tdd import Epoch, TrialElement

TrialElement(etcd="TRT", element="Treatment", epoch=Epoch.TREATMENT)
TrialElement(etcd="ESC", element="Escalation", epoch="DOSE ESCALATION")  # sponsor term
```

Note: `TrialElement.epoch` is a **design-time attribute** — it drives the
element→epoch mapping when deriving TA, but is not written to the TE
dataset (SDTMIG 3.4 has no EPOCH variable in TE). SE is not derived from it:
`epoch_assign(se=)` needs an EPOCH column in SE.

## Mermaid parser

Parse a Mermaid flowchart directly into a design (or use the lower-level
`parse_trial_design()` for raw TE/TA collections):

```python
design = fleet.StudyDesign.from_mermaid(
    """
    flowchart TD
    subgraph SCR[SCREENING]
        SCRN["Screening<br/>P14D"]
    end
    subgraph TRT[TREATMENT]
        DRUG["Drug Treatment<br/>P84D"]
        PBO["Placebo<br/>P84D"]
    end
    SCRN -->|DRUG_ARM| DRUG
    SCRN -->|PBO_ARM| PBO
""",
    study_id="CDISCPILOT01",
)

print(design.to_mermaid())  # a review view; YAML is the lossless round trip
```

The parser reads the drawn structure or raises. Every line must be a
header, a `subgraph`, an `end`, a node, an edge or a `%%` comment. A fork
must label each edge with its ARMCD. A cycle (a crossover or an element
that repeats in an arm), a node with no edge, a node outside a subgraph,
more than one start node and an empty diagram raise a `ValueError`. A
subgraph title that is not a C99079 term is kept as a sponsor epoch, with a
warning.
