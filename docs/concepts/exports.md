# Exporting Datasets

Fleet writes datasets in three formats, selected the same way everywhere —
one `--format` flag on the CLI, one `output_format:` key in the spec, one
writer function per format in Python.

| Format | File | When to use | Requires |
| --- | --- | --- | --- |
| **Parquet** (default) | `.parquet` | Working format: fast, typed, compressed; ideal between pipeline steps and for QC | — |
| **SAS XPT (v5 Transport)** | `.xpt` | Regulatory submission datasets; SAS interop | `io` extra (`pyreadstat`) |
| **CDISC Dataset-JSON v1.1** | `.json` | The emerging submission exchange format; typed, metadata-rich | — |

## From the CLI

Every dataset-writing command takes the same flag and resolves its output
directory from `study_config.yaml`:

```bash
uv run fleet run --format xpt                 # define.yaml pipelines → <sdtm_data>/<adam_data>
uv run fleet run --format dataset-json --dataset ADSL
uv run fleet tdd build --format xpt           # trial design domains → <sdtm_data>
```

## From the spec (`output_format:`)

Declare the format once in `define.yaml` — per dataset or spec-wide. The
choice is recorded in the pipeline DAG and drives the Define-XML leaf
`href`s. `fleet run` writes each dataset in the same format: `--format`,
else the dataset's `output_format:`, else the spec's, else parquet. A
`--format` that differs from the define warns, and `fleet define-xml` warns
when a leaf names a file that the data folder does not hold. `output:`
names the leaf `href` only; `fleet run` warns when it writes another file
name:

```yaml
output_format: parquet          # spec-level default
datasets:
  - name: ADSL
    output_format: xpt          # per-dataset override
```

## From Python

```python
from fleet import save_parquet, save_dataset_json
from fleet.io import save_xpt

save_parquet(adsl, Path("data/adam/adsl.parquet"))
save_xpt(adsl, Path("data/adam/adsl.xpt"))
save_dataset_json(
    adsl, "data/adam/adsl.json", domain="ADSL", label="Subject-Level Analysis Dataset"
)
```

Format-specific behaviour worth knowing:

- **XPT** is SAS transport version 5, the submission format of FDA TCG
  3.1.1, and the member is named as the file (`adsl.xpt` holds `ADSL`).
  Names are upper-cased. A `pl.Date` is stored as a SAS date with DATE9, a
  `pl.Datetime` with DATETIME20 and a `pl.Time` with TIME8. NaN and infinity
  become SAS missing. Nothing is cut: a name over 8 characters, a label over
  40 or a value over 200 bytes stops the write. A value that is not ASCII is
  written as UTF-8 bytes, with a warning. Pass `label=` and `column_labels=`
  for the dataset and variable labels; `fleet run` takes them from
  `define.yaml`. Install the writer with `uv add "fleet-cdisc[io]"`.
- **Dataset-JSON** embeds dataset metadata (`domain`, `label`, originator,
  file OID) alongside typed column data. Pass `columns=` for the variable
  labels, lengths and key sequence, and `study_oid=` and
  `metadata_version_oid=` for the define. `fleet run` and `to_dataset_json`
  after `from_spec` take them from `define.yaml`. Each `itemOID` is the
  ItemDef OID of the Define-XML. A `pl.Date`, `pl.Datetime` or `pl.Time` is
  written with `targetDataType: integer` and DATE9., DATETIME20. or TIME8.,
  so `read_dataset_json` gives the date back. NaN and infinity are written
  as null, with a warning, because JSON has no such number. A duration
  column stops the write: convert it to a number first.
  `read_dataset_json` reads `float` and `decimal` as `pl.Float64`, as SAS
  holds them, and an integer written as `63.0` as 63.
- **Parquet** forwards any keyword arguments to Polars'
  `write_parquet` (compression, statistics, ...).

## Reading

The mirror-image loaders auto-detect format from the extension — CSV,
Parquet, XPT, and SAS7BDAT all land as LazyFrames:

```python
from fleet import load_raw_data, load_datasets

dm_raw = load_raw_data("data/raw/dm_raw.csv")  # one file → LazyFrame
frames = load_datasets(
    {"DM": "data/sdtm/dm.parquet", "AE": "data/sdtm/ae.xpt"}  # many files → dict
)
```

What the readers decide for you:

- **A SAS blank is a missing value.** SAS has one character missing value,
  the blank, so a blank in an XPT or SAS7BDAT file reads as null and
  `is_null()` finds it. A variable with no value keeps its SAS type.
- **A CSV file holds no types.** Polars infers them from every row. A column
  with a leading zero (SITEID `001`) stays text, with a warning, because a
  number would lose the zero. `schema_overrides={"LBORRES": pl.String}` is
  the `$` informat; your types always win. `fleet run` reads the variables
  of define type `text`, and their raw source columns, as text.
- **The encoding is yours to name.** A file from a WLATIN1 SAS session needs
  `load_raw_data(path, encoding="iso-8859-1")`, or `--encoding iso-8859-1` on
  `fleet compare` and `fleet validate`. A keyword the reader does not take
  raises; it is never dropped.

In a join on keys a missing key matches a missing key, as SAS MERGE BY does,
in every verb that joins (`merge`, `pick`, `first_date`, `derive_param`, ...).

## Not to be confused with TLG render formats

Tables, listings, and graphs render to **display** formats — HTML, RTF,
PDF, PPTX — via `fleet tlg run --format ...`. Those are outputs for humans;
this page covers dataset files for machines and submissions. See
[TLG from a Spec](../examples/tlg_pipeline.md).
