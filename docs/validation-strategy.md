# Fleet Validation Strategy

**Package:** `fleet-cdisc` (import name: `fleet`) &nbsp;|&nbsp; **Specification version:** 1.0 &nbsp;|&nbsp; **Date:** 2026-03-30

---

## 1. Executive Summary

Fleet is a Python library that generates CDISC SDTM and ADaM datasets for clinical statistical programming. It is built entirely on [Polars](https://pola.rs/) through a namespace extension API, and is designed to run inside a sponsor's existing validated Python infrastructure. This document defines Fleet's validation strategy using the risk-based framework established by the R Validation Hub and the software-agnostic regulatory context articulated by the FDA. The strategy is structured around four complementary pillars: standards traceability through the CDISC Library API, cross-language benchmark parity against `{admiral}`, regulatory-grade validation via the official CDISC Rules Engine (CORE), and automated unit testing with static analysis.

---

## 2. Regulatory Basis

### 2.1 FDA Position on Statistical Software

The FDA's 2015 Statistical Software Clarifying Statement[^1] explicitly states that the agency **does not require nor endorse any specific software** for analyzing data from clinical investigations. Sponsors are responsible for ensuring that any software used produces accurate results and for maintaining adequate documentation of that accuracy. This places the validation obligation on the sponsor's qualified infrastructure — of which Fleet is one component — rather than on the software vendor alone.

!!! note "Implication for Fleet"
Fleet does not need to be independently validated by a regulatory body. Sponsors qualify Fleet by demonstrating it produces accurate, traceable, and reproducible CDISC-compliant outputs within their own validated environment.

### 2.2 R Validation Hub Framework

The R Validation Hub white paper[^2] — co-authored by representatives from AstraZeneca, GSK, Roche/Genentech, Amgen, and other sponsors — establishes a **risk-based approach** for assessing package accuracy within validated infrastructure. Although written for R, the framework is language-agnostic and is increasingly applied to Python packages used in regulatory submissions. The framework classifies packages into three risk tiers based on:

| Risk Factor                   | Description                                                                    |
| ----------------------------- | ------------------------------------------------------------------------------ |
| **Intended use**              | How directly the package generates submission-ready outputs                    |
| **Consequence of inaccuracy** | Patient safety risk and regulatory impact if results are wrong                 |
| **Testability**               | Availability of unit tests, cross-validation tools, and independent benchmarks |

Fleet addresses all three dimensions, as documented in the qualification summary in §5.

---

## 3. Validation Pillars

### Pillar 1 — CDISC Library Traceability

Fleet's `fleet init define` and `fleet init ct` CLI commands query the **CDISC Library REST API**[^3] directly to bootstrap study specifications and controlled terminology. Variable metadata (labels, types, core designations, permitted terms) is sourced from the authoritative CDISC machine-readable IG model — not hard-coded. The resulting `define.yaml` and `codelists.py` are committed artefacts that provide full lineage from source variable to CDISC standard.

```bash
# Step 1: Pull domain variable metadata from the CDISC Library IG for SDTM 3.4
uv run fleet init define

# Step 2: Generate codelists.py from NCI concept IDs in define.yaml
uv run fleet init ct
```

This produces codelist classes — for example `SEX` (C66731), `RACE` (C74457) — that are used in pipeline code by class name, never raw string ID:

```python
from examples.cdiscpilot01.sdtm.codelists import SEX, RACE

dm = (
    raw_df.sdtm.assign("SEX", source="sex", ct=SEX)
    .assign("RACE", source="race", ct=RACE)
    .to_frame()
)
```

**Traceability chain:** `CDISC Library API → define.yaml → codelists.py → pipeline code → output dataset`

Each link is a versioned, reviewable artefact stored alongside the study specification.

---

### Pillar 2 — Cross-Language Benchmark: `{admiral}` Parity

`{admiral}`[^4] is the pharmaverse R package for ADaM derivations; it is the de-facto gold standard in R-based clinical programming and is documented in multiple regulatory submissions. Fleet's test suite contains `tests/unit/test_admiral_parity.py` — 400+ lines of tests that benchmark Fleet's Python outputs against documented `{admiral}` algorithm specifications.

**Coverage as of v0.1.0:**

| Test class                 | Algorithms verified                                                                |
| -------------------------- | ---------------------------------------------------------------------------------- |
| `TestBSA`                  | Dubois-DuBois, Mosteller, Haycock, Gehan-George (4 methods)                        |
| `TestMeanArterialPressure` | Standard MAP formula                                                               |
| `TestQTc`                  | Bazett, Fridericia (2 methods)                                                     |
| `TestAgeInYears`           | Day-accurate age in years, months, weeks                                           |
| `TestDeriveSummaryRecords` | Mean aggregation by parameter group (BDS record generation)                        |
| `TestDeriveLOCFRecords`    | Last-observation-carried-forward imputation                                        |
| `TestDeriveParam`          | BMI derivation from height/weight                                                  |
| `TestADSLAgeYears`         | Age derivations on ADSL frame                                                      |
| `TestADSLDerivePeriod`     | Exposure period flags                                                              |
| `TestANL01FLAdmiralParity` | `restrict_derivation` + `derive_var_extreme_flag` (last-valid-row ANL01FL pattern) |

**No R runtime is required.** The parity tests work in two ways:

- **Formula transcription** — mathematical formulas (BSA, QTc, MAP, age conversion) are transcribed directly from `{admiral}`'s published R source code. The tests then assert that Fleet's Polars implementation produces numerically identical results for the same inputs, using analytically-derived expected values computed in pure Python from the same formula.
- **Behavioural specification** — for higher-level patterns such as ANL01FL flagging, the expected output rows and flag values are transcribed verbatim from `{admiral}`'s documented examples (the test comments quote the equivalent R code). Fleet's Python implementation is then verified to reproduce that exact output.

This approach means the validation does not depend on an R installation, a specific R version, or `rpy2`. The published `{admiral}` specification is the invariant; Fleet's implementation is validated against it.

```python
# Example: ANL01FL last-valid-row parity test
# tests/unit/test_admiral_parity.py — TestANL01FLAdmiralParity
#
# Equivalent admiral R pattern (quoted in test docstring):
#   restrict_derivation(advs, derivation = derive_var_extreme_flag,
#     args = params(by_vars = exprs(USUBJID, PARAMCD),
#                   order = exprs(ADT), new_var = ANL01FL, mode = "last"),
#     filter = !is.na(AVAL))

result = bds_frame.adam.flag(
    "ANL01FL",
    criteria="last",
    order_by="ADT",
    by=["USUBJID", "PARAMCD"],
    where='~pl.col("AVAL").is_null()',
).to_frame()
# Only the last non-null-AVAL record per group receives "Y"; all others are null
assert result["ANL01FL"].to_list() == [None, "Y", None, "Y", None, "Y"]
```

---

### Pillar 3 — Official CDISC Rules Engine (CORE)

Fleet integrates the **official CDISC Rules Engine (CORE)**[^5] — the open-source validation binary published by CDISC and used by FDA as the reference conformance checker for SDTM and SEND submissions. (ADaM standard/version selection is supported by the engine, but CDISC has not yet published an executable ADaMIG rule set — ADaM validation today runs custom rules; see [Validation with CORE](concepts/validation-core.md).) Fleet manages the engine lifecycle through its own CLI and wraps it via a Python API.

#### Installation and health check

```bash
# Download the managed engine binary for the current platform
uv run fleet install-engine

# Verify engine and supporting dependencies
uv run fleet doctor
```

`fleet doctor` outputs a structured status report covering: engine binary presence, engine version, `pyreadstat` availability for XPT serialisation, and environment variable overrides.

#### Python validation API

```python
from fleet import ValidationService

svc = ValidationService()

# Validate an SDTM domain against SDTMIG 3.4
dm_result = svc.validate_sdtm(dm, domain="DM", version="3.4")
dm_result.print_report()  # console: pass/warn/fail by rule
dm_result.save_html_report("outputs/dm_validation.html")  # archivable HTML

# Validate an ADaM dataset against ADaMIG 1.3
adsl_result = svc.validate_adam(adsl, dataset="ADSL", version="1.3")
assert adsl_result.is_valid
```

The `ValidationResult` object exposes `.is_valid` (bool), `.print_report(report_type="summary")` (or `"full"` for expanded details including INFO-level engine noise), and `.save_html_report(path)` — an HTML page with the dataset status and one table row per error, warning and info finding, suitable for archiving as a validation deliverable. Every cell is HTML-escaped, because messages carry data values and the text of custom rules. `fleet validate --report` writes the same page for a sweep.

#### Engine discovery order

Fleet resolves the engine path at runtime via a four-tier chain (first match wins):

1. `validation.engine_path` in `study_config.yaml` (committable to VCS for team reuse)
2. `FLEET_RULES_ENGINE` environment variable (`.env` at project root)
3. Managed install under `~/.fleet/cdisc-rules-engine/core/`
4. Legacy `../cdisc-rules-engine/core.py` (development fallback)

The study config comes first, so a stale environment variable on one machine
cannot replace the engine the team pinned. An explicit `rules_engine_path=` on
`.validate()` beats all four.

---

### Pillar 4 — Automated Test Suite and Static Analysis

Fleet maintains a comprehensive automated test suite executed on every change:

```bash
uv run pytest                  # unit + integration tests
uv run ruff check              # style and lint (PEP 8, import ordering, type hints)
uv run ruff format --check     # formatting consistency
```

In addition, all five example scripts in `examples/` are treated as **integration smoke tests** and must execute without error after every feature change:

```bash
uv run python examples/full_pipeline_example.py
uv run python examples/cdiscpilot01_inline.py
uv run python examples/cdiscpilot01_spec_driven.py
uv run python examples/adnca_example.py
uv run python examples/tdd_example.py
```

These scripts exercise the complete derivation pipeline end-to-end — from raw CSV ingestion through SDTM and ADaM derivation to final export — against the CDISCPILOT01 reference study.

---

### Pillar 5 — Local Rule Snapshot (`fleet init rules`)

Fleet's `fleet init rules` command caches the exact CDISC conformance rules for the IG versions declared in the study's `define.yaml` files. Rules are fetched from the CDISC Library API, grouped by domain, and written as human-readable YAML into `metadata/sdtm/rules/` and `metadata/adam/rules/`.

```bash
# After fleet init define has created define.yaml files:
uv run fleet init rules
```

Each YAML file records the rule's CORE ID, description, check logic, scope, severity, and regulatory citations. When committed to VCS, these files provide:

- **Version lock:** The exact rule definitions in effect when the study was validated, immune to upstream CDISC updates.
- **Audit trail:** Reviewers (including regulators) can inspect which rules were applied without re-querying the CDISC Library.
- **Diff visibility:** Any change in the rule set between study milestones is visible in version control history.

#### Custom rules

When the standard CDISC CORE rule set does not cover a study-specific requirement, sponsors can author custom rules in the same YAML schema used by the engine.

Fleet provides first-class support for custom rules through:

- **`validation.custom_rules`** in `study_config.yaml` — sets a team-wide default directory
- **`fleet add-rule`** — scaffolds a schema-valid YAML skeleton with a `# TODO` `Check:` block
- **`fleet check-rule`** — validates a rule file (YAML syntax, structure, full JSON Schema)
- **`custom_rules=` parameter** on `.validate()` — loads rules per-pipeline

```bash
# Scaffold a new rule (auto-increments ID)
uv run fleet add-rule --domain AE --description "AESEV required when AESER = Y"

# Validate the rule file before running against datasets
uv run fleet check-rule metadata/custom_rules/FLEET-AE-001.yaml

# Use in pipeline
# .validate("AE", custom_rules="metadata/custom_rules")
```

Use a company prefix (e.g. `ACME-AE-001`) to avoid collisions with `CORE-XXXXXX`.

---

## 4. Risk Assessment

Applying the R Validation Hub risk-based framework to Fleet:

| Dimension                     | Fleet's profile                                                                                                                                  | Risk                                    |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------- |
| **Intended use**              | Generates submission-ready SDTM/ADaM datasets included in regulatory packages                                                                    | High intended-use criticality           |
| **Consequence of inaccuracy** | Incorrect derivations could affect safety/efficacy conclusions; however, CORE validation provides an independent runtime check before submission | Mitigated by Pillar 3                   |
| **Testability**               | 400+ admiral parity tests; CDISC Library traceability; CORE conformance checking; smoke test examples; ruff static analysis                      | High testability → lowers residual risk |
| **Open source provenance**    | Public GitHub repository; MIT license; full source inspectable by sponsor QA                                                                     | Transparent                             |
| **Dependency surface**        | Polars ≥ 1.0, Pydantic ≥ 2.0, PyYAML, httpx, lxml; all actively maintained, no high-CVE dependencies (check at installation)                     | Low-medium                              |

**Overall risk classification: Medium** (high criticality, but substantially mitigated by the four pillars above). This places Fleet in the same tier as `{admiral}`, `tern`, and other commonly qualified open-source clinical packages.

---

## 5. Qualification Summary

| Validation activity                | Primary artefact                                | Scope                                                     | Status                      |
| ---------------------------------- | ----------------------------------------------- | --------------------------------------------------------- | --------------------------- |
| Standards metadata sourcing        | `fleet init define` → `define.yaml`             | SDTM IG + ADaM IG variable metadata from CDISC Library    | Automated at study setup    |
| Controlled terminology generation  | `fleet init ct` → `codelists.py`                | NCI concept IDs for all study domains                     | Automated at study setup    |
| Conformance rule snapshot          | `fleet init rules` → `metadata/*/rules/*.yaml`  | All CDISC CORE rules for IG version, version-locked       | Automated at study setup    |
| Custom rule scaffolding            | `fleet add-rule` → `metadata/custom_rules/`     | Sponsor SOP / TCG gap rules, schema-validated             | On demand                   |
| Custom rule schema check           | `fleet check-rule <file>`                       | YAML syntax + structure + JSON Schema validation          | On demand / CI gate         |
| Cross-language algorithm benchmark | `tests/unit/test_admiral_parity.py`             | BSA, MAP, QTc, LOCF, BMI, ANL01FL, age/period             | Runs in CI on every commit  |
| SDTM conformance                   | `ValidationService.validate_sdtm()`             | All SDTM domains, SDTMIG 3.4                              | Run at study delivery       |
| ADaM conformance                   | `ValidationService.validate_adam()`             | ADSL, BDS, OCCDS datasets, ADaMIG 1.3                     | Run at study delivery       |
| Unit and integration tests         | `pytest` (400+ tests across 20 test modules)    | Namespace verbs, CT validation, Define-XML, TDD workflows | Runs in CI on every commit  |
| Static analysis                    | `ruff check` + `ruff format`                    | Full source tree                                          | Runs in CI on every commit  |
| End-to-end smoke tests             | `examples/*.py` (5 scripts, CDISCPILOT01 study) | Full SDTM + ADaM pipelines                                | Runs in CI on every commit  |
| Validation HTML report             | `ValidationResult.save_html_report()`           | Per-domain, per-delivery, archivable                      | Generated at study delivery |

---

## 6. References

[^1]: U.S. Food and Drug Administration (2015). _Statistical Software Clarifying Statement._ Office of Translational Sciences, Center for Drug Evaluation and Research. Available from: <https://www.fda.gov/media/161196/download>

[^2]: R Validation Hub (2020). _A Risk-based Approach for Assessing R Package Accuracy within a Validated Infrastructure._ pharmaR Working Group. Available from: <https://www.pharmar.org/white-paper/>

[^3]: CDISC (2024). _CDISC Library API._ Available from: <https://library.cdisc.org/api>

[^4]: pharmaverse (2021–present). _{admiral}: ADaM in R Asset Library._ CRAN. Available from: <https://cran.r-project.org/package=admiral>

[^5]: CDISC (2022–present). _CDISC Rules Engine (CORE)._ Open-source reference implementation for CDISC conformance checking. Available from: <https://github.com/cdisc-org/cdisc-rules-engine>
