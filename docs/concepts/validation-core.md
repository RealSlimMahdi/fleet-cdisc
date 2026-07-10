# Validation with CORE (CDISC Rules Engine)

Fleet's conformance validation is built on **CORE** — the open-source
[CDISC Rules Engine](https://github.com/cdisc-org/cdisc-rules-engine), the
official executable implementation of CDISC's conformance rules. Fleet
manages the engine lifecycle (download, discovery, health check) and wraps
execution behind one CLI command and one namespace verb, so validation runs
with the same rules a regulator's reviewer tooling references.

## One-time setup

```bash
uv run fleet install-engine     # downloads the CORE binary to ~/.fleet
uv run fleet doctor             # confirms engine + extras are healthy
```

Teams can pin a shared engine instead via `validation.engine_path` in
`study_config.yaml` or the `FLEET_RULES_ENGINE` environment variable.

## Running validation

Everything resolves from the discovered `study_config.yaml`:

```bash
uv run fleet validate                          # all datasets in <sdtm_data> and <adam_data>
uv run fleet validate data/sdtm/ae.parquet     # one dataset
uv run fleet validate --report findings.html   # HTML findings report
```

- **Standard detection**: `AD*` datasets validate as ADaM, everything else
  as SDTM (`--standard` overrides).
- **IG versions** come from the config's `sdtm.ig_version` /
  `adam.ig_version` (`--version` overrides).
- **Custom rules** load automatically from `validation.custom_rules`
  (`--custom-rules` overrides) — see
  [Custom Validation Rules](custom-rules.md).
- Exit code is 1 when any dataset has errors, so `fleet validate` drops
  straight into CI.

The same run from Python, chainable at the end of a pipeline:

```python
result = (
    raw_df.sdtm.assign("DOMAIN", value="AE")
    # ... derivations ...
    .validate(domain="AE")  # runs CORE on the materialised frame
)
```

## Which rules actually exist upstream

CORE executes the rule sets CDISC has published to its Library. As of
mid-2026 that means:

| Standard | Published executable rules |
| --- | --- |
| SDTMIG 3.2 / 3.3 / 3.4 | ✅ full SD-series rule sets |
| SENDIG 3.0 / 3.1 / 3.1.1 (+DART, GENETOX, AR) | ✅ |
| FDA Business Rules | ✅ (SDTM/SEND-oriented) |
| TIG 1.0 (incl. its ADaM substandard) | ✅ |
| USDM | ✅ |
| **ADaMIG 1.0–1.3** | ⚠️ **selection plumbing exists (engine ≥ v0.13.0), but no executable ADaMIG rule set is published yet** — [ADaM Conformance Rules v5.0](https://www.cdisc.org/standards/foundational/adam/adam-conformance-rules-v5-0) remains a document, not machine rules |

Practical consequence: an ADaM `fleet validate` run today executes your
**custom rules** (plus any TIG-ADaM rules you opt into), while SDTM runs get
the full official battery. Fleet tracks the upstream catalog — when CDISC
publishes executable ADaMIG rules, the same command picks them up through
the engine's standard/version selection with no Fleet change.

## Where CORE sits in Fleet's validation stack

Validation is layered — each layer fires at a different moment and catches a
different error class:

| Layer | When | What it catches |
| --- | --- | --- |
| Spec registry models | `from_spec()` load time | unknown algorithms, misspelled/missing derivation fields |
| `DefineValidator` / `fleet check` | on demand / CI gate | define.yaml schema + business rules |
| Trial-design audit (`fleet tdd audit`) | on demand, offline | P21-style SD-series + FDA TS profile for TDD domains |
| **CORE (`fleet validate`)** | after datasets materialise | official CDISC conformance rules against the data itself |

See [Custom Validation Rules](custom-rules.md) for extending CORE with
sponsor-, study-, or TCG-specific checks — they run in the same engine,
report in the same format, and live in version control next to the study.
