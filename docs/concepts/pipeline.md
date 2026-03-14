# Namespace Pipeline Architecture

## How the pipeline works

Every Pymaverse namespace (`sdtm`, `adam`, `adsl`, `occds`) follows the same pattern:

1. **Access** the namespace on a Polars DataFrame: `df.sdtm`
2. **Chain** verb calls — each returns a new namespace object accumulating `pl.Expr` objects
3. **Materialise** with `.to_frame()` — executes a single `df.with_columns(...)` pass

```python
result = (
    raw_df.sdtm                  # 1. access
    .assign_no_ct("USUBJID", source="patient_id")   # 2. chain
    .hardcode_no_ct("DOMAIN", value="DM")
    .assign_ct("SEX", source="sex_raw",
               ct_codelist="C66731", ct_mapping={"M": "M", "F": "F"})
    .to_frame()                  # 3. materialise
)
```

Nothing runs at step 2 — verbs only build an internal expression list.

---

## Lazy evaluation

```
df.sdtm
  │
  ├─ .assign_no_ct("USUBJID", ...)  →  [Expr("patient_id".alias("USUBJID"))]
  ├─ .assign_ct("SEX", ...)         →  [..., Expr(when/then.alias("SEX"))]
  └─ .to_frame()
       │
       └─ df.with_columns(*exprs)   ← single Polars pass
```

This means you pay no cost for columns you don't chain. Expression ordering mirrors declaration order.

---

## SDTM verbs at a glance

| Verb | Purpose |
|------|---------|
| `assign_no_ct(target, source)` | Copy raw column, no CT validation |
| `hardcode_no_ct(target, value)` | Constant literal for all rows |
| `assign_ct(target, source, ct_codelist, ct_mapping)` | Recode values through a CT codelist |
| `assign_datetime(target, source, mode)` | Normalise to ISO 8601 date or datetime |
| `derivation(target, expression)` | Arbitrary `pl.Expr` |
| `if_then_else(target, when, else_value)` | Multi-branch conditional |
| `to_frame()` | Materialise |

---

## ADaM verbs at a glance

| Verb | Purpose |
|------|---------|
| `source(target)` | Pass-through column |
| `derivation(target, expression)` | Arbitrary `pl.Expr` |
| `assigned(target, value)` | Constant literal |
| `study_day(target, analysis_date, reference_date)` | CDISC study-day formula |
| `flag(target, criteria, groups)` | Per-group boolean flag |
| `baseline(target, aval, baseline_flag)` | Carry baseline AVAL within groups |
| `chg(target, aval, base)` | Change from baseline |
| `pchg(target, aval, base)` | Percent change from baseline |
| `imputation(target, method, groups)` | LOCF / WOCF imputation |
| `to_frame()` | Materialise |

---

## ADSL verbs at a glance

| Verb | Purpose |
|------|---------|
| `source(target)` | Pass-through column |
| `first_date(target, from_dataset, date_col, where)` | Earliest event date per subject |
| `last_date(target, from_dataset, date_col, where)` | Latest event date per subject |
| `duration(target, start_date, end_date)` | Integer day count |
| `eligibility_flag(target, criteria)` | `"Y"` flag based on row condition |
| `count_events(target, from_dataset, where)` | Event count per subject |
| `to_frame()` | Materialise |

---

## OCCDS verbs at a glance

| Verb | Purpose |
|------|---------|
| `source(target)` | Pass-through column |
| `first_occ(target, date_col, groups)` | Flag first occurrence within group |
| `worst_severity(target, severity_col, order, groups)` | Worst severity flag |
| `any_flag(target, col, value, groups)` | `"Y"` if event exists in group |
| `to_frame()` | Materialise |
