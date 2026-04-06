## Plan: AE ARD Export to Pharma-Style HTML and PDF

Build a dedicated TLG rendering layer that converts the already-implemented AE outputs into submission-style table artifacts. Use the existing AE summary ARD and AE listing as input, render pharma-style HTML first (modeled on NEST AET01 structure), then generate PDF from the same HTML using WeasyPrint. Expose both Python API and CLI entry points while keeping ARD computation unchanged.

**Steps**

1. Phase 1: Lock output contract from NEST AET01 and Fleet AE outputs. Depends on discovery only.

- Define a display contract for AE summary and AE listing: title, subtitle, treatment columns with N counts, left stub labels, indentation rules, right-aligned numeric cells, section rows, and optional footnotes/source lines.
- Map Fleet ARD fields to display roles: group1/group1_level to treatment columns, stat_name/stat_fmt to metrics, variable/variable_level to row hierarchy.
- Confirm canonical behavior for missing values, zero counts, and long labels wrapping.

2. Phase 2: Build table-model shaping utilities for summary and listing. Depends on Step 1.

- Add a transformation layer that converts long ARD into a deterministic wide table model for rendering without changing ARD schema.
- Build a listing model from AE listing output with ordered columns, display labels, and row ordering.
- Keep summary/listing shaping pure and testable so renderers are thin.

3. Phase 3: Implement pharma-style HTML renderer. Depends on Step 2.

- Add a rendering module under src/fleet/tlg that outputs semantic HTML with thead/tbody and an explicit style block.
- Implement summary layout matching AET01 conventions: arm headers plus N row, row hierarchy with indentation, count and n (%) display, section divider rows, compact submission-like spacing.
- Implement listing layout with sponsor-style borders/alignment and print-friendly defaults.
- Add metadata support for title/subtitle/program-run timestamp and optional footnotes.

4. Phase 4: Integrate Python API for AE summary and listing export. Depends on Step 3.

- Add public methods on AE namespace to export summary/listing to HTML using existing AE pipelines.
- Keep API explicit about whether input is ARD vs listing frame and whether writer returns string or writes file.
- Add Google-style docstrings and examples for all new public methods.

5. Phase 5: Add CLI entry point for AE table export. Depends on Step 4.

- Extend CLI parser with a TLG export command aligned with current fleet command patterns.
- Support both summary and listing artifacts, format selection, metadata fields (title/subtitle/footnotes), and output path.
- Provide predictable logs similar to define-xml command output.

6. Phase 6: Add PDF generation from HTML with WeasyPrint (phase 2). Depends on Step 3; can run in parallel with Step 5 once HTML renderer contract is stable.

- Introduce optional PDF path that renders HTML first and converts to PDF using WeasyPrint.
- Add dependency handling in pyproject so users who only need HTML are not blocked.
- Ensure page margins, font scaling, and page break behavior are acceptable for clinical review.

7. Phase 7: Testing, examples, docs, and release hygiene. Depends on Steps 4-6.

- Add unit tests for ARD-to-table-model transforms and listing model transforms.
- Add renderer tests that validate key HTML structure and style tokens.
- Add CLI tests for argument parsing and output artifact generation.
- Extend AE example to generate real HTML (and optional PDF) artifacts from existing adverse event workflow.
- Document new APIs and CLI usage in docs and update nav if adding a TLG API page.
- Regenerate llms context because this adds user-facing API/CLI surface.

**Relevant files**

- /Users/aboutm/Code/Python/Fleet-tlg_experimentation/src/fleet/tlg/ae_namespace.py — existing AE summary/listing API to extend with export methods.
- /Users/aboutm/Code/Python/Fleet-tlg_experimentation/src/fleet/tlg/\_ard.py — ARD schema/formatting utilities; reference point for summary shaping contract.
- /Users/aboutm/Code/Python/Fleet-tlg_experimentation/src/fleet/tlg/\_specs.py — spec models; potential place for render/export spec options.
- /Users/aboutm/Code/Python/Fleet-tlg_experimentation/src/fleet/tlg/**init**.py — public exports for new renderer interfaces.
- /Users/aboutm/Code/Python/Fleet-tlg_experimentation/src/fleet/cli.py — CLI parser/dispatch pattern to mirror define-xml style for new TLG export command.
- /Users/aboutm/Code/Python/Fleet-tlg_experimentation/src/fleet/define_xml/spec_generator.py — existing HTML preview generation pattern to reuse for file-writing ergonomics.
- /Users/aboutm/Code/Python/Fleet-tlg_experimentation/tests/unit/test_tlg_namespace.py — primary test bed for summary/listing behavior and ARD contracts.
- /Users/aboutm/Code/Python/Fleet-tlg_experimentation/examples/tlg_ae_example.py — end-to-end AE workflow to extend with artifact export.
- /Users/aboutm/Code/Python/Fleet-tlg_experimentation/pyproject.toml — optional dependency definition for PDF backend.
- /Users/aboutm/Code/Python/Fleet-tlg_experimentation/mkdocs.yml — docs nav updates if a TLG API/export page is added.
- /Users/aboutm/Code/Python/Fleet-tlg_experimentation/docs/api/index.md — API landing updates for new export docs.

**Verification**

1. Run lint and format checks in required order.

- uv run ruff check
- uv run ruff format --check

2. Run full test suite.

- uv run pytest

3. Run all required examples, including AE TLG example because this scope is AE export.

- uv run python examples/full_pipeline_example.py
- uv run python examples/cdiscpilot01_inline.py
- uv run python examples/cdiscpilot01_spec_driven.py
- uv run python examples/adnca_example.py
- uv run python examples/tdd_example.py
- uv run python examples/tlg_ae_example.py

4. Regenerate and verify llms context due new public APIs/CLI.

- uv run python scripts/build_llms.py
- uv run python scripts/build_llms.py --check

5. If docs change, validate docs build.

- uv run --extra docs mkdocs build --clean

**Decisions**

- Output phaseing: HTML first, PDF second.
- Integration surface: Both Python API and CLI.
- Scope: AE summary plus AE listing.
- Style reference: NEST AET01 template at insightsengineering tlg-catalog.
- PDF backend: WeasyPrint.
- Out of scope for this initiative: non-AE TLG domains, RTF/PPTX exporters, changes to ARD schema semantics.
