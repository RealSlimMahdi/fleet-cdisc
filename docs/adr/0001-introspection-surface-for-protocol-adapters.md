# Protocol adapters consume a narrow introspection surface, not the registries

The language server reached directly into `fleet.core.spec_registry`, `fleet.core.algorithm_resolver`, `fleet.define_xml.schema_builder` and `fleet._version` — four private-ish import paths with no contract. Once the VS Code client ships from its own repository on its own cadence, those imports become an accidental public API that no test guards and no version promise covers.

So `fleet.introspect` is the single contract: `algorithms`, `get_algorithm`, `suggest_algorithm`, `algorithm_doc`, `define_schema`, returning purpose-built frozen dataclasses (`AlgorithmInfo`, `ParamInfo`, `AlgorithmDoc`) rather than `SpecAlgorithm` itself, whose `dispatch` callable, `overwrite_guard` and `define_template` are execution internals that must stay free to change.

## Consequences

- **Additive-only within a major version**, tracked by `fleet.__version__` alone — no separate surface version. Names, return fields and algorithms may be added; nothing is removed or renamed except on a major. A client therefore declares a *minimum* Fleet version and never a maximum.
- **The LSP handshake carries the same promise.** `initialize` announces `serverInfo` of `{"name": "fleet-lsp", "version": fleet.__version__}`, and a shipped client reads it to enforce that minimum, so it is part of the surface rather than an incidental argument to `LanguageServer(...)`. Pinned by a test alongside the import sweep.
- The DTOs duplicate part of the registry's shape. That duplication is the price of letting `spec_registry` be refactored without breaking a shipped extension.
- An AST sweep in `tests/unit/test_introspect.py` fails when `lsp_server.py` imports anything from `fleet` outside the surface, using the grandfathered-allowlist pattern already established by `tests/unit/test_api_conventions.py`.
- `mcp_server.py` got a **weaker** boundary, deliberately (#68). It ships inside Fleet and versions with it, so it needs no frozen DTOs and no additive-only promise — nothing external imports it. What it does need is the right dependency direction: it may use Fleet's public packages (`fleet`, `fleet.tlg`, `fleet.validation`, …) and may not import `fleet.cli` or any private name. `tests/unit/test_mcp_boundary.py` enforces exactly that.
