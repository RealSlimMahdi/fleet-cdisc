"""Standard ADaM statistical function implementations."""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime
from typing import Literal

import polars as pl

from fleet.core.dtc import (
    date_part,
    is_iso8601,
    refuse_number,
    time_groups,
    to_day,
    warn_on_collect,
)
from fleet.core.exceptions import DerivationError, VerbUsageError


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
    """Change from baseline: CHG = AVAL - BASE, as Float64 (an unsigned input cannot wrap)."""
    return (pl.col(aval).cast(pl.Float64) - pl.col(base).cast(pl.Float64)).alias(target)


def pchg(aval: str = "AVAL", base: str = "BASE", target: str = "PCHG") -> pl.Expr:
    """Percent change from baseline: PCHG = (AVAL - BASE) / BASE * 100, as Float64."""
    a = pl.col(aval).cast(pl.Float64)
    b = pl.col(base).cast(pl.Float64)
    return pl.when(b.is_not_null() & (b != 0)).then((a - b) / b * 100).otherwise(None).alias(target)


def sas_round(expr: pl.Expr, digits: int | None) -> pl.Expr:
    """Round as SAS ``ROUND(x, 10**-digits)``: half away from zero; ``None`` keeps *expr*.

    The value is first rounded to 8 decimals of the scaled number, so a
    binary value such as 24.25 rounds to 24.3, as SAS does.
    """
    if digits is None:
        return expr
    scale = 10.0**digits
    # The last round(digits) removes the 1-ulp error of the division (93.30000000000001).
    rounded = (expr * scale).round(8).round(0, mode="half_away_from_zero") / scale
    return rounded.round(digits)


def bmi(
    weight: str = "weight_kg",
    height: str = "height_cm",
    target: str = "BMI",
    *,
    round_digits: int | None = None,
) -> pl.Expr:
    """BMI = weight_kg / (height_m^2). Height input assumed in cm; height 0 gives null."""
    height_m = pl.col(height) / 100.0
    value = pl.when(pl.col(height) != 0).then(pl.col(weight) / (height_m * height_m))
    return sas_round(value, round_digits).alias(target)


def nrind(
    value: str, low: str, high: str, target: str = "NRIND", *, signif_dig: int = 15
) -> pl.Expr:
    """Normal range indicator: LOW / NORMAL / HIGH (admiral semantics).

    Null guard: a null or NaN analysis value, or both limits null, yields a
    null indicator instead of a spurious "NORMAL".  One-sided ranges
    classify against the available limit only.  The three values are
    compared at *signif_dig* significant digits, as admiral ``signif()``.
    """

    def _signif(name: str) -> pl.Expr:
        return pl.col(name).cast(pl.Float64).fill_nan(None).round_sig_figs(signif_dig)

    value_col = _signif(value)
    low_col = _signif(low)
    high_col = _signif(high)
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
    dtypes: Mapping[str, pl.DataType] | None = None,
) -> pl.Expr:
    """ONTRTFL = "Y" when ADT is on or between TRTSDT and TRTEDT (inclusive).

    When *open_ended* is ``True`` (default) and TRTEDT is null the interval
    is treated as ongoing — ``adt >= trtsdt`` is sufficient for "Y".
    Each column is read by its dtype in *dtypes* (``to_day``): ``--DTC``
    text by its date portion, a number raises.  The start comparison
    keeps the time when ADT and TRTSDT are both ``pl.Datetime``; the end
    comparison is at date level (admiral ``derive_var_ontrtfl``).
    """
    dtypes = dtypes or {}

    def day(name: str) -> pl.Expr:
        return to_day(pl.col(name), dtypes.get(name), verb="on_treatment").cast(pl.Date)

    adt_d, start_d, end_d = day(adt), day(trtsdt), day(trtedt)
    timed = isinstance(dtypes.get(adt), pl.Datetime) and isinstance(dtypes.get(trtsdt), pl.Datetime)
    started = pl.col(adt) >= pl.col(trtsdt) if timed else adt_d >= start_d

    on_trt = started & (adt_d <= end_d)
    if open_ended:
        on_trt = on_trt | (end_d.is_null() & started)

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
    round_digits: int | None = None,
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
    return sas_round(expr, round_digits).alias(target)


# ------------------------------------------------------------------ #
# Admiral-parity: Mean Arterial Pressure                              #
# ------------------------------------------------------------------ #


def mean_arterial_pressure(
    systolic: str = "SYSBP",
    diastolic: str = "DIABP",
    *,
    target: str = "MAP",
    round_digits: int | None = None,
) -> pl.Expr:
    """
    Mean Arterial Pressure: ``MAP = DBP + (SBP - DBP) / 3``.
    """
    sbp = pl.col(systolic).cast(pl.Float64)
    dbp = pl.col(diastolic).cast(pl.Float64)
    return sas_round(dbp + (sbp - dbp) / 3.0, round_digits).alias(target)


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
    round_digits: int | None = None,
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
    return sas_round(expr, round_digits).alias(target)


# ------------------------------------------------------------------ #
# Admiral-parity: Age in years (unit-aware)                            #
# ------------------------------------------------------------------ #


def age_in_years(
    age_col: str = "AGE",
    age_unit_col: str = "AGEU",
    *,
    target: str = "AAGE",
    round_digits: int | None = None,
) -> pl.Expr:
    """
    Convert age to years, handling common unit strings.

    Recognises *AGEU* values: ``YEARS``, ``MONTHS``, ``WEEKS``, ``DAYS``
    (case-insensitive).  Unknown units return null.
    """
    age = pl.col(age_col).cast(pl.Float64)
    unit = pl.col(age_unit_col).str.to_uppercase()
    years = (
        pl.when(unit == "YEARS")
        .then(age)
        .when(unit == "MONTHS")
        .then(age / 12.0)
        .when(unit == "WEEKS")
        .then(age / 52.1775)
        .when(unit == "DAYS")
        .then(age / 365.25)
        .otherwise(None)
    )
    return sas_round(years, round_digits).alias(target)


def age_between(
    birth: pl.Expr,
    reference: pl.Expr,
    *,
    unit: Literal["years", "decimal"],
    round_digits: int | None,
    verb: str,
) -> pl.Expr:
    """Age from two date expressions: completed years (Int64) or decimal years.

    ``"years"`` is SAS ``FLOOR(YRDIF(birth, reference, 'AGE'))``: the year
    difference, minus 1 when the birthday of the reference year is not yet
    reached.  A 29 February birthday is reached on 1 March in a non-leap
    year.  A reference date before birth gives a negative age.
    ``"decimal"`` is days / 365.25, rounded only with *round_digits*.
    """
    if unit == "years":
        if round_digits is not None:
            raise VerbUsageError(
                f"{verb}: round_digits applies to unit='decimal' only; "
                "unit='years' gives whole completed years."
            )
        before_birthday = (reference.dt.month() < birth.dt.month()) | (
            (reference.dt.month() == birth.dt.month()) & (reference.dt.day() < birth.dt.day())
        )
        return (
            reference.dt.year().cast(pl.Int64)
            - birth.dt.year().cast(pl.Int64)
            - before_birthday.cast(pl.Int64)
        )
    if unit == "decimal":
        return sas_round((reference - birth).dt.total_days() / 365.25, round_digits)
    raise VerbUsageError(f"{verb}: unit={unit!r} is not supported. Use 'years' or 'decimal'.")


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


#: Year, month and day of a ``--DTC`` value; a hyphen stands for a missing part (SDTMIG 4.4.2).
_DATE_FORM = r"^(\d{4})(?:-(\d{2}|-)(?:-(\d{2}|-))?)?(?:T|$)"


def _col(source: str | pl.Expr) -> pl.Expr:
    return pl.col(source) if isinstance(source, str) else source


def _date_form(source: str | pl.Expr) -> tuple[pl.Expr, pl.Expr, pl.Expr]:
    """Year, month and day text of a value; a missing part, or a value of another form, is null."""
    parts = _col(source).str.extract_groups(_DATE_FORM)
    year, month, day = (parts.struct.field(str(i)) for i in (1, 2, 3))
    return year, pl.when(month != "-").then(month), pl.when(day != "-").then(day)


def _imputed_level(source: str | pl.Expr) -> pl.Expr:
    """0 for a complete date, 1 when the day is missing, 2 when the month is missing."""
    year, month, day = _date_form(source)
    return (
        pl.when(year.is_null())
        .then(None)
        .when(month.is_null())
        .then(2)
        .when(day.is_null())
        .then(1)
        .otherwise(0)
    )


def source_text(source: str, dtype: pl.DataType | None, *, verb: str) -> pl.Expr:
    """Return ``--DTC`` text of *source*: text as it is, a date or a date-time as ISO 8601.

    A ``pl.Date`` gives ``2021-03-15`` and a ``pl.Datetime`` gives
    ``2021-03-15T10:30:00.000000``, so the one date engine reads every
    source.  A number raises (``refuse_number``).

    Args:
        source: The column name.
        dtype: Its dtype in the frame, or ``None`` when unknown.
        verb: The verb call, quoted in the error for a number.

    Returns:
        pl.Expr: A ``pl.String`` expression named *source*.

    Raises:
        DerivationError: When *dtype* is numeric.

    Examples:
        Read a SAS date column as ISO text::

            text = source_text("TRTSDT", adsl.collect_schema().get("TRTSDT"), verb="date")
    """
    col = pl.col(source)
    if dtype == pl.Date:
        return col.dt.to_string("%Y-%m-%d")
    if isinstance(dtype, pl.Datetime):
        return col.dt.to_string("%Y-%m-%dT%H:%M:%S%.f")
    refuse_number(source, dtype, verb=verb)
    return col


def dtf_expr(source: str | pl.Expr, target: str = "DTF") -> pl.Expr:
    """Derive the Date Imputation Flag from a ``--DTC`` character column.

    Reads the form of the value, as the date engine does (SDTMIG 3.4
    section 4.4.2): a hyphen stands for a missing part.

    Returns:
        ``"M"`` when the month is missing (month and day imputed: ``2021``,
        ``2021---15``),
        ``"D"`` when only the day is missing (``2021-03``, ``2021-03--T08:30``),
        ``null`` when the date is complete, or the value is null or of no
        ISO 8601 date form.
    """
    level = _imputed_level(source)
    return (
        pl.when(level == 2)
        .then(pl.lit("M"))
        .when(level == 1)
        .then(pl.lit("D"))
        .otherwise(pl.lit(None, dtype=pl.String))
        .alias(target)
    )


def tmf_expr(source: str | pl.Expr, target: str = "TMF") -> pl.Expr:
    """Derive the Time Imputation Flag from a ``--DTC`` character column.

    Reads the time part of the value (ADaM CT C81226, TIMEFL):

    Returns:
        ``"H"`` when no hour is collected (hours, minutes and seconds imputed),
        ``"M"`` when only the hour is collected (minutes and seconds imputed),
        ``"S"`` when hours and minutes are collected (seconds imputed),
        ``null`` when the seconds are collected, or the value is null.
    """
    col = _col(source)
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
    source: str | pl.Expr,
    target: str,
    *,
    day_imputation: str = "first",
    month_imputation: str = "first",
) -> pl.Expr:
    """Impute a partial ``--DTC`` string and parse to ``pl.Date``.

    Reads the form of the value, a hyphen standing for a missing part
    (SDTMIG 3.4 section 4.4.2; admiral ``impute_dtc_dt``):

    - complete date (``YYYY-MM-DD``, with or without a time) → parsed directly;
    - day missing (``YYYY-MM``, ``YYYY-MM--T08:30``) → day from *day_imputation*;
    - month missing (``YYYY``, ``YYYY---15``) → month and day imputed; a
      collected day is not used, as admiral does;
    - year missing, null, or another form (``202103``) → null.

    For ``day_imputation="last"`` the last day of the month is calculated
    using Polars date arithmetic.

    Args:
        source: Name of the ``--DTC`` column (``pl.String``), or a text expression.
        target: Name of the output ``pl.Date`` column.
        day_imputation: One of ``"first"``, ``"last"``, ``"mid"``, ``"none"``,
            a column name, or a date literal (``"YYYY-MM-DD"``).
        month_imputation: One of ``"first"``, ``"last"``, ``"mid"``, ``"none"``,
            a column name, or a date literal (``"YYYY-MM-DD"``).

    Returns:
        pl.Expr: Expression producing a ``pl.Date`` column.
    """
    col = _col(source)
    year, month, _ = _date_form(col)
    level = _imputed_level(col)

    def build(month_text: pl.Expr) -> pl.Expr:
        if day_imputation == "none":
            return pl.lit(None, dtype=pl.Date)
        if day_imputation == "last":
            first = pl.concat_str(year, month_text, pl.lit("01"), separator="-")
            return first.str.to_date("%Y-%m-%d", strict=False).dt.month_end()
        text = pl.concat_str(year, month_text, _resolve_day(day_imputation), separator="-")
        return text.str.to_date("%Y-%m-%d", strict=False)

    with_day = build(month)
    if month_imputation == "none":
        with_month_day = pl.lit(None, dtype=pl.Date)
    else:
        with_month_day = build(_resolve_month(month_imputation))

    return (
        pl.when(level == 0)
        .then(date_part(col))
        .when(level == 1)
        .then(with_day)
        .when(level == 2)
        .then(with_month_day)
        .otherwise(pl.lit(None, dtype=pl.Date))
        .alias(target)
    )


#: Year, month, day, hour, minute and second of a ``--DTC`` value; a hyphen is a missing part.
_DTM_FORM = (
    r"^(\d{4}|-)(?:-(\d{2}|-)(?:-(\d{2}|-)"
    r"(?:T(\d{2}|-)(?::(\d{2}|-)(?::(\d{2}(?:\.\d+)?|-))?)?)?)?)?"
    r"(?:Z|[+-]\d{2}(?::?\d{2})?)?$"
)

#: admiral ``highest_imputation`` on a *DTM target: the first missing part it may impute.
_HIGHEST_DTM = {"M": 1, "D": 2, "h": 3, "m": 4, "s": 5, "n": 6}


def _dtm_form(source: str | pl.Expr) -> tuple[pl.Expr, pl.Expr, pl.Expr, pl.Expr]:
    """The first missing part (0 year to 5 second, 6 none) and the hour, minute, second text."""
    groups = _col(source).str.extract_groups(_DTM_FORM)
    parts = [groups.struct.field(str(i)) for i in range(1, 7)]
    level = pl.lit(6)
    for i in reversed(range(6)):
        level = pl.when(parts[i].is_null() | (parts[i] == "-")).then(pl.lit(i)).otherwise(level)
    return level, parts[3], parts[4], parts[5]


def _dtm_ceiling(highest: str | None, target: str) -> int:
    """The lowest first-missing part *highest* accepts; no *highest* accepts a missing month."""
    if highest is None:
        return _HIGHEST_DTM["M"]
    if highest == "Y":
        raise DerivationError(
            f"date('{target}'): highest='Y' is not supported. Fleet does not impute a missing "
            "year; admiral needs min_dates or max_dates for it, and a *DTM target refuses "
            "min_date= and max_date=. Use 'n', 's', 'm', 'h', 'D' or 'M'."
        )
    if highest not in _HIGHEST_DTM:
        raise DerivationError(
            f"date('{target}'): highest={highest!r} is not valid. "
            "Choose 'n', 's', 'm', 'h', 'D' or 'M'."
        )
    return _HIGHEST_DTM[highest]


def impute_dtc_to_datetime(
    source: str | pl.Expr,
    target: str,
    *,
    date_imputation: str = "first",
    time_imputation: str = "first",
    highest: str | None = None,
) -> tuple[pl.Expr, pl.Expr, pl.Expr]:
    """Impute a ``--DTC`` value to ``pl.Datetime``, with its DTF and TMF flags.

    The one *DTM path of ``.sdtm.date()`` and ``.adam.date()``.  It follows
    admiral ``derive_vars_dtm`` with ``preserve = FALSE``:

    - The first missing part decides.  A part below it is not used, so
      ``2021-03--T08:30`` gives 2021-03-01T00:00:00 with DTF ``D`` and
      TMF ``H``, and ``2021-03-15T08:-:45`` gives 08:00:00 with TMF ``M``.
    - A missing date part takes *date_imputation*, as ``impute_dtc_to_date``.
    - No hour: the whole time from *time_imputation* (``first`` 00:00:00,
      ``mid`` 12:00:00, ``last`` 23:59:59, a column or a literal).  Hour
      only: minutes and seconds 00, or 59 for ``last``.  Hour and minute:
      seconds 00 or 59.
    - *highest* names the highest part that may be imputed: ``"M"``,
      ``"D"``, ``"h"``, ``"m"``, ``"s"`` or ``"n"`` (none).  A value that
      needs more is null.  ``None`` is ``"M"``, as on a *DT target.

    A fraction of a second is kept.  A ``Z`` or an offset is dropped, so
    the value is the wall clock.  A missing year gives null.  A flag is
    null where the value is null.

    Args:
        source: Name of the ``--DTC`` column (``pl.String``), or a text expression.
        target: Name of the output ``pl.Datetime`` column.
        date_imputation: Strategy for the missing date parts, or ``"none"``.
        time_imputation: Strategy for the missing time parts, or ``"none"``.
        highest: The admiral ``highest_imputation`` level, or ``None``.

    Returns:
        tuple[pl.Expr, pl.Expr, pl.Expr]: The ``pl.Datetime("us")`` value
            named *target*, the DTF flag and the TMF flag.

    Raises:
        DerivationError: When *highest* is ``"Y"`` or not a level.

    References:
        admiral 1.4.1 ``derive_vars_dtm`` and ``impute_dtc_dtm``; ADaMIG
        1.3 section 3.3.3 (DTF and TMF); ADR-0045.

    Examples:
        Impute AESTDTC to ASTDTM, with no imputation above the hour::

            value, dtf, tmf = impute_dtc_to_datetime("AESTDTC", "ASTDTM", highest="h")
            adae = ae.with_columns(value, dtf.alias("ASTDTF"), tmf.alias("ASTTMF"))
    """
    ceiling = _dtm_ceiling(highest, target)
    col = _col(source)
    level, hour, minute, second = _dtm_form(col)
    date = (
        pl.when(level >= 3)
        .then(date_part(col))
        .otherwise(
            impute_dtc_to_date(
                col, "__date__", day_imputation=date_imputation, month_imputation=date_imputation
            )
        )
    )
    if time_imputation == "none":
        clock = pl.when(level == 6).then(pl.concat_str(hour, minute, second, separator=":"))
    else:
        fill = pl.lit("59" if time_imputation == "last" else "00")
        clock = (
            pl.when(level <= 3)
            .then(_whole_time(time_imputation))
            .when(level == 4)
            .then(pl.concat_str(hour, fill, fill, separator=":"))
            .when(level == 5)
            .then(pl.concat_str(hour, minute, fill, separator=":"))
            .otherwise(pl.concat_str(hour, minute, second, separator=":"))
        )
    text = pl.concat_str(date.dt.to_string("%Y-%m-%d"), pl.lit("T"), clock)
    value = pl.when(level >= ceiling).then(
        text.str.to_datetime("%Y-%m-%dT%H:%M:%S%.f", time_unit="us", strict=False)
    )
    dtf = pl.when(value.is_not_null()).then(
        pl.when(level == 1).then(pl.lit("M")).when(level == 2).then(pl.lit("D"))
    )
    tmf = pl.when(value.is_not_null()).then(
        pl.when(level <= 3)
        .then(pl.lit("H"))
        .when(level == 4)
        .then(pl.lit("M"))
        .when(level == 5)
        .then(pl.lit("S"))
    )
    return value.alias(target), dtf, tmf


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


#: admiral ``highest_imputation`` on a *DT target: the highest date part that may be imputed.
_HIGHEST_DT = {"n": 0, "D": 1, "M": 2}


def _apply_highest(
    source: str | pl.Expr,
    highest: str,
    target: str,
) -> pl.Expr:
    """Return True where the date needs no imputation above *highest* (admiral meaning).

    ``"n"``: no imputation; ``"D"``: the day may be imputed; ``"M"``: the
    month and the day may be imputed.  Time levels and ``"Y"`` raise.
    """
    if highest in ("h", "m", "s"):
        raise DerivationError(
            f"date('{target}'): highest={highest!r} is a time level and a *DT target has no "
            "time. Use 'n', 'D' or 'M'."
        )
    if highest == "Y":
        raise DerivationError(
            f"date('{target}'): highest='Y' is not supported. Fleet does not impute a missing "
            "year; admiral needs min_dates or max_dates for it. Use 'n', 'D' or 'M'."
        )
    if highest not in _HIGHEST_DT:
        raise DerivationError(
            f"date('{target}'): highest={highest!r} is not valid. Choose 'n', 'D' or 'M'."
        )
    return _imputed_level(source) <= _HIGHEST_DT[highest]


def _apply_bounds(
    source: str | pl.Expr,
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
    source: str | pl.Expr | None,
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
    *source* is a column name or a text expression (``source_text``).  A
    flag is null where the target is null.

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
                parsed = pl.coalesce(
                    pl.lit(value).str.to_datetime(
                        "%Y-%m-%dT%H:%M:%S", time_unit="us", strict=False
                    ),
                    pl.lit(value).str.to_date("%Y-%m-%d", strict=False).cast(pl.Datetime("us")),
                )
                return [parsed.alias(target)]

    assert source is not None, "Either source or value must be provided"

    exprs: list[pl.Expr] = []

    if output_type == "dtc":
        # DTC path is handled by the SDTM namespace directly
        from fleet.sdtm.utils import dtc_text

        exprs.append(dtc_text(_col(source)).alias(target))
        return exprs

    if output_type == "dt":
        # Date path: impute partial DTC → pl.Date
        date_expr = impute_dtc_to_date(
            source,
            target,
            day_imputation=impute,
            month_imputation=impute,
        )
        if highest is not None:
            date_expr = pl.when(_apply_highest(source, highest, target)).then(date_expr)
        # Bounds move an imputed date only (admiral derive_vars_dt)
        if min_date is not None or max_date is not None:
            date_expr = _apply_bounds(source, date_expr, min_date, max_date)
        exprs.append(warn_unread(source, target, date_expr, pl.Date).alias(target))
        if dtf_name is not None:
            exprs.append(pl.when(date_expr.is_not_null()).then(dtf_expr(source)).alias(dtf_name))
        return exprs

    # output_type == "dtm"
    refuse_dtm_bounds(target, min_date, max_date)
    dtm_expr, dtf, tmf = impute_dtc_to_datetime(
        source,
        target,
        date_imputation=impute,
        time_imputation=impute_time or impute,
        highest=highest,
    )
    exprs.append(warn_unread(source, target, dtm_expr, pl.Datetime("us")).alias(target))
    if dtf_name is not None:
        exprs.append(dtf.alias(dtf_name))
    if tmf_name is not None:
        exprs.append(tmf.alias(tmf_name))
    return exprs


def refuse_dtm_bounds(target: str, min_date: str | None, max_date: str | None) -> None:
    """Refuse ``min_date`` and ``max_date`` on a date-time target (no tested rule)."""
    if min_date is not None or max_date is not None:
        raise DerivationError(
            f"date('{target}'): min_date= and max_date= apply to a date (*DT) target only. "
            "Derive the *DT variable with the bound, then build the date-time from it."
        )


def warn_unread(source: str | pl.Expr, target: str, value: pl.Expr, dtype: pl.DataType) -> pl.Expr:
    """*value*, warning at collect on source text that is not ISO 8601 or carries an offset."""
    text = _col(source).cast(pl.String)
    if not isinstance(source, str):
        source = source.meta.output_name(raise_if_undetermined=False) or "the source"
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


def dtm_source_text(
    schema: pl.Schema,
    *,
    source: str,
    target: str,
    time: str,
    input_format: str | None = None,
) -> pl.Expr:
    """Join a date column and a time column or ``hh:mm[:ss]`` literal into ``--DTC`` text.

    The *DTM path then reads the text as any ``--DTC`` value, so ``time=``
    comes first, then the imputation, then ``highest=`` (ADR-0045).  The
    text follows SDTMIG 3.4 section 4.4.2: ``2024-03-15`` and ``08:15``
    give ``2024-03-15T08:15``; a partial date takes a hyphen for each
    missing part (``2024-03--T08:15``); a blank time leaves the date alone.
    A time in another layout (``0815``) is left out, with one warning.

    Args:
        schema: The schema of the frame.
        source: The date column: text, ``pl.Date``, or raw text read with *input_format*.
        target: The *DTM column, quoted in the messages.
        time: A time column, or an ``hh:mm[:ss]`` literal.
        input_format: A ``strptime`` layout of the raw date text, or ``None``.

    Returns:
        pl.Expr: A ``pl.String`` expression of ``--DTC`` text.

    Raises:
        DerivationError: When *time* names no column, or *source* is a
            number or already holds a time.

    Examples:
        Join AESTDTC and AESTTIM, then impute::

            text = dtm_source_text(ae.collect_schema(), source="AESTDTC",
                                   target="ASTDTM", time="AESTTIM")
            astdtm, astdtf, asttmf = impute_dtc_to_datetime(text, "ASTDTM")
    """
    from fleet.sdtm.utils import TIME_LITERAL, bad_time, dtc_text, dtc_with_time

    call = f"date('{target}')"
    if isinstance(schema.get(source), pl.Datetime):
        raise DerivationError(
            f"{call}: {source} is a date-time and already holds a time. Drop time=, or "
            "pass the date column."
        )
    time_is_literal = bool(TIME_LITERAL.match(time))
    if not time_is_literal and time not in schema.names():
        raise DerivationError(
            f"time='{time}' column not found in the DataFrame. Available columns: {schema.names()}"
        )
    date_text = dtc_text(
        source_text(source, schema.get(source), verb=call), input_format=input_format
    )
    raw_time = pl.lit(time) if time_is_literal else pl.col(time)
    return warn_on_collect(
        dtc_with_time(date_text, pl.col(source), raw_time),
        bad_time(raw_time),
        lambda n, values: (
            f"{call}: {n} time value(s) of {time} are not hh:mm[:ss], so {target} takes an "
            f"imputed time. Values: {values}"
        ),
        dtype=pl.String,
        shown=raw_time.cast(pl.String),
    ).alias(source)
