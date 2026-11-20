---
description: Pre-alpha release readiness assessment for fleet-cdisc — packaging, CI, docs topology, repo hygiene, and the ordered remediation plan
---

> **Status (2026-08-24): assessment complete, remediation not started.**
> Every finding below was reproduced against the working tree at commit `bd85276`
> (`main`). Items marked **[verified]** were executed or read directly; nothing here
> is inferred. Check items off as they land.

# Fleet — Pre-Alpha Release Readiness Assessment

## 0. Verdict

**The engine is ready. The package is not.**

Fleet's code quality gates are all green and its test backbone is substantial. What
blocks a credible public pre-alpha is entirely in the *distribution and presentation*
layer: the PyPI artifact is 5 months stale with a broken extras graph and a blank
project page, CI never executes the example scripts that the contributor docs call
the primary regression gate, and the repository root carries ~3,000 lines of
half-superseded narrative and planning markdown that a first-time visitor will hit
before they reach the real documentation site.

None of these are hard to fix. All of them are visible to the first person who runs
`pip install fleet-cdisc`.

| Area | State | Blocking? |
|---|---|---|
| Code quality gates | 🟢 all green | No |
| Test suite | 🟢 2021 passing | No |
| Examples | 🟢 9/9 passing locally | No |
| Docs site build | 🟢 builds, 1 broken anchor | No |
| **PyPI artifact** | 🔴 stale + broken extras + blank page | **Yes** |
| **Packaging metadata** | 🔴 no `readme`, 1/5 URLs | **Yes** |
| **CI coverage of examples** | 🔴 not wired | **Yes** |
| **Versioning story** | 🟠 contradicts `AGENTS.md` | Yes |
| Root markdown topology | 🟠 duplicated / stale | Yes (credibility) |
| OSS community files | 🟠 4 missing | No |
| Committed artifacts | 🟡 minor | No |

---

## 1. Verified green — do not re-litigate these

Executed locally on 2026-08-24, Python 3.12, `uv`:

| Gate | Command | Result |
|---|---|---|
| Lint | `uv run ruff check` | **[verified]** `All checks passed!` |
| Format | `uv run ruff format --check` | **[verified]** 205 files already formatted |
| Doc code blocks | `uv run blacken-docs --check --line-length 100 $(find docs -name '*.md')` | **[verified]** exit 0 |
| Tests | `uv run pytest` | **[verified]** **2021 passed**, 33 warnings, 9.5s |
| llms.txt / README drift | `uv run python scripts/build_llms.py --check` | **[verified]** up to date |
| Docs site | `uv run mkdocs build --strict` | **[verified]** builds in 13.05s |
| Examples | all 9 scripts in `examples/` | **[verified]** 9/9 exit 0 |

Note the examples number: `AGENTS.md` lists **5** required examples, but there are
**9** runnable scripts and all 9 pass. `adlb_grading_example.py`, `r2r_ae_example.py`,
`tlg_ae_example.py`, `tlg_vs_example.py` are unlisted and therefore unprotected.

Also confirmed healthy:

- `src/fleet/py.typed` exists (PEP 561) — the advertised IDE typing story is real.
- Test skips are all conditional on optional extras (`dsjson`, `python-pptx`,
  `jsonschema`). No `xfail`, no dead tests.
- CI's Python matrix (3.12 / 3.13 / 3.14) matches the `pyproject.toml` classifiers.
- CI *does* run `blacken-docs` and `gen_cli_docs.py --check` — the earlier assumption
  that these were missing is wrong.

### Correction to an earlier draft finding

An automated pass flagged `.env` as "tracked in git with an exposed secret." **This is
false.** **[verified]** `git ls-files .env` → 0 results, and `git log --all -- .env` →
empty. The file is local-only and correctly gitignored. No secret is in the repository
or its history.

Separate, minor, and worth doing anyway: the key value was read out of the local `.env`
into an assistant transcript during this assessment. Rotating `CDISC_API_KEY` at
[library.cdisc.org](https://library.cdisc.org) is cheap insurance. Not a release blocker.

---

## 2. P0 — Blockers

### 2.1 The published PyPI package is broken and stale

**[verified]** via `https://pypi.org/pypi/fleet-cdisc/json`:

- Published version **0.1.0**, uploaded **2026-03-17** — roughly five months of work
  is not in the artifact users install.
- `provides_extra: ["all", "dev", "docs", "io"]`. The published package is missing
  `tlg-pdf`, `tlg-pptx`, `migrate`, `watch`, `lsp`, `mcp`.
- **Broken dependency graph:** `requires_dist` contains `fleet[io]; extra == "all"`.
  That resolves to the unrelated PyPI project named `fleet`, not `fleet-cdisc`. Anyone
  running `pip install fleet-cdisc[all]` today pulls a foreign package. Current
  [pyproject.toml](pyproject.toml#L66-L76) has this fixed to `fleet-cdisc[io]`, but the
  fix has never shipped.
- `description: ""` and `description_content_type: null` → **the PyPI project page is
  blank.** Root cause below.

**Action:** yank or replace 0.1.0. Do not publish again until §2.2 and §2.3 land.

### 2.2 `[project]` has no `readme` key — PyPI page renders empty

**[verified]** `grep -nE "^readme" pyproject.toml` → no match.
[pyproject.toml](pyproject.toml#L1-L18) declares `name`, `version`, `description`,
`requires-python`, `license`, `authors`, `keywords`, `classifiers` — and no `readme`.

Hatchling does **not** auto-attach `README.md` to core metadata without it. This is the
single highest-leverage one-line fix in the repo: a 553-line README exists and is
currently invisible on the package page.

```toml
[project]
readme = "README.md"
```

While there: [pyproject.toml:6](pyproject.toml#L6) uses the deprecated table form
`license = { text = "MIT" }`. Modern form is `license = "MIT"` plus
`license-files = ["LICENSE"]`.

### 2.3 `[project.urls]` has 1 of 5 entries

**[verified]** [pyproject.toml:97-98](pyproject.toml#L97-L98) contains only
`Repository`. The docs site, issue tracker, and changelog are unreachable from PyPI.

```toml
[project.urls]
Homepage = "https://realslimmahdi.github.io/fleet-cdisc/"
Documentation = "https://realslimmahdi.github.io/fleet-cdisc/"
Repository = "https://github.com/RealSlimMahdi/fleet-cdisc"
Issues = "https://github.com/RealSlimMahdi/fleet-cdisc/issues"
Changelog = "https://realslimmahdi.github.io/fleet-cdisc/changelog/"
```

### 2.4 CI never runs the examples

**[verified]** [.github/workflows/ci.yml](.github/workflows/ci.yml#L30-L52) runs ruff,
blacken-docs, `build_llms.py --check`, `gen_cli_docs.py --check`, and pytest. There is
**no step that executes anything in `examples/`.**

This directly contradicts [AGENTS.md](AGENTS.md#L22-L38) ("ALL must pass after any
change") and [CONTRIBUTING.md](CONTRIBUTING.md#L134-L160), which both treat the examples
as a mandatory gate. The examples are the most end-to-end coverage Fleet has — they
exercise real SDTM→ADaM→TLG→Define-XML paths that unit tests stub out — and nothing
enforces them.

Add after the pytest step, on the 3.12 leg only:

```yaml
      - name: Run examples
        if: matrix.python-version == '3.12'
        run: |
          for f in examples/*.py; do
            [ "$(basename "$f")" = "__init__.py" ] && continue
            echo "::group::$f"; uv run python "$f" || exit 1; echo "::endgroup::"
          done
```

Globbing rather than listing keeps this from rotting the way the 5-of-9 list in
`AGENTS.md` already has. Update `AGENTS.md` to say "every script in `examples/`."

---

## 3. P1 — High

### 3.1 The versioning story contradicts itself

[AGENTS.md](AGENTS.md#L62-L64) states: *"Version comes from git tags — never edit
version strings manually."*

**[verified]** reality:

- [pyproject.toml:2](pyproject.toml#L2) → `version = "0.1.0"`, hardcoded. No
  `dynamic = ["version"]`, no `hatch-vcs` in `build-system.requires`
  ([pyproject.toml:107-109](pyproject.toml#L107-L109)).
- [src/fleet/_version.py](src/fleet/_version.py#L3) → `__version__ = "0.1.0"`,
  a second hardcoded copy.
- [.github/workflows/publish.yml](.github/workflows/publish.yml#L26-L40) `sed`-patches
  **both** files at publish time.
- `git tag` → **empty**. No tag has ever existed, so the `v*` → PyPI path in
  publish.yml has never executed. The 0.1.0 on PyPI was produced some other way.

So the documented policy is aspirational, the implementation is string-substitution in
CI, and the mechanism is untested. Pick one and make it true:

**Recommended — adopt `hatch-vcs`:**

```toml
[build-system]
requires = ["hatchling", "hatch-vcs"]

[project]
dynamic = ["version"]

[tool.hatch.version]
source = "vcs"

[tool.hatch.build.hooks.vcs]
version-file = "src/fleet/_version.py"
```

Then delete both `sed` steps from publish.yml, add `src/fleet/_version.py` to
`.gitignore`, and make `AGENTS.md` accurate. Requires `fetch-depth: 0` on the checkout
step so tags are visible.

### 3.2 `publish.yml` uses long-lived API tokens

**[verified]** [.github/workflows/publish.yml](.github/workflows/publish.yml#L50-L64)
authenticates with `secrets.PYPI_API_TOKEN` / `secrets.TEST_PYPI_API_TOKEN` via twine.

PyPI Trusted Publishing (OIDC) removes the stored credential entirely. For a package
that will be installed inside pharma environments, "no long-lived token in CI" is worth
the 15 minutes.

```yaml
    permissions:
      id-token: write
    steps:
      # ...
      - uses: pypa/gh-action-pypi-publish@release/v1
```

Also add a GitHub Environment with a required reviewer on the PyPI job, so a stray tag
push cannot ship.

### 3.3 Root markdown topology — the question that started this

Nine markdown files sit at the repository root. **[verified]** none of `GUIDE.md`,
`STRUCTURE.md`, or the four `*-PLAN`/`*-REVIEW` documents appear in
[mkdocs.yml](mkdocs.yml) navigation. They are invisible on the docs site and
unavoidable on the GitHub landing page — exactly backwards.

| File | Lines | Verdict | Action |
|---|---:|---|---|
| `README.md` | 553 | **Update** | Add `lsp` / `mcp` extras and CLI commands (§3.4) |
| `AGENTS.md` | 84 | **Update** | Fix version claim (§3.1); examples = all of `examples/` (§2.4) |
| `CONTRIBUTING.md` | 235 | **Minor update** | [L161](CONTRIBUTING.md#L161) tells contributors to update `GUIDE.md`; retarget to `docs/` |
| `LICENSE` | — | **Keep** | MIT, complete |
| `GUIDE.md` | 1814 | **Merge into `docs/`, then delete** | See below |
| `STRUCTURE.md` | 414 | **Move to `docs/`** | Stale (§3.5); belongs in nav |
| `BRIDGE-PLAN.md` | 327 | **Move to `.github/prompts/`** | Self-described "design, pre-implementation" |
| `EXTENSION-PLAN.md` | 323 | **Move to `.github/prompts/`** | Self-described "approved design, not yet implemented" |
| `DEFINE-METHODS-PLAN.md` | 291 | **Move to `.github/prompts/`** | Self-described "Status: implemented" — historical record |
| `DX-REVIEW.md` | 383 | **Move to `.github/prompts/`** | Backlog document, already cross-references `.github/prompts/` |

The four planning documents are precisely what `.github/prompts/*.prompt.md` is for,
and the convention is already established in this repo — every existing file there
carries a `> **Status (date): …**` header. Rename on move:

```
BRIDGE-PLAN.md          → .github/prompts/plan-interactiveTlgBridge.prompt.md
EXTENSION-PLAN.md       → .github/prompts/plan-companyExtensions.prompt.md
DEFINE-METHODS-PLAN.md  → .github/prompts/plan-defineMethodsConformance.prompt.md
DX-REVIEW.md            → .github/prompts/review-developerExperience.prompt.md
```

Use `git mv` to preserve history, and add a `> **Status (2026-08): …**` line to
`plan-cosmosMappingPrediction` and `plan-zensicalMigration`, which currently lack one.

**On `GUIDE.md` specifically.** It is 1814 lines and roughly 70% duplicates
`docs/getting-started/*` and `docs/concepts/*`, with divergence that actively misleads:

- **[verified]** [GUIDE.md:11](GUIDE.md#L11) — *"CDISC Library API key — **required**
  for CLI bootstrapping and codelist generation."* But
  [GUIDE.md:621](GUIDE.md#L621) in the same file says TDD verbs *"run offline — no CDISC
  Library API key required,"* and `docs/getting-started/quickstart.md` demonstrates a
  complete SDTM pipeline with no key at all. The front-page prerequisite is a
  self-inflicted adoption barrier.
- **[verified]** [GUIDE.md:17-20](GUIDE.md#L17-L20) — a *"From TestPyPI (pre-release)"*
  install section pointing at `test.pypi.org`, while README and
  `docs/getting-started/installation.md` both say `uv add fleet-cdisc`. Three
  install paths, one repo.

Genuinely unique and worth keeping: **Part 13** (Define-XML depth), **Part 15**
(`.inspect()` / `.explain()` / `.trail()` debugging), **Part 18** (`@derivation`
decorator pattern). Extract those into `docs/concepts/` pages, add them to
`mkdocs.yml` nav, then delete `GUIDE.md`.

Do this carefully: **[verified]** [tests/unit/test_docs_examples.py:10](tests/unit/test_docs_examples.py#L10)
parses and executes code blocks from `GUIDE.md`, and
[.github/workflows/docs.yml](.github/workflows/docs.yml#L17) watches it. Repoint both at
the new locations in the same commit, or the deletion breaks CI.

### 3.4 README omits shipped features

**[verified]** `grep -nE "\[lsp\]|\[mcp\]|fleet lsp|fleet mcp" README.md` → **no matches.**

Both extras exist in [pyproject.toml](pyproject.toml#L56-L64) and both CLI commands are
live — **[verified]** `fleet --help` lists 19 subcommands including `mcp` and `lsp`.
README also omits `new`, `add-acrf`, `check-rule`, `uninstall-engine`, `doctor`, and
`derivation`.

The LSP and MCP servers plus the VS Code extension are among the most
differentiating things Fleet has for a pre-alpha announcement, and the README does not
mention them once.

### 3.5 `STRUCTURE.md` is missing three modules

**[verified]** `src/fleet/` contains `lsp_server.py`, `mcp_server.py`, and a `review/`
directory. `grep -nEi "lsp_server|mcp_server|review/" STRUCTURE.md` → **no matches.**

Also: `src/fleet/review/` **[verified]** contains only `__pycache__` — no `__init__.py`,
no source. It is a stale local artifact from a deleted module. Remove the directory
locally; it is not tracked.

Additionally, `df.adam.pk` and `df.adam.tte` appear in the namespace table but get no
detailed section, unlike every other therapeutic-area namespace.

---

## 4. P2 — Medium

### 4.1 Committed build/output artifacts

**[verified]** via `git ls-files`:

| Path | Tracked | Assessment |
|---|---|---|
| `outputs/cdiscpilot01/*.xml`, `.pdf`, `.xsl` | **4 files tracked** | **Intentional** — `test_define_semantics.py` asserts these match generated output, per [DEFINE-METHODS-PLAN.md](DEFINE-METHODS-PLAN.md#L5-L12). Keep, but the `outputs/` name implies scratch space. Move to `tests/golden/` |
| `benchmark/data/*.csv` (3 files) | **tracked** | Timestamped filenames (`ae_raw_20260418_214047.csv`) suggest a one-off dump, not a fixture. Confirm intent or generate them |
| `tmp_lineage_probe.py` | **tracked** | Scratch file at repo root. Delete or move to `scripts/` |
| `.env`, `dist/`, `site/`, `tmp-clones/`, `my_rules/`, `.claude/` | not tracked | Correct (`papers/` was here too; it moved to the fleet-talks repository on 2026-11-09) |

447 tracked files, 30 MB `.git`. Healthy.

### 4.2 Missing OSS community files

**[verified]** absent: `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CITATION.cff`,
`.github/pull_request_template.md`.

`.github/ISSUE_TEMPLATE/` **[verified]** contains only `feature_request.md` and
`feature_request.yml`. **There is no bug report template** — inverted priorities for a
pre-alpha, where bug reports are the entire point.

`CHANGELOG.md` does not exist at root; [docs/changelog.md](docs/changelog.md) holds real,
substantive content under an `Unreleased` heading. That is fine — just add the
`Changelog` project URL (§2.3) and cut a `## 0.2.0a1` section at release.

`CITATION.cff` matters more than usual here: the target audience is pharma
biometrics, and the PHUSE paper OS12 (in the sibling repository fleet-talks) shows that academic citation is clearly in scope.

### 4.3 No coverage floor

**[verified]** [pyproject.toml:126-128](pyproject.toml#L126-L128) configures
`[tool.coverage.run]` but sets no threshold, and CI uploads to Codecov with
`fail_ci_if_error: false`. With 2021 tests the number is probably good; measure it, then
set `fail_under` slightly below the current value so it ratchets rather than blocks.

### 4.4 One broken docs anchor

**[verified]** from `mkdocs build`: `docs/examples/adtte_pipeline.md` links to
`../api/ta.md#time-to-event--dfadamtte`, and that anchor does not exist in
`docs/api/ta.md`.

`mkdocs build --strict` exits 0 today because this is emitted at INFO level. Set
`validation.links.anchors: warn` (or `error`) in [mkdocs.yml](mkdocs.yml) so link rot is
caught rather than logged.

---

## 5. Execution order

Ordered so each step is independently mergeable and nothing breaks CI mid-flight.

**Stage 1 — unblock the artifact** (P0, small diffs, no behavioural risk)

- [ ] Add `readme = "README.md"` to `[project]`; modernise `license` / `license-files`
- [ ] Expand `[project.urls]` to 5 entries
- [ ] Add the examples loop to `ci.yml`; update `AGENTS.md` to "every script in `examples/`"
- [ ] Verify the built wheel: `uv build && uv run twine check dist/*`

**Stage 2 — make the release mechanism trustworthy**

- [ ] Adopt `hatch-vcs`; delete the `sed` steps from `publish.yml`; `fetch-depth: 0`
- [ ] Switch to Trusted Publishing; add a protected environment on the PyPI job
- [ ] Dry-run end-to-end against TestPyPI from `devel` before tagging anything

**Stage 3 — fix the front door**

- [ ] README: add `lsp` / `mcp` extras, the missing CLI commands, and an explicit
      *"pre-alpha, API may change"* banner
- [ ] Remove the TestPyPI section and the "API key required" prerequisite from `GUIDE.md`
- [ ] `git mv` the four plan/review docs into `.github/prompts/` with status headers
- [ ] Extract GUIDE Parts 13 / 15 / 18 into `docs/concepts/`; repoint
      `test_docs_examples.py` and `docs.yml`; delete `GUIDE.md`
- [ ] Move `STRUCTURE.md` into `docs/`, add to nav, document `lsp_server` / `mcp_server`
      and the PK / TTE namespaces
- [ ] Retarget [CONTRIBUTING.md:161](CONTRIBUTING.md#L161) away from `GUIDE.md`

**Stage 4 — community surface**

- [ ] `SECURITY.md`, `CODE_OF_CONDUCT.md`, `CITATION.cff`, PR template
- [ ] **Bug report** issue template
- [ ] Cut `## 0.2.0a1` in `docs/changelog.md`

**Stage 5 — hygiene**

- [ ] Delete `tmp_lineage_probe.py` and the empty `src/fleet/review/`
- [ ] Decide on `benchmark/data/*.csv`; relocate golden `outputs/` to `tests/golden/`
- [ ] `mkdocs.yml`: `validation.links.anchors: warn`; fix the ADTTE anchor
- [ ] Measure coverage, set a ratcheting `fail_under`
- [ ] Rotate `CDISC_API_KEY` (precautionary, see §1)

**Stage 6 — ship**

- [ ] Version `0.2.0a1` — the alpha suffix sets expectations that `0.1.0` did not
- [ ] Tag `v0.2.0a1`, confirm the PyPI page renders the README and lists all 8 extras
- [ ] `pip install fleet-cdisc[all]` in a clean venv and run one example

---

## 6. What is genuinely strong

Worth saying plainly, because the list above is all problems: 2021 passing tests, nine
working end-to-end examples, a clean lint record across 205 files, generated-artifact
drift checks for both `llms.txt` and the CLI docs, a shipped LSP **and** MCP server, a
`py.typed` marker backing the typing claims, and a docs site that builds strict.

The gap between this repository's engineering quality and its packaging quality is the
single largest thing to close before anyone outside sees it.
