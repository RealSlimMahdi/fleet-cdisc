# A study that `fleet run` builds end to end (MINIPILOT)

`examples/minipilot` is a small synthetic study. Its define files drive every
dataset, from the raw CSV files to ADaM, so one command builds the whole study:

```bash
uv run fleet run --config examples/minipilot/study_config.yaml --out out/minipilot
```

## Why this study exists

- **The CDISCPILOT01 example is script-driven.** Its define files read raw
  columns that only `examples/cdiscpilot01_spec_driven.py` creates, and the
  script derives some variables inline. So `fleet run` cannot build its ADVS,
  ADAE or ADEX (finding c1-347).
- **MINIPILOT holds no code.** Every variable is either derived in a define
  file or carried from an input that the `inputs:` block names. What
  `fleet run` writes is what the define files say.
- **It is a template.** Copy the folder to start a study that `fleet run`
  builds, and replace the raw files and the variables.
- **A test keeps it working.** `tests/unit/test_minipilot_study.py` runs it
  with `fleet run` and checks every declared variable.

## What is in the folder

| Path | Content |
|---|---|
| `study_config.yaml` | Study id, IG versions, where the define files are |
| `raw/*.csv` | 3 subjects: demographics, adverse events, vital signs, exposure |
| `sdtm/define.yaml` | DM, AE, VS and EX, each from one raw file |
| `adam/define.yaml` | ADSL from DM and EX; ADVS, ADAE and ADEX from their SDTM domain and ADSL |

The run order comes from the `type: dataset` inputs: ADSL runs before ADVS,
ADAE and ADEX, because they read it.

## The clinical rules it shows

| Variable | Rule |
|---|---|
| ADSL.SAFFL | Y when the subject has an EX record with EXDOSE > 0, or EXDOSE = 0 and EXTRT contains PLACEBO; else N. Subject 003 had no dose: N. |
| ADVS.AVAL | VSSTRESN. |
| ADVS.ABLFL | The last record, by ADT then VISITNUM, with a non-missing AVAL and ADT on or before TRTSDT, per USUBJID and PARAMCD. Subject 002 has no DAY 1 value, so its baseline is the screening record. |
| ADVS.CHG, PCHG | Only on post-baseline records (ADT after TRTSDT); null on the baseline record and before it. |
| ADAE.TRTEMFL | Start on or after TRTSDT and on or before TRTEDT. |
| ADEX.EXDURD | AENDT - ASTDT + 1. |

## How to use it

### 1. Check the study

`fleet check` reads the study config and checks each define file against its
schema, before any dataset is built:

```bash
uv run fleet check --config examples/minipilot/study_config.yaml
```

### 2. Build the datasets

Build every dataset, then only some of them:

```bash
uv run fleet run --config examples/minipilot/study_config.yaml --out out/minipilot
uv run fleet run --config examples/minipilot/study_config.yaml --out out/minipilot \
    --dataset ADSL --dataset ADVS
```

`out/minipilot` then holds one parquet file per dataset: `dm.parquet` to
`adex.parquet`.

### 3. QC a dataset with inline verbs

A QC programmer writes ADVS a second time, with the inline verbs, from the
SDTM VS and the ADSL that `fleet run` wrote. Each verb is one rule of the
define file:

```python
import polars as pl

import fleet

vs = fleet.frame(pl.read_parquet("out/minipilot/vs.parquet"))
adsl = pl.read_parquet("out/minipilot/adsl.parquet").select("USUBJID", "TRT01A", "TRTSDT", "SAFFL")

advs = (
    vs.adam.merge(dataset=adsl, on="USUBJID", how="left")
    .assign("PARAMCD", source="VSTESTCD")
    .assign("PARAM", source="VSTEST")
    .assign("AVAL", source="VSSTRESN")
    .assign("AVALU", source="VSSTRESU")
    .date("ADT", source="VSDTC")
    .flag(
        "ABLFL",
        criteria="last",
        by=["USUBJID", "PARAMCD"],
        order_by=["ADT", "VISITNUM"],
        where="pl.col('AVAL').is_not_null() & (pl.col('ADT') <= pl.col('TRTSDT'))",
    )
    .baseline("BASE", aval="AVAL", baseline_flag="ABLFL", by=["USUBJID", "PARAMCD"])
    .chg("CHG", aval="AVAL", base="BASE", post_baseline="pl.col('ADT') > pl.col('TRTSDT')")
    .pchg("PCHG", aval="AVAL", base="BASE", post_baseline="pl.col('ADT') > pl.col('TRTSDT')")
    .to_frame()
    # keep= of SAS: the ADVS variables of the define, without the SDTM VS ones
    .select(
        "STUDYID",
        "USUBJID",
        "TRT01A",
        "TRTSDT",
        "SAFFL",
        "PARAMCD",
        "PARAM",
        "AVAL",
        "AVALU",
        "VISITNUM",
        "VISIT",
        "ADT",
        "ADTF",
        "ABLFL",
        "BASE",
        "CHG",
        "PCHG",
    )
)
advs.write_parquet("out/minipilot/advs_qc.parquet")
```

Then `fleet compare`, the PROC COMPARE of Fleet, checks every variable of
the two datasets:

```bash
uv run fleet compare out/minipilot/advs.parquet out/minipilot/advs_qc.parquet \
    --keys USUBJID,PARAMCD,VISITNUM
```

The verdict is `EQUAL: no differences found.` and the exit code is 0.

## When a variable is missing

A variable with no `derivation:` is carried from the inputs. When no input has
it, `fleet run` stops and names the variable, so a dataset is never written
without it (ADR 0053). There are two ways out:

- `optional: true` on the variable in the define, for a variable the study
  does not collect. A reviewer sees it in the define.
- `fleet run --no-strict`, for one draft run: the stop becomes a warning.
