# Advanced Patterns

Fleet provides significant flexibility to handle complex clinical trial scenarios that don't fit perfectly into standard CDISC verbs.

## Custom Derivations with Polars Expressions

While Fleet provides verbs like `.study_day()` or `.baseline()`, you will often need custom logic to derive variables specific to a study.

### Simple Inline Derivations

For row-by-row logic or straightforward column math, use the `.derivation()` verb to inject custom [Polars expressions](https://pola.rs/) directly into the pipeline:

```python
import polars as pl

# Custom derivation: categorising age into predefined buckets
adsl = (
    dm.adam.adsl
    # ... other standard verbs
    .derivation(
        "AGEGR1",
        expression=(
            pl.when(pl.col("AGE") < 18).then(pl.lit("<18"))
            .when(pl.col("AGE") <= 65).then(pl.lit("18-65"))
            .otherwise(pl.lit(">65"))
        )
    )
    .to_frame()
)
```

### Complex Multi-Dataset Derivations (Escaping the Pipeline)

For highly complex, advanced logic—such as derivations requiring customized multi-dataset joins, complex rolling window aggregations, or logic that simply cannot be expressed linearly in standard verbs—the recommended pattern is to "escape" the automated pipeline.

Because Fleet is built securely on Polars DataFrames, you can drop out to native Polars, compute your advanced logic, merge it back, and then seamlessly resume your Fleet pipeline.

```python
import polars as pl

# 1. Start by compiling your base ADSL dataset to a Polars DataFrame
# (Assuming you already have adsl base and adverse events dataframes)
base_adsl = ctx.build("ADSL") # Or adsl_pipeline.to_frame()

# 2. Compute complex custom logic using pure Polars (e.g. tracking a multi-step clinical event pattern)
# Here we find patients who had a Severe AE specifically after taking a certain concomitant medication.
complex_events = (
    base_adsl.select(["USUBJID", "TRTSDT"])
    .join(ae_df.filter(pl.col("AESEV") == "SEVERE"), on="USUBJID", how="inner")
    .join(cm_df.filter(pl.col("CMINDC") == "NAUSEA"), on="USUBJID", how="left")
    .group_by("USUBJID")
    .agg([
        pl.when(pl.col("AESTDTC").min() > pl.col("CMSTDTC").min())
          .then(pl.lit("Y"))
          .otherwise(pl.lit("N"))
          .alias("CUSTFL")
    ])
)

# 3. Merge the result natively using Polars
merged_adsl = base_adsl.join(complex_events, on="USUBJID", how="left")

# 4. Jump back into Fleet if you need to finalize any remaining standard derivations or metadata
final_adsl = (
    merged_adsl.adam.adsl
    .derivation("CUSTFL", expression=pl.col("CUSTFL").fill_null("N"))
    .to_frame()
)
```

This pattern ensures you are never bottlenecked by the package API: if you can write it in Polars, you can execute it in Fleet.

## Subclassing Namespaces

If your organisation uses standard proprietary derivations across multiple datasets, you can extend Fleet namespaces by subclassing them.

```python
from fleet.adam.adam_namespace import AdamNamespace
import polars as pl

class CompanyAdamNamespace(AdamNamespace):
    def proprietary_flag(self, target_col: str, condition: str) -> "CompanyAdamNamespace":
        """Re-usable custom flag for your company."""
        expr = pl.when(pl.col(condition) == "Y").then(pl.lit("Y")).otherwise(pl.lit(None))
        return self._add_expr(expr.alias(target_col))

# You can register this as a custom accessor using Polars
@pl.api.register_dataframe_namespace("company_adam")
class _CompanyAdamPolarsAccessor(CompanyAdamNamespace):
    def __init__(self, df: pl.DataFrame):
        super().__init__(df)
```

## Handing Non-CDISC Raw Sources

If you are pulling in non-standard vendor files, use Fleet verbs to rename and map columns directly inside the pipeline. The `.source()` verb (ADaM) and `.assign_no_ct()` verb (SDTM) both accept a `from_col` / `source` keyword to copy a raw column under a CDISC-compliant name — no intermediate Polars `.rename()` call needed:

```python
import polars as pl
from fleet import load_study_context

raw_labs = pl.read_csv("vendor_labs.csv")

# Rename non-standard columns inline using Fleet verbs, then continue derivation
adlb = (
    raw_labs.adam
    .source("USUBJID", from_col="Subject_ID")
    .source("AVAL", from_col="Lab_Result")
    .baseline("BASE", aval="AVAL", baseline_flag="ABLFL")
    .to_frame()
)
```

For SDTM pipelines the equivalent verb is `.assign_no_ct()`:

```python
dm = (
    raw_df.sdtm
    .assign_no_ct("USUBJID", source="subject_id")
    .assign_no_ct("SUBJID", source="subject_id")
    .to_frame()
)
```

Only fall back to raw Polars for pre-processing that genuinely cannot be expressed as a Fleet verb (e.g. pivoting wide vendor files, multi-file concatenation), and re-enter the Fleet pipeline immediately afterwards.

## Pipeline Debugging & Observability

Fleet pipelines are lazy — all derivations accumulate until `.to_frame()` collects the result. This can make it hard to pinpoint which step introduced bad data or types. Two chainable verbs help:

### `.inspect()` — Hard Checkpoint

Materialises the pipeline at that point, prints schema, shape, and first rows, then returns a fresh namespace wrapping the collected frame. The pipeline resumes from this checkpoint.

```python
adsl = (
    dm.adam.adsl
    .source("USUBJID")
    .first_date("TRTSDT", from_dataset=ex, date_col="EXSTDTC")
    .inspect(prefix="After TRTSDT")   # prints and checkpoints
    .duration("TRTDURD", start_date="TRTSDT", end_date="TRTEDT")
    .to_frame()
)
```

### `.explain()` — Query Plan

Prints the Polars logical plan without materialising. Useful for understanding how Polars optimises the accumulated derivation pipeline.

```python
advs = (
    vs_raw.adam
    .source("USUBJID")
    .derivation("AVAL", expression="VSSTRESN")
    .explain()   # shows optimised plan
    .to_frame()
)
```

Both verbs are available on `df.sdtm`, `df.adam`, and all ADaM sub-namespaces.
