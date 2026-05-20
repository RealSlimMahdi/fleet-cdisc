# Plan: Implement `.pin()` Pipeline Passport in Fleet

Add a `.pin(domain, df)` chainable verb to both SDTM and ADaM namespaces that attaches reference domains to the pipeline instance. Pinned domains propagate via `copy.copy()` (same mechanism as `_tdd_stage`, `_domain_meta`). Cross-domain verbs consume pins via `_require_pin()`. Pin usage is recorded in lineage and feeds the DAG with variable-granular cross-domain edges.

Use a new branch `feature/pin_pipeline_passport` for development. don't commit, don't push anything.

---

### The Key Question: "How Does `.pin("DM", dm_df)` Know the Join Key?"

**It doesn't guess. You tell it.**

```python
# Default: join on USUBJID (covers 95% of CDISC use cases)
.pin("DM", dm_df)

# Explicit: join on a different key
.pin("DM", dm_df, join_on="RSUBJID")       # AP domains
.pin("TV", tv_df, join_on=["ARMCD"])        # arm-specific visits
.pin("EX", ex_df, join_on=["USUBJID", "EXTRT"])  # compound key
```

The `join_on` is stored alongside the DataFrame in `_pinned`. Every downstream verb retrieves it via `self._pin_join_key("DM")` — no hidden resolution, no surprises. The user declares the relationship at pin time; verbs consume it transparently.

```python
def _normalize_key(join_on: str | list[str]) -> list[str]:
    return [join_on] if isinstance(join_on, str) else list(join_on)

def pin(self, domain: str, df: pl.DataFrame, *, join_on: str | list[str] = "USUBJID") -> Self:
    """Attach a reference domain to this pipeline.

    Args:
        domain: Logical name (e.g. "DM", "ADSL", "TV").
        df: The materialized reference DataFrame.
        join_on: Column(s) used to join this reference into the pipeline.
            Stored and reused by all downstream verbs that consume this pin.
    """
    new = copy.copy(self)
    key = domain.upper()
    if key in getattr(self, '_pinned', {}):
        warnings.warn(f"Pin '{key}' replaced. Use .repin() to suppress this warning.")
    new._pinned = {**getattr(self, '_pinned', {}), key: (df, _normalize_key(join_on))}
    return new

def repin(self, domain: str, df: pl.DataFrame, *, join_on: str | list[str] = "USUBJID") -> Self:
    """Replace an existing pin explicitly (no warning)."""
    new = copy.copy(self)
    new._pinned = {**getattr(self, '_pinned', {}), domain.upper(): (df, _normalize_key(join_on))}
    return new
```

**Duplicate-pin guard (Option C — warn + `.repin()` hybrid):**

- `.pin("DM", df)` followed by `.pin("DM", df2)` → emits `UserWarning`, but proceeds (REPL-friendly)
- `.repin("DM", df2)` → silent replacement, signals explicit intent (production code)
- Rationale: the warning acts as a lint signal without breaking the chain

When a verb needs the pin:

```python
def study_day(self, target, *, date_col, ref_col="RFSTDTC", ref_pin="DM", dm=None):
    if dm is not None:
        ref_df, join_key = dm, ["USUBJID"]  # explicit override
    else:
        ref_df, join_key = self._require_pin_with_key("DM", "study_day")
        # join_key comes from what the user declared in .pin()

    ref_slim = ref_df.select(join_key + [ref_col]).unique(subset=join_key)
    df = self._lazy.collect().join(ref_slim, on=join_key, how="left")
    # ... compute study day, drop ref_col ...
```

The user can always inspect what's pinned:

```python
ae_ns = raw_ae.sdtm.pin("DM", dm_df).pin("TV", tv_df, join_on="ARMCD")
ae_ns.pins()
# {'DM': (DataFrame[200 rows, 25 cols], join_on=['USUBJID']),
#  'TV': (DataFrame[12 rows, 6 cols],   join_on=['ARMCD'])}
```

---

### Steps

**Phase 1 — Core Infrastructure** (no cross-step dependencies)

1. **`PinMixin` class** — new file `src/fleet/core/_pin_mixin.py`
   - `.pin(domain, df, *, join_on="USUBJID") -> Self` — warns if domain already pinned
   - `.repin(domain, df, *, join_on="USUBJID") -> Self` — silent replacement (explicit intent)
   - `_require_pin(domain, verb, columns=None) -> pl.DataFrame` — retrieves pin or raises actionable `LookupError`
   - `_pin_join_key(domain) -> list[str]` — returns the stored join key
   - `_check_fk(col, *, pin, ref_col, severity) -> set` — FK validation
   - `_auto_fk_check(target) -> None` — dispatches FK check if target matches `_FK_RULES`
   - `.fk_policy(severity) -> Self` — set default FK strictness
   - `.pins() -> dict` — introspection method
   - `_FK_RULES: ClassVar[dict]` — empty in mixin, overridden per namespace

2. **`PinDependency` dataclass** — extend `src/fleet/core/dag.py`
   - Fields: `target_col`, `target_domain`, `verb`, `source_domain`, `source_cols`, `join_key`, `relationship`
   - Extend `VariableNode` with optional `pin_sources: list[PinDependency]`
   - Extend `PipelineDAG.to_dict()` to serialize pin dependencies

3. **Extend lineage** — modify `src/fleet/core/lineage.py`
   - `record_pin_lineage(owner, target_col, verb, source_domain, source_cols, join_key, relationship)`
   - Called from `_require_pin()` — automatic, zero verb-side effort
   - `pin_lineage_of(namespace) -> list[PinDependency]` public accessor

**Phase 2 — Namespace Integration** (_depends on Phase 1_)

4. **Wire into `SDTMNamespace`** — modify `src/fleet/sdtm/namespace.py`
   - Add `PinMixin` to inheritance chain
   - Init `_pinned = {}`, `_pin_lineage = []`
   - Define `_FK_RULES = {"USUBJID": {"pin":"DM"}, "VISITNUM": {"pin":"TV"}, ...}`
   - Wire `_auto_fk_check(target)` into `assign_no_ct()`, `assign_ct()`, `hardcode_ct()`

5. **Wire into ADaM** — modify `src/fleet/adam/_mixins.py`
   - Add `PinMixin` to `SharedADaMVerbsMixin` inheritance
   - Define `_FK_RULES = {"USUBJID": {"pin":"ADSL"}}`
   - Add `.join_adsl(*cols) -> Self` — pulls columns from pinned ADSL, records `carry_forward` lineage

**Phase 3 — Cross-Domain Verbs** (_depends on Phase 2_)

6. **SDTM `.study_day()`** — `src/fleet/sdtm/namespace.py`
   - Resolution: explicit `dm=` → pinned DM → ref_col already in frame → actionable error
   - Uses `_pin_join_key("DM")` for join — transparent, declared by user at `.pin()` time
   - CDISC algorithm: `diff + 1` when `diff >= 0`, else `diff` (no day 0)
   - Drops temp ref_col after computation

7. **SDTM `.baseline_flag()`** — `src/fleet/sdtm/namespace.py`
   - Groups by USUBJID + `--TESTCD` + optional extra vars
   - Last observation before ref date → flag = "Y"

8. **ADaM `.study_day()`** — `src/fleet/adam/_mixins.py`
   - Same algorithm, defaults to `ref_col="TRTSDT"`, `ref_pin="ADSL"`

**Phase 4 — DAG Integration** (_depends on Phase 3_)

9. **Merge pin lineage into DAG** — `src/fleet/core/dag.py`
   - `inject_lineage(dag, namespace, dataset_name)` — creates cross-domain edges from `_pin_lineage`
   - `PipelineDAG.trace(dataset, variable) -> list` — full provenance chain
   - Extend `impacted_by()` to follow pin-derived edges

10. **Completeness reporting** — `src/fleet/sdtm/namespace.py`
    - `.to_frame(report=True)` prints Req/Exp variable coverage when IG metadata is pinned/fetched

**Phase 5 — Tests & Verification** (_depends on Phase 4_)

11. **Tests** — 4 new test files:
    - `tests/unit/test_pin_mixin.py` — immutability, propagation, FK checks, `.pins()`, error messages
    - `tests/unit/test_pin_sdtm.py` — `.study_day()`, `.baseline_flag()`, FK auto-check on `assign_no_ct`
    - `tests/unit/test_pin_adam.py` — `.join_adsl()`, ADaM `.study_day()`, carry_forward lineage
    - `tests/unit/test_pin_lineage.py` — `PinDependency` recording, DAG edge creation, `trace()`

12. **Full validation** — pytest, ruff, all example scripts, `build_llms.py --check`

---

### Relevant Files

| File                             | Action | What                                                                                           |
| -------------------------------- | ------ | ---------------------------------------------------------------------------------------------- |
| `src/fleet/core/_pin_mixin.py`   | NEW    | PinMixin class, FK validation, `.pins()` introspection                                         |
| `src/fleet/core/dag.py`          | MODIFY | Add `PinDependency`, extend `VariableNode`, extend DAG exports                                 |
| `src/fleet/core/lineage.py`      | MODIFY | Add `record_pin_lineage()`, `pin_lineage_of()`                                                 |
| `src/fleet/sdtm/namespace.py`    | MODIFY | Inherit PinMixin, add `_FK_RULES`, add `study_day()`, `baseline_flag()`, wire `_auto_fk_check` |
| `src/fleet/adam/_mixins.py`      | MODIFY | Inherit PinMixin, add `_FK_RULES`, add `join_adsl()`, add `study_day()`                        |
| `tests/unit/test_pin_mixin.py`   | NEW    | Core mixin tests                                                                               |
| `tests/unit/test_pin_sdtm.py`    | NEW    | SDTM integration tests                                                                         |
| `tests/unit/test_pin_adam.py`    | NEW    | ADaM integration tests                                                                         |
| `tests/unit/test_pin_lineage.py` | NEW    | Lineage/DAG integration tests                                                                  |

---

### Verification

1. `uv run pytest tests/unit/test_pin_*.py` — all pin tests pass
2. `uv run pytest` — full suite passes (no regressions)
3. `uv run ruff check && uv run ruff format --check` — clean
4. All 7 example scripts execute without error
5. `uv run python scripts/build_llms.py --check` — if API surface changed
6. Manual: build a pipeline with `.pin("DM", dm_df).study_day(...)`, call `pin_lineage_of()`, confirm `PinDependency` appears with correct `source_domain="DM"`, `source_cols=["RFSTDTC"]`, `join_key=["USUBJID"]`

---

### Decisions

- **`join_on` is declared at `.pin()` time** — no hidden key inference. The user sees exactly how domains connect. Verbs read it via `_pin_join_key()`.
- **FK checks activate only when pin exists** — no pin = no check = no noise. Existing pipelines unaffected.
- **Every cross-domain verb accepts an explicit `dm=` / `adsl=` override** — pin is the convenient default, not the only path.
- **`_pin_lineage` is separate from `_lineage`** — `_lineage` tracks intra-frame Polars expressions. `_pin_lineage` tracks cross-domain dependencies. Merged at DAG build time.
- **Scope boundary:** This plan covers `.pin()`, FK validation, `.study_day()`, `.baseline_flag()`, `.join_adsl()`, lineage, and DAG integration. Follow-up work: `.epoch()`, `.clean_not_done()`, `.suggest()`, `.validate()` cross-domain rules, completeness dashboard.

---

### Further Considerations

1. **Deferred FK checks** — Inline FK checks call `.collect()`. For very large frames, consider a `fk_mode="deferred"` that batches checks at `.to_frame()` time. Start inline (simpler), optimize later.
2. **Pin from file path** — Future: `.pin("DM", path="outputs/dm.parquet")` auto-loads lazily. Not in v1 — pins are runtime DataFrames only.
