# Plan: Fleet v0.1.0 Release Readiness

**TL;DR**: The library is substantially complete and ready for v0.1.0. `pyproject.toml` and `_version.py` already declare `0.1.0`. No stubs, TODOs, or FIXMEs found. Two hard blockers to verify before tagging; everything else is polish.

---

## Steps

### Phase 1 — Verification (Blockers)

1. Run `pytest --cov` and confirm coverage targets are met:
   - sdtm/adam: ≥ 90%
   - define_xml/ct: ≥ 85%
   - overall: ≥ 85%
     If short, identify uncovered lines and add targeted tests.

2. Run both example scripts from a clean environment to confirm no regressions:
   - `uv run python examples/admiral_adsl_cdiscpilot01.py`
   - `uv run python examples/pipeline_cdiscpilot01.py`

3. Confirm a CI/CD release workflow exists (e.g., `.github/workflows/release.yml`) that tags and publishes to PyPI. If missing, create one.

### Phase 2 — Documentation Polish (Nice-to-Have)

4. Add a "Known Issues & Limitations" section to `docs/changelog.md` under `[0.1.0]`:
   - TA namespaces (onco, ophtha, peds, vaccine, metabolic, neuro) are less battle-tested than core sdtm/adam.
   - Validation module architecture is in place; external CDISC Rules Engine integration not bundled.
   - Complex multi-stage `from_spec()` workflows may need iteration.

5. Fill the empty `[Unreleased]` section in `docs/changelog.md` with a v0.2 roadmap (e.g., pharmaversepy adapter, Airflow orchestration, extended TA test coverage).

### Phase 3 — Release

6. Tag `v0.1.0` in git and trigger the publish workflow.
7. Verify the PyPI package installs correctly: `pip install fleet==0.1.0`.
8. Rebuild and deploy MkDocs docs site (`mkdocs gh-deploy` or CI equivalent).

---

## Relevant Files

- `pyproject.toml` — version declared as `0.1.0`, build system (hatchling), dependencies all set
- `src/fleet/_version.py` — `__version__ = "0.1.0"`, matches pyproject.toml
- `docs/changelog.md` — add Known Issues + Unreleased roadmap
- `examples/admiral_adsl_cdiscpilot01.py` — must run clean (end-to-end ADSL)
- `examples/pipeline_cdiscpilot01.py` — must run clean (spec-driven SDTM/ADaM/Define-XML)
- `tests/unit/` — 12 test files, 200+ tests; run coverage report
- `.github/workflows/` — verify or create release workflow

---

## Verification

1. `pytest --cov=src/fleet --cov-report=term-missing` — all targets pass
2. `uv run python examples/admiral_adsl_cdiscpilot01.py` — exits cleanly
3. `uv run python examples/pipeline_cdiscpilot01.py` — exits cleanly, outputs written to `outputs/cdiscpilot01/`
4. `pip install fleet==0.1.0` from a fresh venv — imports without error
5. MkDocs site builds without warnings: `mkdocs build --strict`

---

## Decisions

- **Scope**: v0.1.0 ships as-is; no new features.
- **Excluded**: pharmaversepy adapter, Airflow integration, advanced TA test expansion — deferred to v0.2.
- **Validation module**: Ships with partial functionality (architecture complete, external rules engine not bundled). Document in Known Issues.
- **XPT support**: Ships as optional `[io]` extra; Parquet is primary format for v0.1.

---

## Known Architectural Gaps (Acceptable for v0.1, Document Them)

- `ValidationService` requires external CDISC Rules Engine — not bundled.
- TA namespaces (onco, ophtha, peds, vaccine, metabolic, neuro): ~10-20 tests each vs. 60+ for core sdtm/adam.
- Complex `from_spec()` multi-stage specs may need iteration for advanced use cases.
