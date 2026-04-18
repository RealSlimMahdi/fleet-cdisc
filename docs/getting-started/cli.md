# CLI Reference

Fleet provides the `fleet` command-line tool for bootstrapping studies, generating define specs, managing CDISC Controlled Terminology, and producing Define-XML. Commands that query the CDISC Library require a valid `CDISC_API_KEY` — set it in a `.env` file at your project root or as an environment variable.

```bash title=".env"
CDISC_API_KEY=your-api-key-here
```

---

## Bootstrapping Pipeline

The recommended way to start a new study. Run these three commands in order:

```bash
fleet init cfg    --study-id STUDY01 --domains DM,AE,VS,EX --adam-datasets ADSL,ADVS
fleet init define                      # reads study_config.yaml, queries CDISC IG
fleet init ct                          # reads define.yaml, downloads codelists
```

!!! note "Using `--root`?"
If you pass `--root` to `init cfg` (e.g. `--root ./my_study`), the config is written
to `./my_study/study_config.yaml` instead of the current directory. You must then pass
`--config ./my_study/study_config.yaml` to every subsequent `init` command — or `cd`
into that directory before running them:

    ```bash
    fleet init cfg --study-id STUDY01 --domains DM,AE,VS,EX --root ./my_study
    fleet init define --config ./my_study/study_config.yaml
    fleet init ct     --config ./my_study/study_config.yaml
    ```

### `fleet init cfg`

Create `study_config.yaml` and the study directory structure.

```bash
fleet init cfg --study-id CDISCPILOT01 --company "CDISC" \
  --domains DM,AE,VS,EX --adam-datasets ADSL,ADVS,ADAE --root ./my_study
```

| Option            | Default             | Description                   |
| ----------------- | ------------------- | ----------------------------- |
| `--study-id`      | _(required)_        | Study identifier              |
| `--company`       | _(none)_            | Originator / company name     |
| `--domains`       | _(none)_            | Comma-separated SDTM domains  |
| `--adam-datasets` | _(none)_            | Comma-separated ADaM datasets |
| `--ig`            | `3-4`               | SDTM IG version               |
| `--adam-ig`       | `1-1`               | ADaM IG version               |
| `--package`       | `sdtmct-2023-12-15` | CT package version            |
| `--root` / `-r`   | `.`                 | Study root directory          |

!!! warning "Non-default `--root` requires `--config` in subsequent commands"
When `--root` is set to anything other than `.`, the generated `study_config.yaml`
lives inside that folder. The next commands (`fleet init define`, `fleet init ct`)
default to looking for `study_config.yaml` in the **current working directory**.
Pass `--config <root>/study_config.yaml` explicitly, or `cd` into the root first.

### `fleet init define`

Generate `define.yaml` files pre-populated with standard variables from the CDISC Library IG. Reads domains/datasets from `study_config.yaml`.

```bash
fleet init define                              # both SDTM + ADaM (default)
fleet init define --sdtm-only                  # SDTM only
fleet init define --adam-only                  # ADaM only
fleet init define --config path/to/config.yaml # custom config location
```

| Option            | Default             | Description               |
| ----------------- | ------------------- | ------------------------- |
| `--config` / `-c` | `study_config.yaml` | Path to config file       |
| `--sdtm-only`     | _(off)_             | Generate SDTM define only |
| `--adam-only`     | _(off)_             | Generate ADaM define only |

The generated YAML includes variable names, labels, types, mandatory flags, **CDISC core designations** (`Req`, `Exp`, `Perm`, `Conditionally Required`), codelist references, and origin hints — all sourced from the CDISC Library. The `core` field enables graduated check severity (see [DatasetChecker](#datasetChecker) below). Variables are created **without** derivation blocks (carry-through columns); add derivation blocks to drive the pipeline.

### `fleet init ct`

Generate `codelists.py` from the codelist references in the `define.yaml` files. Reads all define specs and downloads the referenced codelists from the CDISC Library.

```bash
fleet init ct                                # reads config + both defines
fleet init ct --config path/to/config.yaml   # custom config location
fleet init ct --no-docs                      # lightweight file
```

| Option            | Default             | Description                          |
| ----------------- | ------------------- | ------------------------------------ |
| `--config` / `-c` | `study_config.yaml` | Path to config file                  |
| `--no-docs`       | _(off)_             | Omit definitions and preferred terms |

---

## Standalone Commands

These commands work independently of the bootstrapping pipeline.

## `fleet init-ct`

Bootstrap a `codelists.py` from the CDISC Library SDTM Implementation Guide.

This is a **one-time** operation when setting up a new study. It queries the SDTM IG to discover every codelist referenced by variables in the requested domains, then downloads the term definitions and generates a typed Python module.

```bash
fleet init-ct --domains DM,AE,VS,EX --output specs/my_study/sdtm/codelists.py
```

### Options

| Option            | Default             | Description                                                       |
| ----------------- | ------------------- | ----------------------------------------------------------------- |
| `--domains`       | _(required)_        | Comma-separated SDTM domain abbreviations (e.g. `DM,AE,VS,EX,LB`) |
| `--output` / `-o` | `codelists.py`      | Output file path                                                  |
| `--ig`            | `3-4`               | SDTM IG version                                                   |
| `--package`       | `sdtmct-2023-12-15` | CT package version to download terms from                         |
| `--no-docs`       | _(off)_             | Omit definitions and preferred terms (smaller file)               |

### Examples

```bash
# Standard bootstrap for a typical study
fleet init-ct --domains DM,AE,VS,EX --output specs/cdiscpilot01/sdtm/codelists.py

# Pin to a specific CT version
fleet init-ct --domains DM,AE --ig 3-4 --package sdtmct-2025-09-26 --output codelists.py

# Generate a lightweight file without definitions
fleet init-ct --domains DM --no-docs --output codelists.py
```

---

## `fleet add-ct`

Add domains to an **existing** `codelists.py` without losing previously generated codelists.

This command reads the existing file, detects which concept IDs are already present, discovers the new codelists required by the requested domains, and regenerates the file with the merged set.

```bash
fleet add-ct --domains LB,CM --output specs/my_study/sdtm/codelists.py
```

### Options

Same as `init-ct`. The `--output` path must point to an existing `codelists.py` (or a new file — in which case it behaves like `init-ct`).

### Examples

```bash
# Add lab and conmed domains to an existing file
fleet add-ct --domains LB,CM --output specs/cdiscpilot01/sdtm/codelists.py

# If all codelists are already present, the command reports "Nothing to add"
fleet add-ct --domains DM --output specs/cdiscpilot01/sdtm/codelists.py
```

### Typical output

```
Adding domains: LB, CM
Existing file:  specs/cdiscpilot01/sdtm/codelists.py (24 codelists)

New codelists to add: 8
Total after merge:    32

Updated /path/to/codelists.py — 32 codelists
```

---

## Workflow

The recommended bootstrapping workflow for a new study:

```mermaid
graph TD
    A[New study] --> B["fleet init cfg --study-id ... --domains DM,AE,VS,EX"]
    B --> C["fleet init define"]
    C --> D["fleet init ct"]
    D --> E["Edit define.yaml — add derivation blocks"]
    E --> F["Write pipelines with from codelists import SEX, RACE"]
    F --> G{Need more domains?}
    G -->|Yes| H["fleet add-ct --domains LB,CM"]
    H --> F
    G -->|No| I["fleet define-xml --spec define.yaml --output define.xml"]
```

### Source of truth

The source of truth for which variables and codelists to generate is the **CDISC Library IG model**. The `init define` command queries the IG endpoints and extracts variable metadata (name, label, type, core, codelist) from each domain. The `init ct` command then reads the generated `define.yaml` to download the exact codelists referenced.

---

## `fleet define-xml`

Generate a CDISC Define-XML 2.1 document from a `define.yaml` specification.

```bash
fleet define-xml --spec specs/cdiscpilot01/sdtm/define.yaml --output outputs/define_sdtm.xml
```

### Options

| Option            | Default      | Description                                        |
| ----------------- | ------------ | -------------------------------------------------- |
| `--spec` / `-s`   | _(required)_ | Path to the `define.yaml` specification file       |
| `--output` / `-o` | _(required)_ | Output path for the Define-XML file                |
| `--no-preview`    | _(off)_      | Skip generating the HTML preview alongside the XML |

By default, an HTML preview is generated alongside the XML (e.g. `define_sdtm.xml` → `define_sdtm_preview.html`) using the CDISC `define2-1.xsl` stylesheet. Place `define2-1.xsl` in the same directory as the output XML, or the preview step will be skipped with a warning.

### Examples

```bash
# Generate SDTM Define-XML with HTML preview
fleet define-xml --spec specs/cdiscpilot01/sdtm/define.yaml --output outputs/define_sdtm.xml

# Generate ADaM Define-XML without preview
fleet define-xml --spec specs/cdiscpilot01/adam/define.yaml --output outputs/define_adam.xml --no-preview
```
