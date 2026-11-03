"""
SDTM Polars namespace extension.

Registers ``df.sdtm`` on every Polars DataFrame and ``lf.sdtm`` on every
LazyFrame (``pl.scan_parquet(...).sdtm`` chains fully lazily).

Usage
-----
    import fleet  # triggers registration

    result = (
        raw_df.sdtm
        .assign("USUBJID", source="patient_number")
        .assign("SEX", source="sex", ct=SEX)
        .date("BRTHDTC", source="birth_date")
        .assign("DOMAIN", value="DM")
        .to_frame()
    )

    # Or spec-driven:
    result = raw_df.sdtm.from_spec("examples/cdiscpilot01/sdtm/define.yaml", dataset="DM").to_frame()

Discover every available verb programmatically with ``df.sdtm.verbs()``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import polars as pl

from fleet.core._flag_mixin import FlagCriterionMixin
from fleet.core._pin_mixin import PinMixin
from fleet.core._verb_mixin import SharedVerbsMixin
from fleet.core.define_spec import load_define_spec
from fleet.core.dtc import date_part, datetime_part, warn_on_collect
from fleet.core.exceptions import DerivationError
from fleet.sdtm._tdd_mixin import TrialDesignMixin
from fleet.sdtm.models import NSVMeta
from fleet.sdtm.utils import (
    TIME_LITERAL,
    bad_time,
    dtc_date_expr,
    dtc_text,
    dtc_with_time,
    guessed_values,
    parse_expression,
)


@pl.api.register_dataframe_namespace("sdtm")
@pl.api.register_lazyframe_namespace("sdtm")
class SDTMNamespace(SharedVerbsMixin, PinMixin, FlagCriterionMixin, TrialDesignMixin):
    """
    Immutable pipeline builder for SDTM derivations.

    Each verb appends to a lazy expression list; `to_frame()` materialises
    everything in one ``with_columns`` call.  Accepts both ``pl.DataFrame``
    and ``pl.LazyFrame`` inputs, so scanned sources stay lazy end-to-end.
    """

    # -- SharedVerbsMixin configuration --
    _STUDY_DAY_REF_COL: str = "RFSTDTC"
    _STUDY_DAY_REF_PIN: str = "DM"
    _SEQ_DEFAULT_GROUPS: list[str] = ["STUDYID", "USUBJID"]

    _FK_RULES: dict[str, dict[str, str]] = {
        "USUBJID": {"pin": "DM", "ref_col": "USUBJID"},
        "VISITNUM": {"pin": "TV", "ref_col": "VISITNUM"},
        "VISIT": {"pin": "TV", "ref_col": "VISIT"},
        "EPOCH": {"pin": "TE", "ref_col": "EPOCH"},
        "ETCD": {"pin": "TE", "ref_col": "ETCD"},
    }

    def __init__(self, df: pl.DataFrame | pl.LazyFrame) -> None:
        self._lazy = df.lazy()
        self._nsv_meta: list[NSVMeta] = []
        self._domain: str | None = None
        self._pinned: dict[str, tuple[pl.DataFrame, list[str]]] = {}
        self._pin_lineage: list = []
        self._pending_fk_checks: list[tuple[str, str, str, str]] = []

    # ------------------------------------------------------------------ #
    # assign / case_when are inherited from SharedVerbsMixin.             #
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # 3. date — unified date verb                                          #
    # ------------------------------------------------------------------ #

    def date(
        self,
        target: str,
        *,
        source: str | None = None,
        value: str | None = None,
        output: str | None = None,
        time: str | None = None,
        impute: str = "first",
        impute_time: str | None = None,
        highest: str | None = None,
        flag: bool | str = True,
        min_date: str | None = None,
        max_date: str | None = None,
        format: str | None = None,
    ) -> SDTMNamespace:
        """Parse, convert, impute, and flag a date or datetime column.

        Dispatches behavior based on the CDISC suffix of *target* (DTC, DT,
        DTM) or an explicit *output* override.

        For DTC targets: converts raw text to ISO 8601 and never guesses.
        A valid ISO 8601 value stays as it is, partial dates included
        (SDTMIG 3.4 section 4.4).  ``YYYYMMDD``, ``DD-MON-YYYY``,
        ``DD MON YYYY`` and ``DDMONYYYY`` convert with no *format*.  A slash
        date or a two-digit year raises until *format* names the layout.
        Any other value becomes null, with one warning at collect that
        gives the count and the first values.  With *time*, a blank time
        leaves the date alone, a partial date takes a hyphen for each
        missing component (``2021-03--T08:30``), and a time with no date
        gives ``-----T08:30`` (SDTMIG 3.4 section 4.4.2).  Imputation
        parameters are ignored.

        For DT/DTM targets: delegates to the shared imputation engine.

        Args:
            target: Name of the output column.
            source: Column name to read values from.  Mutually exclusive
                with *value*.
            value: Literal date value to broadcast.  Mutually exclusive
                with *source*.
            output: Explicit output type: ``"dtc"``, ``"dt"``, or ``"dtm"``.
            time: Time column or literal to combine with date (DTM/DTC).
            impute: Imputation strategy (DT/DTM only).
            impute_time: Time-part imputation override (DTM only).
            highest: Imputation ceiling (DT/DTM only).
            flag: DTF/TMF flag control.
            min_date: Lower bound for an imputed date.  Applies only when
                the bound is inside the possible range of the partial value;
                a complete date never changes.  DT targets only.
            max_date: Upper bound for an imputed date, with the same rule.
            format: ``strptime`` layout of the raw text (DTC only), e.g.
                ``"%m/%d/%Y"``.  Use ``%y`` for a two-digit year: it reads
                00-69 as 20xx and 70-99 as 19xx.

        Returns:
            SDTMNamespace: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Parse raw date to ISO 8601 DTC::

                ae = (
                    raw_df.sdtm
                    .date("AESTDTC", source="ae_start_date")
                    .to_frame()
                )

            Custom input format::

                ae = (
                    raw_df.sdtm
                    .date("AEENDTC", source="ae_end_date",
                          format="%d/%m/%Y")
                    .to_frame()
                )
        """
        from fleet.adam.utils import _resolve_output_type, impute_and_flag

        # Validate source / value mutual exclusivity
        if source is not None and value is not None:
            raise DerivationError("Cannot specify both source= and value=. Choose one.")
        if source is None and value is None:
            raise DerivationError("Must specify either source= or value=.")

        output_type = _resolve_output_type(target, output)

        # value= path
        if value is not None:
            if flag is True:
                flag = False
            exprs = impute_and_flag(None, target, value=value, output_type=output_type, flag=flag)
            return self._chain(*exprs, verb="date")

        # source= path
        assert source is not None

        if output_type == "dtc":
            return self._dtc(target, source, time=time, format=format)

        # DT/DTM: delegate to imputation engine
        if time is not None and output_type != "dtm":
            raise DerivationError(
                f"time= parameter is only valid for DTM targets, "
                f"but target '{target}' resolves to output='{output_type}'."
            )

        # DTM + time=: combine date source with explicit time column/literal
        if time is not None and output_type == "dtm":
            return self._dtm_with_time(
                source=source,
                target=target,
                time=time,
                impute_time=impute_time,
                flag=flag,
                format=format,
            )

        exprs = impute_and_flag(
            source,
            target,
            output_type=output_type,
            impute=impute,
            impute_time=impute_time,
            highest=highest,
            min_date=min_date,
            max_date=max_date,
            flag=flag,
        )
        return self._chain(*exprs, verb="date")

    def _dtc(
        self, target: str, source: str, *, time: str | None, format: str | None
    ) -> SDTMNamespace:
        """``--DTC`` text from raw text: ISO 8601 or null, never a guess, with warnings."""
        raw = pl.col(source)
        guessed = guessed_values(raw, input_format=format).fill_null(False)
        sample = (
            self._lazy.select(raw.cast(pl.String).filter(guessed).unique(maintain_order=True))
            .head(3)
            .collect()
            .to_series()
            .to_list()
        )
        if sample and format is None:
            raise DerivationError(
                f"date('{target}'): {source} needs a guess to become a date (the order of day "
                "and month, or the century of a two-digit year). Name the layout with "
                "format='%m/%d/%Y' (month first) or format='%d/%m/%Y' (day first); for a "
                "two-digit year use %y, which reads 00-69 as 20xx and 70-99 as 19xx. "
                f"Values: {sample}"
            )
        if sample:
            raise DerivationError(
                f"date('{target}', format='{format}'): {source} gives a year before 1000 with "
                f"this layout, so the year has two digits: use %y in place of %Y. Values: {sample}"
            )

        text = dtc_text(raw, input_format=format)
        given = raw.cast(pl.String).str.strip_chars().fill_null("") != ""
        value = warn_on_collect(
            text,
            given & text.is_null(),
            lambda n, values: (
                f"date('{target}'): {n} value(s) of {source} are not ISO 8601 and could not be "
                f"converted, so {target} is null for them (SDTMIG 3.4 section 4.4.1). Name the "
                f"layout with format=. Values: {values}"
            ),
            dtype=pl.String,
            shown=raw.cast(pl.String),
        )
        if time is not None:
            raw_time = pl.lit(time) if TIME_LITERAL.match(time) else pl.col(time)
            value = warn_on_collect(
                dtc_with_time(value, raw, raw_time),
                bad_time(raw_time),
                lambda n, values: (
                    f"date('{target}'): {n} time value(s) of {time} are not hh:mm[:ss], so "
                    f"{target} keeps the date only. Values: {values}"
                ),
                dtype=pl.String,
                shown=raw_time.cast(pl.String),
            )
        return self._chain(value.alias(target), verb="date")

    def _dtm_with_time(
        self,
        source: str,
        target: str,
        time: str,
        impute_time: str | None,
        flag: bool | str,
        format: str | None,
    ) -> SDTMNamespace:
        """Combine a date column with an explicit time column or literal into DTM.

        When *time* is a column reference that does not exist in the current
        schema, raises ``ValueError``.  For rows where the time column is null,
        falls back to the *impute_time* strategy.
        """
        from fleet.adam.utils import _resolve_flag_names, _resolve_time

        _TIME_LITERAL_RE = re.compile(r"^\d{2}:\d{2}(:\d{2})?$")
        time_is_literal = bool(_TIME_LITERAL_RE.match(time))

        # Validate column existence when time is a column reference
        if not time_is_literal:
            schema_cols = self._lazy.collect_schema().names()
            if time not in schema_cols:
                raise DerivationError(
                    f"time='{time}' column not found in the DataFrame. "
                    f"Available columns: {schema_cols}"
                )

        # Resolve fallback for null time values
        fallback_strategy = impute_time or "first"
        fallback_time = _resolve_time(fallback_strategy)

        # Build time expression: literal broadcast or column reference
        if time_is_literal:
            # Pad HH:MM → HH:MM:SS
            padded = time if len(time) == 8 else time + ":00"
            time_expr = pl.lit(padded)
        else:
            # Column reference: pad HH:MM → HH:MM:SS, fallback for nulls
            raw_time = pl.col(time).cast(pl.String)
            padded_time = (
                pl.when(raw_time.str.len_chars() == 5)
                .then(raw_time + pl.lit(":00"))
                .otherwise(raw_time)
            )
            if fallback_time is None:
                # impute_time="none" → null when time column is null
                time_expr = padded_time
            elif isinstance(fallback_time, str) and fallback_time.startswith("T"):
                time_expr = (
                    pl.when(raw_time.is_null())
                    .then(pl.lit(fallback_time[1:]))
                    .otherwise(padded_time)
                )
            else:
                # fallback is a column name
                time_expr = (
                    pl.when(raw_time.is_null())
                    .then(pl.col(fallback_time).cast(pl.String))
                    .otherwise(padded_time)
                )

        # Parse the date source column
        date_expr = dtc_date_expr(source, "__dtm_date_tmp__", input_format=format)

        # Combine date + time → Datetime
        combined = (
            (pl.col("__dtm_date_tmp__") + pl.lit("T") + time_expr)
            .str.to_datetime("%Y-%m-%dT%H:%M:%S", strict=False)
            .alias(target)
        )

        # Materialise and clean up temp column
        df = self._lazy.with_columns(date_expr).collect()
        result = df.with_columns(combined)
        if "__dtm_date_tmp__" in result.columns:
            result = result.drop("__dtm_date_tmp__")

        # Flags: DTF from source precision, TMF is null (time was observed)
        dtf_name, tmf_name = _resolve_flag_names(target, flag, "dtm")
        if dtf_name is not None:
            from fleet.adam.utils import dtf_expr

            result = result.with_columns(dtf_expr(source, dtf_name))
        if tmf_name is not None:
            result = result.with_columns(pl.lit(None, dtype=pl.String).alias(tmf_name))

        return self._materialise_then(result)

    # ------------------------------------------------------------------ #
    # 5b. nsv — Non-Standard Variable (qualifier) derivation               #
    # ------------------------------------------------------------------ #

    def nsv(
        self,
        target: str,
        *,
        source: str | None = None,
        value: Any | None = None,
        label: str,
        origin: str = "Derived",
        evaluator: str | None = None,
    ) -> SDTMNamespace:
        """Derive a Non-Standard Variable with qualifier metadata.

        Behaves like ``assign(source=...)`` (when *source* is given) or
        ``assign(value=...)`` (when *value* is given) but additionally
        registers SUPPQUAL metadata (label, origin, evaluator) on the
        pipeline.  Use ``export_supp()`` to produce the vertical SUPPQUAL
        structure for SDTM IG ≤3.4.  For IG 3.5+, NSVs remain in the
        parent domain via ``to_frame()`` unchanged.

        Args:
            target: Name of the qualifier variable (becomes QNAM in SUPP).
            source: Name of the raw column to copy from.  Mutually
                exclusive with *value*.
            value: A literal value to broadcast.  Mutually exclusive with
                *source*.
            label: Human-readable label (becomes QLABEL in SUPP).
            origin: Variable origin (becomes QORIG in SUPP) — the
                Define-XML 2.1 vocabulary shared with ``origin:`` in a
                define.yaml (``Collected``, ``Derived``, ``Assigned``,
                ``Protocol``, ``Predecessor``).
            evaluator: Optional evaluator (becomes QEVAL in SUPP).

        Returns:
            SDTMNamespace: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Derive population flag NSVs for DM::

                dm = (
                    raw_df.sdtm
                    .assign("DOMAIN", value="DM")
                    .assign("USUBJID", source="patient_number")
                    .nsv("SAFETY", source="safety_flag",
                         label="Safety Population Flag")
                    .nsv("ITT", source="itt_flag",
                         label="Intent to Treat Population Flag")
                    .to_frame()
                )
        """
        if source is None and value is None:
            raise DerivationError("nsv() requires either 'source' or 'value'.")
        if source is not None and value is not None:
            raise DerivationError("nsv() accepts 'source' or 'value', not both.")

        expr = pl.col(source).alias(target) if source else pl.lit(value).alias(target)
        new = self._chain(expr, verb="nsv")
        # Copy-on-write: avoid mutating shared list across copies
        new._nsv_meta = [
            *self._nsv_meta,
            NSVMeta(target=target, label=label, origin=origin, evaluator=evaluator),
        ]
        return new

    # ------------------------------------------------------------------ #
    # 5c. study_day is inherited from SharedVerbsMixin (one shared        #
    # implementation; `dm=` / `adsl=` are documented ref_df aliases).     #
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # 5d. baseline_flag — last pre-reference-date observation flag        #
    # ------------------------------------------------------------------ #

    def baseline_flag(
        self,
        target: str,
        *,
        date_col: str,
        testcd_col: str | None = None,
        ref_col: str = "RFSTDTC",
        ref_pin: str = "DM",
        dm: pl.DataFrame | None = None,
        by: list[str] | None = None,
        result_col: str | None = None,
        order_by: str | list[str] | None = None,
    ) -> SDTMNamespace:
        """Flag the last observation with a result before the reference date as baseline.

        Sets *target* to ``"Y"`` for one record (per subject and optional
        grouping variables): the last record with a result strictly before
        the reference date/time, and ``null`` for all other records.  A
        record on the reference date is eligible only when it and the
        reference both have a time and the record time is earlier; a record
        on that date with no time is not eligible, because it may follow
        the dose (SDTMIG "prior to"; sdtm.oak ``derive_blfl``).  Among
        eligible records the latest date, then the latest time, wins.

        A record has a result when *result_col* is not null or blank and
        ``--STAT`` (when present) is not ``"NOT DONE"``.  When ``--ORRES`` is
        present and is not *result_col*, it must hold a value too, unless
        ``--DRVFL`` is ``"Y"`` (CG0553).  A tie on the last date and time
        goes to the last record by *order_by*, then input order, as SAS
        ``LAST.`` after PROC SORT; with no *order_by* the tie is broken by
        ``--SEQ`` (when present) and a warning names the groups.

        Args:
            target: Name of the output flag variable
                (e.g. ``"VSBLFL"``).
            date_col: Column containing the observation date
                (e.g. ``"VSDTC"``).
            testcd_col: Optional test code column to group by
                (e.g. ``"VSTESTCD"``).  When set, baseline is
                computed independently for each test.
            ref_col: Reference date column in DM (default ``"RFSTDTC"``).
            ref_pin: Pinned domain for the reference date
                (default ``"DM"``).
            dm: Optional explicit DataFrame override.
            by: Additional grouping columns beyond USUBJID and
                *testcd_col*, such as ``--CAT``, ``--SCAT``, ``--SPEC`` and
                ``--METHOD``.
            result_col: Result column (default ``--STRESC`` when present,
                else ``--ORRES``; the prefix comes from *target*).
            order_by: Column(s) that break a tie on the last date and time
                (default ``--SEQ`` when present).

        Returns:
            SDTMNamespace: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Raises:
            DerivationError: When no result column is found or named.

        References:
            SDTMIG 3.4, ``--LOBXFL``: the last non-missing value prior to
            RFXSTDTC; CDISC CORE FB2603/FB2604 (one flag per group);
            admiral ``ad_advs.R`` order (ADT, VISITNUM, VSSEQ).

        Examples:
            Flag baseline vital signs::

                vs = (
                    vs_raw.sdtm
                    .assign("DOMAIN", value="VS")
                    .assign("USUBJID", source="patient_number")
                    .assign("VSTESTCD", source="vstestcd")
                    .assign("VSORRES", source="vsresult")
                    .date("VSDTC", source="vs_date")
                    .pin("DM", dm_df)
                    .baseline_flag("VSBLFL", date_col="VSDTC",
                                   testcd_col="VSTESTCD")
                    .to_frame()
                )
        """
        import warnings

        from fleet.core.lineage import record_pin_lineage

        df = self._lazy.collect()

        prefix = next(
            (target[: -len(s)] for s in ("LOBXFL", "BLFL") if target.endswith(s) and target != s),
            target[:2],
        )
        if result_col is None:
            candidates = (f"{prefix}STRESC", f"{prefix}ORRES")
            result_col = next((c for c in candidates if c in df.columns), None)
            if result_col is None:
                raise DerivationError(
                    f"baseline_flag('{target}'): neither {candidates[0]} nor {candidates[1]} "
                    "is in the frame. Name the result column with result_col=."
                )
        elif result_col not in df.columns:
            raise DerivationError(
                f"baseline_flag('{target}'): result_col={result_col!r} is not in the frame."
            )

        # Resolve reference date
        if dm is not None:
            ref_df = dm
            join_key = ["USUBJID"]
        elif ref_col in df.columns:
            ref_df = None
            join_key = []
        else:
            ref_df = self._require_pin(ref_pin.upper(), "baseline_flag", columns=[ref_col])
            join_key = self._pin_join_key(ref_pin.upper())

        # Join reference if needed
        _ref_tmp = f"__pin_{ref_col}__"
        if ref_df is not None:
            ref_slim = ref_df.select(
                [c for c in dict.fromkeys(join_key + [ref_col]) if c in ref_df.columns]
            ).unique(subset=join_key if join_key else None)
            ref_slim = ref_slim.rename({ref_col: _ref_tmp})
            df = df.join(ref_slim, on=join_key, how="left", nulls_equal=True)
            ref_col_name = _ref_tmp
        else:
            ref_col_name = ref_col

        # Build grouping keys
        grp_keys = ["USUBJID"]
        if testcd_col is not None:
            grp_keys.append(testcd_col)
        if by:
            grp_keys.extend(by)
        grp_keys = list(dict.fromkeys(grp_keys))

        # Last record strictly before the reference (Q1 B, 2026-11-02): on the reference
        # date a record is eligible only when both times are known and it is earlier.
        def day_and_time(name: str) -> tuple[pl.Expr, pl.Expr]:
            dtype = df.schema[name]
            if dtype == pl.String:
                return date_part(pl.col(name)), datetime_part(pl.col(name))
            if isinstance(dtype, pl.Datetime):
                return pl.col(name).cast(pl.Date), pl.col(name).cast(pl.Datetime("us"))
            return pl.col(name), pl.lit(None, dtype=pl.Datetime("us"))

        day, time = day_and_time(date_col)
        ref_day, ref_time = day_and_time(ref_col_name)
        before_ref = (day < ref_day) | ((day == ref_day) & (time < ref_time))

        has_result = pl.col(result_col).is_not_null()
        if df.schema[result_col] == pl.String:
            has_result = has_result & (pl.col(result_col).str.strip_chars() != "")
        stat_col, orres_col, drvfl_col = f"{prefix}STAT", f"{prefix}ORRES", f"{prefix}DRVFL"
        if stat_col in df.columns:
            has_result = has_result & (pl.col(stat_col).fill_null("") != "NOT DONE")
        if orres_col in df.columns and orres_col != result_col:
            orres_ok = pl.col(orres_col).cast(pl.String).str.strip_chars().fill_null("") != ""
            if drvfl_col in df.columns:
                orres_ok = orres_ok | (pl.col(drvfl_col).fill_null("") == "Y")
            has_result = has_result & orres_ok

        eligible = before_ref.fill_null(False) & has_result.fill_null(False)
        key = pl.coalesce(time, day.cast(pl.Datetime("us")))
        df = df.with_row_index("__bl_row__").with_columns(
            pl.when(eligible).then(key).alias("__bl_key__"),
        )

        if order_by is not None:
            tie_cols = [order_by] if isinstance(order_by, str) else list(order_by)
        else:
            tie_cols = [c for c in (f"{prefix}SEQ",) if c in df.columns]
        last_day = (
            df.filter(pl.col("__bl_key__").is_not_null())
            .filter(pl.col("__bl_key__") == pl.col("__bl_key__").max().over(grp_keys))
            .sort(["__bl_key__", *tie_cols, "__bl_row__"], descending=True, nulls_last=True)
            .group_by(grp_keys, maintain_order=True)
            .agg(pl.col("__bl_row__").first().alias("__bl_win__"), pl.len().alias("__bl_n__"))
        )
        n_ties = last_day.filter(pl.col("__bl_n__") > 1).height
        if n_ties and order_by is None:
            rule = f"the last {tie_cols[0]}" if tie_cols else "the last input record"
            warnings.warn(
                f"baseline_flag('{target}'): {n_ties} group(s) have more than one record with a "
                f"result on the last date and time before the reference. The flag goes to "
                f"{rule}; pass order_by= to state the SAP rule.",
                stacklevel=2,
            )

        df = df.with_columns(
            pl.when(pl.col("__bl_row__").is_in(last_day["__bl_win__"]))
            .then(pl.lit("Y"))
            .otherwise(pl.lit(None, dtype=pl.String))
            .alias(target)
        )

        # Clean up temp columns
        drop_cols = ["__bl_row__", "__bl_key__"]
        if ref_df is not None:
            drop_cols.append(_ref_tmp)
        df = df.drop([c for c in drop_cols if c in df.columns])

        new = self._materialise_then(df)

        # Record variable lineage
        from fleet.core.dag import VariableNode as _VN

        var_lineage: list = list(getattr(new, "_lineage", []))
        var_lineage.append(
            _VN(
                name=target,
                verb="baseline_flag",
                sources=[date_col, ref_col, result_col],
                method="fleet.sdtm.namespace.SDTMNamespace.baseline_flag",
                domain=getattr(new, "_domain", None),
            )
        )
        new._lineage = var_lineage

        if ref_df is not None:
            record_pin_lineage(
                new,
                target_col=target,
                verb="baseline_flag",
                source_domain=ref_pin.upper(),
                source_cols=[ref_col],
                join_key=join_key,
                relationship="derivation",
            )
        return new

    # ------------------------------------------------------------------ #
    # 6. condition_add — if condition then value else null                 #
    # ------------------------------------------------------------------ #

    def condition_add(
        self,
        target: str,
        *,
        condition: str | pl.Expr,
        then_value: Any,
    ) -> SDTMNamespace:
        """Set *target* to *then_value* where *condition* is true, else null.

        Args:
            target: Name of the output SDTM variable.
            condition: A Polars expression (or string) that evaluates to a
                boolean mask.
            then_value: The value to assign when *condition* is true.

        Returns:
            SDTMNamespace: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Set ``AEOUT`` to ``"FATAL"`` where the death flag is set::

                ae = (
                    raw_df.sdtm
                    .condition_add(
                        "AEOUT",
                        condition='pl.col("death_flag") == "Y"',
                        then_value="FATAL",
                    )
                    .to_frame()
                )
        """
        cond_expr = condition if isinstance(condition, pl.Expr) else parse_expression(condition)
        expr = pl.when(cond_expr).then(pl.lit(then_value)).otherwise(pl.lit(None)).alias(target)
        return self._chain(expr, verb="condition_add")

    # ------------------------------------------------------------------ #
    # 8. ae_aerel — AE causality string mapping                           #
    # ------------------------------------------------------------------ #

    _DEFAULT_AEREL_MAP: dict[str, str] = {
        "yes": "RELATED",
        "y": "RELATED",
        "related": "RELATED",
        "possibly related": "POSSIBLY RELATED",
        "probable": "PROBABLE",
        "no": "NOT RELATED",
        "n": "NOT RELATED",
        "not related": "NOT RELATED",
        "remote": "REMOTE",
        "unlikely related": "UNLIKELY RELATED",
    }

    def ae_aerel(
        self,
        target: str = "AEREL",
        *,
        source: str = "ae_relationship",
        aerel_map: dict[str, str] | None = None,
    ) -> SDTMNamespace:
        """Map free-text AE causality strings to ``AEREL`` values.

        Mapping is case-insensitive against *aerel_map*.  The default map
        is Fleet's own convention, not CDISC terminology: SDTM IG v3.4
        gives AEREL no codelist, so the sponsor defines the terms.  The
        AE relationship table (``AERelationshipSpec.relationship_order``)
        must list the same terms; a term it does not list stops the
        table.

        Args:
            target: Output column name (default ``"AEREL"``).
            source: Raw column containing causality strings.
            aerel_map: Optional ``{raw_text: decoded_value}`` override.

        Returns:
            SDTMNamespace: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        References:
            SDTM IG v3.4, AE domain, AEREL (no controlled terminology).

        Examples:
            Derive ``AEREL`` from raw causality using the default mapping::

                ae = (
                    raw_df.sdtm
                    .ae_aerel("AEREL", source="ae_relationship")
                    .to_frame()
                )
        """
        mapping = aerel_map or self._DEFAULT_AEREL_MAP

        raw = pl.col(source).cast(pl.String)
        normalised = raw.str.to_lowercase().str.strip_chars()
        expr = normalised.replace_strict(
            mapping,
            default=raw.str.to_uppercase(),
            return_dtype=pl.String,
        ).alias(target)
        return self._chain(expr, verb="ae_aerel")

    # ------------------------------------------------------------------ #
    # 9. seq — --SEQ sequence number (with SDTM naming convention check)  #
    # ------------------------------------------------------------------ #

    def seq(
        self,
        target: str,
        *,
        order_by: list[str] | None = None,
        by: list[str] | None = None,
        start_at: int = 1,
        check_uniqueness: bool = False,
    ) -> SDTMNamespace:
        """Derive the ``--SEQ`` sequence number variable.

        Generates a 1-based integer sequence that uniquely identifies each
        record within the domain, per subject.  The dataset is sorted by
        *order_by* columns within each *by* partition before numbering
        — this follows the sdtm.oak ``derive_seq()`` pattern and ensures
        deterministic, reproducible sequence values.

        Args:
            target: Name of the output ``--SEQ`` variable (e.g. ``"AESEQ"``,
                ``"VSSEQ"``).  A warning is emitted if the name does not end
                in ``SEQ``.
            order_by: Columns that define the sort order within each group.
                When ``None``, the current row order is preserved.
            by: Subject-level grouping columns (default
                ``["STUDYID", "USUBJID"]``).  The sequence restarts at
                *start_at* for each unique combination.
            start_at: First sequence value (default ``1``).
            check_uniqueness: If ``True``, emit a warning when the
                combination of *by* + *order_by* does not uniquely
                identify each row.

        Returns:
            SDTMNamespace: A fresh namespace with *target* appended.  Call
                ``.to_frame()`` to materialise.

        Examples:
            Derive ``AESEQ`` ordered by start date within each subject::

                ae = (
                    raw_df.sdtm
                    .assign("DOMAIN", value="AE")
                    .assign("USUBJID", source="patient_number")
                    .assign("AETERM", source="ae_term")
                    .assign("AESTDTC", source="ae_start_date")
                    .seq("AESEQ", order_by=["AESTDTC"])
                    .to_frame()
                )
        """
        import warnings

        if not target.endswith("SEQ"):
            warnings.warn(
                f"Target variable '{target}' does not end in 'SEQ'. "
                "SDTM --SEQ variables should follow the naming convention.",
                stacklevel=2,
            )

        return super().seq(
            target,
            order_by=order_by,
            by=by,
            start_at=start_at,
            check_uniqueness=check_uniqueness,
        )

    # ------------------------------------------------------------------ #
    # 10. merge is inherited from SharedVerbsMixin (canonical join verb). #
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # 10. group_by — aggregate records                                     #
    # ------------------------------------------------------------------ #

    def group_by(
        self,
        *,
        by: list[str],
        agg: list[pl.Expr],
    ) -> SDTMNamespace:
        """Group by *by* and apply *agg* aggregations (lazily).

        Args:
            by: Column(s) to group by.
            agg: List of Polars aggregation expressions.

        Returns:
            SDTMNamespace: A fresh namespace continuing from the grouped
                plan.

        Examples:
            Compute max vital-sign result per subject and test::

                vs_agg = (
                    raw_df.sdtm
                    .group_by(
                        by=["USUBJID", "VSTESTCD"],
                        agg=[pl.col("VSSTRESN").max().alias("AVAL")],
                    )
                    .to_frame()
                )
        """
        return self._with_lazy(self._lazy.group_by(by).agg(agg))

    # ------------------------------------------------------------------ #
    # 13. notsubmitted — mark variable as null / not-submitted            #
    # ------------------------------------------------------------------ #

    def notsubmitted(self, *targets: str) -> SDTMNamespace:
        """Mark one or more variables as not submitted (set to null).

        Useful to explicitly null out eCRF fields that are not included in
        the SDTM submission.

        Args:
            *targets: One or more variable names to null out.

        Returns:
            SDTMNamespace: The namespace with each *target* set to null;
                call ``.to_frame()`` to materialise.

        Examples:
            Null out internal scratch fields before submission::

                dm = (
                    raw_df.sdtm
                    .assign("USUBJID", source="subject_id")
                    .notsubmitted("_raw_id", "_site_code")
                    .to_frame()
                )
        """
        exprs = [pl.lit(None).alias(t) for t in targets]
        return self._chain(*exprs, verb="notsubmitted")

    # ------------------------------------------------------------------ #
    # 14. multiple_responses — expand multi-value eCRF fields             #
    # ------------------------------------------------------------------ #

    def multiple_responses(
        self,
        target: str,
        *,
        source: str,
        delimiter: str = "|",
    ) -> SDTMNamespace:
        """Explode a delimited multi-response field into separate rows.

        Splits *source* on *delimiter* and explodes — lazily, as part of
        the accumulated plan.

        Args:
            target: Name of the output column for the split values.
            source: Name of the raw column containing delimited responses.
            delimiter: Separator between responses (default ``"|"``).

        Returns:
            SDTMNamespace: A fresh namespace with one row per response.

        Examples:
            Explode pipe-delimited AE terms into separate rows::

                ae = (
                    raw_df.sdtm
                    .multiple_responses(
                        "AETERM", source="ae_terms", delimiter="|",
                    )
                    .to_frame()
                )
        """
        return self._with_lazy(
            self._lazy.with_columns(pl.col(source).str.split(delimiter).alias("__split__"))
            .explode("__split__")
            .with_columns(pl.col("__split__").str.strip_chars().alias(target))
            .drop("__split__")
        )

    # ------------------------------------------------------------------ #
    # Spec-driven pipeline: from_spec() is inherited from                  #
    # SharedVerbsMixin and executes through fleet.core.spec_registry.      #
    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #
    # Terminal operations                                                  #
    # ------------------------------------------------------------------ #

    def export_supp(
        self,
        *,
        qualifiers: dict[str, dict[str, str]] | None = None,
        spec: str | Path | None = None,
        dataset: str | None = None,
        idvar: str | None = None,
        domain: str | None = None,
    ) -> pl.DataFrame:
        """Export Non-Standard Variables as a vertical SUPPQUAL DataFrame.

        Produces the CDISC SUPPQUAL structure (STUDYID, RDOMAIN, USUBJID,
        IDVAR, IDVARVAL, QNAM, QLABEL, QVAL, QORIG, QEVAL) for SDTM
        IG ≤3.4 submissions.

        Resolution order (first match wins):

        1. **qualifiers** dict — explicit metadata per qualifier column.
        2. **spec** + **dataset** — reads ``role: qualifier`` variables
           from a ``define.yaml``.
        3. **Pipeline metadata** — uses ``_nsv_meta`` populated by prior
           ``nsv()`` calls in the chain.

        Args:
            qualifiers: Explicit qualifier metadata mapping.  Keys are
                column names (QNAM), values are dicts with ``"label"``
                and optionally ``"origin"`` and ``"evaluator"`` keys.
            spec: Path to a ``define.yaml`` file.  Used with *dataset*
                to discover ``role: qualifier`` variables.
            dataset: Dataset name within the spec (e.g. ``"DM"``).
            idvar: Name of the identifying variable column (e.g.
                ``"DMSEQ"``).  When ``None``, IDVAR and IDVARVAL are
                set to null (typical for DM).
            domain: Explicit RDOMAIN value.  When ``None``, inferred
                from the ``DOMAIN`` column in the frame.

        Returns:
            pl.DataFrame: Vertical SUPPQUAL frame with columns STUDYID,
                RDOMAIN, USUBJID, IDVAR, IDVARVAL, QNAM, QLABEL, QVAL,
                QORIG, QEVAL.

        Examples:
            Export from pipeline metadata (Pattern A)::

                ns = (
                    raw_df.sdtm
                    .assign("DOMAIN", value="DM")
                    .assign("USUBJID", source="patient_number")
                    .nsv("SAFETY", source="safety_flag",
                         label="Safety Population Flag")
                )
                suppdm = ns.export_supp()

            Export from define.yaml spec (Pattern D)::

                dm = raw_df.sdtm.from_spec("define.yaml", dataset="DM").to_frame()
                suppdm = dm.sdtm.export_supp(
                    spec="define.yaml", dataset="DM", idvar="DMSEQ"
                )

            Export with explicit qualifier dict (Pattern C)::

                suppdm = dm.sdtm.export_supp(
                    qualifiers={
                        "COMPLT16": {"label": "Completers of Week 16",
                                     "origin": "Derived"},
                        "SAFETY": {"label": "Safety Population Flag",
                                   "origin": "Derived"},
                    },
                    idvar="DMSEQ",
                )
        """
        # Resolve qualifier metadata from one of three sources
        meta: list[NSVMeta] = self._resolve_supp_meta(qualifiers, spec, dataset)

        if not meta:
            # Return empty frame with correct schema
            return pl.DataFrame(
                schema={
                    "STUDYID": pl.String,
                    "RDOMAIN": pl.String,
                    "USUBJID": pl.String,
                    "IDVAR": pl.String,
                    "IDVARVAL": pl.String,
                    "QNAM": pl.String,
                    "QLABEL": pl.String,
                    "QVAL": pl.String,
                    "QORIG": pl.String,
                    "QEVAL": pl.String,
                }
            )

        df = self._lazy.collect()

        # Determine RDOMAIN
        rdomain = domain or (df["DOMAIN"][0] if "DOMAIN" in df.columns else None)

        # Filter to only qualifier columns present in the frame
        present_meta = [m for m in meta if m.target in df.columns]
        if not present_meta:
            raise DerivationError(
                f"No qualifier columns found in frame. "
                f"Expected: {[m.target for m in meta]}. "
                f"Available: {df.columns}"
            )

        # Build SUPP rows via unpivot
        qual_cols = [m.target for m in present_meta]
        label_map = {m.target: m.label for m in present_meta}
        origin_map = {m.target: m.origin for m in present_meta}
        eval_map = {m.target: m.evaluator for m in present_meta}

        # Determine base columns needed
        base_cols = []
        if "STUDYID" in df.columns:
            base_cols.append("STUDYID")
        if "USUBJID" in df.columns:
            base_cols.append("USUBJID")

        # Unpivot qualifier columns
        supp = df.select(
            base_cols + ([idvar] if idvar and idvar in df.columns else []) + qual_cols
        ).unpivot(
            on=qual_cols,
            index=base_cols + ([idvar] if idvar and idvar in df.columns else []),
            variable_name="QNAM",
            value_name="QVAL",
        )

        # Cast QVAL to string
        supp = supp.with_columns(pl.col("QVAL").cast(pl.String))

        # Drop null QVAL rows
        supp = supp.filter(pl.col("QVAL").is_not_null())

        # Add SUPPQUAL metadata columns
        supp = supp.with_columns(
            pl.lit(rdomain).cast(pl.String).alias("RDOMAIN"),
            pl.col("QNAM").replace_strict(label_map, default=None).cast(pl.String).alias("QLABEL"),
            pl.col("QNAM")
            .replace_strict(origin_map, default="Derived")
            .cast(pl.String)
            .alias("QORIG"),
            pl.col("QNAM").replace_strict(eval_map, default=None).cast(pl.String).alias("QEVAL"),
        )

        # Handle IDVAR / IDVARVAL
        if idvar and idvar in supp.columns:
            supp = supp.with_columns(
                pl.lit(idvar).alias("IDVAR"),
                pl.col(idvar).cast(pl.String).alias("IDVARVAL"),
            ).drop(idvar)
        else:
            supp = supp.with_columns(
                pl.lit(None, dtype=pl.String).alias("IDVAR"),
                pl.lit(None, dtype=pl.String).alias("IDVARVAL"),
            )

        # Ensure STUDYID exists
        if "STUDYID" not in supp.columns:
            supp = supp.with_columns(pl.lit(None, dtype=pl.String).alias("STUDYID"))

        # Ensure USUBJID exists
        if "USUBJID" not in supp.columns:
            supp = supp.with_columns(pl.lit(None, dtype=pl.String).alias("USUBJID"))

        # Select final columns in CDISC order
        return supp.select(
            "STUDYID",
            "RDOMAIN",
            "USUBJID",
            "IDVAR",
            "IDVARVAL",
            "QNAM",
            "QLABEL",
            "QVAL",
            "QORIG",
            "QEVAL",
        )

    def _resolve_supp_meta(
        self,
        qualifiers: dict[str, dict[str, str]] | None,
        spec: str | Path | None,
        dataset: str | None,
    ) -> list[NSVMeta]:
        """Resolve NSV metadata from qualifiers dict, spec file, or pipeline."""
        # Priority 1: explicit qualifiers dict
        if qualifiers is not None:
            return [
                NSVMeta(
                    target=name,
                    label=info.get("label", ""),
                    origin=info.get("origin", "Derived"),
                    evaluator=info.get("evaluator"),
                )
                for name, info in qualifiers.items()
            ]

        # Priority 2: spec file
        if spec is not None:
            spec_data = load_define_spec(spec)
            if not spec_data.datasets:
                return []
            try:
                ds = spec_data.select(dataset)
            except DerivationError:
                return []
            meta = []
            for var in ds.variables:
                is_qual = (
                    var.role == "qualifier" or (var.derivation or {}).get("algorithm") == "nsv"
                )
                if is_qual:
                    meta.append(
                        NSVMeta(
                            target=var.name,
                            label=var.label or "",
                            origin=var.origin or "Derived",
                            evaluator=var.evaluator,
                        )
                    )
            return meta

        # Priority 3: pipeline metadata
        return list(self._nsv_meta)
