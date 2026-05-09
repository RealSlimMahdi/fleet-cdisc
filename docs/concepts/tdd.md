# Trial Design Domains

Fleet provides first-class support for all seven CDISC Trial Design Model (TDD) domains through a **fixed-sequence verb pipeline** with **rich Pydantic models** and **collection-level validators**.

## Overview

| Domain | Full Name                 | Structure             | Type               |
| ------ | ------------------------- | --------------------- | ------------------ |
| **TE** | Trial Elements            | 1 rec/element         | Protocol-reference |
| **TA** | Trial Arms                | 1 rec/element/arm     | Protocol-reference |
| **TV** | Trial Visits              | 1 rec/visit/arm       | Protocol-reference |
| **TS** | Trial Summary             | 1 rec/parameter       | Protocol-reference |
| **TI** | Trial Inclusion/Exclusion | 1 rec/criterion       | Protocol-reference |
| **SV** | Subject Visits            | 1 rec/subject/visit   | Subject-level      |
| **SE** | Subject Elements          | 1 rec/subject/element | Subject-level      |

## Domain Dependency Chain

```
TA + TE → TV → SV
TE + TA → SE
```

## Pipeline Patterns

### Protocol-Reference Domains

Protocol-reference domains (TE, TA, TV, TS, TI) follow a **fixed sequence**:

```
fetch_structure() → study_header() → add_*() → to_frame()
```

Each step validates that the previous step was completed. Calling verbs out of order raises a `ValueError` with a descriptive message.

```python
from fleet.sdtm.tdd import TrialElement, TrialElements, Epoch

# 1. Define your trial elements using rich Pydantic models
te_rows = TrialElements(elements=[
    TrialElement(etcd="SCRN", element="Screening",
                 testrl="INFORMED CONSENT", teenrl="RANDOMIZATION - 1",
                 tedur="P14D", epoch=Epoch.SCREENING),
    TrialElement(etcd="TRT", element="Treatment",
                 testrl="RANDOMIZATION", teenrl="END OF TREATMENT",
                 tedur="P84D", epoch=Epoch.TREATMENT),
    TrialElement(etcd="FU", element="Follow-up",
                 testrl="END OF TREATMENT + 1", teenrl="END OF FOLLOW-UP",
                 tedur="P28D", epoch=Epoch.FOLLOW_UP),
])

# 2. Build the pipeline
te = (
    pl.DataFrame().sdtm
    .fetch_structure("TE", ig_version="3-4",
                     save_to="metadata/sdtm/te_structure.yaml")
    .study_header(study_id="CDISCPILOT01", domain="TE")
    .add_elements(te_rows)
    .to_frame()
)
```

### Subject-Level Domains

Subject-level domains (SV, SE) use derivation verbs that **freely mix** with existing SDTM verbs:

```python
sv = (
    raw_visits.sdtm
    .hardcode_no_ct("DOMAIN", value="SV")
    .assign_no_ct("USUBJID", source="subject_id")
    .assign_dtc("SVSTDTC", source="visit_date")
    .visit_map("VISITNUM", "VISIT", date_col="SVSTDTC",
               planned_visits=tv_rows, ref_date="RFSTDTC",
               tolerance={"before": 3, "after": 3})
    .study_day("SVSTDY", date_col="SVSTDTC", ref_date_col="RFSTDTC")
    .epoch_assign("EPOCH", date_col="SVSTDTC", epoch_ranges=epoch_map)
    .to_frame()
)
```

## Collection Models

Every `add_*()` verb requires a **collection model** (not a bare list). Collections enforce integrity at construction time:

| Collection        | Checks                                      |
| ----------------- | ------------------------------------------- |
| `TrialElements`   | Unique ETCD, epoch consistency              |
| `TrialArms`       | Sequential TAETORD per arm, FK to TE (opt.) |
| `TrialVisits`     | Unique VISITNUM, VISITDY ordering           |
| `TrialParameters` | Unique TSPARMCD                             |
| `TrialCriteria`   | Unique IETESTCD                             |

### Example: Collection Validation

```python
# This raises ValueError — duplicate ETCD
TrialElements(elements=[
    TrialElement(etcd="SCRN", element="Screening", epoch=Epoch.SCREENING),
    TrialElement(etcd="SCRN", element="Screening 2", epoch=Epoch.SCREENING),
])
# ValueError: Duplicate ETCD: {'SCRN'}
```

## Cross-Domain FK Validation

Pass upstream collections to `add_*()` verbs for foreign-key validation.
First, define the arm rows using the `TrialArms` / `TrialArm` models
(each ETCD must match an element defined in `te_rows` above):

```python
from fleet.sdtm.tdd import TrialArm, TrialArms

ta_rows = TrialArms(arms=[
    TrialArm(armcd="PBO", arm="Placebo", taetord=1,
             etcd="SCRN", element="Screening", epoch=Epoch.SCREENING),
    TrialArm(armcd="PBO", arm="Placebo", taetord=2,
             etcd="TRT", element="Treatment", epoch=Epoch.TREATMENT),
    TrialArm(armcd="PBO", arm="Placebo", taetord=3,
             etcd="FU", element="Follow-up", epoch=Epoch.FOLLOW_UP),
])
```

Then build TA with or without FK validation:

```python
# Validates TA.ETCD ∈ TE.ETCD
ta = (
    pl.DataFrame().sdtm
    .fetch_structure("TA")
    .study_header("CDISCPILOT01", "TA")
    .add_arms(ta_rows, te=te_rows)  # FK check
    .to_frame()
)

# Omit te= to skip FK check (iterative development)
ta_draft = (
    pl.DataFrame().sdtm
    .fetch_structure("TA")
    .study_header("CDISCPILOT01", "TA")
    .add_arms(ta_rows)              # no FK check
    .to_frame()
)
```

## Schema Reconciliation

`fetch_structure()` queries the CDISC Library for the domain's IG metadata
and compares it against Fleet's static Pydantic models. Discrepancies are
reported as `UserWarning`:

- **Missing required variables**: IG requires a field not in the model
- **Type mismatches**: IG declares `Num` but model uses `str`
- **Codelist drift**: IG links to a different codelist than the `Epoch` enum

## Epoch Enum

The `Epoch` enum is bound to NCI C99079 with all 14 standard values:

```python
from fleet.sdtm.tdd import Epoch

Epoch.SCREENING        # "SCREENING"
Epoch.TREATMENT        # "TREATMENT"
Epoch.FOLLOW_UP        # "FOLLOW-UP"
Epoch.BASELINE         # "BASELINE"
# ... plus 10 more
```

## Mermaid Parser (Bonus)

Parse a Mermaid flowchart directly into TE and TA collections:

```python
from fleet.sdtm.tdd import parse_trial_design

te, ta = parse_trial_design("""
    flowchart TD
    subgraph SCR[SCREENING]
        SCRN["Screening<br/>P14D"]
    end
    subgraph TRT[TREATMENT]
        TREAT["Treatment<br/>P84D"]
    end
    subgraph FU[FOLLOW-UP]
        FOLL["Follow-up<br/>P28D"]
    end
    SCRN --> TREAT
    TREAT --> FOLL
""")
```
