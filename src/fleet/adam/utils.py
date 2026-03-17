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
    return pl.when(expr >= 0).then(expr + 1).otherwise(expr).cast(pl.Int64).alias(target)


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
    ranked = pl.when(is_baseline).then(pl.lit("Y")).otherwise(pl.lit(None)).alias(target)
    return ranked


def bmi(weight: str = "weight_kg", height: str = "height_cm", target: str = "BMI") -> pl.Expr:
    """BMI = weight_kg / (height_m^2). Height input assumed in cm."""
    height_m = pl.col(height) / 100.0
    return (pl.col(weight) / (height_m * height_m)).round(1).alias(target)


def nrind(value: str, low: str, high: str, target: str = "NRIND") -> pl.Expr:
    """Normal range indicator: LOW / NORMAL / HIGH."""
    return (
        pl.when(pl.col(value) < pl.col(low))
        .then(pl.lit("LOW"))
        .when(pl.col(value) > pl.col(high))
        .then(pl.lit("HIGH"))
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


# ------------------------------------------------------------------ #
# Admiral-parity: Body Surface Area                                    #
# ------------------------------------------------------------------ #


def bsa(
    weight: str = "WEIGHT",
    height: str = "HEIGHT",
    *,
    method: str = "Mosteller",
    target: str = "BSA",
) -> pl.Expr:
    """
    Body Surface Area (m²).

    Supported *method* values:

    - ``"Mosteller"`` (default): ``sqrt(height_cm * weight_kg / 3600)``
    - ``"DuBois"``: ``0.007184 * height_cm^0.725 * weight_kg^0.425``
    - ``"Haycock"``: ``0.024265 * height_cm^0.3964 * weight_kg^0.5378``
    - ``"Gehan-George"``: ``0.0235 * height_cm^0.42246 * weight_kg^0.51456``
    """
    h = pl.col(height).cast(pl.Float64)
    w = pl.col(weight).cast(pl.Float64)
    method_lower = method.lower()
    if method_lower == "mosteller":
        expr = (h * w / 3600.0).sqrt()
    elif method_lower == "dubois":
        expr = 0.007184 * h.pow(0.725) * w.pow(0.425)
    elif method_lower == "haycock":
        expr = 0.024265 * h.pow(0.3964) * w.pow(0.5378)
    elif method_lower in ("gehan-george", "gehan_george"):
        expr = 0.0235 * h.pow(0.42246) * w.pow(0.51456)
    else:
        raise ValueError(
            f"Unknown BSA method '{method}'. Supported: Mosteller, DuBois, Haycock, Gehan-George."
        )
    return expr.round(4).alias(target)


# ------------------------------------------------------------------ #
# Admiral-parity: Mean Arterial Pressure                              #
# ------------------------------------------------------------------ #


def mean_arterial_pressure(
    systolic: str = "SYSBP",
    diastolic: str = "DIABP",
    *,
    target: str = "MAP",
) -> pl.Expr:
    """
    Mean Arterial Pressure: ``MAP = DBP + (SBP - DBP) / 3``.
    """
    sbp = pl.col(systolic).cast(pl.Float64)
    dbp = pl.col(diastolic).cast(pl.Float64)
    return (dbp + (sbp - dbp) / 3.0).round(2).alias(target)


# ------------------------------------------------------------------ #
# Admiral-parity: Corrected QT interval                               #
# ------------------------------------------------------------------ #


def qtc(
    qt: str = "QT",
    rr: str = "RR",
    *,
    method: str = "Fridericia",
    target: str = "QTC",
) -> pl.Expr:
    """
    Corrected QT interval.

    Supported *method* values:

    - ``"Fridericia"`` (default): ``QT / RR^(1/3)``
    - ``"Bazett"``: ``QT / RR^(1/2)``

    *QT* is in ms; *RR* is in seconds.
    """
    qt_col = pl.col(qt).cast(pl.Float64)
    rr_col = pl.col(rr).cast(pl.Float64)
    method_lower = method.lower()
    if method_lower == "fridericia":
        expr = qt_col / rr_col.pow(1.0 / 3.0)
    elif method_lower == "bazett":
        expr = qt_col / rr_col.sqrt()
    else:
        raise ValueError(f"Unknown QTc method '{method}'. Supported: Fridericia, Bazett.")
    return expr.round(2).alias(target)


# ------------------------------------------------------------------ #
# Admiral-parity: Age in years (unit-aware)                            #
# ------------------------------------------------------------------ #


def age_in_years(
    age_col: str = "AGE",
    age_unit_col: str = "AGEU",
    *,
    target: str = "AAGE",
) -> pl.Expr:
    """
    Convert age to years, handling common unit strings.

    Recognises *AGEU* values: ``YEARS``, ``MONTHS``, ``WEEKS``, ``DAYS``
    (case-insensitive).  Unknown units return null.
    """
    age = pl.col(age_col).cast(pl.Float64)
    unit = pl.col(age_unit_col).str.to_uppercase()
    return (
        pl.when(unit == "YEARS")
        .then(age)
        .when(unit == "MONTHS")
        .then(age / 12.0)
        .when(unit == "WEEKS")
        .then(age / 52.1775)
        .when(unit == "DAYS")
        .then(age / 365.25)
        .otherwise(None)
        .round(1)
        .alias(target)
    )


# ------------------------------------------------------------------ #
# Admiral-parity: Extreme flags (min / max)                            #
# ------------------------------------------------------------------ #


def extreme_flag(
    value_col: str = "AVAL",
    *,
    mode: str = "max",
    groups: list[str] | None = None,
    target: str = "ANL01FL",
) -> pl.Expr:
    """
    Flag the record(s) with the extreme (max or min) value per group.

    Returns ``"Y"`` for records matching the extreme, null otherwise.

    *mode*: ``"max"`` or ``"min"``.
    """
    grps = groups or ["USUBJID", "PARAMCD"]
    val = pl.col(value_col)
    if mode == "max":
        extreme = val.max().over(grps)
    elif mode == "min":
        extreme = val.min().over(grps)
    else:
        raise ValueError(f"extreme_flag mode must be 'max' or 'min', got '{mode}'.")
    return pl.when(val == extreme).then(pl.lit("Y")).otherwise(pl.lit(None)).alias(target)
