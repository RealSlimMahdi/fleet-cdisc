---
name: "Fleet Examples Namespace-Only"
description: "Use when editing or generating Python examples in Fleet; enforce namespace-only transformations."
applyTo: "examples/**/*.py"
---

# Namespace-only policy for Fleet examples

- Use Fleet namespace chaining for all dataset transformations.
- Start transformations from a namespace entrypoint like .sdtm, .adam, .adam.adsl, .adam.occds, or .adam.pk.
- End every transformation chain with .to_frame().
- Do not use direct DataFrame transformation methods in examples (for example: .with_columns, .rename, .select, .filter, .join, .group_by, pl.concat) when the step is a derivation or merge that belongs in namespace verbs.
- If a required derivation is not covered by an existing namespace verb, stop and implement or request a namespace verb first; do not inline plain Polars transformation logic in the example.
- Keep mapping arguments explicit and keyword-based (source=, value=, ct_mapping=, etc.).
- Preserve lazy/chained style and avoid mixed patterns where part of the pipeline is namespace-based and part is ad hoc DataFrame logic.
- Only use non-namespace operations for basic IO boundaries (read/write files, constants, simple printing), not for derivation logic.
- For shared ADaM logic needed in multiple namespaces, implement in mixins instead of per-namespace duplication.

# Validation requirement

- After any change to example scripts, **ALL** `.py` files in `examples/` must be re-run and pass without error. This includes:
  ```
  uv run python examples/full_pipeline_example.py
  uv run python examples/cdiscpilot01_inline.py
  uv run python examples/cdiscpilot01_spec_driven.py
  uv run python examples/adnca_example.py
  uv run python examples/tdd_example.py
  ```
- If a new example script is added, it must also be added to the validation list in `.github/copilot-instructions.md` §3 and §9.
