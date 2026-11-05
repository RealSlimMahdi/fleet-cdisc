# TTE censors at the last record before the stop date

The alpha audit of November 2026 (c1-355) found that `df.adam.tte.param()` censored a subject without an event at the end date, not at the last censor record on or before it. Example: subject A, TRTSDT 2024-01-01, last assessment 2024-03-01, new anticancer therapy 2024-04-01, no progression. Fleet gave ADT 2024-04-01, AVAL 92. admiral 1.5 `derive_param_tte` (`end_dates`, `event_type = "negative"`) gives ADT 2024-03-01, AVAL 61. The unassessed 31 days counted as progression-free. The `event_type` argument changed nothing, and the doc page claimed "admiral 1.5 parity". We decided to follow the admiral rule, and to replace the source objects with plain frames (Mahdi, option A and the API below).

## The decision

```python
adtte = adsl.adam.tte.param(
    "PFS",
    start="TRTSDT",
    events={"PD": adrs.filter(pl.col("AVALC") == "PD")},
    censors={2: last_assessment, 3: adsl.select("USUBJID", ADT="TRTSDT")},
    stop_at=["EOSDT", "NACTDT"],
)
```

- **Sources are plain frames.** Each event or censor value is a Polars frame with the subject keys and `ADT`. The key of `events=` is the EVNTDESC. The key of `censors=` is the CNSR (an integer >= 1). A frame may carry `SRCDOM`, `SRCVAR`, `SRCSEQ`, `CNSDTDSC` and, for a censor, `EVNTDESC`; a censor without `EVNTDESC` gets null. `SRCSEQ` breaks a tie on one date.
- **Stop date.** The stop date of a subject is the earliest non-null `stop_at` date in ADSL. Event and censor records after it are dropped; a record on the stop date stays. This is the admiral rule for both event types.
- **Selection.** The first event left wins: CNSR 0. Without an event, the last censor record left wins: CNSR is the key of its frame. On a censor date tie, the frame given last wins (admiral: the last source in `censor_conditions`). A date before `start` is set to `start` (admiral: ADT = max(ADT, STARTDT)).
- **No record left.** The subject drops, with a warning that names the count and the first USUBJIDs. A censor frame on the start date (CNSR 3 above) keeps such a subject; `retain="censor_at_start"` is the other way.
- **Positive events.** No `event_type` argument. For a favorable event (time to response), add a censor frame on the stop date, for example `{1: adsl.select("USUBJID", ADT=pl.min_horizontal("EOSDT", "NACTDT"))}`. It is the last record in the window, so a subject without the event is censored at the stop date, as admiral `event_type = "positive"`.
- **AVAL** is unchanged: `.aval()` gives ADT − STARTDT + 1 days. Subject A: 61.
- The old `EventSource` / `CensorSource` objects, the prebuilt library (`DEATH_EVENT`, ...), `sources_frame()` and the `start_date=`, `end_dates=` and `event_type=` arguments are removed. No example, define.yaml or spec registry entry used them. When the base frame is ADSL and no ADSL is pinned, `param()` pins it, so a later `param()`, `join_adsl()` and `km_data()` read it.

## Considered options

- **B: keep censoring at the end date.** Rejected: an admiral or SAS double program that censors at the last assessment differs for each such subject (31 days for subject A), and the FDA guidance on oncology endpoints censors at the last adequate assessment before new anticancer therapy.
- **C: keep the source objects and add `consider_end_dates`.** Rejected: the objects repeat what `filter` and `select` already say, and the pin nickname hid which frame a source read.

## Consequences

- A difference from admiral: admiral takes the CNSR and the `set_values_to` of the first end date for a censor record (unless the source sets `consider_end_dates = FALSE`). Fleet takes the CNSR from the key of the censor frame, and the stop columns carry no CNSR. To tell "censored before new therapy" from "censored before end of study", give two censor frames with their own CNSR, or derive `EVNTDESC` on the frame.
- Code that used the old API must change to frames. The package is pre-alpha, so there is no shim.
- References: admiral 1.5.0 `derive_param_tte` (`end_dates`, `event_type`, `censor_source(consider_end_dates)`), its example "End of the observation period"; FDA Guidance for Industry, Clinical Trial Endpoints for the Approval of Cancer Drugs and Biologics (2018), PFS censoring.
