# Study Codelists (CDISCPILOT01)

This page documents the **auto-generated** codelist module that ships with the
CDISCPILOT01 example study (`examples/cdiscpilot01/sdtm/codelists.py`). It is
generated from the CDISC Library by [`CodelistGenerator`][fleet.ct.CodelistGenerator]
and is regenerated whenever a new domain is added.

!!! tip "One source of truth — three audiences served"
The same Python module powers:

    - **IDE auto-completion** for programmers writing pipelines (`SEX.M`, `RACE.WHITE`).
    - **Live runtime validation** through
      [`assign(ct=...)`][fleet.core._verb_mixin.SharedVerbsMixin.assign].
    - **Direct hyperlinks to the CDISC Library Browser** for reviewers and auditors,
      via the `_cdisc_url` attribute on every codelist class.

    No separate spreadsheet, no copy-pasted concept IDs, no drift between code and CT.

## How to use

### In a standalone study project (recommended)

When your study lives in its own directory with a `study_config.yaml`,
use `import_codelists()` to load the generated module without `sys.path` hacks:

```python
from fleet.ct import import_codelists

# Auto-discovers codelists.py via study_config.yaml in CWD
ct = import_codelists()

dm = (
    raw_df.sdtm.assign("SEX", source="sex", ct=ct.SEX)
    .assign("RACE", source="race", ct=ct.RACE)
    .assign("AGEU", value="YEARS", ct=ct.AGEU)
    .to_frame()
)
```

Or register the module so bare `from codelists import ...` works:

```python
from fleet.ct import import_codelists

import_codelists()  # registers 'codelists' in sys.modules
from codelists import SEX, RACE, AGEU  # now works everywhere in the session

dm = (
    raw_df.sdtm.assign("SEX", source="sex", ct=SEX)
    .assign("RACE", source="race", ct=RACE)
    .assign("AGEU", value="YEARS", ct=AGEU)
    .to_frame()
)
```

You can also pass an explicit path if your codelists file lives somewhere non-standard:

```python
ct = import_codelists("path/to/my_codelists.py")
```

### Within the Fleet repo (example studies)

```python
from examples.cdiscpilot01.sdtm.codelists import SEX, RACE, AGEU

dm = (
    raw_df.sdtm.assign("SEX", source="sex", ct=SEX)
    .assign("RACE", source="race", ct=RACE)
    .assign("AGEU", value="YEARS", ct=AGEU)
    .to_frame()
)
```

Each codelist class exposes:

| Attribute         | Description                                                      |
| ----------------- | ---------------------------------------------------------------- |
| `_concept_id`     | NCI concept ID (e.g. `"C66731"`).                                |
| `_cdisc_url`      | Deep link to the CDISC Library Browser entry.                    |
| `_preferred_term` | Preferred term as published by CDISC (when `include_docs=True`). |
| `_terms`          | Every submission value of the codelist, as a tuple.              |
| `<TERM>`          | One class attribute per submission value (`SEX.M`, `SEX.F`, …).  |

A term that starts with a digit gets `T_` in front (`FREQ.T_2_TIMES_PER_WEEK`).
A term with no letter or digit (`%`) is `T_<term NCI code>`. When two terms
give one name, each name ends with the term NCI code, so no term is lost.

## Generated module

::: examples.cdiscpilot01.sdtm.codelists
options:
show_root_heading: false
show_root_toc_entry: false
heading_level: 3
members_order: source
show_source: false
filters: ["!^_"]
show_bases: false
show_if_no_docstring: true
docstring_section_style: list
