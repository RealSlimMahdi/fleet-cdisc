# Plan: Trial Design Domains — Full TDD Workflow

## TL;DR

Implement all 7 CDISC Trial Design Model domains (TE, TA, TV, TS, TI, SV, SE) in Fleet using a **fixed-sequence verb pipeline** with **rich Pydantic models**, **collection-level validators**, **cross-domain FK checks**, and a **reusable `fetch_structure()` verb** that queries the CDISC Library. Protocol-reference domains (TE, TA, TV, TS, TI) use `add_*()` verbs with schema-enforced row objects; subject-level domains (SV, SE) use derivation verbs (`visit_map`, `element_boundaries`, `epoch_assign`, `study_day`) that mix freely with existing SDTM verbs.

## Scope

| Dimension           | Count | Details                                                              |
| ------------------- | ----- | -------------------------------------------------------------------- |
| **Domains**         | 7     | TE, TA, TV, TS, TI (protocol-reference) + SV, SE (subject-level)     |
| **Verbs**           | 11    | 2 shared + 5 protocol-reference + 4 subject-level                    |
| **Pydantic models** | 12    | 7 row models + 5 collection models                                   |
| **New files**       | 4     | `tdd.py`, `_tdd_mixin.py`, `docs/concepts/tdd.md`, `docs/api/tdd.md` |
| **Modified files**  | 4     | `namespace.py`, `__init__.py`, `scaffolder.py`, `mkdocs.yml`         |

---

## CDISC Trial Design Model Context

| Domain | Full Name                 | Structure             | Key Variables                                          | Source                |
| ------ | ------------------------- | --------------------- | ------------------------------------------------------ | --------------------- |
| **TA** | Trial Arms                | 1 rec/element/arm     | ARMCD, ARM, TAETORD, ETCD, ELEMENT, EPOCH              | Protocol definition   |
| **TE** | Trial Elements            | 1 rec/element         | ETCD, ELEMENT, TESTRL, TEENRL, TEDUR                   | Protocol definition   |
| **TV** | Trial Visits              | 1 rec/visit/arm       | VISITNUM, VISIT, VISITDY, ARMCD, TVSTRL, TVENRL        | Protocol schedule     |
| **TS** | Trial Summary             | 1 rec/parameter       | TSPARMCD, TSPARM, TSVAL, TSVALNF, TSVALCD              | Protocol summary      |
| **TI** | Trial Inclusion/Exclusion | 1 rec/criterion       | IETESTCD, IETEST, IECAT, IESCAT, TIRL                  | Protocol I/E criteria |
| **SV** | Subject Visits            | 1 rec/subject/visit   | USUBJID, VISITNUM, VISIT, SVSTDTC, SVENDTC, EPOCH      | Raw visit data + TV   |
| **SE** | Subject Elements          | 1 rec/subject/element | USUBJID, SESEQ, ETCD, ELEMENT, SESTDTC, SEENDTC, EPOCH | Disposition + TE      |

**Dependency chain:** `TA + TE → TV → SV`; `TE + TA → SE` (SE may also reference SV).

---

## Core Design Principles

1. **Fixed verb sequence** for protocol-reference domains: `fetch_structure() → study_header() → add_*() → validate()/to_frame()`
2. **Rich Pydantic models** — every field uses the richest possible type (constrained strings, CT-bound enums, ISO 8601 regex, `Field(ge=1)`, min/max_length)
3. **Collection models** are the mandatory input to `add_*()` verbs (no bare lists) — all collection-level validators run at construction time
4. **Cross-domain FK validation** is opt-in via upstream injection (`te=` parameter)
5. **Subject-level verbs** (SV, SE) are freely mixable with existing SDTM verbs
6. **Static models + reconciliation warnings** — no `create_model()` (destroys IDE autocompletion); the IG fetch acts as a runtime lint
7. **`fetch_structure()`** is domain-agnostic — same verb works for all 7 TDD domains and any future SDTM domain

---

## Steps

### Phase 1: Pydantic Row & Collection Models (`src/fleet/sdtm/tdd.py`)

1. Create `Epoch` enum bound to NCI C99079 (14 standard values from existing `codelists.py`)
2. Define constrained types: `ElementCode`, `ArmCode`, `ISODuration`, `RuleExpression`
3. Create `TrialElement` row model (ETCD, ELEMENT, TESTRL, TEENRL, TEDUR, EPOCH) with `_SDTM_MAP`
4. Create `TrialArm` row model (ARMCD, ARM, TAETORD, ETCD, ELEMENT, EPOCH) with `_SDTM_MAP`
5. Create `TrialVisit` row model (VISITNUM, VISIT, VISITDY, ARMCD, TVSTRL, TVENRL) with `_SDTM_MAP`
6. Create `TrialParameter` row model (TSPARMCD, TSPARM, TSVAL, TSVALNF, TSVALCD) with `_SDTM_MAP`
7. Create `TrialCriterion` row model (IETESTCD, IETEST, IECAT, IESCAT, TIRL) with `_SDTM_MAP`
8. Create `TrialElements` collection model — unique ETCD check, epoch consistency check, `to_polars()`
9. Create `TrialArms` collection model — sequential TAETORD check, FK check via context, `to_polars()`
10. Create `TrialVisits` collection model — unique VISITNUM, VISITDY ordering, `to_polars()`
11. Create `TrialParameters` collection model — unique TSPARMCD, `to_polars()`
12. Create `TrialCriteria` collection model — unique IETESTCD, `to_polars()`

### Phase 2: TDD Mixin (`src/fleet/sdtm/_tdd_mixin.py`)

13. Create `TrialDesignMixin` class with `_tdd_stage` tracking and `_check_stage()` helper (~15 lines)
14. Verb: `fetch_structure(domain, *, ig_version="3-4", save_to=None)` — queries CDISC Library, caches YAML, sets `_domain_meta`, performs schema reconciliation
15. Verb: `study_header(study_id, domain)` — hardcodes STUDYID + DOMAIN, validates domain against `_domain_meta`
16. Verb: `add_elements(elements: TrialElements)` — converts to Polars, validates against IG, materialises
17. Verb: `add_arms(arms: TrialArms, *, te: TrialElements | None = None)` — FK check via context
18. Verb: `add_visits(visits: TrialVisits)` — same pattern
19. Verb: `add_parameters(params: TrialParameters)` — same pattern
20. Verb: `add_criteria(criteria: TrialCriteria)` — same pattern

### Phase 3: Subject-Level Derivation Verbs (in `_tdd_mixin.py`)

21. Verb: `visit_map(target_num, target_name, *, date_col, planned_visits, ref_date=None, tolerance=None)` — joins raw dates to TV
22. Verb: `element_boundaries(target_start, target_end, *, milestones, element_col, subject_col)` — derives element start/end from milestones
23. Verb: `epoch_assign(target, *, date_col, epoch_ranges)` — maps dates to EPOCH
24. Verb: `study_day(target, *, date_col, ref_date_col)` — CDISC study day (no day 0)

### Phase 4: Integration

25. Add `TrialDesignMixin` to `SDTMNamespace` inheritance in `src/fleet/sdtm/namespace.py`
26. Update `src/fleet/sdtm/__init__.py` exports
27. Extract `_parse_ig_variable()` / `_parse_ig_dataset()` from `src/fleet/core/scaffolder.py` into importable functions

### Phase 5: Tests

28. Unit tests for Pydantic field validation (reject bad types, boundary values)
29. Unit tests for collection-level validation (duplicate keys, ordering, FK)
30. Unit tests for cross-domain FK (with and without upstream injection)
31. Unit tests for sequence enforcement (wrong order → `ValueError`)
32. Unit tests for `fetch_structure()` (mocked API, cache-first, reconciliation warnings)
33. Integration tests: full TE → TA → TV pipelines producing correct DataFrames
34. Integration tests: SV and SE with `visit_map()`, `element_boundaries()`, `epoch_assign()`, `study_day()`
35. Regression: existing SDTM tests still pass

### Phase 6: Documentation

36. Create `docs/concepts/tdd.md` — collection models, cross-domain validation, pipeline pattern, dependency map
37. Create `docs/api/tdd.md` — verb signatures, model classes, Epoch enum
38. Add new pages to `mkdocs.yml` nav

### Phase 7: Bonus — Mermaid Parser

39. Implement `parse_trial_design(mermaid_text: str) → tuple[TrialElements, TrialArms]` (~110 lines)
40. 4 regexes: subgraphs → epochs, nodes → elements, edge labels → arm assignments, BFS → TAETORD
41. Unit tests for linear, branching, and convergence flowcharts

---

## Relevant Files

| File                                   | Action     | Purpose                                                                                      |
| -------------------------------------- | ---------- | -------------------------------------------------------------------------------------------- |
| `src/fleet/sdtm/tdd.py`                | **CREATE** | Row models (7), collection models (5), constrained types, Epoch enum, `parse_trial_design()` |
| `src/fleet/sdtm/_tdd_mixin.py`         | **CREATE** | `TrialDesignMixin` with 11 verbs + stage tracking + schema reconciliation                    |
| `src/fleet/sdtm/namespace.py`          | MODIFY     | Add `TrialDesignMixin` to `SDTMNamespace` inheritance                                        |
| `src/fleet/sdtm/__init__.py`           | MODIFY     | Export new models and mixin                                                                  |
| `src/fleet/core/scaffolder.py`         | MODIFY     | Extract `_parse_ig_variable`/`_parse_ig_dataset` as module-level functions                   |
| `mkdocs.yml`                           | MODIFY     | Add TDD doc pages to nav                                                                     |
| `docs/concepts/tdd.md`                 | **CREATE** | TDD concepts documentation                                                                   |
| `docs/api/tdd.md`                      | **CREATE** | TDD API reference                                                                            |
| `tests/unit/test_tdd_workflow.py`      | **CREATE** | Full test suite                                                                              |
| `specs/cdiscpilot01/sdtm/codelists.py` | REFERENCE  | `C99079` (EPOCH) already exists — basis for `Epoch` enum                                     |
| `src/fleet/adam/_mixins.py`            | REFERENCE  | Mixin architecture pattern                                                                   |
| `src/fleet/ct/api.py`                  | REFERENCE  | `CDISCClient._get()` — already general, no changes needed                                    |

---

## Pydantic Models Detail

### CT-Bound Enums

```python
class Epoch(str, Enum):
    """EPOCH (C99079) — all 14 CDISC-standard trial epoch values."""
    SCREENING = "SCREENING"
    BASELINE = "BASELINE"
    RUN_IN = "RUN-IN"
    WASHOUT = "WASHOUT"
    TREATMENT = "TREATMENT"
    BLINDED_TREATMENT = "BLINDED TREATMENT"
    OPEN_LABEL_TREATMENT = "OPEN LABEL TREATMENT"
    CONTINUATION_TREATMENT = "CONTINUATION TREATMENT"
    INDUCTION_TREATMENT = "INDUCTION TREATMENT"
    FOLLOW_UP = "FOLLOW-UP"
    LONG_TERM_FOLLOW_UP = "LONG-TERM FOLLOW-UP"
    OBSERVATION = "OBSERVATION"
    PRE_SCREENING = "PRE-SCREENING"
```

### Constrained Types

```python
ElementCode = Annotated[str, Field(min_length=1, max_length=8, pattern=r"^[A-Z0-9_]+$")]
ArmCode = Annotated[str, Field(min_length=1, max_length=20, pattern=r"^[A-Z0-9_]+$")]
ISODuration = Annotated[str, Field(pattern=r"^P(?:\d+Y)?(?:\d+M)?(?:\d+W)?(?:\d+D)?(?:T(?:\d+H)?(?:\d+M)?(?:\d+S)?)?$")]
RuleExpression = Annotated[str, Field(max_length=2000)]
```

### Row Models

```python
class TrialElement(BaseModel):
    """One row in the TE (Trial Elements) domain."""
    _SDTM_MAP: ClassVar[dict[str, str]] = {
        "etcd": "ETCD", "element": "ELEMENT", "testrl": "TESTRL",
        "teenrl": "TEENRL", "tedur": "TEDUR", "epoch": "EPOCH",
    }
    etcd: ElementCode
    element: str = Field(min_length=1, max_length=200)
    testrl: RuleExpression = ""
    teenrl: RuleExpression = ""
    tedur: ISODuration | Literal[""] = ""
    epoch: Epoch

class TrialArm(BaseModel):
    """One row-per-element in the TA (Trial Arms) domain."""
    _SDTM_MAP: ClassVar[dict[str, str]] = {
        "armcd": "ARMCD", "arm": "ARM", "taetord": "TAETORD",
        "etcd": "ETCD", "element": "ELEMENT", "epoch": "EPOCH",
    }
    armcd: ArmCode
    arm: str = Field(min_length=1, max_length=200)
    taetord: int = Field(ge=1)
    etcd: ElementCode
    element: str = Field(min_length=1, max_length=200)
    epoch: Epoch

class TrialVisit(BaseModel):
    """One row in the TV (Trial Visits) domain."""
    _SDTM_MAP: ClassVar[dict[str, str]] = {
        "visitnum": "VISITNUM", "visit": "VISIT", "visitdy": "VISITDY",
        "armcd": "ARMCD", "tvstrl": "TVSTRL", "tvenrl": "TVENRL",
    }
    visitnum: int = Field(ge=1)
    visit: str = Field(min_length=1, max_length=200)
    visitdy: int | None = None
    armcd: ArmCode | Literal[""] = ""
    tvstrl: RuleExpression = ""
    tvenrl: RuleExpression = ""

class TrialParameter(BaseModel):
    """One row in the TS (Trial Summary) domain."""
    _SDTM_MAP: ClassVar[dict[str, str]] = {
        "tsparmcd": "TSPARMCD", "tsparm": "TSPARM", "tsval": "TSVAL",
        "tsvalnf": "TSVALNF", "tsvalcd": "TSVALCD",
    }
    tsparmcd: str = Field(min_length=1, max_length=8, pattern=r"^[A-Z0-9_]+$")
    tsparm: str = Field(min_length=1, max_length=200)
    tsval: str = ""
    tsvalnf: str = ""
    tsvalcd: str = ""

class TrialCriterion(BaseModel):
    """One row in the TI (Trial Inclusion/Exclusion) domain."""
    _SDTM_MAP: ClassVar[dict[str, str]] = {
        "ietestcd": "IETESTCD", "ietest": "IETEST", "iecat": "IECAT",
        "iescat": "IESCAT", "tirl": "TIRL",
    }
    ietestcd: str = Field(min_length=1, max_length=8, pattern=r"^[A-Z0-9_]+$")
    ietest: str = Field(min_length=1, max_length=200)
    iecat: Literal["INCLUSION", "EXCLUSION"]
    iescat: str = ""
    tirl: RuleExpression = ""
```

### Collection Models

```python
class TrialElements(BaseModel):
    """Typed collection of TE rows with TDD-specific integrity validation."""
    elements: list[TrialElement]

    @model_validator(mode="after")
    def check_unique_etcd(self) -> "TrialElements":
        codes = [e.etcd for e in self.elements]
        dupes = [c for c in codes if codes.count(c) > 1]
        if dupes:
            raise ValueError(f"Duplicate ETCD: {set(dupes)}")
        return self

    @model_validator(mode="after")
    def check_epochs_consistent(self) -> "TrialElements":
        mapping = {}
        for e in self.elements:
            if e.etcd in mapping and mapping[e.etcd] != e.epoch:
                raise ValueError(f"ETCD {e.etcd} maps to multiple EPOCHs")
            mapping[e.etcd] = e.epoch
        return self

    def to_polars(self) -> pl.DataFrame:
        return pl.DataFrame([e.model_dump() for e in self.elements]).rename(TrialElement._SDTM_MAP)


class TrialArms(BaseModel):
    """Typed collection of TA rows with TDD integrity validation."""
    arms: list[TrialArm]

    @model_validator(mode="after")
    def check_taetord_sequential(self) -> "TrialArms":
        by_arm = {}
        for a in self.arms:
            by_arm.setdefault(a.armcd, []).append(a.taetord)
        for armcd, orders in by_arm.items():
            expected = list(range(1, len(orders) + 1))
            if sorted(orders) != expected:
                raise ValueError(f"TAETORD for {armcd} must be sequential 1..N, got {sorted(orders)}")
        return self

    @model_validator(mode="after")
    def check_etcd_references(self, info) -> "TrialArms":
        te = info.context.get("te") if info.context else None
        if te is not None:
            valid_etcds = {e.etcd for e in te.elements}
            for a in self.arms:
                if a.etcd not in valid_etcds:
                    raise ValueError(f"TA.ETCD '{a.etcd}' not found in TE")
        return self

    def to_polars(self) -> pl.DataFrame:
        return pl.DataFrame([a.model_dump() for a in self.arms]).rename(TrialArm._SDTM_MAP)


class TrialVisits(BaseModel):
    """Typed collection of TV rows with TDD integrity validation."""
    visits: list[TrialVisit]

    @model_validator(mode="after")
    def check_visitnum_unique(self) -> "TrialVisits":
        nums = [v.visitnum for v in self.visits]
        if len(nums) != len(set(nums)):
            raise ValueError("Duplicate VISITNUM values")
        return self

    @model_validator(mode="after")
    def check_visitdy_ordering(self) -> "TrialVisits":
        sorted_visits = sorted(self.visits, key=lambda v: v.visitnum)
        days = [v.visitdy for v in sorted_visits if v.visitdy is not None]
        if days != sorted(days):
            raise ValueError("VISITDY must increase with VISITNUM")
        return self

    def to_polars(self) -> pl.DataFrame:
        return pl.DataFrame([v.model_dump() for v in self.visits]).rename(TrialVisit._SDTM_MAP)


class TrialParameters(BaseModel):
    """Typed collection of TS rows."""
    parameters: list[TrialParameter]

    @model_validator(mode="after")
    def check_unique_tsparmcd(self) -> "TrialParameters":
        codes = [p.tsparmcd for p in self.parameters]
        if len(codes) != len(set(codes)):
            raise ValueError("Duplicate TSPARMCD values")
        return self

    def to_polars(self) -> pl.DataFrame:
        return pl.DataFrame([p.model_dump() for p in self.parameters]).rename(TrialParameter._SDTM_MAP)


class TrialCriteria(BaseModel):
    """Typed collection of TI rows."""
    criteria: list[TrialCriterion]

    @model_validator(mode="after")
    def check_unique_ietestcd(self) -> "TrialCriteria":
        codes = [c.ietestcd for c in self.criteria]
        if len(codes) != len(set(codes)):
            raise ValueError("Duplicate IETESTCD values")
        return self

    def to_polars(self) -> pl.DataFrame:
        return pl.DataFrame([c.model_dump() for c in self.criteria]).rename(TrialCriterion._SDTM_MAP)
```

---

## Verb Reference

### Shared Verbs (all TDD domains)

| Verb              | Signature                                     | Stage | Notes                                                                   |
| ----------------- | --------------------------------------------- | ----- | ----------------------------------------------------------------------- |
| `fetch_structure` | `(domain, *, ig_version="3-4", save_to=None)` | 0→1   | Queries CDISC Library, caches YAML, sets `_domain_meta`, reconciliation |
| `study_header`    | `(study_id, domain)`                          | 1→2   | Hardcodes STUDYID + DOMAIN                                              |

### Protocol-Reference Verbs (TE, TA, TV, TS, TI)

| Verb             | Signature                                                | Stage | Input Model       |
| ---------------- | -------------------------------------------------------- | ----- | ----------------- |
| `add_elements`   | `(elements: TrialElements)`                              | 2→3   | `TrialElements`   |
| `add_arms`       | `(arms: TrialArms, *, te: TrialElements \| None = None)` | 2→3   | `TrialArms`       |
| `add_visits`     | `(visits: TrialVisits)`                                  | 2→3   | `TrialVisits`     |
| `add_parameters` | `(params: TrialParameters)`                              | 2→3   | `TrialParameters` |
| `add_criteria`   | `(criteria: TrialCriteria)`                              | 2→3   | `TrialCriteria`   |

### Subject-Level Verbs (SV, SE)

| Verb                 | Signature                                                                               | Stage | Notes                     |
| -------------------- | --------------------------------------------------------------------------------------- | ----- | ------------------------- |
| `visit_map`          | `(target_num, target_name, *, date_col, planned_visits, ref_date=None, tolerance=None)` | free  | Joins raw dates to TV     |
| `element_boundaries` | `(target_start, target_end, *, milestones, element_col, subject_col)`                   | free  | Derives element start/end |
| `epoch_assign`       | `(target, *, date_col, epoch_ranges)`                                                   | free  | Maps dates to EPOCH       |
| `study_day`          | `(target, *, date_col, ref_date_col)`                                                   | free  | CDISC day (no day 0)      |

---

## Sequence Enforcement

The mixin tracks `_tdd_stage: int` via a `_check_stage(verb)` helper (~15 lines). Each TDD verb calls it at entry:

- Stage 0 → `fetch_structure()` (entry point)
- Stage 1 → `study_header()` (after fetch)
- Stage 2 → `add_*()` (after header)
- Stage 3 → `validate()` / `to_frame()` (after rows added)

Wrong stage → `ValueError("Cannot call add_elements() at stage 0. Expected sequence: fetch_structure() → study_header() → add_*() → validate()/to_frame()")`

Non-TDD verbs (`.derivation()`, `.hardcode_no_ct()`, etc.) remain freely chainable — stage checking only applies to TDD-specific verbs. When `_tdd_stage` is not set (regular SDTM pipeline), no enforcement occurs.

---

## fetch_structure() — What It Enables

1. **Column validation** in `add_*()`: checks output columns exist in `_domain_meta.variables`
2. **Type enforcement**: IG says VISITNUM is `integer` → verifies Polars dtype matches
3. **Mandatory field checking**: IG `core: Req` → warns when column has nulls
4. **Codelist cross-reference**: IG says EPOCH → C99079 → validates `Epoch` enum stays in sync
5. **`select()` auto-ordering**: variable ordinal defines column order in final DataFrame (CDISC display order)

### Schema Reconciliation

After fetching the IG structure, `fetch_structure()` compares it against the static Pydantic model:

- **Missing required variables**: IG `core: Req` + no Pydantic field → `UserWarning`
- **Type mismatches**: IG `Num` but Pydantic `str` → warning
- **Codelist drift**: IG links to different codelist than `Epoch` enum → warning suggesting `fleet init ct`
- **Extra fields**: Pydantic has fields not in IG → allowed (custom extensions)
- **`_reconciliation_report`** attribute set on namespace for programmatic inspection

---

## Cross-Domain FK Validation

Each `add_*()` verb accepts an optional upstream parameter. When provided, Pydantic's `context=` passes the upstream collection to `@model_validator` for FK checks:

```python
# Pass te= for FK validation (TA.ETCD ∈ TE.ETCD)
ta = (
    pl.DataFrame().sdtm
    .fetch_structure("TA", ...)
    .study_header("CDISCPILOT01", "TA")
    .add_arms(ta_rows, te=te_rows)     # validates ETCD ∈ TE.ETCD
    .to_frame()
)

# Omit te= to skip FK check (iterative development)
ta_draft = (
    pl.DataFrame().sdtm
    .fetch_structure("TA", ...)
    .study_header("CDISCPILOT01", "TA")
    .add_arms(ta_rows)                 # structural validation only
    .to_frame()
)
```

**Dependency map:**

| Verb             | Optional upstream | FK check                                               |
| ---------------- | ----------------- | ------------------------------------------------------ |
| `add_elements()` | —                 | ETCD uniqueness, EPOCH consistency (self-contained)    |
| `add_arms(te=)`  | `TrialElements`   | ETCD ∈ TE.ETCD, TAETORD sequential per arm             |
| `add_visits()`   | —                 | VISITNUM uniqueness, VISITDY ordering (self-contained) |

---

## Pipeline Examples

### TE (Trial Elements)

```python
from fleet.sdtm.tdd import TrialElement, TrialElements, Epoch

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
    .fetch_structure("TE", ig_version="3-4",
                     save_to="metadata/sdtm/te_structure.yaml")
    .study_header(study_id="CDISCPILOT01", domain="TE")
    .add_elements(te_rows)
    .to_frame()
)
```

### TA (Trial Arms)

```python
from fleet.sdtm.tdd import TrialArm, TrialArms

ta_rows = TrialArms(arms=[
    TrialArm(armcd="PBO", arm="Placebo", taetord=1, etcd="SCRN", element="Screening", epoch=Epoch.SCREENING),
    TrialArm(armcd="PBO", arm="Placebo", taetord=2, etcd="PBO_TRT", element="Placebo Treatment", epoch=Epoch.TREATMENT),
    TrialArm(armcd="PBO", arm="Placebo", taetord=3, etcd="FU", element="Follow-up", epoch=Epoch.FOLLOW_UP),
])

ta = (
    pl.DataFrame().sdtm
    .fetch_structure("TA", save_to="metadata/sdtm/ta_structure.yaml")
    .study_header("CDISCPILOT01", "TA")
    .add_arms(ta_rows, te=te_rows)  # FK check: ETCD ∈ TE.ETCD
    .to_frame()
)
```

### SV (Subject Visits) — Subject-Level

```python
sv = (
    raw_visits.sdtm
    .hardcode_no_ct("DOMAIN", value="SV")
    .assign_no_ct("USUBJID", source="subject_id")
    .assign_datetime("SVSTDTC", source="visit_date")
    .visit_map("VISITNUM", "VISIT", date_col="SVSTDTC",
               planned_visits=tv, ref_date="RFSTDTC",
               tolerance={"before": 3, "after": 3})
    .study_day("SVSTDY", date_col="SVSTDTC", ref_date_col="RFSTDTC")
    .epoch_assign("EPOCH", date_col="SVSTDTC", epoch_ranges=se_epochs)
    .to_frame()
)
```

### SE (Subject Elements) — Subject-Level

```python
se = (
    disposition_df.sdtm
    .hardcode_no_ct("DOMAIN", value="SE")
    .assign_no_ct("USUBJID", source="subject_id")
    .element_boundaries("SESTDTC", "SEENDTC",
                        milestones={"SCRN": "screening_date", "TRT": "first_dose_date", "FU": "last_visit_date"},
                        element_col="ETCD")
    .cross_reference(["ELEMENT", "TAETORD"], dataset=te, on="ETCD")
    .study_day("SESTDY", date_col="SESTDTC", ref_date_col="RFSTDTC")
    .epoch_assign("EPOCH", date_col="SESTDTC", epoch_ranges=epoch_map)
    .to_frame()
)
```

---

## Verification Criteria

1. **Pydantic field validation:** `TrialElement(etcd="SCRN", element="Screening", epoch=Epoch.SCREENING)` succeeds; `TrialElement(etcd=123)` rejects; `TrialElement(etcd="toolongcode_xx")` rejects (max_length=8); `TrialElement(tedur="14 days")` rejects (ISO 8601 pattern); `TrialElement(element="")` rejects (min_length=1); `TrialArm(taetord=0)` rejects (ge=1)
2. **Collection validation:** `TrialElements` with duplicate ETCD raises `ValueError`; `TrialArms` with non-sequential TAETORD raises; `TrialVisits` with VISITDY not increasing raises; `TrialParameters` with duplicate TSPARMCD raises; `TrialCriteria` with duplicate IETESTCD raises
3. **Cross-domain FK:** `add_arms(ta_rows, te=te_rows)` rejects orphaned ETCD; omitting `te=` skips FK check
4. **Sequence enforcement:** calling `add_elements()` before `fetch_structure()` raises `ValueError` with descriptive message
5. **fetch_structure (mocked API):** returns correct schema, writes YAML to disk, sets `_domain_meta`
6. **fetch_structure (cache-first):** pre-existing YAML file → no API call made
7. **Schema reconciliation:** fetched IG with extra required variable → `UserWarning`; type mismatch → warning; codelist drift → warning
8. **Protocol-reference pipelines (TE, TA, TV, TS, TI):** each produces DataFrame with correct columns in IG ordinal order
9. **Subject-level pipelines (SV, SE):** `visit_map()` correctly maps actual to planned visits within tolerance; `element_boundaries()` derives correct start/end dates; `epoch_assign()` assigns correct EPOCH; `study_day()` produces correct CDISC day values (no day 0)
10. **Regression:** `uv run pytest tests/unit/test_sdtm_namespace.py` — existing tests pass
11. **Same `fetch_structure()` works for all 7 TDD domains**
12. **Documentation:** `docs/concepts/tdd.md` and `docs/api/tdd.md` render correctly via `uv run --extra docs mkdocs serve`

---

## Decisions

1. **Full TDD scope: 7 domains** — TE, TA, TV, TS, TI (protocol-reference) + SV, SE (subject-level)
2. **11 TDD verbs total:** 2 shared + 5 protocol-reference + 4 subject-level
3. **12 Pydantic models:** 7 row models + 5 collection models
4. **Sequence enforcement: YES** — ~15 lines, prevents calling verbs on uninitialized state
5. **Model mutation: NO** — static models + reconciliation warnings (preserves IDE autocompletion)
6. **Rich typing: ALL variables** — every field uses richest possible type
7. **Cross-domain FK: opt-in** via upstream injection (`te=` parameter)
8. **Collection models: mandatory** — no bare lists accepted by `add_*()` verbs
9. **Subject-level verbs freely mix** with existing SDTM verbs
10. **TDD documentation is a first-class deliverable** — concepts + API reference pages

---

## Bonus: Mermaid → TA/TE Helper Function

**Standalone utility** in `src/fleet/sdtm/tdd.py` (~110 lines, no external dependencies):

`parse_trial_design(mermaid_text: str) → tuple[TrialElements, TrialArms]`

Parses a minimal Mermaid flowchart into TE and TA collections. Uses 4 regexes to extract:

- Subgraphs → Epochs
- Nodes with labels/durations → `TrialElement` rows
- Labeled edges → Arm assignments (edge label = ARMCD)
- BFS path traversal per arm → TAETORD ordering

Handles: branching (arm splits), convergence (shared elements), sequential paths, duration in node labels (`<br/>P14D`).
Does NOT handle: crossover designs, adaptive arms, TESTRL/TEENRL rule expressions.
No new dependencies required. Output plugs directly into `add_elements()` and `add_arms()`.
