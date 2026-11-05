# derive_param adds no record with a null AVAL

The alpha audit of November 2026 found two gaps in `derive_param` against admiral `derive_param_computed`. First (c1-321), a by group with a null component (for example WEIGHT not done at BASELINE) got a new BMI record with a null AVAL. admiral adds no record by default (`keep_nas = FALSE`). Second (c1-320), Fleet had no `constant_by_vars`: a per-visit BMI with the height of the screening visit only gave one BMI record, at SCREENING.

## The decision

```python
advs = (
    vs.adam.derive_param(
        by=["USUBJID", "AVISIT"],
        constant_by=["USUBJID"],
        constant_parameters={"H": "HEIGHT"},
        parameter_filter={"W": "WEIGHT"},
        set_values_to={"PARAMCD": "BMI", "PARAM": "Body Mass Index"},
        analysis_value=pl.col("W") / (pl.col("H") / 100) ** 2,
    ).to_frame()
)
```

- **`keep_nas=False` is the default.** A new record whose AVAL is null is not added. This includes an AVAL that is infinite or NaN (a division by zero): it becomes null with a warning, and the record is not added. `keep_nas=True` keeps the record with a null AVAL, as before.
- **`constant_parameters` join on `constant_by`.** The parts of `parameter_filter` join on `by`; the parts of `constant_parameters` then join on `constant_by`, which must be a subset of `by`. Each part must be unique on its own key.
- **A PARAMCD with no record warns** with a did-you-mean hint (admiral warns that no observation fulfils the filter).
- **`set_values_to` holds constants only.** An expression raises. In `derive_summary_records`, an expression is evaluated per group (admiral `set_values_to = exprs(ADT = min(ADT))`).

## Considered options

- **Keep the null record by default.** Rejected: a BMI record with a null AVAL at a visit where the weight was not done adds a row that a QC programmer with admiral or SAS does not have, and the counts of a by-visit table differ.
- **A separate verb for constant parameters.** Rejected: the rule is one join more; two arguments on `derive_param` keep one verb, as admiral.

## Consequences

- A pipeline that relied on the null records gets fewer records. Give `keep_nas=True` to keep them.
- References: admiral `derive_param_computed` (`keep_nas`, `constant_by_vars`, `constant_parameters`); admiral ADVS template (`derive_param_bmi(constant_by_vars = exprs(USUBJID))`).
