"""Trial Design Domain mixin — adds TDD verbs to ``SDTMNamespace``.

Provides two families of verbs:

Protocol-reference verbs
    ``fetch_structure()``, ``study_header()``, ``add_elements()``,
    ``add_arms()``, ``add_visits()``, ``add_parameters()``,
    ``add_criteria()`` — follow a fixed stage sequence.

Subject-level verbs
    ``visit_map()``, ``element_boundaries()``, ``epoch_assign()``,
    ``study_day()`` — freely mixable with any existing SDTM verb.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any

import polars as pl
import yaml

from fleet.sdtm.tdd import (
    Epoch,
    TrialArms,
    TrialCriteria,
    TrialElements,
    TrialParameters,
    TrialVisits,
)

if TYPE_CHECKING:
    from typing import Self

# Map: domain code → expected add verb name
_DOMAIN_ADD_VERBS: dict[str, str] = {
    "TE": "add_elements",
    "TA": "add_arms",
    "TV": "add_visits",
    "TS": "add_parameters",
    "TI": "add_criteria",
}

# Stage labels for error messages
_STAGE_SEQUENCE = (
    "fetch_structure()",
    "study_header()",
    "add_*()",
    "validate()/to_frame()",
)


class TrialDesignMixin:
    """Mixin that adds Trial Design Domain verbs to the SDTM namespace.

    Stage tracking (``_tdd_stage``) ensures protocol-reference verbs are
    called in the correct order.  Subject-level verbs ignore the stage.
    """

    # These attributes are set lazily; their absence means "not in TDD mode"
    _tdd_stage: int
    _domain_meta: dict[str, Any]
    _reconciliation_report: list[str]

    # ------------------------------------------------------------------ #
    # Stage enforcement                                                    #
    # ------------------------------------------------------------------ #

    def _check_stage(self, verb: str, required: int) -> None:
        """Raise ``ValueError`` if the TDD stage does not match *required*."""
        stage = getattr(self, "_tdd_stage", None)
        if stage is None and required > 0:
            raise ValueError(
                f"Cannot call {verb}() without first calling fetch_structure(). "
                f"Expected sequence: {' → '.join(_STAGE_SEQUENCE)}"
            )
        if stage is not None and stage < required:
            current_label = (
                _STAGE_SEQUENCE[stage] if stage < len(_STAGE_SEQUENCE) else f"stage {stage}"
            )
            raise ValueError(
                f"Cannot call {verb}() at {current_label}. "
                f"Expected sequence: {' → '.join(_STAGE_SEQUENCE)}"
            )

    # ------------------------------------------------------------------ #
    # Shared TDD verbs                                                     #
    # ------------------------------------------------------------------ #

    def fetch_structure(
        self,
        domain: str,
        *,
        ig_version: str = "3-4",
        save_to: str | Path | None = None,
        define_path: str | Path | None = None,
    ) -> Self:  # type: ignore[type-var]
        """Query the CDISC Library for *domain*'s IG structure.

        When *define_path* is given the domain variables (including ``core``)
        are read from the define.yaml first; if the domain is not found the
        method falls back to the online CDISC Library.

        When *save_to* is given the fetched metadata is cached as YAML; on
        subsequent calls the cache is read instead of hitting the API.

        Sets ``_domain_meta`` on the namespace for downstream validation
        and performs schema reconciliation against the static Pydantic model.

        Args:
            domain: SDTM domain code (e.g. ``"TE"``, ``"TA"``).
            ig_version: SDTM IG version slug (default ``"3-4"``).
            save_to: Optional path to cache the fetched YAML.
            define_path: Optional path to a ``define.yaml``. When provided,
                domain metadata is extracted from the spec (offline) before
                falling back to the CDISC Library API.

        Returns:
            Self: The namespace at stage 1; call ``study_header()`` next.

        Examples:
            Fetch the TE structure from the CDISC Library::

                te = (
                    pl.DataFrame().sdtm
                    .fetch_structure("TE", ig_version="3-4",
                                     save_to="metadata/te_structure.yaml")
                    .study_header("CDISCPILOT01", "TE")
                    .add_elements(te_rows)
                    .to_frame()
                )
        """
        self._check_stage("fetch_structure", required=0)
        domain = domain.upper()

        # Priority: define_path → save_to cache → online CDISC Library
        meta: dict[str, Any] | None = None

        if define_path is not None:
            meta = _extract_domain_from_define(domain, Path(define_path))

        cache_path = Path(save_to) if save_to else None
        if meta is None and cache_path and cache_path.exists():
            meta = yaml.safe_load(cache_path.read_text())

        if meta is None:
            try:
                meta = self._fetch_ig_domain(domain, ig_version)
            except Exception as exc:
                raise type(exc)(
                    f"Domain '{domain}' not found in SDTM IG {ig_version}. "
                    f"If this is a company-specific domain, provide its structure "
                    f"via define_path= or a cached YAML via save_to=."
                ) from exc
            if cache_path:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(yaml.dump(meta, default_flow_style=False, sort_keys=False))

        # Propagate to the new namespace instance
        new = self._chain()  # type: ignore[attr-defined]
        new._domain_meta = meta
        new._tdd_stage = 1
        new._reconciliation_report = _reconcile_schema(domain, meta)
        for msg in new._reconciliation_report:
            warnings.warn(msg, UserWarning, stacklevel=2)
        return new  # type: ignore[return-value]

    def study_header(
        self,
        study_id: str,
        domain: str,
    ) -> Self:  # type: ignore[type-var]
        """Hardcode ``STUDYID`` and ``DOMAIN`` columns.

        Args:
            study_id: The study identifier value.
            domain: The SDTM domain code.

        Returns:
            Self: The namespace at stage 2; call an ``add_*()`` verb next.

        Examples:
            Set the study header for a TE domain::

                te = (
                    pl.DataFrame().sdtm
                    .fetch_structure("TE")
                    .study_header("CDISCPILOT01", "TE")
                    .add_elements(te_rows)
                    .to_frame()
                )
        """
        self._check_stage("study_header", required=1)
        new = self._chain(  # type: ignore[attr-defined]
            pl.lit(study_id).alias("STUDYID"),
            pl.lit(domain.upper()).alias("DOMAIN"),
        )
        new._tdd_stage = 2
        return new  # type: ignore[return-value]

    # ------------------------------------------------------------------ #
    # Protocol-reference add verbs                                         #
    # ------------------------------------------------------------------ #

    def add_elements(self, elements: TrialElements) -> Self:  # type: ignore[type-var]
        """Materialise a validated ``TrialElements`` collection into the pipeline.

        Args:
            elements: A ``TrialElements`` collection (pre-validated by Pydantic).

        Returns:
            Self: The namespace at stage 3 with TE rows loaded.

        Examples:
            Add trial elements to a TE pipeline::

                te = (
                    pl.DataFrame().sdtm
                    .fetch_structure("TE")
                    .study_header("CDISCPILOT01", "TE")
                    .add_elements(te_rows)
                    .to_frame()
                )
        """
        self._check_stage("add_elements", required=2)
        return self._materialise_collection(elements.to_polars())

    def add_arms(
        self,
        arms: TrialArms,
        *,
        te: TrialElements | None = None,
    ) -> Self:  # type: ignore[type-var]
        """Materialise a validated ``TrialArms`` collection into the pipeline.

        Args:
            arms: A ``TrialArms`` collection.
            te: Optional ``TrialElements`` for FK validation (ETCD ∈ TE.ETCD).

        Returns:
            Self: The namespace at stage 3 with TA rows loaded.

        Examples:
            Add trial arms with FK validation::

                ta = (
                    pl.DataFrame().sdtm
                    .fetch_structure("TA")
                    .study_header("CDISCPILOT01", "TA")
                    .add_arms(ta_rows, te=te_rows)
                    .to_frame()
                )
        """
        self._check_stage("add_arms", required=2)
        if te is not None:
            valid_etcds = {e.etcd for e in te.elements}
            for a in arms.arms:
                if a.etcd not in valid_etcds:
                    raise ValueError(
                        f"TA.ETCD '{a.etcd}' not found in TE. Valid: {sorted(valid_etcds)}"
                    )
        return self._materialise_collection(arms.to_polars())

    def add_visits(self, visits: TrialVisits) -> Self:  # type: ignore[type-var]
        """Materialise a validated ``TrialVisits`` collection into the pipeline.

        Args:
            visits: A ``TrialVisits`` collection.

        Returns:
            Self: The namespace at stage 3 with TV rows loaded.

        Examples:
            Add trial visits::

                tv = (
                    pl.DataFrame().sdtm
                    .fetch_structure("TV")
                    .study_header("CDISCPILOT01", "TV")
                    .add_visits(tv_rows)
                    .to_frame()
                )
        """
        self._check_stage("add_visits", required=2)
        return self._materialise_collection(visits.to_polars())

    def add_parameters(self, params: TrialParameters) -> Self:  # type: ignore[type-var]
        """Materialise a validated ``TrialParameters`` collection into the pipeline.

        Args:
            params: A ``TrialParameters`` collection.

        Returns:
            Self: The namespace at stage 3 with TS rows loaded.

        Examples:
            Add trial summary parameters::

                ts = (
                    pl.DataFrame().sdtm
                    .fetch_structure("TS")
                    .study_header("CDISCPILOT01", "TS")
                    .add_parameters(ts_rows)
                    .to_frame()
                )
        """
        self._check_stage("add_parameters", required=2)
        return self._materialise_collection(params.to_polars())

    def add_criteria(self, criteria: TrialCriteria) -> Self:  # type: ignore[type-var]
        """Materialise a validated ``TrialCriteria`` collection into the pipeline.

        Args:
            criteria: A ``TrialCriteria`` collection.

        Returns:
            Self: The namespace at stage 3 with TI rows loaded.

        Examples:
            Add inclusion/exclusion criteria::

                ti = (
                    pl.DataFrame().sdtm
                    .fetch_structure("TI")
                    .study_header("CDISCPILOT01", "TI")
                    .add_criteria(ti_rows)
                    .to_frame()
                )
        """
        self._check_stage("add_criteria", required=2)
        return self._materialise_collection(criteria.to_polars())

    # ------------------------------------------------------------------ #
    # Subject-level derivation verbs                                       #
    # ------------------------------------------------------------------ #

    def visit_map(
        self,
        target_num: str,
        target_name: str,
        *,
        date_col: str,
        planned_visits: TrialVisits | pl.DataFrame,
        ref_date: str | None = None,
        tolerance: dict[str, int] | None = None,
    ) -> Self:  # type: ignore[type-var]
        """Map raw visit dates to planned visits from TV.

        For each row, finds the planned visit whose ``VISITDY`` is closest
        to the actual study day (computed from *date_col* − *ref_date*),
        within the optional *tolerance* window.

        Args:
            target_num: Name of the output ``VISITNUM`` column.
            target_name: Name of the output ``VISIT`` column.
            date_col: Column containing the actual visit date (ISO 8601 string).
            planned_visits: A ``TrialVisits`` collection or a DataFrame with
                ``VISITNUM``, ``VISIT``, and ``VISITDY`` columns.
            ref_date: Column with the reference date for study day calculation.
                When ``None``, the raw study day is expected in the data.
            tolerance: Optional ``{"before": n, "after": n}`` window in days.

        Returns:
            Self: The namespace with *target_num* and *target_name* appended.

        Examples:
            Map subject visits to planned visits::

                sv = (
                    raw_visits.sdtm
                    .assign("USUBJID", source="subject_id")
                    .assign_dtc("SVSTDTC", source="visit_date")
                    .visit_map("VISITNUM", "VISIT",
                               date_col="SVSTDTC",
                               planned_visits=tv_rows,
                               ref_date="RFSTDTC",
                               tolerance={"before": 3, "after": 3})
                    .to_frame()
                )
        """
        tv_df = (
            planned_visits.to_polars()
            if isinstance(planned_visits, TrialVisits)
            else planned_visits
        )

        # Materialise so we can do a cross-join + window
        df = self._lazy.collect()  # type: ignore[attr-defined]

        # Calculate actual study day if ref_date is given
        if ref_date and ref_date in df.columns and date_col in df.columns:
            df = df.with_columns(
                (
                    pl.col(date_col).str.to_date(strict=False).cast(pl.Date)
                    - pl.col(ref_date).str.to_date(strict=False).cast(pl.Date)
                )
                .dt.total_days()
                .alias("__actual_dy__")
            )
            # CDISC: no day 0
            df = df.with_columns(
                pl.when(pl.col("__actual_dy__") >= 0)
                .then(pl.col("__actual_dy__") + 1)
                .otherwise(pl.col("__actual_dy__"))
                .alias("__actual_dy__")
            )
        elif "VISITDY" in df.columns:
            df = df.with_columns(pl.col("VISITDY").alias("__actual_dy__"))
        else:
            df = df.with_columns(pl.lit(None).cast(pl.Int64).alias("__actual_dy__"))

        # Cross join with planned visits to find closest
        tv_slim = tv_df.select(
            pl.col("VISITNUM").alias("__tv_num__"),
            pl.col("VISIT").alias("__tv_name__"),
            pl.col("VISITDY").alias("__tv_dy__"),
        )

        df = df.with_row_index("__row_idx__")
        crossed = df.join(tv_slim, how="cross")
        crossed = crossed.with_columns(
            (pl.col("__actual_dy__") - pl.col("__tv_dy__")).abs().alias("__diff__")
        )

        # Apply tolerance filter
        if tolerance:
            before = tolerance.get("before", 999999)
            after = tolerance.get("after", 999999)
            crossed = crossed.filter(
                (pl.col("__actual_dy__") - pl.col("__tv_dy__") >= -before)
                & (pl.col("__actual_dy__") - pl.col("__tv_dy__") <= after)
            )

        # Pick closest visit per row
        best = (
            crossed.sort("__diff__")
            .group_by("__row_idx__")
            .first()
            .select("__row_idx__", "__tv_num__", "__tv_name__")
            .rename({"__tv_num__": target_num, "__tv_name__": target_name})
        )

        df = df.join(best, on="__row_idx__", how="left").drop("__row_idx__", "__actual_dy__")

        return self._materialise_then(df)  # type: ignore[attr-defined]

    def element_boundaries(
        self,
        target_start: str,
        target_end: str,
        *,
        milestones: dict[str, str],
        element_col: str = "ETCD",
        subject_col: str = "USUBJID",
    ) -> Self:  # type: ignore[type-var]
        """Derive element start/end dates from milestone columns.

        For each *element_col* value, maps the corresponding column from
        *milestones* to produce *target_start*.  The end date is the start
        of the next element (by row order within each subject).

        Args:
            target_start: Name of the output start-date column (e.g. ``"SESTDTC"``).
            target_end: Name of the output end-date column (e.g. ``"SEENDTC"``).
            milestones: ``{element_code: source_date_column}`` mapping.
            element_col: Column identifying the element (default ``"ETCD"``).
            subject_col: Column identifying the subject (default ``"USUBJID"``).

        Returns:
            Self: The namespace with *target_start* and *target_end* appended.

        Examples:
            Derive SE element boundaries::

                se = (
                    disposition_df.sdtm
                    .element_boundaries("SESTDTC", "SEENDTC",
                                        milestones={"SCRN": "screening_date",
                                                     "TRT": "first_dose_date"})
                    .to_frame()
                )
        """
        # Build a when/then chain mapping element codes to date columns
        cases: list[tuple[str, str]] = list(milestones.items())
        if not cases:
            return self._chain(  # type: ignore[attr-defined]
                pl.lit(None).alias(target_start),
                pl.lit(None).alias(target_end),
            )

        first_code, first_col = cases[0]
        expr = pl.when(pl.col(element_col) == first_code).then(pl.col(first_col))
        for code, col in cases[1:]:
            expr = expr.when(pl.col(element_col) == code).then(pl.col(col))
        start_expr = expr.otherwise(pl.lit(None)).alias(target_start)

        # End = next element's start within same subject
        df = self._lazy.collect()  # type: ignore[attr-defined]
        df = df.with_columns(start_expr)
        df = df.with_columns(pl.col(target_start).shift(-1).over(subject_col).alias(target_end))

        return self._materialise_then(df)  # type: ignore[attr-defined]

    def epoch_assign(
        self,
        target: str,
        *,
        date_col: str,
        epoch_ranges: list[dict[str, str]] | pl.DataFrame,
    ) -> Self:  # type: ignore[type-var]
        """Assign ``EPOCH`` based on date ranges.

        Each entry in *epoch_ranges* maps a date interval to an ``Epoch``
        value.  The first matching range wins.

        Args:
            target: Name of the output ``EPOCH`` column.
            date_col: Column containing the date to classify.
            epoch_ranges: A list of ``{"start": date, "end": date,
                "epoch": str}`` dicts, or a DataFrame with those columns.

        Returns:
            Self: The namespace with *target* appended.

        Examples:
            Assign epoch from date ranges::

                sv = (
                    raw_df.sdtm
                    .epoch_assign("EPOCH", date_col="SVSTDTC",
                                  epoch_ranges=[
                                      {"start": "2014-01-01", "end": "2014-01-15",
                                       "epoch": "SCREENING"},
                                      {"start": "2014-01-16", "end": "2014-04-15",
                                       "epoch": "TREATMENT"},
                                  ])
                    .to_frame()
                )
        """
        if isinstance(epoch_ranges, pl.DataFrame):
            ranges = epoch_ranges.to_dicts()
        else:
            ranges = epoch_ranges

        if not ranges:
            return self._chain(pl.lit(None).alias(target))  # type: ignore[attr-defined]

        # Build nested when/then
        first = ranges[0]
        expr = pl.when(
            (
                pl.col(date_col).str.to_date(strict=False)
                >= pl.lit(first["start"]).str.to_date(strict=False)
            )
            & (
                pl.col(date_col).str.to_date(strict=False)
                <= pl.lit(first["end"]).str.to_date(strict=False)
            )
        ).then(pl.lit(first["epoch"]))

        for r in ranges[1:]:
            expr = expr.when(
                (
                    pl.col(date_col).str.to_date(strict=False)
                    >= pl.lit(r["start"]).str.to_date(strict=False)
                )
                & (
                    pl.col(date_col).str.to_date(strict=False)
                    <= pl.lit(r["end"]).str.to_date(strict=False)
                )
            ).then(pl.lit(r["epoch"]))

        final_expr = expr.otherwise(pl.lit(None)).alias(target)
        return self._chain(final_expr)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _materialise_collection(self, df: pl.DataFrame) -> Self:  # type: ignore[type-var]
        """Replace the lazy plan with *df*, preserving STUDYID/DOMAIN."""
        # Collect current header columns (STUDYID, DOMAIN)
        current = self._lazy.collect()  # type: ignore[attr-defined]
        header_cols = {}
        for col in ("STUDYID", "DOMAIN"):
            if col in current.columns and current.height > 0:
                header_cols[col] = current[col][0]

        # Broadcast header onto the collection rows
        if header_cols:
            df = df.with_columns([pl.lit(v).alias(k) for k, v in header_cols.items()])

        new = self._materialise_then(df)  # type: ignore[attr-defined]
        new._tdd_stage = 3
        return new  # type: ignore[return-value]

    @staticmethod
    def _fetch_ig_domain(domain: str, ig_version: str) -> dict[str, Any]:
        """Fetch domain metadata from the CDISC Library IG."""
        from fleet.ct.api import CDISCClient

        with CDISCClient() as client:
            detail = client._get(f"/mdr/sdtmig/{ig_version}/datasets/{domain}")

        # Parse into a lightweight dict
        variables: list[dict[str, str]] = []
        for var in sorted(
            detail.get("datasetVariables", []),
            key=lambda v: int(v.get("ordinal", 999)),
        ):
            var_info: dict[str, str] = {
                "name": var.get("name", ""),
                "label": var.get("label", ""),
                "type": var.get("simpleDatatype", "Char"),
                "core": var.get("core", "Perm"),
                "role": var.get("role", ""),
            }
            # Extract codelist reference
            for cl in var.get("_links", {}).get("codelist", []):
                import re

                m = re.search(r"codelists/(C\d+)", cl.get("href", ""))
                if m:
                    var_info["codelist"] = m.group(1)
                    break
            variables.append(var_info)

        return {
            "domain": domain,
            "label": detail.get("label", ""),
            "ig_version": ig_version,
            "variables": variables,
        }


# Reverse map: define.yaml type → CDISC simpleDatatype for reconciliation
_DEFINE_TO_IG_TYPE: dict[str, str] = {
    "text": "Char",
    "integer": "Integer",
    "float": "Num",
    "date": "Char",
    "datetime": "Char",
}

# define.yaml mandatory+core → IG core string
_DEFINE_CORE_TO_IG: dict[str, str] = {
    "Req": "Req",
    "Exp": "Exp",
    "Perm": "Perm",
    "Cond": "Perm",
    "Conditionally Required": "Perm",
}


def _extract_domain_from_define(domain: str, define_path: Path) -> dict[str, Any] | None:
    """Try to extract domain metadata from a define.yaml.

    Returns ``None`` when the file doesn't exist or the domain is not found,
    so the caller can fall back to the online CDISC Library.
    """
    if not define_path.is_file():
        return None

    data = yaml.safe_load(define_path.read_text(encoding="utf-8"))
    for ds in data.get("datasets", []):
        if ds.get("name", "").upper() == domain:
            variables: list[dict[str, str]] = []
            for var in ds.get("variables", []):
                core = var.get("core", "")
                if not core:
                    # Fall back to mandatory boolean
                    core = "Req" if var.get("mandatory") else "Perm"
                var_info: dict[str, str] = {
                    "name": var.get("name", ""),
                    "label": var.get("label", ""),
                    "type": _DEFINE_TO_IG_TYPE.get(var.get("type", "text"), "Char"),
                    "core": _DEFINE_CORE_TO_IG.get(core, "Perm"),
                    "role": "",
                }
                if var.get("codelist"):
                    var_info["codelist"] = var["codelist"]
                variables.append(var_info)
            return {
                "domain": domain,
                "label": ds.get("label", ""),
                "ig_version": "",
                "variables": variables,
            }
    return None


# ------------------------------------------------------------------ #
# Schema reconciliation                                                #
# ------------------------------------------------------------------ #

# Static model fields by domain
_DOMAIN_FIELDS: dict[str, set[str]] = {
    "TE": {"STUDYID", "DOMAIN", "ETCD", "ELEMENT", "TESTRL", "TEENRL", "TEDUR", "EPOCH"},
    "TA": {"STUDYID", "DOMAIN", "ARMCD", "ARM", "TAETORD", "ETCD", "ELEMENT", "EPOCH"},
    "TV": {"STUDYID", "DOMAIN", "VISITNUM", "VISIT", "VISITDY", "ARMCD", "TVSTRL", "TVENRL"},
    "TS": {"STUDYID", "DOMAIN", "TSPARMCD", "TSPARM", "TSVAL", "TSVALNF", "TSVALCD"},
    "TI": {"STUDYID", "DOMAIN", "IETESTCD", "IETEST", "IECAT", "IESCAT", "TIRL"},
    "SV": {"STUDYID", "DOMAIN", "USUBJID", "VISITNUM", "VISIT", "SVSTDTC", "SVENDTC", "EPOCH"},
    "SE": {
        "STUDYID",
        "DOMAIN",
        "USUBJID",
        "SESEQ",
        "ETCD",
        "ELEMENT",
        "SESTDTC",
        "SEENDTC",
        "EPOCH",
    },
}

# Variables that are always Char in Fleet's Pydantic models, even if the IG
# metadata reports them as Num/Integer (known IG metadata quirks).
_ALWAYS_CHAR_VARS: frozenset[str] = frozenset(
    {
        "ETCD",
        "ARMCD",
        "ELEMENT",
        "ARM",
        "VISIT",
        "TSPARMCD",
        "TSPARM",
        "IETESTCD",
        "IETEST",
    }
)


def _reconcile_schema(domain: str, meta: dict[str, Any]) -> list[str]:
    """Compare fetched IG metadata against the static Pydantic model.

    Returns a list of warning messages (empty if everything matches).
    """
    report: list[str] = []
    domain = domain.upper()
    static_fields = _DOMAIN_FIELDS.get(domain)
    if static_fields is None or "variables" not in meta:
        return report

    ig_vars = {v["name"]: v for v in meta["variables"]}

    # Check for required IG variables missing from static model
    for vname, vinfo in ig_vars.items():
        core = vinfo.get("core", "Perm")
        if core in ("Req", "Required") and vname not in static_fields:
            report.append(
                f"TDD reconciliation [{domain}]: IG requires '{vname}' "
                f"(core={core}) but no Pydantic field exists"
            )

    # Check for type mismatches — flag IG Num/Integer on known-string variables
    for vname in static_fields:
        if vname in ig_vars:
            ig_type = ig_vars[vname].get("type", "Char")
            if ig_type in ("Num", "Integer") and vname in _ALWAYS_CHAR_VARS:
                report.append(
                    f"TDD reconciliation [{domain}]: IG type '{ig_type}' for "
                    f"'{vname}' but Pydantic model uses 'str'"
                )

    # Check for codelist drift on EPOCH
    for vname, vinfo in ig_vars.items():
        if vname == "EPOCH" and "codelist" in vinfo:
            if vinfo["codelist"] != Epoch._concept_id:
                report.append(
                    f"TDD reconciliation [{domain}]: EPOCH codelist "
                    f"'{vinfo['codelist']}' differs from Epoch enum "
                    f"({Epoch._concept_id}). Run `fleet init ct` to sync."
                )

    return report
