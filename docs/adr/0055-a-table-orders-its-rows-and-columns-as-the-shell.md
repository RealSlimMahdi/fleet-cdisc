# A table orders its rows and columns as the shell

The alpha audit of November 2026 found that a Fleet table sorted its levels and its columns as text. Week 12 printed before Week 2 (c1-439), the age group `<65` printed after `65-80`, a `Total` pool printed between two arms, and an Enum arm lost its order (c1-438). A typo in `column_order` was silently ignored. The demographics table showed Mean and SD for age with no `n` row, so the reader could not see that a subject had no age (c1-804). A SAS programmer gets the shell order from a numeric code (`BY AVISITN`), from a format with `ORDER=DATA`, or from `PROC REPORT ORDER=INTERNAL`.

## The decision

```python
# Levels sort by AVISITN when ADLB has it: Baseline, Week 2, Week 4, Week 12.
ard = adlb.tlg.lb.t_summary(groupby="TRTA", adsl=adsl)

# An explicit key for a field without a <field>N column.
spec = LBSummarySpec(rows=[Row(field="PARAMCD", order_by="PARAMN"), Row(field="AVISIT")])
```

- **Row levels.** A row field sorts on `Row.order_by`. When it is not set, the engine takes `<field>N` when the dataset has it (`AVISIT` by `AVISITN`, `AGEGR1` by `AGEGR1N`, `RACE` by `RACEN`). Each level sorts on the minimum of the order column within its parent level; a null key sorts last, and a tie sorts as text. A field without an order column sorts as text, as before. `PARAMCD` has no default: `PARAMCDN` is not an ADaM variable, so set `order_by="PARAMN"`. The missing level stays last in its block (ADR-0038).
- **Columns.** The arms come first, then the pools in their definition order. The arms follow the categories of an Enum arm column (ADSL first, else the analysis dataset), and a category with no subject keeps its column with N=0. Without an Enum, the arms sort as text. `column_order` moves its entries to the front; an entry that is not an arm or a pool raises.
- **Arm type.** The arm column must be text (String, Categorical or Enum). A numeric arm (`TRTAN`) stops with a message that names `TRTA` and `column_order`. It is not cast: a Float64 code from an XPT file would print as `1.0`.
- **Continuous blocks of the demographics table** start with `n`, the count of subjects with a value, as PROC MEANS `N` and tern `analyze_vars`.

## Considered options

- **An `arms:` field that lists the columns.** Rejected for now: `column_order` and an Enum give the order, and a second field would have to agree with both.
- **Sort every level as text and let the user sort the ARD.** Rejected: the rendered table follows the ARD order, so a user who does not know the rule prints Week 12 before Week 2.
- **Dispatch on the dtype of the row field (sort a numeric field numerically).** Rejected: `AVISIT` is text; only its `N` companion carries the order.

## Consequences

- The order of a table with a `<field>N` column, a pool, or an Enum arm changes. The values do not change.
- The golden `dmt01` ARD gains one `n` row per arm.
- A spec with a `column_order` typo, or a numeric `groupby`, now stops.
- References: CDISC ADaMIG v1.3, BDS timing variables (AVISITN is the numeric version of AVISIT and gives its sort order; a `*N` variable is the numeric version of its character variable); SAS PROC REPORT `ORDER=` and PROC MEANS `N`; tern `analyze_vars`.
