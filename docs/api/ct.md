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

<!-- docs:no-run: calls the CDISC Library API -->

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

- **One class per codelist** with `_concept_id`, `_cdisc_url`, `_terms` and submission-value constants:

  ```python
  class C66731:
      """SEX (C66731).

      The assemblage of physical properties or qualities by which male is
      distinguished from female.

      See: https://library.cdisc.org/browser/#/mdr/ct/2023-12-15/packages/sdtmct-2023-12-15/codelists/C66731
      """

      _concept_id = "C66731"
      _cdisc_url = "https://library.cdisc.org/browser/#/mdr/ct/2023-12-15/packages/sdtmct-2023-12-15/codelists/C66731"
      _preferred_term = "CDISC SDTM Sex of Individual Terminology"

      _terms = ("F", "INTERSEX", "M", "U")

      F = "F"
      INTERSEX = "INTERSEX"
      M = "M"
      U = "U"
  ```

  !!! tip "Direct line to the source of truth"
      The `_cdisc_url` attribute and the `See:` line in each docstring point to the codelist's entry in the **CDISC Library Browser**. When a reviewer or auditor reads pipeline code, hovering `SEX` in an IDE shows the URL; clicking the link in the docs site takes them straight to the authoritative CDISC definition. There is no separate lookup table to maintain. The URL is built from the NCI concept ID and the CT package at generation time.

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
  (`__ct_package__ = "sdtmct-2025-09-26"`). A file with codelists from an
  SDTM and an ADaM package has `__ct_packages__` instead
  (`("adamct-2023-06-30", "sdtmct-2023-12-15")`). The
  [stale checks](../concepts/define-yaml.md#controlled-terminology-in-the-spec-path)
  compare them with `ct.package` and `ct.adam_package` in `study_config.yaml`.

### Importing codelists in standalone study projects

When your study lives in its own directory (not inside the Fleet repo), the
generated `codelists.py` isn't on the Python path by default.
Use [`import_codelists()`][fleet.ct.import_codelists] to load it dynamically:

<!-- docs:no-run: needs a study codelists.py -->

```python
from fleet.ct import import_codelists

# Strategy 1: auto-discover via study_config.yaml in CWD or a parent folder
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

    1. `study_config.yaml` in CWD or the nearest parent folder (git-style, as the
       CLI does) → reads `paths.metadata_sdtm` → appends `/codelists.py`
    2. Falls back to `<CWD>/metadata/sdtm/codelists.py`

    So a script in `programs/sdtm` finds the codelists of its study with no path.

!!! tip "Editor auto-completion"
    `import_codelists()` loads the module at run time, so the editor does not
    see `from codelists import SEX` by itself. Add the metadata folder to the
    analysis paths in `.vscode/settings.json` at the study root:

    ```json
    {"python.analysis.extraPaths": ["metadata/sdtm"]}
    ```

### Using generated codelists in pipelines

<!-- docs:no-run: needs a study codelists.py -->

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

**The check runs when you call the verb**, not when you call `.to_frame()`.

**A codelist class holds its terms.** The generated `codelists.py` writes the
submission values of each codelist into the class (`_terms`). With `ct=SEX`,
`assign` checks the values against these terms. You do not load anything.
This is true for `source=` (the distinct values of the column) and for
`value=` (the literal).

**A concept ID string needs loaded CT.** With `ct="C66731"`, the check reads
the validator cache. Load it once with `get_validator().load_ct_file(path)`.
If the cache does not hold the codelist, `assign` warns
`codelist 'C66731' not found / CT not loaded` and writes the values
unchecked.

**Failures warn, they do not block.** A value that is not a submission term
gives a `UserWarning`. The pipeline continues and the value is written as
it is. Null and blank values are never findings.

#### Example: check against the codelist classes

`import_codelists()` puts the study `codelists.py` on the import path (see
[Importing codelists](#importing-codelists-in-standalone-study-projects)).

```python
import warnings

import polars as pl

import fleet
from codelists import AGEU, SEX

raw_df = pl.from_repr("""
┌────────────┬─────┐
│ subject_id ┆ sex │
│ ---        ┆ --- │
│ str        ┆ str │
╞════════════╪═════╡
│ S1         ┆ M   │
│ S2         ┆ Q   │
└────────────┴─────┘
""")

with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    dm = (
        raw_df.sdtm.assign("SEX", source="sex", ct=SEX)  # Q is not a SEX term
        .assign("AGEU", value="YRS", ct=AGEU)  # YRS is not an AGEU term
        .to_frame()
    )

for w in caught:
    print(w.message)
# SEX: column 'sex' contains values not in codelist 'C66731': ['Q']. Valid values:
#   ['F', 'INTERSEX', 'M', 'U']. Consider providing a ct_map parameter.
# assign('AGEU'): value 'YRS' not in codelist 'C66781'. Valid values:
#   ['DAYS', 'HOURS', 'MONTHS', 'WEEKS', 'YEARS']
```

#### Optional: load a CT file for concept ID strings

`get_validator().load_ct_file(path)` fills the validator cache. The file is
one of:

- YAML: one key per codelist, each a mapping of code to decoded value.
- CSV: the columns `codelist`, `code` and `value`, one row per term.

<!-- docs:no-run: needs a CT file on disk -->

```python
from pathlib import Path

from fleet import get_validator

Path("ct.yaml").write_text("C66731:\n  F: Female\n  M: Male\n  U: Unknown\n")

v = get_validator()
v.load_ct_file("ct.yaml", aliases={"SEX": "C66731"})
print(v.get_cache_info())
# {'codelists_loaded': ['C66731'], 'aliases': {'SEX': 'C66731'},
#  'ct_path': 'ct.yaml', 'initialized': True}
print(v.get_valid_values("SEX"))  # ['F', 'M', 'U']
```

`load_controlled_terminology(path)` reads the same file formats and only
returns a dict (`{codelist: {code: value}}`). It does not fill the validator.

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
