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
`href`s, so the metadata always points at the files you actually ship:

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

- **XPT** enforces the SAS v5 Transport constraints for you: column names
  are upper-cased and truncated to 8 characters on write. Install the
  writer with `uv add "fleet-cdisc[io]"`.
- **Dataset-JSON** embeds dataset metadata (`domain`, `label`, originator,
  file OID) alongside typed column data — pass them as keyword arguments.
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

## Not to be confused with TLG render formats

Tables, listings, and graphs render to **display** formats — HTML, RTF,
PDF, PPTX — via `fleet tlg run --format ...`. Those are outputs for humans;
this page covers dataset files for machines and submissions. See
[TLG from a Spec](../examples/tlg_pipeline.md).
