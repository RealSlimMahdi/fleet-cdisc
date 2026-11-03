# Every CORE finding blocks until the study accepts it

The alpha audit of 2 November 2026 (package H) found that `fleet validate` said `Status: PASS` and exited 0 on a DM without COUNTRY. Fleet read a `Severity` key that no CORE report has, so every finding became a warning, and `on_fail="raise"` never raised. Engine problems read as data failures: a timeout, a crash or a half-written report gave `FAIL` with an invented rule ID (`TIMEOUT-001`, `ENGINE-001`, `ERROR-001`), and the engine workers kept running after a timeout. We decided that Fleet invents no severity, that every finding blocks until the study accepts it with a reason, and that an engine problem is its own outcome.

## The decision

- **Every finding blocks** (Mahdi, Q1 A). A finding stops blocking only when `validation.accepted` in `study_config.yaml` lists its rule ID and its dataset with a reason, as an SDRG explanation does. An accepted finding stays in the report with its reason.
- **Status words.** `PASS`: at least one rule executed and no finding. `FINDINGS (n)`: every finding accepted. `NOT ASSESSED`: the `Rules_Report` shows no executed rule (`SUCCESS` or `ISSUE_REPORTED`). `FAIL`: a finding blocks. `COULD NOT RUN`: the engine crashed, timed out, wrote no report or wrote a report Fleet cannot read. Exit codes: 0, 0, 0, 1, 2.
- **Study-level findings.** In a sweep they get their own `STUDY` block, which is not counted as a dataset. In a single-dataset run (the verb, the MCP tool) they are information only: one dataset cannot show what the study lacks.
- **The engine run.** Fleet reads the return code before the report, runs the engine in its own process group and stops the whole group on timeout. The limit comes from `--timeout`, else `validation.timeout`, else 300 s. Fleet no longer passes `-rr`: the standard JSON report has the same keys, and CORE 0.17 crashed in the raw-report writer.
- **Tested engine versions.** `fleet.validation.engine.TESTED_ENGINE_VERSIONS` lists the CORE versions Fleet runs on. `fleet install-engine` installs the default tag from that table; the report header and `fleet doctor` name any other version. A weekly workflow (`core-canary.yml`) runs Fleet on the newest CORE release; a version joins the table only after it passes.

## Considered options

- **No finding blocks by default** (Q1 B). Rejected: a CI job stays green on a DM without COUNTRY.
- **A fixed list of blocking rules** (Q1 C). Rejected: no CDISC document states such a list, and the QC programmer would have to defend it.
- **The executability field decides** (Q1 D). Rejected: it says how reliable a rule is, not how serious its finding is.
- **Keep the engine errors as findings.** Rejected: a timeout on a large LB is not a data problem, and exit 1 sent the programmer to fix data that was correct.

## Consequences

- The first run of a study fails on findings that the study must fix or explain (for example CORE-000767 when there is no FA domain). Each explanation is written once, in the study config, with its reason.
- `fleet validate` exits 2 more often: every engine problem is "could not run".
- CORE v1.0.0 (released 3 November 2026) adds rules: on the same DM and AE it gives 13 findings where 0.15.0 gives 8, among them CORE-000510 on non-split datasets. It ships no ADaM rules and stops with "No rules were selected"; Fleet reads that as `NOT ASSESSED`, as 0.15.0 already gave for ADSL (0 rules executed).
