# Advanced Patterns

Fleet provides significant flexibility to handle complex clinical trial scenarios that don't fit perfectly into standard CDISC verbs.

## Custom Derivations with Polars Expressions

While Fleet provides verbs like `.study_day()` or `.baseline()`, you will often need custom logic to derive variables specific to a study.

You can use the `.derivation()` verb to inject custom [Polars expressions](https://pola.rs/) into the pipeline.

```python
import polars as pl

# Custom derivation: categorising age into predefined buckets
adsl = (
    dm.adam.adsl
    ...
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

If you are pulling in non-standard vendor files, use raw Polars filtering or renaming _before_ jumping into a Fleet pipeline:

```python
import polars as pl
from fleet import load_study_context

# 1. Standard Polars data cleaning to get it into a reasonable shape
raw_labs = pl.read_csv("vendor_labs.csv")
cleaned_labs = raw_labs.rename({"Subject_ID": "USUBJID", "Lab_Result": "AVAL"})

# 2. Transition into Fleet for formal CDISC derivation
adlb = (
    cleaned_labs.adam
    .source("USUBJID")
    .source("AVAL")
    .baseline("BASE", aval="AVAL", baseline_flag="ABLFL")
    .to_frame()
)
```
