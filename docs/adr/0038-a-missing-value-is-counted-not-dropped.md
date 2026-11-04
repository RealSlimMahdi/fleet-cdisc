# A missing value is counted, not dropped

The audit found three places where a table drops a null without a sign, so the rows do not add up to N:

- A subject in the population with a null arm (a screen failure with TRT01A null) stopped the DM table with a raw `TypeError` (c1-430), and a `"*"` Total pool counted analysis records that have no arm, so Total was larger than the sum of the arms (c1-431).
- A null category value (RACE null, AESEV null) had no row and no message (c1-442).

We decided to exclude a null arm with a warning, and to count a null category in a "Missing" row (Mahdi, 4 November 2026, answers A and A).

## The decision

- **A null arm is in no column.** `compute_big_n` leaves the subjects out of every N, a `"*"` pool included, and raises one `UserWarning` that names the arm column, the count and up to five USUBJIDs. This is the nearest to SAS: PROC FREQ leaves out a missing class level and prints a frequency-missing count. A `"*"` pool pools every arm present; a null is not an arm.
- **A null category counts in a "Missing" row**, last in its block, only when a null exists. The percent base is big N. A blank string counts as null, so an XPT file and a Parquet file give the same table.
- **The rule is a spec field, `missing: MissingLevel(columns, label)`**, with a default per template, not per row: DM (SEX, AGEGR1, RACE, ETHNIC), AET03, AET04 and the relationship table (the ranked level), DST01 (EOSSTT), ENT01 (SITEID), PDT01 (DVDECOD). DCSREAS (completers), DTHCAT (it has "Unknown"), PARAMCD and AVISIT get no Missing row. The builder verb is `.missing()`.
- **`missing: null` switches the rule off. `label: null` adds no row**: the count goes to the ARD `warning` column of that variable, with one `UserWarning`.
- **In a worst-case table a ranked value beats a null.** A subject with MILD and a null intensity counts under MILD; a subject with only a null counts under Missing.

## Considered options

- **Stop with a SchemaError for a null arm.** Rejected: every normal ADSL with screen failures would need a population filter, and the zero-config call stops.
- **A "Missing" arm column.** Rejected: the column is not in the mock shell.
- **No Missing row, only a warning.** Kept as `label: null`, not the default: the rendered table does not add up to N.
- **Percentages on non-missing values (tern, PROC FREQ default).** Rejected: every percentage of the block differs from a double program that divides by big N.

## Consequences

- A QC programmer can miss the null-arm warning when a randomized subject lost the arm by a data error; N is then low by one. Read the log, or set a population filter.
- A SAP that counts a missing severity as severe sees an extra row in PROC COMPARE until it sets `missing: null` or derives ASEV.
- No golden table changed: the pilot fixture has no null in those columns.

References: FDA CDER Standard Safety Tables and Figures IG v2.0, section 2.1.2; SAS PROC FREQ, missing values.
