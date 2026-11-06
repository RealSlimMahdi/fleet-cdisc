# Vaccine flags follow their cited definitions, and the call states the SAP rule

The alpha audit found three vaccine verbs that did not do what their citations say. `fever_flag` flagged only values strictly above 38.0 °C, although the FDA 2007 toxicity grading scale and the Brighton Collaboration start fever at 38.0 °C (c1-417). `seroconversion_flag` applied only AVAL / BASE, so a subject below the LLOQ at baseline (HI '<10', BASE 5) and 20 after vaccination was seroconverted, while the FDA CBER 2007 influenza rule needs a post-vaccination titre of at least 1:40 (c1-416). `event_flag` ignored AVALC unless told, missed the AVALC value Y, spread one event to every FAOBJ of a subject through its default `by=["USUBJID"]`, and gave N to a diary with no data (c1-418). Mahdi decided on 4 November 2026: c1-417 option B, c1-416 option A, c1-418 option A.

## The decision

- **`fever_flag` is inclusive by default** (`>=`), and a new `inclusive=False` gives `>` for a strict SAP limit such as FDA grade 4 (> 40 °C).
- **`seroconversion_flag` has a required `lloq_col`.** `lloq_col="ISLLOQ"` applies the two-arm rule: BASE below the LLOQ needs `AVAL >= seronegative_fold x LLOQ` (default `fold_rise`), BASE at or above the LLOQ needs `AVAL >= fold_rise x BASE`. `lloq_col=None` keeps the plain ratio for a SAP that states it. The flag stays Y or null.
- **`event_flag` follows admiralvaccine `derive_vars_event_flag`.** `by` is required. `severity_col` defaults to `"AVALC"` (`None` opts out), and the default severity values add Y; `[]` means no value counts. A group with an event gives Y on every record. In a group with no event, a record that shows no event (AVAL <= cutoff or AVALC = "N") gives N, and a record with missing AVAL and AVALC gives null.

## Considered options

- **c1-417 A, plain `>=` with no argument.** Not chosen: a strict limit would need `case_when`.
- **c1-417 C, keep `>` by default.** Rejected: each default call misses 38.0 °C.
- **c1-416 B or C, a default for `lloq_col`.** Rejected: either default hides a SAP choice that differs between sponsors (FDA 2007 against an AstraZeneca-type plain ratio).
- **c1-418 B or C, N for a group with no assessable data.** Rejected: a missing diary counts as no event and the event rate is under-stated.

## Consequences

- A call of `seroconversion_flag` or `event_flag` without the new required argument stops with a `TypeError`. The programmer adds the rule of the SAP.
- With `inclusive=False` at 38.0 °C, the 38.0 miss comes back with no warning. QC checks the argument against the SAP.
- A plan with a third seroconversion rule (MET44, pre < 1:8 and post >= 1:8) may fit neither form. The programmer then writes the rule with `case_when`.
- `event_flag` can now give null; every denominator states how null is counted.
