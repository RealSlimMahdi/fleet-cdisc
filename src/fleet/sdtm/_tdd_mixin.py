"""Trial Design Domain mixin — adds TDD verbs to ``SDTMNamespace``.

Provides two families of verbs:

Protocol-reference verbs
    ``fetch_structure()``, ``study_header()``, ``add_elements()``,
    ``add_arms()``, ``add_visits()``, ``add_parameters()``,
    ``add_criteria()``, ``add_disease_assessments()``,
    ``add_milestones()`` — follow a fixed stage sequence.

Subject-level verbs
    ``visit_map()``, ``element_boundaries()``, ``epoch_assign()``,
    ``study_day()`` — freely mixable with any existing SDTM verb.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import polars as pl
import yaml

from fleet.core.define_spec import load_spec_yaml
from fleet.core.dtc import cdisc_day, date_part, datetime_part, to_day
from fleet.core.exceptions import CTError, DerivationError
from fleet.sdtm.tdd import (
    Epoch,
    TrialArms,
    TrialCriteria,
    TrialDiseaseAssessments,
    TrialElements,
    TrialMilestones,
    TrialParameters,
    TrialVisits,
)
from fleet.sdtm.utils import to_char

if TYPE_CHECKING:
    from typing import Self

# Map: domain code → expected add verb name
_DOMAIN_ADD_VERBS: dict[str, str] = {
    "TE": "add_elements",
    "TA": "add_arms",
    "TV": "add_visits",
    "TS": "add_parameters",
    "TI": "add_criteria",
    "TD": "add_disease_assessments",
    "TM": "add_milestones",
}

# Packaged SDTMIG 3.4 structures for the TDD domains (offline default).
_PACKAGED_STRUCTURES = Path(__file__).with_name("_tdd_structures.yaml")
_PACKAGED_IG_VERSION = "3-4"


def _load_packaged_structure(domain: str, ig_version: str) -> dict[str, Any] | None:
    """Return the packaged IG metadata for *domain*, or None when unavailable."""
    if ig_version.replace(".", "-") != _PACKAGED_IG_VERSION:
        return None
    return yaml.safe_load(_PACKAGED_STRUCTURES.read_text(encoding="utf-8")).get(domain)


def packaged_structure(domain: str) -> dict[str, Any] | None:
    """Return the packaged SDTMIG 3.4 label and variables of a trial design domain."""
    return _load_packaged_structure(domain.upper(), _PACKAGED_IG_VERSION)


def _same_day_rule(date_col: str, same_day: str) -> Literal["earlier", "later"]:
    """The element a record with no time takes on a transition date."""
    if same_day in ("earlier", "later"):
        return same_day  # type: ignore[return-value]
    if same_day != "by_class":
        raise DerivationError(
            f"epoch_assign(same_day={same_day!r}): choose 'by_class', 'earlier' or 'later'."
        )
    name = date_col.upper()
    if name.endswith("STDTC"):
        return "later"
    if name.endswith("DTC") and not name.endswith("ENDTC"):
        return "earlier"
    raise DerivationError(
        f"epoch_assign(date_col='{date_col}', same_day='by_class'): the record kind comes "
        "from the name, --DTC (Findings) takes the earlier element and --STDTC (Events, "
        f"Interventions) the later one. '{date_col}' is neither: pass same_day='earlier' "
        "or same_day='later'."
    )


def _epoch_from_se(
    df: pl.DataFrame,
    se: pl.DataFrame | pl.LazyFrame,
    target: str,
    date_col: str,
    subject_col: str,
    rule: Literal["earlier", "later"],
    same_day: str,
) -> pl.DataFrame:
    """``__row_idx__`` and *target* for each row of *df* that falls in an SE element."""
    se_df = se.collect() if isinstance(se, pl.LazyFrame) else se
    if "EPOCH" not in se_df.columns:
        raise DerivationError(
            f"epoch_assign({target}, se=): SE has no EPOCH. EPOCH is Permissible in SE: add "
            "it by ETCD, for example with a join from TA; elements with no TA row stay null."
        )
    end_raw = pl.col("SEENDTC").cast(pl.String).str.strip_chars()
    elements = se_df.select(
        pl.col(subject_col),
        date_part(pl.col("SESTDTC")).alias("__sd__"),
        datetime_part(pl.col("SESTDTC")).alias("__st__"),
        date_part(pl.col("SEENDTC")).alias("__ed__"),
        datetime_part(pl.col("SEENDTC")).alias("__et__"),
        (end_raw.is_null() | (end_raw == "")).alias("__open__"),
        pl.col("EPOCH").alias("__ep__"),
    )
    usable = pl.col("__sd__").is_not_null() & (pl.col("__ed__").is_not_null() | pl.col("__open__"))
    skipped = elements.filter(~usable).height
    if skipped:
        warnings.warn(
            f"epoch_assign({target}): {skipped} SE record(s) have no complete date in "
            "SESTDTC or SEENDTC, so these elements are skipped.",
            stacklevel=3,
        )

    dtype = df.schema[date_col]
    if dtype == pl.String:
        row_time = datetime_part(pl.col(date_col))
    elif isinstance(dtype, pl.Datetime):
        row_time = pl.col(date_col).cast(pl.Datetime("us"))
    else:
        row_time = pl.lit(None, dtype=pl.Datetime("us"))
    rows = df.select(
        "__row_idx__",
        pl.col(subject_col),
        to_day(pl.col(date_col), dtype).alias("__d__"),
        row_time.alias("__t__"),
        pl.col(date_col).cast(pl.String).alias("__raw__"),
    )
    d, t = pl.col("__d__"), pl.col("__t__")
    # On a transition date the time decides when the record and the boundary both have one.
    starts_later = (d == pl.col("__sd__")) & (t < pl.col("__st__"))
    ended_earlier = (d == pl.col("__ed__")) & (t >= pl.col("__et__"))
    candidates = (
        rows.join(elements.filter(usable), on=subject_col, how="inner")
        .filter((d >= pl.col("__sd__")) & (pl.col("__open__") | (d <= pl.col("__ed__"))))
        .filter(~(starts_later.fill_null(False) | ended_earlier.fill_null(False)))
        .sort("__row_idx__", "__sd__", "__st__", nulls_last=False)
    )
    picked = candidates.group_by("__row_idx__", maintain_order=True).agg(
        pl.len().alias("__n__"),
        pl.col("__ep__").first().alias("__first__"),
        pl.col("__ep__").last().alias("__last__"),
        pl.col(subject_col).first().alias("__subject__"),
        pl.col("__raw__").first(),
    )
    ambiguous = picked.filter(pl.col("__n__") > 1)
    if ambiguous.height:
        sample = ", ".join(
            f"{s} {v}" for s, v in ambiguous.select("__subject__", "__raw__").head(5).iter_rows()
        )
        warnings.warn(
            f"epoch_assign({target}): {ambiguous.height} row(s) fall on an element transition "
            f"date with no time to compare; EPOCH set to the {rule} element "
            f"(same_day='{same_day}', date_col {date_col}). First rows: {sample}. "
            "State this rule in the SDRG.",
            stacklevel=3,
        )
    choice = pl.col("__first__") if rule == "earlier" else pl.col("__last__")
    return picked.select(
        "__row_idx__",
        pl.when(pl.col("__n__") == 1).then(pl.col("__first__")).otherwise(choice).alias(target),
    )


def _unscheduled_visits(
    df: pl.DataFrame,
    crossed: pl.DataFrame,
    best: pl.DataFrame,
    verb: str,
    tv_slim: pl.DataFrame,
) -> pl.DataFrame:
    """Number each dated row with no planned visit as last planned VISITNUM + .1, .2, ..."""
    dated = df.filter(
        pl.col("__actual_dy__").is_not_null()
        & ~pl.col("__row_idx__").is_in(best["__row_idx__"].implode())
    )
    if dated.is_empty():
        return best.clear()
    subject = ["USUBJID"] if "USUBJID" in df.columns else []
    base = (
        crossed.filter(pl.col("__tv_dy__") <= pl.col("__actual_dy__"))
        .sort("__row_idx__", "__tv_dy__", "__tv_num__")
        .group_by("__row_idx__", maintain_order=True)
        .last()
        .select("__row_idx__", pl.col("__tv_num__").cast(pl.Float64).alias("__base__"))
    )
    rows = (
        dated.select("__row_idx__", *subject, "__actual_dy__")
        .join(base, on="__row_idx__", how="left")
        .with_columns(pl.col("__base__").fill_null(0.0))
        .sort("__actual_dy__", "__row_idx__")
        .with_columns(pl.int_range(1, pl.len() + 1).over([*subject, "__base__"]).alias("__k__"))
        .with_columns((pl.col("__base__") + pl.col("__k__") / 10).round(6).alias("__tv_num__"))
    )
    too_many = rows.filter(pl.col("__tv_num__") >= pl.col("__base__").floor() + 1)
    planned = rows.filter(
        pl.col("__tv_num__").is_in(tv_slim["__tv_num__"].cast(pl.Float64).implode())
    )
    if too_many.height or planned.height:
        raise DerivationError(
            f"{verb}: an unscheduled visit would take the number "
            f"{(too_many if too_many.height else planned)['__tv_num__'][0]}, which reaches "
            "the next whole number or repeats a planned VISITNUM. Map these visits by hand."
        )
    return rows.select(
        "__row_idx__",
        "__tv_num__",
        (pl.lit("UNSCHEDULED ") + to_char(pl.col("__tv_num__"), pl.Float64)).alias("__tv_name__"),
    )


def _warn_visit_map(df: pl.DataFrame, verb: str, target_num: str, unscheduled: int) -> None:
    """One warning for null and unscheduled rows, one for repeated SV keys."""
    parts = []
    if nulls := df[target_num].null_count():
        parts.append(f"{nulls} row(s) have no study day, so {target_num} is null")
    if unscheduled:
        parts.append(f"{unscheduled} row(s) are outside every window and get an unscheduled number")
    if parts:
        warnings.warn(f"{verb}: " + "; ".join(parts) + ".", stacklevel=3)
    if "DOMAIN" not in df.columns or "USUBJID" not in df.columns:
        return
    sv = df.filter((pl.col("DOMAIN") == "SV") & pl.col(target_num).is_not_null())
    repeats = sv.group_by("USUBJID", target_num).len().filter(pl.col("len") > 1)
    if repeats.height:
        warnings.warn(
            f"{verb}: {repeats.height} USUBJID + {target_num} key(s) repeat on "
            f"{repeats['len'].sum()} row(s). The SV key must be unique (SDTMIG 3.4).",
            stacklevel=3,
        )


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
    _tdd_domain: str
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

        SDTMIG 3.4 structures for the nine TDD domains (TE, TA, TV, TS, TI,
        TD, TM, SV, SE) ship with Fleet, so the default flow needs no
        network access and no API key; the CDISC Library is only queried
        for other domains or IG versions.

        Keeps the IG metadata on the namespace and compares it with the
        static Pydantic model; each difference gives a warning.  The
        requested domain is kept too: ``study_header`` and the ``add_*``
        verb must name the same domain.

        Args:
            domain: SDTM domain code (e.g. ``"TE"``, ``"TA"``).
            ig_version: SDTM IG version slug (default ``"3-4"``).
            save_to: Optional path to cache the fetched YAML.  A cache
                that holds another domain or IG version raises.
            define_path: Optional path to a ``define.yaml``. When provided,
                domain metadata is extracted from the spec (offline) before
                falling back to the CDISC Library API.

        Returns:
            Self: The namespace at stage 1; call ``study_header()`` next.

        Raises:
            FileNotFoundError: When *define_path* is not a file.
            ValueError: When the *save_to* cache holds another domain or
                IG version.
            CTError: When the CDISC Library cannot give the domain; the
                message gives the cause (for example a missing API key).

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

        # Priority: define_path → save_to cache → packaged IG 3.4 → online
        meta: dict[str, Any] | None = None

        if define_path is not None:
            if not Path(define_path).is_file():
                raise FileNotFoundError(f"fetch_structure('{domain}'): no file {define_path}")
            meta = _extract_domain_from_define(domain, Path(define_path))

        cache_path = Path(save_to) if save_to else None
        if meta is None and cache_path and cache_path.exists():
            meta = yaml.safe_load(cache_path.read_text(encoding="utf-8"))
            cached = {k: (meta or {}).get(k) for k in ("domain", "ig_version")}
            if cached["domain"] and str(cached["domain"]).upper() != domain:
                raise ValueError(
                    f"fetch_structure('{domain}'): the cache {cache_path} holds domain "
                    f"{cached['domain']}, not {domain}."
                )
            if cached["ig_version"] and cached["ig_version"] != ig_version:
                raise ValueError(
                    f"fetch_structure('{domain}', ig_version='{ig_version}'): the cache "
                    f"{cache_path} holds SDTM IG {cached['ig_version']}."
                )

        if meta is None:
            meta = _load_packaged_structure(domain, ig_version)
            if meta is None:
                try:
                    meta = self._fetch_ig_domain(domain, ig_version)
                except Exception as exc:
                    raise CTError(
                        f"Could not get domain '{domain}' from SDTM IG {ig_version}: {exc}. "
                        f"If this is a company-specific domain, provide its structure "
                        f"via define_path= or a cached YAML via save_to=."
                    ) from exc
            if cache_path:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_text(
                    yaml.dump(meta, default_flow_style=False, sort_keys=False), encoding="utf-8"
                )

        # Propagate to the new namespace instance
        new = self._chain()  # type: ignore[attr-defined]
        new._domain_meta = meta
        new._tdd_domain = domain
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
            study_id: The study identifier value (a non-empty string).
            domain: The SDTM domain code; it must match ``fetch_structure``.

        Returns:
            Self: The namespace at stage 2; call an ``add_*()`` verb next.

        Raises:
            ValueError: When *study_id* is empty or not a string, or when
                *domain* is not the domain of ``fetch_structure``.

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
        if not isinstance(study_id, str) or not study_id.strip():
            raise ValueError(
                f"study_header(): study_id must be a non-empty string, got {study_id!r}"
            )
        fetched = getattr(self, "_tdd_domain", None)
        if fetched is not None and domain.upper() != fetched:
            raise ValueError(
                f"study_header('{domain.upper()}') does not match fetch_structure('{fetched}')."
            )
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
        return self._materialise_collection(elements.to_polars(), "add_elements")

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
        return self._materialise_collection(arms.to_polars(), "add_arms")

    def add_visits(
        self,
        visits: TrialVisits,
        *,
        ta: TrialArms | None = None,
    ) -> Self:  # type: ignore[type-var]
        """Materialise a validated ``TrialVisits`` collection into the pipeline.

        Args:
            visits: A ``TrialVisits`` collection.
            ta: Optional ``TrialArms`` for FK validation (non-blank
                ARMCD ∈ TA.ARMCD).

        Returns:
            Self: The namespace at stage 3 with TV rows loaded.

        Examples:
            Add trial visits with FK validation::

                tv = (
                    pl.DataFrame().sdtm
                    .fetch_structure("TV")
                    .study_header("CDISCPILOT01", "TV")
                    .add_visits(tv_rows, ta=ta_rows)
                    .to_frame()
                )
        """
        self._check_stage("add_visits", required=2)
        if ta is not None:
            valid_armcds = {a.armcd for a in ta.arms}
            for v in visits.visits:
                if v.armcd and v.armcd not in valid_armcds:
                    raise ValueError(
                        f"TV.ARMCD '{v.armcd}' not found in TA. Valid: {sorted(valid_armcds)}"
                    )
        return self._materialise_collection(visits.to_polars(), "add_visits")

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
        return self._materialise_collection(params.to_polars(), "add_parameters")

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
        return self._materialise_collection(criteria.to_polars(), "add_criteria")

    def add_disease_assessments(self, assessments: TrialDiseaseAssessments) -> Self:  # type: ignore[type-var]
        """Materialise a validated ``TrialDiseaseAssessments`` collection.

        Args:
            assessments: A ``TrialDiseaseAssessments`` collection.

        Returns:
            Self: The namespace at stage 3 with TD rows loaded.

        Examples:
            Add trial disease assessments::

                td = (
                    pl.DataFrame().sdtm
                    .fetch_structure("TD")
                    .study_header("CDISCPILOT01", "TD")
                    .add_disease_assessments(td_rows)
                    .to_frame()
                )
        """
        self._check_stage("add_disease_assessments", required=2)
        return self._materialise_collection(assessments.to_polars(), "add_disease_assessments")

    def add_milestones(self, milestones: TrialMilestones) -> Self:  # type: ignore[type-var]
        """Materialise a validated ``TrialMilestones`` collection.

        Args:
            milestones: A ``TrialMilestones`` collection.

        Returns:
            Self: The namespace at stage 3 with TM rows loaded.

        Examples:
            Add trial disease milestones::

                tm = (
                    pl.DataFrame().sdtm
                    .fetch_structure("TM")
                    .study_header("CDISCPILOT01", "TM")
                    .add_milestones(tm_rows)
                    .to_frame()
                )
        """
        self._check_stage("add_milestones", required=2)
        return self._materialise_collection(milestones.to_polars(), "add_milestones")

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
        """Map raw visit dates to planned visits from TV, by nearest study day.

        Use it only when the CRF does not collect the visit: it never
        replaces a collected VISITNUM.  For each row, the verb takes the
        planned visit whose ``VISITDY`` is nearest to the actual study day
        (from *date_col* and *ref_date*), within the optional *tolerance*
        window.  The distance is the difference of the study-day numbers,
        as ``abs(SVSTDY - VISITDY)`` in a SAS program: across the missing
        Day 0, Day -1 is 2 days from ``VISITDY`` 1.  Ties resolve to the
        earlier ``VISITNUM``.  When TV has ``ARMCD`` values, a row only
        takes a visit of its own arm or a visit with a blank ``ARMCD``.

        A dated row outside every window is an unscheduled visit.  It gets
        the ``VISITNUM`` of the last planned visit on or before its study
        day plus .1, .2, ... in date order within the subject, and the
        ``VISIT`` ``UNSCHEDULED <VISITNUM>``.  A row with no study day gets
        a null.  One warning gives both counts.  With ``DOMAIN`` SV, one
        warning gives the ``USUBJID`` + ``VISITNUM`` keys that repeat.

        With no *tolerance*, every dated record takes the nearest planned
        visit, however far it is, so no record is unscheduled (ADR-0035).
        One warning then gives the count and the largest distance.

        Args:
            target_num: Name of the output ``VISITNUM`` column.  An
                existing column of that name is replaced.
            target_name: Name of the output ``VISIT`` column.  An existing
                column of that name is replaced.
            date_col: Column containing the actual visit date (ISO 8601 string).
            planned_visits: A ``TrialVisits`` collection or a DataFrame with
                ``VISITNUM``, ``VISIT``, and ``VISITDY`` columns (and
                optionally ``ARMCD``).
            ref_date: Column with the reference date for the study day.
                When it is not a column of the frame, it is read from the
                pinned DM, as ``study_day()`` does.  When ``None``, the
                frame must hold the study day in a ``VISITDY`` column.
            tolerance: Optional ``{"before": n, "after": n}`` window in
                study days, boundaries inclusive: the actual study day may
                precede the planned ``VISITDY`` by up to *before* and
                follow it by up to *after*.

        Returns:
            Self: The namespace with *target_num* and *target_name* appended.

        Raises:
            DerivationError: When *date_col* or *ref_date* cannot be found,
                when TV has arm-specific visits and the frame has no
                ``ARMCD``, or when an unscheduled number would repeat a
                planned ``VISITNUM`` or reach the next whole number.

        References:
            SDTMIG 3.4 SV and TV: ``USUBJID`` + ``VISITNUM`` is the SV key,
            ``VISITNUM`` is Req, a null TV ``ARMCD`` means all arms.  The
            decimal number of an unscheduled visit is a sponsor convention
            (the CDISC pilot uses ``UNSCHEDULED 5.1``); see
            ``docs/adr/0035-visit-map-numbers-an-unscheduled-visit.md``.

        Examples:
            Map subject visits to planned visits::

                sv = (
                    raw_visits.sdtm
                    .assign("DOMAIN", value="SV")
                    .assign("USUBJID", source="subject_id")
                    .date("SVSTDTC", source="visit_date")
                    .pin("DM", dm)
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
        verb = f"visit_map({target_num})"
        df = self._lazy.collect().with_row_index("__row_idx__")  # type: ignore[attr-defined]
        df = df.drop([c for c in (target_num, target_name) if c in df.columns])
        actual = self._visit_map_study_day(df, verb, date_col, ref_date)
        df = df.with_columns(actual.alias("__actual_dy__"))

        tv_arm = (
            pl.col("ARMCD").cast(pl.String).replace("", None)
            if "ARMCD" in tv_df.columns
            else pl.lit(None, dtype=pl.String)
        )
        tv_slim = tv_df.select(
            pl.col("VISITNUM").alias("__tv_num__"),
            pl.col("VISIT").alias("__tv_name__"),
            pl.col("VISITDY").alias("__tv_dy__"),
            tv_arm.alias("__tv_arm__"),
        )
        arm_specific = tv_slim["__tv_arm__"].is_not_null().any()
        if arm_specific and "ARMCD" not in df.columns:
            raise DerivationError(
                f"{verb}: the planned visits hold arm-specific ARMCD values, and the frame "
                "has no ARMCD column. Add ARMCD so each subject takes only the visits of its arm."
            )

        crossed = df.select("__row_idx__", "__actual_dy__", *(["ARMCD"] if arm_specific else []))
        crossed = crossed.join(tv_slim, how="cross").filter(pl.col("__actual_dy__").is_not_null())
        if arm_specific:
            crossed = crossed.filter(
                pl.col("__tv_arm__").is_null() | (pl.col("__tv_arm__") == pl.col("ARMCD"))
            )
        offset = pl.col("__actual_dy__") - pl.col("__tv_dy__")
        candidates = crossed.filter(offset.is_not_null()).with_columns(
            offset.abs().alias("__diff__")
        )
        if tolerance:
            before = tolerance.get("before", 999999)
            after = tolerance.get("after", 999999)
            candidates = candidates.filter((offset >= -before) & (offset <= after))

        best = (
            candidates.sort("__row_idx__", "__diff__", "__tv_num__")
            .group_by("__row_idx__", maintain_order=True)
            .first()
            .select("__row_idx__", "__tv_num__", "__tv_name__", "__diff__")
        )
        if not tolerance and best.height:
            warnings.warn(
                f"{verb}: no tolerance=: {best.height} row(s) mapped to the nearest visit, the "
                f"largest distance is {best['__diff__'].max()} study days. Give tolerance= to "
                "make a record outside every window an unscheduled visit.",
                stacklevel=2,
            )
        best = best.drop("__diff__")
        unscheduled = _unscheduled_visits(df, crossed, best, verb, tv_slim)
        best = pl.concat([best, unscheduled], how="vertical_relaxed").rename(
            {"__tv_num__": target_num, "__tv_name__": target_name}
        )

        df = (
            df.join(best, on="__row_idx__", how="left")
            .sort("__row_idx__")
            .drop("__row_idx__", "__actual_dy__")
        )
        _warn_visit_map(df, verb, target_num, unscheduled.height)
        return self._materialise_then(df)  # type: ignore[attr-defined]

    def _visit_map_study_day(
        self, df: pl.DataFrame, verb: str, date_col: str, ref_date: str | None
    ) -> pl.Series:
        """The study day of each row, with no Day 0, from *ref_date* or VISITDY."""
        if ref_date is None:
            if "VISITDY" not in df.columns:
                raise DerivationError(
                    f"{verb}: with ref_date=None the study day is read from a VISITDY column, "
                    "and the frame has none. Pass ref_date= (for example RFSTDTC)."
                )
            return df["VISITDY"]
        if date_col not in df.columns:
            raise DerivationError(f"{verb}: date_col '{date_col}' is not a column of the frame.")
        ref = df
        if ref_date not in df.columns:
            pin = getattr(self, "_STUDY_DAY_REF_PIN", "DM").upper()
            pinned = getattr(self, "_pinned", {})
            if pin not in pinned or ref_date not in pinned[pin][0].columns:
                raise DerivationError(
                    f"{verb}: ref_date '{ref_date}' is not a column of the frame, and no "
                    f'pinned {pin} holds it. Check the name, or add .pin("{pin}", dm).'
                )
            key = self._pin_join_key(pin)  # type: ignore[attr-defined]
            source = self._require_pin(pin, "visit_map", columns=[ref_date])  # type: ignore[attr-defined]
            ref = df.join(
                source.select(*key, ref_date).unique(subset=key, keep="first"),
                on=key,
                how="left",
                nulls_equal=True,
            ).sort("__row_idx__")
        diff = (
            to_day(pl.col(date_col), ref.schema[date_col])
            - to_day(pl.col(ref_date), ref.schema[ref_date])
        ).dt.total_days()
        return ref.select(cdisc_day(diff)).to_series()

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
        of the next element by start date within the subject: the verb
        sorts on the ISO 8601 start text (a null start last, then the row
        order), so the input row order does not matter.  The output keeps
        the input row order.  The last element gets a null end.

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

        # End = next element's start within the subject, in start-date order
        df = self._lazy.collect().with_row_index("__row_idx__")  # type: ignore[attr-defined]
        df = df.with_columns(start_expr)
        df = (
            df.sort(subject_col, target_start, "__row_idx__", nulls_last=True)
            .with_columns(pl.col(target_start).shift(-1).over(subject_col).alias(target_end))
            .sort("__row_idx__")
            .drop("__row_idx__")
        )

        return self._materialise_then(df)  # type: ignore[attr-defined]

    def epoch_assign(
        self,
        target: str,
        *,
        date_col: str,
        epoch_ranges: list[dict[str, str]] | pl.DataFrame | None = None,
        se: pl.DataFrame | pl.LazyFrame | None = None,
        subject_col: str = "USUBJID",
        same_day: Literal["by_class", "earlier", "later"] = "by_class",
    ) -> Self:  # type: ignore[type-var]
        """Assign ``EPOCH`` based on date ranges or per-subject SE intervals.

        With *epoch_ranges*, each entry maps a study-level date interval to
        an ``Epoch`` value; the first matching range wins.  With *se*, the
        subject's own element intervals drive the assignment: for each row,
        the epoch of the SE record whose ``[SESTDTC, SEENDTC]`` interval
        contains the date (SDTMIG 3.4: EPOCH of the start or collection
        date/time).  A blank or null ``SEENDTC`` is open-ended; an element
        whose dates are partial is skipped, with a warning.

        On a transition date, where one element ends and the next starts,
        the time decides when the record and the boundary both have one.
        When one of them has no time, *same_day* decides, and one warning
        gives the count and the rule:

        - ``"by_class"`` (default): a Findings date (``--DTC``) takes the
          earlier element, an Events or Interventions date (``--STDTC``)
          the later one.  Any other *date_col* name raises.
        - ``"earlier"``: the element that ends on that date.
        - ``"later"``: the element that starts on that date.

        No guidance fixes this case, so state the rule in the SDRG.

        Args:
            target: Name of the output ``EPOCH`` column.
            date_col: Column containing the date to classify.
            epoch_ranges: A list of ``{"start": date, "end": date,
                "epoch": str}`` dicts, or a DataFrame with those columns.
            se: An SE domain frame with ``USUBJID``, ``SESTDTC``,
                ``SEENDTC``, and ``EPOCH`` columns.  Mutually exclusive
                with *epoch_ranges*.  EPOCH is Permissible in SE: an SE
                with no EPOCH raises.
            subject_col: Subject key used to join *se* (default
                ``"USUBJID"``).
            same_day: The rule for a record with no time on a transition
                date (with *se* only).

        Returns:
            Self: The namespace with *target* appended.

        Raises:
            ValueError: When neither or both of *epoch_ranges* and *se*
                are provided.
            DerivationError: When ``same_day="by_class"`` and *date_col*
                is neither a ``--DTC`` nor a ``--STDTC`` name, or when *se*
                has no ``EPOCH``.

        Examples:
            Stamp EPOCH onto any domain from the subject's SE intervals::

                ae = (
                    ae_raw.sdtm
                    .assign("USUBJID", source="subject_id")
                    .date("AESTDTC", source="ae_start_date")
                    .epoch_assign("EPOCH", date_col="AESTDTC", se=se)
                    .to_frame()
                )
        """
        if (epoch_ranges is None) == (se is None):
            raise ValueError("epoch_assign() takes exactly one of epoch_ranges= or se=")

        if se is not None:
            rule = _same_day_rule(date_col, same_day)
            df = self._lazy.collect().with_row_index("__row_idx__")  # type: ignore[attr-defined]
            best = _epoch_from_se(df, se, target, date_col, subject_col, rule, same_day)
            out = (
                df.drop(target, strict=False)
                .join(best, on="__row_idx__", how="left")
                .drop("__row_idx__")
            )
            return self._materialise_then(out)  # type: ignore[attr-defined]

        if isinstance(epoch_ranges, pl.DataFrame):
            ranges = epoch_ranges.to_dicts()
        else:
            ranges = epoch_ranges

        if not ranges:
            return self._chain(pl.lit(None).alias(target))  # type: ignore[attr-defined]

        day = to_day(pl.col(date_col), self._lazy.collect_schema().get(date_col))  # type: ignore[attr-defined]
        expr = pl.when(pl.lit(False)).then(pl.lit(None, dtype=pl.String))
        for r in ranges:
            start = date_part(pl.lit(str(r["start"])))
            end = date_part(pl.lit(str(r["end"])))
            expr = expr.when((day >= start) & (day <= end)).then(pl.lit(r["epoch"]))

        final_expr = expr.otherwise(pl.lit(None)).alias(target)
        return self._chain(final_expr)  # type: ignore[attr-defined]

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _materialise_collection(self, df: pl.DataFrame, verb: str) -> Self:  # type: ignore[type-var]
        """Replace the lazy plan with *df*, with STUDYID and DOMAIN first."""
        domain = getattr(self, "_tdd_domain", None)
        expected = _DOMAIN_ADD_VERBS.get(domain or "")
        if expected is not None and expected != verb:
            raise ValueError(
                f"{verb}() does not build {domain}: fetch_structure('{domain}') needs {expected}()."
            )
        # Collect current header columns (STUDYID, DOMAIN)
        current = self._lazy.collect()  # type: ignore[attr-defined]
        header_cols = {}
        for col in ("STUDYID", "DOMAIN"):
            if col in current.columns and current.height > 0:
                header_cols[col] = current[col][0]

        # Broadcast the header onto the collection rows, in SDTMIG column order
        if header_cols:
            df = df.select(
                *[pl.lit(v).alias(k) for k, v in header_cols.items()],
                pl.exclude(*header_cols),
            )

        new = self._materialise_then(df)  # type: ignore[attr-defined]
        new._tdd_stage = 3
        return new  # type: ignore[return-value]

    @staticmethod
    def _fetch_ig_domain(domain: str, ig_version: str) -> dict[str, Any]:
        """Fetch domain metadata from the CDISC Library IG."""
        from fleet.core.rules_scaffolder import normalise_ig_version
        from fleet.ct.api import CDISCClient

        with CDISCClient() as client:
            path = f"/mdr/sdtmig/{normalise_ig_version(ig_version)}/datasets/{domain}"
            detail = client.get(path)

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

    Returns ``None`` when the domain is not in the file, so the caller can
    fall back to the packaged IG structure or the CDISC Library.  The
    caller checks that the file exists.
    """
    data = load_spec_yaml(define_path.read_text(encoding="utf-8"))
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
    "TE": {"STUDYID", "DOMAIN", "ETCD", "ELEMENT", "TESTRL", "TEENRL", "TEDUR"},
    "TA": {
        "STUDYID",
        "DOMAIN",
        "ARMCD",
        "ARM",
        "TAETORD",
        "ETCD",
        "ELEMENT",
        "TABRANCH",
        "TATRANS",
        "EPOCH",
    },
    "TV": {
        "STUDYID",
        "DOMAIN",
        "VISITNUM",
        "VISIT",
        "VISITDY",
        "ARMCD",
        "ARM",
        "TVSTRL",
        "TVENRL",
    },
    "TS": {
        "STUDYID",
        "DOMAIN",
        "TSSEQ",
        "TSGRPID",
        "TSPARMCD",
        "TSPARM",
        "TSVAL",
        "TSVALNF",
        "TSVALCD",
        "TSVCDREF",
        "TSVCDVER",
    },
    "TI": {"STUDYID", "DOMAIN", "IETESTCD", "IETEST", "IECAT", "IESCAT", "TIRL", "TIVERS"},
    "TD": {
        "STUDYID",
        "DOMAIN",
        "TDORDER",
        "TDANCVAR",
        "TDSTOFF",
        "TDTGTPAI",
        "TDMINPAI",
        "TDMAXPAI",
        "TDNUMRPT",
    },
    "TM": {"STUDYID", "DOMAIN", "MIDSTYPE", "TMDEF", "TMRPT"},
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
