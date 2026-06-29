"""
TLG template registry — single source of truth for catalog metadata.

Each TLG output (ported from the cards-based ``tlg.templates`` package) is
described by a :class:`TemplateMeta` entry.  Names, titles, CDISC
classification, and namespace placement live here as *metadata* so that
renaming, re-classifying, or moving a template between namespaces is a
data edit — never a code move.

Implementation methods are thin wrappers; they reference their template by
``id`` and inherit display/title/class from this registry.  Renders and
the catalog read titles from here, so changing a title in one place
updates everywhere.

CDISC general-observation-class grouping (the proposed generalist scheme):
  - ``EVENTS``        — AE, MH, DS, deaths, deviations  (was: ae, mh, ds)
  - ``INTERVENTIONS`` — CM, EX                          (was: cm, ex)
  - ``FINDINGS``      — LB, VS, EG, PK, RS              (was: lb, vs, eg)
  - ``DEMOGRAPHICS``  — DM/ADSL baseline
  - ``DISPOSITION``   — subject disposition/enrollment
  - ``SURVIVAL``      — time-to-event / KM / forest      (deferred: needs stats)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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


#: The proof-set registry (one core template per domain).  Expand by
#: appending entries — methods reference these by ``id``.
TEMPLATES: dict[str, TemplateMeta] = {
    "aet01": TemplateMeta(
        id="aet01",
        title="Overview of Adverse Events",
        cdisc_class=CDISCClass.EVENTS,
        namespace="ae",
        method="t_summary",
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
    ),
    "dmt01": TemplateMeta(
        id="dmt01",
        title="Demographic Characteristics",
        cdisc_class=CDISCClass.DEMOGRAPHICS,
        namespace="dm",
        method="t_summary",
        output_type=OutputType.TABLE,
        domains=("ADSL", "ADVS"),
        source_ref="template_gdsr_dmt01.R",
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
    ),
    "pdt01": TemplateMeta(
        id="pdt01",
        title="Protocol Deviations",
        cdisc_class=CDISCClass.DISPOSITION,
        namespace="ds",
        method="t_deviations",
        output_type=OutputType.TABLE,
        domains=("ADSL",),
        source_ref="template_gdsr_pdt01.R",
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
        "AEs by Relationship",
        CDISCClass.EVENTS,
        "ae",
        "t_relationship",
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
}


def get(template_id: str) -> TemplateMeta:
    """Return the registry entry for *template_id*.

    Args:
        template_id: Stable template id (e.g. ``"aet01"``).

    Returns:
        TemplateMeta: The catalog metadata entry.

    Raises:
        KeyError: If *template_id* is not registered.
    """
    return TEMPLATES[template_id]


def by_class(cdisc_class: CDISCClass) -> list[TemplateMeta]:
    """Return all registered templates for a CDISC class."""
    return [t for t in TEMPLATES.values() if t.cdisc_class == cdisc_class]


def by_namespace(namespace: str) -> list[TemplateMeta]:
    """Return all registered templates for a ``df.tlg`` sub-namespace."""
    return [t for t in TEMPLATES.values() if t.namespace == namespace]
