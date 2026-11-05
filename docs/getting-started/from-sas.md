# Coming from SAS

This page maps common SAS DATA step and PROC statements to Fleet verbs. It
also shows where a missing value gives a result other than SAS. Read the
null rules before you port a flag or a category.

## Statement map

| SAS                                                        | Fleet                                                                       |
| ---------------------------------------------------------- | --------------------------------------------------------------------------- |
| `PROC SORT NODUPKEY; BY USUBJID PARAMCD ADT;`              | `.nodup(subset=["USUBJID", "PARAMCD", "ADT"], sort_by=[...], keep="first")` |
| `BY USUBJID PARAMCD; IF FIRST.PARAMCD THEN ...`            | `.flag("FIRSTFL", criteria="first", order_by="ADT", by=[...])`              |
| `IF LAST.PARAMCD THEN ...`                                 | `.flag("LASTFL", criteria="last", order_by="ADT", by=[...])`                |
| `MERGE A(IN=A) B(KEEP=USUBJID TRT01A); BY USUBJID; IF A;`  | `.merge(b, on="USUBJID", keep=["TRT01A"])`                                  |
| `IF ... THEN ...; ELSE IF ...; ELSE ...;`                  | `.case_when("VAR", when=[...], else_=...)`                                  |
| `VAR = OLDVAR;` / `VAR = "TEXT";`                          | `.assign("VAR", source="oldvar")` / `.assign("VAR", value="TEXT")`          |
| `KEEP STUDYID USUBJID ...;`                                | `.keep("STUDYID", "USUBJID", ...)`                                          |
| `WHERE AESER = "Y";`                                       | `.whereclauses(where='pl.col("AESER") == "Y"')` (ADaM namespaces)           |
| `PROC COMPARE BASE=PROD COMPARE=QC; ID USUBJID;`           | `.compare(prod, keys=["USUBJID"])`                                          |

A BY group with FIRST. and LAST. on one record:

```python
import polars as pl

import fleet  # noqa: F401  (registers df.sdtm and df.adam)

vs = pl.from_repr("""
┌─────────┬─────────┬────────────┬───────┐
│ USUBJID ┆ PARAMCD ┆ ADT        ┆ AVAL  │
│ ---     ┆ ---     ┆ ---        ┆ ---   │
│ str     ┆ str     ┆ date       ┆ f64   │
╞═════════╪═════════╪════════════╪═══════╡
│ S1      ┆ SYSBP   ┆ 2024-01-01 ┆ 120.0 │
│ S1      ┆ SYSBP   ┆ 2024-01-08 ┆ 118.0 │
└─────────┴─────────┴────────────┴───────┘
""")

out = (
    vs.adam.flag("FIRSTFL", criteria="first", order_by="ADT", by=["USUBJID", "PARAMCD"])
    .flag("LASTFL", criteria="last", order_by="ADT", by=["USUBJID", "PARAMCD"])
    .to_frame()
)
```

## Nulls are not SAS missing values

In SAS, a missing numeric value is lower than every number, so
`IF AGE < 65` is true when AGE is missing. In Polars, a comparison with a
null gives null, and a filter or a `when` treats null as false.

| Expression, AGE missing         | SAS                    | Fleet                                                      |
| ------------------------------- | ---------------------- | ---------------------------------------------------------- |
| `AGE < 65`                      | true                   | null                                                       |
| `.flag("YNGFL", criteria=...)`  | Y                      | null (`false_value="N"` gives N)                           |
| `case_when` with `else_=">=65"` | `<65` (first branch)   | `>=65` (no branch matches, so the `else_` value)           |
| `AGE = .` / `AGE IS MISSING`    | `missing(AGE)`         | `pl.col("AGE").is_null()`                                  |
| `PROC SORT` (ascending)         | missing sorts first    | `sort()` puts nulls first; `nulls_last=True` puts them last |

Write the null case on purpose, so that the code states the rule of the SAP:

```python
adsl = pl.from_repr("""
┌─────────┬──────┐
│ USUBJID ┆ AGE  │
│ ---     ┆ ---  │
│ str     ┆ i64  │
╞═════════╪══════╡
│ S1      ┆ 70   │
│ S2      ┆ null │
└─────────┴──────┘
""")

adsl = adsl.adam.adsl.case_when(
    "AGEGR1",
    when=[
        {"condition": 'pl.col("AGE").is_null()', "value": "Missing"},
        {"condition": 'pl.col("AGE") < 65', "value": "<65"},
    ],
    else_=">=65",
).to_frame()
```

## Two more differences

- **Lazy frames.** Most verbs add a step to a plan. Polars runs the plan at
  `.to_frame()`, as SAS runs a DATA step at `RUN;`. Some verbs read the data
  before the chain continues (a check, a join on records, `nodup`); the chain
  does not break.
- **No update in place.** A verb returns a new frame and never changes its
  input, as a DATA step writes a new data set. Assign the result
  (`adsl = ...to_frame()`) to keep it.
