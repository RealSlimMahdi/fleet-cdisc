# Plan: SDTM Mapping Prediction via COSMOS Enrichment + Column Matching

**TL;DR**: Enrich `fleet init define` with CDISC COSMOS metadata (Biomedical Concepts + Dataset Specializations) surfaced as YAML comments, then build a lightweight column matcher using rapidfuzz + Polars (no pandas). LLM deferred to Phase 3.

---

## Phase 1: COSMOS Enrichment of `fleet init define`

**Steps**:

1. **Verify COSMOS API access** — probe `GET /api/cosmos/v2/mdr/specializations/sdtm/datasetspecializations?domain=VS` with existing `.env` API key. First action, blocks everything.

2. **Extend `CDISCClient`** with 4 COSMOS methods (_parallel with step 3_):
   - `get_sdtm_specializations(domain)` — list specializations per domain
   - `get_sdtm_specialization(spec_id)` — variable-level detail (originType, assignedTerm, codelist)
   - `get_biomedical_concepts()` — list BCs
   - `get_biomedical_concept(concept_id)` — detail (synonyms, definition, categories)

3. **Create `src/fleet/core/cosmos.py`** — Pydantic models for COSMOS responses + `COSMOSResolver` class (_parallel with step 2_)

4. **Add response caching** — JSON files at `~/.fleet/cache/cosmos/`, 7-day TTL. Avoids re-fetching on every `init define` run.

5. **Integrate into `DefineScaffolder.scaffold_sdtm()`** — new `cosmos: bool` param. When True, annotate each variable with COSMOS data as YAML comments:

   ```yaml
   # COSMOS: origin=Assigned, assignedTerm=SYSBP, codelist=C66741
   # BC: Systolic Blood Pressure | synonyms: SBP, systolic BP
   - name: VSTESTCD
     label: Vital Signs Test Short Name
   ```

6. **CLI flag** — add `--cosmos / --no-cosmos` to `fleet init define` (defaults to `--cosmos` when API key available).

---

## Phase 2: Column Matching Engine

**Prerequisite — Extend `load_raw_data()` with clinical formats**:

Currently `src/fleet/io/loaders.py` only handles CSV, Excel, and Parquet. Clinical raw data arrives in many formats. Extend the universal loader before the profiler can consume arbitrary inputs:

| Format   | Polars call                       | Extra dependency | Notes                                                                  |
| -------- | --------------------------------- | ---------------- | ---------------------------------------------------------------------- |
| CSV      | `pl.scan_csv`                     | None             | Already supported                                                      |
| Parquet  | `pl.scan_parquet`                 | None             | Already supported                                                      |
| Excel    | `pl.read_excel`                   | None             | Already supported                                                      |
| SAS7BDAT | `pl.read_sas`                     | `pyreadstat`     | Polars calls pyreadstat internally via C — no pandas at Fleet boundary |
| XPT      | `pl.read_sas`                     | `pyreadstat`     | Same call, auto-detected by extension                                  |
| RDS      | `pyreadr.read_r` → `pl.DataFrame` | `pyreadr`        | Pure C, no pandas dependency                                           |
| RData    | `pyreadr.read_r` → `pl.DataFrame` | `pyreadr`        | Returns dict of frames; first or user-specified dataset used           |

**Steps** (_depends on Phase 1_):

6b. **Extend `load_raw_data()` in `src/fleet/io/loaders.py`** — add `.sas7bdat`, `.xpt`, `.rds`, `.rda`/`.rdata` to the suffix dispatch. SAS formats via `pl.read_sas()` (requires `pyreadstat`). R formats via `pyreadr.read_r()` → `pl.from_pandas()`. Raise clear error with install hint when optional dep is missing. Also extract SAS variable labels from `pyreadstat` metadata when available (bonus matching signal).

7. **Create `src/fleet/mapping/profiler.py`** — profile raw data (loaded via `load_raw_data()`, format-agnostic): column names, dtypes, cardinality, sample values, date patterns, and SAS labels when present.

8. **Create `src/fleet/mapping/matcher.py`** — multi-signal scorer (_depends on step 7_):
   - Name similarity (rapidfuzz token_sort_ratio against variable name + label + BC synonyms)
   - Type compatibility (date-like → DTC; numeric → numeric)
   - Codelist value overlap (raw values ∩ codelist terms)
   - COSMOS origin hint (Assigned variables = constants, skip matching)

9. **Create `src/fleet/mapping/verb_selector.py`** — rules engine mapping (origin + signals) → Fleet verb (_parallel with step 8_)

10. **CLI command** — `fleet suggest-mapping --raw <file> --domain <D> --spec <define.yaml>` (accepts any supported format: csv, parquet, sas7bdat, xpt, rds, rdata)

11. **Add `rapidfuzz` to `[mapping]` extra** in `pyproject.toml`

---

## Phase 3: LLM Resolver (future)

12. Optional `fleet[ai]` extra. Magneto/Schemora pattern — sentence-transformer retrieval + LLM rerank. Only for unmatched columns from Phase 2.

---

## Relevant Files

| File                                 | Action                                                                                             |
| ------------------------------------ | -------------------------------------------------------------------------------------------------- |
| `src/fleet/ct/api.py`                | Extend with 4 COSMOS methods + caching                                                             |
| `src/fleet/core/cosmos.py`           | New: data models + resolver                                                                        |
| `src/fleet/core/scaffolder.py`       | Integrate COSMOS annotations                                                                       |
| `src/fleet/mapping/__init__.py`      | New module                                                                                         |
| `src/fleet/mapping/profiler.py`      | New: raw data profiling (Polars)                                                                   |
| `src/fleet/mapping/matcher.py`       | New: multi-signal matcher (rapidfuzz)                                                              |
| `src/fleet/mapping/verb_selector.py` | New: verb recommendation rules                                                                     |
| `src/fleet/io/loaders.py`            | Extend with SAS/XPT/RDS/RData formats                                                              |
| `src/fleet/cli.py`                   | `--cosmos` flag + `suggest-mapping` command                                                        |
| `pyproject.toml`                     | `[clinical-io]` extra (`pyreadstat`, `pyreadr`); `[mapping]` extra (`rapidfuzz` + `[clinical-io]`) |

---

## Verification

1. COSMOS API probe with existing key → 200 response
2. `fleet init define --cosmos` produces annotated define.yaml for DM/AE/VS
3. `fleet suggest-mapping` correctly maps `patient_number→USUBJID`, `sex→SEX`, `ae_term→AETERM`
4. All 5 example scripts pass
5. `uv run ruff check && uv run pytest`

---

## Decisions

- **Comments not fields** — COSMOS data as YAML comments, no schema changes, non-breaking
- **No pandas** — reimplement COMA-like matching with rapidfuzz + Polars (~300 lines)
- **Both BCs + Specializations** — BCs provide synonyms crucial for fuzzy matching
- **Same API key** — COSMOS uses same `api-key` header at same base URL
- **Graceful degradation** — domains without COSMOS coverage fall back to IG-only
- **Clinical I/O via Polars boundary** — `pyreadstat` and `pyreadr` are C extensions, not pandas wrappers. Polars calls `pyreadstat` natively for SAS. R formats go through `pyreadr` → `pl.DataFrame`. No pandas import ever crosses into Fleet code.

---

## Risks

1. **API key scope** — existing key may not have COSMOS access. Step 1 is a blocking probe.
2. **COSMOS domain coverage** — iteratively expanded; some domains may lack specializations. Handled by fallback.
3. **VLM complexity** — VS has 20+ specializations (one per test). Need to decide: annotate at variable level (generic) or expand VLM in comments.

---

## Research Backing

| Tool/Paper                   | Relevance                                                                                                                                 |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| **Magneto** (VLDB 2025)      | SLM retrieval + LLM rerank. GDC benchmark = healthcare standard mapping. Architecture template for Phase 3.                               |
| **Schemora** (Jul 2025)      | LLM metadata enrichment before matching. Zero-shot, MIMIC-OMOP validated. Inspiration for BC synonym usage.                               |
| **Valentine** (ICDE 2021)    | COMA/Cupid/SimilarityFlooding algorithms. Phase 2 reimplements COMA scoring logic without pandas.                                         |
| **sdtm_mapper** (PhUSE)      | ELMo + NN for AE mapping. Proved NLP works but requires training data — exactly what we avoid.                                            |
| **sdtm.oak** (Pharmaverse)   | Same verb-based approach as Fleet. "Metadata-driven code generation" on roadmap but unshipped.                                            |
| **CDISC COSMOS**             | Official machine-readable mapping metadata. Dataset Specializations give originType → verb selection. BCs give synonyms → fuzzy matching. |
| **cdisc-library-mcp-server** | Existing MCP server for COSMOS API. Validates endpoint structure and response schemas.                                                    |
