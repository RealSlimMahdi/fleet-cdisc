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

- **Sources are plain frames.** Each event or censor value is a Polars frame with the subject keys and `ADT`. The key of `events=` is the EVNTDESC. The key of `censors=` is the CNSR (an integer >= 1). A frame may carry `SRCDOM`, `SRCVAR`, `SRCSEQ`, `CNSDTDSC` and, for a censor, `EVNTDESC`; a censor without `EVNTDESC` gets null and a warning (see "EVNTDESC of a censor"). `SRCSEQ` breaks a tie on one date.
- **Stop date.** The stop date of a subject is the earliest non-null `stop_at` date in ADSL. Event and censor records after it are dropped; a record on the stop date stays. This is the admiral rule for both event types.
- **Selection.** The first event left wins: CNSR 0. Without an event, the last censor record left wins: CNSR is the key of its frame. On a censor date tie, the frame given last wins (admiral: the last source in `censor_conditions`). A date before `start` is set to `start` (admiral: ADT = max(ADT, STARTDT)). This applies to events and censors; the CNSR does not change (Mahdi: keep the admiral rule).
- **No record left.** The subject drops, with a warning that names the count and the first USUBJIDs. A censor frame on the start date (CNSR 3 above) keeps such a subject; `retain="censor_at_start"` is the other way.
- **Positive events.** No `event_type` argument. For a favorable event (time to response), add a censor frame on the stop date, for example `{1: adsl.select("USUBJID", ADT=pl.min_horizontal("EOSDT", "NACTDT"))}`. It is the last record in the window, so a subject without the event is censored at the stop date, as admiral `event_type = "positive"`.
- **AVAL** is unchanged: `.aval()` gives ADT − STARTDT + 1 days. Subject A: 61.
- The old `EventSource` / `CensorSource` objects, the prebuilt library (`DEATH_EVENT`, ...), `sources_frame()` and the `start_date=`, `end_dates=` and `event_type=` arguments are removed. No example, define.yaml or spec registry entry used them. When the base frame is ADSL and no ADSL is pinned, `param()` pins it, so a later `param()`, `join_adsl()` and `km_data()` read it.

## EVNTDESC of a censor

Mahdi: use the guidance first, then the admiral default, else make a call.

- **Guidance.** ADaM BDS-TTE v1.0 (CDISC, published 2016-02-12) defines EVNTDESC (Event or Censoring Description) as a permissible free-text variable with no codelist; its examples give a study text on each row (for example DEATH, COMPLETED STUDY). CDISC ADaM CT on NCI EVS (checked November 2026) has no EVNTDESC codelist. So the guidance gives no default value.
- **admiral.** `censor_source()` has no default EVNTDESC: it is NA unless `set_values_to` gives it.
- **The call.** A censor frame without an `EVNTDESC` column gives a null EVNTDESC, as admiral, and `param()` warns once per call. The warning names the CNSR keys and shows the fix (`EVNTDESC=pl.lit("ALIVE")` on the frame). A fixed text such as "CENSORED" was rejected: the reason of the censoring is study text from the SAP, and a text that Fleet invents differs from an admiral or SAS double program on every censored row. A silent null was rejected: BDS-TTE expects a description on censored rows, and the reviewer cannot tell why a subject was censored.
- `retain="censor_at_start"` keeps its own text, NO EVENT OBSERVED.

## PARAM label

Mahdi: when `param` is not given, use the controlled terminology. `param()` takes PARAM from, in this order:

1. `param=`, or PARAM in `set_values_to`.
2. The study CT: the `decode` of PARAMCD in the codelist that a `PARAMCD` variable of the ADaM `define.yaml` references (the ADTTE dataset first, then the other datasets). The study is the first `study_config.yaml` in the working directory or above it, as `import_codelists()` finds it. `fleet init ct` writes the CDISC CT preferred terms as these decodes, so a PARAMCD from a pinned CDISC CT codelist resolves here too.
3. CDISC CT itself: no lookup. CDISC ADaM CT (NCI EVS, November 2026) has no time-to-event PARAMCD codelist; its parameter code codelists (for example GAD02PC, HAMD1PC) are questionnaire and scale codes. The generated `codelists.py` holds submission values only, not decodes. Fleet makes no network call.

If no source gives a label, `param()` raises. The message names PARAMCD, the places searched and the fix (`param=`, or a decode in the define.yaml codelist). When PARAMCD comes from `set_values_to` (strata), PARAM must come from there too, because the static PARAMCD does not name the stratum. Before this change, a missing label gave rows without PARAM; ADaMIG requires PARAM with a one-to-one map to PARAMCD.

## Considered options

- **B: keep censoring at the end date.** Rejected: an admiral or SAS double program that censors at the last assessment differs for each such subject (31 days for subject A), and the FDA guidance on oncology endpoints censors at the last adequate assessment before new anticancer therapy.
- **C: keep the source objects and add `consider_end_dates`.** Rejected: the objects repeat what `filter` and `select` already say, and the pin nickname hid which frame a source read.

## Consequences

- A difference from admiral: admiral takes the CNSR and the `set_values_to` of the first end date for a censor record (unless the source sets `consider_end_dates = FALSE`). Fleet takes the CNSR from the key of the censor frame, and the stop columns carry no CNSR. To tell "censored before new therapy" from "censored before end of study", give two censor frames with their own CNSR, or derive `EVNTDESC` on the frame.
- Code that used the old API must change to frames. The package is pre-alpha, so there is no shim.
- References: admiral 1.5.0 `derive_param_tte` (`end_dates`, `event_type`, `censor_source(consider_end_dates)`), its example "End of the observation period"; FDA Guidance for Industry, Clinical Trial Endpoints for the Approval of Cancer Drugs and Biologics (2018), PFS censoring; CDISC ADaM BDS-TTE v1.0 (EVNTDESC, CNSDTDSC); ADaMIG v1.3 (PARAM, PARAMCD); CDISC ADaM CT, NCI EVS `ADaM Terminology.txt`.
