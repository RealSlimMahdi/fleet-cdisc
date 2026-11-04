# A date verb reads the type of each column

The alpha audit of 4 November 2026 (findings c1-4, c1-5, c1-7, c1-78, c1-117, c1-141, c1-143, c1-371) found date verbs that cast every input to a date. A SAS date stored as a number became a date counted from 1970, 10 years off, with no message. A `pl.Date` source to `.date("ADT")` stopped with a raw Polars error. `on_treatment` dropped the time, so a pre-dose record on the first dose day was on treatment. `duration()` read a `pl.Expr` as 24-hour periods and wrote ISO 8601 durations with no sign.

## The decision

- **A number raises.** Every verb that reads a date (`.date()`, `duration`, `study_day`, `on_treatment`, `treatment_emergent`, `onset_recovery`, `age_from_dates`, the `peds` ages, `aval`) checks the dtype in the lazy schema. A numeric column raises `DerivationError` with the column name and the conversion: `pl.date(1960, 1, 1) + pl.duration(days=pl.col(...))` for a SAS date, `pl.datetime(1960, 1, 1) + pl.duration(seconds=...)` for a SAS date-time. Fleet does not guess the origin. The check lives in `fleet.core.dtc.to_day`, so each date verb gets it.
- **A date or a date-time converts.** `.date()` reads a `pl.Date` or `pl.Datetime` source as its ISO 8601 text and sends it through the one engine, so the flags follow the same rules.
- **`--DTC` text is read by its date portion** in every day count (ADR-0011). A partial value gives null.
- **A `pl.Expr` input is read by its type**, as a column name is.
- **`on_treatment` keeps the time of the start comparison** when the analysis date and the treatment start are both date-times; the end comparison stays at date level, as admiral `derive_var_ontrtfl` does by default. Date, text and mixed inputs stay at date level, because a date read as midnight would fall before a 09:00 dose.
- **`aval()` takes each row from its own columns:** the end is the date of `ADTM`, else `ADT`; the start the date of `STARTDTM`, else `STARTDT`.
- **A sub-day duration on text with no time gives null and one warning** with the column and the count, and a hint to `.date()` for an imputed time with a flag (finding c1-5).
- **An ISO 8601 duration keeps the sign and adds one only on request** (Mahdi, c1-7 A). `-PT15M` for a pre-dose sample; `PT1H30M` for 90 minutes; `P9D` from 1 to 10 January, an elapsed time; `add_one=True` gives `P10D`. Months and years raise, because they have no fixed length; weeks that are not whole give null with a warning.

## Considered options

- **A `sas_epoch=` option on each verb.** Rejected: one more argument on every verb, and a default origin is still a guess.
- **Add one day by default to an ISO 8601 day duration, as the numeric output does** (option B). Rejected by Mahdi: `--ELTM` and `--DUR` are elapsed times, and a QC programmer would see every PK value one unit too large.
- **Raise unless `add_one` is explicit** (option C). Rejected: every existing call would change.

## Consequences

- A frame with a numeric SAS date column now stops at the verb call. Convert the column at the IO boundary.
- `on_treatment` on two date-time columns can now give null for a record on the first dose day, before the dose.
- `duration(out="iso8601")` now writes `-` for a negative span and hours with minutes, and refuses months and years.
