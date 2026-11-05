# Fleet Interactive TLG — Strategy & Design Options (Bridge, v2)

> **Status:** design, not implemented as a whole (rechecked 2026-11-05). Open; tracked in [issue #144](https://github.com/RealSlimMahdi/fleet-cdisc/issues/144) and the ideas tracker.

> Rewritten after an adversarial review of v1. This is an **options document
> with recommendations**, not a single-path plan. It answers three questions
> in order: (1) should TLG live inside Fleet at all, (2) what should the
> interactive tool be, (3) how does each option feel to **create**, to
> **maintain**, and to **put in production** in a pharma environment.

**Status:** design, pre-implementation. Decisions marked ⬜ are open; ✅ are
recommended defaults that stand unless overruled.

---

## 0. The organizing principle

Reporting in pharma is unsolved — layout wars (sponsor shells, RTF
conventions), double-programming validation culture, per-study flexibility,
and few tools anyone actually trusts. The design consequence is not "avoid
reporting" but **invest inversely to churn**:

| Layer | Stability | Investment stance |
|---|---|---|
| Statistics → **ARD** ({cards}-compatible, already in `tlg/_ard.py`) | stable, validatable | core Fleet asset — protect and freeze its contract |
| Templates & spec schema (`schema_version: 1` already exists) | semi-stable | versioned contract, evolve deliberately |
| Renderers (HTML/RTF/PDF/PPTX layout) | churns per sponsor | thin, swappable, behind the ARD |
| Interactive shells | churns fastest | thinnest of all — generated code, zero framework |

Every option below is judged against this gradient. The numbers must have one
implementation; everything above the numbers should be cheap to replace.

---

## 1. Strategic question — does TLG belong in Fleet?

The doubt is legitimate: Fleet's derivation core (SDTM→ADaM) is the solved,
benchmarked, stable asset; reporting could dilute it. Four options.

### A. Status quo — TLG stays in Fleet core

- **Create:** best DX — one install, `import fleet`, `df.tlg` just works.
- **Maintain:** reporting churn drives core releases; every Fleet release
  re-validates TLG too; the package's identity blurs ("is Fleet a derivation
  engine or a reporting tool?").
- **Prod:** one package to qualify — simplest install, heaviest per-release
  qualification surface.

### B. Same repo, separate distribution — `fleet-cdisc` + `fleet-tlg` ✅ (as destination)

Split the *distribution*, not the code layout: `fleet.tlg` becomes a
namespace package shipped as its own wheel. `import fleet.tlg` is unchanged;
a meta-extra (`fleet-cdisc[tlg]`) hides the seam.

- **Create:** identical user experience; two version numbers.
- **Maintain:** core and reporting release on independent cadences; a
  renderer layout fix no longer triggers derivation re-validation; the ARD +
  spec schema become an explicit, tested **contract** between the wheels.
- **Prod:** sponsors qualify the derivation engine once and accept reporting
  updates on their own cycle — this matches how pharma actually validates.

### C. TLG out of Fleet entirely — ARD-only boundary

Fleet emits ARDs + metadata; presentation is delegated (Great Tables, R
{tfrmt}/{gtsummary} via ARD interchange, Quarto/typst).

- **Create:** analysts stitch tools across languages; the "one definition,
  two run modes" story dies at the package boundary.
- **Maintain:** smallest Fleet surface — but you now *depend on* the exact
  ecosystem the doubt calls unreliable, instead of owning a thin slice of it.
- **Prod:** multi-tool, often multi-language qualification — the worst
  deployment story of the four.
- Honest note: statistics drift (the dangerous kind) is still prevented,
  because the ARD stays single-sourced. Only *formatting* drift returns.

### D. Core ARD + plugin renderers

Renderers register via entry points; sponsors ship their own layout plugins.
A refinement of B, not an alternative — record as a later extension.

### Recommendation

**Discipline now, packaging later.** The blocking asset is the *contract*,
not the wheel split: freeze and version the ARD schema (track CDISC ARS
alignment) and the spec `schema_version`, add contract tests, and route all
new work through that boundary. When the contract has held for 2–3 releases,
the B split is mechanical. Deciding A-vs-B today is not required to build
anything below — **the interactive tool never touches statistics, so it is
independent of the packaging decision.**

⬜ Decision for maintainer: adopt B as stated destination, or defer entirely.

---

## 2. Constraints carried over from the v1 grill

Non-negotiable regardless of which options are chosen:

1. **Single filter ownership.** Every filter — declared or interactive —
   lives in spec fields and is applied inside `run_spec`. No second
   filtering implementation in any cohort/UI layer. (v1's cohort-layer
   semi-join filtering is dead.)
2. **Listings population gap.** Listing specs mark `adsl_filter` unconsumed
   (`_specs.py:701`); a population-filtered listing currently has no spec
   representation. Spec schema RFC required — this bumps `schema_version`.
3. **The TLG path is eager end-to-end today** (zero `.collect()` in
   `src/fleet/tlg/`). Laziness is *new* work in the loading layer, not a
   flag flip.
4. **Verify CSE before building on it.** The compute-once-fan-out pattern
   assumes common-subplan elimination across `collect_all` on the streaming
   engine. Prove it with an `explain()` assertion before any architecture
   depends on it.
5. **Pin `polars<2` when 2.0 releases; adopt deliberately after
   re-validation.** An unbounded `>=1.41` in a validated toolchain is the
   real 2.0 action item.
6. **Free predicates are bounded by the AST whitelist** of
   `parse_expression` — audit its vocabulary (dates, `is_in`, boolean
   trees) before promising teal-style filtering.
7. **Interactive filter widgets compose with spec-declared filters by
   explicit rule** (AND-merge, surfaced in the definition panel) — never
   silently replace them.

---

## 3. The engine work every option shares: the Workbench kernel

A small, UI-agnostic library (`src/fleet/tlg/_workbench.py`), no new
dependencies:

- **Lazy sources:** registers `scan_parquet`/`scan_ipc` per `StudyContext`;
  fingerprints each source once (size + mtime + schema hash — cheap, and
  documented as the staleness boundary).
- **Content-addressed memoization:** `ws.ard(spec)` keyed by
  `hash(fingerprints, spec_fields)`; `ws.render(spec)` keyed by
  `(ard_key, layout_fields)` — so formatting tweaks skip statistics
  entirely. Cache writes are temp-file-then-rename; eviction is LRU by
  bytes with a configurable cap.
- **Never filters, never computes statistics.** It loads, memoizes, and
  delegates to `run_spec`. That is the whole job.

This is Phase 1 regardless of every other choice, and it is fully testable
headless.

---

## 4. Interactive tool options

Five options, each scored on create / maintain / prod. They are not all
mutually exclusive — the recommendation is a portfolio.

### O1 — Spec-first live preview (`fleet tlg run --watch` + browser reload) ✅ ship first

The `--watch` loop already exists (`cli.py:214`). Add HTML auto-reload (a
1-line meta-refresh or SSE ping) and a `--serve-preview` flag that opens the
rendered output. The workflow becomes: edit YAML in your editor → table
re-renders on save. With the [VS Code extension](https://github.com/RealSlimMahdi/fleet-vscode)
and the existing LSP groundwork, spec editing gets completion + preview like a
static-site generator (`mkdocs serve` feel).

- **Create:** zero new concepts — the spec is the artifact, the editor is
  the UI. Closest possible fit to Fleet's spec-first philosophy.
- **Maintain:** ~200 lines on existing infrastructure; no UI framework at
  all; nothing to keep in sync.
- **Prod:** not a prod surface — it's a *development* surface. Nothing to
  deploy or qualify.
- **Limit:** no widgets, no cohort experimentation for non-programmers.

### O2 — Reactive notebook: marimo shell, generated by `fleet tlg notebook <spec>` ✅ programmer flagship

marimo = reactive dataflow notebook, pure `.py`, no hidden state, runs as
notebook / read-only app / static export. The generated shell is ~25 visible
lines binding `mo.ui` widgets to spec fields, calling `ws.render(view)`, and
showing the definition YAML for promotion into `specs/`.

- **Create:** widgets, live tables, and a promote-by-saving-YAML loop with
  **no framework API** — the interactive surface is the batch surface.
  Codegen means the starting point is free; the file lives next to the
  study's specs, diffable and reviewable.
- **Maintain:** marimo is a single optional dependency
  (`tlg-notebook = ["marimo"]`); the shell is generated, so template fixes
  regenerate it; the kernel it calls is shell-agnostic, so marimo is
  swappable if it loses momentum (it is younger than Jupyter — the real
  risk, mitigated exactly here).
- **Prod:** runs on the analyst's qualified workstation environment
  (uv.lock). `marimo run` can serve it read-only later without new code.
- **Limit:** an analyst tool. Reviewers without Python get nothing from it
  directly.

### O3 — Static explorer v2: `fleet tlg explore --split` ✅ reviewer flagship

Today's explorer is one self-contained HTML capped at 500 variants (an
artifact-size cap, not an engine cap). `--split` writes an index plus
per-variant fragment files; the cap disappears and the artifact stays a
folder of files.

- **Create:** nothing new for the author — same `interactive:` axes in the
  spec.
- **Maintain:** an output mode of an existing renderer; no server code.
- **Prod:** **the pharma-native deployment**: files on a governed shared
  drive. File ACLs are the auth model the industry already validates;
  outputs are immutable and checksummable. Zero IT engagement.
- **Limit:** sanctioned pre-declared views only — by design. Verify the
  index→fragment loading works from `file://` (iframe display, no fetch())
  on the target browsers before committing.

### O4 — Live server (deferred, explicit entry criteria)

Variants, in ascending build cost: `marimo run` of O2 notebooks behind SSO →
Shiny for Python app → FastAPI compute service returning Arrow + thin JS
client (AG Grid).

- **Create:** the richest reviewer experience — free cohort widgets for
  non-programmers.
- **Maintain:** a service: session management, dependency patching,
  monitoring — a standing cost every other option avoids.
- **Prod:** the swamp the grill mapped: authn/authz, per-view audit trail
  (Part-11-adjacent), unblinding controls, multi-user CPU contention,
  qualified *service* validation instead of artifact validation. In pharma
  this usually means Posit Connect / Domino / on-prem SSO — real IT
  procurement.
- **Entry criteria (all three, before any build):** a named deployment with
  a platform owner; an auth + audit design; evidence that O2+O3 left a real
  gap.

### O5 — No Fleet tool: ARD hand-off to external presentation

The interactive layer is someone else's product (e.g. ARD → Great Tables in
Quarto dashboards, ARD → R {tfrmt}). This is strategic option C wearing UI
clothes.

- **Create/maintain:** cheapest for Fleet, most stitching for users.
- **Prod:** per-sponsor tool zoo; formatting drift returns.
- Keep as the escape hatch if maintenance capacity collapses — the ARD
  contract (§1) is exactly what makes this exit clean. Not recommended
  while O1–O3 cost as little as they do.

### Portfolio recommendation

| Audience | Tool | Cost profile |
|---|---|---|
| Spec author (daily) | O1 watch-preview | days of work, no deps |
| Stat programmer (exploration) | O2 marimo codegen | one optional dep, thin codegen |
| Reviewer / clinician | O3 explorer `--split` | output mode of existing code |
| Multi-user live | O4 | deferred behind entry criteria |
| Exit hatch | O5 | enabled by the ARD contract, unused |

Three shells, one kernel, one engine — and O1+O3 are nearly free because
they finish infrastructure the repo already has.

---

## 5. Production & qualification matrix

How outputs actually reach people, per mode:

| Mode | Artifact | Auth model | Validation story |
|---|---|---|---|
| CI batch (`fleet tlg run`) | files in `outputs/`, checksummed | repo/drive ACL | golden tests; the validated path everything else is pinned to |
| Watch-preview (O1) | ephemeral local HTML | n/a (dev only) | none needed — never leaves the workstation |
| Notebook (O2) | `.py` next to specs + on-screen views | workstation env (uv.lock) | golden test: notebook default view ≡ batch output (define the fragment boundary precisely) |
| Explorer (O3) | folder on shared drive | file ACLs | every variant pre-rendered by the validated engine at build time |
| Server (O4) | live sessions | SSO + audit log | service qualification — the expensive one |

Cross-cutting: promoted view-state (spec YAML + widget selections) is the
audit unit for interactive work — log it in O2 from day one; it is cheap
there and painful to retrofit.

---

## 6. Polars 2.0 alignment (condensed from v1, gates unchanged)

| Item | Gate | Use |
|---|---|---|
| `engine="streaming"` | available now | new lazy loading layer only — there are no existing collects to flip |
| 2.0 default flip | **pin `<2`, re-validate, then lift** | see §2.5 |
| Memory limit / spill | first-PR, flag it | only relevant if O4 ever exists |
| Adaptive S3 | active | `scan_parquet("s3://…")` for governed lakes — pool/ISS phase |
| Distributed exprs | in progress, hard | re-validate order-sensitive derivations on any distributed run |
| Iceberg atomic sinks | roadmap, flag it | snapshot **promoted** ARDs only — never per-view churn |

Benchmark note: `benchmark/` already has `inflate_data.py` — extend it to a
synthetic-pool TLG benchmark so the performance claims have evidence at
study scale *and* pool scale, including the CSE assertion (§2.4).

---

## 7. Phasing with decision gates

**Gate 0 (decisions, no code):** packaging stance (§1 ⬜); spec-schema RFC
for listings population + filter composition (§2.2, §2.7); AST-whitelist
audit (§2.6).

**Phase 1 — kernel + spec fixes:** Workbench (lazy sources, memoization);
schema_version 2 with listings population; contract tests on ARD + spec
schema; CSE benchmark.

**Phase 2 — the free shells:** O1 watch-preview polish; O3 explorer
`--split` (+ `file://` verification); golden tests pinning both to batch.

**Phase 3 — the flagship shell:** O2 `fleet tlg notebook` codegen +
`tlg-notebook` extra; view-state audit logging; graphs get their own extra
(`tlg-graphs = ["altair", "vl-convert-python"]`) with the static-figure
export path (PNG into RTF/PDF) solved before templates ship.

**Phase 4 — scale & maybe-server:** synthetic-pool benchmarks, S3 scans,
streaming; O4 only if its entry criteria are met; B-split of the
distribution if the contract has held.

---

## 8. Decision log

1. **TLG stays, as a disciplined layer** — the ARD/spec contract is frozen
   first so that both the B-split and the O5 exit remain cheap. Reporting
   churn is contained by the investment gradient (§0), not by amputation.
2. **No application framework.** The interactive tool is a portfolio of
   thin shells (watch-preview, generated notebook, static explorer) over
   one kernel; teal's category error — a second app-shaped implementation —
   is structurally excluded.
3. **v1's cohort-layer filtering is withdrawn** (dual-implementation drift);
   filters live in specs, applied by `run_spec`, merged by explicit rule.
4. **Server demoted from centerpiece to gated option** with named entry
   criteria; pharma-native distribution (files + ACLs) is the default prod
   story.
5. **Great Tables stays out of the sanctioned path** (renderer identity is
   what makes the golden tests possible); it remains available via the ARD
   as an unsanctioned scratch surface.
6. **Streaming/2.0 features adopted behind maturity gates; `polars<2` pin
   at release.**
