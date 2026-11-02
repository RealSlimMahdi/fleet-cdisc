# Study run

A **study run** reads the study's define files, builds every dataset they declare from its inputs, and hands each built dataset forward. `fleet.plan_study` returns the study plan without building anything; `fleet.run_study` yields one built dataset per step and writes no file. `fleet run` is the command on top of it: it prints the plan, writes each dataset and sets the exit code. A run that cannot plan or build raises [`StudyRunError`][fleet.core.exceptions.StudyRunError], documented with the other [exceptions](core.md#exceptions). The rule for inputs is ADR 0006: every input is pinned, and only carry-through columns (declared with no derivation) are joined from the other inputs.

## plan_study

::: fleet.run.plan_study
options:
show_root_heading: true
heading_level: 3

## run_study

::: fleet.run.run_study
options:
show_root_heading: true
heading_level: 3

## Records

::: fleet.run.StudyPlan
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]

::: fleet.run.Step
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]

::: fleet.run.BuiltDataset
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]

::: fleet.run.ResolvedInput
options:
show_root_heading: true
heading_level: 3
filters: ["!^_"]
