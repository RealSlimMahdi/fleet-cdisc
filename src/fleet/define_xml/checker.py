"""Post-dataset creation checks against a Fleet define YAML spec.

When a Fleet pipeline materialises a dataset with ``.to_frame()`` the
caller can optionally pass the resulting ``pl.DataFrame`` to a
``DatasetChecker`` to verify that:

1. **Column completeness** — every non-private variable in the define appears
   as a column in the DataFrame (columns starting with ``_`` are ignored in
   both directions).
2. **Type consistency** — each column's Polars dtype is compatible with the
   define's declared type.
3. **Controlled terminology** — variables declaring a ``codelist:`` are
   verified against the spec's own inline ``codelists:`` items; values
   outside the declared submission values are **errors** (with a decode /
   ``ct_map`` hint when the offending value looks like an unapplied
   mapping).
4. **Labels** — a mapping of ``column → label`` is built from the define so it
   can be attached as report metadata or written to a SAS transport file.

All checks are **deactivatable** per-instance (``enabled=False``) or
per-check-category (``check_columns``, ``check_types``, ``check_ct``).

Two additional methods complete the post-pipeline workflow:

* :meth:`validate_core` — runs the official CDISC Rules Engine against the
  DataFrame.  Standard (SDTMIG / ADAMIG) and version are auto-detected from
  the ``study`` block in the define YAML.
* :meth:`write_xpt` — reorders DataFrame columns to match define variable
  order (required for valid XPT) and writes an SAS transport file.

Typical usage::

    from fleet import DatasetChecker

    checker = DatasetChecker("examples/cdiscpilot01/sdtm/define.yaml")
    dm = dm_raw.sdtm.from_spec(..., dataset="DM").to_frame()

    # 1. Lightweight define checks (always fast, no external deps)
    result = checker.check(dm, dataset="DM")
    result.print_report()
    result.raise_on_errors()

    # 2. Full CDISC Core validation (requires rules engine install)
    core_result = checker.validate_core(dm, dataset="DM")
    core_result.print_report()

    # 3. Write XPT (columns auto-reordered per define)
    checker.write_xpt(dm, dataset="DM", path="outputs/dm.xpt")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl

from fleet.core.define_spec import read_define_yaml

if TYPE_CHECKING:
    from fleet.validation.models import ValidationResult

# Maps simplified define type → acceptable Polars dtype families.
# A column passes the type check if its dtype is an instance of any of the
# listed Polars types.
_POLARS_COMPAT: dict[str, tuple[type, ...]] = {
    "text": (pl.String, pl.Categorical, pl.Enum),
    "integer": (pl.Int8, pl.Int16, pl.Int32, pl.Int64, pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64),
    "float": (
        pl.Float32,
        pl.Float64,
        pl.Int8,
        pl.Int16,
        pl.Int32,
        pl.Int64,  # integers are accepted in float cols
        pl.UInt8,
        pl.UInt16,
        pl.UInt32,
        pl.UInt64,
    ),
    "date": (pl.Date,),
    "datetime": (pl.Datetime, pl.Date),  # Date is acceptable in datetime columns
}

# Human-readable type family name for reporting
_TYPE_LABEL: dict[str, str] = {
    "text": "String/Categorical",
    "integer": "Int*",
    "float": "Float*/Int*",
    "date": "Date",
    "datetime": "Datetime/Date",
}

# CDISC core values that are treated as "required" when strict=True.
_REQ_CORES: frozenset[str] = frozenset({"Req"})
# CDISC core values that are treated as "expected" (warning-level).
_EXP_CORES: frozenset[str] = frozenset({"Exp"})


@dataclass
class TypeMismatch:
    variable: str
    define_type: str
    actual_dtype: str


def _code_text(value: Any) -> str:
    """The text of a coded value; a whole float (54.0, read from XPT) is '54'."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


@dataclass
class CheckResult:
    """Result of a ``DatasetChecker.check()`` call.

    Attributes
    ----------
    dataset:
        Name of the checked dataset (e.g. ``"DM"``).
    labels:
        Mapping of variable name → label string from the define.
    missing_columns:
        Variables declared in the define that are absent from the DataFrame.
        Private columns (``_``-prefix) and ``_``-prefixed vars are excluded.
    extra_columns:
        Columns in the DataFrame that are not declared in the define (and are
        not private ``_``-prefix columns).
    type_mismatches:
        Variables that are present but whose Polars dtype is not compatible
        with the define's declared type.
    ct_violations:
        Messages for values found outside the inline codelist declared for
        a variable (always also present in ``errors``).
    errors:
        All issues classified as errors. For ``core="Req"`` variables: missing
        columns and type mismatches.  When ``strict=False`` these are
        downgraded to warnings.
    warnings:
        All issues classified as warnings (``core="Exp"`` missing/mismatched,
        extra columns, downgraded Req errors when ``strict=False``).
    info:
        Informational notes (``core="Perm"``, ``"Cond"``, or
        ``"Conditionally Required"`` variables that are absent or have
        type mismatches).
    """

    dataset: str
    labels: dict[str, str] = field(default_factory=dict)
    missing_columns: list[str] = field(default_factory=list)
    extra_columns: list[str] = field(default_factory=list)
    type_mismatches: list[TypeMismatch] = field(default_factory=list)
    ct_violations: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """True when there are no errors (warnings are allowed)."""
        return len(self.errors) == 0

    def print_report(self) -> None:
        """Print a human-readable validation summary to stdout."""
        status = "PASS" if self.is_valid else "FAIL"
        print(f"\n{'=' * 60}")
        print(f"  Dataset Checker — {self.dataset}  [{status}]")
        print(f"{'=' * 60}")
        if self.errors:
            print(f"\n  ERRORS ({len(self.errors)}):")
            for e in self.errors:
                print(f"    ✗  {e}")
        if self.warnings:
            print(f"\n  WARNINGS ({len(self.warnings)}):")
            for w in self.warnings:
                print(f"    ⚠  {w}")
        if self.info:
            print(f"\n  INFO ({len(self.info)}):")
            for i in self.info:
                print(f"    ℹ  {i}")
        if self.is_valid and not self.warnings and not self.info:
            print("  All checks passed.")
        print()

    def raise_on_errors(self) -> None:
        """Raise ``DefineCheckError`` (a ``ValueError``) if any errors were found."""
        from fleet.core.exceptions import DefineCheckError

        if not self.is_valid:
            summary = "; ".join(self.errors)
            raise DefineCheckError(f"Dataset '{self.dataset}' failed define checks: {summary}")


def _classify(
    result: CheckResult,
    msg: str,
    *,
    core: str,
    mandatory: bool,
    strict: bool,
) -> None:
    """Route *msg* to errors / warnings / info based on *core* and *strict*.

    Severity logic:
    - ``core`` Req → error (or warning if ``strict=False``).
    - ``core`` Exp → warning.
    - ``core`` Perm or Cond → info.
    - Fallback for defines without ``core``: ``mandatory=True`` → error/warning.
    """
    if core:
        if core in _REQ_CORES:
            if strict:
                result.errors.append(msg)
            else:
                result.warnings.append(msg + " [strict=False: downgraded from error]")
        elif core in _EXP_CORES:
            result.warnings.append(msg)
        else:
            # Perm, Permissible, Conditionally Required
            result.info.append(msg)
    else:
        # No core field — fall back to mandatory boolean
        if mandatory:
            if strict:
                result.errors.append(msg)
            else:
                result.warnings.append(msg + " [strict=False: downgraded from error]")
        else:
            result.warnings.append(msg)


class DatasetChecker:
    """Validate a ``pl.DataFrame`` against a simplified Fleet define YAML.

    Parameters
    ----------
    define_yaml_path:
        Path to a ``define.yaml`` conforming to ``define_spec_schema.json``.
    enabled:
        Master switch.  When *False* all checks are skipped and ``check()``
        returns an empty ``CheckResult`` immediately.
    check_columns:
        When *True* (default), verify column completeness (missing / extra).
    check_types:
        When *True* (default), verify Polars dtype compatibility.
    check_ct:
        When *True* (default), verify values of variables declaring a
        ``codelist:`` against the spec's inline ``codelists:`` items.
        Out-of-codelist values are errors.
    check_values:
        When *True* (default), verify the define ``length`` of text values,
        no null in a ``mandatory`` variable, and no two records with the
        same ``keys`` (a null key value counts as one value, as in
        ``PROC SORT NODUPKEY``).
    validate_schema:
        When *True* (default), validate the YAML against the JSON schema on
        load.  Set to *False* to skip during tight inner loops.
    """

    def __init__(
        self,
        define_yaml_path: str | Path,
        *,
        enabled: bool = True,
        check_columns: bool = True,
        check_types: bool = True,
        check_ct: bool = True,
        check_values: bool = True,
        validate_schema: bool = True,
    ) -> None:
        self._enabled = enabled
        self._check_columns = check_columns
        self._check_types = check_types
        self._check_ct = check_ct
        self._check_values = check_values

        self._data: dict[str, Any] = read_define_yaml(
            define_yaml_path, validate_schema=validate_schema and enabled
        )

        # Build a lookup: dataset_name (upper) → dataset dict
        self._datasets: dict[str, dict[str, Any]] = {
            ds["name"].upper(): ds for ds in self._data.get("datasets", [])
        }
        # Inline codelists: oid → codelist dict (used by the CT check)
        self._codelists: dict[str, dict[str, Any]] = {
            cl["oid"]: cl for cl in self._data.get("codelists", [])
        }

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def check(
        self,
        df: pl.DataFrame | pl.LazyFrame,
        dataset: str,
        *,
        strict: bool = True,
    ) -> CheckResult:
        """Check *df* against the define for *dataset*.

        Args:
            df: The ``pl.DataFrame`` to check.  A ``pl.LazyFrame`` is
                collected.
            dataset: Dataset name to look up in the define (e.g. ``"DM"``).
                Case-insensitive.
            strict: When ``True`` (default), ``core="Req"`` issues are
                errors.  When ``False``, ``Req`` issues are downgraded to
                warnings so the pipeline can proceed despite missing
                required variables (e.g. during development or when source
                data is incomplete).

        Returns:
            CheckResult: Always returns a result — never raises unless you
                call ``result.raise_on_errors()``.

        Examples:
            Check DM against the pilot define::

                checker = DatasetChecker("examples/cdiscpilot01/sdtm/define.yaml")
                checker.check(dm, "DM").print_report()
        """
        result = CheckResult(dataset=dataset.upper())

        if not self._enabled:
            return result
        if isinstance(df, pl.LazyFrame):
            df = df.collect()

        ds_def = self._datasets.get(dataset.upper())
        if ds_def is None:
            result.errors.append(
                f"Dataset '{dataset}' not found in define. Available: {sorted(self._datasets)}"
            )
            return result

        # Build variable index (exclude private _-prefix names)
        vars_by_name: dict[str, dict[str, Any]] = {
            v["name"]: v for v in ds_def["variables"] if not v["name"].startswith("_")
        }

        # Labels always populated regardless of other flags
        result.labels = {name: v["label"] for name, v in vars_by_name.items()}

        # Actual DataFrame columns excluding private _-prefix columns
        actual_cols: set[str] = {c for c in df.columns if not c.startswith("_")}

        if self._check_columns:
            self._run_column_checks(result, vars_by_name, actual_cols, strict=strict)

        if self._check_types:
            self._run_type_checks(result, df, vars_by_name, actual_cols, strict=strict)

        if self._check_ct:
            self._run_ct_checks(result, df, vars_by_name, actual_cols)

        if self._check_values:
            self._run_value_checks(result, df, ds_def, vars_by_name, actual_cols, strict=strict)

        return result

    def datasets(self) -> list[str]:
        """Return the list of dataset names declared in the define."""
        return list(self._datasets)

    def labels(self, dataset: str) -> dict[str, str]:
        """Return the variable → label mapping for *dataset* without running full checks."""
        ds_def = self._datasets.get(dataset.upper())
        if ds_def is None:
            return {}
        return {v["name"]: v["label"] for v in ds_def["variables"] if not v["name"].startswith("_")}

    # ------------------------------------------------------------------ #
    # Check runners                                                        #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _run_column_checks(
        result: CheckResult,
        vars_by_name: dict[str, dict[str, Any]],
        actual_cols: set[str],
        *,
        strict: bool = True,
    ) -> None:
        define_cols = set(vars_by_name)

        missing = define_cols - actual_cols
        for col in sorted(missing):
            var_def = vars_by_name[col]
            core = var_def.get("core", "")
            msg = f"Column '{col}' declared in define is missing from the DataFrame."
            result.missing_columns.append(col)
            _classify(
                result, msg, core=core, mandatory=var_def.get("mandatory", False), strict=strict
            )

        extra = actual_cols - define_cols
        for col in sorted(extra):
            msg = f"Column '{col}' is present in the DataFrame but not declared in the define."
            result.extra_columns.append(col)
            result.warnings.append(msg)

    @staticmethod
    def _run_type_checks(
        result: CheckResult,
        df: pl.DataFrame,
        vars_by_name: dict[str, dict[str, Any]],
        actual_cols: set[str],
        *,
        strict: bool = True,
    ) -> None:
        schema = df.schema
        for col_name, var_def in vars_by_name.items():
            if col_name not in actual_cols:
                continue  # already reported as missing
            define_type = var_def["type"]
            actual_dtype = schema[col_name]
            # --DTC is ISO 8601 text whatever the define type says (SDTMIG 3.4 4.4)
            is_dtc = col_name.upper().endswith("DTC")
            compat_types = (pl.String,) if is_dtc else _POLARS_COMPAT.get(define_type, ())

            ok = isinstance(actual_dtype, compat_types)
            if not ok and define_type == "integer" and actual_dtype in (pl.Float32, pl.Float64):
                # SAS transport has only Char and Num: an XPT code reads as a float.
                values = df[col_name].drop_nulls()
                ok = bool((values == values.round(0)).all())
            if not ok:
                mm = TypeMismatch(
                    variable=col_name,
                    define_type=define_type,
                    actual_dtype=str(actual_dtype),
                )
                result.type_mismatches.append(mm)
                expected_label = (
                    "String (ISO 8601 text)"
                    if is_dtc
                    else _TYPE_LABEL.get(define_type, define_type)
                )
                msg = (
                    f"Column '{col_name}': define type '{define_type}' "
                    f"(expects {expected_label}) but actual dtype is '{actual_dtype}'."
                )
                core = var_def.get("core", "")
                _classify(
                    result, msg, core=core, mandatory=var_def.get("mandatory", False), strict=strict
                )

    def _run_ct_checks(
        self,
        result: CheckResult,
        df: pl.DataFrame,
        vars_by_name: dict[str, dict[str, Any]],
        actual_cols: set[str],
    ) -> None:
        """Verify variable values against the spec's inline codelists.

        The define.yaml already declares each codelist's submission values
        (``codelists[].items[].coded_value``) — a dataset asserting
        conformance to them must actually contain them.  Out-of-codelist
        values are **errors**.  When an offending value matches a decode
        (or a raw ``ct_map`` key from the variable's derivation), the
        message says so — those are almost always unapplied mappings.
        """
        for col_name, var_def in vars_by_name.items():
            oid = var_def.get("codelist")
            if not oid or col_name not in actual_cols:
                continue
            codelist = self._codelists.get(oid)
            if codelist is None:
                result.warnings.append(
                    f"Column '{col_name}' references codelist '{oid}' which is not "
                    f"declared in this define. Declared codelist OIDs: "
                    f"{sorted(self._codelists)}"
                )
                continue
            items = codelist.get("items") or []
            if not items:
                result.warnings.append(
                    f"Column '{col_name}': codelist {oid} has no items, so its values "
                    "are not checked; run fleet init ct."
                )
                continue
            coded: set[str] = {str(item["coded_value"]) for item in items}
            decode_of: dict[str, str] = {
                str(item["decode"]): str(item["coded_value"])
                for item in items
                if item.get("decode")
            }
            ct_mapping: dict[str, Any] = (var_def.get("derivation") or {}).get("ct_map") or {}

            values = [_code_text(v) for v in df[col_name].drop_nulls().unique().to_list()]
            values = [v for v in values if v != ""]
            invalid = sorted(v for v in values if v not in coded)
            if not invalid:
                continue

            hints: list[str] = []
            for v in invalid:
                if v in decode_of:
                    hints.append(f"'{v}' is the decode of submission value '{decode_of[v]}'")
                elif v in ct_mapping:
                    hints.append(f"'{v}' is a raw ct_map key — the mapping was not applied")
            hint = f" ({'; '.join(hints)})" if hints else ""
            msg = (
                f"Column '{col_name}': value(s) {invalid} not in codelist "
                f"'{oid}' ({codelist.get('name', oid)}). "
                f"Valid values: {sorted(coded)}.{hint}"
            )
            result.ct_violations.append(msg)
            result.errors.append(msg)

    @staticmethod
    def _run_value_checks(
        result: CheckResult,
        df: pl.DataFrame,
        ds_def: dict[str, Any],
        vars_by_name: dict[str, dict[str, Any]],
        actual_cols: set[str],
        *,
        strict: bool = True,
    ) -> None:
        """Check the define Length, the Mandatory variables and the key of *df*."""
        found: list[str] = []
        for col_name, var_def in vars_by_name.items():
            if col_name not in actual_cols:
                continue
            column = df[col_name]
            length = var_def.get("length")
            if length is not None and column.dtype == pl.String:
                too_long = column.str.len_bytes() > int(length)
                if too_long.any():
                    longest = int(column.str.len_bytes().max() or 0)
                    found.append(
                        f"Column '{col_name}': {int(too_long.sum())} value(s) longer than the "
                        f"define Length {length} (longest {longest} bytes)."
                    )
            if var_def.get("mandatory"):
                empty = column.is_null()
                if column.dtype == pl.String:
                    empty = empty | (column.str.strip_chars() == "")
                if empty.any():
                    found.append(
                        f"Column '{col_name}': {int(empty.sum())} null value(s), but the "
                        "define marks it Mandatory."
                    )
        keys = list(ds_def.get("keys") or [])
        absent = [k for k in keys if k not in actual_cols]
        if keys and absent:
            found.append(
                f"Key variable(s) {absent} are missing, so duplicate keys are not checked."
            )
        elif keys:
            dupes = df.select(keys).is_duplicated()
            if dupes.any():
                example = df.filter(dupes).select(keys).row(0)
                found.append(
                    f"{int(dupes.sum())} record(s) share their key {keys} with another "
                    f"record (first: {dict(zip(keys, example, strict=True))})."
                )
        for msg in found:
            if strict:
                result.errors.append(msg)
            else:
                result.warnings.append(msg + " [strict=False: downgraded from error]")

    # ------------------------------------------------------------------ #
    # CDISC Core validation                                                #
    # ------------------------------------------------------------------ #

    def validate_core(
        self,
        df: pl.DataFrame,
        dataset: str,
        *,
        standard: str | None = None,
        version: str | None = None,
    ) -> ValidationResult:
        """Run the official CDISC Rules Engine against *df*.

        Standard (``"SDTMIG"`` / ``"ADAMIG"``) and version are auto-detected
        from the ``study`` block in the define YAML.  Override either with the
        *standard* / *version* keyword arguments.

        Requires the CDISC Rules Engine to be installed and discoverable.  See
        ``OfficialCDISCValidator`` for setup instructions.

        Args:
            df: The materialised ``pl.DataFrame`` to validate.
            dataset: Dataset / domain name (e.g. ``"DM"``, ``"ADVS"``).
            standard: Override — e.g. ``"SDTMIG"`` or ``"ADAMIG"``.
            version: Override — e.g. ``"3.4"`` or ``"1.1"``.

        Returns:
            ValidationResult: The engine findings.

        Raises:
            ValidationSetupError: The run setup is refused (an IG version
                Fleet does not support), or no engine is found.  The
                engine, custom rules, timeout and accepted findings come
                from the study config, as for ``fleet validate``.

        Examples:
            Run CORE on DM with the define's standard::

                checker = DatasetChecker("examples/cdiscpilot01/sdtm/define.yaml")
                result = checker.validate(dm, "DM")
        """
        from fleet.core.exceptions import ValidationSetupError
        from fleet.validation.run_setup import build_run_setup, missing_engine_reason
        from fleet.validation.service import ValidationService

        study = self._data.get("study", {})
        detected_standard = (standard or study.get("standard", "SDTMIG")).upper()
        declared = study.get("standard_version")
        setup = build_run_setup(
            name=dataset,
            standard="adam" if "ADAM" in detected_standard else "sdtm",
            version=version or (str(declared) if declared is not None else None),
        )
        if setup.engine.value is None:
            raise ValidationSetupError(missing_engine_reason(setup))

        svc = ValidationService(rules_engine_path=setup.engine.value)
        ig, rules, timeout = (
            setup.ig_version.value,
            setup.custom_rules.value,
            setup.timeout.value,
        )
        if setup.standard.value == "adam":
            result = svc.validate_adam(
                df, dataset=dataset, version=ig, custom_rules=rules, timeout=timeout
            )
        else:
            result = svc.validate_sdtm(
                df, domain=dataset, version=ig, custom_rules=rules, timeout=timeout
            )
        result.apply_setup(setup)
        return result

    # ------------------------------------------------------------------ #
    # XPT export                                                           #
    # ------------------------------------------------------------------ #

    def write_xpt(
        self,
        df: pl.DataFrame,
        dataset: str,
        path: str | Path,
        *,
        reorder: bool = True,
    ) -> Path:
        """Write *df* as a SAS transport file, version 5, with the define labels.

        When *reorder* is ``True`` (default) the DataFrame columns are
        rearranged to match the variable order declared in the define before
        writing.  Columns not declared in the define (e.g. private ``_``-prefix
        columns) are silently dropped so the XPT only contains define-declared
        variables.  The dataset and variable labels come from the define;
        the rules of the file are those of :func:`fleet.io.save_xpt`.

        Requires ``pyreadstat``.  Install with ``uv add "fleet-cdisc[io]"``.

        Args:
            df: The materialised ``pl.DataFrame`` to write.
            dataset: Dataset name used to look up the variable order in the
                define.  It must equal the file name (FDA TCG 3.1.1).
            path: Destination file path (e.g. ``"outputs/dm.xpt"``).
            reorder: Whether to reorder / filter columns to match define
                order.

        Returns:
            Path: Resolved path of the written file.

        Raises:
            FleetIOError: When the file name is not the dataset name.

        Examples:
            Write DM with the define labels::

                checker = DatasetChecker("examples/cdiscpilot01/sdtm/define.yaml")
                checker.write_xpt(dm, "DM", "outputs/dm.xpt")
        """
        from fleet.core.exceptions import FleetIOError
        from fleet.io import save_xpt

        out = Path(path)
        if out.stem.upper() != dataset.upper():
            raise FleetIOError(
                f"{out.name} would hold dataset {dataset.upper()}; name the file "
                f"{dataset.lower()}.xpt, because the member is named as the file (FDA TCG 3.1.1)."
            )

        ds_def = self._datasets.get(dataset.upper())
        if reorder and ds_def is not None:
            define_names = [v["name"] for v in ds_def["variables"]]
            # Keep only columns that are both in define and in df; preserve define order
            ordered = [c for c in define_names if c in df.columns]
            df = df.select(ordered)

        return save_xpt(
            df,
            out,
            label=ds_def.get("label") if ds_def is not None else None,
            column_labels=self.labels(dataset),
        )
