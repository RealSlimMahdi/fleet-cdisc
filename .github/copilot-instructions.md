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

## 6. Publishing to PyPI

The package distribution name is `fleet-cdisc` (import name remains `fleet`).

### Build

```bash
# Remove any previous build artifacts, then rebuild
rm -rf dist/
uv run python -m build
```

This produces `dist/fleet_cdisc-0.1.0-py3-none-any.whl` and `dist/fleet_cdisc-0.1.0.tar.gz`.

### Upload to TestPyPI (staging)

```bash
uv run twine upload --repository testpypi dist/*
```

Use `__token__` as the username and your TestPyPI API token as the password.

### Verify TestPyPI install

```bash
pip install -i https://test.pypi.org/simple/ fleet-cdisc==0.1.0
```

### Upload to real PyPI

```bash
uv run twine upload dist/*
```

Use `__token__` as the username and your PyPI API token as the password.

## 7. ADaM Namespace Mixin Discipline (NO code duplication)

Fleet's ADaM layer is built from composable namespace classes (`ADSLNamespace`, `OCCDSNamespace`, `OncoNamespace`, …). Many verbs are identical across these classes. **Duplicating verb implementations across namespace classes is strictly forbidden.**

### The rule

> **If a verb makes sense for 2 or more namespaces, it MUST live in a mixin in `src/fleet/adam/_mixins.py`. NEVER copy the implementation into individual namespace classes.**

### Decision tree

| Scope                                   | Action                                                                      |
| --------------------------------------- | --------------------------------------------------------------------------- |
| Verb used in **1** namespace only       | Implement directly in that class                                            |
| Verb used in **2 or more** namespaces   | Extract into a mixin in `_mixins.py`; all namespaces inherit it             |
| Verb used in **all** namespaces         | Add to `SharedADaMVerbsMixin`                                               |
| Verb used in a **subset** of namespaces | Create a focused mixin (e.g. `DateDerivationMixin`) and inherit selectively |

### How to add a shared verb

1. Add the method to the appropriate mixin class in `src/fleet/adam/_mixins.py`.
2. The method return type MUST be `Self` (from `typing`) so IDE auto-complete resolves to the concrete subclass at each call-site.
3. Every namespace class that inherits from that mixin gets the verb automatically — **no per-class edits needed**.

```python
# src/fleet/adam/_mixins.py
class SharedADaMVerbsMixin:
    def my_new_verb(self, target: str, *, param: str) -> Self:
        ...
        return self._chain(some_expr.alias(target))
```

### How to expose a verb only in some namespaces

Create a separate mixin and inherit selectively:

```python
# _mixins.py
class DateDerivationMixin:
    def impute_date(self, target: str, *, source: str) -> Self: ...

# adsl_namespace.py  ← needs date verbs
class ADSLNamespace(SharedADaMVerbsMixin, DateDerivationMixin): ...

# onco_namespace.py  ← does NOT need date verbs
class OncoNamespace(SharedADaMVerbsMixin): ...
```

### How to extend a shared verb in one namespace

Override the method and call `super()` to reuse the base logic:

```python
class ADSLNamespace(SharedADaMVerbsMixin):
    def derivation(self, target: str, *, expression: str | pl.Expr) -> Self:
        # ADSL-specific validation here
        ...
        return super().derivation(target, expression=expression)
```

### Chaining infrastructure

All mixin methods MUST use `self._chain(*exprs)` to append Polars expressions to the lazy plan and `self._materialise_then(df)` for operations that require materialisation (e.g. filters). These helpers are defined in `SharedADaMVerbsMixin` and ensure the returned instance is always the correct concrete subtype.

### Canonical reference

`src/fleet/adam/_mixins.py` is the **single source of truth** for all shared ADaM verbs. Read the module docstring there before adding, removing, or modifying any shared verb — it explains the full architecture.
