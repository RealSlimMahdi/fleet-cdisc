# TLG from a Spec

One YAML file defines a clinical table; the same file drives the batch
render, the interactive explorer, and the QC trail. This walkthrough takes
the shipped `aet01` (Overview of Adverse Events) spec from definition to
rendered outputs.

## 1. The spec is the table

`examples/tlg_specs/aet01.yaml`, abbreviated — every knob is a plain spec
field:

```yaml
template: aet01                # resolves spec class + df.tlg.ae method
schema_version: 1

adsl_filter: 'pl.col("SAFFL") == "Y"'   # safety population (N and n)

header_rows:
  - label: Subjects with at least one adverse event
  - label: Subjects with at least one serious adverse event
    filter: 'pl.col("AESER") == "Y"'
  - label: Subjects with at least one adverse event leading to discontinuation
    filter: 'pl.col("AEACN") == "DRUG WITHDRAWN"'

statistics: [n_subjects, n_pct]
```

Discover the available templates and their spec schemas from the registry:

```bash
uv run fleet tlg list                 # every registered template
uv run fleet tlg schema aet01         # the spec's JSON Schema (editor validation)
```

## 2. Batch render

Inside a study workspace the datasets and output directory resolve from
`study_config.yaml` — ADAE and ADSL are found by name in the configured
`adam_data` directory and the table lands in the `outputs` directory:

```bash
uv run fleet tlg run examples/tlg_specs/aet01.yaml --format html
```

```text
aet01.yaml → outputs/aet01.html  (aet01, table, 9 rows)
```

Outside a study (or to override), pass paths explicitly:

```bash
uv run fleet tlg run examples/tlg_specs/aet01.yaml \
  --data ADAE=adae.parquet --adsl adsl.parquet --adsl-groupby TRT01A \
  -o out/ --format rtf --rows-per-page 40
```

ADAE holds the arm as `TRTA` and a conformant ADSL holds it as `TRT01A`:
`--adsl-groupby TRT01A` names the ADSL arm for the big N. Without it the
CLI stops and names the flag.

`--format` selects the display format — `html`, `rtf`, `pdf`, or `pptx`
(PDF/PPTX need the `tlg-pdf` / `tlg-pptx` extras).

## 3. The same spec, interactive

Declare degrees of freedom in an `interactive:` block (population presets,
dataset filters, statistics variants) and render **one self-contained HTML
explorer** — no server, every variant pre-computed by the same engine:

```bash
uv run fleet tlg explore examples/tlg_specs/aet01.yaml
```

The batch output is byte-identical to the explorer's default variant, so
there is no second implementation to drift — see
[Interactive Explorer](../concepts/interactive-explorer.md).

## 4. The same spec, from Python

```python
import polars as pl
import fleet.tlg as tlg

adae = pl.read_parquet("data/adam/adae.parquet")
adsl = pl.read_parquet("data/adam/adsl.parquet")

spec = tlg.load_spec("examples/tlg_specs/aet01.yaml")
ard = tlg.run_spec(spec, adae, adsl=adsl)  # Analysis Results Dataset
```

The ARD is a long-format Polars DataFrame holding every computed statistic —
rendering (HTML/RTF/PDF/PPTX) is a separate, display-only step, so QC
compares numbers, not formatting. For ad-hoc summaries without a spec file,
`fleet tlg export --domain ae --format pdf` renders a domain's `t_summary`
directly from the configured datasets.

## Where to go next

- Add the table to a one-file raw-to-render script:
  [R2R Strategy](r2r_strategy.md)
- Sanctioned interactivity and the variant-space limits:
  [Interactive Explorer](../concepts/interactive-explorer.md)
- Dataset (not display) outputs: [Exporting Datasets](../concepts/exports.md)
