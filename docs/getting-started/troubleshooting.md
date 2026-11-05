# Troubleshooting Guide

When you build SDTM or ADaM pipelines in Fleet, an error comes from the data or from the pipeline code. This page shows the common messages, what they mean and how to fix them.

## Common Errors

### `UserWarning: ... contains values not in codelist ...`

**What it means:** `.assign(ct=...)` found values that are not submission terms of the codelist. It is a warning, not an error. The pipeline continues and writes the values as they are:

```text
SEX: column 'sex' contains values not in codelist 'C66731': ['Q']. Valid values: ['F', 'INTERSEX', 'M', 'U']. Consider providing a ct_map parameter.
```

**How to fix it:**

1. Look at the raw values: `df.select("raw_column").unique()`.
2. Add the missing raw value to `ct_map={...}`. A raw value that is not in `ct_map` is kept as text, as SAS `PUT` with no `OTHER=` keeps it.
3. Or correct the data upstream.

To make warnings stop the run while you develop, use `warnings.simplefilter("error")`.

### `DerivationError: ... column '...' not found in the frame`

**What it means:** A verb reads a column that is not in the frame yet. For example, `chg` reads `AVAL` and `BASE` before you derive them:

```text
chg('CHG'): column 'AVAL' not found in the frame. Available columns: ['patient_id', 'sex_raw']
```

`DerivationError` is a `FleetError` and a `ValueError`. The message names the verb and the columns that are available.

**How to fix it:**
Order matters in a Fleet pipeline. Derive a variable _before_ the verbs that read it. For example, `.source("AVAL")` must come before `.baseline(aval="AVAL", ...)`.

### `SpecError: ... unknown algorithm '...'`

**What it means:** In a spec-driven pipeline, an `algorithm:` in `define.yaml` is not a verb name:

```text
define.yaml → dataset ADSL → variable X: unknown algorithm 'asign' for the adam spec path. Did you mean 'assign'? Pass strict=False to warn and skip instead.
```

**How to fix it:**
Use the verb name that the message suggests, or one from the [Namespace Pipeline](../concepts/pipeline.md) tables. An editor that reads the JSON Schema (`define_spec_schema.json`) marks an unknown algorithm before you run the pipeline. See [Validating `define.yaml`](#validating-defineyaml) below.

## Debugging Lazy Evaluation

Each verb adds one step to the plan of one Polars LazyFrame. Nothing runs until `.to_frame()`. So a stack trace can point to `.to_frame()` and not to the verb that caused the problem.

Two chainable verbs show the pipeline before it runs:

- `.explain()` prints the Polars query plan.
- `.trail()` prints one row per derived variable: the verb and the origin.

```python
import polars as pl

import fleet

dm = pl.from_repr("""
┌────────────┐
│ patient_id │
│ ---        │
│ str        │
╞════════════╡
│ P1         │
└────────────┘
""")

pipeline = dm.sdtm.assign("DOMAIN", value="DM").assign("USUBJID", source="patient_id")

pipeline.explain()
#  WITH_COLUMNS:
#  ["DM".alias("DOMAIN"), col("patient_id").alias("USUBJID")]
#   DF ["patient_id"]; PROJECT */1 COLUMNS
pipeline.trail()
# Variable trail (2 derivation(s)):
# │ 1 ┆ DOMAIN  ┆ assign ┆ (literal)  ┆ — │
# │ 2 ┆ USUBJID ┆ assign ┆ patient_id ┆ DM │
```

You can also stop the chain early and look at the intermediate frame:

```python
debug_df = (
    dm.sdtm.assign("DOMAIN", value="DM")
    # .assign("SEX", source="sex_raw", ct=...)  <-- commented out to isolate the bug
    .to_frame()
)
print(debug_df.head())
```

## Validating `define.yaml`

If you are using the spec-driven approach, validate your `define.yaml` file against the Fleet schema _before_ running pipelines. This ensures you don't waste time tracing runtime errors that are actually typos in the specification.

The [Fleet VS Code extension](https://github.com/RealSlimMahdi/fleet-vscode) does this with no setup: `fleet lsp` loads the schema from the installed package, so it can never drift from the Fleet that runs your pipeline.

Without the extension, a generic YAML language server can read the same schema from a comment at the top of the file:

```yaml
# yaml-language-server: $schema=<path to define_spec_schema.json>
```

`fleet init define` prints that line with the path already resolved against your install. Scaffolded specs no longer carry it by default, because running both validators reports every schema error twice.
