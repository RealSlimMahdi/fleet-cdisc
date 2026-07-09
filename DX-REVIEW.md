# Fleet DX Review — What's Suboptimal, What's Next

> Consolidated audit of Fleet's developer experience for the statistical programmer:
> verb API, core engine, CLI, TLG engine, YAML schemas (TLG + define.yaml), the dual
> inline/spec path, typing/IDE support, and the interactive-vs-batch TLG question.
> Findings marked **[verified live]** were reproduced by executing code against the
> current checkout (commit `d3a96ae`). Related: the typing gap filed upstream as
> [pola-rs/polars#27795](https://github.com/pola-rs/polars/issues/27795) and the IDE
> tooling plan in `.github/prompts/plan-fleetIdeTooling.prompt.md`.

---

## 0. Executive summary

Fleet's compute core is genuinely strong: honest denominator semantics in the ARD
engine, immutable builder chains, a real golden-test backbone, exemplary error
messages in a few places (`_require_pin`), and a spec dispatcher that works for happy
paths. The DX problems cluster into five root causes:

1. **Silent degradation is the house failure mode.** A dozen verified paths produce
   *wrong or empty output with no warning* — the worst possible behavior for a GxP
   audience. (§1)
2. **Verb knowledge is duplicated in ~6 places** (namespace method, algorithm enum,
   `from_spec` elif ladder, Pydantic field bag, JSON schema, docs) and four of the six
   already disagree today. One generated registry mechanically fixes most of §4. (§4.1)
3. **Docs/examples diverge from runtime behavior** in load-bearing places — the
   flagship YAML example in the docs is unexecutable, the GUIDE teaches unnecessary
   chain breaks, docstring examples throw. (§6)
4. **The entry points are hostile**: `df.sdtm` is invisible to type checkers (49
   `# type: ignore` in Fleet's own examples), the CLI can scaffold but not *execute*,
   and errors surface as raw tracebacks/polars plans with no verb attribution. (§2, §3, §5)
5. **The last mile of TLG is missing**: the renderer drops continuous stats, there is
   no RTF, no pagination, no decimal control — the four things a submission table
   needs. (§3)

Priority order (detail in §8): **P0 correctness → P1 single registry + errors + CLI
execution → P2 naming/typing (one breaking release before 1.0) → P3 TLG submission
readiness → P4 interactive explorer + round-trip → P5 LSP/MCP/IDE tooling.**

> ⚠️ **PHUSE papers note:** several claims currently in docs are not repo-true and
> must not appear in the papers: "nothing executes until `.to_frame()`" (false for
> ~half the verbs), "every TLG creatable inline AND via spec" (tables only), CDISC ARS
> support (module was removed), "editor validation via JSON schema" (schema is stale).

---

## 1. Correctness first — silent-wrong-answer bugs (P0)

These precede any DX work because they make correct-looking output wrong.

| # | Bug | Evidence |
|---|-----|----------|
| C1 | **Renderer silently drops all continuous statistics** — a VS/LB/EG/DM ARD with n/mean/sd/median/min/max renders cells containing only `n`. 9 of 21 registered templates produce confidently formatted, statistically empty tables. **[verified live]** | `src/fleet/tlg/render/_models.py:326-339` |
| C2 | `target_cols` is a **no-op** in both `sdtm.merge` (`with_columns` instead of `select`) and `adam.lookup` (writes to dead `_pipeline` attr). Users believe they restricted a join. **[verified live]** | `sdtm/namespace.py:1155`, `adam/namespace.py:153` |
| C3 | `nrind()` classifies **null values / null limits as "NORMAL"** — statistical error feeding shift tables. | `adam/utils.py:71-81` |
| C4 | `assign_ct` with typo'd/unloaded codelist **silently passes values through unvalidated** (two bare `except Exception: pass`). Same in `hardcode_ct`. **[verified live]** | `sdtm/namespace.py:214-240, 585` |
| C5 | `assign_ct` in no-mapping mode applies `replace(decode_map)` that can rewrite valid submission values ("M") into NCI preferred terms ("Male"), contradicting its docstring. | `sdtm/namespace.py:221-225` |
| C6 | Spec models are **typo-tolerant flat bags** (`extra="allow"`, all fields optional): `recod_map` typo → column of nulls, zero warnings. Docs claim a `ValidationError` that is fabricated. **[verified live]** | `adam/models.py:132`, `sdtm/models.py:98` |
| C7 | `from_spec` **silently overwrites already-derived columns** — the flagship spec example double-derives TRTSDT (inline `first_date` then spec `RFSTDTC` copy); spec wins, define.yaml documents a different derivation than executed. **[verified live]** | `examples/cdiscpilot01_spec_driven.py:211,234` |
| C8 | Percentages are **rounded to 1dp inside the ARD `stat` column** — precision unrecoverable, breaks the {cards} stat/format separation and QC vs SAS. | `tlg/_ard.py:490,673` |
| C9 | CLI `tlg export` auto-detects arm against **ADSL** columns (`TRTA` never there) → silently picks `TRT01P`, groups wrong or crashes; no `--groupby` override. | `cli.py:918` |
| C10 | `baseline()` silently takes `max()` across duplicate baseline-flagged records (admiral errors). | `adam/utils.py:26-47` |
| C11 | `duration(out="iso8601")` **silently ignored** when target ends in "DY" (suffix magic early-returns). **[verified live]** | `core/_verb_mixin.py:581-589` |
| C12 | `pick()` events ignore unknown dict keys — `"orderby"` typo silently defaults ordering, wrong record picked. **[verified live]** | `adam/_mixins.py:1084-1090` |
| C13 | Spec-driven example's `DatasetChecker` prints `[FAIL]` (9 errors) then generates Define-XML and **exits 0**; `raise_on_errors()` exists unused. **[verified live]** | `examples/cdiscpilot01_spec_driven.py:350` |
| C14 | Unknown `algorithm:` in a spec → `warnings.warn` and **skip the variable** — dataset ships missing a column. | `sdtm/namespace.py:1431`, `adam/namespace.py:1202` |
| C15 | Define-XML: `MethodOID` emitted on `ItemDef` (2.1 puts it on `ItemRef`); `def:leaf` hrefs hardcoded `.xpt` while pipeline writes parquet; no ValueListDef/WhereClauseDef (the core of a BDS define). | `define_xml/spec_generator.py:403,467` |

**Implementation plan — "no silent fallbacks" pass**
- One PR series, one theme: every degraded path either raises or warns with context.
- C1: emit one display row per statistic under each stub (universal pharma layout); golden HTML tests for vst01/lbt01. C2: `select` with `on+target_cols`, delete `_pipeline`. C3: guard nulls → null NRIND. C4/C5: warn on CT pass-through, validate-and-pass in no-mapping mode. C6: see §4.1 (discriminated unions). C7: `from_spec` errors on overwrite unless `overwrite=True`/`omit=`. C8: store unrounded stat, move 1dp into `fmt_fn`. C9: `--groupby` flag + detect against data frame. C10: `strict=True` default raising on >1 flagged row. C11: never ignore explicit kwargs — raise. C12: reject unknown event keys. C13: end example with `raise_on_errors()`, fix ADVS spec/pipeline mismatch. C14: `strict=True` default in `from_spec`. C15: fix element placement, derive href from export format.
- Size: ~2 weeks. Each fix ships with the regression test that would have caught it.

---

## 2. Verb API & core engine

### 2.1 Naming chaos (one breaking-change budget, spend it before 1.0)

- **Three names for "input column"**: `assign_no_ct(source=)`, `adam.source(from_col=)`, `adam.rename(source=)` — the last two are the *same implementation*. (`sdtm/namespace.py:80`, `adam/_mixins.py:799,892`)
- **Five names for "group by"**: `groups=`, `by=`, `by_vars=`, `group_cols=`, `group_by=` — the most-typed kwarg in BDS programming. Plus TLG adds `by()`/`groupby=`/`group_col=`/`columns:` for the same concept.
- **Duplicated conditional verbs**: `if_then_else(when=)` (SDTM) vs `condderivation(conditions=)` (ADaM) — near-identical bodies maintained twice. (`sdtm/namespace.py:938`, `adam/_mixins.py:914`)
- **Literal-assignment triplication**: `hardcode_no_ct` / `dataset_level` / `assigned`.
- **Four join verbs, four shapes**: `merge(on=)`, `lookup(on=)`, `merge_adsl(by=)`, `join_adsl(*cols)`; column restriction spelled `target_cols`/`keep_cols`/positional.
- `study_day` overridden 3× with 3 escape-hatch kwargs (`ref_df=`/`dm=`/`adsl=`); SDTM `date()` has `format=`, ADaM's doesn't; `seq()` target optional in ADaM, required in SDTM; `_ct`/`_no_ct` suffix pairs double the SDTM surface (`assign_ct(ct_codelist=None)` already covers both).

**Implementation plan — naming unification**
- Canonical set: `assign(target, source=…, value=…, ct=…, ct_map=…)`, `case_when(target, when=[…], else_=…)`, `merge(dataset, on=, keep=, where=)`, `by=` everywhere for grouping, `where=` for pre-filters, `ref_df=` for reference frames.
- Mechanics: add canonical verbs to `SharedVerbsMixin` (single implementation); old names become thin deprecated aliases via a `@deprecated_alias("groups", "by")` decorator emitting `FutureWarning` once per session; remove in 1.0.
- Migration aid: `fleet migrate <file.py>` (libcst rename pass) — cheap and makes the break painless.
- Size: ~1 week + docs regeneration. Do **after** §4.1 so the spec registry names are born canonical.

### 2.2 Error experience

- **Column typos surface only at `to_frame()`** as raw polars errors with zero verb attribution — in a 30-verb chain nothing says which verb/variable broke. Fleet already has the lineage to say `assign_no_ct('USUBJID', source='patient_numbr') at step 3: column not found; did you mean 'patient_number'?`. **[verified live]** (`core/_verb_mixin.py:84-91`)
- `flag(criteria="frist")` falls through to expression parsing → blames a nonexistent *column* when the user typo'd a *keyword*; no did-you-mean anywhere in `src/fleet` (grep-verified). (`adam/_mixins.py:221-286`)
- **The exception hierarchy is dead code**: `FleetError/SDTMError/ADAMError` defined, but verbs raise builtin `ValueError`/`TypeError`/`LookupError` (~42 sites); `except FleetError` catches nothing.
- `parse_expression` asymmetry: bare `"VSSTRESN"` works, `"AVAL * 2"` → `NameError`-flavored message that never suggests `pl.col()`. **[verified live]** (`sdtm/utils.py:170-190`)
- 15 `print()` call sites in the verb layer (`inspect`, `trail`, `nodup`, `validate`) — batch runs can't route/capture/suppress; `nodup`'s audit findings can't reach a log file.

**Implementation plan — error experience**
1. In `_chain()`, validate `expr.meta.root_names()` against `collect_schema().names()` (cheap, no data read); raise `DerivationError(FleetError, ValueError)` naming verb, target, and `difflib.get_close_matches` suggestion. (~60 LOC + tests)
2. Wrap `to_frame()`'s collect; translate polars errors through `_lineage` as fallback.
3. Re-parent existing raises onto dual-inheritance Fleet exceptions (`class DerivationError(FleetError, ValueError)`) so both catch styles work. Mechanical, ~1 day.
4. Bare-identifier-not-in-schema in `flag`/`parse_expression` → check distance to keyword set, report both interpretations; resolve bare `ast.Name`s to `pl.col(name)` so `"AVAL * 2"` works (the SAS-friendly option).
5. `logging.getLogger("fleet")` replaces `print`; `nodup` returns its report frame.
6. `validate()` gets `on_fail="raise"|"warn"|"ignore"` and returns an accessible result.

### 2.3 Laziness & performance

- **The "nothing executes until `.to_frame()`" claim is false for ~half the verb surface** — ~25 verbs eagerly `collect()` mid-chain (`duration`, `study_day`, `select`, `nodup`, `date` DTC+time, `merge`, `group_by`, `pick`, all `derive_*`, all sub-namespace properties, …). A DM→AE pipeline materializes 3-4×. (`core/_verb_mixin.py:521,683,936,1068`, …)
- **No LazyFrame namespace** — `pl.scan_parquet(...).sdtm` doesn't exist, so predicate pushdown is impossible for exactly the users (large LB/PC) who need it.
- **Pinning makes every assign quadratic-ish**: `_auto_fk_check` collects the whole accumulated pipeline on each assign verb when a pin exists. (`core/_pin_mixin.py:268`)
- Python-loop hot paths: `_flag_ranked` (per-row list comp), `_flag_temporal_exists` (`iter_rows` + filter per row, O(rows×source)), `ae_aerel` (`map_elements`). 50-500× slower than expression equivalents.
- **Sub-namespace switch discards pins/lineage/NSV state**: `.pin("ADSL", adsl).occds` → `_pinned == {}` then a confusing `LookupError` later. **[verified live]** (`adam/namespace.py:1256-1320`)

**Implementation plan — lazy/perf pass**
1. Register `pl.api.register_lazyframe_namespace` for the same classes (they already hold `_lazy`; constructors accept both). (~1 day)
2. Propagate `_pinned`/`_lineage`/`_domain` into sub-namespace constructors; hand over the LazyFrame, not `to_frame()`.
3. Defer FK checks to `to_frame()` (batch once) or cache the collected key column.
4. Vectorize the four hot paths (`int_range().over()` ranks, window any, `join_asof`, `str.replace` mapping).
5. Make lazily-implementable verbs lazy (`duration` numeric path, `study_day` lazy join, `seq` pure window).
6. Correct GUIDE + add `.explain()` note showing checkpoint count. Honest docs even before the code improves.

### 2.4 Ergonomics & discoverability

- Carry-through needs one `.source()` line per column — 13 consecutive calls in the flagship example. Fix: variadic `source("STUDYID", "USUBJID", …)` or `keep([...])`.
- `flag()` is a 15-parameter god-verb, stringly-dispatched, irrelevant params silently ignored. Fix: validate the parameters injected in the function depending on the intent (what the user tries to derive), or more elegant equivalent.
- **No programmatic verb listing** (`dir()` returns mixin internals); published verb counts contradict each other (`__init__.py` says 14/16/6/5, GUIDE says 14/22/8/5). Fix: per-class verb registry powering `df.sdtm.verbs()` and doc generation — reuse the TLG registry pattern.
- `from_spec` god-dispatchers duplicated across SDTM/ADaM (~15 and ~20 elif branches + duplicated `_extract_define_variables`). Fix: single table-driven dispatcher in the shared mixin — subsumed by §4.1.
- `Literal[...]` types for enum-like params (`criteria`, `impute`, `out`, `how`, `report`) — cheap, directly improves autocomplete. `@overload` for `derivation()`'s dual-mode first arg.

---

## 3. TLG engine

### 3.1 Dual API is table-only, and the YAML path is not a workflow

- **Listings unreachable from the fluent builder** (`template("ael01")` raises); parity tests filter to `OutputType.TABLE`, institutionalizing the gap. (`tlg/_builder.py:153`, `test_tlg_parity.py:60`)
- **A YAML file alone cannot reproduce a table**: no template id, no method, no schema version in the YAML; `from_yaml` must be called on the *correct* spec class; no `fleet.tlg.load_spec()`, no CLI `--spec`; zero example `.yaml` TLG files in the repo. (`tlg/_specs.py:300-347`)
- `t_relationship` exists but is **absent from the registry** — unreachable inline, invisible in `catalog()`, no golden. (`tlg/ae_namespace.py:338`)
- **Registry closed to users**: `TEMPLATES` is a hardcoded dict; custom templates require editing Fleet source — no `register_template()`. Every sponsor has shells Fleet doesn't ship. (`tlg/_registry.py:91-345`)
- Builder verbs silently ignored when the target template doesn't consume them (verified: `rows()` ignored by `t_abnormal`); sibling templates have inconsistent contracts (`t_shift` drops `header_rows`, `t_abnormal` raises). **[verified live]**
- `columns: list[str]` is a lie — only `columns[0]` is ever read; `columns: [TRTA, SEX]` silently discards SEX.
- `aet01` titled "Overview of Adverse Events" actually produces a SOC→PT table (duplicate of `aet02`); a real AET01 overview isn't canned.
- No `schema_version` on specs; docs claim JSON-schema exports that don't exist (`grep model_json_schema` → nothing); filter strings validate lazily and explode later without naming the field.
- Continuous stats hardwired to a column literally named `AVAL` (and `USUBJID`); summarizing `CHG`/`PCHG`/`BASE` requires pre-renaming; absent `AVAL` yields **null stats, not an error**.
- Nested hierarchies cap at 2 levels — SOC→PT→grade shells impossible ({cards} supports N levels).
- `Row.label` and `Column.format` are dead fields — consumed nowhere; tables ship `PARAMCD` codes in the stub with no `label_col` mapping.
- ARD `stat` is Float64-only; non-numeric stats **silently nulled**; `validate_ard` rejects extra columns, blocking the standard {cards} post-processing workflow.
- Goldens stored as CSV flatten null↔"" — a semantically load-bearing distinction here. Fix: Parquet goldens.
- `df.tlg.check()` claims "all sub-namespaces", checks only AE. Root `df.tlg` exposes no `catalog()`. Docs cover 2 of 9 namespaces.

### 3.2 Missing submission essentials

- **No RTF** — the de facto submission/QC format; PPTX shipped before RTF.
- **No pagination anywhere**: `page_by` is documented "(future use)" and never read; no "Page X of Y", no repeated titles; PPTX puts a 300-row table on one slide.
- **No decimal-precision control**: formats come solely from `_DEFAULT_FMT`; "one more decimal than collected" is unimplementable without ARD surgery.
- **No inferential statistics** (no p-values/CIs/model hooks) and **zero graphs** despite the G in TLG. Near-term: document the boundary honestly; medium-term: pluggable `Statistic` hook for scipy/statsmodels.

**Implementation plan — TLG completeness**
1. **Renderer fix (C1)** first: one display row per stat, `stat_label` as row label; golden HTML per continuous template. (~3 days)
2. **YAML-as-workflow**: add `template: lbt02` + `schema_version: 1` to specs; `fleet.tlg.load_spec(path)` dispatching through the registry; `fleet tlg run <specs-dir>` and `fleet tlg list` (drive choices from `catalog()`). Ship example spec YAMLs. (~4 days)
3. **Open registry**: `fleet.tlg.register_template(meta, fn)` where `fn(df, *, adsl, spec, groupby) -> ARD`; builder `.template()` and `catalog()` resolve through it. (~2 days)
4. **RTF renderer**: `render_rtf(model, path)` — `TableModel` is already renderer-agnostic; pharma RTF (Courier, borders, page headers) ~300 LOC, model on r2rtf. Pagination implemented in the model layer (`TableModel` → list of pages, `page_by` splits, repeated title/footnote blocks) so HTML/PDF/RTF/PPTX all inherit it. (~1.5 weeks)
5. **Decimal control**: `decimals: dict[stat, fmt]` on `SummarySpecBase` + per-`Row` override threaded into `fmt_fn`; `value_col: str = "AVAL"` + builder `.value("CHG")`; `label_col` for PARAM display; raise instead of nulling when the value column is missing. (~3 days)
6. Builder/spec parity: accept `Row` objects in `.rows()`; `to_spec()` raises on state the target method won't consume; listings get `.columns([...]).sort_by([...]).to_listing()`. Register or delete `t_relationship`. (~4 days)

---

## 4. Spec path / dual path (define.yaml)

### 4.1 The single highest-leverage refactor: one algorithm registry

Verb knowledge currently lives in ≥6 places and four already disagree:

- Docs advertise algorithms the engine rejects (`first_date`, `last_date`, `count`) — the docs' flagship TRTSDT YAML example raises `ValidationError`. **[verified live]** (`docs/concepts/define-yaml.md:52-135` vs `adam/models.py:9-41`)
- The published JSON schema's enum is stale — **12 valid algorithms rejected in editors** (`callable`, `seq`, `date`, `duration`, `pick`, `atoxgr`, …); both example specs point editors at it via `$schema`. **[verified live]** (`define_xml/schemas/define_spec_schema.json:291`)
- **Define-XML generation hard-fails on any spec using the sanctioned `callable` escape hatch** (validates against the same stale schema). **[verified live]** (`define_xml/spec_generator.py:94,210`)
- Dead declared fields (`lookup_dataset/lookup_key/…`) vs live undocumented `getattr` extras (`dataset`, `join_on`, `how`, ~18 total); unreachable defaults (`low=getattr(var,"low","LBSTNRLO")` on a *declared* field that defaults to `None` → documented defaults crash). **[verified live]** (`adam/models.py:66`, `adam/namespace.py:1124`)
- The only parity test is a substring scan that the docstring itself satisfies. (`test_spec_parity.py:31`)
- Two parallel define-YAML dialects (simplified vs verbose); the per-algorithm business rules (ALG01-05) only run on the dead one.

**Implementation plan — `@spec_algorithm` registry (P1, do before naming unification)**
1. Decorator on each verb: `@spec_algorithm("nrind", params={"low": Param(default="LBSTNRLO"), …})` capturing name, spec-field mapping, requiredness, defaults.
2. Generate from the registry: the `SDTMAlgorithm`/`ADAMAlgorithm` enums, the `from_spec` dispatch (one shared table-driven executor replacing both elif ladders), **discriminated-union Pydantic models** (`Literal["recode"]` + required `recode_map`, `extra="forbid"` — fixes C6), the JSON schema (`model_json_schema()` at build time), and the docs table.
3. Sync test: schema enum == registry == docs table; per-algorithm functional round-trip test (spec → execute → expected columns) replaces the substring scan.
4. Publish the **verb-coverage matrix** (inline verb ↔ spec algorithm ↔ `SPEC_UNSUPPORTED` allowlist) so "which subset is spec-safe" has a machine-checked answer. Wire `first_date`/`last_date`/`count_events` into the spec path — they're the archetypal ADSL derivations.
5. Add `fleet_spec_version: 1` to the schema; check in `from_spec`/`DefineSpecGenerator`; commit to a migration policy.
- Size: ~2 weeks. Mechanically resolves the doc drift, schema staleness, editor red squiggles, typo-tolerance, dead fields, and dispatcher duplication in one move.

### 4.2 Spec error context & escape hatch

- Spec errors carry **no variable/dataset/file context**: a 910-line define.yaml fails with `1 validation error for ADAMVariableSpec / algorithm / Input should be…` and raw polars `TypeError`s leak through. **[verified live]** Fix: wrap per-variable dispatch, re-raise as `SpecError(f"{path} → {dataset} → {variable}: …")`. (~1 day, huge payoff)
- Callable registry: silent overwrite (two studies' `AGEGR1` shadow each other), import-order footgun. Fix: warn on overwrite; spec-level `derivations_module:` key that `from_spec` imports itself.
- `select(spec=…)` silently intersects — computed columns dropped (AGEGR1 in the example), spec-declared-but-absent columns unnoticed. Fix: warn on both; golden test asserting inline vs spec-driven example outputs match on the shared variable set (today they diverge by **10 ADSL variables**). **[verified live]**
- `depends_on` auto-flush is **dead code** (flush condition can never be true; 0 flushes measured) yet documented as a headline feature and missing from the JSON schema. Fix: delete it (sequential lazy `with_columns` already orders correctly) or fix the check against materialized columns. **[verified live]** (`adam/namespace.py:1040`)

### 4.3 Round-trip, DAG, CT

- **No code→spec path** despite lineage capturing everything needed (target/verb/sources/method per variable). The natural workflow — prototype inline, freeze to spec — ends in retyping ~900 lines of YAML. Plan: `ns.to_spec_yaml(dataset="ADSL")` emitting `derivation:` blocks from `_lineage` for registry-covered verbs + `algorithm: callable` stubs for the rest; even 80% coverage removes the cliff. (~4 days after §4.1; this is also the foundation for the IDE "convert to spec" action in the tooling plan.)
- `PipelineDAG.trace()` is a stub (returns one hop dressed as a chain); DAG trusts `inputs:` declarations never reconciled with runtime pins (ADVS declares `[VS, ADSL]`, pipeline feeds `vs_raw`); lineage verb attribution via `inspect.stack()[2]` misattributes wrapped calls (spec `study_day` records as `duration`). Fixes: recursive trace; cross-check declared vs runtime edges in `inject_lineage`; pass verb name explicitly from `_chain()`.
- **CT knowledge lives in three unlinked stores** (generated `codelists.py`, define.yaml inline `codelists:`, `CTValidator` cache) — a spec can declare `codelist: C66731`, ship invalid values, pass every Fleet check, and emit a Define-XML asserting conformance. The spec path can't even opt into validation. Fixes: `from_spec` honors spec-level `ct: {validate: true}`; `DatasetChecker` verifies values against the spec's own inline codelists; normalize lookups to concept IDs.
- Define-XML tests are skipped without an external sibling checkout and assert `isinstance(result, bool)`. Fix: in-repo fixture + parsed-XML structural assertions + ODM XSD validation.

---

## 5. CLI

**The gap**: the CLI can scaffold everything but *execute* almost nothing. The three
daily workflows — run a spec pipeline, validate datasets, render a TLG from spec —
all have working Python internals and no command.

- Missing `CDISC_API_KEY` or malformed `study_config.yaml` → **raw tracebacks on day one**. **[verified live]** (`ct/api.py:109`, no handler in `cli.py`)
- Config discovery inconsistent (some commands `--config`, `add-rule` hardcodes cwd, four commands ignore config; nothing searches parents) — the documented quickstart fails without a warning admonition.
- No `fleet --version` (validated environments require it — first thing QA types). Errors go to stdout not stderr. Exit codes inconsistent (`fleet init` bare exits 0). `[all]` extra omits tlg-pdf/pptx so documented invocations traceback.
- `fleet doctor` ignores `validation.engine_path` from config — tells users to reinstall a working engine; doesn't check API key or extras (the three things actually likely missing).
- Public CLI reference documents 8 of 14 commands, duplicates two, and lost a heading; the internal agent instructions file is better than the docs.
- `derivation add` silently falls back to `./derivations` when config missing (siblings hard-error).
- No watch mode / fast dev loop for define.yaml → Define-XML preview or TLG spec → HTML.

**Implementation plan — CLI execution & polish**
1. Top-level `except FleetError` handler → clean message to stderr, exit 1; `--version`; `required=True` subparsers. (~1 day)
2. `find_study_config()` walking parents (git-style), used by **every** command; global `--config`. (~1 day)
3. **`fleet run [--dataset ADVS] [--out …]`** — config → define.yaml → `from_spec` → writers (~30-line composition of existing pieces). **`fleet validate <dir> [--custom-rules …]`** wrapping `ValidationService`. **`fleet check`** = one CI gate (config + spec parse + rule YAMLs + `DatasetChecker` + `doctor`). (~3 days)
4. `fleet tlg run/list` (from §3.2-2), `--groupby` fix (C9), extras in `[all]`, ImportError → install hint.
5. `fleet new STUDY01 --domains …` chaining the four init steps; `--watch` on `define-xml` and `tlg export` (watchfiles, one dep). Regenerate `cli.md` from the parser. `tests/unit/test_cli.py` asserting exit codes and stderr.

---

## 6. Docs-vs-reality drift (cheap, high-impact)

- GUIDE teaches `.to_frame()` chain breaks for derived-column dependencies and calls it "a Polars constraint" — **the unbroken chain works**; every reader learns a slower, lineage-destroying pattern. **[verified live]** (`GUIDE.md:492-514`)
- Docstring examples that throw on copy-paste: `duration(start_date=…)` (real kwargs `start=`/`end=`), `raw_df.sdtm.flag(…)` (SDTM doesn't inherit `FlagCriterionMixin` — `hasattr(df.sdtm,"flag") → False`). **[verified live]**
- `docs/concepts/define-yaml.md` flagship example unexecutable (§4.1); fabricated error message in CT docs (§1-C6).
- Stale `__pycache__` residue for five deleted TLG modules (`_ars`, `_shells`, …) — don't cite ARS in papers.

**Implementation plan**: xdoctest (or pytest --doctest-modules) on all docstring examples in CI; a docs-code executor test that runs every YAML/Python block in `define-yaml.md` and GUIDE parts 8/9; delete the chain-break teaching; generate verb counts from the registry. (~3 days, permanent guardrail)

---

## 7. Typing / IDE story

### 7.1 The entry-point cliff (polars #27795)

Registration via `register_dataframe_namespace` is invisible to Pylance/Pyright/mypy —
Fleet's own examples carry **49 `# type: ignore[attr-defined]`**. The `TYPE_CHECKING`-only
`fleet.DataFrame` subclass in `__init__.py:51-61` helps nobody by default because nothing
ever *produces* that type. Once inside a namespace, autocomplete is good (methods return
`Self`) — the cliff is purely at entry. Upstream may eventually ship a hook, but Fleet
shouldn't wait.

**Implementation plan — typed entry points (P2, non-breaking)**
1. Add module-level typed entry functions as the *documented* spelling:
   `fleet.sdtm(df) -> SDTMNamespace`, `fleet.adam(df)`, `fleet.tlg(df)` — one-liners,
   fully typed, zero runtime cost; attribute access stays as sugar. Examples/GUIDE
   rewritten without a single `type: ignore`.
2. Add `fleet.frame(df) -> fleet.DataFrame` cast helper for those who prefer the
   attribute style with checking; document the annotation trick.
3. `Literal` types + `@overload`s from §2.4; keep `py.typed`.
4. Keep advocating on polars #27795 (Option B — `TYPE_CHECKING`-safe declaration — is
   the least invasive for them; your issue already frames it well).
- Size: ~2 days + docs sweep.

### 7.2 LSP / MCP / VS Code (from `plan-fleetIdeTooling.prompt.md`)

The plan is sound and its core principle (discover Fleet's surface dynamically, never
hardcode) is exactly right — but it **depends on the registries existing**: the LSP's
algorithm autocomplete needs §4.1's generated schema/discriminated unions; the "convert
to spec" code action is §4.3's `to_spec_yaml()` with an AST front-end; DAG diagnostics
need §4.3's DAG fixes. Sequence it after P1/P2:

1. `fleet lsp --stdio` (pygls, `[lsp]` extra): schema validation from the *generated*
   JSON schema, algorithm/param completion from the registry, codelist hover from inline
   `codelists:`, `depends_on` handling per §4.2's resolution (delete or fix first).
2. `fleet mcp --stdio` (~200 LOC, no new deps): the 8 tools in the plan map to existing
   APIs; immediately amplifies every MCP-capable assistant. Can ship **before** the LSP.
3. VS Code shell (TreeView, DAG webview, `@fleet` participant) — after LSP.

---

## 8. Interactive vs batch TLG — solving the teal drift problem

### Why teal drifts

In the R stack the table definition is **imperative code in two dialects owned by two
parties**: the study's batch `basic_table() %>% split_cols_by() %>% …` chain, and the
layout logic frozen inside `tm_t_*` module server functions (NEST-maintained). Shared
tern *leaf* functions don't help: composition, preprocessing (`ANL01FL` logic duplicated
in scripts and `teal_data` quoted blocks), and defaults (`choices_selected` hardcoding
`ARM` while the batch program moved to `TRT01A`) all live twice. Filter-panel state is
session state — a human *transcribes* the good interactive view into the batch program,
and transcription is the drift point. "Show R Code" proves the app reproduces itself,
not that it matches the QC'd report.

### Why Fleet can be structurally immune

Fleet's TLG definition is already **data** (`TLGSpec` — filters as serializable strings,
rows, statistics, pools — with YAML round-trip), and both existing paths converge on one
engine (`spec → t_summary → ARD → TableModel → render`). teal shares *functions* between
two bodies of code; Fleet can share the *definition* between two evaluators — there is
no second body of code to drift.

### Recommended design: declared degrees of freedom + variant engine (zero new deps)

One new declarative block on the existing spec:

```yaml
output: aet01
columns: [TRTA]
statistics: [n_subjects, n_pct]
interactive:
  groupby:    {choices: [TRTA, TRT01A], default: TRTA}
  population:
    - {label: Safety, filter: 'pl.col("SAFFL") == "Y"', default: true}
    - {label: ITT,    filter: 'pl.col("ITTFL") == "Y"'}
  dataset_filter:
    - {label: All AEs,      filter: null, default: true}
    - {label: Serious only, filter: 'pl.col("AESER") == "Y"'}
  stats:
    - {label: "n (%)",    statistics: [n_subjects, n_pct], default: true}
    - {label: "+ events", statistics: [n_subjects, n_pct, n_events]}
```

Every choice is just a value for an **existing** spec field — a widget is a spec-field
editor, no new semantics. Then:

- **Batch**: `fleet tlg run specs/` renders the *default* variant → submission outputs
  (registry-dispatched, replacing the hardcoded CLI domain map).
- **Interactive**: `fleet tlg explore specs/ -o explorer.html` enumerates the declared
  variant space via `spec.model_copy(update=…)`, runs **every variant through the same
  engine**, and embeds the pre-rendered HTML fragments (+ each variant's ARD as JSON for
  a "download ARD" QC button, + its exact spec YAML in a "show definition" panel) into
  one self-contained HTML file with ~150 lines of dumb show/hide JS. No server, no new
  dependency, works from a shared drive / SharePoint / email.

**Why drift is structurally impossible**: (a) the submission output *is* the explorer's
default variant — same functions, same build; a golden test asserts byte-equality;
(b) no stat or layout logic exists in JS (that would be teal's disease reborn);
(c) promotion without transcription — the "show definition" panel displays the current
view's spec YAML; adopting it = saving that YAML into `specs/`, which the batch run then
consumes. The artifact you *viewed* is the artifact you *run*.

**Later, on demand**: `fleet tlg serve` (Shiny for Python, `[interactive]` extra,
+12-15 pkgs) — same `interactive:` block, widgets bound to `reactive.calc(spec variant →
to_ard → render_html)`, plus free-form filters through the same AST-whitelisted
`parse_expression`. The variant engine, spec block, and definition panel are 100% reused;
static explorer and live server are eager vs lazy evaluation of the same variant space.
(marimo-per-output was considered and rejected: the notebook becomes a second definition
format — the exact disease being cured.)

**Implementation plan** (≈550–750 LOC, zero new deps):

| Component | What | Est. |
|---|---|---|
| `_specs.py` | `InteractiveBlock`/`ChoiceOption` models; `interactive:` on `TLGSpec`; validate defaults ∈ choices, filters are string exprs | ~80 LOC |
| `tlg/_runner.py` | `run_spec(spec, data, adsl) → ARD` — registry-driven dispatch; refactors `cli.py`'s hardcoded map (this refactor *is* part of the anti-drift guarantee) | ~70 |
| `tlg/_variants.py` | Cartesian enumeration → `[(id, labels, TLGSpec)]`; cap ~500 with warning | ~80 |
| `render/explorer.py` | Fragments + widget bar + show-spec/download-ARD panels → one self-contained HTML; vanilla JS show/hide only | ~250 |
| CLI | `fleet tlg run <dir>`, `fleet tlg explore <dir> -o out.html` | ~100 |
| Builder | `.interactive(…)` verb → same block via `to_spec()` (keeps dual-API promise) | ~40 |
| Tests | **Golden: default explorer fragment == batch HTML bytes** (the drift regression test); variant cap; round-trip | ~120 |

Depends on: §3.2-2 (template id in YAML + registry dispatch) and C1 (renderer fix) —
do those first. Risks: combinatorial explosion (cap + pointer to future serve mode);
explorer size for listings (per-listing variant cap).

---

## 9. Roadmap — natural next steps in order

| Phase | Theme | Contents | Why this order |
|---|---|---|---|
| **P0** | Correctness | §1 no-silent-fallbacks pass (C1–C15) + §6 docs-vs-reality fixes | Wrong numbers and false docs poison everything else; also protects the PHUSE papers |
| **P1** | One source of truth + execution | §4.1 algorithm registry; §4.2 spec error context; §5 CLI (`fleet run/validate/check`, error handler, config discovery, `--version`) | Registry unblocks schema/LSP/round-trip; CLI makes Fleet batch-runnable like `sas program.sas` |
| **P2** | The breaking release (pre-1.0) | §2.1 naming unification (+ `fleet migrate`); §7.1 typed entry points; §2.2 error experience; sub-namespace state propagation | Spend the one breaking-change budget in a single, well-migrated release |
| **P3** | TLG submission readiness | §3.2 renderer/RTF/pagination/decimals; §3.1 YAML-as-workflow + open registry + listings parity | Makes Fleet the *final* producer of a submission table |
| **P4** | Write once, run everywhere | §8 interactive explorer (`fleet tlg explore`); §4.3 `to_spec_yaml()` round-trip; lazy/perf pass §2.3 | Both build on P1's registry + P3's spec workflow |
| **P5** | Tooling ecosystem | §7.2 `fleet mcp` → `fleet lsp` → VS Code extension; later `fleet tlg serve` | Amplifies everything above; premature before the registries exist |

**Quick wins to do this week regardless of phase**: `fleet --version` + top-level error
handler (2 h); GUIDE chain-break deletion (1 h); `SpecError` context wrapper (1 day);
`select(spec=…)` warnings (2 h); C2 `target_cols` fix (1 h); Parquet goldens (2 h).
