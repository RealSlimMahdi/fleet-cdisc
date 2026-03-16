# Fleet Coding Agent Instructions

When acting as an AI coding agent or assistant on the **Fleet** repository, adhere strictly to the following guidelines.

## 1. Project Overview & Philosophy

**Fleet** is a Python-based CDISC SDTM/ADaM derivation toolkit built entirely on **Polars** DataFrame namespace extensions.

- **Goal:** Minimalistic, simple, yet powerful package to generate datasets for clinical statistical programming.
- **Workflow:** Users can choose inline Python pipeline chaining _or_ a metadata-driven approach using `define.yaml` (`StudyContext`).

## 2. Core Technical Constraints

- **Package Manager:** ALWAY use `uv`. **NEVER** use `pip`, `poetry`, `conda`, `pipenv` commands.
- **Data Manipulation:** NEVER use Pandas. ONLY use Polars. Maintain lazy evaluation semantics where possible (all code returns `pl.Expr` or accumulates into the fleet namespaces and is called at the end via `.to_frame()`).

## 3. Supported Execution Commands

These commands have been tested and verified for managing and maintaining this repo:

### Installing dependencies

```bash
# Sync all dependencies (and docs tools) via uv
uv sync --extra docs --extra all --extra dev
```

### Running Tests

```bash
# We use pytest
uv run pytest
```

### Linting & Formatting

```bash
# We use Ruff. DO NOT run black or flake8 or isort.
uv run ruff check
uv run ruff format
```

### Running Examples

```bash
# Test the full ADSL/ADVS end-to-end pipeline:
uv run python examples/full_pipeline_example.py
```

### Building and Serving Documentation

```bash
# Serve mkdocs site locally using the 'docs' extra dependencies
uv run --extra docs mkdocs serve

# Build the documentation structure cleanly
uv run --extra docs mkdocs build
```

## 4. Coding Style Guidelines (The Namespace API)

When modifying or suggesting code for Fleet pipelines:

- Use explicit chaining on `.sdtm`, `.adam`, `.adam.adsl`, or `.adam.occds`.
- Close the pipeline execution with `.to_frame()`.
- Watch out for positional argument limits. Key mapping values like `source=`, `value=`, and `ct_mapping=` in SDTM are implemented as keyword-only arguments to enforce explicit declarations.

_Example pattern:_

```python
dm = (
    raw_df.sdtm
    .hardcode_no_ct("DOMAIN", value="DM")
    .assign_no_ct("USUBJID", source="subject_id")
    .assign_ct("SEX", source="sex", ct_codelist="C66731", ct_mapping={"M": "M", "F": "F"})
    .to_frame()
)
```

## 5. Spec Driven Development (`define.yaml`)

Fleet supports reading schemas and standard standard version outputs from YAML specs. Always respect the `StudyContext.init()` initialization methods and Schema definitions when implementing CLI commands. Schema is managed via `pydantic`.
