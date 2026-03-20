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
show_root_heading: true
heading_level: 3
filters: ["!^_"]

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
show_root_heading: true
heading_level: 3
filters: ["!^_"]

---

## CT Validator

The singleton `CTValidator` provides runtime validation of values against loaded codelists.

::: fleet.ct.CTValidator
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]

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
