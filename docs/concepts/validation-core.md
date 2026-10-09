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

`fleet doctor` prints the engine that validation will use, where it came
from, and its version. It takes them from the same run setup as the verb and
`fleet validate`.

Teams can pin a shared engine instead via `validation.engine_path` in
`study_config.yaml`. Inside a study, `validation.engine_path` beats the
`FLEET_RULES_ENGINE` environment variable, so that every programmer runs the
same engine build. Outside a study, `FLEET_RULES_ENGINE` still applies.

### Engine version

Every report header prints the engine version, so a QC programmer can check
that two runs used the same rule build. Fleet takes the version from the
first source that gives it:

1. the engine's own `core version` command (`0.15.0`),
2. the `fleet-release-tag.txt` file that `fleet install-engine` writes next
   to the managed binary (tag `v0.15.0`, printed as `0.15.0`),
3. else `unknown`.

## Running validation

Everything resolves from the discovered `study_config.yaml`:

```bash
uv run fleet validate                          # all datasets in <sdtm_data> and <adam_data>
uv run fleet validate data/sdtm/ae.parquet     # one dataset
uv run fleet validate --report findings.html   # HTML findings report
```

- **Sweep**: the engine runs once for all SDTM datasets and once for all
  ADaM datasets, so rules that span several datasets of one standard can
  execute. The report shows one result per dataset.
- **Standard detection**: a dataset in the configured `sdtm_data` or
  `adam_data` directory takes the standard of that directory. For any other
  path, `AD*` datasets validate as ADaM and everything else as SDTM.
  `--standard` overrides both.
- **IG versions** come from the config's `sdtm.ig_version` /
  `adam.ig_version` (`--version` overrides).
- **Custom rules** load automatically from `validation.custom_rules`
  (`--custom-rules` overrides). They run in a second engine run next to the
  official rules, so a sweep of both standards with custom rules makes four
  engine runs. See [Custom Validation Rules](custom-rules.md).
- The report header of each dataset shows every input with its source, as on
  the verb.
- **HTML report**: `--report findings.html` writes one page with a section
  per dataset (its inputs, status and counts, then one card per error,
  warning and info finding) and a section per dataset that could not run.
  It is the page `ValidationResult.save_html_report()` writes for one
  dataset, and every value on it is HTML-escaped.
- **Could not run**: a dataset whose directory and file name disagree
  (`data/sdtm/adsl.parquet`), or an unsupported IG version, is not validated.
  The reason is printed, and the other datasets still run.
- Exit codes: 0 no errors, 1 any dataset has errors, 2 any dataset could not
  run. So `fleet validate` drops straight into CI.

### The CI gate: `fleet check`

`fleet check` builds the same run setup for SDTM and ADaM, with no datasets.
It catches a setup error before delivery, without an engine:

- `sdtm.ig_version: 3-5`, or any IG version not in the supported list, fails
  the gate.
- A `validation.custom_rules` directory that does not exist fails the gate.
- No engine found is a warning only, because CI installs no engine.

### The MCP tool

`fleet_validate(dataset_path, standard=None, version=None, custom_rules=None)`
builds the same run setup. It looks for `study_config.yaml` from the
directory of the dataset, not from the working directory of the server. A
refused setup returns `{"outcome": "could not run", "reason": ...}` and does
not raise. See [IDE tooling](../getting-started/ide-tooling.md).

The same run from Python, chainable at the end of a pipeline:

```python
result = (
    raw_df.sdtm.assign("DOMAIN", value="AE")
    # ... derivations ...
    .validate("AE")  # runs CORE on the materialised frame
)
```

### Where the verb takes its inputs

The verb builds a **run setup** before the engine starts. Each input comes
from the first source that gives it:

| Input | Argument | Study config | Environment | Default |
| --- | --- | --- | --- | --- |
| Standard | (none) | (none) | (none) | the namespace: `.sdtm` or `.adam` |
| IG version | `version=` | `sdtm.ig_version` / `adam.ig_version` | (none) | SDTMIG 3.4, ADaMIG 1.3 |
| Custom rules | `custom_rules=` | `validation.custom_rules` | (none) | none |
| Engine | `rules_engine_path=` | `validation.engine_path` | `FLEET_RULES_ENGINE` | managed install |

The verb looks for `study_config.yaml` from the working directory, then
each parent. `version=` accepts `"3-4"` and `"3.4"`. The supported versions
are SDTMIG 3.2, 3.3, 3.4 and ADaMIG 1.0, 1.1, 1.2, 1.3.

The report header prints each input with its source and the study config
used:

```text
Standard:     SDTMIG (namespace)
IG version:   3.3 (study config)
Custom rules: /study/metadata/custom_rules (study config)
Engine:       /study/tools/core/core (study config)
CORE version: 0.15.0
Study config: /study/study_config.yaml
```

### Could not run

Some setups are refused before the engine starts. The verb then raises
`ValidationSetupError` in every `on_fail` mode, because no rule ran:

- the dataset name belongs to the other standard: `adae.adam.validate("AE")`
  or `ae.sdtm.validate("ADAE")`,
- the IG version is not supported, for example SDTMIG 3.1.3,
- the custom rules directory does not exist.

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
| `DefineValidator` / `fleet check` | on demand / CI gate | define.yaml schema + business rules, run setup (IG versions, custom rules directory) |
| Trial-design audit (`fleet tdd audit`) | on demand, offline | P21-style SD-series + FDA TS profile for TDD domains |
| **CORE (`fleet validate`)** | after datasets materialise | official CDISC conformance rules against the data itself |

See [Custom Validation Rules](custom-rules.md) for extending CORE with
sponsor-, study-, or TCG-specific checks — they run next to the official
rules, report in the same format with their source, and live in version
control next to the study.
