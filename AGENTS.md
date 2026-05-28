# Fleet — Agent Instructions

**Fleet** is a Python-based CDISC SDTM/ADaM derivation toolkit built on **Polars** DataFrame namespace extensions.

## Hard Rules

- **Package manager:** ALWAYS use `uv`. NEVER use `pip`, `poetry`, `conda`, `pipenv`.
- **Data manipulation:** NEVER use Pandas. ONLY use Polars. Maintain lazy evaluation (`pl.Expr` / `.to_frame()`).
- **Linter:** ONLY use Ruff. NEVER use black, flake8, or isort.

## Verified Commands

```bash
# Install
uv sync --extra docs --extra all --extra dev

# Test
uv run pytest

# Lint & format
uv run ruff check
uv run ruff format

# Examples (ALL must pass after any change)
uv run python examples/full_pipeline_example.py
uv run python examples/cdiscpilot01_inline.py
uv run python examples/cdiscpilot01_spec_driven.py
uv run python examples/adnca_example.py
uv run python examples/tdd_example.py
```

## Verification Order

After every feature or fix: lint → tests → examples → `llms.txt` → docs build.

```bash
uv run ruff check && uv run ruff format --check
uv run pytest
uv run python examples/full_pipeline_example.py && uv run python examples/cdiscpilot01_inline.py && uv run python examples/cdiscpilot01_spec_driven.py && uv run python examples/adnca_example.py && uv run python examples/tdd_example.py
```

If user-facing API changed (new verbs, signatures, CLI commands):

```bash
uv run python scripts/build_llms.py
uv run python scripts/build_llms.py --check
```

## Data Samples

Prefer `pl.from_repr()` over `pl.DataFrame({...})` for inline sample data:

```python
raw_dm = pl.from_repr("""\
┌────────────┬─────┬─────┐
│ subject_id ┆ sex ┆ age │
│ ---        ┆ --- ┆ --- │
│ str        ┆ str ┆ i64 │
╞════════════╪═════╪═════╡
│ S001       ┆ M   ┆ 35  │
│ S002       ┆ F   ┆ 42  │
└────────────┴─────┴─────┘
""")
```

Exception: empty DataFrames for TDD scaffolding, programmatic/random data.

## Publishing

Distribution name: `fleet-cdisc` (import: `fleet`). Version comes from git tags — never edit version strings manually.

## Polars Stubs (Pylance Autocomplete)

`src/polars-stubs/dataframe/frame.pyi` declares `.sdtm`, `.adam`, `.tlg` properties on `pl.DataFrame` so Pylance can offer code completion. Update this file when:

1. **New top-level namespace** added (e.g. `df.safety`) — add a `@property` entry.
2. **Namespace class renamed or moved** — update the import path.

Do NOT update for new verbs or changed signatures — those are resolved from the real `.py` source.

## CLI Reference

See `.github/instructions/cli.instructions.md` for full CLI command reference.
