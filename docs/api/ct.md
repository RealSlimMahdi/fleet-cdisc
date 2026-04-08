# Controlled Terminology

Fleet provides three layers for working with CDISC Controlled Terminology:

1. **CDISC Library API client** — download CT directly from the authoritative source.
2. **Code generator** — turn API responses into typed Python constants with IDE auto-completion.
3. **CT validator** — validate values at runtime against loaded codelists.

---

## CDISC Library API Client

The `CDISCClient` wraps `httpx` to authenticate against the CDISC Library REST API. It requires an API key set via a `.env` file or the `CDISC_API_KEY` environment variable.

::: fleet.ct.CDISCClient
options:
show*root_heading: true
heading_level: 3
filters: ["!^*"]

::: fleet.ct.CDISCClientConfig
options:
show_root_heading: true
heading_level: 3

---

## Codelist Code Generator

The `CodelistGenerator` converts CDISC Library JSON responses into a Python module containing typed classes — one per codelist — with human-readable aliases and IDE auto-completion support.

### Recommended workflow

```bash
# Bootstrap from the SDTM IG (source of truth)
fleet init-ct --domains DM,AE,VS,EX --output specs/my_study/sdtm/codelists.py

# Add domains later (preserves existing codelists)
fleet add-ct --domains LB,CM --output specs/my_study/sdtm/codelists.py
```

### Programmatic usage

```python
from fleet.ct.api import CDISCClient
from fleet.ct.generator import CodelistGenerator

with CDISCClient() as client:
    # Recommended: derive codelists from the SDTM IG
    gen = CodelistGenerator.from_sdtm_ig(
        client,
        domains=["DM", "AE", "VS", "EX"],
        package="sdtmct-2025-09-26",
    )
    gen.write("specs/my_study/sdtm/codelists.py")
```

### Generated output

The generated `codelists.py` contains:

- **One class per codelist** with `_concept_id` attribute and submission value constants:

  ```python
  class C66731:
      """SEX (C66731)."""
      _concept_id = "C66731"
      F = "F"
      M = "M"
      U = "U"
  ```

- **Human-readable aliases** derived from the CDISC submission value:

  ```python
  SEX = C66731
  RACE = C74457
  ```

- **`__all__`** for clean wildcard imports:

  ```python
  from codelists import SEX, RACE
  # or
  from codelists import *
  ```

### Using generated codelists in pipelines

```python
from specs.cdiscpilot01.sdtm.codelists import SEX, RACE

dm = (
    raw_df.sdtm
    .assign_ct("SEX", source="sex", ct_codelist=SEX)
    .assign_ct("RACE", source="race", ct_codelist=RACE)
    .to_frame()
)
```

`assign_ct` accepts either a codelist class (`SEX`) or a raw NCI concept ID string (`"C66731"`). The class form is preferred for readability and auto-completion.

::: fleet.ct.CodelistGenerator
options:
show*root_heading: true
heading_level: 3
filters: ["!^*"]

---

## CT Validator

The singleton `CTValidator` provides runtime validation of values against loaded codelists.

### How CT validation works

**Validation fires at pipeline-build time** — when you call `.hardcode_ct()` or `.assign_ct()` in
Python, not when you call `.to_frame()`. The check happens during the method call itself, before
any data is processed.

**The validator is opt-in via initialization.** Fleet ships a module-level singleton that starts
empty. You must load CT data into it before using `ct_codelist=` parameters. If the singleton
has no data loaded, validation is silently skipped and the value is assigned as-is — no error,
no warning.

**Failures warn, they do not block.** If a value is not a valid CDISC submission term, a Python
`UserWarning` is emitted via `warnings.warn()`. The pipeline continues and the value is still
written to the output. This design keeps pipelines runnable during development even before CT
packages are fully loaded.

#### Step-by-step — enabling CT validation

```python
import warnings
from fleet import load_controlled_terminology, get_validator

# 1. Load the CT package once, at script/session start.
#    The file is a YAML or CSV produced by `fleet init ct` or `fleet init-ct`.
load_controlled_terminology("specs/cdiscpilot01/sdtm/ct_package.yaml")

# 2. Import the generated codelist classes.
from specs.cdiscpilot01.sdtm.codelists import AGEU, SEX

# 3. Build your pipeline — validation fires here on each verb call.
import warnings
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    dm = (
        raw_df.sdtm
        .hardcode_ct("AGEU", value="YEARS", ct_codelist=AGEU)   # OK — valid term
        .hardcode_ct("AGEU", value="YRS",   ct_codelist=AGEU)   # Warns immediately
        .to_frame()
    )

# Any invalid values produce a warning at the .hardcode_ct() call site,
# not when .to_frame() runs.
for w in caught:
    print(w.message)
# UserWarning: Value 'YRS' not in codelist 'C66781'. Valid values: DAYS, HOURS, MINUTES, MONTHS, WEEKS, YEARS
```

#### Inspecting the validator state

```python
from fleet import get_validator

v = get_validator()
print(v.get_cache_info())
# {'codelists_loaded': ['C66781', 'C66731', ...], 'aliases': {'AGEU': 'C66781', ...},
#  'ct_path': 'specs/.../ct_package.yaml', 'initialized': True}

# Check all valid terms for a codelist
print(v.get_valid_values("C66781"))  # ['DAYS', 'HOURS', 'MINUTES', 'MONTHS', 'WEEKS', 'YEARS']
```

#### ADaM namespaces

The ADaM namespace verbs (`.assigned()`, `.derivation()`, etc.) do **not** accept a
`ct_codelist=` parameter — ADaM CT compliance is validated post-hoc via the CDISC Rules Engine
rather than inline. CT validation at pipeline-build time is a feature of the SDTM namespace only.

---

::: fleet.ct.CTValidator
options:
show*root_heading: true
heading_level: 3
filters: ["!^*"]

## load_controlled_terminology

::: fleet.ct.load_controlled_terminology
options:
show_root_heading: true
heading_level: 3

## get_validator

::: fleet.ct.get_validator
options:
show_root_heading: true
heading_level: 3
