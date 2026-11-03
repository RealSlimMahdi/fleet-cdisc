# ADSL and OCCDS verbs follow the admiral rules they name

The alpha audit of 2 November 2026 (package B) found that three verbs which cite admiral gave other answers than admiral. `treatment_emergent` flagged an AE with no start date as not emergent, read a start after TRTEDT as emergent with no window, and never looked at the end date. `pick` with `order=["LSTALVDT"], mode="last"` kept the first listed event, not the latest date, so LSTALVDT could be weeks early. `recode` always gave text, so `recode_map={"MILD": 1, ...}` made a text ASEVN. The recipes for SAFFL dropped placebo subjects (EXDOSE = 0) and left non-members blank. We decided that a verb which names an admiral function gives the admiral answer, and that the documented recipes state the SAP choice they make.

## The decision

- **`treatment_emergent` follows `derive_var_trtemfl`.** The first rule that applies decides: no TRTSDT gives null; an end date before TRTSDT gives null; no start date gives Y; a start on or after TRTSDT (plus `offset_days`) gives Y, and with `end_window` only up to TRTEDT plus the window, a null TRTEDT read as open; anything else gives null. `end_date=` is a required keyword (pass `None` to state that there is none), and `trtedt=` and `end_window=` come together, so the window is always written in the call.
- **`pick` decides across events as `derive_vars_extreme_event`.** With a top-level `order`, every event's record competes on it and `mode`: `order=["LSTALVDT"], mode="last"` gives the latest date over all sources. A tie goes to the first listed event. With no top-level `order`, the first listed event with a record wins, as the admiral DTHCAUS template. Sorts keep the input order, so the result does not change between runs.
- **`recode` types the output from the map.** Integer values give an integer column, floats (alone or with integers) a float column, other single kinds text. A map that mixes kinds raises `DerivationError`. A `*N` variable is Num in the ADaMIG, so a typing slip must stop the run, not give text.
- **SAFFL recipes state the exposure rule and give N.** The recipes use the admiral template condition `EXDOSE > 0 or (EXDOSE = 0 and EXTRT contains PLACEBO)`, case-insensitive, with a comment that the SAP decides. SAFFL and ITTFL use `false_value="N"`, because ADaMIG 1.3 says a population flag cannot be blank. The `flag` default stays null.

## Considered options

- **Keep the old `treatment_emergent` signature and add the admiral rules behind a switch.** Rejected: the old default gives a wrong TRTEMFL with no message, and a switch keeps it the default.
- **A default `end_window` of 30 days, as the admiral ADAE template.** Rejected: the window is an SAP decision. The examples use 0, which keeps their results; the cheat sheet shows 30.
- **Keep the pick cascade and teach `max_horizontal` for LSTALVDT.** Rejected: the call already reads as admiral's, and a programmer who ports admiral code gets the wrong date.
- **Change the `flag` default to N.** Rejected: most flags (ABLFL, ANL01FL) are Y or null.

## Consequences

- Every `treatment_emergent` call must give `end_date=`; calls with `trtedt=` must give `end_window=`.
- `pick` calls with a top-level `order` over several events can give another winner. Calls that need a cascade drop the top-level `order` and put it on each event.
- `recode` with integer values now gives `Int64`, not text; code that compared the result with `"1"` must compare with `1`.
