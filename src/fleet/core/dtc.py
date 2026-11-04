"""One reader for ISO 8601 ``--DTC`` text (SDTMIG 3.4 section 4.4).

Every date verb reads ``--DTC`` text through these expressions, so a time
part, a partial date or a value that is not ISO 8601 gives the same result
everywhere: the date part of a value with a complete date, null otherwise,
and never a guess.  The expressions stay lazy.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable

import polars as pl

from fleet.core.exceptions import DerivationError

__all__ = [
    "date_part",
    "datetime_part",
    "has_time",
    "is_iso8601",
    "refuse_number",
    "time_groups",
    "to_day",
    "warn_on_collect",
]

#: A complete date at the start of the value, alone or followed by a time.
_DATE = r"^(\d{4}-\d{2}-\d{2})(?:T|$)"

#: The time parts of a value with a complete date (SDTMIG 4.4.1).
_TIME = (
    r"^\d{4}-\d{2}-\d{2}(?:T(\d{2})(?::(\d{2})(?::(\d{2}(?:\.\d+)?))?)?)?"
    r"(Z|[+-]\d{2}(?::?\d{2})?)?$"
)

_YEAR = r"(?:\d{4}|-)"
_MONTH = r"(?:0[1-9]|1[0-2]|-)"
_DAY = r"(?:0[1-9]|[12]\d|3[01]|-)"
_CLOCK = r"T(?:[01]\d|2[0-3]|-)(?::(?:[0-5]\d|-)(?::(?:[0-5]\d(?:\.\d+)?|-))?)?"
_ZONE = r"(?:Z|[+-](?:[01]\d|2[0-3])(?::?[0-5]\d)?)?"
#: One value: right truncation, or a hyphen for each missing component (SDTMIG 4.4.2).
_ISO_VALUE = rf"^{_YEAR}(?:-{_MONTH}(?:-{_DAY}(?:{_CLOCK}{_ZONE})?)?)?$"


def date_part(dtc: pl.Expr) -> pl.Expr:
    """Return the date of a ``--DTC`` value with a complete, real date; null otherwise.

    ``2021-03-20T10:30`` gives 2021-03-20.  A partial date (``2021-03``),
    an impossible date (``2021-02-30``) and text that is not ISO 8601 give
    null.

    Args:
        dtc: An expression of ``--DTC`` text.

    Returns:
        pl.Expr: A ``pl.Date`` expression.

    Examples:
        Study day on the date part of a timed value::

            ae = raw.with_columns(date_part(pl.col("AESTDTC")).alias("ASTDT"))
    """
    return dtc.str.extract(_DATE, 1).str.to_date("%Y-%m-%d", strict=False)


def time_groups(dtc: pl.Expr) -> pl.Expr:
    """Return the hour, minute, second and zone of a value with a complete date.

    The struct has the fields ``hour``, ``minute``, ``second`` and ``zone``
    (text, null when absent).  Every field is null when the value has no
    complete date or does not follow ISO 8601.

    Args:
        dtc: An expression of ``--DTC`` text.

    Returns:
        pl.Expr: A struct expression.

    Examples:
        Read the collected hour::

            hours = raw.select(time_groups(pl.col("EXSTDTC")).struct.field("hour"))
    """
    return dtc.str.extract_groups(_TIME).struct.rename_fields(["hour", "minute", "second", "zone"])


def has_time(dtc: pl.Expr) -> pl.Expr:
    """Return True for a value with a complete date and at least hours and minutes.

    Args:
        dtc: An expression of ``--DTC`` text.

    Returns:
        pl.Expr: A boolean expression; null when *dtc* is null.

    Examples:
        Keep the timed records::

            timed = vs.filter(has_time(pl.col("VSDTC")))
    """
    return time_groups(dtc).struct.field("minute").is_not_null()


def datetime_part(dtc: pl.Expr) -> pl.Expr:
    """Return the date-time of a value with a complete date and hours and minutes.

    Seconds default to 0 and a fraction is kept.  A time zone or offset is
    dropped, so the value is the wall clock (as admiral does).  A value with
    no time, or with hours only, gives null: nothing is invented.

    Args:
        dtc: An expression of ``--DTC`` text.

    Returns:
        pl.Expr: A ``pl.Datetime("us")`` expression.

    Examples:
        Compare a timed record with the first dose::

            pre = vs.filter(datetime_part(pl.col("VSDTC")) < pl.col("TRTSDTM"))
    """
    parts = time_groups(dtc)
    text = pl.concat_str(
        date_part(dtc).dt.to_string("%Y-%m-%d"),
        pl.lit("T"),
        parts.struct.field("hour"),
        pl.lit(":"),
        parts.struct.field("minute"),
        pl.lit(":"),
        parts.struct.field("second").fill_null("00"),
    )
    return text.str.to_datetime("%Y-%m-%dT%H:%M:%S%.f", time_unit="us", strict=False)


def is_iso8601(dtc: pl.Expr) -> pl.Expr:
    """Return True for a ``--DTC`` value that SDTMIG 3.4 sections 4.4.1 to 4.4.3 allow.

    Allowed: right truncation (``2021``, ``2021-03``), a hyphen for each
    missing component (``2021---15``, ``-----T08:30``), a time to the
    fraction of a second, ``Z`` or an offset, and an interval of two such
    values (``a/b``).  The ranges of month, day, hour, minute and second
    apply, and a complete date must exist in the calendar.

    Args:
        dtc: An expression of ``--DTC`` text.

    Returns:
        pl.Expr: A boolean expression; null when *dtc* is null.

    Examples:
        Find the values that a submission cannot hold::

            bad = ae.filter(~is_iso8601(pl.col("AESTDTC")))
    """
    one = pl.element()
    valid_one = one.str.contains(_ISO_VALUE) & (
        ~one.str.contains(r"^\d{4}-\d{2}-\d{2}") | date_part(one).is_not_null()
    )
    sides = dtc.str.split("/")
    return (
        pl.when(dtc.is_null())
        .then(None)
        .otherwise((sides.list.len() <= 2) & sides.list.eval(valid_one).list.all())
    )


def refuse_number(name: str, dtype: pl.DataType | None, *, verb: str | None = None) -> None:
    """Raise when a date column holds numbers, because the origin of a number is a guess.

    A SAS date counts days from 1960-01-01 and a SAS date-time counts
    seconds from the same day; Polars counts from 1970-01-01.  The
    message gives both conversions, so the programmer states the origin.

    Args:
        name: The column name, quoted in the message.
        dtype: Its dtype in the frame, or ``None`` when unknown.
        verb: The verb call, quoted at the start of the message.

    Raises:
        DerivationError: When *dtype* is numeric.

    References:
        ADR-0022 (a date verb reads the column type); SAS date and
        date-time values count from 1 January 1960.

    Examples:
        Check a column before day arithmetic::

            refuse_number("BRTHDT", adsl.collect_schema().get("BRTHDT"), verb="age")
    """
    if dtype is None or not dtype.is_numeric():
        return
    where = f"{verb}: " if verb else ""
    raise DerivationError(
        f"{where}{name} is a number ({dtype}), not a date, and Fleet does not guess its "
        f"origin. A SAS date counts days from 1960-01-01: convert it with "
        f"pl.date(1960, 1, 1) + pl.duration(days=pl.col('{name}')). A SAS date-time counts "
        f"seconds: use pl.datetime(1960, 1, 1) + pl.duration(seconds=pl.col('{name}'))."
    )


def to_day(expr: pl.Expr, dtype: pl.DataType | None, *, verb: str | None = None) -> pl.Expr:
    """Reduce a text, date-time or date column to its date, for day arithmetic.

    Text uses :func:`date_part`, a ``pl.Datetime`` its date, and a
    ``pl.Date`` stays as it is (SDTMIG 3.4 section 4.4.4: study day uses
    the date portion).  A number raises (see :func:`refuse_number`).  Any
    other type is returned unchanged.

    Args:
        expr: The column expression.
        dtype: Its dtype in the frame, or ``None`` when unknown.
        verb: The verb call, quoted in the error for a number.

    Returns:
        pl.Expr: A ``pl.Date`` expression for the three temporal sources.

    Raises:
        DerivationError: When *dtype* is numeric.

    Examples:
        Day difference between a timed text and a date::

            days = (to_day(pl.col("AESTDTC"), pl.String) - pl.col("TRTSDT")).dt.total_days()
    """
    if dtype == pl.String:
        return date_part(expr)
    if isinstance(dtype, pl.Datetime):
        return expr.cast(pl.Date)
    refuse_number(
        expr.meta.output_name(raise_if_undetermined=False) or "the column", dtype, verb=verb
    )
    return expr


def warn_on_collect(
    value: pl.Expr,
    problem: pl.Expr,
    describe: Callable[[int, list[str]], str],
    *,
    dtype: pl.DataType,
    shown: pl.Expr | None = None,
) -> pl.Expr:
    """Return *value* unchanged, and warn once at collect when *problem* is true on a row.

    The check runs inside the plan, so the frame stays lazy and the raw
    text that caused the problem is still there.  The warning gives the
    count and the first five distinct values of *shown* (default *value*).

    Args:
        value: The result expression.
        problem: A boolean expression, true on a row that needs the warning.
        describe: Builds the message from the count and the sample values.
        dtype: The dtype of *value*.
        shown: The values to quote in the message, usually the raw text.

    Returns:
        pl.Expr: *value*, with its dtype; alias it to name the column.

    Examples:
        Warn on raw values that did not convert::

            expr = warn_on_collect(
                parsed,
                raw.is_not_null() & parsed.is_null(),
                lambda n, sample: f"{n} value(s) did not convert: {sample}",
                dtype=pl.String,
                shown=raw,
            )
    """
    shown = value if shown is None else shown

    def check(batch: pl.Series) -> pl.Series:
        bad = batch.struct.field("problem").fill_null(False)
        count = int(bad.sum())
        if count:
            sample = (
                batch.struct.field("shown")
                .filter(bad)
                .cast(pl.String)
                .unique(maintain_order=True)
                .head(5)
                .to_list()
            )
            warnings.warn(describe(count, sample), UserWarning, stacklevel=2)
        return batch.struct.field("value")

    return pl.struct(
        value.alias("value"), problem.alias("problem"), shown.alias("shown")
    ).map_batches(check, return_dtype=dtype)
