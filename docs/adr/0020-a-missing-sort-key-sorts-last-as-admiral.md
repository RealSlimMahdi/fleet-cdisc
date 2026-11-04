# A missing sort key sorts last, as admiral

The admiral oracle of alpha audit 5.3 found that `flag(criteria="last")` differs from admiral `derive_var_extreme_flag(mode = "last")` when an `order_by` value is missing. Fleet left out every record with a missing key, so an AE with no AESEVN or no ASTDT never got ANL01FL, and a group whose records all missed the key got no flag at all. admiral sorts with `dplyr::arrange`, which puts a missing value last in each key. We decided to follow admiral (Mahdi, 4 November 2026).

## The decision

- **A missing value sorts last in each key**, then the next key, then input order. `"last"` takes the last record of that order, so a record with a missing key wins over the others. `"first"` takes a record with a missing key only when every candidate of the group misses that key, and the next key then decides.
- **`flag_all=True` flags every candidate equal to the winner on the order keys**, where a missing value equals a missing value.
- **`where` still filters first**: a record that fails it takes no part (ADR-0013).

admiral 1.4.1, run on the rows of `test_a_missing_order_value_sorts_last_as_admiral`, gives the values that test holds. `scripts/admiral_oracle.py` compares the same rule weekly.

## Considered options

- **Leave the record out, as before.** Rejected: an admiral double program flags a record that Fleet does not, and a group with only missing keys gets no flag.
- **A missing value first, as SAS PROC SORT.** Rejected by the decision to match admiral. A QC program with PROC SORT and `LAST.` differs on a group with a missing key: it takes the last non-missing record.

## Consequences

- ANL01FL, ABLFL and other `first`/`last` flags can now fall on a record with a missing order value. When the SAP wants the last non-missing record, give `where=` (for example `where="AESEVN.is_not_null()"`).
- Polars 1.x ignores `nulls_last` in a window `order_by` with more than one key. The verb sorts on `is_null()` before each key, so the rule holds on Polars 1.x and 2.x.
