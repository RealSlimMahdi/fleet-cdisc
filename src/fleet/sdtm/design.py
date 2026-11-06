"""Study design aggregate — define the trial design once, derive every domain.

``StudyDesign`` is the single typed source of truth for a study's structure:
elements, arms (as ordered element paths), visits, criteria, and summary
parameters.  Every Trial Design domain (TE, TA, TV, TS, TI, TD, TM) is
*derived* from it, so TAETORD ordering, element/epoch duplication across
arms, and cross-domain FK consistency fall out mechanically instead of being
hand-maintained per row.

Usage::

    import fleet

    design = fleet.StudyDesign(
        study_id="CDISCPILOT01",
        elements=[
            {"etcd": "SCRN", "element": "Screening", "tedur": "P14D",
             "epoch": "SCREENING"},
            {"etcd": "TRT", "element": "Treatment", "tedur": "P84D",
             "epoch": "TREATMENT"},
            {"etcd": "FU", "element": "Follow-up", "tedur": "P28D",
             "epoch": "FOLLOW-UP"},
        ],
        arms={"PBO": ["SCRN", "TRT", "FU"], "XAN_LO": ["SCRN", "TRT", "FU"]},
        arm_names={"PBO": "Placebo", "XAN_LO": "Xanomeline Low Dose"},
    )
    ta = design.to_ta()
    frames = design.domains()       # {"TE": df, "TA": df, ...}
    findings = design.audit()       # P21-style conformance pre-check
"""

from __future__ import annotations

import datetime
import html
import re
import warnings
from pathlib import Path
from typing import Any

import polars as pl
import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fleet.sdtm.tdd import (
    ElementCode,
    EpochLike,
    RuleExpression,
    TrialArm,
    TrialArms,
    TrialCriteria,
    TrialCriterion,
    TrialDiseaseAssessment,
    TrialDiseaseAssessments,
    TrialElement,
    TrialElements,
    TrialMilestone,
    TrialMilestones,
    TrialParameter,
    TrialParameters,
    TrialVisit,
    TrialVisits,
    parse_trial_design,
)


def _dates_to_iso(value: Any) -> Any:
    """Recursively turn YAML-parsed date/datetime scalars back into ISO strings.

    YAML parses an unquoted ``2026-01-01`` as ``datetime.date``, but every
    SDTM date-bearing field (TSVAL, rule text, ...) is a string.
    """
    if isinstance(value, dict):
        return {k: _dates_to_iso(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_dates_to_iso(v) for v in value]
    if isinstance(value, datetime.datetime | datetime.date):
        return value.isoformat()
    return value


class _StrictLoader(yaml.SafeLoader):
    """A SafeLoader that refuses a repeated mapping key."""


def _mapping_with_unique_keys(loader: _StrictLoader, node: yaml.MappingNode) -> dict:
    seen: set[Any] = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in seen:
            raise yaml.constructor.ConstructorError(
                None, None, f"repeated key {key!r}", key_node.start_mark
            )
        seen.add(key)
    return loader.construct_mapping(node, deep=True)


_StrictLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping_with_unique_keys
)


def load_strict_yaml(text: str) -> Any:
    """Parse YAML like ``yaml.safe_load``, but raise on a repeated key.

    Args:
        text: The YAML document.

    Returns:
        Any: The parsed document.

    Raises:
        yaml.constructor.ConstructorError: When a mapping repeats a key.

    Examples:
        Load a trial design spec::

            data = load_strict_yaml(Path("trial_design.yaml").read_text())
    """
    return yaml.load(text, Loader=_StrictLoader)  # noqa: S506 - a SafeLoader subclass


class ArmStep(BaseModel):
    """One position of an arm path, with the TA values of that position.

    A plain ETCD string in a path is the short form of a step with no
    override.  *epoch* replaces the element's epoch at this position (a
    crossover, an element that repeats).  *tabranch* replaces the default
    ``Randomized to <arm>`` text, and *tatrans* gives the TATRANS rule.
    """

    model_config = ConfigDict(extra="forbid")

    etcd: ElementCode
    epoch: EpochLike | None = None
    tabranch: RuleExpression = ""
    tatrans: RuleExpression = ""


def _etcd(entry: str | ArmStep) -> str:
    return entry if isinstance(entry, str) else entry.etcd


def _sdtm_code(name: str, max_len: int, taken: set[str]) -> str:
    """Derive a unique upper-case SDTM short code from a free-text name."""
    base = re.sub(r"[^A-Z0-9]", "", name.upper())[:max_len] or "X"
    code, n = base, 1
    while code in taken:
        n += 1
        suffix = str(n)
        code = base[: max_len - len(suffix)] + suffix
    taken.add(code)
    return code


_USDM_TAG_RE = re.compile(r"<usdm:tag\s+name=\"([^\"]+)\"\s*/>")
_MARKUP_RE = re.compile(r"<[^>]+>")


def _usdm_text(text: str, name: str, dictionary: dict[str, str]) -> str:
    """Plain criterion text: usdm:tag resolved through the dictionary, XHTML removed."""

    def resolve(match: re.Match[str]) -> str:
        if match.group(1) not in dictionary:
            raise ValueError(
                f"USDM criterion '{name}': tag '{match.group(1)}' is not in its syntax dictionary"
            )
        return dictionary[match.group(1)]

    text = _USDM_TAG_RE.sub(resolve, text)
    left = re.search(r"<usdm:[^>]*>", text)
    if left:
        raise ValueError(f"USDM criterion '{name}': cannot resolve {left.group(0)}")
    return " ".join(html.unescape(_MARKUP_RE.sub(" ", text)).split())


def _usdm_criteria(study: dict, version: dict, sd: dict) -> list[TrialCriterion]:
    """TI rows from USDM v4 criterion items or USDM v3 population criteria."""
    items = {i.get("id"): i for i in version.get("eligibilityCriterionItems") or []}
    dictionaries = {
        d.get("id"): {p.get("tag"): p.get("reference", "") for p in d.get("parameterMaps") or []}
        for d in version.get("dictionaries") or study.get("dictionaries") or []
    }
    raw = list(sd.get("eligibilityCriteria") or version.get("eligibilityCriteria") or [])
    by_id = {c.get("id"): c for c in raw}
    for entry in (sd.get("population") or {}).get("criteria") or []:
        crit = by_id.get(entry) if isinstance(entry, str) else entry
        if crit is not None and crit not in raw:
            raw.append(crit)

    criteria: list[TrialCriterion] = []
    codes: set[str] = set()
    cut: list[str] = []
    for crit in raw:
        name = crit.get("name") or crit.get("identifier") or crit.get("id", "")
        source = items.get(crit.get("criterionItemId")) or crit
        if not source.get("text"):
            raise ValueError(f"USDM criterion '{name}' has no text")
        text = _usdm_text(source["text"], name, dictionaries.get(source.get("dictionaryId"), {}))
        category = str((crit.get("category") or {}).get("decode", "")).upper()
        if "EXCL" in category:
            iecat, prefix = "EXCLUSION", "EX"
        elif "INCL" in category:
            iecat, prefix = "INCLUSION", "IN"
        else:
            raise ValueError(f"USDM criterion '{name}' has no inclusion or exclusion category")
        code = str(crit.get("identifier") or crit.get("name") or "").upper()
        if code[:1].isdigit():
            code = prefix + code  # SDTMIG 3.4 section 4.5.3: --TESTCD cannot start with a digit
        if code in codes:
            raise ValueError(f"USDM criteria give IETESTCD '{code}' twice")
        codes.add(code)
        if len(text) > 200:
            cut.append(code)
        criteria.append(TrialCriterion(ietestcd=code, ietest=text[:200], iecat=iecat))
    if cut:
        warnings.warn(
            f"from_usdm: {len(cut)} criterion text(s) are over 200 characters and are cut at "
            f"200 in TI.IETEST: {cut}. Keep the full text in the protocol.",
            stacklevel=3,
        )
    return criteria


def _usdm_chain(items: list[dict]) -> list[dict]:
    """*items* in previousId/nextId order when the chain is complete, else in array order."""
    by_id = {i.get("id"): i for i in items}
    heads = [i for i in items if i.get("previousId") not in by_id]
    if len(heads) != 1 or not all("nextId" in i or "previousId" in i for i in items):
        return list(items)
    ordered, seen, item = [], set(), heads[0]
    while item is not None and item.get("id") not in seen:
        ordered.append(item)
        seen.add(item.get("id"))
        item = by_id.get(item.get("nextId"))
    return ordered if len(ordered) == len(items) else list(items)


def _usdm_study_id(version: dict) -> str | None:
    """The identifier whose scope organization is the sponsor, else the first identifier."""
    orgs = {o.get("id"): o for o in version.get("organizations") or [] if isinstance(o, dict)}
    idents = [i for i in version.get("studyIdentifiers") or [] if isinstance(i, dict)]

    def org_type(ident: dict) -> str:
        org = ident.get("studyIdentifierScope") or orgs.get(ident.get("scopeId")) or {}
        kind = org.get("organizationType") or org.get("type") or {}
        return str(kind.get("decode", "") if isinstance(kind, dict) else kind)

    ordered = sorted(idents, key=lambda i: org_type(i) != "Clinical Study Sponsor")
    return next((i.get("studyIdentifier") or i.get("text") for i in ordered), None)


class StudyDesign(BaseModel):
    """Typed aggregate of a study's trial design.

    ``arms`` maps each ARMCD to its ordered path of element codes — the
    per-arm element name/epoch/TAETORD repetition of raw TA rows is derived,
    never written by hand.  A path entry is an ETCD string or an
    :class:`ArmStep` (``{"etcd": ..., "epoch": ..., "tabranch": ...,
    "tatrans": ...}``) for the TA values of one position.  All fields accept
    plain dicts (Pydantic coerces), so a ``trial_design.yaml`` deserialises
    directly via :meth:`from_yaml`.  An unknown key raises.

    TABRANCH defaults to ``Randomized to <arm>`` on the last element that
    every arm shares, or on the *randomized_at* element when it is given.
    A step's *tabranch* replaces that text: state the real rule when the
    branch is not a randomization.

    Each arm needs its protocol name in *arm_names* (TA.ARM); an arm with
    no name raises.

    References:
        SDTMIG 3.4 TA (ARM is the protocol name of the arm);
        ``docs/adr/0052-a-trial-design-arm-needs-its-protocol-name.md``.
    """

    model_config = ConfigDict(extra="forbid")

    study_id: str = Field(min_length=1)
    elements: list[TrialElement] = []
    arms: dict[str, list[str | ArmStep]] = {}
    arm_names: dict[str, str] = {}
    randomized_at: str | None = None
    visits: list[TrialVisit] = []
    criteria: list[TrialCriterion] = []
    parameters: list[TrialParameter] = []
    assessments: list[TrialDiseaseAssessment] = []
    milestones: list[TrialMilestone] = []

    @model_validator(mode="after")
    def check_referential_integrity(self) -> StudyDesign:
        TrialElements(elements=self.elements)  # uniqueness + epoch consistency
        known = {e.etcd for e in self.elements}
        for armcd, path in self.arms.items():
            if not path:
                raise ValueError(f"Arm '{armcd}' has an empty element path")
            missing = [_etcd(entry) for entry in path if _etcd(entry) not in known]
            if missing:
                raise ValueError(f"Arm '{armcd}' references undefined elements: {missing}")
        stray_names = sorted(set(self.arm_names) - set(self.arms))
        if stray_names:
            raise ValueError(f"arm_names holds ARMCD(s) that are not in arms: {stray_names}")
        unnamed = [armcd for armcd in self.arms if not self.arm_names.get(armcd)]
        if unnamed:
            raise ValueError(
                f"arm(s) {unnamed} have no name in arm_names. TA.ARM is the protocol name "
                "of the arm (SDTMIG 3.4): give arm_names={ARMCD: name}."
            )
        if self.randomized_at is not None and self.randomized_at not in known:
            raise ValueError(f"randomized_at '{self.randomized_at}' is not a defined element")
        for visit in self.visits:
            if visit.armcd and visit.armcd not in self.arms:
                raise ValueError(f"Visit '{visit.visit}' references undefined arm '{visit.armcd}'")
        return self

    # ------------------------------------------------------------------ #
    # Derivation                                                           #
    # ------------------------------------------------------------------ #

    def _frame(self, df: pl.DataFrame, domain: str) -> pl.DataFrame:
        """Prepend STUDYID/DOMAIN in SDTM column order."""
        return df.select(
            pl.lit(self.study_id).alias("STUDYID"),
            pl.lit(domain).alias("DOMAIN"),
            pl.all(),
        )

    def _branch_index(self) -> int | None:
        """Index of the last element shared by every arm before paths diverge.

        ponytail: single randomized-branch designs only; nested or adaptive
        branch points need explicit TrialArm rows built by hand.
        """
        paths = [[_etcd(e) for e in p] for p in self.arms.values()]
        if len(paths) < 2:
            return None
        prefix = 0
        while all(len(p) > prefix for p in paths) and len({p[prefix] for p in paths}) == 1:
            prefix += 1
        if prefix == 0 or all(p[prefix:] == paths[0][prefix:] for p in paths):
            return None  # identical paths or no shared prefix — no branch to describe
        return prefix - 1

    def arm_collection(self) -> TrialArms:
        """Derive the validated ``TrialArms`` collection from the arm paths.

        Returns:
            TrialArms: One row per arm/element with TAETORD, ELEMENT, EPOCH
                looked up from the element definitions (or the step's epoch)
                and TABRANCH rendered at the branch point (or the step's
                tabranch).

        References:
            SDTMIG 3.4 TA: EPOCH is the epoch of this element of the arm,
            TABRANCH the condition met at the end of the element; see
            ``docs/adr/0036-an-arm-path-entry-is-an-element-or-a-step.md``.

        Examples:
            Derive TA rows from a design::

                design = fleet.StudyDesign(study_id="S1", elements=[...],
                                           arms={"PBO": ["SCRN", "TRT"]})
                ta_rows = design.arm_collection()
        """
        lookup = {e.etcd: e for e in self.elements}
        branch_at = None if self.randomized_at else self._branch_index()
        rows = []
        for armcd, path in self.arms.items():
            arm = self.arm_names[armcd]
            codes = [_etcd(e) for e in path]
            randomized = codes.index(self.randomized_at) if self.randomized_at in codes else None
            for order, entry in enumerate(path, start=1):
                step = ArmStep(etcd=entry) if isinstance(entry, str) else entry
                el = lookup[step.etcd]
                at_branch = order - 1 in (branch_at, randomized)
                default = f"Randomized to {arm}" if at_branch else ""
                rows.append(
                    TrialArm(
                        armcd=armcd,
                        arm=arm,
                        taetord=order,
                        etcd=step.etcd,
                        element=el.element,
                        tabranch=step.tabranch or default,
                        tatrans=step.tatrans,
                        epoch=step.epoch or el.epoch,
                    )
                )
        return TrialArms(arms=rows)

    def to_te(self) -> pl.DataFrame:
        """Derive the TE (Trial Elements) domain.

        Returns:
            pl.DataFrame: TE with STUDYID/DOMAIN and SDTM column names.

        Examples:
            Derive TE from a design::

                te = design.to_te()
        """
        return self._frame(TrialElements(elements=self.elements).to_polars(), "TE")

    def to_ta(self) -> pl.DataFrame:
        """Derive the TA (Trial Arms) domain from the arm paths.

        Returns:
            pl.DataFrame: TA with STUDYID/DOMAIN and SDTM column names.

        Examples:
            Derive TA from a design::

                ta = design.to_ta()
        """
        return self._frame(self.arm_collection().to_polars(), "TA")

    def to_tv(self) -> pl.DataFrame:
        """Derive the TV (Trial Visits) domain.

        Returns:
            pl.DataFrame: TV with STUDYID/DOMAIN and SDTM column names.

        Examples:
            Derive TV from a design::

                tv = design.to_tv()
        """
        return self._frame(TrialVisits(visits=self.visits).to_polars(), "TV")

    def to_ts(self) -> pl.DataFrame:
        """Derive the TS (Trial Summary) domain.

        Returns:
            pl.DataFrame: TS with STUDYID/DOMAIN and SDTM column names.

        Examples:
            Derive TS from a design::

                ts = design.to_ts()
        """
        return self._frame(TrialParameters(parameters=self.parameters).to_polars(), "TS")

    def to_ti(self) -> pl.DataFrame:
        """Derive the TI (Trial Inclusion/Exclusion) domain.

        Returns:
            pl.DataFrame: TI with STUDYID/DOMAIN and SDTM column names.

        Examples:
            Derive TI from a design::

                ti = design.to_ti()
        """
        return self._frame(TrialCriteria(criteria=self.criteria).to_polars(), "TI")

    def to_td(self) -> pl.DataFrame:
        """Derive the TD (Trial Disease Assessments) domain.

        Returns:
            pl.DataFrame: TD with STUDYID/DOMAIN and SDTM column names.

        Examples:
            Derive TD from a design::

                td = design.to_td()
        """
        return self._frame(TrialDiseaseAssessments(assessments=self.assessments).to_polars(), "TD")

    def to_tm(self) -> pl.DataFrame:
        """Derive the TM (Trial Disease Milestones) domain.

        Returns:
            pl.DataFrame: TM with STUDYID/DOMAIN and SDTM column names.

        Examples:
            Derive TM from a design::

                tm = design.to_tm()
        """
        return self._frame(TrialMilestones(milestones=self.milestones).to_polars(), "TM")

    def domains(self) -> dict[str, pl.DataFrame]:
        """Derive every populated Trial Design domain.

        Returns:
            dict[str, pl.DataFrame]: Domain code → DataFrame, skipping
                domains whose design section is empty.

        Examples:
            Build all domains and write them out::

                for domain, df in design.domains().items():
                    df.write_parquet(f"data/sdtm/{domain.lower()}.parquet")
        """
        sections = {
            "TE": (self.elements, self.to_te),
            "TA": (self.arms, self.to_ta),
            "TV": (self.visits, self.to_tv),
            "TS": (self.parameters, self.to_ts),
            "TI": (self.criteria, self.to_ti),
            "TD": (self.assessments, self.to_td),
            "TM": (self.milestones, self.to_tm),
        }
        return {domain: build() for domain, (section, build) in sections.items() if section}

    def audit(self, *, dm: pl.DataFrame | None = None) -> pl.DataFrame:
        """Run the P21-style conformance pre-check over the derived domains.

        Two design checks come first: arms with the same path
        (``FLEETTD04``), and an element that repeats in one arm with no
        per-position epoch (``FLEETTD05``).  An empty elements or arms
        section is an error, and an empty visits or criteria section a
        warning (``FLEETTD09``).

        Args:
            dm: Optional DM domain for cross-checking ARMCD assignments.

        Returns:
            pl.DataFrame: One row per finding (``rule_id``, ``severity``,
                ``domain``, ``message``); empty when clean.

        Examples:
            Audit a design before export::

                findings = design.audit()
                errors = findings.filter(pl.col("severity") == "error")
        """
        from fleet.sdtm.tdd_audit import audit

        frames = self.domains()
        findings = audit(
            te=frames.get("TE"),
            ta=frames.get("TA"),
            tv=frames.get("TV"),
            # TS is always audited: an absent parameters section means every
            # FDA-required parameter is missing (rejection-level), not "skip".
            ts=frames.get("TS", self.to_ts()),
            ti=frames.get("TI"),
            dm=dm,
            td=frames.get("TD"),
            tm=frames.get("TM"),
        )
        return pl.concat([pl.DataFrame(self._design_findings(), schema=findings.schema), findings])

    def _design_findings(self) -> list[dict[str, str]]:
        """Findings on the arm paths that the derived domains cannot show."""
        found = []
        sections = (
            ("TE", self.elements, "error"),
            ("TA", self.arms, "error"),
            ("TV", self.visits, "warning"),
            ("TI", self.criteria, "warning"),
        )
        for domain, section, severity in sections:
            if not section:
                found.append(
                    {
                        "rule_id": "FLEETTD09",
                        "severity": severity,
                        "domain": domain,
                        "message": f"The design has no {domain} records, so {domain} is not built.",
                    }
                )
        by_path: dict[tuple[str, ...], list[str]] = {}
        for armcd, path in self.arms.items():
            by_path.setdefault(tuple(_etcd(e) for e in path), []).append(armcd)
            codes = [_etcd(e) for e in path]
            for etcd in sorted({c for c in codes if codes.count(c) > 1}):
                plain = [
                    e for e in path if _etcd(e) == etcd and (isinstance(e, str) or not e.epoch)
                ]
                if plain:
                    found.append(
                        {
                            "rule_id": "FLEETTD05",
                            "severity": "warning",
                            "domain": "TA",
                            "message": f"Arm '{armcd}' repeats element '{etcd}' with no "
                            "per-position epoch: give each position {etcd, epoch}.",
                        }
                    )
        for arms in by_path.values():
            if len(arms) > 1:
                found.append(
                    {
                        "rule_id": "FLEETTD04",
                        "severity": "warning",
                        "domain": "TA",
                        "message": f"Arms {arms} have the same element path, so TA cannot "
                        "tell them apart: check the protocol.",
                    }
                )
        return found

    # ------------------------------------------------------------------ #
    # Interchange                                                          #
    # ------------------------------------------------------------------ #

    @classmethod
    def from_yaml(cls, path: str | Path) -> StudyDesign:
        """Load a design from a ``trial_design.yaml`` spec.

        The YAML mirrors the model schema; a top-level ``trial_design:``
        wrapper key is accepted so the section can live inside a larger
        study file.  A repeated key or a key the model does not read
        raises, so a typo cannot drop a rule, a visit or an arm.

        Args:
            path: Path to the YAML file.

        Returns:
            StudyDesign: The validated design.

        Raises:
            yaml.constructor.ConstructorError: When a mapping repeats a key.
            ValueError: When the file is empty or is not a mapping.
            pydantic.ValidationError: When a key is unknown or a value is
                not valid.

        Examples:
            Load and build every domain::

                design = fleet.StudyDesign.from_yaml("metadata/trial_design.yaml")
                frames = design.domains()
        """
        data = load_strict_yaml(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path}: the file is empty or is not a mapping of design sections.")
        return cls(**_dates_to_iso(data.get("trial_design", data)))

    def to_yaml(self, path: str | Path | None = None) -> str:
        """Serialise the design to YAML (the ``from_yaml`` round-trip).

        Args:
            path: Optional file path to write to.

        Returns:
            str: The YAML document.

        Examples:
            Persist a design next to the study metadata::

                design.to_yaml("metadata/trial_design.yaml")
        """
        text = yaml.dump(
            self.model_dump(mode="json", exclude_defaults=True),
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
        if path is not None:
            Path(path).write_text(text, encoding="utf-8")
        return text

    @classmethod
    def from_mermaid(cls, mermaid_text: str, *, study_id: str, **sections: Any) -> StudyDesign:
        """Build a design from a Mermaid flowchart.

        The diagram gives the elements and the arm paths.  ARM comes from
        *arm_names* when given, else from the ARMCD.

        Args:
            mermaid_text: A Mermaid ``flowchart TD`` string (see
                :func:`fleet.sdtm.tdd.parse_trial_design`).
            study_id: The study identifier.
            **sections: Extra design sections (``arm_names=``, ``visits=``,
                ``criteria=``, ``parameters=``, ...) passed through to the
                constructor.

        Returns:
            StudyDesign: Design with elements and arm paths from the diagram.

        Raises:
            ValueError: When the diagram cannot give a design (see
                :func:`fleet.sdtm.tdd.parse_trial_design`).

        Examples:
            Diagram in, datasets out::

                design = fleet.StudyDesign.from_mermaid(diagram_text,
                                                        study_id="CDISCPILOT01")
                ta = design.to_ta()
        """
        te, ta = parse_trial_design(mermaid_text)
        arms: dict[str, list[str | ArmStep]] = {}
        arm_names: dict[str, str] = {}
        for row in sorted(ta.arms, key=lambda a: (a.armcd, a.taetord)):
            arms.setdefault(row.armcd, []).append(row.etcd)
            arm_names[row.armcd] = row.arm
        arm_names.update(sections.pop("arm_names", None) or {})
        return cls(
            study_id=study_id,
            elements=te.elements,
            arms=arms,
            arm_names=arm_names,
            **sections,
        )

    def to_mermaid(self) -> str:
        """Render the design as a Mermaid flowchart for a review document.

        Elements are grouped into epoch subgraphs; edges follow the arm
        paths, labelled with the ARMCD where the design branches (on the
        first edge for a single arm).  The diagram is a review view: it
        carries ETCD, ELEMENT, TEDUR, the element epochs and the arm paths,
        but not ARM, TESTRL, TEENRL, TABRANCH, TATRANS or a per-position
        epoch.  When :meth:`from_mermaid` cannot read the paths back (arms
        with the same path, a repeated element, a crossover), a warning says
        so.  YAML (:meth:`to_yaml`) is the lossless round trip.

        Returns:
            str: A Mermaid ``flowchart TD`` document.

        Examples:
            Render for a design-review doc::

                print(design.to_mermaid())
        """
        lines = ["flowchart TD"]
        by_epoch: dict[str, list[TrialElement]] = {}
        for el in self.elements:
            by_epoch.setdefault(str(el.epoch), []).append(el)
        for i, (epoch, els) in enumerate(by_epoch.items()):
            lines.append(f"    subgraph EP{i}[{epoch}]")
            for el in els:
                dur = f"<br/>{el.tedur}" if el.tedur else ""
                name = el.element.replace('"', "#quot;")
                lines.append(f'        {el.etcd}["{name}{dur}"]')
            lines.append("    end")
        branch_at = 0 if len(self.arms) == 1 else self._branch_index()
        paths = {armcd: [_etcd(e) for e in path] for armcd, path in self.arms.items()}
        seen: set[tuple[str, str, str]] = set()
        for armcd, path in paths.items():
            for i, (src, dst) in enumerate(zip(path, path[1:])):
                label = f"|{armcd}|" if branch_at is not None and i == branch_at else ""
                edge = (src, label, dst)
                if edge not in seen:
                    seen.add(edge)
                    lines.append(f"    {src} -->{label} {dst}")
        text = "\n".join(lines)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                _, ta = parse_trial_design(text)
            back: dict[str, list[str]] = {}
            for row in ta.arms:
                back.setdefault(row.armcd, []).append(row.etcd)
            lossless = back == paths and not any(
                isinstance(e, ArmStep) and e.epoch for path in self.arms.values() for e in path
            )
        except ValueError:
            lossless = False
        if not lossless:
            warnings.warn(
                "to_mermaid: from_mermaid cannot read this design back (arms with the same "
                "path, a repeated element, a crossover or a per-position epoch). Use to_yaml() "
                "for a lossless copy.",
                stacklevel=2,
            )
        return text

    @classmethod
    def from_usdm(cls, data: dict, *, study_id: str | None = None) -> StudyDesign:
        """Build a design from a CDISC USDM (DDF) study definition.

        Maps the structural subset of USDM v3/v4 JSON: arms + epochs +
        elements + studyCells become the arm paths (with the epoch of each
        cell), encounters become visits, and eligibility criteria become TI
        rows.  TI text comes from the v4 criterion item (or the v3
        population criteria), with ``usdm:tag`` resolved through the syntax
        dictionary and XHTML removed.  An identifier that starts with a
        digit takes an IN or EX prefix (SDTMIG 3.4 section 4.5.3).

        Epochs and encounters follow their previousId/nextId chain when it
        is complete, else the array order.  An encounter's transition rules
        give TVSTRL and TVENRL; one warning counts the visits with no start
        rule.  Only the first study design is mapped, with a warning when
        there are more.  A study cell with an unknown armId, epochId or
        elementId raises.

        ponytail: schedule timelines, objectives/endpoints, and biomedical
        concepts are intentionally not mapped — extend when a consumer needs
        them.

        Args:
            data: Parsed USDM JSON (the ``{"study": ...}`` wrapper or the
                study object itself).
            study_id: Override for STUDYID; defaults to the study
                identifier whose scope organization type is "Clinical
                Study Sponsor", else the first study identifier.

        Returns:
            StudyDesign: Design with the mapped structural subset.

        Raises:
            ValueError: When the version has no study design, a study cell
                holds an unknown reference, a criterion has no text or no
                inclusion or exclusion category, a tag cannot be resolved,
                or two criteria give the same IETESTCD.

        Examples:
            Import an OpenStudyBuilder / DDF export::

                import json
                design = fleet.StudyDesign.from_usdm(
                    json.loads(Path("usdm.json").read_text()),
                    study_id="CDISCPILOT01",
                )
        """
        study = data.get("study", data)
        versions = study.get("versions") or study.get("studyVersions") or [study]
        version = versions[0]
        designs = version.get("studyDesigns") or []
        if not designs:
            raise ValueError("from_usdm: the study version has no studyDesigns")
        if len(designs) > 1:
            warnings.warn(
                f"from_usdm: the study version has {len(designs)} study designs; only the "
                f"first ('{designs[0].get('id', '')}') is mapped.",
                stacklevel=2,
            )
        sd = designs[0]

        if study_id is None:
            study_id = _usdm_study_id(version) or (study.get("name") or "STUDY")

        def label(obj: dict) -> str:
            return obj.get("label") or obj.get("name") or obj.get("id", "")

        epochs = _usdm_chain(sd.get("epochs", []))
        epoch_order = [e["id"] for e in epochs]
        epoch_label = {e["id"]: label(e).upper() for e in epochs}
        taken: set[str] = set()
        etcd_by_id: dict[str, str] = {}
        element_models: dict[str, dict] = {}
        for el in sd.get("elements", []):
            etcd = _sdtm_code(label(el), 8, taken)
            etcd_by_id[el["id"]] = etcd
            element_models[el["id"]] = {
                "etcd": etcd,
                "element": label(el)[:200],
                "testrl": (el.get("transitionStartRule") or {}).get("text", "")[:2000],
                "teenrl": (el.get("transitionEndRule") or {}).get("text", "")[:2000],
            }

        arm_label = {a["id"]: label(a) for a in sd.get("arms", [])}
        arm_taken: set[str] = set()
        armcd_by_id = {aid: _sdtm_code(name, 20, arm_taken) for aid, name in arm_label.items()}

        arms: dict[str, list[str | ArmStep]] = {}
        for cell in sd.get("studyCells", []):
            cell_id = cell.get("id", "")
            if cell.get("armId") not in armcd_by_id:
                raise ValueError(f"from_usdm: study cell '{cell_id}' has an unknown armId")
            if cell.get("epochId") not in epoch_label:
                raise ValueError(f"from_usdm: study cell '{cell_id}' has an unknown epochId")
            unknown = [e for e in cell.get("elementIds", []) if e not in element_models]
            if unknown:
                raise ValueError(
                    f"from_usdm: study cell '{cell_id}' has unknown elementIds {unknown}"
                )
        cells = sorted(sd.get("studyCells", []), key=lambda c: epoch_order.index(c["epochId"]))
        for cell in cells:
            armcd = armcd_by_id[cell["armId"]]
            cell_epoch = epoch_label[cell["epochId"]]
            for element_id in cell.get("elementIds", []):
                epoch = element_models[element_id].setdefault("epoch", cell_epoch)
                etcd = etcd_by_id[element_id]
                arms.setdefault(armcd, []).append(
                    etcd if epoch == cell_epoch else ArmStep(etcd=etcd, epoch=cell_epoch)
                )

        elements = [
            TrialElement(**{"epoch": "TREATMENT", **model}) for model in element_models.values()
        ]

        encounters = _usdm_chain(sd.get("encounters", []))
        visits = [
            TrialVisit(
                visitnum=num,
                visit=label(enc)[:200],
                tvstrl=(enc.get("transitionStartRule") or {}).get("text", "")[:2000],
                tvenrl=(enc.get("transitionEndRule") or {}).get("text", "")[:2000],
            )
            for num, enc in enumerate(encounters, start=1)
        ]
        no_start = sum(1 for v in visits if not v.tvstrl)
        if no_start:
            warnings.warn(
                f"from_usdm: {no_start} visit(s) have no transitionStartRule, so TVSTRL is "
                "blank. TVSTRL is Req in TV (SDTMIG 3.4): add the rule.",
                stacklevel=2,
            )

        return cls(
            study_id=study_id,
            elements=elements,
            arms=arms,
            arm_names={armcd_by_id[aid]: name for aid, name in arm_label.items()},
            visits=visits,
            criteria=_usdm_criteria(study, version, sd),
        )
