"""ADTTE namespace (``df.adam.tte``) — time-to-event parameter derivation.

One ``.param()`` call per parameter, sources described by typed
:class:`~fleet.adam.tte.EventSource` / :class:`~fleet.adam.tte.CensorSource`
objects, source frames resolved through the **pin** system::

    adtte = (
        adsl.adam.tte.pin("ADSL", adsl).pin("ADAE", adae)
        .param("OS", "Overall Survival", start_date="TRTSDT",
               events=[DEATH_EVENT], censors=[LASTALIVE_CENSOR])
        .param("TTAE", "Time to First AE", start_date="TRTSDT",
               events=[AE_EVENT], censors=[EOS_CENSOR])
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
from fleet.adam.tte import CensorSource, EventSource, select_tte
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
        param: str,
        *,
        start_date: str,
        events: list[EventSource],
        censors: list[CensorSource] | None = None,
        end_dates: list[CensorSource] | None = None,
        event_type: Literal["negative", "positive"] = "negative",
        by: list[str] | None = None,
        set_values_to: dict[str, Any] | None = None,
        subject_keys: list[str] | None = None,
        create_datetime: bool = False,
        retain: Literal["drop", "censor_at_start"] = "drop",
        explain: bool = False,
    ) -> TTENamespace:
        """Derive one time-to-event parameter and append its rows.

        Per subject: the EARLIEST record pooled from *events* wins
        (``CNSR=0``); otherwise the LATEST record pooled from *censors*
        (``CNSR`` = the source's censor value).  ``STARTDT`` comes from the
        pinned ADSL (or the base frame when ADSL is not pinned); dates before
        it are floored to it.  ``SRCDOM``/``SRCVAR``/``SRCSEQ`` are stamped
        automatically from each source's declaration (override via the
        source's ``set=``).  AVAL is derived separately by :meth:`aval`.

        The first ``param()`` call replaces the pipeline frame with the
        derived rows (the base frame is the subject universe, not output
        rows); subsequent calls append, so one chain builds the whole ADTTE.

        Args:
            paramcd: PARAMCD for the new parameter (may be an expression
                string when *by* is used, e.g. ``'"TTAE" + pl.col("AEDECOD")'``
                is not needed — pass a pl.Expr in *set_values_to* instead).
            param: PARAM label.
            start_date: Time-origin column in ADSL (→ ``STARTDT``).
            events: Ordered event sources (highest priority first).
            censors: Ordered censoring sources.
            end_dates: Censor sources whose EARLIEST date closes the
                observation window (events after it do not count; it takes
                precedence over ordinary censoring).
            event_type: ``"positive"`` for favorable events — requires
                *end_dates*; subjects without the event censor at the window
                end.
            by: Stratification columns (must exist in every source frame) —
                one parameter row per subject per stratum; use expressions in
                *set_values_to* for per-stratum PARAMCD/PARAM.
            set_values_to: Extra constant/expression columns on the new rows
                (PARAMN, PARCAT1, ...). Expressions may reference *by*
                columns; a static PARAMCD with several strata raises (1:1
                guard).
            subject_keys: Subject identifiers (default: the ADSL pin's join
                key, usually ``["USUBJID"]``).
            create_datetime: Emit ``ADTM``/``STARTDTM`` instead of dates.
            retain: ``"drop"`` (admiral parity, warns) or
                ``"censor_at_start"`` for subjects with no event and no
                censor record.
            explain: Log the per-subject decision trace (every candidate,
                the winner, and the reason) through the fleet logger.

        Returns:
            TTENamespace: A fresh namespace whose frame contains the
                accumulated ADTTE rows; call ``.to_frame()`` to materialise.

        Raises:
            DerivationError: On unknown columns (with did-you-mean), string
                date columns, PARAMCD collisions, or by-group 1:1 violations.

        Examples:
            Overall survival from prebuilt sources::

                from fleet.adam.tte import DEATH_EVENT, LASTALIVE_CENSOR

                adtte = (
                    adsl.adam.tte.pin("ADSL", adsl)
                    .param("OS", "Overall Survival", start_date="TRTSDT",
                           events=[DEATH_EVENT], censors=[LASTALIVE_CENSOR])
                    .aval(unit="days")
                    .to_frame()
                )
        """
        base = self.to_frame()
        universe = self._pinned["ADSL"][0] if "ADSL" in getattr(self, "_pinned", {}) else base
        keys = subject_keys or (
            self._pin_join_key("ADSL") if "ADSL" in getattr(self, "_pinned", {}) else ["USUBJID"]
        )

        def resolve(name: str) -> pl.DataFrame:
            pinned = getattr(self, "_pinned", {})
            if name.upper() in pinned:
                return pinned[name.upper()][0]
            if name.upper() == "ADSL":
                return universe
            raise DerivationError(
                f"TTE source dataset '{name}' is not pinned. Pinned: "
                f"{sorted(pinned) or 'none'}. Attach it with .pin({name!r}, df)."
            )

        rows, trace = select_tte(
            universe=universe,
            start_date=start_date,
            events=events,
            censors=censors or [],
            end_dates=end_dates,
            event_type=event_type,
            resolve=resolve,
            subject_keys=keys,
            by=by,
            create_datetime=create_datetime,
            retain=retain,
        )

        # Parameter identity + extra metadata.
        rows = rows.with_columns(pl.lit(paramcd).alias("PARAMCD"), pl.lit(param).alias("PARAM"))
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
                logger.info("TTE decision trace — %s (%s):\n%s", paramcd, param, trace)

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
        from fleet.core.lineage import record_lineage

        record_lineage(
            new,
            (pl.col(start_date).alias(paramcd),),
            verb="param",
            params={
                "param": param,
                "events": [e.label for e in events],
                "censors": [c.label for c in censors or []],
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
                    adsl.adam.tte.pin("ADSL", adsl)
                    .param("OS", "Overall Survival", start_date="TRTSDT",
                           events=[DEATH_EVENT], censors=[LASTALIVE_CENSOR])
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
