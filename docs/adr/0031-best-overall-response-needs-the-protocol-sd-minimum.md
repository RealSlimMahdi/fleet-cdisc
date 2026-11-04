# Best overall response needs the protocol SD minimum

Alpha audit finding c1-407 found that `best_overall_response` applied no minimum time for SD or NON-CR/NON-PD: a subject with SD on day 14 and PD on day 56 got BOR SD, where RECIST 1.1 gives PD. Finding c1-408 found that the documented chain took the best response over all records, so a response after the first PD set BOR. We decided that the SD minimum is a required argument, and that the verb stays a plain minimum over the records it gets, with `filter_pd` documented first (Mahdi, 4 November 2026).

## The decision

- **`date_col`, `reference_date` and `min_sd_days` are required, with no default.** RECIST 1.1 section 4.4.3 says the minimum is protocol specified, so no value is safe as a default.
- **An SD or NON-CR/NON-PD before `reference_date + min_sd_days`, or with a null date, counts as NE** before the rank, as admiralonco `derive_param_bor` (`ADT >= reference + minimum`). CR and PR have no minimum.
- **`min_sd_days=0` switches the rule off.** The two date columns are then not read.
- **The verb does not cut at the first PD.** The docstrings and the module example run `filter_pd` on a copy, then join BOR back to the full ADRS.

## Considered options

- **Optional arguments with a warning.** Rejected: a programmer who misses the warning still gets SD for B05.
- **A 42-day default from RANDDT, as the admiralonco `bor_sd` event.** Rejected: with a 35-day protocol minimum, SD on day 38 gives NE instead of SD.
- **No rule, a docstring note and a hand recode per study.** Rejected: each study needs a new reviewed recode.
- **Cut at the first PD by default (c1-408 option B).** Rejected: under iRECIST or a SAP that counts post-PD response the result changes, and existing calls break.
- **Warn when a better response follows a PD (c1-408 option C).** Rejected: the number stays wrong, and QC must read the log.

## Consequences

- Every old call stops with a TypeError until the programmer adds the three arguments. A study with no protocol minimum writes `min_sd_days=0`.
- A QC programmer who follows RECIST and a production program that calls the verb without `filter_pd` still differ on a response after PD: the docstring states it.
