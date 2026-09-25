# One run setup for every validation surface

The verb `.validate()`, `fleet validate`, the MCP tool `fleet_validate` and the `fleet check` gate each resolved the standard, the IG version, the custom rules and the engine in their own way, so one study gave different rules on different surfaces. We decided that one module in `fleet.validation` builds a run setup, a fixed record of every input of a validation with the source of each, and that every surface validates from it and resolves nothing itself.

## Decisions a reader would not expect

- **The study config beats `FLEET_RULES_ENGINE` inside a study.** The usual order lets the environment override a config file. We reversed it because a team lead pins `validation.engine_path` so that every programmer runs the same rule build; a stale environment variable on one machine would silently give different QC findings. The environment variable still applies outside a study, and every report prints the engine path and version it used.
- **Official and custom rules run in two engine runs.** CORE 0.15.0 treats `-lr` as a replacement for its rule set, not an addition: one AE file ran 430 official rules without `-lr` and 2 local rules with it. One run would drop every CDISC rule as soon as a study sets `validation.custom_rules`. The two results join into one report and each finding names its source.
- **A sweep is one engine run per standard**, because the engine takes one standard per run. SDTM and ADaM results still join into one report and one exit code.
- **The IG version list is fixed in Fleet**, not read from `core list-rule-sets`, so that `fleet check` gives the same answer in CI, where no engine is installed, as on a programmer's machine.

## Considered options

- **Keep resolution on each surface and share helpers.** Rejected: the drift came from four call sites choosing which helpers to call, and helpers do not stop a fifth surface from skipping one.
- **Let the environment variable win, as today.** Rejected for the reason above.
- **Keep the engine's `-lr` behaviour and warn that official rules did not run.** Rejected: one line in a long report is easy to miss at delivery.

## Consequences

- A study with custom rules takes about twice as long to validate.
- A new CORE release that adds an IG version needs a Fleet release before Fleet accepts it.
- A setup problem (unclear standard, unsupported IG version) is its own outcome, "could not run": exit 2 on the CLI, an exception on the verb, and an `outcome` field on the MCP tool.
