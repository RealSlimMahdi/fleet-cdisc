# LOCF adds records with DTYPE, as admiral

Alpha audit finding c1-317 found that `derive_locf_records` filled a null AVAL in place, set no DTYPE, and added no record for a missed visit. ADaMIG v1.3 requires DTYPE on a record whose AVAL is imputed, and a LOCF analysis at WEEK 24 needs a WEEK 24 record for each subject. Finding c1-318 found that the default `order_by="ADT"` sorted undated missed visits first and filled nothing. We decided to port admiral `derive_locf_records`, with `imputation="add"` as the default (Mahdi, 4 November 2026).

## The decision

- **`dataset_ref` is required.** It holds the expected visits (for example AVISIT and AVISITN). For each `by` group, a visit of `dataset_ref` with no record with a non-null value gets a new record.
- **Each imputed record has DTYPE "LOCF".** An existing DTYPE on other records is kept.
- **The default is `imputation="add"`, as admiral.** A record with a null value is kept, and a second record with the carried value and DTYPE "LOCF" is added. `"update"` puts the value on that record. `"update_add"` does both.
- **`order_by` is required.** Its first column must be in `dataset_ref`, so that a new record has a sort value. A null value in an `order_by` column raises.

admiral 1.4.1, run on the rows of `tests/unit/test_bds_record_verbs.py`, gives the values that the test holds for the three modes.

## Considered options

- **`imputation="update"` as the default.** Rejected: the updated record keeps the collected ADT, so the value looks collected on that date, and a QC program with the admiral default has more rows.
- **No default for `imputation`.** Rejected: each admiral call ported without `imputation=` stops with a TypeError, and the admiral default is a published convention.
- **Keep the in-place fill and add DTYPE only.** Rejected: a subject with no WEEK 24 record still has no WEEK 24 value.

## Consequences

- PROC COMPARE with `ID USUBJID PARAMCD AVISITN` reports duplicate keys in add mode: put DTYPE in the ID statement.
- Old calls (`by=` and `order_by="ADT"` only) stop with a TypeError until `dataset_ref=` and `order_by=` are given.
- A group with no earlier value keeps a null value on the new record, as admiral.
