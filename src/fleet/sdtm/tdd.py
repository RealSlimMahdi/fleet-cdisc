"""Trial Design Domain (TDD) Pydantic models.

Provides row models, collection models, constrained types, and an ``Epoch``
enum for the CDISC Trial Design domains: TE, TA, TV, TS, TI, TD, TM
(protocol-reference) and SV, SE (subject-level).

Each **row model** maps one record in the target SDTM domain and carries a
``_SDTM_MAP`` that translates Python-friendly field names to official CDISC
variable names.

Each **collection model** wraps a list of row models and enforces integrity
constraints (uniqueness, ordering, FK references) at construction time via
Pydantic ``@model_validator``.  The ``to_polars()`` method converts the
validated collection into a ``pl.DataFrame`` with CDISC column names.

Usage::

    from fleet.sdtm.tdd import TrialElement, TrialElements, Epoch

    te = TrialElements(elements=[
        TrialElement(etcd="SCRN", element="Screening",
                     tedur="P14D", epoch=Epoch.SCREENING),
        TrialElement(etcd="TRT", element="Treatment",
                     tedur="P84D", epoch=Epoch.TREATMENT),
    ])
    df = te.to_polars()
"""

from __future__ import annotations

import re
from enum import Enum, StrEnum
from typing import Annotated, ClassVar, Literal

import polars as pl
from pydantic import BaseModel, Field, model_validator

# ------------------------------------------------------------------ #
# CT-bound Enum                                                        #
# ------------------------------------------------------------------ #


class Epoch(StrEnum):
    """EPOCH (C99079) — all 14 CDISC-standard trial epoch values."""

    SCREENING = "SCREENING"
    BASELINE = "BASELINE"
    RUN_IN = "RUN-IN"
    WASHOUT = "WASHOUT"
    TREATMENT = "TREATMENT"
    BLINDED_TREATMENT = "BLINDED TREATMENT"
    OPEN_LABEL_TREATMENT = "OPEN LABEL TREATMENT"
    CONTINUATION_TREATMENT = "CONTINUATION TREATMENT"
    INDUCTION_TREATMENT = "INDUCTION TREATMENT"
    FOLLOW_UP = "FOLLOW-UP"
    LONG_TERM_FOLLOW_UP = "LONG-TERM FOLLOW-UP"
    OBSERVATION = "OBSERVATION"
    PRE_SCREENING = "PRE-SCREENING"

    _concept_id: ClassVar[str] = "C99079"


# ------------------------------------------------------------------ #
# Constrained types                                                    #
# ------------------------------------------------------------------ #

# C99079 is an extensible codelist: accept the standard Epoch enum first,
# then any sponsor-defined term in CT casing (upper-case words).
EpochLike = Epoch | Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[A-Z0-9 /()\-]+$")]

ElementCode = Annotated[
    str,
    Field(min_length=1, max_length=8, pattern=r"^[A-Z0-9_]+$"),
]
ArmCode = Annotated[
    str,
    Field(min_length=1, max_length=20, pattern=r"^[A-Z0-9_]+$"),
]
ISODuration = Annotated[
    str,
    Field(pattern=r"^P(?:\d+Y)?(?:\d+M)?(?:\d+W)?(?:\d+D)?(?:T(?:\d+H)?(?:\d+M)?(?:\d+S)?)?$"),
]
RuleExpression = Annotated[str, Field(max_length=2000)]


# ------------------------------------------------------------------ #
# Row models                                                           #
# ------------------------------------------------------------------ #


class TrialElement(BaseModel):
    """One row in the TE (Trial Elements) domain.

    ``epoch`` is a design-time attribute: SDTMIG 3.4 has no EPOCH variable
    in TE, so it is excluded from ``to_polars()`` output — but it drives the
    element→epoch mapping used when deriving TA and SE.
    """

    _SDTM_MAP: ClassVar[dict[str, str]] = {
        "etcd": "ETCD",
        "element": "ELEMENT",
        "testrl": "TESTRL",
        "teenrl": "TEENRL",
        "tedur": "TEDUR",
    }

    etcd: ElementCode
    element: str = Field(min_length=1, max_length=200)
    testrl: RuleExpression = ""
    teenrl: RuleExpression = ""
    tedur: ISODuration | Literal[""] = ""
    epoch: EpochLike


class TrialArm(BaseModel):
    """One row-per-element in the TA (Trial Arms) domain."""

    _SDTM_MAP: ClassVar[dict[str, str]] = {
        "armcd": "ARMCD",
        "arm": "ARM",
        "taetord": "TAETORD",
        "etcd": "ETCD",
        "element": "ELEMENT",
        "tabranch": "TABRANCH",
        "tatrans": "TATRANS",
        "epoch": "EPOCH",
    }

    armcd: ArmCode
    arm: str = Field(min_length=1, max_length=200)
    taetord: int = Field(ge=1)
    etcd: ElementCode
    element: str = Field(min_length=1, max_length=200)
    tabranch: RuleExpression = ""
    tatrans: RuleExpression = ""
    epoch: EpochLike


class TrialVisit(BaseModel):
    """One row in the TV (Trial Visits) domain."""

    _SDTM_MAP: ClassVar[dict[str, str]] = {
        "visitnum": "VISITNUM",
        "visit": "VISIT",
        "visitdy": "VISITDY",
        "armcd": "ARMCD",
        "tvstrl": "TVSTRL",
        "tvenrl": "TVENRL",
    }

    visitnum: int = Field(ge=1)
    visit: str = Field(min_length=1, max_length=200)
    visitdy: int | None = None
    armcd: ArmCode | Literal[""] = ""
    tvstrl: RuleExpression = ""
    tvenrl: RuleExpression = ""


class TrialParameter(BaseModel):
    """One row in the TS (Trial Summary) domain."""

    _SDTM_MAP: ClassVar[dict[str, str]] = {
        "tsseq": "TSSEQ",
        "tsparmcd": "TSPARMCD",
        "tsparm": "TSPARM",
        "tsval": "TSVAL",
        "tsvalnf": "TSVALNF",
        "tsvalcd": "TSVALCD",
        "tsvcdref": "TSVCDREF",
        "tsvcdver": "TSVCDVER",
    }

    tsseq: int = Field(default=1, ge=1)
    tsparmcd: str = Field(min_length=1, max_length=8, pattern=r"^[A-Z0-9_]+$")
    tsparm: str = Field(min_length=1, max_length=200)
    tsval: str = ""
    tsvalnf: str = ""
    tsvalcd: str = ""
    tsvcdref: str = ""
    tsvcdver: str = ""


class TrialCriterion(BaseModel):
    """One row in the TI (Trial Inclusion/Exclusion) domain."""

    _SDTM_MAP: ClassVar[dict[str, str]] = {
        "ietestcd": "IETESTCD",
        "ietest": "IETEST",
        "iecat": "IECAT",
        "iescat": "IESCAT",
        "tirl": "TIRL",
        "tivers": "TIVERS",
    }

    ietestcd: str = Field(min_length=1, max_length=8, pattern=r"^[A-Z0-9_]+$")
    ietest: str = Field(min_length=1, max_length=200)
    iecat: Literal["INCLUSION", "EXCLUSION"]
    iescat: str = ""
    tirl: RuleExpression = ""
    tivers: str = ""


class TrialDiseaseAssessment(BaseModel):
    """One row in the TD (Trial Disease Assessments) domain."""

    _SDTM_MAP: ClassVar[dict[str, str]] = {
        "tdorder": "TDORDER",
        "tdancvar": "TDANCVAR",
        "tdstoff": "TDSTOFF",
        "tdtgtpai": "TDTGTPAI",
        "tdminpai": "TDMINPAI",
        "tdmaxpai": "TDMAXPAI",
        "tdnumrpt": "TDNUMRPT",
    }

    tdorder: int = Field(ge=1)
    tdancvar: str = Field(min_length=1, max_length=8)
    tdstoff: ISODuration | Literal[""] = ""
    tdtgtpai: ISODuration
    tdminpai: ISODuration | Literal[""] = ""
    tdmaxpai: ISODuration | Literal[""] = ""
    tdnumrpt: int = Field(ge=1)


class TrialMilestone(BaseModel):
    """One row in the TM (Trial Disease Milestones) domain."""

    _SDTM_MAP: ClassVar[dict[str, str]] = {
        "midstype": "MIDSTYPE",
        "tmdef": "TMDEF",
        "tmrpt": "TMRPT",
    }

    midstype: str = Field(min_length=1, max_length=200)
    tmdef: str = Field(min_length=1, max_length=2000)
    tmrpt: Literal["Y", "N"]


# ------------------------------------------------------------------ #
# Collection models                                                    #
# ------------------------------------------------------------------ #


def _rows_to_polars(rows: list[BaseModel]) -> pl.DataFrame:
    """Convert row models to a DataFrame with CDISC names via ``_SDTM_MAP``."""
    dicts = [
        {
            sdtm: v.value if isinstance(v := getattr(row, field), Enum) else v
            for field, sdtm in type(row)._SDTM_MAP.items()
        }
        for row in rows
    ]
    return pl.DataFrame(dicts)


class TrialElements(BaseModel):
    """Typed collection of TE rows with TDD-specific integrity validation."""

    elements: list[TrialElement]

    @model_validator(mode="after")
    def check_unique_etcd(self) -> TrialElements:
        codes = [e.etcd for e in self.elements]
        dupes = [c for c in codes if codes.count(c) > 1]
        if dupes:
            raise ValueError(f"Duplicate ETCD: {set(dupes)}")
        return self

    @model_validator(mode="after")
    def check_epochs_consistent(self) -> TrialElements:
        mapping: dict[str, Epoch] = {}
        for e in self.elements:
            if e.etcd in mapping and mapping[e.etcd] != e.epoch:
                raise ValueError(f"ETCD {e.etcd} maps to multiple EPOCHs")
            mapping[e.etcd] = e.epoch
        return self

    def to_polars(self) -> pl.DataFrame:
        """Convert validated elements to a Polars DataFrame with SDTM names.

        Returns:
            pl.DataFrame: DataFrame with columns named per CDISC SDTM (e.g.
                ``ETCD``, ``ELEMENT``, ``EPOCH``).

        Examples:
            Materialise trial elements::

                te = TrialElements(elements=[...])
                df = te.to_polars()
        """
        return _rows_to_polars(self.elements)


class TrialArms(BaseModel):
    """Typed collection of TA rows with TDD integrity validation."""

    arms: list[TrialArm]

    @model_validator(mode="after")
    def check_taetord_sequential(self) -> TrialArms:
        by_arm: dict[str, list[int]] = {}
        for a in self.arms:
            by_arm.setdefault(a.armcd, []).append(a.taetord)
        for armcd, orders in by_arm.items():
            expected = list(range(1, len(orders) + 1))
            if sorted(orders) != expected:
                raise ValueError(
                    f"TAETORD for {armcd} must be sequential 1..N, got {sorted(orders)}"
                )
        return self

    def to_polars(self) -> pl.DataFrame:
        """Convert validated arms to a Polars DataFrame with SDTM names.

        Returns:
            pl.DataFrame: DataFrame with columns named per CDISC SDTM (e.g.
                ``ARMCD``, ``ARM``, ``TAETORD``, ``ETCD``).

        Examples:
            Materialise trial arms::

                ta = TrialArms(arms=[...])
                df = ta.to_polars()
        """
        return _rows_to_polars(self.arms)


class TrialVisits(BaseModel):
    """Typed collection of TV rows with TDD integrity validation."""

    visits: list[TrialVisit]

    @model_validator(mode="after")
    def check_visitnum_unique(self) -> TrialVisits:
        nums = [v.visitnum for v in self.visits]
        if len(nums) != len(set(nums)):
            raise ValueError("Duplicate VISITNUM values")
        return self

    @model_validator(mode="after")
    def check_visitdy_ordering(self) -> TrialVisits:
        sorted_visits = sorted(self.visits, key=lambda v: v.visitnum)
        days = [v.visitdy for v in sorted_visits if v.visitdy is not None]
        if days != sorted(days):
            raise ValueError("VISITDY must increase with VISITNUM")
        return self

    @classmethod
    def from_schedule(
        cls,
        schedule: list[tuple[str, int]],
        *,
        anchor: str = "RANDOMIZATION",
        window: int | tuple[int, int] | None = None,
    ) -> TrialVisits:
        """Build a visit schedule from day offsets relative to an anchor event.

        Visits are sorted by offset; ``VISITNUM`` is assigned 1..N in that
        order and ``VISITDY`` follows the CDISC no-day-zero convention
        (offset 0 → day 1, negative offsets stay negative).  ``TVSTRL`` is
        rendered deterministically from the offset, anchor, and window, so
        rule text stays consistent across visits and study amendments.

        Args:
            schedule: ``(visit_name, day_offset)`` pairs; offsets are days
                relative to the *anchor* event (day 0).
            anchor: Name of the anchoring milestone (e.g. ``"RANDOMIZATION"``).
            window: Allowed deviation in days — a single int for a symmetric
                window or a ``(before, after)`` tuple.

        Returns:
            TrialVisits: A validated collection ready for ``add_visits()``.

        Examples:
            Build a 12-week schedule anchored on randomization::

                tv_rows = TrialVisits.from_schedule(
                    [("Screening", -14), ("Baseline", 0), ("Week 4", 28),
                     ("Week 8", 56), ("Week 12", 84)],
                    anchor="RANDOMIZATION",
                    window=3,
                )
                tv = (
                    fleet.frame(pl.DataFrame()).sdtm
                    .fetch_structure("TV")
                    .study_header("CDISCPILOT01", "TV")
                    .add_visits(tv_rows)
                    .to_frame()
                )
        """
        before, after = (window, window) if isinstance(window, int) else (window or (0, 0))
        window_txt = f"; window -{before}/+{after} days" if window else ""
        visits = []
        for num, (name, offset) in enumerate(sorted(schedule, key=lambda p: p[1]), start=1):
            if offset == 0:
                rule = f"On day of {anchor}"
            elif offset > 0:
                rule = f"{offset} days after {anchor}"
            else:
                rule = f"{-offset} days before {anchor}"
            visits.append(
                TrialVisit(
                    visitnum=num,
                    visit=name,
                    visitdy=offset + 1 if offset >= 0 else offset,
                    tvstrl=rule + window_txt,
                )
            )
        return cls(visits=visits)

    def to_polars(self) -> pl.DataFrame:
        """Convert validated visits to a Polars DataFrame with SDTM names.

        Returns:
            pl.DataFrame: DataFrame with columns named per CDISC SDTM (e.g.
                ``VISITNUM``, ``VISIT``, ``VISITDY``).

        Examples:
            Materialise trial visits::

                tv = TrialVisits(visits=[...])
                df = tv.to_polars()
        """
        return _rows_to_polars(self.visits)


class TrialParameters(BaseModel):
    """Typed collection of TS rows."""

    parameters: list[TrialParameter]

    @model_validator(mode="after")
    def check_unique_tsparmcd(self) -> TrialParameters:
        keys = [(p.tsparmcd, p.tsseq) for p in self.parameters]
        if len(keys) != len(set(keys)):
            dupes = {k for k in keys if keys.count(k) > 1}
            raise ValueError(f"Duplicate (TSPARMCD, TSSEQ) pairs: {sorted(dupes)}")
        return self

    @classmethod
    def from_ctgov(cls, nct_id: str, *, timeout: float = 30.0) -> TrialParameters:
        """Seed TS parameters from a ClinicalTrials.gov registration.

        Fetches the study record from the ClinicalTrials.gov v2 JSON API and
        maps the cleanly-derivable fields to TS parameters.  The result is a
        **starting point**, not a submission-ready TS: dictionary-bound
        parameters (INDIC/SNOMED, TRT/UNII, PCLAS/MED-RT) are deliberately
        not guessed and must be added by the study team.

        Args:
            nct_id: ClinicalTrials.gov identifier (e.g. ``"NCT01234567"``).
            timeout: HTTP timeout in seconds.

        Returns:
            TrialParameters: Collection with one row per derivable parameter
                (repeating parameters such as FCNTRY get incrementing TSSEQ).

        Raises:
            httpx.HTTPStatusError: When the NCT ID is unknown to the registry.

        Examples:
            Seed TS from the registry, then extend and build::

                ts_rows = TrialParameters.from_ctgov("NCT00048217")
                ts = (
                    fleet.frame(pl.DataFrame()).sdtm
                    .fetch_structure("TS")
                    .study_header("CDISCPILOT01", "TS")
                    .add_parameters(ts_rows)
                    .to_frame()
                )
        """
        import httpx

        resp = httpx.get(
            f"https://clinicaltrials.gov/api/v2/studies/{nct_id}",
            timeout=timeout,
            follow_redirects=True,
        )
        resp.raise_for_status()
        return cls(parameters=_ctgov_to_parameters(resp.json()))

    def to_polars(self) -> pl.DataFrame:
        """Convert validated parameters to a Polars DataFrame with SDTM names.

        Returns:
            pl.DataFrame: DataFrame with columns named per CDISC SDTM (e.g.
                ``TSPARMCD``, ``TSPARM``, ``TSVAL``).

        Examples:
            Materialise trial summary parameters::

                ts = TrialParameters(parameters=[...])
                df = ts.to_polars()
        """
        return _rows_to_polars(self.parameters)


class TrialCriteria(BaseModel):
    """Typed collection of TI rows."""

    criteria: list[TrialCriterion]

    @model_validator(mode="after")
    def check_unique_ietestcd(self) -> TrialCriteria:
        codes = [c.ietestcd for c in self.criteria]
        if len(codes) != len(set(codes)):
            raise ValueError("Duplicate IETESTCD values")
        return self

    def to_polars(self) -> pl.DataFrame:
        """Convert validated criteria to a Polars DataFrame with SDTM names.

        Returns:
            pl.DataFrame: DataFrame with columns named per CDISC SDTM (e.g.
                ``IETESTCD``, ``IETEST``, ``IECAT``).

        Examples:
            Materialise trial criteria::

                ti = TrialCriteria(criteria=[...])
                df = ti.to_polars()
        """
        return _rows_to_polars(self.criteria)


class TrialDiseaseAssessments(BaseModel):
    """Typed collection of TD rows."""

    assessments: list[TrialDiseaseAssessment]

    @model_validator(mode="after")
    def check_unique_tdorder(self) -> TrialDiseaseAssessments:
        orders = [a.tdorder for a in self.assessments]
        if len(orders) != len(set(orders)):
            raise ValueError("Duplicate TDORDER values")
        return self

    def to_polars(self) -> pl.DataFrame:
        """Convert validated assessments to a Polars DataFrame with SDTM names.

        Returns:
            pl.DataFrame: DataFrame with columns named per CDISC SDTM (e.g.
                ``TDORDER``, ``TDANCVAR``, ``TDTGTPAI``).

        Examples:
            Materialise trial disease assessments::

                td = TrialDiseaseAssessments(assessments=[...])
                df = td.to_polars()
        """
        return _rows_to_polars(self.assessments)


class TrialMilestones(BaseModel):
    """Typed collection of TM rows."""

    milestones: list[TrialMilestone]

    @model_validator(mode="after")
    def check_unique_midstype(self) -> TrialMilestones:
        types = [m.midstype for m in self.milestones]
        if len(types) != len(set(types)):
            raise ValueError("Duplicate MIDSTYPE values")
        return self

    def to_polars(self) -> pl.DataFrame:
        """Convert validated milestones to a Polars DataFrame with SDTM names.

        Returns:
            pl.DataFrame: DataFrame with columns named per CDISC SDTM (e.g.
                ``MIDSTYPE``, ``TMDEF``, ``TMRPT``).

        Examples:
            Materialise trial disease milestones::

                tm = TrialMilestones(milestones=[...])
                df = tm.to_polars()
        """
        return _rows_to_polars(self.milestones)


# ------------------------------------------------------------------ #
# ClinicalTrials.gov v2 → TS parameters                                #
# ------------------------------------------------------------------ #

# ctgov enum → CDISC C66737 (Trial Phase) submission values
_CTGOV_PHASE = {
    "EARLY_PHASE1": "PHASE 0 TRIAL",
    "PHASE1": "PHASE I TRIAL",
    "PHASE1|PHASE2": "PHASE I/II TRIAL",
    "PHASE2": "PHASE II TRIAL",
    "PHASE2|PHASE3": "PHASE II/III TRIAL",
    "PHASE3": "PHASE III TRIAL",
    "PHASE4": "PHASE IV TRIAL",
    "NA": "NOT APPLICABLE",
}
_CTGOV_MASKING = {"NONE": "OPEN LABEL", "SINGLE": "SINGLE BLIND", "DOUBLE": "DOUBLE BLIND"}
_CTGOV_SEX = {"ALL": "BOTH", "FEMALE": "F", "MALE": "M"}
_CTGOV_AGE_RE = re.compile(r"(\d+)\s*(Year|Month|Week|Day)", re.IGNORECASE)


def _ctgov_age_to_iso(age: str | None) -> str | None:
    """``"50 Years"`` → ``"P50Y"`` (None when unparseable)."""
    m = _CTGOV_AGE_RE.match(age or "")
    return f"P{m.group(1)}{m.group(2)[0].upper()}" if m else None


def _ctgov_to_parameters(study: dict) -> list[TrialParameter]:
    """Map a ClinicalTrials.gov v2 study record to TS parameter rows."""
    proto = study.get("protocolSection", {})
    ident = proto.get("identificationModule", {})
    status = proto.get("statusModule", {})
    design = proto.get("designModule", {})
    design_info = design.get("designInfo", {})
    elig = proto.get("eligibilityModule", {})
    rows: list[TrialParameter] = []

    def add(code: str, name: str, value: object, seq: int = 1) -> None:
        if value not in (None, "", []):
            rows.append(TrialParameter(tsseq=seq, tsparmcd=code, tsparm=name, tsval=str(value)))

    add("REGID", "Registry Identifier", ident.get("nctId"))
    add("TITLE", "Trial Title", ident.get("officialTitle") or ident.get("briefTitle"))
    add("STYPE", "Study Type", design.get("studyType"))
    add(
        "TPHASE", "Trial Phase Classification", _CTGOV_PHASE.get("|".join(design.get("phases", [])))
    )
    add("INTMODEL", "Intervention Model", design_info.get("interventionModel"))
    allocation = design_info.get("allocation")
    if allocation in ("RANDOMIZED", "NON_RANDOMIZED"):
        add("RANDOM", "Trial is Randomized", "Y" if allocation == "RANDOMIZED" else "N")
    masking = design_info.get("maskingInfo", {}).get("masking")
    add("TBLIND", "Trial Blinding Schema", _CTGOV_MASKING.get(masking, masking))
    arms = proto.get("armsInterventionsModule", {}).get("armGroups", [])
    add("NARMS", "Planned Number of Arms", len(arms) or None)
    add("PLANSUB", "Planned Number of Subjects", design.get("enrollmentInfo", {}).get("count"))
    add("AGEMIN", "Planned Minimum Age of Subjects", _ctgov_age_to_iso(elig.get("minimumAge")))
    add("AGEMAX", "Planned Maximum Age of Subjects", _ctgov_age_to_iso(elig.get("maximumAge")))
    add("SEXPOP", "Sex of Participants", _CTGOV_SEX.get(elig.get("sex", "")))
    if isinstance(elig.get("healthyVolunteers"), bool):
        add("HLTSUBJI", "Healthy Subject Indicator", "Y" if elig["healthyVolunteers"] else "N")
    add("SSTDTC", "Study Start Date", status.get("startDateStruct", {}).get("date"))
    if status.get("overallStatus") == "COMPLETED":
        add("SENDTC", "Study End Date", status.get("completionDateStruct", {}).get("date"))
    add(
        "SPONSOR",
        "Clinical Study Sponsor",
        proto.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name"),
    )
    outcomes = proto.get("outcomesModule", {}).get("primaryOutcomes", [])
    for seq, outcome in enumerate(outcomes, start=1):
        add("OUTMSPRI", "Primary Outcome Measure", outcome.get("measure"), seq=seq)
    locations = proto.get("contactsLocationsModule", {}).get("locations", [])
    countries = sorted({loc["country"] for loc in locations if loc.get("country")})
    for seq, country in enumerate(countries, start=1):
        add("FCNTRY", "Planned Country of Investigational Sites", country, seq=seq)
    return rows


# ------------------------------------------------------------------ #
# Mermaid → TA/TE parser                                               #
# ------------------------------------------------------------------ #

# Regex patterns for Mermaid flowchart parsing
_SUBGRAPH_RE = re.compile(r"subgraph\s+(\w+)\s*\[([^\]]+)\]", re.IGNORECASE)
_NODE_RE = re.compile(r"(\w+)\[\"([^\"]+?)(?:<br/>(\S+))?\"\]")
_EDGE_RE = re.compile(r"(\w+)\s*-->(?:\|([^|]+)\|)?\s*(\w+)")
_SUBGRAPH_END_RE = re.compile(r"^\s*end\s*$", re.IGNORECASE)


def parse_trial_design(
    mermaid_text: str,
) -> tuple[TrialElements, TrialArms]:
    """Parse a Mermaid flowchart into TE and TA collections.

    Extracts epochs from ``subgraph`` blocks, elements from node labels,
    and arm assignments from labelled edges.  BFS traversal per arm
    determines ``TAETORD``.

    Handles branching (arm splits), convergence (shared elements), and
    sequential paths.  Duration is extracted from ``<br/>P…`` suffixes in
    node labels.

    Does **not** handle crossover designs, adaptive arms, or
    ``TESTRL``/``TEENRL`` rule expressions.

    Args:
        mermaid_text: A Mermaid ``flowchart TD`` string.

    Returns:
        tuple[TrialElements, TrialArms]: Validated collections ready for
            ``add_elements()`` and ``add_arms()``.

    Examples:
        Parse a simple 3-element design::

            te, ta = parse_trial_design('''
                flowchart TD
                subgraph SCR[SCREENING]
                    SCRN["Screening<br/>P14D"]
                end
                subgraph TRT[TREATMENT]
                    TREAT["Treatment<br/>P84D"]
                end
                subgraph FU[FOLLOW-UP]
                    FOLL["Follow-up<br/>P28D"]
                end
                SCRN --> TREAT
                TREAT --> FOLL
            ''')
    """
    # 1. Parse subgraphs → epoch mapping (node_id → Epoch)
    node_epoch: dict[str, Epoch] = {}
    subgraph_nodes: dict[str, list[str]] = {}

    lines = mermaid_text.strip().splitlines()
    current_subgraph: str | None = None
    epoch_map: dict[str, Epoch] = {}

    for line in lines:
        line_stripped = line.strip()

        sg_match = _SUBGRAPH_RE.search(line_stripped)
        if sg_match:
            sg_id = sg_match.group(1)
            sg_label = sg_match.group(2).strip()
            current_subgraph = sg_id
            subgraph_nodes[sg_id] = []
            # Try to match label to Epoch enum
            try:
                epoch_map[sg_id] = Epoch(sg_label)
            except ValueError:
                # Try normalised form
                for ep in Epoch:
                    if ep.value.replace("-", " ").replace("  ", " ").upper() == sg_label.upper():
                        epoch_map[sg_id] = ep
                        break
            continue

        if _SUBGRAPH_END_RE.match(line_stripped):
            current_subgraph = None
            continue

        node_match = _NODE_RE.search(line_stripped)
        if node_match and current_subgraph:
            node_id = node_match.group(1)
            subgraph_nodes.setdefault(current_subgraph, []).append(node_id)
            if current_subgraph in epoch_map:
                node_epoch[node_id] = epoch_map[current_subgraph]

    # 2. Parse nodes → elements
    node_label: dict[str, str] = {}
    node_dur: dict[str, str] = {}

    for line in lines:
        m = _NODE_RE.search(line.strip())
        if m:
            nid, label, dur = m.group(1), m.group(2), m.group(3)
            node_label[nid] = label
            if dur:
                node_dur[nid] = dur

    # 3. Parse edges (with optional arm labels)
    edges: list[tuple[str, str | None, str]] = []  # (from, arm_label, to)
    for line in lines:
        m = _EDGE_RE.search(line.strip())
        if m:
            src, arm_lbl, dst = m.group(1), m.group(2), m.group(3)
            edges.append((src, arm_lbl.strip() if arm_lbl else None, dst))

    # 4. Build adjacency and discover arms via BFS
    adj: dict[str, list[tuple[str | None, str]]] = {}
    for src, arm_lbl, dst in edges:
        adj.setdefault(src, []).append((arm_lbl, dst))

    # Find root nodes (no incoming edges)
    all_dst = {dst for _, _, dst in edges}
    all_src = {src for src, _, _ in edges}
    roots = all_src - all_dst
    if not roots:
        roots = {edges[0][0]} if edges else set()

    # BFS per arm: discover arm paths
    arm_paths: dict[str, list[str]] = {}

    def _walk(node: str, arm: str, path: list[str], visited: set[str] | None = None) -> None:
        if visited is None:
            visited = set()
        if node in visited:
            arm_paths[arm] = list(path)
            return
        visited.add(node)
        path.append(node)
        neighbors = adj.get(node, [])
        if not neighbors:
            arm_paths[arm] = list(path)
            path.pop()
            return
        for arm_lbl, nxt in neighbors:
            target_arm = arm_lbl if arm_lbl else arm
            _walk(nxt, target_arm, list(path), set(visited))
        if arm not in arm_paths:
            arm_paths[arm] = list(path)

    for root in sorted(roots):
        _walk(root, "DEFAULT", [])

    # If no labelled edges, treat as single-arm
    if len(arm_paths) == 1 and "DEFAULT" in arm_paths:
        arm_paths["SCRNARM"] = arm_paths.pop("DEFAULT")
    # With labelled edges the walk also records the shared pre-branch prefix
    # under "DEFAULT" — that is not a real arm, drop it.
    elif "DEFAULT" in arm_paths:
        del arm_paths["DEFAULT"]

    # 5. Build TrialElements (deduplicated)
    seen_etcd: set[str] = set()
    te_list: list[TrialElement] = []
    for path in arm_paths.values():
        for nid in path:
            etcd = nid.upper()[:8]
            if etcd in seen_etcd:
                continue
            seen_etcd.add(etcd)
            te_list.append(
                TrialElement(
                    etcd=etcd,
                    element=node_label.get(nid, nid),
                    tedur=node_dur.get(nid, ""),
                    epoch=node_epoch.get(nid, Epoch.TREATMENT),
                )
            )

    # 6. Build TrialArms
    ta_list: list[TrialArm] = []
    for armcd, path in arm_paths.items():
        arm_name = armcd.replace("_", " ").title()
        for order, nid in enumerate(path, 1):
            etcd = nid.upper()[:8]
            ta_list.append(
                TrialArm(
                    armcd=armcd.upper()[:20],
                    arm=arm_name,
                    taetord=order,
                    etcd=etcd,
                    element=node_label.get(nid, nid),
                    epoch=node_epoch.get(nid, Epoch.TREATMENT),
                )
            )

    return TrialElements(elements=te_list), TrialArms(arms=ta_list)
