# Study Codelists (CDISCPILOT01)

This page documents the **auto-generated** codelist module that ships with the
CDISCPILOT01 example study (`examples/cdiscpilot01/sdtm/codelists.py`). It is
generated from the CDISC Library by [`CodelistGenerator`][fleet.ct.CodelistGenerator]
and is regenerated whenever a new domain is added.

!!! tip "One source of truth — three audiences served"
The same Python module powers:

    - **IDE auto-completion** for programmers writing pipelines (`SEX.M`, `RACE.WHITE`).
    - **Live runtime validation** through [`assign_ct`][fleet.sdtm.SDTMNamespace.assign_ct]
      and [`hardcode_ct`][fleet.sdtm.SDTMNamespace.hardcode_ct].
    - **Direct hyperlinks to the CDISC Library Browser** for reviewers and auditors,
      via the `_cdisc_url` attribute on every codelist class.

    No separate spreadsheet, no copy-pasted concept IDs, no drift between code and CT.

## How to use

```python
from examples.cdiscpilot01.sdtm.codelists import SEX, RACE, AGEU

dm = (
    raw_df.sdtm
    .assign_ct("SEX", source="sex", ct_codelist=SEX)
    .assign_ct("RACE", source="race", ct_codelist=RACE)
    .hardcode_ct("AGEU", value="YEARS", ct_codelist=AGEU)
    .to_frame()
)
```

Each codelist class exposes:

| Attribute         | Description                                                      |
| ----------------- | ---------------------------------------------------------------- |
| `_concept_id`     | NCI concept ID (e.g. `"C66731"`).                                |
| `_cdisc_url`      | Deep link to the CDISC Library Browser entry.                    |
| `_preferred_term` | Preferred term as published by CDISC (when `include_docs=True`). |
| `<TERM>`          | One class attribute per submission value (`SEX.M`, `SEX.F`, …).  |

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
