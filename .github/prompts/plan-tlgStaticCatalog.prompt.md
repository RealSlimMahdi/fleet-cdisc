# Plan: TLG Static Catalog + cards-Aligned Scaling

Ship the next TLG feature as a **static-first catalog**: self-describing specs → composable ARD primitives → one ordered HTML/PDF shell for many tables, plus an ARD-level QC comparison for double-programming. The scaling lever is refactoring AE/VS compute onto **cards-style primitives**, so adding a _new report type_ becomes a new composition — not new bespoke code.

## Why this shape

- Today AE `t_summary()` and VS `t_summary()` duplicate near-identical arm×level×stat loops. That duplication is the real barrier to LB/EX/… and a compute-layer divergence risk.
- Mirroring `{cards}` (which Fleet's ARD already aligns to): a handful of `ard_categorical` / `ard_continuous` / `ard_dichotomous` / `ard_stack` primitives that every table composes from. **More report types = more compositions, not more engines.** That is linear scaling, and it stays 100% inside Fleet's frozen-artifact philosophy.

## Steps

1. **Phase 1 — Self-describing specs.** Add `id`, `number`, `title`, `population`, `domain` to `TLGSpec` in `src/fleet/tlg/_specs.py`. Plain attributes — no registry/decorator (avoids import side-effects). Feed into `RenderMetadata`.
2. **Phase 2 — Composable ARD primitives** (_the scaling engine_). New `_primitives.py` (or extend `src/fleet/tlg/_ard.py`): `ard_categorical`, `ard_continuous`, `ard_dichotomous`, `ard_stack`. Refactor AE + VS `t_summary` to call them (removes duplication). Each emits canonical ARD rows and passes `validate_ard()`. _cardx_ statistical-test ARDs noted as an extension point, deferred (YAGNI).
3. **Phase 3 — Explicit catalog renderer** (_parallel-safe after P1/P2_). `render_catalog(specs: list, data: dict, path, fmt)` in new `_catalog.py`. Takes an **explicit list** (no discovery magic), sorts by `number`, computes each ARD, shapes via `ard_to_table_model`, concatenates into one ordered document. Reuses `render/html.py` + `render/pdf.py`.
4. **Phase 4 — ARD QC comparison.** `compare_ard(prod, qc) -> pl.DataFrame` — join on group/variable/stat_name, diff `stat`, return mismatches. Tool-agnostic double-programming evidence (SAS-ARD vs Fleet-ARD).
5. **Phase 5 — Generated index.** `catalog_index(specs) -> pl.DataFrame` → the "Excel" TOC, generated on demand, never hand-maintained. Optional TOC page prepended to the shell.

## Relevant files

- `src/fleet/tlg/_specs.py` — catalog metadata fields on `TLGSpec`
- `src/fleet/tlg/_ard.py` — reuse `ard_row`/`compute_stat`/`rows_to_ard`/`validate_ard`; possibly host primitives
- `src/fleet/tlg/ae_namespace.py` + `src/fleet/tlg/vs_namespace.py` — refactor `t_summary` onto primitives
- `src/fleet/tlg/_catalog.py` _(new)_ — `render_catalog`, `compare_ard`, `catalog_index`
- `src/fleet/tlg/__init__.py` — export new public API
- `examples/tlg_catalog_example.py` _(new)_ — AE+VS → one shell + QC compare

## Verification

1. `uv run ruff check && uv run ruff format --check`
2. `uv run pytest`
3. `uv run python examples/tlg_ae_example.py && uv run python examples/tlg_vs_example.py`
4. New `examples/tlg_catalog_example.py` runs: AE+VS → one PDF + one HTML, `compare_ard` demo
5. `uv run python scripts/build_llms.py && uv run python scripts/build_llms.py --check` (public API changed)

## Decisions

- HTML/PDF only (no RTF). Scope = AE **and** VS to prove scalability.
- No discovery/decorator/lockfile, no FilterContext, no reactive layer — all deferred to a future RFC.
- cardx statistical tests + spec-inheritance footnotes noted as extension points, not built now.

## Further Considerations

1. **Where do primitives live?** Inside `_ard.py` (fewer files, KISS) vs a dedicated `_primitives.py` (clearer separation as the library grows). Recommendation: dedicated module — it _is_ the scaling surface and will accumulate functions.
2. **Refactor depth in Phase 2.** Minimal (extract only the shared loop) vs thorough (full cards-parity primitive set up front). Recommendation: minimal — extract exactly what AE+VS share now, add primitives later per real report type (YAGNI).
3. **Catalog `data` resolution.** Route specs to DataFrames by `domain` string (simple) vs an explicit `{spec.id: df}` mapping (unambiguous when two specs share a domain). Recommendation: explicit mapping, falling back to `domain`.
