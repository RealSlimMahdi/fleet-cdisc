# IDE & AI Tooling

Fleet ships three optional layers of editor/assistant integration. None of them change
what a pipeline does: each one exposes the workflow Fleet already has — its verbs,
arguments and validation — to the editor or to an assistant, so the intended path is
more obvious and the wrong path fails sooner. Pipelines run identically with or
without them.

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

**VS Code:** the client ships from its own repository,
[`RealSlimMahdi/fleet-vscode`](https://github.com/RealSlimMahdi/fleet-vscode)
(installation, settings, and the development loop are documented there). It
finds the server via the `fleet.server.path` setting, then the `FLEET_LSP` env
var, then `.venv/bin/fleet`, then `uv run fleet`.
**Other editors:** point any LSP client at `fleet lsp --stdio` for YAML files.

## AI assistants — `fleet mcp` (Model Context Protocol)

The MCP server lets any MCP-capable assistant (Claude Code, Claude Desktop,
Cursor, ...) call Fleet's pipeline intelligence as tools instead of guessing
from source code.

### Setup

```bash
uv add "fleet-cdisc[mcp]"
# Claude Code (run from the study root — see note below):
claude mcp add fleet -- uv run fleet mcp --stdio
```

Any other MCP client uses the same stdio command. For JSON-config clients
(Claude Desktop, Cursor, a project `.mcp.json`):

```json
{
  "mcpServers": {
    "fleet": {
      "command": "uv",
      "args": ["run", "fleet", "mcp", "--stdio"],
      "cwd": "/path/to/your/study"
    }
  }
}
```

**Launch from the study root.** The tools take dataset/spec paths as
arguments; registering the server with the study workspace as its working
directory (`cwd` above, or running `claude mcp add` inside the study) lets
the assistant pass the same relative paths your `study_config.yaml` uses
(`data/sdtm/ae.parquet`, `metadata/sdtm/define.yaml`, ...).

### Exposed tools

Each is a thin wrapper over a public Fleet API:

| Tool | Does |
| --- | --- |
| `fleet_execution_order(spec_paths)` | topological dataset build order from define.yaml |
| `fleet_impacted_by(spec_paths, node)` | what must re-run if a dataset changes |
| `fleet_lineage(dag_json_path, dataset)` | variable-level lineage from a pipeline DAG export |
| `fleet_validate(dataset_path, standard?, version?, custom_rules?)` | CDISC Rules Engine validation from the run setup |
| `fleet_ct_terms(codelist, ct_path?)` | valid terms for a codelist |
| `fleet_tlg_catalog()` | all registered TLG templates |
| `fleet_tlg_run(spec_path, data_path, adsl_path?, groupby?)` | run a TLG spec YAML, return rendered HTML |
| `fleet_dataset_check(data_path, define_yaml, dataset)` | conformance check against the spec |

`fleet_validate` builds the same run setup as `fleet validate`. It looks for
the `study_config.yaml` from the directory of the dataset, not from the
working directory of the server. So a dataset inside a study uses the study's
IG version, custom rules and engine. When `standard` is not given, the
configured data directory that holds the file names it, else the file stem
(`adsl.parquet` is ADaM). The result lists each input with its source:

```json
{
  "outcome": "pass",
  "dataset": "ADSL",
  "standard": "adam",
  "is_valid": true,
  "setup": {
    "standard": {"value": "adam", "source": "data directory"},
    "ig_version": {"value": "1.3", "source": "study config"},
    "custom_rules": {"value": "/study/metadata/custom_rules", "source": "study config"},
    "engine": {"value": "/home/me/.fleet/cdisc-rules-engine/core/core", "source": "default"},
    "engine_version": "0.15.0",
    "study_config": "/study/study_config.yaml"
  },
  "issues": []
}
```

A refused run setup does not raise. The tool returns
`{"outcome": "could not run", "reason": ...}`: for example a standard
conflict (`data/adam/dm.parquet`), an unsupported IG version, a custom rules
directory that does not exist, or no engine found.

### What to ask your assistant

Once connected, these workflows stop being copy-paste-the-error loops and
become one question each:

- *"In what order do I need to build the datasets in metadata/adam/define.yaml?"*
  → `fleet_execution_order`
- *"If I change DM, which downstream datasets must re-run?"* → `fleet_impacted_by`
- *"Where does ADSL.TRTSDT come from?"* → `fleet_lineage`
- *"Validate data/sdtm/ae.parquet and summarise the errors."* → `fleet_validate`
- *"Is 'INTERVENTIONAL' a valid term for C99077? What are the others?"* → `fleet_ct_terms`
- *"Which TLG template covers an AE overview table, and run it against my ADAE."*
  → `fleet_tlg_catalog` + `fleet_tlg_run`
- *"Does data/sdtm/dm.parquet conform to its define.yaml spec?"* → `fleet_dataset_check`

Combined with `llms.txt` (the machine-readable API summary shipped at the
repo root), an assistant can both **write** Fleet pipelines and **verify**
their outputs without leaving the conversation.

`fleet doctor` reports whether the `lsp` and `mcp` extras are installed.
