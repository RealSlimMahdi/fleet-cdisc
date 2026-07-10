# ADTTE: Time-to-Event in One Chain

A time-to-event parameter answers one question per subject: *how long until X
happened — and if it never did, how long did we watch?* This walkthrough
builds a two-parameter ADTTE (overall survival + time to first adverse
event) in a single chain, shows **why** every subject got their row, and
hands the result straight to a Kaplan-Meier fit. Every output below is real.

## The model in 30 seconds

- An **`EventSource`** says: *in this dataset, these rows, this date column —
  if selected, the clock stops here with `CNSR = 0`.*
- A **`CensorSource`** says the same for censoring (`CNSR ≥ 1`).
- **`.param()`** plays referee per parameter: pool the events, the
  **earliest wins**; no event → the **latest censor**. `STARTDT` comes from
  the pinned ADSL; dates before it are floored to it.
- **`.aval()`** turns `ADT − STARTDT` into `AVAL` (+`AVALU`) afterwards.

Datasets attach by nickname through the pin system — a source saying
`dataset="ADAE"` reads whatever you pinned as `ADAE`.

## 1. Input data

```python
from datetime import date

import polars as pl
import fleet
from fleet.adam.tte import AE_EVENT, CensorSource, DEATH_EVENT, LASTALIVE_CENSOR

adsl = pl.DataFrame(
    {
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
`Date` — a DTC string column is rejected with instructions to `.date()` it
first.

## 2. Sources — typed, reusable, and inspectable

`DEATH_EVENT`, `LASTALIVE_CENSOR`, and `AE_EVENT` ship with Fleet (the full
prebuilt registry: `prebuilt_sources_frame()`). Custom ones are one
constructor call — and unlike admiral's opaque source objects, **every
source renders as a DataFrame**:

```python
from fleet.adam.tte import sources_frame

EOS = CensorSource(dataset="ADSL", date="EOSDT", set={"EVNTDESC": "END OF STUDY"})
print(sources_frame(DEATH_EVENT, LASTALIVE_CENSOR, AE_EVENT))
```

```text
┌────────┬─────────┬──────────┬──────────────────────────┬───────┬────────┬──────────────────────────┐
│ kind   ┆ dataset ┆ date     ┆ where                    ┆ order ┆ censor ┆ set                      │
╞════════╪═════════╪══════════╪══════════════════════════╪═══════╪════════╪══════════════════════════╡
│ event  ┆ ADSL    ┆ DTHDT    ┆ pl.col("DTHFL") == "Y"   ┆ null  ┆ null   ┆ EVNTDESC='DEATH'         │
│ censor ┆ ADSL    ┆ LSTALVDT ┆ null                     ┆ null  ┆ 1      ┆ EVNTDESC='ALIVE'         │
│ event  ┆ ADAE    ┆ ASTDT    ┆ pl.col("TRTEMFL") == "Y" ┆ AESEQ ┆ null   ┆ EVNTDESC='ADVERSE EVENT' │
└────────┴─────────┴──────────┴──────────────────────────┴───────┴────────┴──────────────────────────┘
```

In `set=`, strings are **literals** (`EVNTDESC="DEATH"` is never a column
lookup); reference source columns with a `pl.Expr`. `SRCDOM`/`SRCVAR`/
`SRCSEQ` are stamped automatically from the source's own declaration.

## 3. Derive both parameters in one chain

```python
adtte_ns = (
    adsl.adam.tte.pin("ADSL", adsl)
    .pin("ADAE", adae)
    .param(
        "OS",
        "Overall Survival",
        start_date="TRTSDT",
        events=[DEATH_EVENT],
        censors=[LASTALIVE_CENSOR],
        retain="censor_at_start",
    )  # keep subject 03, censored at STARTDT
    .param(
        "TTAE",
        "Time to First Adverse Event",
        start_date="TRTSDT",
        events=[AE_EVENT],
        censors=[EOS],
        explain=True,
    )  # ← prints the decision trace below
    .aval(unit="days")  # AVAL = ADT − STARTDT + 1, AVALU stamped
    .seq("ASEQ", order_by=["PARAMCD"])
)
adtte = adtte_ns.to_frame()
```

```text
┌─────────┬─────────┬─────────────────────────────┬────────────┬────────────┬──────┬───────────────────┬────────┬──────────┬────────┬───────┬───────┬──────┐
│ USUBJID ┆ PARAMCD ┆ PARAM                       ┆ STARTDT    ┆ ADT        ┆ CNSR ┆ EVNTDESC          ┆ SRCDOM ┆ SRCVAR   ┆ SRCSEQ ┆ AVAL  ┆ AVALU ┆ ASEQ │
╞═════════╪═════════╪═════════════════════════════╪════════════╪════════════╪══════╪═══════════════════╪════════╪══════════╪════════╪═══════╪═══════╪══════╡
│ 01      ┆ OS      ┆ Overall Survival            ┆ 2023-01-01 ┆ 2023-03-01 ┆ 0    ┆ DEATH             ┆ ADSL   ┆ DTHDT    ┆ null   ┆ 60.0  ┆ DAYS  ┆ 1    │
│ 02      ┆ OS      ┆ Overall Survival            ┆ 2023-01-02 ┆ 2023-06-30 ┆ 1    ┆ ALIVE             ┆ ADSL   ┆ LSTALVDT ┆ null   ┆ 180.0 ┆ DAYS  ┆ 1    │
│ 03      ┆ OS      ┆ Overall Survival            ┆ 2023-01-03 ┆ 2023-01-03 ┆ 1    ┆ NO EVENT OBSERVED ┆ ADSL   ┆ TRTSDT   ┆ null   ┆ 1.0   ┆ DAYS  ┆ 1    │
│ 01      ┆ TTAE    ┆ Time to First Adverse Event ┆ 2023-01-01 ┆ 2023-01-10 ┆ 0    ┆ ADVERSE EVENT     ┆ ADAE   ┆ ASTDT    ┆ 1      ┆ 10.0  ┆ DAYS  ┆ 2    │
│ 02      ┆ TTAE    ┆ Time to First Adverse Event ┆ 2023-01-02 ┆ 2023-02-05 ┆ 0    ┆ ADVERSE EVENT     ┆ ADAE   ┆ ASTDT    ┆ 1      ┆ 35.0  ┆ DAYS  ┆ 2    │
│ 03      ┆ TTAE    ┆ Time to First Adverse Event ┆ 2023-01-03 ┆ 2023-02-01 ┆ 1    ┆ END OF STUDY      ┆ ADSL   ┆ EOSDT    ┆ null   ┆ 30.0  ┆ DAYS  ┆ 2    │
└─────────┴─────────┴─────────────────────────────┴────────────┴────────────┴──────┴───────────────────┴────────┴──────────┴────────┴───────┴───────┴──────┘
```

Worth noticing:

- Subject 01's TTAE picked the **earlier** AE, with `order=["AESEQ"]`
  breaking same-date ties deterministically (`SRCSEQ = 1`).
- Subject 03 survived the OS derivation thanks to
  `retain="censor_at_start"` — without it Fleet **warns** with a count
  instead of silently dropping, admiral-style.
- `SRCDOM`/`SRCVAR` are filled in without anyone typing them.
- `AVALU` is stamped by `.aval()` — `unit="months"`/`"years"` use the CDISC
  conversions (30.4375 / 365.25).

## 4. Why did subject 03 get censored? — the decision trace

`explain=True` prints every candidate per subject with the winner and the
reason (the inspectability admiral's quosure objects can't offer):

```text
TTE decision trace — TTAE (Time to First Adverse Event):
┌─────────┬────────┬────────┬────────────┬──────────┬──────────────────────────┐
│ USUBJID ┆ kind   ┆ SRCDOM ┆ date       ┆ selected ┆ reason                   │
╞═════════╪════════╪════════╪════════════╪══════════╪══════════════════════════╡
│ 01      ┆ event  ┆ ADAE   ┆ 2023-01-10 ┆ true     ┆ earliest event           │
│ 02      ┆ event  ┆ ADAE   ┆ 2023-02-05 ┆ true     ┆ earliest event           │
│ 01      ┆ censor ┆ ADSL   ┆ 2023-03-01 ┆ false    ┆ not selected             │
│ 02      ┆ censor ┆ ADSL   ┆ 2023-06-30 ┆ false    ┆ not selected             │
│ 03      ┆ censor ┆ ADSL   ┆ 2023-02-01 ┆ true     ┆ latest censor (no event) │
└─────────┴────────┴────────┴────────────┴──────────┴──────────────────────────┘
```

Typos never make it this far: a source naming `DTHDTT` fails at declaration
with `Did you mean 'DTHDT'?`, before a single row is computed.

## 5. Straight into a survival fit

`km_data()` returns exactly what `lifelines` / `scikit-survival` consume —
and group columns you ask for resolve from the pinned ADSL automatically:

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

<!-- docs:no-run -->

```python
from lifelines import KaplanMeierFitter  # optional — not a Fleet dependency

kmf = KaplanMeierFitter()
for (arm,), grp in km.group_by("TRT01P"):
    kmf.fit(grp["duration"], grp["event"], label=arm)
```

## Going further

- **Window truncation** (admiral 1.5 parity): `end_dates=[CensorSource(...)]`
  closes the observation window — events after it don't count, and the end
  source supplies its own `CNSR`/`EVNTDESC`. `event_type="positive"` covers
  favorable events (time to response): subjects without one censor at the
  window end.
- **Strata**: `by=["AEDECOD"]` derives one parameter per term, with
  per-stratum `PARAMCD` built via an expression in `set_values_to` (a static
  `PARAMCD` across strata is rejected — the 1:1 mapping guard).
- The full verb reference lives in the
  [cheat sheet](../api/cheat_sheet.md#time-to-event-dfadamtte) and the
  [TA API page](../api/ta.md#time-to-event--dfadamtte).
