"""
Shared verb mixin — base class for both SDTM and ADaM namespaces.

Provides the verbs whose logic is identical (or parameterised-identical)
across the SDTM and ADaM namespace hierarchies:

Infrastructure (Group A):
    ``_chain``, ``_materialise_then``, ``to_frame``, ``to_dataset_json``,
    ``inspect``, ``explain``, ``write_parquet``

Algorithmic (Group B):
    ``derivation``, ``_apply_derivation``, ``duration``, ``study_day``,
    ``seq``

Utility:
    ``validate``, ``select``, ``_spec_dataset_meta``

Namespace classes set class-level constants to control default behaviour
(e.g. ``_STUDY_DAY_REF_COL``, ``_STUDY_DAY_REF_PIN``, ``_SEQ_DEFAULT_GROUPS``).
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Self

import polars as pl
import yaml

if TYPE_CHECKING:
    from collections.abc import Callable

    from fleet.core.derivation import Derivation


class SharedVerbsMixin:
    """Base mixin providing verbs shared across SDTM and ADaM namespaces.

    Concrete namespace classes must provide:
        - ``_lazy: pl.LazyFrame`` instance attribute (set in ``__init__``)

    Class-level constants for parameterised verbs:
        - ``_STUDY_DAY_REF_COL``: default reference date column (e.g. ``"RFSTDTC"`` or ``"TRTSDT"``)
        - ``_STUDY_DAY_REF_PIN``: default pinned domain name (e.g. ``"DM"`` or ``"ADSL"``)
        - ``_SEQ_DEFAULT_GROUPS``: default grouping columns for ``seq()``
        - ``_VALIDATE_STANDARD``: ``"sdtm"`` or ``"adam"``
        - ``_VALIDATE_DEFAULT_VERSION``: default IG version string
    """

    _lazy: pl.LazyFrame

    # -- Subclass configuration constants (overridden per namespace) ----
    _STUDY_DAY_REF_COL: ClassVar[str] = "RFSTDTC"
    _STUDY_DAY_REF_PIN: ClassVar[str] = "DM"
    _SEQ_DEFAULT_GROUPS: ClassVar[list[str]] = ["STUDYID", "USUBJID"]
    _VALIDATE_STANDARD: ClassVar[str] = "sdtm"
    _VALIDATE_DEFAULT_VERSION: ClassVar[str] = "3.4"

    # ------------------------------------------------------------------ #
    # Infrastructure (Group A)                                             #
    # ------------------------------------------------------------------ #

    def _chain(self, *exprs: pl.Expr) -> Self:
        """Append expressions to the lazy plan; return a *new* namespace."""
        from fleet.core.lineage import record_lineage

        new = copy.copy(self)
        new._lazy = self._lazy.with_columns(list(exprs))
        record_lineage(new, exprs)
        return new

    def _materialise_then(self, df: pl.DataFrame) -> Self:
        """Return a fresh namespace wrapping *df* as a new lazy plan."""
        new = copy.copy(self)
        new._lazy = df.lazy()
        return new

    def to_frame(self) -> pl.DataFrame:
        """Materialise the accumulated pipeline into a Polars DataFrame.

        Returns:
            pl.DataFrame: The fully materialised result of all chained
                verbs.

        Examples:
            Collect the pipeline result::

                result = (
                    df.sdtm
                    .hardcode_no_ct("DOMAIN", value="DM")
                    .assign_no_ct("USUBJID", source="subject_id")
                    .to_frame()
                )
        """
        return self._lazy.collect()

    def to_dataset_json(
        self,
        path: str | Path,
        *,
        domain: str,
        label: str | None = None,
    ) -> Path:
        """Materialise the pipeline and write a CDISC Dataset-JSON v1.1 file.

        This is a terminal verb — it collects the lazy plan and writes the
        result.  No further chaining is possible after this call.

        Args:
            path: Destination file path (should end in ``.json``).
            domain: Dataset / domain name (e.g. ``"DM"``, ``"ADSL"``).
            label: Optional human-readable dataset label.

        Returns:
            Path: Path to the written file.

        Examples:
            Export a dataset to Dataset-JSON::

                path = (
                    df.sdtm
                    .hardcode_no_ct("DOMAIN", value="DM")
                    .assign_no_ct("USUBJID", source="subject_id")
                    .to_dataset_json("outputs/dm.json", domain="DM")
                )
        """
        from fleet.io.dataset_json import save_dataset_json

        return save_dataset_json(self._lazy.collect(), path, domain=domain, label=label)

    def inspect(self, prefix: str = "DEBUG") -> Self:
        """Materialise the pipeline at this point and log its state.

        Creates a hard checkpoint: the pipeline resumes from the
        materialised frame, making it easy to isolate exactly where a
        derivation goes wrong.

        Args:
            prefix: Label printed alongside the diagnostic output.

        Returns:
            Self: A fresh namespace wrapping the materialised frame;
                call further verbs or ``.to_frame()`` to continue.

        Examples:
            Inspect the pipeline after assigning key variables::

                result = (
                    df.sdtm
                    .hardcode_no_ct("DOMAIN", value="DM")
                    .inspect(prefix="After DOMAIN")
                    .assign_no_ct("USUBJID", source="subject_id")
                    .to_frame()
                )
        """
        df = self._lazy.collect()
        print(f"[{prefix}] Schema: {df.schema}")
        print(f"[{prefix}] Shape:  {df.shape}")
        print(df.head(5))
        return self._materialise_then(df)

    def explain(self) -> Self:
        """Print the current Polars query plan without materialising.

        Useful for understanding how Polars will optimise the accumulated
        derivation pipeline.

        Returns:
            Self: The same namespace instance (unchanged); call
                further verbs or ``.to_frame()`` to continue.

        Examples:
            Print the query plan before collecting::

                result = (
                    df.sdtm
                    .hardcode_no_ct("DOMAIN", value="DM")
                    .explain()
                    .to_frame()
                )
        """
        print(self._lazy.explain())
        return self

    def write_parquet(
        self,
        path: str | Path,
        *,
        mkdir: bool = True,
    ) -> pl.DataFrame:
        """Materialise the pipeline, write to Parquet, and return the DataFrame.

        This is a drop-in alternative to ``to_frame()`` when you want to
        persist the dataset as part of the chain.

        Args:
            path: Destination file path.
            mkdir: When ``True`` (default) any missing parent directories
                are created automatically.

        Returns:
            pl.DataFrame: The materialised result.

        Examples:
            Write a domain to Parquet::

                dm = (
                    raw_df.sdtm
                    .assign_no_ct("USUBJID", source="patient_number")
                    .write_parquet("outputs/dm.parquet")
                )
        """
        df = self.to_frame()
        dest = Path(path)
        if mkdir:
            dest.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(dest)
        return df

    # ------------------------------------------------------------------ #
    # Algorithmic (Group B)                                                #
    # ------------------------------------------------------------------ #

    def derivation(
        self,
        target: str | Derivation | None = None,
        *,
        expression: str | pl.Expr | Callable[[], pl.Expr] | None = None,
    ) -> Self:
        """Derive *target* using an expression, lambda, or ``Derivation`` object.

        Four call forms are supported:

        **Case 1 — string (AST-sandboxed, YAML-compatible)**::

            .derivation("COL", expression="pl.col('src').cast(pl.String)")

        **Case 2 — direct ``pl.Expr``**::

            .derivation("COL", expression=pl.col("src").cast(pl.String))

        **Case 3 — zero-arg lambda returning ``pl.Expr`` (full IDE support)**::

            .derivation("COL", expression=lambda: pl.col("src").cast(pl.Int32))

        **Case 4 — ``@derivation`` object (file-based, full lineage)**::

            from specs.study01.derivations import MY_DRULE
            .derivation(MY_DRULE)

        Args:
            target: For Cases 1–3, the name of the output variable
                (required).  For Case 4, the
                :class:`~fleet.core.derivation.Derivation` object to dispatch.
            expression: A Polars expression, expression string, or zero-arg
                callable returning ``pl.Expr``.  Required for Cases 1–3.

        Returns:
            Self: The namespace with *target* appended; call ``.to_frame()``
                to materialise.

        Raises:
            ValueError: If *target* is a string but *expression* is not
                provided, or vice-versa.
            TypeError: If a lambda-style *expression* does not return
                ``pl.Expr``.

        Examples:
            Case 1 — string expression::

                result = (
                    raw_df.sdtm
                    .derivation("SITEID", expression="pl.col('site_id').cast(pl.String)")
                    .to_frame()
                )

            Case 3 — lambda::

                result = (
                    raw_df.sdtm
                    .derivation("VISITNUM", expression=lambda: pl.col("visit").cast(pl.Int32))
                    .to_frame()
                )

            Case 4 — ``@derivation`` object::

                from specs.study01.derivations import MY_DRULE

                result = (
                    raw_df.sdtm
                    .derivation(MY_DRULE)
                    .to_frame()
                )
        """
        from fleet.sdtm.utils import parse_expression

        # Case 4: Derivation object passed as first positional arg.
        if target is not None and not isinstance(target, str):
            return self._apply_derivation(target)  # type: ignore[arg-type]

        # Cases 1–3 require a string target.
        if target is None:
            raise ValueError("target is required when expression= is provided.")
        if expression is None:
            raise ValueError("expression is required when target is a string.")

        # Case 2: direct pl.Expr.
        if isinstance(expression, pl.Expr):
            return self._chain(expression.alias(target))

        # Case 3: lambda / zero-arg callable.
        if callable(expression) and not isinstance(expression, str):
            expr = expression()
            if not isinstance(expr, pl.Expr):
                raise TypeError(
                    f"expression callable must return pl.Expr, got {type(expr).__name__}"
                )
            return self._chain(expr.alias(target))

        # Case 1: string through AST sandbox.
        return self._chain(parse_expression(str(expression)).alias(target))

    def _apply_derivation(self, drv: Derivation) -> Self:
        """Dispatch a :class:`~fleet.core.derivation.Derivation` object.

        Routing:

        * ``kind="column"`` — expression stays lazy; lineage via ``_chain()``.
        * ``kind="frame"`` or ``kind="param"`` — the frame is materialised,
          the function called, and the result re-wrapped.

        Args:
            drv: The :class:`~fleet.core.derivation.Derivation` to execute.

        Returns:
            Self: Updated namespace.

        Raises:
            TypeError: If a frame/param derivation returns a non-DataFrame.
        """
        from fleet.core.lineage import _append_lineage_nodes

        if drv.kind == "column":
            expr: pl.Expr = drv()
            return self._chain(expr.alias(drv.targets[0]))

        df = self.to_frame()
        result = drv(df)
        if not isinstance(result, pl.DataFrame):
            raise TypeError(
                f"Derivation '{drv.name}' is kind={drv.kind!r} but fn() returned "
                f"{type(result).__name__!r} — expected pl.DataFrame."
            )
        ns = self._materialise_then(result)
        return _append_lineage_nodes(ns, drv)

    # ------------------------------------------------------------------ #
    # duration                                                             #
    # ------------------------------------------------------------------ #

    def duration(
        self,
        target: str,
        *,
        start: str | pl.Expr,
        end: str | pl.Expr,
        unit: str = "days",
        add_one: bool | None = None,
        out: str = "numeric",
    ) -> Self:
        """Compute the duration between two date/datetime columns.

        Supports column references (``str``) and Polars expressions
        for *start* and *end*.

        The ``add_one`` parameter controls inclusive counting:

        - ``None`` (default): auto-resolves from the target suffix.
          ``*DY`` targets use CDISC study-day convention (no day 0);
          all others add 1 for inclusive counting.
        - ``True``: always add 1 (inclusive).
        - ``False``: raw difference (e.g. PK elapsed time).

        Args:
            target: Name of the output column.
            start: Start date column name or expression.
            end: End date column name or expression.
            unit: Duration unit — ``"seconds"``, ``"minutes"``, ``"hours"``,
                ``"days"`` (default), ``"weeks"``, ``"months"``, ``"years"``.
            add_one: Override for inclusive counting.
            out: Output format — ``"numeric"`` (default) or ``"iso8601"``.

        Returns:
            Self: The namespace with *target* appended; call ``.to_frame()``
                to materialise.

        Examples:
            ISO 8601 duration::

                ex = (
                    raw_df.sdtm
                    .date("EXSTDTC", source="dose_start")
                    .date("EXENDTC", source="dose_end")
                    .duration("EXDUR", start="EXSTDTC", end="EXENDTC",
                              out="iso8601")
                    .to_frame()
                )

            Treatment duration in days::

                adsl = (
                    dm_df.adam.adsl
                    .duration("TRTDURD", start="TRTSDT", end="TRTEDT")
                    .to_frame()
                )
        """
        if not isinstance(start, (str, pl.Expr)):
            raise TypeError(f"start must be a column name (str) or pl.Expr, got {type(start)}")
        if not isinstance(end, (str, pl.Expr)):
            raise TypeError(f"end must be a column name (str) or pl.Expr, got {type(end)}")

        df = self._lazy.collect()

        def _to_date_expr(col_or_expr: str | pl.Expr) -> pl.Expr:
            """Resolve a column reference or expression to a temporal expr."""
            if isinstance(col_or_expr, str):
                col_name = col_or_expr
                if col_name in df.columns:
                    dtype = df[col_name].dtype
                    if dtype == pl.Date:
                        return pl.col(col_name)
                    if dtype.is_(pl.Datetime) or str(dtype).startswith("Datetime"):
                        if unit in ("seconds", "minutes", "hours"):
                            return pl.col(col_name)
                        return pl.col(col_name).cast(pl.Date)
                    # String → try to parse
                    if unit in ("seconds", "minutes", "hours"):
                        return pl.col(col_name).str.to_datetime(strict=False)
                    return pl.col(col_name).str.to_date(strict=False)
                return pl.col(col_name)
            return col_or_expr

        s_expr = _to_date_expr(start)
        e_expr = _to_date_expr(end)

        valid_units = {
            "seconds",
            "minutes",
            "hours",
            "days",
            "weeks",
            "months",
            "years",
        }
        if unit not in valid_units:
            raise ValueError(
                f"duration unit={unit!r} is not supported. Choose one of: {sorted(valid_units)}"
            )

        if unit in ("seconds", "minutes", "hours"):
            s_dtm = s_expr.cast(pl.Datetime("us"))
            e_dtm = e_expr.cast(pl.Datetime("us"))
            diff_s = (e_dtm - s_dtm).dt.total_seconds().cast(pl.Float64)
            if unit == "seconds":
                diff = diff_s.cast(pl.Int64)
            elif unit == "minutes":
                diff = diff_s / 60.0
            else:  # hours
                diff = diff_s / 3600.0
        else:
            diff_days = (e_expr - s_expr).dt.total_days()
            if unit == "days":
                diff = diff_days
            elif unit == "weeks":
                diff = diff_days.cast(pl.Float64) / 7.0
            elif unit == "months":
                diff = diff_days.cast(pl.Float64) / 30.4375
            else:  # years
                diff = diff_days.cast(pl.Float64) / 365.25

        # Resolve add_one
        if add_one is None:
            if target.endswith("DY"):
                # CDISC study day: +1 if >= 0, no day 0
                result_expr = (
                    (pl.when(diff >= 0).then(diff + 1).otherwise(diff)).cast(pl.Int64).alias(target)
                )
                return self._materialise_then(df.with_columns(result_expr))
            else:
                add_one = True

        if add_one:
            result_expr = (diff + 1).alias(target)
        else:
            result_expr = diff.alias(target)

        if out == "iso8601":
            abs_val = diff.abs()
            unit_suffix_map = {
                "days": ("P", "D"),
                "hours": ("PT", "H"),
                "weeks": ("P", "W"),
                "months": ("P", "M"),
                "years": ("P", "Y"),
                "minutes": ("PT", "M"),
                "seconds": ("PT", "S"),
            }
            prefix, suffix = unit_suffix_map[unit]
            iso_expr = (
                pl.lit(prefix) + abs_val.cast(pl.Int64).cast(pl.String) + pl.lit(suffix)
            ).alias(target)
            return self._materialise_then(df.with_columns(iso_expr))

        return self._materialise_then(df.with_columns(result_expr))

    # ------------------------------------------------------------------ #
    # study_day                                                            #
    # ------------------------------------------------------------------ #

    def study_day(
        self,
        target: str,
        *,
        date_col: str,
        ref_col: str | None = None,
        ref_pin: str | None = None,
        ref_df: pl.DataFrame | None = None,
    ) -> Self:
        """Derive a CDISC study day variable from a date column and reference date.

        Uses the CDISC algorithm: ``date - ref_date + 1`` when
        ``date >= ref_date``, else ``date - ref_date`` (no day 0).

        The reference date is resolved in this order:

        1. Explicit ``ref_df=`` parameter (highest priority).
        2. Pinned domain (via ``.pin(...)``).
        3. ``ref_col`` already present in the current frame.
        4. Actionable ``LookupError``.

        Args:
            target: Name of the output study day variable
                (e.g. ``"AESTDY"``, ``"ASTDY"``).
            date_col: Column containing the date to measure from.
            ref_col: Reference date column name.  Defaults to
                ``_STUDY_DAY_REF_COL`` class constant.
            ref_pin: Pinned domain name.  Defaults to
                ``_STUDY_DAY_REF_PIN`` class constant.
            ref_df: Optional explicit DataFrame override — bypasses pinning.

        Returns:
            Self: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Raises:
            LookupError: If the reference date cannot be resolved from
                any source.

        Examples:
            Derive study day from pinned reference::

                ae = (
                    ae_raw.sdtm
                    .pin("DM", dm_df)
                    .study_day("AESTDY", date_col="AESTDTC")
                    .to_frame()
                )

            ADaM study day::

                adae = (
                    ae_df.adam.occds("ADAE")
                    .pin("ADSL", adsl_df)
                    .study_day("ASTDY", date_col="ASTDT")
                    .to_frame()
                )
        """
        from fleet.core.lineage import record_pin_lineage

        # Resolve defaults from class constants
        _ref_col = ref_col if ref_col is not None else self._STUDY_DAY_REF_COL
        _ref_pin = ref_pin if ref_pin is not None else self._STUDY_DAY_REF_PIN

        df = self._lazy.collect()

        # Resolve reference date source
        if ref_df is not None:
            source_df = ref_df
            join_key = ["USUBJID"]
        elif _ref_col in df.columns:
            # ref_col already in frame — no join needed
            date_expr = pl.col(date_col)
            ref_expr = pl.col(_ref_col)
            # Handle both Date and String types
            if df.schema.get(date_col) == pl.String:
                date_expr = date_expr.str.to_date(format="%Y-%m-%d", strict=False)
            if df.schema.get(_ref_col) == pl.String:
                ref_expr = ref_expr.str.to_date(format="%Y-%m-%d", strict=False)
            diff = (date_expr - ref_expr).dt.total_days()
            study_day_expr = pl.when(diff >= 0).then(diff + 1).otherwise(diff).alias(target)
            return self._materialise_then(df.with_columns(study_day_expr))
        else:
            source_df = self._require_pin(_ref_pin.upper(), "study_day", columns=[_ref_col])
            join_key = self._pin_join_key(_ref_pin.upper())

        # Join, compute, drop temp column
        ref_slim = source_df.select(
            [c for c in dict.fromkeys(join_key + [_ref_col]) if c in source_df.columns]
        ).unique(subset=join_key)

        _ref_tmp = f"__pin_{_ref_col}__"
        ref_slim = ref_slim.rename({_ref_col: _ref_tmp})

        df = df.join(ref_slim, on=join_key, how="left")

        date_expr = pl.col(date_col)
        ref_expr = pl.col(_ref_tmp)
        if df.schema.get(date_col) == pl.String:
            date_expr = date_expr.str.to_date(format="%Y-%m-%d", strict=False)
        if df.schema.get(_ref_tmp) == pl.String:
            ref_expr = ref_expr.str.to_date(format="%Y-%m-%d", strict=False)

        diff = (date_expr - ref_expr).dt.total_days()
        study_day_expr = pl.when(diff >= 0).then(diff + 1).otherwise(diff).alias(target)
        df = df.with_columns(study_day_expr).drop(_ref_tmp)

        new = self._materialise_then(df)

        # Record variable lineage
        from fleet.core.dag import VariableNode

        var_lineage: list = list(getattr(new, "_lineage", []))
        var_lineage.append(
            VariableNode(
                name=target,
                verb="study_day",
                sources=[date_col, _ref_col],
                method=f"{self.__class__.__module__}.{self.__class__.__qualname__}.study_day",
                domain=getattr(new, "_domain", None),
            )
        )
        new._lineage = var_lineage

        # Record pin lineage
        record_pin_lineage(
            new,
            target_col=target,
            verb="study_day",
            source_domain=_ref_pin.upper(),
            source_cols=[_ref_col],
            join_key=join_key,
            relationship="derivation",
        )
        return new

    # ------------------------------------------------------------------ #
    # seq                                                                   #
    # ------------------------------------------------------------------ #

    def seq(
        self,
        target: str = "ASEQ",
        *,
        order_by: list[str] | None = None,
        groups: list[str] | None = None,
        start_at: int = 1,
        check_uniqueness: bool = False,
    ) -> Self:
        """Derive a 1-based sequence number within each group.

        Generates a 1-based integer sequence that uniquely identifies each
        record within a grouping partition.  The dataset is sorted by
        *order_by* columns within each *groups* partition before numbering
        — ensuring deterministic, reproducible sequence values.

        Args:
            target: Name of the output sequence variable (e.g. ``"AESEQ"``,
                ``"ASEQ"``).
            order_by: Columns that define the sort order within each group.
                When ``None``, the current row order is preserved.
            groups: Partition columns.  Defaults to class constant
                ``_SEQ_DEFAULT_GROUPS``.
            start_at: First sequence value (default ``1``).
            check_uniqueness: If ``True``, emit a warning when the
                combination of *groups* + *order_by* does not uniquely
                identify each row.

        Returns:
            Self: A fresh namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            SDTM sequence number::

                ae = (
                    raw_df.sdtm
                    .seq("AESEQ", order_by=["AESTDTC"])
                    .to_frame()
                )

            ADaM sequence number::

                adae = (
                    ae_df.adam.occds
                    .seq("ASEQ", order_by=["ASTDT"], groups=["USUBJID"])
                    .to_frame()
                )
        """
        from fleet.core.seq import derive_seq

        grps = groups or list(self._SEQ_DEFAULT_GROUPS)
        df = derive_seq(
            self._lazy.collect(),
            target,
            order_by=order_by,
            groups=grps,
            start_at=start_at,
            check_uniqueness=check_uniqueness,
        )
        return self._materialise_then(df)

    # ------------------------------------------------------------------ #
    # validate                                                             #
    # ------------------------------------------------------------------ #

    def validate(
        self,
        dataset_or_domain: str,
        version: str | None = None,
        rules_engine_path: Path | None = None,
    ) -> Self:
        """Run CDISC conformance validation and print the report.

        Returns *self* so the chain can continue after validation.

        Dispatches to either SDTM or ADaM validation based on the
        ``_VALIDATE_STANDARD`` class constant.

        Args:
            dataset_or_domain: Domain code (SDTM: e.g. ``"DM"``) or
                dataset name (ADaM: e.g. ``"ADSL"``).
            version: IG version to validate against.  Defaults to
                ``_VALIDATE_DEFAULT_VERSION``.
            rules_engine_path: Optional path to a custom rules engine.

        Returns:
            Self: The same namespace instance (for continued chaining).

        Examples:
            Validate an SDTM domain::

                dm = (
                    raw_df.sdtm
                    .hardcode_no_ct("DOMAIN", value="DM")
                    .validate("DM")
                    .to_frame()
                )

            Validate an ADaM dataset::

                adsl = (
                    dm_df.adam.adsl
                    .validate("ADSL")
                    .to_frame()
                )
        """
        from fleet.validation.service import ValidationService

        ver = version if version is not None else self._VALIDATE_DEFAULT_VERSION
        svc = ValidationService(rules_engine_path=rules_engine_path)

        if self._VALIDATE_STANDARD == "adam":
            result = svc.validate_adam(self.to_frame(), dataset=dataset_or_domain, version=ver)
        else:
            result = svc.validate_sdtm(self.to_frame(), domain=dataset_or_domain, version=ver)

        result.print_report()
        return self

    # ------------------------------------------------------------------ #
    # select                                                               #
    # ------------------------------------------------------------------ #

    def select(
        self,
        columns: list[str] | None = None,
        *,
        spec: str | Path | None = None,
        dataset: str | None = None,
        drop_pattern: str | None = r"^_",
    ) -> Self:
        """Materialise the pipeline then select and reorder columns.

        Resolution order:

        1. ``spec`` + ``dataset``: derive the ordered column list from a
           ``define.yaml``.  Only columns present in the frame are kept.
        2. ``columns``: explicit list to keep (in that order).
        3. Neither: keep all current columns (subject to ``drop_pattern``).

        ``drop_pattern`` (default ``r"^_"``): regex applied *before* the
        explicit selection — columns whose names match are removed.  This
        enforces the convention that ``_``-prefixed columns are scratch
        variables.  Set to ``None`` to disable (e.g. during debugging).

        Args:
            columns: Explicit list of columns to keep (in order).
            spec: Path to a ``define.yaml`` file.
            dataset: Dataset name within the spec.
            drop_pattern: Regex for columns to auto-drop.

        Returns:
            Self: A fresh namespace wrapping the selected frame.

        Examples:
            Keep only spec columns::

                dm = (
                    raw_df.sdtm
                    .select(spec="specs/sdtm/define.yaml", dataset="DM")
                    .to_frame()
                )
        """
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

        return self._materialise_then(df)

    @staticmethod
    def _spec_dataset_meta(
        spec_path: Path, dataset: str | None
    ) -> tuple[list[str], dict[str, str]]:
        """Return ``(column_names, date_type_map)`` for *dataset* from a define.yaml."""
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
