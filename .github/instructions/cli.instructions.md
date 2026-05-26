---
description: "Use when working with Fleet CLI commands, bootstrapping studies, CDISC CT, define-xml, TLG export, or validation engine"
---

# Fleet CLI Reference

## Bootstrapping Pipeline (new studies)

```bash
uv run fleet init cfg --study-id CDISCPILOT01 --company "CDISC" \
  --domains DM,AE,VS,EX --adam-datasets ADSL,ADVS,ADAE --root ./my_study
uv run fleet init define
uv run fleet init ct
uv run fleet init rules
```

## Standalone Codelist Commands

```bash
uv run fleet init-ct --domains DM,AE,VS,EX --output examples/cdiscpilot01/sdtm/codelists.py
uv run fleet add-ct --domains LB,CM --output examples/cdiscpilot01/sdtm/codelists.py
uv run fleet init-ct --domains DM,AE --ig 3-4 --package sdtmct-2025-09-26 --output codelists.py
uv run fleet init-ct --domains DM --no-docs --output codelists.py
```

## Define-XML Generation

```bash
uv run fleet define-xml --spec examples/cdiscpilot01/sdtm/define.yaml --output outputs/define_sdtm.xml
uv run fleet define-xml --spec examples/cdiscpilot01/sdtm/define.yaml --output outputs/define_sdtm.xml --enrich-methods
uv run fleet define-xml --spec examples/cdiscpilot01/adam/define.yaml --output outputs/define_adam.xml --no-preview
```

## TLG Export

```bash
uv run fleet tlg export --domain ae --data adae.csv --adsl adsl.csv --output ae_summary.html \
    --title "Table 14.3.1.1" --subtitle "AE Summary" --footnote "Source: ADAE"
uv run fleet tlg export --domain ae --format pdf --data adae.csv --adsl adsl.csv --output ae.pdf
uv run fleet tlg export --domain ae --format pptx --data adae.csv --adsl adsl.csv --output ae.pptx
uv run fleet tlg export --domain vs --data advs.csv --adsl adsl.csv --output vs_summary.html
```

## CDISC Rules Engine (Validation)

```bash
uv run fleet install-engine
uv run fleet install-engine --version v0.15
uv run fleet install-engine --force
uv run fleet doctor
uv run fleet uninstall-engine
```

Engine discovery order: `FLEET_RULES_ENGINE` env → `validation.engine_path` in study_config.yaml → managed install → legacy fallback.

## Documentation

```bash
uv run --extra docs mkdocs serve
uv run --extra docs mkdocs build
```
