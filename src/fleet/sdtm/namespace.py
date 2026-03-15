"""
SDTM Polars namespace extension.

Registers ``df.sdtm`` on every Polars DataFrame.

Usage
-----
    import fleet  # triggers registration

    result = (
        raw_df.sdtm
        .assign_no_ct("USUBJID", source="patient_number")
        .assign_ct("SEX", source="sex", ct_codelist="C66731")
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
        """Copy *source* column to *target* with no CT validation."""
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
        """
        Derive *target* using a Polars expression or expression string.

        Example::

            .derivation("SITEID", expression="pl.col('site_id').cast(pl.String)")
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
        """
        Remove duplicate rows, optionally on a *subset* of columns.

        Materialises, deduplicates, and returns a fresh namespace.
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
        """
        Group by *group_cols* and apply *agg* aggregations.

        Materialises, groups, and returns a fresh namespace.

        Example::

            .group_by(
                group_cols=["USUBJID", "VSTESTCD"],
                agg=[pl.col("VSSTRESN").max().alias("AVAL")],
            )
        """
        new = object.__new__(SDTMNamespace)
        new._lazy = self._lazy.group_by(group_cols).agg(agg)
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
        """
        Build a pipeline from a YAML specification file.

        Reads a ``define.yaml`` with a top-level ``datasets`` list where each
        variable carries a ``derivation`` block.  Pass *dataset* to select
        which dataset to execute (e.g. ``dataset="DM"``).  When the file
        contains only one dataset the *dataset* argument may be omitted.

        Example::

            df.sdtm.from_spec("specs/cdiscpilot01/sdtm/define.yaml", dataset="DM").to_frame()
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

        Examples::

            # Keep only spec columns, drop scratch _ variables (default)
            .select(spec="specs/sdtm/define.yaml", dataset="DM")

            # Same but disable auto-drop for debugging
            .select(spec="specs/sdtm/define.yaml", dataset="DM", drop_pattern=None)

            # Just drop _ variables, keep everything else
            .select()

            # Fully disable — do nothing (passthrough, for debugging)
            .select(drop_pattern=None)
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
            col_list = self._spec_columns(spec_path, dataset)
            type_map = self._spec_type_map(spec_path, dataset)

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
    def _spec_columns(spec_path: Path, dataset: str | None) -> list[str]:
        """Return the ordered variable-name list for *dataset* from a define.yaml."""
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
        return [v["name"] for v in ds["variables"]]

    @staticmethod
    def _spec_type_map(spec_path: Path, dataset: str | None) -> dict[str, str]:
        """Return ``{col_name: type}`` for date/datetime variables in *dataset*."""
        spec_data = yaml.safe_load(spec_path.read_text())
        datasets = spec_data.get("datasets", [])
        if dataset is None:
            ds = datasets[0] if len(datasets) == 1 else None
        else:
            matches = [d for d in datasets if d["name"].upper() == dataset.upper()]
            ds = matches[0] if matches else None
        if ds is None:
            return {}
        return {
            v["name"]: v["type"]
            for v in ds["variables"]
            if v.get("type") in ("date", "datetime")
        }

    def _new_from(self, df: pl.DataFrame) -> "SDTMNamespace":
        """Return a fresh SDTMNamespace wrapping *df* as a lazy plan."""
        new = object.__new__(SDTMNamespace)
        new._lazy = df.lazy()
        return new

    # ------------------------------------------------------------------ #
    # Terminal operations                                                  #
    # ------------------------------------------------------------------ #

    def to_frame(self) -> pl.DataFrame:
        """Materialise the accumulated pipeline into a Polars DataFrame."""
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

        Example::

            dm = (
                raw_df.sdtm
                .assign_no_ct("USUBJID", source="patient_number")
                ...
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
