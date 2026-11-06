# Date imputation reads the form of the value and follows admiral highest_imputation

**Status: partly superseded by ADR-0045.** A `*DTM` target now takes `highest=` (except `"Y"`), and a partial date with `time=` is imputed. The rest stands.

The alpha audit of 4 November 2026 (findings c1-67, c1-69, c1-74, c1-119) found that `.date(highest=)` was one level stricter than admiral `highest_imputation`: `highest="M"` gave null for `2021`, `highest="D"` gave null for `2021-03`, and `"h"` nulled even a complete date. The imputation and the `*DTF` flag read the length of the text, so `2021---15` gave null and `202103` carried a flag on a null date. On a `*DTM` target, `highest=` and `time=` of `.adam.date()` had no effect and gave no message.

## The decision

- **The form decides, not the length.** The date engine reads year, month and day, a hyphen standing for a missing part (SDTMIG 3.4 section 4.4.2). A missing day imputes the day (`2021-03`, `2021-03--T08:30`). A missing month imputes the month and the day, and a collected day is not used (`2021---15` gives 2021-01-01 with flag M), as admiral `impute_dtc_dt` does. Any other form gives null.
- **`highest=` has the admiral meaning.** It names the highest part that may be imputed: `"n"` none, `"D"` the day, `"M"` the month and the day. A date that needs more is null. No `highest=` keeps the Fleet default: month and day may be imputed.
- **`"Y"` and the time levels raise on a `*DT` target.** Fleet does not impute a missing year; admiral needs `min_dates` or `max_dates` for it. `"h"`, `"m"` and `"s"` have no meaning on a date.
- **A `*DTM` target refuses `highest=`**, as it refuses `min_date=` and `max_date=`, in both namespaces, until a tested date-time rule exists.
- **A flag is null where the date is null.** The `*DTF` and `*TMF` flags describe an imputed value; a null value has nothing to describe.
- **`.adam.date()` honours `time=`** on a `*DTM` target with the same code as `.sdtm.date()`. A partial date with `time=` gives null in both namespaces.
- **`value=` with date-only text on a `*DTM` target gives midnight** (`2024-01-15` gives 2024-01-15T00:00:00).

## Considered options

- **Rename `highest=` and keep the old meaning.** Rejected: the name is the admiral name, and a programmer who knows admiral reads it with the admiral meaning.
- **Impute `highest="Y"` with a fixed year.** Rejected: admiral refuses it without bounds, and a guessed year changes TRTEMFL.

## Consequences

- `.date("ASTDT", highest="M")` now imputes `2021` to 2021-01-01; a spec that relied on the stricter meaning gets more imputed dates. Check the `*DTF` flag.
- `highest="Y"`, `"h"`, `"m"` and `"s"` now raise on a `*DT` target, and any `highest=` raises on a `*DTM` target.
- Values such as `2021---15` and `2021-03--T08:30` now give an imputed date with a flag, not null.
