# Troubleshooting Guide

When building SDTM or ADaM pipelines in Fleet, you may encounter errors either from data mismatches or pipeline syntax. This guide will help you understand common errors and debug effectively.

## Common Errors

### `CTError: Invalid value for codelist...`

**What it means:** A value in your source data does not match the expected Controlled Terminology mappings for a variable derived using `.assign(ct=...)`.

**How to fix it:**

1. Check the raw values using Polars: `df.select("raw_column").unique()`.
2. Compare those values to the mapping dictionary provided in `.assign(ct_map={...})`.
3. Add the missing key -> value pair, or fix upstream data collection errors.

### `ColumnNotFoundError` from Polars

**What it means:** You are attempting to derive a variable that depends on a column not yet present in the pipeline (e.g. asking for `AVAL` before it has been sourced or derived).

**How to fix it:**
Order matters in a Fleet pipeline! Make sure that a dependency variable is derived _before_ subsequent verbs that rely on it. For example, `.source("AVAL")` must appear before `.baseline(aval="AVAL", ...)`

### `ValueError: Unknown algorithm in define.yaml`

**What it means:** In a spec-driven pipeline, your `define.yaml` uses an algorithm name under a `derivation` block that doesn't match any recognised namespace verbs.

**How to fix it:**
Check your spelling against the supported lists of verbs in the [Namespace Pipeline](../concepts/pipeline.md) or the API Reference. The JSON Schema (`define_spec_schema.json`) enforces a strict `enum` of valid algorithm names — if you include the `# yaml-language-server: $schema=...` directive at the top of your YAML file, your editor will flag invalid algorithms and empty `derivation: {}` blocks before you even run the pipeline.

## Debugging Lazy Evaluation

Because Fleet builds pipelines conceptually and executes them lazily via Polars, a python stack trace might sometimes point to `.to_frame()` rather than the specific verb that caused an issue.

To inspect what expressions have been queued up before running:

```python
pipeline = dm.sdtm.assign("DOMAIN", value="DM").assign("USUBJID", source="patient_id")

# Inspect the underlying Polars Expressions
print(pipeline._exprs)
```

You can also comment out `.to_frame()` and print intermediate outputs to verify your structure step-by-step.

```python
# To debug an intermediate state, truncate the pipeline:
debug_df = (
    dm.sdtm.assign("DOMAIN", value="DM")
    # .assign("SEX", source="sex_raw", ct=...)  <-- Commented out to isolate the bug
    .to_frame()
)
print(debug_df.head())
```

## Validating `define.yaml`

If you are using the spec-driven approach, validate your `define.yaml` file against the Fleet schema _before_ running pipelines. This ensures you don't waste time tracing runtime errors that are actually typos in the specification.

If you have configured the schema comment in your YAML file:

```yaml
# yaml-language-server: $schema=../../../src/fleet/define_xml/schemas/define_spec_schema.json
```

Your editor (like VS Code) should highlight structural or naming errors automatically.
