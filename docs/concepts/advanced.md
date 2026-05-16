# Advanced Patterns

Fleet provides significant flexibility to handle complex clinical trial scenarios that don't fit perfectly into standard CDISC verbs.

## Custom Derivations with Polars Expressions

While Fleet provides verbs like `.study_day()` or `.baseline()`, you will often need custom logic to derive variables specific to a study.

### Simple Inline Derivations

For row-by-row logic or straightforward column math, use the `.derivation()` verb. It accepts four forms:

**String expression (YAML-compatible, AST-sandboxed):**

```python
adsl = (
    dm.adam.adsl
    .derivation("AGEGR1", expression="pl.when(pl.col('AGE') < 65).then(pl.lit('<65 yrs')).otherwise(pl.lit('>=65 yrs'))")
    .to_frame()
)
```

**Direct `pl.Expr` (full Polars power):**

```python
import polars as pl

adsl = (
    dm.adam.adsl
    .derivation(
        "AGEGR1",
        expression=(
            pl.when(pl.col("AGE") < 18).then(pl.lit("<18"))
            .when(pl.col("AGE") <= 65).then(pl.lit("18-65"))
            .otherwise(pl.lit(">65"))
        ),
    )
    .to_frame()
)
```

**Lambda returning `pl.Expr` (inline, IDE auto-complete, no string sandbox):**

```python
adsl = (
    dm.adam.adsl
    .derivation("AGEGR1", expression=lambda: (
        pl.when(pl.col("AGE") < 65).then(pl.lit("<65 yrs"))
        .otherwise(pl.lit(">=65 yrs"))
    ))
    .to_frame()
)
```

## `@derivation` — File-Based, Lineage-Tracked Derivations

For study-specific logic that should be versioned, reused, and automatically documented in Define-XML, use the `@derivation` decorator. This is the **primary escape-hatch pattern** for anything too complex for a one-liner.

### Three `kind` values

| Kind     | When to use                                  | Signature                                                       |
| -------- | -------------------------------------------- | --------------------------------------------------------------- |
| `column` | Row-by-row expression (no DataFrame needed)  | `() -> pl.Expr`                                                 |
| `frame`  | Multi-column or aggregation logic            | `(df: pl.DataFrame) -> pl.DataFrame`                            |
| `param`  | By-group reshape (e.g. tall/narrow BDS rows) | `(df: pl.DataFrame) -> pl.DataFrame` + `by=` / `set_values_to=` |

### `kind="column"` example

```python
# specs/cdiscpilot01/adam/derivations/AGEGR1.py
from fleet.core.derivation import derivation
import polars as pl

@derivation
def AGEGR1() -> pl.Expr:
    """Classify AGE into pooled age groups for ADSL."""
    return (
        pl.when(pl.col("AGE") < 65)
        .then(pl.lit("<65 yrs"))
        .otherwise(pl.lit(">=65 yrs"))
    ).alias("AGEGR1")
```

Use it directly in a pipeline:

```python
from specs.cdiscpilot01.adam.derivations import AGEGR1

adsl = (
    dm.adam.adsl
    .derivation(AGEGR1)
    .to_frame()
)
```

### `kind="frame"` example

```python
@derivation(targets=["SAFFL", "ITTFL"])
def add_pop_flags(df: pl.DataFrame) -> pl.DataFrame:
    """Add SAFFL and ITTFL population flags."""
    return df.with_columns(
        pl.lit("Y").alias("SAFFL"),
        pl.lit("Y").alias("ITTFL"),
    )
```

### `kind="param"` example

```python
@derivation(
    by=["USUBJID", "ADT"],
    set_values_to={"PARAMCD": "BMI", "PARAM": "Body Mass Index"},
)
def BMI(df: pl.DataFrame) -> pl.DataFrame:
    """Compute BMI per subject visit."""
    return df.with_columns(
        (pl.col("WEIGHT") / (pl.col("HEIGHT") / 100) ** 2).alias("AVAL")
    )
```

### Derivations folder convention

Study derivations live under:

```
specs/<study_id>/adam/derivations/
    __init__.py        # auto-updated by `fleet derivation add`
    AGEGR1.py
    BMI.py
```

Scaffold a new derivation with the CLI:

```bash
fleet derivation add AGEGR1 --dataset ADSL --kind column
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
from fleet.adam.namespace import AdamNamespace
import polars as pl

class CompanyAdamNamespace(AdamNamespace):
    def proprietary_flag(self, target_col: str, condition: str) -> "CompanyAdamNamespace":
        """Re-usable custom flag for your company."""
        expr = pl.when(pl.col(condition) == "Y").then(pl.lit("Y")).otherwise(pl.lit(None))
        return self._chain(expr.alias(target_col))

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

## Cross-Domain Derivations with `.pin()`

Many CDISC derivations require data from sibling domains — SDTM study day needs DM's `RFSTDTC`, ADaM datasets need ADSL columns like `TRTSDT` and population flags. Fleet's **Pipeline Passport** (`.pin()`) lets verbs _see_ reference data without polluting the frame.

### Pinning a reference domain

```python
# Build DM first
dm = dm_raw.sdtm.hardcode_no_ct("DOMAIN", value="DM") ...  .to_frame()

# Pin DM to the AE pipeline — verbs can now resolve RFSTDTC
ae = (
    ae_raw.sdtm
    .hardcode_no_ct("DOMAIN", value="AE")
    .assign_no_ct("USUBJID", source="patient_number")
    .date("AESTDTC", source="ae_start_date")
    .pin("DM", dm)                                      # ← attach reference
    .study_day("AESTDY", date_col="AESTDTC")            # ← consumes the pin
    .baseline_flag("AEBLFL", date_col="AESTDTC")        # ← also consumes it
    .to_frame()
)
```

The pinned DataFrame is **not** merged into the frame — it stays beside it. Verbs borrow what they need, compute, and drop temp columns. The output frame stays clean.

### Multiple pins

You can pin as many domains as you need:

```python
ae = (
    ae_raw.sdtm
    .pin("DM", dm_df)                                # join on USUBJID (default)
    .pin("TV", tv_df, join_on="VISITNUM")            # different join key
    .pin("EX", ex_df, join_on=["USUBJID", "EXTRT"]) # compound key
    .study_day("AESTDY", date_col="AESTDTC")        # uses DM pin
    .to_frame()
)
```

### Inspecting pins

```python
ae_ns = ae_raw.sdtm.pin("DM", dm).pin("TV", tv, join_on="VISITNUM")
ae_ns.pins()
# {'DM': {'df': ..., 'join_on': ['USUBJID']},
#  'TV': {'df': ..., 'join_on': ['VISITNUM']}}
```

### ADaM: `.join_adsl()` and `.study_day()`

For ADaM datasets, pin ADSL and use `.join_adsl()` to carry forward columns, and `.study_day()` with the ADaM-standard default (`TRTSDT`):

```python
adae = (
    ae_df.adam.occds("ADAE")
    .pin("ADSL", adsl)
    .source("USUBJID")
    .join_adsl("TRTSDT", "TRTEDT", "SAFFL")             # carry forward from ADSL
    .study_day("ASTDY", date_col="AESTDTC", ref_col="TRTSDT")
    .to_frame()
)
```

### FK validation

When a pin exists, Fleet can automatically check foreign-key integrity. By default it emits warnings for orphan values; use `.fk_policy()` to make it strict or silent:

```python
ae = (
    ae_raw.sdtm
    .pin("DM", dm)
    .fk_policy("error")                                  # raise on FK violations
    .assign_no_ct("USUBJID", source="patient_number")   # FK auto-checked vs DM
    .to_frame()
)
```

### Lineage tracing

Every pin access is recorded. After building a pipeline, inspect pin lineage:

```python
from fleet.core.lineage import pin_lineage_of

for dep in pin_lineage_of(ae_ns):
    print(f"{dep.target_col} ← {dep.source_domain}.{dep.source_cols} via {dep.verb}")
# AESTDY ← DM.['RFSTDTC'] via study_day
```

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
