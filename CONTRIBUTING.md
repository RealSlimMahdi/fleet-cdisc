# Contributing to Fleet

Thank you for your interest in Fleet! This guide explains our philosophy, API conventions, and the quality bar we expect from every contribution.

---

## Project Philosophy

Fleet is a **minimalistic, simple, yet powerful** CDISC SDTM/ADaM derivation toolkit built entirely on [Polars](https://pola.rs) DataFrame namespace extensions. Every design decision follows from four principles:

1. **Workflow quality first.** The workflow is the product: one obvious path from raw data to submission artefact. A step is chained inline or declared in `define.yaml` — same verb name, same argument names either way — and the two round-trip. Ambiguity is the defect: two verbs for the same derivation, or a failure that surfaces three steps late, forces the next reader to guess.
2. **Intent-driven syntax.** Code should read like a specification. A verb like `.baseline()` communicates clinical intent; ten lines of manual join logic do not.
3. **Lazy evaluation first.** Most verbs append a `pl.Expr` to one lazy plan, and Polars runs it at `.to_frame()`. Some verbs read data before the chain continues: checks (`baseline`, `date` to a DTC variable) and verbs that build or filter records (`whereclauses`, `pick`, `derive_*`, `nodup`). GUIDE.md lists them. A new verb stays lazy unless it cannot.
4. **Single import, batteries included.** `import fleet` registers all namespaces (`df.sdtm`, `df.adam`, `df.adam.adsl`, `df.adam.occds`, `df.adam.onco`, …). No sub-package juggling.

Principle 1 is why Fleet works well with AI coding agents — not the other way round. A codebase with a weak or ambiguous workflow gives an agent nothing to steer by, and it fails the same way a new human programmer does: plausible code, wrong derivation. A sharp workflow constrains the search space and points at the expected outcome, so the agent's chance of getting it right on the first pass goes up. We do not add features *for* AI. We invest in workflow clarity, and AI effectiveness follows.

If your contribution doesn't make the library simpler for the end user, reconsider whether it belongs.

---

## Setting Up

```bash
# Clone and install (uv is the ONLY supported package manager)
git clone https://github.com/RealSlimMahdi/fleet-cdisc.git
cd fleet-cdisc
uv sync --extra docs --extra all --extra dev

# Add project root to the Python path (makes specs/ importable for examples)
uv run python -c "import sysconfig; from pathlib import Path; (Path(sysconfig.get_path('purelib')) / 'fleet-dev.pth').write_text(str(Path.cwd()))"
```

> **Never** use `pip`, `poetry`, `conda`, or `pipenv`.

### Where the VS Code extension lives

This repository holds the Python side of the editor tooling — `fleet lsp --stdio` and the
`fleet.introspect` contract it consumes. The VS Code client is a separate project with its
own release cadence: [`RealSlimMahdi/fleet-vscode`](https://github.com/RealSlimMahdi/fleet-vscode).
Open TypeScript, packaging, and Marketplace pull requests there.

---

## API Shape & Conventions

### The Namespace Pipeline

Every Fleet derivation follows the same pattern:

```python
result = (
    raw_df.<namespace>
    .<verb>(target, *, keyword_args)
    .<verb>(...)
    .to_frame()
)
```

- **Namespaces:** `sdtm`, `adam`, `adam.adsl`, `adam.occds`, `adam.onco`, `adam.ophtha`, `adam.peds`, `adam.vaccine`, `adam.metabolic`, `adam.neuro`, `adam.pk`.
- **Verbs** are keyword-only after `target` to enforce explicit declarations.
- **Return type** is always `Self` — enabling chaining and IDE autocomplete on the concrete subclass.
- **Chaining infrastructure:** use `self._chain(*exprs)` to append expressions and `self._materialise_then(df)` when materialisation is required (e.g. filters, joins).

### No Code Duplication (Mixin Discipline)

If a verb is useful in **two or more** ADaM namespaces, it **must** live in a mixin in `src/fleet/adam/_mixins.py`. Never copy verb implementations across namespace classes.

| Scope            | Where it goes                                                         |
| ---------------- | --------------------------------------------------------------------- |
| 1 namespace only | Directly in that class                                                |
| 2+ namespaces    | Mixin in `_mixins.py`                                                 |
| All namespaces   | `SharedADaMVerbsMixin`                                                |
| Subset           | Focused mixin (e.g. `DateDerivationMixin`) with selective inheritance |

### Controlled Terminology

Always use generated codelist classes (`SEX`, `RACE`, …) — never raw NCI concept ID strings (`"C66731"`).

```python
# Correct
.assign("SEX", source="sex", ct=SEX)

# Wrong — raw concept ID
.assign("SEX", source="sex", ct="C66731")
```

### Polars Only

Fleet uses **Polars exclusively**. Never introduce Pandas as a dependency or use it in implementation code.

---

## Docstring Convention

All public functions and methods use **Google-style docstrings** with these sections (in order):

1. One-sentence summary (imperative mood)
2. Extended description (optional, 2–3 sentences)
3. `Args:`
4. `Returns:`
5. `Raises:` (only if non-obvious)
6. `Examples:` — at least one complete pipeline snippet ending with `.to_frame()`

```python
def verb_name(self, target: str, *, source: str) -> Self:
    """One-sentence summary of what the verb does.

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
                .assign("USUBJID", source="subject_id")
                .to_frame()
            )
    """
```

---

## Documentation (`docs/api/`) Rules

Files under `docs/api/` contain **mkdocstrings directives** — YAML blocks embedded in Markdown that reference Python dotted paths. They are **not** regular Markdown prose. A Markdown formatter can silently corrupt them.

**Three invariants:**

1. **Never escape underscores in `:::` directives.** `\_` breaks module resolution.
2. **Never replace `_` with `*` in YAML option blocks.** `show*root_heading` and `filters: ["!^*"]` are corrupted forms of `show_root_heading` and `filters: ["!^_"]`.
3. **Always verify the build** after touching any `docs/api/*.md` file:
   ```bash
   uv run mkdocs build --clean
   ```

---

## PR Checklist (Mandatory)

Every PR must pass **all** of these before review:

```bash
# 1. Lint & format
uv run ruff check
uv run ruff format --check

# 2. Full test suite
uv run pytest

# 3. All example scripts
uv run python examples/full_pipeline_example.py
uv run python examples/cdiscpilot01_inline.py
uv run python examples/cdiscpilot01_spec_driven.py
uv run python examples/adnca_example.py
uv run python examples/tdd_example.py
uv run python examples/r2r_ae_example.py

# 4. Docs build (if you touched docs/ or docstrings)
uv run mkdocs build --clean
```

**Conditional checks:**

- If you changed user-facing API (new verbs, renamed parameters, new CLI commands): regenerate `llms.txt` with `uv run python scripts/build_llms.py` and include the diff.
- If you made an architectural change (new namespace, new module, new directory): update `GUIDE.md` and/or `STRUCTURE.md`.

---

## What Makes a Good PR

- **Small and focused.** One feature, one bug fix, or one refactor per PR. Don't bundle unrelated changes.
- **Tests included.** New verbs need unit tests. Bug fixes need a regression test.
- **Docstrings included.** Every new public method needs a Google-style docstring with an `Examples:` section.
- **Example script updated.** If your change affects an end-to-end workflow, update or add to `examples/`.
- **Descriptive commit messages.** Explain _what_ changed and _why_, not _how_.

---

## What Will Get Your PR Rejected

- Introducing Pandas or any non-Polars DataFrame library.
- Duplicating verb logic across namespace classes instead of using a mixin.
- Using raw NCI concept ID strings instead of codelist classes.
- Missing tests for new functionality.
- Failing lint, tests, or example scripts.
- Bulk reformatting or refactoring of code you didn't change.
- Changes with no clear purpose or that add complexity without justification.

---

## AI-Assisted Contributions & Bot Policy

We welcome thoughtful contributions regardless of whether you used AI tools to help write them. What we don't welcome is low-quality, unreviewed AI-generated PRs submitted in bulk.

### Our expectations

1. **You must understand the change.** If a reviewer asks "why did you do X?", you must be able to explain the reasoning. "The AI suggested it" is not an answer.
2. **You must have run the full checklist locally.** Every item in the PR Checklist above must pass on your machine before you open the PR. We will know if you didn't.
3. **You must have read the relevant code.** PRs that modify functions the author clearly never read (wrong parameter names, misunderstanding of return types, ignoring existing patterns) will be closed without review.
4. **No hallucinated context.** Don't reference functions, parameters, or modules that don't exist. Don't claim tests pass if you haven't run them.
5. **No bulk drive-by PRs.** If your first contribution to Fleet is a 500-line PR touching 20 files, that's a red flag. Start small — fix a typo, add a test, improve a docstring.

### Signals that will get your PR closed immediately

- PR description is generic boilerplate that doesn't mention Fleet-specific concepts.
- The diff introduces patterns that contradict this file (Pandas usage, code duplication, missing docstrings).
- The author cannot respond to review feedback with substantive technical answers.
- The PR description is missing the two lines required by the "Pull requests" section of `AGENTS.md`.

### We value

- First-time contributors who start with a small, well-tested change.
- Issues opened _before_ PRs, so we can discuss the approach.
- Honest disclosure: "I used Copilot/Claude/GPT to help draft this, and I verified it by…" is perfectly fine and appreciated.

---

## Releasing (maintainers)

### How the version is set

- The version comes from the git tag, through `hatch-vcs`. Never edit a version string.
- Tag `v0.2.0a1` builds `0.2.0a1`. A commit after a tag builds a `.devN` version.
- Fleet is pre-alpha. Use PEP 440 pre-release tags: `vX.Y.ZaN`, then `bN`, then `rcN`.
- Users install a pre-release with `pip install --pre fleet-cdisc` or `uv add fleet-cdisc --prerelease=allow`.

### Release steps

1. Merge all release changes to `main`. CI must be green.
2. Add a `## [X.Y.ZaN]` section to `docs/changelog.md`, under `[Unreleased]`.
3. Check the build on your machine:

   ```bash
   uv build && uvx twine check --strict dist/*
   ```

4. Tag `main` and push the tag:

   ```bash
   git tag -a v0.2.0a1 -m "Fleet 0.2.0a1 (pre-alpha)"
   git push origin v0.2.0a1
   ```

5. If the `pypi` environment has required reviewers, approve the deployment in the GitHub Actions run.
6. Check the project page on pypi.org, then run `pip install --pre fleet-cdisc` in a clean environment.

A bad release cannot be replaced. PyPI refuses to take the same version number twice. Yank the bad version on pypi.org and tag the next number.

### What the publish workflow does

`.github/workflows/publish.yml` runs four jobs:

| Job        | When                   | What it does                                                         |
| ---------- | ---------------------- | -------------------------------------------------------------------- |
| `test`     | every run              | `ruff check`, `ruff format --check`, `pytest`                        |
| `build`    | after `test`           | `uv build`, `twine check --strict`, install the wheel and smoke-test |
| `testpypi` | push to `devel`        | upload to TestPyPI with the `TEST_PYPI_API_TOKEN` secret             |
| `pypi`     | push of a `v*` tag     | upload to PyPI with Trusted Publishing                               |

### Configuration outside this repository

- **pypi.org:** `fleet-cdisc` has a trusted publisher: owner `RealSlimMahdi`, repo `fleet-cdisc`, workflow `publish.yml`, environment `pypi`. There is no PyPI API token. If you rename the workflow file or the environment, update the trusted publisher too.
- **GitHub:** the repository has a `pypi` environment. The `pypi` job runs in it.
- **TestPyPI:** the `TEST_PYPI_API_TOKEN` repository secret holds the upload token.

### What goes into the package

- The wheel holds `src/fleet` only, with its JSON, YAML and XSD data files.
- The sdist holds `src/fleet`, `tests`, `README.md`, `LICENSE` and `pyproject.toml`. The include list is in `[tool.hatch.build.targets.sdist]`. Do not widen it.
- The README is the PyPI project page. Use absolute URLs for links and images. Relative links break on pypi.org.
- The Define-XML and ODM schemas in `src/fleet/define_xml/schemas/xsd/` come from `cdisc-org/data-definition-engine` under the MIT licence. Keep `LICENSE-CDISC` and `SOURCES.txt` next to them when you update the schemas.

### Release history

- `0.1.0`: first upload to PyPI, built before the version came from git tags. It is yanked.
- `v0.1.1`: a tag that was only on a local machine and never pushed. It was deleted.
- `0.2.0a1`: the first pre-alpha published from a tag.

---

## Getting Help

- **Issues:** Open an issue to discuss your idea before writing code. This prevents wasted effort.
- **Discussions:** Use GitHub Discussions for questions about Fleet's architecture or design decisions.
- **Docs:** Read [GUIDE.md](GUIDE.md) for workflow patterns and [STRUCTURE.md](STRUCTURE.md) for the codebase layout.

---

Thank you for helping make clinical programming better. We review every PR carefully and appreciate the effort that goes into a quality contribution.
