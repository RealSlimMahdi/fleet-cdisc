"""Standard ADaM statistical function implementations."""

from __future__ import annotations

import re

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


def on_treatment(
    adt: str,
    trtsdt: str,
    trtedt: str,
    target: str = "ONTRTFL",
    *,
    open_ended: bool = True,
) -> pl.Expr:
    """ONTRTFL = "Y" when ADT is on or between TRTSDT and TRTEDT (inclusive).

    When *open_ended* is ``True`` (default) and TRTEDT is null the interval
    is treated as ongoing — ``adt >= trtsdt`` is sufficient for "Y".
    """
    adt_d = pl.col(adt).cast(pl.Date)
    start_d = pl.col(trtsdt).cast(pl.Date)
    end_d = pl.col(trtedt).cast(pl.Date)

    on_trt = (adt_d >= start_d) & (adt_d <= end_d)
    if open_ended:
        on_trt = on_trt | (end_d.is_null() & (adt_d >= start_d))

    return pl.when(on_trt).then(pl.lit("Y")).otherwise(pl.lit(None)).alias(target)


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
# Partial-date imputation helpers (vectorised)                         #
# ------------------------------------------------------------------ #

# ISO 8601 date literal pattern (used to distinguish literal from col name)
_DATE_LITERAL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_LITERAL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")


def _is_date_literal(value: str) -> bool:
    return bool(_DATE_LITERAL_RE.match(value))


def _is_datetime_literal(value: str) -> bool:
    return bool(_DATETIME_LITERAL_RE.match(value) or _DATE_LITERAL_RE.match(value))


def _resolve_day(strategy: str) -> pl.Expr:
    """Return an expression that yields the imputed day-of-month as a 2-char string."""
    if strategy == "first":
        return pl.lit("01")
    if strategy == "mid":
        return pl.lit("15")
    if strategy == "last":
        # We need month context — handled at call-site via _pad_to_full_date
        raise ValueError("day_imputation='last' must be handled at call-site")
    if strategy == "none":
        return pl.lit(None, dtype=pl.String)
    # Column reference or date literal
    if _is_date_literal(strategy):
        day = int(strategy.split("-")[2])
        return pl.lit(f"{day:02d}")
    # Column reference: extract day-of-month from that column
    return pl.col(strategy).cast(pl.Date).dt.day().cast(pl.String).str.pad_start(2, "0")


def _resolve_month(strategy: str) -> pl.Expr:
    """Return an expression that yields the imputed month as a 2-char string."""
    if strategy == "first":
        return pl.lit("01")
    if strategy == "mid":
        return pl.lit("06")
    if strategy == "last":
        return pl.lit("12")
    if strategy == "none":
        return pl.lit(None, dtype=pl.String)
    if _is_date_literal(strategy):
        month = int(strategy.split("-")[1])
        return pl.lit(f"{month:02d}")
    return pl.col(strategy).cast(pl.Date).dt.month().cast(pl.String).str.pad_start(2, "0")


def _resolve_time(strategy: str) -> str | None:
    """Return a time literal string for the chosen imputation strategy."""
    if strategy == "first":
        return "T00:00:00"
    if strategy == "mid":
        return "T12:00:00"
    if strategy == "last":
        return "T23:59:59"
    if strategy == "none":
        return None
    # Fixed datetime literal: extract time part
    if _is_datetime_literal(strategy) and "T" in strategy:
        return "T" + strategy.split("T")[1]
    if _is_date_literal(strategy):
        return "T00:00:00"
    # Column reference — return sentinel; handled at call-site
    return strategy


def dtf_expr(source: str, target: str = "DTF") -> pl.Expr:
    """Derive the Date Imputation Flag from a ``--DTC`` character column.

    Returns:
        ``"M"`` when only year is present (month was imputed),
        ``"D"`` when year-month is present (day was imputed),
        ``null`` when the date is complete (YYYY-MM-DD or longer).
    """
    length = pl.col(source).str.len_chars()
    return (
        pl.when(pl.col(source).is_null() | (length == 0))
        .then(pl.lit(None, dtype=pl.String))
        .when(length <= 4)
        .then(pl.lit("M"))
        .when(length <= 7)
        .then(pl.lit("D"))
        .otherwise(pl.lit(None, dtype=pl.String))
        .alias(target)
    )


def tmf_expr(source: str, target: str = "TMF") -> pl.Expr:
    """Derive the Time Imputation Flag from a ``--DTC`` character column.

    Returns:
        ``"H"`` when no time part is present (hours imputed),
        ``"M"`` when only hours present (minutes imputed),
        ``"S"`` when hours+minutes present (seconds imputed),
        ``null`` when the datetime is complete.
    """
    length = pl.col(source).str.len_chars()
    return (
        pl.when(pl.col(source).is_null() | (length == 0))
        .then(pl.lit(None, dtype=pl.String))
        .when(length <= 10)
        .then(pl.lit("H"))
        .when(length <= 13)
        .then(pl.lit("M"))
        .when(length <= 16)
        .then(pl.lit("S"))
        .otherwise(pl.lit(None, dtype=pl.String))
        .alias(target)
    )


def impute_dtc_to_date(
    source: str,
    target: str,
    *,
    day_imputation: str = "first",
    month_imputation: str = "first",
) -> pl.Expr:
    """Pad a partial ``--DTC`` string and parse to ``pl.Date``.

    Handles four levels of completeness based on string length:
    - ``>=10``  → already complete (YYYY-MM-DD or longer), parse directly
    - ``7``     → YYYY-MM, append ``-DD`` using *day_imputation*
    - ``4``     → YYYY, append ``-MM-DD`` using *month_imputation* and *day_imputation*
    - null/empty → null

    For ``day_imputation="last"`` the last day of the month is calculated
    using Polars date arithmetic.

    Args:
        source: Name of the ``--DTC`` column (``pl.String``).
        target: Name of the output ``pl.Date`` column.
        day_imputation: One of ``"first"``, ``"last"``, ``"mid"``, ``"none"``,
            a column name, or a date literal (``"YYYY-MM-DD"``).
        month_imputation: One of ``"first"``, ``"last"``, ``"mid"``, ``"none"``,
            a column name, or a date literal (``"YYYY-MM-DD"``).

    Returns:
        pl.Expr: Expression producing a ``pl.Date`` column.
    """
    col = pl.col(source)
    length = col.str.len_chars()
    date_part = col.str.slice(0, 10)  # strip any time portion

    # Complete date: just parse the first 10 characters
    complete = date_part.str.to_date("%Y-%m-%d", strict=False)

    # YYYY-MM: append day
    if day_imputation == "none":
        with_day = pl.lit(None, dtype=pl.Date)
    elif day_imputation == "last":
        # Parse YYYY-MM-01 then go to next month and subtract 1 day
        first_of_month = (col.str.slice(0, 7) + pl.lit("-01")).str.to_date("%Y-%m-%d", strict=False)
        with_day = first_of_month.dt.month_end()
    else:
        day_val = _resolve_day(day_imputation)
        with_day = (col.str.slice(0, 7) + pl.lit("-") + day_val).str.to_date(
            "%Y-%m-%d", strict=False
        )

    # YYYY: append month and day
    if month_imputation == "none":
        with_month_day = pl.lit(None, dtype=pl.Date)
    else:
        month_val = _resolve_month(month_imputation)
        if day_imputation == "none":
            with_month_day = pl.lit(None, dtype=pl.Date)
        elif day_imputation == "last":
            first_of_month = (
                col.str.slice(0, 4) + pl.lit("-") + month_val + pl.lit("-01")
            ).str.to_date("%Y-%m-%d", strict=False)
            with_month_day = first_of_month.dt.month_end()
        else:
            day_val = _resolve_day(day_imputation)
            with_month_day = (
                col.str.slice(0, 4) + pl.lit("-") + month_val + pl.lit("-") + day_val
            ).str.to_date("%Y-%m-%d", strict=False)

    return (
        pl.when(col.is_null() | (length == 0))
        .then(pl.lit(None, dtype=pl.Date))
        .when(length >= 10)
        .then(complete)
        .when(length >= 7)
        .then(with_day)
        .when(length >= 4)
        .then(with_month_day)
        .otherwise(pl.lit(None, dtype=pl.Date))
        .alias(target)
    )


def impute_dtc_to_datetime(
    source: str,
    target: str,
    *,
    day_imputation: str = "first",
    month_imputation: str = "first",
    time_imputation: str = "first",
) -> pl.Expr:
    """Pad a partial ``--DTC`` string and parse to ``pl.Datetime``.

    Extends :func:`impute_dtc_to_date` with time handling:
    - ``>= 19`` → complete datetime, parse directly
    - ``10-18`` → date complete but time partially or fully missing, impute time
    - ``< 10``  → partial date, impute date components first then time

    Args:
        source: Name of the ``--DTC`` column (``pl.String``).
        target: Name of the output ``pl.Datetime`` column.
        day_imputation: Strategy for missing day component.
        month_imputation: Strategy for missing month component.
        time_imputation: Strategy for missing time component.

    Returns:
        pl.Expr: Expression producing a ``pl.Datetime`` column.
    """
    col = pl.col(source)
    length = col.str.len_chars()

    time_suffix = _resolve_time(time_imputation)

    # Full datetime string: parse directly
    full_dtm = col.str.to_datetime("%Y-%m-%dT%H:%M:%S", strict=False)

    # Date part complete (len >= 10) but time missing or partial:
    # get the date portion and append the default time
    if time_imputation == "none":
        date_with_time = pl.lit(None, dtype=pl.Datetime("us"))
    elif isinstance(time_suffix, str) and time_suffix.startswith("T"):
        date_with_time = (col.str.slice(0, 10) + pl.lit(time_suffix)).str.to_datetime(
            "%Y-%m-%dT%H:%M:%S", strict=False
        )
    else:
        # Column reference for time — extract time from that column
        date_with_time = (
            col.str.slice(0, 10) + pl.lit("T") + pl.col(time_suffix).cast(pl.Time).cast(pl.String)
        ).str.to_datetime("%Y-%m-%dT%H:%M:%S", strict=False)

    # Partial dates (len < 10) require materialisation for date imputation
    # and are handled by the derive_dtm verb in _mixins.py.
    # This function only handles complete/nearly-complete strings.
    return (
        pl.when(col.is_null() | (length == 0))
        .then(pl.lit(None, dtype=pl.Datetime("us")))
        .when(length >= 19)
        .then(full_dtm)
        .when(length >= 10)
        .then(date_with_time)
        .otherwise(pl.lit(None, dtype=pl.Datetime("us")))
        .alias(target)
    )
