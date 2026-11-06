# Coming from SAS

This page lists the places where Fleet and SAS can give different results on
the same data. For each one it gives the SAS rule, the Fleet rule and a sample
that runs. The decision records (ADRs) give the reasons.

The samples share this setup:

```python
import polars as pl

import fleet
```

## Missing values in a condition

**SAS:** a missing numeric value is lower than every number. `IF AVAL < 5`
is true for a missing AVAL, so an IF/ELSE gives the record the "true" branch.

**Fleet:** a condition on a missing value is missing (ADR-0033, as admiral).
`criterion()` gives a null CRITyFL and CRITyFN on that record. When the SAP
says "missing is not met", write it in the condition with `.fill_null(False)`.

```python
adlb = pl.from_repr("""
┌─────────┬──────┐
│ USUBJID ┆ AVAL │
│ ---     ┆ ---  │
│ str     ┆ f64  │
╞═════════╪══════╡
│ S1      ┆ 3.0  │
│ S2      ┆ null │
└─────────┴──────┘
""")

crit = adlb.adam.criterion(1, condition=pl.col("AVAL") < 5, description="AVAL < 5").to_frame()
crit["CRIT1FL"].to_list()  # ['Y', None]; SAS IF/ELSE gives 'Y' for S2 too
```

## Sort order of a missing key

**SAS:** PROC SORT puts a missing value first (it is the lowest value), and
last with `DESCENDING`.

**Fleet:** two rules, each stated in its docstring.

- The flag verbs (`flag(criteria="first"/"last")`, `flag_first`) follow
  admiral: a missing value sorts **last** in each key (ADR-0020). A QC program
  with PROC SORT and `LAST.` can pick another record when a key is missing.
- `nodup()` translates PROC SORT NODUPKEY, so it follows SAS: a missing value
  is the lowest value (ADR-0023). Ties keep their input order, as `EQUALS`.

```python
adae = pl.from_repr("""
┌─────────┬────────┬────────┐
│ USUBJID ┆ AETERM ┆ AESEVN │
│ ---     ┆ ---    ┆ ---    │
│ str     ┆ str    ┆ i64    │
╞═════════╪════════╪════════╡
│ S1      ┆ RASH   ┆ null   │
│ S1      ┆ RASH   ┆ 2      │
└─────────┴────────┴────────┘
""")

worst = adae.adam.nodup(
    subset=["USUBJID", "AETERM"], order_by=["AESEVN"], keep="first", descending=True
).to_frame()
worst["AESEVN"].to_list()  # [2]: as PROC SORT BY DESCENDING AESEVN NODUPKEY
```

## Rounding of a printed value

**SAS:** `ROUND(31.25, 0.1)` gives 31.3: a tie rounds half away from zero.

**Fleet:** the same rule for every printed cell (ADR-0037). The ARD keeps the
unrounded value; only the printed text is rounded. A Python f-string rounds
the binary value and can print 31.2: do not use one for a table cell.

```python
from fleet.tlg import apply_fmt_fn

apply_fmt_fn(5 / 16 * 100, "xx.x")  # '31.3', as SAS ROUND
```

## Merge

**SAS:** `MERGE a b(KEEP=USUBJID AGE); BY USUBJID;` keeps every column of `a`.
A column on both sides takes the value of `b` with no message.

**Fleet:** `merge(keep=)` limits the right dataset in the same way, and every
column of the chain stays. A non-key column on both sides **raises** and names
the column: drop or rename it first (ADR-0032, as admiral). `merge_adsl` and
`join_adsl` also raise when ADSL has more than one record for a subject.

```python
ae = pl.from_repr("""
┌─────────┬──────────┐
│ USUBJID ┆ AETERM   │
│ ---     ┆ ---      │
│ str     ┆ str      │
╞═════════╪══════════╡
│ S1      ┆ HEADACHE │
└─────────┴──────────┘
""")
dm = pl.from_repr("""
┌─────────┬─────┬─────┐
│ USUBJID ┆ AGE ┆ SEX │
│ ---     ┆ --- ┆ --- │
│ str     ┆ i64 ┆ str │
╞═════════╪═════╪═════╡
│ S1      ┆ 63  ┆ F   │
└─────────┴─────┴─────┘
""")

ae_dm = ae.sdtm.merge(dm, on="USUBJID", keep=["AGE"]).to_frame()
ae_dm.columns  # ['USUBJID', 'AETERM', 'AGE']
```

## Dates

**SAS:** an informat reads the text you name (`yymmdd10.`, `date9.`). A
partial date has no SAS date value.

**Fleet:** a `--DTC` column is ISO 8601 text (`pl.String`). `.sdtm.date()`
never guesses: a slash date or a two-digit year raises until `format=` names
the layout, as an explicit SAS informat does. A partial date stays partial in
`--DTC`, and a day count on it is missing (ADR-0011). Imputation happens only
when you ask for it, on a `*DT` target (`impute=`, `highest=`).

```python
raw = pl.from_repr("""
┌────────────┐
│ start      │
│ ---        │
│ str        │
╞════════════╡
│ 2024-03-15 │
│ 2024-03    │
└────────────┘
""")

ex = raw.sdtm.date("EXSTDTC", source="start").to_frame()
ex["EXSTDTC"].to_list()  # ['2024-03-15', '2024-03']: the partial date stays partial
```
