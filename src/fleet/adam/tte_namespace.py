"""ADTTE namespace (``df.adam.tte``) — time-to-event parameter derivation.

One ``.param()`` call per parameter. Each event or censor source is a plain
Polars frame with ``USUBJID`` and ``ADT``::

    adtte = (
        adsl.adam.tte
        .param("OS", "Overall Survival", start="TRTSDT",
               events={"DEATH": adsl.filter(pl.col("DTHFL") == "Y")
                                    .select("USUBJID", ADT="DTHDT")},
               censors={1: adsl.select("USUBJID", ADT="LSTALVDT",
                                       EVNTDESC=pl.lit("ALIVE"))})
        .aval(unit="days")
        .seq("ASEQ", order_by=["PARAMCD"])
        .to_frame()
    )
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import polars as pl

from fleet.adam._mixins import SharedADaMVerbsMixin
from fleet.adam.tte import param_label, select_tte
from fleet.core.dtc import to_day
from fleet.core.exceptions import DerivationError

logger = logging.getLogger("fleet")

#: Days per unit — CDISC conventions (SDTMIG/ADaMIG durations).
_UNIT_DAYS: dict[str, float] = {
    "days": 1.0,
    "weeks": 7.0,
    "months": 30.4375,
    "years": 365.25,
}


class TTENamespace(SharedADaMVerbsMixin):
    """
    Immutable pipeline builder for ADTTE (time-to-event) derivations.

    Inherits shared verbs from ``SharedADaMVerbsMixin``; each verb returns a
    new ``TTENamespace``; ``to_frame()`` materialises the result.
    """

    _domain = "ADTTE"

    # ------------------------------------------------------------------ #
    # 1. param — derive one TTE parameter (admiral derive_param_tte)       #
    # ------------------------------------------------------------------ #

    def param(
        self,
        paramcd: str,
        param: str | None = None,
        *,
        start: str,
        events: dict[str, pl.DataFrame | pl.LazyFrame],
        censors: dict[int, pl.DataFrame | pl.LazyFrame] | None = None,
        stop_at: list[str] | None = None,
        by: list[str] | None = None,
        set_values_to: dict[str, Any] | None = None,
        subject_keys: list[str] | None = None,
        create_datetime: bool = False,
        retain: Literal["drop", "censor_at_start"] = "drop",
        explain: bool = False,
    ) -> TTENamespace:
        """Derive one time-to-event parameter and append its rows.

        Each source is a plain frame with the subject keys and ``ADT``.
        The stop date of a subject is the earliest non-null *stop_at* date
        in ADSL; event and censor records after it are dropped. The first
        event left wins: ``CNSR = 0`` and ``EVNTDESC`` = its key. A subject
        without an event is censored at the last censor record left:
        ``CNSR`` = its key (on a date tie, the frame given last wins). A
        subject with no record left is dropped with a warning. ``STARTDT``
        comes from ADSL (the pinned ADSL, else the base frame). An event or
        censor date before it is set to it (admiral: ADT = max(ADT,
        STARTDT)); the CNSR does not change. AVAL comes from :meth:`aval`.

        A source frame may also carry ``EVNTDESC`` (censors only),
        ``CNSDTDSC``, ``SRCDOM``, ``SRCVAR`` and ``SRCSEQ``; they go onto the
        selected row, and ``SRCSEQ`` breaks a tie on one date. A censor
        frame without an ``EVNTDESC`` column gives a null ``EVNTDESC`` and a
        warning that names the frame: the reason of the censoring is study
        text, so Fleet does not invent it.

        Without *param* (and without PARAM in *set_values_to*), PARAM is
        the decode of *paramcd* in the study CT: the codelist of the
        ``PARAMCD`` variable in the ADaM ``define.yaml`` of the first
        ``study_config.yaml`` in the working directory or above it (ADTTE
        first). CDISC ADaM CT has no time-to-event PARAMCD codelist. If no
        decode is found, ``param()`` raises and names the places searched.

        For a favorable event (admiral ``event_type = "positive"``), censor
        at the stop date: add ``{1: adsl.select("USUBJID",
        ADT=pl.min_horizontal("EOSDT", "NACTDT"))}`` to *censors*.

        The first ``param()`` call replaces the pipeline frame with the
        derived rows; later calls append, so one chain builds the whole
        ADTTE. STUDYID is carried from ADSL as the first column. Other ADSL
        variables come from ``join_adsl()`` after the last ``param()``.

        Args:
            paramcd: PARAMCD of the new parameter.
            param: PARAM label (or give PARAM in *set_values_to*). When
                neither is given, the study CT gives it (see above).
            start: Date column in ADSL that starts the clock (``STARTDT``).
            events: ``EVNTDESC -> frame`` of event records.
            censors: ``CNSR -> frame`` of censor records (CNSR >= 1).
            stop_at: Date columns in ADSL. The earliest non-null one ends
                the observation: records after it are dropped.
            by: Stratum columns, present in every source frame. Give a
                per-stratum PARAMCD as an expression in *set_values_to*.
            set_values_to: Extra constant or expression columns on the new
                rows (PARAMN, PARCAT1, ...). A static PARAMCD with several
                strata raises (1:1 guard).
            subject_keys: Subject identifiers (default: the ADSL pin's join
                key, usually ``["USUBJID"]``).
            create_datetime: Give ``ADTM``/``STARTDTM`` instead of dates.
            retain: ``"drop"`` (admiral, warns) or ``"censor_at_start"``
                for a subject with no record.
            explain: Log the decision trace per subject (every candidate,
                the selected one and the reason) through the fleet logger.

        Returns:
            TTENamespace: A fresh namespace whose frame contains the
                accumulated ADTTE rows; call ``.to_frame()`` to materialise.

        Raises:
            DerivationError: On unknown columns (with did-you-mean), date
                columns that are not Date/Datetime, bad dict keys, PARAMCD
                collisions, by-group 1:1 violations, or no PARAM label.

        References:
            admiral 1.5 ``derive_param_tte`` (``end_dates``,
            ``event_type = "negative"``: records after the first end date
            are not used; ADT = max(ADT, STARTDT); ``censor_source`` has no
            default EVNTDESC). ADaM BDS-TTE v1.0: EVNTDESC is permissible
            free text with no codelist. ADaMIG v1.3: PARAM and PARAMCD map
            one to one. ADR-0043
            (docs/adr/0043-tte-censors-at-the-last-record-before-the-stop-date.md).

        Examples:
            PFS censored at the last assessment before new therapy::

                last_assessment = adrs.select(
                    "USUBJID", "ADT", EVNTDESC=pl.lit("NO PROGRESSION"),
                    CNSDTDSC=pl.lit("LAST ASSESSMENT"),
                )
                adtte = (
                    adsl.adam.tte
                    .param(
                        "PFS",
                        "Progression-Free Survival",
                        start="TRTSDT",
                        events={"PD": adrs.filter(pl.col("AVALC") == "PD")},
                        censors={2: last_assessment, 3: adsl.select("USUBJID", ADT="TRTSDT")},
                        stop_at=["EOSDT", "NACTDT"],
                    )
                    .aval(unit="days")
                    .to_frame()
                )
        """
        base = self.to_frame()
        pinned = getattr(self, "_pinned", {})
        universe = pinned["ADSL"][0] if "ADSL" in pinned else base
        keys = subject_keys or (self._pin_join_key("ADSL") if "ADSL" in pinned else ["USUBJID"])
        if param is None and "PARAM" not in (set_values_to or {}):
            if "PARAMCD" in (set_values_to or {}):
                raise DerivationError(
                    "param(): PARAMCD comes from set_values_to, so give PARAM there too."
                )
            param = param_label(paramcd, self._domain)

        rows, trace = select_tte(
            universe=universe,
            start=start,
            events=events,
            censors=censors or {},
            stop_at=stop_at,
            subject_keys=keys,
            by=by,
            create_datetime=create_datetime,
            retain=retain,
        )

        # Parameter identity + extra metadata.
        rows = rows.with_columns(pl.lit(paramcd).alias("PARAMCD"))
        if param is not None:
            rows = rows.with_columns(pl.lit(param).alias("PARAM"))
        for name, value in (set_values_to or {}).items():
            expr = value if isinstance(value, pl.Expr) else pl.lit(value)
            rows = rows.with_columns(expr.alias(name))

        # by-strata 1:1 guard: PARAMCD must uniquely identify a stratum.
        if by:
            n_combos = rows.select(["PARAMCD", *by]).unique().height
            n_params = rows.select("PARAMCD").unique().height
            if n_params < n_combos:
                raise DerivationError(
                    f"param(): PARAMCD is constant across {n_combos} {by} strata — "
                    "the PARAMCD ↔ parameter mapping must be 1:1. Derive PARAMCD "
                    "per stratum via an expression in set_values_to."
                )

        if explain and not trace.is_empty():
            with pl.Config(
                tbl_hide_dataframe_shape=True, tbl_hide_column_data_types=True, tbl_rows=-1
            ):
                logger.info("TTE decision trace — %s (%s):\n%s", paramcd, param or "", trace)

        # Accumulate: a base frame that already carries PARAMCD holds prior
        # ADTTE rows → append (with collision guard); otherwise replace.
        if "PARAMCD" in base.columns and base.height:
            if (base.get_column("PARAMCD") == paramcd).any():
                raise DerivationError(
                    f"param(): PARAMCD '{paramcd}' already exists in the dataset — "
                    "the PARAMCD ↔ PARAM mapping must stay one-to-one."
                )
            for c in base.columns:
                if c not in rows.columns:
                    rows = rows.with_columns(pl.lit(None).cast(base.schema[c]).alias(c))
            for c in rows.columns:
                if c not in base.columns:
                    base = base.with_columns(pl.lit(None).cast(rows.schema[c]).alias(c))
            combined = pl.concat([base, rows.select(base.columns)], how="vertical_relaxed")
        else:
            combined = rows

        new = self._materialise_then(combined)
        if "ADSL" not in pinned and "PARAMCD" not in base.columns:
            # The base frame was ADSL: later param(), join_adsl() and km_data() read it.
            new = new.pin("ADSL", universe, join_on=keys)
        from fleet.core.lineage import record_lineage

        record_lineage(
            new,
            (pl.col(start).alias(paramcd),),
            verb="param",
            params={
                "param": param,
                "events": list(events),
                "censors": [f"CNSR {c}" for c in censors or {}],
                "stop_at": list(stop_at or []),
            },
        )
        return new

    # ------------------------------------------------------------------ #
    # 2. aval — analysis value + unit from STARTDT/ADT                     #
    # ------------------------------------------------------------------ #

    def aval(
        self,
        *,
        unit: Literal["days", "weeks", "months", "years"] = "days",
        add_one: bool = True,
        avalu: bool = True,
    ) -> TTENamespace:
        """Derive ``AVAL`` (and ``AVALU``) from ``STARTDT``/``ADT``.

        ``AVAL = (ADT − STARTDT [+ 1 day]) / unit`` using the CDISC
        conventions (7, 30.4375, 365.25 days per week/month/year).  The
        ``+ 1`` inclusive convention matches admiral's
        ``derive_vars_duration(add_one=TRUE)``.  Each row takes its end as
        the date of ``ADTM``, else ``ADT``, and its start as the date of
        ``STARTDTM``, else ``STARTDT``, so one chain can mix date and
        date-time parameters.

        Args:
            unit: Output unit (default ``"days"``).
            add_one: Include both endpoints (CDISC day convention).
            avalu: Also stamp the ``AVALU`` unit variable (default True —
                a required BDS variable admiral leaves to the user).

        Returns:
            TTENamespace: The namespace with ``AVAL`` (and ``AVALU``)
                appended; call ``.to_frame()`` to materialise.

        Examples:
            Analysis value in months::

                adtte = (
                    adsl.adam.tte
                    .param("OS", "Overall Survival", start="TRTSDT",
                           events={"DEATH": adsl.filter(pl.col("DTHFL") == "Y")
                                                .select("USUBJID", ADT="DTHDT")},
                           censors={1: adsl.select("USUBJID", ADT="LSTALVDT",
                                                   EVNTDESC=pl.lit("ALIVE"))})
                    .aval(unit="months")
                    .to_frame()
                )
        """
        if unit not in _UNIT_DAYS:
            raise DerivationError(
                f"aval() unit={unit!r} is not supported. Choose one of {sorted(_UNIT_DAYS)}."
            )
        schema = self._lazy.collect_schema()

        def day(*names: str) -> pl.Expr:
            present = [
                to_day(pl.col(n), schema.get(n), verb="aval").cast(pl.Date)
                for n in names
                if n in schema.names()
            ]
            return pl.coalesce(present) if present else pl.lit(None, dtype=pl.Date)

        days = (day("ADTM", "ADT") - day("STARTDTM", "STARTDT")).dt.total_days()
        if add_one:
            days = pl.when(days >= 0).then(days + 1).otherwise(days)
        exprs = [(days / _UNIT_DAYS[unit]).alias("AVAL")]
        if avalu:
            exprs.append(pl.lit(unit.upper()).alias("AVALU"))
        return self._chain(*exprs, verb="aval")

    # ------------------------------------------------------------------ #
    # 3. km_data — bridge to the Python survival stack                     #
    # ------------------------------------------------------------------ #

    def km_data(
        self,
        paramcd: str | None = None,
        *,
        by: list[str] | None = None,
    ) -> pl.DataFrame:
        """Return the ``(duration, event)`` frame survival libraries consume.

        ``duration = AVAL`` and ``event = CNSR == 0`` — exactly the inputs of
        ``lifelines.KaplanMeierFitter.fit`` / scikit-survival, with optional
        grouping columns carried through.  No new dependency: just the shape.

        Args:
            paramcd: Restrict to one parameter (required when the frame
                holds several).
            by: Grouping columns to carry (e.g. ``["TRT01P"]``).  Columns
                not present on the ADTTE rows are pulled from the pinned
                ADSL automatically.

        Returns:
            pl.DataFrame: ``USUBJID | duration | event [| by...]``.

        Raises:
            DerivationError: When AVAL/CNSR are missing (call ``aval()``
                first) or several parameters are present and *paramcd* is
                not given.

        Examples:
            Fit a KM curve per treatment arm::

                km = adtte_ns.km_data("OS", by=["TRT01P"])
                # lifelines: kmf.fit(km["duration"], km["event"])
        """
        df = self.to_frame()
        missing = [c for c in ("AVAL", "CNSR") if c not in df.columns]
        if missing:
            raise DerivationError(
                f"km_data(): missing column(s) {missing} — derive them with "
                "param() and aval() first."
            )
        if paramcd is not None:
            df = df.filter(pl.col("PARAMCD") == paramcd)
        elif "PARAMCD" in df.columns and df.get_column("PARAMCD").n_unique() > 1:
            raise DerivationError(
                "km_data(): several parameters present — pass paramcd= to pick one."
            )

        # Group columns absent from the ADTTE rows resolve from the pinned
        # ADSL (the admiral template's post-hoc derive_vars_merged, built in).
        needed = [c for c in (by or []) if c not in df.columns]
        if needed:
            pinned = getattr(self, "_pinned", {})
            if "ADSL" not in pinned:
                raise DerivationError(
                    f"km_data(): column(s) {needed} not on the ADTTE rows and no "
                    "ADSL is pinned to resolve them — pin ADSL or join_adsl() first."
                )
            adsl_df, join_on = pinned["ADSL"]
            missing = [c for c in needed if c not in adsl_df.columns]
            if missing:
                raise DerivationError(
                    f"km_data(): column(s) {missing} not found on the ADTTE rows "
                    "nor in the pinned ADSL."
                )
            df = df.join(
                adsl_df.select(list(join_on) + needed),
                on=list(join_on),
                how="left",
                nulls_equal=True,
            )

        cols = [
            pl.col("USUBJID"),
            pl.col("AVAL").alias("duration"),
            (pl.col("CNSR") == 0).alias("event"),
        ]
        return df.select(cols + [pl.col(c) for c in (by or [])])
