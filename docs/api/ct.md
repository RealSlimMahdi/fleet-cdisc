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
fleet add-ct --domains DM,AE,VS,EX --output specs/my_study/sdtm/codelists.py

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

- **One class per codelist** with `_concept_id`, `_cdisc_url`, and submission-value constants:

  ```python
  class C66731:
      """SEX (C66731).

      The assemblage of physical properties or qualities by which male is
      distinguished from female.

      See: https://library.cdisc.org/browser/#/codelist/C66731
      """

      _concept_id = "C66731"
      _cdisc_url = "https://library.cdisc.org/browser/#/codelist/C66731"
      F = "F"
      M = "M"
      U = "U"
  ```

  !!! tip "Direct line to the source of truth"
  The `_cdisc_url` attribute and the `See:` line in each docstring point to the codelist's entry in the **CDISC Library Browser**. When a reviewer or auditor reads pipeline code, hovering `SEX` in an IDE shows the URL; clicking the link in the docs site takes them straight to the authoritative CDISC definition. There is no separate lookup table to maintain — the URL is constructed from the NCI concept ID at generation time.

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

- **`__ct_package__`** at the top, naming the CT package every class came from
  (`__ct_package__ = "sdtmct-2025-09-26"`). The
  [stale checks](../concepts/define-yaml.md#controlled-terminology-in-the-spec-path)
  compare it with `ct.package` in `study_config.yaml`.

### Importing codelists in standalone study projects

When your study lives in its own directory (not inside the Fleet repo), the
generated `codelists.py` isn't on the Python path by default.
Use [`import_codelists()`][fleet.ct.import_codelists] to load it dynamically:

```python
from fleet.ct import import_codelists

# Strategy 1: auto-discover via study_config.yaml in CWD
ct = import_codelists()
SEX = ct.SEX

# Strategy 2: register in sys.modules so bare imports work
import_codelists()  # one-time call
from codelists import SEX, RACE  # works for the rest of the session

# Strategy 3: explicit path (non-standard locations)
ct = import_codelists("/absolute/path/to/codelists.py")
```

!!! info "Resolution order"
    When called without arguments, `import_codelists()` resolves the file as follows:

    1. `study_config.yaml` in CWD → reads `paths.metadata_sdtm` → appends `/codelists.py`
    2. Falls back to `<CWD>/metadata/sdtm/codelists.py`

    This means `cd`-ing into your study root before running a script is all you need.

### Using generated codelists in pipelines

```python
from fleet.ct import import_codelists

ct = import_codelists()

dm = (
    raw_df.sdtm.assign("SEX", source="sex", ct=ct.SEX)
    .assign("RACE", source="race", ct=ct.RACE)
    .to_frame()
)
```

`assign(ct=...)` accepts either a codelist class (`SEX`) or a raw NCI concept ID string (`"C66731"`). The class form is preferred for readability and auto-completion.

::: fleet.ct.CodelistGenerator
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]

---

## Codelist Importer

The [`import_codelists()`][fleet.ct.import_codelists] function dynamically loads a
generated `codelists.py` from your study workspace, removing the need for `sys.path`
manipulation or package-relative imports.

::: fleet.ct.import_codelists
options:
show_root_heading: true
heading_level: 3

---

## CT Validator

The singleton `CTValidator` provides runtime validation of values against loaded codelists.

### How CT validation works

**Validation fires at pipeline-build time** — when you call `.assign(ct=...)` in
Python, not when you call `.to_frame()`. The check happens during the method call itself, before
any data is processed.

**The validator is opt-in via initialization.** Fleet ships a module-level singleton that starts
empty. You must load CT data into it before using `ct=` parameters. If the singleton
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
#    The file is a YAML or CSV produced by `fleet init ct` or `fleet add-ct`.
load_controlled_terminology("examples/cdiscpilot01/sdtm/ct_package.yaml")

# 2. Import the generated codelist classes.
from fleet.ct import import_codelists

ct = import_codelists()
AGEU = ct.AGEU
SEX = ct.SEX

# 3. Build your pipeline — validation fires here on each verb call.
import warnings

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    dm = (
        raw_df.sdtm.assign("AGEU", value="YEARS", ct=AGEU)  # OK — valid term
        .assign("AGEU", value="YRS", ct=AGEU)  # Warns immediately
        .to_frame()
    )

# Any invalid values produce a warning at the .assign(ct=...) call site,
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

ADaM pipelines typically skip build-time CT validation (`assign` without `ct=`) —
ADaM CT compliance is validated post-hoc via the CDISC Rules Engine rather than
inline. Passing `ct=` still works on any namespace since `assign` is shared.

---

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
