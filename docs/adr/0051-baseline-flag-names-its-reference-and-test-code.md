# baseline_flag names its reference date and its test code

Alpha audit finding c1-107 found two silent defaults in the SDTM
`baseline_flag`. The reference date was `RFSTDTC` by default, but SDTMIG 3.4
defines `--LOBXFL` as "the last non-missing value prior to RFXSTDTC". With no
`testcd_col`, the verb flagged one record per subject across all tests, so
WEIGHT got no flag when SYSBP had a later record. Neither choice was visible in
the call, so a QC programmer could not see it.

## The decision

- **`ref_col` is required.** The call names the reference date, for example
  `ref_col="RFXSTDTC"` for `--LOBXFL` or `ref_col="RFSTDTC"` for a sponsor
  `--BLFL`. sdtm.oak `derive_blfl` has no default for `ref_var` either.
- **`testcd_col` is required.** The call names the test code column, for
  example `testcd_col="VSTESTCD"`. `testcd_col=None` is still legal for a frame
  with one test, but the programmer must write it.

## Considered options

- **Change the default to `RFXSTDTC`.** Rejected: a `--BLFL` program that
  relied on `RFSTDTC` would change its flags with no message.
- **Keep the defaults and warn when the frame holds more than one test code.**
  Rejected: it fixes the test code only, and the reference stays hidden.

## Consequences

- Each existing call without `ref_col=` or `testcd_col=` raises a `TypeError`
  that names the missing argument. Add the two arguments; the flags do not
  change when the old defaults were right.
- The ADaM `baseline_flag` is a different verb and does not change.
