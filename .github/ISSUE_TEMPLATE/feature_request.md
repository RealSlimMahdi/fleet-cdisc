---
name: Feature Request (Markdown)
about: Propose a new Fleet feature that fits the project philosophy, API style, and quality bar.
title: "[Feature]: "
labels: enhancement
---

## What problem are you trying to solve?

Describe the real workflow gap, study programming pain point, or missing capability.

## What should Fleet do?

Describe the feature in normal user language.

## What should the user-facing shape look like?

If relevant, describe the namespace, verb, CLI command, or spec shape you expect.

Examples:

- A new verb on `df.sdtm` or `df.adam`
- A CLI command
- A `define.yaml` capability

## Philosophy fit

- [ ] This keeps Fleet simpler, not more complicated.
- [ ] This fits the way Fleet already reads like a clinical specification.
- [ ] This feels native to Fleet's chaining style rather than introducing a foreign pattern.

## API and architecture fit

- [ ] This should stay Polars-first.
- [ ] This should preserve lazy execution as much as possible.
- [ ] This should reuse existing namespaces or verbs where possible.
- [ ] If shared across ADaM namespaces, this should be implemented once rather than duplicated.
- [ ] If controlled terminology is involved, this should use generated codelist classes rather than raw concept IDs.

## How should this be validated?

Describe the tests, example scripts, or end-to-end checks that should prove the feature works.

## What documentation would need to change?

Note docstrings, examples, README, generated AI context, guides, or architecture docs if relevant.

If the feature changes verbs or public API surface, describe the source-of-truth update rather than only the rendered docs. In Fleet, verb API pages are derived from code via mkdocstrings, and the README namespace block plus `llms.txt` are generated, not edited by hand.

## What alternatives did you consider?

Explain why an existing verb, namespace, or workflow is not enough.

## What is out of scope?

Keep the request focused.

## Final checks

- [ ] I checked that this is not already covered by an existing Fleet verb, namespace, or workflow.
- [ ] I understand that any eventual implementation must include tests and documentation updates where needed.
