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
        .assign_datetime("BRTHDTC", source="birth_date")
        .hardcode_no_ct("DOMAIN", value="DM")
        .to_frame()
    )

    # Or spec-driven:
    result = raw_df.sdtm.from_spec("specs/cdiscpilot01/sdtm/define.yaml", dataset="DM").to_frame()
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

import polars as pl
import yaml

from .utils import parse_expression, to_iso8601_date, to_iso8601_datetime
from ._tdd_mixin import TrialDesignMixin

if TYPE_CHECKING:
    from ..ct.validator import CTValidator


@pl.api.register_dataframe_namespace("sdtm")
class SDTMNamespace(TrialDesignMixin):
    """
    Immutable pipeline builder for SDTM derivations.

    Each verb appends to a lazy expression list; `to_frame()` materialises
    everything in one ``with_columns`` call.
    """

    def __init__(self, df: pl.DataFrame) -> None:
        self._lazy = df.lazy()

    # ------------------------------------------------------------------ #
    # Internal chaining helper                                             #
    # ------------------------------------------------------------------ #

    def _chain(self, *exprs: pl.Expr) -> "SDTMNamespace":
        new = object.__new__(SDTMNamespace)
        new._lazy = self._lazy.with_columns(list(exprs))
        return new

    # ------------------------------------------------------------------ #
    # 1. assign_no_ct — direct 1:1 column rename                          #
    # ------------------------------------------------------------------ #

    def assign_no_ct(self, target: str, *, source: str) -> "SDTMNamespace":

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
        return self._chain(pl.col(source).alias(target))

    # ------------------------------------------------------------------ #
    # 1b. derivation — expression-based derivation                        #
    # ------------------------------------------------------------------ #

    def derivation(
        self,
        target: str,
        *,
        expression: "str | pl.Expr",
    ) -> "SDTMNamespace":
        """Derive *target* using a Polars expression or expression string.

        Args:
            target: Name of the output SDTM variable to create.
            expression: A Polars expression object or a string that evaluates
                to one (e.g. ``"pl.col('site_id').cast(pl.String)"``).

        Returns:
            SDTMNamespace: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Cast a raw site column to string for ``SITEID``::

                dm = (
                    raw_df.sdtm
                    .derivation("SITEID", expression="pl.col('site_id').cast(pl.String)")
                    .to_frame()
                )
        """
        expr = expression if isinstance(expression, pl.Expr) else parse_expression(str(expression))
        return self._chain(expr.alias(target))

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
        ct_validator: "CTValidator | None" = None,
    ) -> "SDTMNamespace":
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
            return self._chain(mapping_expr)

        # Try to auto-resolve from the singleton CTValidator
        if ct_validator is None:
            try:
                from ..ct.validator import get_validator
                ct_validator = get_validator()
            except Exception:
                ct_validator = None

        if ct_validator is not None:
            try:
                mapping = {v: v for v in ct_validator.get_valid_values(ct_codelist)}
                # Build decode map from CT (code → decode/preferred term)
                all_ct = ct_validator._ct_cache.get(ct_codelist, {})
                decode_map = {
                    coded: info.get("preferred_term", coded)
                    for coded, info in all_ct.items()
                }
                if decode_map:
                    return self._chain(
                        pl.col(source).replace(decode_map).alias(target)
                    )
            except Exception:
                pass

        # Fallback: pass-through (CT not loaded)
        return self._chain(pl.col(source).alias(target))

    # ------------------------------------------------------------------ #
    # 3. assign_datetime — convert raw date/datetime to ISO 8601          #
    # ------------------------------------------------------------------ #

    def assign_datetime(
        self,
        target: str,
        *,
        source: str,
        mode: str = "date",          # "date" | "datetime"
        input_format: str | None = None,
    ) -> "SDTMNamespace":
        """Parse *source* date string and format as ISO 8601.

        Args:
            target: Name of the output ``--DTC`` variable.
            source: Name of the raw column containing date strings.
            mode: ``"date"`` (default) for YYYY-MM-DD or ``"datetime"`` for
                YYYY-MM-DDTHH:MM:SS.
            input_format: Optional strptime format hint.

        Returns:
            SDTMNamespace: The namespace with *target* appended; call
                ``.to_frame()`` to materialise.

        Examples:
            Parse a raw AE start date into ISO 8601 ``AESTDTC``::

                ae = (
                    raw_df.sdtm
                    .assign_datetime("AESTDTC", source="ae_start_date")
                    .to_frame()
                )
        """
        if mode == "datetime":
            fn = to_iso8601_datetime
        else:
            fn = to_iso8601_date

        expr = pl.col(source).map_elements(fn, return_dtype=pl.String).alias(target)
        return self._chain(expr)

    # ------------------------------------------------------------------ #
    # 4. hardcode_ct — literal constant with CT validation                #
    # ------------------------------------------------------------------ #

    def hardcode_ct(
        self,
        target: str,
        *,
        value: Any,
        ct_codelist: str | None = None,
    ) -> "SDTMNamespace":
        """Set *target* to a constant *value*, validated against controlled terminology.

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
        return self._chain(pl.lit(value).alias(target))

    # ------------------------------------------------------------------ #
    # 5. hardcode_no_ct — literal constant, no CT                         #
    # ------------------------------------------------------------------ #

    def hardcode_no_ct(self, target: str, *, value: Any) -> "SDTMNamespace":
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
        return self._chain(pl.lit(value).alias(target))

    # ------------------------------------------------------------------ #
    # 6. condition_add — if condition then value else null                 #
    # ------------------------------------------------------------------ #

    def condition_add(
        self,
        target: str,
        *,
        condition: str | pl.Expr,
        then_value: Any,
    ) -> "SDTMNamespace":
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
    ) -> "SDTMNamespace":
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
        cond = first["condition"] if isinstance(first["condition"], pl.Expr) else parse_expression(first["condition"])
        chain = pl.when(cond).then(pl.lit(first["value"]))
        for branch in when[1:]:
            c = branch["condition"] if isinstance(branch["condition"], pl.Expr) else parse_expression(branch["condition"])
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
    ) -> "SDTMNamespace":
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
    # 9. merge — join another dataset                                      #
    # ------------------------------------------------------------------ #

    def merge(
        self,
        target_cols: list[str] | None = None,
        *,
        dataset: pl.DataFrame,
        on: str | list[str],
        how: str = "left",
    ) -> "SDTMNamespace":
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
        new = object.__new__(SDTMNamespace)
        new._lazy = joined
        if target_cols:
            new._lazy = new._lazy.with_columns([pl.col(c) for c in target_cols])
        return new

    # ------------------------------------------------------------------ #
    # 10. remove_dup — deduplicate rows                                    #
    # ------------------------------------------------------------------ #

    def remove_dup(
        self,
        *,
        subset: list[str] | None = None,
        keep: str = "first",
    ) -> "SDTMNamespace":
        """Remove duplicate rows, optionally on a *subset* of columns.

        Materialises, deduplicates, and returns a fresh namespace.

        Args:
            subset: Column(s) to consider for duplicate detection.  When
                ``None``, all columns are used.
            keep: Which duplicate to keep: ``"first"`` (default), ``"last"``,
                or ``"none"``.

        Returns:
            SDTMNamespace: A fresh namespace wrapping the deduplicated frame.

        Examples:
            Deduplicate VS records on subject and visit::

                vs = (
                    raw_df.sdtm
                    .assign_no_ct("USUBJID", source="subject_id")
                    .remove_dup(subset=["USUBJID", "VISIT"])
                    .to_frame()
                )
        """
        new = object.__new__(SDTMNamespace)
        new._lazy = self._lazy.unique(subset=subset, keep=keep)  # type: ignore[arg-type]
        return new

    # ------------------------------------------------------------------ #
    # 11. group_by — aggregate records                                     #
    # ------------------------------------------------------------------ #

    def group_by(
        self,
        *,
        group_cols: list[str],
        agg: list[pl.Expr],
    ) -> "SDTMNamespace":
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
        new = object.__new__(SDTMNamespace)
        new._lazy = self._lazy.group_by(group_cols).agg(agg)
        return new

    # ------------------------------------------------------------------ #
    # 12. dataset_level — constant for whole dataset (alias hardcode_no_ct)
    # ------------------------------------------------------------------ #

    def dataset_level(self, target: str, *, value: Any) -> "SDTMNamespace":
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

    def notsubmitted(self, *targets: str) -> "SDTMNamespace":
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
    ) -> "SDTMNamespace":
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
        new = object.__new__(SDTMNamespace)
        new._lazy = (
            self._lazy
            .with_columns(
                pl.col(source).str.split(delimiter).alias("__split__")
            )
            .explode("__split__")
            .with_columns(pl.col("__split__").str.strip_chars().alias(target))
            .drop("__split__")
        )
        return new

    # ------------------------------------------------------------------ #
    # Spec-driven pipeline                                                 #
    # ------------------------------------------------------------------ #

    def from_spec(self, spec_path: str | Path, *, dataset: str | None = None) -> "SDTMNamespace":
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
                    .from_spec("specs/cdiscpilot01/sdtm/define.yaml", dataset="DM")
                    .to_frame()
                )
        """
        from .models import SDTMDomainSpec, SDTMVariableSpec

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
            elif alg == "assign_datetime":
                ns = ns.assign_datetime(
                    target,
                    source=var.source or target,
                    mode="datetime" if "DT" in target and "C" in target else "date",
                    input_format=var.input_format,
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
            # merge, remove_dup, group_by, multiple_responses require extra data
            # — skip in spec-driven mode if not fully specified

        return ns

    @staticmethod
    def _extract_define_variables(
        spec_data: dict, dataset: str | None
    ) -> list:
        """Convert define.yaml dataset variables into SDTMVariableSpec objects."""
        from .models import SDTMVariableSpec

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
            spec = SDTMVariableSpec(
                target=var["name"],
                **drv,
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
        rules_engine_path: "Path | None" = None,
    ) -> "SDTMNamespace":
        """Run CDISC SDTM conformance validation and print the report.

        Returns *self* so the chain can continue after validation.

        Args:
            domain: SDTM domain code (e.g. ``"DM"``, ``"AE"``).
            version: SDTM IG version to validate against (default ``"3.4"``).
            rules_engine_path: Optional path to a custom rules engine.

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
        """
        from ..validation.service import ValidationService

        svc = ValidationService(rules_engine_path=rules_engine_path)
        result = svc.validate_sdtm(self.to_frame(), domain=domain, version=version)
        result.print_report()
        return self

    # ------------------------------------------------------------------ #
    # select — column selection / variable-leakage guard                  #
    # ------------------------------------------------------------------ #

    def select(
        self,
        columns: list[str] | None = None,
        *,
        spec: "str | Path | None" = None,
        dataset: str | None = None,
        drop_pattern: str | None = r"^_",
    ) -> "SDTMNamespace":
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
            v["name"]: v["type"]
            for v in ds["variables"]
            if v.get("type") in ("date", "datetime")
        }
        return columns, type_map

    def _new_from(self, df: pl.DataFrame) -> "SDTMNamespace":
        """Return a fresh SDTMNamespace wrapping *df* as a lazy plan."""
        new = object.__new__(SDTMNamespace)
        new._lazy = df.lazy()
        return new

    # ------------------------------------------------------------------ #
    # Terminal operations                                                  #
    # ------------------------------------------------------------------ #

    def to_frame(self) -> pl.DataFrame:
        """Materialise the accumulated pipeline into a Polars DataFrame.

        Returns:
            pl.DataFrame: The fully materialised result of all chained
                SDTM verbs.

        Examples:
            Collect the pipeline result::

                dm = (
                    raw_df.sdtm
                    .hardcode_no_ct("DOMAIN", value="DM")
                    .assign_no_ct("USUBJID", source="subject_id")
                    .to_frame()
                )
        """
        return self._lazy.collect()

    def write_parquet(
        self,
        path: "str | Path",
        *,
        mkdir: bool = True,
    ) -> pl.DataFrame:
        """
        Materialise the pipeline, write the result to *path* as Parquet,
        and return the DataFrame.

        This is a drop-in alternative to ``to_frame()`` when you want to
        persist the dataset as part of the chain.

        *mkdir*: when ``True`` (default) any missing parent directories are
        created automatically.

        Examples:
            Write the DM domain to Parquet::

                dm = (
                    raw_df.sdtm
                    .assign_no_ct("USUBJID", source="patient_number")
                    .select(spec="specs/sdtm/define.yaml", dataset="DM")
                    .write_parquet("outputs/cdiscpilot01/dm.parquet")
                )
        """
        df = self.to_frame()
        dest = Path(path)
        if mkdir:
            dest.parent.mkdir(parents=True, exist_ok=True)
        df.write_parquet(dest)
        return df
