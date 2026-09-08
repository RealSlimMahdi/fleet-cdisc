"""
Shared verb mixin — base class for both SDTM and ADaM namespaces.

Provides the verbs whose logic is identical (or parameterised-identical)
across the SDTM and ADaM namespace hierarchies:

Infrastructure (Group A):
    ``_chain``, ``_materialise_then``, ``to_frame``, ``to_dataset_json``,
    ``inspect``, ``explain``, ``trail``, ``write_parquet``

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
import difflib
import importlib
import re
import sys
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, cast, overload

import polars as pl
import yaml

from fleet.core import log as fleet_log
from fleet.core.define_spec import DefineSpec, load_define_spec
from fleet.core.exceptions import (
    ComparisonError,
    DerivationError,
    SpecError,
    ValidationError,
    VerbUsageError,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from fleet.comparison import ComparisonReport
    from fleet.comparison.report import MaxPrint
    from fleet.core.derivation import Derivation
    from fleet.core.frames import DataFrame
    from fleet.ct.validator import CTValidator
    from fleet.validation.models import ValidationResult

logger = fleet_log.get_logger(__name__)

# Valid Implementation Guide versions supported by the CDISC Rules Engine.
_VALID_SDTM_VERSIONS = {"3.1.2", "3.1.3", "3.2", "3.3", "3.4"}
_VALID_ADAM_VERSIONS = {"1.0", "1.1", "1.2", "1.3"}


#: What ``on_fail`` accepts on the checking verbs (``validate``, ``compare``).
_ON_FAIL_VALUES = ("warn", "raise", "ignore")


def _check_on_fail(verb: str, on_fail: str) -> None:
    """Raise ``DerivationError`` if *on_fail* is not one of :data:`_ON_FAIL_VALUES`."""
    if on_fail not in _ON_FAIL_VALUES:
        raise DerivationError(
            f"{verb} on_fail={on_fail!r} is not supported. Choose 'warn', 'raise', or 'ignore'."
        )


def _settle_on_fail(on_fail: str, summary: str, error: type[Exception]) -> None:
    """Apply *on_fail* to a failed check: raise *error*, warn, or stay silent.

    The warning points at the verb's caller, two frames up from here.
    """
    if on_fail == "raise":
        raise error(summary)
    if on_fail == "warn":
        warnings.warn(summary, stacklevel=3)


def _check_ig_version(version: str, *, standard: str) -> None:
    """Raise ``DerivationError`` if *version* is not a valid IG version for *standard*."""
    if standard == "adam":
        valid = _VALID_ADAM_VERSIONS
        label = "ADaM IG"
    else:
        valid = _VALID_SDTM_VERSIONS
        label = "SDTM IG"
    if version not in valid:
        sorted_versions = sorted(valid, key=lambda v: [int(x) for x in v.split(".")])
        raise DerivationError(
            f"Invalid {label} version '{version}'. Supported versions: {', '.join(sorted_versions)}"
        )


#: Spec-format version this Fleet build understands (``fleet_spec_version``).
SUPPORTED_SPEC_VERSION = 1


def _check_spec_version(spec: DefineSpec, *, source: str) -> None:
    """Raise ``SpecError`` when the spec declares an unknown future version."""
    version = spec.fleet_spec_version
    if version is not None and version != SUPPORTED_SPEC_VERSION:
        raise SpecError(
            f"{source}: unsupported fleet_spec_version {version!r}. "
            f"This Fleet version supports fleet_spec_version {SUPPORTED_SPEC_VERSION}."
        )


def _import_derivations_module(spec: DefineSpec, *, source: str) -> None:
    """Import the spec-declared ``derivations_module`` (callable registrations)."""
    module = spec.derivations_module
    if not module:
        return
    try:
        importlib.import_module(str(module))
    except ImportError as err:
        raise SpecError(f"{source}: cannot import derivations_module '{module}': {err}") from err


#: Variable-level metadata keys merged into the derivation dict so that
#: algorithms like ``nsv`` can consume them.
_SPEC_META_KEYS = ("label", "origin", "role", "evaluator")


def _extract_spec_variables(
    spec: DefineSpec, dataset: str | None
) -> tuple[str, list[tuple[str, dict]]]:
    """Return ``(dataset_name, [(variable_name, derivation_dict), ...])``.

    Handles both the define.yaml format (top-level ``datasets`` where each
    variable carries a ``derivation`` block) and the simplified
    single-dataset format (top-level ``variables`` with inline algorithm
    fields).  Variables without a derivation are carry-through columns and
    are skipped.
    """
    if spec.datasets is not None:
        ds = spec.select(dataset)
        out: list[tuple[str, dict]] = []
        for var in ds.variables:
            drv = var.derivation
            if not drv:
                continue  # no derivation → carry-through / manual column
            # Backward compat: callable: without algorithm: → inject algorithm.
            if "callable" in drv and "algorithm" not in drv:
                drv = {**drv, "algorithm": "callable"}
            merged = dict(drv)
            for meta in _SPEC_META_KEYS:
                value = getattr(var, meta, None)
                if value and meta not in merged:
                    merged[meta] = value
            out.append((var.name, merged))
        return ds.name, out

    # Simplified single-dataset format (domain:/dataset: + variables:).
    ds_name = spec.domain or spec.dataset or "spec"
    out = []
    for var in spec.variables or []:
        entry = dict(var)
        if "callable" in entry and "algorithm" not in entry:
            entry["algorithm"] = "callable"
        name = entry.pop("target", None) or entry.pop("name", None)
        out.append((name, entry))
    return str(ds_name), out


def _dtype_to_spec_type(dtype: pl.DataType | None) -> str:
    """Map a Polars dtype onto the define-spec ``type`` vocabulary."""
    if dtype is None:
        return "text"
    if dtype == pl.Date:
        return "date"
    if isinstance(dtype, pl.Datetime) or str(dtype).startswith("Datetime"):
        return "datetime"
    try:
        if dtype.is_integer():
            return "integer"
        if dtype.is_float():
            return "float"
    except AttributeError:  # pragma: no cover — older polars
        pass
    return "text"


def _indent_yaml(text: str, spaces: int) -> str:
    """Indent every non-empty line of a YAML fragment by *spaces*."""
    pad = " " * spaces
    return "\n".join(pad + ln if ln.strip() else ln for ln in text.rstrip().splitlines())


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

    def _chain(
        self,
        *exprs: pl.Expr,
        verb: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Self:
        """Append expressions to the lazy plan; return a *new* namespace.

        Every expression's root columns are validated against the
        accumulated lazy schema (schema resolution only — no data is
        read), so a column typo raises a verb-attributed
        ``DerivationError`` at the offending verb call instead of a raw
        Polars error at ``to_frame()``.  Columns chained by previous
        verbs are already part of the accumulated schema and validate
        fine.

        *verb* is the user-facing verb name recorded in the error and in
        lineage; when omitted it is derived from the calling function's
        name.  *params* are the verb's keyword arguments recorded in
        lineage for spec round-tripping (``to_spec_yaml``); when omitted
        a best-effort stack capture is attempted.
        """
        from fleet.core.lineage import record_lineage

        if verb is None:
            try:
                verb = sys._getframe(1).f_code.co_name.lstrip("_") or "unknown"
            except Exception:
                verb = "unknown"
        self._validate_chain_exprs(exprs, verb)
        new = copy.copy(self)
        new._lazy = self._lazy.with_columns(list(exprs))
        record_lineage(new, exprs, verb=verb, params=params)
        return new

    def _validate_chain_exprs(self, exprs: tuple[pl.Expr, ...], verb: str) -> None:
        """Validate expression root columns against the lazy schema.

        Cheap by construction: ``collect_schema()`` resolves the plan's
        schema without reading data.  Unresolvable roots (wildcards,
        regex selectors) are skipped.
        """
        if not exprs:
            return
        try:
            schema_names = self._lazy.collect_schema().names()
        except Exception:
            # Schema resolution failed for unrelated reasons — let Polars
            # surface its own error at collect time.
            return
        available = set(schema_names)
        for expr in exprs:
            try:
                roots = expr.meta.root_names()
            except Exception:
                continue
            for root in roots:
                if root in available or root == "*" or root.startswith("^"):
                    continue
                try:
                    out_name = expr.meta.output_name()
                except Exception:
                    out_name = None
                suggestion = difflib.get_close_matches(root, schema_names, n=1)
                hint = f" Did you mean '{suggestion[0]}'?" if suggestion else ""
                target_part = f"({out_name!r})" if out_name else ""
                shown = schema_names if len(schema_names) <= 25 else schema_names[:25]
                more = "" if len(schema_names) <= 25 else f" (+{len(schema_names) - 25} more)"
                raise DerivationError(
                    f"{verb}{target_part}: column '{root}' not found in the frame.{hint} "
                    f"Available columns: {shown}{more}"
                )

    def _materialise_then(self, df: pl.DataFrame) -> Self:
        """Return a fresh namespace wrapping *df* as a new lazy plan."""
        new = copy.copy(self)
        new._lazy = df.lazy()
        return new

    def _with_lazy(self, lf: pl.LazyFrame) -> Self:
        """Return a fresh namespace continuing from lazy plan *lf*.

        Like ``_chain`` but for verbs that restructure the plan (joins,
        sorts, filters) rather than appending column expressions; no
        lineage is recorded.
        """
        new = copy.copy(self)
        new._lazy = lf
        return new

    def to_frame(self) -> DataFrame:
        """Materialise the accumulated pipeline into a Polars DataFrame.

        Returns:
            DataFrame: The fully materialised result of all chained
                verbs — a plain ``pl.DataFrame`` at runtime, typed as
                :class:`fleet.DataFrame` so re-entering ``.sdtm`` /
                ``.adam`` / ``.tlg`` type-checks.

        Raises:
            DerivationError: When collection fails because a column is
                missing — enriched with the lineage entries that
                reference the column, so the error names the verb(s)
                involved.

        Examples:
            Collect the pipeline result::

                result = (
                    df.sdtm
                    .assign("DOMAIN", value="DM")
                    .assign("USUBJID", source="subject_id")
                    .to_frame()
                )
        """
        try:
            df = self._lazy.collect()
        except (
            pl.exceptions.ColumnNotFoundError,
            pl.exceptions.SchemaFieldNotFoundError,
            pl.exceptions.StructFieldNotFoundError,
        ) as err:
            raise self._enrich_collect_error(err) from err
        run_checks = getattr(self, "_run_pending_fk_checks", None)
        if run_checks is not None:
            run_checks(df)
        return cast("DataFrame", df)

    def _enrich_collect_error(self, err: Exception) -> DerivationError:
        """Translate a Polars missing-column error into a lineage-aware one."""
        raw = str(err)
        match = re.search(r'"([^"]+)"', raw)
        col = match.group(1) if match else None
        first_line = raw.splitlines()[0] if raw else type(err).__name__
        lines = [f"Pipeline collection failed: {first_line}"]
        if col is not None:
            nodes = [
                node
                for node in getattr(self, "_lineage", [])
                if node.name == col or col in node.sources
            ]
            if nodes:
                lines.append(f"Derivations referencing '{col}':")
                for node in nodes:
                    srcs = ", ".join(node.sources) if node.sources else "literal"
                    lines.append(f"  - {node.name} ← {node.verb}({srcs})")
        return DerivationError("\n".join(lines))

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
                    .assign("DOMAIN", value="DM")
                    .assign("USUBJID", source="subject_id")
                    .to_dataset_json("outputs/dm.json", domain="DM")
                )
        """
        from fleet.io.dataset_json import save_dataset_json

        return save_dataset_json(self._lazy.collect(), path, domain=domain, label=label)

    def inspect(self, prefix: str = "DEBUG") -> Self:
        """Materialise the pipeline at this point and log its state.

        Creates a hard checkpoint: the pipeline resumes from the
        materialised frame, making it easy to isolate exactly where a
        derivation goes wrong.  Output goes through the ``"fleet"``
        logger (INFO level, stdout by default — see
        :mod:`fleet.core.log`).

        Args:
            prefix: Label logged alongside the diagnostic output.

        Returns:
            Self: A fresh namespace wrapping the materialised frame;
                call further verbs or ``.to_frame()`` to continue.

        Examples:
            Inspect the pipeline after assigning key variables::

                result = (
                    df.sdtm
                    .assign("DOMAIN", value="DM")
                    .inspect(prefix="After DOMAIN")
                    .assign("USUBJID", source="subject_id")
                    .to_frame()
                )
        """
        df = self._lazy.collect()
        fleet_log.ensure_default_handler()
        logger.info("[%s] Schema: %s", prefix, df.schema)
        logger.info("[%s] Shape:  %s", prefix, df.shape)
        logger.info("%s", df.head(5))
        return self._materialise_then(df)

    def explain(self) -> Self:
        """Log the current Polars query plan without materialising.

        Useful for understanding how Polars will optimise the accumulated
        derivation pipeline.  Output goes through the ``"fleet"`` logger
        (INFO level, stdout by default — see :mod:`fleet.core.log`).

        Returns:
            Self: The same namespace instance (unchanged); call
                further verbs or ``.to_frame()`` to continue.

        Examples:
            Log the query plan before collecting::

                result = (
                    df.sdtm
                    .assign("DOMAIN", value="DM")
                    .explain()
                    .to_frame()
                )
        """
        fleet_log.ensure_default_handler()
        logger.info("%s", self._lazy.explain())
        return self

    def trail(self) -> Self:
        """Log a table of each derived variable's origin in the pipeline.

        Renders the accumulated variable lineage — the verb that produced
        each column and the source columns it consumed, including
        cross-domain pin sources — as a table through the ``"fleet"``
        logger (INFO level, stdout by default — see
        :mod:`fleet.core.log`), then returns the namespace unchanged so
        the chain continues. Unlike ``inspect``, nothing is
        materialised: the trail is pure metadata captured automatically on
        every verb call.

        Only *derived* variables appear; columns that pass through untouched
        from the source frame are not listed. When a variable is derived more
        than once, each derivation is shown in pipeline order. Variables with
        no source column (e.g. hardcoded constants) are marked ``(literal)``.

        Returns:
            Self: The same namespace instance (unchanged); call further
                verbs or ``.to_frame()`` to continue.

        Examples:
            Print the origin of every derived variable before collecting::

                ae = (
                    ae_raw.sdtm
                    .assign("USUBJID", source="patient_number")
                    .assign("AESTDTC", source="ae_start_date")
                    .pin("DM", dm)
                    .study_day("AESTDY", date_col="AESTDTC")
                    .trail()
                    .to_frame()
                )
        """
        from fleet.core.lineage import lineage_of, pin_lineage_of

        fleet_log.ensure_default_handler()
        nodes = lineage_of(self)
        if not nodes:
            logger.info("Variable trail: (empty — no derivations recorded yet)")
            return self

        # Group cross-domain pin sources by the variable they feed.
        pin_origins: dict[str, list[str]] = {}
        pinned_cols: dict[str, set[str]] = {}
        for dep in pin_lineage_of(self):
            cols = ", ".join(dep.source_cols) if dep.source_cols else "*"
            label = f"{dep.source_domain}.{cols}"
            if dep.relationship != "derivation":
                label += f" [{dep.relationship}]"
            pin_origins.setdefault(dep.target_col, []).append(label)
            pinned_cols.setdefault(dep.target_col, set()).update(dep.source_cols)

        has_domain = any(node.domain for node in nodes)
        rows: list[dict[str, object]] = []
        for i, node in enumerate(nodes, start=1):
            # Drop bare local sources already attributed to a pinned domain.
            covered = pinned_cols.get(node.name, set())
            local = [src for src in node.sources if src not in covered]
            origins = list(dict.fromkeys([*local, *pin_origins.get(node.name, [])]))
            row: dict[str, object] = {
                "#": i,
                "Variable": node.name,
                "Verb": node.verb,
                "Origin": ", ".join(origins) if origins else "(literal)",
            }
            if has_domain:
                row["Domain"] = node.domain or "—"
            rows.append(row)

        table = pl.DataFrame(rows)
        logger.info("Variable trail (%d derivation(s)):", table.height)
        with pl.Config(
            tbl_hide_dataframe_shape=True,
            tbl_hide_column_data_types=True,
            fmt_str_lengths=100,
            tbl_rows=table.height,
        ):
            logger.info("%s", table)
        return self

    def write_parquet(
        self,
        path: str | Path,
        *,
        mkdir: bool = True,
    ) -> DataFrame:
        """Materialise the pipeline, write to Parquet, and return the DataFrame.

        This is a drop-in alternative to ``to_frame()`` when you want to
        persist the dataset as part of the chain.

        Args:
            path: Destination file path.
            mkdir: When ``True`` (default) any missing parent directories
                are created automatically.

        Returns:
            DataFrame: The materialised result (typed as
                :class:`fleet.DataFrame` — see ``to_frame()``).

        Examples:
            Write a domain to Parquet::

                dm = (
                    raw_df.sdtm
                    .assign("USUBJID", source="patient_number")
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
    # Canonical verbs (naming unification)                                 #
    # ------------------------------------------------------------------ #

    def assign(
        self,
        target: str,
        *,
        source: str | None = None,
        value: Any | None = None,
        ct: str | type | None = None,
        ct_map: dict[str, str] | None = None,
        ct_validator: CTValidator | None = None,
        validate_values: bool | None = None,
    ) -> Self:
        """Assign *target* from a source column or a literal value.

        The one canonical assignment verb.  Exactly one of *source* /
        *value* must be given; controlled-terminology behaviour is
        toggled by the presence of *ct* / *ct_map*.

        Args:
            target: Name of the output variable to create.
            source: Input column to copy from.  Mutually exclusive with
                *value*.
            value: Literal value to broadcast to every row.  Mutually
                exclusive with *source*.
            ct: CDISC CT codelist for validation — a generated codelist
                class (e.g. ``SEX``) or an NCI concept ID string
                (e.g. ``"C66731"``).  With *source* and no *ct_map*,
                values are passed through and validated; with *value*,
                the literal is validated at pipeline-build time.
            ct_map: Explicit ``{raw_value: ct_value}`` mapping applied to
                *source* (raw codes that need remapping).  Requires
                *source*.
            ct_validator: Optional pre-built validator instance.
            validate_values: Controls the pass-through validation (no
                effect when *ct_map* is given).  ``None`` (default):
                validate whenever codelist terms are available and warn
                about the degradation otherwise.  ``False``: skip
                validation silently.

        Returns:
            Self: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Raises:
            DerivationError: When neither or both of *source* / *value*
                are given.
            VerbUsageError: When *ct_map* is combined with *value*.

        Examples:
            Copy, hardcode, and CT-map in one vocabulary::

                dm = (
                    raw_df.sdtm
                    .assign("USUBJID", source="subject_id")
                    .assign("DOMAIN", value="DM")
                    .assign("SEX", source="sex", ct=SEX,
                            ct_map={"1": "M", "2": "F"})
                    .to_frame()
                )
        """
        return self._assign_impl(
            target,
            source=source,
            value=value,
            ct=ct,
            ct_map=ct_map,
            ct_validator=ct_validator,
            validate_values=validate_values,
            verb="assign",
            fk=True,
        )

    def _assign_impl(
        self,
        target: str,
        *,
        source: str | None = None,
        value: Any | None = None,
        ct: str | type | None = None,
        ct_map: dict[str, str] | None = None,
        ct_validator: CTValidator | None = None,
        validate_values: bool | None = None,
        verb: str = "assign",
        fk: bool = True,
    ) -> Self:
        """Implementation behind ``assign``.

        *verb* is recorded in lineage/errors (spec-driven runs attribute
        the spec algorithm); *fk* controls the automatic foreign-key check.
        """
        if (source is None) == (value is None):
            raise DerivationError(f"{verb}('{target}'): pass exactly one of source= or value=.")
        if value is not None and ct_map is not None:
            raise VerbUsageError(
                f"{verb}('{target}'): ct_map= requires source= — a literal value "
                "cannot be mapped through a raw-to-CT dictionary."
            )

        ct_mode = ct is not None or ct_map is not None
        ct_cls: type | None = ct if (ct is not None and not isinstance(ct, str)) else None
        ct_id: str | None = None
        if ct is not None:
            ct_id = ct if isinstance(ct, str) else (getattr(ct, "_concept_id", None) or ct.__name__)

        lineage_params = {
            "target": target,
            "source": source,
            "value": value,
            "ct": ct_id,
            "ct_map": ct_map,
        }

        # ── value path (hardcode) ──
        if value is not None:
            if ct_mode:
                from fleet.ct.validator import get_validator

                validator = ct_validator or get_validator()
                if ct_id is not None and validator.has_codelist(ct_id):
                    valid, msg = validator.validate_value(ct_id, str(value))
                    if not valid:
                        warnings.warn(msg, stacklevel=3)
                else:
                    warnings.warn(
                        f"{verb}('{target}'): codelist '{ct_id}' not found / CT not "
                        f"loaded — value {value!r} assigned unvalidated. Load CT via "
                        "fleet.get_validator().load_ct_file(...) or drop the ct= "
                        "parameter.",
                        stacklevel=3,
                    )
            ns = self._chain(pl.lit(value).alias(target), verb=verb, params=lineage_params)
            if target == "DOMAIN":
                ns._domain = str(value)
            if fk:
                ns._auto_fk_check(target)
            return ns

        # ── source path ──
        assert source is not None
        if ct_map:
            ns = self._chain(
                pl.col(source).replace(ct_map).alias(target), verb=verb, params=lineage_params
            )
            if fk:
                ns._auto_fk_check(target)
            if validate_values is True and ct_id:
                if ct_validator is None:
                    from fleet.ct.validator import get_validator

                    ct_validator = get_validator()
                # Validate the post-mapping values the column will contain.
                self._warn_invalid_values(
                    source, ct_id, ct_validator, ct_cls, target=target, value_map=ct_map
                )
            return ns

        ns = self._chain(pl.col(source).alias(target), verb=verb, params=lineage_params)
        if fk:
            ns._auto_fk_check(target)

        if not ct_mode or validate_values is False:
            return ns

        # No-mapping CT mode: validate-and-pass-through (values are never
        # rewritten — decoding submission values into NCI preferred terms
        # would corrupt conformant data).
        if ct_validator is None:
            from fleet.ct.validator import get_validator

            ct_validator = get_validator()
        validated = self._warn_invalid_values(
            source, ct_id or "", ct_validator, ct_cls, target=target
        )
        if not validated:
            warnings.warn(
                f"{verb}('{target}'): codelist '{ct_id}' not found / CT not "
                f"loaded — values from '{source}' copied unvalidated. Load CT via "
                "fleet.get_validator().load_ct_file(...), pass an explicit ct_map, "
                "or pass validate_values=False to silence this warning.",
                stacklevel=3,
            )
        return ns

    def _warn_invalid_values(
        self,
        source: str,
        ct_codelist: str,
        ct_validator: CTValidator | None,
        ct_codelist_cls: type | None = None,
        *,
        target: str | None = None,
        value_map: dict[str, str] | None = None,
    ) -> bool:
        """Eagerly check unique *source* values against the loaded codelist.

        Emits a UserWarning for any values not in the valid submission
        terms, naming the dataset (when known), the target variable, and
        the codelist.  Derives valid values from the validator cache
        first, falling back to introspecting the codelist class
        attributes when CT is not loaded.  When *value_map* is given the
        mapping is applied before checking, so the *post-mapping* column
        values are validated.

        Returns:
            True when validation was performed (valid terms were
            available), False when it could not be performed — callers
            use this to report the degradation.
        """
        valid_values: set[str] = set()

        # Strategy 1: from the validator cache
        if ct_validator is not None:
            valid_values = set(ct_validator.get_valid_values(ct_codelist))

        # Strategy 2: introspect the codelist class (works without CT loaded)
        if not valid_values and ct_codelist_cls is not None:
            valid_values = {
                v
                for k, v in vars(ct_codelist_cls).items()
                if not k.startswith("_") and isinstance(v, str)
            }

        if not valid_values:
            return False

        try:
            unique_vals = (
                self._lazy.select(pl.col(source).drop_nulls().unique())
                .collect()
                .to_series()
                .to_list()
            )
        except pl.exceptions.PolarsError:
            # Source values not retrievable — validation did not happen.
            return False
        if value_map:
            unique_vals = list(dict.fromkeys(value_map.get(v, v) for v in unique_vals))
        invalid = [v for v in unique_vals if v not in valid_values]
        if invalid:
            domain = getattr(self, "_domain", None)
            where = f"{domain}.{target}" if domain and target else (target or source)
            warnings.warn(
                f"{where}: column '{source}' contains values not in codelist "
                f"'{ct_codelist}': {invalid}. "
                f"Valid values: {sorted(valid_values)}. "
                f"Consider providing a ct_map parameter.",
                stacklevel=3,
            )
        return True

    def case_when(
        self,
        target: str,
        *,
        when: list[dict[str, Any]],
        else_: Any = None,
    ) -> Self:
        """Multi-branch conditional derivation (first matching branch wins).

        The one canonical conditional verb.

        Args:
            target: Name of the output variable.
            when: Ordered list of ``{"condition": expr, "value": any}``
                dicts.  ``condition`` may be a Polars expression or an
                expression string.
            else_: Fallback value when no branch matches.

        Returns:
            Self: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Derive an age group::

                adsl = (
                    dm_df.adam.adsl
                    .case_when("AGEGR1", when=[
                        {"condition": 'pl.col("AGE") < 65', "value": "<65"},
                        {"condition": 'pl.col("AGE") < 75', "value": "65-74"},
                    ], else_=">=75")
                    .to_frame()
                )
        """
        return self._case_when_impl(target, when=when, else_=else_, verb="case_when")

    def _case_when_impl(
        self,
        target: str,
        *,
        when: list[dict[str, Any]],
        else_: Any,
        verb: str = "case_when",
    ) -> Self:
        """Implementation behind ``case_when``."""
        from fleet.sdtm.utils import parse_expression

        def _cond(raw: Any) -> pl.Expr:
            return raw if isinstance(raw, pl.Expr) else parse_expression(str(raw))

        params = {"target": target, "when": when, "else_": else_}
        if not when:
            return self._chain(pl.lit(else_).alias(target), verb=verb, params=params)
        first = when[0]
        chain = pl.when(_cond(first["condition"])).then(pl.lit(first["value"]))
        for branch in when[1:]:
            chain = chain.when(_cond(branch["condition"])).then(pl.lit(branch["value"]))
        return self._chain(chain.otherwise(pl.lit(else_)).alias(target), verb=verb, params=params)

    def merge(
        self,
        dataset: pl.DataFrame | pl.LazyFrame | None = None,
        *,
        on: str | list[str] | None = None,
        how: str = "left",
        keep: list[str] | None = None,
        where: str | pl.Expr | None = None,
    ) -> Self:
        """Join *dataset* into the pipeline using key column(s) *on*.

        The one canonical join verb.  The join is appended to the lazy
        plan; nothing is materialised.

        Args:
            dataset: The ``pl.DataFrame`` / ``pl.LazyFrame`` to merge in.
            on: Key column name(s) for the join.
            how: Join strategy (default ``"left"``).
            keep: Optional columns to keep from the joined result — the
                output is restricted to the *on* key(s) plus these
                columns (order preserved).  When ``None``, all columns
                are retained.
            where: Optional filter expression applied to *dataset*
                before the join.

        Returns:
            Self: The namespace continuing from the joined plan.

        Raises:
            VerbUsageError: When *dataset* or *on* is missing.
            DerivationError: When a *keep* entry is absent from the
                joined result (with a did-you-mean suggestion).

        Examples:
            Merge supplemental qualifier data onto the DM domain::

                dm = (
                    raw_df.sdtm
                    .assign("DOMAIN", value="DM")
                    .merge(suppdm_df, on="USUBJID", keep=["QVAL"])
                    .to_frame()
                )
        """
        return self._merge_impl(dataset, on=on, how=how, keep=keep, where=where, verb="merge")

    def _merge_impl(
        self,
        dataset: pl.DataFrame | pl.LazyFrame | None,
        *,
        on: str | list[str] | None,
        how: str = "left",
        keep: list[str] | None = None,
        where: str | pl.Expr | None = None,
        verb: str = "merge",
    ) -> Self:
        """Implementation behind ``merge``."""
        from fleet.sdtm.utils import parse_expression

        if isinstance(dataset, pl.LazyFrame):
            right = dataset
        elif isinstance(dataset, pl.DataFrame):
            right = dataset.lazy()
        else:
            raise VerbUsageError(
                f"{verb}() requires dataset= (a DataFrame or LazyFrame), "
                f"got {type(dataset).__name__}."
            )
        if on is None:
            raise VerbUsageError(f"{verb}() requires on= (join key column(s)).")
        if where is not None:
            where_expr = where if isinstance(where, pl.Expr) else parse_expression(str(where))
            right = right.filter(where_expr)

        joined = self._lazy.join(right, on=on, how=how)
        if keep:
            on_list = [on] if isinstance(on, str) else list(on)
            keep_list = list(dict.fromkeys(on_list + list(keep)))
            schema_names = joined.collect_schema().names()
            missing = [c for c in keep_list if c not in schema_names]
            if missing:
                hints = []
                for col in missing:
                    close = difflib.get_close_matches(col, schema_names, n=1)
                    hints.append(f"'{col}'" + (f" (did you mean '{close[0]}'?)" if close else ""))
                raise DerivationError(
                    f"{verb}(keep=...): column(s) {', '.join(hints)} not found "
                    f"in the joined result. Available columns: {schema_names}"
                )
            joined = joined.select(keep_list)
        return self._with_lazy(joined)

    def keep(self, *columns: str | list[str]) -> Self:
        """Restrict the frame to *columns*, in the given order.

        Accepts either variadic names — ``keep("STUDYID", "USUBJID")`` —
        or a single list — ``keep(["STUDYID", "USUBJID"])``.  Stays lazy.

        Args:
            *columns: Column names (or one list of names) to keep.

        Returns:
            Self: The namespace continuing from the restricted plan.

        Raises:
            DerivationError: When a requested column is absent (with a
                did-you-mean suggestion), or no columns are given.

        Examples:
            Keep only the submission variables::

                dm = (
                    raw_df.sdtm
                    .assign("USUBJID", source="subject_id")
                    .keep("STUDYID", "USUBJID", "SEX")
                    .to_frame()
                )
        """
        if len(columns) == 1 and isinstance(columns[0], list):
            cols: list[str] = list(columns[0])
        else:
            cols = [c for c in columns]  # type: ignore[misc]
        if not cols:
            raise DerivationError("keep() requires at least one column name.")
        schema_names = self._lazy.collect_schema().names()
        missing = [c for c in cols if c not in schema_names]
        if missing:
            hints = []
            for col in missing:
                close = difflib.get_close_matches(col, schema_names, n=1)
                hints.append(f"'{col}'" + (f" (did you mean '{close[0]}'?)" if close else ""))
            raise DerivationError(
                f"keep(): column(s) {', '.join(hints)} not found in the frame. "
                f"Available columns: {schema_names}"
            )
        return self._with_lazy(self._lazy.select(cols))

    # ------------------------------------------------------------------ #
    # verbs — programmatic verb listing                                    #
    # ------------------------------------------------------------------ #

    #: Public methods that are infrastructure rather than verbs — kept
    #: out of the ``verbs()`` listing.
    _VERBS_EXCLUDE: ClassVar[frozenset[str]] = frozenset({"verbs"})

    def verbs(self) -> pl.DataFrame:
        """List the public verbs available on this namespace.

        Walks the class MRO collecting public Fleet-defined methods and
        returns a tidy frame with each verb's name and the first
        sentence of its docstring.  This is the always-current
        alternative to hard-coded verb counts in docs.

        Returns:
            pl.DataFrame: Columns ``verb`` and ``summary``, sorted by
                verb name.

        Examples:
            Discover what an SDTM pipeline can do::

                import fleet  # noqa: F401

                catalog = raw_df.sdtm.verbs()
                print(catalog)
        """
        from fleet.core.algorithm_resolver import docstring_summary

        rows: list[dict[str, str]] = []
        seen: set[str] = set(self._VERBS_EXCLUDE)
        for klass in type(self).__mro__:
            if not klass.__module__.startswith("fleet."):
                continue
            for name, attr in vars(klass).items():
                if name.startswith("_") or name in seen:
                    continue
                seen.add(name)
                if isinstance(attr, (property, staticmethod, classmethod)):
                    continue
                if not callable(attr):
                    continue
                rows.append({"verb": name, "summary": docstring_summary(attr.__doc__)})
        rows.sort(key=lambda r: r["verb"])
        return pl.DataFrame(rows, schema={"verb": pl.String, "summary": pl.String})

    # ------------------------------------------------------------------ #
    # Algorithmic (Group B)                                                #
    # ------------------------------------------------------------------ #

    @overload
    def derivation(
        self,
        target: str,
        *,
        expression: str | pl.Expr | Callable[[], pl.Expr],
    ) -> Self: ...

    @overload
    def derivation(self, target: Derivation) -> Self: ...

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
            raise DerivationError("target is required when expression= is provided.")
        if expression is None:
            raise DerivationError("expression is required when target is a string.")

        params = {"target": target, "expression": expression}

        # Case 2: direct pl.Expr.
        if isinstance(expression, pl.Expr):
            return self._chain(expression.alias(target), verb="derivation", params=params)

        # Case 3: lambda / zero-arg callable.
        if callable(expression) and not isinstance(expression, str):
            expr = expression()
            if not isinstance(expr, pl.Expr):
                raise VerbUsageError(
                    f"expression callable must return pl.Expr, got {type(expr).__name__}"
                )
            return self._chain(expr.alias(target), verb="derivation", params=params)

        # Case 1: string through AST sandbox.
        return self._chain(
            parse_expression(str(expression)).alias(target), verb="derivation", params=params
        )

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
            ns = self._chain(expr.alias(drv.targets[0]), verb="derivation", params={})
            # Registered derivations round-trip via to_spec_yaml as
            # `algorithm: callable` blocks referencing their dotted path.
            if ns._lineage:
                ns._lineage[-1].spec = {"algorithm": "callable", "callable": drv.dotted_path}
            return ns

        df = self.to_frame()
        result = drv(df)
        if not isinstance(result, pl.DataFrame):
            raise VerbUsageError(
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
        unit: Literal["seconds", "minutes", "hours", "days", "weeks", "months", "years"] = "days",
        add_one: bool | None = None,
        out: Literal["numeric", "iso8601"] = "numeric",
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
                ``"iso8601"`` is incompatible with the ``*DY`` study-day
                convention: pass ``add_one`` explicitly (or use a non-DY
                target) to combine them.

        Returns:
            Self: The namespace with *target* appended; call ``.to_frame()``
                to materialise.

        Raises:
            DerivationError: On an unknown *unit*/*out* value, or when
                ``out="iso8601"`` is combined with a ``*DY`` target while
                ``add_one`` is unset (the study-day convention would
                silently override the requested format).

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
            raise VerbUsageError(f"start must be a column name (str) or pl.Expr, got {type(start)}")
        if not isinstance(end, (str, pl.Expr)):
            raise VerbUsageError(f"end must be a column name (str) or pl.Expr, got {type(end)}")
        if out not in ("numeric", "iso8601"):
            raise DerivationError(
                f"duration out={out!r} is not supported. Choose 'numeric' or 'iso8601'."
            )
        if out == "iso8601" and add_one is None and target.endswith("DY"):
            raise DerivationError(
                f"duration('{target}', out='iso8601'): targets ending in 'DY' follow the "
                "CDISC study-day convention (integer day count, no day 0) and always "
                "produce numeric output, so out='iso8601' would be ignored. Either use a "
                "target that does not end in 'DY', or pass add_one=True/False explicitly "
                "to opt out of the study-day convention and get ISO 8601 output."
            )

        duration_params = {
            "target": target,
            "start": start,
            "end": end,
            "unit": unit,
            "add_one": add_one,
            "out": out,
        }

        schema = self._lazy.collect_schema()

        def _to_date_expr(col_or_expr: str | pl.Expr) -> pl.Expr:
            """Resolve a column reference or expression to a temporal expr."""
            if isinstance(col_or_expr, str):
                col_name = col_or_expr
                dtype = schema.get(col_name)
                if dtype is not None:
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
            raise DerivationError(
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
                return self._chain(result_expr, verb="duration", params=duration_params)
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
            return self._chain(iso_expr, verb="duration", params=duration_params)

        return self._chain(result_expr, verb="duration", params=duration_params)

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
        dm: pl.DataFrame | None = None,
        adsl: pl.DataFrame | None = None,
    ) -> Self:
        """Derive a CDISC study day variable from a date column and reference date.

        Uses the CDISC algorithm: ``date - ref_date + 1`` when
        ``date >= ref_date``, else ``date - ref_date`` (no day 0).

        The reference date is resolved in this order:

        1. Explicit ``ref_df=`` parameter (highest priority).  ``dm=``
           and ``adsl=`` are accepted aliases of ``ref_df=`` matching
           the SDTM/ADaM vocabulary.
        2. Pinned domain (via ``.pin(...)``).
        3. ``ref_col`` already present in the current frame.
        4. Actionable ``LookupError``.

        Args:
            target: Name of the output study day variable
                (e.g. ``"AESTDY"``, ``"ASTDY"``).
            date_col: Column containing the date to measure from.
            ref_col: Reference date column name.  Defaults to
                ``_STUDY_DAY_REF_COL`` class constant (``RFSTDTC`` on
                SDTM, ``TRTSDT`` on ADaM).
            ref_pin: Pinned domain name.  Defaults to
                ``_STUDY_DAY_REF_PIN`` class constant (``DM`` on SDTM,
                ``ADSL`` on ADaM).
            ref_df: Optional explicit DataFrame override — bypasses pinning.
            dm: Alias of *ref_df* (SDTM vocabulary).
            adsl: Alias of *ref_df* (ADaM vocabulary).

        Returns:
            Self: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Raises:
            LookupError: If the reference date cannot be resolved from
                any source.
            VerbUsageError: If more than one of *ref_df* / *dm* / *adsl*
                is given.

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

        provided = [f for f in (ref_df, dm, adsl) if f is not None]
        if len(provided) > 1:
            raise VerbUsageError(
                f"study_day() accepts only one of ref_df= / dm= / adsl= — got {len(provided)}."
            )
        ref_df = provided[0] if provided else None

        # Resolve defaults from class constants
        _ref_col = ref_col if ref_col is not None else self._STUDY_DAY_REF_COL
        _ref_pin = ref_pin if ref_pin is not None else self._STUDY_DAY_REF_PIN

        schema = self._lazy.collect_schema()

        # Resolve reference date source
        if ref_df is not None:
            source_df = ref_df
            join_key = ["USUBJID"]
        elif _ref_col in schema.names():
            # ref_col already in frame — no join needed; stays lazy.
            date_expr = pl.col(date_col)
            ref_expr = pl.col(_ref_col)
            # Handle both Date and String types
            if schema.get(date_col) == pl.String:
                date_expr = date_expr.str.to_date(format="%Y-%m-%d", strict=False)
            if schema.get(_ref_col) == pl.String:
                ref_expr = ref_expr.str.to_date(format="%Y-%m-%d", strict=False)
            diff = (date_expr - ref_expr).dt.total_days()
            study_day_expr = pl.when(diff >= 0).then(diff + 1).otherwise(diff).alias(target)
            return self._chain(
                study_day_expr,
                verb="study_day",
                params={"target": target, "date_col": date_col, "ref_col": _ref_col},
            )
        else:
            source_df = self._require_pin(_ref_pin.upper(), "study_day", columns=[_ref_col])
            join_key = self._pin_join_key(_ref_pin.upper())

        df = self._lazy.collect()

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
                params={
                    "target": target,
                    "date_col": date_col,
                    "ref_col": _ref_col,
                    "ref_pin": _ref_pin,
                },
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
        by: list[str] | None = None,
        start_at: int = 1,
        check_uniqueness: bool = False,
    ) -> Self:
        """Derive a 1-based sequence number within each group.

        Generates a 1-based integer sequence that uniquely identifies each
        record within a grouping partition.  The dataset is sorted by
        *order_by* columns within each *by* partition before numbering
        — ensuring deterministic, reproducible sequence values.  The
        sort and the window numbering are appended to the lazy plan.

        Args:
            target: Name of the output sequence variable (e.g. ``"AESEQ"``,
                ``"ASEQ"``).
            order_by: Columns that define the sort order within each group.
                When ``None``, the current row order is preserved.
            by: Partition columns.  Defaults to class constant
                ``_SEQ_DEFAULT_GROUPS``.
            start_at: First sequence value (default ``1``).
            check_uniqueness: If ``True``, emit a warning when the
                combination of *by* + *order_by* does not uniquely
                identify each row (requires reading the key columns).

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
                    .seq("ASEQ", order_by=["ASTDT"], by=["USUBJID"])
                    .to_frame()
                )
        """
        grps = by or list(self._SEQ_DEFAULT_GROUPS)

        lf = self._lazy
        if order_by:
            lf = lf.sort(order_by)

        if check_uniqueness and order_by:
            key_cols = grps + list(order_by)
            schema_names = lf.collect_schema().names()
            available = [c for c in key_cols if c in schema_names]
            counts = lf.select(
                pl.len().alias("__n_total__"),
                pl.struct(available).n_unique().alias("__n_unique__"),
            ).collect()
            n_total = int(counts["__n_total__"][0])
            n_unique = int(counts["__n_unique__"][0])
            if n_unique < n_total:
                warnings.warn(
                    f"Rows are not unique by {available}: "
                    f"{n_total} rows but only {n_unique} unique combinations. "
                    f"{target} values may be arbitrary for tied rows.",
                    stacklevel=2,
                )

        seq_expr = (pl.int_range(pl.len()).over(grps) + start_at).cast(pl.Int64).alias(target)
        return self._with_lazy(lf.with_columns(seq_expr))

    # ------------------------------------------------------------------ #
    # validate                                                             #
    # ------------------------------------------------------------------ #

    @property
    def last_validation(self) -> ValidationResult | None:
        """The most recent ``ValidationResult`` produced by ``validate()``.

        ``None`` when ``validate()`` has not run on this chain.  Use it
        to gate CI on validation outcomes without breaking the fluent
        chain::

            ns = df.sdtm.assign("DOMAIN", value="DM").validate("DM")
            assert ns.last_validation is not None
            assert ns.last_validation.is_valid
        """
        return getattr(self, "_last_validation", None)

    def validate(
        self,
        dataset_or_domain: str,
        version: str | None = None,
        rules_engine_path: Path | None = None,
        custom_rules: str | Path | None = None,
        report: Literal["smart", "summary", "full"] = "smart",
        on_fail: Literal["warn", "raise", "ignore"] = "warn",
    ) -> Self:
        """Run CDISC conformance validation and report the findings.

        Returns a namespace copy so the chain can continue after
        validation; the full :class:`~fleet.validation.models.ValidationResult`
        is retrievable via the :attr:`last_validation` property.  The
        report is emitted through the ``"fleet.validation"`` logger
        (stdout by default — see :mod:`fleet.core.log`).

        Dispatches to either SDTM or ADaM validation based on the
        ``_VALIDATE_STANDARD`` class constant.

        Issues are cross-linked to the chain's own variable lineage, so a
        finding on a column this pipeline derived also reports the verb
        that produced it (see
        :func:`fleet.validation.lineage_join.enrich_with_lineage`).

        Args:
            dataset_or_domain: Domain code (SDTM: e.g. ``"DM"``) or
                dataset name (ADaM: e.g. ``"ADSL"``).
            version: IG version to validate against.  Defaults to
                ``_VALIDATE_DEFAULT_VERSION``.
            rules_engine_path: Optional path to a custom rules engine.
            custom_rules: Optional path to a directory containing custom
                validation rule YAML files. Passed to the engine via ``-lr``.
            report: Report detail level — ``"smart"`` (default) for a
                deduplicated view grouping identical findings with row
                ranges, ``"summary"`` for one line per issue, ``"full"``
                for every individual finding expanded.
            on_fail: What to do when validation reports errors —
                ``"warn"`` (default) emits a ``UserWarning`` and
                continues, ``"raise"`` raises
                :class:`~fleet.core.exceptions.ValidationError`,
                ``"ignore"`` continues silently.

        Returns:
            Self: A namespace copy carrying the result in
                ``last_validation`` (for continued chaining).

        Raises:
            ValidationError: When errors are found and
                ``on_fail="raise"``.
            DerivationError: On an invalid *on_fail* or *version* value.

        Examples:
            Validate an SDTM domain::

                dm = (
                    raw_df.sdtm
                    .assign("DOMAIN", value="DM")
                    .validate("DM")
                    .to_frame()
                )

            Gate a CI pipeline on the ADaM validation outcome::

                adsl = (
                    dm_df.adam.adsl
                    .validate("ADSL", on_fail="raise")
                    .to_frame()
                )
        """
        from fleet.core.lineage import latest_lineage_of
        from fleet.validation.lineage_join import enrich_with_lineage
        from fleet.validation.service import ValidationService

        _check_on_fail("validate", on_fail)
        ver = version if version is not None else self._VALIDATE_DEFAULT_VERSION
        _check_ig_version(ver, standard=self._VALIDATE_STANDARD)
        svc = ValidationService(rules_engine_path=rules_engine_path)

        if self._VALIDATE_STANDARD == "adam":
            result = svc.validate_adam(
                self.to_frame(), dataset=dataset_or_domain, version=ver, custom_rules=custom_rules
            )
        else:
            result = svc.validate_sdtm(
                self.to_frame(), domain=dataset_or_domain, version=ver, custom_rules=custom_rules
            )

        enrich_with_lineage(result, latest_lineage_of(self))
        result.print_report(report_type=report)

        new = copy.copy(self)
        new._last_validation = result
        if not result.is_valid:
            summary = (
                f"CDISC validation failed for '{dataset_or_domain}': "
                f"{len(result.errors)} error(s), {len(result.warnings)} warning(s). "
                "Access details via .last_validation."
            )
            _settle_on_fail(on_fail, summary, ValidationError)
        return new

    # ------------------------------------------------------------------ #
    # compare                                                              #
    # ------------------------------------------------------------------ #

    @property
    def last_comparison(self) -> ComparisonReport | None:
        """The most recent comparison report produced by ``compare()``.

        ``None`` when ``compare()`` has not run on this chain.  Use it to
        gate a script on the comparison outcome without breaking the
        fluent chain::

            ns = qc_df.adam.source("USUBJID").compare(adsl_prod, keys="USUBJID")
            assert ns.last_comparison is not None
            assert ns.last_comparison.is_equal, ns.last_comparison.raised_flags
        """
        return getattr(self, "_last_comparison", None)

    def compare(
        self,
        base: pl.DataFrame | pl.LazyFrame,
        *,
        keys: str | Sequence[str],
        max_print: MaxPrint = 50,
        base_name: str | None = None,
        candidate_name: str | None = None,
        on_fail: Literal["warn", "raise", "ignore"] = "warn",
    ) -> Self:
        """Compare the chain against a base dataset, PROC COMPARE style.

        The chain is the **candidate** and *base* is the reference it is
        measured against.  The chain is materialised, paired with the base
        on *keys* through :func:`fleet.compare`, and the report is printed
        through the ``"fleet.comparison"`` logger (stdout by default — see
        :mod:`fleet.core.log`).  Differences never stop the chain by
        default: the verb returns a namespace copy carrying the
        :class:`~fleet.comparison.ComparisonReport` as
        :attr:`last_comparison`, so the pipeline continues.

        Args:
            base: The reference dataset, as a DataFrame or LazyFrame.
            keys: Variable(s) that identify one observation on each side.
                Required; the compare refuses to run when a key is missing
                or not unique on either side.
            max_print: Print limits for the text report (differences per
                variable, a ``(per_variable, total)`` pair, or ``None`` for
                everything).  The report's listing is never truncated.
            base_name: Label for the base in the report, when known.
            candidate_name: Label for the chain in the report, when known.
            on_fail: What to do when the datasets differ — ``"warn"``
                (default) emits a ``UserWarning`` and continues,
                ``"raise"`` raises
                :class:`~fleet.core.exceptions.ComparisonError`,
                ``"ignore"`` continues silently.

        Returns:
            Self: A namespace copy carrying the report in
                ``last_comparison`` (for continued chaining).

        Raises:
            ComparisonError: When the datasets differ and
                ``on_fail="raise"``, or when the comparison cannot run
                (a key missing, duplicated or of an incompatible type).
            DerivationError: On an invalid *on_fail* value.

        Examples:
            Prove an independently programmed ADAE matches its base, and
            keep chaining::

                adae_qc = (
                    ae_df.adam.occds
                    .source("USUBJID")
                    .source("AESEQ")
                    .compare(adae_prod, keys=["USUBJID", "AESEQ"])
                    .to_frame()
                )

            Gate a CI script on the comparison outcome::

                adsl = (
                    dm_df.adam.adsl
                    .source("USUBJID")
                    .compare(adsl_prod, keys="USUBJID", on_fail="raise")
                    .to_frame()
                )
        """
        from fleet.comparison import compare as compare_frames

        _check_on_fail("compare", on_fail)
        report = compare_frames(
            base,
            self.to_frame(),
            keys=keys,
            max_print=max_print,
            base_name=base_name,
            candidate_name=candidate_name,
        )
        report.print_report()

        new = copy.copy(self)
        new._last_comparison = report
        if not report.is_equal:
            summary = f"{report.summary}. Access details via .last_comparison."
            _settle_on_fail(on_fail, summary, ComparisonError)
        return new

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
        """Select and reorder columns (lazily — nothing is materialised).

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
            Self: A fresh namespace continuing from the selected plan.

        Examples:
            Keep only spec columns::

                dm = (
                    raw_df.sdtm
                    .select(spec="specs/sdtm/define.yaml", dataset="DM")
                    .to_frame()
                )
        """
        schema = self._lazy.collect_schema()
        names = schema.names()

        # Step 1: drop scratch variables matching the pattern
        if drop_pattern is not None:
            pat = re.compile(drop_pattern)
            names = [c for c in names if not pat.search(c)]

        # Step 2: resolve explicit column list (spec takes priority over columns)
        col_list = columns
        type_map: dict[str, str] = {}
        if spec is not None:
            spec_path = Path(spec)
            col_list, type_map = self._spec_dataset_meta(spec_path, dataset)

        # Step 3: intersect with existing columns (preserving spec order)
        final_cols = names
        if col_list is not None:
            final_cols = [c for c in col_list if c in names]
            if spec is not None:
                missing = [c for c in col_list if c not in names]
                if missing:
                    warnings.warn(
                        f"select(spec=...): {len(missing)} spec-declared column(s) "
                        f"are absent from the frame and were skipped: {missing}",
                        stacklevel=2,
                    )
                computed = {node.name for node in getattr(self, "_lineage", [])}
                dropped = [c for c in names if c not in col_list and c in computed]
                if dropped:
                    warnings.warn(
                        f"select(spec=...): dropping computed column(s) that are "
                        f"not declared in the spec: {dropped}",
                        stacklevel=2,
                    )

        lf = self._lazy.select(final_cols)

        # Step 4: cast date/datetime columns declared in the spec
        if type_map:
            casts = []
            for col_name, spec_type in type_map.items():
                if col_name not in final_cols:
                    continue
                dtype = schema.get(col_name)
                if spec_type == "date":
                    if dtype == pl.String:
                        casts.append(pl.col(col_name).str.to_date("%Y-%m-%d", strict=False))
                    elif dtype is not None and (
                        dtype.is_(pl.Datetime) or str(dtype).startswith("Datetime")
                    ):
                        casts.append(pl.col(col_name).cast(pl.Date))
                elif spec_type == "datetime":
                    if dtype == pl.String:
                        casts.append(pl.col(col_name).str.to_datetime(strict=False))
            if casts:
                lf = lf.with_columns(casts)

        return self._with_lazy(lf)

    @staticmethod
    def _spec_dataset_meta(
        spec_path: Path, dataset: str | None
    ) -> tuple[list[str], dict[str, str]]:
        """Return ``(column_names, date_type_map)`` for *dataset* from a define.yaml."""
        ds = load_define_spec(spec_path).select(dataset)
        columns = [v.name for v in ds.variables]
        type_map = {v.name: v.type for v in ds.variables if v.type in ("date", "datetime")}
        return columns, type_map

    # ------------------------------------------------------------------ #
    # from_spec — registry-driven spec execution                           #
    # ------------------------------------------------------------------ #

    def from_spec(
        self,
        spec_path: str | Path,
        *,
        dataset: str | None = None,
        only: list[str] | None = None,
        omit: list[str] | None = None,
        strict: bool = True,
        overwrite: bool = False,
    ) -> Self:
        """Build a derivation pipeline from a YAML specification file.

        Reads either a ``define.yaml`` (top-level ``datasets`` list where
        each variable carries a ``derivation`` block) or a simplified
        single-dataset spec (top-level ``variables`` list).  Every
        ``algorithm:`` is resolved through the central spec registry
        (:mod:`fleet.core.spec_registry`), validated against its strict
        per-algorithm model, and executed via the matching namespace verb.

        A top-level ``ct:`` block opts the spec into controlled-terminology
        validation::

            ct:
              validate: true
              file: ct/cdisc_ct.yaml   # optional — loaded into the CT cache

        With ``validate: true`` every assign-family derivation that
        declares a codelist (``assign_ct`` / ``hardcode_ct``) runs with
        ``validate_values=True``: out-of-codelist values emit the
        standard warning naming dataset, variable, and codelist.  Specs
        without a ``ct:`` block behave exactly as before.

        Args:
            spec_path: Path to the YAML specification file.
            dataset: Dataset to execute from a multi-dataset define.yaml
                (e.g. ``dataset="DM"``).  May be omitted when the file
                contains a single dataset.
            only: Optional allow-list — process only these variable names.
            omit: Optional deny-list — skip these variable names; useful to
                override a spec variable with custom inline logic.
                Mutually exclusive with *only*.
            strict: When ``True`` (default) an unknown ``algorithm:`` raises
                :class:`~fleet.core.exceptions.SpecError`.  Pass ``False``
                to restore the legacy warn-and-skip behaviour.
            overwrite: When ``True``, allow spec variables to overwrite
                columns that already exist in the frame.  By default an
                overwrite raises ``SpecError`` unless the derivation is a
                declared carry-through (its source column *is* the target).

        Returns:
            Self: A namespace pre-loaded with all spec-driven derivations;
                call ``.to_frame()`` to materialise.

        Raises:
            SpecError: On unknown algorithms (strict mode), invalid or
                misspelled derivation fields, column overwrites, unknown
                ``fleet_spec_version``, or any error raised while executing
                a variable — always naming file, dataset, and variable.
            ValueError: When both *only* and *omit* are given, or when
                *dataset* is required/unknown.

        Examples:
            Build and materialise the DM domain from a spec::

                dm = (
                    raw_df.sdtm
                    .from_spec("examples/cdiscpilot01/sdtm/define.yaml", dataset="DM")
                    .to_frame()
                )

            Keep an inline derivation for one variable::

                adsl = (
                    dm_df.adam
                    .from_spec("define.yaml", dataset="ADSL", omit=["TRTSDT"])
                    .to_frame()
                )
        """
        from fleet.core import spec_registry

        if only is not None and omit is not None:
            raise DerivationError(
                "Cannot specify both only= and omit= in from_spec(). "
                "Use only= to allow-list variables, or omit= to deny-list them."
            )

        path = Path(spec_path)
        spec = load_define_spec(path)
        _check_spec_version(spec, source=str(path))
        _import_derivations_module(spec, source=str(path))

        standard = self._VALIDATE_STANDARD
        ds_name, raw_vars = _extract_spec_variables(spec, dataset)

        ns = self

        # Spec-level CT config: `ct: {validate: true, file: <path>}`.
        if spec.ct.enabled:
            ct_file = spec.ct.file
            if ct_file:
                from fleet.ct.validator import get_validator

                ct_path = Path(ct_file)
                if not ct_path.is_absolute():
                    ct_path = path.parent / ct_path
                try:
                    get_validator().load_ct_file(ct_path)
                except Exception as err:
                    raise SpecError(
                        f"{path}: ct.file '{ct_file}' could not be loaded: {err}"
                    ) from err
            ns = copy.copy(ns)
            ns._spec_ct_validate = True
        for var_name, drv in raw_vars:
            if only is not None and var_name not in only:
                continue
            if omit is not None and var_name in omit:
                continue

            context = f"{path} → dataset {ds_name} → variable {var_name}"
            alg = drv.get("algorithm")
            algo = spec_registry.get_algorithm(standard, str(alg)) if alg else None
            if algo is None:
                hint = spec_registry.suggest_algorithm(standard, str(alg))
                suffix = f" Did you mean '{hint}'?" if hint else ""
                if strict:
                    raise SpecError(
                        f"{context}: unknown algorithm '{alg}' for the {standard} "
                        f"spec path.{suffix} Pass strict=False to warn and skip instead."
                    )
                warnings.warn(
                    f"from_spec: skipping variable '{var_name}' — "
                    f"algorithm '{alg}' is not supported in spec-driven mode.{suffix}",
                    stacklevel=2,
                )
                continue

            try:
                model = spec_registry.model_for(standard, algo.name)
                var = model.model_validate({**drv, "target": var_name})
            except Exception as err:
                raise SpecError(f"{context}: {err}") from err

            columns = ns._lazy.collect_schema().names()

            # Auto-flush when a declared dependency is not yet committed.
            deps = getattr(var, "depends_on", None) or []
            if deps and any(d not in columns for d in deps):
                ns = ns._materialise_then(ns.to_frame())
                columns = ns._lazy.collect_schema().names()

            if (
                algo.takes_target
                and algo.overwrite_guard
                and not overwrite
                and var.target in columns
                and not spec_registry.is_identity_copy(var)
            ):
                raise SpecError(
                    f"{context}: would overwrite the existing column "
                    f"'{var.target}'. Pass overwrite=True to allow spec "
                    f"overwrites, or omit=[{var.target!r}] to keep the "
                    f"inline derivation."
                )

            try:
                ns = spec_registry.execute_variable(ns, var)
            except SpecError:
                raise
            except Exception as err:
                raise SpecError(f"{context}: {type(err).__name__}: {err}") from err

        return ns

    # ------------------------------------------------------------------ #
    # to_spec_yaml — round-trip: pipeline lineage → define.yaml            #
    # ------------------------------------------------------------------ #

    def to_spec_yaml(
        self,
        dataset: str | None = None,
        path: str | Path | None = None,
        *,
        predecessor: str | None = None,
    ) -> str:
        """Serialise the pipeline's lineage into a define.yaml spec.

        The natural prototype-then-freeze workflow: build the dataset
        inline, then emit the equivalent ``derivation:`` blocks instead
        of retyping them.  Variables are emitted in frame column order:
        derived variables carry their ``derivation:`` block (last
        derivation wins when a target was re-derived); CDISC-named
        carry-through columns are listed as metadata-only entries; raw
        columns that violate the CDISC name pattern are skipped.  Verbs
        covered by the spec registry emit real blocks; verbs that are
        not spec-expressible (or whose arguments cannot be serialised,
        e.g. inline Polars expressions) emit an ``algorithm: callable``
        stub with a ``# TODO`` comment carrying the verb name and
        sources.  Auto-generated by-product columns (e.g. ``--DTF``
        imputation flags) are listed without a derivation.

        The output validates against Fleet's define-spec JSON schema;
        study-level fields are placeholders to review before use.

        Args:
            dataset: Dataset name for the emitted spec.  Defaults to the
                pipeline's domain context (set by ``assign("DOMAIN",
                ...)``) or ``"DATASET"``.
            path: Optional file path — when given, the YAML is also
                written there (parent directories are created).
            predecessor: Name of the upstream dataset this ADaM pipeline
                was built from (e.g. ``"DM"``).  When given, variables
                carried through unchanged — metadata-only entries and
                pure ``algorithm: source`` copies of CDISC-named columns
                — are emitted with ``origin: Predecessor`` and
                ``predecessor: '<DATASET>.<SOURCE>'``.  The emitted YAML
                stays the explicit, reviewable source of truth; Fleet
                never infers Predecessor at Define-XML generation time.
                Columns brought in by ``merge()`` leave no lineage and
                are labeled like carry-throughs — when the pipeline
                contains a join, a review note is added to the header.
                ADaM pipelines only.

        Returns:
            str: The define.yaml document.

        Examples:
            Freeze an inline DM prototype to a spec::

                ns = (
                    raw_df.sdtm
                    .assign("DOMAIN", value="DM")
                    .assign("USUBJID", source="subject_id")
                )
                yaml_text = ns.to_spec_yaml(dataset="DM", path="specs/define_dm.yaml")
                dm = raw_df.sdtm.from_spec("specs/define_dm.yaml", dataset="DM").to_frame()

            Freeze an ADSL prototype, labelling DM carry-throughs::

                adsl_ns.to_spec_yaml(dataset="ADSL", predecessor="DM")
        """
        from fleet.core import spec_registry
        from fleet.core.lineage import latest_lineage_of

        standard = self._VALIDATE_STANDARD
        ds_name = (dataset or getattr(self, "_domain", None) or "DATASET").upper()

        pred_ds = predecessor.upper() if predecessor else None
        if pred_ds:
            if standard != "adam":
                raise DerivationError(
                    "to_spec_yaml(predecessor=...) applies to ADaM pipelines only — "
                    "SDTM variables built from raw data are Collected/Derived, not "
                    "Predecessor."
                )
            if not re.match(r"^[A-Z_][A-Z0-9_]{0,7}$", pred_ds):
                raise DerivationError(
                    f"to_spec_yaml(): predecessor {predecessor!r} is not a valid "
                    "dataset name (expected e.g. 'DM' or 'ADSL')."
                )

        schema = self._lazy.collect_schema()
        derived = {n.name: n for n in latest_lineage_of(self)}
        name_pattern = re.compile(r"^[A-Z_][A-Z0-9_]{0,7}$")

        entries: list[tuple[dict[str, Any], str | None]] = []
        for col in schema.names():
            node = derived.get(col)
            if node is None and not name_pattern.match(col):
                continue  # raw scratch column — not part of the dataset spec
            entry: dict[str, Any] = {
                "name": col,
                "label": col,
                "type": _dtype_to_spec_type(schema.get(col)),
            }
            comment: str | None = None
            if node is not None:
                status, block, meta = spec_registry.derivation_from_lineage(standard, node)
                if meta.get("label"):
                    entry["label"] = str(meta["label"])[:40]
                if meta.get("origin"):
                    entry["origin"] = meta["origin"]
                if status == "ok":
                    # A pure copy of a CDISC-named upstream column is a
                    # Predecessor in Define-XML terms; an explicit origin
                    # captured from the verb call wins.
                    source = str(block.get("source") or col) if block else col
                    if (
                        pred_ds
                        and "origin" not in entry
                        and block
                        and block.get("algorithm") == "source"
                        and name_pattern.match(source)
                    ):
                        entry["origin"] = "Predecessor"
                        entry["predecessor"] = f"{pred_ds}.{source}"
                    entry["derivation"] = block
                elif status == "stub":
                    srcs = ", ".join(node.sources) if node.sources else "none"
                    comment = (
                        f"TODO: verb '{node.verb}' (sources: {srcs}) is not spec-expressible "
                        f"— replace this stub with a registered derivation "
                        f"(algorithm: callable)."
                    )
                    entry["derivation"] = {
                        "algorithm": "callable",
                        "callable": f"TODO_{col}",
                    }
                # status == "byproduct": metadata-only (auto-generated column).
            elif pred_ds:
                # Metadata-only carry-through — flowed in untouched.
                entry["origin"] = "Predecessor"
                entry["predecessor"] = f"{pred_ds}.{col}"
            entries.append((entry, comment))

        if not entries:
            raise DerivationError(
                "to_spec_yaml(): nothing to serialise — the frame has no derived "
                "variables and no CDISC-named columns."
            )

        stubs = [entry["name"] for entry, comment in entries if comment]
        if stubs:
            warnings.warn(
                f"to_spec_yaml: {len(stubs)} variable(s) have no reviewer-facing "
                f"derivation text for Define-XML ({', '.join(stubs)}) — add a "
                "`comment:` in the spec or wrap the logic in a @derivation callable.",
                stacklevel=2,
            )

        var_names = [e["name"] for e, _ in entries]
        keys = [k for k in ("STUDYID", "USUBJID") if k in var_names] or var_names[:1]

        study = {
            "id": "STUDY",
            "name": "STUDY",
            "description": (
                "Generated by Fleet to_spec_yaml() — replace with the study description."
            ),
            "protocol_name": "STUDY",
            "originator": "Fleet",
            "standard": "SDTMIG" if standard == "sdtm" else "ADAMIG",
            "standard_version": self._VALIDATE_DEFAULT_VERSION,
        }
        head = {"fleet_spec_version": SUPPORTED_SPEC_VERSION, "study": study}
        ds_head = {
            "name": ds_name,
            "label": ds_name,
            "structure": "One record per observation (review)",
            "keys": keys,
        }

        lines: list[str] = [
            "# Generated by Fleet to_spec_yaml() — review study fields, labels, keys,",
            "# and TODO stubs before use.",
        ]
        if pred_ds and "JOIN" in self._lazy.explain().upper():
            lines.append(
                f"# predecessor={pred_ds!r}: this pipeline merges other datasets, and "
                "merged-in columns"
            )
            lines.append(
                f"# are indistinguishable from {pred_ds} carry-throughs — review each "
                "predecessor: entry."
            )
        lines += [
            yaml.safe_dump(head, sort_keys=False, allow_unicode=True).rstrip(),
            "datasets:",
            _indent_yaml(yaml.safe_dump([ds_head], sort_keys=False, allow_unicode=True), 2),
            "    variables:",
        ]
        for entry, comment in entries:
            block_text = _indent_yaml(
                yaml.safe_dump([entry], sort_keys=False, allow_unicode=True), 6
            )
            if comment:
                block_lines: list[str] = []
                for ln in block_text.splitlines():
                    if ln.strip().startswith("derivation:"):
                        pad = ln[: len(ln) - len(ln.lstrip())]
                        block_lines.append(f"{pad}# {comment}")
                    block_lines.append(ln)
                block_text = "\n".join(block_lines)
            lines.append(block_text)

        text = "\n".join(lines) + "\n"
        if path is not None:
            dest = Path(path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8")
        return text

    # ------------------------------------------------------------------ #
    # nodup — detect and optionally remove duplicates                      #
    # ------------------------------------------------------------------ #

    @property
    def last_nodup_report(self) -> pl.DataFrame | None:
        """Duplicate rows found by the most recent ``nodup()`` call.

        A ``pl.DataFrame`` containing every row that participated in a
        duplicate key group (empty frame when no duplicates were found),
        or ``None`` when ``nodup()`` has not run on this chain.  Makes
        report-only audits programmatically reachable::

            ns = df.sdtm.nodup(subset=["USUBJID", "AESEQ"])
            dups = ns.last_nodup_report
            assert dups is not None and dups.height == 0
        """
        return getattr(self, "_nodup_report", None)

    def nodup(
        self,
        *,
        subset: list[str],
        sort_by: list[str] | None = None,
        keep: Literal["first", "last"] | None = None,
        descending: bool | list[bool] = False,
    ) -> Self:
        """Detect duplicate rows and optionally deduplicate after sorting.

        Materialises the pipeline, logs duplicate diagnostics through the
        ``"fleet"`` logger (stdout by default — see :mod:`fleet.core.log`),
        and optionally removes duplicates.  When ``keep`` is ``None``
        (default) the verb operates in report-only mode — duplicates are
        reported but the frame is returned unchanged, making it safe to
        insert anywhere in a pipeline for auditing purposes.  The
        duplicate rows are also attached to the returned namespace and
        retrievable via :attr:`last_nodup_report`.

        Args:
            subset: Column(s) that define the uniqueness key.
            sort_by: Column(s) to sort by before deduplication.  Required
                when ``keep`` is not ``None``.
            keep: Which duplicate to retain after sorting:
                ``"first"``, ``"last"``, or ``None`` (report only, no removal).
            descending: Sort direction(s) for *sort_by*.  A single ``bool``
                applies to all columns; a list must match *sort_by* length.

        Returns:
            Self: A fresh namespace wrapping the (optionally deduplicated)
                frame, carrying the duplicates in ``last_nodup_report``;
                call ``.to_frame()`` to materialise.

        Raises:
            DerivationError: If ``keep`` is set but ``sort_by`` is not
                provided, or ``keep`` is not one of the accepted values.

        Examples:
            Report-only mode (audit duplicates without removing)::

                ae = (
                    raw_df.sdtm
                    .assign("USUBJID", source="subject_id")
                    .nodup(subset=["USUBJID", "AEDECOD", "AESTDTC"])
                    .to_frame()
                )

            Sort and deduplicate (keep latest record)::

                adae = (
                    ae_df.adam.occds
                    .nodup(
                        subset=["USUBJID", "AEDECOD"],
                        sort_by=["ASTDT", "ASEQ"],
                        keep="last",
                        descending=True,
                    )
                    .to_frame()
                )
        """
        if keep is not None and sort_by is None:
            raise DerivationError("sort_by is required when keep is set.")
        if keep is not None and keep not in ("first", "last"):
            raise DerivationError(f"keep must be 'first', 'last', or None — got {keep!r}.")

        fleet_log.ensure_default_handler()
        df = self._lazy.collect()

        # Detect duplicates
        dup_mask = df.select(pl.struct(subset).is_duplicated()).to_series()
        n_dup = dup_mask.sum()
        dup_rows = df.filter(dup_mask)

        if n_dup == 0:
            logger.info("[NODUP] No duplicates found (subset: %s)", ", ".join(subset))
            new = self._materialise_then(df)
            new._nodup_report = dup_rows
            return new

        # Summarise duplicate groups
        dup_groups = (
            dup_rows.group_by(subset)
            .agg(pl.len().alias("__count"))
            .sort("__count", descending=True)
        )
        n_groups = len(dup_groups)

        logger.info(
            "[NODUP] %d duplicate rows across %d key group(s) (subset: %s)",
            n_dup,
            n_groups,
            ", ".join(subset),
        )
        # Show top offending groups (up to 5)
        top = dup_groups.head(5)
        logger.info("[NODUP] Top offenders:")
        for row in top.iter_rows(named=True):
            count = row.pop("__count")
            key_str = ", ".join(f"{k}={v}" for k, v in row.items())
            logger.info("  %s  (%d rows)", key_str, count)

        # Report-only mode
        if keep is None:
            logger.info("[NODUP] Action: report only (keep=None)")
            new = self._materialise_then(df)
            new._nodup_report = dup_rows
            return new

        # Sort then deduplicate
        df = df.sort(sort_by, descending=descending)
        df = df.unique(subset=subset, keep=keep, maintain_order=True)

        logger.info(
            "[NODUP] Action: keeping '%s' after sorting by %s (descending=%s)",
            keep,
            sort_by,
            descending,
        )
        logger.info("[NODUP] Result: %d rows (removed %d)", len(df), n_dup - n_groups)
        new = self._materialise_then(df)
        new._nodup_report = dup_rows
        return new
