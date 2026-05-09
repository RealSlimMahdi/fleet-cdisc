# Plan: Migrate Documentation from MkDocs Material to Zensical

## TL;DR
Migrate Fleet's documentation from MkDocs Material to Zensical using the new `zensical.toml` config format with the modern theme variant. Add Google Analytics 4, front-matter tags, and Giscus comments. Convert 2 Jupyter notebooks to Markdown. Replace `mike` with Zensical's fork. Keep `build_llms.py` for LLM context generation. Continue deploying to GitHub Pages.

---

## Current State Analysis

### What we have (MkDocs Material)
- **Config:** `mkdocs.yml` with Material for MkDocs theme
- **Plugins (6):** search, mkdocstrings[python], mkdocs-jupyter, git-revision-date-localized, mkdocs-llmstxt, mike
- **Markdown extensions (12):** admonition, details, emoji, superfences (mermaid), highlight, inlinehilite, tabbed, snippets, tables, attr_list, md_in_html, toc
- **API docs:** 12 pages using `:::` mkdocstrings directives across `docs/api/`
- **Notebooks:** 2 pre-rendered `.ipynb` files in `docs/examples/`
- **Theme features:** Navigation tabs (sticky), search (highlight+suggest), code copy/annotate, dark/light toggle, back-to-top
- **Versioning:** `mike>=2.1` from PyPI with `dev` + release tag deployment
- **CI/CD:** `.github/workflows/docs.yml` — deploys via mike to GitHub Pages
- **Dependencies (pyproject.toml `[docs]`):** mkdocs-material>=9.5, mkdocstrings[python]>=0.25, mkdocs-jupyter>=0.25, mkdocs-git-revision-date-localized-plugin>=1.2, mkdocs-llmstxt>=0.2, mike>=2.1

### What Zensical provides natively (no plugins needed)
- Search (Disco engine) — replaces search plugin
- Tags — built-in with front-matter `tags:` support
- Google Analytics 4 — native `extra.analytics` config
- Feedback widget — native ("Was this page helpful?")
- All current Markdown extensions — supported out of the box with defaults enabled
- Dark/light theme toggle, navigation tabs, code copy, back-to-top — all compatible
- Modern or classic theme variant

### Compatibility gaps / risks

| Current Plugin | Zensical Status | Migration Strategy |
|---|---|---|
| **search** | ✅ Built-in (Disco) | Drop plugin, use built-in |
| **mkdocstrings** | ⚠️ Tier 1, preliminary support | Install `mkdocstrings-python` separately. configure in `zensical.toml`. Minor risk: backlinks not yet supported |
| **mkdocs-jupyter** | ❌ Not supported | **Convert 2 notebooks to Markdown** |
| **git-revision-date-localized** | ⚠️ Tier 2, not yet available | **Drop for now** — Zensical has built-in revisioning on roadmap. Can add back later |
| **mkdocs-llmstxt** | ❌ Not in plugin list | **Keep `scripts/build_llms.py`** — already exists, runs independently |
| **mike** | ⚠️ Tier 1, use Zensical fork | Replace PyPI `mike>=2.1` with `git+https://github.com/squidfunk/mike.git` |

---

## Steps

### Phase 1: Preparation (no breaking changes yet)

1. **Convert Jupyter notebooks to Markdown**
   - Convert `docs/examples/01_code_driven_pipeline.ipynb` → `docs/examples/01_code_driven_pipeline.md`
   - Convert `docs/examples/02_spec_driven_pipeline.ipynb` → `docs/examples/02_spec_driven_pipeline.md`
   - Preserve all code cells as fenced code blocks and outputs as text/images
   - Use `jupyter nbconvert --to markdown` then clean up formatting
   - Update nav references in config to point to `.md` files instead of `.ipynb`

2. **Set up Giscus on the repository**
   - Install Giscus GitHub App on `fleet-cdisc` repo (manual step — user action)
   - Enable GitHub Discussions on the repo (manual step — user action)
   - Visit https://giscus.app/ to generate the integration snippet with `data-mapping="pathname"` and `data-reactions-enabled="1"`
   - Record the `data-repo-id`, `data-category`, and `data-category-id` values

3. **Create Google Analytics 4 property** (manual step — user action)
   - Create GA4 property at https://analytics.google.com/
   - Obtain the `G-XXXXXXXXXX` measurement ID

### Phase 2: Create Zensical Configuration

4. **Create `zensical.toml`** — translate `mkdocs.yml` to TOML format
   - Map all `mkdocs.yml` settings to `[project]` scope
   - Configure theme variant as `modern`
   - Set up color scheme with palette toggle (grey/teal light, teal/cyan dark)
   - Configure navigation features: tabs, sticky tabs, sections, expand, top, search highlight/suggest, code copy/annotate, linked tabs
   - Configure logo, favicon, fonts (Roboto/Roboto Mono)
   - Configure repo URL and edit URI
   - Markdown extensions: use Zensical defaults (which cover all 12 current extensions + more). Only override mermaid custom fence and toc permalink
   - Configure mkdocstrings plugin under `[project.plugins.mkdocstrings]` with Google docstrings, `show_source: true`, `paths = ["src"]`, existing handler options
   - Configure analytics: `[project.extra.analytics]` with `provider = "google"` and `property = "G-XXXXXXXXXX"` (placeholder until user gets GA ID)
   - Configure version provider: `[project.extra.version]` with `provider = "mike"`, `default = "dev"`
   - Set up nav structure (identical to current)
   - Configure feedback widget under `[project.extra.analytics.feedback]`

5. **Add tags to key documentation pages**
   - Add front-matter `tags:` to documentation pages. Suggested taxonomy:
     - `SDTM`, `ADaM`, `ADSL`, `OCCDS` — domain-specific pages
     - `API`, `CLI`, `Pipeline` — feature categories
     - `Getting Started`, `Example`, `Concept` — content types
     - `CDISC`, `Controlled Terminology`, `Define-XML` — standards
   - Tags show up in search results automatically

6. **Create Giscus theme extension override**
   - Create `overrides/partials/comments.html` with the Giscus snippet
   - Include palette-aware theme switching (light ↔ transparent_dark)
   - Configure `custom_dir: overrides` in `zensical.toml`
   - Comments enabled per-page via `comments: true` in front-matter
   - Add `comments: true` to selected pages (API reference, concepts, examples)

### Phase 3: Update Dependencies & CI

7. **Update `pyproject.toml` dependencies**
   - Replace docs extras:
     - Remove: `mkdocs-material>=9.5`, `mkdocs-jupyter>=0.25`, `mkdocs-git-revision-date-localized-plugin>=1.2`, `mkdocs-llmstxt>=0.2`, `mike>=2.1`
     - Add: `zensical>=0.0.33`, `mkdocstrings[python]>=0.25`, `mike @ git+https://github.com/squidfunk/mike.git`
   - Keep `mkdocstrings[python]>=0.25` (still needed as external install)

8. **Update `.github/workflows/docs.yml`**
   - Replace `uv run mkdocs build` → `uv run zensical build`
   - Replace `uv run mkdocs serve` → `uv run zensical serve`
   - Mike commands stay the same (fork is CLI-compatible)
   - Update path triggers: add `zensical.toml`, keep `docs/**`
   - Install mike from git in CI: `uv pip install git+https://github.com/squidfunk/mike.git`
   - Verify `fetch-depth: 0` still present (needed for git-based features)

9. **Update build/serve commands in project documentation**
   - Update `copilot-instructions.md` §3: `uv run zensical serve`, `uv run zensical build`
   - Update `GUIDE.md` if it references mkdocs commands
   - Update `docs/getting-started/installation.md` if it mentions mkdocs serve

### Phase 4: Cleanup & Verification

10. **Remove old `mkdocs.yml`** (after confirming zensical.toml works)
    - Delete `mkdocs.yml`
    - Remove `site/` from `.gitignore` if present (Zensical uses same default)

11. **Verify build locally**
    - `uv sync --extra docs`
    - `uv run zensical build --clean`
    - Verify: all pages render, API docs generate, search works, mermaid diagrams render, code blocks have copy button, navigation tabs work, dark/light toggle works
    - `uv run zensical serve` — check local preview
    - Verify Giscus comments appear on pages with `comments: true`
    - Verify tags render on tagged pages and appear in search
    - Verify GA tracking code is in page HTML source

12. **Run full project validation suite**
    - `uv run pytest` — tests still pass
    - `uv run ruff check && uv run ruff format --check` — lint clean
    - All example scripts still run
    - `uv run python scripts/build_llms.py --check` — llms.txt still valid

---

## Relevant Files

- `mkdocs.yml` — current config to translate (then delete)
- `pyproject.toml` — update `[project.optional-dependencies.docs]`
- `.github/workflows/docs.yml` — update build/deploy commands
- `.github/copilot-instructions.md` — update §3 build/serve commands
- `docs/examples/01_code_driven_pipeline.ipynb` — convert to .md
- `docs/examples/02_spec_driven_pipeline.ipynb` — convert to .md
- `docs/api/*.md` — verify mkdocstrings `:::` directives still work (no changes expected)
- All `docs/**/*.md` — add front-matter tags to selected pages
- `GUIDE.md`, `STRUCTURE.md` — update if they reference mkdocs

### New files to create
- `zensical.toml` — main configuration
- `overrides/partials/comments.html` — Giscus integration

---

## Verification Checklist

- [ ] `uv sync --extra docs` completes without errors
- [ ] `uv run zensical build --clean` completes with zero ERROR lines
- [ ] `uv run zensical serve` — local preview: all pages accessible, navigation works, search works
- [ ] API doc pages (`docs/api/*.md`) render correctly with auto-generated Python docs
- [ ] Converted notebook pages display code/output correctly
- [ ] Dark/light theme toggle works, Giscus theme syncs with toggle
- [ ] Tags appear on tagged pages and are searchable
- [ ] Google Analytics snippet present in HTML `<head>` (inspect page source)
- [ ] Giscus comment widget loads on pages with `comments: true`
- [ ] `uv run mike deploy --push dev` succeeds in CI (test with a dry run first)
- [ ] Full project validation: `uv run pytest`, `uv run ruff check`, all example scripts

---

## Decisions

- **Config format:** `zensical.toml` (modern, recommended)
- **Theme variant:** `modern` (new Zensical design)
- **Notebooks:** Convert to Markdown (mkdocs-jupyter not supported)
- **git-revision-date-localized:** Dropped for now (Tier 2, not yet available). Zensical has built-in revisioning on roadmap
- **llms.txt:** Keep `scripts/build_llms.py` (runs independently of doc builder)
- **Versioning:** Zensical's mike fork from GitHub
- **Giscus repo:** `fleet-cdisc` (same repo)
- **GA4:** User needs to create property (no ID yet)
- **Deployment:** GitHub Pages (unchanged)
- **Tags taxonomy:** SDTM, ADaM, ADSL, OCCDS, API, CLI, Pipeline, Getting Started, Example, Concept, CDISC, Controlled Terminology, Define-XML

## Risks & Considerations

1. **Zensical is alpha software (v0.0.33)** — Some features are in flux. The mkdocstrings integration is "preliminary" (backlinks not supported). Monitor Zensical releases for breaking changes. Consider pinning to a specific version.
2. **git-revision-date-localized loss** — Pages will no longer show "Last updated" dates. This can be restored when Zensical ships native revisioning or the Tier 2 plugin is supported.
3. **mike fork instability** — Zensical's mike fork must be installed from GitHub (not PyPI). This adds a git dependency to CI. Native versioning is on Zensical's roadmap, at which point mike can be dropped entirely.
