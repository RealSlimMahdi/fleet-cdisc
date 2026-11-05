# Advanced Patterns

Fleet provides significant flexibility to handle complex clinical trial scenarios that don't fit perfectly into standard CDISC verbs.

## Custom Derivations with Polars Expressions

While Fleet provides verbs like `.study_day()` or `.baseline()`, you will often need custom logic to derive variables specific to a study.

### Simple Inline Derivations

For row-by-row logic or straightforward column math, use the `.derivation()` verb. It accepts four forms:

**String expression (YAML-compatible, checked before it runs):**

A string may use Polars expression constructors (`pl.col`, `pl.lit`, `pl.when`, ...), data types and expression methods. Fleet refuses anything else before evaluation: file and module access such as `pl.read_csv`, and methods that take a function or (de)serialise, such as `pipe` and `map_elements`. A `callable:` or `derivations_module:` in a `define.yaml` imports Python code, so review a received spec that holds them as a program.

```python
adsl = dm.adam.adsl.derivation(
    "AGEGR1",
    expression="pl.when(pl.col('AGE') < 65).then(pl.lit('<65 yrs')).otherwise(pl.lit('>=65 yrs'))",
).to_frame()
```

**Direct `pl.Expr` (full Polars power):**

```python
import polars as pl

adsl = dm.adam.adsl.derivation(
    "AGEGR1",
    expression=(
        pl.when(pl.col("AGE") < 18)
        .then(pl.lit("<18"))
        .when(pl.col("AGE") <= 65)
        .then(pl.lit("18-65"))
        .otherwise(pl.lit(">65"))
    ),
).to_frame()
```

**Date differences are durations, not days.** In Polars, `TRTEDT - TRTSDT` gives a Duration, not a number of days as in SAS. In a string expression, `flag`, `case_when` and `derivation` refuse `TRTEDT - TRTSDT > 10` and name the correct form, `(TRTEDT - TRTSDT).dt.total_days() > 10`. A direct `pl.Expr` is not checked: write `(pl.col("TRTEDT") - pl.col("TRTSDT")).dt.total_days()` yourself, or `> 10` compares with 10 microseconds.

**Lambda returning `pl.Expr` (inline, IDE auto-complete, no string sandbox):**

```python
adsl = dm.adam.adsl.derivation(
    "AGEGR1",
    expression=lambda: (
        pl.when(pl.col("AGE") < 65).then(pl.lit("<65 yrs")).otherwise(pl.lit(">=65 yrs"))
    ),
).to_frame()
```

## `@derivation` — File-Based, Lineage-Tracked Derivations

For study-specific logic that should be versioned, reused, and automatically documented in Define-XML, use the `@derivation` decorator. This is the **primary escape-hatch pattern** for anything too complex for a one-liner.

### Two `kind` values

| Kind     | When to use                                 | Signature                            |
| -------- | ------------------------------------------- | ------------------------------------ |
| `column` | Row-by-row expression (no DataFrame needed) | `() -> pl.Expr`                      |
| `frame`  | Multi-column or aggregation logic           | `(df: pl.DataFrame) -> pl.DataFrame` |

**What the function receives and returns:**

- **`column`** — the function takes **no arguments** and returns a
  `pl.Expr`. Fleet splices the expression into the lazy pipeline, so
  nothing is materialised: it behaves exactly like an inline
  `.derivation(expression=...)`, just versioned in its own file. The
  result goes to the column named as the function (`AGEGR1` below). An
  explicit `.alias()` on the expression wins.
- **`frame`** — the `df` parameter is **the pipeline's current state**,
  materialised as a plain `pl.DataFrame` at the point the derivation runs
  (every column derived by earlier verbs is present). The function returns
  a `pl.DataFrame` — usually `df.with_columns(...)` — and Fleet wraps the
  result back into the namespace so the chain continues.

You rarely need to pass `kind=` yourself — it is inferred from the
signature: a return annotation of `pl.Expr` (or a zero-argument function)
means `column`; everything else is `frame`.

A new parameter row, such as BMI from WEIGHT and HEIGHT, is not a
`@derivation`: use `.adam.derive_param()`. `@derivation(by=...,
set_values_to=...)` raises `VerbUsageError`.

### `kind="column"` example

```python
# examples/cdiscpilot01/adam/derivations/AGEGR1.py
from fleet.core.derivation import derivation
import polars as pl


@derivation
def AGEGR1() -> pl.Expr:
    """Classify AGE into pooled age groups for ADSL."""
    return (
        pl.when(pl.col("AGE") < 65).then(pl.lit("<65 yrs")).otherwise(pl.lit(">=65 yrs"))
    ).alias("AGEGR1")
```

Use it directly in a pipeline:

```python
from examples.cdiscpilot01.adam.derivations import AGEGR1

adsl = dm.adam.adsl.derivation(AGEGR1).to_frame()
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

### A new parameter row: `derive_param`

```python
advs = vs.adam.derive_param(
    by=["USUBJID", "ADT"],
    set_values_to={"PARAMCD": "BMI", "PARAM": "Body Mass Index"},
    parameter_filter={"WEIGHT": "WEIGHT", "HEIGHT": "HEIGHT"},
    analysis_value=pl.col("WEIGHT") / (pl.col("HEIGHT") / 100) ** 2,
).to_frame()
```

### Derivations folder convention

Study derivations live under the study's configured programs tree:

```
programs/derivations/       # <programs dir from study_config.yaml>
    __init__.py
    AGEGR1.py
    BMI.py
```

Scaffold a new derivation with the CLI (config-context — run it anywhere
inside the study workspace):

```bash
fleet derivation add AGEGR1 --dataset ADSL --kind column
```

The convention is **standard-agnostic**: the same `@derivation` objects and
`callable:` escape hatch work in SDTM pipelines and specs exactly
as in ADaM — both dispatch through the shared core registry.

### Complex Multi-Dataset Derivations (Escaping the Pipeline)

For highly complex, advanced logic—such as derivations requiring customized multi-dataset joins, complex rolling window aggregations, or logic that simply cannot be expressed linearly in standard verbs—the recommended pattern is to "escape" the automated pipeline.

Because Fleet is built securely on Polars DataFrames, you can drop out to native Polars, compute your advanced logic, merge it back, and then seamlessly resume your Fleet pipeline.

```python
import polars as pl

# 1. Start by compiling your base ADSL dataset to a Polars DataFrame
# (Assuming you already have adsl base and adverse events dataframes)
base_adsl = (
    adsl_pipeline.to_frame()
)  # or dm.adam.from_spec("define.yaml", dataset="ADSL").to_frame()

# 2. Compute complex custom logic using pure Polars (e.g. tracking a multi-step clinical event pattern)
# Here we find patients who had a Severe AE specifically after taking a certain concomitant medication.
complex_events = (
    base_adsl.select(["USUBJID", "TRTSDT"])
    .join(ae_df.filter(pl.col("AESEV") == "SEVERE"), on="USUBJID", how="inner")
    .join(cm_df.filter(pl.col("CMINDC") == "NAUSEA"), on="USUBJID", how="left")
    .group_by("USUBJID")
    .agg(
        [
            pl.when(pl.col("AESTDTC").min() > pl.col("CMSTDTC").min())
            .then(pl.lit("Y"))
            .otherwise(pl.lit("N"))
            .alias("CUSTFL")
        ]
    )
)

# 3. Merge the result natively using Polars
merged_adsl = base_adsl.join(complex_events, on="USUBJID", how="left")

# 4. Jump back into Fleet if you need to finalize any remaining standard derivations or metadata
final_adsl = merged_adsl.adam.adsl.derivation(
    "CUSTFL", expression=pl.col("CUSTFL").fill_null("N")
).to_frame()
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

## Handling Non-CDISC Raw Sources

If you are pulling in non-standard vendor files, rename and map columns
directly inside the pipeline — no intermediate Polars `.rename()` call
needed. **`.assign(target, source=...)` is the canonical rename verb in
both SDTM and ADaM**; the ADaM `.source(*cols)` verb is the variadic
pass-through for carrying already-named columns as-is:

```python
import polars as pl

raw_labs = pl.read_csv("vendor_labs.csv")

# Rename non-standard columns inline, then continue the derivation
adlb = (
    raw_labs.adam.assign("USUBJID", source="Subject_ID")
    .assign("AVAL", source="Lab_Result")
    .baseline("BASE", aval="AVAL", baseline_flag="ABLFL")
    .to_frame()
)
```

Same verb, same spelling in SDTM:

```python
dm = (
    raw_df.sdtm.assign("USUBJID", source="subject_id")
    .assign("SUBJID", source="subject_id")
    .to_frame()
)
```

Only fall back to raw Polars for pre-processing that genuinely cannot be expressed as a Fleet verb (e.g. pivoting wide vendor files, multi-file concatenation), and re-enter the Fleet pipeline immediately afterwards.

## Cross-Domain Derivations with `.pin()`

Many CDISC derivations require data from sibling domains — SDTM study day needs DM's `RFSTDTC`, ADaM datasets need ADSL columns like `TRTSDT` and population flags. Fleet's **Pipeline Passport** (`.pin()`) lets verbs _see_ reference data without polluting the frame.

### Pinning a reference domain

```python
# Build DM first
dm = dm_raw.sdtm.assign("DOMAIN", value="DM").to_frame()  # ...plus the rest of DM

# Pin DM to the VS pipeline — verbs can now resolve RFSTDTC
vs = (
    vs_raw.sdtm.assign("DOMAIN", value="VS")
    .assign("USUBJID", source="patient_number")
    .assign("VSTESTCD", source="vs_test_code")
    .assign("VSORRES", source="vs_result")
    .date("VSDTC", source="vs_date")
    .pin("DM", dm)  # ← attach reference (join_on="USUBJID" by default)
    .study_day("VSDY", date_col="VSDTC")  # ← consumes the pin
    .baseline_flag("VSBLFL", date_col="VSDTC", testcd_col="VSTESTCD")  # ← also consumes it
    .to_frame()
)
```

You don't see `RFSTDTC` in the call because `.study_day()` fills it in from
its **SDTM defaults**: `ref_pin="DM"` and `ref_col="RFSTDTC"` — i.e. "look
up RFSTDTC in the pinned DM, joined on the pin's key". Spelled out in full,
the call above is:

```python
vs_ns.study_day("VSDY", date_col="VSDTC", ref_pin="DM", ref_col="RFSTDTC")
```

On ADaM namespaces the same defaults become `ref_pin="ADSL"` /
`ref_col="TRTSDT"`. Resolution order: an explicit `ref_df=`/`dm=`/`adsl=`
frame wins, then the pinned domain, then a `ref_col` already present in the
frame — and a `LookupError` tells you what to pin when none of those hold.

The pinned DataFrame is **not** merged into the frame — it stays beside it. Verbs borrow what they need, compute, and drop temp columns. The output frame stays clean.

### Multiple pins

You can pin as many domains as you need:

```python
ae = (
    ae_raw.sdtm.pin("DM", dm_df)  # join on USUBJID (default)
    .pin("TV", tv_df, join_on="VISITNUM")  # different join key
    .pin("EX", ex_df, join_on=["USUBJID", "EXTRT"])  # compound key
    .study_day("AESTDY", date_col="AESTDTC")  # ← reads DM.RFSTDTC via the DM pin
    .to_frame()
)
```

Datasets sharing a join key can be declared in one call — the keyword
form mirrors the define.yaml `inputs:` block (kwarg name = dataset name):

```python
adae = (
    ae_df.adam.occds("ADAE")
    .pin(ADSL=adsl_df, EX=ex_df)  # both join on USUBJID (default)
    .join_adsl("TRTSDT", "SAFFL")
    .to_frame()
)
```

Each verb names the pin it consumes (or falls back to its default
`ref_pin`), and the join uses **that pin's** stored `join_on` — so the TV
and EX pins above sit untouched until a visit- or exposure-consuming verb
asks for them.

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
    .pin("ADSL", adsl)  # join_on="USUBJID" unless overridden
    .source("USUBJID")
    .join_adsl("TRTSDT", "TRTEDT", "SAFFL")  # left-join on the ADSL pin's key (USUBJID)
    .study_day("ASTDY", date_col="AESTDTC", ref_col="TRTSDT")
    .to_frame()
)
```

`.join_adsl()` has no `by=` parameter on purpose: the merge key is whatever
the ADSL pin was registered with — `USUBJID` by default, or
`.pin("ADSL", adsl, join_on=["STUDYID", "USUBJID"])` for a compound key —
so the join key is declared once, next to the data it belongs to. The
pin-free alternative `.merge_adsl(adsl, by=["USUBJID"], keep=[...])` takes
an explicit frame and defaults `by=` to `["USUBJID"]`.

### FK validation

When a pin exists, Fleet checks foreign-key integrity at `.to_frame()`: every `USUBJID` of the final frame must be in the pinned `DM` (SDTM) or `ADSL` (ADaM). By default it emits a warning for orphan values; use `.fk_policy()` to make it strict or silent. The check runs once, on the final frame, with the last policy of the chain, so the order of `pin`, `fk_policy` and the verbs does not matter. `VISITNUM`, `VISIT` and `EPOCH` are not checked: an unscheduled visit is a valid value that the trial design does not list.

```python
ae = (
    ae_raw.sdtm.pin("DM", dm)
    .assign("USUBJID", source="patient_number")
    .fk_policy("error")  # raise on FK violations, checked against DM at to_frame()
    .to_frame()
)
```

### Lineage tracing

Every derivation — including cross-domain pin access — is recorded automatically. Print the origin of every derived variable with the `.trail()` verb (detailed in the Observability section below), without breaking the chain:

```python
ae = (
    ae_raw.sdtm.assign("USUBJID", source="patient_number")
    .assign("AESTDTC", source="ae_start_date")
    .pin("DM", dm)
    .study_day("AESTDY", date_col="AESTDTC")
    .trail()  # prints the origin table; pipeline continues
    .to_frame()
)
```

The cross-domain pin is attributed in the `Origin` column as `DM.RFSTDTC`.

## Pipeline Debugging & Observability

Fleet pipelines are lazy — all derivations accumulate until `.to_frame()` collects the result. This can make it hard to pinpoint which step introduced bad data or types — or to see where each variable came from. Three chainable verbs help:

### `.inspect()` — Hard Checkpoint

Materialises the pipeline at that point, prints schema, shape, and first rows, then returns a fresh namespace wrapping the collected frame. The pipeline resumes from this checkpoint.

```python
adsl = (
    dm.adam.adsl.source("USUBJID")
    .first_date("TRTSDT", from_dataset=ex, date_col="EXSTDTC")
    .inspect(prefix="After TRTSDT")  # prints and checkpoints
    .duration("TRTDURD", start="TRTSDT", end="TRTEDT")
    .to_frame()
)
```

### `.explain()` — Query Plan

Prints the Polars logical plan without materialising. Useful for understanding how Polars optimises the accumulated derivation pipeline.

```python
advs = (
    vs_raw.adam.source("USUBJID")
    .derivation("AVAL", expression="VSSTRESN")
    .explain()  # shows optimised plan
    .to_frame()
)
```

### `.trail()` — Variable Origin

Prints a table of every *derived* variable: the verb that produced it and the source columns it consumed, including cross-domain pin sources shown as `DOMAIN.COLUMN`. Nothing is materialised — the trail is metadata captured automatically on every verb — so it can sit anywhere in the chain, though it is most complete just before `.to_frame()`.

```python
ae = (
    ae_raw.sdtm.assign("DOMAIN", value="AE")
    .assign("USUBJID", source="patient_number")
    .assign("AESTDTC", source="ae_start_date")
    .pin("DM", dm)
    .study_day("AESTDY", date_col="AESTDTC")
    .trail()  # prints the table below, pipeline continues
    .to_frame()
)
```

```text
Variable trail (4 derivation(s)):
┌───┬──────────┬────────────────┬─────────────────────┬────────┐
│ # ┆ Variable ┆ Verb           ┆ Origin              ┆ Domain │
╞═══╪══════════╪════════════════╪═════════════════════╪════════╡
│ 1 ┆ DOMAIN   ┆ assign         ┆ (literal)           ┆ —      │
│ 2 ┆ USUBJID  ┆ assign         ┆ patient_number      ┆ AE     │
│ 3 ┆ AESTDTC  ┆ assign         ┆ ae_start_date       ┆ AE     │
│ 4 ┆ AESTDY   ┆ study_day      ┆ AESTDTC, DM.RFSTDTC ┆ AE     │
└───┴──────────┴────────────────┴─────────────────────┴────────┘
```

Variables with no source column (e.g. hardcoded constants) are marked `(literal)`; a variable derived more than once appears once per derivation, in pipeline order. Passthrough columns that no verb touched are not listed.

All three verbs are available on `df.sdtm`, `df.adam`, and all ADaM sub-namespaces.
