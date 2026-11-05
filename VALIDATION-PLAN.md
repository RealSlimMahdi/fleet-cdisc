# Spec: fleet.validation, as built

Status: decided and built (issues #121 and #124 to #127, ADR-0003). Kept as the design record; the code is the reference now. Derived from the code at commit `0425f6a` (fleet 0.1.2.dev7) and from probe runs against CORE engine 0.15.0 on 2026-09-11. Sections marked **OPEN (Qn)** wait for a grilling decision. Sections marked **AS BUILT** describe what the code does today, even where the docs say otherwise.

Related: `docs/validation-strategy.md`, `docs/concepts/validation-core.md`, `docs/concepts/custom-rules.md`, issues #97 and #119.

## Problem Statement

A statistical programmer who has produced an SDTM domain or an ADaM dataset with Fleet must know, before delivery, whether it conforms to the CDISC Implementation Guide. In SAS shops this is a Pinnacle 21 run. The programmer needs four things: a report a reviewer can read, a pass or fail a CI job can gate on, a way to add sponsor rules the standard set does not cover, and a link from each finding back to the verb that produced the variable.

Two more moments exist. A team lead wants to sweep every written dataset of a study in one command at delivery. An AI agent wants the same verdict in a machine-readable shape.

## Solution

**AS BUILT.** Fleet wraps the official CDISC Rules Engine (CORE) behind one Python service and exposes it on three surfaces: the namespace verb `.validate()`, the CLI command `fleet validate`, and the MCP tool `fleet_validate`. The service writes the frame as a Dataset-JSON file, runs the engine as a subprocess, parses the raw JSON report into a validation result made of errors, warnings and infos, and prints a report through the `fleet.validation` logger. Custom rules in the CORE YAML schema run in the same engine. The engine lifecycle is managed by `fleet install-engine`, `fleet uninstall-engine` and `fleet doctor`. Rule authoring is helped by `fleet add-rule`, `fleet check-rule` and the rule section of `fleet check`.

**OPEN (Q1, Q2, Q3).** What the verdict means. Today the engine emits no severity, so every conformance finding becomes a warning, the result is valid, the CLI exits 0 and `on_fail="raise"` does not raise. A run that executes zero rules (every ADaM run today) is reported as PASS.

## User Stories

Stories the code delivers today are unmarked. Stories the docs promise but the code does not deliver are marked **NOT MET**, with the evidence.

1. As a stat programmer, I want to chain `.validate("AE")` at the end of an SDTM pipeline, so that the conformance report prints and the chain continues.
2. As a stat programmer, I want `.validate("ADSL")` on an ADaM chain to select the ADaM standard by itself, so that I do not name the standard twice.
3. As a stat programmer, I want the full result on `last_validation` after the verb, so that I can inspect findings in code.
4. As a stat programmer, I want each finding on a derived variable to name the verb that produced it, so that I go straight to the line to fix.
5. As a stat programmer, I want `on_fail="raise"` to stop the pipeline when the dataset does not conform, so that a bad dataset never reaches the next step. **NOT MET**: with the official rules, no finding is ever an error, so the raise never fires (see C1).
6. As a stat programmer, I want a PASS on a dataset to mean the rules ran and found nothing, so that I can sign it off. **NOT MET**: a DM with a duplicate USUBJID, a negative AGE and three missing required variables reports PASS (see C1). An ADSL run executes zero rules and reports PASS (see C2).
7. As a stat programmer, I want controlled terminology checks to run, so that SEX = "X" is caught. **NOT MET**: the engine is never given a CT package, so codelist rules do not run (see C3).
8. As a stat programmer, I want a choice of report detail (smart, summary, full), so that a long report stays readable.
9. As a stat programmer, I want repeated findings grouped with row ranges, so that a rule failing on 500 rows takes one block.
10. As a stat programmer, I want to validate against the IG version declared for the study, so that I do not retype it. **NOT MET on the verb**: the verb defaults to a built-in constant and does not read the study config; only the CLI reads it (see C5).
11. As a stat programmer, I want an invalid IG version rejected with the list of supported versions, so that a typo does not run the wrong rules. **NOT MET on the CLI**: the CLI passes any string to the engine (see C6).
12. As a stat programmer, I want sponsor rules in a directory to run with the official rules, so that SOP checks share one report.
13. As a stat programmer, I want the rules directory from the study config used when I do not pass one, so that the team runs the same rules. **NOT MET on the verb and MCP**: only the CLI reads `validation.custom_rules` (see C7).
14. As a stat programmer, I want `fleet add-rule` to give me a schema-valid skeleton with a unique ID, so that I only write the Check block.
15. As a stat programmer, I want `fleet check-rule` and `fleet check` to reject a malformed rule before the engine sees it, so that a YAML typo fails fast in CI.
16. As a team lead, I want `fleet validate` with no arguments to sweep the configured SDTM and ADaM directories, so that delivery validation is one command.
17. As a team lead, I want `fleet validate` to exit 1 when any dataset fails, so that CI blocks the delivery. **NOT MET**: exit 1 fires only when the engine itself fails (see C1).
18. As a team lead, I want one HTML report for the sweep, so that I archive it with the delivery.
19. As a team lead, I want a shared engine path in the study config, so that every programmer runs the same engine build. **NOT MET on the verb and MCP**: only the CLI and `fleet doctor` honour `validation.engine_path` (see C7).
20. As a team lead, I want to know how many rules ran and how many could not run, so that a PASS on a single dataset is not mistaken for a full study check. **NOT MET**: the engine's rules report is discarded, and execution errors are silenced as noise (see C2, C4).
21. As a QC programmer, I want an engine crash or timeout reported as "could not run", not as a data failure, so that I do not open a data investigation for an infrastructure problem. **NOT MET**: a timeout is an error finding `TIMEOUT-001` and the dataset reads FAIL (see C8).
22. As an AI agent, I want `fleet_validate` to return the verdict and findings as JSON, so that I can act on them.
23. As an AI agent, I want the MCP tool to honour the study config like the CLI, so that I validate with the same rules as the humans. **NOT MET** (see C7).
24. As a new user, I want `fleet install-engine` to fetch the right binary for my platform and `fleet doctor` to confirm it runs, so that setup is two commands.
25. As a documentation reader, I want the examples in the docs to run, so that I can copy them. **NOT MET**: `.validate(domain="AE")` raises a TypeError (see C9).

## Implementation Decisions

All items in this section are **AS BUILT** unless marked OPEN.

### Package shape

- One package, `fleet.validation`, with these parts: the result models, the service, the provider abstraction, the official engine wrapper, the engine installer and discovery, the lineage join, the rule scaffolder and checker, and the vendored CORE rule JSON schema.
- The rule snapshot (`fleet init rules`) lives outside the package in the core scaffolders and writes YAML under `metadata/*/rules/`. It records ID, version, status, description, message, rule type, sensitivity and executability. It records no severity, because CDISC publishes none. Nothing in the validation package reads the snapshot.
- The engine is the CORE binary, run as a subprocess with the engine directory as working directory. There is no in-process rule execution and no second engine.

### Engine invocation

- The frame is collected and written as Dataset-JSON v1.1 to a temporary directory. The dataset name is the domain or dataset name in upper case.
- Command: `validate -s <sdtmig|adamig> -v <X-Y> -dp <file> -o <out> -of JSON -rr`, plus `-lr <dir>` when custom rules are given. The dotted IG version is turned into the dashed form for the engine.
- The custom rules path must exist and must be a directory. The engine loads every YAML file in it.
- Timeout is fixed at 300 seconds and is not exposed on any surface.
- Not passed to the engine: controlled terminology package, Define-XML path and version, rule include or exclude lists, dictionaries, pool size. The engine therefore runs without CT and without define metadata.
- A legacy `core.py` path is run with the bare `python` on PATH.

### Engine discovery

- Order: `FLEET_RULES_ENGINE` environment variable, then `validation.engine_path` in the study config when a study root is given, then the managed install under the Fleet home directory, then the legacy sibling checkout.
- The CLI and `fleet doctor` pass the study root. The verb, the service and the MCP tool do not, so step two is skipped for them.
- The managed install is the latest GitHub release of the engine, or a tag given with `--version`. The engine version is not pinned in the study config and is not recorded in the result.

### Result model

- A validation result has a dataset name, a dataset type, a model version, a total, and three lists: errors, warnings, infos. A result is valid when the error list is empty. The summary status is PASS or FAIL from that flag.
- A finding has a severity, a rule ID, a message, and optional variable, rows affected, suggested fix, producing verb, verb method and spec reference.
- Severity is an enumeration of Error, Warning and Info.
- The dataset type and model version fields hold whatever the engine echoes back in lower case (`sdtmig`, `v3.4`) on the parsed path, and the request values (`sdtmig`, `3-4`) on the failure path.

### Parsing of the raw engine report

- Findings come from `Issue_Details`. Each row gives the rule ID, the message, the row number, and the variables. Template variables such as `$dataset_variables` are resolved from the parallel values list. For the two missing-variable rules the set difference is shown.
- Severity is read from a `Severity` key on the row. The engine writes no such key. The fallback is Warning. In practice every engine finding is a warning.
- Messages that match the engine noise patterns (evaluation dataset failed to build, rule evaluation error, rule execution error, operation failed, unknown exception) are dropped without trace.
- `Issue_Summary` rows for rule IDs not already seen in errors or warnings are added as warnings with no variable and no row.
- `Rules_Report` is discarded. The counts of rules that succeeded, reported issues, were skipped or hit an execution error are not kept.
- When the engine writes no report: a non-zero exit becomes one Error finding `ENGINE-001`; a zero exit becomes one Info finding `INFO-000`. A timeout becomes one Error finding `TIMEOUT-001`. Any other exception becomes one Error finding `ERROR-001`. These three synthetic rule IDs are the only source of Error severity today.

### The verb

- Signature: `validate(dataset_or_domain, version=None, rules_engine_path=None, custom_rules=None, report="smart", on_fail="warn")`. The first argument is positional only in practice; the keyword `domain=` is not accepted.
- The standard comes from the namespace class: SDTM namespaces validate as SDTM with default version 3.4, ADaM namespaces as ADaM with default version 1.3.
- The version is checked against a whitelist before the engine runs: SDTM 3.1.2, 3.1.3, 3.2, 3.3, 3.4; ADaM 1.0, 1.1, 1.2, 1.3. An unknown version raises a derivation error listing the supported ones.
- The chain is collected, validated, and the findings are enriched with the chain's own lineage by exact variable name. The report prints. A namespace copy is returned with the result on `last_validation`.
- `on_fail` accepts warn, raise and ignore, the same vocabulary as `.compare()`. When the result is not valid: warn emits a UserWarning with the error and warning counts, raise raises `ValidationError`, ignore stays silent.

### The CLI

- `fleet validate [paths] [--standard sdtm|adam] [--version X.Y] [--custom-rules DIR] [--report PATH] [--config PATH]`.
- With no paths, the configured SDTM and ADaM data directories are swept. Directories are expanded to parquet, csv, xpt and sas7bdat files.
- The standard is forced by `--standard`, else guessed: a file stem starting with `AD` is ADaM, everything else is SDTM.
- The version comes from `--version`, else from the study config's `sdtm.ig_version` or `adam.ig_version` with dashes turned into dots, else the service default (3.4, 1.3). No whitelist check runs on the CLI path.
- Custom rules come from `--custom-rules`, else from `validation.custom_rules` in the study config.
- The engine comes from discovery with the study root, so `validation.engine_path` is honoured. A missing engine is a Fleet error, exit 1.
- Each dataset prints its smart report. The command ends with a one-line count of passed and failed datasets. Exit 1 when any dataset has at least one error finding, else exit 0. Because engine findings are never errors, exit 1 today means the engine failed on some dataset.
- `--report` writes one HTML table of every finding across datasets, HTML-escaped. This is a second renderer, separate from the per-result `save_html_report`, which is not escaped (issue #119).

### The MCP tool

- `fleet_validate(dataset_path, standard=None, version=None, custom_rules=None)`. The file stem is the dataset name. The inputs come from the run setup; the study config is looked for from the dataset's directory. Returns `outcome` (pass or fail), the dataset name, the standard, the valid flag, each run-setup input with its source, and the flat list of findings with severity, rule ID, message, variable and source. A refused setup, a missing file or a missing engine returns `{"outcome": "could not run", "reason": ...}`.

### Study configuration

- `validation.engine_path` and `validation.custom_rules`, both relative to the study root or absolute. `fleet init cfg` sets `custom_rules` to `metadata/custom_rules`.
- `sdtm.ig_version` defaults to `3-4`. `adam.ig_version` defaults to `1-1`. The verb, the service and the CLI outside a study default ADaM to 1.3.
- `ct.package` exists in the config but is not used by validation.

### Custom rules

- `fleet add-rule` writes a schema-valid skeleton with a `Check` placeholder, a `yaml-language-server` schema comment, an ID of the form `PREFIX-DOMAIN-NNN` auto-incremented per directory, and refuses an existing ID.
- `fleet check-rule` runs three levels: YAML parse, required top-level keys and a few structural checks, then full JSON Schema validation against the vendored CORE schema.
- `fleet check` runs the same check on every rule file in the configured directory and fails the gate on the first error per file. It also builds the run setup for SDTM and ADaM with no datasets: an unsupported IG version or a missing custom rules directory fails the gate, a missing engine is a warning.
- The CORE rule schema has no severity field. A custom rule cannot declare one.

### Reports

- Console reports go through the `fleet.validation` logger at INFO level, with a default stdout handler. Three shapes: smart groups identical findings and prints row ranges; summary prints one line per error and warning; full prints every field including infos.
- `save_html_report` on a result writes a styled page with error and warning cards. Infos are counted but not listed.

### Decisions from the grilling

Settled on 2026-09-11, round 1:

- **Q2, settled: errors block, warnings never block.** Exit 1 on the CLI and `ValidationError` on `on_fail="raise"` fire on errors only. The final summary line always prints the warning count.
- **Q3, settled: zero executed rules is "not assessed".** A third outcome next to pass and fail. Not valid, not failed, exit 0, `on_fail` does not fire, and the report says how many rules executed. The executed-rule count comes from the engine's rules report and is kept on every result.
- **Q4, settled: the study config is the source of the IG version on every surface.** Verb, CLI and MCP read `sdtm.ig_version` and `adam.ig_version` when a study config is discoverable. An explicit `version=` on the verb (or `--version` on the CLI) forces the version. The built-in default applies only outside a study.
- **Q5, settled: the CLI sweep validates the whole directory in one engine run.** The report is split per dataset. The verb keeps single-dataset mode and its report says so, with the counts of rules executed, skipped and unable to run.

Settled on 2026-09-25, run setup grilling, round 1 (architecture review candidate 1, issue #121, ADR 0003):

- **R1, settled: one module produces the run setup.** Verb, CLI, MCP tool and the `fleet check` gate get a run setup from it and resolve no input themselves.
- **R2, settled: the standard comes from the directory the dataset was swept from; the file-stem prefix applies to explicit paths.** When the two disagree, an enforcing mechanism applies (round 2 decides which). `--standard` or `standard=` forces the standard.
- **R3, settled: a sweep is one engine run per standard.** The SDTM and ADaM results join into one report with one exit code.
- **R4, settled: precedence is explicit argument, then study config, then environment variable, then built-in default.** `FLEET_RULES_ENGINE` no longer overrides `validation.engine_path` inside a study. Every report prints the engine path and version it used.
- **R5, settled: the MCP tool looks for the study config from the dataset's directory; the verb looks from the working directory.** Every report names the study config used, or says there was none.

Round 2:

- **R6, settled: a standard conflict refuses that dataset.** A dataset whose directory and file-stem prefix disagree is not validated. It is reported as "could not run: standard unclear, pass `--standard`". The other datasets run. The CLI exits 2. This covers setup problems only; C8 (engine crash or timeout) stays open.
- **R7, settled: the ADaM default is 1.3 everywhere.** `fleet init cfg` writes `adam.ig_version: 1-3` and always writes the key.
- **R8, settled: the engine version comes from `core version`, with a marker file written by `fleet install-engine` as fallback.** The report prints "unknown" when neither gives a version. Verified: `core version` prints `0.15.0` on the managed install.
- **R9, settled: `fleet check` builds a run setup with no datasets.** An unknown IG version or a missing rules directory fails the gate. A missing engine stays a WARN.
- **R10, settled: every entry point accepts `3-4` and `3.4`.** The run setup stores the dotted form and checks it. Only the engine call uses the dashed form.

Round 3:

- **R11, settled: official and custom rules run in two engine runs per standard.** The findings join into one report per dataset. Each finding records its source (official or custom). Resolves C16.
- **R12, settled: the IG version list is fixed in Fleet and matches what CORE ships.** SDTMIG 3.2, 3.3, 3.4; ADaMIG 1.0 to 1.3. A version not on the list is "could not run", with the supported versions listed. Resolves C17.
- **R13, settled: the verb refuses a namespace and dataset name conflict.** `adae.adam.validate("AE")` raises a setup error in every `on_fail` mode. The verb gets no `standard=` argument.
- **R14, settled: `fleet_validate(dataset_path, standard=None, version=None, custom_rules=None)`.** All inputs come from the run setup. A setup refusal returns `{"outcome": "could not run", "reason": ...}`.

Taken on Mahdi's behalf during the run setup grilling (engineering):

- The precedence of R4 applies to all five inputs, not only the engine.
- One `validation.custom_rules` directory serves both standards. The engine lists rules of the other standard as skipped and does not fail.
- The run setup is one frozen record, built by one function in `fleet.validation`. `fleet doctor` uses it for the engine and the study config.
- The report header prints each input of the run setup with its source (argument, study config, environment, default).
- The verdict questions Q1 to Q3 and C8 stay outside the run setup.

Still open:

- **Q1** Where severity comes from when the engine gives none.
- Round 2: engine failure as "could not run" (like compare exit 2); passing the CT package; the ADaM default version; glossary terms.

Taken on Mahdi's behalf (engineering, follows from the settled answers):

- The IG version whitelist applies on all three surfaces, not only on the verb.
- By extension of Q4, `validation.engine_path` and `validation.custom_rules` are read by the verb and the MCP tool the same way the CLI reads them: a study config discovered git-style from the working directory, explicit arguments override.
- The verb's single-dataset report prints one line of counts (executed, skipped, could not run), never the list of rules that could not run.
- The CLI `--report` uses the result's own HTML renderer, escaped, so one renderer remains (issue #119).

## Testing Decisions

A good test checks external behaviour at a seam and never the shape of the subprocess command beyond its contract.

Seams that exist today, from highest to lowest:

1. **The service seam.** `ValidationService` is replaced by a stub that returns a hand-built result. Used by the verb tests for `on_fail`, `last_validation` and lineage enrichment, and by the CLI test for config resolution. Prior art: `TestValidateResultAccess` in `tests/unit/test_error_experience.py`, `test_validate_defaults_resolve_from_config` in `tests/unit/test_cli.py`.
2. **The subprocess seam.** `subprocess.run` is patched to capture the engine command. Used to pin the `-lr` flag. Prior art: `TestCustomRulesEngineIntegration` in `tests/unit/test_custom_rules.py`.
3. **The engine seam.** Tests that run the real engine skip when it is not installed. Prior art: `TestCustomRuleEngine` in `tests/unit/test_custom_rule.py`. CI does not install the engine.
4. **The rule schema seam.** Rule YAML files are validated against the vendored JSON Schema. Prior art: `TestCustomRuleSchema`.

Gaps: no test feeds a raw engine JSON report to the parser, so severity mapping, the noise filter, the summary rollup and the discarded rules report are untested. No test pins the CLI exit code on a conformance finding. No test covers the two HTML renderers or the MCP tool.

Proposal for the spec after grilling: add a **raw report seam**. Save the raw JSON reports from the probe runs (DM with violations, ADSL with zero rules) as fixtures and test the parser and the verdict against them. This is the highest seam that does not need the engine and it is where every open decision lands.

## Out of Scope

- Define-XML and define.yaml validation (`DefineValidator`, `fleet check`, `fleet define-xml`).
- The trial design audit (`fleet tdd audit`).
- Controlled terminology validation at `assign` time (`fleet.ct`).
- Dataset comparison (`fleet compare`).
- The rule snapshot (`fleet init rules`), except where the grilling decides that the snapshot's severity should feed validation.
- Engine features Fleet does not use: dictionaries, Define-XML input, TIG use cases, Excel output.

## Further Notes

### Contradictions found

Each item names the two sides. The grilling resolves the ones that are decisions; the rest are defects to file.

- **C1. Nothing fails.** Docs: `fleet validate` "exit 1 on errors", `on_fail="raise"` "errors stop the build", r2r strategy shows `Status: FAIL, Errors: 2` for AE. Code: the engine emits no severity, the parser defaults to Warning, `is_valid` is true. Probe: DM with duplicate USUBJID, AGE = -5, missing SUBJID, SITEID and COUNTRY gives PASS, 0 errors, 8 warnings. Decision Q1, Q2.
- **C2. Zero rules is PASS.** Docs: "an ADaM run today executes your custom rules". Code: ADaM 1.3 runs zero rules (rules report empty), the result is PASS with total 0, and nothing says that no rule ran. Decision Q3.
- **C3. Validation checks no controlled terminology.** Code: no `-ct` and no `-dxp` is passed. Probe: passing the CT package `sdtmct-2023-12-15` adds no finding; passing the study's define.xml adds one define-versus-IG finding and still no codelist finding. Cause: the SDTMIG 3.4 rule set of CORE 0.15.0 has no rule that checks a variable value against its codelist (the only two CT rules concern the DOMAIN code and TSVALCD). SEX = "X" is caught by Fleet's assign-time CT layer (`ct=SEX`), never by `validate`. Decision Q8: document the split, or build a CT pass into validate.
- **C14. Docs claim a severity in the rule snapshot.** The validation strategy page says each snapshot YAML records "severity". The scaffolder writes none, and the CDISC Library rule has none. Defect in docs.
- **C15. Fleet's define.xml omits the variable Role.** With the define.xml passed, the engine fires CORE-001081: the define gives no role for STUDYID while the IG says Identifier. Defect in the Define-XML generator, outside this spec.
- **C4. Silenced execution errors.** Code drops 24 of 32 detail rows on the DM probe as noise, and drops the rules report. One cross-domain false finding survives (CORE-000739, "EX is not present in study"). Decision Q5.
- **C5. Two IG version defaults for ADaM.** Config default `1-1`, verb and service default `1.3`, docs say 1.3. Decision Q4.
- **C6. Whitelist on one surface only.** The verb rejects unknown versions; the CLI and MCP pass any string to the engine. The verb accepts SDTM 3.1.2 and 3.1.3, for which the docs list no published rule set. Round 2.
- **C7. Study config honoured on one surface only.** Docs (custom rules page): explicit parameter, then `validation.custom_rules`, applies to `.validate()`. Docs (CORE page): teams pin `validation.engine_path`. Code: only the CLI and `fleet doctor` read either; the verb and the MCP tool ignore both. Round 2.
- **C8. Engine failure reads as data failure.** A timeout or crash is an Error finding on the dataset, the status is FAIL, the CLI exits 1. `fleet compare` distinguishes "could not run" with exit 2. Round 2.
- **C9. Docs call a keyword that does not exist.** `.validate(domain="AE")` in the CORE concept page and the cheat sheet raises a TypeError. Defect.
- **C10. Two HTML renderers, one unescaped.** Issue #119, already filed.
- **C11. Report header format.** Docs show `Dataset Type: SDTM 3.4`; the code prints `sdtmig v3.4` on the parsed path and `sdtmig 3-4` on the failure path. Defect.
- **C12. Default report shape.** The validation strategy page says `print_report(report_type="summary")` with "full" as the alternative; the default is "smart". Defect in docs.
- **C16. Custom rules replace the official rules.** Docs and story 12: sponsor rules run with the official rules. Probe on 2026-09-25, CORE 0.15.0, one AE file: without `-lr` the rules report has 430 rules; with `-lr my_rules` it has 2, both local. The engine runs only the local directory. Run setup grilling round 3.
- **C17. The whitelist accepts versions the engine has no rules for.** Fleet accepts SDTMIG 3.1.2 and 3.1.3. `core list-rule-sets` on CORE 0.15.0 lists SDTMIG 3-2, 3-3, 3-4 and ADaMIG 1-0 to 1-3. Run setup grilling round 3.
- **C13. Info findings can be duplicated.** The summary rollup checks only errors and warnings for seen rule IDs, so an Info finding's rule would be added again as a Warning. Latent today because no engine finding is Info. Defect.

### Probe evidence

Engine 0.15.0, SDTMIG 3.4, single DM file with two rows: 331 rules skipped, 68 succeeded, 24 execution errors, 7 reported issues. Detail rows: 32, none with a severity key. After Fleet's parsing: 0 errors, 8 warnings, PASS.

Engine 0.15.0, ADaMIG 1.3, single ADSL file with two rows: 0 rules in the rules report, 0 findings, PASS in 0.05 seconds.

Executability of the seven DM findings that survive the noise filter: six "fully executable" (SUBJID unique, negative AGE, expected variables missing, required variables missing, EX not present, variable order), one "partially executable" (USUBJID unique). The 24 silenced rules are cross-dataset rules (ARM against TA, VISITNUM against SV, RFXSTDTC against EX, RACE against SUPPDM) and one define rule.

Same DM with `-dxp outputs/cdiscpilot01/define_sdtm.xml -dv 2-1`: 69 succeeded, 22 execution errors, 8 reported issues, one new finding (CORE-001081). Adding `-ct` on top of `-dxp` crashed the engine (SystemError in its cache loader); `-ct` alone runs and adds nothing.

CDISC Library serves `adamig-1-1`, `adamig-1-2` and `adamig-1-3`, so the define scaffolder can work from any of them.
