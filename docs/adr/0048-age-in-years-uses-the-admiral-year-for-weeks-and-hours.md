# Age in years uses the admiral year for weeks and hours

The alpha audit of November 2026 (c1-83) found that `adsl.age_years()` divided an age in WEEKS by 52.1775 and gave null for an age in HOURS. admiral `compute_age_years` divides weeks by 365.25/7 (52.17857) and hours by 8766. AGE 587 WEEKS gave 11.250060 in Fleet and 11.249829 in admiral; with `round_digits=1` the values were 11.3 and 11.2. The docstring said that admiral uses 52.1775 weeks, which is not true. HOURS is a value of the CDISC CT codelist AGEU (C66781).

## The decision

- **One year is 12 months, 365.25/7 weeks, 365.25 days or 8766 hours**, as admiral `compute_age_years`. `age_in_years` computes `AGE * 7 / 365.25` for WEEKS and `AGE / 8766` for HOURS.
- **An unknown unit gives null and a warning.** `adsl.age_years()` counts the rows whose AGEU is not YEARS, MONTHS, WEEKS, DAYS or HOURS (for example `YEAR`) and names some of the values. The expression in `fleet.adam.utils` stays a pure expression and does not warn.

## Considered options

- **Keep 52.1775 weeks per year** (365.2425/7, the Gregorian mean year). Rejected: the days branch already uses 365.25, so the two branches disagreed, and admiral parity is the stated aim of the verb.
- **Raise on an unknown unit.** Rejected: a DM with one bad AGEU row would stop the whole ADSL; a null with a warning keeps the other subjects and points at the row.

## Consequences

- An age in weeks changes in the sixth significant digit. A rounded value can change by one unit in the last digit.
- `tests/unit/test_admiral_parity.py::TestAgeInYears::test_weeks` now holds the admiral values.
