---
description: "Use when working with Fleet CLI commands, bootstrapping studies, CDISC CT, define-xml, TLG export, or validation engine"
---

# Fleet CLI

**Authoritative reference:** `docs/getting-started/cli.md` — AUTO-GENERATED from the argparse tree by `scripts/gen_cli_docs.py` (CI fails if stale). Do not duplicate command/flag inventories here or anywhere else; regenerate with `uv run python scripts/gen_cli_docs.py`, or check freshness with `--check`. `uv run fleet <cmd> --help` is always current.

## Command map (names only)

- **Bootstrap:** `fleet init cfg|define|ct|rules` (pipeline), `fleet new` (all four, one confirmation)
- **Pipeline:** `fleet run` (execute define.yaml), `fleet check` (CI gate), `fleet validate` (CDISC Rules Engine, one engine run per standard; exit 0 no errors, 1 errors, 2 could not run), `fleet compare` (PROC COMPARE analogue; exit 0 equal, 1 different, 2 could not run)
- **Migration:** `fleet migrate` (libcst codemod: removed pre-alpha verb/kwarg spellings → canonical)
- **TLG:** `fleet tlg list|schema|run|explore|export` (`run`/`explore` take `--watch`, needs the `watch` extra)
- **Define-XML:** `fleet define-xml` (also `--watch`)
- **CT:** `fleet add-ct` (bootstraps or extends codelists.py); prefer the `fleet init` pipeline for full studies
- **Rules:** `fleet add-rule`, `fleet check-rule`, `fleet install-engine`, `fleet uninstall-engine`, `fleet doctor`
- **Tooling servers:** `fleet mcp --stdio`, `fleet lsp --stdio` (require the `mcp` / `lsp` extras). The VS Code client for `fleet lsp` lives in its own repository, `RealSlimMahdi/fleet-vscode` — Fleet owns only the Python side.
- **Misc:** `fleet derivation`, `fleet --version`

## Conventions

- Config discovery is git-style: cwd, then parents, until `study_config.yaml` is found; `--config <path>` overrides.
- Errors go to stderr; exit codes: 0 success, 1 Fleet error, 2 usage error. `fleet compare` is the exception: its exit code is the verdict (0 equal, 1 different, 2 could not run).

## Documentation build

```bash
uv run --extra docs mkdocs serve
uv run --extra docs mkdocs build
```
