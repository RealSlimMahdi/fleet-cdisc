# IDE & AI Tooling

Fleet ships three optional layers of editor/assistant integration. None of them
change runtime behavior — pipelines run identically with or without them.

## Typed entry — `fleet.frame()` (optional)

`df.sdtm` / `df.adam` / `df.tlg` are registered on Polars frames at runtime, which
static type checkers cannot see ([pola-rs/polars#27795](https://github.com/pola-rs/polars/issues/27795)).
Pipelines work either way — the only difference is what your editor reports:

```python
import fleet
import polars as pl

# Without frame(): runs fine, but Pyright/Pylance flag `.sdtm` as unknown.
dm = pl.read_csv("dm_raw.csv").sdtm.assign("DOMAIN", value="DM").to_frame()

# With frame(): fully typed, zero runtime cost (returns its input unchanged).
raw = fleet.frame(pl.read_csv("dm_raw.csv"))
dm = raw.sdtm.assign("DOMAIN", value="DM").to_frame()  # -> fleet.DataFrame
dm.tlg.ae  # typed downstream too, since to_frame() returns fleet.DataFrame
```

`fleet.DataFrame` / `fleet.LazyFrame` are plain aliases of the Polars classes at
runtime (`isinstance` behaves normally); the namespace properties exist only for
type checkers. Wrap loads at IO boundaries and everything downstream stays typed.

## Language server — `fleet lsp` (define.yaml intelligence)

```bash
uv add "fleet-cdisc[lsp]"      # adds pygls
fleet lsp --stdio              # spoken by any LSP client
```

Capabilities on `define.yaml` files, all discovered live from the installed
Fleet package (never hardcoded):

| Capability | Source of truth |
| --- | --- |
| Diagnostics on open/change | generated JSON schema (`define_spec_schema.json`) |
| Unknown `algorithm:` did-you-mean | spec-algorithm registry |
| Completions: algorithm ids and per-algorithm parameter keys | registry (required params first) |
| Completions: codelist OIDs | the file's own `codelists:` section |
| Hover: algorithm docs, codelist name + terms | verb docstrings / inline codelists |

**VS Code:** a ready extension lives in [`editors/vscode/`](https://github.com/RealSlimMahdi/fleet-cdisc/tree/main/editors/vscode)
(see its README for F5 debugging and packaging). It finds the server via the
`FLEET_LSP` env var, then `.venv/bin/fleet`, then `uv run fleet`.
**Other editors:** point any LSP client at `fleet lsp --stdio` for YAML files.

## AI assistants — `fleet mcp` (Model Context Protocol)

```bash
uv add "fleet-cdisc[mcp]"
# Claude Code:
claude mcp add fleet -- uv run fleet mcp --stdio
```

Exposed tools, each a thin wrapper over a public Fleet API:

| Tool | Does |
| --- | --- |
| `fleet_execution_order(spec_paths)` | topological dataset build order from define.yaml |
| `fleet_impacted_by(spec_paths, node)` | what must re-run if a dataset changes |
| `fleet_lineage(dag_json_path, dataset)` | variable-level lineage from a pipeline DAG export |
| `fleet_validate(dataset_path, standard, ...)` | CDISC Rules Engine validation |
| `fleet_ct_terms(codelist, ct_path?)` | valid terms for a codelist |
| `fleet_tlg_catalog()` | all registered TLG templates |
| `fleet_tlg_run(spec_path, data_path, adsl_path?, groupby?)` | run a TLG spec YAML, return rendered HTML |
| `fleet_dataset_check(data_path, define_yaml, dataset)` | conformance check against the spec |

`fleet doctor` reports whether the `lsp` and `mcp` extras are installed.
