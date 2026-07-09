> **Status (2026-07): implemented and promoted to `.github/instructions/tests.instructions.md`.**

## Plan: Replace factories & CSV fixtures with `pl.from_repr()`

**TL;DR:** Replace the `tests/factories.py` module and CSV-backed session fixtures with inline `pl.from_repr()` tables directly in tests. Each test becomes self-documenting — no chasing external files or factory parameters. Keep only a tiny `shuffle_rows()` helper.

---

**Phase 1 — Convert conftest.py fixtures to `from_repr`**

1. Replace `simple_raw`, `simple_vs`, `dm_raw`, `vs_raw`, `ae_raw`, `adrs_frame`, `adis_frame` fixture bodies with equivalent `pl.from_repr(...)` tables
2. Remove the factory import block and all factory-based fixtures (`messy_dm`, `messy_vs`, `messy_ae`, `adsl_with_null_dates`, `merge_mismatch_frames`)

**Phase 2 — Update test files that used factories**

- `tests/unit/test_sdtm_namespace.py` — replace `build_dm_cohort` with inline `from_repr`
- `tests/unit/test_adam_namespace.py` — replace `shuffle_rows` import
- `tests/unit/test_nodup.py` — replace `build_ae_cohort` with inline `from_repr`
- `tests/unit/test_robustness.py` — replace factory calls with inline tables

**Phase 3 — Minimal helpers file**

- Create `tests/helpers.py` with just `shuffle_rows(df, seed=42)` (~3 lines)
- Update imports in the 3 files that need it

**Phase 4 — Delete dead code**

- Delete `tests/factories.py`
- Delete `tests/fixtures/raw/dm_raw.csv`
- Delete `tests/fixtures/raw/vs_raw.csv`
- Delete `tests/fixtures/raw/ae_raw.csv`
- Delete `tests/fixtures/raw/` directory

**Phase 5 — Verification**

1. `uv run pytest` — all 1037+ tests pass
2. `uv run ruff check && uv run ruff format --check`
3. Example scripts still pass (they read from `datasets/`, unaffected)

---

**Decisions**

- `datasets/cdiscpilot01/raw/` stays — used by example scripts, separate concern
- `tests/fixtures/ct/` and `tests/fixtures/specs/` stay — YAML specs, not data
- `shuffle_rows` stays as a helper (no `from_repr` alternative for randomization)
- No factory-style parameterization — each test owns its visible data inline

**Relevant files**

- /Users/aboutm/Code/Python/Fleet/tests/conftest.py — central fixture entry point
- /Users/aboutm/Code/Python/Fleet/tests/factories.py — to be deleted
- /Users/aboutm/Code/Python/Fleet/tests/assertions.py — keep as-is (still useful)
- /Users/aboutm/Code/Python/Fleet/tests/fixtures/raw/dm_raw.csv — to be deleted
- /Users/aboutm/Code/Python/Fleet/tests/fixtures/raw/vs_raw.csv — to be deleted
- /Users/aboutm/Code/Python/Fleet/tests/fixtures/raw/ae_raw.csv — to be deleted
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_sdtm_namespace.py — update factory imports
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_adam_namespace.py — update factory imports
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_nodup.py — update factory imports
- /Users/aboutm/Code/Python/Fleet/tests/unit/test_robustness.py — update factory imports

**Verification**

1. For each phase, run only the touched test cluster first so failures stay attributable.
2. After each cluster is stable, run the full Fleet test suite with `uv run pytest`.
3. Run `uv run ruff check && uv run ruff format --check` to ensure lint cleanliness.
4. Run example scripts to confirm they are unaffected.
