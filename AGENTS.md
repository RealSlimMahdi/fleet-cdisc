# Fleet — Agent Instructions

**Fleet** is a Python-based CDISC SDTM/ADaM derivation toolkit built on **Polars** DataFrame namespace extensions.

## Hard Rules

- **Package manager:** ALWAYS use `uv`. NEVER use `pip`, `poetry`, `conda`, `pipenv`.
- **Data manipulation:** NEVER use Pandas. ONLY use Polars. Maintain lazy evaluation (`pl.Expr` / `.to_frame()`).
- **Linter:** ONLY use Ruff. NEVER use black, flake8, or isort.

## Who you are talking to

A statistical programmer in the pharmaceutical industry: advanced in SAS and CDISC, intermediate in R, a beginner in Python and Polars. Clinical and SAS questions need less context; Python and architecture questions need more.

Write to him in ASD-STE100 Simplified Technical English: brief, plain words, one idea per sentence. Structure text with headings and lists and punctuate with commas and full stops: no emoji, no em dashes. When he asks for reasoning, give it step by step: the issue and its pitfalls, the strategy, the implementation, then the weaknesses.

Ask before deciding on architecture, on clinical logic (study design, SAP, IG version) or when a protocol element is missing; otherwise implement.

When a skill asks a question:

- One idea per question, with a concrete clinical-data example (an ADAE row, a USUBJID, a SAS procedure).
- For each option, one sentence on what goes wrong for a QC programmer if it is chosen.
- Mark each question **domain** (clinical or SAS knowledge decides; Mahdi answers) or **engineering** (you recommend; "ok" accepts and the ADR records the reason).
- At most five questions per round.
- Close every grilling with the list of decisions taken on his behalf.

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
uv run python examples/r2r_ae_example.py
```

## Verification Order

After every feature or fix: lint → tests → examples → `llms.txt` → docs build.

```bash
uv run ruff check && uv run ruff format --check
uv run blacken-docs --check --line-length 100 $(find docs -name '*.md')  # CI gate — run after ANY docs edit; drop --check to auto-fix
uv run pytest
uv run python examples/full_pipeline_example.py && uv run python examples/cdiscpilot01_inline.py && uv run python examples/cdiscpilot01_spec_driven.py && uv run python examples/adnca_example.py && uv run python examples/tdd_example.py && uv run python examples/r2r_ae_example.py
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

## Typed Entry (IDE Autocomplete)

`fleet.frame()` (`src/fleet/core/frames.py`) is the typed entry: wrap loads at IO boundaries and type checkers see `.sdtm`, `.adam`, `.tlg` (and `.to_frame()` stays typed downstream). There is deliberately no `polars-stubs` overlay — partial stubs shadow the real `pl.DataFrame` and break native method typing. Update `core/frames.py` when:

1. **New top-level namespace** added (e.g. `df.safety`) — add a `@property` to the `DataFrame`/`LazyFrame` declarations.
2. **Namespace class renamed or moved** — update the import path.

Do NOT update for new verbs or changed signatures — those are resolved from the real `.py` source.

## CLI Reference

See `.github/instructions/cli.instructions.md` for full CLI command reference.

## Editor tooling boundary

Fleet owns the Python protocol adapters (`src/fleet/lsp_server.py`, `src/fleet/mcp_server.py`) and the `fleet.introspect` contract they consume. The VS Code client is **not** in this repository — it lives in [`RealSlimMahdi/fleet-vscode`](https://github.com/RealSlimMahdi/fleet-vscode) and ships on its own cadence. Send TypeScript, packaging, and Marketplace changes there.

`fleet.introspect` is additive-only within a major version, because that client declares a minimum Fleet version and no ceiling.

## Agent skills

### Issue tracker

Issues live in GitHub Issues for `RealSlimMahdi/fleet-cdisc`, driven by the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

The five canonical triage roles, each label string equal to its name. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.
