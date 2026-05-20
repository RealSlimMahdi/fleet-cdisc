"""
SDTM Polars namespace extension.

Registers ``df.sdtm`` on every Polars DataFrame.

Usage
-----
    import fleet  # triggers registration

    result = (
        raw_df.sdtm
        .assign_no_ct("USUBJID", source="patient_number")
        .assign_ct("SEX", source="sex", ct_codelist=SEX)
        .date("BRTHDTC", source="birth_date")
        .hardcode_no_ct("DOMAIN", value="DM")
        .to_frame()
    )

    # Or spec-driven:
    result = raw_df.sdtm.from_spec("examples/cdiscpilot01/sdtm/define.yaml", dataset="DM").to_frame()
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl
import yaml

from fleet.core._pin_mixin import PinMixin
from fleet.core._verb_mixin import SharedVerbsMixin
from fleet.sdtm._tdd_mixin import TrialDesignMixin
from fleet.sdtm.models import NSVMeta
from fleet.sdtm.utils import dtc_date_expr, dtc_datetime_expr, parse_expression

if TYPE_CHECKING:
    from fleet.ct.validator import CTValidator


def _resolve_callable(ref: str) -> Any:
    """Resolve a callable reference by name or dotted import path.

    Discovery order:

    1. Look up *ref* in the Fleet transform registry.
    2. If *ref* contains a dot, treat it as a dotted import path.
    3. Raise ``ValueError`` if neither lookup succeeds.

    Args:
        ref: Registry name or dotted import path.

    Returns:
        The callable or :class:`~fleet.core.derivation.Derivation` object.

    Raises:
        ValueError: If *ref* cannot be resolved.
    """
    from fleet.adam.transforms import get_transform

    try:
        return get_transform(ref)
    except KeyError:
        pass

    if "." in ref:
        import importlib

        module_path, _, attr = ref.rpartition(".")
        mod = importlib.import_module(module_path)
        return getattr(mod, attr)

    raise ValueError(
        f"Callable '{ref}' is not registered and is not a dotted import path. "
        "Register it with @derivation or import the derivations module before from_spec()."
    )


@pl.api.register_dataframe_namespace("sdtm")
class SDTMNamespace(SharedVerbsMixin, PinMixin, TrialDesignMixin):
    """
    Immutable pipeline builder for SDTM derivations.

    Each verb appends to a lazy expression list; `to_frame()` materialises
    everything in one ``with_columns`` call.
    """

    # -- SharedVerbsMixin configuration --
    _STUDY_DAY_REF_COL: str = "RFSTDTC"
    _STUDY_DAY_REF_PIN: str = "DM"
    _SEQ_DEFAULT_GROUPS: list[str] = ["STUDYID", "USUBJID"]
    _VALIDATE_STANDARD: str = "sdtm"
    _VALIDATE_DEFAULT_VERSION: str = "3.4"

    _FK_RULES: dict[str, dict[str, str]] = {
        "USUBJID": {"pin": "DM", "ref_col": "USUBJID"},
        "VISITNUM": {"pin": "TV", "ref_col": "VISITNUM"},
        "VISIT": {"pin": "TV", "ref_col": "VISIT"},
        "EPOCH": {"pin": "TE", "ref_col": "EPOCH"},
        "ETCD": {"pin": "TE", "ref_col": "ETCD"},
    }

    def __init__(self, df: pl.DataFrame) -> None:
        self._lazy = df.lazy()
        self._nsv_meta: list[NSVMeta] = []
        self._domain: str | None = None
        self._pinned: dict[str, tuple[pl.DataFrame, list[str]]] = {}
        self._pin_lineage: list = []

    # ------------------------------------------------------------------ #
    # 1. assign_no_ct — direct 1:1 column rename                          #
    # ------------------------------------------------------------------ #

    def assign_no_ct(self, target: str, *, source: str) -> SDTMNamespace:
        """Copy *source* column to *target* with no controlled-terminology validation.

        Args:
            target: Name of the output SDTM variable to create.
            source: Name of the raw/source column to copy from.

        Returns:
            SDTMNamespace: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Copy the raw subject identifier to ``USUBJID``::

                dm = (
                    raw_df.sdtm
                    .assign_no_ct("USUBJID", source="subject_id")
                    .to_frame()
                )
        """
        ns = self._chain(pl.col(source).alias(target))
        ns._auto_fk_check(target)
        return ns

    # ------------------------------------------------------------------ #
    # 2. assign_ct — 1:1 mapping with CT decode/validation                #
    # ------------------------------------------------------------------ #

    def assign_ct(
        self,
        target: str,
        *,
        source: str,
        ct_codelist: str | type,
        ct_mapping: dict[str, str] | None = None,
        ct_validator: CTValidator | None = None,
    ) -> SDTMNamespace:
        """Copy *source* to *target*, translating values via controlled terminology.

        Values are decoded using *ct_mapping* (explicit override) or, when
        omitted, from the singleton ``CTValidator`` for the given codelist.

        ``ct_mapping`` and ``ct_codelist`` are complementary:

        * **With** ``ct_mapping`` — raw values are translated through the
          supplied dictionary.  Use this when the source column contains
          non-standard codes that need remapping (e.g.
          ``{"1": "M", "2": "F"}``).
        * **Without** ``ct_mapping`` — the raw values are assumed to
          *already* match the CDISC submission values (e.g. the source
          column already contains ``"M"`` / ``"F"``).  In this mode the
          values are passed through and validated against the
          ``ct_codelist`` via the ``CTValidator``.

        In both cases ``ct_codelist`` identifies the NCI codelist used for
        downstream validation (e.g. Define-XML, P21).

        Args:
            target: Name of the output SDTM variable.
            source: Name of the raw column containing coded values.
            ct_codelist: CDISC CT codelist identifier — either a string
                (e.g. ``"C66731"``) or a generated codelist class
                (e.g. ``SEX``) that exposes ``_concept_id``.
            ct_mapping: Explicit ``{raw_value: ct_value}`` mapping.  When
                provided, the CT validator is bypassed.  May be omitted when
                raw data already matches the CDISC submission values — the
                codelist is still recorded for validation.
            ct_validator: Optional pre-built validator instance.

        Returns:
            SDTMNamespace: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Map raw ``sex`` values to CDISC Sex codelist using a generated
            codelist class::

                from codelists import SEX

                dm = (
                    raw_df.sdtm
                    .assign_ct(
                        "SEX",
                        source="sex",
                        ct_codelist=SEX,
                        ct_mapping={"M": "M", "F": "F"},
                    )
                    .to_frame()
                )

            Using a generated codelist class instead of a raw code::

                from codelists import SEX

                dm = (
                    raw_df.sdtm
                    .assign_ct("SEX", source="sex", ct_codelist=SEX)
                    .to_frame()
                )
        """
        # Resolve codelist class to its concept ID string.
        if not isinstance(ct_codelist, str):
            ct_codelist = getattr(ct_codelist, "_concept_id", None) or ct_codelist.__name__

        if ct_mapping:
            mapping_expr = pl.col(source).replace(ct_mapping).alias(target)
            ns = self._chain(mapping_expr)
            ns._auto_fk_check(target)
            return ns

        # Try to auto-resolve from the singleton CTValidator
        if ct_validator is None:
            try:
                from fleet.ct.validator import get_validator

                ct_validator = get_validator()
            except Exception:
                ct_validator = None

        if ct_validator is not None:
            try:
                _ = {v: v for v in ct_validator.get_valid_values(ct_codelist)}
                # Build decode map from CT (code → decode/preferred term)
                all_ct = ct_validator._ct_cache.get(ct_codelist, {})
                decode_map = {
                    coded: info.get("preferred_term", coded) for coded, info in all_ct.items()
                }
                if decode_map:
                    ns = self._chain(pl.col(source).replace(decode_map).alias(target))
                    ns._auto_fk_check(target)
                    return ns
            except Exception:
                pass

        # Fallback: pass-through (CT not loaded)
        ns = self._chain(pl.col(source).alias(target))
        ns._auto_fk_check(target)
        return ns

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

        For DTC targets: parses raw strings to ISO 8601, preserving partial
        dates.  Imputation parameters are ignored.  ``format`` is active.

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
            min_date: Lower clamp bound (DT/DTM only).
            max_date: Upper clamp bound (DT/DTM only).
            format: ``strptime`` format string for raw parsing (DTC only).

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
            raise ValueError("Cannot specify both source= and value=. Choose one.")
        if source is None and value is None:
            raise ValueError("Must specify either source= or value=.")

        output_type = _resolve_output_type(target, output)

        # value= path
        if value is not None:
            if flag is True:
                flag = False
            exprs = impute_and_flag(None, target, value=value, output_type=output_type, flag=flag)
            return self._chain(*exprs)

        # source= path
        assert source is not None

        if output_type == "dtc":
            # DTC: parse raw → ISO 8601 string
            if time is not None:
                # Combine date + time into DTC string
                date_part = dtc_date_expr(source, "__dtc_date_tmp__", input_format=format)
                time_part = pl.col(time) if not re.match(r"^\d{2}:\d{2}", time) else pl.lit(time)
                combined = (pl.col("__dtc_date_tmp__") + pl.lit("T") + time_part).alias(target)
                df = self._lazy.with_columns(date_part).collect()
                result = df.with_columns(combined)
                if "__dtc_date_tmp__" in result.columns:
                    result = result.drop("__dtc_date_tmp__")
                return self._materialise_then(result)

            if format is not None:
                # Use dtc_datetime_expr for datetime format, dtc_date_expr otherwise
                if any(c in format for c in ("H", "M", "S")):
                    expr = dtc_datetime_expr(source, target, input_format=format)
                else:
                    expr = dtc_date_expr(source, target, input_format=format)
            else:
                expr = dtc_date_expr(source, target)
            return self._chain(expr)

        # DT/DTM: delegate to imputation engine
        if time is not None and output_type != "dtm":
            raise ValueError(
                f"time= parameter is only valid for DTM targets, "
                f"but target '{target}' resolves to output='{output_type}'."
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
        return self._chain(*exprs)

    # ------------------------------------------------------------------ #
    # 4. hardcode_ct — literal constant with CT validation                #
    # ------------------------------------------------------------------ #

    def hardcode_ct(
        self,
        target: str,
        *,
        value: Any,
        ct_codelist: str | type | None = None,
    ) -> SDTMNamespace:
        """Set *target* to a constant *value*, validated against controlled terminology.

        When *ct_codelist* is provided **and** a ``CTValidator`` has been
        initialised with CT data, the *value* is checked at pipeline-build
        time.  A warning is emitted if the value is not a valid submission
        value for that codelist.  If CT data is not loaded, the validation
        is silently skipped and the value is assigned as-is.

        Args:
            target: Name of the output SDTM variable.
            value: The literal value to assign.
            ct_codelist: CDISC CT codelist for validation — pass a generated
                codelist class (e.g. ``SEX``) or a raw NCI concept ID string
                (e.g. ``"C66741"``).  Prefer the class form.

        Returns:
            SDTMNamespace: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Set ``AGEU`` to a constant value with CT validation::

                from codelists import AGEU

                dm = (
                    raw_df.sdtm
                    .hardcode_ct("AGEU", value="YEARS",
                                 ct_codelist=AGEU)
                    .to_frame()
                )
        """
        if ct_codelist is not None:
            # Resolve codelist class to its concept ID string.
            if not isinstance(ct_codelist, str):
                ct_codelist = getattr(ct_codelist, "_concept_id", None) or ct_codelist.__name__

            try:
                from fleet.ct.validator import get_validator

                validator = get_validator()
                valid, msg = validator.validate_value(ct_codelist, str(value))
                if not valid:
                    import warnings

                    warnings.warn(msg, stacklevel=2)
            except Exception:
                pass  # CT not loaded — skip validation

        ns = self._chain(pl.lit(value).alias(target))
        ns._auto_fk_check(target)
        return ns

    # ------------------------------------------------------------------ #
    # 5. hardcode_no_ct — literal constant, no CT                         #
    # ------------------------------------------------------------------ #

    def hardcode_no_ct(self, target: str, *, value: Any) -> SDTMNamespace:
        """Set *target* to a literal *value* for every row, with no CT validation.

        Args:
            target: Name of the output SDTM variable.
            value: The literal value to assign to every row.

        Returns:
            SDTMNamespace: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Hardcode the ``DOMAIN`` variable to ``"DM"``::

                dm = (
                    raw_df.sdtm
                    .hardcode_no_ct("DOMAIN", value="DM")
                    .to_frame()
                )
        """
        ns = self._chain(pl.lit(value).alias(target))
        if target == "DOMAIN":
            ns._domain = str(value)
        return ns

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
        origin: str = "DERIVED",
        evaluator: str | None = None,
    ) -> SDTMNamespace:
        """Derive a Non-Standard Variable with qualifier metadata.

        Behaves like ``assign_no_ct`` (when *source* is given) or
        ``hardcode_no_ct`` (when *value* is given) but additionally
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
            origin: Variable origin (becomes QORIG in SUPP).
            evaluator: Optional evaluator (becomes QEVAL in SUPP).

        Returns:
            SDTMNamespace: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Derive population flag NSVs for DM::

                dm = (
                    raw_df.sdtm
                    .hardcode_no_ct("DOMAIN", value="DM")
                    .assign_no_ct("USUBJID", source="patient_number")
                    .nsv("SAFETY", source="safety_flag",
                         label="Safety Population Flag")
                    .nsv("ITT", source="itt_flag",
                         label="Intent to Treat Population Flag")
                    .to_frame()
                )
        """
        if source is None and value is None:
            raise ValueError("nsv() requires either 'source' or 'value'.")
        if source is not None and value is not None:
            raise ValueError("nsv() accepts 'source' or 'value', not both.")

        expr = pl.col(source).alias(target) if source else pl.lit(value).alias(target)
        new = self._chain(expr)
        # Copy-on-write: avoid mutating shared list across copies
        new._nsv_meta = [
            *self._nsv_meta,
            NSVMeta(target=target, label=label, origin=origin, evaluator=evaluator),
        ]
        return new

    # ------------------------------------------------------------------ #
    # 5c. study_day — thin override for backward-compat `dm=` kwarg       #
    # ------------------------------------------------------------------ #

    def study_day(
        self,
        target: str,
        *,
        date_col: str,
        ref_col: str = "RFSTDTC",
        ref_pin: str = "DM",
        dm: pl.DataFrame | None = None,
    ) -> SDTMNamespace:
        """Derive a CDISC study day variable from a date column and a reference date.

        Uses the CDISC algorithm: ``date - ref_date + 1`` when
        ``date >= ref_date``, else ``date - ref_date`` (no day 0).

        The reference date is resolved in this order:

        1. Explicit ``dm=`` parameter (highest priority).
        2. Pinned domain (via ``.pin("DM", dm_df)``).
        3. ``ref_col`` already present in the current frame.
        4. Actionable ``LookupError`` telling the user what to do.

        Args:
            target: Name of the output study day variable
                (e.g. ``"AESTDY"``).
            date_col: Column in the current frame containing the date
                to measure from (e.g. ``"AESTDTC"``).
            ref_col: Column name of the reference start date in the
                pinned/explicit domain (default ``"RFSTDTC"``).
            ref_pin: Pinned domain to look up (default ``"DM"``).
            dm: Optional explicit DataFrame override — bypasses pinning.

        Returns:
            SDTMNamespace: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Raises:
            LookupError: If the reference date cannot be resolved from
                any source.

        Examples:
            Derive AE study day from pinned DM::

                ae = (
                    ae_raw.sdtm
                    .hardcode_no_ct("DOMAIN", value="AE")
                    .assign_no_ct("USUBJID", source="patient_number")
                    .date("AESTDTC", source="ae_start_date")
                    .pin("DM", dm_df)
                    .study_day("AESTDY", date_col="AESTDTC")
                    .to_frame()
                )
        """
        return super().study_day(
            target, date_col=date_col, ref_col=ref_col, ref_pin=ref_pin, ref_df=dm
        )

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
        group_by: list[str] | None = None,
    ) -> SDTMNamespace:
        """Flag the last observation before the reference date as baseline.

        Sets *target* to ``"Y"`` for the last record (per subject and
        optional grouping variables) that occurs on or before the
        reference date, and ``null`` for all other records.

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
            group_by: Additional grouping columns beyond USUBJID
                and *testcd_col*.

        Returns:
            SDTMNamespace: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Flag baseline vital signs::

                vs = (
                    vs_raw.sdtm
                    .hardcode_no_ct("DOMAIN", value="VS")
                    .assign_no_ct("USUBJID", source="patient_number")
                    .assign_no_ct("VSTESTCD", source="vstestcd")
                    .date("VSDTC", source="vs_date")
                    .pin("DM", dm_df)
                    .baseline_flag("VSBLFL", date_col="VSDTC",
                                   testcd_col="VSTESTCD")
                    .to_frame()
                )
        """
        from fleet.core.lineage import record_pin_lineage

        df = self._lazy.collect()

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
            df = df.join(ref_slim, on=join_key, how="left")
            ref_col_name = _ref_tmp
        else:
            ref_col_name = ref_col

        # Build grouping keys
        grp_keys = ["USUBJID"]
        if testcd_col is not None:
            grp_keys.append(testcd_col)
        if group_by:
            grp_keys.extend(group_by)
        grp_keys = list(dict.fromkeys(grp_keys))

        # Parse dates, filter pre-reference, find last
        date_parsed = pl.col(date_col).str.to_date(format="%Y-%m-%d", strict=False)
        ref_parsed = pl.col(ref_col_name).str.to_date(format="%Y-%m-%d", strict=False)

        df = df.with_columns(
            date_parsed.alias("__bl_date__"),
            ref_parsed.alias("__bl_ref__"),
        )

        # For each group, find the max date on or before the reference date
        # Then flag rows where the date matches that max
        pre_ref = pl.when(pl.col("__bl_date__") <= pl.col("__bl_ref__")).then(pl.col("__bl_date__"))
        max_pre_ref = pre_ref.max().over(grp_keys).alias("__bl_max__")

        df = df.with_columns(max_pre_ref)

        df = df.with_columns(
            pl.when(pl.col("__bl_date__") == pl.col("__bl_max__"))
            .then(pl.lit("Y"))
            .otherwise(pl.lit(None, dtype=pl.String))
            .alias(target)
        )

        # Clean up temp columns
        drop_cols = ["__bl_date__", "__bl_ref__", "__bl_max__"]
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
                sources=[date_col, ref_col],
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
        return self._chain(expr)

    # ------------------------------------------------------------------ #
    # 7. if_then_else — multi-branch conditional                          #
    # ------------------------------------------------------------------ #

    def if_then_else(
        self,
        target: str,
        *,
        when: list[dict[str, Any]],
        else_value: Any = None,
    ) -> SDTMNamespace:
        """Multi-branch conditional mapping.

        Branches are evaluated in order; first match wins.

        Args:
            target: Name of the output SDTM variable.
            when: List of ``{"condition": expr_str, "value": any}`` dicts.
            else_value: Fallback value when no branch matches.

        Returns:
            SDTMNamespace: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Map raw age-unit strings to CDISC ``AGEU`` values::

                dm = (
                    raw_df.sdtm
                    .if_then_else("AGEU", when=[
                        {"condition": 'pl.col("age_unit") == "years"', "value": "YEARS"},
                        {"condition": 'pl.col("age_unit") == "months"', "value": "MONTHS"},
                    ], else_value="YEARS")
                    .to_frame()
                )
        """
        if not when:
            return self._chain(pl.lit(else_value).alias(target))

        # Build nested pl.when().then().when().then()...
        first = when[0]
        cond = (
            first["condition"]
            if isinstance(first["condition"], pl.Expr)
            else parse_expression(first["condition"])
        )
        chain = pl.when(cond).then(pl.lit(first["value"]))
        for branch in when[1:]:
            c = (
                branch["condition"]
                if isinstance(branch["condition"], pl.Expr)
                else parse_expression(branch["condition"])
            )
            chain = chain.when(c).then(pl.lit(branch["value"]))
        expr = chain.otherwise(pl.lit(else_value)).alias(target)
        return self._chain(expr)

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
        """Map free-text AE causality strings to controlled ``AEREL`` values.

        Mapping is case-insensitive against *aerel_map* (defaults to the
        built-in CDISC causality mapping).

        Args:
            target: Output column name (default ``"AEREL"``).
            source: Raw column containing causality strings.
            aerel_map: Optional ``{raw_text: decoded_value}`` override.

        Returns:
            SDTMNamespace: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Derive ``AEREL`` from raw causality using the default mapping::

                ae = (
                    raw_df.sdtm
                    .ae_aerel("AEREL", source="ae_relationship")
                    .to_frame()
                )
        """
        mapping = aerel_map or self._DEFAULT_AEREL_MAP

        def _map(val: str | None) -> str | None:
            if val is None:
                return None
            return mapping.get(str(val).lower().strip(), str(val).upper())

        expr = pl.col(source).map_elements(_map, return_dtype=pl.String).alias(target)
        return self._chain(expr)

    # ------------------------------------------------------------------ #
    # 9. seq — --SEQ sequence number (with SDTM naming convention check)  #
    # ------------------------------------------------------------------ #

    def seq(
        self,
        target: str,
        *,
        order_by: list[str] | None = None,
        groups: list[str] | None = None,
        start_at: int = 1,
        check_uniqueness: bool = False,
    ) -> SDTMNamespace:
        """Derive the ``--SEQ`` sequence number variable.

        Generates a 1-based integer sequence that uniquely identifies each
        record within the domain, per subject.  The dataset is sorted by
        *order_by* columns within each *groups* partition before numbering
        — this follows the sdtm.oak ``derive_seq()`` pattern and ensures
        deterministic, reproducible sequence values.

        Args:
            target: Name of the output ``--SEQ`` variable (e.g. ``"AESEQ"``,
                ``"VSSEQ"``).  A warning is emitted if the name does not end
                in ``SEQ``.
            order_by: Columns that define the sort order within each group.
                When ``None``, the current row order is preserved.
            groups: Subject-level grouping columns (default
                ``["STUDYID", "USUBJID"]``).  The sequence restarts at
                *start_at* for each unique combination.
            start_at: First sequence value (default ``1``).
            check_uniqueness: If ``True``, emit a warning when the
                combination of *groups* + *order_by* does not uniquely
                identify each row.

        Returns:
            SDTMNamespace: A fresh namespace with *target* appended.  Call
                ``.to_frame()`` to materialise.

        Examples:
            Derive ``AESEQ`` ordered by start date within each subject::

                ae = (
                    raw_df.sdtm
                    .hardcode_no_ct("DOMAIN", value="AE")
                    .assign_no_ct("USUBJID", source="patient_number")
                    .assign_no_ct("AETERM", source="ae_term")
                    .assign_no_ct("AESTDTC", source="ae_start_date")
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
            groups=groups,
            start_at=start_at,
            check_uniqueness=check_uniqueness,
        )

    # ------------------------------------------------------------------ #
    # 10. merge — join another dataset                                     #
    # ------------------------------------------------------------------ #

    def merge(
        self,
        target_cols: list[str] | None = None,
        *,
        dataset: pl.DataFrame,
        on: str | list[str],
        how: str = "left",
    ) -> SDTMNamespace:
        """Join *dataset* into the pipeline using key column(s) *on*.

        Materialises the current pipeline first (join requires a concrete
        frame), then returns a namespace wrapping the joined result.

        Args:
            target_cols: Optional list of columns to keep from the joined
                result. When ``None``, all columns are retained.
            dataset: The ``pl.DataFrame`` to merge in.
            on: Key column name(s) for the join.
            how: Join strategy (default ``"left"``).

        Returns:
            SDTMNamespace: A fresh namespace wrapping the joined frame.

        Examples:
            Merge supplemental qualifier data onto the DM domain::

                dm = (
                    raw_df.sdtm
                    .hardcode_no_ct("DOMAIN", value="DM")
                    .merge(dataset=suppdm_df, on="USUBJID")
                    .to_frame()
                )
        """
        joined = self._lazy.join(dataset.lazy(), on=on, how=how)
        if target_cols:
            joined = joined.with_columns([pl.col(c) for c in target_cols])
        return self._materialise_then(joined.collect())

    # ------------------------------------------------------------------ #
    # 10. group_by — aggregate records                                     #
    # ------------------------------------------------------------------ #

    def group_by(
        self,
        *,
        group_cols: list[str],
        agg: list[pl.Expr],
    ) -> SDTMNamespace:
        """Group by *group_cols* and apply *agg* aggregations.

        Materialises, groups, and returns a fresh namespace.

        Args:
            group_cols: Column(s) to group by.
            agg: List of Polars aggregation expressions.

        Returns:
            SDTMNamespace: A fresh namespace wrapping the grouped frame.

        Examples:
            Compute max vital-sign result per subject and test::

                vs_agg = (
                    raw_df.sdtm
                    .group_by(
                        group_cols=["USUBJID", "VSTESTCD"],
                        agg=[pl.col("VSSTRESN").max().alias("AVAL")],
                    )
                    .to_frame()
                )
        """
        return self._materialise_then(self._lazy.group_by(group_cols).agg(agg).collect())

    # ------------------------------------------------------------------ #
    # 12. dataset_level — constant for whole dataset (alias hardcode_no_ct)
    # ------------------------------------------------------------------ #

    def dataset_level(self, target: str, *, value: Any) -> SDTMNamespace:
        """Set a dataset-level constant on *target* (alias for ``hardcode_no_ct``).

        Args:
            target: Name of the output SDTM variable.
            value: The literal constant to broadcast to every row.

        Returns:
            SDTMNamespace: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Hardcode ``STUDYID`` at the dataset level::

                dm = (
                    raw_df.sdtm
                    .dataset_level("STUDYID", value="CDISCPILOT01")
                    .to_frame()
                )
        """
        return self.hardcode_no_ct(target, value=value)

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
                    .assign_no_ct("USUBJID", source="subject_id")
                    .notsubmitted("_raw_id", "_site_code")
                    .to_frame()
                )
        """
        exprs = [pl.lit(None).alias(t) for t in targets]
        return self._chain(*exprs)

    # ------------------------------------------------------------------ #
    # 14. multiple_responses — expand multi-value eCRF fields             #
    # ------------------------------------------------------------------ #

    def multiple_responses(
        self,
        target: str,
        *,
        source: str,
        delimiter: str = "|",
        id_cols: list[str] | None = None,
    ) -> SDTMNamespace:
        """Explode a delimited multi-response field into separate rows.

        Materialises the current pipeline, then splits *source* on
        *delimiter* and explodes, keeping *id_cols* intact.

        Args:
            target: Name of the output column for the split values.
            source: Name of the raw column containing delimited responses.
            delimiter: Separator between responses (default ``"|"``).
            id_cols: Columns to carry through unchanged.

        Returns:
            SDTMNamespace: A fresh namespace with one row per response.

        Examples:
            Explode pipe-delimited AE terms into separate rows::

                ae = (
                    raw_df.sdtm
                    .multiple_responses(
                        "AETERM", source="ae_terms", delimiter="|",
                        id_cols=["USUBJID"],
                    )
                    .to_frame()
                )
        """
        return self._materialise_then(
            self._lazy.with_columns(pl.col(source).str.split(delimiter).alias("__split__"))
            .explode("__split__")
            .with_columns(pl.col("__split__").str.strip_chars().alias(target))
            .drop("__split__")
            .collect()
        )

    # ------------------------------------------------------------------ #
    # Spec-driven pipeline                                                 #
    # ------------------------------------------------------------------ #

    def from_spec(self, spec_path: str | Path, *, dataset: str | None = None) -> SDTMNamespace:
        """Build a pipeline from a YAML specification file.

        Reads a ``define.yaml`` with a top-level ``datasets`` list where each
        variable carries a ``derivation`` block.  Pass *dataset* to select
        which dataset to execute (e.g. ``dataset="DM"``).  When the file
        contains only one dataset the *dataset* argument may be omitted.

        Args:
            spec_path: Path to the ``define.yaml`` specification file.
            dataset: Name of the dataset to execute from the spec.

        Returns:
            SDTMNamespace: A namespace pre-loaded with all spec-driven
                derivations; call ``.to_frame()`` to materialise.

        Examples:
            Build and materialise the DM domain from a spec::

                dm = (
                    raw_df.sdtm
                    .from_spec("examples/cdiscpilot01/sdtm/define.yaml", dataset="DM")
                    .to_frame()
                )
        """
        from fleet.sdtm.models import SDTMDomainSpec

        spec_data = yaml.safe_load(Path(spec_path).read_text())

        # ── Detect format: define.yaml has a top-level "datasets" key ──
        if "datasets" in spec_data:
            variables = self._extract_define_variables(spec_data, dataset)
        else:
            spec = SDTMDomainSpec(**spec_data)
            variables = spec.variables

        ns: SDTMNamespace = self
        for var in variables:
            alg = var.algorithm.value
            target = var.target

            if alg == "assign_no_ct":
                ns = ns.assign_no_ct(target, source=var.source or target)
            elif alg == "assign_ct":
                ns = ns.assign_ct(
                    target,
                    source=var.source or target,
                    ct_codelist=var.ct_codelist or "",
                    ct_mapping=var.ct_mapping,
                )
            elif alg in ("assign_dtc", "assign_datetime", "date"):
                kwargs: dict[str, Any] = {}
                if var.source:
                    kwargs["source"] = var.source
                elif getattr(var, "value", None):
                    kwargs["value"] = var.value
                else:
                    kwargs["source"] = var.source or target
                if getattr(var, "output", None):
                    kwargs["output"] = var.output
                if getattr(var, "format", None) or getattr(var, "input_format", None):
                    kwargs["format"] = getattr(var, "format", None) or var.input_format
                ns = ns.date(target, **kwargs)
            elif alg == "duration":
                ns = ns.duration(
                    target,
                    start=getattr(var, "start", None) or var.source or "",
                    end=getattr(var, "end", None) or "",
                    unit=getattr(var, "unit", "days") or "days",
                )
            elif alg == "hardcode_ct":
                ns = ns.hardcode_ct(target, value=var.value, ct_codelist=var.ct_codelist)
            elif alg in ("hardcode_no_ct", "dataset_level"):
                ns = ns.hardcode_no_ct(target, value=var.value)
            elif alg == "condition_add":
                ns = ns.condition_add(
                    target,
                    condition=var.condition or "pl.lit(True)",
                    then_value=var.then_value,
                )
            elif alg == "if_then_else":
                ns = ns.if_then_else(target, when=var.when or [], else_value=var.else_value)
            elif alg == "ae_aerel":
                ns = ns.ae_aerel(
                    target,
                    source=var.aerel_source or "ae_relationship",
                    aerel_map=var.aerel_map,
                )
            elif alg == "notsubmitted":
                ns = ns.notsubmitted(target)
            elif alg == "nsv":
                ns = ns.nsv(
                    target,
                    source=var.source,
                    value=var.value if var.source is None else None,
                    label=var.label or "",
                    origin=var.origin or "DERIVED",
                    evaluator=var.evaluator,
                )
            elif alg == "callable":
                fn = _resolve_callable(var.callable_ref or "")
                if hasattr(fn, "kind"):
                    ns = ns.derivation(fn)
                else:
                    ns = ns._materialise_then(fn(ns.to_frame()))
            # merge, group_by, multiple_responses require extra data
            # — skip in spec-driven mode if not fully specified

        return ns

    @staticmethod
    def _extract_define_variables(spec_data: dict, dataset: str | None) -> list:
        """Convert define.yaml dataset variables into SDTMVariableSpec objects."""
        from fleet.sdtm.models import SDTMVariableSpec

        datasets = spec_data["datasets"]
        if dataset is None:
            if len(datasets) != 1:
                names = [d["name"] for d in datasets]
                raise ValueError(
                    f"define.yaml contains {len(datasets)} datasets {names}. "
                    "Pass dataset= to select one."
                )
            ds = datasets[0]
        else:
            matches = [d for d in datasets if d["name"].upper() == dataset.upper()]
            if not matches:
                names = [d["name"] for d in datasets]
                raise ValueError(
                    f"Dataset '{dataset}' not found in define.yaml. Available: {names}"
                )
            ds = matches[0]

        result = []
        for var in ds["variables"]:
            drv = var.get("derivation")
            if not drv:
                continue  # no derivation → carry-through / manual column
            # Backward compat: callable: without algorithm: → inject algorithm.
            if "callable" in drv and "algorithm" not in drv:
                drv = {**drv, "algorithm": "callable"}
            # Pass top-level variable attributes into the spec if relevant
            extra: dict[str, Any] = {}
            if var.get("label"):
                extra["label"] = var["label"]
            if var.get("origin"):
                extra["origin"] = var["origin"]
            if var.get("role"):
                extra["role"] = var["role"]
            if var.get("evaluator"):
                extra["evaluator"] = var["evaluator"]
            spec = SDTMVariableSpec(
                target=var["name"],
                **drv,
                **extra,
            )
            result.append(spec)
        return result

    # ------------------------------------------------------------------ #
    # Validation integration                                               #
    # ------------------------------------------------------------------ #

    def validate(
        self,
        domain: str,
        version: str = "3.4",
        rules_engine_path: Path | None = None,
        custom_rules: str | Path | None = None,
    ) -> SDTMNamespace:
        """Run CDISC SDTM conformance validation and print the report.

        Returns *self* so the chain can continue after validation.

        Args:
            domain: SDTM domain code (e.g. ``"DM"``, ``"AE"``).
            version: SDTM IG version to validate against (default ``"3.4"``).
            rules_engine_path: Optional path to a custom rules engine.
            custom_rules: Optional path to a directory containing custom
                validation rule YAML files. Passed to the engine via ``-lr``.

        Returns:
            SDTMNamespace: The same namespace instance (for continued
                chaining).

        Examples:
            Validate a DM domain against SDTM 3.4::

                dm = (
                    raw_df.sdtm
                    .hardcode_no_ct("DOMAIN", value="DM")
                    .assign_no_ct("USUBJID", source="subject_id")
                    .validate("DM", version="3.4")
                    .to_frame()
                )

            Validate with custom sponsor rules::

                ae = (
                    raw_df.sdtm
                    .hardcode_no_ct("DOMAIN", value="AE")
                    .validate("AE", custom_rules="specs/custom_rules")
                    .to_frame()
                )
        """
        from fleet.validation.service import ValidationService

        svc = ValidationService(rules_engine_path=rules_engine_path)
        result = svc.validate_sdtm(
            self.to_frame(), domain=domain, version=version, custom_rules=custom_rules
        )
        result.print_report()
        return self

    # ------------------------------------------------------------------ #
    # select — column selection / variable-leakage guard                  #
    # ------------------------------------------------------------------ #

    def select(
        self,
        columns: list[str] | None = None,
        *,
        spec: str | Path | None = None,
        dataset: str | None = None,
        drop_pattern: str | None = r"^_",
    ) -> SDTMNamespace:
        """
        Materialise the pipeline then select and reorder columns.

        Resolution order:

        1. ``spec`` + ``dataset``: derive the ordered column list from a
           ``define.yaml``.  Only columns present in the frame are kept.
        2. ``columns``: explicit list to keep (in that order).
        3. Neither: keep all current columns (subject to ``drop_pattern``).

        ``drop_pattern`` (default ``r"^_"``): regex applied *before* the
        explicit selection — columns whose names match are removed.  This
        enforces the convention that ``_``-prefixed columns are scratch
        variables.  Set to ``None`` to disable (e.g. during debugging).

        Examples:
            Keep only spec columns, drop scratch ``_`` variables (default)::

                dm = (
                    raw_df.sdtm
                    .select(spec="specs/sdtm/define.yaml", dataset="DM")
                    .to_frame()
                )

            Disable auto-drop for debugging::

                dm = (
                    raw_df.sdtm
                    .select(spec="specs/sdtm/define.yaml", dataset="DM",
                            drop_pattern=None)
                    .to_frame()
                )
        """
        import re

        df = self.to_frame()

        # Step 1: drop scratch variables matching the pattern
        if drop_pattern is not None:
            pat = re.compile(drop_pattern)
            df = df.select([c for c in df.columns if not pat.search(c)])

        # Step 2: resolve explicit column list (spec takes priority over columns)
        col_list = columns
        type_map: dict[str, str] = {}
        if spec is not None:
            spec_path = Path(spec)
            col_list, type_map = self._spec_dataset_meta(spec_path, dataset)

        # Step 3: intersect with existing columns (preserving spec order)
        if col_list is not None:
            existing = [c for c in col_list if c in df.columns]
            df = df.select(existing)

        # Step 4: cast date/datetime columns declared in the spec
        if type_map:
            casts = []
            for col_name, spec_type in type_map.items():
                if col_name not in df.columns:
                    continue
                dtype = df[col_name].dtype
                if spec_type == "date":
                    if dtype == pl.String:
                        casts.append(pl.col(col_name).str.to_date("%Y-%m-%d", strict=False))
                    elif dtype.is_(pl.Datetime) or str(dtype).startswith("Datetime"):
                        casts.append(pl.col(col_name).cast(pl.Date))
                elif spec_type == "datetime":
                    if dtype == pl.String:
                        casts.append(pl.col(col_name).str.to_datetime(strict=False))
            if casts:
                df = df.with_columns(casts)

        return self._new_from(df)

    @staticmethod
    def _spec_dataset_meta(
        spec_path: Path, dataset: str | None
    ) -> tuple[list[str], dict[str, str]]:
        """Return ``(column_names, date_type_map)`` for *dataset* from a define.yaml.

        Parses the YAML once and resolves the dataset, avoiding duplicate I/O.
        """
        spec_data = yaml.safe_load(spec_path.read_text())
        datasets = spec_data.get("datasets", [])
        if dataset is None:
            if len(datasets) != 1:
                names = [d["name"] for d in datasets]
                raise ValueError(
                    f"define.yaml contains {len(datasets)} datasets {names}; "
                    "pass dataset= to select one."
                )
            ds = datasets[0]
        else:
            matches = [d for d in datasets if d["name"].upper() == dataset.upper()]
            if not matches:
                names = [d["name"] for d in datasets]
                raise ValueError(
                    f"Dataset '{dataset}' not found in define.yaml. Available: {names}"
                )
            ds = matches[0]
        columns = [v["name"] for v in ds["variables"]]
        type_map = {
            v["name"]: v["type"] for v in ds["variables"] if v.get("type") in ("date", "datetime")
        }
        return columns, type_map

    def _new_from(self, df: pl.DataFrame) -> SDTMNamespace:
        """Return a fresh SDTMNamespace wrapping *df* as a lazy plan."""
        return self._materialise_then(df)

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
                    .hardcode_no_ct("DOMAIN", value="DM")
                    .assign_no_ct("USUBJID", source="patient_number")
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
                                     "origin": "DERIVED"},
                        "SAFETY": {"label": "Safety Population Flag",
                                   "origin": "DERIVED"},
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
            raise ValueError(
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
            .replace_strict(origin_map, default="DERIVED")
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
                    origin=info.get("origin", "DERIVED"),
                    evaluator=info.get("evaluator"),
                )
                for name, info in qualifiers.items()
            ]

        # Priority 2: spec file
        if spec is not None:
            spec_data = yaml.safe_load(Path(spec).read_text())
            if "datasets" not in spec_data:
                return []
            datasets = spec_data["datasets"]
            if dataset:
                matches = [d for d in datasets if d["name"].upper() == dataset.upper()]
                ds = matches[0] if matches else None
            elif len(datasets) == 1:
                ds = datasets[0]
            else:
                ds = None
            if ds is None:
                return []
            meta = []
            for var in ds.get("variables", []):
                is_qual = var.get("role") == "qualifier" or (
                    var.get("derivation", {}).get("algorithm") == "nsv"
                )
                if is_qual:
                    meta.append(
                        NSVMeta(
                            target=var["name"],
                            label=var.get("label", ""),
                            origin=var.get("origin", "DERIVED"),
                            evaluator=var.get("evaluator"),
                        )
                    )
            return meta

        # Priority 3: pipeline metadata
        return list(self._nsv_meta)
