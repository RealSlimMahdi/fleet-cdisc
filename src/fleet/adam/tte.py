"""Time-to-event (ADTTE) source models, prebuilt library, and selection engine.

Implements the admiral ``derive_param_tte`` architecture the Fleet way:

- :class:`EventSource` / :class:`CensorSource` — typed, validated Pydantic
  descriptions of where an event/censoring candidate lives (``dataset`` is a
  **pin nickname** resolved against the pipeline's pinned frames).
- A prebuilt library porting admiral's ``tte_source_objects`` (``DEATH_EVENT``,
  ``AE_EVENT``, ...), browsable as a DataFrame via
  :func:`prebuilt_sources_frame`.
- :func:`select_tte` — the pure selection engine: per subject, the earliest
  event wins (CNSR=0); otherwise the latest censoring record (CNSR≥1).

Unlike admiral's opaque quosure objects, every layer here is inspectable as a
DataFrame: sources render via ``to_polars()`` / :func:`sources_frame`, and the
engine returns a per-subject decision **trace** explaining every selection.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from typing import Any, Literal

import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from fleet.core.exceptions import DerivationError

# ------------------------------------------------------------------ #
# Source models                                                        #
# ------------------------------------------------------------------ #


class TTESource(BaseModel):
    """Base description of a time-to-event candidate source.

    Each field carries its own ``description`` (rendered by mkdocstrings) —
    Pydantic fields are not ``__init__`` parameters, so a docstring ``Args:``
    section would confuse griffe.  In ``set``, plain values (including
    strings) are **literals**; pass a ``pl.Expr`` (e.g. ``pl.col("AESEQ")``)
    to reference source columns — ``EVNTDESC="DEATH"`` is never read as a
    column lookup.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    dataset: str = Field(
        min_length=1,
        description='Pin nickname of the frame to scan (e.g. "ADSL", "ADAE") — '
        "attach frames with .pin(name, df).",
    )
    date: str = Field(
        min_length=1,
        description="Date column in that frame (must be Date/Datetime typed; "
        "parse DTC strings with .date() first).",
    )
    where: str | pl.Expr | None = Field(
        default=None,
        description="Optional filter selecting which records qualify "
        "(string expression or pl.Expr).",
    )
    order: list[str] | None = Field(
        default=None,
        description="Tie-break columns when several records share the "
        'selected date (e.g. ["AESEQ"]).',
    )
    set: dict[str, Any] = Field(
        default_factory=dict,
        description="Constant/derived columns stamped on the output row when "
        "this source is selected. SRCDOM/SRCVAR/SRCSEQ are auto-stamped from "
        "dataset/date/order unless overridden here.",
    )

    @property
    def kind(self) -> str:
        """``"event"`` or ``"censor"``."""
        return "censor" if isinstance(self, CensorSource) else "event"

    @property
    def label(self) -> str:
        """Human-readable identifier used in error messages and traces."""
        desc = self.set.get("EVNTDESC")
        return str(desc) if isinstance(desc, str) else f"{self.kind}({self.dataset}.{self.date})"

    def to_polars(self) -> pl.DataFrame:
        """Render the source definition as a one-row DataFrame.

        Returns:
            pl.DataFrame: Columns ``kind``, ``dataset``, ``date``, ``where``,
                ``order``, ``censor``, ``set`` — the inspectable answer to
                "what does this source actually select?".

        Examples:
            Review a source before using it::

                from fleet.adam.tte import DEATH_EVENT

                print(DEATH_EVENT.to_polars())
        """
        return pl.DataFrame(
            {
                "kind": [self.kind],
                "dataset": [self.dataset],
                "date": [self.date],
                "where": [str(self.where) if self.where is not None else None],
                "order": [", ".join(self.order) if self.order else None],
                "censor": [self.censor if isinstance(self, CensorSource) else None],
                "set": [", ".join(f"{k}={v!r}" for k, v in self.set.items()) or None],
            },
            schema_overrides={
                "where": pl.String,
                "order": pl.String,
                "censor": pl.Int64,
                "set": pl.String,
            },
        )


class EventSource(TTESource):
    """A source of **event** records — the earliest one per subject wins (CNSR=0)."""


class CensorSource(TTESource):
    """A source of **censoring** records — the latest one per subject is used
    when no event exists."""

    censor: int = Field(
        default=1,
        ge=1,
        description="Value written to CNSR when this source is selected "
        "(must be ≥ 1 — events are implicitly 0).",
    )


def sources_frame(*sources: TTESource) -> pl.DataFrame:
    """Stack any mix of sources into one inspectable definition table.

    Args:
        *sources: Event and/or censor sources.

    Returns:
        pl.DataFrame: One row per source (see ``TTESource.to_polars``).

    Examples:
        Review a study's TTE source library::

            from fleet.adam.tte import sources_frame, DEATH_EVENT, LASTALIVE_CENSOR

            print(sources_frame(DEATH_EVENT, LASTALIVE_CENSOR))
    """
    if not sources:
        raise DerivationError("sources_frame() requires at least one source.")
    return pl.concat([s.to_polars() for s in sources], how="vertical")


# ------------------------------------------------------------------ #
# Prebuilt library (ported from admiral R/tte_sources.R)               #
# ------------------------------------------------------------------ #

DEATH_EVENT = EventSource(
    dataset="ADSL",
    where='pl.col("DTHFL") == "Y"',
    date="DTHDT",
    set={"EVNTDESC": "DEATH"},
)
LASTALIVE_CENSOR = CensorSource(
    dataset="ADSL",
    date="LSTALVDT",
    set={"EVNTDESC": "ALIVE"},
)
AE_EVENT = EventSource(
    dataset="ADAE",
    where='pl.col("TRTEMFL") == "Y"',
    date="ASTDT",
    order=["AESEQ"],
    set={"EVNTDESC": "ADVERSE EVENT"},
)
AE_SER_EVENT = EventSource(
    dataset="ADAE",
    where='(pl.col("TRTEMFL") == "Y") & (pl.col("AESER") == "Y")',
    date="ASTDT",
    order=["AESEQ"],
    set={"EVNTDESC": "SERIOUS ADVERSE EVENT"},
)
AE_SEV_EVENT = EventSource(
    dataset="ADAE",
    where='(pl.col("TRTEMFL") == "Y") & (pl.col("AESEV") == "SEVERE")',
    date="ASTDT",
    order=["AESEQ"],
    set={"EVNTDESC": "SEVERE ADVERSE EVENT"},
)
AE_WD_EVENT = EventSource(
    dataset="ADAE",
    where='(pl.col("TRTEMFL") == "Y") & (pl.col("AEACN") == "DRUG WITHDRAWN")',
    date="ASTDT",
    order=["AESEQ"],
    set={"EVNTDESC": "ADVERSE EVENT LEADING TO DRUG WITHDRAWAL"},
)
_AE_GRADE_EVENTS = {
    f"AE_GR{g}_EVENT": EventSource(
        dataset="ADAE",
        where=f'(pl.col("TRTEMFL") == "Y") & (pl.col("ATOXGR") == "{g}")',
        date="ASTDT",
        order=["AESEQ"],
        set={"EVNTDESC": f"GRADE {g} ADVERSE EVENT"},
    )
    for g in range(1, 6)
}
AE_GR1_EVENT = _AE_GRADE_EVENTS["AE_GR1_EVENT"]
AE_GR2_EVENT = _AE_GRADE_EVENTS["AE_GR2_EVENT"]
AE_GR3_EVENT = _AE_GRADE_EVENTS["AE_GR3_EVENT"]
AE_GR4_EVENT = _AE_GRADE_EVENTS["AE_GR4_EVENT"]
AE_GR5_EVENT = _AE_GRADE_EVENTS["AE_GR5_EVENT"]
AE_GR35_EVENT = EventSource(
    dataset="ADAE",
    where='(pl.col("TRTEMFL") == "Y") & pl.col("ATOXGR").is_in(["3", "4", "5"])',
    date="ASTDT",
    order=["AESEQ"],
    set={"EVNTDESC": "GRADE 3-5 ADVERSE EVENT"},
)

#: The ported admiral prebuilt registry — name → source.
PREBUILT_SOURCES: dict[str, TTESource] = {
    "DEATH_EVENT": DEATH_EVENT,
    "LASTALIVE_CENSOR": LASTALIVE_CENSOR,
    "AE_EVENT": AE_EVENT,
    "AE_SER_EVENT": AE_SER_EVENT,
    "AE_SEV_EVENT": AE_SEV_EVENT,
    "AE_WD_EVENT": AE_WD_EVENT,
    **_AE_GRADE_EVENTS,
    "AE_GR35_EVENT": AE_GR35_EVENT,
}


def prebuilt_sources_frame() -> pl.DataFrame:
    """Browse the prebuilt source library as a DataFrame.

    Returns:
        pl.DataFrame: One row per prebuilt source with a leading ``name``
            column (the importable constant name).

    Examples:
        List every shipped TTE source::

            from fleet.adam.tte import prebuilt_sources_frame

            print(prebuilt_sources_frame())
    """
    rows = [
        src.to_polars()
        .with_columns(pl.lit(name).alias("name"))
        .select("name", pl.all().exclude("name"))
        for name, src in PREBUILT_SOURCES.items()
    ]
    return pl.concat(rows, how="vertical")


# ------------------------------------------------------------------ #
# Selection engine                                                     #
# ------------------------------------------------------------------ #

_ADT = "__tte_date__"
_KIND = "__tte_kind__"
_CNSR = "__tte_cnsr__"
_SRC_IDX = "__tte_src_idx__"


def _parse(expr: str | pl.Expr) -> pl.Expr:
    from fleet.sdtm.utils import parse_expression

    return expr if isinstance(expr, pl.Expr) else parse_expression(str(expr))


def _validate_source_columns(
    source: TTESource, frame: pl.DataFrame, subject_keys: list[str], by: list[str]
) -> None:
    """Fail at declaration time with did-you-mean hints — never mid-engine."""
    import difflib

    available = frame.columns
    needed: list[tuple[str, str]] = [("date", source.date)]
    needed += [("order", c) for c in (source.order or [])]
    needed += [("subject key", c) for c in subject_keys]
    needed += [("by", c) for c in by]
    if source.where is not None:
        expr = _parse(source.where)
        try:
            needed += [("where", c) for c in expr.meta.root_names()]
        except Exception:  # pragma: no cover - unresolvable roots
            pass
    for key, value in source.set.items():
        if isinstance(value, pl.Expr):
            try:
                needed += [(f"set[{key}]", c) for c in value.meta.root_names()]
            except Exception:  # pragma: no cover - unresolvable roots
                pass

    for role, col in needed:
        if col not in available:
            close = difflib.get_close_matches(col, available, n=1)
            hint = f" Did you mean '{close[0]}'?" if close else ""
            raise DerivationError(
                f"TTE source '{source.label}' on pin {source.dataset}: {role} column "
                f"'{col}' not found.{hint} Available: {available[:25]}"
            )

    dtype = frame.schema[source.date]
    if dtype not in (pl.Date,) and not isinstance(dtype, pl.Datetime):
        raise DerivationError(
            f"TTE source '{source.label}' on pin {source.dataset}: date column "
            f"'{source.date}' has dtype {dtype} — dates must be typed Date/Datetime. "
            "Parse DTC strings first with .date()."
        )


def _candidates(
    source: TTESource,
    index: int,
    frame: pl.DataFrame,
    subject_keys: list[str],
    by: list[str],
    create_datetime: bool,
) -> pl.DataFrame:
    """One selected record per subject(+stratum) for a single source."""
    keys = subject_keys + by
    df = frame
    if source.where is not None:
        df = df.filter(_parse(source.where))
    df = df.filter(pl.col(source.date).is_not_null())
    if df.is_empty():
        return pl.DataFrame()

    order = source.order or []
    if not order:
        dup = df.group_by(keys + [source.date]).len().filter(pl.col("len") > 1)
        if dup.height:
            warnings.warn(
                f"TTE source '{source.label}': {dup.height} group(s) have several "
                f"records on the selected date and no order= tie-break — resolving "
                "deterministically by full-row sort. Add order= to control this.",
                UserWarning,
                stacklevel=4,
            )
    # Deterministic regardless of input row order: after date+order, break any
    # remaining ties on every other column (sorted by name).
    residual = sorted(c for c in df.columns if c not in {*keys, source.date, *order})
    df = df.sort(keys + [source.date] + order + residual)
    grouped = df.group_by(keys, maintain_order=True)
    picked = grouped.first() if source.kind == "event" else grouped.last()

    date_expr = pl.col(source.date)
    date_expr = date_expr.cast(pl.Datetime("us")) if create_datetime else date_expr.cast(pl.Date)

    stamped: list[pl.Expr] = [
        date_expr.alias(_ADT),
        pl.lit(source.kind).alias(_KIND),
        pl.lit(0 if source.kind == "event" else source.censor).cast(pl.Int64).alias(_CNSR),
        pl.lit(index).cast(pl.Int64).alias(_SRC_IDX),
    ]
    # Auto traceability: SRCDOM/SRCVAR/SRCSEQ from what the source already
    # declares; explicit set= entries override.
    set_spec: dict[str, Any] = {
        "SRCDOM": pl.lit(source.dataset),
        "SRCVAR": pl.lit(source.date),
        **({"SRCSEQ": pl.col(source.order[0])} if source.order else {}),
        **source.set,
    }
    for name, value in set_spec.items():
        # Strings (and other plain values) are literals; only pl.Expr
        # references source columns — EVNTDESC="DEATH" must never be read
        # as a column lookup.
        expr = value if isinstance(value, pl.Expr) else pl.lit(value)
        stamped.append(expr.alias(name))

    picked = picked.with_columns(stamped)
    payload = [c for c in set_spec]
    return picked.select(keys + [_ADT, _KIND, _CNSR, _SRC_IDX] + payload)


def select_tte(
    *,
    universe: pl.DataFrame,
    start_date: str,
    events: list[EventSource],
    censors: list[CensorSource],
    resolve: Callable[[str], pl.DataFrame],
    subject_keys: list[str],
    by: list[str] | None = None,
    end_dates: list[CensorSource] | None = None,
    event_type: Literal["negative", "positive"] = "negative",
    create_datetime: bool = False,
    retain: Literal["drop", "censor_at_start"] = "drop",
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Select one TTE record per subject (per stratum) — the pure engine.

    Selection rule (admiral parity): pool the FIRST record per subject from
    every event source and keep the EARLIEST → CNSR=0.  Subjects without an
    event take the LATEST record pooled from the censor sources → CNSR≥1.
    ``end_dates`` sources close the observation window: the earliest end date
    invalidates later events and takes precedence over ordinary censoring.
    Dates before the start date are floored to it.

    Args:
        universe: Subject-level frame (ADSL) supplying the population and
            *start_date*.
        start_date: Column in *universe* holding the time origin.
        events: Ordered event sources.
        censors: Ordered censor sources.
        resolve: ``pin nickname → DataFrame`` resolver.
        subject_keys: Subject identifier columns (usually ``["USUBJID"]``).
        by: Optional stratification columns (must exist in every source
            frame) — one output row per subject per stratum.
        end_dates: Censor sources whose EARLIEST date truncates the window.
        event_type: ``"positive"`` requires *end_dates* (favorable events —
            subjects without one are censored at the window end).
        create_datetime: Emit ``ADTM``/``STARTDTM`` (µs) instead of dates.
        retain: ``"drop"`` (admiral parity — subjects with no event and no
            censor record are dropped, with a warning) or
            ``"censor_at_start"`` (kept, censored at STARTDT with
            ``EVNTDESC="NO EVENT OBSERVED"``).

    Returns:
        tuple[pl.DataFrame, pl.DataFrame]: ``(rows, trace)`` — the selected
            TTE rows, and the per-candidate decision trace
            (``kind | SRCDOM | date | selected | reason`` per subject).

    Raises:
        DerivationError: On unknown columns (with did-you-mean), string-typed
            date columns, missing by-columns, or ``event_type="positive"``
            without *end_dates*.
    """
    by = by or []
    if not events:
        raise DerivationError("select_tte() requires at least one event source.")
    if event_type not in ("negative", "positive"):
        raise DerivationError(
            f"select_tte() event_type={event_type!r} is not supported. "
            "Choose 'negative' or 'positive'."
        )
    if event_type == "positive" and not end_dates:
        raise DerivationError("event_type='positive' requires end_dates= sources.")
    if start_date not in universe.columns:
        import difflib

        close = difflib.get_close_matches(start_date, universe.columns, n=1)
        hint = f" Did you mean '{close[0]}'?" if close else ""
        raise DerivationError(f"start_date column '{start_date}' not found in ADSL.{hint}")

    date_dtype = pl.Datetime("us") if create_datetime else pl.Date
    base = universe.select(
        subject_keys + [pl.col(start_date).cast(date_dtype).alias("__startdt__")]
    ).unique(subject_keys)

    def pool(sources: list[TTESource], offset: int = 0) -> pl.DataFrame:
        frames = []
        for i, src in enumerate(sources):
            frame = resolve(src.dataset)
            _validate_source_columns(src, frame, subject_keys, by)
            cand = _candidates(src, offset + i, frame, subject_keys, by, create_datetime)
            if not cand.is_empty():
                frames.append(cand)
        if not frames:
            return pl.DataFrame()
        return pl.concat(frames, how="diagonal_relaxed")

    keys = subject_keys + by
    event_pool = pool(list(events))
    censor_pool = pool(list(censors), offset=len(events))
    end_pool = pool(list(end_dates or []), offset=len(events) + len(censors))

    # Winners: earliest event / latest censor / earliest window end.
    def winner(candidates: pl.DataFrame, earliest: bool) -> pl.DataFrame:
        if candidates.is_empty():
            return candidates
        picked = candidates.sort(
            keys + [_ADT, _SRC_IDX], descending=[False] * len(keys) + [not earliest, False]
        )
        return picked.group_by(keys, maintain_order=True).first()

    event_win = winner(event_pool, earliest=True)
    end_win = winner(end_pool, earliest=True)

    # Window truncation: an event after the subject's end date does not count.
    if not event_win.is_empty() and not end_win.is_empty():
        event_win = event_win.join(
            end_win.select(keys + [pl.col(_ADT).alias("__end__")]), on=keys, how="left"
        )
        event_win = event_win.filter(
            pl.col("__end__").is_null() | (pl.col(_ADT) <= pl.col("__end__"))
        ).drop("__end__")

    censor_win = winner(censor_pool, earliest=False)

    # Precedence: event → window-end censor → ordinary censor.
    chosen = event_win
    for fallback in (end_win, censor_win):
        if fallback.is_empty():
            continue
        taken = chosen.select(keys).unique() if not chosen.is_empty() else None
        extra = fallback if taken is None else fallback.join(taken, on=keys, how="anti")
        chosen = extra if chosen.is_empty() else pl.concat([chosen, extra], how="diagonal_relaxed")

    # Universe join: STARTDT, strata expansion, and retain policy.
    if by:
        strata = (
            pl.concat(
                [p.select(by) for p in (event_pool, censor_pool, end_pool) if not p.is_empty()],
                how="vertical_relaxed",
            ).unique()
            if not (event_pool.is_empty() and censor_pool.is_empty() and end_pool.is_empty())
            else pl.DataFrame()
        )
        base = base.join(strata, how="cross") if not strata.is_empty() else base
    rows = (
        base.join(chosen, on=keys, how="left")
        if not chosen.is_empty()
        else base.with_columns(
            pl.lit(None, dtype=date_dtype).alias(_ADT),
            pl.lit(None, dtype=pl.String).alias(_KIND),
            pl.lit(None, dtype=pl.Int64).alias(_CNSR),
            pl.lit(None, dtype=pl.Int64).alias(_SRC_IDX),
        )
    )

    unresolved = rows.filter(pl.col(_KIND).is_null())
    rows = rows.filter(pl.col(_KIND).is_not_null())
    if unresolved.height:
        if retain == "censor_at_start":
            filled = unresolved.with_columns(
                pl.col("__startdt__").alias(_ADT),
                pl.lit("censor").alias(_KIND),
                pl.lit(1).cast(pl.Int64).alias(_CNSR),
                pl.lit("NO EVENT OBSERVED").alias("EVNTDESC"),
                pl.lit("ADSL").alias("SRCDOM"),
                pl.lit(start_date).alias("SRCVAR"),
            )
            rows = pl.concat([rows, filled], how="diagonal_relaxed") if rows.height else filled
        else:
            warnings.warn(
                f"select_tte(): {unresolved.height} subject(s) have no event and no "
                "censoring record and were dropped. Use retain='censor_at_start' "
                "or add an ADSL censor source to keep them.",
                UserWarning,
                stacklevel=3,
            )

    # Floor dates before the time origin to the origin (admiral parity).
    floored = (pl.col(_ADT) < pl.col("__startdt__")) & pl.col("__startdt__").is_not_null()
    rows = rows.with_columns(
        floored.fill_null(False).alias("__floored__"),
        pl.when(floored).then(pl.col("__startdt__")).otherwise(pl.col(_ADT)).alias(_ADT),
    )

    # Decision trace — every pooled candidate, with the winner marked.
    trace_pool = (
        pl.concat(
            [p for p in (event_pool, censor_pool, end_pool) if not p.is_empty()],
            how="diagonal_relaxed",
        )
        if not (event_pool.is_empty() and censor_pool.is_empty() and end_pool.is_empty())
        else pl.DataFrame()
    )
    if not trace_pool.is_empty():
        winners = rows.select(keys + [_ADT, _KIND, _SRC_IDX, "__floored__"]).with_columns(
            pl.lit(True).alias("selected")
        )
        trace = trace_pool.join(winners, on=keys + [_KIND, _SRC_IDX], how="left", suffix="_w")
        trace = trace.with_columns(
            pl.col("selected").fill_null(False),
            pl.when(pl.col("selected") & (pl.col(_KIND) == "event") & pl.col("__floored__"))
            .then(pl.lit("earliest event (floored to STARTDT)"))
            .when(pl.col("selected") & (pl.col(_KIND) == "event"))
            .then(pl.lit("earliest event"))
            .when(pl.col("selected") & pl.col("__floored__"))
            .then(pl.lit("latest censor, floored to STARTDT"))
            .when(pl.col("selected"))
            .then(pl.lit("latest censor (no event)"))
            .otherwise(pl.lit("not selected"))
            .alias("reason"),
        ).select(
            keys
            + [
                pl.col(_KIND).alias("kind"),
                pl.col("SRCDOM"),
                pl.col(_ADT).alias("date"),
                "selected",
                "reason",
            ]
        )
    else:
        trace = pl.DataFrame()
    if unresolved.height and retain == "drop":
        dropped = unresolved.select(
            keys
            + [
                pl.lit(None, dtype=pl.String).alias("kind"),
                pl.lit(None, dtype=pl.String).alias("SRCDOM"),
                pl.lit(None, dtype=date_dtype).alias("date"),
                pl.lit(False).alias("selected"),
                pl.lit("dropped: no event or censor record").alias("reason"),
            ]
        )
        trace = pl.concat([trace, dropped], how="diagonal_relaxed") if trace.height else dropped

    # Final shape.
    start_name = "STARTDTM" if create_datetime else "STARTDT"
    adt_name = "ADTM" if create_datetime else "ADT"
    rows = rows.rename({"__startdt__": start_name, _ADT: adt_name, _CNSR: "CNSR"}).drop(
        _KIND, _SRC_IDX, "__floored__"
    )
    return rows, trace
