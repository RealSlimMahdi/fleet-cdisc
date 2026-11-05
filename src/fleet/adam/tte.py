"""Time-to-event (ADTTE) selection engine behind ``df.adam.tte.param()``.

Each event or censor source is a plain Polars frame with the subject keys and
an ``ADT`` column. :func:`select_tte` selects one record per subject: the
first event on or before the first stop date (``CNSR = 0``), else the last
censor record on or before it (``CNSR`` = the key of its frame). It also
returns a decision trace that tells why each record was selected.
"""

from __future__ import annotations

import difflib
import warnings
from typing import Literal

import polars as pl

from fleet.core.exceptions import DerivationError

#: Columns that a source frame carries onto the selected ADTTE row.
CARRIED_COLUMNS = ("EVNTDESC", "CNSDTDSC", "SRCDOM", "SRCVAR", "SRCSEQ")

_ADT = "__tte_date__"
_KIND = "__tte_kind__"
_CNSR = "__tte_cnsr__"
_SRC = "__tte_source__"
_IDX = "__tte_src_idx__"
_START = "__startdt__"
_STOP = "__stopdt__"


def _hint(col: str, available: list[str]) -> str:
    close = difflib.get_close_matches(col, available, n=1)
    return f" Did you mean '{close[0]}'?" if close else ""


def _is_date(dtype: pl.DataType) -> bool:
    return dtype == pl.Date or isinstance(dtype, pl.Datetime)


def _check_columns(where: str, frame: pl.DataFrame, needed: list[str]) -> None:
    for col in needed:
        if col not in frame.columns:
            fix = (
                ' Give the date as ADT, for example adae.select("USUBJID", ADT="ASTDT").'
                if col == "ADT"
                else ""
            )
            raise DerivationError(
                f"{where}: column '{col}' not found.{_hint(col, frame.columns)}{fix} "
                f"Available: {frame.columns[:25]}"
            )


def _check_date(where: str, frame: pl.DataFrame, col: str) -> None:
    dtype = frame.schema[col]
    if not _is_date(dtype):
        raise DerivationError(
            f"{where}: date column '{col}' has dtype {dtype}. Dates must be typed "
            "Date/Datetime. Parse DTC strings first with .date()."
        )


def _candidates(
    label: str,
    kind: Literal["event", "censor"],
    cnsr: int,
    index: int,
    frame: pl.DataFrame,
    keys: list[str],
    stops: pl.DataFrame | None,
    subject_keys: list[str],
    date_dtype: pl.DataType,
) -> pl.DataFrame:
    """One record per subject (and stratum) from one source frame."""
    df = frame.filter(pl.col("ADT").is_not_null()).with_columns(
        pl.col("ADT").cast(date_dtype).alias(_ADT)
    )
    if stops is not None:
        df = (
            df.join(stops, on=subject_keys, how="left", nulls_equal=True)
            .filter(pl.col(_STOP).is_null() | (pl.col(_ADT) <= pl.col(_STOP)))
            .drop(_STOP)
        )
    if df.is_empty():
        return pl.DataFrame()

    if "SRCSEQ" not in df.columns:
        dup = df.group_by(keys + [_ADT]).len().filter(pl.col("len") > 1)
        if dup.height:
            warnings.warn(
                f"TTE source {label}: {dup.height} group(s) have several records on the "
                "selected date and no SRCSEQ column. The record is chosen by a sort on "
                'all columns. Carry SRCSEQ (for example SRCSEQ="AESEQ") to control this.',
                UserWarning,
                stacklevel=4,
            )
    order = ["SRCSEQ"] if "SRCSEQ" in df.columns else []
    residual = sorted(c for c in df.columns if c not in {*keys, _ADT, *order})
    grouped = df.sort(keys + [_ADT] + order + residual).group_by(keys, maintain_order=True)
    picked = grouped.first() if kind == "event" else grouped.last()

    carried = [c for c in CARRIED_COLUMNS if c in df.columns]
    stamps = [
        pl.lit(kind).alias(_KIND),
        pl.lit(cnsr).cast(pl.Int64).alias(_CNSR),
        pl.lit(label).alias(_SRC),
        pl.lit(index).cast(pl.Int64).alias(_IDX),
    ]
    if kind == "event":
        carried = [c for c in carried if c != "EVNTDESC"] + ["EVNTDESC"]
        stamps.append(pl.lit(label).alias("EVNTDESC"))
    return picked.with_columns(stamps).select(keys + [_ADT, _KIND, _CNSR, _SRC, _IDX] + carried)


def _sources(
    events: dict[str, pl.DataFrame | pl.LazyFrame],
    censors: dict[int, pl.DataFrame | pl.LazyFrame],
) -> list[tuple[str, Literal["event", "censor"], int, pl.DataFrame]]:
    if not events:
        raise DerivationError("param() needs at least one event frame in events=.")
    out: list[tuple[str, Literal["event", "censor"], int, pl.DataFrame]] = []
    for label, frame in events.items():
        if not isinstance(label, str) or not label:
            raise DerivationError(
                f"events= keys are the EVNTDESC of each event, a non-empty string. Got {label!r}."
            )
        out.append((label, "event", 0, frame))
    for cnsr, frame in censors.items():
        if isinstance(cnsr, bool) or not isinstance(cnsr, int) or cnsr < 1:
            raise DerivationError(
                f"censors= keys are CNSR values, integers >= 1 (events are CNSR 0). Got {cnsr!r}."
            )
        out.append((f"CNSR {cnsr}", "censor", cnsr, frame))
    for label, _, _, frame in out:
        if not isinstance(frame, pl.DataFrame | pl.LazyFrame):
            raise DerivationError(
                f"TTE source {label}: expected a Polars frame, got {type(frame).__name__}."
            )
    return [
        (lb, kd, cn, fr.collect() if isinstance(fr, pl.LazyFrame) else fr) for lb, kd, cn, fr in out
    ]


def select_tte(
    *,
    universe: pl.DataFrame,
    start: str,
    events: dict[str, pl.DataFrame | pl.LazyFrame],
    censors: dict[int, pl.DataFrame | pl.LazyFrame],
    subject_keys: list[str],
    stop_at: list[str] | None = None,
    by: list[str] | None = None,
    create_datetime: bool = False,
    retain: Literal["drop", "censor_at_start"] = "drop",
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Select one time-to-event record per subject (per stratum).

    The stop date of a subject is the earliest non-null *stop_at* date in
    *universe*. Event and censor records after it are dropped. The first
    event left wins (``CNSR = 0``, ``EVNTDESC`` = its key). A subject
    without an event takes the last censor record left (``CNSR`` = its
    key); on a date tie the censor frame given last wins. A date before the
    start date is set to the start date.

    Args:
        universe: Subject-level frame (ADSL) with *start*, *stop_at* and the
            subject keys.
        start: Date column in *universe* that starts the clock
            (``STARTDT``).
        events: ``EVNTDESC -> frame``. Each frame holds the subject keys
            and ``ADT``.
        censors: ``CNSR -> frame`` (CNSR >= 1). Each frame holds the
            subject keys and ``ADT``; ``EVNTDESC`` comes from a frame
            column, else it is null.
        subject_keys: Subject identifier columns (usually ``["USUBJID"]``).
        stop_at: Date columns in *universe*; the earliest non-null one
            ends the observation of the subject.
        by: Stratum columns, present in every source frame.
        create_datetime: Give ``ADTM``/``STARTDTM`` instead of dates.
        retain: ``"drop"`` (a subject with no record left is dropped with a
            warning) or ``"censor_at_start"`` (censored at ``STARTDT`` with
            ``EVNTDESC = "NO EVENT OBSERVED"``).

    Returns:
        tuple[pl.DataFrame, pl.DataFrame]: The selected rows, and the
            decision trace (one row per candidate: ``kind``, ``source``,
            ``date``, ``selected``, ``reason``).

    Raises:
        DerivationError: On a missing column (with a did-you-mean hint), a
            date column that is not Date/Datetime, or a bad dict key.

    References:
        admiral 1.5 ``derive_param_tte`` (``end_dates``,
        ``event_type = "negative"``); ADR-0043
        (docs/adr/0043-tte-censors-at-the-last-record-before-the-stop-date.md).

    Examples:
        PFS, censored at the last assessment before new therapy::

            rows, trace = select_tte(
                universe=adsl,
                start="TRTSDT",
                events={"PD": adrs.filter(pl.col("AVALC") == "PD")},
                censors={2: adrs.select("USUBJID", "ADT")},
                subject_keys=["USUBJID"],
                stop_at=["EOSDT", "NACTDT"],
            )
    """
    by = by or []
    stop_at = stop_at or []
    sources = _sources(events, censors)
    keys = subject_keys + by

    _check_columns("ADSL", universe, subject_keys + [start, *stop_at])
    for col in [start, *stop_at]:
        _check_date("ADSL", universe, col)

    date_dtype: pl.DataType = pl.Datetime("us") if create_datetime else pl.Date
    base = universe.select(subject_keys + [pl.col(start).cast(date_dtype).alias(_START)]).unique(
        subject_keys, maintain_order=True
    )
    stops = (
        universe.select(
            subject_keys
            + [pl.min_horizontal([pl.col(c).cast(date_dtype) for c in stop_at]).alias(_STOP)]
        ).unique(subject_keys, maintain_order=True)
        if stop_at
        else None
    )

    pools: dict[str, list[pl.DataFrame]] = {"event": [], "censor": []}
    for index, (label, kind, cnsr, frame) in enumerate(sources):
        where = f"TTE {kind} {label}"
        _check_columns(where, frame, keys + ["ADT"])
        _check_date(where, frame, "ADT")
        cand = _candidates(label, kind, cnsr, index, frame, keys, stops, subject_keys, date_dtype)
        if not cand.is_empty():
            pools[kind].append(cand)
    event_pool, censor_pool = (
        pl.concat(pools[k], how="diagonal_relaxed") if pools[k] else pl.DataFrame()
        for k in ("event", "censor")
    )

    def winner(pool: pl.DataFrame, first: bool) -> pl.DataFrame:
        if pool.is_empty():
            return pool
        grouped = pool.sort(keys + [_ADT, _IDX]).group_by(keys, maintain_order=True)
        return grouped.first() if first else grouped.last()

    chosen = winner(event_pool, first=True)
    censor_win = winner(censor_pool, first=False)
    if not censor_win.is_empty():
        extra = (
            censor_win
            if chosen.is_empty()
            else censor_win.join(chosen.select(keys), on=keys, how="anti", nulls_equal=True)
        )
        chosen = extra if chosen.is_empty() else pl.concat([chosen, extra], how="diagonal_relaxed")

    pooled = [p for p in (event_pool, censor_pool) if not p.is_empty()]
    if by and pooled:
        strata = pl.concat([p.select(by) for p in pooled], how="vertical_relaxed").unique(
            maintain_order=True
        )
        base = base.join(strata, how="cross")
    rows = (
        base.join(chosen, on=keys, how="left", nulls_equal=True)
        if not chosen.is_empty()
        else base.with_columns(
            pl.lit(None, dtype=date_dtype).alias(_ADT),
            pl.lit(None, dtype=pl.String).alias(_KIND),
            pl.lit(None, dtype=pl.Int64).alias(_CNSR),
            pl.lit(None, dtype=pl.String).alias(_SRC),
            pl.lit(None, dtype=pl.Int64).alias(_IDX),
        )
    )

    unresolved = rows.filter(pl.col(_KIND).is_null())
    rows = rows.filter(pl.col(_KIND).is_not_null())
    if unresolved.height:
        if retain == "censor_at_start":
            filled = unresolved.with_columns(
                pl.col(_START).alias(_ADT),
                pl.lit("censor").alias(_KIND),
                pl.lit(1).cast(pl.Int64).alias(_CNSR),
                pl.lit("NO EVENT OBSERVED").alias("EVNTDESC"),
                pl.lit("ADSL").alias("SRCDOM"),
                pl.lit(start).alias("SRCVAR"),
            )
            rows = pl.concat([rows, filled], how="diagonal_relaxed") if rows.height else filled
        else:
            ids = unresolved.get_column(subject_keys[-1]).unique(maintain_order=True)
            window = " on or before the first stop_at date" if stop_at else ""
            warnings.warn(
                f"select_tte(): {ids.len()} subject(s) have no event and no censor "
                f"record{window} and were dropped: {ids.head(5).to_list()}"
                f"{' ...' if ids.len() > 5 else ''}. Add a censor frame on the start date "
                f'(for example {{3: adsl.select("USUBJID", ADT="{start}")}}) or use '
                "retain='censor_at_start'.",
                UserWarning,
                stacklevel=3,
            )

    # admiral: ADT = max(ADT, STARTDT).
    floored = (pl.col(_ADT) < pl.col(_START)) & pl.col(_START).is_not_null()
    rows = rows.with_columns(
        floored.fill_null(False).alias("__floored__"),
        pl.when(floored).then(pl.col(_START)).otherwise(pl.col(_ADT)).alias(_ADT),
    )

    trace = _trace(pooled, rows, keys, date_dtype)
    if unresolved.height and retain == "drop":
        dropped = unresolved.select(
            keys
            + [
                pl.lit(None, dtype=pl.String).alias("kind"),
                pl.lit(None, dtype=pl.String).alias("source"),
                pl.lit(None, dtype=date_dtype).alias("date"),
                pl.lit(False).alias("selected"),
                pl.lit("dropped: no event or censor record").alias("reason"),
            ]
        )
        trace = pl.concat([trace, dropped], how="diagonal_relaxed") if trace.height else dropped

    start_name, adt_name = ("STARTDTM", "ADTM") if create_datetime else ("STARTDT", "ADT")
    rows = rows.rename({_START: start_name, _ADT: adt_name, _CNSR: "CNSR"}).drop(
        _KIND, _SRC, _IDX, "__floored__"
    )
    if "STUDYID" in universe.columns and "STUDYID" not in rows.columns:
        study = universe.select(subject_keys + ["STUDYID"]).unique()
        if study.select(subject_keys).is_duplicated().any():
            raise DerivationError(
                f"select_tte(): a subject key {subject_keys} has two STUDYID values in ADSL. "
                'Give subject_keys=["STUDYID", "USUBJID"].'
            )
        rows = rows.join(study, on=subject_keys, how="left", nulls_equal=True).select(
            "STUDYID", pl.exclude("STUDYID")
        )
    return rows, trace


def _trace(
    pooled: list[pl.DataFrame], rows: pl.DataFrame, keys: list[str], date_dtype: pl.DataType
) -> pl.DataFrame:
    """Every candidate per subject, the selected one marked, with the reason."""
    if not pooled:
        return pl.DataFrame()
    winners = rows.select(keys + [_KIND, _IDX, "__floored__"]).with_columns(
        pl.lit(True).alias("selected")
    )
    trace = pl.concat(pooled, how="diagonal_relaxed").join(
        winners, on=keys + [_KIND, _IDX], how="left", nulls_equal=True
    )
    selected = pl.col("selected")
    event = pl.col(_KIND) == "event"
    return trace.with_columns(
        selected.fill_null(False),
        pl.when(selected & event & pl.col("__floored__"))
        .then(pl.lit("earliest event (floored to STARTDT)"))
        .when(selected & event)
        .then(pl.lit("earliest event"))
        .when(selected & pl.col("__floored__"))
        .then(pl.lit("last censor, floored to STARTDT"))
        .when(selected)
        .then(pl.lit("last censor (no event)"))
        .otherwise(pl.lit("not selected"))
        .alias("reason"),
    ).select(
        keys
        + [
            pl.col(_KIND).alias("kind"),
            pl.col(_SRC).alias("source"),
            pl.col(_ADT).cast(date_dtype).alias("date"),
            "selected",
            "reason",
        ]
    )
