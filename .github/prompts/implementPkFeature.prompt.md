
---

## Plan: PK Namespace — `df.adam.pk` (revised)

**TL;DR:** Add `df.adam.pk` with 6 PK-specific verbs. `seq()` is **promoted** out of `OCCDSNamespace` into a new `MultiRowMixin` — both OCCDS and PK inherit it, zero duplication. `merge_adsl()` goes into `SharedADaMVerbsMixin` as a universal verb. Follows the mixin discipline already established in the codebase.

---

### Phase 1a — `merge_adsl()` in `SharedADaMVerbsMixin`

_File:_ \_mixins.py

```python
def merge_adsl(self, adsl: pl.DataFrame, *, by: list[str] = ["USUBJID"], keep_cols: list[str] | None = None) -> Self
```

Materializes, left-joins `adsl` (optionally subset to `keep_cols + by`), returns `_materialise_then()`.

---

### Phase 1b — New `MultiRowMixin` in `_mixins.py` _(depends on nothing)_

_File:_ \_mixins.py

Add `MultiRowMixin` with `seq()` — body moved verbatim from `OCCDSNamespace`.

**occds_namespace.py** is updated simultaneously:

- `class OCCDSNamespace(SharedADaMVerbsMixin, MultiRowMixin):` — `seq()` method body **deleted**
- `TestSeq` in test_occds_namespace.py still passes without changes (same API surface)

---

### Phase 2 — `PKNamespace` _(depends on 1a + 1b)_

_File:_ `src/fleet/adam/pk_namespace.py` (**NEW**)

```python
class PKNamespace(SharedADaMVerbsMixin, MultiRowMixin):
```

Gets for free: all 7 shared verbs, `merge_adsl()`, `seq()`.

6 PK-only verbs added here:

| Verb                                                                 | Key logic                              | Style         |
| -------------------------------------------------------------------- | -------------------------------------- | ------------- |
| `blq_flag(target, *, conc_col, lloq_col)`                            | `conc < lloq → "Y"`                    | lazy `_chain` |
| `blq_impute(target, *, conc_col, lloq_col, method="half_lloq")`      | 4 methods: half_lloq/zero/lloq/missing | lazy `_chain` |
| `nominal_time(target, *, from_col, input_unit="h", output_unit="h")` | unit scale from `PCTPTNUM`             | lazy `_chain` |
| `actual_time(target, *, sample_dtm, dose_dtm, unit="h")`             | `dt.total_seconds()` difference        | lazy `_chain` |
| `predose_flag(target, *, time_col, window_hrs=1.0)`                  | `-window ≤ time < 0 → "Y"`             | lazy `_chain` |
| `dose_normalized(target, *, conc_col, dose_col)`                     | `conc / dose`                          | lazy `_chain` |

---

### Phase 3 — Registration _(parallel with Phase 2)_

- namespace.py: add `@property def pk(self)` after the `occds` property
- **init**.py: add `PKNamespace`, `MultiRowMixin` imports + `__all__`

---

### Phase 4 — Synthetic Sample Data _(parallel)_

`datasets/cdiscpilot01/raw/pc_raw.csv` and `pp_raw.csv` — 3 subjects × 8 timepoints (0, 0.5, 1, 2, 4, 8, 12, 24h), modeled on pharmaverse/admiral ADPC vignette structure.

---

### Phase 5 — Tests

`tests/unit/test_pk_namespace.py` (**NEW**): `TestMergeAdsl`, `TestSeq`, `TestBlqFlag`, `TestBlqImpute`, `TestNominalTime`, `TestActualTime`, `TestPredoseFlag`, `TestDoseNormalized`

Also verify `tests/unit/test_occds_namespace.py::TestSeq` still passes (regression check for the extracted mixin).

---

**Relevant files:**

- \_mixins.py — `merge_adsl()` + new `MultiRowMixin`
- occds_namespace.py — updated inheritance, `seq()` removed
- `src/fleet/adam/pk_namespace.py` — 6 PK verbs, inherits `(SharedADaMVerbsMixin, MultiRowMixin)`
- namespace.py — add `pk` property
- **init**.py — exports

**Verification:**

1. `uv run pytest tests/unit/test_pk_namespace.py -v`
2. `uv run pytest` — full suite passes, especially `test_occds_namespace.py::TestSeq`
3. `uv run ruff check src/fleet/adam/`
