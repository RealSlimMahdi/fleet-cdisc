---
description: "Use when writing or modifying SDTM pipeline code, namespace verbs, codelist mappings, or any file under src/fleet/sdtm/"
applyTo: "src/fleet/sdtm/**"
---

# SDTM Coding Style

## Namespace API

- Use explicit chaining on `.sdtm` namespace.
- Close pipeline with `.to_frame()`.
- Key mapping values (`source=`, `value=`, `ct_mapping=`) are keyword-only arguments.

## Codelist Rule

**NEVER use raw NCI concept ID strings** (e.g. `ct_codelist="C66731"`). Always import and use generated codelist class names:

```python
from examples.cdiscpilot01.sdtm.codelists import SEX, RACE

dm = (
    raw_df.sdtm
    .hardcode_no_ct("DOMAIN", value="DM")
    .assign_no_ct("USUBJID", source="subject_id")
    .assign_ct("SEX", source="sex", ct_codelist=SEX, ct_mapping={"M": "M", "F": "F"})
    .assign_ct("RACE", source="race", ct_codelist=RACE)
    .to_frame()
)
```

When raw data already matches the standard, `ct_mapping` can be omitted — the codelist is still recorded for validation.

## Prerequisites

`codelists.py` must exist before pipelines use codelist classes. Generate with:

```bash
uv run fleet init ct
# or standalone:
uv run fleet init-ct --domains DM,AE,VS,EX --output codelists.py
```
