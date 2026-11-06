# A study run stops on a declared variable that no input has

`fleet run` on the CDISCPILOT01 example wrote ADSL without SAFFL and ITTFL, and
exited 0. The define declared both with no derivation, because the example
script derived them inline, and no input had them. `select(spec=)` skipped the
absent columns with a `UserWarning` only. A QC programmer then gets an ADSL
with no safety population flag from a run that reports success.

## The decision

- **A carry-through column that no input has stops the run.** After a step is
  built, `run_study` checks each declared variable with no derivation. When
  the built dataset does not have it, a `StudyRunError` names the dataset, the
  variables and the inputs, and says how to fix it. Nothing is written for the
  step: `fleet run` keeps the old file.
- **`optional: true` on a variable is the permanent exception.** It is in the
  define, so a reviewer sees it. It applies only to a variable with no
  derivation. An optional variable is still carried when an input has it.
- **`--no-strict` (`strict=False`) is the run-wide exception.** It already
  turned an unknown algorithm into a warning; it now does the same for an
  absent variable. It is for a draft run, not for a study that is final.

## Considered options

- **A per-dataset list (`allow_absent: [RFXSTDTC]`).** Rejected: the list is
  far from the variable, so a renamed variable leaves a stale entry.
- **A run-level list (`--allow-absent ADSL.SAFFL`).** Rejected: the exception
  is in the command line, so two programmers who run the same study get
  different datasets.
- **An error only for `mandatory: true`.** Rejected: the pilot marks SAFFL
  `mandatory: false`, so it would still be lost with exit 0.

## Consequences

- The pilot ADSL now derives SAFFL and ITTFL in its define (`algorithm: flag`,
  `criteria: exists` on the pinned EX). Its DM marks RFXSTDTC and RFXENDTC
  `optional: true`: no input has them.
- `examples/minipilot` is a small study that `fleet run` builds end to end, from
  raw CSV files to ADSL, ADVS, ADAE and ADEX (finding c1-347).
