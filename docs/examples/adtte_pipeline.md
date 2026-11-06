# ADTTE: Time-to-Event in One Chain

A time-to-event parameter answers one question per subject: *how long until X
happened, and if it never did, how long did we watch?* This walkthrough
builds a two-parameter ADTTE (overall survival + time to first adverse
event) in a single chain, shows **why** every subject got their row, and
hands the result straight to a Kaplan-Meier fit. It then adds a PFS
parameter that stops the observation at new anticancer therapy. Every output
below is real.

## The model in 30 seconds

- An **event** or **censor** source is a plain Polars frame with `USUBJID`
  and `ADT`. Build it with `filter` and `select`.
- **`.param()`** plays referee per parameter: the **earliest event wins**
  (`CNSR = 0`, `EVNTDESC` = its key in `events=`); no event gives the
  **last censor record** (`CNSR` = its key in `censors=`). `STARTDT` comes
  from ADSL; a date before it is set to it.
- **`stop_at=`** maps ADSL date columns to `(CNSR, EVNTDESC)`. The earliest
  one ends the observation: event and censor records after it are dropped
  (admiral 1.5 `end_dates`, ADR-0043). A censored subject takes the date
  from the censor frame and the reason from the stop.
- **`.aval()`** turns `ADT − STARTDT + 1` into `AVAL` (+`AVALU`) afterwards.

!!! note "Choosing the time origin (`start=`)"
    `TRTSDT` (ADaMIG: *Date of First Exposure to Treatment*) is the
    conventional origin for **safety** endpoints like time to first AE.
    For ITT **efficacy** endpoints in randomized trials, overall survival
    in particular, use the randomization date (`RANDDT`): ITT time starts
    at randomization, not at first dose. `start=` accepts any ADSL date
    column, so pick per parameter.

## 1. Input data

```python
from datetime import date

import polars as pl
import fleet

adsl = pl.DataFrame(
    {
        "STUDYID": ["S1", "S1", "S1"],
        "USUBJID": ["01", "02", "03"],
        "TRT01P": ["Drug A", "Placebo", "Drug A"],
        "TRTSDT": [date(2023, 1, 1), date(2023, 1, 2), date(2023, 1, 3)],
        "DTHFL": ["Y", None, None],
        "DTHDT": [date(2023, 3, 1), None, None],
        "LSTALVDT": [date(2023, 3, 1), date(2023, 6, 30), None],
        "EOSDT": [date(2023, 3, 1), date(2023, 6, 30), date(2023, 2, 1)],
    }
)
adae = pl.DataFrame(
    {
        "USUBJID": ["01", "01", "02"],
        "TRTEMFL": ["Y", "Y", "Y"],
        "ASTDT": [date(2023, 1, 20), date(2023, 1, 10), date(2023, 2, 5)],
        "AESEQ": [2, 1, 1],
    }
)
```

Note the traps this tiny study contains: subject 01 has an earlier *and* a
later AE (tie-break needed), subject 03 has **no death, no last-alive date,
and no AE** (the classic silently-dropped subject), and dates must be typed
`Date`: a DTC string column is rejected with instructions to `.date()` it
first.

## 2. Sources: plain frames

Each source is one `select`. The date goes to `ADT`. A source may also
carry `SRCDOM`, `SRCVAR`, `SRCSEQ`, `CNSDTDSC` and (censors only)
`EVNTDESC`; they go onto the selected row. `SRCSEQ` also breaks a tie on
one date. A censor frame without `EVNTDESC` gives a null `EVNTDESC` and a
warning: the reason of the censoring is study text.

Without a PARAM label, `.param()` reads it from the study CT: the decode
of PARAMCD in the codelist of `ADTTE.PARAMCD` in the ADaM `define.yaml`.
If there is no such decode, it raises and asks for `param=`.

```python
death = adsl.filter(pl.col("DTHFL") == "Y").select(
    "USUBJID", ADT="DTHDT", SRCDOM=pl.lit("ADSL"), SRCVAR=pl.lit("DTHDT")
)
alive = adsl.select(
    "USUBJID",
    ADT="LSTALVDT",
    EVNTDESC=pl.lit("ALIVE"),
    SRCDOM=pl.lit("ADSL"),
    SRCVAR=pl.lit("LSTALVDT"),
)
first_ae = adae.filter(pl.col("TRTEMFL") == "Y").select(
    "USUBJID", ADT="ASTDT", SRCDOM=pl.lit("ADAE"), SRCVAR=pl.lit("ASTDT"), SRCSEQ="AESEQ"
)
eos = adsl.select(
    "USUBJID",
    ADT="EOSDT",
    EVNTDESC=pl.lit("END OF STUDY"),
    SRCDOM=pl.lit("ADSL"),
    SRCVAR=pl.lit("EOSDT"),
)
```

## 3. Derive both parameters in one chain

```python
adtte_ns = (
    adsl.adam.tte.param(
        "OS",
        "Overall Survival",
        start="TRTSDT",
        events={"DEATH": death},
        censors={1: alive},
        retain="censor_at_start",
    )  # keep subject 03, censored at STARTDT
    .param(
        "TTAE",
        "Time to First Adverse Event",
        start="TRTSDT",
        events={"ADVERSE EVENT": first_ae},
        censors={1: eos},
        explain=True,
    )  # ← prints the decision trace below
    .join_adsl("TRT01P")  # after the last param(): earlier rows would get null
    .aval(unit="days")  # AVAL = ADT − STARTDT + 1, AVALU stamped
    .seq("ASEQ", order_by=["PARAMCD"])
)
adtte = adtte_ns.to_frame()
```

```text
┌─────────┬─────────┬────────────┬────────────┬──────┬────────┬──────────┬───────────────────┬─────────┬─────────────────────────────┬────────┬─────────┬───────┬───────┬──────┐
│ STUDYID ┆ USUBJID ┆ STARTDT    ┆ ADT        ┆ CNSR ┆ SRCDOM ┆ SRCVAR   ┆ EVNTDESC          ┆ PARAMCD ┆ PARAM                       ┆ SRCSEQ ┆ TRT01P  ┆ AVAL  ┆ AVALU ┆ ASEQ │
╞═════════╪═════════╪════════════╪════════════╪══════╪════════╪══════════╪═══════════════════╪═════════╪═════════════════════════════╪════════╪═════════╪═══════╪═══════╪══════╡
│ S1      ┆ 01      ┆ 2023-01-01 ┆ 2023-03-01 ┆ 0    ┆ ADSL   ┆ DTHDT    ┆ DEATH             ┆ OS      ┆ Overall Survival            ┆ null   ┆ Drug A  ┆ 60.0  ┆ DAYS  ┆ 1    │
│ S1      ┆ 02      ┆ 2023-01-02 ┆ 2023-06-30 ┆ 1    ┆ ADSL   ┆ LSTALVDT ┆ ALIVE             ┆ OS      ┆ Overall Survival            ┆ null   ┆ Placebo ┆ 180.0 ┆ DAYS  ┆ 1    │
│ S1      ┆ 03      ┆ 2023-01-03 ┆ 2023-01-03 ┆ 1    ┆ ADSL   ┆ TRTSDT   ┆ NO EVENT OBSERVED ┆ OS      ┆ Overall Survival            ┆ null   ┆ Drug A  ┆ 1.0   ┆ DAYS  ┆ 1    │
│ S1      ┆ 01      ┆ 2023-01-01 ┆ 2023-01-10 ┆ 0    ┆ ADAE   ┆ ASTDT    ┆ ADVERSE EVENT     ┆ TTAE    ┆ Time to First Adverse Event ┆ 1      ┆ Drug A  ┆ 10.0  ┆ DAYS  ┆ 2    │
│ S1      ┆ 02      ┆ 2023-01-02 ┆ 2023-02-05 ┆ 0    ┆ ADAE   ┆ ASTDT    ┆ ADVERSE EVENT     ┆ TTAE    ┆ Time to First Adverse Event ┆ 1      ┆ Placebo ┆ 35.0  ┆ DAYS  ┆ 2    │
│ S1      ┆ 03      ┆ 2023-01-03 ┆ 2023-02-01 ┆ 1    ┆ ADSL   ┆ EOSDT    ┆ END OF STUDY      ┆ TTAE    ┆ Time to First Adverse Event ┆ null   ┆ Drug A  ┆ 30.0  ┆ DAYS  ┆ 2    │
└─────────┴─────────┴────────────┴────────────┴──────┴────────┴──────────┴───────────────────┴─────────┴─────────────────────────────┴────────┴─────────┴───────┴───────┴──────┘
```

Worth noticing:

- The first `.param()` uses the base frame as ADSL and pins it, so the
  next `.param()`, `.join_adsl()` and `.km_data()` read it too.
- STUDYID comes from ADSL on every row. Other ADSL variables, such as
  TRT01P, come from `.join_adsl()` after the last `.param()`.
- Subject 01's TTAE picked the **earlier** AE; `SRCSEQ` breaks same-date
  ties deterministically.
- Subject 03 survived the OS derivation thanks to
  `retain="censor_at_start"`. Without it Fleet **warns** with the count and
  the USUBJIDs instead of silently dropping, admiral-style.
- `AVALU` is stamped by `.aval()`; `unit="months"`/`"years"` use the CDISC
  conversions (30.4375 / 365.25).

## 4. Why did subject 03 get censored? The decision trace

`explain=True` logs every candidate per subject with the selected one, the
reason and `cnsr_from`, the rule that gave the CNSR:

```text
TTE decision trace — TTAE (Time to First Adverse Event):
┌─────────┬────────┬───────────────┬────────────┬──────────┬────────────────────────┬─────────────┐
│ USUBJID ┆ kind   ┆ source        ┆ date       ┆ selected ┆ reason                 ┆ cnsr_from   │
╞═════════╪════════╪═══════════════╪════════════╪══════════╪════════════════════════╪═════════════╡
│ 01      ┆ event  ┆ ADVERSE EVENT ┆ 2023-01-10 ┆ true     ┆ earliest event         ┆ event       │
│ 02      ┆ event  ┆ ADVERSE EVENT ┆ 2023-02-05 ┆ true     ┆ earliest event         ┆ event       │
│ 01      ┆ censor ┆ CNSR 1        ┆ 2023-03-01 ┆ false    ┆ not selected           ┆ null        │
│ 02      ┆ censor ┆ CNSR 1        ┆ 2023-06-30 ┆ false    ┆ not selected           ┆ null        │
│ 03      ┆ censor ┆ CNSR 1        ┆ 2023-02-01 ┆ true     ┆ last censor (no event) ┆ censors key │
└─────────┴────────┴───────────────┴────────────┴──────────┴────────────────────────┴─────────────┘
```

A frame without `ADT` fails before a single row is computed, and the error
shows the fix: `adae.select("USUBJID", ADT="ASTDT")`.

## 5. Straight into a survival fit

`km_data()` returns exactly what `lifelines` / `scikit-survival` consume,
and group columns you ask for resolve from ADSL automatically:

```python
km = adtte_ns.km_data("OS", by=["TRT01P"])
```

```text
┌─────────┬──────────┬───────┬─────────┐
│ USUBJID ┆ duration ┆ event ┆ TRT01P  │
╞═════════╪══════════╪═══════╪═════════╡
│ 01      ┆ 60.0     ┆ true  ┆ Drug A  │
│ 02      ┆ 180.0    ┆ false ┆ Placebo │
│ 03      ┆ 1.0      ┆ false ┆ Drug A  │
└─────────┴──────────┴───────┴─────────┘
```

<!-- docs:no-run: needs lifelines, not a Fleet dependency -->

```python
from lifelines import KaplanMeierFitter  # optional — not a Fleet dependency

kmf = KaplanMeierFitter()
for (arm,), grp in km.group_by("TRT01P"):
    kmf.fit(grp["duration"], grp["event"], label=arm)
```

## 6. PFS: stop the observation at new therapy or data cut-off

`stop_at=` follows admiral 1.5 `derive_param_tte` with `end_dates` and
`event_type = "negative"` (ADR-0043). It maps an ADSL date column to a
`(CNSR, EVNTDESC)` pair. The earliest non-null `stop_at` date of a subject
ends the observation. Events and censor records after it are dropped, so a
subject without progression is censored at the **last assessment before
the stop**, not at the stop date.

A censored row holds two facts (FDA 2018 oncology endpoints guidance, EMA
PFS appendix, ADaM BDS-TTE):

- The **date**: the last adequate assessment. It comes from the censor
  frame, with `CNSDTDSC`.
- The **reason**: why the observation stopped. It comes from the stop:
  `CNSR` and `EVNTDESC`.

```python
adsl_pfs = pl.from_repr("""
┌─────────┬────────────┬────────────┬────────────┬────────────┐
│ USUBJID ┆ TRTSDT     ┆ EOSDT      ┆ NACTDT     ┆ DCUTDT     │
│ ---     ┆ ---        ┆ ---        ┆ ---        ┆ ---        │
│ str     ┆ date       ┆ date       ┆ date       ┆ date       │
╞═════════╪════════════╪════════════╪════════════╪════════════╡
│ A       ┆ 2024-01-01 ┆ 2024-06-30 ┆ 2024-04-01 ┆ 2024-05-31 │
│ B       ┆ 2024-01-01 ┆ 2024-06-30 ┆ 2024-02-15 ┆ 2024-05-31 │
│ C       ┆ 2024-01-01 ┆ null       ┆ null       ┆ 2024-05-31 │
│ D       ┆ 2024-01-01 ┆ null       ┆ null       ┆ 2024-05-31 │
└─────────┴────────────┴────────────┴────────────┴────────────┘
""")
adrs = pl.from_repr("""
┌─────────┬────────────┬───────┐
│ USUBJID ┆ ADT        ┆ AVALC │
│ ---     ┆ ---        ┆ ---   │
│ str     ┆ date       ┆ str   │
╞═════════╪════════════╪═══════╡
│ A       ┆ 2024-02-01 ┆ SD    │
│ A       ┆ 2024-03-01 ┆ SD    │
│ B       ┆ 2024-02-01 ┆ SD    │
│ B       ┆ 2024-03-10 ┆ PD    │
│ C       ┆ 2024-02-01 ┆ SD    │
│ C       ┆ 2024-04-15 ┆ SD    │
│ C       ┆ 2024-06-10 ┆ PD    │
└─────────┴────────────┴───────┘
""")
last_assessment = adrs.select(
    "USUBJID",
    "ADT",
    EVNTDESC=pl.lit("NO PROGRESSION"),
    CNSDTDSC=pl.lit("LAST ADEQUATE TUMOR ASSESSMENT"),
)
no_baseline = adsl_pfs.join(adrs, on="USUBJID", how="anti").select(
    "USUBJID", ADT="TRTSDT", EVNTDESC=pl.lit("NO BASELINE ASSESSMENT")
)

pfs = (
    adsl_pfs.adam.tte.param(
        "PFS",
        "Progression-Free Survival",
        start="TRTSDT",
        events={"PROGRESSIVE DISEASE": adrs.filter(pl.col("AVALC") == "PD")},
        censors={1: last_assessment, 3: no_baseline},  # key = CNSR
        stop_at={  # column: (CNSR, EVNTDESC)
            "EOSDT": (4, "END OF STUDY"),
            "NACTDT": (2, "NEW ANTICANCER THERAPY"),
            "DCUTDT": (5, "DATA CUT-OFF"),
        },
        keep_reason=[3],
    )
    .aval()
    .to_frame()
)
```

```text
┌─────────┬────────────┬────────────┬──────┬────────────────────────┬────────────────────────────────┬───────┐
│ USUBJID ┆ STARTDT    ┆ ADT        ┆ CNSR ┆ EVNTDESC               ┆ CNSDTDSC                       ┆ AVAL  │
╞═════════╪════════════╪════════════╪══════╪════════════════════════╪════════════════════════════════╪═══════╡
│ A       ┆ 2024-01-01 ┆ 2024-03-01 ┆ 2    ┆ NEW ANTICANCER THERAPY ┆ LAST ADEQUATE TUMOR ASSESSMENT ┆ 61.0  │
│ B       ┆ 2024-01-01 ┆ 2024-02-01 ┆ 2    ┆ NEW ANTICANCER THERAPY ┆ LAST ADEQUATE TUMOR ASSESSMENT ┆ 32.0  │
│ C       ┆ 2024-01-01 ┆ 2024-04-15 ┆ 5    ┆ DATA CUT-OFF           ┆ LAST ADEQUATE TUMOR ASSESSMENT ┆ 106.0 │
│ D       ┆ 2024-01-01 ┆ 2024-01-01 ┆ 3    ┆ NO BASELINE ASSESSMENT ┆ null                           ┆ 1.0   │
└─────────┴────────────┴────────────┴──────┴────────────────────────┴────────────────────────────────┴───────┘
```

- Subject A has no progression: ADT is the last assessment (2024-03-01),
  not the new-therapy date (2024-04-01). The reason is the new therapy:
  CNSR 2.
- Subject B progressed on 2024-03-10, after new therapy on 2024-02-15: the
  PD does not count. B is censored at the last assessment before it.
- Subject C progressed on 2024-06-10, after the data cut-off: the PD does
  not count. C is censored at 2024-04-15 with CNSR 5, DATA CUT-OFF.
- Subject D has no assessment. `keep_reason=[3]` keeps CNSR 3 and the text
  of its frame, although the data cut-off applies to D too (admiral
  `consider_end_dates = FALSE`). Without such a frame, D is dropped with a
  warning.

CNSR and EVNTDESC of a censored subject come from, in this order:

1. A censor frame whose key is in `keep_reason=`.
2. The stop of the subject. On a tie of two stop dates, the first column
   in `stop_at=` wins.
3. The censor frame (CNSR = its key), when the subject has no stop date.

The stop codes must differ from each other and from the `censors=` keys,
so that one CNSR value names one reason. `explain=True` adds a
`cnsr_from` column to the trace, with the rule per subject.

For a favorable event (time to response, admiral `event_type =
"positive"`), censor at the stop date: add
`{1: adsl.select("USUBJID", ADT=pl.min_horizontal("EOSDT", "NACTDT"))}` to
`censors=`.

## Going further

- **Strata**: `by=["AEDECOD"]` derives one parameter per term, with
  per-stratum `PARAMCD` built via an expression in `set_values_to` (a static
  `PARAMCD` across strata is rejected: the 1:1 mapping guard). Every source
  frame carries the `by` columns.
- The full verb reference lives in the
  [cheat sheet](../api/cheat_sheet.md#time-to-event-dfadamtte) and the
  [TA API page](../api/ta.md#time-to-event-dfadamtte).
