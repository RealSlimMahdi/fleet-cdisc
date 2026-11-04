# A criterion on a missing value is missing, as admiral

The alpha audit (finding c1-204) found that `criterion()` gave CRITyFL `N` and CRITyFN `0` when the condition could not be evaluated. A record with a missing AVAL then counted as "criterion not met", and a responder table with the denominator Y + N held a subject with no value. admiral `derive_vars_crit_flag(values_yn = TRUE, create_numeric_flag = TRUE)` gives a missing flag on that record. We decided to follow admiral (Mahdi, 4 November 2026).

## The decision

- **A null condition gives a null CRITyFL and a null CRITyFN.** A true condition gives `Y` and `1`, a false condition gives `N` and `0`.
- **CRITy keeps the description on every record**, also on a record with a null condition.
- **A SAP rule "missing is not met" is written in the condition**: `condition=(pl.col("AVAL") >= 10).fill_null(False)`.

## Considered options

- **Keep N and 0 and document it.** Rejected: an admiral QC program differs, and `AVAL < 5` gives N on a missing AVAL where a plain SAS IF/ELSE gives Y.

## Consequences

- A SAS QC program with `IF AVAL >= 10 THEN ... ELSE ...` gives N on a missing AVAL. It differs from Fleet until it handles the missing value explicitly.
- `flag()` is not changed: its `false_value` still applies to every record that does not meet the criteria.
