# SAS files follow SAS rules: a blank is missing, a missing key matches, transport is version 5

The alpha audit of 2 November 2026 (package F) found that Fleet read and wrote SAS files by Polars rules, not SAS rules. A blank character value stayed `""`, so `is_null()` missed it and seven TLG templates printed rows with no label. Once a blank becomes null, a Polars join drops a null key, where SAS MERGE BY matches missing to missing. The XPT writer made a version 8 file with the member `DATASET` and stored a date as DATETIME seconds, and both directions needed pandas, which no documented install provides. We decided that every SAS file follows the SAS rule at the reader and the writer, and that every verb join follows SAS MERGE BY.

## The decision

- **A SAS blank reads as null.** SAS has one character missing value, the blank, and an XPT file cannot tell a blank from a missing value. The XPT and SAS7BDAT reader turns `""` into null, with no opt-out. admiral asks for the same step (`convert_blanks_to_na`) before any derivation.
- **A missing key matches a missing key.** Every verb that joins on keys the user names (`merge`, `pick`, `first_date`, `last_date`, `count_events`, `merge_adsl`, `flag` with `exists`, `flag_relative`, `derive_param`, the pin joins and the TTE joins) joins with `nulls_equal=True`. SAS MERGE BY and dplyr do the same, so an admiral port and a SAS double program give the same records.
- **A blank from another tool is a value until the user says otherwise.** `fleet.compare` stays exact: `""` against null differs. `blank_is_missing=True` (`--blank-is-missing`) reads `""` as null on both sides, keys included, and the settings line shows it.
- **XPT goes through the Polars route of pyreadstat, version 5.** Read with `output_format="polars"`, write a Polars frame with `file_format_version=5`. The member is the file name (FDA TCG 3.1.1). A date is SAS days with DATE9, a datetime seconds with DATETIME20, a time seconds with TIME8. NaN and infinity become missing; infinity warns. A name over 8 characters, a label over 40 or a value over 200 bytes stops the write, because a cut value is a silent change.
- **A value that is not ASCII is written as UTF-8 bytes, with a warning.** TCG 3.1.5 allows UTF-8 and advises against it, and a stop would block every study that is not for the FDA.
- **A CSV file holds no types; Fleet decides them in the open.** `load_raw_data` infers from every row and keeps a column with a leading zero as text, with a warning. `fleet run` reads define type `text` variables, and their raw sources, as text. `fleet compare` types a CSV side against the other side, or across both CSV sides: text when a value has a leading zero or is not a number, a number otherwise, and `--text` as the `$` informat.
- **The encoding is the user's to name.** `load_raw_data(..., encoding=)` reaches pyreadstat and Polars, and `--encoding` is on `fleet compare` and `fleet validate`. A keyword a reader does not take raises.

## Considered options

- **A blank rule in the TLG engine** (`prepare_frame`). Rejected: it cannot reach ADSL or the verbs, so ADSL and the table would disagree. One fix at the reader covers them all.
- **Keep the pandas route and declare pandas and pyarrow in the `io` extra.** Rejected: two heavy dependencies for a conversion the reader does natively, and the pandas route stores a Polars date as DATETIME.
- **Stop the write on a value that is not ASCII.** Rejected for the reason above; the warning names the column.
- **`""` and null always equal in `fleet compare`.** Rejected: the two frames give different `is_null()` results, so a production pipeline that skipped the blank step would pass QC and still give a wrong table.
- **All CSV columns as text in `fleet compare`.** Rejected: AVAL `1.10` against `1.1` would differ and `--abs-tol` would do nothing.

## Consequences

- `pyreadstat>=1.3.3` is the floor of the `io` extra: 1.2.x and 1.3.0 reject a Polars frame. A CI job installs the `io` extra alone and checks that pandas and pyarrow are absent.
- `DatasetChecker.write_xpt` calls `save_xpt` with the define labels and refuses a file named after another dataset.
- `fleet run --format xpt` and `fleet tdd build --format xpt` write dataset and variable labels from `define.yaml` and the packaged SDTMIG structures.
- This amends ADR-0002, which assumed that pandas lives in the `io` extra.
