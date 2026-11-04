# Pediatric BMI uses the CDC 2000 or WHO 2007 reference, and the adult rule moves to metabolic

The alpha audit (c1-161, issue #178) found that `peds.bmi_category` applied the WHO adult cut-offs (18.5, 25, 30 kg/m2) from the pediatrics namespace. A boy aged 5 years with BMI 18.0 got Underweight, while the CDC 2000 charts put him at or above the 95th percentile (17.94), so obese. We decided on option C (Mahdi, 4 November 2026): move the adult rule out of `peds` and add a pediatric verb with the two reference tables an SAP names.

## The decision

- **`metabolic.bmi_category_adult`** holds the WHO adult rule. `peds.bmi_category` is removed with no `VERB_RENAMES` entry, because a rename would carry an adult rule into pediatric code without a warning. A null, NaN or infinite BMI, or a value not below the last bound, gets null (c1-158).
- **`peds.bmi_percentile_category`** classifies BMI by age in months and sex. `reference` has no default: the SAP names `"CDC2000"` or `"WHO2007"`.
  - CDC 2000 (24 to < 240 months): the row of the completed month (60.5 stands for 60.0 to 60.99 months, as CDC states), compared with the published P5, P85 and P95. Classes: Underweight, Healthy weight, Overweight, Obesity (CDC "Child and Teen BMI Categories").
  - WHO 2007 (61 to 228 months): L, M and S interpolated linearly between the two whole months around the age, the z-score rounded to 2 decimals, as the WHO `anthroplus` R package. Classes: Severe thinness (< -3), Thinness (< -2), Normal, Overweight (> +1), Obesity (> +2).
- **The tables are package data** under `src/fleet/adam/data/growth/`, from the official files: CDC `bmiagerev.csv` byte for byte, and the WHO expanded LMS workbooks converted to CSV. `scripts/regen_growth_references.py` downloads them again; the README in that folder gives the URLs, versions and SHA-256 values.

## Considered options

- **Option A, move the rule with no pediatric verb.** Rejected by the decision: the programmer would have to copy the CDC or WHO table and the lookup rule himself.
- **Option B, keep the adult rule in `peds` as `bmi_category_adult`.** Rejected: a reviewer can still accept an adult class for a child.
- **A default reference.** Rejected: CDC and WHO give different classes for the same child, and the SAP names one.

## Consequences

- QC must check the reference and the age rule (completed months or exact age) against the SAP. A wrong reference gives a plausible class that differs from the SAS result.
- The CDC 2022 extended BMI-for-age charts change z-scores above the 95th percentile only; the four classes do not use them. Severe obesity (>= 120 % of P95 or >= 35 kg/m2) is not a class of this verb.
- Ages under 24 months (CDC) or under 61 months (WHO 2007) get null. The WHO 2006 child growth standards for 0 to 5 years are not included.
