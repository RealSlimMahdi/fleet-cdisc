#!/usr/bin/env python3
"""
Generate llms.txt from static Python strings + live example files.

Usage
-----
# Regenerate llms.txt (written to repo root by default):
    uv run python scripts/build_llms.py

# Write to a custom path:
    uv run python scripts/build_llms.py --output path/to/llms.txt

# CI stale-check (exits 1 if llms.txt is out of date):
    uv run python scripts/build_llms.py --check

Editing guide
-------------
* Verb signatures + one-line summaries → **auto-generated** from the live
  Python classes via :mod:`inspect`.  Just edit the verb's docstring or
  signature in ``src/fleet/...`` and re-run this script — ``llms.txt``
  will pick the change up automatically.  The curated lists in the
  ``_*_verbs_section()`` functions act as the *editorial filter*: they
  decide which verbs are worth advertising to AI agents.
* Static section content  → edit the string-returning functions below.
* Example code            → edit examples/cdiscpilot01_inline.py or
                            examples/cdiscpilot01_spec_driven.py.
* Section order           → edit build().
* README namespace catalog→ auto-synced between
                            ``<!-- AUTO:NAMESPACES:BEGIN -->`` and
                            ``<!-- AUTO:NAMESPACES:END -->`` in README.md.
                            Edit the ``_README_*_VERBS`` lists below to
                            change what verbs appear; counts and the
                            "(N verbs: …)" labels are derived from list
                            length.
* Never edit llms.txt or the README namespace block by hand — both are
  overwritten on every run.
"""

from __future__ import annotations

import argparse
import inspect
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _example(filename: str) -> str:
    """Read examples/<filename> and wrap it in a fenced python code block."""
    path = REPO_ROOT / "examples" / filename
    source = path.read_text(encoding="utf-8")
    return f"```python\n{source}\n```"


def _verb_signature(cls: type, verb: str) -> str:
    """Return ``verb(arg1, arg2, ...)`` rendered from the live signature.

    The leading ``self`` parameter is stripped.  Default values are kept
    in the standard ``inspect`` form so that the output mirrors what an
    IDE would show.
    """
    import re

    method = getattr(cls, verb)
    sig = inspect.signature(method)
    params = [p for name, p in sig.parameters.items() if name != "self"]
    new_sig = sig.replace(parameters=params)
    rendered = f"{verb}{new_sig}"
    # ``from __future__ import annotations`` makes annotations strings, so
    # ``inspect`` renders them with surrounding quotes (e.g. ``: 'str'``).
    # Strip those quotes only after ``:`` and ``->`` so that string
    # defaults like ``mode='date'`` are left intact.
    rendered = re.sub(r"(:\s*)'([^']+)'", r"\1\2", rendered)
    rendered = re.sub(r"(->\s*)'([^']+)'", r"\1\2", rendered)
    return rendered


def _verb_summary(cls: type, verb: str) -> str:
    """Return the first non-empty line of *verb*'s docstring on *cls*."""
    method = getattr(cls, verb)
    doc = inspect.getdoc(method) or ""
    for line in doc.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


def _render_verb_bullets(cls: type, verbs: list[str]) -> str:
    """Render a markdown bullet list of ``- ``verb(sig)`` — summary``.

    Signatures and summaries are pulled live from the class via
    :mod:`inspect`, so editing a verb's docstring or signature in the
    source automatically refreshes ``llms.txt`` on the next build.
    """
    lines: list[str] = []
    for verb in verbs:
        sig = _verb_signature(cls, verb)
        summary = _verb_summary(cls, verb)
        if summary:
            lines.append(f"- `{sig}` — {summary}")
        else:
            lines.append(f"- `{sig}`")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _header_section() -> str:
    return """\
# Fleet

> CDISC SDTM/ADaM derivation toolkit for Polars DataFrames.

Fleet adds chainable verb pipelines directly onto every Polars DataFrame so you can build \
standards-compliant CDISC datasets with minimal boilerplate. Importing the package registers \
`.sdtm` and `.adam` namespaces automatically.\
"""


def _rules_section() -> str:
    return """\
## Rules for AI Agents

1. **Fleet-first verb priority** — Always reach for a named Fleet verb (`duration`, \
`baseline`, `chg`, `treatment_emergent`, …) before falling back to a raw \
`derivation(expression=...)` call. Named verbs encode CDISC semantics, enforce correct \
argument names, and appear in Define-XML traceability. Use `derivation` only as a last \
resort for logic not yet covered by a typed verb.

2. **Polars-only** — Fleet pipelines are built on Polars. Never introduce Pandas, NumPy \
array operations, or any other DataFrame library. All expressions must be `pl.Expr` objects \
or expression strings that Fleet will evaluate with `eval()`.

3. **Lazy-first execution** — Most verbs accumulate expressions into a single Polars pass; a \
few window/cross-domain verbs (`baseline`, `study_day` with a pinned join, `date` with time, \
`first_date`/`last_date`) checkpoint internally but **do not break the chain**. Write \
`flag → baseline → chg` as one pipeline — no intermediate `.to_frame()` is needed (that old \
advice was wrong). Only call `.to_frame()` when you need a plain `pl.DataFrame` for non-Fleet \
code. Do not inspect column values mid-chain; use `.inspect()` for a debug checkpoint.

4. **Google-style docstrings** — All public verbs use Google-style docstrings with `Args:`, \
`Returns:`, and `Examples:` sections. Every example must be a complete pipeline snippet \
ending with `.to_frame()`. Never use NumPy/Sphinx `Parameters ----------` style or bare \
`Example::` headers.

5. **Prefer `pl.from_repr()` for small reproducible snippets** — When generating small \
inline DataFrames for tests, examples, or user-facing code snippets, prefer `pl.from_repr()` \
with a Unicode box-drawing table over `pl.DataFrame({...})`. This makes column names, types, \
and data immediately visible without execution. Use `pl.DataFrame()` (empty) only for TDD \
scaffolding and `pl.DataFrame(variable)` when data is built programmatically.\
"""


def _install_section() -> str:
    return """\
## Install

```
uv add fleet-cdisc
```\
"""


def _quickstart_section() -> str:
    return """\
## Quickstart

```python
import fleet
import polars as pl
from codelists import SEX  # generated by: uv run fleet init-ct --domains DM

# fleet.frame() is a zero-cost cast so .sdtm/.adam/.tlg type-check (returns its input).
raw_df = fleet.frame(pl.read_csv("dm_raw.csv"))

dm = (
    raw_df.sdtm
    .assign("DOMAIN",  value="DM")
    .assign("STUDYID", value="MYSTUDY01")
    .assign("USUBJID", source="patient_id")
    .assign("SEX", source="sex_raw", ct=SEX)
    .to_frame()
)
```

`assign` is the one canonical assignment verb (`source=` copies, `value=` hardcodes, \
`ct=`/`ct_map=` add CT); `case_when` is the one conditional; `merge` is the one join. \
The pre-alpha spellings (`assign_no_ct`, `hardcode_no_ct`, `if_then_else`, `lookup`, …) were \
removed outright — run `fleet migrate <files...> --write` to rewrite old scripts.\
"""


def _data_construction_section() -> str:
    return """\
## Data Sample Construction

When creating inline sample DataFrames for tests, examples, or reproducible snippets, \
prefer `pl.from_repr()` over `pl.DataFrame({...})`. Column names, types, and data are \
immediately visible without execution.

### Pattern

```python
import polars as pl

raw_dm = pl.from_repr(\"\"\"\\
┌────────────┬─────┬─────┐
│ subject_id ┆ sex ┆ age │
│ ---        ┆ --- ┆ --- │
│ str        ┆ str ┆ i64 │
╞════════════╪═════╪═════╡
│ S001       ┆ M   ┆ 35  │
│ S002       ┆ F   ┆ 42  │
└────────────┴─────┴─────┘
\"\"\")
```

### Generating the repr string

Fleet ships a `to_repr()` helper that renders any DataFrame with full-width, \
no-truncation settings so the output is directly pasteable:

```python
from fleet import to_repr
import polars as pl

# From any existing DataFrame (CSV load, query result, dict, etc.)
df = pl.DataFrame({"USUBJID": ["S001", "S002"], "AGE": [35, 42]})

# Print the from_repr-ready string
print(to_repr(df))
# ┌─────────┬─────┐
# │ USUBJID ┆ AGE │
# │ ---     ┆ --- │
# │ str     ┆ i64 │
# ╞═════════╪═════╡
# │ S001    ┆ 35  │
# │ S002    ┆ 42  │
# └─────────┴─────┘

# Paste that output into your test/example:
df = pl.from_repr(\"\"\"\\
┌─────────┬─────┐
│ USUBJID ┆ AGE │
│ ---     ┆ --- │
│ str     ┆ i64 │
╞═════════╪═════╡
│ S001    ┆ 35  │
│ S002    ┆ 42  │
└─────────┴─────┘
\"\"\")
```

### When `pl.DataFrame()` is still acceptable

- Empty DataFrames for TDD scaffolding: `pl.DataFrame().sdtm`
- Programmatic data built with loops or random generators (e.g. benchmark scripts)
- API type annotations referencing `pl.DataFrame` as a return/parameter type\
"""


def _golden_master_section() -> str:
    inline = _example("cdiscpilot01_inline.py")
    spec = _example("cdiscpilot01_spec_driven.py")
    tdd = _example("tdd_example.py")
    return f"""\
## Golden Master Examples

These are the canonical end-to-end reference pipelines. Prefer these patterns when generating \
Fleet code — they demonstrate correct chaining, namespace switching, and materialisation points.

### Inline pipeline

{inline}

### Spec-driven pipeline

{spec}

### Trial Design Domains pipeline

{tdd}\
"""


def _namespaces_section() -> str:
    return """\
## Namespaces

Registered on every `pl.DataFrame` **and** `pl.LazyFrame` (so `pl.scan_parquet(...).sdtm` \
stays lazy). Call `.verbs()` on any namespace for the always-current list.

- `df.sdtm` — SDTM derivation verbs (domain mapping, CT via `assign(ct=)`, date normalisation, study day, TDD)
- `df.adam` — ADaM BDS verbs (date/datetime parsing, elapsed time, baseline, change, flags, BSA, MAP, QTc, LOCF, \
summary records, derived parameters, toxicity grading)
- `df.adam.adsl` — patient-level verbs (treatment dates, duration, population flags, AE \
counts, age conversion, periods)
- `df.adam.occds` — occurrence verbs (treatment-emergent flag, worst severity, onset/recovery \
dates, sequence number)

### Trial Design Domain extensions (via `df.sdtm`)

- Protocol-reference verbs: `fetch_structure`, `study_header`, `add_elements`, `add_arms`, \
`add_visits`, `add_parameters`, `add_criteria`
- Subject-level verbs: `visit_map`, `element_boundaries`, `epoch_assign`
- Pydantic models: `TrialElement`, `TrialArm`, `TrialVisit`, `TrialParameter`, `TrialCriterion`
- Collection models: `TrialElements`, `TrialArms`, `TrialVisits`, `TrialParameters`, `TrialCriteria`
- Enum: `Epoch` (NCI C99079 — 14 standard trial epoch values)
- Utility: `parse_trial_design(mermaid_text)` — parse Mermaid flowcharts into TE + TA collections

### Therapeutic-area extensions (via `df.adam.<ta>`)

- `df.adam.onco` — Oncology: AVAL response, BOR, filter_pd
- `df.adam.ophtha` — Ophthalmology: ETDRS/LogMAR, study eye derivation
- `df.adam.peds` — Pediatrics: age derivations, prematurity flag
- `df.adam.vaccine` — Vaccine: fever flag, seroconversion, ADIS AVAL
- `df.adam.metabolic` — Metabolic: waist-to-hip ratio, body fat %
- `df.adam.neuro` — Neuroscience: Centiloid, MMSE, CDR-SoB
- `df.adam.tte` — Time-to-event (ADTTE): EventSource/CensorSource objects, param, AVAL/AVALU, KM inputs\
"""


def _sdtm_verbs_section() -> str:
    from fleet.sdtm import SDTMNamespace

    verbs = [
        "assign",
        "case_when",
        "date",
        "duration",
        "derivation",
        "condition_add",
        "ae_aerel",
        "merge",
        "keep",
        "nodup",
        "group_by",
        "notsubmitted",
        "multiple_responses",
        "flag",
        "to_frame",
    ]
    bullets = _render_verb_bullets(SDTMNamespace, verbs)
    return (
        "## SDTM verbs\n\n"
        "`assign` is the one assignment verb (the pre-alpha "
        "`assign_no_ct`/`assign_ct`/`hardcode_no_ct`/`hardcode_ct`/`dataset_level` "
        "spellings were removed); `case_when` replaces `if_then_else`.\n\n" + bullets
    )


def _tdd_verbs_section() -> str:
    from fleet.sdtm import SDTMNamespace

    protocol_verbs = [
        "fetch_structure",
        "study_header",
        "add_elements",
        "add_arms",
        "add_visits",
        "add_parameters",
        "add_criteria",
    ]
    subject_verbs = [
        "visit_map",
        "element_boundaries",
        "epoch_assign",
    ]
    protocol_bullets = _render_verb_bullets(SDTMNamespace, protocol_verbs)
    subject_bullets = _render_verb_bullets(SDTMNamespace, subject_verbs)

    return f"""\
## Trial Design Domain (TDD) verbs

Fleet supports all 7 CDISC Trial Design Model domains through `df.sdtm`. Protocol-reference \
domains (TE, TA, TV, TS, TI) follow a fixed sequence: `fetch_structure() → study_header() → \
add_*() → to_frame()`. Subject-level domains (SV, SE) mix freely with standard SDTM verbs.

### Protocol-reference verbs

{protocol_bullets}

### Subject-level verbs

{subject_bullets}

### Pydantic models

Row models: `TrialElement`, `TrialArm`, `TrialVisit`, `TrialParameter`, `TrialCriterion`. \
Collection models: `TrialElements`, `TrialArms`, `TrialVisits`, `TrialParameters`, \
`TrialCriteria`. Collections enforce integrity at construction time (unique keys, ordering, \
FK references) and provide `to_polars()` for DataFrame conversion.

### Epoch enum

`Epoch` (NCI C99079) provides all 14 CDISC-standard trial epoch values: SCREENING, BASELINE, \
RUN-IN, WASHOUT, TREATMENT, BLINDED TREATMENT, OPEN LABEL TREATMENT, CONTINUATION TREATMENT, \
INDUCTION TREATMENT, FOLLOW-UP, LONG-TERM FOLLOW-UP, OBSERVATION, PRE-SCREENING.

### Mermaid parser

`parse_trial_design(mermaid_text) → (TrialElements, TrialArms)` — extract TE and TA \
collections from a Mermaid flowchart. Subgraphs → epochs, nodes → elements, labelled edges \
→ arm assignments.\
"""


def _shared_adam_verbs_section() -> str:
    from fleet.adam._mixins import SharedADaMVerbsMixin

    verbs = [
        "source",
        "assign",
        "case_when",
        "derivation",
        "recode",
        "merge",
        "keep",
        "whereclauses",
        "merge_adsl",
        "date",
        "duration",
        "flag",
        "pick",
    ]
    bullets = _render_verb_bullets(SharedADaMVerbsMixin, verbs)
    return (
        "## Shared ADaM verbs (available on all sub-namespaces)\n\n"
        "These verbs are defined once in `SharedADaMVerbsMixin` "
        "(`src/fleet/adam/_mixins.py`) and inherited by every ADaM "
        "sub-namespace: `adsl`, `occds`, `onco`, `ophtha`, `peds`, "
        "`vaccine`, `metabolic`, `neuro`, `pk`. Call them directly "
        "on any sub-namespace without switching back to the base "
        "`adam` namespace. (`assign` replaced the removed `assigned`/`rename`; "
        "`case_when` replaced `condderivation`; `merge` replaced `lookup`.)\n\n" + bullets
    )


def _adam_verbs_section() -> str:
    from fleet.adam import AdamNamespace

    verbs = [
        "flag",
        "baseline",
        "chg",
        "pchg",
        "bmi",
        "bsa",
        "map",
        "qtc",
        "nrind",
        "on_treatment",
        "shift",
        "derive_summary_records",
        "derive_locf_records",
        "derive_param",
        "atoxgr",
        "transform",
        "from_spec",
    ]
    bullets = _render_verb_bullets(AdamNamespace, verbs)
    return (
        "## ADaM verbs\n\n"
        "Available on `df.adam` (BDS base namespace). Shared verbs "
        "(source, assign, case_when, derivation, recode, merge, keep, "
        "whereclauses, merge_adsl, date, duration, flag) "
        "are also available here via the shared mixin.\n\n" + bullets
    )


def _adsl_verbs_section() -> str:
    from fleet.adam.adsl_namespace import ADSLNamespace

    verbs = [
        "first_date",
        "last_date",
        "duration",
        "count_events",
        "age_years",
        "derive_period",
    ]
    bullets = _render_verb_bullets(ADSLNamespace, verbs)
    return f"## ADSL verbs\n\n{bullets}"


def _occds_verbs_section() -> str:
    from fleet.adam.occds_namespace import OCCDSNamespace

    verbs = [
        "treatment_emergent",
        "onset_recovery",
        "seq",
    ]
    bullets = _render_verb_bullets(OCCDSNamespace, verbs)
    return (
        "## OCCDS verbs\n\n"
        "Available on `df.adam.occds` (and `df.adam.pk` for sequence). "
        "Shared verbs (source, assign, case_when, derivation, recode, "
        "merge, whereclauses, merge_adsl) are also available "
        "here via the shared mixin.\n\n" + bullets
    )


def _verb_mapping_section() -> str:
    return """\
## Operation → Fleet Verb Mapping

| CDISC Operation | Fleet Verb | Namespace | Notes |
| --- | --- | --- | --- |
| Copy column | `assign` (source=) | `sdtm` / `adam` | Direct 1:1 copy/rename, no CT |
| Copy column | `source` | `adam` / all sub-ns | Variadic pass-through column(s) |
| Constant value | `assign` (value=) | `sdtm` / `adam` | Same literal for every row |
| CT recode | `assign` (ct=, ct_map=) | `sdtm` / `adam` | Validate / decode via codelist |
| CT recode | `recode` | `adam` / all sub-ns | Map raw→decoded values |
| Multi-branch conditional | `case_when` | `sdtm` / `adam` | Ordered `when=[{condition, value}]`, `else_=` |
| Join reference dataset | `merge` | `sdtm` / `adam` | `on=`, `keep=`, `where=` |
| Arbitrary expression | `derivation` | `sdtm` / `adam` | Polymorphic: `str`, `pl.Expr`, lambda `() -> pl.Expr`, or `@derivation` object |
| ISO 8601 parse (SDTM) | `date` | `sdtm` | Normalises to `YYYY-MM-DD` or `YYYY-MM-DDTHH:MM:SS`; preserves partial dates |
| Date imputation (ADaM) | `date` | `adam` / all sub-ns | Imputes partial --DTC → `pl.Date` or `pl.Datetime` with optional DTF/TMF flags |
| Study day (ADY) | `duration` | `adam` / `sdtm` | CDISC study-day: +1 if ≥ 0, no day 0 |
| Elapsed time | `duration` | `adam` / all sub-ns | Supports days, hours, minutes, seconds, weeks, months, years |
| Baseline flag (ABLFL) | `flag` | `adam` | Per-group boolean flag |
| Baseline value (BASE) | `baseline` | `adam` | Carries AVAL at baseline row |
| Change from baseline (CHG) | `chg` | `adam` | `CHG = AVAL − BASE` |
| % change from baseline | `pchg` | `adam` | `PCHG = (AVAL − BASE) / BASE × 100` |
| BMI | `bmi` | `adam` | `weight / (height/100)²` |
| BSA | `bsa` | `adam` | 4 methods: Mosteller, DuBois, Haycock, Gehan |
| Mean arterial pressure (MAP) | `map` | `adam` | `(SBP + 2×DBP) / 3` |
| Corrected QT (QTc) | `qtc` | `adam` | Fridericia or Bazett method |
| Normal range indicator | `nrind` | `adam` | Returns `LOW / NORMAL / HIGH` |
| On-treatment flag | `on_treatment` | `adam` | `TRTSDT ≤ ADT ≤ TRTEDT` |
| Categorical shift | `shift` | `adam` | `"BASELINE / POST-BASELINE"` string |
| LOCF imputation records | `derive_locf_records` | `adam` | Forward-fill within patient groups |
| Summary records | `derive_summary_records` | `adam` | Aggregate and append summary rows |
| Derived parameter rows | `derive_param` | `adam` | New parameter rows from existing ones |
| Join reference dataset | `merge` | `adam` / `sdtm` | Left-join another DataFrame into lazy plan |
| Merge ADSL columns | `merge_adsl` | `adam` / all sub-ns | Join ADSL onto current dataset |
| Filter rows | `whereclauses` | `adam` / all sub-ns | Filter by expression (materialises first) |
| Treatment dates (ADSL) | `first_date` / `last_date` | `adam.adsl` | Earliest/latest event date per subject |
| Treatment duration (TRTDURD) | `duration` | `adam` / all sub-ns | Elapsed time between two date/datetime columns |
| Population flag (SAFFL, etc.) | `flag` | `adam` / all sub-ns | `"Y"` / null based on row condition |
| Event count (NUMAE, NUMSAE) | `count_events` | `adam.adsl` | Integer event count per subject |
| Age conversion | `age_years` | `adam.adsl` | Unit-aware: YEARS, MONTHS, WEEKS, DAYS |
| Period variables | `derive_period` | `adam.adsl` | APxxSDT, APxxEDT, TRTxxP |
| Sequence number (ASEQ) | `seq` | `adam.occds` / `adam.pk` | Sequential 1-based record number per group |
| Worst severity | `flag` | `adam` / all sub-ns | Use `criteria="max"` with numeric rank column |
| Treatment-emergent flag | `treatment_emergent` | `adam.occds` | TRTEMFL using TRTSDT/TRTEDT window |
| Onset/recovery dates | `onset_recovery` | `adam.occds` | Onset and recovery date derivation |
| Run spec derivations | `from_spec` | `adam` | Execute all derivations defined in define.yaml |\
"""


def _define_yaml_section() -> str:
    return """\
## define.yaml

A single YAML file is the source of truth for a study: it declares output variables, \
derivation algorithms, codelists, and structural metadata. The same file drives Define-XML 2.1 \
generation, pipeline execution, and post-dataset checks.

### Derivation algorithms

Every spec-executable algorithm is declared once in the central registry \
(`fleet.core.spec_registry`), which drives the `from_spec` executor, the strict \
discriminated-union validation models, and the JSON schema. Spec algorithm ids are \
stable YAML vocabulary and resolve to canonical verbs (e.g. `assign_no_ct` → `assign`, \
`count` → `count_events`).

- `assigned` → `.assign(target, value=...)`
- `source` → `.assign(target, source=...)`
- `assign_ct` → `.assign(target, source=..., ct=..., ct_map=...)`
- `derivation` → `.derivation(target, expression=...)`
- `callable` → `.derivation(drv_obj)` (dispatches `@derivation`-decorated function by name or dotted path)
- `first_date` / `last_date` → `.first_date(target, from_dataset=..., date_col=..., where=...)`
- `count_events` → `.count_events(target, from_dataset=..., where=...)`
- `duration` → `.duration(target, start=..., end=...)`
- `flag` → `.flag(target, criteria=...)`

Full machine-readable list: `spec_registry.algorithm_names("adam"|"sdtm")`; the \
inline-only allowlist is `spec_registry.SPEC_UNSUPPORTED`. `from_spec(strict=True, \
overwrite=False)` raises a `SpecError` (naming file → dataset → variable) on unknown \
algorithms, typo'd fields, or column overwrites; `to_spec_yaml()` does the reverse — \
emits a define.yaml from a prototyped inline pipeline.

### Spec-driven pipeline

```python
import polars as pl
import fleet

dm = fleet.frame(pl.read_parquet("outputs/sdtm/dm.parquet"))
ex = pl.read_parquet("outputs/sdtm/ex.parquet")
adsl = (
    dm.adam
    .pin("EX", ex)
    .from_spec("examples/cdiscpilot01/adam/define.yaml", dataset="ADSL")
    .to_frame()
)
```

### Define-XML generation

```python
from pathlib import Path

from fleet import DefineXMLGenerator

gen = DefineXMLGenerator(Path("examples/cdiscpilot01/adam/define.yaml"))
gen.generate(Path("outputs/cdiscpilot01/define_adam.xml"))
```

New spec keys: `fleet_spec_version: 1` (dialect pin), `derivations_module:` \
(auto-import for `callable:`), `output_format:` (parquet/json/xpt), `value_level:` \
(value-level metadata), and `ct: {validate: true, file: ...}` (opt into CT validation).\
"""


def _ct_section() -> str:
    return """\
## Controlled Terminology

### CLI bootstrap (recommended)

Fleet provides a CLI for bootstrapping typed CT constants from the CDISC Library API. \
Set `CDISC_API_KEY` in a `.env` file at the project root.

```bash
# Bootstrap codelists.py from the SDTM IG for your study's domains
uv run fleet init-ct --domains DM,AE,VS,EX --output codelists.py

# Add more domains incrementally (preserves existing codelists)
uv run fleet add-ct --domains LB,CM --output codelists.py

# Pin to a specific IG version and CT package
uv run fleet init-ct --domains DM,AE --ig 3-4 --package sdtmct-2025-09-26 --output codelists.py

# Generate Define-XML from a define.yaml specification
uv run fleet define-xml --spec specs/study/sdtm/define.yaml --output outputs/define_sdtm.xml
```

The source of truth for which codelists to generate is the **CDISC Library SDTM IG** — not the \
user-authored `define.yaml`. The CLI queries the IG model to find every codelist referenced \
by variables in the requested domains.

Generated `codelists.py` provides classes with `_concept_id`, term attributes, human-readable \
aliases (e.g. `SEX = C66731`), and `__all__` for clean imports.

### Using generated codelists in pipelines

```python
from codelists import SEX, RACE

dm = (
    raw_df.sdtm
    .assign("SEX", source="sex", ct=SEX)
    .assign("RACE", source="race", ct=RACE)
    .to_frame()
)
```

`assign(ct=...)` accepts either a generated codelist class (e.g. `SEX`) or a raw NCI concept ID \
string (e.g. `"C66731"`). Prefer the class form for IDE auto-completion and readability. \
When raw data already matches the standard, `ct_map` can be omitted (values are validated and \
passed through).

### Programmatic API

```python
from fleet.ct.api import CDISCClient
from fleet.ct.generator import CodelistGenerator

with CDISCClient() as client:
    gen = CodelistGenerator.from_sdtm_ig(
        client,
        domains=["DM", "AE", "VS", "EX"],
    )
    gen.write("codelists.py")
```

### Runtime validation

```python
from fleet import CTValidator

ct = CTValidator.get_instance()
ct.load_ct_file("specs/ct/sdtm_ct.yaml")
ok, msg = ct.validate_value("C66731", "M")
```\
"""


def _docs_section() -> str:
    return """\
## Documentation

Full docs: https://realslimmahdi.github.io/fleet-cdisc/

- Getting started: https://realslimmahdi.github.io/fleet-cdisc/getting-started/installation/
- define.yaml guide: https://realslimmahdi.github.io/fleet-cdisc/concepts/define-yaml/
- Trial Design Domains: https://realslimmahdi.github.io/fleet-cdisc/concepts/tdd/
- API reference: https://realslimmahdi.github.io/fleet-cdisc/api/
- ADSL example notebook: https://realslimmahdi.github.io/fleet-cdisc/examples/adsl_pipeline/\
"""


def _rules_caching_section() -> str:
    return """\
## CDISC Conformance Rules Caching

### CLI

```bash
# Cache all CDISC conformance rules for the IG versions in your define.yaml files
uv run fleet init rules

# SDTM rules only
uv run fleet init rules --sdtm-only

# Overwrite existing cached rules
uv run fleet init rules --force
```

`fleet init rules` reads the IG version from each `define.yaml` (`study.standard_version`), \
fetches all conformance rules from the CDISC Library API, groups them by domain, and writes \
one YAML file per domain into `metadata/sdtm/rules/` and `metadata/adam/rules/`.

Each YAML file contains the rule ID, description, check logic, scope, severity, and \
references — providing a human-readable, version-controlled audit trail of the exact rules \
applied to the study.

For sponsor-specific checks not covered by CDISC CORE, see the **Custom Validation Rules** \
section below (`fleet add-rule`, `fleet check-rule`)."""


def _custom_rules_section() -> str:
    return """## Custom Validation Rules

Sponsors can author rules in the same YAML schema as CDISC CORE and run them alongside official rules via the `-lr` flag in the CDISC Rules Engine.

### CLI

```bash
# Scaffold a schema-valid rule YAML (fills in all required fields automatically)
uv run fleet add-rule --domain AE --description "AESEV must be populated when AESER = Y"

# Custom company prefix (default: FLEET)
uv run fleet add-rule --domain AE --prefix ROCHE --description "Severity required for serious AEs"

# Explicit rule ID override (skips auto-increment)
uv run fleet add-rule --domain AE --id ROCHE-AE-042 --description "Custom check"

# Write to a specific directory (overrides study_config.yaml)
uv run fleet add-rule --domain VS --description "VSORRES range check" --output ./my_rules/

# Validate a rule YAML (YAML syntax + structure + JSON Schema)
uv run fleet check-rule my_rules/FLEET-AE-001.yaml
```

`fleet add-rule` auto-increments the sequence number by scanning existing rules in the target directory, checks uniqueness of `Core.Id` across all files in that directory, and writes a fully schema-valid skeleton with a TODO `Check:` block the programmer fills in.

`fleet check-rule` performs three levels of validation:
1. YAML syntax — reports line and column on parse errors
2. Structure — checks for required top-level keys, Core.Id, combinators, non-empty scope
3. JSON Schema — full validation against the vendored CDISC rule schema

### study_config.yaml

Set a team-wide default rules directory:

```yaml
validation:
  custom_rules: metadata/custom_rules  # all .yaml files here are loaded via -lr
```

`fleet init cfg` creates this directory and sets the config field automatically.

### Python API

```python
# Per-call override: pass a directory path to .validate()
ae = (
    raw_df.sdtm
    .assign("DOMAIN", value="AE")
    .validate("AE", custom_rules="metadata/custom_rules")
    .to_frame()
)

# Via ValidationService
from fleet.validation.service import ValidationService
svc = ValidationService()
result = svc.validate_sdtm(ae, domain="AE", custom_rules="metadata/custom_rules")
result.print_report()
```

Resolution order: explicit `custom_rules=` param > `study_config.yaml` default > None.

### Rule ID convention

Use a company prefix to avoid clashing with official `CORE-XXXXXX` identifiers:
`<COMPANY>-<DOMAIN>-<NNN>` e.g. `ROCHE-AE-001`, `FLEET-DM-003`

### Reference

CDISC Rules Engine rule types and operators:
https://github.com/cdisc-org/cdisc-rules-engine/wiki/Rule-Types"""


# ---------------------------------------------------------------------------
# README namespace block (auto-synced between sentinel comments)
# ---------------------------------------------------------------------------

README_PATH = REPO_ROOT / "README.md"
README_BEGIN = "<!-- AUTO:NAMESPACES:BEGIN -->"
README_END = "<!-- AUTO:NAMESPACES:END -->"

# Curated verb lists per README namespace block. Edit these to control what
# the README advertises; counts and the "(N verbs: …)" summary line are
# derived automatically.
_SHARED_ADAM_VERBS = [
    "source",
    "assign",
    "case_when",
    "derivation",
    "recode",
    "merge",
    "keep",
    "whereclauses",
    "merge_adsl",
    "date",
    "duration",
    "flag",
    "pick",
    "pin",
    "repin",
    "join_adsl",
    "study_day",
    "nodup",
    "fk_policy",
    "pins",
]

_README_SDTM_VERBS = [
    "assign",
    "case_when",
    "date",
    "duration",
    "condition_add",
    "ae_aerel",
    "merge",
    "keep",
    "nodup",
    "group_by",
    "notsubmitted",
    "multiple_responses",
    "nsv",
    "export_supp",
    "flag",
    "pin",
    "repin",
    "study_day",
    "baseline_flag",
    "fk_policy",
    "pins",
]

_README_ADAM_SPECIFIC = [
    "baseline",
    "chg",
    "pchg",
    "bmi",
    "nrind",
    "on_treatment",
    "shift",
    "bsa",
    "map",
    "qtc",
    "derive_summary_records",
    "derive_locf_records",
    "derive_param",
    "atoxgr",
    "combine_grades",
    "transform",
]

_README_ADSL_SPECIFIC = [
    "first_date",
    "last_date",
    "count_events",
    "age_years",
    "age_from_dates",
    "derive_period",
]

_README_OCCDS_SPECIFIC = ["treatment_emergent", "onset_recovery"]
_README_OCCDS_MULTI = ["seq"]

_README_ONCO_SPECIFIC = [
    "aval_resp",
    "tumor_response_flag",
    "best_overall_response",
    "confirmed_response_flag",
    "filter_pd",
]

_README_OPHTHA_SPECIFIC = [
    "etdrs_to_logmar",
    "logmar_to_etdrs",
    "study_eye",
    "affected_eye",
    "bcva_criterion",
]

_README_PEDS_SPECIFIC = [
    "age_days",
    "age_months",
    "age_years",
    "corrected_age",
    "prematurity_flag",
    "bmi_category",
]

_README_VACCINE_SPECIFIC = [
    "fever_flag",
    "seroconversion_flag",
    "seroresponse_flag",
    "aval_adis",
    "event_flag",
]

_README_METABOLIC_SPECIFIC = [
    "waist_hip_ratio",
    "waist_height_ratio",
    "body_fat_pct",
    "visceral_fat_flag",
]

_README_NEURO_SPECIFIC = [
    "centiloid",
    "mmse_category",
    "cdrsob_total",
    "moca_category",
    "panss_total",
]

_README_PK_SPECIFIC = [
    "blq_flag",
    "blq_impute",
    "nominal_time",
    "predose_flag",
    "dose_normalized",
    "evid",
    "mrrlt",
    "blqfn",
    "log_conc",
    "mdv",
    "amt",
    "cmt",
    "avalcat",
    "anl_flag",
]
_README_PK_MULTI = ["seq"]

_README_TTE_SPECIFIC = [
    "param",
    "aval",
    "km_data",
]


def _render_namespace_details(
    *,
    namespace: str,
    title: str,
    specific: list[str],
    with_shared: bool,
    multi_row: list[str] | None = None,
) -> str:
    """Render one ``<details>`` block for the README namespace catalog.

    Counts in the summary line and the body breakdown are computed from
    the verb lists, so adding/removing a curated verb updates both
    automatically.
    """
    n_specific = len(specific)
    n_multi = len(multi_row) if multi_row else 0
    n_shared = len(_SHARED_ADAM_VERBS) if with_shared else 0
    total = n_specific + n_shared + n_multi

    if with_shared or n_multi:
        breakdown_parts = [f"{n_specific} specific"]
        if n_shared:
            breakdown_parts.append(f"{n_shared} shared")
        if n_multi:
            breakdown_parts.append(f"{n_multi} multi-row")
        count_label = f"{total} verbs: " + " + ".join(breakdown_parts)
    else:
        count_label = f"{total} verbs"

    summary = f"<summary><b><code>{namespace}</code></b> — {title} ({count_label})</summary>"

    def _join(verbs: list[str]) -> str:
        return " · ".join(f"`{v}`" for v in verbs)

    if with_shared or n_multi:
        body_parts = [f"**Specific:** {_join(specific)}"]
        if multi_row:
            body_parts.append(f"**Multi-row:** {_join(multi_row)}")
        if with_shared:
            body_parts.append(f"**Shared:** {_join(_SHARED_ADAM_VERBS)}")
        body = "\n\n".join(body_parts)
    else:
        body = _join(specific)

    return f"<details>\n{summary}\n\n{body}\n\n</details>"


def _readme_namespaces_block() -> str:
    """Build the auto-synced README namespace catalog (between sentinels)."""
    intro = (
        "Importing `fleet` registers chainable namespaces on **every** "
        "Polars DataFrame. All ADaM namespaces also inherit "
        f"**{len(_SHARED_ADAM_VERBS)} shared verbs** from the common mixin: "
        + ", ".join(f"`{v}`" for v in _SHARED_ADAM_VERBS)
        + "."
    )

    blocks: list[str] = [
        _render_namespace_details(
            namespace="df.sdtm",
            title="SDTM domains",
            specific=_README_SDTM_VERBS,
            with_shared=False,
        ),
        _render_namespace_details(
            namespace="df.adam",
            title="ADaM BDS",
            specific=_README_ADAM_SPECIFIC,
            with_shared=True,
        ),
        _render_namespace_details(
            namespace="df.adam.adsl",
            title="ADSL",
            specific=_README_ADSL_SPECIFIC,
            with_shared=True,
        ),
        _render_namespace_details(
            namespace="df.adam.occds",
            title="OCCDS / ADAE, ADCM…",
            specific=_README_OCCDS_SPECIFIC,
            with_shared=True,
            multi_row=_README_OCCDS_MULTI,
        ),
        _render_namespace_details(
            namespace="df.adam.onco",
            title="Oncology",
            specific=_README_ONCO_SPECIFIC,
            with_shared=True,
        ),
        _render_namespace_details(
            namespace="df.adam.ophtha",
            title="Ophthalmology",
            specific=_README_OPHTHA_SPECIFIC,
            with_shared=True,
        ),
        _render_namespace_details(
            namespace="df.adam.peds",
            title="Pediatrics",
            specific=_README_PEDS_SPECIFIC,
            with_shared=True,
        ),
        _render_namespace_details(
            namespace="df.adam.vaccine",
            title="Vaccine",
            specific=_README_VACCINE_SPECIFIC,
            with_shared=True,
        ),
        _render_namespace_details(
            namespace="df.adam.metabolic",
            title="Metabolic",
            specific=_README_METABOLIC_SPECIFIC,
            with_shared=True,
        ),
        _render_namespace_details(
            namespace="df.adam.neuro",
            title="Neuroscience",
            specific=_README_NEURO_SPECIFIC,
            with_shared=True,
        ),
        _render_namespace_details(
            namespace="df.adam.pk",
            title="Pharmacokinetics",
            specific=_README_PK_SPECIFIC,
            with_shared=True,
            multi_row=_README_PK_MULTI,
        ),
        _render_namespace_details(
            namespace="df.adam.tte",
            title="Time-to-event (ADTTE)",
            specific=_README_TTE_SPECIFIC,
            with_shared=True,
        ),
    ]

    return intro + "\n\n" + "\n\n".join(blocks)


def _render_readme(existing: str) -> str:
    """Return the README text with the namespace block re-synced.

    Looks for ``README_BEGIN`` / ``README_END`` sentinel comments and
    replaces everything between them with the freshly generated
    namespace catalog. Raises ``RuntimeError`` if the sentinels are
    missing or unbalanced.
    """
    begin_idx = existing.find(README_BEGIN)
    end_idx = existing.find(README_END)
    if begin_idx == -1 or end_idx == -1 or end_idx < begin_idx:
        raise RuntimeError(
            f"Sentinels {README_BEGIN!r} / {README_END!r} not found "
            f"(or out of order) in {README_PATH}. Add them around the "
            "namespace block before regenerating."
        )

    head = existing[: begin_idx + len(README_BEGIN)]
    tail = existing[end_idx:]
    block = _readme_namespaces_block()
    return f"{head}\n\n{block}\n\n{tail}"


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build() -> str:
    """Assemble all sections into the final llms.txt content."""
    sections = [
        _header_section(),
        _rules_section(),
        _install_section(),
        _quickstart_section(),
        _data_construction_section(),
        _golden_master_section(),
        _namespaces_section(),
        _sdtm_verbs_section(),
        _tdd_verbs_section(),
        _shared_adam_verbs_section(),
        _adam_verbs_section(),
        _adsl_verbs_section(),
        _occds_verbs_section(),
        _verb_mapping_section(),
        _define_yaml_section(),
        _ct_section(),
        _rules_caching_section(),
        _custom_rules_section(),
        _docs_section(),
    ]
    return "\n\n".join(sections) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate llms.txt from static strings + example files."
    )
    parser.add_argument(
        "--output",
        default=str(REPO_ROOT / "llms.txt"),
        help="Output path (default: llms.txt at repo root)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if llms.txt is stale (do not write)",
    )
    args = parser.parse_args()

    content = build()
    output_path = Path(args.output)

    # README namespace catalog is synced from the same curated lists
    # so the two artefacts can never drift out of sync.
    readme_existing = README_PATH.read_text(encoding="utf-8")
    readme_new = _render_readme(readme_existing)

    if args.check:
        stale: list[str] = []
        if not output_path.exists():
            print(f"STALE: {output_path} does not exist. Run without --check to generate it.")
            sys.exit(1)
        if output_path.read_text(encoding="utf-8") != content:
            stale.append(str(output_path))
        if readme_existing != readme_new:
            stale.append(str(README_PATH))
        if stale:
            for path in stale:
                print(
                    f"STALE: {path} is out of date. "
                    "Run `uv run python scripts/build_llms.py` to regenerate."
                )
            sys.exit(1)
        print(f"OK: {output_path} and {README_PATH} are up to date.")
    else:
        output_path.write_text(content, encoding="utf-8")
        print(f"Written: {output_path}")
        if readme_existing != readme_new:
            README_PATH.write_text(readme_new, encoding="utf-8")
            print(f"Written: {README_PATH} (namespace block synced)")
        else:
            print(f"Unchanged: {README_PATH} (namespace block already in sync)")


if __name__ == "__main__":
    main()
