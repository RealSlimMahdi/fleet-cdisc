# TTE censors at the last record before the stop date

The alpha audit of November 2026 (c1-355) found that `df.adam.tte.param()` censored a subject without an event at the end date, not at the last censor record on or before it. Example: subject A, TRTSDT 2024-01-01, last assessment 2024-03-01, new anticancer therapy 2024-04-01, no progression. Fleet gave ADT 2024-04-01, AVAL 92. admiral 1.5 `derive_param_tte` (`end_dates`, `event_type = "negative"`) gives ADT 2024-03-01, AVAL 61. The unassessed 31 days counted as progression-free. The `event_type` argument changed nothing, and the doc page claimed "admiral 1.5 parity". We decided to follow the admiral rule, and to replace the source objects with plain frames (Mahdi, option A and the API below).

## The decision

```python
adtte = adsl.adam.tte.param(
    "PFS",
    "Progression-Free Survival",
    start="TRTSDT",
    events={"PROGRESSIVE DISEASE": adrs.filter(pl.col("AVALC") == "PD")},
    censors={
        1: last_assessment.with_columns(CNSDTDSC=pl.lit("LAST ADEQUATE TUMOR ASSESSMENT")),
        3: no_baseline,
    },
    stop_at={
        "EOSDT": (4, "END OF STUDY"),
        "NACTDT": (2, "NEW ANTICANCER THERAPY"),
        "DCUTDT": (5, "DATA CUT-OFF"),
    },
    keep_reason=[3],
)
```

- **Sources are plain frames.** Each event or censor value is a Polars frame with the subject keys and `ADT`. The key of `events=` is the EVNTDESC. The key of `censors=` is the CNSR (an integer >= 1). A frame may carry `SRCDOM`, `SRCVAR`, `SRCSEQ`, `CNSDTDSC` and, for a censor, `EVNTDESC`; a censor without `EVNTDESC` gets null and a warning (see "EVNTDESC of a censor"). `SRCSEQ` breaks a tie on one date.
- **Stop date.** `stop_at=` maps an ADSL date column to `(CNSR, EVNTDESC)`. The stop date of a subject is the earliest non-null `stop_at` date. Event and censor records after it are dropped; a record on the stop date stays. This is the admiral rule for both event types.
- **Selection.** The first event left wins: CNSR 0, EVNTDESC its key. Without an event, the last censor record left gives the date (ADT, CNSDTDSC). On a censor date tie, the frame given last wins (admiral: the last source in `censor_conditions`). CNSR and EVNTDESC follow "Reason of the censoring" below. A date before `start` is set to `start` (admiral: ADT = max(ADT, STARTDT)). This applies to events and censors; the CNSR does not change (Mahdi: keep the admiral rule).
- **No record left.** The subject drops, with a warning that names the count and the first USUBJIDs. A censor frame on the start date (CNSR 3 above) keeps such a subject; `retain="censor_at_start"` is the other way.
- **Positive events.** No `event_type` argument. For a favorable event (time to response), add a censor frame on the stop date, for example `{1: adsl.select("USUBJID", ADT=pl.min_horizontal("EOSDT", "NACTDT"))}`. It is the last record in the window, so a subject without the event is censored at the stop date, as admiral `event_type = "positive"`. The stop gives the CNSR and EVNTDESC of that row.
- **AVAL** is unchanged: `.aval()` gives ADT − STARTDT + 1 days. Subject A: 61.
- The old `EventSource` / `CensorSource` objects, the prebuilt library (`DEATH_EVENT`, ...), `sources_frame()` and the `start_date=`, `end_dates=` and `event_type=` arguments are removed. No example, define.yaml or spec registry entry used them. When the base frame is ADSL and no ADSL is pinned, `param()` pins it, so a later `param()`, `join_adsl()` and `km_data()` read it.

## Reason of the censoring

A follow-up of c1-355 (Mahdi, option B, November 2026). The first version took the CNSR from the key of the censor frame, and the stop columns carried no CNSR. To tell "censored before new therapy" from "censored at end of study", a programmer had to build one censor frame per stop. A forgotten frame gave a wrong CNSR on every such subject.

**Rationale.** RECIST 1.1 defines progression, not censoring. The FDA guidance "Clinical Trial Endpoints for the Approval of Cancer Drugs and Biologics" (2018) and the EMA appendix on PFS (Guideline on the evaluation of anticancer medicinal products, Appendix 1) separate two facts for a censored subject:

- The **date**: the last adequate tumour assessment before the stop.
- The **reason**: why the observation stopped (new anticancer therapy, end of study, data cut-off, no baseline assessment).

ADaM BDS-TTE puts the reason in CNSR and EVNTDESC, and the description of the date in CNSDTDSC. So the stop carries CNSR and EVNTDESC; the censor frame carries the date and CNSDTDSC. This is also the admiral rule for `end_dates`: a censor record takes the `censor` and `set_values_to` of the first end date, and `consider_end_dates = FALSE` on a `censor_source` is the opt-out.

**The rule.** For a subject with no event in the window, CNSR and EVNTDESC come from, in this order:

1. A censor frame whose key is in `keep_reason=`: its own key and its own EVNTDESC (admiral `consider_end_dates = FALSE`). Example: no baseline assessment, censored on TRTSDT with CNSR 3, although the data cut-off applies.
2. Else, when the subject has a stop date: the stop. If two stop columns share the earliest date, the first column in the `stop_at` dict wins.
3. Else (no stop date): the key of the censor frame, and EVNTDESC from the frame (or null with the warning).

CNSDTDSC from the censor frame is kept in all cases. ADT and AVAL do not change. An event keeps CNSR 0 and its EVNTDESC; events after the stop date stay dropped. `retain="censor_at_start"` keeps its own CNSR 1 and NO EVENT OBSERVED: it is a fallback for subjects with no record, not a censor frame.

**Validation.**

- `stop_at` must be a dict. A list raises, and the message shows the dict form. The package is pre-alpha, so there is no shim; a list form "stop with no reason" was rejected because two forms of one argument hide which rule gave the CNSR.
- Each value is `(CNSR, EVNTDESC)`: an integer >= 1 and a non-empty text.
- The stop codes are distinct, and they differ from the `censors=` keys. One CNSR value then names one reason, and a reviewer can read the reason from CNSR alone. admiral allows two end dates with the same `censor` (its default is 1); Fleet does not. To give two columns one reason, combine them first, for example `adsl.with_columns(STOPDT=pl.min_horizontal("EOSDT", "LSTCONDT"))`.
- `keep_reason` keys must be keys of `censors=`.

**Trace.** `explain=True` (and the trace of `select_tte()`) has a `cnsr_from` column on the selected row: `event`, `keep_reason`, `stop_at <column>`, `censors key` or `retain`.

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

- Differences from admiral: the stop codes must be distinct (admiral allows the same `censor` on two end dates). The stop EVNTDESC replaces the EVNTDESC of the censor frame; in admiral, a `set_values_to` of the censor source overwrites the end date value unless it uses `coalesce()`. Fleet takes the guidance order: the reason of the stop wins, and `keep_reason` is the explicit opt-out.
- Code that used the old API must change to frames. The package is pre-alpha, so there is no shim. Code that passed `stop_at` as a list must give the dict form.
- References: admiral 1.5.0 `derive_param_tte` (`end_dates`, `event_type`, `censor_source(consider_end_dates)`), its examples "End of the observation period" and "Differentiating censoring reasons"; FDA Guidance for Industry, Clinical Trial Endpoints for the Approval of Cancer Drugs and Biologics (2018), PFS censoring; EMA Guideline on the evaluation of anticancer medicinal products in man, Appendix 1 (methodological considerations for PFS); RECIST 1.1; CDISC ADaM BDS-TTE v1.0 (CNSR, EVNTDESC, CNSDTDSC); ADaMIG v1.3 (PARAM, PARAMCD); CDISC ADaM CT, NCI EVS `ADaM Terminology.txt`.
