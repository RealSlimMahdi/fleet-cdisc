"""Standard ADaM statistical function implementations."""

from __future__ import annotations

import polars as pl


def study_day(analysis_date: str, reference_date: str, target: str = "ADY") -> pl.Expr:
    """
    Compute study day: (ADT - TRTSDT) with day 1 = reference date.

    Study day is 1-based: day 0 is mapped to day -1 (pre-treatment).
    """
    expr = (
        pl.col(analysis_date).cast(pl.Date) - pl.col(reference_date).cast(pl.Date)
    ).dt.total_days()

    # CDISC convention: no day 0; positive days +1, negative days unchanged
    return (
        pl.when(expr >= 0)
        .then(expr + 1)
        .otherwise(expr)
        .cast(pl.Int64)
        .alias(target)
    )


def baseline(
    aval: str,
    baseline_flag_col: str = "ABLFL",
    group_by: list[str] | None = None,
    target: str = "BASE",
) -> pl.Expr:
    """
    Compute BASE as the AVAL at the baseline record (where ABLFL == "Y").

    Uses a window function so all records in the same subject/parameter get
    the same baseline value.
    """
    groups = group_by or ["USUBJID", "PARAMCD"]
    base_expr = (
        pl.when(pl.col(baseline_flag_col) == "Y")
        .then(pl.col(aval))
        .otherwise(None)
        .max()
        .over(groups)
        .alias(target)
    )
    return base_expr


def chg(aval: str = "AVAL", base: str = "BASE", target: str = "CHG") -> pl.Expr:
    """Change from baseline: CHG = AVAL - BASE."""
    return (pl.col(aval) - pl.col(base)).alias(target)


def pchg(aval: str = "AVAL", base: str = "BASE", target: str = "PCHG") -> pl.Expr:
    """Percent change from baseline: PCHG = (AVAL - BASE) / BASE * 100."""
    return (
        pl.when(pl.col(base).is_not_null() & (pl.col(base) != 0))
        .then((pl.col(aval) - pl.col(base)) / pl.col(base) * 100)
        .otherwise(None)
        .alias(target)
    )


def flag_baseline(
    criteria_expr: pl.Expr,
    group_by: list[str] | None = None,
    target: str = "ABLFL",
) -> pl.Expr:
    """
    Flag the baseline record within each group using *criteria_expr*.

    Typically: earliest pre-treatment measurement.
    Returns "Y" for the baseline record, null otherwise.
    """
    groups = group_by or ["USUBJID", "PARAMCD"]
    # Row index within group (use pl.int_range over groups to find first hit)
    is_baseline = criteria_expr
    ranked = (
        pl.when(is_baseline)
        .then(pl.lit("Y"))
        .otherwise(pl.lit(None))
        .alias(target)
    )
    return ranked


def bmi(weight: str = "weight_kg", height: str = "height_cm", target: str = "BMI") -> pl.Expr:
    """BMI = weight_kg / (height_m^2). Height input assumed in cm."""
    height_m = pl.col(height) / 100.0
    return (pl.col(weight) / (height_m * height_m)).round(1).alias(target)


def nrind(value: str, low: str, high: str, target: str = "NRIND") -> pl.Expr:
    """Normal range indicator: LOW / NORMAL / HIGH."""
    return (
        pl.when(pl.col(value) < pl.col(low)).then(pl.lit("LOW"))
        .when(pl.col(value) > pl.col(high)).then(pl.lit("HIGH"))
        .otherwise(pl.lit("NORMAL"))
        .alias(target)
    )


def on_treatment(adt: str, trtsdt: str, trtedt: str, target: str = "ONTRTFL") -> pl.Expr:
    """ONTRTFL = "Y" when ADT is on or between TRTSDT and TRTEDT (inclusive)."""
    return (
        pl.when(
            (pl.col(adt).cast(pl.Date) >= pl.col(trtsdt).cast(pl.Date))
            & (pl.col(adt).cast(pl.Date) <= pl.col(trtedt).cast(pl.Date))
        )
        .then(pl.lit("Y"))
        .otherwise(pl.lit(None))
        .alias(target)
    )


def shift(baseline_cat: str, post_cat: str, target: str = "SHIFT1", sep: str = " to ") -> pl.Expr:
    """Categorical shift string: "<baseline_cat> to <post_cat>"."""
    return (pl.col(baseline_cat) + pl.lit(sep) + pl.col(post_cat)).alias(target)
