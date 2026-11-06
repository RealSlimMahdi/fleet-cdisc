# A table refuses values that SAS cannot hold

The alpha audit of November 2026 found two inputs that a SAS table program cannot meet and that Fleet summarised without a message. A NaN analysis value was counted in n and blanked the mean and SD, and an infinite value printed `inf` and then crashed the renderer (c1-434). A duplicate ADSL record weighted the mean age by records, and a subject in two arms counted twice (c1-443). SAS has no NaN or infinite value, and ADaMIG requires one ADSL record per subject.

## The decision

```python
# NaN counts as missing, with one UserWarning: "AVAL has 1 NaN value(s); ..."
ard = adlb.tlg.lb.t_summary(groupby="TRTA", adsl=adsl)
```

- **NaN** in the analysis-value column (or a `continuous_vars` column of the demographics table) becomes null before any statistic, with one `UserWarning` that gives the count. n, mean, SD and the quantiles then match PROC MEANS and R `mean(na.rm = TRUE)`.
- **An infinite value** (`inf`, `-inf`) raises `SchemaError` with the column and the count.
- **A duplicate ADSL record** (the same USUBJID and arm twice, after the population filter) raises `SchemaError` with the count and the first USUBJIDs. The demographics `check()` reports it too.
- **One USUBJID in two arms** (a crossover ADSL read by period) counts in each arm, with one `UserWarning`.

## Considered options

- **Raise on NaN.** Rejected: NaN comes from a Polars division by zero in a derivation; a missing value is the SAS reading of it, and the warning makes it visible.
- **Drop duplicate ADSL records silently, or keep the first.** Rejected: the two records can differ, and the choice would decide the numbers.
- **Raise on a subject in two arms.** Rejected: a crossover study can read ADSL by period on purpose. The warning names the subjects.

## Consequences

- A table on a dataset with NaN now warns and gives the PROC MEANS values.
- A table on an ADSL with duplicate records now stops.
- References: CDISC ADaMIG v1.3, section 3.1 (ADSL has one record per subject); SAS PROC MEANS (missing values are left out); R `mean(na.rm = TRUE)`.
