# Define-XML method/origin conformance — handoff plan

> **Status: implemented** (this branch, 2026-07-28; 1878 tests passing).
> Deviations from the plan below:
>
> - The **golden TSV snapshot** (Phase 3) was replaced by an
>   outputs-reproducibility sync test — `outputs/cdiscpilot01/define_*.xml`
>   are committed artifacts, and `test_define_semantics.py` asserts they
>   match what the code generates from the specs (same pattern as the
>   JSON-schema sync test). Text drift still lands as a reviewed git diff,
>   on the real define.xml instead of a parallel TSV.
> - **Phase 7** shipped as `to_spec_yaml(dataset=..., predecessor="DM")`
>   rather than a standalone CLI: carry-through columns and pure
>   `algorithm: source` copies are emitted with `origin: Predecessor` /
>   `predecessor: DM.<VAR>`. Merge-introduced columns leave no lineage, so
>   a review note is added to the header when the pipeline contains a join;
>   generation-time inference remains off (decision 1 intact).
> - `FormalExpression` renders the faithful call (optional upgrade taken).

Branch `pydantic-define-spec-envelope`, uncommitted, 1842 tests passing.

**Amendments vs. the original chat handoff** (all in the direction of ease/automation —
one-time fixes become standing machinery):

- **Phase 2**: templates are *synthesized by default* from registry metadata;
  `define_template` is an override, not a required field. New registry-wide render test.
- **Phase 3**: the lock-in rules become a *runtime semantic lint* living next to the XSD
  check, not just CI assertions over Fleet's examples. Adds a golden snapshot of
  reviewer-facing text.
- **Phase 4**: adds a generation-time "looks like a Predecessor" warning (lint severity).
- **Phase 6**: adds an actionable stub-coverage report at generation time.
- **New Phase 7 (optional)**: spec-autofill tool that *writes* `predecessor:` entries as a
  reviewable diff — automates authoring without relitigating the explicit-field decision.
- **Phase 2 (optional)**: `FormalExpression` may render the faithful call
  (`fleet.sdtm.ae_aerel(source="AEREL_RAW")`) instead of the bare dotted path.

## 1. Where things stand

Already completed this session (do not redo):

- `fleet.core.define_spec` — validated envelope for spec files; single ingest for
  `from_spec`, `build_dag`, `_spec_dataset_meta`, NSV resolution.
- Single origin vocabulary (Define-XML 2.1: `Collected/Derived/Assigned/Protocol/
  Predecessor`) replacing the old 2.0-era set; `origin_source` added; QORIG shares the
  vocabulary.
- CDISC ODM 1.3.2 + Define-XML 2.1 XSDs vendored at
  `src/fleet/define_xml/schemas/xsd/{define/2.1,odm/1.3.2}` (from
  `cdisc-org/data-definition-engine`, MIT). **XSD validation now runs automatically**
  inside `DefineSpecGenerator._serialise()`; `validate_xml=False` bypasses.
- Five conformance defects fixed (Standard name/PublishingSet enums, ItemGroupDef child
  order, `def:leaf` title element, duplicate leaf `xs:ID`).

**Target file for this work:** `src/fleet/define_xml/spec_generator.py`
(`DefineSpecGenerator`). Note there is a *second*, unrelated generator —
`src/fleet/define_xml/generator.py` / `DefineXMLGenerator` — for the pharmaverse-format
path. Don't confuse them.

## 2. The problem

The generated define.xml is now *structurally* valid but *semantically* wrong in
reviewer-facing content.

**2a. MethodDefs on non-derived variables.** Measured on the generated SDTM define:

```
Origin      MethodOID              count
Collected   MT.assign_no_ct        13
Assigned    MT.hardcode_no_ct       9
Collected   MT.assign_dtc           8
Derived     MT.assign_no_ct         7
Protocol    MT.assign_no_ct         5
Collected   MT.assign_ct            3
Assigned    MT.assign_no_ct         2
```

43 of 49 `MethodOID` references sit on Collected/Assigned/Protocol variables. A
`MethodDef Type="Computation"` on a collected variable that is merely a column rename is
not what MethodDef means.

**2b. Method text is Fleet's API docstring, not the study's derivation.**
`_register_method` pulls `resolve_algorithm_docstring()`, giving the same generic sentence
to every variable using that verb:

```
assign_no_ct → "Assign *target* from a source column or a literal value."
derivation   → "Derive *target* using an expression, lambda, or ``Derivation`` object."
```

Four faults: identical across 27 variables; written as an API instruction rather than a
statement of what the value is; reST markup (`*target*`, double backticks) leaks into a
regulatory document; and a developer improving a docstring silently rewrites a submission
artifact — two Fleet versions produce different define.xml text from an identical spec.

**2c. The docstring is appended to the study's own comment without a separator:**

```
USUBJID Origin desc: "Concatenation of STUDYID, SITEID, and SUBJID Assign *target* from a source column or a literal value."
```

**2d. `Predecessor` origin is never emitted.** ADaM variables carried from SDTM are marked
`Collected`. Expected: `Origin Type="Predecessor"` with Description `DM.COUNTRY`.

**2e. `MethodDef/@Name` is Fleet's internal algorithm id** (`assign_no_ct`), and
`FormalExpression` contains a stub (`.ae_aerel(...)`).

**Target rendering** (standard define.xml Origin column):

| Case | Define-XML 2.1 | Renders as |
|---|---|---|
| ADaM from SDTM | `Type="Predecessor"` + Desc `DM.COUNTRY` | `Predecessor: DM.COUNTRY` |
| Assigned from a variable | `Type="Assigned"` + Desc `DM.AGE` | `Assigned: DM.AGE` |
| Assigned, param-varying | `Type="Assigned"` + Desc `See Value Level Metadata` | `Assigned: See Value Level Metadata` |
| Derived | `Type="Derived"` + MethodDef Description | `Derived: Set to the datepart of Date of Death [ADSL.DTHDTC]…` |
| Collected | `Type="Collected" Source="Investigator"` + PDFPageRef | `CRF: page 8` |

## 3. Key architectural insight (drives the design)

Both pipelines converge on one `(algorithm, params)` pair *before* any XML is written:

- **Spec-driven:** validated per-algorithm model → `model_dump()`
- **Inline code:** `src/fleet/core/spec_registry.py` reverse-maps a runtime
  `VariableNode` (verb + captured kwargs) to the same derivation block. Existing, tested
  machinery behind `to_spec_yaml()`.

So the text renderer must take `(algorithm_name, params: dict)` — **not** a spec model —
and live in the registry, where both callers reach it.

The registry already carries reviewer-shaped, markup-free text per algorithm — *and per
param* (`SpecAlgorithm.description`, `Param.description`) — unused for this purpose:

```
assign_no_ct  "Copy a raw column without controlled-terminology mapping."   params: ['source']
date          "Parse, convert, impute, and flag a date/datetime column."    params: ['source','impute',…]
bmi           "Body Mass Index from weight and height."                     params: ['weight','height']
```

Text-source rule (first match wins, top to bottom):

- **Spec `comment:`** — always overrides.
- **Study `@derivation` docstring** — escape-hatch cases (`resolve_callable_docstring()`
  exists); this *is* study-authored text, unlike Fleet's verb docstrings.
- **Registry `define_template` override** — where the synthesized default reads poorly.
- **Synthesized default from registry metadata** — all other registry-covered
  derivations, both paths (see Phase 2).
- **Fleet verb docstring** — never (API-shaped, generic, version-unstable).

Coverage limit: `derivation_from_lineage` returns `ok` / `stub` / `byproduct`. On the
CDISCPILOT01 DM pipeline, 15 of 17 inline-derived variables are `ok` (~88%); the two
stubs (`SITEID` string derivation, `ARMCD` inline Polars `if_then_else`) have no algorithm
to template from and need `comment:` or a `@derivation` wrapper.

## 4. Decisions taken (do not relitigate)

1. **Predecessor** — explicit `predecessor:` field; lineage *inference* at generation time
   is opt-in only. (Phase 7's autofill tool is compatible: it automates *authoring* the
   explicit field as a reviewable diff; generation itself stays explicit.)
2. **`MethodDef/@Name`** — `Algorithm for TRTSDT`.
3. **Collected with no CRF pages** — emit a placeholder description.
4. **Dotted path** — keep as provenance, in `FormalExpression Context="Python/Fleet"`
   (replacing the current `.verb(...)` stub). *Not* `def:DocumentRef`, which requires a
   `leafID` to a real document.

## 5. Plan

**Order: 1 → 3 → 2 → 4 → 5 → 6 → (7 optional, any time after 4).**

### Phase 1 — Remove wrong text (small)

`src/fleet/define_xml/spec_generator.py`

- `_build_item_def`: `def:Origin/Description` from spec `comment:` only; delete the
  docstring append.
- Attach `MethodOID` only when `origin == "Derived"`.
- Collected variables without `crf_pages`: emit the agreed placeholder.

**Accept:** 0 `MethodOID` on non-Derived origins; XSD valid; XSLT renders.

### Phase 3 — Runtime semantic lint + golden snapshot (small, do early) *(amended)*

Do this **before** Phase 2 so the lint catches template mistakes as they're authored.

- **Semantic lint module** next to `src/fleet/define_xml/xsd.py` (e.g.
  `semantic_checks.py`), run automatically inside `_serialise()` under the same
  `validate_xml` flag as the XSD check. Rules:
  - no `MethodOID` on non-Derived origins;
  - no reST markup (`*…*`, backticks) in any `TranslatedText`;
  - `MethodDef/@Name` never equals a registry algorithm id;
  - every `Predecessor` description matches `DATASET.VARIABLE`.

  Rationale: as CI assertions these rules protect only Fleet's examples; as a runtime
  lint they protect every user's define. Same shape as the XSD hook, which is precedent.
  Severity: error (same as XSD failure). `validator.py`'s BR01–BR04 layer is the analogue
  on the YAML side — keep the new lint on the XML side, post-generation.
- **Tests** in `tests/define_xml/test_define_xsd.py` (or a sibling) become thin: assert
  the lint passes on all generated examples, and assert the lint itself stays strict
  (feed it a deliberately bad tree, expect failure).
- **Golden snapshot of reviewer-facing text**: per example, extract
  `variable → origin type → origin/method description` to a committed TSV and compare.
  Any text change — including a later `define_template` edit — becomes an explicit
  reviewed diff instead of silent drift in a submission artifact (the 2b failure mode,
  which templates alone do not eliminate). Regeneration path: rerun the example scripts,
  commit the updated TSV deliberately.

**Accept:** lint runs inside `_serialise()`; bad-tree test fails; goldens committed.

### Phase 2 — Registry templates, synthesized by default (medium) *(amended)*

`src/fleet/core/spec_registry.py`, `src/fleet/define_xml/spec_generator.py`

- Add `render_method_text(standard, algorithm, params) -> str` in the registry: the
  single choke point for both pipelines.
- **Default rendering is synthesized** from metadata the registry already has:
  `SpecAlgorithm.description` (already reviewer-shaped) + rendered param values, e.g.
  `"Copy a raw column without controlled-terminology mapping. Source: AEREL_RAW."`
  Every algorithm — including future ones — gets reviewer-safe text by construction;
  adding a verb without define text becomes impossible, not just discouraged.
- Add `define_template: str | None = None` to `SpecAlgorithm` + `spec_algorithm()` as an
  **override** for algorithms where the synthesized default reads poorly. The task is now
  "review ~25 synthesized defaults, override the weak ones" — not "author 25 templates".
  Review overrides as submission content, not code.
- **Registry-wide render test**: render every registered algorithm with dummy params;
  assert no unfilled `{…}` placeholders, no reST markup, non-empty text.
- `MethodDef/@Name` = `Algorithm for <VARIABLE>`; `@Description` = rendered text;
  `comment:` overrides (per §3 text-source rule).
- `FormalExpression` = dotted path per decision 4. **Optional upgrade:** a sibling
  `render_formal_expression(standard, algorithm, params)` emitting the faithful call —
  `fleet.sdtm.ae_aerel(source="AEREL_RAW")`, kwargs deterministically sorted — real
  provenance at zero authoring cost, same choke point. Either satisfies decision 4.

**Accept:** no `*` or backticks in any `TranslatedText` (now lint-enforced); `@Name`
never a registry algorithm id; registry-wide render test green; goldens updated and
reviewed.

### Phase 4 — Predecessor (small-medium) *(amended: adds a warning)*

- Schema (`predecessor` property, conditionally required when `origin: Predecessor`) —
  mind `schema_builder.py` hand-owned defs (see Gotchas).
- `src/fleet/core/define_spec.py` `VariableEntry`; `spec_generator.py` emission; ADaM
  example migration `Collected → Predecessor`.
- **Generation-time diagnostic** (lint, warning severity): a variable that is a pure
  cross-dataset copy but marked `Collected` → warn "looks like a Predecessor". Does not
  change output — decision 1 stands; it just surfaces the miss where the author can act.

### Phase 5 — Value-level metadata (small)

When a variable has a `def:ValueListRef` and no `comment:`, Origin description =
`See Value Level Metadata`.

### Phase 6 — Inline parity + stub report (small) *(amended)*

- Test proving inline DM pipeline → `to_spec_yaml()` → define.xml yields text identical
  to the spec-driven route — both routes compared against the **same golden** from
  Phase 3.
- `stub` variables: `resolve_callable_docstring()` for `@derivation`; otherwise warn.
- **Stub-coverage report**: generation emits an actionable summary via the Phase 3 lint
  (warning severity): "2 variables have no reviewer-facing derivation text — add
  `comment:` or wrap in `@derivation`", naming the variables. Turns a silent quality gap
  into a checklist at the moment the study programmer can act on it.

### Phase 7 — Predecessor autofill tool (small, optional) *(new)*

A spec-authoring command (CLI or mode of an existing spec tool): walk lineage, find pure
cross-dataset copies, and *write* `origin: Predecessor` + `predecessor: DM.COUNTRY` into
the spec YAML (or print a patch). The spec remains the audited source of truth; the human
reviews one diff instead of typing ~50 entries. Compatible with decision 1 — this
automates authoring, not generation. Honour the config-context rule: resolve paths via
`study_config.yaml` discovery, never CWD.

## 6. Gotchas

- XSD validation is automatic now — any structural mistake fails at generation, loudly.
  Use it. The Phase 3 semantic lint rides the same hook; keep both behind `validate_xml`.
- `schema_builder.py` regenerates the derivation half of `define_spec_schema.json`;
  structural sections are hand-owned in `_HAND_OWNED_DEFS`. A sync test enforces the
  round-trip. Phase 4's `predecessor` property is structural → hand-owned side.
- Every phase changes `outputs/cdiscpilot01/define_*.xml`, the `_preview.html` files,
  **and the Phase 3 golden TSVs**. Expected; regenerate via the examples and commit the
  golden diff deliberately — that diff *is* the review step.
- `tests/.../test_crf_pages.py` asserts origin content and will need updating in Phase 1.
- Don't let the semantic lint and the golden test double-report the same failure; the
  lint checks invariants, the golden checks exact text.

## 7. Verification (per AGENTS.md)

```bash
uv run ruff check && uv run ruff format --check
uv run pytest
uv run python examples/cdiscpilot01_spec_driven.py   # regenerates define_*.xml under XSD validation
uv run python examples/full_pipeline_example.py && uv run python examples/cdiscpilot01_inline.py \
  && uv run python examples/adnca_example.py && uv run python examples/tdd_example.py
```
