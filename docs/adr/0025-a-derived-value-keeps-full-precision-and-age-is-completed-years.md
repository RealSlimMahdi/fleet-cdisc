# A derived value keeps full precision, and age is completed years

The alpha audit (c1-76, c1-138, c1-77) found that `bmi`, `bsa`, `map`, `qtc` and `adsl.age_years` rounded the stored value with a fixed half-to-even rule that no docstring stated and no argument turned off. WEIGHT 86.6 kg and HEIGHT 170 cm gave BMI 30.0, so the subject fell into an SAP group BMI >= 30 that the unrounded value 29.9654 does not reach. `age_from_dates` and `peds.age_years` returned days / 365.25 rounded to 1 or 2 decimals, so a subject born 1956-06-01 was 65.0 on 2021-05-31, one day before the 65th birthday, and went into AGEGR1 '>=65'. `nrind` compared raw floats, so 1.3 x 88.4 = 114.92000000000002 against ANRHI 114.92 was HIGH. We decided to follow admiral and SAS on all three points (Mahdi, 4 November 2026).

## The decision

- **Full precision by default.** `bmi`, `bsa`, `map`, `qtc` and `adsl.age_years` store the unrounded value, as admiral `compute_bmi`, `compute_bsa`, `compute_map`, `compute_qtc` and `compute_age_years`. A new `round_digits=` argument rounds with the SAS `ROUND` rule: half away from zero, after a first rounding of the scaled value to 8 decimals so that 24.25 gives 24.3. The helper is `fleet.adam.utils.sas_round`.
- **Age from dates is completed years.** `adsl.age_from_dates` and `peds.age_years` return Int64 completed years by default, as admiral `derive_vars_aage` and SAS `FLOOR(YRDIF(b, r, 'AGE'))`. A 29 February birthday is reached on 1 March in a non-leap year. `unit="decimal"` gives days / 365.25 at full precision, and only that form takes `round_digits=`. Both verbs use one helper, `fleet.adam.utils.age_between`.
- **`nrind` compares at 15 significant digits**, as admiral `derive_var_anrind` (`signif(x, 15)` on AVAL, ANRLO and ANRHI), and gives null for a NaN value. The new `signif_dig=` argument changes the number of digits.

## Considered options

- **Keep one decimal by default and state it.** Rejected: PROC COMPARE against an admiral or unrounded SAS program differs on nearly every row, and subjects near a cut-off change group.
- **Unrounded decimal age by default.** Rejected: PROC COMPARE against an integer age differs on almost all rows, and `AAGE >= 65` is false on the 65th birthday for some birth dates.
- **Keep the rounded decimal age and add an integer option.** Rejected: about 1 subject in 20 still reads one year too old with the default.

## Consequences

- A SAP that says "round to one decimal, then classify" needs `round_digits=1` in the call.
- A SAP that defines a decimal age (a PK covariate) needs `unit="decimal"`.
- Outputs of existing pipelines change: BMI, BSA, MAP, QTc and AAGE gain decimals, and AAGE from dates becomes an integer that can be one year lower.
