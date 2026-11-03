# One flagged record per group, and units stated for QTc

The alpha audit of 2 November 2026 (package C) found three verbs that gave a wrong flag or value with no message. `baseline_flag` chose by date only, so a NOT DONE record on the last date took the baseline flag and every record on that date got it. `flag(criteria="last", where=)` lost the flag when a record that failed `where` tied on `order_by`, so ABLFL, BASE and CHG were lost. `qtc` read RR in seconds while most studies hold it in ms, so QTcF was ten times too low. We decided that a baseline needs a result, that one record per group gets the flag, chosen as SAS `LAST.` chooses it, and that `qtc` reads RR in ms unless the call says otherwise.

## The decision

- **A baseline needs a result.** `baseline_flag` takes a record only when its result is not null or blank and `--STAT` is not NOT DONE. The result is `--STRESC` when present, else `--ORRES`, or the new `result_col=`. When `--ORRES` is present and is not the result, it must hold a value too, unless `--DRVFL` is Y (CG0553). With no result column the verb stops. SDTMIG 3.4 defines `--LOBXFL` as the last non-missing value prior to RFXSTDTC.
- **One record on a tie, as SAS `LAST.`** (Mahdi, Q1 A). A tie on the last date and time goes to the last record by the new `order_by=`, default `--SEQ`, then input order, with a warning when `order_by=` is not given. This is the admiral `ad_advs.R` order and the result a SAS QC program with PROC SORT and `LAST.` gives. CORE FB2603 and FB2604 expect one flag per group.
- **`where` filters first.** In `flag(criteria="first"/"last")` a record that fails `where` takes no part, even on a tie. On a tie among candidates, `last` takes the last input record and `first` the first, as SAS PROC SORT with EQUALS and admiral. `flag_all=True` takes the extreme over candidates only.
- **QTc reads RR in ms by default** (Mahdi, Q2 A), as admiral `compute_qtc`. `rr_unit=` takes `ms`, `msec`, `s` or `sec`. The verb stops when a value cannot be in its unit: an RR under 10 in ms, an RR of 10 or more in seconds, or a QT under 10 ms.

## Considered options

- **Flag every record on the tied date** (sdtm.oak). Rejected: CORE fires on each tie, and a QC program with `LAST.` shows a difference on each.
- **Stop on a tie until `order_by=` is given.** Rejected: a study with triplicate ECGs stops at the first run.
- **Keep RR in seconds as the default.** Rejected: most calls would need `rr_unit="ms"`, and the call would not look like the admiral or SAS code QC compares it with.
- **No default RR unit.** Rejected: every define.yaml `qtc` entry would need an edit before it runs.

## Consequences

- `baseline_flag` on a frame with no `--STRESC` or `--ORRES` stops: give `result_col=`.
- Date-only data with replicates on the last date get one flag, not one per replicate, and a warning.
- `qtc` on RR in seconds stops until the call gives `rr_unit="s"`.
