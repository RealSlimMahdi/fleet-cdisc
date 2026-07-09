"""
TLG template registry — single source of truth for catalog metadata.

Each TLG output (ported from the cards-based ``tlg.templates`` package) is
described by a :class:`TemplateMeta` entry.  Names, titles, CDISC
classification, and namespace placement live here as *metadata* so that
renaming, re-classifying, or moving a template between namespaces is a
data edit — never a code move.

The registry is load-bearing: ``TLGBuilder.template(id)`` resolves inline
targets through it, ``fleet.tlg.catalog()`` exposes it as a DataFrame, and
the registry-driven test suite asserts every DONE entry resolves to a
working namespace method.

CDISC general-observation-class grouping (the proposed generalist scheme):
  - ``EVENTS``        — AE, MH, DS, deaths, deviations  (was: ae, mh, ds)
  - ``INTERVENTIONS`` — CM, EX                          (was: cm, ex)
  - ``FINDINGS``      — LB, VS, EG, PK, RS              (was: lb, vs, eg)
  - ``DEMOGRAPHICS``  — DM/ADSL baseline
  - ``DISPOSITION``   — subject disposition/enrollment
  - ``SURVIVAL``      — time-to-event / KM / forest      (deferred: needs stats)
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

import polars as pl

from fleet.core.exceptions import SchemaError

if TYPE_CHECKING:
    from ._specs import TLGSpec

#: Signature every user-registered template function must implement:
#: ``fn(df, *, adsl, spec, groupby) -> ARD`` (a {cards}-compatible
#: long-format DataFrame).
TemplateFunc = Callable[..., pl.DataFrame]


class CDISCClass(str, Enum):  # noqa: UP042
    """Generalist CDISC observation-class buckets for TLG outputs."""

    EVENTS = "events"
    INTERVENTIONS = "interventions"
    FINDINGS = "findings"
    DEMOGRAPHICS = "demographics"
    DISPOSITION = "disposition"
    SURVIVAL = "survival"


class OutputType(str, Enum):  # noqa: UP042
    """TLG output layout: table, listing, or graph."""

    TABLE = "table"
    LISTING = "listing"
    GRAPH = "graph"


class Status(str, Enum):  # noqa: UP042
    """Port status for a template."""

    DONE = "done"
    PLANNED = "planned"
    DEFERRED = "deferred"


@dataclass(frozen=True)
class TemplateMeta:
    """Catalog metadata for one TLG template.

    All display/structure attributes live here so downstream changes
    (rename, re-class, move namespace) are metadata edits only.

    Args:
        id: Stable template id (e.g. ``"aet01"``), matches the source ref.
        title: Human-readable output title.
        cdisc_class: Generalist CDISC class bucket.
        namespace: ``df.tlg`` sub-namespace attribute (e.g. ``"ae"``).
        method: Method name on that namespace producing the ARD.
        output_type: Table / listing / graph.
        domains: ADaM domains required (for fixtures + validation).
        source_ref: Original cards template file (reference only).
        status: Port status.
        func: Standalone template function for user-registered
            templates (``fn(df, *, adsl, spec, groupby) -> ARD``).
            ``None`` for built-ins, which dispatch through
            *namespace*/*method* instead.  Set by
            [`register_template()`][fleet.tlg.register_template].
        spec_cls: Spec model class validating YAML files for this
            template.  ``None`` resolves through the namespace's
            builder spec table (built-ins) or falls back to
            ``SummarySpecBase`` (user templates).
    """

    id: str
    title: str
    cdisc_class: CDISCClass
    namespace: str
    method: str
    output_type: OutputType
    domains: tuple[str, ...]
    source_ref: str
    status: Status = Status.PLANNED
    func: TemplateFunc | None = dataclasses.field(default=None, repr=False, compare=False)
    spec_cls: type[TLGSpec] | None = dataclasses.field(default=None, repr=False, compare=False)


#: The proof-set registry (one core template per domain).  Expand by
#: appending entries — methods reference these by ``id``.
TEMPLATES: dict[str, TemplateMeta] = {
    "aet01": TemplateMeta(
        id="aet01",
        title="Overview of Adverse Events",
        cdisc_class=CDISCClass.EVENTS,
        namespace="ae",
        method="t_overview",
        output_type=OutputType.TABLE,
        domains=("ADSL", "ADAE"),
        source_ref="template_gdsr_aet01.R",
        status=Status.DONE,
    ),
    "ael01": TemplateMeta(
        id="ael01",
        title="Listing of Adverse Events",
        cdisc_class=CDISCClass.EVENTS,
        namespace="ae",
        method="l_listing",
        output_type=OutputType.LISTING,
        domains=("ADAE",),
        source_ref="template_gdsr_ael01.R",
        status=Status.DONE,
    ),
    "vst01": TemplateMeta(
        id="vst01",
        title="Vital Signs Summary",
        cdisc_class=CDISCClass.FINDINGS,
        namespace="vs",
        method="t_summary",
        output_type=OutputType.TABLE,
        domains=("ADSL", "ADVS"),
        source_ref="template_gdsr_vst01.R",
        status=Status.DONE,
    ),
    "cmt01a": TemplateMeta(
        id="cmt01a",
        title="Concomitant Medications by Class",
        cdisc_class=CDISCClass.INTERVENTIONS,
        namespace="cm",
        method="t_summary",
        output_type=OutputType.TABLE,
        domains=("ADSL", "ADCM"),
        source_ref="template_gdsr_cmt01a.R",
        status=Status.DONE,
    ),
    "ext01": TemplateMeta(
        id="ext01",
        title="Exposure Summary",
        cdisc_class=CDISCClass.INTERVENTIONS,
        namespace="ex",
        method="t_summary",
        output_type=OutputType.TABLE,
        domains=("ADSL", "ADEX"),
        source_ref="template_gdsr_ext01.R",
        status=Status.DONE,
    ),
    "dmt01": TemplateMeta(
        id="dmt01",
        title="Demographic Characteristics",
        cdisc_class=CDISCClass.DEMOGRAPHICS,
        namespace="dm",
        method="t_summary",
        output_type=OutputType.TABLE,
        domains=("ADSL",),
        source_ref="template_gdsr_dmt01.R",
        status=Status.DONE,
    ),
    "dst01": TemplateMeta(
        id="dst01",
        title="Subject Disposition",
        cdisc_class=CDISCClass.DISPOSITION,
        namespace="ds",
        method="t_summary",
        output_type=OutputType.TABLE,
        domains=("ADSL",),
        source_ref="template_gdsr_dst01.R",
        status=Status.DONE,
    ),
    "dtht01": TemplateMeta(
        id="dtht01",
        title="Deaths Summary",
        cdisc_class=CDISCClass.EVENTS,
        namespace="ds",
        method="t_deaths",
        output_type=OutputType.TABLE,
        domains=("ADSL",),
        source_ref="template_gdsr_dtht01.R",
        status=Status.DONE,
    ),
    "egt01": TemplateMeta(
        id="egt01",
        title="ECG Summary",
        cdisc_class=CDISCClass.FINDINGS,
        namespace="eg",
        method="t_summary",
        output_type=OutputType.TABLE,
        domains=("ADSL", "ADEG"),
        source_ref="template_gdsr_egt01.R",
        status=Status.DONE,
    ),
    "ent01": TemplateMeta(
        id="ent01",
        title="Enrollment by Site",
        cdisc_class=CDISCClass.DISPOSITION,
        namespace="ds",
        method="t_enrollment",
        output_type=OutputType.TABLE,
        domains=("ADSL",),
        source_ref="template_gdsr_ent01.R",
        status=Status.DONE,
    ),
    "lbt01": TemplateMeta(
        id="lbt01",
        title="Laboratory Results Summary",
        cdisc_class=CDISCClass.FINDINGS,
        namespace="lb",
        method="t_summary",
        output_type=OutputType.TABLE,
        domains=("ADSL", "ADLB"),
        source_ref="template_gdsr_lbt01.R",
        status=Status.DONE,
    ),
    "lbl01": TemplateMeta(
        id="lbl01",
        title="Listing of Laboratory Abnormalities",
        cdisc_class=CDISCClass.FINDINGS,
        namespace="lb",
        method="l_listing",
        output_type=OutputType.LISTING,
        domains=("ADLB",),
        source_ref="template_gdsr_lbl01.R",
        status=Status.DONE,
    ),
    "mht01": TemplateMeta(
        id="mht01",
        title="Medical History",
        cdisc_class=CDISCClass.EVENTS,
        namespace="mh",
        method="t_summary",
        output_type=OutputType.TABLE,
        domains=("ADSL", "ADMH"),
        source_ref="template_gdsr_mht01.R",
        status=Status.DONE,
    ),
    "pdt01": TemplateMeta(
        id="pdt01",
        title="Protocol Deviations",
        cdisc_class=CDISCClass.DISPOSITION,
        namespace="ds",
        method="t_deviations",
        output_type=OutputType.TABLE,
        domains=("ADSL", "ADDV"),
        source_ref="template_gdsr_pdt01.R",
        status=Status.DONE,
    ),
    "aet02": TemplateMeta(
        "aet02",
        "AEs by SOC and PT",
        CDISCClass.EVENTS,
        "ae",
        "t_soc_pt",
        OutputType.TABLE,
        ("ADSL", "ADAE"),
        "template_gdsr_aet02.R",
        Status.DONE,
    ),
    "aet03": TemplateMeta(
        "aet03",
        "AEs by Greatest Severity",
        CDISCClass.EVENTS,
        "ae",
        "t_severity",
        OutputType.TABLE,
        ("ADSL", "ADAE"),
        "template_gdsr_aet03.R",
        Status.DONE,
    ),
    "aet04": TemplateMeta(
        "aet04",
        "Adverse Events by Highest NCI CTCAE Grade",
        CDISCClass.EVENTS,
        "ae",
        "t_grade",
        OutputType.TABLE,
        ("ADSL", "ADAE"),
        "template_gdsr_aet04.R",
        Status.DONE,
    ),
    "lbt02": TemplateMeta(
        "lbt02",
        "Lab Mean Change from Baseline",
        CDISCClass.FINDINGS,
        "lb",
        "t_chg",
        OutputType.TABLE,
        ("ADSL", "ADLB"),
        "template_gdsr_lbt02.R",
        Status.DONE,
    ),
    "lbt03": TemplateMeta(
        "lbt03",
        "Lab Shift Table",
        CDISCClass.FINDINGS,
        "lb",
        "t_shift",
        OutputType.TABLE,
        ("ADSL", "ADLB"),
        "template_gdsr_lbt03.R",
        Status.DONE,
    ),
    "lbt04": TemplateMeta(
        "lbt04",
        "Lab Abnormalities",
        CDISCClass.FINDINGS,
        "lb",
        "t_abnormal",
        OutputType.TABLE,
        ("ADSL", "ADLB"),
        "template_gdsr_lbt04.R",
        Status.DONE,
    ),
    "egt03": TemplateMeta(
        "egt03",
        "ECG Change from Baseline",
        CDISCClass.FINDINGS,
        "eg",
        "t_chg",
        OutputType.TABLE,
        ("ADSL", "ADEG"),
        "template_gdsr_egt03.R",
        Status.DONE,
    ),
    "egt05": TemplateMeta(
        "egt05",
        "QTc Category Counts",
        CDISCClass.FINDINGS,
        "eg",
        "t_qtcat",
        OutputType.TABLE,
        ("ADSL", "ADEG"),
        "template_gdsr_egt05_qtcat.R",
        Status.DONE,
    ),
    "cmt02": TemplateMeta(
        "cmt02",
        "Concomitant Meds by PT",
        CDISCClass.INTERVENTIONS,
        "cm",
        "t_by_pt",
        OutputType.TABLE,
        ("ADSL", "ADCM"),
        "template_gdsr_cmt02_pt.R",
        Status.DONE,
    ),
    "aet05": TemplateMeta(
        "aet05",
        "AEs by SOC and Relationship to Study Drug",
        CDISCClass.EVENTS,
        "ae",
        "t_relationship",
        OutputType.TABLE,
        ("ADSL", "ADAE"),
        "template_gdsr_aet05.R",
        Status.DONE,
    ),
}


def get(template_id: str) -> TemplateMeta:
    """Return the registry entry for *template_id*.

    Args:
        template_id: Stable template id (e.g. ``"aet01"``).

    Returns:
        TemplateMeta: The catalog metadata entry.

    Raises:
        KeyError: If *template_id* is not registered.

    Examples:
        Look up a built-in template's metadata::

            import fleet.tlg as tlg

            meta = tlg.get("aet01")
            print(meta.title, meta.domains)
    """
    return TEMPLATES[template_id]


def register_template(meta: TemplateMeta, fn: TemplateFunc) -> TemplateMeta:
    """Register a user-defined TLG template without touching Fleet source.

    The template becomes a first-class citizen: it appears in
    :func:`catalog`, resolves through :func:`get`, is reachable from the
    inline builder via ``.template(meta.id)``, and executes from a YAML
    spec through [`run_spec()`][fleet.tlg.run_spec].

    Args:
        meta: Catalog metadata for the template.  Set ``meta.spec_cls``
            to a custom spec model to control which YAML fields the
            template accepts (defaults to ``SummarySpecBase``).
        fn: Template function with signature
            ``fn(df, *, adsl, spec, groupby) -> ARD`` returning a
            {cards}-compatible long-format DataFrame.

    Returns:
        TemplateMeta: The stored registry entry (*meta* with ``func``
            attached).

    Raises:
        SchemaError: If ``meta.id`` is already registered or *fn* is not
            callable.

    Examples:
        Register and run a sponsor shell::

            import fleet.tlg as tlg

            def my_shell(df, *, adsl, spec, groupby):
                return df.tlg.ae.t_summary(groupby=groupby, adsl=adsl, spec=spec)

            tlg.register_template(
                tlg.TemplateMeta(
                    id="spon01", title="Sponsor AE Shell",
                    cdisc_class=tlg.CDISCClass.EVENTS, namespace="ae",
                    method="my_shell", output_type=tlg.OutputType.TABLE,
                    domains=("ADSL", "ADAE"), source_ref="sponsor",
                    status=tlg.Status.DONE,
                ),
                my_shell,
            )
            ard = adae.tlg.ae.population(adsl).by("TRTA").template("spon01").to_ard()
    """
    if meta.id in TEMPLATES:
        raise SchemaError(
            f"Template id {meta.id!r} is already registered "
            f"({TEMPLATES[meta.id].title!r}). Template ids are stable "
            "identifiers — pick a new id or unregister_template() first."
        )
    if not callable(fn):
        raise SchemaError(f"Template function for {meta.id!r} must be callable, got {fn!r}.")
    entry = dataclasses.replace(meta, func=fn)
    TEMPLATES[meta.id] = entry
    return entry


def unregister_template(template_id: str) -> None:
    """Remove a user-registered template from the registry.

    Only templates added via :func:`register_template` can be removed —
    built-ins are load-bearing (goldens, tests, docs) and stay.

    Args:
        template_id: Id of the user-registered template.

    Returns:
        None.

    Raises:
        SchemaError: If the id is unknown or belongs to a built-in.

    Examples:
        Remove a sponsor template after a run::

            import fleet.tlg as tlg

            tlg.unregister_template("spon01")
    """
    meta = TEMPLATES.get(template_id)
    if meta is None:
        raise SchemaError(f"Unknown template id {template_id!r}. Known ids: {sorted(TEMPLATES)}")
    if meta.func is None:
        raise SchemaError(f"Template {template_id!r} is a Fleet built-in and cannot be removed.")
    del TEMPLATES[template_id]


def by_class(cdisc_class: CDISCClass) -> list[TemplateMeta]:
    """Return all registered templates for a CDISC class.

    Args:
        cdisc_class: The CDISC dataset class to filter on.

    Returns:
        list[TemplateMeta]: Matching catalog entries.

    Examples:
        List every Events-class template::

            import fleet.tlg as tlg

            for meta in tlg.by_class(tlg.CDISCClass.EVENTS):
                print(meta.id, meta.title)
    """
    return [t for t in TEMPLATES.values() if t.cdisc_class == cdisc_class]


def by_namespace(namespace: str) -> list[TemplateMeta]:
    """Return all registered templates for a ``df.tlg`` sub-namespace.

    Args:
        namespace: Sub-namespace attribute name (e.g. ``"ae"``).

    Returns:
        list[TemplateMeta]: Matching catalog entries.

    Examples:
        List the AE templates::

            import fleet.tlg as tlg

            for meta in tlg.by_namespace("ae"):
                print(meta.id, meta.title)
    """
    return [t for t in TEMPLATES.values() if t.namespace == namespace]


def catalog() -> pl.DataFrame:
    """Return the template catalog as a DataFrame (one row per template).

    Returns:
        pl.DataFrame: Columns ``id``, ``title``, ``cdisc_class``,
            ``namespace``, ``method``, ``output_type``, ``domains``,
            ``source_ref``, ``status``.

    Examples:
        ``fleet.tlg.catalog().filter(pl.col("status") == "done")``
    """
    return pl.DataFrame(
        [
            {
                "id": m.id,
                "title": m.title,
                "cdisc_class": m.cdisc_class.value,
                "namespace": m.namespace,
                "method": m.method,
                "output_type": m.output_type.value,
                "domains": list(m.domains),
                "source_ref": m.source_ref,
                "status": m.status.value,
            }
            for m in TEMPLATES.values()
        ]
    )
