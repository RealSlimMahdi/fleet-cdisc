# nodup sorts a missing key as SAS

The alpha audit (finding c1-18) found that `nodup(sort_by=["AESEVN"], keep="first", descending=True)` kept the record with no severity, not the worst one. Polars puts a missing value first in both directions, so a descending sort put it on top. SAS PROC SORT BY DESCENDING puts it last, and admiral `filter_extreme(order = exprs(desc(AESEVN)), mode = "first")` keeps the worst value too. We decided that `nodup` follows the SAS rule (Mahdi, 4 November 2026).

## The decision

- **A missing value is the lowest value**: it sorts first when ascending and last when descending, per key.
- **Records that tie on `sort_by` keep their input order**, as PROC SORT EQUALS (c1-21). `keep="first"` takes the first input record of a tie and `keep="last"` the last.

## Considered options

- **A missing value last in both directions, as admiral and ADR-0020.** Rejected for `nodup`: `nodup` translates PROC SORT NODUPKEY, so a QC program with PROC SORT is its reference. On a descending sort both rules agree. They differ only on an ascending sort, where SAS keeps the missing record first.
- **Leave the Polars default.** Rejected: a keep-worst selection kept a missing value, with no warning.

## Consequences

- Fleet has two null rules for sorts. The flag verbs follow admiral (ADR-0020). `nodup` follows SAS. Each docstring states its rule.
- Only a descending `nodup` changes its result. The ascending result is the same as before.
