# A count cell shows every number the table needs

The audit found three rendered cells that hide a number the ARD holds:

- In a SOC/PT table the SOC row had empty cells, so the SOC subject count never reached the table, and the PT rows (3 records for 2 subjects) cannot give it (c1-451).
- When a spec asked for `n_events`, the table dropped the event count, so the explorer choice "+ events" changed nothing (c1-452).
- The LBT04 cells printed `n (%)` with a percent of a per-cell N that the table did not show (c1-453).

We decided on the common SAS shell forms (Mahdi, 4 November 2026, answers A and A; c1-453 without a decision).

## The decision

- **The SOC row prints its subject count**: `NERVOUS 2 (50.0%)`, the common SAS shell and the gtsummary form. A parent of continuous rows (PARAMCD in a lab summary) stays blank. A page never ends on a SOC row: the stub test reads the row type.
- **An event count prints in the same cell**: `2 (50.0%) 3`, the SAS "n (%) E" form, also with `n` alone (`2 3`). A footnote explains the form: "n (%) E: n = number of subjects, E = number of events."
- **A cell with a per-cell N prints `n/N (%)`**, and `n/N` when n or N is 0: `1/2 (50.0%)`, `0/3`, `0/0`. This is the NEST LBT04 form and the ARD stat label "n / N (%)".

## Considered options

- **tern form for the SOC count**: a blank SOC stub, then "Total number of patients with at least one AE". Rejected: one more row per SOC, and a SAS shell with counts on the SOC row no longer matches line by line.
- **Keep the SOC row blank.** Rejected: the SOC count can be checked only in the ARD.
- **A second row "Number of events" under each level**, as tern. Rejected: the table doubles in length and no longer matches a one-row-per-PT shell.

## Consequences

- A QC programmer who validates against a NEST or tern program maps the SOC count to another row.
- A parser or a PROC REPORT compare must split three values in an "n (%) E" cell.
- The ARD does not change; only the rendered cells and the footnotes do.
