## Plan: Raise Fleet to 9/10

Tighten the repo where it is currently weakest: automate the documented quality bar, remove packaging and release inconsistencies, and correct documentation drift around the real API surface. Preserve the current architecture; the plan focuses on maturity, reliability, and discoverability rather than redesign.

**Steps**

1. Phase 1: Align automation with the repo’s documented standards. Update CI to run Ruff lint, Ruff format check, pytest with coverage enforcement, and all required example scripts. This is the highest-leverage step because it converts team norms into merge-time guarantees.
2. Phase 1: Strengthen docs/build automation in parallel with step 1 by validating mkdocs builds and keeping llms.txt freshness checks in place. If docs API pages under docs/api/ are touched, ensure the docs job catches mkdocstrings formatting corruption early.
3. Phase 1: Review release workflow gating so publish jobs depend on healthy validation, and replace any remaining pip-based build/install steps with uv-consistent commands. This depends on the CI job shape from step 1.
4. Phase 2: Consolidate packaging metadata in pyproject.toml by resolving duplicate dev dependency declarations, clarifying which dependency grouping mechanism is authoritative, and tightening public metadata such as supported Python classifiers and project URLs. This can run after or in parallel with step 3 if no workflow assumptions depend on it.
5. Phase 2: Improve release/version hygiene by validating build artifacts before upload, simplifying dev version generation, and documenting or enforcing the intended version-source-of-truth behavior between git tags, pyproject.toml, and src/fleet/\_version.py. This depends on step 3.
6. Phase 3: Fix documentation drift around the actual ADaM API surface. Update README.md, GUIDE.md, STRUCTURE.md, and llms.txt so they consistently describe first-class ADaM methods, namespace-specific verbs, TA extensions, CLI usage, and the preferred direct-method style over generic dispatch when both exist.
7. Phase 3: Add representative examples for specialized namespaces such as adam.adsl, adam.occds, and adam.onco so both humans and LLM tooling discover the intended patterns quickly. This depends on step 6.
8. Phase 4: Add missing tests for namespace capability contracts and workflow integration. Create tests that verify shared-verb inheritance and namespace-specific verb availability, plus at least one integration test for the CLI bootstrap path on a temporary study workspace. This depends on the clarified docs/API model from step 6.
9. Phase 4: Review optional-boundary candidates such as making Define-XML dependencies more clearly documented or optional, and documenting preferred access patterns such as fleet.get_validator(). This is included only as clarity work, not a package split or architectural redesign.
10. Phase 5: Finish by reconciling all developer-facing guidance so README, GUIDE, STRUCTURE, docs/test-status, and workflow files describe the same validation sequence, commands, and release process.

**Relevant files**

- `/Users/aboutm/Code/Python/Fleet/.github/workflows/ci.yml` — add the missing enforced quality checks: Ruff, format check, coverage threshold, and example execution.
- `/Users/aboutm/Code/Python/Fleet/.github/workflows/docs.yml` — add explicit mkdocs validation and keep docs-specific failures visible before deployment.
- `/Users/aboutm/Code/Python/Fleet/.github/workflows/publish.yml` — align publish behavior with uv-only repo policy, artifact validation, and release gating.
- `/Users/aboutm/Code/Python/Fleet/pyproject.toml` — resolve dependency declaration duplication, clean metadata, and clarify packaging intent.
- `/Users/aboutm/Code/Python/Fleet/src/fleet/_version.py` — keep versioning behavior consistent with the release workflow.
- `/Users/aboutm/Code/Python/Fleet/README.md` — fix install/documentation drift and keep public API claims accurate.
- `/Users/aboutm/Code/Python/Fleet/GUIDE.md` — improve workflow guidance and add specialized namespace examples.
- `/Users/aboutm/Code/Python/Fleet/STRUCTURE.md` — correct ADaM method counts/categories and architectural explanations.
- `/Users/aboutm/Code/Python/Fleet/llms.txt` — expand golden-path examples to reflect the preferred modern API.
- `/Users/aboutm/Code/Python/Fleet/docs/getting-started/installation.md` — correct package-install instructions and packaging naming where needed.
- `/Users/aboutm/Code/Python/Fleet/docs/test-status.md` — make documented coverage/test targets match enforced automation.
- `/Users/aboutm/Code/Python/Fleet/src/fleet/adam/namespace.py` — reference point for the actual first-class ADaM surface the docs should reflect.
- `/Users/aboutm/Code/Python/Fleet/src/fleet/adam/_mixins.py` — reference point for shared-verb architecture and inheritance expectations.
- `/Users/aboutm/Code/Python/Fleet/src/fleet/sdtm/namespace.py` — reference point for immutable lazy pipeline behavior and parity expectations.
- `/Users/aboutm/Code/Python/Fleet/src/fleet/ct/validator.py` — clarify preferred validator access patterns if documentation is updated.
- `/Users/aboutm/Code/Python/Fleet/tests/` — add contract tests and CLI integration coverage without disturbing existing unit coverage.

**Verification**

1. Run `uv run ruff check` and `uv run ruff format --check` after workflow and config changes.
2. Run `uv run pytest` with enforced coverage minimum, and confirm new contract/integration tests pass.
3. Run every example script listed in the repo instructions: `examples/full_pipeline_example.py`, `examples/cdiscpilot01_inline.py`, `examples/cdiscpilot01_spec_driven.py`, `examples/adnca_example.py`, and `examples/tdd_example.py`.
4. Run `uv run python scripts/build_llms.py` and `uv run python scripts/build_llms.py --check` if docs or public API guidance changes.
5. Run `uv run --extra docs mkdocs build` or the stricter project-approved docs build command after any docs/api or docs workflow change.
6. Validate release workflow logic with a dry-run mindset: build wheel and sdist locally, verify artifact integrity, and ensure version stamping logic is deterministic.
7. Review generated docs and workflow YAML side-by-side to confirm the documented verification order matches actual automation.

**Decisions**

- Included: CI hardening, docs drift cleanup, packaging/release polish, missing contract tests, and workflow consistency.
- Excluded: major API redesign, namespace rewrites, performance refactors, and any migration away from Polars or the immutable lazy pipeline model.
- Preserve: copy.copy-based immutable chaining, shared ADaM mixin architecture, Polars namespace registration, and the current domain-first API style.
- Recommended execution order: automation first, then packaging/release cleanup, then docs alignment, then missing tests.

**Further Considerations**

1. Coverage policy recommendation: use a repo-wide minimum first, then move to per-module thresholds later if you want the CI signal to reflect the stricter targets documented in docs/test-status.md.
2. Packaging policy recommendation: choose one dependency declaration approach in pyproject.toml and document it explicitly; mixed styles are manageable now but will confuse contributors later.
3. CLI validation recommendation: if CDISC API credentials make full end-to-end testing hard in CI, add a credential-free smoke/integration test plus a separately documented manual validation path.
