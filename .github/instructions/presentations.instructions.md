---
description: Use when writing or editing Marp markdown presentations
applyTo: "presentation/**/*.md"
---

# Presentation Instructions

## Diagrams

- **Always use Mermaid** (`mermaid` fenced code blocks) for graphs, flowcharts, sequence diagrams, and architecture schemas.
- **Never use ASCII art** with Unicode box-drawing characters (`─`, `│`, `┌`, `└`, `▶`, etc.) — these render inconsistently across Marp themes and export targets.
- Prefer `graph LR` for horizontal flows, `graph TD` for vertical flows.
- Use `<br/>` for multi-line node labels.
- Use dotted links (`-.->` or `-. text .->`) for weak/drift relationships.

## Export

- Generate PDF with: `marp --pdf --allow-local-files --html <file>.md`
- Output the PDF in the same directory as the source markdown.
