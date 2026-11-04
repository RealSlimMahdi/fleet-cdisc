# Merge reads as SAS MERGE and stops on a clash

The alpha audit found that the join verbs of Fleet changed data with no message. `merge(keep=)` kept only the key and the listed columns, so every other pipeline column was lost (c1-17). A non-key column on both sides gave an `X_right` column and kept the old left value (c1-12, c1-131). A repeated subject in ADSL multiplied the AE records in `merge_adsl`, and `join_adsl` and `study_day` took one row by input order (c1-14). `how="full"` lost the key of a subject on the right only (c1-15). We decided to make the join verbs read as SAS MERGE and stop as admiral `derive_vars_merged` stops (Mahdi, 4 November 2026).

## The decision

- **`keep` limits the right dataset.** `ae.sdtm.merge(dm, on="USUBJID", keep=["AGE"])` reads as `merge ae dm(keep=USUBJID AGE)`: every AE column stays. A `keep` name that is not in the right dataset raises with a did-you-mean. `where` filters the right dataset first, so it may use a column that `keep` leaves out. A spec `merge` block raises when its variable is not in the frame after the block.
- **A non-key column on both sides raises** in `merge`, `merge_adsl`, `join_adsl`, `first_date`, `last_date` and `count_events`, and the message names the columns. There is no `overwrite=` option: drop or rename the column first. This is the admiral rule; SAS keeps the right value with no message, which a QC program can miss.
- **ADSL holds one record per subject** (ADaMIG 1.3). `merge_adsl`, `join_adsl`, `study_day` and `baseline_flag` with a reference frame, and the carry-through join of `fleet run`, raise and name the first 5 repeated keys. Identical rows count as one row.
- **Generic `merge` decides nothing about the key**, because one-to-many is a normal join (DM onto AE). It warns at `to_frame()` when a key repeats on both sides (many-to-many), as the SAS NOTE on repeats of BY values. `validate="m:1"`, `"1:m"` or `"1:1"` makes the rule strict; the error at `to_frame()` names the repeated keys. The check waits for `to_frame()`, so `merge` stays lazy.
- **`how="full"` gives one key column**, as SAS MERGE with no IN= and dplyr `full_join`.
- **Keys match exactly.** `"S1 "` and `"S1"` are two keys, in `merge` as in SAS.

## Considered options

- **Keep the old `keep` meaning and document it.** Rejected: a SAS programmer reads `keep` as a data set option, and the old meaning dropped columns with no message.
- **An `overwrite=` argument on a clash.** Rejected: it adds a choice for a case that a `drop` or a `select` states more clearly.
- **Warn on any repeated key in `merge`.** Rejected: one-to-many joins are normal and would warn on every DM to AE merge.

## Consequences

- A program that merged a frame with shared columns (STUDYID, DOMAIN) now raises. Give `keep=`, or select the right columns.
- A spec `merge` block with no `keep:` brings every column of its dataset and raises on a shared column. Give `keep: [VAR]`.
- The many-to-many warning reads the left plan once more at `to_frame()`.
