---
description: Use when writing or editing Marp markdown presentations (the talk decks of the fleet-talks repository)
applyTo: "talks/**/deck/**/*.md"
---

# Presentation Instructions

## Diagrams

- **Always use Mermaid** (`mermaid` fenced code blocks) for graphs, flowcharts, sequence diagrams, and architecture schemas.
- **Never use ASCII art** with Unicode box-drawing characters (`─`, `│`, `┌`, `└`, `▶`, etc.) — these render inconsistently across Marp themes and export targets.
- Prefer `graph LR` for horizontal flows, `graph TD` for vertical flows.
- Use `<br/>` for multi-line node labels.
- Use dotted links (`-.->` or `-. text .->`) for weak/drift relationships.

## Export

- The talk decks are in the sibling repository `fleet-talks`, one folder per submission: `talks/<id>/deck/`. Build the PPTX and the slides PDF there with `bash kit/deck/build-pptx.sh talks/<id>` (steps in `kit/deck/README.md`).
- For a single Marp file: `marp --pdf --allow-local-files --html <file>.md`, with the PDF in the same directory as the source markdown.
