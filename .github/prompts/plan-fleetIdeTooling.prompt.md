> **Status (2026-08): Tier 1 LSP + MCP shipped (`fleet lsp --stdio`, `fleet mcp --stdio`); the VS Code client now ships from [`RealSlimMahdi/fleet-vscode`](https://github.com/RealSlimMahdi/fleet-vscode); Tiers 2b/3/4 open.**

# Companion VS Code Extension & Language Server for Fleet — Updated Plan (May 2026)

**What changed since the original brainstorm:** Fleet has grown significantly. 200+ verbs across 12 namespaces. A full TLG/ARD pipeline. A pin system for cross-domain data access. Staged derivation ordering via `depends_on`. 9 validated example scripts. The overarching design principle for tooling must therefore be: **discover Fleet's surface dynamically from the installed package, never hardcode it.** Every feature that enumerates verbs, algorithms, or namespaces must call into the live Python runtime, because Fleet will keep growing.

---

## Tier 1: Language Server Protocol (LSP) for define.yaml

**Approach:** A Python LSP via `pygls`, launched as `fleet lsp --stdio`, auto-discovered from the project `.venv` by the VS Code extension. Ship as `fleet-cdisc[lsp]` optional extra (adds only `pygls`). The LSP imports Fleet directly — it never hardcodes verb names, algorithm enums, or schema fields.

### 1.1 Schema-aware autocomplete

The LSP reads `SDTMAlgorithm` and `ADAMAlgorithm` enums from the live Fleet package to populate `algorithm:` completions. New algorithm types added to Fleet appear in autocomplete immediately without an extension update.

For each algorithm, parameter completion is driven by the corresponding Pydantic model (`SDTMVariableSpec`, `ADAMVariableSpec`). When the user types `algorithm: assign_ct`, the LSP knows to require `source:` and `ct_codelist:` and to offer `ct_mapping:` as optional — because Pydantic validates it.

**Edge case:** `algorithm: derivation` accepts a free-form `expression:` string (arbitrary Polars syntax). The LSP does not attempt to validate Polars expressions, but it completes the key name and shows a hover note: _"Arbitrary Polars expression string, evaluated at runtime."_

### 1.2 `depends_on` field awareness

The define.yaml `depends_on:` field is ADVS-critical: `ADT → ADY → BASE → CHG`. The LSP must:

- Recognize `depends_on:` as a valid key in variable derivation blocks
- Complete with variable names from the same dataset's `variables:` list
- Validate that `depends_on:` references exist in the same dataset (no cross-dataset depends_on)
- Flag cycles within a single dataset's depends_on graph as a diagnostic

**Edge case:** `depends_on:` can be a list. Multi-stage chains (`[ADT, ABLFL]`) must all resolve within the dataset.

### 1.3 Multi-input dataset handling

Datasets like ADVS have `inputs: [VS, ADSL]`. The LSP must:

- Validate that all `inputs[].name` values are defined elsewhere in the file (same define.yaml) or in a sibling define.yaml (SDTM domains referenced from ADaM)
- Support cross-file resolution: parse sibling YAML files in the same `examples/` subtree
- For `source:` values referencing upstream columns, offer completions from the union of all input datasets' known variables (read from their define.yaml `variables:` blocks)

**Edge case:** Raw inputs (`type: raw`) have no variable list — the LSP cannot offer completions for raw column names since they're in the CSV. It should show a fallback note: _"Source column from raw file — no schema available."_

### 1.4 Pin system in define.yaml

The `pin:` pattern (cross-domain data access) is currently an inline Python verb, not representable in define.yaml. However, when a dataset's `inputs:` lists multiple datasets, the spec-driven executor uses that as its equivalent. The LSP should:

- Treat multiple `inputs:` as a semantic signal that cross-domain joins occur
- Flag when a `source:` variable name exists only in a secondary input (not the primary), and annotate: _"Derived from input dataset [ADSL], not the primary input [VS]."_

### 1.5 Codelist hover and completion

- Resolve `ct_codelist: C66731` to its human-readable name and valid terms from the define.yaml's own `codelists:` section — **no API call needed** (the codelist is always declared inline)
- For codelist OIDs not declared in the file, look up `codelists.py` in the project for the class-to-OID mapping
- Offer `ct_mapping:` sub-key completions from the codelist's declared `items[].coded_value` list

**Edge case:** Some define.yaml files omit `ct_mapping:` entirely (when raw data already matches the codelist). The LSP accepts this as valid — `ct_mapping:` is always optional when the source values already match coded_values.

### 1.6 DAG-aware diagnostics

Use `build_dag()` on the whole define.yaml to detect:

- Missing `inputs:` references (dataset not declared in this or sibling YAML)
- Topological cycles across datasets
- Orphan datasets (declared but never consumed by any other dataset)

Run this analysis on every file save (debounced 500ms). Surface as workspace-level diagnostics, not just file-level.

### 1.7 Variable lineage hover (when pipeline_dag.json exists)

When `outputs/*/pipeline_dag.json` is present (written by `build_dag(..., output_dir=...)`), the LSP enriches variable hover cards with runtime lineage:

```
TRTSDT — derived by first_date
  Sources: RFSTDTC, EXSTDTC
  Method: fleet.adam.adsl_namespace.ADSLNamespace.first_date
  [Click to open definition]
```

**Edge case:** If pipeline*dag.json is stale (older than the define.yaml mtime), show a warning badge: *"Lineage data may be outdated — re-run pipeline to refresh."\_

### 1.8 CDISC Library variable hover

One-time cache per (standard, version) pair, stored in `.fleet/ig_cache/`. On hover over a variable name (USUBJID, AVAL, etc.), show: label, type, length, core/expected status, and CDISC notes. **If `.fleet/ig_cache/` has no entry for that domain, show a "Fetch from CDISC Library" CodeLens action** rather than auto-querying (network calls should always be opt-in from the editor).

---

## Tier 2: VS Code Extension — Pipeline Intelligence for Python Files

### 2a. Pipeline DAG View

**Prerequisite:** `pipeline_dag.json` does not currently exist in the repo — it is only written when `build_dag(..., output_dir=...)` is called explicitly. The extension must first offer a "Generate DAG" action that runs `uv run python -c "from fleet import build_dag; build_dag(...)"` using paths from `study_config.yaml`. Once the JSON exists, it polls for changes on save.

**Webview panel features:**

- Render dataset nodes as a directed graph (D3 or Cytoscape.js embedded in Webview). Node types colour-coded: `raw` (grey) / `sdtm` (blue) / `adam` (green) / `send` (gold)
- Expand a node to see its `variables` dict: each column with verb, sources, method link
- "What breaks?" input box — calls `dag.impacted_by(name)` and highlights the affected subgraph
- Topological execution order displayed as a numbered overlay on each node

**Edge cases:**

- Cycles are caught by `build_dag()` itself (raises `ValueError`) — the extension catches this and shows it as an error panel notification, not a crash
- Nodes with no `variables` recorded (spec-only, not yet materialised) show a "not run" placeholder, not an empty section

### 2b. "Convert to spec-driven" Code Action

Three-pass approach:

**Pass 1 — AST parsing (instant, no I/O):**

Walk the Python AST of the selected pipeline chain. For each verb call, extract keyword arguments:

| Verb class                                | What AST gives you                       | define.yaml field                                                             |
| ----------------------------------------- | ---------------------------------------- | ----------------------------------------------------------------------------- |
| `hardcode_no_ct`, `hardcode_ct`           | `value=` literal                         | `algorithm: hardcode_no_ct`, `value:` ✅                                      |
| `assign_no_ct`, `assign_ct`, `assign_dtc` | `source=`, `ct_codelist=`, `ct_mapping=` | Full `derivation:` block ✅                                                   |
| `date`                                    | `source=`, `impute=`, `output=`          | `algorithm: date` + params ✅                                                 |
| `first_date`, `last_date`                 | `from_dataset=`, `date_col=`, `where=`   | `algorithm: derivation`, `expression: # TODO` ⚠️                              |
| `baseline`, `chg`, `pchg`                 | `aval=`, `baseline_flag=`                | `algorithm: derivation`, `depends_on:` inferred ⚠️                            |
| `derivation(expression=...)`              | expression string/expr object            | `algorithm: derivation`, `expression:` if string literal ✅ / stub if Expr ⚠️ |
| `pin(...)` + any join verb                | nothing recoverable                      | `inputs:` entry suggested, join logic as `# TODO` ❌                          |
| `treatment_emergent`, `seq`, `flag`       | verb name + args                         | `# TODO: not representable in spec` ❌                                        |

`ct_codelist=SEX` → resolved to OID `C66731` via a local lookup of `codelists.py` in the project (no API call).

**Pass 2 — CDISC Library API (one batch call per domain, cached):**

Fills the metadata fields that are invisible in code: `label`, `type`, `length`, `mandatory`, `origin`. Strategy:

- One HTTP GET per domain to the CDISC IG endpoint: `GET /mdr/sdtmig/3-4/datasets/{domain}/variables` returns all variables for the domain in a single payload
- Cache response as `.fleet/ig_cache/sdtmig-3.4/{domain}.json` — reused forever unless explicitly invalidated
- Match variable names from the pipeline against the IG response
- For non-standard variables (custom ADVS parameterization, sponsor-specific analysis variables): no IG match → emit `label: # TODO`, `type: # TODO` with a comment

**Edge case:** No CDISC API key → skip Pass 2 entirely, emit all metadata fields as `# TODO` with a note: _"Set CDISC_API_KEY to auto-populate from CDISC Library."_

**Edge case:** ADaM variables (AVAL, ADT, ABLFL) → use ADaMIG endpoint instead of SDTMIG. The extension infers the standard from the namespace in the pipeline (`.adam.*` → ADaMIG, `.sdtm` → SDTMIG).

**Pass 3 — merge and emit:**

- Variables with complete AST + IG metadata → full stanza, ready to use
- Variables with partial derivation (complex verbs) → stanza with `# TODO: fill expression` inline
- Variables not representable in spec (pin joins, treatment_emergent, seq) → full metadata stanza + `derivation:` block replaced with a prominently commented `# NOTE: derive inline after from_spec()`
- Order variables in output YAML to match the order they appear in the pipeline chain

**Completeness note:** For a typical SDTM DM pipeline (~14 variables, mostly `assign_no_ct` / `assign_ct` / `hardcode_no_ct`), the action generates a fully-populated define.yaml stanza with zero manual edits. For ADAE or ADVS with event-level verbs and joins, expect 50–60% automation with clearly marked TODOs for the rest.

### 2c. Reverse direction: define.yaml → skeleton inline pipeline

Read a define.yaml dataset block and generate a Python pipeline skeleton:

- `algorithm: hardcode_no_ct` → `.sdtm.hardcode_no_ct("DOMAIN", value="DM")`
- `algorithm: assign_ct` with `ct_codelist: C66731` → `.assign_ct("SEX", source="sex", ct_codelist=SEX, ct_mapping={...})`
- `algorithm: derivation` → `.sdtm.derivation("AVAL", expression=<expression from YAML>)` or `.adam.derivation(...)` based on standard
- `algorithm: source` → `.assign_no_ct(...)` (SDTM) or `.source(...)` (ADaM)
- Variables with `# TODO` comments → emitted as stub comments in the Python chain

Imports are auto-generated: `from examples.{study}.{standard}.codelists import SEX, RACE` based on `ct_codelist:` references found in the YAML.

### 2d. Live Validation Panel

- **CT on save:** Run `CTValidator.validate_value()` for every `assign_ct` call in the file. Surface mismatches as diagnostics
- **DatasetChecker integration:** After `to_frame()` materialises a dataset, if a define.yaml entry exists for it, run `DatasetChecker.check()` and show column mismatches, type errors, and missing required columns in the Problems panel
- **Define-XML preview:** Webview rendering of define.yaml via `DefineSpecGenerator` + the bundled `define2-1.xsl` — same output as `fleet define-xml` but live-updating on YAML save
- **TLG preview:** For a pipeline ending in `.to_html()`, "Preview Table" button renders the ARD output in a Webview panel. ARD format is {cards}-compatible — the panel can optionally show the long-format ARD alongside the formatted table for debugging

---

## Tier 3: LLM-Enhanced Features

### 3a. Fleet-Tuned Copilot Context

- **`llms.txt` injection:** The extension detects when Copilot is active and points to the project's `llms.txt` for context injection. `llms.txt` is auto-generated by `build_llms.py` via live introspection of the installed package — as Fleet grows, `llms.txt` grows automatically. No manual curation needed.
- **`copilot-instructions.md` is already in the repo** — it wires Fleet's verb grammar, codelist rules, mixin discipline, and docstring conventions into Copilot's system context. The extension's value-add is keeping it up to date when `build_llms.py --check` detects drift.
- **define.yaml grounding:** When the user asks Copilot to generate a pipeline, the extension automatically appends the relevant define.yaml stanza as a code block in the prompt. The LLM generates from the actual spec, not from training data guesses about CDISCPILOT01.

### 3b. Chat Participant `@fleet`

Full participant registration in the VS Code extension. Key commands, grounded in specific Fleet APIs:

- **`@fleet generate DM from raw_dm.csv`** — Reads raw file headers (via `load_raw_data` → `.schema`), fetches CDISC IG variable list (cached), generates a `.sdtm` chain with correct verb selection per variable type. Emits `from codelists import ...` imports automatically
- **`@fleet explain this pipeline`** — Takes selected Python code, runs AST analysis + `lineage_of()` if available, produces step-by-step walkthrough citing `VariableNode.method` for docstring links
- **`@fleet what's missing for DM submission?`** — Compares the pipeline's output columns against the IG required/expected list for the domain. Uses the same cached IG API response as the "Convert to spec" feature
- **`@fleet impacted_by ae_raw`** — Calls `dag.impacted_by("ae_raw")` on the project's DAG and presents the ordered re-run list with dataset types and file paths
- **`@fleet convert to spec`** / **`@fleet convert to inline`** — Invokes the Tier 2b code action via the chat interface, with conversational output instead of in-editor YAML insertion
- **`@fleet validate`** — Runs `ValidationService`, presents results with verb-attributed findings (from `VariableNode.method` lineage)
- **`@fleet tlg preview`** — Executes the TLG builder chain in an isolated subprocess, renders HTML, opens Webview

**Forward-compatibility:** The `@fleet` participant discovers available verbs from the project's installed Fleet package, not from a bundled list. If a new TA namespace (`df.adam.cardiac`) is added in Fleet 0.5, `@fleet generate` picks it up immediately via dynamic introspection.

### 3c. RAG from CDISC Library

- **Local vector store** (ChromaDB or SQLite-vec, shipped with the extension): Index the CDISC IG variable definitions, implementation notes, and CDISC conformance rules (from `.fleet/rules/`) as retrieved by `fleet init rules`
- **Conformance rules cache:** `fleet init rules` already downloads rules as human-readable YAML. The extension indexes these into the vector store, so `@fleet validate` explanations can cite the specific rule text
- **Community patterns:** Index pharmaverse admiral patterns (from public documentation) and map to Fleet equivalents for users migrating from R

---

## Tier 4: Workflow & Collaboration Features

### 4a. Study Explorer Sidebar (TreeView)

Root node is `study_config.yaml`. Hierarchy:

```
📁 CDISCPILOT01
├── 📋 Study Config
├── 🗄️ Raw Data (datasets/cdiscpilot01/raw/)
│   ├── dm_raw.csv (linked to → DM in DAG)
│   └── ae_raw.csv (linked to → AE in DAG)
├── 📊 SDTM
│   ├── DM  ✅  14/14 vars derived
│   ├── AE  ⚠️  10/18 vars → missing: AETOXGR, AEACN
│   └── VS  ❌  not run
├── 📈 ADaM
│   ├── ADSL ✅  22/22 vars derived
│   ├── ADVS ⚠️  3/15 vars (staged — run DM, VS first)
│   └── ADAE ❌  not started
├── 🔗 Pipeline DAG  (⚠️ stale — click to regenerate)
├── 📝 Define-XML
│   ├── SDTM define.xml  (last built: 2026-05-15)
│   └── ADaM define.xml  (not built)
├── 📊 TLG
│   ├── ae_summary.html
│   └── vs_summary.html
└── ✅ Validation Status  (last run: never)
```

**Progress tracking:** Compare define.yaml `variables:` count against `pipeline_dag.json`'s `variables` dict for each node. If `variables` dict is absent (node not yet materialised), show ❌. If variable count matches, show ✅. If partial, show ⚠️ with missing variable names in tooltip.

**Edge case:** ADSL has `depends_on` chains. When ADSL shows ⚠️, the sidebar must note _"Staged derivation: run ADSL first pass before CHG/PCHG columns are available."_ — derived from the `depends_on` graph, not from guessing.

### 4b. Spec-Code Sync Guardian

Drift detection on every Python file save:

1. Parse the `_lineage` from the last materialisation (if `pipeline_dag.json` is current)
2. For each variable in lineage, check if it has a matching entry in define.yaml
3. If a lineage variable is absent from define.yaml → yellow warning: _"MYVAR derived in code but not in spec. Push to spec?"_
4. If a define.yaml variable has no lineage entry → blue info: _"MYVAR declared in spec but not derived in this pipeline."_

**"Push to spec" quick-fix:** Inserts a generated stanza into define.yaml at the correct position (after the last variable in the dataset block). Uses Pass 1 AST analysis + Pass 2 CDISC API (if key available).

**Edge case:** Variables derived by `treatment_emergent`, `seq`, `flag` — these cannot be pushed to spec. The guardian marks them with a distinct icon: _"Inline-only derivation — spec representation not supported."_

### 4c. Test & Example Runner

- **Gutter run buttons** for pipeline chains (`.sdtm.` / `.adam.` chains ending in `.to_frame()`): materialise the chain in a subprocess and display the resulting DataFrame in a VS Code table Webview
- **Golden master diffing:** After running, diff against a saved reference output (CSV/Parquet). Highlight changed cells; link changed columns back to the `VariableNode.verb` that produced them
- **TLG preview:** For `.to_html()`, `.to_ard()`, render inline in Webview
- **ARD inspector:** For `.to_ard()` output, show both the formatted table view and the underlying long-format ARD side by side — helps users understand the {cards}-compatible structure

---

## Tier 5: Architecture & Packaging

### 5.1 Hybrid architecture (recommended)

TypeScript extension shell + Python LSP backend.

| Layer             | Responsibility                                                                                            | Language         |
| ----------------- | --------------------------------------------------------------------------------------------------------- | ---------------- |
| VS Code extension | UI: TreeView, Webview, Chat Participant, gutter icons, CodeLens                                           | TypeScript       |
| Python LSP        | Semantic logic: define.yaml validation, verb completions, DAG analysis, CDISC API                         | Python (`pygls`) |
| Fleet package     | All business logic: `build_dag()`, `lineage_of()`, `CTValidator`, `DatasetChecker`, `DefineSpecGenerator` | Python           |

**LSP discovery order** — as shipped by [`fleet-vscode`](https://github.com/RealSlimMahdi/fleet-vscode), which is now the source of truth:

1. The `fleet.server.path` setting (an explicit `fleet` executable)
2. `FLEET_LSP` env var (the worktree escape hatch)
3. `.venv/bin/fleet lsp` in the workspace root (standard `uv sync` install)
4. `uv run fleet lsp` (resolves the project environment)

The planned bundled fallback LSP was dropped: the client reports a startup failure instead of degrading to YAML-only syntax checking.

**Forward-compatibility principle:** The LSP imports Fleet dynamically at startup. It calls `importlib.import_module("fleet")` and inspects the live package for verb lists, algorithm enums, namespace exports, and Pydantic model fields. When Fleet releases a new version, the LSP capabilities update automatically without a VS Code extension update.

### 5.2 What to hardcode vs. discover dynamically

| Item                        | Approach                                                          | Reason                               |
| --------------------------- | ----------------------------------------------------------------- | ------------------------------------ |
| Verb names per namespace    | Discover via `inspect.getmembers(namespace_class)` at LSP startup | Grows with every Fleet release       |
| Algorithm enum values       | Import `SDTMAlgorithm`, `ADAMAlgorithm`                           | Enum-driven — safe to import         |
| define.yaml JSON schema     | Read `define_spec_schema.json` bundled with Fleet package         | Versioned with Fleet                 |
| Pydantic field requirements | Import model and call `.model_fields`                             | Zero duplication of constraint logic |
| Codelist OIDs               | Read `codelists.py` at workspace path                             | Project-specific, not in Fleet core  |
| CDISC IG metadata           | Cache in `.fleet/ig_cache/` — fetch once per domain               | API-rate-limited, slow               |
| CT term values              | Import `CTValidator` and call `.get_valid_values()`               | Always in sync with loaded CT        |
| Namespace registry          | Read `fleet.__all__` or `fleet` module exports                    | Discovers new TAs automatically      |

### 5.3 MCP Server

Expose Fleet as an MCP server. Each tool maps directly to an existing public API:

| MCP Tool                                         | Fleet API                                | Notes                        |
| ------------------------------------------------ | ---------------------------------------- | ---------------------------- |
| `fleet_execution_order(spec_paths)`              | `build_dag(*paths).execution_order()`    | Returns ordered list         |
| `fleet_impacted_by(spec_paths, node)`            | `dag.impacted_by(node)`                  | Returns re-run list          |
| `fleet_inspect_lineage(dag_json_path, dataset)`  | Parse pipeline_dag.json                  | Returns VariableNode records |
| `fleet_validate(dataset_path, domain)`           | `ValidationService.run()`                | Returns ValidationResult     |
| `fleet_ct_terms(codelist_id)`                    | `CTValidator.get_valid_values(codelist)` | Returns valid terms          |
| `fleet_cdisc_lookup(variable, domain)`           | Cached IG API response                   | Returns label/type/core      |
| `fleet_tlg_preview(ard_json)`                    | `render_html(TableModel)`                | Returns HTML string          |
| `fleet_dataset_check(parquet_path, define_yaml)` | `DatasetChecker.check()`                 | Returns CheckResult          |

The MCP server runs as `fleet mcp --stdio` — a new CLI subcommand. It imports Fleet directly (same process), so it's always version-locked.

### 5.4 Packaging

- VS Code extension: `fleet-cdisc` on the Marketplace — TypeScript, lightweight shell
- Python LSP: `fleet-cdisc[lsp]` — adds only `pygls` (≤ 50KB) to Fleet's existing deps
- MCP server: `fleet mcp --stdio` CLI command — no extra deps beyond Fleet core
- Extension auto-discovers the LSP/MCP server via the workspace `.venv` or `uv run fleet`

---

## Implementation Sequence

1. **`fleet lsp --stdio` CLI command** — the foundation everything else builds on. Ships with `pygls` in the `lsp` extra. Provides: define.yaml schema validation, algorithm autocomplete, codelist hover, depends_on cycle detection. Scope: ~500 LOC.

2. **VS Code extension shell** — TypeScript wrapper that launches `fleet lsp`, registers the extension on `.yaml` files in `examples/` directories, and provides the DAG Webview panel. Scope: ~300 LOC TypeScript + LSP launch code.

3. **`fleet mcp --stdio` CLI command** — expose the 8 tools above. Ships in Fleet core (no extra deps). Immediately amplifies every MCP-compatible AI. Scope: ~200 LOC.

4. **"Convert to spec-driven" code action** — AST parsing + CDISC API caching. The hardest feature, but the most valuable for spec-driven workflow adoption. Scope: ~600 LOC (AST walker + IG API client + YAML emitter).

5. **`@fleet` Chat Participant** — registered in the VS Code extension. Grounded in: `llms.txt`, project define.yaml, `pipeline_dag.json` lineage. Scope: ~400 LOC TypeScript (mostly prompt construction and result formatting).

6. **Study Explorer Sidebar** — TreeView wiring `study_config.yaml` → define.yaml → `pipeline_dag.json`. Scope: ~300 LOC TypeScript.

7. **Spec-Code Sync Guardian** — file-save listener + lineage comparison + quick-fix CodeAction. Scope: ~200 LOC Python in LSP + ~100 LOC TypeScript.
