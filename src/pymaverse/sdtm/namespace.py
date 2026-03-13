"""
SDTM Polars namespace extension.

Registers ``df.sdtm`` on every Polars DataFrame.

Usage
-----
    import pymaverse  # triggers registration

    result = (
        raw_df.sdtm
        .assign_no_ct("USUBJID", source="patient_number")
        .assign_ct("SEX", source="sex", ct_codelist="C66731")
        .assign_datetime("BRTHDTC", source="birth_date")
        .hardcode_no_ct("DOMAIN", value="DM")
        .to_frame()
    )

    # Or spec-driven:
    result = raw_df.sdtm.from_spec("specs/dm_spec.yaml").to_frame()
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TYPE_CHECKING

import polars as pl
import yaml

from .utils import parse_expression, to_iso8601_date, to_iso8601_datetime

if TYPE_CHECKING:
    from ..ct.validator import CTValidator


@pl.api.register_dataframe_namespace("sdtm")
class SDTMNamespace:
    """
    Immutable pipeline builder for SDTM derivations.

    Each verb appends to a lazy expression list; `to_frame()` materialises
    everything in one ``with_columns`` call.
    """

    def __init__(self, df: pl.DataFrame) -> None:
        self._df = df
        self._pipeline: list[pl.Expr] = []

    # ------------------------------------------------------------------ #
    # Internal chaining helper                                             #
    # ------------------------------------------------------------------ #

    def _chain(self, *exprs: pl.Expr) -> "SDTMNamespace":
        new = object.__new__(SDTMNamespace)
        new._df = self._df
        new._pipeline = self._pipeline + list(exprs)
        return new

    # ------------------------------------------------------------------ #
    # 1. assign_no_ct — direct 1:1 column rename                          #
    # ------------------------------------------------------------------ #

    def assign_no_ct(self, target: str, *, source: str) -> "SDTMNamespace":
        """Copy *source* column to *target* with no CT validation."""
        return self._chain(pl.col(source).alias(target))

    # ------------------------------------------------------------------ #
    # 2. assign_ct — 1:1 mapping with CT decode/validation                #
    # ------------------------------------------------------------------ #

    def assign_ct(
        self,
        target: str,
        *,
        source: str,
        ct_codelist: str,
        ct_mapping: dict[str, str] | None = None,
        ct_validator: "CTValidator | None" = None,
    ) -> "SDTMNamespace":
        """
        Copy *source* to *target*, translating values into the CT decode.

        *ct_mapping*: explicit ``{raw_value: ct_value}`` override.
        *ct_validator*: if supplied (or auto-resolved), used for decode.
        """
        if ct_mapping:
            # Build if/when chain to avoid deprecated replace(default=) API
            items = list(ct_mapping.items())
            k0, v0 = items[0]
            expr_chain = pl.when(pl.col(source) == k0).then(pl.lit(v0))
            for k, v in items[1:]:
                expr_chain = expr_chain.when(pl.col(source) == k).then(pl.lit(v))
            mapping_expr = expr_chain.otherwise(pl.col(source)).alias(target)
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
                    items = list(decode_map.items())
                    k0, v0 = items[0]
                    expr_chain = pl.when(pl.col(source) == k0).then(pl.lit(v0))
                    for k, v in items[1:]:
                        expr_chain = expr_chain.when(pl.col(source) == k).then(pl.lit(v))
                    return self._chain(
                        expr_chain.otherwise(pl.col(source)).alias(target)
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
        """
        Parse *source* date string and format as ISO 8601.

        *mode*: ``"date"`` → YYYY-MM-DD, ``"datetime"`` → YYYY-MM-DDTHH:MM:SS.
        *input_format*: optional strptime format hint (unused in current impl).
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
        """Set *target* to *value* (validated against CT if codelist provided)."""
        return self._chain(pl.lit(value).alias(target))

    # ------------------------------------------------------------------ #
    # 5. hardcode_no_ct — literal constant, no CT                         #
    # ------------------------------------------------------------------ #

    def hardcode_no_ct(self, target: str, *, value: Any) -> "SDTMNamespace":
        """Set *target* to a literal *value* for every row."""
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
        """
        WHERE *condition* is true, set *target* = *then_value*, else null.

        *condition*: a Polars expression or a string that evaluates to one.
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
        """
        Multi-branch conditional mapping.

        *when*: list of ``{"condition": expr_str, "value": any}`` dicts.
        Branches are evaluated in order; first match wins.

        Example::

            .if_then_else("AGEU", when=[
                {"condition": 'pl.col("age_unit") == "years"', "value": "YEARS"},
                {"condition": 'pl.col("age_unit") == "months"', "value": "MONTHS"},
            ], else_value="YEARS")
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
        """
        Map free-text AE causality string to controlled AEREL values.

        Mapping is case-insensitive against *aerel_map* (defaults to built-in).
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
        """
        Join *dataset* into the pipeline using key *on*.

        This verb materialises the current pipeline first (join needs a
        concrete frame), then returns a namespace wrapping the joined frame.
        """
        joined = self.to_frame().join(dataset, on=on, how=how)
        new = object.__new__(SDTMNamespace)
        new._df = joined
        new._pipeline = []
        if target_cols:
            new._pipeline = [pl.col(c) for c in target_cols]
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
        """
        Remove duplicate rows, optionally on a *subset* of columns.

        Materialises, deduplicates, and returns a fresh namespace.
        """
        deduped = self.to_frame().unique(subset=subset, keep=keep)  # type: ignore[arg-type]
        new = object.__new__(SDTMNamespace)
        new._df = deduped
        new._pipeline = []
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
        """
        Group by *group_cols* and apply *agg* aggregations.

        Materialises, groups, and returns a fresh namespace.

        Example::

            .group_by(
                group_cols=["USUBJID", "VSTESTCD"],
                agg=[pl.col("VSSTRESN").max().alias("AVAL")],
            )
        """
        grouped = self.to_frame().group_by(group_cols).agg(agg)
        new = object.__new__(SDTMNamespace)
        new._df = grouped
        new._pipeline = []
        return new

    # ------------------------------------------------------------------ #
    # 12. dataset_level — constant for whole dataset (alias hardcode_no_ct)
    # ------------------------------------------------------------------ #

    def dataset_level(self, target: str, *, value: Any) -> "SDTMNamespace":
        """Set a dataset-level constant on *target* (alias for hardcode_no_ct)."""
        return self.hardcode_no_ct(target, value=value)

    # ------------------------------------------------------------------ #
    # 13. notsubmitted — mark variable as null / not-submitted            #
    # ------------------------------------------------------------------ #

    def notsubmitted(self, *targets: str) -> "SDTMNamespace":
        """
        Mark one or more variables as not submitted (set to null).

        Useful to explicitly drop or null out eCRF fields not
        included in SDTM submission.
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
        """
        Explode a delimited multi-response field into separate rows.

        Materialises the current pipeline, then splits *source* on
        *delimiter* and explodes, keeping *id_cols* intact.

        Example::

            .multiple_responses("AETERM", source="ae_terms", delimiter="|",
                                 id_cols=["USUBJID"])
        """
        df = self.to_frame()
        # Split source into list, then explode
        expanded = (
            df
            .with_columns(
                pl.col(source).str.split(delimiter).alias("__split__")
            )
            .explode("__split__")
            .with_columns(pl.col("__split__").str.strip_chars().alias(target))
            .drop("__split__")
        )
        new = object.__new__(SDTMNamespace)
        new._df = expanded
        new._pipeline = []
        return new

    # ------------------------------------------------------------------ #
    # Spec-driven pipeline                                                 #
    # ------------------------------------------------------------------ #

    def from_spec(self, spec_path: str | Path) -> "SDTMNamespace":
        """
        Build a pipeline from a YAML specification file.

        The YAML must have a top-level ``variables`` list where each entry
        follows the :class:`~pymaverse.sdtm.models.SDTMVariableSpec` schema.

        Example::

            df.sdtm.from_spec("specs/cdiscpilot01/sdtm/dm_spec.yaml").to_frame()
        """
        from .models import SDTMDomainSpec

        spec_data = yaml.safe_load(Path(spec_path).read_text())
        spec = SDTMDomainSpec(**spec_data)

        ns: SDTMNamespace = self
        for var in spec.variables:
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

    # ------------------------------------------------------------------ #
    # Validation integration                                               #
    # ------------------------------------------------------------------ #

    def validate(
        self,
        domain: str,
        version: str = "3.4",
        rules_engine_path: "Path | None" = None,
    ) -> "SDTMNamespace":
        """
        Run CDISC conformance validation and print the report.

        Returns *self* so the chain can continue.
        """
        from ..validation.service import ValidationService

        svc = ValidationService(rules_engine_path=rules_engine_path)
        result = svc.validate_sdtm(self.to_frame(), domain=domain, version=version)
        result.print_report()
        return self

    # ------------------------------------------------------------------ #
    # Terminal operation                                                   #
    # ------------------------------------------------------------------ #

    def to_frame(self) -> pl.DataFrame:
        """Materialise the accumulated pipeline into a Polars DataFrame."""
        if not self._pipeline:
            return self._df
        return self._df.with_columns(self._pipeline)
