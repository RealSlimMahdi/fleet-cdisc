"""Lesson 01 scratch file: an expression is a value.

Run it:
    cd /Users/aboutm/Code/Python/Fleet
    uv run python learn/scratch/lesson01.py

Then change it. The three edits the lesson asks for are marked EDIT 1, 2, 3.
"""

import polars as pl

from fleet.adam.utils import baseline, chg

adlb = pl.from_repr("""
┌─────────┬─────────┬─────────┬───────┬──────┐
│ USUBJID ┆ PARAMCD ┆ AVISITN ┆ ABLFL ┆ AVAL │
│ ---     ┆ ---     ┆ ---     ┆ ---   ┆ ---  │
│ str     ┆ str     ┆ i64     ┆ str   ┆ f64  │
╞═════════╪═════════╪═════════╪═══════╪══════╡
│ S001    ┆ ALT     ┆ 0       ┆ Y     ┆ 30.0 │
│ S001    ┆ ALT     ┆ 1       ┆ null  ┆ 45.0 │
│ S001    ┆ ALT     ┆ 2       ┆ null  ┆ 52.0 │
│ S002    ┆ ALT     ┆ 0       ┆ Y     ┆ 28.0 │
│ S002    ┆ ALT     ┆ 1       ┆ null  ┆ 26.0 │
└─────────┴─────────┴─────────┴───────┴──────┘
""")


def step(n: int, title: str) -> None:
    print(f"\n{'=' * 62}\n  {n}. {title}\n{'=' * 62}")


step(1, "The data")
print(adlb)


step(2, "An expression is a value. Nothing has run.")
chg_expr = pl.col("AVAL") - pl.col("BASE")
print("the object :", chg_expr)
print("its type   :", type(chg_expr).__name__)
# EDIT 3: uncomment. This is exactly what Fleet uses to catch a missing column
# before anything is collected. See _validate_chain_exprs in core/_verb_mixin.py.
# print("reads      :", chg_expr.meta.root_names())
# print("writes     :", chg_expr.meta.output_name())


step(3, "One expression, two contexts, two shapes")
mean_expr = pl.col("AVAL").mean()
# EDIT 1: change .select to .with_columns. Predict the row count first.
# EDIT 2: delete .alias("MEAN"). What is the column called now, and why?
print(adlb.select(mean_expr.alias("MEAN")))
print(adlb.with_columns(mean_expr.alias("MEAN")))


step(4, "Fleet's own expression factories, used directly")
base_expr = baseline("AVAL", "ABLFL", ["USUBJID", "PARAMCD"], "BASE")
chg_expr2 = chg("AVAL", "BASE", "CHG")
print("baseline() returned :", type(base_expr).__name__)
print("chg() returned      :", type(chg_expr2).__name__)
print("\nneither touched the data. now give them a context:\n")
print(adlb.with_columns(base_expr).with_columns(chg_expr2))


step(5, "Why .max() is in baseline(): nulls are skipped")
masked = pl.when(pl.col("ABLFL") == "Y").then(pl.col("AVAL")).otherwise(None)
print("after when/then/otherwise, only the baseline row survives:")
print(adlb.select("USUBJID", "ABLFL", "AVAL").with_columns(masked.alias("masked")))
print("max() of one value and some nulls is that one value:")
print(pl.DataFrame({"x": [None, None, 7.0]}).select(pl.col("x").max()))


step(6, "The same thing through the Fleet verb chain")
# Nothing is computed until .to_frame(). Everything before it extends a lazy plan.
result = adlb.adam.baseline("BASE", aval="AVAL", baseline_flag="ABLFL").chg("CHG").to_frame()
print(result)
