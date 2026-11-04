---
description: Fleet migration from Polars 1.x to Polars 2.0 — evidence from a real run, the breaking changes that touch Fleet, and the ordered plan
---

> **Status (2026-11-04): assessment complete, migration not started.**
> Evidence: `main` at `22aab6a`, test suite and the 8 examples run on Polars **2.1.0**
> (worktree, `uv pip install --no-deps "polars>=2" "polars-runtime-32>=2"` over the
> locked environment). Pin today: `polars>=1.41,<2` (`pyproject.toml`); lock 1.41.0
> (PR #204 moves it to 1.44.2). Source of the breaking changes:
> <https://docs.pola.rs/releases/upgrade/2/>. Read the guide again before you start:
> this memo lists only what touches Fleet.

# Polars 2.0 migration memo

## 1. Result

| Run on Polars 2.1.0 | Result |
|---|---|
| `pytest` | **21 failed**, 2887 passed |
| Examples | 7 of 8 pass; `cdiscpilot01_spec_driven.py` stops |
| Silent risk | row order of joins, `group_by` and `unique` under the new default engine |

Three causes explain all 21 failures. A fourth change (the streaming engine) gives no
failure today, but it can change results with no error. Treat it as the main risk.

## 2. The causes, with the Fleet sites

### 2.1 String to Date/Datetime/Time casts are removed (15 tests, 1 example)

Polars 2.0: `pl.col(s).cast(pl.Date)` on a `String` raises
`InvalidOperationError: casting from string to date is not supported`.
Polars 1.44 already warns ("Casting from String to Date is deprecated").

- 30 sites in `src/fleet` cast to `pl.Date`, `pl.Datetime` or `pl.Time`. Some cast a
  value that is already a date (harmless); the ones that receive text fail. Find them:
  `grep -rnE '\.cast\(pl\.(Date|Datetime|Time)' src/fleet`.
- Failing verbs: `on_treatment` (`adam/utils.py:109-111`), `onset_recovery`
  (`occds_namespace.py:180`), onco `filter_pd` and `confirmed_response_flag`
  (`onco_namespace.py:239, 292, 299`), peds `age_days` / `age_months` / `age_years`
  (`peds_namespace.py:82, 125, 168`), the duration of the spec-driven ADAE
  (`AENDT`, `_verb_mixin.py` duration path).
- **Fix:** do not write `str.to_date()` at each site. Read text through the shared
  `--DTC` reader of ADR-0011 (`fleet.core.dtc`, `to_day`), which keeps the date part
  of a timed value and never guesses. Note that `core/dtc.py:188` itself ends with
  `expr.cast(pl.Date)`: check that it receives a temporal type only. This also
  removes duplicate date logic (audit `c1-87`).

### 2.2 Joins and other operations no longer keep row order (3 tests)

Polars 2.0: `LazyFrame.collect()` defaults to the **streaming engine**. It does not
guarantee row order for joins, `group_by`, `unpivot` and similar operations.

- Failing: `test_null_join_keys::test_merge_pairs_a_null_key_with_a_null_key`,
  `test_spec_parity::test_sdtm_round_trip[merge]`,
  `test_run::TestRawPaths::test_raw_and_dataset_inputs_keep_the_raw_records`
  (rows come back as S2, S1 or NAUSEA, HEADACHE).
- Counts in `src/fleet`: 25 calls pass `maintain_order=` (joins, `group_by` and
  `unique` together); 33 `group_by`, 48 `unique`, 33 `collect`. Each needs a check.
- **Why it matters clinically:** several rules use input order as a tie-break, as
  SAS `FIRST.`/`LAST.` do: `flag(criteria="first"/"last")` (ADR-0013, ADR-0020),
  `seq`, `baseline_flag`. If a join before them reorders the rows, the flagged
  record or the sequence number changes, with no error.
- **Fix:** `maintain_order="left"` on every left/inner join whose order a later step
  reads; `maintain_order=True` on `group_by`/`unique` where the order is the output;
  an explicit `sort` where the order is a rule.

### 2.3 A zero-column frame keeps its height (3 tests)

Polars 2.0: `pl.DataFrame()` has height 0, and `with_columns(pl.lit(...))` on it adds
no row.

- Failing: `test_tdd_workflow` (`test_correct_sequence_succeeds`, `test_te_pipeline`,
  `test_ta_pipeline`): STUDYID and DOMAIN are lost.
- Cause: the trial-design chain starts from `pl.DataFrame()`;
  `study_header` adds STUDYID and DOMAIN as literals (`sdtm/_tdd_mixin.py:328`), and
  `_materialise_collection` (`_tdd_mixin.py:810`) reads them back from the data only
  when `current.height > 0`.
- **Fix:** keep the header values on the namespace (as `_tdd_stage` is kept), not in
  the rows of an empty frame. Do not change the documented entry
  `pl.DataFrame().sdtm.fetch_structure(...)`.

### 2.4 Other 2.0 changes: checked

| Change | Fleet | Action |
|---|---|---|
| `is_in` no longer coerces lossily | 24 `is_in` calls; 1.44 warns once ("`is_in` with a collection of the same datatype is ambiguous") | Pass `.implode()` or a matching dtype; check each call that compares a date with text or an int with a float |
| `explode()` gives no row for an empty list | 1 call; 1.44 warns ("`empty_as_null` will change") | Decide the row count, then pass `empty_as_null=` explicitly |
| `read_csv` goes through `scan_csv`: a `schema_overrides` list must cover every column, `columns=[...]` keeps the requested order | 7 `read_csv`/`scan_csv` calls | Read each call; the raw CSV readers of package F are the main ones |
| `concat(how="horizontal")` no longer pads, `pl.datetime`/`pl.repeat` output names, `join_nulls`, `how="outer"`, `replace(default=)`, `with_row_count`, `melt`, `str.concat`, `cut`/`qcut`, `shift(None)`, `profile()` | 0 uses in `src/fleet` | None |
| Window `order_by` with several keys ignores `nulls_last` | Polars 1.41 and 1.44 have this bug; 2.1.0 does not | `flag` works around it (PR #205); keep the workaround while 1.x is supported |
| The parse allow-list of expression strings (`sdtm/utils.py`, `_PL_NAMES`, PR #203) is built from `dir(pl.Expr)` | Removed 2.0 methods leave the list by themselves | Add any new 2.0 constructor that docs use to `_PL_NAMES` |

## 3. Decisions to take first

1. **Engine (engineering).** Option A: keep the in-memory engine
   (`pl.Config.set_engine_affinity("in-memory")` at import, or `engine="in-memory"`
   on each `collect`). What goes wrong for QC: none at first, but Fleet then depends on
   an engine Polars no longer tunes, and a user setting can override it. Option B:
   the streaming engine plus an explicit order at every step that needs one. What goes
   wrong for QC: one missed `maintain_order` gives a different ANL01FL or AESEQ with no
   error. Recommendation: B, with a CI leg that runs the suite on both engines and
   compares the outputs of the examples.
2. **Support window (engineering).** Support both `>=1.44,<3` during the change, or
   jump to `>=2,<3`. Recommendation: both, until one release has passed on 2.x; every
   fix in section 2 works on 1.44.

## 4. Order of work

1. Fix 2.3 (TDD header) and 2.1 (date reads through `fleet.core.dtc`). Both work on
   1.x, so they can merge before the pin moves.
2. Add `maintain_order` / `sort` per 2.2. Add a test that shuffles the input
   (`tests/helpers.py`, `shuffle_rows`) before each order-sensitive verb.
3. Answer the `is_in`, `explode` and `read_csv` rows of 2.4 call by call.
4. Add a CI job "polars-2": `uv pip install --no-deps "polars>=2" "polars-runtime-32>=2"`
   after `uv sync --locked`, then `pytest` and the examples. Make it required once green.
5. Raise the pin, `uv lock --upgrade-package polars --upgrade-package polars-runtime-32`,
   changelog entry, and a line in `docs/getting-started/installation.md`.
6. Run `scripts/admiral_oracle.py` and the golden TLG tests on the new lock; compare the
   example outputs (`outputs/`) with `fleet compare`.

## 5. Verification

The full order of `AGENTS.md`, on Polars 1.44 **and** 2.x: ruff, blacken-docs,
`build_llms.py --check`, `gen_cli_docs.py --check`, `pytest`, the 8 examples,
`mkdocs build --strict`. Then the fresh-install job (`fresh-install.yml`, PR #204),
because a user without the lock gets the newest allowed Polars.

## 6. How to reproduce the evidence

```bash
git worktree add --detach /tmp/fleet-pl2 origin/main
export UV_PROJECT_ENVIRONMENT=/tmp/fleet-pl2-venv
uv --directory /tmp/fleet-pl2 sync --locked --extra dev --extra all
uv pip install -p /tmp/fleet-pl2-venv/bin/python --no-deps "polars>=2" "polars-runtime-32>=2"
cd /tmp/fleet-pl2 && /tmp/fleet-pl2-venv/bin/python -m pytest -q -o pythonpath="src:." -rf
```
