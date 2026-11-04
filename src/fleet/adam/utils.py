"""Standard ADaM statistical function implementations."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

import polars as pl

from fleet.core.dtc import date_part, is_iso8601, time_groups, warn_on_collect
from fleet.core.exceptions import DerivationError


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
    """BMI = weight_kg / (height_m^2). Height input assumed in cm; a height of 0 gives null."""
    height_m = pl.when(pl.col(height) != 0).then(pl.col(height) / 100.0)
    return (pl.col(weight) / (height_m * height_m)).round(1).alias(target)


def nrind(value: str, low: str, high: str, target: str = "NRIND") -> pl.Expr:
    """Normal range indicator: LOW / NORMAL / HIGH (admiral semantics).

    Null guard: a null analysis value, or both limits null, yields a
    null indicator instead of a spurious "NORMAL".  One-sided ranges
    classify against the available limit only.
    """
    value_col = pl.col(value)
    low_col = pl.col(low)
    high_col = pl.col(high)
    return (
        pl.when(value_col.is_null() | (low_col.is_null() & high_col.is_null()))
        .then(pl.lit(None, dtype=pl.String))
        .when(low_col.is_not_null() & (value_col < low_col))
        .then(pl.lit("LOW"))
        .when(high_col.is_not_null() & (value_col > high_col))
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
        raise DerivationError(
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

_RR_UNITS = {"ms": 1000.0, "msec": 1000.0, "s": 1.0, "sec": 1.0}


def qtc(
    qt: str = "QT",
    rr: str = "RR",
    *,
    method: str = "Fridericia",
    target: str = "QTC",
    rr_unit: str = "ms",
) -> pl.Expr:
    """
    Corrected QT interval.

    Supported *method* values:

    - ``"Fridericia"`` (default): ``QT / RR^(1/3)``
    - ``"Bazett"``: ``QT / RR^(1/2)``

    *QT* is in ms; *RR* is in *rr_unit* (``"ms"``/``"msec"``, default, or
    ``"s"``/``"sec"``) and enters the formula in seconds, as admiral
    ``compute_qtc``.
    """
    unit = rr_unit.lower()
    if unit not in _RR_UNITS:
        raise DerivationError(
            f"qtc: rr_unit={rr_unit!r} is not supported. Use 'ms', 'msec', 's' or 'sec'."
        )
    qt_col = pl.col(qt).cast(pl.Float64)
    rr_col = pl.col(rr).cast(pl.Float64) / _RR_UNITS[unit]
    method_lower = method.lower()
    if method_lower == "fridericia":
        expr = qt_col / rr_col.pow(1.0 / 3.0)
    elif method_lower == "bazett":
        expr = qt_col / rr_col.sqrt()
    else:
        raise DerivationError(f"Unknown QTc method '{method}'. Supported: Fridericia, Bazett.")
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
        raise DerivationError("day_imputation='last' must be handled at call-site")
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

    Reads the time part of the value (ADaM CT C81226, TIMEFL):

    Returns:
        ``"H"`` when no hour is collected (hours, minutes and seconds imputed),
        ``"M"`` when only the hour is collected (minutes and seconds imputed),
        ``"S"`` when hours and minutes are collected (seconds imputed),
        ``null`` when the seconds are collected, or the value is null.
    """
    col = pl.col(source)
    parts = time_groups(col)
    return (
        pl.when(col.is_null() | (col.str.strip_chars() == ""))
        .then(pl.lit(None, dtype=pl.String))
        .when(parts.struct.field("hour").is_null())
        .then(pl.lit("H"))
        .when(parts.struct.field("minute").is_null())
        .then(pl.lit("M"))
        .when(parts.struct.field("second").is_null())
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
    complete = date_part(col)

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
        pl.when(col.str.contains(r"^\d{4}-\d{2}-\d{2}(?:T|$)"))
        .then(complete)
        .when(col.str.contains(r"^\d{4}-\d{2}$"))
        .then(with_day)
        .when(col.str.contains(r"^\d{4}$"))
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
    """Parse a ``--DTC`` string with a complete date to ``pl.Datetime``, imputing the time.

    Every collected part of the time is kept, and only the missing parts
    are imputed, by position (admiral ``derive_vars_dtm``):

    - no hour: the whole time from *time_imputation* (``first`` 00:00:00,
      ``mid`` 12:00:00, ``last`` 23:59:59, a column or a literal);
    - hour only: minutes and seconds 00 (``first``, ``mid``) or 59 (``last``);
    - hour and minute: seconds 00 or 59.

    A fraction of a second is kept.  A ``Z`` or an offset is dropped, so
    the value is the wall clock.  A partial date gives null here; the
    ``.date()`` verb imputes the date first.

    Args:
        source: Name of the ``--DTC`` column (``pl.String``).
        target: Name of the output ``pl.Datetime`` column.
        day_imputation: Kept for the call signature; dates are not imputed here.
        month_imputation: Kept for the call signature; dates are not imputed here.
        time_imputation: Strategy for the missing time parts, or ``"none"``.

    Returns:
        pl.Expr: Expression producing a ``pl.Datetime("us")`` column.
    """
    col = pl.col(source)
    parts = time_groups(col)
    hour, minute, second = (parts.struct.field(f) for f in ("hour", "minute", "second"))
    if time_imputation == "none":
        clock = pl.when(second.is_not_null()).then(
            pl.concat_str(hour, minute, second, separator=":")
        )
    else:
        fill = "59" if time_imputation == "last" else "00"
        clock = (
            pl.when(hour.is_null())
            .then(_whole_time(time_imputation))
            .when(minute.is_null())
            .then(pl.concat_str(hour, pl.lit(fill), pl.lit(fill), separator=":"))
            .when(second.is_null())
            .then(pl.concat_str(hour, minute, pl.lit(fill), separator=":"))
            .otherwise(pl.concat_str(hour, minute, second, separator=":"))
        )
    text = pl.concat_str(date_part(col).dt.to_string("%Y-%m-%d"), pl.lit("T"), clock)
    return text.str.to_datetime("%Y-%m-%dT%H:%M:%S%.f", time_unit="us", strict=False).alias(target)


def _whole_time(strategy: str) -> pl.Expr:
    """``hh:mm:ss`` for a value with no hour, from a strategy, a literal or a column."""
    suffix = _resolve_time(strategy)
    if isinstance(suffix, str) and suffix.startswith("T"):
        return pl.lit(suffix[1:])
    return pl.col(strategy).cast(pl.Time).dt.to_string("%H:%M:%S")


# ------------------------------------------------------------------ #
# Unified date API helpers                                             #
# ------------------------------------------------------------------ #


def _infer_output_type(target: str) -> Literal["dtc", "dt", "dtm"] | None:
    """Infer output type from the CDISC suffix of *target*.

    Returns None if no recognizable suffix is found.
    """
    if target.endswith("DTC"):
        return "dtc"
    if target.endswith("DTM"):
        return "dtm"
    if target.endswith("DT"):
        return "dt"
    return None


def _resolve_output_type(target: str, output: str | None) -> Literal["dtc", "dt", "dtm"]:
    """Combine explicit *output* override with suffix inference.

    Raises ValueError when the output type cannot be determined.
    """
    if output is not None:
        out = output.lower()
        if out not in ("dtc", "dt", "dtm"):
            raise DerivationError(f"output={output!r} is not valid. Choose 'dtc', 'dt', or 'dtm'.")
        return out  # type: ignore[return-value]
    inferred = _infer_output_type(target)
    if inferred is None:
        raise DerivationError(
            f"Cannot infer output type from target '{target}'. "
            "Use output='dt', 'dtm', or 'dtc' to specify explicitly."
        )
    return inferred


def _extract_prefix(target: str) -> str:
    """Strip the DTC/DTM/DT suffix from *target* and return the prefix.

    Raises ValueError if no recognizable suffix is found.
    """
    if target.endswith("DTM"):
        return target[:-3]
    if target.endswith("DTC"):
        return target[:-3]
    if target.endswith("DT"):
        return target[:-2]
    raise DerivationError(f"Cannot extract prefix from '{target}'")


def _resolve_flag_names(
    target: str,
    flag: bool | str,
    output_type: str,
) -> tuple[str | None, str | None]:
    """Resolve (dtf_name, tmf_name) from the *flag* parameter.

    Returns ``(None, None)`` when flags are suppressed.
    """
    if flag is False:
        return None, None
    if isinstance(flag, str):
        dtf = flag
        tmf = flag.replace("DTF", "TMF") if "DTF" in flag and output_type == "dtm" else None
        return dtf, tmf
    # flag is True → auto-name from prefix
    try:
        prefix = _extract_prefix(target)
    except ValueError:
        raise DerivationError(
            f"Cannot auto-name flag for target '{target}'. Use flag='<name>DTF' or flag=False."
        ) from None
    dtf = f"{prefix}DTF"
    tmf = f"{prefix}TMF" if output_type == "dtm" else None
    return dtf, tmf


def _apply_highest(
    source_col: pl.Expr,
    highest: str,
) -> pl.Expr:
    """Return a boolean mask that is True when the source has enough precision.

    Used to nullify results where the imputation ceiling is exceeded.
    """
    # Map highest level to the minimum string length that satisfies it
    # Y=4 (YYYY), M=7 (YYYY-MM), D=10 (YYYY-MM-DD)
    # h=13 (YYYY-MM-DDThh), m=16 (YYYY-MM-DDThh:mm), s=19 (full)
    level_map = {"Y": 4, "M": 7, "D": 10, "h": 13, "m": 16, "s": 19}
    min_len = level_map.get(highest)
    if min_len is None:
        raise DerivationError(
            f"highest={highest!r} is not valid. Choose one of: {sorted(level_map)}"
        )
    length = source_col.str.len_chars()
    return length >= min_len


def _apply_bounds(
    source: str,
    target_expr: pl.Expr,
    min_date: str | None,
    max_date: str | None,
) -> pl.Expr:
    """Move an imputed date to a bound that lies inside the possible range of the partial value.

    The range of ``2021-03`` is 2021-03-01 to 2021-03-31, so a lower bound of
    2021-03-15 applies and one of 2021-04-01 does not.  A complete date has
    a range of one day, so it never changes (admiral ``derive_vars_dt``).
    Bounds can be column names or date literals (YYYY-MM-DD).
    """
    lowest = impute_dtc_to_date(source, "__lo__", day_imputation="first", month_imputation="first")
    highest = impute_dtc_to_date(source, "__hi__", day_imputation="last", month_imputation="last")
    expr = target_expr
    for bound_name, lower in ((min_date, True), (max_date, False)):
        if bound_name is None:
            continue
        bound = (
            pl.lit(bound_name).str.to_date("%Y-%m-%d", strict=False)
            if _is_date_literal(bound_name)
            else pl.col(bound_name).cast(pl.Date)
        )
        inside = (lowest <= bound) & (bound <= highest)
        moves = expr < bound if lower else expr > bound
        expr = pl.when(inside & moves).then(bound).otherwise(expr)
    return expr


def impute_and_flag(
    source: str | None,
    target: str,
    *,
    value: str | date | datetime | None = None,
    output_type: Literal["dtc", "dt", "dtm"],
    time: str | None = None,
    impute: str = "first",
    impute_time: str | None = None,
    highest: str | None = None,
    min_date: str | None = None,
    max_date: str | None = None,
    flag: bool | str = True,
) -> list[pl.Expr]:
    """Unified imputation engine for the ``.date()`` verb.

    Returns a list of expressions: the target column plus any flag columns.

    When *value* is provided, broadcasts a literal and skips imputation.
    When *flag* is a str, uses it as the explicit DTF flag name.
    """
    dtf_name, tmf_name = _resolve_flag_names(target, flag, output_type)

    # ── value= path: literal broadcast, no imputation ──
    if value is not None:
        if isinstance(value, datetime):
            if output_type == "dtm":
                return [pl.lit(value).alias(target)]
            elif output_type == "dt":
                return [pl.lit(value.date()).alias(target)]
            else:  # dtc
                return [pl.lit(value.isoformat()).alias(target)]
        elif isinstance(value, date):
            if output_type == "dt":
                return [pl.lit(value).alias(target)]
            elif output_type == "dtm":
                dt_val = datetime(value.year, value.month, value.day)
                return [pl.lit(dt_val).alias(target)]
            else:  # dtc
                return [pl.lit(value.isoformat()).alias(target)]
        else:
            # String literal
            if output_type == "dtc":
                return [pl.lit(value).alias(target)]
            elif output_type == "dt":
                parsed = pl.lit(value).str.to_date("%Y-%m-%d", strict=False)
                return [parsed.alias(target)]
            else:  # dtm
                parsed = pl.lit(value).str.to_datetime("%Y-%m-%dT%H:%M:%S", strict=False)
                if parsed is None:
                    parsed = (
                        pl.lit(value).str.to_date("%Y-%m-%d", strict=False).cast(pl.Datetime("us"))
                    )
                return [parsed.alias(target)]

    assert source is not None, "Either source or value must be provided"

    exprs: list[pl.Expr] = []

    if output_type == "dtc":
        # DTC path is handled by the SDTM namespace directly
        from fleet.sdtm.utils import dtc_date_expr

        exprs.append(dtc_date_expr(source, target))
        return exprs

    if output_type == "dt":
        # Date path: impute partial DTC → pl.Date
        date_expr = impute_dtc_to_date(
            source,
            target,
            day_imputation=impute,
            month_imputation=impute,
        )
        # Apply highest ceiling
        if highest is not None:
            mask = _apply_highest(pl.col(source), highest)
            date_expr = (
                pl.when(mask).then(date_expr).otherwise(pl.lit(None, dtype=pl.Date)).alias(target)
            )
        # Bounds move an imputed date only (admiral derive_vars_dt)
        if min_date is not None or max_date is not None:
            date_expr = _apply_bounds(source, date_expr, min_date, max_date)
        exprs.append(warn_unread(source, target, date_expr, pl.Date).alias(target))
        # Flags
        if dtf_name is not None:
            exprs.append(dtf_expr(source, dtf_name))
        return exprs

    # output_type == "dtm"
    refuse_dtm_bounds(target, min_date, max_date)
    dtm_expr = impute_dtc_to_datetime(
        source,
        target,
        day_imputation=impute,
        month_imputation=impute,
        time_imputation=impute_time or impute,
    )
    exprs.append(warn_unread(source, target, dtm_expr, pl.Datetime("us")).alias(target))
    if dtf_name is not None:
        exprs.append(dtf_expr(source, dtf_name))
    if tmf_name is not None:
        exprs.append(tmf_expr(source, tmf_name))
    return exprs


def refuse_dtm_bounds(target: str, min_date: str | None, max_date: str | None) -> None:
    """Refuse ``min_date`` and ``max_date`` on a date-time target, which has no tested rule yet."""
    if min_date is not None or max_date is not None:
        raise DerivationError(
            f"date('{target}'): min_date= and max_date= apply to a date (*DT) target only. "
            "Derive the *DT variable with the bound, then build the date-time from it."
        )


def warn_unread(source: str, target: str, value: pl.Expr, dtype: pl.DataType) -> pl.Expr:
    """*value*, warning at collect on source text that is not ISO 8601 or carries an offset."""
    text = pl.col(source).cast(pl.String)
    given = text.str.strip_chars().fill_null("") != ""
    value = warn_on_collect(
        value,
        given & ~is_iso8601(text).fill_null(True),
        lambda n, values: (
            f"date('{target}'): {n} value(s) of {source} are not ISO 8601, so {target} is "
            f"null for them. Values: {values}"
        ),
        dtype=dtype,
        shown=text,
    )
    if dtype == pl.Date:
        return value
    return warn_on_collect(
        value,
        time_groups(text).struct.field("zone").is_not_null(),
        lambda n, values: (
            f"date('{target}'): {n} value(s) of {source} carry a UTC offset or Z; {target} "
            f"keeps the wall clock and drops the offset, as admiral does. Values: {values}"
        ),
        dtype=dtype,
        shown=text,
    )
