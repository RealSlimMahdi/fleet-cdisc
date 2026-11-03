# Grading criteria are generated from admiral, with their provenance

The alpha audit of 2 November 2026 (package D) found that the bundled CTCAE and DAIDS criteria gave wrong grades with no message: a null BNRIND gave grade 0 for ALT at 22 x ULN, a unit in lower case gave null, a term with several subgroups or units took the cut-offs of the last entry, CTCAE v5 INR had no absolute cut-offs, and v4 Hemoglobin increased raised an error. Only 4 of 399 entries had a test. The cause was the format: grade-level rules, written by hand, that could not state an AND, a null arm or an addition. We decided that the criteria files are generated from the admiral metadata by a kept script, keep the admiral text of each term, and are tested against a frozen admiral grid.

## The decision

- **One source, generated** (Mahdi, Q2 A). `scripts/regen_grading_criteria.R` parses each admiral `GRADE_CRITERIA_CODE` and `FILTER` with R's own parser and writes them as expression trees (schema version 2). Each term is the ordered arms of the R `case_when`: the first arm that holds gives the grade, a null condition counts as false, and no arm gives null. Nobody edits the JSON by hand; a Fleet rule that must differ from admiral goes in the script's `OVERRIDES`, with its reason.
- **Provenance in the file.** Each file names the admiral version, the dataset and the generator. Each term keeps the admiral GRADE_1 to GRADE_5 text, COMMENT and the R code, so a reviewer compares an arm with its source without R.
- **admiral rules for the dataset.** The term and the unit match without case. Of a term's entries, the first population filter that holds is used (a null filter gives a null grade), then the entry of the row's unit. A row with another unit, a null unit or no entry gets null, and every row stays in its order (admiral drops a row whose filter is NA; Fleet keeps it with null). With several units for a term, `unit_var=` is required.
- **INR takes the worst case** (Mahdi, Q1 A). CTCAE v5 and v6 INR increased apply the absolute cut-offs and the baseline multiples, and the higher grade wins, as the admiral COMMENT says ("assume on anticoagulation"). A SAP with another rule uses a custom criteria file.
- **`signif_dig` defaults to 15**, as admiral `signif_digits`.
- **The old format is dropped** (Mahdi, Q3 A). A file without `schema_version` stops with a message that says how to rewrite it. Fleet has no release yet.
- **The oracle is a frozen admiral grid.** `scripts/regen_admiral_grading_grid.R` grades 34,146 seeded rows (every entry, every cut-off, BNRIND, SEX, age band and unit spelling) with admiral 1.4.1 into `tests/fixtures/goldens/grading/admiral_grid.parquet`. CI compares Fleet with it and needs no R.

## Considered options

- **Keep the grade-level format and correct the known terms by hand** (Q2 B). Rejected: the other entries stay hand-made, and the next admiral change is found only by chance.
- **Store the admiral R code and translate it at load.** Rejected: Fleet would need an R parser at run time. R's own parser, run once by the script, is exact.
- **Convert old-format files at load** (Q3 B). Rejected: that format cannot state AND or null arms, so a converted file can still grade wrongly.

## Consequences

- Grades change for null BNRIND, unit case, DAIDS subgroups, multi-unit terms, CTCAE v5/v6 INR and the terms the old files had wrong.
- A custom criteria file must be rewritten in schema version 2.
- Updating to a new admiral version is: run the two scripts, read the JSON diff with its `source` text, run the tests.
