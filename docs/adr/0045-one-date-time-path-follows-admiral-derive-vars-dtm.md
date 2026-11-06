# One date-time path follows admiral derive_vars_dtm

The alpha audit of November 2026 (c1-119, with c1-67 and c1-74) found that `.adam.date()` and `.sdtm.date()` gave two results for one `*DTM` call. `.adam` imputed `2024-03` to 2024-03-01T00:00:00; `.sdtm` gave null. With `time=`, both gave null for a partial date, and `highest=` raised (ADR-0021, step 1). The `time=` path set TMF to null, even for a time it imputed.

We checked admiral 1.4.1 `derive_vars_dtm` on a grid of 15 `--DTC` forms, six `highest_imputation` levels and the first and last imputation (`scripts/regen_admiral_dtm_grid.R`, frozen in `tests/fixtures/goldens/dates/admiral_dtm_grid.csv`).

## The decision

- **One path.** `impute_dtc_to_datetime` in `fleet.adam.utils` gives the `*DTM` value, its DTF and its TMF for both namespaces.
- **`time=` comes first.** The date and the time become one `--DTC` value by SDTMIG 3.4 section 4.4.2 (`2024-03` and `08:15` give `2024-03--T08:15`). The value then takes the imputation and `highest=`, as a `--DTC` source does. A time in another layout (`0815`) is left out, with one warning.
- **`highest=` has the admiral meaning on a `*DTM` target:** `"M"`, `"D"`, `"h"`, `"m"`, `"s"` or `"n"` names the highest part that may be imputed. A value that needs more is null. No `highest=` is `"M"`, as on a `*DT` target (ADR-0021). This is not the admiral default (`"h"`), which gives null for every partial date.
- **The first missing part decides** (admiral `preserve = FALSE`, the default). A part below it is not used: `2021-03--T08:30` gives 2021-03-01T00:00:00 with DTF `D` and TMF `H`; `2021-03-15T08:-:45` gives 08:00:00 with TMF `M`. This is the same rule as `2021---15` on a `*DT` target.
- **TMF follows the imputed parts**, also with `time=`: `08:30` gives TMF `S`, a null time gives `H`.
- **`"Y"` still raises.** admiral imputes a year only with `min_dates` or `max_dates`, and a `*DTM` target refuses `min_date=` and `max_date=` (ADR-0021).

## Considered options

- **Keep a collected time below a missing day** (admiral `preserve = TRUE`). Rejected for the default: admiral does not do it by default, and `*DT` drops a collected day below a missing month. A `preserve=` argument can come later if a SAP asks for it.
- **The admiral default `highest = "h"`.** Rejected: a `*DT` target imputes the month and the day by default, and the two targets of one `--DTC` value would disagree.
- **Null for a partial date in `.sdtm.date()`, with a docstring note.** Rejected: one verb name would still give two results.

## Consequences

- `.sdtm.date("ASTDTM", ...)` on a partial date now gives an imputed value with its flags, not null.
- With `time=`, a partial date now gives an imputed value; the collected time is not kept. An `hh:mm` time takes seconds 00, or 59 with `impute_time="last"`, and TMF `S`.
- A null time with `time=` takes `impute_time`, else `impute` (it took `"first"` before).
- `impute="mid"` on a missing month gives June 15, and admiral gives June 30. That is a separate defect and is out of the grid.
- An `hh:mm` time (`2021-03-15T10:30`) gives TMF `S`. admiral `derive_vars_dtm` gives NA by default, because `ignore_seconds_flag = TRUE`. The `date` docstring says so; a SAP that follows admiral drops or nulls the TMF column (c1-73).
