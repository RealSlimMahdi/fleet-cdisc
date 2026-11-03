# One reader for --DTC text, and the date rules it carries

The alpha audit of 2 November 2026 (package A) found 43 places in `src/fleet` that parsed `--DTC` text, each in its own way. A time part made `study_day` null, a partial date won a text minimum in `first_date`, a slash date was read day first with no message, and `select(spec=)` turned a partial `AESTDTC` into null. We decided that every date verb reads `--DTC` text through one module, `fleet.core.dtc`, and that the module never guesses.

## The decision

- **One reader.** `date_part` gives the date of a value with a complete, real date; `datetime_part` the date-time of a value with hours and minutes; `is_iso8601` checks the SDTMIG 3.4 forms (right truncation, hyphens for missing components, offsets, intervals). Day arithmetic uses the date portion (SDTMIG 3.4 section 4.4.4). A partial date gives null in a day count (CG0007).
- **Warnings run at collect.** `warn_on_collect` wraps the result, so the plan stays lazy and the message can quote the raw text: one warning per call, with the count and the first five values.
- **`.sdtm.date()` never guesses.** A valid ISO 8601 value stays. `YYYYMMDD` and `DD-MON-YYYY` convert, because they cannot be read two ways. A slash date or a two-digit year raises until `format=` names the layout, as an explicit SAS informat and the required `.format` of sdtm.oak do (Mahdi, Q4 A). Any other value becomes null with a warning (c1-90 A).
- **A time joins a date by SDTMIG 4.4.2.** A blank time leaves the date; a partial date takes one hyphen per missing component; a time with no date gives `-----T08:30`, as sdtm.oak does (Q5 A).
- **Baseline is strictly before the reference.** A record on the reference date is eligible only when both times are known and it is earlier (Q1 B, the IG text "prior to" and sdtm.oak `derive_blfl`).
- **EPOCH on a transition date with no time follows the record kind.** Findings (`--DTC`) take the earlier element, Events and Interventions (`--STDTC`) the later one, and `epoch_assign(same_day=)` overrides (Q2 E). No guidance fixes this case, so the warning gives the rule for the SDRG.
- **Duration adds one day only when the end is on or after the start,** before the division for weeks, months and years, and never for hours, minutes and seconds by default (admiral `compute_duration`; Q3 A).
- **A date-time keeps every collected part.** Only missing parts are imputed, by position; a fraction stays; an offset is dropped with a warning, so the wall clock stays (admiral).
- **A bound moves only an imputed date** whose possible range holds it; a complete date never moves (admiral `derive_vars_dt`).
- **First and last dates compare dates.** A partial value is left out with a warning unless `impute=` states the SAP rule, which then writes the `*DTF` flag of the winning record.
- **`select(spec=)` never casts `--DTC` and never imputes.** SDTM columns stay text; ADaM `*DT` and `*DTM` are read from text, and a value that is not complete becomes null with a warning. `DatasetChecker` expects text for every `*DTC`.

## Considered options

- **Keep format inference per column.** Rejected: the result of one row depended on the other rows, and a column of timed values raised.
- **Warn and keep a guess for slash dates.** Rejected: the wrong date reaches AESTDTC and TRTEMFL, and one warning in a long log is easy to miss.
- **Collect a snapshot at each verb for the warnings.** Rejected: it runs the plan twice. The check inside the plan sees the same raw text.

## Consequences

- Date-only data changes in one place: a record on the reference date is no longer baseline unless both times show it is earlier.
- `first_date` and `last_date` on `--DTC` text now give `pl.Date` (or `pl.Datetime` for `*DTM`), not text.
- `epoch_assign` with `same_day="by_class"` raises for a date column whose name is neither `--DTC` nor `--STDTC`.
