# Toxicity grading states its unit and description columns

The alpha audit found three ways in which a grading call gave a wrong grade with no warning. `atoxgr` without `unit_var` compared a hemoglobin of 13.5 g/dL with the SI cut-offs of `ctcae_v5` (80 g/L) and gave grade 3 (c1-329). `combine_grades` gave ATOXGR '0' when one direction had no grade, also when the description of that direction was present, so a potassium with a missing ANRHI read as normal (c1-386). `atoxgr(direction="LOW")` and `aval_adis(lloq_rule="HALF")` accepted any text and gave all-null grades or the full LLOQ (c1-420). Mahdi decided on 4 November 2026: c1-329 the recommendation, c1-386 option B, c1-420 the fix as described.

## The decision

- **`unit_var` is a required keyword of `atoxgr`**, as `get_unit_expr` in admiral 1.4.1 `derive_var_atoxgr_dir`. A row whose unit is not a unit of the term's criteria gets null, and the verb warns once per term with the count of such rows. The docstring states that `ctcae_*` and `daids` hold SI cut-offs and `*_uscv` hold US conventional units.
- **`combine_grades` needs the description columns**, with the defaults `low_desc_var="ATOXDSCL"` and `high_desc_var="ATOXDSCH"`, and raises when a column is absent. It gives '0' only when each side is '0' or its description is null, as admiral `derive_var_atoxgr`.
- **Closed values are checked.** `grade_dataset` (so `atoxgr`) raises `DerivationError` for a `direction` other than `"L"` or `"H"`, before the criteria lookup. `aval_adis` raises for a `lloq_rule` other than `"half"` or `"lloq"`. An empty lookup (a custom file with only H terms and `direction="L"`) is still a valid all-null result.

## Considered options

- **Keep `unit_var` optional and warn.** Rejected: a warning in a batch log is easy to miss, and admiral refuses the call.
- **c1-386 A, keep '0' and document it.** Rejected: the row reads as normal and differs from an admiral double program.
- **c1-386 C, null when one side is null and no description is named.** Rejected: every normal anemia row with no high criteria becomes null and leaves the shift table denominators.

## Consequences

- Old calls of `atoxgr` without `unit_var` stop with a `TypeError`; old calls of `combine_grades` on data without ATOXDSCL or ATOXDSCH stop with a `DerivationError`. A one-direction study adds the other description as a null column.
- The define.yaml schema marks `unit_var` as required for `algorithm: atoxgr`, and `direction` as `L` or `H`.
