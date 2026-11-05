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
from pathlib import Path
from typing import Literal

import polars as pl

from fleet.core.define_spec import load_spec_yaml
from fleet.core.exceptions import DerivationError
from fleet.core.joins import refuse_repeated_keys
from fleet.core.study_context import StudyConfigError, find_study_config, load_study_context

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
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """One record per subject (and stratum) from one source frame.

    Also returns the records after the stop date, for the decision trace.
    """
    df = frame.filter(pl.col("ADT").is_not_null()).with_columns(
        pl.col("ADT").cast(date_dtype).alias(_ADT)
    )
    stamps = [
        pl.lit(kind).alias(_KIND),
        pl.lit(cnsr).cast(pl.Int64).alias(_CNSR),
        pl.lit(label).alias(_SRC),
        pl.lit(index).cast(pl.Int64).alias(_IDX),
    ]
    after = pl.DataFrame()
    if stops is not None:
        df = df.join(stops, on=subject_keys, how="left", nulls_equal=True)
        late = pl.col(_STOP).is_not_null() & (pl.col(_ADT) > pl.col(_STOP))
        after = df.filter(late).with_columns(stamps).select(keys + [_ADT, _KIND, _SRC])
        df = df.filter(~late).drop(_STOP)
    if df.is_empty():
        return pl.DataFrame(), after

    order = ["SRCSEQ"] if "SRCSEQ" in df.columns else []
    dup = df.group_by(keys + [_ADT] + order).len().filter(pl.col("len") > 1)
    if dup.height:
        cols = ", ".join([*keys, "ADT", *order])
        fix = (
            "The record is chosen by a sort on all columns. Carry SRCSEQ (for example "
            'SRCSEQ="AESEQ") to control this.'
            if not order
            else "The record is chosen by a sort on the other columns."
        )
        warnings.warn(
            f"TTE source {label}: {dup.height} group(s) have duplicate records with respect "
            f"to {cols}{'' if order else ' (no SRCSEQ column)'}. {fix}",
            UserWarning,
            stacklevel=4,
        )
    residual = sorted(c for c in df.columns if c not in {*keys, _ADT, *order})
    grouped = df.sort(keys + [_ADT] + order + residual).group_by(keys, maintain_order=True)
    picked = grouped.first() if kind == "event" else grouped.last()

    carried = [c for c in CARRIED_COLUMNS if c in df.columns]
    if kind == "event":
        carried = [c for c in carried if c != "EVNTDESC"] + ["EVNTDESC"]
        stamps.append(pl.lit(label).alias("EVNTDESC"))
    picked = picked.with_columns(stamps).select(keys + [_ADT, _KIND, _CNSR, _SRC, _IDX] + carried)
    return picked, after


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


def param_label(paramcd: str, domain: str = "ADTTE") -> str:
    """Return the PARAM of *paramcd* from the study's controlled terminology.

    The study is the first ``study_config.yaml`` in the working directory
    or above it. The label is the ``decode`` of the *paramcd* item in a
    codelist that a ``PARAMCD`` variable of the ADaM ``define.yaml``
    references (the *domain* dataset first, then the others). ``fleet init
    ct`` writes the CDISC CT preferred terms as these decodes, so a PARAMCD
    in a pinned CDISC CT codelist resolves here too.

    Args:
        paramcd: The parameter code, for example ``"OS"``.
        domain: The dataset whose ``PARAMCD`` codelist is read first.

    Returns:
        str: The decode, for example ``"Overall Survival"``.

    Raises:
        DerivationError: When no source gives a label. The message names
            *paramcd*, the places searched and the fix (``param=``).

    References:
        ADaMIG v1.3, BDS analysis parameter variables: PARAM and PARAMCD
        map one to one. CDISC
        ADaM CT (NCI EVS) has no time-to-event PARAMCD codelist; its
        parameter codelists are questionnaire and scale codes. ADR-0043.

    Examples:
        The label of OS in a study whose ADTTE.PARAMCD has a codelist::

            label = param_label("OS")  # "Overall Survival"
    """
    searched: list[str] = []
    config = find_study_config()
    if config is None:
        searched.append(f"no study_config.yaml in {Path.cwd()} or above it")
    else:
        try:
            define = load_study_context(config).metadata_adam_dir / "define.yaml"
        except StudyConfigError as err:
            searched.append(f"{config} (cannot be read: {err})")
        else:
            label = _define_decode(define, paramcd, domain) if define.is_file() else None
            if label is not None:
                return label
            searched.append(f"the PARAMCD codelists of {define}")
    searched.append("CDISC ADaM CT (it has no time-to-event PARAMCD codelist)")
    raise DerivationError(
        f"param(): no PARAM label for PARAMCD '{paramcd}'. Searched: {'; '.join(searched)}. "
        f'Pass param=, for example param("{paramcd}", "Overall Survival", ...), or add '
        f"'{paramcd}' with a decode to the PARAMCD codelist of {domain} in the ADaM define.yaml."
    )


def _define_decode(define: Path, paramcd: str, domain: str) -> str | None:
    """The decode of *paramcd* in a codelist a PARAMCD variable of *define* references."""
    spec = load_spec_yaml(define.read_text(encoding="utf-8")) or {}
    codelists = {str(cl.get("oid")): cl for cl in spec.get("codelists") or []}
    datasets = sorted(spec.get("datasets") or [], key=lambda ds: ds.get("name") != domain)
    for ds in datasets:
        for var in ds.get("variables") or []:
            if var.get("name") != "PARAMCD" or not var.get("codelist"):
                continue
            for item in codelists.get(str(var["codelist"]), {}).get("items") or []:
                if str(item.get("coded_value")) == paramcd and item.get("decode"):
                    return str(item["decode"])
    return None


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
    key); on a date tie the censor frame given last wins. An event or
    censor date before the start date is set to the start date; the CNSR
    does not change.

    Args:
        universe: Subject-level frame (ADSL) with *start*, *stop_at* and the
            subject keys.
        start: Date column in *universe* that starts the clock
            (``STARTDT``).
        events: ``EVNTDESC -> frame``. Each frame holds the subject keys
            and ``ADT``.
        censors: ``CNSR -> frame`` (CNSR >= 1). Each frame holds the
            subject keys and ``ADT``; ``EVNTDESC`` comes from a frame
            column, else it is null and a warning names the frame.
        subject_keys: Subject identifier columns (usually ``["USUBJID"]``).
        stop_at: Date columns in *universe*; the earliest non-null one
            ends the observation of the subject.
        by: Stratum columns, present in every event frame.  A censor frame
            with none of them (for example from ADSL) is crossed with the
            strata of the event frames; a frame with only some raises.
        create_datetime: Give ``ADTM``/``STARTDTM`` instead of dates.
        retain: ``"drop"`` (a subject with no record left is dropped with a
            warning) or ``"censor_at_start"`` (censored at ``STARTDT`` with
            ``EVNTDESC = "NO EVENT OBSERVED"``).

    ADSL flags of *start* go onto the rows: ``<start>DTF`` as STARTDTF and,
    with *create_datetime*, ``<start>TMF`` as STARTTMF (admiral rules
    ``(DT|DTM)$`` to ``DTF`` and ``DTM$`` to ``TMF``).

    Returns:
        tuple[pl.DataFrame, pl.DataFrame]: The selected rows, and the
            decision trace (one row per candidate: ``kind``, ``source``,
            ``date``, ``selected``, ``reason``; also a row per record after
            the stop date and per subject with no record).

    Raises:
        DerivationError: On a missing column (with a did-you-mean hint), a
            date column that is not Date/Datetime, a bad dict key, a
            *retain* value other than ``"drop"`` or ``"censor_at_start"``,
            or a subject with two different rows in ADSL.

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
    if retain not in ("drop", "censor_at_start"):
        raise DerivationError(
            f"retain={retain!r} is not supported. Choose 'drop' or 'censor_at_start'."
        )
    by = by or []
    stop_at = stop_at or []
    sources = _sources(events, censors)
    keys = subject_keys + by

    no_desc = [lb for lb, kd, _, fr in sources if kd == "censor" and "EVNTDESC" not in fr.columns]
    if no_desc:
        warnings.warn(
            f"TTE censor frame(s) {', '.join(no_desc)} have no EVNTDESC column, so EVNTDESC "
            "is null on their rows. Give the reason of the censoring on the frame, for "
            'example adsl.select("USUBJID", ADT="LSTALVDT", EVNTDESC=pl.lit("ALIVE")).',
            UserWarning,
            stacklevel=3,
        )

    _check_columns("ADSL", universe, subject_keys + [start, *stop_at])
    for col in [start, *stop_at]:
        _check_date("ADSL", universe, col)

    date_dtype: pl.DataType = pl.Datetime("us") if create_datetime else pl.Date
    flags = _start_flags(universe.columns, start, create_datetime)
    adsl = refuse_repeated_keys(
        "param()",
        universe.select(list(dict.fromkeys([*subject_keys, start, *stop_at, *flags]))),
        subject_keys,
        source="ADSL",
    )
    base = adsl.select(
        subject_keys
        + [pl.col(start).cast(date_dtype).alias(_START)]
        + [pl.col(src).alias(dst) for src, dst in flags.items()]
    )
    stops = (
        adsl.select(
            subject_keys
            + [pl.min_horizontal([pl.col(c).cast(date_dtype) for c in stop_at]).alias(_STOP)]
        )
        if stop_at
        else None
    )

    frames = _cross_strata(sources, by, keys)
    pools: dict[str, list[pl.DataFrame]] = {"event": [], "censor": []}
    late: list[pl.DataFrame] = []
    for index, (label, kind, cnsr, frame) in enumerate(frames):
        cand, after = _candidates(
            label, kind, cnsr, index, frame, keys, stops, subject_keys, date_dtype
        )
        if not cand.is_empty():
            pools[kind].append(cand)
        if not after.is_empty():
            late.append(after)
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
    if by and not pooled:
        raise DerivationError(
            f"select_tte(): by={by} is set, but no event or censor record is left in "
            f"{[lb for lb, _, _, _ in sources]}, so no stratum exists. Check the source "
            "frames and the stop_at dates."
        )
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
            fix = (
                f"Add a censor frame: a frame with none of the by columns {by} is crossed "
                f'with the strata, for example {{3: adsl.select("USUBJID", ADT="EOSDT")}}. '
                "retain='censor_at_start' censors them at the start date instead."
                if by
                else "Add a censor frame on the start date "
                f'(for example {{3: adsl.select("USUBJID", ADT="{start}")}}) or use '
                "retain='censor_at_start'."
            )
            warnings.warn(
                f"select_tte(): {ids.len()} subject(s) have no event and no censor "
                f"record{window} and were dropped: {ids.head(5).to_list()}"
                f"{' ...' if ids.len() > 5 else ''}. {fix}",
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
    extra = [
        frame.select(
            keys
            + [
                pl.col(_KIND).alias("kind"),
                pl.col(_SRC).alias("source"),
                pl.col(_ADT).cast(date_dtype).alias("date"),
                pl.lit(False).alias("selected"),
                pl.lit("after the stop date").alias("reason"),
            ]
        )
        for frame in late
    ]
    if unresolved.height:
        kept = retain == "censor_at_start"
        extra.append(
            unresolved.select(
                keys
                + [
                    pl.lit("censor" if kept else None, dtype=pl.String).alias("kind"),
                    pl.lit("ADSL" if kept else None, dtype=pl.String).alias("source"),
                    (pl.col(_START) if kept else pl.lit(None)).cast(date_dtype).alias("date"),
                    pl.lit(kept).alias("selected"),
                    pl.lit(
                        "censored at STARTDT: no record"
                        if kept
                        else "dropped: no event or censor record"
                    ).alias("reason"),
                ]
            )
        )
    if extra:
        trace = pl.concat([trace, *extra] if trace.height else extra, how="diagonal_relaxed")

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


def _start_flags(columns: list[str], start: str, create_datetime: bool) -> dict[str, str]:
    """The imputation flags of *start* in ADSL, as admiral: ``(DT|DTM)$`` to ``DTF``, ``DTM$`` to ``TMF``."""
    import re

    rules = [(r"(DT|DTM)$", "DTF", "STARTDTF")]
    if create_datetime:
        rules.append((r"DTM$", "TMF", "STARTTMF"))
    flags: dict[str, str] = {}
    for pattern, suffix, target in rules:
        name = re.sub(pattern, suffix, start)
        if name != start and name in columns:
            flags[name] = target
    return flags


def _cross_strata(
    sources: list[tuple[str, Literal["event", "censor"], int, pl.DataFrame]],
    by: list[str],
    keys: list[str],
) -> list[tuple[str, Literal["event", "censor"], int, pl.DataFrame]]:
    """Check each source; cross a censor frame with none of the *by* columns with the strata.

    The strata are the *by* values of the event frames (admiral ``derive_param_tte``
    with ``by_vars`` and a censor source from ADSL).
    """
    for label, kind, _, frame in sources:
        where = f"TTE {kind} {label}"
        _check_columns(where, frame, [*keys[: len(keys) - len(by)], "ADT"])
        _check_date(where, frame, "ADT")
    if not by:
        return sources
    events = [fr for _, kd, _, fr in sources if kd == "event" and set(by) <= set(fr.columns)]
    strata = (
        pl.concat([fr.select(by) for fr in events], how="vertical_relaxed").unique(
            maintain_order=True
        )
        if events
        else pl.DataFrame(schema=dict.fromkeys(by, pl.String))
    )
    out = []
    for label, kind, cnsr, frame in sources:
        if kind == "censor" and not set(by) & set(frame.columns):
            frame = frame.join(strata, how="cross")
        else:
            _check_columns(f"TTE {kind} {label}", frame, by)
        out.append((label, kind, cnsr, frame))
    return out


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
