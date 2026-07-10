---
description: "Use when writing or modifying SDTM pipeline code, namespace verbs, codelist mappings, or any file under src/fleet/sdtm/"
applyTo: "src/fleet/sdtm/**"
---

# SDTM Coding Style

## Namespace API

- Use explicit chaining on `.sdtm` namespace.
- Close pipeline with `.to_frame()`.
- Key mapping values (`source=`, `value=`, `ct=`, `ct_map=`) are keyword-only arguments.
- `assign` is the single mapping verb (constant via `value=`, copy via `source=`, CT via `ct=`/`ct_map=`). The pre-alpha spellings (`assign_no_ct`, `assign_ct`, `hardcode_no_ct`, `hardcode_ct`, …) are removed at runtime; `fleet migrate` rewrites them.

## Codelist Rule

**NEVER use raw NCI concept ID strings** (e.g. `ct="C66731"`). Always import and use generated codelist class names:

```python
from examples.cdiscpilot01.sdtm.codelists import SEX, RACE

dm = (
    raw_df.sdtm
    .assign("DOMAIN", value="DM")
    .assign("USUBJID", source="subject_id")
    .assign("SEX", source="sex", ct=SEX, ct_map={"M": "M", "F": "F"})
    .assign("RACE", source="race", ct=RACE)
    .to_frame()
)
```

When raw data already matches the standard, `ct_map` can be omitted — the codelist is still recorded for validation.

## Prerequisites

`codelists.py` must exist before pipelines use codelist classes. Generate with:

```bash
uv run fleet init ct
```

(Prefer the pipeline `fleet init cfg → init define → init ct`; `fleet add-ct` covers standalone bootstrap.)
