# Installation

## Requirements

- Python 3.12 to 3.14
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

## Install

Fleet is pre-alpha. Only pre-release versions are on PyPI, so tell the installer to accept them.

=== "uv (recommended)"

    ```bash
    uv init my-study && cd my-study
    uv add fleet-cdisc --prerelease=allow
    ```

=== "pip"

    ```bash
    pip install --pre fleet-cdisc
    ```

### Optional extras

| Extra  | Installs         | When to use                    |
| ------ | ---------------- | ------------------------------ |
| `io`   | `pyreadstat`     | Reading SAS files (`.xpt`, `.sas7bdat`) and writing XPT |
| `all`  | All extras       | Full feature set               |
| `docs` | MkDocs + plugins | Building this documentation    |
| `dev`  | pytest, ruff, io | Contributing to Fleet          |

```bash
# SAS XPT support
uv add "fleet-cdisc[io]"

# Development
uv add "fleet-cdisc[dev]"
```

## Verify the installation

```python
import fleet

print(fleet.__version__)  # e.g. 0.2.0a1
```

Save this as a file and run it with `uv run python <file>.py`, or run
`uv run python -c "import fleet; print(fleet.__version__)"`.

After the import, `.sdtm`, `.adam` and `.tlg` are on every `polars.DataFrame`.
The ADSL and OCCDS verbs are under `.adam.adsl` and `.adam.occds`.

---

# Quickstart

## 1. SDTM domain from raw data

```python
import fleet
import polars as pl
from fleet.ct import import_codelists

import_codelists()  # metadata/sdtm/codelists.py, made by: fleet init ct
from codelists import SEX

raw = pl.from_repr("""
┌────────────┬─────────┬────────────┐
│ patient_id ┆ sex_raw ┆ birth_date │
│ ---        ┆ ---     ┆ ---        │
│ str        ┆ str     ┆ str        │
╞════════════╪═════════╪════════════╡
│ 001        ┆ M       ┆ 1970-04-15 │
│ 002        ┆ F       ┆ 1985-11-02 │
│ 003        ┆ M       ┆ 1960-07-30 │
└────────────┴─────────┴────────────┘
""")

dm = (
    raw.sdtm.assign("DOMAIN", value="DM")
    .assign("STUDYID", value="MYSTUDY01")
    .assign("USUBJID", source="patient_id")
    .assign("SEX", source="sex_raw", ct=SEX, ct_map={"M": "M", "F": "F"})
    .date("BRTHDTC", source="birth_date")
    .to_frame()
)
```

## 2. ADaM BDS dataset

```python
vs_sdtm = pl.from_repr("""
┌─────────┬──────────┬──────────┬──────────┬────────────┬────────────┐
│ USUBJID ┆ VISITNUM ┆ VSTESTCD ┆ VSSTRESN ┆ VSDTC      ┆ TRTSDT     │
│ ---     ┆ ---      ┆ ---      ┆ ---      ┆ ---        ┆ ---        │
│ str     ┆ i64      ┆ str      ┆ f64      ┆ str        ┆ str        │
╞═════════╪══════════╪══════════╪══════════╪════════════╪════════════╡
│ 001-01  ┆ 1        ┆ SYSBP    ┆ 120.0    ┆ 2024-01-10 ┆ 2024-01-10 │
│ 001-01  ┆ 2        ┆ SYSBP    ┆ 115.0    ┆ 2024-02-10 ┆ 2024-01-10 │
│ 001-01  ┆ 3        ┆ SYSBP    ┆ 118.0    ┆ 2024-03-10 ┆ 2024-01-10 │
└─────────┴──────────┴──────────┴──────────┴────────────┴────────────┘
""")

advs = (
    vs_sdtm.adam.source("USUBJID")
    .assign("PARAMCD", source="VSTESTCD")
    .assign("AVAL", source="VSSTRESN")
    .date("ADT", source="VSDTC")
    .study_day("ADY", date_col="ADT", ref_col="TRTSDT")
    .flag("ABLFL", criteria='pl.col("VISITNUM") == 1', by=["USUBJID", "PARAMCD"])
    .baseline("BASE", aval="AVAL", baseline_flag="ABLFL", by=["USUBJID", "PARAMCD"])
    .chg("CHG", aval="AVAL", base="BASE")
    .pchg("PCHG", aval="AVAL", base="BASE")
    .to_frame()
)
```

## 3. ADSL (one row per subject)

```python
# Exposure rule of the admiral template (ad_adsl.R): a placebo dose of 0 is exposure.
# The SAP decides. Change this if placebo is not coded EXDOSE = 0 with PLACEBO in EXTRT.
treated = (
    '(pl.col("EXDOSE") > 0) | '
    '((pl.col("EXDOSE") == 0) & pl.col("EXTRT").str.to_uppercase().str.contains("PLACEBO"))'
)

adsl = (
    dm_sdtm.adam.adsl.source("USUBJID", "AGE", "SEX")
    .first_date("TRTSDT", from_dataset=ex_sdtm, date_col="EXSTDTC", where=treated)
    .last_date("TRTEDT", from_dataset=ex_sdtm, date_col="EXENDTC", where=treated)
    .duration("TRTDURD", start="TRTSDT", end="TRTEDT")
    .flag("SAFFL", criteria='pl.col("TRTSDT").is_not_null()', false_value="N")
    .count_events("NUMAE", from_dataset=ae_sdtm)
    .to_frame()
)
```

## 4. define.yaml-driven pipeline

Fleet can read a `define.yaml` specification and execute the whole pipeline
without hand-writing verbs:

```python
import polars as pl
import fleet  # noqa: F401

dm = pl.read_parquet("outputs/sdtm/dm.parquet")
ex = pl.read_parquet("outputs/sdtm/ex.parquet")

adsl = (
    dm.adam.pin("EX", ex)
    .from_spec("examples/cdiscpilot01/adam/define.yaml", dataset="ADSL")
    .to_frame()
)
```

`from_spec` is the execution entry point: pin any datasets the spec references
by name, then materialise with `.to_frame()`. See
[How define.yaml works](../concepts/define-yaml.md) for the full spec format.

## 5. Generate Define-XML

One CLI command — inside a study workspace both paths default from
`study_config.yaml` (`--spec`, `--output`, and `--standard sdtm|adam`
override):

```bash
uv run fleet define-xml --standard adam
```

The same generation from Python, for notebooks or custom scripts:

```python
from fleet import DefineSpecGenerator

DefineSpecGenerator("examples/cdiscpilot01/adam/define.yaml").generate(
    "outputs/cdiscpilot01/define_adam.xml"
)
```

## Next steps

- [Quickstart](quickstart.md)
- [Full pipeline walkthrough](../examples/full_pipeline.md)
- [define.yaml concept guide](../concepts/define-yaml.md)
- [API reference](../api/index.md)
