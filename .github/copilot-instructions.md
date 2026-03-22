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

All Python scripts in `examples/` are part of the project's validation surface. **Every script must execute without error** after any change.

```bash
# Run ALL example scripts (mandatory after every feature change):
uv run python examples/full_pipeline_example.py
uv run python examples/cdiscpilot01_inline.py
uv run python examples/cdiscpilot01_spec_driven.py
uv run python examples/adnca_example.py
uv run python examples/tdd_example.py
```

If a new `.py` file is added to `examples/`, it MUST also be included in this validation list and run as part of verification.

### CDISC Controlled Terminology CLI

Fleet provides a CLI for bootstrapping studies and managing CDISC CT. An API key is required — set `CDISC_API_KEY` in a `.env` file at the project root.

#### Bootstrapping Pipeline (recommended for new studies)

```bash
# Step 1: Create study_config.yaml + directory structure
uv run fleet init cfg --study-id CDISCPILOT01 --company "CDISC" \
  --domains DM,AE,VS,EX --adam-datasets ADSL,ADVS,ADAE --root ./my_study

# Step 2: Generate define.yaml from the CDISC Library IG (both SDTM + ADaM)
uv run fleet init define

# Step 3: Generate codelists.py from the define.yaml codelist references
uv run fleet init ct
```

#### Standalone Commands

```bash
# Bootstrap codelists.py directly from the SDTM IG (without config/define pipeline)
uv run fleet init-ct --domains DM,AE,VS,EX --output specs/cdiscpilot01/sdtm/codelists.py

# Add more domains incrementally (preserves existing codelists)
uv run fleet add-ct --domains LB,CM --output specs/cdiscpilot01/sdtm/codelists.py

# Pin to a specific IG version and CT package
uv run fleet init-ct --domains DM,AE --ig 3-4 --package sdtmct-2025-09-26 --output codelists.py

# Generate without definitions/docs (lightweight file)
uv run fleet init-ct --domains DM --no-docs --output codelists.py
```

The generated `codelists.py` provides:

- **Classes per codelist** (e.g. `class C66731:`) with `_concept_id` and term attributes.
- **Human-readable aliases** (e.g. `SEX = C66731`, `RACE = C74457`) derived from CDISC submission values.
- **`__all__`** for clean `from codelists import *` usage.

The source of truth for which variables and codelists to generate is the **CDISC Library IG model**. The `init define` command queries the IG endpoints and pre-populates the define.yaml with standard variable metadata.

### Define-XML Generation

```bash
# Generate Define-XML 2.1 from a define.yaml specification
uv run fleet define-xml --spec specs/cdiscpilot01/sdtm/define.yaml --output outputs/define_sdtm.xml

# Without HTML preview
uv run fleet define-xml --spec specs/cdiscpilot01/adam/define.yaml --output outputs/define_adam.xml --no-preview
```

### CDISC Rules Engine (Validation)

Fleet wraps the official CDISC Rules Engine for regulatory-grade validation. The engine is distributed as a PyInstaller bundle and must be installed before validation commands can run.

```bash
# Download the CDISC Rules Engine binary for your platform (macOS/Linux/Windows)
uv run fleet install-engine

# Pin to a specific release tag
uv run fleet install-engine --version v0.15

# Re-download (overwrite existing installation)
uv run fleet install-engine --force

# Check installation health: engine, pyreadstat, etc.
uv run fleet doctor

# Remove the managed engine installation
uv run fleet uninstall-engine
```

The engine binary is stored at a platform-appropriate location:

- **macOS / Linux:** `~/.fleet/cdisc-rules-engine/core/core`
- **Windows:** `%LOCALAPPDATA%\fleet\cdisc-rules-engine\core\core.exe`

**Discovery order** (first match wins):

1. `FLEET_RULES_ENGINE` environment variable (or `.env` file).
2. `validation.engine_path` in `study_config.yaml` (team-shared, committed to VCS).
3. Managed install from `fleet install-engine`.
4. Legacy `../cdisc-rules-engine/core.py` (development fallback).

To share an engine path across a team, add it to `study_config.yaml`:

```yaml
validation:
  engine_path: tools/cdisc-core # relative to study root
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
- **All public functions and methods MUST use Google-style docstrings** (see §8 for full convention). Every docstring needs `Args:`, `Returns:`, and `Examples:` sections. Examples must be complete pipeline snippets ending with `.to_frame()`.
- **NEVER use raw NCI concept ID strings** (e.g. `ct_codelist="C66731"`) in pipeline code. Always import and use the generated codelist class names (e.g. `ct_codelist=SEX`). The codelist classes are generated by `fleet init ct` (or `fleet init-ct`) and live in `codelists.py`. Raw concept IDs are unfriendly and error-prone — the class form provides IDE auto-completion, readability, and traceability.

_Prerequisites:_ The `codelists.py` file must exist before pipelines can use codelist classes. Generate it with the bootstrapping pipeline (`fleet init ct`) or standalone (`fleet init-ct --domains DM,AE,VS,EX --output codelists.py`).

_Example pattern:_

```python
from specs.cdiscpilot01.sdtm.codelists import SEX, RACE

dm = (
    raw_df.sdtm
    .hardcode_no_ct("DOMAIN", value="DM")
    .assign_no_ct("USUBJID", source="subject_id")
    .assign_ct("SEX", source="sex", ct_codelist=SEX, ct_mapping={"M": "M", "F": "F"})
    .assign_ct("RACE", source="race", ct_codelist=RACE)
    .to_frame()
)
```

`assign_ct` accepts either a generated codelist class (e.g. `SEX`) or a raw NCI concept ID string (e.g. `"C66731"`). **Always prefer the class form.** When raw data already matches the standard (e.g. source is already `"M"`), `ct_mapping` can be omitted — the codelist is still recorded for validation.

## 5. Spec Driven Development (`define.yaml`)

Fleet supports reading schemas and standard standard version outputs from YAML specs. Always respect the `StudyContext.init()` initialization methods and Schema definitions when implementing CLI commands. Schema is managed via `pydantic`.

## 6. Publishing to PyPI

The package distribution name is `fleet-cdisc` (import name remains `fleet`).

### How versioning works

The **git tag** is the single source of truth for published versions. The CI publish workflow (`.github/workflows/publish.yml`) extracts the version from the tag name (e.g. `v0.2.0` → `0.2.0`) and injects it into both `pyproject.toml` and `src/fleet/_version.py` before building. You do **not** need to manually edit version strings before releasing.

### CI/CD publish triggers

| Trigger                         | Target       | Version source                |
| ------------------------------- | ------------ | ----------------------------- |
| Push a `v*` tag (e.g. `v0.2.0`) | **PyPI**     | Tag name, `v` prefix stripped |
| Push to `devel` branch          | **TestPyPI** | Dev version from commit SHA   |

### Releasing a new version (step-by-step)

1. Make sure all changes are merged into `main`.
2. Tag the release commit:
   ```bash
   git tag v0.2.0
   git push origin v0.2.0
   ```
3. The publish workflow will automatically:
   - Write `0.2.0` into `pyproject.toml` and `_version.py`
   - Build the wheel and sdist
   - Upload to PyPI using the `PYPI_API_TOKEN` secret
4. Verify the release:
   ```bash
   pip install fleet-cdisc==0.2.0
   python -c "import fleet; print(fleet.__version__)"
   ```

### Local build (optional, for testing)

```bash
rm -rf dist/
uv run python -m build
```

### Manual upload (rarely needed)

```bash
# TestPyPI
uv run twine upload --repository testpypi dist/*

# PyPI
uv run twine upload dist/*
```

Use `__token__` as the username and the corresponding API token as the password.

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

All mixin methods MUST use `self._chain(*exprs)` to append Polars expressions to the lazy plan and `self._materialise_then(df)` for operations that require materialisation (e.g. filters). These helpers use `copy.copy(self)` internally to preserve all instance state (including subclass attributes) across chaining calls, then update only the `_lazy` plan. They are defined in `SharedADaMVerbsMixin` and ensure the returned instance is always the correct concrete subtype.

### Debugging verbs

Both `SDTMNamespace` and all ADaM sub-namespaces expose two chainable debug verbs:

- **`inspect(prefix="DEBUG")`** — materialises the pipeline at that point, prints schema + shape + head rows, and returns a fresh namespace wrapping the collected frame (hard checkpoint).
- **`explain()`** — prints the Polars query plan without materialising, returns `self` unchanged.

Use `.inspect()` to isolate which derivation step introduced bad data or types. Use `.explain()` to understand Polars optimisation without triggering computation.

### Canonical reference

`src/fleet/adam/_mixins.py` is the **single source of truth** for all shared ADaM verbs. Read the module docstring there before adding, removing, or modifying any shared verb — it explains the full architecture.

## 8. Docstring Convention (Google-style)

All public functions and methods **MUST** use Google-style docstrings with these sections (in order):

1. **One-sentence summary** (imperative mood).
2. **Extended description** (optional, 2–3 sentences max). Reference CDISC spec where applicable.
3. **Args:** — one line per parameter, keyword-only markers implicit.
4. **Returns:** — type and short description.
5. **Raises:** — only if non-obvious exceptions can occur.
6. **Examples:** — at least one copy-pasteable, CDISC-compliant code block ending with `.to_frame()`.

### Rules

- Use `Examples:` (plural, no trailing `::`) as the section header inside the docstring, followed by a description and `::` for the code block.
- Every example must be a **complete pipeline snippet** (not a bare `.verb(...)` fragment).
- Never use NumPy/Sphinx `Parameters ----------` style — always use `Args:`.
- Never use bare `Example::` (singular with double colon) — always `Examples:`.
- Private helpers (`_chain`, `_materialise_then`, etc.) are exempt.

### Template

```python
def verb_name(self, target: str, *, source: str) -> Self:
    """One-sentence summary of what the verb does.

    Longer description if needed (2-3 sentences max).

    Args:
        target: Name of the output column to create.
        source: Name of the input column.

    Returns:
        Self: The namespace with *target* appended; call ``.to_frame()``
            to materialise.

    Examples:
        Copy the raw subject ID to USUBJID::

            dm = (
                raw_df.sdtm
                .assign_no_ct("USUBJID", source="subject_id")
                .to_frame()
            )
    """
```

## 9. Documentation Files (`docs/`) — Formatting Rules

Files under `docs/api/` contain **mkdocstrings directives** — special YAML blocks embedded in Markdown that reference Python module paths. These are NOT regular Markdown and must NEVER be reformatted by Markdown linters, Prettier, or other automated tools.

### Critical rules for `docs/api/*.md` files

1. **NEVER escape underscores in `:::` directives.** The `:::` line is a Python dotted path, not Markdown prose. Writing `\_` instead of `_` will break the build.

   ```markdown
   <!-- WRONG — build will fail -->

   ::: fleet.sdtm.\_tdd_mixin

   <!-- CORRECT -->

   ::: fleet.sdtm.\_tdd_mixin
   ```

2. **NEVER replace underscores with asterisks in YAML option blocks.** Markdown formatters may interpret `_word_` as emphasis and "normalize" `_` to `*`. This silently breaks mkdocstrings options.

   ```yaml
   # WRONG — option is silently ignored
   show*root_heading: true
   filters: ["!^*"]

   # CORRECT
   show_root_heading: true
   filters: ["!^_"]
   ```

3. **After editing any `docs/api/*.md` file, always verify the build:**

   ```bash
   uv run mkdocs build --clean
   ```

   The build MUST complete with zero `ERROR` lines. Warnings about unclosed divs from pandoc are acceptable.

### Known corruption pattern

Markdown formatters (Prettier, markdownlint --fix, editor extensions) may auto-replace `_` with `*` inside mkdocstrings option blocks and escape `_` with `\_` in `:::` directives. If you see `show*root_heading`, `filters: ["!^*"]`, or `\_` in a `:::` line, fix them immediately — they are formatting corruption, not intentional content.

### Standard mkdocstrings block template

Every API doc entry should follow this pattern exactly:

```markdown
::: fleet.<module>.<ClassName>
options:
show*root_heading: true
heading_level: 3
filters: ["!^*"]
```

## 10. Validation & Verification Requirements

After **every new feature implementation or bug fix**, the following checks MUST all pass before the change is considered complete:

### Mandatory checks

1. **Tests** — The full test suite must pass:

   ```bash
   uv run pytest
   ```

2. **Linting & formatting** — Code must be clean:

   ```bash
   uv run ruff check
   uv run ruff format --check
   ```

3. **All example scripts** — Every `.py` file in `examples/` must run without error:
   ```bash
   uv run python examples/full_pipeline_example.py
   uv run python examples/cdiscpilot01_inline.py
   uv run python examples/cdiscpilot01_spec_driven.py
   uv run python examples/adnca_example.py
   uv run python examples/tdd_example.py
   ```
   If a new example script is added to `examples/`, it MUST be added to this list and to the §3 "Running Examples" section above.

### Conditional checks

4. **LLM context file** — If the change affects any **user-facing API** (new verbs, renamed parameters, changed signatures, new CLI commands), regenerate and verify `llms.txt`:

   ```bash
   uv run python scripts/build_llms.py
   uv run python scripts/build_llms.py --check
   ```

5. **GUIDE.md and STRUCTURE.md updates** — If the change involves a **major architectural or API change** (new namespace, new module, restructured directory layout, new top-level workflow concept), the relevant file(s) MUST be updated:
   - `GUIDE.md` — for workflow, usage patterns, or API surface changes.
   - `STRUCTURE.md` — for new modules, directories, or file additions/removals.

### Verification order

Run checks in this order: lint → tests → examples → llms.txt → docs build → docs review. Fix any failure before proceeding to the next step.
