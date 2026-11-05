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
import warnings
from enum import Enum, StrEnum
from typing import Annotated, ClassVar, Literal

import polars as pl
from pydantic import BaseModel, ConfigDict, Field, model_validator

# ------------------------------------------------------------------ #
# CT-bound Enum                                                        #
# ------------------------------------------------------------------ #


class Epoch(StrEnum):
    """EPOCH (C99079): the 13 CDISC-standard trial epoch values.

    C99079 is extensible: a sponsor term is accepted as an upper-case string
    (see ``EpochLike``).

    References:
        NCI EVS C99079 (sdtmct-2023-12-15): 13 terms.
    """

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


# Set after the class: inside a StrEnum body it would become a 14th member.
Epoch._concept_id = "C99079"  # type: ignore[attr-defined]


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

    model_config = ConfigDict(extra="forbid")

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

    model_config = ConfigDict(extra="forbid")

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

    model_config = ConfigDict(extra="forbid")

    _SDTM_MAP: ClassVar[dict[str, str]] = {
        "visitnum": "VISITNUM",
        "visit": "VISIT",
        "visitdy": "VISITDY",
        "armcd": "ARMCD",
        "arm": "ARM",
        "tvstrl": "TVSTRL",
        "tvenrl": "TVENRL",
    }

    visitnum: int = Field(ge=1)
    visit: str = Field(min_length=1, max_length=200)
    visitdy: int | None = None
    armcd: ArmCode | Literal[""] = ""
    arm: str = Field(default="", max_length=200)
    tvstrl: RuleExpression = ""
    tvenrl: RuleExpression = ""


class TrialParameter(BaseModel):
    """One row in the TS (Trial Summary) domain."""

    model_config = ConfigDict(extra="forbid")

    _SDTM_MAP: ClassVar[dict[str, str]] = {
        "tsseq": "TSSEQ",
        "tsgrpid": "TSGRPID",
        "tsparmcd": "TSPARMCD",
        "tsparm": "TSPARM",
        "tsval": "TSVAL",
        "tsvalnf": "TSVALNF",
        "tsvalcd": "TSVALCD",
        "tsvcdref": "TSVCDREF",
        "tsvcdver": "TSVCDVER",
    }

    tsseq: int = Field(default=1, ge=1)
    tsgrpid: str = ""
    tsparmcd: str = Field(min_length=1, max_length=8, pattern=r"^[A-Z0-9_]+$")
    tsparm: str = Field(min_length=1, max_length=40)
    tsval: str = ""
    tsvalnf: str = ""
    tsvalcd: str = ""
    tsvcdref: str = ""
    tsvcdver: str = ""


class TrialCriterion(BaseModel):
    """One row in the TI (Trial Inclusion/Exclusion) domain."""

    model_config = ConfigDict(extra="forbid")

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

    model_config = ConfigDict(extra="forbid")

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

    model_config = ConfigDict(extra="forbid")

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


def _split_tsval(text: str, size: int = 200) -> list[str]:
    """Split *text* into pieces of at most *size* characters at a word boundary."""
    pieces: list[str] = []
    while len(text) > size:
        cut = text.rfind(" ", 1, size + 1)
        cut = cut if cut > 0 else size
        pieces.append(text[:cut])
        text = text[cut:]
    pieces.append(text)
    return pieces


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
            window: Allowed deviation in study days (no Day 0, as
                ``visit_map``) — a single int for a symmetric window or a
                ``(before, after)`` tuple.

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
        window_txt = f"; window -{before}/+{after} study days, no Day 0" if window else ""
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
            urllib.error.HTTPError: When the NCT ID is unknown to the registry.

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
        import json
        import urllib.request

        # ponytail: stdlib on purpose — ctgov's WAF 403s httpx's TLS/client
        # fingerprint in some environments while urllib passes.
        req = urllib.request.Request(
            f"https://clinicaltrials.gov/api/v2/studies/{nct_id}",
            headers={
                "User-Agent": "fleet-cdisc (https://github.com/RealSlimMahdi/fleet-cdisc)",
                "Accept": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed https URL
            return cls(parameters=_ctgov_to_parameters(json.load(resp)))

    def to_polars(self) -> pl.DataFrame:
        """Convert validated parameters to a Polars DataFrame with SDTM names.

        A TSVAL over 200 characters is split at a word boundary into TSVAL,
        TSVAL1, ..., TSVALn (SDTMIG 3.4 TS assumption 8).  The space goes to
        the start of the next piece, so the pieces joined give the source
        text.  A word over 200 characters is cut at 200.

        Returns:
            pl.DataFrame: DataFrame with columns named per CDISC SDTM (e.g.
                ``TSPARMCD``, ``TSPARM``, ``TSVAL``).

        Examples:
            Materialise trial summary parameters::

                ts = TrialParameters(parameters=[...])
                df = ts.to_polars()
        """
        df = _rows_to_polars(self.parameters)
        pieces = [_split_tsval(p.tsval) for p in self.parameters]
        width = max((len(p) for p in pieces), default=1)
        if width == 1:
            return df
        split = pl.DataFrame(
            {
                ("TSVAL" if i == 0 else f"TSVAL{i}"): [p[i] if i < len(p) else "" for p in pieces]
                for i in range(width)
            }
        )
        at = df.columns.index("TSVAL")
        return df.select(df.columns[:at]).hstack(split).hstack(df.select(df.columns[at + 1 :]))


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
    enrollment = design.get("enrollmentInfo", {})
    # C66738: PLANSUB is the planned count, ACTSUB the enrolled count; no type, no row.
    enrollment_parm = {
        "ESTIMATED": ("PLANSUB", "Planned Number of Subjects"),
        "ACTUAL": ("ACTSUB", "Actual Number of Subjects"),
    }.get(enrollment.get("type", ""))
    if enrollment_parm:
        add(*enrollment_parm, enrollment.get("count"))
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

# Every non-blank line of the diagram must fully match one of these forms.
_HEADER_RE = re.compile(r"(?:flowchart|graph)\s+(?:TD|TB|BT|LR|RL)", re.IGNORECASE)
_SUBGRAPH_RE = re.compile(r"subgraph\s+(\w+)\s*\[\s*\"?([^\]\"]+?)\"?\s*\]", re.IGNORECASE)
_SUBGRAPH_END_RE = re.compile(r"end", re.IGNORECASE)
_NODE_RE = re.compile(r"(\w+)\[\"([^\"]+?)(?:<br\s*/?>\s*(\S+))?\"\]")
_EDGE_RE = re.compile(r"(\w+)\s*-->\s*(?:\|([^|]+)\|\s*)?(\w+)")


def _epoch_key(text: str) -> str:
    return re.sub(r"[\s\-]+", " ", text.strip().upper())


def _subgraph_epoch(label: str) -> EpochLike:
    """The C99079 term of a subgraph title, else the title as a sponsor epoch."""
    key = _epoch_key(label)
    for ep in Epoch:
        if _epoch_key(ep.value) == key:
            return ep
    sponsor = label.strip().upper()
    warnings.warn(
        f"parse_trial_design: subgraph title '{label}' is not a C99079 term; it is kept as "
        f"the sponsor epoch '{sponsor}'. C99079 is extensible, so check the spelling.",
        stacklevel=4,
    )
    return sponsor


def _refuse_cycle(out: dict[str, list[tuple[str | None, str]]]) -> None:
    """Raise when the edges hold a cycle (a crossover or a repeated element)."""
    done: set[str] = set()

    def visit(node: str, path: list[str]) -> None:
        if node in path:
            raise ValueError(
                f"parse_trial_design: the path {' -> '.join([*path, node])} is a cycle. A "
                "crossover or a repeated element cannot be read back from a diagram: use YAML."
            )
        if node in done:
            return
        for _, nxt in out[node]:
            visit(nxt, [*path, node])
        done.add(node)

    for node in out:
        visit(node, [])


def _arm_paths(nodes: list[str], edges: list[tuple[str, str | None, str]]) -> dict[str, list[str]]:
    """One path per arm, from the single start node to each end node."""
    out: dict[str, list[tuple[str | None, str]]] = {n: [] for n in nodes}
    incoming = {n: 0 for n in nodes}
    for src, label, dst in edges:
        out[src].append((label, dst))
        incoming[dst] += 1
    _refuse_cycle(out)
    orphans = [n for n in nodes if not out[n] and not incoming[n]]
    if len(nodes) > 1 and orphans:
        raise ValueError(f"parse_trial_design: node(s) {orphans} have no edge")
    for node, nexts in out.items():
        if len(nexts) > 1 and any(label is None for label, _ in nexts):
            raise ValueError(
                f"parse_trial_design: node {node} forks with an unlabelled edge. Label every "
                "edge of a fork with its ARMCD (A -->|ARMCD| B)."
            )
    roots = [n for n in nodes if not incoming[n]]
    if len(roots) != 1:
        raise ValueError(
            f"parse_trial_design: the diagram must have one start node, found {roots or 'none'}"
        )

    paths: list[tuple[list[str], list[str]]] = []

    def walk(node: str, path: list[str], labels: list[str]) -> None:
        path = [*path, node]
        if not out[node]:
            paths.append((path, labels))
        for label, nxt in out[node]:
            walk(nxt, path, [*labels, label] if label else labels)

    walk(roots[0], [], [])
    arms: dict[str, list[str]] = {}
    for path, labels in paths:
        if not labels and len(paths) > 1:
            raise ValueError(f"parse_trial_design: the path {' -> '.join(path)} has no ARMCD label")
        armcd = (labels[-1] if labels else "SCRNARM").upper()[:20]
        if armcd in arms:
            raise ValueError(f"parse_trial_design: two paths give ARMCD '{armcd}'")
        arms[armcd] = path
    return arms


def parse_trial_design(
    mermaid_text: str,
) -> tuple[TrialElements, TrialArms]:
    """Parse a Mermaid flowchart into TE and TA collections.

    Each ``subgraph ID[TITLE]`` is an epoch; each node inside it is an
    element (``ETCD["Element name<br/>P14D"]``); each path from the start
    node to an end node is an arm, named by the last ``|ARMCD|`` label on
    its edges.  A title that is not a C99079 term is kept, upper case, as a
    sponsor epoch, with a warning.  ``%%`` comment lines are skipped.

    The diagram carries ETCD, ELEMENT, TEDUR, EPOCH and the arm paths.  It
    does not carry ARM, TESTRL, TEENRL, TABRANCH or TATRANS, and it cannot
    carry a crossover or an element that repeats in one arm: YAML is the
    lossless round trip.

    Args:
        mermaid_text: A Mermaid ``flowchart TD`` string.

    Returns:
        tuple[TrialElements, TrialArms]: Validated collections ready for
            ``add_elements()`` and ``add_arms()``.

    Raises:
        ValueError: On an empty diagram, a line of an unknown form, a node
            outside a subgraph, an unlabelled fork, a cycle, a node with no
            edge, more than one start node, or two nodes or two arms that
            give the same code.

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
    node_epoch: dict[str, EpochLike] = {}
    node_label: dict[str, str] = {}
    node_dur: dict[str, str] = {}
    edges: list[tuple[str, str | None, str]] = []
    current: EpochLike | None = None

    for raw in mermaid_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("%%") or _HEADER_RE.fullmatch(line):
            continue
        if m := _SUBGRAPH_RE.fullmatch(line):
            current = _subgraph_epoch(m.group(2))
        elif _SUBGRAPH_END_RE.fullmatch(line):
            current = None
        elif m := _NODE_RE.fullmatch(line):
            nid = m.group(1)
            if current is None:
                raise ValueError(f"parse_trial_design: node {nid} is outside every subgraph")
            node_epoch[nid] = current
            node_label[nid] = m.group(2).replace("#quot;", '"')
            if m.group(3):
                node_dur[nid] = m.group(3)
        elif m := _EDGE_RE.fullmatch(line):
            label = m.group(2).strip() if m.group(2) else None
            edges.append((m.group(1), label, m.group(3)))
        else:
            raise ValueError(f"parse_trial_design: cannot read the line {line!r}")

    if not node_label:
        raise ValueError("parse_trial_design: the diagram holds no element node")
    unknown = sorted({n for src, _, dst in edges for n in (src, dst)} - set(node_label))
    if unknown:
        raise ValueError(f"parse_trial_design: edge node(s) {unknown} are not declared")
    etcd = {nid: nid.upper()[:8] for nid in node_label}
    if len(set(etcd.values())) != len(etcd):
        raise ValueError(f"parse_trial_design: node ids give the same ETCD: {sorted(etcd)}")

    arm_paths = _arm_paths(list(node_label), edges)
    te_list = [
        TrialElement(
            etcd=etcd[nid],
            element=node_label[nid],
            tedur=node_dur.get(nid, ""),
            epoch=node_epoch[nid],
        )
        for nid in dict.fromkeys(n for path in arm_paths.values() for n in path)
    ]
    ta_list = [
        TrialArm(
            armcd=armcd,
            arm=armcd.replace("_", " ").title(),
            taetord=order,
            etcd=etcd[nid],
            element=node_label[nid],
            epoch=node_epoch[nid],
        )
        for armcd, path in arm_paths.items()
        for order, nid in enumerate(path, 1)
    ]
    return TrialElements(elements=te_list), TrialArms(arms=ta_list)
