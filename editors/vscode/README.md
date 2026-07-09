# Fleet CDISC — VS Code extension

Language support for Fleet `define.yaml` specifications. The extension is a
thin TypeScript shell that launches the Python language server shipped with
the `fleet-cdisc` package (`fleet lsp --stdio`) — all semantic knowledge
(algorithms, schema, codelists) is discovered from the installed Fleet
package at runtime, never bundled.

## Features

- **Diagnostics** — YAML syntax errors, JSON-schema violations from the
  generated define-spec schema, and did-you-mean hints for unknown
  `algorithm:` values.
- **Completions** — `algorithm:` ids per standard, per-algorithm parameter
  keys (required first), and codelist OIDs from the file's own
  `codelists:` section.
- **Hover** — algorithm summaries with the dispatched verb's docstring and
  parameter table; inline-codelist term previews.

## Requirements

The workspace needs Fleet with the `lsp` extra installed:

```bash
uv sync --extra lsp        # or: uv pip install 'fleet-cdisc[lsp]'
```

Server discovery order:

1. `FLEET_LSP` environment variable — path to a `fleet` executable.
2. `<workspace>/.venv/bin/fleet` (`.venv\Scripts\fleet.exe` on Windows).
3. `uv run fleet` as a fallback.

## Development

```bash
cd editors/vscode
npm install
npm run compile
```

Then open `editors/vscode` in VS Code and press **F5** ("Run Extension") to
launch an Extension Development Host. Open a folder containing a
`define.yaml` (e.g. this repo's `examples/cdiscpilot01/`) to activate.

## Packaging

```bash
npm install -g @vscode/vsce
vsce package          # produces fleet-cdisc-<version>.vsix
code --install-extension fleet-cdisc-*.vsix
```
