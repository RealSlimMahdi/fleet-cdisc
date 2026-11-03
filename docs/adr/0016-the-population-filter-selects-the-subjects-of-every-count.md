# The population filter selects the subjects of every count

The alpha audit of 2 November 2026 (package G) found five TLG rules that gave a wrong number with no message:

- `adsl_filter` changed only the big N. A record of a subject outside the population still counted in n, so a percentage could pass 100.
- On a continuous table, n counted distinct subjects, also those with a missing value and twice for a subject with two records. Q1 and Q3 used the Polars default, not the SAS one.
- `worst_case` ranked an unknown value below every listed value. With the default `relationship_order ['N', 'Y']`, a POSSIBLY RELATED event lost to N.
- The shift and abnormality tables guessed the post-baseline rule: `ONTRTFL` when present, else `ABLFL`. Without both, screening records counted as post-baseline.
- The QTc table pooled every parameter and visit, and the VS summary pooled every visit.

We decided that a table counts only what the programmer states, and stops when a rule is missing.

## The decision

- **The population filter selects subjects** (Mahdi, Q1 A). The filter selects the ADSL subjects for N, and the engine keeps only the analysis records of those subjects for n. A subject in ADSL but outside the filter is left out with an INFO note on the `fleet` logger. A subject not in ADSL at all is left out with a warning, because that is a data issue. This is the SAS idiom `where saffl = 'Y'` on both datasets. An `adsl_filter` with no ADSL stops.
- **Continuous n is PROC MEANS N** (Mahdi, Q2 A). On a table with continuous statistics, n is the count of non-missing values in the cell. A null value never counts. There is no warning: the programmer selects the analysis records (for example with `ANL01FL`). Q1 and Q3 follow SAS QNTLDEF=5 (R type 2).
- **An unknown value stops the worst-case table** (Mahdi, Q3 A). `relationship_order` keeps its default `['N', 'Y']`, and a value outside the order stops the table with the name of the spec field to set. A null or blank value still ranks below every listed value.
- **The post-baseline rule is a stated prefilter** (Mahdi, Q4 A). `LBShiftSpec` and `LBAbnormalSpec` default to `ONTRTFL = 'Y'` and not the `ABLFL` record. Without these columns the table stops and proposes a SAP rule, for example `pl.col("ADY") > 1`. `prefilter=None` survives a YAML round trip.
- **QTc percentages use the visit base** (Mahdi, Q5 A). One block per parameter and visit, with an n row: the subjects with a non-missing AVALCAT1 in the arm, parameter and visit. `percent_base="adsl"` selects the big N instead. Two records of one subject in one block stop the table.
- **VS summary per visit.** `VSSummarySpec` rows default to PARAMCD and AVISIT, as LB and EG do.

## Considered options

- **Keep the filter on ADSL only** (Q1 B). Rejected: n and N come from two populations.
- **Count subjects for continuous n, with a warning on duplicates** (Q2 B). Rejected: a hidden rule behind the scene. The programmer owns the record selection.
- **Change the relationship default to the sponsor terms** (Q3 B). Rejected: AEREL has no CDISC codelist, so no default fits every study.
- **Keep the ONTRTFL or ABLFL guess** (Q4 B). Rejected: the rule changes with the columns present, with no sign in the output.

## Consequences

- A table with `adsl_filter` and analysis records outside the population now gives lower n and lower percentages.
- Continuous n can change where a cell has null values or several records per subject. Q1 and Q3 can change.
- Shift and abnormality calls on data without ONTRTFL must state a prefilter.
- Studies with sponsor AEREL terms must set `relationship_order`.
- The egt05 and vst01 goldens changed.
